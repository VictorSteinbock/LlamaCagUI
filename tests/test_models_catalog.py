"""models_catalog sanity: the curated list is well-formed and has one default."""

from llamacag_ui.models_catalog import (
    CATALOG,
    DEFAULT_MODEL_REPO,
    default_model,
    find,
)


def test_catalog_non_empty():
    assert len(CATALOG) >= 5


def test_exactly_one_default():
    defaults = [entry for entry in CATALOG if entry.default]
    assert len(defaults) == 1
    assert default_model() is defaults[0]


def test_default_matches_env_example():
    assert default_model().repo == DEFAULT_MODEL_REPO
    assert DEFAULT_MODEL_REPO == "google/gemma-4-12B-it-qat-q4_0-gguf"


def test_all_entries_have_metadata():
    for entry in CATALOG:
        assert "/" in entry.repo  # <user>/<repo>[:quant]
        assert entry.label
        assert entry.context
        assert entry.size
        assert entry.description


def test_repos_are_unique():
    repos = [entry.repo for entry in CATALOG]
    assert len(repos) == len(set(repos))


def test_find_returns_entry_or_none():
    assert find(DEFAULT_MODEL_REPO) is default_model()
    assert find("someone/custom-model:Q4") is None
