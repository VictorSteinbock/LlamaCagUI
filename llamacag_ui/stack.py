"""The one module that runs subprocesses. docker compose, list args, no shell.

Optional local control of the sibling stack's docker compose deployment. Every
call uses an explicit argument list with ``cwd`` set to the stack directory —
the shell is never invoked, the command is never a constructed string, and it is
never arbitrary. If Docker is absent or no stack directory is configured, the
whole capability degrades to a disabled state (``available()`` is False) and the
app still works as a pure client of a remote ``api_url``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

# docker compose (v2) is the plugin form; that is what the stack ships with.
DOCKER = "docker"
COMPOSE_FILENAME = "docker-compose.yml"
ENV_FILENAME = ".env"
LLAMA_SERVICE = "llama-server"
LLAMA_MODEL_KEY = "LLAMA_MODEL"

_LLAMA_MODEL_RE = re.compile(r"^LLAMA_MODEL=.*$", re.MULTILINE)

# Guidance surfaced when the stack has never been initialised.
NO_ENV_MESSAGE = (
    "The stack has no .env file yet. Run `python llamacag.py setup` in the "
    "stack directory first to generate it, then try again."
)


class StackError(RuntimeError):
    """A stack operation could not be performed (bad state, missing file)."""


class StackController:
    """Drive ``docker compose`` for a configured stack directory.

    ``runner`` is the callable used to execute argument lists; it defaults to
    ``subprocess.run`` and is injected in tests so no real Docker is required.
    """

    def __init__(
        self,
        stack_dir: Path | str | None,
        *,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.stack_dir = Path(stack_dir) if stack_dir else None
        self._run = runner

    # --- capability checks -------------------------------------------------

    @property
    def compose_file(self) -> Path | None:
        if self.stack_dir is None:
            return None
        return self.stack_dir / COMPOSE_FILENAME

    @property
    def env_file(self) -> Path | None:
        if self.stack_dir is None:
            return None
        return self.stack_dir / ENV_FILENAME

    @staticmethod
    def docker_present() -> bool:
        return shutil.which(DOCKER) is not None

    def has_compose(self) -> bool:
        compose = self.compose_file
        return compose is not None and compose.is_file()

    def available(self) -> bool:
        """True iff we can actually run stack commands: docker on PATH and a
        compose file present in the configured directory."""
        return self.docker_present() and self.has_compose()

    def unavailable_reason(self) -> str | None:
        """Human-readable explanation for why control is disabled, or None."""
        if self.stack_dir is None:
            return "No stack directory configured (set one in Settings)."
        if not self.has_compose():
            return f"No {COMPOSE_FILENAME} found in {self.stack_dir}."
        if not self.docker_present():
            return "Docker not found on PATH. Install Docker to control the stack."
        return None

    # --- command execution -------------------------------------------------

    def _compose(self, *args: str) -> list[str]:
        return [DOCKER, "compose", *args]

    def _execute(
        self,
        args: list[str],
        *,
        timeout: float | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        if self.stack_dir is None:
            raise StackError("No stack directory configured.")
        try:
            result = self._run(
                args,
                cwd=str(self.stack_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:  # docker binary vanished
            raise StackError("Docker not found on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise StackError(f"`{' '.join(args)}` timed out after {timeout:g}s.") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise StackError(f"`{' '.join(args)}` failed: {detail}")
        return result

    # --- status ------------------------------------------------------------

    def ps(self) -> str:
        """``docker compose ps`` output (JSON lines). Raw for the caller to
        render or parse; the Stack tab shows it in the log/status view."""
        result = self._execute(
            self._compose("ps", "--format", "json"), timeout=30, check=False
        )
        return result.stdout

    # --- lifecycle ---------------------------------------------------------

    def start(self, on_progress: Callable[[str], None] | None = None) -> str:
        return self._run_with_output(
            self._compose("up", "-d"), timeout=600, on_progress=on_progress
        )

    def stop(self, on_progress: Callable[[str], None] | None = None) -> str:
        return self._run_with_output(
            self._compose("down"), timeout=300, on_progress=on_progress
        )

    def restart_llama(self, on_progress: Callable[[str], None] | None = None) -> str:
        """Recreate just llama-server (used after a model switch)."""
        return self._run_with_output(
            self._compose("up", "-d", LLAMA_SERVICE), timeout=600, on_progress=on_progress
        )

    def _run_with_output(
        self,
        args: list[str],
        *,
        timeout: float,
        on_progress: Callable[[str], None] | None,
    ) -> str:
        result = self._execute(args, timeout=timeout, check=True)
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        if on_progress is not None and output:
            for line in output.splitlines():
                on_progress(line)
        return output

    # --- model management --------------------------------------------------

    def current_model(self) -> str | None:
        """Read the ``LLAMA_MODEL`` value from ``.env``, or None if unset/absent."""
        env = self.env_file
        if env is None or not env.is_file():
            return None
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{LLAMA_MODEL_KEY}="):
                return line.split("=", 1)[1].strip()
        return None

    def set_model(self, repo_spec: str) -> None:
        """Rewrite only the ``LLAMA_MODEL=`` line in ``.env`` in place.

        Does not restart anything — the caller triggers ``restart_llama()``
        afterwards so the progress/timeout is surfaced as its own operation.
        Raises if there is no ``.env`` (the stack was never set up).
        """
        repo_spec = repo_spec.strip()
        if not repo_spec:
            raise StackError("Model spec is empty.")
        env = self.env_file
        if env is None:
            raise StackError("No stack directory configured.")
        if not env.is_file():
            raise StackError(NO_ENV_MESSAGE)

        text = env.read_text(encoding="utf-8")
        new_line = f"{LLAMA_MODEL_KEY}={repo_spec}"
        if _LLAMA_MODEL_RE.search(text):
            text = _LLAMA_MODEL_RE.sub(new_line, text, count=1)
        else:
            # No existing line: append one, keeping a trailing newline tidy.
            text = text.rstrip("\n") + f"\n{new_line}\n"
        env.write_text(text, encoding="utf-8")
