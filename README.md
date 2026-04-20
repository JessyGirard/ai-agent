# ai-agent
The creation of a powerful friend and ally.

## Build Status

- CI and nightly soak workflows are now included in `.github/workflows/`.
- After your first push, add repo badges here (Actions -> workflow -> `Create status badge`) so pass/fail is visible at a glance.
- Reliability evidence and acceptance criteria: `docs/reliability/RELIABILITY_EVIDENCE.md`

## Current Architecture

- `playground.py`: top-level orchestration and runtime flow (input handling, deterministic branch ordering, tool flow, service wiring)
- `core/llm.py`: Anthropic call path and preflight
- `core/persistence.py`: state/memory/journal file persistence helpers
- `services/memory_service.py`: memory normalization, scoring, retrieval, runtime write logic
- `services/journal_service.py`: project journal/outcome feedback/recent-answer history helpers
- `services/routing_service.py`: action typing and routing/control-path detection
- `services/prompt_builder.py`: prompt assembly + answer-line shaping
- `app/ui.py`: Streamlit frontend using the same `playground.handle_user_input` path. **Windows (Jessy / operators):** double-click **`Launch-Agent-UI.cmd`** at the repo root (uses **`.venv-win`** like `Open-DevShell.cmd`; default Streamlit port). For **fixed port 8501** (`http://localhost:8501`), run **`Start-Agent-Server.cmd`** when you want a visible console server. **Desktop/taskbar UI:** run **`Create-Agent-UI-Shortcut.ps1`** — the **`.lnk`** opens **only** Google Chrome with **`--app=http://localhost:8501`** (no `.cmd` from the shortcut; **LAUNCH-08**). Start Streamlit separately before opening the app window. See `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md` → *Pin to the taskbar*. **Re-run the shortcut script after pulls** and **re-pin** if the icon predates launcher changes. Use **`Launch-Agent-UI.cmd`** when you want the same visible terminal without forcing port 8501. **Any OS:** from repo root, `streamlit run app/ui.py` or `python -m streamlit run app/ui.py`. In the UI, select **API** (top bar or sidebar backup) to run `system_eval` suites without the terminal (same engine as `tools/system_eval_runner.py`). Relaunch details: `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md` → *Windows one-click launch*. **Agent → Speech to text:** uses optional **`streamlit-mic-recorder`** (install with `pip install -r requirements.txt`); Chrome/Edge + microphone permission; transcript is reviewed and sent explicitly, same as typed chat. **Open-and-go (Agent):** a new browser session already defaults to the **Agent** surface; the empty thread shows a short **Ready** line (local session, no extra UI “connect” step). Optional URL query **`?ui_surface=Agent`** (or **API**, **Prompt**, **Regression**, **Terminal**) is applied once then stripped so bookmarks can pin a surface.

## Project History

- High-level milestone timeline: `CHANGELOG.md`
- Reliability audit trail and reproducible gate evidence: `docs/reliability/RELIABILITY_EVIDENCE.md`
- Current build mission and execution sequence: `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md`
- External ChatGPT collaboration bootstrap/sync: `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

## Testing Workflow

- The protected baseline test suite is: `python tests/run_regression.py`
- Quick stability gate (recommended on every change): `python tests/run_soak.py --iterations 1000 --chunk-size 250 --progress-interval 125 --result-path "logs/test_runs/ci_soak_1000.json" --checkpoint-path "logs/test_runs/ci_soak_1000_checkpoint.json" --aggregate-path "logs/test_runs/ci_soak_1000_aggregate.json"`
- Deep periodic stability gate (recommended nightly): `python tests/run_soak.py --iterations 10000 --chunk-size 1000 --progress-interval 250 --result-path "logs/test_runs/nightly_soak_10000.json" --checkpoint-path "logs/test_runs/nightly_soak_10000_checkpoint.json" --aggregate-path "logs/test_runs/nightly_soak_10000_aggregate.json"`
- Chunked soak now auto-cleans per-chunk artifacts by default to reduce log clutter; use `--keep-chunk-artifacts` when you need every chunk file for debugging.
- Soak artifacts run in compact mode by default (keeps primary final artifact). Use `--keep-auxiliary-artifacts` to retain checkpoint/result companion files.
- Pytest-based tests are supplemental and can be run for additional coverage.
- Any code change must keep the regression suite passing before commit.
- If pytest and regression results differ, treat regression as the release gate and resolve the discrepancy before merge or push.
- Current baseline size after the latest hardening sequence: **`438`** regression scenarios (`python tests/run_regression.py`; confirm with `docs/handoffs/SESSION_SYNC_LOG.md` bottom after large merges).
- GitHub Actions automation:
  - `.github/workflows/ci.yml` runs regression + quick chunked soak on pull requests and pushes to `main`/`master`.
  - `.github/workflows/nightly-soak.yml` runs a scheduled 10k chunked soak and supports manual trigger (`workflow_dispatch`).

Live API smoke scripts (`test_openai.py`, `test_claude.py`) call the network and require keys. Run them only when you intend to: set `RUN_LIVE_API_TESTS=1` in the environment; otherwise they print a skip message and exit without calling the APIs.

## AI System Test Engineering (Phase 1)

- Operator runbook: `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`
- Runner: `python tools/system_eval_runner.py --suite "system_tests/suites/example_http_suite.json" --output-dir "logs/system_eval" --file-stem "local_eval_run"`
- Core implementation: `core/system_eval.py`
- **Tool 1 UI first pass:** `python tools/tool1_verify_server.py` (listens on `http://127.0.0.1:37641`), then `streamlit run app/ui.py` → surface **API** uses default suite `system_tests/suites/tool1_local_starter_suite.json` → expect **PASS** (details in runbook).
- Example suite template: `system_tests/suites/example_http_suite.json` (optional per-case `lane`: `stability` | `correctness` | `consistency`; `stability` → optional `stability_attempts` 1–50 (default 3); `consistency` → optional `repeat_count` 1–50 (default 3); repeated attempts must all pass the same assertions; outcomes in artifacts)
- **Scenario cases (`steps`):** correctness lane only — ordered **`steps`** with per-step **`name`**, **`method`**, **`url`**, optional **`headers`** / **`payload`**, and the same assertion / **`extract`** keys as single-request cases (flat on each step). Shared runtime **`variables`** from **`extract`**; reuse values in URLs / headers / payload with **`{{variable_name}}`**. Optional case-level **`step_templates`** and per-step **`use`** + overrides. Failures are prefixed with **`step failed`** and the step id. Case results include **`step_results`** (per-step PASS/FAIL, substituted URL, **`latency_ms`**, optional **`reason`**). **Markdown artifacts** include a compact **`### Steps`** subsection for operator visibility.
- **Legacy placeholder two-hop** (no **`steps`**): optional **`request_url_initial`**, **`payload_initial`**, **`headers_initial`** for a single case that uses **`{{...}}`** before variables exist; **`stability`** / **`consistency`** lanes reject request placeholders.
- **Tool 1 public demo suites** (JSONPlaceholder / httpbin, no credentials): `system_tests/suites/tool1_public_demo/` — see folder `README.md` and `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md` § *Public demo scenario pack*.
- **Playground fetch modes:** `tools/fetch_page.py` stays the facade. Default `FETCH_MODE` is **http** (`requests` + BeautifulSoup in `tools/fetch_http.py`). Set **`FETCH_MODE=browser`** to use headless Chromium via **Playwright** (`tools/fetch_browser.py`, public `http://` / `https://` only). Navigation uses a bounded **`commit` → `domcontentloaded` → `load`** goto ladder (each step gets an equal slice of the navigation timeout), then short post-goto readiness waits. Extraction prefers **`main` / `[role="main"]` / `article`** (first match each) when they yield more visible text than **`body`**, then one optional bounded scroll and a second extract pass if content is still thin. When structured **`h1` / `h2` / role=heading / scoped header+article headings** yield a stronger compact bundle than thin generic text, that headline line replaces the body slice (deterministic **` | `** join, capped) before merge with the page title. A final bounded **`page.evaluate`** pass walks **text nodes** under **`main` / `[role="main"]` / `body`** (skipping script/style) and may replace the body slice when that string wins the same length / thin-page rule—separate from **`inner_text`** headline collection. On **`browser_timeout`**, **`browser_error`**, and **`low_content`**, responses may end with a compact **` diag=…`** suffix (bounded DOM snapshot / **`exc=`** class / merge length; probe uses JSON + fallbacks including **`fb=1`** pipe / **`fb=2`** micro lengths, or **`st=1`** if every bounded **`evaluate`** path is unusable) for operators—**`[fetch:tag]`** names unchanged. **Token glossary:** `docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md` → section *Operator reference: `diag=` suffix*. Optional **`FETCH_BROWSER_TIMEOUT_SECONDS`** (integer, clamped **5–120**, default **20**) bounds that navigation budget for browser mode only. Install browser deps once: `pip install playwright` then `playwright install chromium`. Failures use the same `[fetch:tag]` pattern as HTTP mode.
- Artifacts written per run:
  - `logs/system_eval/<file_stem>.json` — full structured result (including **`step_results`** when a case used **`steps`**)
  - `logs/system_eval/<file_stem>.md` — human summary; multi-step cases include a **`### Steps`** block (PASS/FAIL, latency, URL, reason on failure)

## Offline memory import (optional)

From the repo root, with `OPENAI_API_KEY` in `.env`:

1. Put alternating user/assistant dialogue in `memory/raw_chat.txt` (one non-empty line per message; optional `USER:` / `AI:` prefixes are stripped by `memory/import_chat.py`).
2. `python memory/import_chat.py` → writes `memory/imported.json`.
3. `python memory/extractors/run_extractor.py` → **merges** new facts into `memory/extracted_memory.json` (use `--replace` to discard existing rows for that run only). A copy of the previous `extracted_memory.json` is saved as `memory/extracted_memory.pre_extract.json` before each write.

Optional: set `EXTRACT_MESSAGE_LIMIT` in `.env` to process more than the default 50 messages per extract (hard cap 500 in code). Full file layout and behavior are in `docs/specs/PROJECT_SPECIFICATION.md`. **Memory:** technical reference plus verbatim execution-plan archives live in `docs/specs/MEMORY_SYSTEM.md` (§14 memory-only plan, §15 pointer to two-lane plan). **Two-lane plan** (durable memory + operator input UX — paste, mic): `docs/specs/UX_system.md`.

## Recent behavior updates

- Completed structural stabilization extraction sequence with regression parity preserved:
  - persistence helpers -> `core/persistence.py`
  - journal/outcome-feedback helpers -> `services/journal_service.py`
  - memory scoring/retrieval/write helpers -> `services/memory_service.py`
  - routing/control-path logic -> `services/routing_service.py`
  - prompt/answer assembly -> `services/prompt_builder.py`
- `playground.py` is now focused on orchestration and is substantially smaller than before the extraction sequence.
