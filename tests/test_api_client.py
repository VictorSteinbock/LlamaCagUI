"""api_client contract tests against the in-memory FakeCagApi.

Mirrors the sibling repo's api tests: happy path for every endpoint, and each
error status mapped to its specific exception with the server ``detail`` carried
through.
"""

import httpx
import pytest

from llamacag_ui.api_client import (
    ApiClient,
    ApiUnreachable,
    Document,
    DocumentTooLarge,
    HealthReport,
    InferenceError,
    MaintenanceReport,
    NoDocuments,
    NotFound,
    QueryResult,
    StackDegraded,
    UnsupportedFile,
)

# --- happy paths -----------------------------------------------------------


def test_health_ok(api_client, fake_api):
    report = api_client.health()
    assert isinstance(report, HealthReport)
    assert report.status == "ok"
    assert report.ok is True
    assert report.llama_ok is True
    assert report.db_ok is True
    assert report.slots == 1


def test_health_degraded_is_data_not_error(api_client, fake_api):
    # 503 is a health report, not a raise: cag-api is up, a dependency is down.
    fake_api.llama_healthy = False
    report = api_client.health()
    assert report.status == "degraded"
    assert report.ok is False
    assert report.llama_ok is False
    assert "error" in report.llama_server


def test_list_documents(api_client, fake_api):
    fake_api.add_document("a.txt")
    fake_api.add_document("b.md", status="pending", n_tokens=None)
    docs = api_client.list_documents()
    assert [d.file_name for d in docs] == ["a.txt", "b.md"]
    assert all(isinstance(d, Document) for d in docs)
    assert docs[0].status == "cached"
    assert docs[1].status == "pending"


def test_upload_document_returns_document(api_client, fake_api):
    doc = api_client.upload_document("notes.md", b"# Facts\ntext", content_type="text/markdown")
    assert isinstance(doc, Document)
    assert doc.file_name == "notes.md"
    assert doc.status == "cached"
    assert doc.deduplicated is False
    assert doc.warm_ms == 4200


def test_upload_dedupe_surfaces_flag(api_client, fake_api):
    fake_api.add_document("orig.txt")
    fake_api.dedupe_next = True
    doc = api_client.upload_document("copy.txt", b"same content")
    assert doc.deduplicated is True


def test_delete_document(api_client, fake_api):
    doc = fake_api.add_document("bye.txt")
    assert api_client.delete_document(doc["id"]) == doc["id"]


def test_query_roundtrip(api_client, fake_api):
    fake_api.add_document("facts.txt")
    result = api_client.query("What is the capital?")
    assert isinstance(result, QueryResult)
    assert result.answer == "The capital is Fredville."
    assert result.duration_ms == 1234
    assert result.timings.cache_source == "memory"
    assert result.timings.prompt_tokens_evaluated == 12
    assert result.timings.prompt_tokens_from_cache == 480
    assert result.timings.answer_tokens == 20
    assert result.document["file_name"] == "facts.txt"


def test_query_sends_history_and_params(api_client, fake_api):
    fake_api.add_document("facts.txt")
    captured = {}

    def spy(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return fake_api.handler(request)

    client = ApiClient("http://testserver", transport=httpx.MockTransport(spy))
    client.query(
        "And its population?",
        document_id=1,
        max_tokens=256,
        temperature=0.5,
        history=[
            {"role": "user", "content": "What is the capital?"},
            {"role": "assistant", "content": "Fredville."},
        ],
    )
    client.close()
    body = captured["body"]
    assert body["document_id"] == 1
    assert body["max_tokens"] == 256
    assert body["temperature"] == 0.5
    assert [t["role"] for t in body["history"]] == ["user", "assistant"]


def test_maintenance(api_client, fake_api):
    fake_api.add_document("keep.txt")
    report = api_client.maintenance()
    assert isinstance(report, MaintenanceReport)
    assert report.cached_documents == 1
    assert report.orphan_files_removed == ["doc-9.bin"]
    assert report.queries_24h == 3


# --- error status -> specific exception ------------------------------------


def test_query_no_documents_is_409(api_client, fake_api):
    with pytest.raises(NoDocuments) as exc:
        api_client.query("hello?")
    assert exc.value.status == 409
    assert "ingest one first" in str(exc.value)


def test_query_unknown_document_is_404(api_client, fake_api):
    fake_api.add_document("facts.txt")
    with pytest.raises(NotFound) as exc:
        api_client.query("q", document_id=42)
    assert exc.value.status == 404
    assert "42" in str(exc.value)


def test_delete_unknown_is_404(api_client, fake_api):
    with pytest.raises(NotFound):
        api_client.delete_document(999)


def test_upload_unsupported_is_415(api_client, fake_api):
    with pytest.raises(UnsupportedFile) as exc:
        api_client.upload_document("evil.exe", b"MZ\x00\x01")
    assert exc.value.status == 415


def test_upload_too_large_is_413_with_fields(api_client, fake_api):
    fake_api.next_upload_error = (
        413,
        {
            "detail": "Document is 5000 tokens but the per-slot limit is 900.",
            "n_tokens": 5000,
            "limit": 900,
            "ctx_size": 1000,
        },
    )
    with pytest.raises(DocumentTooLarge) as exc:
        api_client.upload_document("big.txt", b"x" * 100)
    assert exc.value.status == 413
    assert exc.value.n_tokens == 5000
    assert exc.value.limit == 900
    assert exc.value.ctx_size == 1000


def test_query_llama_down_is_502(api_client, fake_api):
    fake_api.add_document("facts.txt")
    fake_api.llama_healthy = False
    with pytest.raises(InferenceError) as exc:
        api_client.query("q")
    assert exc.value.status == 502


def test_503_maps_to_stack_degraded(api_client, fake_api):
    # /health treats 503 as data, but any *other* endpoint returning 503 is a
    # StackDegraded error per the taxonomy.
    def degraded(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "service unavailable"})

    client = ApiClient("http://testserver", transport=httpx.MockTransport(degraded))
    with pytest.raises(StackDegraded) as exc:
        client.list_documents()
    client.close()
    assert exc.value.status == 503
    assert "service unavailable" in str(exc.value)


def test_unexpected_status_is_generic_api_error(api_client, fake_api):
    # A route the fake does not know returns 404 with detail -> NotFound here,
    # but an unmapped status such as 500 maps to the base ApiError.
    def five_hundred(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "kaboom"})

    client = ApiClient("http://testserver", transport=httpx.MockTransport(five_hundred))
    with pytest.raises(Exception) as exc:  # noqa: PT011 - asserting exact type below
        client.list_documents()
    client.close()
    from llamacag_ui.api_client import ApiError

    assert type(exc.value) is ApiError
    assert exc.value.status == 500
    assert "kaboom" in str(exc.value)


# --- transport failures -> ApiUnreachable ----------------------------------


def test_unreachable_health_raises(api_client, fake_api):
    fake_api.reachable = False
    with pytest.raises(ApiUnreachable):
        api_client.health()


def test_unreachable_list_raises(api_client, fake_api):
    fake_api.reachable = False
    with pytest.raises(ApiUnreachable):
        api_client.list_documents()


def test_unreachable_query_raises(api_client, fake_api):
    fake_api.reachable = False
    with pytest.raises(ApiUnreachable):
        api_client.query("q")
