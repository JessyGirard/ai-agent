# ai-agent
The creation of a powerful friend and ally.

## Testing Workflow

- The protected baseline test suite is: `python tests/run_regression.py`
- Pytest-based tests are supplemental and can be run for additional coverage.
- Any code change must keep the regression suite passing before commit.
- If pytest and regression results differ, treat regression as the release gate and resolve the discrepancy before merge or push.

Live API smoke scripts (`test_openai.py`, `test_claude.py`) call the network and require keys. Run them only when you intend to: set `RUN_LIVE_API_TESTS=1` in the environment; otherwise they print a skip message and exit without calling the APIs.
