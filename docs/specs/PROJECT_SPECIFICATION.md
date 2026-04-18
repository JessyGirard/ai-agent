# ai-agent — Project specification

**Purpose:** Single shareable inventory of the repository: what each file is for, how pieces connect, and how quality is guarded.  
**Scope:** Files present in the working tree as of generation; excludes git history and local-only folders (e.g. virtualenvs).

---

## 1. System overview

This project is a **local AI assistant / agent** built around:

- **Orchestration loop** (`playground.py`): top-level input flow, deterministic branch ordering, service wiring, LLM/tool call ordering.
- **Service modules**:
  - `services/memory_service.py` (memory normalization/scoring/retrieval/runtime-write)
  - `services/journal_service.py` (journal, outcome feedback, recent-answer context)
  - `services/routing_service.py` (action typing and control-path routing)
  - `services/prompt_builder.py` (answer-line shaping and prompt/message assembly)
- **Persistence layer** (`core/persistence.py`): file I/O for state, memory payload, journal, and archive.
- **LLM layer** (`core/llm.py`): Anthropic client, default tool-routing system prompt, preflight checks.
- **Config** (`config/settings.py`): `.env` loading, model name, max tokens, API key accessor.
- **Web fetch** (`tools/fetch_page.py`): Facade for **HTTP** fetch + HTML-to-text (`tools/fetch_http.py`, truncated) and optional **browser** mode when **`FETCH_MODE=browser`** (Playwright in `tools/fetch_browser.py`, public `http`/`https` only). Optional **`FETCH_BROWSER_TIMEOUT_SECONDS`** bounds browser navigation time. Failure lines may carry **`[fetch:tag]`** and (browser) a compact **`diag=`** suffix; see `docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`.
- **Streamlit UI** (`app/ui.py`): Chat-style front-end that calls `playground.handle_user_input`; includes **Assistant** and **Tool 1 — System eval (HTTP)** tabs. **Windows:** one-click launch via **`Launch-Agent-UI.cmd`** (see `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`).
- **Memory pipeline (offline)**: `raw_chat.txt` → `import_chat.py` → `imported.json` → OpenAI-based extractor → **`extracted_memory.json` (merge by default)** (`memory/import_chat.py`, `memory/extractors/run_extractor.py`). Optional env `EXTRACT_MESSAGE_LIMIT` (default 50, max 500). Extractor backs up the prior file to `memory/extracted_memory.pre_extract.json` before each write; `--replace` discards existing rows for a clean run.
- **Legacy simple history** (`memory/memory.py`): reads/writes `memory/history.json` (last 10 entries); parallel to the richer `extracted_memory.json` system.

---

## 2. Entry points

| Entry | Role |
|--------|------|
| `playground.py` (`main()`) | Interactive REPL/orchestrator: loads state, runs top-level flow, delegates to services. |
| `main.py` | Minimal placeholder (`print("Hello Jessy")`); not the agent entry. |
| `app/ui.py` | Streamlit app: session state, themed UI, invokes `playground.handle_user_input` (Assistant + Tool 1 tabs). |
| `Launch-Agent-UI.cmd` | **Windows:** starts Streamlit via **`.venv-win\Scripts\python.exe -m streamlit run app\ui.py`** from repo root (same venv convention as `Open-DevShell.cmd`). |
| `memory/import_chat.py` | CLI: `raw_chat.txt` → `imported.json` (one non-empty line per turn; alternates user/assistant; strips leading `USER:` / `AI:` / `ASSISTANT:` labels from content). |
| `memory/extractors/run_extractor.py` | CLI: `imported.json` → structured `extracted_memory.json` (OpenAI). **Merges** with existing `extracted_memory.json` on matching category+value keys; reinforces evidence. Server-side filters: noise list, no `?` in values, max value length. Writes `meta.last_extract` stats. |
| `tests/run_regression.py` | **Protected baseline** regression harness (see `README.md`). |

---

## 3. Dependencies

**Declared in `requirements.txt`:** `anthropic`, `python-dotenv`, `beautifulsoup4`, `streamlit`, `requests`, `openai` (covers `playground` / `fetch_page` / offline extractor paths). Pytest is optional for supplemental tests and is not pinned in this file.

**Environment:** `.env` (gitignored) for `ANTHROPIC_API_KEY`, optional `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS`; offline extractor expects `OPENAI_API_KEY`. Optional: `EXTRACT_MESSAGE_LIMIT` (integer; default 50, capped at 500 in code; limits how many `imported.json` messages are processed per extract run).

---

## 4. Testing and quality gate

Documented in `README.md`:

- Baseline: `python tests/run_regression.py`
- Quick stability gate: `python tests/run_soak.py --iterations 1000 --chunk-size 250 ...`
- Deep periodic gate: `python tests/run_soak.py --iterations 10000 --chunk-size 1000 ...`
- Pytest-based files may exist for supplemental checks; regression wins on conflict.
- GitHub Actions automation is now in:
  - `.github/workflows/ci.yml` (PR/push regression + quick soak)
  - `.github/workflows/nightly-soak.yml` (scheduled/manual 10k chunked soak)

Supplemental scripts (not the baseline gate):

- `test_playground_memory.py` — pytest-style memory unit tests (if `pytest` is installed).
- `test_openai.py`, `test_claude.py` — **live API smoke scripts** (network + keys); not equivalent to `run_regression.py`.

---

## 5. File inventory (by location)

### Repository root

| File | Description |
|------|-------------|
| `README.md` | Project tagline, **Testing Workflow**, fetch modes, Streamlit/Tool 1 notes, and short **offline memory import** steps (regression as protected baseline). |
| `Open-DevShell.cmd`, `op.cmd`, `go.cmd` | Windows dev shell entry (PowerShell + **`.venv-win`**). |
| `docs/handoffs/HANDOFF_RECENT_WORK.md` | Human-oriented summary of recent increments for pasting into other chats (not a runtime dependency). |
| `requirements.txt` | Pip dependencies for the main app, fetch tool, and offline extractor (see §3). |
| `playground.py` | Core orchestrator: command handling, deterministic branch ordering, service composition, LLM/tool invocation sequencing, and journaling hooks. |
| `main.py` | Trivial hello script; not primary entry. |
| `test_playground_memory.py` | Pytest-oriented tests for memory normalization / keys / transient identity (supplemental). |
| `test_openai.py` | Calls OpenAI Responses API; prints output (manual verification). |
| `test_claude.py` | Calls Anthropic Messages API; prints output (manual verification). |

### `config/`

| File | Description |
|------|-------------|
| `settings.py` | `load_dotenv`, `get_model_name`, `get_max_tokens`, `get_api_key` (Anthropic). |

### `core/`

| File | Description |
|------|-------------|
| `llm.py` | `llm_preflight_check`, `ask_ai` / `chat` via Anthropic; default system prompt teaches `TOOL:fetch <url>` pattern. |
| `persistence.py` | File I/O helpers for state/memory/journal load/save/append/archive paths. |
| `system_eval.py` | Phase 1 HTTP system-eval: suite validation, deterministic assertions, artifact-shaped results (isolated from `playground.py`). Supports **`steps`** scenarios, **`step_templates`** / **`use`**, **`{{variable}}`** substitution, **`step_results`** in JSON results, and per-step summaries in **`.md`** artifacts. |

### `services/`

| File | Description |
|------|-------------|
| `memory_service.py` | Memory-related runtime logic: tokenization, key canonicalization/dedupe, retrieval scoring/ranking, durable/personal context selection, runtime write conflict handling, and memory item updates. |
| `journal_service.py` | Journal and outcome-feedback logic: append/flush/compaction coordination, retrieval/formatting helpers, anti-repeat guard, recent-answer history helpers. |
| `routing_service.py` | Routing/control logic: action type detection, subtarget detection, strict-mode/override checks, vague research intent classification, and specific next-step selection. |
| `prompt_builder.py` | Prompt composition layer: post-fetch prompt build, answer-line construction, and full `build_messages` system/user prompt assembly. |

### `tools/`

| File | Description |
|------|-------------|
| `fetch_page.py` | `fetch_page(url)`: dispatches to **HTTP** or **browser** backend from env; returns extracted text or classified error string (**`[fetch:tag]`**); browser path may append **`diag=`** details. |
| `fetch_http.py` | HTTP implementation used by default fetch mode. |
| `fetch_browser.py` | Playwright/Chromium implementation when **`FETCH_MODE=browser`**; bounded navigation, extraction, and operator **`diag=`** diagnostics. |
| `system_eval_runner.py` | CLI: run JSON suites against real HTTP; writes `logs/system_eval` artifacts. |
| `tool1_verify_server.py` | Tiny local HTTP server for Tool 1 manual **PASS** checks (default port **37641**). |

### `app/`

| File | Description |
|------|-------------|
| `ui.py` | Streamlit UI: loads snippet of `memory/extracted_memory.json`, syncs `playground` state, quick prompts, formatted assistant messages, chat flow via `playground.handle_user_input`. |

### `tests/`

| File | Description |
|------|-------------|
| `run_regression.py` | Isolated temp files for memory/state/journal where needed; fakes `ask_ai` / `fetch_page` in places; broad scenario coverage (state, memory write/retrieval, journal/outcome flow, routing/strictness, prompt shaping, tool fetch + browser mocks, system_eval runner, extractor fixtures, error handling). **Current protected baseline: 297 scenarios. Exit code 1 if any test fails.** Confirm with `README.md` / latest `SESSION_SYNC_LOG.md` gate run if this drifts. |
| `run_soak.py` | Long-duration stability runner with progress checkpoints, chunked mode (`--chunk-size`), and synchronized per-run result/checkpoint/aggregate artifacts for reliable interrupted/long runs. |
| `fixtures/extractor_validation_cases.json` | Offline JSON cases consumed by regression to assert `run_extractor.validate_candidate` accept/reject behavior (no OpenAI call). |

### `memory/` — code

| File | Description |
|------|-------------|
| `import_chat.py` | Parses `raw_chat.txt` line-by-line into alternating user/assistant JSON messages → `imported.json`; strips `USER:` / `AI:` / `ASSISTANT:` prefixes from each line’s stored content. |
| `memory.py` | Legacy: load/save list to `history.json`, keeps last 10 items. |
| `extractors/run_extractor.py` | OpenAI-based batch extractor: reads `imported.json`, filters noise (plus **no question marks** and **max length** on stored values), assigns categories (`identity`, `goal`, `preference`, `project`), **merges** into `extracted_memory.json` (use `--replace` to wipe first). Writes `meta.last_extract` summary. |

### `memory/` — data / artifacts

| File | Description |
|------|-------------|
| `extracted_memory.json` | Primary structured memory store: `meta` + `memory_items[]` (ids, category, value, confidence, evidence, sources, etc.). Updated by extractor (merge) and by `playground` runtime. |
| `extracted_memory.pre_extract.json` | **Rotating** on-disk copy of `extracted_memory.json` immediately before each extractor write (overwrite each run). |
| `extracted_memory.json.bak` | Optional manual or script-created backup (not required by code). |
| `imported.json` | Intermediate chat transcript JSON for the extractor pipeline. |
| `raw_chat.txt` | Source text for `import_chat.py`. |
| `history.json` | Legacy rolling history used by `memory/memory.py`. |
| `current_state.json` | Persisted focus/stage (or related state) for the agent; used by `playground` state helpers. |
| `project_journal.jsonl` | Append-only JSON lines: conversation, tool flows, state commands, with timestamps and previews. |
| *(no `memory_schema.json` in tree at inventory time)* | If added later: document as optional schema reference for memory JSON. |

### Git / tooling (root)

| File | Description |
|------|-------------|
| `.gitignore` | Ignores venvs, `.env`, `__pycache__`, logs, local extractor backups (`extracted_memory.pre_extract.json`, `extracted_memory.json.bak`). |
| `.gitattributes` | Forces LF line endings for `*.json`. |
| `.github/workflows/ci.yml` | Automated PR/push quality gate: regression + quick chunked soak artifact upload. |
| `.github/workflows/nightly-soak.yml` | Automated nightly/manual long soak (10k chunked) artifact upload. |
| `.pytest_cache/` *(if present)* | Local pytest cache; not part of product behavior. |

---

## 6. Data flow (high level)

1. **Optional import:** `raw_chat.txt` → `import_chat.py` → `imported.json` → `run_extractor.py` → **`extracted_memory.json` merged** with prior rows (same category+value key reinforces evidence); `run_extractor.py --replace` starts from an empty in-memory map instead.
2. **Runtime:** User input → `playground.handle_user_input` (orchestration) → service-layer routing/memory/journal/prompt logic → LLM → optional `fetch_page` follow-up → journal append.
3. **UI:** Same handler as CLI, via Streamlit.

---

## 7. Known structural notes (non-blocking)

- Two memory mechanisms coexist: **`memory/memory.py` + `history.json`** vs **`extracted_memory.json` + service/runtime memory flow**. Intentional or legacy; worth documenting owner-of-truth per feature.
- Dependency versions are not pinned; add a lockfile or version caps when you formalize production installs.

---

## 8. How to share this document

This file is self-contained Markdown. Recipients can open it in any editor or render on GitHub/GitLab. Regenerate or extend the inventory when you add folders (e.g. `agents/`) or new memory schema files.

---

*End of specification.*
