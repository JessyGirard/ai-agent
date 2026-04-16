# ai-agent — Project specification

**Purpose:** Single shareable inventory of the repository: what each file is for, how pieces connect, and how quality is guarded.  
**Scope:** Files present in the working tree as of generation; excludes git history and local-only folders (e.g. virtualenvs).

---

## 1. System overview

This project is a **local AI assistant / agent** built around:

- **CLI loop** (`playground.py`): state commands, journaling, optional web fetch via tools, Anthropic chat, and a JSON-backed **memory store** with runtime extraction and deduplication.
- **LLM layer** (`core/llm.py`): Anthropic client, default tool-routing system prompt, preflight checks.
- **Config** (`config/settings.py`): `.env` loading, model name, max tokens, API key accessor.
- **Web tool** (`tools/fetch_page.py`): HTTP fetch + HTML-to-text (truncated).
- **Streamlit UI** (`app/ui.py`): Chat-style front-end that calls `playground.handle_user_input`.
- **Memory pipeline (offline)**: raw chat → `imported.json` → OpenAI-based extractor → `extracted_memory.json` (`memory/import_chat.py`, `memory/extractors/run_extractor.py`).
- **Legacy simple history** (`memory/memory.py`): reads/writes `memory/history.json` (last 10 entries); parallel to the richer `extracted_memory.json` system.

---

## 2. Entry points

| Entry | Role |
|--------|------|
| `playground.py` (`main()`) | Interactive REPL: loads state, optional LLM preflight warnings, `handle_user_input` loop. |
| `main.py` | Minimal placeholder (`print("Hello Jessy")`); not the agent entry. |
| `app/ui.py` | Streamlit app: session state, themed UI, invokes `playground.handle_user_input`. |
| `memory/import_chat.py` | CLI: `raw_chat.txt` → `imported.json`. |
| `memory/extractors/run_extractor.py` | CLI: `imported.json` → structured `extracted_memory.json` (OpenAI). |
| `tests/run_regression.py` | **Protected baseline** regression harness (see `README.md`). |

---

## 3. Dependencies

**Declared in `requirements.txt`:** `anthropic`, `python-dotenv`, `beautifulsoup4`, `streamlit`.

**Used by code but not listed in `requirements.txt` (gap):** `requests` (used by `tools/fetch_page.py`), `openai` (used by `memory/extractors/run_extractor.py`). Install as needed for those paths.

**Environment:** `.env` (gitignored) for `ANTHROPIC_API_KEY`, optional `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS`; extractor expects `OPENAI_API_KEY`.

---

## 4. Testing and quality gate

Documented in `README.md`:

- Baseline: `python tests/run_regression.py`
- Pytest-based files may exist for supplemental checks; regression wins on conflict.

Supplemental scripts (not the baseline gate):

- `test_playground_memory.py` — pytest-style memory unit tests (if `pytest` is installed).
- `test_openai.py`, `test_claude.py` — **live API smoke scripts** (network + keys); not equivalent to `run_regression.py`.

---

## 5. File inventory (by location)

### Repository root

| File | Description |
|------|-------------|
| `README.md` | Project tagline + **Testing Workflow** (regression as protected baseline). |
| `requirements.txt` | Pip dependencies (partial vs full codebase; see §3). |
| `playground.py` | Core agent: state load/save, project journal (append, flush, archive, compaction), memory load/save, retrieval/scoring, runtime memory extraction/write with normalization (`normalize_memory_display_value`, `canonicalize_memory_key_value`, dedupe on load), routing and prompts, `handle_user_input` orchestration (commands → memory write → LLM → optional fetch tool loop → journal). |
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

### `tools/`

| File | Description |
|------|-------------|
| `fetch_page.py` | `fetch_page(url)`: GET, BeautifulSoup text extraction, strip scripts/styles, cap length, error string on failure. |

### `app/`

| File | Description |
|------|-------------|
| `ui.py` | Streamlit UI: loads snippet of `memory/extracted_memory.json`, syncs `playground` state, quick prompts, formatted assistant messages, chat flow via `playground.handle_user_input`. |

### `tests/`

| File | Description |
|------|-------------|
| `run_regression.py` | Isolated temp files for memory/state/journal where needed; fakes `ask_ai` / `fetch_page` in places; full list of scenario tests (state, memory write, journal, tool fetch, LLM errors, memory key canonicalization, identity edge cases, etc.). **Exit code 1 if any test fails.** |

### `memory/` — code

| File | Description |
|------|-------------|
| `import_chat.py` | Parses `raw_chat.txt` line-by-line into alternating user/assistant JSON messages → `imported.json`. |
| `memory.py` | Legacy: load/save list to `history.json`, keeps last 10 items. |
| `extractors/run_extractor.py` | OpenAI-based batch extractor: reads `imported.json`, filters noise, assigns categories (`identity`, `goal`, `preference`, `project`), writes `extracted_memory.json` with schema metadata and `memory_items`. |

### `memory/` — data / artifacts

| File | Description |
|------|-------------|
| `extracted_memory.json` | Primary structured memory store: `meta` + `memory_items[]` (ids, category, value, confidence, evidence, sources, etc.). Updated by extractor and by `playground` runtime. |
| `extracted_memory.backup.20260416_115434.json` | Point-in-time backup of extracted memory (safety copy). |
| `imported.json` | Intermediate chat transcript JSON for the extractor pipeline. |
| `raw_chat.txt` | Source text for `import_chat.py`. |
| `history.json` | Legacy rolling history used by `memory/memory.py`. |
| `current_state.json` | Persisted focus/stage (or related state) for the agent; used by `playground` state helpers. |
| `project_journal.jsonl` | Append-only JSON lines: conversation, tool flows, state commands, with timestamps and previews. |
| *(no `memory_schema.json` in tree at inventory time)* | If added later: document as optional schema reference for memory JSON. |

### Git / tooling (root)

| File | Description |
|------|-------------|
| `.gitignore` | Ignores venvs, `.env`, `__pycache__`, logs. |
| `.gitattributes` | Forces LF line endings for `*.json`. |
| `.pytest_cache/` *(if present)* | Local pytest cache; not part of product behavior. |

---

## 6. Data flow (high level)

1. **Optional import:** `raw_chat.txt` → `import_chat.py` → `imported.json` → `run_extractor.py` → `extracted_memory.json`.
2. **Runtime:** User input → `playground.handle_user_input` → state commands / journal / runtime memory merge → LLM → optional `fetch_page` follow-up → journal append.
3. **UI:** Same handler as CLI, via Streamlit.

---

## 7. Known structural notes (non-blocking)

- Two memory mechanisms coexist: **`memory/memory.py` + `history.json`** vs **`extracted_memory.json` + playground runtime**. Intentional or legacy; worth documenting owner-of-truth per feature.
- `requirements.txt` is not a complete lockfile for all import paths; tighten when you formalize installs.

---

## 8. How to share this document

This file is self-contained Markdown. Recipients can open it in any editor or render on GitHub/GitLab. Regenerate or extend the inventory when you add folders (e.g. `agents/`) or new memory schema files.

---

*End of specification.*
