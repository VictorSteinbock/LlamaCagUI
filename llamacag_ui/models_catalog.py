"""Curated GGUF model list, mirroring the stack's ``.env.example`` table.

These are the same options the sibling repo documents for ``LLAMA_MODEL``,
verified mid-2026. The Stack tab offers them in a combo alongside a free-form
``repo[:quant]`` field, so this list is a convenience, not a restriction. No
network here — just static metadata.
"""

from __future__ import annotations

from dataclasses import dataclass

# The stack's default LLAMA_MODEL (see .env.example / docker-compose.yml).
DEFAULT_MODEL_REPO = "google/gemma-4-12B-it-qat-q4_0-gguf"


@dataclass(frozen=True)
class ModelEntry:
    """One curated model. ``repo`` is the Hugging Face ``<user>/<repo>[:quant]``
    spec written verbatim into ``.env`` as ``LLAMA_MODEL``."""

    repo: str
    label: str
    context: str
    size: str
    description: str
    default: bool = False


CATALOG: list[ModelEntry] = [
    ModelEntry(
        repo="google/gemma-4-12B-it-qat-q4_0-gguf",
        label="Gemma 4 12B (QAT q4_0)",
        context="262k",
        size="~6.5 GB",
        description="Default. Google's quantization-aware-trained build; best all-round pick.",
        default=True,
    ),
    ModelEntry(
        repo="google/gemma-4-E4B-it-qat-q4_0-gguf",
        label="Gemma 4 E4B (QAT q4_0)",
        context="262k",
        size="~3 GB",
        description="Lightweight — for ~8 GB machines where the 12B is too heavy.",
    ),
    ModelEntry(
        repo="unsloth/Qwen3.5-9B-GGUF:Q4_K_M",
        label="Qwen 3.5 9B",
        context="128k",
        size="~5.5 GB",
        description="Strong small dense model; a solid alternative to Gemma 12B.",
    ),
    ModelEntry(
        repo="google/gemma-4-26B-A4B-it-qat-q4_0-gguf",
        label="Gemma 4 26B-A4B (MoE)",
        context="262k",
        size="~15 GB",
        description="MoE: 26B quality at ~4B active speed; wants ~20 GB free RAM.",
    ),
    ModelEntry(
        repo="ggml-org/GLM-4.7-Flash-GGUF:Q4_K",
        label="GLM 4.7 Flash",
        context="200k",
        size="~27 GB",
        description="Big-workstation class; highest quality, heaviest footprint.",
    ),
]


def default_model() -> ModelEntry:
    return next(entry for entry in CATALOG if entry.default)


def find(repo: str) -> ModelEntry | None:
    """Return the catalog entry for ``repo``, or None if it is a free-form spec."""
    for entry in CATALOG:
        if entry.repo == repo:
            return entry
    return None
