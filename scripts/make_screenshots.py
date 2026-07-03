"""Generate README screenshots offscreen, so the visuals never rot.

Runs an offscreen QApplication, wires the MainWindow to a self-contained fake
cag-api (no network, no Docker), seeds it with a few documents and one
conversation, and grabs each surface to ``docs/images/<name>.png``.

Usage (from the repo root):

    QT_QPA_PLATFORM=offscreen python scripts/make_screenshots.py

Re-run whenever the UI changes and commit the refreshed PNGs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Offscreen must be set before any Qt import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _ensure_fonts() -> None:
    """PySide6 6.11 no longer ships fonts; the offscreen backend then renders
    text as tofu. Point Qt at a platform system-font directory if the caller
    hasn't already, so the screenshots show real text."""
    if os.environ.get("QT_QPA_FONTDIR"):
        return
    for candidate in (
        "C:/Windows/Fonts",  # Windows
        "/usr/share/fonts",  # Linux
        "/System/Library/Fonts",  # macOS
    ):
        if Path(candidate).is_dir():
            os.environ["QT_QPA_FONTDIR"] = candidate
            return


_ensure_fonts()

import httpx  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# Make the package importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llamacag_ui.api_client import ApiClient  # noqa: E402
from llamacag_ui.config import AppConfig  # noqa: E402
from llamacag_ui.ui.main_window import MainWindow  # noqa: E402
from llamacag_ui.ui.theme import apply_theme  # noqa: E402
from llamacag_ui.ui.welcome_dialog import WelcomeDialog  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "images"


class _ScreenshotApi:
    """A tiny fixed-response cag-api for deterministic screenshots."""

    def __init__(self) -> None:
        self.documents = [
            {
                "id": 1,
                "file_name": "annual-report-2025.pdf",
                "status": "cached",
                "n_tokens": 48213,
                "cache_file": "doc-1.bin",
                "error": None,
                "created_at": "2026-06-30T09:12:00+00:00",
                "cached_at": "2026-06-30T09:14:20+00:00",
                "last_used_at": "2026-07-02T11:40:00+00:00",
                "use_count": 7,
            },
            {
                "id": 2,
                "file_name": "product-handbook.md",
                "status": "cached",
                "n_tokens": 12987,
                "cache_file": "doc-2.bin",
                "error": None,
                "created_at": "2026-07-01T15:03:00+00:00",
                "cached_at": "2026-07-01T15:03:40+00:00",
                "last_used_at": "2026-07-02T10:05:00+00:00",
                "use_count": 3,
            },
            {
                "id": 3,
                "file_name": "meeting-notes.txt",
                "status": "pending",
                "n_tokens": None,
                "cache_file": None,
                "error": None,
                "created_at": "2026-07-02T12:00:00+00:00",
                "cached_at": None,
                "last_used_at": None,
                "use_count": 0,
            },
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "hot_documents": {"0": 1},
                    "slots": 1,
                    "llama_server": {"status": "ok"},
                    "database": "ok",
                },
            )
        if path == "/documents" and request.method == "GET":
            return httpx.Response(200, json={"documents": self.documents})
        if path == "/query":
            return httpx.Response(
                200,
                json={
                    "answer": (
                        "Revenue grew 18% year over year, driven mainly by the "
                        "EMEA region. The report attributes the rest to the new "
                        "subscription tier launched in Q2."
                    ),
                    "document": {"id": 1, "file_name": "annual-report-2025.pdf", "n_tokens": 48213},
                    "duration_ms": 2140,
                    "timings": {
                        "prompt_tokens_evaluated": 11,
                        "prompt_tokens_from_cache": 48202,
                        "answer_tokens": 41,
                        "cache_source": "memory",
                    },
                },
            )
        return httpx.Response(404, json={"detail": "not found"})


def _client_factory(api: _ScreenshotApi):
    return lambda url: ApiClient(url, transport=httpx.MockTransport(api.handler))


def _seed_conversation(window: MainWindow) -> None:
    chat = window.chat_tab
    chat.set_send_enabled(True)
    chat.input.setPlainText("What drove revenue growth this year?")
    chat.send()
    QApplication.processEvents()
    # Let the worker deliver the answer.
    for _ in range(200):
        QApplication.processEvents()
        if chat._history:
            break


def _grab(widget, name: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{name}.png"
    widget.grab().save(str(path))
    print(f"wrote {path}")


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("LlamaCag")
    app.setApplicationName("LlamaCagUI")
    apply_theme(app)

    # Use throwaway in-memory settings so a developer's real config is untouched.
    settings = QSettings()
    settings.clear()
    config = AppConfig(settings)

    api = _ScreenshotApi()
    window = MainWindow(config, client_factory=_client_factory(api))
    window.stop_polling()
    window.resize(1160, 760)
    window.show()

    # Deterministic first paint.
    window.poll_health_now()
    window.documents_tab.refresh()
    for _ in range(50):
        QApplication.processEvents()

    # Welcome dialog.
    welcome = WelcomeDialog(config, parent=window)
    welcome.show()
    QApplication.processEvents()
    _grab(welcome, "welcome")
    welcome.close()

    # Chat (with a seeded exchange).
    window.tabs.setCurrentWidget(window.chat_tab)
    _seed_conversation(window)
    for _ in range(20):
        QApplication.processEvents()
    _grab(window, "chat")

    # Documents.
    window.tabs.setCurrentWidget(window.documents_tab)
    QApplication.processEvents()
    _grab(window, "documents")

    # Stack.
    window.tabs.setCurrentWidget(window.stack_tab)
    window.poll_health_now()
    for _ in range(20):
        QApplication.processEvents()
    _grab(window, "stack")

    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
