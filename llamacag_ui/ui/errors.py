"""Turn an exception into a human-readable line for toasts and chat bubbles.

The server's ``detail`` is authoritative (ARCHITECTURE N3), so we lead with it.
This helper only adds a short prefix per exception type where that makes the
failure more actionable — e.g. "Stack unreachable: ..." for a down cag-api, or
the fit numbers for a too-large document.
"""

from __future__ import annotations

from ..api_client import (
    ApiError,
    ApiUnreachable,
    DocumentTooLarge,
    InferenceError,
    NoDocuments,
    NotFound,
    StackDegraded,
    UnsupportedFile,
)


def message_for(exc: BaseException) -> str:
    """Best human-readable message for ``exc``."""
    if isinstance(exc, ApiUnreachable):
        return str(exc)
    if isinstance(exc, DocumentTooLarge):
        detail = str(exc)
        if exc.n_tokens is not None and exc.limit is not None:
            return f"{detail} (document {exc.n_tokens} tokens, limit {exc.limit})"
        return detail
    if isinstance(exc, StackDegraded):
        return f"Stack degraded: {exc}"
    if isinstance(exc, NoDocuments):
        return str(exc)
    if isinstance(exc, NotFound):
        return str(exc)
    if isinstance(exc, UnsupportedFile):
        return str(exc)
    if isinstance(exc, InferenceError):
        return f"Inference failed: {exc}"
    if isinstance(exc, ApiError):
        return str(exc)
    return str(exc) or exc.__class__.__name__
