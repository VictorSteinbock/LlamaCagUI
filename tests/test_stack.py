"""stack.py tests: no real Docker. A fake runner records argv/cwd, and .env
patching happens on a tmp copy.
"""

import subprocess

import pytest

from llamacag_ui.stack import NO_ENV_MESSAGE, StackController, StackError

COMPOSE = "services:\n  llama-server:\n    image: x\n"
ENV = (
    "LLAMA_MODEL=google/gemma-4-12B-it-qat-q4_0-gguf\n"
    "LLAMA_CTX_SIZE=65536\n"
    "CAG_SLOTS=1\n"
    "DB_PASSWORD=secret\n"
)


@pytest.fixture
def stack_dir(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    (tmp_path / ".env").write_text(ENV, encoding="utf-8")
    return tmp_path


class RecordingRunner:
    """Stands in for subprocess.run; records calls, returns a scripted result."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(
            args, self.returncode, stdout=self.stdout, stderr=self.stderr
        )


# --- availability ----------------------------------------------------------


def test_available_requires_docker_and_compose(stack_dir, monkeypatch):
    controller = StackController(stack_dir, runner=RecordingRunner())
    monkeypatch.setattr("llamacag_ui.stack.shutil.which", lambda _: "/usr/bin/docker")
    assert controller.available() is True
    assert controller.unavailable_reason() is None


def test_unavailable_without_docker(stack_dir, monkeypatch):
    controller = StackController(stack_dir, runner=RecordingRunner())
    monkeypatch.setattr("llamacag_ui.stack.shutil.which", lambda _: None)
    assert controller.available() is False
    assert "Docker not found" in controller.unavailable_reason()


def test_unavailable_without_stack_dir():
    controller = StackController(None, runner=RecordingRunner())
    assert controller.available() is False
    assert "No stack directory" in controller.unavailable_reason()


def test_unavailable_without_compose_file(tmp_path, monkeypatch):
    controller = StackController(tmp_path, runner=RecordingRunner())
    monkeypatch.setattr("llamacag_ui.stack.shutil.which", lambda _: "/usr/bin/docker")
    assert controller.available() is False
    assert "docker-compose.yml" in controller.unavailable_reason()


# --- argv / cwd construction -----------------------------------------------


def test_start_builds_compose_up_with_cwd(stack_dir):
    runner = RecordingRunner(stdout="Started")
    StackController(stack_dir, runner=runner).start()
    call = runner.calls[-1]
    assert call["args"] == ["docker", "compose", "up", "-d"]
    assert call["kwargs"]["cwd"] == str(stack_dir)
    assert call["kwargs"]["capture_output"] is True
    assert call["kwargs"]["text"] is True


def test_stop_builds_compose_down(stack_dir):
    runner = RecordingRunner()
    StackController(stack_dir, runner=runner).stop()
    assert runner.calls[-1]["args"] == ["docker", "compose", "down"]


def test_restart_llama_targets_only_that_service(stack_dir):
    runner = RecordingRunner()
    StackController(stack_dir, runner=runner).restart_llama()
    assert runner.calls[-1]["args"] == ["docker", "compose", "up", "-d", "llama-server"]


def test_ps_uses_json_format(stack_dir):
    runner = RecordingRunner(stdout='{"Service":"cag-api","State":"running"}')
    out = StackController(stack_dir, runner=runner).ps()
    assert runner.calls[-1]["args"] == ["docker", "compose", "ps", "--format", "json"]
    assert "cag-api" in out


def test_start_reports_progress_lines(stack_dir):
    runner = RecordingRunner(stdout="line one\nline two")
    lines = []
    StackController(stack_dir, runner=runner).start(on_progress=lines.append)
    assert lines == ["line one", "line two"]


def test_failed_command_raises_stack_error(stack_dir):
    runner = RecordingRunner(returncode=1, stderr="boom")
    with pytest.raises(StackError, match="boom"):
        StackController(stack_dir, runner=runner).start()


def test_no_shell_true_ever(stack_dir):
    # Guard the core invariant: shell is never enabled.
    runner = RecordingRunner()
    controller = StackController(stack_dir, runner=runner)
    controller.start()
    controller.stop()
    controller.restart_llama()
    for call in runner.calls:
        assert "shell" not in call["kwargs"]
        assert isinstance(call["args"], list)


# --- model management ------------------------------------------------------


def test_current_model_reads_env(stack_dir):
    controller = StackController(stack_dir, runner=RecordingRunner())
    assert controller.current_model() == "google/gemma-4-12B-it-qat-q4_0-gguf"


def test_set_model_rewrites_only_that_line(stack_dir):
    controller = StackController(stack_dir, runner=RecordingRunner())
    controller.set_model("unsloth/Qwen3.5-9B-GGUF:Q4_K_M")

    text = (stack_dir / ".env").read_text(encoding="utf-8")
    assert "LLAMA_MODEL=unsloth/Qwen3.5-9B-GGUF:Q4_K_M" in text
    # Every other line is untouched.
    assert "LLAMA_CTX_SIZE=65536" in text
    assert "CAG_SLOTS=1" in text
    assert "DB_PASSWORD=secret" in text
    # Exactly one LLAMA_MODEL line remains.
    assert text.count("LLAMA_MODEL=") == 1


def test_set_model_appends_when_absent(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    (tmp_path / ".env").write_text("DB_PASSWORD=secret\n", encoding="utf-8")
    controller = StackController(tmp_path, runner=RecordingRunner())
    controller.set_model("google/gemma-4-E4B-it-qat-q4_0-gguf")

    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LLAMA_MODEL=google/gemma-4-E4B-it-qat-q4_0-gguf" in text
    assert "DB_PASSWORD=secret" in text


def test_set_model_without_env_raises_guided_error(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    controller = StackController(tmp_path, runner=RecordingRunner())
    with pytest.raises(StackError, match="setup"):
        controller.set_model("google/gemma-4-12B-it-qat-q4_0-gguf")


def test_no_env_message_mentions_setup():
    assert "setup" in NO_ENV_MESSAGE


def test_current_model_none_without_env(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    controller = StackController(tmp_path, runner=RecordingRunner())
    assert controller.current_model() is None
