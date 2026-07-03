"""Main window: composition root, tab host, and the health poller.

Owns the single ApiClient (rebuilt when settings change), the StackController,
and a 10-second health QTimer whose result drives the status-bar dots, chat-send
enablement, the Stack tab's cards, and periodic document refreshes. Tests inject
a ``client_factory`` (to supply a MockTransport-backed client) and drive polling
explicitly via ``poll_health_now`` after ``stop_polling``.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QWidget,
)

from ..api_client import ApiClient, HealthReport
from ..config import AppConfig
from ..stack import StackController
from ..workers import run_in_pool
from . import theme
from .chat_tab import ChatTab
from .documents_tab import DocumentsTab
from .settings_tab import SettingsTab
from .stack_tab import StackTab

POLL_INTERVAL_MS = 10_000


class _StatusDot(QLabel):
    """Colored ● glyph + secondary-text service name for the status bar."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name
        self.set_state(None)

    def set_state(self, ok: bool | None) -> None:
        if ok is None:
            color, state = theme.TEXT_MUTED, "unknown"
        elif ok:
            color, state = theme.GREEN, "ok"
        else:
            color, state = theme.RED, "down"
        self.setText(
            f'<span style="color:{color}; font-size:14px;">\N{BLACK CIRCLE}</span>'
            f'&nbsp;<span style="color:{theme.TEXT_MUTED};">{self._name}</span>'
        )
        self.setToolTip(f"{self._name}: {state}")


ClientFactory = Callable[[str], ApiClient]


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: AppConfig,
        *,
        client_factory: ClientFactory | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._client_factory = client_factory or (lambda url: ApiClient(url))
        self._client = self._client_factory(config.api_url)
        self._controller = StackController(config.stack_dir)
        self._poll_worker = None

        self.setWindowTitle("LlamaCag UI")
        self.setMinimumSize(1100, 720)
        self.resize(1160, 760)

        self._build_tabs()
        self._build_status_bar()
        self._wire()

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.poll_health_now)
        self.start_polling()

        # Kick off an immediate first poll and document load.
        self.poll_health_now()
        self.documents_tab.refresh()

    # --- construction ------------------------------------------------------

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.chat_tab = ChatTab(self._client, self._config)
        self.documents_tab = DocumentsTab(self._client)
        self.stack_tab = StackTab(self._client, self._controller)
        self.settings_tab = SettingsTab(self._config)

        self.tabs.addTab(self.chat_tab, "Chat")
        self.tabs.addTab(self.documents_tab, "Documents")
        self.tabs.addTab(self.stack_tab, "Stack")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.setCentralWidget(self.tabs)

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        self.api_dot = _StatusDot("api")
        self.llama_dot = _StatusDot("llama")
        self.db_dot = _StatusDot("db")
        self.status_text = QLabel("Connecting…")
        bar.addWidget(self.api_dot)
        bar.addWidget(self.llama_dot)
        bar.addWidget(self.db_dot)
        bar.addWidget(self.status_text)

    def _wire(self) -> None:
        # Documents list feeds the chat picker.
        self.documents_tab.documents_changed.connect(self.chat_tab.set_documents)
        # Applying settings rebuilds the client + controller and re-polls.
        self.settings_tab.settings_applied.connect(self._on_settings_applied)

    # --- polling -----------------------------------------------------------

    def start_polling(self) -> None:
        self._timer.start()

    def stop_polling(self) -> None:
        self._timer.stop()

    def poll_health_now(self) -> None:
        """Run one health check off-thread; result updates dots + gating."""
        self._poll_worker = run_in_pool(
            self._client.health,
            on_finished=self._on_health,
            on_failed=self._on_health_failed,
        )

    def _on_health(self, report: HealthReport) -> None:
        self.api_dot.set_state(True)
        self.llama_dot.set_state(report.llama_ok)
        self.db_dot.set_state(report.db_ok)
        self.status_text.setText(f"Stack status: {report.status}")
        # Chat can send only when everything the query path needs is healthy.
        self.chat_tab.set_send_enabled(report.ok)
        self.stack_tab.update_health(report)

    def _on_health_failed(self, message: str, exc: Exception) -> None:
        self.api_dot.set_state(False)
        self.llama_dot.set_state(None)
        self.db_dot.set_state(None)
        self.status_text.setText("cag-api unreachable — is the stack running?")
        self.chat_tab.set_send_enabled(False)
        self.stack_tab.update_health(HealthReport.unreachable(message))

    # --- settings changed --------------------------------------------------

    def _on_settings_applied(self) -> None:
        old = self._client
        self._client = self._client_factory(self._config.api_url)
        self._controller = StackController(self._config.stack_dir)
        self.chat_tab.set_client(self._client)
        self.documents_tab.set_client(self._client)
        self.stack_tab.set_client(self._client)
        self.stack_tab.set_stack_controller(self._controller)
        try:
            old.close()
        except Exception:  # noqa: BLE001 - closing a stale client must never crash
            pass
        self.poll_health_now()
        self.documents_tab.refresh()

    # --- teardown ----------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.stop_polling()
        # Let in-flight workers finish before our widgets are destroyed, so a
        # late finished/failed signal never targets a deleted C++ object.
        QThreadPool.globalInstance().waitForDone(2000)
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)
