"""config.py tests: defaults, round-trip through an in-memory QSettings, and
stack auto-detection on a tmp sibling layout.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from llamacag_ui.config import (
    DEFAULT_API_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    AppConfig,
    detect_stack_dir,
)


@pytest.fixture
def config():
    settings = QSettings()
    settings.clear()
    return AppConfig(settings)


def test_defaults(config):
    assert config.api_url == DEFAULT_API_URL
    assert config.stack_dir is None
    assert config.max_tokens == DEFAULT_MAX_TOKENS
    assert config.temperature == DEFAULT_TEMPERATURE
    assert config.show_welcome is True


def test_api_url_roundtrip(config):
    config.api_url = "http://192.168.1.5:9000"
    assert config.api_url == "http://192.168.1.5:9000"


def test_api_url_blank_falls_back_to_default(config):
    config.api_url = "   "
    assert config.api_url == DEFAULT_API_URL


def test_stack_dir_roundtrip(config, tmp_path):
    config.stack_dir = tmp_path
    assert config.stack_dir == tmp_path
    config.stack_dir = None
    assert config.stack_dir is None


def test_chat_defaults_roundtrip(config):
    config.max_tokens = 2048
    config.temperature = 0.7
    assert config.max_tokens == 2048
    assert config.temperature == 0.7


def test_show_welcome_roundtrip(config):
    config.show_welcome = False
    assert config.show_welcome is False
    config.show_welcome = True
    assert config.show_welcome is True


def test_show_welcome_reads_string_true(config):
    # Some QSettings backends hand booleans back as strings.
    config._settings.setValue("ui/show_welcome", "false")
    assert config.show_welcome is False
    config._settings.setValue("ui/show_welcome", "true")
    assert config.show_welcome is True


# --- auto-detection --------------------------------------------------------


def test_detect_stack_dir_finds_sibling_with_compose(tmp_path):
    stack = tmp_path / "llama-cag-n8n"
    stack.mkdir()
    (stack / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    assert detect_stack_dir(tmp_path) == stack


def test_detect_stack_dir_matches_capitalized_variant(tmp_path):
    stack = tmp_path / "llama-cag-n8N"
    stack.mkdir()
    (stack / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    assert detect_stack_dir(tmp_path) == stack


def test_detect_stack_dir_ignores_dir_without_compose(tmp_path):
    (tmp_path / "llama-cag-n8n").mkdir()  # no compose file inside
    assert detect_stack_dir(tmp_path) is None


def test_detect_stack_dir_none_when_no_match(tmp_path):
    (tmp_path / "some-other-project").mkdir()
    assert detect_stack_dir(tmp_path) is None


def test_autodetect_persists(config, tmp_path, monkeypatch):
    stack = tmp_path / "llama-cag-n8n"
    stack.mkdir()
    (stack / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    monkeypatch.setattr(
        "llamacag_ui.config.detect_stack_dir", lambda *a, **k: stack
    )
    found = config.autodetect_stack_dir()
    assert found == stack
    assert config.stack_dir == Path(stack)
