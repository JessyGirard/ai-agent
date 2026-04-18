# Tool 1 public demo scenarios

Small **client-style** HTTP suites you can run through Tool 1 (Streamlit **API** surface or `tools/system_eval_runner.py`) against **public** endpoints. No private credentials.

| File | Intent |
|------|--------|
| `tool1_demo_public_smoke.json` | **PASS** — status, body substring, and response header checks (JSONPlaceholder). |
| `tool1_demo_public_validation_failures.json` | **FAIL** — wrong `expected_status` and impossible `body_contains` (readable assertion output). |
| `tool1_demo_public_headers_and_echo.json` | **PASS** — custom header and Bearer-style header echoed by httpbin. |

Assertions use the Tool 1 minimal keys: `expected_status`, `body_contains`, `header_contains` (see `core/system_eval.py`).

**Note:** Third-party hosts can rate-limit or change behavior; if a run fails unexpectedly, retry or adjust timeouts.
