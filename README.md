# ai-agent
The creation of a powerful friend and ally.

## Testing Workflow

- The protected baseline test suite is: `python tests/run_regression.py`
- Pytest-based tests are supplemental and can be run for additional coverage.
- Any code change must keep the regression suite passing before commit.
- If pytest and regression results differ, treat regression as the release gate and resolve the discrepancy before merge or push.

Live API smoke scripts (`test_openai.py`, `test_claude.py`) call the network and require keys. Run them only when you intend to: set `RUN_LIVE_API_TESTS=1` in the environment; otherwise they print a skip message and exit without calling the APIs.

## Offline memory import (optional)

From the repo root, with `OPENAI_API_KEY` in `.env`:

1. Put alternating user/assistant dialogue in `memory/raw_chat.txt` (one non-empty line per message; optional `USER:` / `AI:` prefixes are stripped by `memory/import_chat.py`).
2. `python memory/import_chat.py` → writes `memory/imported.json`.
3. `python memory/extractors/run_extractor.py` → **merges** new facts into `memory/extracted_memory.json` (use `--replace` to discard existing rows for that run only). A copy of the previous `extracted_memory.json` is saved as `memory/extracted_memory.pre_extract.json` before each write.

Optional: set `EXTRACT_MESSAGE_LIMIT` in `.env` to process more than the default 50 messages per extract (hard cap 500 in code). Full file layout and behavior are in `PROJECT_SPECIFICATION.md`.
