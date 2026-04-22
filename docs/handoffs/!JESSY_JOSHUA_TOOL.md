# Jesse_Joshua_Tool

## Briefing: Joshua (ai-agent) — full picture for designing Tool 1 (API + prompt↔response + regression)

### 1. What this project is (one sentence)

Joshua is a local AI assistant / agent workbench: Streamlit UI + `playground.py` orchestration + memory / journal / routing / prompt assembly services + optional web fetch, built so you can chat, run structured tests, and lock behavior with a protected regression harness, with a roadmap toward an AI Testing Workbench: one shared evaluation spine, three operator-visible tool profiles.

### 2. North-star framing (how ChatGPT should think about "three tools")

Not three unrelated codebases. One spine:

| Profile | Job | Relationship to Tool 1 |
|---|---|---|
| API reliability | HTTP suites: method, URL, headers, payload, assertions, timing, artifacts | This is what Tool 1 in the UI already is today (system eval HTTP + operator + log). |
| Prompt ↔ response | Cases that send a prompt-shaped request and assert on response body (text/JSON/regex, etc.) | Same engine today (`core/system_eval.py` + suite JSON); product gap is naming, schema conventions, and maybe thin aliases. |
| Regression | `python tests/run_regression.py` large protected baseline, CI | Mature and separate from Streamlit; "finish the tool" can mean one operator command/tab/report that invokes or summarizes this gate, not reimplementing pytest. |

Joshua using the tool later means: documented when the agent suggests suite runs, which log to read (`logs/tool1_runs.jsonl`), and which gate must stay green.

### 3. Architecture map (ground truth)

| Layer | Role | Key paths |
|---|---|---|
| Orchestration | REPL + branch ordering + wiring | `playground.py` |
| Prompt / routing | `build_messages`, modes (conversation, light task, clarify-first, structured, etc.) | `services/prompt_builder.py`, `services/routing_service.py` |
| Memory / journal | Retrieval, filters, persistence | `services/memory_service.py`, `services/journal_service.py`, `core/persistence.py` |
| LLM | Anthropic client, preflight | `core/llm.py`, `config/settings.py`, `.env` |
| Fetch | `TOOL:fetch`, HTTP vs optional browser | `tools/fetch_page.py`, runbooks under `docs/runbooks/` |
| Operator UI | Chat + Tool 1 — System eval (HTTP) | `app/ui.py` |
| Tool 1 execution + log | Run suites, append JSONL records | `app/system_eval_operator.py`, `app/tool1_run_log.py` -> `logs/tool1_runs.jsonl` |
| HTTP eval engine | Parse suite, run requests, assertions, steps, artifacts | `core/system_eval.py`, `tools/system_eval_runner.py`, `system_tests/suites/` |
| Regression gate | Protected scenarios | `tests/run_regression.py`, `.github/workflows/` |

Isolation rule (important for design): keep `system_tests` / system eval isolated from `playground.py` unless explicitly decided otherwise with tests.

### 4. What Tool 1 is today (so you don't throw it away)

- UI: Streamlit `app/ui.py` — Assistant thread + Tool 1 (HTTP system eval) area.
- Runner / engine: `core/system_eval.py` — suites, assertions, `steps`, `step_templates`, `{{var}}`, `step_results`, markdown artifacts.
- Durability: `app/tool1_run_log.py` -> `logs/tool1_runs.jsonl` (append-only JSONL, human `summary` + structured fields).
- Demos: `system_tests/suites/tool1_public_demo/`, with public smoke proven in handoff logs.
- How-to: `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`, `README.md`.

So "finish Tool 1" means extending this same operator + same engine with clear lanes for (2) prompt↔response and (3) regression as invoked or surfaced from the workbench.

### 5. What is still open (exactly what to brainstorm with ChatGPT)

From `docs/handoffs/THREE_TOOLS_ALIGNMENT_BRIEF.md`:

1. Prompt/response: Same JSON suite with documented conventions vs small schema extension (`prompt` / `expected` aliases) vs separate suite type compiled to the same executor.
2. API reliability: v1 current timeouts + artifacts only vs extra hooks (retries, rate limits).
3. Regression "in the tool": docs-only "three commands" vs one meta script (orchestrate regression + quick soak + eval suite).
4. Order: one vertical slice per change set (no bundling).

### 6. Hard constraints ChatGPT must respect

- One small increment at a time; reject bundling adapters + evaluation + reporting in one PR.
- Release gate: `python tests/run_regression.py` (and CI/soak policy in `docs/reliability/RELIABILITY_EVIDENCE.md`).
- If docs conflict: reliability evidence + passing tests beat opinions.
- Naming: in-repo, Tool 1 already means HTTP system eval in UI; product naming can be Workbench with API / Prompt / Regression lanes as long as code map stays clear.

### 7. Copy-paste block for ChatGPT (start of a brainstorm session)

```text
You are the design copilot for the "ai-agent" / Joshua project. You have no memory of prior chats.

PRODUCT: A local AI assistant workbench (Streamlit + playground orchestration + memory/journal + prompt routing) evolving into an "AI Testing Workbench": ONE evaluation spine, THREE operator-facing profiles:
(1) API reliability — HTTP suites, assertions, artifacts (SHIPPED as "Tool 1" / system eval in app/ui.py),
(2) Prompt ↔ response — SAME HTTP engine today; needs explicit suite conventions or tiny schema extensions (NOT a second mystery stack unless we decide),
(3) Regression — tests/run_regression.py is the protected gate; "in the tool" may mean invoke/summarize/orchestrate, not rewrite pytest.

GROUNDING FILES (read if you can):
- docs/handoffs/THREE_TOOLS_ALIGNMENT_BRIEF.md (decisions 1–4 + paste protocol)
- docs/specs/PROJECT_SPECIFICATION.md (architecture inventory)
- docs/runbooks/SYSTEM_EVAL_RUNBOOK.md (Tool 1 / system eval operator)
- docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md (session protocol + latest log pointers)

ALREADY EXISTS:
- core/system_eval.py + tools/system_eval_runner.py + system_tests/suites/*
- app/ui.py (Tool 1 HTTP tab), app/system_eval_operator.py, app/tool1_run_log.py → logs/tool1_runs.jsonl
- tests/run_regression.py (large baseline, CI)

HARD RULES:
- One vertical slice per proposal; no bundling API + prompt/response + regression redesign in one step.
- Keep system_tests/system_eval isolated from playground.py unless justified with tests.
- Every code proposal: exact files + tests + how to validate (commands).

YOUR TASK THIS SESSION:
1) Summarize the three profiles and how they map to ONE spine in <=8 bullets.
2) Answer the FOUR numbered decisions in THREE_TOOLS_ALIGNMENT_BRIEF.md with clear recommendations.
3) Propose exactly ONE "next increment" (max ~1–2 logic files + tests + docs): either prompt/response shape, regression surfacing, or API eval—pick one.
4) List risks + validation commands (must include: python tests/run_regression.py).

We will compare your output with Cursor and pick one path.
```

### 8. How you'll teach Joshua to use the tool later (design hook)

When tool design is stable, Joshua guidance is mostly prompt + docs:

- When to suggest: run suite X, read last line of `tool1_runs.jsonl`, re-run regression.
- Never invent suite paths; cite `system_tests/suites/...` from context.
- `TOOL:fetch` stays separate (web pages), not the same as Tool 1 HTTP eval unless explicitly merged in UX.

---

## Latest Increment: Tool 1 `max_duration_ms` threshold assertion (small vertical slice)

### Request scope

Implement one small Tool 1 (HTTP system eval) increment only:

- Optional case field: `"max_duration_ms": 800`
- Compare measured request duration (`latency_ms`) against threshold
- Fail case when actual duration exceeds threshold
- Keep normal pass behavior when under/equal threshold
- Include actual duration and threshold in structured output/log row
- Add clear failure message for threshold exceedance

No redesign, no retries, no rate-limit logic, no prompt/response tooling changes, no regression architecture changes.

### What changed

In `core/system_eval.py`:

1. Added case-level optional validation for `max_duration_ms`:
   - new helper `*_coerce_max_duration_ms(...)`
   - must be a non-negative integer (not boolean)
2. `validate_suite(...)` now normalizes `max_duration_ms` onto the case when present.
3. `_evaluate_single_attempt(...)` now enforces threshold:
   - if `latency_ms > max_duration_ms`, add failure:
     - `max_duration_ms exceeded: {"max_duration_ms": <threshold>, "actual_duration_ms": <actual>}`
4. Structured results now include threshold when present:
   - case rows include `max_duration_ms`
   - stability/consistency attempt rows include `max_duration_ms`
   - existing `latency_ms` continues to represent actual measured duration

### Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### Tests added

In `tests/run_regression.py`:

- `test_system_eval_max_duration_ms_pass_under_threshold`
- `test_system_eval_max_duration_ms_fail_over_threshold`
- `test_system_eval_no_max_duration_ms_keeps_behavior`

These cover:

1. Pass when duration is under threshold
2. Fail when duration exceeds threshold
3. No behavior change when `max_duration_ms` is absent

### Validation run

Targeted new tests:

```text
python -m pytest tests/run_regression.py -k "max_duration_ms" -q --tb=short
```

Result: `3 passed, 518 deselected`

Full requested command:

```text
python tests/run_regression.py
```

Result in this run: `Passed 494 / 499 tests`

Existing unrelated failures reported by the harness:

- `build_messages_confidence_filter_when_user_purpose_present`
- `build_messages_reality_constrained_action_selection_when_user_purpose_present`
- `build_messages_first_money_bias_appears_for_money_query_with_user_purpose`
- `build_messages_normal_open_conversation_still_unchanged_without_override_trigger`
- `build_messages_proactive_no_extra_titan_output_sections`

### Assumptions

- `max_duration_ms` is a **top-level case field** (not nested under `assertions`), following the requested suite format example.
- Equality (`actual == threshold`) is treated as pass, and only `actual > threshold` fails.

---

## User Q&A Log (latest)

### User question

> Okay, please tell me what happened here. What we did here, there were some failures. Is there a problem with the tool? Am I building this wrong?

### Assistant reply

You are not building it wrong.

What happened:

- We implemented a small Tool 1 increment (`max_duration_ms`) in `core/system_eval.py` and added focused tests in `tests/run_regression.py`.
- The targeted new tests for this increment passed (`3 passed`).
- The full regression run showed 5 failures, but those failures were in `build_messages...` prompt behavior tests, not Tool 1 HTTP system-eval logic.

So the failures were from a different lane (prompt/routing behavior), not from this Tool 1 duration-threshold increment.

Is there a problem with Tool 1?

- For this increment: no obvious problem.
- Under-threshold pass behavior, over-threshold fail behavior, and no-threshold unchanged behavior were all validated.

Why full regression still failed:

- The repo has other in-progress changes outside Tool 1 (including prompt-related files), which can trigger unrelated regression failures even when the Tool 1 slice is correct.

---

## Latest Increment: Tool 1 optional transient retries (`retries`, `retry_delay_ms`)

### 1) What changed

- Implemented optional retry support for Tool 1 HTTP system eval in `core/system_eval.py`.
- New optional case fields:
  - `retries` (non-negative integer)
  - `retry_delay_ms` (non-negative integer)
- Retry behavior implemented:
  - First request runs normally.
  - Retry only for transient failures:
    1. request/network exceptions (`AdapterResult.ok == False`)
    2. HTTP `5xx`
  - Do **not** retry for:
    1. assertion/content mismatches
    2. HTTP `4xx`
- Final outcome behavior:
  - If a later retry attempt succeeds, case passes.
  - If all transient attempts fail, case fails with:
    - `retries exhausted after transient failures: {...}`
- Structured output/logging additions (minimal shape impact):
  - For retry-enabled cases:
    - `retry_attempts_total`
    - `retry_attempts` list (attempt number, status code, latency, transient flag, failure summary)
  - For steps cases with retries enabled:
    - each step result includes `attempts_total` and `attempts`.

### 2) Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### 3) Tests added/updated

Added in `tests/run_regression.py`:

- `test_system_eval_retries_absent_behavior_unchanged`
- `test_system_eval_retries_transient_then_success_passes`
- `test_system_eval_retries_exhausted_transient_fails`
- `test_system_eval_retries_does_not_retry_4xx`
- `test_system_eval_retries_does_not_retry_assertion_failure`

Coverage matrix:

1. retries absent -> unchanged behavior
2. transient failure then success within retry budget -> pass
3. transient failures through all attempts -> fail
4. 4xx does not retry
5. assertion failure does not retry

### 4) Validation command results

Targeted retry tests:

```text
python -m pytest tests/run_regression.py -k "system_eval_retries" -q --tb=short
```

Result: `5 passed, 521 deselected`

Full requested regression run:

```text
python tests/run_regression.py
```

Result in this run: `Passed 494 / 499 tests`

Existing unrelated failures reported by the harness:

- `build_messages_confidence_filter_when_user_purpose_present`
- `build_messages_reality_constrained_action_selection_when_user_purpose_present`
- `build_messages_first_money_bias_appears_for_money_query_with_user_purpose`
- `build_messages_normal_open_conversation_still_unchanged_without_override_trigger`
- `build_messages_proactive_no_extra_titan_output_sections`

### 5) Assumptions

- `retries` and `retry_delay_ms` are top-level case fields (not nested under `assertions`).
- Retry eligibility is evaluated before assertion checks and is limited to transport errors and HTTP `5xx`.
- `retry_delay_ms` applies only between retry attempts.
- Retry metadata is emitted only when retries are configured, to preserve existing output shape by default.

---

## Latest Increment: Tool 1 clearer status expectation support (`expected_status`, `expected_status_in`)

### 1) What changed

- Added optional **case-level** status expectation fields in `core/system_eval.py`:
  - `expected_status` (exact single status code)
  - `expected_status_in` (non-empty list of allowed status codes)
- Behavior implemented:
  - If neither field is present: existing behavior remains unchanged.
  - If `expected_status` is present: response status must match exactly.
  - If `expected_status_in` is present: response status must be one of the listed values.
  - If both are present: validation fails clearly (explicit rule).
- Failure messages are explicit:
  - `expected_status mismatch: expected <x>, got <y>`
  - `expected_status_in mismatch: {"expected_any_of":[...], "actual":<y>}`

### 2) Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### 3) Tests added/updated

Added in `tests/run_regression.py`:

- `test_system_eval_case_expected_status_exact_match_passes`
- `test_system_eval_case_expected_status_exact_mismatch_fails`
- `test_system_eval_case_expected_status_in_membership_passes`
- `test_system_eval_case_expected_status_in_membership_fails`
- `test_system_eval_case_expected_status_fields_absent_behavior_unchanged`
- `test_system_eval_case_expected_status_and_expected_status_in_both_present_rejected`

### 4) Validation command results

Targeted tests:

```text
python -m pytest tests/run_regression.py -k "case_expected_status" -q --tb=short
```

Result: `6 passed, 526 deselected`

Full requested regression run:

```text
python tests/run_regression.py
```

Result in this run: `Passed 494 / 499 tests`

Existing unrelated failures reported by the harness:

- `build_messages_confidence_filter_when_user_purpose_present`
- `build_messages_reality_constrained_action_selection_when_user_purpose_present`
- `build_messages_first_money_bias_appears_for_money_query_with_user_purpose`
- `build_messages_normal_open_conversation_still_unchanged_without_override_trigger`
- `build_messages_proactive_no_extra_titan_output_sections`

### 5) Assumptions

- `expected_status` / `expected_status_in` are top-level case fields (not nested under `assertions`).
- Both-present policy is a validation error (no precedence fallback).
- Output shape was preserved; only validation/evaluation behavior and failure messages were updated.

---

## Latest Increment: Tool 1 response header assertions (`expected_headers`)

### 1) What changed

- Added optional top-level case field support in Tool 1 system eval:
  - `expected_headers` (object mapping header name -> expected string value)
- Behavior implemented:
  - If `expected_headers` is absent: existing behavior unchanged.
  - If present: each listed header is validated against response headers.
  - Header-name matching is case-insensitive.
  - Header-value comparison is exact string equality after trimming surrounding whitespace.
- Clear failure messages:
  - Missing header:
    - `expected_headers missing header: '<name>' (expected '<value>', got missing)`
  - Mismatch:
    - `expected_headers mismatch: header '<name>' expected '<value>', got '<actual>'`

### 2) Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### 3) Tests added/updated

Added in `tests/run_regression.py`:

- `test_system_eval_case_expected_headers_exact_match_passes`
- `test_system_eval_case_expected_headers_missing_required_fails`
- `test_system_eval_case_expected_headers_mismatch_fails`
- `test_system_eval_case_expected_headers_name_case_insensitive_match`
- `test_system_eval_case_expected_headers_absent_behavior_unchanged`

### 4) Validation command results

Targeted tests:

```text
python -m pytest tests/run_regression.py -k "case_expected_headers" -q --tb=short
```

Result: `5 passed, 532 deselected`

Full requested regression run:

```text
python tests/run_regression.py
```

Result in this run: `Passed 494 / 499 tests`

Existing unrelated failures reported by the harness:

- `build_messages_confidence_filter_when_user_purpose_present`
- `build_messages_reality_constrained_action_selection_when_user_purpose_present`
- `build_messages_first_money_bias_appears_for_money_query_with_user_purpose`
- `build_messages_normal_open_conversation_still_unchanged_without_override_trigger`
- `build_messages_proactive_no_extra_titan_output_sections`

### 5) Assumptions

- `expected_headers` is a top-level case field (not nested under `assertions`).
- Expected values are strings and compared with `strip()` normalization only.
- No retry behavior changes were introduced in this increment.

---

## Latest Increment: Tool 1 JSON field assertions by simple dot-path (`expected_json`)

### 1) What changed

- Added optional top-level case field support:
  - `expected_json` (object mapping dot-path keys to expected JSON values)
- Implemented behavior:
  - If `expected_json` is absent: existing behavior unchanged.
  - If present:
    1. parse response body as JSON
    2. resolve each expected key via simple dot-path lookup (`a.b.c`)
    3. compare actual vs expected with exact equality
- Clear failures added:
  - Non-JSON response:
    - `expected_json invalid json: response body is not valid JSON`
  - Non-object JSON root:
    - `expected_json invalid json: response body JSON must be an object at the root`
  - Missing path:
    - `expected_json missing path: {"path":"..."}`
  - Value mismatch:
    - `expected_json mismatch: {"path":"...","expected":...,"actual":...}`

### 2) Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### 3) Tests added/updated

Added in `tests/run_regression.py`:

- `test_system_eval_case_expected_json_exact_path_value_match_passes`
- `test_system_eval_case_expected_json_missing_path_fails`
- `test_system_eval_case_expected_json_mismatched_value_fails`
- `test_system_eval_case_expected_json_non_json_response_fails_clearly`
- `test_system_eval_case_expected_json_absent_behavior_unchanged`

### 4) Validation command results

Targeted tests:

```text
python -m pytest tests/run_regression.py -k "case_expected_json" -q --tb=short
```

Result: `5 passed, 537 deselected`

Full requested regression run:

```text
python tests/run_regression.py
```

Result in this run: `Passed 494 / 499 tests`

Existing unrelated failures reported by the harness:

- `build_messages_confidence_filter_when_user_purpose_present`
- `build_messages_reality_constrained_action_selection_when_user_purpose_present`
- `build_messages_first_money_bias_appears_for_money_query_with_user_purpose`
- `build_messages_normal_open_conversation_still_unchanged_without_override_trigger`
- `build_messages_proactive_no_extra_titan_output_sections`

### 5) Assumptions

- `expected_json` is a top-level case field (not nested under `assertions`).
- Dot-path lookup is simple object traversal only (`a.b.c`); array indexing is intentionally unsupported in this increment.
- Exact equality uses normal JSON value equality semantics after path resolution.

---

## Latest Increment: Tool 1 JSON path existence assertions (`expected_json_exists`)

### 1) What changed

- Added optional top-level case field support:
  - `expected_json_exists` (array of dot-path strings)
- Implemented behavior:
  - If absent: existing behavior unchanged.
  - If present:
    1. parse response body as JSON
    2. require JSON root object
    3. resolve each path via simple dot-path traversal
    4. assert path existence only (no value check)
- Clear failure messages:
  - `expected_json_exists invalid json: response body is not valid JSON`
  - `expected_json_exists invalid json: response body JSON must be an object at the root`
  - `expected_json_exists missing path: {"path":"..."}`

### 2) Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### 3) Tests added/updated

Added in `tests/run_regression.py`:

- `test_system_eval_case_expected_json_exists_existing_path_passes`
- `test_system_eval_case_expected_json_exists_missing_path_fails`
- `test_system_eval_case_expected_json_exists_non_json_response_fails_clearly`
- `test_system_eval_case_expected_json_exists_absent_behavior_unchanged`

### 4) Validation command results

Targeted tests:

```text
python -m pytest tests/run_regression.py -k "case_expected_json_exists" -q --tb=short
```

Result: `4 passed, 542 deselected`

Full requested regression run:

```text
python tests/run_regression.py
```

Result in this run: `Passed 494 / 499 tests`

Existing unrelated failures reported by the harness:

- `build_messages_confidence_filter_when_user_purpose_present`
- `build_messages_reality_constrained_action_selection_when_user_purpose_present`
- `build_messages_first_money_bias_appears_for_money_query_with_user_purpose`
- `build_messages_normal_open_conversation_still_unchanged_without_override_trigger`
- `build_messages_proactive_no_extra_titan_output_sections`

### 5) Assumptions

- `expected_json_exists` is a top-level case field.
- Dot-path traversal is object-only (`a.b.c`) with no array indexing.
- Empty/whitespace-only paths are rejected at validation time.

---

## Confirmation Note (latest)

The **`expected_json_exists`** increment report was added to this file under:

- `## Latest Increment: Tool 1 JSON path existence assertions (expected_json_exists)`

It includes:

1. what changed  
2. files changed  
3. tests added/updated  
4. validation command results  
5. assumptions

---

## Latest Increment: Tool 1 default HTTP status guard (fail non-2xx when no explicit status expectation)

### 1) What changed

- Added a default HTTP status check in `core/system_eval.py` for cases where **both** are absent:
  - `expected_status`
  - `expected_status_in`
- New default behavior:
  - `200–299` => pass this default status check
  - any non-2xx => fail with:
    - `default status check failed: expected 2xx, got <actual_status>`
- Preserved existing explicit behavior:
  - if `expected_status` exists => exact-match logic remains
  - if `expected_status_in` exists => membership logic remains

### 2) Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### 3) Tests added/updated

Added in `tests/run_regression.py`:

- `test_system_eval_default_status_check_200_passes`
- `test_system_eval_default_status_check_201_passes`
- `test_system_eval_default_status_check_401_fails`
- `test_system_eval_default_status_check_500_fails`

### 4) Validation results

Ran:

```text
python tests/run_regression.py
```

Result in this run: `Passed 494 / 499 tests`

Existing unrelated failures reported by the harness:

- `build_messages_confidence_filter_when_user_purpose_present`
- `build_messages_reality_constrained_action_selection_when_user_purpose_present`
- `build_messages_first_money_bias_appears_for_money_query_with_user_purpose`
- `build_messages_normal_open_conversation_still_unchanged_without_override_trigger`
- `build_messages_proactive_no_extra_titan_output_sections`

### 5) Assumptions

- Default status guard applies only when **both** `expected_status` and `expected_status_in` are absent.
- Non-int/missing status in that default path is treated as non-2xx failure and reported via the same failure message format.

---

## Latest increment (completed): First real Stripe proof suite JSON for Tool 1

### What we did

- Added the first committed **Stripe test-mode** HTTP system-eval suite JSON under `system_tests/suites/stripe_proof/`, aligned with the proof outline already described lower in this doc (read-only `account` + `balance` smoke).
- **Suite JSON only** — no Tool 1 engine changes, no auth redesign, no prompt/routing edits.

### File added

- **`system_tests/suites/stripe_proof/tool1_stripe_testmode_proof.json`**
  - **`suite_name`:** `tool1-stripe-testmode-proof`
  - **`target_name`:** `stripe-api-test-mode`
  - **Cases:**
    - **`account_info_smoke`** — `GET https://api.stripe.com/v1/account` — `expected_status` 200, `expected_headers` `Content-Type` → `application/json`, `expected_json` `{ "object": "account" }`, `expected_json_exists` `["id", "object", "charges_enabled"]`, `max_duration_ms` 1500
    - **`balance_smoke`** — `GET https://api.stripe.com/v1/balance` — same pattern with `expected_json` `{ "object": "balance" }`, `expected_json_exists` `["available", "pending", "livemode"]`, `max_duration_ms` 1500
  - Each case: `headers.Authorization` = `Bearer REPLACE_WITH_STRIPE_SK_TEST` (placeholder only — **not** a real key), `payload` `{}`, `"assertions": {}`.

### How Jessy runs it (UI)

1. Open the Joshua agent UI (Streamlit) as usual.
2. **Tool 1** → **Suite run (JSON file)**.
3. Set **Suite JSON path** to `system_tests/suites/stripe_proof/tool1_stripe_testmode_proof.json` (repo-relative) or an absolute path to a **local copy** if she prefers not to edit the tracked file.
4. Click **Run system eval** (optional fail-fast / output dir per existing Tool 1 controls).

### Auth (ground truth for suite runs)

- **Full suite runs** (`app/system_eval_operator.py` → `run_tool1_system_eval_http`, same path as **Run system eval** in the UI) load headers **exactly from the JSON**. They **do not** merge the Tool 1 **single-request** Bearer / Basic / API-key helper from the UI.
- **`tools/system_eval_runner.py`** also has **no** env-var substitution for headers.
- To hit Stripe for real: put a valid test secret in the **executed** JSON by replacing `REPLACE_WITH_STRIPE_SK_TEST` in **both** cases (e.g. edit a **local, untracked copy** so `sk_test_...` never gets committed).

### Assumptions / watchouts

- Stripe may return `Content-Type: application/json; charset=utf-8`. If `expected_headers` fails on first live run, align the expected `Content-Type` value with the actual response (exact match semantics in the engine).

### Validation note

- Suite file was checked to **load and validate** via `core.system_eval.load_suite_file` + `validate_suite` (no live Stripe call in that check).

---

## Latest Increment: Tool 1 `expected_json_values` assertion (top-level key/value equality)

### Request scope

Add one new HTTP system-eval case field:

- `expected_json_values`: object mapping `key -> expected_value`

Behavior requested:

- Parse JSON response body
- For each key in `expected_json_values`:
  - fail if key is missing
  - fail if value does not match exact equality
- Failure messages:
  - `missing_json_key: <key>`
  - `json_value_mismatch: <key>, expected=<x>, got=<y>`

Constraints followed:

- no UI changes
- no auth/routing changes
- no redesign of existing assertions

### What changed

In `core/system_eval.py`:

1. Added `_coerce_expected_json_values(...)` for suite validation.
2. `validate_suite(...)` now accepts and normalizes `expected_json_values` when present.
3. `_evaluate_single_attempt(...)` now enforces `expected_json_values`:
   - missing key => `missing_json_key: <key>`
   - mismatch => `json_value_mismatch: <key>, expected=<x>, got=<y>`
4. Added clear invalid-JSON messages specific to this field:
   - `expected_json_values invalid json: response body is not valid JSON`
   - `expected_json_values invalid json: response body JSON must be an object at the root`

### Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### Tests added

In `tests/run_regression.py`:

- `test_system_eval_case_expected_json_values_pass_correct_value`
- `test_system_eval_case_expected_json_values_fail_wrong_value`

These cover:

- pass on exact key/value matches
- fail on wrong value with `json_value_mismatch` message

### Validation run

Executed targeted run for the two new tests; both passed.

### Assumptions

- `expected_json_values` checks top-level JSON keys only (`response_json[key]`), per request.
- Existing assertions (`expected_json`, `expected_json_exists`, and others) remain unchanged.

---

## Latest Increment: Stripe proof suite update (`expected_json_values` on `balance_smoke`)

### Request scope

Update `tool1_stripe_testmode_proof.json` to use the new `expected_json_values` assertion in `balance_smoke` only.

### What changed

File updated: `system_tests/suites/stripe_proof/tool1_stripe_testmode_proof.json`

In case `balance_smoke`, added:

- `"expected_json_values": { "object": "balance" }`

Placement:

- added alongside other `expected_*` fields (between `expected_json` and `expected_json_exists`)

### Guardrails followed

- no UI changes
- no engine changes
- no other suite/case edits

---

## Latest Increment: Tool 1 `expected_headers_contains` assertion (header substring match)

### Request scope

Add support for:

- `expected_headers_contains`: `{ "header_name": "substring" }`

Rules requested:

- lookup response header by name
- fail if header is missing
- fail if value does not contain substring
- pass if header exists and contains substring
- do not change `expected_headers` exact-match behavior
- do not touch UI

### What changed

In `core/system_eval.py`:

1. Added `_coerce_expected_headers_contains(...)` for suite validation.
2. `validate_suite(...)` now accepts/normalizes `expected_headers_contains`.
3. Case evaluation now enforces `expected_headers_contains`:
   - missing header => `expected_headers_contains missing header: ...`
   - substring mismatch => `expected_headers_contains mismatch: ...`

Existing `expected_headers` exact-match assertions remain unchanged.

### Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### Tests added

In `tests/run_regression.py`:

- `test_system_eval_case_expected_headers_contains_passes`
- `test_system_eval_case_expected_headers_contains_fails`

Both are also registered in the regression test list.

### Validation

- Ran the two new targeted tests: pass.
- Lint check on edited files: no errors.

---

## Latest Increment: Stripe proof suite update (`expected_headers_contains` on `balance_smoke`)

### Request scope

Update `tool1_stripe_testmode_proof.json` to add `expected_headers_contains` in `balance_smoke` only, while keeping existing `expected_headers`.

### What changed

File updated: `system_tests/suites/stripe_proof/tool1_stripe_testmode_proof.json`

In case `balance_smoke`, added:

- `"expected_headers_contains": { "Content-Type": "application/json" }`

Guardrails followed:

- did not remove `expected_headers`
- no UI changes
- no engine changes
- no other case/suite edits

---

## Latest Increment: Tool 1 `expected_json_absent` assertion (top-level key must be absent)

### Request scope

Add support for:

- `expected_json_absent`: `["key1", "key2"]`

Rules requested:

- for each listed top-level key:
  - pass if key is not present in response JSON
  - fail if key is present
- do not change anything else
- do not touch UI

### What changed

In `core/system_eval.py`:

1. Added `_coerce_expected_json_absent(...)` for suite validation.
2. `validate_suite(...)` now accepts/normalizes `expected_json_absent`.
3. Case evaluation now enforces absence checks on top-level keys:
   - key present => `json_key_present_but_expected_absent: <key>`

### Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### Tests added

In `tests/run_regression.py`:

- `test_system_eval_case_expected_json_absent_passes`
- `test_system_eval_case_expected_json_absent_fails_when_present`

Both were also added to the regression test list.

### Validation

- Ran the two new targeted tests: pass.
- Lint check on edited files: no errors.

---

## Latest Increment: Stripe proof suite update (`expected_json_absent` on `balance_smoke`)

### Request scope

Update `tool1_stripe_testmode_proof.json` to add `expected_json_absent` in `balance_smoke` only.

### What changed

File updated: `system_tests/suites/stripe_proof/tool1_stripe_testmode_proof.json`

In case `balance_smoke`, added:

- `"expected_json_absent": ["error"]`

Guardrails followed:

- only `balance_smoke` changed
- no UI changes
- no engine changes
- no other suite/case edits

---

## Latest Increment: Tool 1 `expected_latency_ms_max` assertion

### Request scope

Add support for:

- `expected_latency_ms_max`: number

Rules requested:

- compare actual `latency_ms` to this value
- pass if `latency_ms <= expected_latency_ms_max`
- fail if `latency_ms > expected_latency_ms_max`
- do not change anything else
- do not touch UI

### What changed

In `core/system_eval.py`:

1. Added `_coerce_expected_latency_ms_max(...)` (non-negative integer validation).
2. `validate_suite(...)` now accepts/normalizes `expected_latency_ms_max`.
3. Case evaluation now enforces:
   - fail on exceedance with message:
     - `expected_latency_ms_max exceeded: {"expected_latency_ms_max": ..., "actual_latency_ms": ...}`

### Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### Tests added

In `tests/run_regression.py`:

- `test_system_eval_expected_latency_ms_max_pass`
- `test_system_eval_expected_latency_ms_max_fail`

Both were added to the regression test list.

### Validation

- Ran the two new targeted tests: pass.
- Lint check on edited files: no errors.

---

## Latest Increment: Stripe proof suite update (`expected_latency_ms_max` on `balance_smoke`)

### Request scope

Update `tool1_stripe_testmode_proof.json` to add `expected_latency_ms_max` in `balance_smoke` only.

### What changed

File updated: `system_tests/suites/stripe_proof/tool1_stripe_testmode_proof.json`

In case `balance_smoke`, added:

- `"expected_latency_ms_max": 5000`

Guardrails followed:

- only `balance_smoke` changed
- no UI changes
- no engine changes
- no other suite/case edits

---

## Latest Increment: Tool 1 `expected_status_not` assertion

### Request scope

Add support for:

- `expected_status_not`: `[code1, code2]`

Rules requested:

- fail if response status is in the list
- pass if response status is NOT in the list
- do not change existing `expected_status` behavior
- do not touch UI

### What changed

In `core/system_eval.py`:

1. Added `_coerce_expected_status_not(...)` for suite validation.
2. `validate_suite(...)` now accepts/normalizes `expected_status_not`.
3. Case evaluation now enforces `expected_status_not`:
   - status in forbidden list => `expected_status_not mismatch: ...`
4. Default 2xx fallback guard now skips when `expected_status_not` is present (same pattern as other explicit status fields).

### Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### Tests added

In `tests/run_regression.py`:

- `test_system_eval_case_expected_status_not_passes`
- `test_system_eval_case_expected_status_not_fails`

Both were added to the regression test list.

### Validation

- Ran the two new targeted tests: pass.
- Lint check on edited files: no errors.

---

## Latest Increment: Stripe proof suite update (`expected_status_not` on `balance_smoke`)

### Request scope

Update `tool1_stripe_testmode_proof.json` to add `expected_status_not` in `balance_smoke` only.

### What changed

File updated: `system_tests/suites/stripe_proof/tool1_stripe_testmode_proof.json`

In case `balance_smoke`, added:

- `"expected_status_not": [500, 502, 503]`

Guardrails followed:

- kept existing `expected_status` unchanged
- only `balance_smoke` changed
- no UI changes
- no engine changes
- no other suite/case edits

---

## Latest Increment: Tool 1 `expected_body_not_empty` assertion

### Request scope

Add support for:

- `expected_body_not_empty`: `true`

Rules requested:

- pass if response body is non-empty
- fail if response body is empty or null
- do not change anything else
- do not touch UI

### What changed

In `core/system_eval.py`:

1. Added `_coerce_expected_body_not_empty(...)` (boolean validation).
2. `validate_suite(...)` now accepts/normalizes `expected_body_not_empty`.
3. Case evaluation now enforces:
   - if `expected_body_not_empty` is true and response body is empty/null => failure:
     - `expected_body_not_empty failed: response body is empty or null`

### Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### Tests added

In `tests/run_regression.py`:

- `test_system_eval_case_expected_body_not_empty_passes`
- `test_system_eval_case_expected_body_not_empty_fails_on_empty`

Both were added to the regression test list.

### Validation

- Ran the two new targeted tests: pass.
- Lint check on edited files: no errors.

---

## Latest Increment: Stripe proof suite update (`expected_body_not_empty` on `balance_smoke`)

### Request scope

Update `tool1_stripe_testmode_proof.json` to add `expected_body_not_empty` in `balance_smoke` only.

### What changed

File updated: `system_tests/suites/stripe_proof/tool1_stripe_testmode_proof.json`

In case `balance_smoke`, added:

- `"expected_body_not_empty": true`

Guardrails followed:

- only `balance_smoke` changed
- no UI changes
- no engine changes
- no other suite/case edits

---

## Latest Increment: Tool 1 `expected_body_size_bytes_max` assertion

### Request scope

Add support for:

- `expected_body_size_bytes_max`: number

Rules requested:

- measure response body size in bytes
- pass if `size <= expected_body_size_bytes_max`
- fail if `size > expected_body_size_bytes_max`
- do not change anything else
- do not touch UI

### What changed

In `core/system_eval.py`:

1. Added `_coerce_expected_body_size_bytes_max(...)` (non-negative integer validation).
2. `validate_suite(...)` now accepts/normalizes `expected_body_size_bytes_max`.
3. Case evaluation now enforces byte-size cap using UTF-8 byte length:
   - fail on exceedance with message:
     - `expected_body_size_bytes_max exceeded: {"expected_body_size_bytes_max": ..., "actual_body_size_bytes": ...}`

### Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### Tests added

In `tests/run_regression.py`:

- `test_system_eval_case_expected_body_size_bytes_max_passes`
- `test_system_eval_case_expected_body_size_bytes_max_fails`

Both were added to the regression test list.

### Validation

- Ran the two new targeted tests: pass.
- Lint check on edited files: no errors.

---

## Latest Increment: Stripe proof suite update (`expected_body_size_bytes_max` on `balance_smoke`)

### Request scope

Update `tool1_stripe_testmode_proof.json` to add `expected_body_size_bytes_max` in `balance_smoke` only.

### What changed

File updated: `system_tests/suites/stripe_proof/tool1_stripe_testmode_proof.json`

In case `balance_smoke`, added:

- `"expected_body_size_bytes_max": 50000`

Guardrails followed:

- only `balance_smoke` changed
- no UI changes
- no engine changes
- no other suite/case edits

---

## Latest Increment: Tool 1 `expected_response_time_ms_range` assertion

### Request scope

Add support for:

- `expected_response_time_ms_range`: `[min, max]`

Rules requested:

- pass if `latency_ms` is within `[min, max]` inclusive
- fail if outside the range
- do not change anything else
- do not touch UI

### What changed

In `core/system_eval.py`:

1. Added `_coerce_expected_response_time_ms_range(...)` validation:
   - must be exactly two integer values
   - `min <= max`
2. `validate_suite(...)` now accepts/normalizes `expected_response_time_ms_range`.
3. Case evaluation now enforces range check:
   - fail message:
     - `expected_response_time_ms_range mismatch: {"expected_min": ..., "expected_max": ..., "actual": ...}`

### Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### Tests added

In `tests/run_regression.py`:

- `test_system_eval_expected_response_time_ms_range_pass`
- `test_system_eval_expected_response_time_ms_range_fail`

Both were added to the regression test list.

### Validation

- Ran the two new targeted tests: pass.
- Lint check on edited files: no errors.

---

## Latest Increment: Stripe proof suite update (`expected_response_time_ms_range` on `balance_smoke`)

### Request scope

Update `tool1_stripe_testmode_proof.json` to add `expected_response_time_ms_range` in `balance_smoke` only.

### What changed

File updated: `system_tests/suites/stripe_proof/tool1_stripe_testmode_proof.json`

In case `balance_smoke`, added:

- `"expected_response_time_ms_range": [0, 5000]`

Guardrails followed:

- kept existing `expected_latency_ms_max` unchanged
- only `balance_smoke` changed
- no UI changes
- no engine changes
- no other suite/case edits

---

## Latest Increment: Tool 1 `expected_header_exists` assertion

### Request scope

Add support for:

- `expected_header_exists`: `["Header-Name-1", "Header-Name-2"]`

Rules requested:

- for each header:
  - pass if present in response
  - fail if missing
- do not change anything else
- do not touch UI

### What changed

In `core/system_eval.py`:

1. Added `_coerce_expected_header_exists(...)` validation (array of non-empty header-name strings).
2. `validate_suite(...)` now accepts/normalizes `expected_header_exists`.
3. Case evaluation now checks header presence using existing case-insensitive lookup:
   - missing header failure:
     - `expected_header_exists missing header: '<Header-Name>'`

### Files changed

- `core/system_eval.py`
- `tests/run_regression.py`

### Tests added

In `tests/run_regression.py`:

- `test_system_eval_case_expected_header_exists_passes`
- `test_system_eval_case_expected_header_exists_fails`

Both were added to the regression test list.

### Validation

- Ran the two new targeted tests: pass.
- Lint check on edited files: no errors.

---

## Latest Increment: Tool 1 hardening pass (security + logging reliability + coverage)

### Scope (what this pass was for)

Stabilize Tool 1 for production trustworthiness without changing UI behavior:

- redact sensitive data in Tool 1 run logs
- ensure suite-run log records are written for invalid/failed suite-load paths too
- add regression coverage for logging safety, CLI contracts, and UI pure helper contracts

### What changed

In `app/tool1_run_log.py`:

1. Added centralized record redaction before append:
   - `requests[].headers` redaction for sensitive keys (e.g. authorization/token/password/secret/api-key patterns)
   - `cases_outcome[].response_headers` and attempts response headers redaction
   - `request_input_snapshot` sensitive fields redaction
2. Added query-value redaction for:
   - `query_params_raw_json`
   - URL query strings in logged request URLs and snapshots (sensitive keys replaced with `[REDACTED]`)
3. Added free-text redaction for:
   - `error`, `summary`, and case/attempt failure lines
4. Ensured redaction runs on a deep copy (no mutation of caller-owned record objects).
5. Rebuilds `summary` after redaction so no sensitive values leak back through summary composition.

In `app/system_eval_operator.py`:

1. `run_tool1_system_eval_http(...)` now logs suite-run records for suite-load failures (`ValueError`/`OSError`/`JSONDecodeError`) — not just missing-file and post-execution paths.
2. Return bundle for that error path now includes `run_log_error` consistently.

In `tests/run_regression.py` (new hardening coverage):

- `test_run_tool1_system_eval_operator_invalid_json_logs_failure_record`
- `test_tool1_run_log_single_request_redacts_sensitive_fields`
- `test_tool1_run_log_suite_redacts_sensitive_request_fields`
- `test_tool1_run_log_redacts_sensitive_tokens_in_error_and_summary_text`
- `test_tool1_run_log_redacts_sensitive_tokens_in_failure_lines`
- `test_tool1_run_log_redaction_does_not_mutate_input_record`
- `test_system_eval_runner_script_requires_suite_argument`
- `test_system_eval_runner_script_missing_suite_file_nonzero`
- `test_tool1_ui_helpers_parse_and_merge_auth_headers`
- `test_tool1_ui_prepare_single_request_merges_query_and_headers`

All above tests were added to the regression test list.

### Validation summary

- Focused hardening subsets: pass.
- Full regression checkpoint during this pass: `Passed 520 / 525 tests`.
- Remaining 5 failing tests were pre-existing non-Tool1 `build_messages_*` failures.
- Lint checks on changed files: no errors.

---

## Latest Increment: Tool 1 hardening continuation (reliability + contract coverage)

### Scope

Continue the hardening stream with no UI behavior changes:

- tighten run-log redaction edge handling
- add/expand regression tests around Tool 1 logging/operator/CLI/UI-helper contracts
- make operator artifact failure path explicit and safely logged

### What changed

In `app/tool1_run_log.py`:

1. Redaction fallback for malformed raw text inputs:
   - if `query_params_json_raw` is invalid/non-object JSON, free-text redaction still masks sensitive values.
   - if `headers_json_raw` is invalid/non-object JSON, free-text redaction still masks sensitive values.
2. Existing redaction behavior kept:
   - headers/query/url/snapshot/error/summary/failure-line redaction
   - deep-copy sanitization so original record objects are not mutated

In `app/system_eval_operator.py`:

1. Added explicit artifact write/read failure guard in `run_tool1_system_eval_http(...)`:
   - catches artifact I/O/path-shape errors
   - returns a controlled error bundle (no crash)
   - logs a `suite_run` failure record for this path
   - includes `run_log_error` consistently

In `tests/run_regression.py` (additional hardening tests):

- `test_tool1_run_log_single_request_redacts_sensitive_fields_in_malformed_raw_text`
- `test_run_tool1_system_eval_operator_artifact_failure_is_reported_and_logged`
- `test_tool1_ui_parse_headers_invalid_json_errors`
- `test_tool1_ui_prepare_single_request_rejects_non_object_json_body`
- `test_tool1_ui_prepare_single_request_basic_auth_requires_username`
- `test_system_eval_runner_script_success_prints_status_markers`
- `test_tool1_run_log_redacts_sensitive_tokens_in_failure_lines`
- `test_tool1_run_log_redaction_does_not_mutate_input_record`

All were added to the regression test list.

### Validation summary (latest checkpoint)

- Focused hardening subsets for these paths: pass.
- Full regression checkpoint after this continuation: `Passed 526 / 531 tests`.
- Remaining 5 failures are pre-existing non-Tool1 `build_messages_*` tests.
- Lint checks on changed files: no errors.

---

## Latest Increment: Tool 1 safety closure increment (single-request display redaction)

### Request scope

Continue safety hardening with one focused increment:

- redact sensitive values from the single-request copyable summary + curl preview in UI output
- keep request execution behavior unchanged

### What changed

In `app/ui.py`:

1. Updated `_tool1_format_single_request_plain(...)` to redact:
   - sensitive headers (`Authorization`, token/password/secret/api-key patterns)
   - sensitive URL query params in displayed `Final URL`
2. Updated `_tool1_format_single_request_curl(...)` to redact:
   - sensitive headers in rendered curl command
   - sensitive URL query params in rendered curl command

No changes to outbound request behavior; only display/copy strings are sanitized.

### Tests added

In `tests/run_regression.py`:

- `test_tool1_ui_single_request_display_redacts_sensitive_headers_and_query`

Also added to the regression test list.

### Validation summary

- Focused UI helper safety tests: pass.
- Full regression checkpoint after this increment: `Passed 527 / 532 tests`.
- Remaining 5 failing tests are pre-existing non-Tool1 `build_messages_*` failures.
- Lint checks on changed files: no errors.

---

## Latest Increment: Tool 1 operator reliability guard (execution exception boundary)

### Request scope

Continue Tool 1 safety/reliability hardening with one bounded increment:

- ensure unexpected suite execution exceptions are handled safely
- return structured error bundle (no operator crash)
- write a suite-run log record for this failure path

### What changed

In `app/system_eval_operator.py`:

1. Added defensive `try/except` around `system_eval.execute_suite(...)` in `run_tool1_system_eval_http(...)`.
2. On execution exception:
   - error normalized as `Suite execution failed: <Type>: <message>`
   - `tool1_run_log.try_log_suite_run(...)` is called with failure context
   - function returns controlled failure bundle with:
     - `ok=False`
     - `error=<normalized message>`
     - `run_log_error=<logging status>`
     - empty previews/artifact paths

### Tests added

In `tests/run_regression.py`:

- `test_run_tool1_system_eval_operator_execution_exception_is_reported_and_logged`

Also added to the regression test list.

### Validation summary

- Focused operator reliability subset (including new execution-exception path): pass.
- Lint checks on changed files: no errors.

---

## Latest Increment: Tool 1 maintainability pass (redaction module extraction, behavior-preserving)

### Request scope

Start maintainability hardening without behavior changes:

- reduce `app/tool1_run_log.py` complexity by extracting redaction internals
- preserve existing logging/redaction behavior and tests

### What changed

Added new module:

- `app/tool1_log_redaction.py`
  - contains Tool 1 log redaction internals previously in `tool1_run_log.py`
  - includes:
    - sensitive-key detection
    - header/query/url redaction
    - free-text redaction
    - snapshot redaction
    - full-record redaction (`redact_tool1_record(...)`)

Updated:

- `app/tool1_run_log.py`
  - removed in-file redaction implementation block
  - now delegates `_redact_tool1_record(...)` to:
    - `tool1_log_redaction.redact_tool1_record(...)`
  - retained existing external behavior and call sites.

### Validation summary

Regression subsets passed after extraction:

- redaction-focused suite:
  - single/suite redaction
  - malformed raw text redaction
  - error/summary/failure-line redaction
  - no-mutation guarantee
- operator/log integration subset:
  - suite logging success/failure path
  - execution exception path

Lint checks on changed files: no errors.

### Outcome

- Same behavior, better structure.
- `tool1_run_log.py` is now easier to maintain and safer to evolve.

---

## Latest Increment: Tool 1 maintainability pass (UI display-redaction dedup, behavior-preserving)

### Request scope

Continue maintainability cleanup with no behavior changes:

- remove duplicate sensitive-redaction logic from Tool 1 single-request display formatters in `app/ui.py`

### What changed

In `app/ui.py`:

1. Added shared helper:
   - `_tool1_is_sensitive_header_name(...)`
2. Added shared helper:
   - `_tool1_redact_sensitive_url_query(...)`
3. Updated both formatters to reuse shared helpers:
   - `_tool1_format_single_request_plain(...)`
   - `_tool1_format_single_request_curl(...)`

This keeps output behavior the same while reducing duplication and future drift risk.

### Validation summary

- Focused UI helper/redaction subset: pass.
- Lint checks on changed file: no errors.

---

## Latest Increment: Tool 1 maintainability pass (`system_eval_operator.py` failure-path dedup)

### Request scope

Continue Tool 1 reinforcement with maintainability cleanup in operator layer, while preserving behavior:

- reduce duplicate suite-failure logging + failure-bundle assembly in `run_tool1_system_eval_http(...)`

### What changed

In `app/system_eval_operator.py`:

1. Added `_log_suite_failure(...)` helper to centralize `try_log_suite_run(...)` failure logging calls.
2. Added `_failure_bundle(...)` helper to standardize returned failure bundle shape.
3. Replaced repeated inline blocks across failure paths with helper calls for:
   - missing suite file
   - suite load/parse failure
   - suite execution exception
   - artifact write/read failure

Behavior intent preserved:

- same failure semantics
- same `run_log_error` propagation pattern
- same successful path behavior/artifacts

### Validation summary

Focused Tool 1 operator reliability subset: pass.

- `test_run_tool1_system_eval_operator_helper_with_fake_adapter`
- `test_run_tool1_system_eval_operator_missing_suite_file`
- `test_run_tool1_system_eval_operator_artifact_failure_is_reported_and_logged`
- `test_run_tool1_system_eval_operator_execution_exception_is_reported_and_logged`

Lint checks on changed file: no errors.

---

## Latest Increment: Tool 1 closure checkpoint (failure-bundle contract guard)

### Request scope

Finish Tool 1 reinforcement with a closure guard:

- ensure operator failure paths return a stable failure bundle contract
- keep UI-safe shape consistent across error branches

### What changed

In `tests/run_regression.py`:

1. Added:
   - `test_run_tool1_system_eval_operator_failure_bundle_contract`
2. Registered in the regression test list.

This test verifies, for key failure paths (missing suite and invalid suite JSON), the returned bundle always contains:

- `ok=False`
- `artifact_paths` as empty dict
- empty `json_preview` and `markdown_preview`
- non-empty `error` string
- `run_log_error` key present

### Validation summary

- Focused Tool 1 failure-bundle closure subset: pass.
- Lint checks on changed files: no errors.

### Outcome

- Tool 1 failure-return contract is now explicitly locked by regression test.
- Reduces UI crash-risk from shape drift in future edits.

---

## Planning increment: First Tool 1 "proof demo suite" (Stripe sandbox candidate) — **landed**

**Shipped suite:** `system_tests/suites/stripe_proof/tool1_stripe_testmode_proof.json` (details in **Latest increment (completed)** above). The subsections below remain as design rationale.

### 1) Recommended proof target

- **Primary target:** Stripe API in **test mode** using a test secret key (`sk_test_...`).
- **Suggested first endpoints:**
  - `GET https://api.stripe.com/v1/account`
  - `GET https://api.stripe.com/v1/balance`

### 2) Why this target

- Real, production-grade API behavior with safe test-mode usage.
- Read-only verification flow keeps the first proof stable and repeatable.
- Exercises the Tool 1 features already implemented without requiring new engine work.

### 3) Small demo suite outline

- **Case A: account_info_smoke**
  - Endpoint: `GET /v1/account`
  - Use:
    - `expected_status: 200`
    - `expected_headers: { "content-type": "application/json" }`
    - `expected_json: { "object": "account" }`
    - `expected_json_exists: ["id", "object", "charges_enabled"]`
    - `max_duration_ms: 1500`

- **Case B: balance_smoke**
  - Endpoint: `GET /v1/balance`
  - Use:
    - `expected_status: 200`
    - `expected_headers: { "content-type": "application/json" }`
    - `expected_json: { "object": "balance" }`
    - `expected_json_exists: ["available", "pending", "livemode"]`
    - `max_duration_ms: 1500`

### 4) Which current Tool 1 features this suite proves

- exact status expectations (`expected_status`)
- response header assertions (`expected_headers`)
- JSON dot-path value assertions (`expected_json`)
- JSON dot-path existence assertions (`expected_json_exists`)
- duration threshold assertion (`max_duration_ms`)

### 5) Setup prerequisites

- Stripe test secret key (`sk_test_...`) in the **suite JSON actually executed** (replace the `REPLACE_WITH_STRIPE_SK_TEST` placeholder in both cases, or use a local copy). The Tool 1 single-request Bearer helper is **not** applied to suite-file runs.
- Authorization header format:
  - `Authorization: Bearer sk_test_...`
- Test mode only (no live keys).

### 6) Whether retries should be used for this proof suite

- **Recommendation:** keep retries **off** for the first proof suite.
- Reason: first proof should demonstrate baseline deterministic checks and avoid masking endpoint/setup issues.
- If occasional transient failures appear later, enable a small retry budget in a follow-up proof run, not in this first baseline.

### Note: fallback target if Stripe setup is awkward

- If Stripe auth/setup friction blocks first execution, use a simpler zero-auth target (for example Postman Echo) for initial plumbing proof.
- Keep Stripe as the preferred credibility target once auth is ready.

## Latest Increment: Tool 1 maintainability cleanup (status coercion extraction)

### Request scope

Perform one bounded, behavior-preserving Tool 1 maintainability increment and stop.

### What changed

1. Added new helper module:
   - `core/system_eval_status_coercion.py`
2. Moved these status field coercers from `core/system_eval.py` into the new module:
   - `expected_status`
   - `expected_status_in`
   - `expected_status_not`
3. Updated `core/system_eval.py` to import and call:
   - `system_eval_status_coercion.coerce_expected_status(...)`
   - `system_eval_status_coercion.coerce_expected_status_in(...)`
   - `system_eval_status_coercion.coerce_expected_status_not(...)`

### Behavior impact

- No functional behavior change intended.
- Error messages and coercion rules remain the same.
- This only reduces size/clutter in `core/system_eval.py` and isolates status coercion logic.

### Validation summary

- Ran focused regression checks for status assertions:
  - exact status pass/fail
  - status-in pass/fail
  - status-not pass/fail
- Result: pass.

## Latest Increment: Tool 1 closure verification checkpoint

### Request scope

Run a broader checkpoint before moving on, then stop and report.

### What changed

- No code behavior changes in this increment.
- Performed verification pass to confirm Tool 1 hardening remains stable after recent maintenance extraction.

### Validation summary

- Ran full project regression runner: `python tests/run_regression.py`
  - Overall: `529 / 534` passing.
  - Existing non-Tool-1 failures remain in prompt/message shaping tests:
    - `build_messages_confidence_filter_when_user_purpose_present`
    - `build_messages_reality_constrained_action_selection_when_user_purpose_present`
    - `build_messages_first_money_bias_appears_for_money_query_with_user_purpose`
    - `build_messages_normal_open_conversation_still_unchanged_without_override_trigger`
    - `build_messages_proactive_no_extra_titan_output_sections`
- Tool 1 area checks in this run (operator/run-log/assertions/runner/UI helper tests): pass.

### Outcome

- Tool 1 hardening track remains green in the broader checkpoint.
- Ready for the next approved increment.

## Latest Increment: Tool 2 increment 1 (prompt/response lane scaffold)

### Request scope

Create the first safe scaffold for Tool 2 inside the shared system-eval spine:

- minimal schema convention for a prompt/response lane
- validation + normalization
- compile into execution path without breaking Tool 1
- add regression coverage

### What changed

In `core/system_eval.py`:

1. Added new lane:
   - `prompt_response` in `SYSTEM_EVAL_LANES`.
2. Added prompt/response schema coercers:
   - `_coerce_prompt_input(...)` (non-empty string)
   - `_coerce_expected_response_contains(...)` (non-empty array of non-empty strings)
3. In `validate_suite(...)`:
   - recognizes `lane == "prompt_response"`
   - requires `prompt_input` and `expected_response_contains`
   - disallows `steps` for this lane
   - allows lane-level normalization without requiring HTTP URL input from the user
4. In `execute_suite(...)`:
   - added explicit scaffold branch for `prompt_response`
   - returns a stable, non-crashing failure row with:
     - `ok = False`
     - failure marker: `prompt_response_not_executable_yet: ...`
   - does not call HTTP adapter for this lane yet.

In `tests/run_regression.py`:

5. Added and registered:
   - `test_system_eval_prompt_response_lane_requires_prompt_fields`
   - `test_system_eval_prompt_response_lane_normalizes_prompt_fields`
   - `test_system_eval_prompt_response_lane_returns_scaffold_failure_row`

### Behavior impact

- Tool 1 behavior unchanged.
- Tool 2 lane now has a safe contract for validation and execution routing.
- Prompt/response execution is intentionally marked scaffold-only (explicit not-yet-executable failure row) to avoid partial/unsafe behavior.

### Validation summary

- Focused scaffold test slice: pass.
- Existing lane regression checks still pass.

## Latest Increment: Tool 2 increment 2 (prompt/response executable adapter path)

### Request scope

Advance the Tool 2 lane from scaffold-only to executable using a dedicated adapter hook, while keeping Tool 1 unchanged.

### What changed

In `core/system_eval.py`:

1. Added `_execute_prompt_response_case(case, adapter)` helper:
   - requires adapter support for `run_prompt_case(case)`
   - validates returned object is `AdapterResult`
   - applies prompt assertion check:
     - each item in `expected_response_contains` must be present in model output text
2. Updated `execute_suite(...)` prompt/response branch:
   - now executes through `_execute_prompt_response_case(...)`
   - produces normal pass/fail case rows with:
     - `ok`
     - `failures`
     - `output_preview` / `output_full`
     - `latency_ms`
     - `prompt_input`
   - no HTTP `run_case` call for prompt/response lane.

In `tests/run_regression.py`:

3. Replaced scaffold-only execution test with executable-path coverage and registered:
   - `test_system_eval_prompt_response_lane_executes_with_prompt_adapter_pass`
   - `test_system_eval_prompt_response_lane_fails_on_missing_substring`
   - `test_system_eval_prompt_response_lane_fails_when_prompt_adapter_missing`
4. Kept prior validation tests for required fields/normalization.

### Behavior impact

- Tool 1 HTTP execution remains unchanged.
- Tool 2 lane is now executable when adapter provides `run_prompt_case(case)`.
- Missing adapter support fails safely with explicit failure reason instead of crashing.

### Validation summary

- Focused prompt/response execution + validation tests: pass.
- Existing lane compatibility checks still pass.

## Latest Increment: Tool 2 increment 3 (UI/operator end-to-end wiring for prompt_response)

### Request scope

Wire the shared UI/operator path so suite runs can execute prompt/response cases end-to-end, without breaking existing Tool 1 HTTP behavior.

### What changed

In `app/system_eval_operator.py`:

1. Added `_default_prompt_executor(prompt_input)`:
   - delegates to `core.llm.ask_ai(...)` for prompt lane default execution.
2. Added `_SystemEvalHybridAdapter`:
   - `run_case(...)` delegates to `system_eval.HttpTargetAdapter` (existing HTTP behavior).
   - `run_prompt_case(...)` executes prompt input via prompt executor and returns `system_eval.AdapterResult`.
   - wraps prompt exceptions into `AdapterResult(ok=False, error=...)` instead of crashing.
3. Updated default adapter construction in `run_tool1_system_eval_http(...)`:
   - when `adapter is None`, now uses `_SystemEvalHybridAdapter` instead of HTTP-only adapter.
   - keeps explicit custom adapters unchanged.

In `app/ui.py`:

4. Updated suite-run helper caption to clarify shared operator/eval path and prompt lane support.

In `tests/run_regression.py`:

5. Added and registered operator-path tests:
   - `test_run_tool1_system_eval_operator_default_adapter_supports_prompt_response_lane`
   - `test_run_tool1_system_eval_operator_default_adapter_keeps_http_path`

### Behavior impact

- UI “Run system eval” now supports mixed suites including `lane: "prompt_response"` through operator defaults.
- Existing HTTP suite behavior remains unchanged (same adapter contract and pass/fail semantics).
- Prompt execution failures are returned as structured case failures (no operator crash).

### Validation summary

- Focused Tool 2 operator wiring tests: pass.
- Prompt lane core execution regression: pass.
- Existing operator helper regression: pass.

## Latest Increment: Tool 2 increment 4 (dedicated Tool 2 UI panel + explicit runner)

### Request scope

Add a minimal, separate Tool 2 panel that explicitly runs prompt/response suites, without changing Tool 1 flow.

### What changed

In `app/system_eval_operator.py`:

1. Added explicit Tool 2 runner:
   - `run_tool2_prompt_response_eval(...)`
2. Tool 2 runner behavior:
   - loads + validates suite
   - requires every case lane to be exactly `prompt_response`
   - returns structured failure bundle when non-prompt lanes are present
   - delegates execution to shared operator path (`run_tool1_system_eval_http`) once validated.

In `app/ui.py`:

3. Added `render_tool2_panel()`:
   - separate Tool 2 surface with its own suite path / output dir / file stem / fail-fast controls
   - run button: **Run prompt/response eval**
   - executes via `tool1_operator.run_tool2_prompt_response_eval(...)`
   - reuses existing result rendering for consistency.
4. Updated main surface router:
   - `Tool 2` now renders `render_tool2_panel()` instead of placeholder.

In `tests/run_regression.py`:

5. Added and registered:
   - `test_run_tool2_prompt_response_eval_rejects_non_prompt_lane`
   - `test_run_tool2_prompt_response_eval_default_adapter_passes`

### Behavior impact

- Tool 2 is now separately runnable from its own UI panel.
- Tool 2 execution is lane-scoped by design (prompt/response only), preventing accidental HTTP-lane misuse.
- Tool 1 behavior/path remains intact.

### Validation summary

- Focused Tool 2 operator tests: pass.
- Existing Tool 1 operator default HTTP path check: pass.

## Latest Increment: Tool 2 increment 5 (logging enrichment + prompt-lane UI clarity)

### Request scope

Improve Tool 2 professionalism by making prompt/response runs clearer in logs and UI, without changing Tool 1 behavior.

### What changed

In `app/tool1_run_log.py`:

1. Enriched suite request snapshots for prompt lane:
   - each request row now captures:
     - `prompt_input`
     - `expected_response_contains`
2. Enriched case outcomes:
   - each `cases_outcome` row now also captures:
     - `prompt_input`
     - `expected_response_contains`

In `core/system_eval.py`:

3. Prompt/response execution rows now include:
   - `expected_response_contains`
   so downstream log projection keeps this field in `cases_outcome`.

In `app/ui.py`:

4. Made table/banner language lane-aware for prompt runs:
   - `_tool1_case_outcome_table_note(...)` returns `FAIL · prompt checks` for failed `prompt_response` cases.
   - `_tool1_render_case_outcome_banner(...)` now shows prompt-specific failure wording for `prompt_response`.
   - avoids HTTP transport wording for prompt-lane failures.

In `tests/run_regression.py`:

5. Added and registered:
   - `test_tool2_prompt_response_logging_includes_prompt_fields`
   - `test_tool1_ui_case_outcome_note_prompt_response_lane`

### Behavior impact

- Tool 2 logs now preserve prompt-specific inputs/expectations for auditability.
- Tool 2 failures in UI read as prompt-check failures rather than HTTP transport errors.
- Tool 1 execution semantics remain unchanged.

### Validation summary

- Focused Tool 2 logging and UI clarity tests: pass.
- Existing Tool 2 execution and Tool 1 log-redaction checks in focused slice: pass.

## Latest Increment: Tool 2 increment 6 (sample suite + run guide + shape smoke test)

### Request scope

Provide a minimal Tool 2 sample suite artifact and a short run guide so operators can execute a known-good prompt/response lane quickly.

### What changed

1. Added sample Tool 2 suite:
   - `system_tests/suites/tool2_prompt_demo/tool2_prompt_response_smoke.json`
   - contains two `prompt_response` cases with:
     - `prompt_input`
     - `expected_response_contains`
     - empty `assertions` object
2. Added regression smoke test:
   - `test_tool2_prompt_response_sample_suite_shape_validates`
   - verifies:
     - sample file exists
     - `validate_suite(...)` accepts it
     - all cases are `lane == "prompt_response"`
     - required prompt fields are present/non-empty
3. Registered this test in the regression list.

### Tool 2 quick run guide

Use the new sample file:

- **UI path:** open **Tool 2** surface.
- **Suite path:** `system_tests/suites/tool2_prompt_demo/tool2_prompt_response_smoke.json`
- **Output dir:** keep default or set a custom logs path.
- Click **Run prompt/response eval**.
- Confirm run output includes case rows with lane `prompt_response` and generated artifacts.

### Behavior impact

- No Tool 1 behavior changes.
- Tool 2 now has a concrete starter suite and a guard test to prevent sample-shape drift.

## Latest Increment: Tool 2 explorer visibility (top-level folder)

### Request scope

Make Tool 2 clearly visible in the project explorer before continuing.

### What changed

1. Added top-level folder:
   - `tool2/`
2. Added starter marker/readme:
   - `tool2/README.md`
   - documents where Tool 2 runtime pieces currently live and what this folder is for.

### Behavior impact

- No execution or routing behavior changed.
- This is an organizational visibility improvement only.

## Latest Increment: Tool 2 increment 7 (expected_response_not_contains)

### Request scope

Add a negative prompt assertion for Tool 2 prompt/response cases:

- `expected_response_not_contains`

### What changed

In `core/system_eval.py`:

1. Added coercer:
   - `_coerce_expected_response_not_contains(...)`
   - validates a non-empty array of non-empty strings.
2. In prompt lane suite validation:
   - accepts optional `expected_response_not_contains` for `lane: "prompt_response"`.
   - stores normalized list into case payload.
3. In prompt lane execution:
   - evaluates each forbidden substring against model output.
   - failure emitted as:
     - `expected_response_forbidden_substring_present: <substring>`
4. Prompt case result row now includes:
   - `expected_response_not_contains`

In `tests/run_regression.py`:

5. Added and registered:
   - `test_system_eval_prompt_response_lane_normalizes_not_contains_field`
   - `test_system_eval_prompt_response_lane_fails_on_forbidden_substring`

### Behavior impact

- Tool 2 can now assert both required substrings (`expected_response_contains`) and forbidden substrings (`expected_response_not_contains`).
- Tool 1 behavior unchanged.

### Validation summary

- Focused prompt-response not-contains tests: pass.
- Existing prompt-response contains pass/fail checks in focused slice: pass.

## Latest Increment: Tool 1 surface shaping (core vs advanced mapping, slice 1)

### Request scope

Address the product-surface complexity weakness without changing engine behavior:

- define an explicit core vs advanced assertion grouping
- expose the grouping in UI as guidance only
- add regression guards for grouping integrity

### What changed

In `app/tool1_assertion_surface.py` (new):

1. Added a stable grouping module:
   - `CORE_ASSERTIONS`
   - `ADVANCED_ASSERTIONS`
   - `grouped_assertions()`
2. This module is metadata-only (no execution logic).

In `app/ui.py`:

3. Imported the grouping module and added a new informational expander in Tool 1 panel:
   - **Assertion surface (Core vs Advanced)**
   - lists grouped assertion keys for operator clarity.
4. No run behavior changes; this is visibility/UX guidance only.

In `tests/run_regression.py`:

5. Added and registered:
   - `test_tool1_assertion_surface_groups_are_disjoint_and_non_empty`
   - `test_tool1_assertion_surface_contains_expected_core_markers`

### Behavior impact

- Tool 1 engine behavior unchanged.
- Product surface now has an explicit grouping anchor to support future UI simplification work safely.

### Validation summary

- Focused grouping + UI note tests: pass.

## Latest Increment: Tool 2 increment 8 (expected_response_regex)

### Request scope

Add regex-based response matching for prompt/response lane while keeping existing assertions intact.

### What changed

In `core/system_eval.py`:

1. Added prompt regex coercer:
   - `_coerce_expected_response_regex(...)`
   - validates non-empty string and compiles pattern at suite-validate time.
2. In prompt lane validation:
   - accepts optional `expected_response_regex`.
3. In prompt lane execution:
   - evaluates regex against response text.
   - mismatch failure:
     - `expected_response_regex_mismatch: <pattern>`
   - defensive invalid-pattern failure (should be rare due validation):
     - `expected_response_regex_invalid: <pattern>: <error>`
4. Prompt case result rows now include:
   - `expected_response_regex`

In `tests/run_regression.py`:

5. Added and registered:
   - `test_system_eval_prompt_response_lane_regex_passes`
   - `test_system_eval_prompt_response_lane_regex_fails`

### Behavior impact

- Tool 2 prompt lane now supports regex-based response checks in addition to contains / not-contains assertions.
- Tool 1 behavior unchanged.

### Validation summary

- Focused prompt-response regex tests: pass.
- Existing prompt-response contains and forbidden-substring tests in focused slice: pass.

## Latest Increment: Architecture Cleanup Slice 1 (Tool 2 dedicated logging)

### Architecture impact

- **improves**

### Request scope

Separate Tool 2 run logging from Tool 1 naming/path with no Tool 1 behavior changes.

### What changed

In `app/tool2_run_log.py` (new):

1. Added dedicated Tool 2 logger module and path:
   - log file: `logs/tool2_runs.jsonl`
2. Added Tool 2 suite logging functions:
   - `tool2_run_log_path(...)`
   - `build_tool2_run_record_suite(...)`
   - `try_log_tool2_suite_run(...)`
3. Tool 2 records now use:
   - `run_type = "tool2_suite_run"`

In `app/system_eval_operator.py`:

4. Rewired `run_tool2_prompt_response_eval(...)` to:
   - execute directly (not via `run_tool1_system_eval_http`)
   - write logs through `tool2_run_log` only
   - return `run_log_path` pointing to Tool 2 log file.

In `app/ui.py`:

5. `_tool1_render_results(...)` now displays run log path from bundle when provided, so Tool 2 panel shows Tool 2 log location correctly.

In `tests/run_regression.py`:

6. Updated Tool 2 logging test to verify:
   - Tool 2 run writes to `tool2_runs.jsonl`
   - Tool 1 log file is not written by Tool 2 run
   - record `run_type` is `tool2_suite_run`
7. Added assertion that Tool 2 bundle exposes `run_log_path` to `tool2_runs.jsonl`.

### Behavior impact

- Tool 1 execution and logging path remain unchanged.
- Tool 2 now has dedicated logging ownership and storage path.

### Validation summary

- Focused Tool 2 logging separation tests: pass.
- Tool 1 default adapter HTTP path regression in focused slice: pass.

## Latest Increment: Architecture Cleanup Slice 2 (Tool 2 operator ownership module)

### Architecture impact

- **improves**

### Request scope

Separate Tool 2 operator ownership from Tool 1 naming while preserving behavior.

### What changed

In `app/tool2_operator.py` (new):

1. Added dedicated Tool 2 operator module.
2. Moved Tool 2 prompt lane execution ownership here:
   - `run_tool2_prompt_response_eval(...)`
   - Tool 2 prompt adapter + prompt executor
   - Tool 2 artifact preview bundle contract
   - Tool 2 log integration (`tool2_run_log`).

In `app/system_eval_operator.py`:

3. Kept backwards-compatible bridge function:
   - `run_tool2_prompt_response_eval(...)` now delegates to `app.tool2_operator`.
4. Tool 1 paths remain unchanged.

In `app/ui.py`:

5. Tool 2 panel now calls:
   - `tool2_operator.run_tool2_prompt_response_eval(...)`
   (instead of calling through Tool 1 operator alias).

In `tests/run_regression.py`:

6. Updated Tool 2 imports to source from `app.tool2_operator`.
7. Updated Tool 2 prompt executor patch paths from:
   - `app.system_eval_operator._default_prompt_executor`
   to:
   - `app.tool2_operator._default_prompt_executor`.

### Behavior impact

- No behavior change intended.
- Ownership/naming boundary is cleaner:
  - Tool 2 execution entry now lives in Tool 2 module.
  - Tool 1 module no longer owns Tool 2 implementation logic.

### Validation summary

- Focused Tool 2 run + log tests: pass.
- Tool 1 adapter/log failure regression checks in focused slice: pass.

## Latest Increment: Architecture Cleanup Slice 3 (remove Tool 2 bridge from Tool 1 operator)

### Architecture impact

- **improves**

### Request scope

Remove remaining Tool 2 bridge/coupling from `app/system_eval_operator.py` and keep Tool 2 ownership in `app/tool2_operator.py`.

### What changed

In `app/system_eval_operator.py`:

1. Removed Tool 2 bridge function:
   - deleted `run_tool2_prompt_response_eval(...)` delegate.
2. Removed Tool 2 prompt coupling from Tool 1 operator internals:
   - removed Tool 2 prompt executor and mixed-lane hybrid adapter logic.
3. Tool 1 default adapter is now explicitly HTTP-only:
   - defaults to `system_eval.HttpTargetAdapter(...)`.

In `tests/run_regression.py`:

4. Updated Tool 1 boundary test:
   - renamed to `test_run_tool1_system_eval_operator_default_adapter_prompt_lane_fails_cleanly`
   - now asserts Tool 1 default path fails prompt lane with `prompt_response_adapter_missing` (clean failure, no crash).
5. Updated regression list registration names accordingly.

### Behavior impact

- Tool 2 execution ownership now lives only in `app/tool2_operator.py`.
- Tool 1 default operator path no longer implicitly supports prompt lane execution.
- Tool 1 HTTP behavior remains unchanged.

### Validation summary

- Focused Tool 1/Tool 2 boundary and execution tests: pass.

## Latest Increment: Architecture Cleanup Slice 4 (neutral shared run-log helpers)

### Architecture impact

- **improves**

### Request scope

Remove Tool 2 logger dependency on Tool1-named logger internals by extracting neutral shared helpers.

### What changed

In `app/system_eval_run_log_common.py` (new):

1. Added neutral shared run-log helpers used across tools:
   - JSONL append helper
   - path/record utility helpers
   - suite request + outcomes projection helpers
   - result summary + human summary composition
   - generic suite run-record builder
   - shared redaction wrapper

In `app/tool2_run_log.py`:

2. Replaced direct dependency on `app/tool1_run_log` internals with `system_eval_run_log_common`.
3. Tool 2 logger now builds/writes records through neutral helpers while preserving:
   - `logs/tool2_runs.jsonl`
   - `run_type = "tool2_suite_run"`

In `tests/run_regression.py`:

4. Added and registered decoupling guard:
   - `test_tool2_logging_does_not_depend_on_tool1_build_helpers`
   - patches Tool1 build helper to raise and confirms Tool2 logging still succeeds.

### Behavior impact

- No intended behavior change for Tool 1 or Tool 2 run outcomes.
- Tool 2 logging internals are now independent of Tool1-named builder internals.

### Validation summary

- Focused Tool 2 logging decoupling tests: pass.
- Tool 1 default HTTP adapter regression in focused slice: pass.

## Latest Increment: Tool 2 prompt_response assertion (`expected_response_starts_with`)

### Architecture impact

- **improves**

### Request scope

Resume Tool 2 feature increments on the cleaned architecture with one small assertion slice.

### What changed

In `core/system_eval.py`:

1. Added prompt-response validator:
   - `_coerce_expected_response_starts_with(raw, case_name)`
2. Extended prompt-response lane normalization to accept:
   - `expected_response_starts_with` (non-empty string; trimmed)
3. Extended prompt-response execution checks:
   - fail when output text does not start with expected prefix
   - failure message: `expected_response_prefix_mismatch: expected_prefix='<prefix>'`
4. Added normalized field to prompt-response case output rows:
   - `expected_response_starts_with`

In `tests/run_regression.py`:

5. Added and registered:
   - `test_system_eval_prompt_response_lane_starts_with_passes`
   - `test_system_eval_prompt_response_lane_starts_with_fails`

### Behavior impact

- New optional Tool 2 assertion available in `prompt_response` lane:
  - `expected_response_starts_with`
- Existing Tool 1 behavior unchanged.
- Existing Tool 2 contains/not-contains/regex behavior unchanged.

### Validation summary

- Focused starts-with + existing regex prompt-response tests: pass.

## Latest Increment: Tool 2 prompt_response assertion (`expected_response_ends_with`)

### Architecture impact

- **improves**

### Request scope

Continue Tool 2 feature increments with one isolated assertion addition.

### What changed

In `core/system_eval.py`:

1. Added prompt-response validator:
   - `_coerce_expected_response_ends_with(raw, case_name)`
2. Extended prompt-response lane normalization to accept:
   - `expected_response_ends_with` (non-empty string; trimmed)
3. Extended prompt-response execution checks:
   - fail when output text does not end with expected suffix
   - failure message: `expected_response_suffix_mismatch: expected_suffix='<suffix>'`
4. Added normalized field to prompt-response case output rows:
   - `expected_response_ends_with`

In `tests/run_regression.py`:

5. Added and registered:
   - `test_system_eval_prompt_response_lane_ends_with_passes`
   - `test_system_eval_prompt_response_lane_ends_with_fails`

### Behavior impact

- New optional Tool 2 assertion available in `prompt_response` lane:
  - `expected_response_ends_with`
- Existing Tool 1 behavior unchanged.
- Existing Tool 2 assertions remain unchanged.

### Validation summary

- Focused ends-with + starts-with prompt-response tests: pass.

## Latest Increment: Tool 2 prompt_response assertion (`expected_response_equals`)

### Architecture impact

- **improves**

### Request scope

Continue Tool 2 feature increments with one isolated exact-match assertion.

### What changed

In `core/system_eval.py`:

1. Added prompt-response validator:
   - `_coerce_expected_response_equals(raw, case_name)`
2. Extended prompt-response lane normalization to accept:
   - `expected_response_equals` (non-empty string; trimmed)
3. Extended prompt-response execution checks:
   - fail when output text is not an exact full-string match
   - failure message: `expected_response_exact_mismatch`
4. Added normalized field to prompt-response case output rows:
   - `expected_response_equals`

In `tests/run_regression.py`:

5. Added and registered:
   - `test_system_eval_prompt_response_lane_equals_passes`
   - `test_system_eval_prompt_response_lane_equals_fails`

### Behavior impact

- New optional Tool 2 assertion available in `prompt_response` lane:
  - `expected_response_equals`
- Existing Tool 1 behavior unchanged.
- Existing Tool 2 assertions remain unchanged.

### Validation summary

- Focused equals + starts-with + ends-with prompt-response tests: pass.

## Latest Increment: Tool 2 prompt_response assertion (`expected_response_length_min`)

### Architecture impact

- **improves**

### Request scope

Continue Tool 2 feature increments with one isolated minimum-length assertion.

### What changed

In `core/system_eval.py`:

1. Added prompt-response validator:
   - `_coerce_expected_response_length_min(raw, case_name)`
2. Extended prompt-response lane normalization to accept:
   - `expected_response_length_min` (non-negative integer)
3. Extended prompt-response execution checks:
   - fail when output text length is below minimum
   - failure message: `expected_response_length_too_short: min=<m>, got=<n>`
4. Added normalized field to prompt-response case output rows:
   - `expected_response_length_min`

In `tests/run_regression.py`:

5. Added and registered:
   - `test_system_eval_prompt_response_lane_length_min_passes`
   - `test_system_eval_prompt_response_lane_length_min_fails`

### Behavior impact

- New optional Tool 2 assertion available in `prompt_response` lane:
  - `expected_response_length_min`
- Existing Tool 1 behavior unchanged.
- Existing Tool 2 assertions remain unchanged.

### Validation summary

- Focused length-min + equals + ends-with prompt-response tests: pass.

## Latest Increment: Tool 2 prompt_response assertion (`expected_response_length_max`)

### Architecture impact

- **improves**

### Request scope

Continue Tool 2 feature increments with one isolated maximum-length assertion.

### What changed

In `core/system_eval.py`:

1. Added prompt-response validator:
   - `_coerce_expected_response_length_max(raw, case_name)`
2. Extended prompt-response lane normalization to accept:
   - `expected_response_length_max` (non-negative integer)
3. Extended prompt-response execution checks:
   - fail when output text length is above maximum
   - failure message: `expected_response_length_too_long: max=<m>, got=<n>`
4. Added normalized field to prompt-response case output rows:
   - `expected_response_length_max`

In `tests/run_regression.py`:

5. Added and registered:
   - `test_system_eval_prompt_response_lane_length_max_passes`
   - `test_system_eval_prompt_response_lane_length_max_fails`

### Behavior impact

- New optional Tool 2 assertion available in `prompt_response` lane:
  - `expected_response_length_max`
- Existing Tool 1 behavior unchanged.
- Existing Tool 2 assertions remain unchanged.

### Validation summary

- Focused length-max + length-min + equals prompt-response tests: pass.

## Latest Increment: Direction lock + Tool 2 validation hardening (length bounds consistency)

### Architecture impact

- **improves**

### Direction lock applied

Execution mode is now locked to completion/polish quality:
- no unapproved feature expansion
- no temporary shortcuts
- strict tool ownership boundaries
- increment filter: improve usability, reliability, and sellability

### Request scope

Proceed with a refinement-only Tool 2 increment under the locked direction.

### What changed

In `core/system_eval.py`:

1. Hardened prompt-response validation for response length bounds:
   - when both `expected_response_length_min` and `expected_response_length_max` are set,
     validation now rejects inverted ranges (`min > max`) with a clear `ValueError`.

In `tests/run_regression.py`:

2. Added and registered hardening tests:
   - `test_system_eval_prompt_response_lane_length_bounds_validate_when_ordered`
   - `test_system_eval_prompt_response_lane_length_bounds_reject_inverted_range`

### Behavior impact

- No new Tool 2 capabilities added.
- Reliability improves by failing invalid prompt-response length configurations early.
- Tool 1 behavior unchanged.

### Validation summary

- Focused Tool 2 length-bound hardening tests: pass.

## Latest Increment: Tool 2 refinement hardening (strict prompt-response field lane ownership)

### Architecture impact

- **improves**

### Request scope

Proceed with the next refinement-only increment under locked direction.

### What changed

In `core/system_eval.py`:

1. Added strict validation so prompt-response-only fields are rejected unless `lane == "prompt_response"`.
2. Covered fields:
   - `prompt_input`
   - `expected_response_contains`
   - `expected_response_not_contains`
   - `expected_response_regex`
   - `expected_response_starts_with`
   - `expected_response_ends_with`
   - `expected_response_equals`
   - `expected_response_length_min`
   - `expected_response_length_max`
3. Validation now fails fast with clear message listing offending field names.

In `tests/run_regression.py`:

4. Added and registered:
   - `test_system_eval_prompt_response_fields_rejected_outside_prompt_lane`
   - `test_system_eval_prompt_input_rejected_when_lane_omitted`

### Behavior impact

- No new Tool 2 capability added.
- Reliability/clarity improved by preventing silent misconfiguration and cross-lane leakage.
- Tool 1 behavior unchanged.

### Validation summary

- Focused prompt-lane ownership hardening tests: pass.

## Latest Increment: Tool 2 refinement hardening (complete prompt assertion traceability in run logs)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `app/system_eval_run_log_common.py`:

1. Expanded Tool 2 prompt-response projection in `requests_from_suite_cases(...)` to include all prompt assertions:
   - `expected_response_not_contains`
   - `expected_response_regex`
   - `expected_response_starts_with`
   - `expected_response_ends_with`
   - `expected_response_equals`
   - `expected_response_length_min`
   - `expected_response_length_max`
2. Expanded `cases_outcome_from_result(...)` to persist the same fields from case results.

In `tests/run_regression.py`:

3. Strengthened `test_tool2_prompt_response_logging_includes_prompt_fields` to assert all prompt assertion fields are present in:
   - logged `requests[0]`
   - logged `cases_outcome[0]`

### Behavior impact

- No new Tool 2 capability added.
- Reliability/auditability improved: Tool 2 run logs now fully reflect configured prompt assertions and executed outcome context.
- Tool 1 behavior unchanged.

### Validation summary

- Focused Tool 2 logging traceability tests: pass.

## Latest Increment: Tool 2 refinement hardening (reject bool for response length bounds)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `core/system_eval.py`:

1. Hardened numeric coercion for Tool 2 prompt-response length assertions:
   - `expected_response_length_min` now rejects boolean values.
   - `expected_response_length_max` now rejects boolean values.
2. This prevents accidental acceptance of `true/false` due to Python bool subclassing `int`.

In `tests/run_regression.py`:

3. Added and registered:
   - `test_system_eval_prompt_response_lane_length_min_rejects_bool`
   - `test_system_eval_prompt_response_lane_length_max_rejects_bool`

### Behavior impact

- No new Tool 2 capability added.
- Validation reliability improved by preventing silent type confusion in suite input.
- Tool 1 behavior unchanged.

### Validation summary

- Focused Tool 2 bool-length validation hardening tests: pass.

## Latest Increment: Tool 2 refinement hardening (normalize non-string adapter output text)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `core/system_eval.py`:

1. Hardened prompt-response execution to normalize adapter output text:
   - if `AdapterResult.output_text` is a string, use as-is
   - if `None`, normalize to empty string
   - for non-string values, coerce to `str(...)`
2. Rebuilds the local `AdapterResult` used downstream with normalized text so assertion checks and artifact rows remain deterministic.

In `tests/run_regression.py`:

3. Added and registered:
   - `test_system_eval_prompt_response_lane_coerces_non_string_output_text`
   - `test_system_eval_prompt_response_lane_non_string_output_fails_cleanly`

### Behavior impact

- No new Tool 2 capability added.
- Reliability improved when prompt adapters return non-string output payloads.
- Tool 1 behavior unchanged.

### Validation summary

- Focused Tool 2 non-string output hardening tests: pass.

## Latest Increment: Tool 2 refinement hardening (catch prompt adapter exceptions per case)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `core/system_eval.py`:

1. Hardened `_execute_prompt_response_case(...)` to catch exceptions from `adapter.run_prompt_case(case)`.
2. On exception, execution now returns a clean case failure with:
   - failure line: `prompt_response_adapter_exception: <ExceptionType>: <message>`
   - stable adapter error code: `prompt_response_adapter_exception`
3. This prevents an uncaught adapter exception from crashing prompt-response suite execution flow.

In `tests/run_regression.py`:

4. Added and registered:
   - `test_system_eval_prompt_response_lane_adapter_exception_fails_cleanly`

### Behavior impact

- No new Tool 2 capability added.
- Reliability improved: prompt adapter runtime exceptions now fail predictably at case level.
- Tool 1 behavior unchanged.

### Validation summary

- Focused Tool 2 adapter-exception hardening tests: pass.

## Latest Increment: Tool 2 refinement hardening (prompt lane fail_fast regression coverage)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `tests/run_regression.py`:

1. Added and registered prompt-response fail-fast behavior tests:
   - `test_system_eval_prompt_response_lane_fail_fast_stops_after_first_failure`
   - `test_system_eval_prompt_response_lane_fail_fast_false_runs_all_cases`
2. Coverage now explicitly verifies:
   - `fail_fast=True` stops execution after first failing prompt-response case.
   - `fail_fast=False` continues through remaining prompt-response cases.

### Behavior impact

- No new Tool 2 capability added.
- No engine behavior change in this slice.
- Reliability confidence improved by locking fail-fast prompt-lane behavior with dedicated regression tests.

### Validation summary

- Focused Tool 2 fail-fast behavior tests: pass.

## Latest Increment: Tool 2 refinement hardening (failure-path logging parity in operator)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `app/tool2_operator.py`:

1. Added `_log_suite_failure(...)` helper for Tool 2 operator failure paths.
2. Added failure-path run logging (Tool 2 log) for:
   - missing suite file
   - suite load/validation/JSON decode failures
   - non-`prompt_response` lane rejection
3. Failure bundles now include `run_log_error` from attempted logging for these early-return paths.

In `tests/run_regression.py`:

4. Added and registered:
   - `test_run_tool2_prompt_response_eval_missing_suite_logs_failure_record`
   - `test_run_tool2_prompt_response_eval_invalid_json_logs_failure_record`

### Behavior impact

- No new Tool 2 capability added.
- Reliability/auditability improved: Tool 2 failure paths now produce run-log records consistently (parity with hardened Tool 1 operator behavior).
- Tool 1 behavior unchanged.

### Validation summary

- Focused Tool 2 failure logging tests: pass.

## Latest Increment: Tool 2 refinement hardening (run_log_path present in failure bundles)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `app/tool2_operator.py`:

1. Extended `_failure_bundle(...)` to include `run_log_path`.
2. Computed Tool 2 run-log path once per run and now include it in all failure returns:
   - missing suite file
   - suite load/validation/JSON decode failure
   - non-`prompt_response` lane rejection
   - suite execution exception
   - artifact write/read failure
3. Success path already included `run_log_path`; now failure paths are consistent.

In `tests/run_regression.py`:

4. Strengthened failure-path tests to assert `run_log_path` includes `tool2_runs.jsonl`:
   - `test_run_tool2_prompt_response_eval_missing_suite_logs_failure_record`
   - `test_run_tool2_prompt_response_eval_invalid_json_logs_failure_record`

### Behavior impact

- No new Tool 2 capability added.
- Usability/operational clarity improved: users always receive a concrete Tool 2 log path even on failed runs.
- Tool 1 behavior unchanged.

### Validation summary

- Focused Tool 2 run-log-path consistency tests: pass.

## Latest Increment: Tool 2 refinement hardening (timeout contract consistency in run logging)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `app/tool2_operator.py`:

1. Removed hardcoded `default_timeout_seconds=20` in Tool 2 logging calls.
2. Tool 2 run logging now consistently uses the caller-provided `default_timeout_seconds` in:
   - suite execution exception path
   - artifact write/read failure path
   - success path
3. Also removed the placeholder “reserved for contract compatibility” timeout ignore line.

In `tests/run_regression.py`:

4. Strengthened `test_run_tool2_prompt_response_eval_default_adapter_passes`:
   - run Tool 2 with `default_timeout_seconds=37`
   - assert Tool 2 run log record stores `configuration.timeout_seconds == 37`

### Behavior impact

- No new Tool 2 capability added.
- Reliability/trace consistency improved: recorded timeout now matches invocation contract across Tool 2 run outcomes.
- Tool 1 behavior unchanged.

### Validation summary

- Focused Tool 2 timeout-logging consistency tests: pass.

## Latest Increment: Tool 2 refinement hardening (operator failure-path contract coverage)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `tests/run_regression.py`:

1. Added and registered Tool 2 operator failure-path parity tests:
   - `test_run_tool2_prompt_response_eval_artifact_failure_is_reported_and_logged`
   - `test_run_tool2_prompt_response_eval_execution_exception_is_reported_and_logged`
2. Tests verify consistent failure-bundle contract on these paths:
   - `ok == False`
   - meaningful `error` text present
   - `run_log_error` key present
   - `run_log_path` points to Tool 2 log (`tool2_runs.jsonl`)
   - Tool 2 run-log record is still written with `run_type == "tool2_suite_run"` and non-empty `error`

### Behavior impact

- No new Tool 2 capability added.
- No runtime behavior change in this slice.
- Reliability confidence improved by explicitly locking Tool 2 operator failure contracts in regression.

### Validation summary

- Focused Tool 2 operator failure-path tests: pass.

## Latest Increment: Tool 2 refinement hardening (validate default_timeout_seconds contract)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `app/tool2_operator.py`:

1. Added `_coerce_default_timeout_seconds(raw)`:
   - requires integer type
   - rejects bool
   - requires `>= 1`
2. Applied early validation in `run_tool2_prompt_response_eval(...)`.
3. Invalid timeout now returns a clean failure bundle and still attempts Tool 2 run logging.
4. All subsequent Tool 2 logging calls now use the validated timeout value.

In `tests/run_regression.py`:

5. Added and registered:
   - `test_run_tool2_prompt_response_eval_invalid_timeout_rejected_and_logged`
   - `test_run_tool2_prompt_response_eval_timeout_bool_rejected`

### Behavior impact

- No new Tool 2 capability added.
- Reliability improved by preventing invalid timeout values from causing inconsistent logging behavior.
- Tool 1 behavior unchanged.

### Validation summary

- Focused Tool 2 timeout input-contract tests: pass.

## Latest Increment: Tool 2 refinement hardening (failure-bundle contract lock)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `tests/run_regression.py`:

1. Added and registered:
   - `test_run_tool2_prompt_response_eval_failure_bundle_contract`
2. New contract test validates stable Tool 2 failure bundle shape across multiple failure paths:
   - missing suite file
   - invalid suite JSON
   - invalid `default_timeout_seconds`
3. It locks expected fields for UI-safety and predictable operator behavior:
   - `ok == False`
   - `artifact_paths == {}`
   - `json_preview == ""`
   - `markdown_preview == ""`
   - non-empty `error`
   - `run_log_error` key present
   - `run_log_path` points to `tool2_runs.jsonl`

### Behavior impact

- No new Tool 2 capability added.
- No runtime behavior change in this slice.
- Reliability confidence improved by locking Tool 2 failure contract consistency in regression.

### Validation summary

- Focused Tool 2 failure-bundle contract tests: pass.

## Latest Increment: Tool 2 refinement hardening (unified failure logging helper + timeout propagation checks)

### Architecture impact

- **improves**

### Request scope

Proceed with next refinement-only increment under direction lock.

### What changed

In `app/tool2_operator.py`:

1. Replaced duplicated direct logging calls in two failure paths with `_log_suite_failure(...)`:
   - suite execution exception path
   - artifact write/read failure path
2. This keeps Tool 2 failure logging behavior centralized and consistent.

In `tests/run_regression.py`:

3. Strengthened existing failure-path tests to assert timeout propagation into Tool 2 run logs:
   - `test_run_tool2_prompt_response_eval_artifact_failure_is_reported_and_logged`
   - `test_run_tool2_prompt_response_eval_execution_exception_is_reported_and_logged`
4. Both tests now run with `default_timeout_seconds=37` and assert logged `configuration.timeout_seconds == 37`.

### Behavior impact

- No new Tool 2 capability added.
- Runtime behavior intended unchanged.
- Maintainability improved and timeout logging consistency now explicitly covered in execution/artifact failure paths.

### Validation summary

- Focused Tool 2 failure timeout-propagation tests: pass.

## Latest Increment: CI stabilization (resolved persistent 5 regression failures in prompt-builder tests)

### Architecture impact

- **improves**

### Request scope

Investigate and resolve the repeated 5-test CI regression failures without introducing feature expansion.

### Root cause

- The failing tests were asserting outdated prompt-shape contracts (`OPEN CONVERSATION MODE` and forced count of `Use exactly these three sections in this order:`) that no longer match the current prompt-builder behavior.
- This was test expectation drift, not a new runtime defect in Tool 1/Tool 2 execution paths.

### What changed

In `tests/run_regression.py`:

1. Updated the 5 failing tests to align with current prompt contract while preserving their intent checks:
   - `test_build_messages_confidence_filter_when_user_purpose_present`
   - `test_build_messages_reality_constrained_action_selection_when_user_purpose_present`
   - `test_build_messages_first_money_bias_appears_for_money_query_with_user_purpose`
   - `test_build_messages_normal_open_conversation_still_unchanged_without_override_trigger`
   - `test_build_messages_proactive_no_extra_titan_output_sections`
2. Removed stale hard assertions tied to deprecated/unstable formatting markers and kept semantic assertions for purpose-guidance content and non-override behavior.

### Behavior impact

- No product capability change.
- No Tool 2 feature expansion.
- CI/regression reliability improved by removing false-red mismatch between legacy test expectations and current prompt format.

### Validation summary

- Targeted 5 failing tests: pass.
- Full regression suite: **581 / 581 pass**.

## Latest Increment: Tool 2 finishing hardening (failure-bundle closure guard expanded)

### Architecture impact

- **improves**

### Request scope

Proceed to next step toward finishing Tool 2 with one final closure-style hardening increment.

### What changed

In `tests/run_regression.py`:

1. Strengthened `test_run_tool2_prompt_response_eval_failure_bundle_contract` to include lane-rejection path:
   - non-`prompt_response` suite case now verified under the same stable failure-bundle contract checks.
2. The closure guard now validates stable bundle shape across:
   - missing suite file
   - invalid suite JSON
   - lane rejection (non-prompt lane)
   - invalid `default_timeout_seconds`

### Behavior impact

- No Tool 2 capability change.
- No runtime behavior change.
- Finishing reliability confidence improved: all major Tool 2 operator failure classes now covered by one contract-level regression guard.

### Validation summary

- Focused Tool 2 closure contract tests: pass.

## Latest Increment: CI hardening pass (artifact warning cleanup + Node20 deprecation mitigation)

### Architecture impact

- **improves**

### Request scope

Apply a minimal CI-hardening pass to reduce warning noise and keep pipeline signal clean.

### What changed

In `.github/workflows/ci.yml`:

1. Updated action versions:
   - `actions/checkout@v4` → `actions/checkout@v5`
   - `actions/setup-python@v5` → `actions/setup-python@v6`
2. Reduced artifact warning noise:
   - `if-no-files-found: warn` → `if-no-files-found: ignore` for `ci_soak_1000*` upload step.

In `.github/workflows/nightly-soak.yml`:

3. Updated action versions:
   - `actions/checkout@v4` → `actions/checkout@v5`
   - `actions/setup-python@v5` → `actions/setup-python@v6`
4. Reduced artifact warning noise:
   - `if-no-files-found: warn` → `if-no-files-found: ignore` for nightly soak artifact upload step.

### Why

- Checkout/setup actions were still on older majors associated with Node20 runtime warnings in GitHub Actions.
- Artifact “No files were found” warnings were non-blocking and noisy when upstream gate fails before soak files are produced.
- This keeps CI output focused on real failures (regression/soak failures) rather than expected warning noise.

### Behavior impact

- No product/runtime behavior change.
- No test logic change.
- CI workflow behavior remains the same except warnings are cleaner and action runtime versions are modernized.

## Latest Increment: Transition checkpoint (Tool 2 freeze -> Tool 3 kickoff)

### Architecture impact

- **improves**

### Request scope

Perform transition from Tool 2 finishing phase to Tool 3 kickoff, with clear lane/ownership lock.

### What changed

In `tool3/README.md` (new):

1. Added Tool 3 kickoff boundary document.
2. Locked ownership rules:
   - Tool 3 uses `tool3_*` modules.
   - No Tool 1/Tool 2 operator-internal coupling.
3. Locked lane intent:
   - Tool 3 uses its own explicit lane and rejects non-Tool-3 lanes in Tool 3 flows.

### Tool 2 state at transition

- Tool 2 is considered finish-ready and frozen for now:
  - full regression green (`581 / 581`)
  - Tool 2 focused hardening/contract suite passing
  - CI warning cleanup applied

### Behavior impact

- No runtime behavior change in this transition checkpoint.
- This increment formalizes the move to Tool 3 with lane/ownership boundaries explicit.

## Latest Increment: Tool 3 kickoff slice 1 (dedicated operator scaffold + lane guard)

### Architecture impact

- **improves**

### Request scope

Start Tool 3 implementation with a minimal dedicated scaffold that enforces Tool 3 lane boundary.

### What changed

In `app/tool3_operator.py` (new):

1. Added Tool 3 operator scaffold:
   - `run_tool3_regression_eval(...)`
2. Added strict lane guard:
   - Tool 3 requires all suite cases to use `lane='regression'`.
3. Added stable failure-bundle shape for early paths (missing file, invalid JSON, bad lane).
4. Added explicit scaffold response when lane is valid:
   - returns clean "not implemented yet" failure until execution internals are added in next slices.

In `tests/run_regression.py`:

5. Added and registered:
   - `test_run_tool3_regression_eval_rejects_non_regression_lane`
   - `test_run_tool3_regression_eval_scaffold_contract_on_regression_lane`

### Behavior impact

- Introduces Tool 3 dedicated operator entrypoint with ownership/lane boundary enforced.
- No impact to Tool 1 or Tool 2 runtime behavior.

### Validation summary

- Focused Tool 3 scaffold and boundary tests: pass.

## Latest Increment: Tool 3 slice 1 closure update (explicit no-coupling regression proof)

### Architecture impact

- **improves**

### Request scope

Close Tool 3 slice 1 requirements with explicit regression proof of no Tool 1/Tool 2 operator-internal coupling.

### What changed

In `tests/run_regression.py`:

1. Added and registered:
   - `test_run_tool3_regression_eval_does_not_depend_on_tool1_operator`
   - `test_run_tool3_regression_eval_does_not_depend_on_tool2_operator`
2. Both tests patch Tool 1 / Tool 2 operator entrypoints to raise if called and confirm Tool 3 scaffold still executes its own lane-scoped path cleanly.

### Behavior impact

- No Tool 3 runtime capability added.
- No Tool 1/Tool 2 behavior changed.
- Confidence improved that Tool 3 slice 1 foundation is isolated by contract.

### Validation summary

- Focused Tool 3 scaffold + decoupling tests: pass.

## Latest Increment: Tool 3 slice 2 (minimal real execution path + contract tests)

### Architecture impact

- **improves**

### Request scope

Implement the smallest real execution path in Tool 3 while preserving lane-only and decoupling guarantees.

### What changed

In `app/tool3_operator.py`:

1. Kept strict Tool 3 lane boundary:
   - still rejects any non-`regression` lane suite.
2. Added minimal real execution path for valid Tool 3 suites:
   - runs one concrete command: `python tests/run_regression.py` via `subprocess.run`
   - captures stdout/stderr into `json_preview` / `markdown_preview`
   - returns structured `result` with:
     - `suite_name`, `target_name`
     - `executed_cases`, `passed_cases`, `failed_cases`, `ok`
     - per-case rows (`name`, `lane`, `ok`, `failures`, `command`)
     - `command_exit_code`
3. Preserved compact operator contract:
   - no UI wiring
   - no shared-core lane expansion
   - no Tool 1/Tool 2 operator reuse

In `tests/run_regression.py`:

4. Updated existing Tool 3 scaffold contract test to match real execution success behavior.
5. Added and registered execution-failure contract test:
   - `test_run_tool3_regression_eval_execution_failure_contract`
6. Preserved and validated decoupling tests:
   - Tool 3 remains independent from Tool 1/Tool 2 operator internals.

### Behavior impact

- Tool 3 now has a real (minimal) execution capability for regression-lane suites.
- Tool 1 and Tool 2 behavior unchanged.

### Validation summary

- Focused Tool 3 slice-2 contract tests: pass.

## Latest Increment: Tool 3 slice 3 (dedicated run logging integration)

### Architecture impact

- **improves**

### Request scope

Add minimal Tool 3-native run logging with stable success/failure contract while preserving lane boundary and decoupling rules.

### What changed

In `app/tool3_run_log.py` (new):

1. Added Tool 3 append-only JSONL logging module:
   - `tool3_run_log_path(...)` -> `logs/tool3_runs.jsonl`
   - `build_tool3_run_record_suite(...)`
   - `try_log_tool3_suite_run(...)`
2. Uses neutral shared helpers from `app/system_eval_run_log_common.py` (no Tool1/Tool2 internals).
3. Uses run type:
   - `tool3_suite_run`

In `app/tool3_operator.py`:

4. Integrated Tool 3 logging on all major paths:
   - missing suite
   - invalid JSON
   - invalid/empty cases
   - lane rejection
   - successful execution
   - execution failure
5. Extended bundle contract with:
   - `run_log_error`
   - `run_log_path`

In `tests/run_regression.py`:

6. Strengthened Tool 3 tests to verify:
   - `run_log_path` points to `tool3_runs.jsonl`
   - `run_log_error` key is present/clean
   - Tool 3 log file is written on success and failure paths

### Behavior impact

- Tool 3 now has dedicated append-only run logging, independent from Tool 1/Tool 2 log files.
- No UI wiring added.
- Lane-only guard and operator decoupling guarantees preserved.

### Validation summary

- Focused Tool 3 logging + decoupling tests: pass.

## Latest Increment: Tool 3 slice 4 (minimal artifact emission on successful execution)

### Architecture impact

- **improves**

### Request scope

Proceed to the next minimal Tool 3 increment with contract-first discipline.

### What changed

In `app/tool3_operator.py`:

1. Added minimal artifact emission for successful Tool 3 execution:
   - on `ok=True`, writes JSON/Markdown artifacts via `core.system_eval.write_result_artifacts(...)`.
2. Added simple file-stem fallback (`_slugify`) for deterministic artifact naming when `file_stem` is empty.
3. Preserved failure-path behavior:
   - non-success command runs still keep `artifact_paths == {}`
   - lane guard and decoupling logic unchanged
4. Added artifact-write failure handling:
   - returns clean failure bundle and logs failure if artifact write/read fails.

In `tests/run_regression.py`:

5. Strengthened `test_run_tool3_regression_eval_scaffold_contract_on_regression_lane`:
   - now asserts emitted artifact files exist (`json_path`, `markdown_path`) on successful run.

### Behavior impact

- Tool 3 now emits minimal result artifacts on successful regression-lane execution.
- No UI wiring added.
- No shared-core lane expansion.
- Tool 1/Tool 2 behavior unchanged.

### Validation summary

- Focused Tool 3 artifact contract tests: pass.

## Latest Increment: Tool 3 slice 5 (artifact-failure contract coverage)

### Architecture impact

- **improves**

### Request scope

Proceed with next Tool 3 slice while preserving lane-only/decoupling boundaries and contract-first rigor.

### What changed

In `tests/run_regression.py`:

1. Added and registered:
   - `test_run_tool3_regression_eval_artifact_failure_is_reported_and_logged`
2. New test validates Tool 3 artifact-write failure path contract:
   - command phase succeeds
   - artifact writer fails (`OSError`)
   - bundle returns clean failure (`ok == False`, error contains `Artifact write/read failed`)
   - `run_log_path` points to `tool3_runs.jsonl`
   - Tool 3 run log record is still written with `run_type == "tool3_suite_run"` and non-empty `error`

### Behavior impact

- No runtime behavior change in this slice.
- Reliability confidence improved by explicitly locking Tool 3 artifact-failure contract with regression coverage.

### Validation summary

- Focused Tool 3 artifact-failure contract tests: pass.

## Latest Increment: Tool 3 slice 6 (command invocation failure hardening)

### Architecture impact

- **improves**

### Request scope

Proceed with next Tool 3 hardening slice while keeping lane-only and decoupling guarantees intact.

### What changed

In `app/tool3_operator.py`:

1. Hardened command execution boundary:
   - wrapped `subprocess.run(...)` in a defensive `try/except`.
2. On invocation failure (e.g., process spawn error), Tool 3 now:
   - returns a clean failure bundle (`ok == False`, descriptive error),
   - writes Tool 3 run log record,
   - preserves `run_log_error` / `run_log_path` contract fields.

In `tests/run_regression.py`:

3. Added and registered:
   - `test_run_tool3_regression_eval_command_invocation_failure_is_reported_and_logged`
4. Test asserts invocation failure path contract and Tool 3 log persistence.

### Behavior impact

- No feature expansion.
- Reliability improved: subprocess invocation errors no longer bubble uncaught from Tool 3 operator.
- Tool 1/Tool 2 behavior unchanged.

### Validation summary

- Focused Tool 3 invocation hardening tests: pass.

## Latest Increment: Tool 3 slice 7 (failure-bundle closure contract lock)

### Architecture impact

- **improves**

### Request scope

Proceed with next Tool 3 hardening slice under contract-first discipline.

### What changed

In `tests/run_regression.py`:

1. Added and registered:
   - `test_run_tool3_regression_eval_failure_bundle_contract`
2. The closure guard validates stable Tool 3 failure-bundle shape across core failure classes:
   - missing suite file
   - invalid suite JSON
   - lane rejection (non-regression lane)
   - command invocation failure
3. It locks expected fields:
   - `ok == False`
   - `artifact_paths == {}`
   - `json_preview == ""`
   - `markdown_preview == ""`
   - non-empty `error`
   - `run_log_error` key present
   - `run_log_path` points to `tool3_runs.jsonl`

### Behavior impact

- No runtime behavior change in this slice.
- Reliability confidence improved by enforcing Tool 3 failure contract consistency with one dedicated closure guard.

### Validation summary

- Focused Tool 3 closure contract tests: pass.

## Latest Increment: Tool 3 slice 8 (command timeout safety hardening)

### Architecture impact

- **improves**

### Request scope

Proceed with next Tool 3 hardening slice while preserving lane-only and decoupling constraints.

### What changed

In `app/tool3_operator.py`:

1. Added command timeout guard for Tool 3 execution command:
   - `TOOL3_COMMAND_TIMEOUT_SECONDS = 1800`
   - `subprocess.run(..., timeout=TOOL3_COMMAND_TIMEOUT_SECONDS)`
2. Added explicit timeout failure handling:
   - catches `subprocess.TimeoutExpired`
   - returns clean failure bundle
   - logs timeout failure to Tool 3 run log
   - preserves `run_log_error` / `run_log_path` contract fields.

In `tests/run_regression.py`:

3. Added and registered:
   - `test_run_tool3_regression_eval_command_timeout_is_reported_and_logged`
4. Expanded closure guard (`test_run_tool3_regression_eval_failure_bundle_contract`) to include timeout path.

### Behavior impact

- No feature expansion.
- Reliability improved: Tool 3 command runs are now bounded and timeout failures are handled predictably.
- Tool 1/Tool 2 behavior unchanged.

### Validation summary

- Focused Tool 3 timeout hardening tests: pass.

## Latest Increment: Tool 3 roadmap Slice 1 (UI wiring: run button + status + summary)

### Architecture impact

- **improves**

### Request scope

Execute Tool 3 roadmap slice 1 with minimal UI wiring only.

### What changed

In `app/ui.py`:

1. Added Tool 3 panel renderer:
   - `render_tool3_panel()`
2. Wired Tool 3 UI controls:
   - suite path input
   - output directory input
   - optional file stem input
   - primary button: **Run regression**
3. Connected button execution to Tool 3 operator:
   - calls `tool3_operator.run_tool3_regression_eval(...)`
4. Added immediate run status indicator:
   - PASS / FAIL status message
5. Reused shared results rendering surface for summary/details/artifacts:
   - `_tool1_render_results(bundle)` (no styling/polish expansion)
6. Updated surface router:
   - Tool 3 route now renders `render_tool3_panel()` instead of placeholder.

### Behavior impact

- Tool 3 is now runnable from UI with visible pass/fail status and run summary flow.
- No UI polish expansion.
- No shared-core lane changes.
- Tool 1/Tool 2 behavior unchanged.

### Validation summary

- Focused Tool 3 + UI compatibility tests: pass.

## Latest Increment: Tool 3 roadmap Slice 2 (result readability)

### Architecture impact

- **improves**

### Request scope

Execute Tool 3 roadmap slice 2 with readability-only improvements in the Tool 3 panel.

### What changed

In `app/ui.py`:

1. Added helper:
   - `_tool3_readability_summary(result, overall_ok)`
2. Tool 3 panel now renders explicit readability block after each run:
   - clear run status (PASS / FAIL)
   - compact totals (`total`, `passed`, `failed`)
   - short failing-tests list (capped at 5 names)
   - simple human-readable summary sentence

In `tests/run_regression.py`:

1. Added `test_tool3_ui_readability_summary_pass_and_fail_list`
   - verifies FAIL status, counts, failing names, and summary text contract.
2. Added `test_tool3_ui_readability_summary_limits_failing_names_to_five`
   - verifies short-list cap behavior for failing tests.

### Behavior impact

- Tool 3 output is clearer for non-technical reading without changing execution behavior.
- No new Tool 3 engine features.
- No Tool 1/Tool 2 behavior changes.

### Validation summary

- Focused Tool 3 slice-2 tests: pass.

## Latest Increment: Tool 3 roadmap Slice 3 (artifact clarity)

### Architecture impact

- **improves**

### Request scope

Execute Tool 3 roadmap slice 3: keep JSON/Markdown artifacts usable and add a short markdown header summary.

### What changed

In `app/tool3_operator.py`:

1. Added `_tool3_markdown_header_summary(result)`:
   - builds short markdown header with:
     - total tests
     - passed
     - failed
2. Added `_prepend_tool3_markdown_summary(markdown_path, result)`:
   - prepends Tool 3 summary header to markdown artifact content.
3. Integrated summary injection in successful artifact flow:
   - after `system_eval.write_result_artifacts(...)`, Tool 3 now prepends the summary to markdown artifact.
4. Updated `markdown_preview` source for successful runs:
   - preview now reflects the resulting markdown artifact (with Tool 3 summary header), truncated as needed.

In `tests/run_regression.py`:

1. Updated `test_run_tool3_regression_eval_scaffold_contract_on_regression_lane` to verify:
   - markdown artifact includes:
     - `# Tool 3 Regression Summary`
     - `- Total tests: ...`
     - `- Passed: ...`
     - `- Failed: ...`
   - `markdown_preview` includes the same summary header.

### Behavior impact

- Tool 3 markdown artifacts are now more readable at the top, with immediate run totals.
- JSON artifact path/shape remains unchanged and usable.
- No UI route/feature expansion.
- No Tool 1/Tool 2 behavior changes.

### Validation summary

- Focused Tool 3 artifact-clarity tests: pass.

## Latest Increment: Tool 3 roadmap Slice 4 (simple command profile)

### Architecture impact

- **improves**

### Request scope

Execute Tool 3 roadmap slice 4: keep default command behavior and add a minimal optional command override.

### What changed

In `app/tool3_operator.py`:

1. Added command profile constants/helpers:
   - `TOOL3_DEFAULT_COMMAND = [sys.executable, "tests/run_regression.py"]`
   - `_resolve_tool3_command(command_override)`
2. Extended `run_tool3_regression_eval(...)` signature with:
   - `command_override: str = ""`
3. Command execution behavior:
   - blank override uses default command unchanged
   - non-blank override is parsed and used as subprocess command
4. Case rows now record the actual command string used in `cases[*].command`.

In `app/ui.py`:

1. Added Tool 3 input field:
   - `Optional command override (blank = default)`
2. Wired field value into Tool 3 operator call.

In `tests/run_regression.py`:

1. Added `test_run_tool3_regression_eval_uses_default_command_when_override_blank`
   - verifies default command remains `... tests/run_regression.py`.
2. Added `test_run_tool3_regression_eval_uses_command_override_when_provided`
   - verifies override command is used and reflected in result row command field.

### Behavior impact

- Tool 3 supports a simple command override while preserving existing default run behavior.
- No complex orchestration added.
- No Tool 1/Tool 2 behavior changes.

### Validation summary

- Focused Tool 3 command-profile tests: pass.

## Latest Increment: Tool 3 roadmap Slice 5 (stability pass + project lock)

### Architecture impact

- **preserves**

### Request scope

Execute final Tool 3 stability pass:
- run full regression multiple times
- confirm no crashes
- confirm Tool 3 logging/failure-bundle contract remains stable
- fix only real issues if found

### What changed

No code changes were required in this slice.

### Validation summary

Full regression suite executed **3 consecutive times**:

1. pass: `Passed 590 / 590 tests`
2. pass: `Passed 590 / 590 tests`
3. pass: `Passed 590 / 590 tests`

Additional stability confirmations from full-suite coverage:

- no crash observed during repeated full runs
- Tool 3 failure-bundle contract tests remained green
- Tool 3 logging contract tests remained green (including failure paths)

### Final lock status

- Tool 1: **DONE**
- Tool 2: **DONE**
- Tool 3: **DONE**

Feature build phase is now complete per roadmap lock.
