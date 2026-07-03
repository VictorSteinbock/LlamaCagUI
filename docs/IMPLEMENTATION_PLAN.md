# Implementation Plan — LlamaCag UI v2

Executor contract. Read docs/PRD.md and docs/ARCHITECTURE.md first; they are
binding. The reference backend lives at `C:\Users\vp\Documents\GitHub\llama-cag-n8N`
— read `api/app/main.py`, `api/app/cag.py`, and `api/tests/` for exact request/
response shapes; do not guess the contract.

## Phase 0 — Clean slate (git preserves everything)

Delete: `FIXES/`, `ADDITIONALREADME/`, `core/`, `ui/`, `utils/`, `scripts/`,
`images/`, `main.py`, `run.sh`, `cleanup_and_fix.sh`, `setup_requirements.sh`,
`model_urls.txt`, all `.DS_Store`. Keep: `.git`, `.gitattributes`, `.gitignore`
(extend), `docs/`, `resources/` only if repopulated (else delete).

## Phase 1 — Skeleton

- `pyproject.toml`: name `llamacag-ui`, version `2.0.0`, `requires-python >=3.11`,
  deps: `PySide6>=6.7`, `httpx>=0.27`; dev extras: `pytest>=8`, `pytest-qt>=4.4`,
  `ruff>=0.6`. Console script `llamacag-ui = llamacag_ui.__main__:main`.
  Ruff config mirroring the sibling repo (line-length 100, rules E,F,W,I,UP,B).
  Pytest config: `testpaths=["tests"]`, and set `qt_api = "pyside6"`.
- `llamacag_ui/__init__.py` (`__version__`), `__main__.py` (QApplication,
  org/app names `LlamaCag`/`LlamaCagUI`, welcome-dialog gate, MainWindow, exec).
- `.gitignore` additions: `.ruff_cache/`, `.pytest_cache/`, `dist/`, `.DS_Store`.
- `.gitattributes`: force LF for `*.py`, `*.yml`, `*.toml` not required; keep as is.

## Phase 2 — Foundation modules (with tests as you go)

1. `llamacag_ui/config.py` — `AppConfig` wrapping QSettings; typed properties
   with defaults (`api_url="http://localhost:8000"`, `stack_dir: Path|None`,
   `max_tokens=1024`, `temperature=0.2`, `show_welcome=True`);
   `detect_stack_dir()` scanning the parent directory for `llama-cag-n8*`
   containing `docker-compose.yml`.
2. `llamacag_ui/api_client.py` — sync httpx client per ARCHITECTURE contract
   table (endpoints, timeouts, exception taxonomy). Dataclasses or TypedDicts
   for Document, QueryResult, HealthReport, MaintenanceReport. Constructor takes
   `base_url` and optional `transport` (for tests).
3. `llamacag_ui/workers.py` — `Worker(QRunnable)` + `WorkerSignals(finished,
   failed)`; helper `run_in_pool(fn, on_finished, on_failed)`.
4. `llamacag_ui/stack.py` — `StackController(stack_dir)`: `available()` (docker
   on PATH + compose file exists), `ps()`, `start()`, `stop()`,
   `restart_llama()`, `current_model()` / `set_model(repo_spec)` (patch `.env`
   `^LLAMA_MODEL=` line; create from `.env.example`-less is out of scope — if no
   `.env`, raise with "run python llamacag.py setup in the stack first").
   Subprocess: list args, `cwd=stack_dir`, capture output, never `shell=True`.
5. `llamacag_ui/models_catalog.py` — entries (verified mid-2026):
   `google/gemma-4-12B-it-qat-q4_0-gguf` (default, 262k ctx, ~6.5 GB),
   `google/gemma-4-E4B-it-qat-q4_0-gguf` (light, ~3 GB),
   `unsloth/Qwen3.5-9B-GGUF:Q4_K_M` (~5.5 GB),
   `google/gemma-4-26B-A4B-it-qat-q4_0-gguf` (MoE, ~15 GB),
   `ggml-org/GLM-4.7-Flash-GGUF:Q4_K` (~27 GB) — each with context, size,
   one-line description.

## Phase 3 — UI

6. `llamacag_ui/ui/toast.py` — port the v1 toast concept (fade in/out,
   auto-dismiss, success/error variants). Keep it ≤120 lines.
7. `llamacag_ui/ui/welcome_dialog.py` — modernized copy: what CAG is (3
   sentences), quickstart (start stack → drop/upload document → chat), link to
   stack README; "don't show again" via config.
8. `llamacag_ui/ui/documents_tab.py` — QTableView+model or QTableWidget:
   columns id, file name, status (colored), tokens, last used, uses; toolbar:
   Upload, Delete, Refresh; drag-drop of files onto the table triggers upload;
   status column auto-refresh (reuse the 10 s poller tick); upload worker shows
   "uploading + warming (minutes on CPU)" toast; dedupe → info toast.
9. `llamacag_ui/ui/chat_tab.py` — document combo (cached docs, "(latest)"
   default), transcript (QListWidget or rich QTextBrowser with bubbles), input
   QPlainTextEdit (Enter sends, Shift+Enter newline), params popover or compact
   row (max_tokens spin, temperature double-spin), per-answer footer badge:
   `⚡ memory | 💾 disk | 🔁 recomputed` + `N tok evaluated / M cached / X ms`,
   Clear conversation button. History = last 20 turns sent to `/query`.
10. `llamacag_ui/ui/stack_tab.py` — three health cards (api/llama/db) with
    detail text, hot-slots list, maintenance button → report rendered as a
    simple key/value panel + toast; stack controls group (Start/Stop/status,
    log tail read-only view) enabled iff `StackController.available()`;
    model switcher group: current model label, catalog combo + free-form field,
    Apply → confirm dialog warning "existing caches re-heal on next use".
11. `llamacag_ui/ui/main_window.py` — QTabWidget (Chat, Documents, Stack,
    Settings), status bar with three colored dots + text, 10 s QTimer health
    poller feeding: dots, chat-send enablement, documents refresh.
12. `llamacag_ui/ui/settings_tab.py` — api_url line edit (with "Test" button →
    health call), stack_dir picker + auto-detect button, chat defaults, "Show
    welcome dialog" button. Apply persists via AppConfig and re-points the
    ApiClient (recreate client object; workers take it per call).

## Phase 4 — Tests (definition of done: all pass offscreen)

- `tests/conftest.py`: `fake_api` — httpx.MockTransport routing GET/POST paths
  to an in-memory store; fixtures `api_client`, `qapp` (pytest-qt provides),
  `main_window` wired to the fake client with poller timer stopped by default.
- `tests/test_api_client.py`: happy paths for all 6 calls; each error status →
  the specific exception; detail text propagation; unreachable → ApiUnreachable.
- `tests/test_stack.py`: tmp dir with fake `docker-compose.yml` + `.env`;
  `set_model` rewrites only the LLAMA_MODEL line; missing `.env` raises the
  guided error; argv construction for start/stop/restart (monkeypatch
  subprocess.run, assert list-args and cwd).
- `tests/test_config.py`: defaults, roundtrip, stack auto-detect on tmp layout.
- `tests/test_ui_smoke.py`: window opens with 4 tabs; documents table shows the
  fake's rows after a manual poll tick; chat send → answer bubble text + badge
  "memory"; health degraded (fake toggled) → send button disabled.

## Phase 5 — Docs, CI, screenshots

- `scripts/make_screenshots.py` per ARCHITECTURE (offscreen grab of welcome,
  chat with a sample exchange, documents, stack tabs using the test fake).
  Run it; commit `docs/images/*.png`.
- `README.md` rewrite: hero line, generated screenshots, relationship diagram
  to llama-cag-n8n (mermaid ok), quickstart (stack first, then
  `pip install -e .` + `llamacag-ui`), features table, settings reference,
  troubleshooting (stack down, long warms, model switch), development section,
  MIT license note.
- `LICENSE` — MIT, `Copyright (c) 2025-2026 VictorSteinbock`.
- `CLAUDE.md` — commands, the one-network-module / one-subprocess-module rule,
  contract source pointer, offscreen test invocation.
- `.github/workflows/ci.yml` — ubuntu-latest: apt Qt deps (`libegl1 libgl1
  libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0`),
  `pip install -e ".[dev]"`, `ruff check .`, `QT_QPA_PLATFORM=offscreen pytest -q`.

## Acceptance criteria (verified before you finish)

1. `python -m venv .venv && pip install -e ".[dev]"` succeeds (use any venv).
2. `ruff check .` → zero findings.
3. `QT_QPA_PLATFORM=offscreen pytest -q` → all green, no network, no Docker.
4. `python scripts/make_screenshots.py` produces the four PNGs.
5. Zero occurrences of `shell=True`, `os.system`, `llama_cpp`, `pickle` in
   `llamacag_ui/`.
6. `git status` shows a coherent tree (deleted v1 dirs gone, no stray backups).

Do NOT: commit (leave the tree dirty for review), push, touch the sibling
llama-cag-n8N repo, or add dependencies beyond the listed ones without noting
why in your final report.
