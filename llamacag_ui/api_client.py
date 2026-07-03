"""The one module that talks to cag-api. No Qt, no threading, no subprocess.

Everything the app knows about the cag-api HTTP contract lives here: endpoints,
payload shapes, per-call timeouts, and the mapping from HTTP status to a typed
exception. The reference implementation and its tests live in the sibling repo
(``api/app/main.py``, ``api/app/cag.py``, ``api/tests/``); this client mirrors
those response shapes exactly rather than guessing.

Callers get dataclasses back (Document, QueryResult, HealthReport,
MaintenanceReport) and catch exceptions from the taxonomy below. The server's
own ``detail`` string is treated as authoritative and carried on every error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

# --- timeouts (seconds), per ARCHITECTURE contract ------------------------
HEALTH_TIMEOUT = 5.0
DOCUMENTS_TIMEOUT = 30.0
UPLOAD_TIMEOUT = 3600.0
QUERY_TIMEOUT = 3600.0
MAINTENANCE_TIMEOUT = 300.0


# --- exception taxonomy ---------------------------------------------------


class ApiError(Exception):
    """Base for every cag-api failure. Carries the server ``detail`` if present.

    ``status`` is the HTTP status code (None for transport-level failures);
    ``payload`` is the decoded JSON body when the server returned one.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


class ApiUnreachable(ApiError):
    """Could not connect, or the request timed out. The stack is likely down."""


class StackDegraded(ApiError):
    """503 — cag-api is up but a dependency (llama-server or db) is unhealthy."""


class NoDocuments(ApiError):
    """409 — a query was issued but no documents are cached yet."""


class NotFound(ApiError):
    """404 — the referenced document does not exist."""


class DocumentTooLarge(ApiError):
    """413 — the document exceeds the per-slot token budget.

    Carries ``n_tokens`` and ``limit`` (and ``ctx_size`` when the server sends
    it) so the UI can explain the fit failure precisely.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status=status, payload=payload)
        self.n_tokens: int | None = self.payload.get("n_tokens")
        self.limit: int | None = self.payload.get("limit")
        self.ctx_size: int | None = self.payload.get("ctx_size")


class UnsupportedFile(ApiError):
    """415 — the uploaded file type cannot be turned into text."""


class InferenceError(ApiError):
    """502 — llama-server is down or returned an error mid-request."""


# --- response dataclasses -------------------------------------------------


@dataclass(frozen=True)
class Document:
    """A row from ``GET /documents`` (or a ``POST /documents`` result).

    Extra keys the server may add over time (``deduplicated``, ``warm_ms``, or
    future fields) are preserved in ``raw`` so nothing is silently lost.
    """

    id: int
    file_name: str
    status: str
    n_tokens: int | None = None
    cache_file: str | None = None
    error: str | None = None
    created_at: str | None = None
    cached_at: str | None = None
    last_used_at: str | None = None
    use_count: int = 0
    deduplicated: bool | None = None
    warm_ms: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        return cls(
            id=int(data["id"]),
            file_name=data.get("file_name", ""),
            status=data.get("status", "unknown"),
            n_tokens=data.get("n_tokens"),
            cache_file=data.get("cache_file"),
            error=data.get("error"),
            created_at=data.get("created_at"),
            cached_at=data.get("cached_at"),
            last_used_at=data.get("last_used_at"),
            use_count=data.get("use_count") or 0,
            deduplicated=data.get("deduplicated"),
            warm_ms=data.get("warm_ms"),
            raw=data,
        )


@dataclass(frozen=True)
class QueryTimings:
    prompt_tokens_evaluated: int | None = None
    prompt_tokens_from_cache: int | None = None
    answer_tokens: int | None = None
    cache_source: str = "recomputed"  # memory | disk | recomputed

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryTimings:
        return cls(
            prompt_tokens_evaluated=data.get("prompt_tokens_evaluated"),
            prompt_tokens_from_cache=data.get("prompt_tokens_from_cache"),
            answer_tokens=data.get("answer_tokens"),
            cache_source=data.get("cache_source", "recomputed"),
        )


@dataclass(frozen=True)
class QueryResult:
    answer: str
    document: dict[str, Any]
    duration_ms: int
    timings: QueryTimings
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryResult:
        return cls(
            answer=data.get("answer", ""),
            document=data.get("document", {}),
            duration_ms=int(data.get("duration_ms", 0)),
            timings=QueryTimings.from_dict(data.get("timings", {})),
            raw=data,
        )


@dataclass(frozen=True)
class HealthReport:
    status: str  # ok | degraded
    hot_documents: dict[str, int]
    slots: int
    llama_server: dict[str, Any]
    database: Any
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def llama_ok(self) -> bool:
        return "error" not in self.llama_server

    @property
    def db_ok(self) -> bool:
        return self.database == "ok"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HealthReport:
        return cls(
            status=data.get("status", "degraded"),
            hot_documents=data.get("hot_documents", {}),
            slots=int(data.get("slots", 0)),
            llama_server=data.get("llama_server", {}),
            database=data.get("database", {}),
            raw=data,
        )

    @classmethod
    def unreachable(cls, detail: str) -> HealthReport:
        """Synthetic report for when cag-api itself cannot be reached."""
        return cls(
            status="unreachable",
            hot_documents={},
            slots=0,
            llama_server={"error": detail},
            database={"error": detail},
            raw={"detail": detail},
        )


@dataclass(frozen=True)
class MaintenanceReport:
    orphan_files_removed: list[str]
    orphan_files_failed: list[Any]
    missing_cache_files: list[str]
    cache_files: int
    cache_bytes: int
    documents: int
    cached_documents: int
    queries_24h: int
    avg_duration_ms_24h: int
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaintenanceReport:
        return cls(
            orphan_files_removed=data.get("orphan_files_removed", []),
            orphan_files_failed=data.get("orphan_files_failed", []),
            missing_cache_files=data.get("missing_cache_files", []),
            cache_files=int(data.get("cache_files", 0)),
            cache_bytes=int(data.get("cache_bytes", 0)),
            documents=int(data.get("documents", 0)),
            cached_documents=int(data.get("cached_documents", 0)),
            queries_24h=int(data.get("queries_24h", 0)),
            avg_duration_ms_24h=int(data.get("avg_duration_ms_24h", 0)),
            raw=data,
        )


# --- status -> exception mapping ------------------------------------------

_STATUS_EXCEPTIONS: dict[int, type[ApiError]] = {
    404: NotFound,
    409: NoDocuments,
    413: DocumentTooLarge,
    415: UnsupportedFile,
    502: InferenceError,
    503: StackDegraded,
}


class ApiClient:
    """Synchronous cag-api client. Constructed per settings; cheap to recreate.

    ``transport`` lets tests inject an ``httpx.MockTransport`` implementing an
    in-memory cag-api — the same fake-driven approach the sibling repo uses.
    """

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # Per-request timeouts are passed explicitly on every call; this default
        # only guards against a caller that forgets one.
        self._client = httpx.Client(
            base_url=self.base_url,
            transport=transport,
            timeout=DOCUMENTS_TIMEOUT,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- request plumbing --------------------------------------------------

    def _request(self, method: str, path: str, *, timeout: float, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, timeout=timeout, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ApiUnreachable(
                f"Cannot reach cag-api at {self.base_url}. Is the stack running?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ApiUnreachable(f"cag-api request timed out after {timeout:g}s.") from exc
        except httpx.HTTPError as exc:
            raise ApiUnreachable(f"cag-api request failed: {exc}") from exc

        if response.status_code >= 400:
            raise self._error_for(response)
        return self._json(response)

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {}

    def _error_for(self, response: httpx.Response) -> ApiError:
        payload = self._json(response)
        payload = payload if isinstance(payload, dict) else {"detail": str(payload)}
        detail = payload.get("detail") or f"cag-api returned HTTP {response.status_code}"
        exc_type = _STATUS_EXCEPTIONS.get(response.status_code, ApiError)
        return exc_type(detail, status=response.status_code, payload=payload)

    # --- endpoints ---------------------------------------------------------

    def health(self) -> HealthReport:
        """GET /health. 200 -> ok, 503 -> degraded (still a report, not a raise).

        Unlike other calls a 503 here is data, not an error: cag-api is up and
        telling us a dependency is down. Only an unreachable cag-api raises.
        """
        try:
            response = self._client.get("/health", timeout=HEALTH_TIMEOUT)
        except httpx.HTTPError as exc:
            raise ApiUnreachable(
                f"Cannot reach cag-api at {self.base_url}. Is the stack running?"
            ) from exc
        payload = self._json(response)
        if not isinstance(payload, dict):
            payload = {}
        if response.status_code not in (200, 503):
            raise self._error_for(response)
        return HealthReport.from_dict(payload)

    def list_documents(self) -> list[Document]:
        data = self._request("GET", "/documents", timeout=DOCUMENTS_TIMEOUT)
        return [Document.from_dict(d) for d in data.get("documents", [])]

    def upload_document(
        self,
        file_name: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> Document:
        """POST /documents (multipart). Warms the document server-side, so this
        can legitimately take minutes — hence the hour-long timeout."""
        files = {"file": (file_name, data, content_type or "application/octet-stream")}
        result = self._request("POST", "/documents", timeout=UPLOAD_TIMEOUT, files=files)
        return Document.from_dict(result)

    def delete_document(self, document_id: int) -> int:
        result = self._request(
            "DELETE", f"/documents/{document_id}", timeout=DOCUMENTS_TIMEOUT
        )
        return int(result.get("deleted", document_id))

    def query(
        self,
        question: str,
        *,
        document_id: int | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> QueryResult:
        """POST /query. History is the prior turns (oldest first); the server
        caps it at 50 — we send at most the last 20 (see MAX_HISTORY_TURNS in
        the chat tab)."""
        body: dict[str, Any] = {"question": question}
        if document_id is not None:
            body["document_id"] = document_id
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if history:
            body["history"] = history
        result = self._request("POST", "/query", timeout=QUERY_TIMEOUT, json=body)
        return QueryResult.from_dict(result)

    def maintenance(self) -> MaintenanceReport:
        result = self._request("POST", "/maintenance", timeout=MAINTENANCE_TIMEOUT)
        return MaintenanceReport.from_dict(result)
