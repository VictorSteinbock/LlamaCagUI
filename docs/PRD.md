# PRD — LlamaCag UI v2

**Status:** Adopted · **Last updated:** 2026-07-02
**Supersedes:** v1 (March 2025, abandoned mid-fight with KV-state pickling)

## 1. Problem

The llama-cag-n8n stack gives you local, cache-augmented document Q&A — but its
interfaces are curl, n8n workflows, and a CLI. A person who just wants to *use*
their documents needs a desktop app: pick a document, chat with it, see what's
cached, manage the model.

v1 of LlamaCag UI tried to be that app **and** the inference engine at once: it
embedded llama-cpp-python, pickled KV state to `.llama_cache` files, hand-rolled
a warm-up mode with a persistent in-process model, and shelled out to bash
scripts from the sibling project. The repo's own `FIXES/` folder (25 files:
`final-attempt.py`, `extreme-cleanup.sh`, `reset-everything.sh`) documents how
that ended. The failure wasn't the vision — it was owning inference-state
mechanics client-side.

## 2. What v1 got right (the goals we keep)

- **The five-surface UX:** Chat / Documents / Cache monitor / Model management /
  Settings, plus a first-run welcome dialog that explains CAG in plain words.
- **The "warm" concept surfaced in the UI:** users could see whether a document
  was hot ("Warmed Up", "Using TRUE KV Cache") — v2 keeps this as the
  `memory / disk / recomputed` cache-source badge.
- **Status-bar health indicators** (color-coded, at-a-glance) and **toast
  notifications**.
- **Token/context-fit feedback** before processing a document.
- **Signal-driven Qt architecture** with all slow work off the UI thread.

## 3. The v2 shift

**LlamaCag UI v2 is a thin desktop client of the llama-cag-n8n v2 stack.**
All inference, KV persistence, warm-up, slot management, extraction, and
registry logic lives server-side in `cag-api` + `llama-server` (proven upstream
code). The UI does HTTP and pixels. What v1 hand-built and broke on —
persistent warm instances, state save/restore — is now `CAG_SLOTS` and
`--slot-save-path` on the server, already tested and shipped.

Standalone-feel is preserved by letting the UI **manage the stack**: detect the
sibling repo, show per-service health, start/stop it (docker compose), and
switch models by editing its `.env` — the same role v1's llama.cpp
installer/model downloader played, minus the compilation pain.

## 4. Goals

- **G1 — Chat with your documents, multi-turn**, against the stack's `/query`
  with `history`; per-conversation document selection; visible cache behavior
  (source badge, tokens evaluated vs cached, duration).
- **G2 — Document lifecycle in two clicks:** upload (file dialog or drag-drop),
  watch status (pending → cached / failed with reason), delete.
- **G3 — Stack visibility and control:** health of api/llama/db, hot slots,
  disk usage, run maintenance, start/stop the stack, switch models from a
  curated 2026 list with a clear "caches will re-heal" warning.
- **G4 — Zero-knowledge onboarding:** welcome dialog explains CAG and walks
  through first document → first answer.
- **G5 — Cross-platform:** Windows/macOS/Linux; Python 3.11+; PySide6; no
  compilation, no llama-cpp-python.
- **G6 — Tested and CI-gated** like the sibling repo: unit tests against a fake
  cag-api (no network, no Docker), offscreen UI smoke tests, ruff, GitHub Actions.

## 5. Non-goals

- **No embedded inference.** The app never links llama.cpp in-process. If the
  stack is down, the app says so and offers to start it — it does not fall back
  to local inference or context-prepending (v1's fallback mode is retired).
- **No streaming tokens in v2.0.** `/query` is request/response; the UI shows a
  generating state and then the answer with timings. (Future: SSE passthrough.)
- **No n8n administration.** n8n remains the automation face; this app talks
  only to cag-api and docker compose.
- **No document editing/preview beyond metadata.**

## 6. Functional requirements

| ID | Requirement |
|----|-------------|
| F1 | Chat tab: document picker (cached docs), multi-turn transcript, params (max_tokens, temperature), Enter-to-send, per-message cache-source badge + timings, conversation reset, copy answer. |
| F2 | History sent as `/query.history` (last 20 turns), errors surfaced as chat bubbles with the API's `detail` text. |
| F3 | Documents tab: table (id, name, status, tokens, size-fit, last used, uses), upload via dialog **and** drag-drop onto the table, delete with confirm, auto-refresh after operations, dedupe result surfaced ("already ingested"). |
| F4 | Upload rejects client-side nothing — server decides; 413/415 responses shown with their remediation text. |
| F5 | Stack tab: health cards (cag-api, llama-server, database) from `/health`, hot documents per slot, maintenance button showing the report (orphans removed, missing caches, cache disk usage), stack start/stop buttons + rolling log tail when a stack directory is configured. |
| F6 | Model switcher: curated list (same table as stack `.env.example`) + free-form HF `repo[:quant]`; writes `LLAMA_MODEL` in the stack's `.env`, restarts `llama-server`, warns that existing caches re-heal on next use. Disabled (with explanation) when no stack dir is set. |
| F7 | Settings tab: cag-api base URL (default `http://localhost:8000`), stack directory (auto-detected if `../llama-cag-n8n*` exists), chat defaults, "show welcome again". Persisted via QSettings. |
| F8 | Status bar: colored dots for api/llama/db, polled every 10 s off-thread; app remains fully responsive when the stack is down. |
| F9 | Welcome dialog on first run (QSettings-gated) with CAG explainer and quickstart. |
| F10 | All long operations (upload+warm, query, maintenance, stack control) run in worker threads; UI never blocks; concurrent actions are queued or disabled, never crash. |

## 7. Non-functional requirements

- **N1:** No `shell=True`, no bash scripts; subprocess only for `docker compose`
  with list arguments.
- **N2:** Warm/upload requests use long timeouts (≥ 1 h) — CPU warming a 30k-token
  document legitimately takes minutes; the UI shows progress state, not a spinner-of-lies.
- **N3:** Every cag-api error status (409, 404, 413, 415, 422, 502, 503) maps to
  a distinct, human-readable message (the API's own `detail` is authoritative).
- **N4:** Test suite runs headless (`QT_QPA_PLATFORM=offscreen`) with a mocked
  transport — no Docker, no network, < 30 s.
- **N5:** README screenshots are **generated** by a script (offscreen render with
  fixture data), so visuals never rot the way v1's screenshot gallery did.

## 8. Success criteria

1. `pip install -e ".[dev]" && llamacag-ui` launches on Windows against a running
   stack; drop a PDF on the Documents tab → status becomes `cached` → switch to
   Chat → ask → answer arrives with `cache_source: memory`.
2. Kill the stack → status dots go red within 10 s, chat send is disabled with
   an actionable message, Stack tab offers Start.
3. `pytest` green in CI on every push; ruff clean.
4. A new user can go from git clone to first answer using only the welcome
   dialog and README.

## 9. Risks

| Risk | Mitigation |
|------|------------|
| cag-api contract drift | Client is one module (`api_client.py`); the sibling repo's tests define the contract; version pinned in README |
| Long warms look like hangs | Explicit "warming (can take minutes on CPU)" state fed by the documents table status polling |
| Qt threading bugs (v1's downfall) | One `Worker` abstraction, signals-only UI updates, no shared mutable state, smoke tests exercise the wiring |
| Docker not installed / stack absent | App still opens; every stack-dependent control degrades to a disabled state with an explanation |
