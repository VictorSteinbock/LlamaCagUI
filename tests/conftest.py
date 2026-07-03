"""Shared test doubles.

``FakeCagApi`` is a tiny in-memory cag-api served through an
``httpx.MockTransport`` — the same fake-driven approach the sibling repo uses,
so tests need no network and no Docker. It keeps a documents dict, answers
canned queries, and has a toggleable health so degraded/unreachable paths are
exercised for real.

Fixtures:
- ``fake_api``        the FakeCagApi instance (mutate it to script scenarios)
- ``api_client``      an ApiClient wired to the fake via MockTransport
- ``main_window``     the real MainWindow on the fake client, poller stopped
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import httpx
import pytest

from llamacag_ui.api_client import ApiClient


@pytest.fixture(autouse=True, scope="session")
def _isolate_qsettings(tmp_path_factory):
    """Keep every test's QSettings off the real registry / plist.

    Force the INI backend into a throwaway directory and set the org/app names
    a bare (QApplication-less) test still needs for QSettings() to resolve.
    """
    from PySide6.QtCore import QCoreApplication, QSettings

    settings_dir = tmp_path_factory.mktemp("qsettings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_dir)
    )
    QCoreApplication.setOrganizationName("LlamaCag")
    QCoreApplication.setApplicationName("LlamaCagUI")
    yield

# --- supported upload types (mirrors the backend's extract.py) -------------
_SUPPORTED_EXT = {".txt", ".text", ".md", ".markdown", ".html", ".htm", ".pdf"}


def _now() -> str:
    return dt.datetime(2026, 7, 2, 12, 0, 0, tzinfo=dt.UTC).isoformat()


class FakeCagApi:
    """In-memory cag-api. One instance per test; scenarios set its attributes."""

    def __init__(self) -> None:
        self.documents: dict[int, dict[str, Any]] = {}
        self._next_id = 1
        # Toggles for scenario scripting.
        self.healthy = True  # llama + db both ok
        self.llama_healthy = True
        self.db_healthy = True
        self.reachable = True  # False -> transport raises ConnectError
        self.slots = 1
        self.hot_documents: dict[str, int] = {}
        # Canned query response knobs.
        self.answer = "The capital is Fredville."
        self.cache_source = "memory"
        self.duration_ms = 1234
        self.prompt_evaluated = 12
        self.prompt_cached = 480
        self.answer_tokens = 20
        # Next upload behaviour overrides (set to force error paths).
        self.next_upload_error: tuple[int, dict[str, Any]] | None = None
        self.dedupe_next = False

    # -- helpers ------------------------------------------------------------

    def add_document(
        self,
        file_name: str,
        *,
        status: str = "cached",
        n_tokens: int | None = 480,
        use_count: int = 0,
        error: str | None = None,
    ) -> dict[str, Any]:
        doc_id = self._next_id
        self._next_id += 1
        doc = {
            "id": doc_id,
            "slug": file_name.rsplit(".", 1)[0],
            "file_name": file_name,
            "n_tokens": n_tokens,
            "cache_file": f"doc-{doc_id}.bin" if status == "cached" else None,
            "status": status,
            "error": error,
            "created_at": _now(),
            "cached_at": _now() if status == "cached" else None,
            "last_used_at": _now() if use_count else None,
            "use_count": use_count,
        }
        self.documents[doc_id] = doc
        return doc

    @staticmethod
    def _public(doc: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in doc.items() if k not in ("content", "slug")}

    def _health_report(self) -> tuple[int, dict[str, Any]]:
        llama_ok = self.healthy and self.llama_healthy
        db_ok = self.healthy and self.db_healthy
        status = "ok" if (llama_ok and db_ok) else "degraded"
        report: dict[str, Any] = {
            "status": status,
            "hot_documents": {str(k): v for k, v in self.hot_documents.items()},
            "slots": self.slots,
            "llama_server": {"status": "ok"} if llama_ok else {"error": "llama-server unreachable"},
            "database": "ok" if db_ok else {"error": "db down"},
        }
        return (200 if status == "ok" else 503), report

    # -- routing ------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.reachable:
            raise httpx.ConnectError("connection refused", request=request)

        path = request.url.path
        method = request.method

        if path == "/health" and method == "GET":
            status, body = self._health_report()
            return httpx.Response(status, json=body)

        if path == "/documents" and method == "GET":
            docs = [self._public(d) for d in self.documents.values()]
            return httpx.Response(200, json={"documents": docs})

        if path == "/documents" and method == "POST":
            return self._handle_upload(request)

        if path.startswith("/documents/") and method == "DELETE":
            return self._handle_delete(path)

        if path == "/query" and method == "POST":
            return self._handle_query(request)

        if path == "/maintenance" and method == "POST":
            return self._handle_maintenance()

        return httpx.Response(404, json={"detail": f"no route {method} {path}"})

    def _handle_upload(self, request: httpx.Request) -> httpx.Response:
        if self.next_upload_error is not None:
            status, body = self.next_upload_error
            self.next_upload_error = None
            return httpx.Response(status, json=body)

        file_name = self._multipart_filename(request) or "upload.txt"
        ext = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if ext not in _SUPPORTED_EXT:
            return httpx.Response(
                415, json={"detail": f"Unsupported file type '{ext or file_name}'."}
            )

        if self.dedupe_next and self.documents:
            self.dedupe_next = False
            existing = next(iter(self.documents.values()))
            body = {**self._public(existing), "deduplicated": True}
            return httpx.Response(201, json=body)

        doc = self.add_document(file_name, status="cached")
        body = {**self._public(doc), "deduplicated": False, "warm_ms": 4200}
        return httpx.Response(201, json=body)

    @staticmethod
    def _multipart_filename(request: httpx.Request) -> str | None:
        # Pull filename="..." out of the multipart body without a full parser.
        content = request.content
        marker = b'filename="'
        idx = content.find(marker)
        if idx == -1:
            return None
        start = idx + len(marker)
        end = content.find(b'"', start)
        if end == -1:
            return None
        return content[start:end].decode("utf-8", errors="replace")

    def _handle_delete(self, path: str) -> httpx.Response:
        try:
            doc_id = int(path.rsplit("/", 1)[-1])
        except ValueError:
            return httpx.Response(404, json={"detail": "bad id"})
        if doc_id not in self.documents:
            return httpx.Response(404, json={"detail": f"No document with id {doc_id}"})
        del self.documents[doc_id]
        return httpx.Response(200, json={"deleted": doc_id})

    def _handle_query(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        document_id = body.get("document_id")

        if document_id is not None:
            doc = self.documents.get(document_id)
            if doc is None:
                return httpx.Response(404, json={"detail": f"No document with id {document_id}"})
        else:
            cached = [d for d in self.documents.values() if d["status"] == "cached"]
            if not cached:
                return httpx.Response(
                    409, json={"detail": "No cached documents yet — ingest one first."}
                )
            doc = cached[-1]

        if not (self.healthy and self.llama_healthy):
            return httpx.Response(502, json={"detail": "llama-server unreachable"})

        return httpx.Response(
            200,
            json={
                "answer": self.answer,
                "document": {
                    "id": doc["id"],
                    "file_name": doc["file_name"],
                    "n_tokens": doc["n_tokens"],
                },
                "duration_ms": self.duration_ms,
                "timings": {
                    "prompt_tokens_evaluated": self.prompt_evaluated,
                    "prompt_tokens_from_cache": self.prompt_cached,
                    "answer_tokens": self.answer_tokens,
                    "cache_source": self.cache_source,
                },
            },
        )

    def _handle_maintenance(self) -> httpx.Response:
        cached = sum(1 for d in self.documents.values() if d["status"] == "cached")
        return httpx.Response(
            200,
            json={
                "orphan_files_removed": ["doc-9.bin"],
                "orphan_files_failed": [],
                "missing_cache_files": [],
                "cache_files": cached,
                "cache_bytes": cached * 1024,
                "documents": len(self.documents),
                "cached_documents": cached,
                "queries_24h": 3,
                "avg_duration_ms_24h": 1500,
            },
        )


@pytest.fixture
def fake_api() -> FakeCagApi:
    return FakeCagApi()


@pytest.fixture
def api_client(fake_api: FakeCagApi) -> ApiClient:
    transport = httpx.MockTransport(fake_api.handler)
    client = ApiClient("http://testserver", transport=transport)
    yield client
    client.close()


@pytest.fixture
def main_window(qtbot, fake_api: FakeCagApi):
    """Real MainWindow wired to the fake client, with the health poller stopped
    so tests drive polling explicitly via ``window.poll_health_now()``."""
    # Imported here (not at module top) so collecting non-UI tests never has to
    # build the widget tree.
    import httpx as _httpx
    from llamacag_ui.ui.main_window import MainWindow
    from PySide6.QtCore import QSettings

    from llamacag_ui.config import AppConfig

    # Isolated QSettings so tests never touch the real registry/plist.
    settings = QSettings()
    settings.clear()
    config = AppConfig(settings)

    def client_factory(base_url: str) -> ApiClient:
        return ApiClient(base_url, transport=_httpx.MockTransport(fake_api.handler))

    window = MainWindow(config, client_factory=client_factory)
    window.stop_polling()
    qtbot.addWidget(window)
    return window
