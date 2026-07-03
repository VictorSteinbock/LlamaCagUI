# CLAUDE.md

Guidance for working in this repository.

## What this is

A PySide6 desktop client for the **llama-cag-n8n** v2 stack. It does HTTP (to
`cag-api`) and pixels — nothing else. No inference, no KV-cache handling, no
model management beyond editing the stack's `.env`. If you find yourself adding
inference-state logic client-side, stop: that belongs in the stack.

## Commands

```bash
# Install (with dev tooling)
pip install -e ".[dev]"

# Lint — must be clean
ruff check .

# Tests — headless, mocked transport, no Docker, no network
QT_QPA_PLATFORM=offscreen pytest -q

# Run the app
llamacag-ui

# Regenerate README screenshots
QT_QPA_PLATFORM=offscreen python scripts/make_screenshots.py
```

## Architectural rules (do not break these)

1. **Exactly one module touches the network:** `llamacag_ui/api_client.py`.
   No `httpx` (or any HTTP) anywhere else. It has no Qt imports and no threading.
2. **Exactly one module touches subprocesses:** `llamacag_ui/stack.py`.
   Always list-argument `docker compose` calls with `cwd=stack_dir`. Never
   `shell=True`, never `os.system`, never a constructed command string.
3. **All UI updates arrive via Qt signals** from `llamacag_ui/workers.py`'s
   single `Worker` / `run_in_pool`. Widgets never call the network or a
   subprocess directly — they hand a callable to a worker. No shared mutable
   state across threads.
4. **No client-side inference state.** No `llama_cpp`, no `pickle`, no KV files.
5. **Runtime deps are only PySide6 and httpx.** Adding another needs a good
   reason (and a note in the PR).

## The cag-api contract (source of truth)

The HTTP contract is defined by the sibling repo, not guessed here:

- `../llama-cag-n8N/api/app/main.py` — routes and error→status mapping
- `../llama-cag-n8N/api/app/cag.py` — response shapes (esp. `/query` timings and
  `cache_source`)
- `../llama-cag-n8N/api/tests/` — exact request/response examples

`api_client.py` mirrors these. If the contract changes upstream, update that one
module and its tests (`tests/test_api_client.py`) — nothing else should need to.

## Layout

```
llamacag_ui/
  __main__.py        entry point (QApplication, welcome gate, MainWindow)
  config.py          AppConfig over QSettings; stack auto-detect
  api_client.py      the one network module (typed errors + dataclasses)
  workers.py         the one threading primitive (Worker + run_in_pool)
  stack.py           the one subprocess module (docker compose, .env patch)
  models_catalog.py  curated model list (mirrors stack .env.example)
  ui/                widgets — presentation only
    main_window.py   tab host + 10s health poller (drives dots, gating, refresh)
    chat_tab.py  documents_tab.py  stack_tab.py  settings_tab.py
    welcome_dialog.py  toast.py  errors.py
tests/               pytest-qt + httpx.MockTransport fake cag-api
scripts/             make_screenshots.py (offscreen, fixture data)
```

## Testing approach

`tests/conftest.py` builds a `FakeCagApi` served through `httpx.MockTransport`
and a `MainWindow` wired to it with the poller stopped. Tests drive real widgets
and wait on observable state with `qtbot.waitUntil` (workers are async on the
thread pool). QSettings is isolated to a temp INI file so tests never touch the
real registry/plist.
