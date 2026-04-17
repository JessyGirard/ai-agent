# ai-agent
The creation of a powerful friend and ally.

## Build Status

- CI and nightly soak workflows are now included in `.github/workflows/`.
- After your first push, add repo badges here (Actions -> workflow -> `Create status badge`) so pass/fail is visible at a glance.
- Reliability evidence and acceptance criteria: `RELIABILITY_EVIDENCE.md`

## Current Architecture

- `playground.py`: top-level orchestration and runtime flow (input handling, deterministic branch ordering, tool flow, service wiring)
- `core/llm.py`: Anthropic call path and preflight
- `core/persistence.py`: state/memory/journal file persistence helpers
- `services/memory_service.py`: memory normalization, scoring, retrieval, runtime write logic
- `services/journal_service.py`: project journal/outcome feedback/recent-answer history helpers
- `services/routing_service.py`: action typing and routing/control-path detection
- `services/prompt_builder.py`: prompt assembly + answer-line shaping
- `app/ui.py`: Streamlit frontend using the same `playground.handle_user_input` path

## Project History

- High-level milestone timeline: `CHANGELOG.md`
- Reliability audit trail and reproducible gate evidence: `RELIABILITY_EVIDENCE.md`
- Current build mission and execution sequence: `TEST_ENGINEERING_ROADMAP.md`
- External ChatGPT collaboration bootstrap/sync: `CHATGPT_COLLAB_SYNC.md`

## Testing Workflow

- The protected baseline test suite is: `python tests/run_regression.py`
- Quick stability gate (recommended on every change): `python tests/run_soak.py --iterations 1000 --chunk-size 250 --progress-interval 125 --result-path "logs/test_runs/ci_soak_1000.json" --checkpoint-path "logs/test_runs/ci_soak_1000_checkpoint.json" --aggregate-path "logs/test_runs/ci_soak_1000_aggregate.json"`
- Deep periodic stability gate (recommended nightly): `python tests/run_soak.py --iterations 10000 --chunk-size 1000 --progress-interval 250 --result-path "logs/test_runs/nightly_soak_10000.json" --checkpoint-path "logs/test_runs/nightly_soak_10000_checkpoint.json" --aggregate-path "logs/test_runs/nightly_soak_10000_aggregate.json"`
- Chunked soak now auto-cleans per-chunk artifacts by default to reduce log clutter; use `--keep-chunk-artifacts` when you need every chunk file for debugging.
- Soak artifacts run in compact mode by default (keeps primary final artifact). Use `--keep-auxiliary-artifacts` to retain checkpoint/result companion files.
- Pytest-based tests are supplemental and can be run for additional coverage.
- Any code change must keep the regression suite passing before commit.
- If pytest and regression results differ, treat regression as the release gate and resolve the discrepancy before merge or push.
- Current baseline size after the latest hardening sequence: `173` regression scenarios.
- GitHub Actions automation:
  - `.github/workflows/ci.yml` runs regression + quick chunked soak on pull requests and pushes to `main`/`master`.
  - `.github/workflows/nightly-soak.yml` runs a scheduled 10k chunked soak and supports manual trigger (`workflow_dispatch`).

Live API smoke scripts (`test_openai.py`, `test_claude.py`) call the network and require keys. Run them only when you intend to: set `RUN_LIVE_API_TESTS=1` in the environment; otherwise they print a skip message and exit without calling the APIs.

## AI System Test Engineering (Phase 1)

- Runner: `python tools/system_eval_runner.py --suite "system_tests/suites/example_http_suite.json" --output-dir "logs/system_eval" --file-stem "local_eval_run"`
- Core implementation: `core/system_eval.py`
- Example suite template: `system_tests/suites/example_http_suite.json`
- Artifacts written per run:
  - `logs/system_eval/<file_stem>.json`
  - `logs/system_eval/<file_stem>.md`

## Offline memory import (optional)

From the repo root, with `OPENAI_API_KEY` in `.env`:

1. Put alternating user/assistant dialogue in `memory/raw_chat.txt` (one non-empty line per message; optional `USER:` / `AI:` prefixes are stripped by `memory/import_chat.py`).
2. `python memory/import_chat.py` → writes `memory/imported.json`.
3. `python memory/extractors/run_extractor.py` → **merges** new facts into `memory/extracted_memory.json` (use `--replace` to discard existing rows for that run only). A copy of the previous `extracted_memory.json` is saved as `memory/extracted_memory.pre_extract.json` before each write.

Optional: set `EXTRACT_MESSAGE_LIMIT` in `.env` to process more than the default 50 messages per extract (hard cap 500 in code). Full file layout and behavior are in `PROJECT_SPECIFICATION.md`.

## Recent behavior updates

- Completed structural stabilization extraction sequence with regression parity preserved:
  - persistence helpers -> `core/persistence.py`
  - journal/outcome-feedback helpers -> `services/journal_service.py`
  - memory scoring/retrieval/write helpers -> `services/memory_service.py`
  - routing/control-path logic -> `services/routing_service.py`
  - prompt/answer assembly -> `services/prompt_builder.py`
- `playground.py` is now focused on orchestration and is substantially smaller than before the extraction sequence.
