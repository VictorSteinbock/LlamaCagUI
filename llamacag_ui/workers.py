"""The one threading primitive. Every slow call goes through here.

v1 drowned in ad-hoc threads and shared mutable state. v2 has a single generic
``Worker(QRunnable)`` that runs a plain function on ``QThreadPool`` and reports
back with exactly two signals — ``finished(result)`` or ``failed(message, exc)``
— both marshalled to the UI thread by Qt. The UI mutates nothing off-thread and
holds no worker state beyond keeping references alive.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class WorkerSignals(QObject):
    """Signals for a Worker. Separate QObject because QRunnable is not one.

    ``finished`` carries the function's return value; ``failed`` carries a
    human-readable message plus the original exception; ``progress`` carries
    interim text lines (used by streaming subprocess output, e.g. log tails).
    """

    finished = Signal(object)
    failed = Signal(str, object)
    progress = Signal(str)


class Worker(QRunnable):
    """Run ``fn(*args, **kwargs)`` on the global thread pool.

    If ``fn`` accepts a ``progress`` keyword, it receives a callback that emits
    the ``progress`` signal — handy for streaming output. Any exception is
    caught and turned into a ``failed`` signal so a background error can never
    take the app down.
    """

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = dict(kwargs)
        self.signals = WorkerSignals()

    def _wants_progress(self) -> bool:
        # Only inject the progress emitter if the target explicitly accepts an
        # ``on_progress`` parameter and the caller didn't already supply one.
        if "on_progress" in self._kwargs:
            return False
        try:
            params = inspect.signature(self._fn).parameters
        except (TypeError, ValueError):
            return False
        return "on_progress" in params

    @Slot()
    def run(self) -> None:
        if self._wants_progress():
            # Emitting the signal marshals progress lines to the UI thread.
            self._kwargs["on_progress"] = self.signals.progress.emit
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001 - deliberately catch-all off-thread
            self._safe_emit(self.signals.failed, str(exc), exc)
        else:
            self._safe_emit(self.signals.finished, result)

    @staticmethod
    def _safe_emit(signal, *args: Any) -> None:
        # If the app is tearing down, the underlying C++ WorkerSignals object may
        # already be gone; emitting then raises RuntimeError on this worker
        # thread. Swallow only that race — the result no longer matters.
        try:
            signal.emit(*args)
        except RuntimeError:
            pass


# In-flight workers are held here so their WorkerSignals QObject is not
# garbage-collected before the result is delivered, and evicted the moment they
# finish so the set never grows without bound (the health poller runs forever).
_INFLIGHT: set[Worker] = set()


def run_in_pool(
    fn: Callable[..., Any],
    *args: Any,
    on_finished: Callable[[Any], None] | None = None,
    on_failed: Callable[[str, Exception], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    pool: QThreadPool | None = None,
    **kwargs: Any,
) -> Worker:
    """Build a Worker, wire callbacks, start it on the pool, and return it.

    The worker is tracked internally until it finishes, so callers do not need
    to keep a reference themselves and there is no unbounded leak.
    """
    worker = Worker(fn, *args, **kwargs)
    if on_finished is not None:
        worker.signals.finished.connect(on_finished)
    if on_failed is not None:
        worker.signals.failed.connect(on_failed)
    if on_progress is not None:
        worker.signals.progress.connect(on_progress)

    _INFLIGHT.add(worker)
    worker.signals.finished.connect(lambda _result: _INFLIGHT.discard(worker))
    worker.signals.failed.connect(lambda _msg, _exc: _INFLIGHT.discard(worker))

    (pool or QThreadPool.globalInstance()).start(worker)
    return worker
