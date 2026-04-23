# !JESSY Tool 1 Manual and Templates

Project: AI Agent  
Scope: Tool 1 only (short operator manual + ingestion-ready templates)

---

## 1) Tool 1 purpose

Tool 1 is the API execution and validation tool.

Use Tool 1 to:
- run real HTTP requests
- validate status, headers, body, and JSON expectations
- produce JSON/Markdown evidence artifacts
- write append-only run logs

Do not use Tool 1 to:
- evaluate LLM output quality (use Tool 2)
- run regression profile comparisons (use Tool 3)

---

## 2) UI location and controls

In `app/ui.py`, open the **Tool 1** surface.

Main controls:
- Output directory
- Single request area (`Send request`)
- Suite path / file stem / fail-fast
- `Run system eval` button for suite runs

Main outputs shown in UI:
- Run summary (pass/fail and counts)
- Detailed per-case table and case details
- Artifact paths
- Markdown preview
- JSON preview

---

## 3) Execution flow (confirmed)

Tool 1 suite flow:

UI (`app/ui.py`)  
-> `app/system_eval_operator.py` `run_tool1_system_eval_http(...)`  
-> `core/system_eval.py` `load_suite_file(...)`  
-> `core/system_eval.py` `execute_suite(...)`  
-> `core/system_eval.py` `write_result_artifacts(...)`  
-> `app/tool1_run_log.py` `try_log_suite_run(...)`  
-> `logs/tool1_runs.jsonl`  
-> UI rendering

---

## 4) Core contracts (short)

### Input contract

`run_tool1_system_eval_http(...)` takes:
- `suite_path: str`
- `output_dir: str`
- `file_stem: str = ""`
- `project_root: Path | None = None`
- `adapter = None`
- `fail_fast: bool = False`
- `default_timeout_seconds: int = 20`

### Return contract

Returns bundle keys:
- `ok`
- `result`
- `artifact_paths`
- `json_preview`
- `markdown_preview`
- `error`
- `run_log_error`

---

## 5) Artifact and log locations

- Run log: `logs/tool1_runs.jsonl`
- Default artifact folder (UI default): `logs/system_eval`
- Artifact files:
  - `<file_stem>.json`
  - `<file_stem>.md`

---

## 6) Failure behavior (operator rules)

- Missing suite file -> failure bundle + failure log record
- Invalid suite JSON -> failure bundle + failure log record
- Empty `cases` -> validation error + failure bundle + failure log record
- Auth failures (401/403) are treated as normal HTTP results and fail assertions/default status checks

---

## 7) Tool 1 decision criteria (ingestion-ready)

Use Tool 1 when:
- validating real API endpoint behavior
- requiring HTTP truth (status/headers/body)
- collecting repeatable evidence artifacts
- debugging integration failures with real execution

Do not use Tool 1 when:
- evaluating prompt/response quality (Tool 2)
- running regression profile workflows (Tool 3)
- doing reasoning-only analysis without execution

---

## 8) Raw-chat template (copy/paste into `memory/raw_chat.txt`)

```text
USER: TOOL 1 DECISION CRITERIA
ASSISTANT: Use Tool 1 when validating real API endpoint behavior under actual execution conditions.
USER: Use Tool 1 when HTTP level truth is required including status headers and body verification.
ASSISTANT: Use Tool 1 when repeatable evidence artifacts are required for audit client proof and run history.
USER: Use Tool 1 when debugging integration failures that require real request response validation.
ASSISTANT: Do not use Tool 1 for evaluating LLM output quality and use Tool 2 for prompt response evaluation.
USER: Do not use Tool 1 for historical regression comparison flows and use Tool 3 for regression execution.
ASSISTANT: Do not use Tool 1 for pure reasoning about expected behavior without execution evidence.
```

---

## 9) Minimal ingestion run commands

```bash
python memory/import_chat.py
python memory/extractors/run_extractor.py
```

---

## 10) ChatGPT diagnostic request format (archived)

Use this exact request format when asking for Tool 1 contract extraction:

```text
Project name: AI Agent

TOOL 1 — EXTRACTION DATA REQUEST
DIAGNOSTIC ONLY — NO CODE CHANGES

I need exact factual data about Tool 1 to build knowledge ingestion entries.

Please answer clearly and precisely.

1. INPUT CONTRACT

* What exact inputs does run_tool1_system_eval_http(...) expect?
* List parameters with names and types if possible

2. OUTPUT CONTRACT

* What is the exact structure of the result returned to UI?
* Show keys (e.g., ok, passed_cases, failed_cases, artifacts, etc.)

3. ARTIFACT STRUCTURE

* What fields exist inside the JSON artifact?
* What fields exist inside the Markdown artifact?

4. FAILURE DETAILS

* When a test case fails, what exact fields are produced?
* Show one example failure structure

5. LOG ENTRY STRUCTURE

* What fields are written into logs/tool1_runs.jsonl?
* Show one full example log entry

6. ASSERTION ENGINE

* Where are assertions evaluated?
* What assertion types are implemented in code (exact list)

7. EXECUTION FLOW (CONFIRM)

* Confirm exact function chain:
  UI → ? → ? → core/system_eval.py → ? → logs

8. EDGE CASES

* What happens if:

  * suite file missing
  * invalid JSON
  * empty cases
  * auth failure

IMPORTANT:

* No assumptions
* No summaries
* Provide real field names and structures
* If unsure, say unsure
```

---

## 11) Tool 1 diagnostic answer pack (consolidated)

This section is the compact, copy-safe diagnostic answer for ingestion and reference.

### 11.1 Input contract

`run_tool1_system_eval_http(...)` signature:

```python
def run_tool1_system_eval_http(
    suite_path: str,
    output_dir: str,
    file_stem: str = "",
    *,
    project_root: Path | None = None,
    adapter=None,
    fail_fast: bool = False,
    default_timeout_seconds: int = 20,
)
```

### 11.2 Output contract

Returned bundle keys:

```json
{
  "ok": "bool",
  "result": "dict | null",
  "artifact_paths": "dict",
  "json_preview": "str",
  "markdown_preview": "str",
  "error": "str | null",
  "run_log_error": "str | null"
}
```

`result` top-level keys:
- `suite_name`
- `target_name`
- `executed_cases`
- `passed_cases`
- `failed_cases`
- `ok`
- `elapsed_seconds`
- `ran_at_utc`
- `cases`

### 11.3 Artifact structure

JSON artifact:
- full serialized `result`

Markdown artifact contains:
- report title
- target/status/executed/passed/failed/elapsed summary lines
- case result lines
- failure lines
- optional step sections
- optional stability/consistency attempt details

### 11.4 Failure detail shape

Per failing case includes:
- `name`
- `ok: false`
- `failures` (list)
- `status_code`
- `latency_ms`
- `response_headers`
- `output_preview`
- `output_full`
- `method`
- `url`
- lane/attempt fields when present

### 11.5 Log entry shape (`logs/tool1_runs.jsonl`)

Top-level keys:
- `schema_version`
- `run_timestamp_utc`
- `run_type`
- `suite_source_path`
- `suite_name`
- `target_name`
- `configuration`
- `requests`
- `auth_mode`
- `query_params_raw_json`
- `result_summary`
- `cases_outcome`
- `artifact_paths`
- `error`
- `project_root`
- `summary`
- `request_input_snapshot` (single request)

### 11.6 Assertion engine location

Assertions are evaluated in `core/system_eval.py`:
- `_evaluate_single_attempt(...)`
- `_assert_output_matches(...)`

Implemented Tool 1 assertion names:
- `expected_status`
- `expected_status_in`
- `expected_status_not`
- `expected_headers`
- `expected_headers_contains`
- `expected_header_exists`
- `expected_json`
- `expected_json_exists`
- `expected_json_values`
- `expected_json_absent`
- `max_duration_ms`
- `expected_latency_ms_max`
- `expected_body_not_empty`
- `expected_body_size_bytes_max`
- `expected_response_time_ms_range`

Legacy/assertions-map keys also active:
- `status_code`
- `expected_response_time_ms`
- `contains_all`
- `not_contains`
- `equals`
- `regex`
- `body_contains`
- `body_equals`
- `body_regex`
- `body_json_path_equals`
- `body_json_has_key`
- `body_json_array_length_equals`
- `body_json_array_length_at_least`
- `body_json_array_length_at_most`
- `header_equals`
- `header_regex`
- `header_contains`
- `extract`

### 11.7 Execution flow confirmation

`app/ui.py`  
-> `app/system_eval_operator.py::run_tool1_system_eval_http`  
-> `core/system_eval.py::load_suite_file`  
-> `core/system_eval.py::execute_suite`  
-> `core/system_eval.py::write_result_artifacts`  
-> `app/tool1_run_log.py::try_log_suite_run`  
-> `logs/tool1_runs.jsonl`

### 11.8 Edge cases

- missing suite file: failure bundle + failure log attempt
- invalid suite JSON: failure bundle + failure log attempt
- empty `cases`: validation error + failure bundle + failure log attempt
- auth failure (401/403): handled as normal HTTP result; assertions/default status may fail

---

## 12) Raw-chat template library (all created in this session)

### 12.1 Decision-criteria template (short)

```text
USER: TOOL 1 DECISION CRITERIA
ASSISTANT: Use Tool 1 when validating real API endpoint behavior under actual execution conditions.
USER: Use Tool 1 when HTTP level truth is required including status headers and body verification.
ASSISTANT: Use Tool 1 when repeatable evidence artifacts are required for audit client proof and run history.
USER: Use Tool 1 when debugging integration failures that require real request response validation.
ASSISTANT: Do not use Tool 1 for evaluating LLM output quality and use Tool 2 for prompt response evaluation.
USER: Do not use Tool 1 for historical regression comparison flows and use Tool 3 for regression execution.
ASSISTANT: Do not use Tool 1 for pure reasoning about expected behavior without execution evidence.
```

### 12.2 Full Tool 1 manual transcript template (long)

```text
USER: TOOL 1 OPERATOR MANUAL CORE IDENTITY
ASSISTANT: Tool 1 is the API testing execution system in this project and it is used to run HTTP system eval tests and produce evidence artifacts.
USER: Tool 1 belongs to the execution layer and not the reasoning layer and its job is real request execution validation and run evidence generation.
ASSISTANT: Tool 1 must be used when the operator needs objective API pass fail proof and repeatable test outputs.
USER: TOOL 1 UI LOCATION MAP
ASSISTANT: In the Streamlit app Tool 1 is the surface named Tool 1 and it is selected from the top navigation or sidebar navigation.
USER: In Tool 1 panel the operator sees output directory controls single request controls suite run controls result summary detailed results and artifact preview areas.
ASSISTANT: The Tool 1 main run actions are Send Request for a single call and Run system eval for suite execution from JSON.
USER: TOOL 1 SINGLE REQUEST USAGE
ASSISTANT: Single request mode is used for fast endpoint smoke checks without creating a suite file.
USER: Single request inputs include method URL query params headers auth mode and optional JSON body and timeout.
ASSISTANT: Tool 1 single request follows the same core execution path and writes artifacts and run logs like suite mode.
USER: TOOL 1 SUITE MODE USAGE
ASSISTANT: Suite mode is used for repeatable validations where multiple cases and assertions are defined in a suite JSON file.
USER: Suite mode requires suite path output directory optional file stem and optional fail fast toggle.
ASSISTANT: Fail fast true stops execution at first failing case and fail fast false executes all suite cases.
USER: TOOL 1 AUTH OPERATING RULES
ASSISTANT: Tool 1 auth must be supplied at runtime via UI controls or safe runtime config and secrets must not be hardcoded in suite files.
USER: Tool 1 supports auth patterns including bearer basic and api key style headers during runtime execution.
ASSISTANT: Sensitive auth material is protected by redaction logic in logging paths so evidence stays usable while secrets are masked.
USER: TOOL 1 ASSERTION MODEL
ASSISTANT: Tool 1 evaluates assertions per case and returns pass fail outcomes with explicit failure messages for operator diagnosis.
USER: Tool 1 supports status checks header checks body checks json structure checks timing checks and negative checks including not and absent expectations.
ASSISTANT: Tool 1 assertions are grouped as core and advanced in UI presentation while engine behavior remains contract driven.
USER: TOOL 1 OUTPUTS ARTIFACTS LOGGING
ASSISTANT: Every Tool 1 run can produce JSON artifact and Markdown artifact and each run is recorded in append only run logs.
USER: Tool 1 run log path is logs/tool1_runs.jsonl and each record contains request context outcomes summary and artifact references.
ASSISTANT: Artifact previews in UI provide quick inspection while full files remain the source of record for audits and proof.
USER: TOOL 1 OPERATOR INTERPRETATION RULES
ASSISTANT: The operator should read run summary first then inspect failed case names then open detailed case failures and response snapshots.
USER: A failing run is not final diagnosis until failure lines headers body preview full body and latency values are reviewed together.
ASSISTANT: A passing run means configured checks passed and does not imply checks that were not explicitly configured.
USER: TOOL 1 WIRING AND OWNERSHIP
ASSISTANT: UI calls the Tool 1 operator and the operator calls the shared evaluation engine then artifacts and logs are written and results return to UI.
USER: Tool 1 execution entrypoint is the Tool 1 operator function run_tool1_system_eval_http from the UI layer.
ASSISTANT: Shared engine logic is in core system eval and Tool 1 specific orchestration and logging remain in Tool 1 owned modules.
USER: Tool 1 must stay isolated from Tool 2 prompt response logic and Tool 3 regression logic except for approved shared core utilities.
ASSISTANT: Cross tool pollution is not allowed and ownership boundaries are required for reliability and maintainability.
USER: TOOL 1 TROUBLESHOOTING PLAYBOOK
ASSISTANT: If suite file is not found first verify path and file name then confirm working directory and rerun.
USER: If auth failures appear verify runtime auth input header names token format and environment source before changing assertions.
ASSISTANT: If JSON assertions fail compare expected keys and values against actual response body and confirm top level versus nested expectations.
USER: If timing assertions fail confirm endpoint health network condition timeout settings and expected latency thresholds.
ASSISTANT: If run log warnings appear check write permissions and path validity because run display can still be valid even when logging fails.
USER: TOOL 1 BEST PRACTICE OPERATION
ASSISTANT: Start with single request smoke then migrate stable checks into suite files and use suite mode for repeatable evidence.
USER: Keep assertions minimal at first then add stricter checks incrementally to avoid noisy false failures.
ASSISTANT: Use artifact markdown for human review and artifact json for machine verification and audit workflows.
USER: Tool 1 should be run daily for target APIs tied to client critical paths to build proof reliability history.
ASSISTANT: Durable operator rule is execute review log refine assertions rerun and preserve clean evidence trails.
USER: TOOL 1 FINAL OPERATOR MEMORY ANCHOR
ASSISTANT: Tool 1 is the trusted API execution machine for this project and the correct operator behavior is safe auth precise assertions disciplined review and evidence first decisions.
```

---

## 13) Tool 1 clean content (atomic memory entries)

```text
TOOL 1 — CLEAN CONTENT (ATOMIC MEMORY ENTRIES)

* Tool 1 is the API testing execution system that runs HTTP system evaluation suites and produces structured validation results and artifacts.

* Tool 1 operates in the execution layer and performs real API requests; it does not perform reasoning.

* The Tool 1 execution entrypoint is run_tool1_system_eval_http located in app/system_eval_operator.py.

* Tool 1 accepts a suite JSON file, executes defined test cases, and evaluates assertions against real API responses.

* Tool 1 produces a structured result containing executed cases, passed cases, failed cases, total duration, and per-case outcomes.

* Each test case result includes status code, latency, response headers, output preview, full response body, and failure messages if applicable.

* Tool 1 generates two artifacts per run: a JSON artifact for machine use and a Markdown report for human review.

* Tool 1 writes append-only run logs to logs/tool1_runs.jsonl containing request data, results summary, case outcomes, and artifact references.

* Tool 1 evaluates assertions including status checks, header checks, JSON structure checks, response time checks, and negative conditions such as absence or mismatch.

* Tool 1 should be used when real API execution is required to validate endpoint behavior under actual conditions.

* Tool 1 should be used when HTTP-level truth is required, including verification of status codes, headers, and response bodies.

* Tool 1 should be used when debugging integration issues that require observing real request and response data.

* Tool 1 should not be used for evaluating LLM output quality; that is handled by Tool 2.

* Tool 1 should not be used for regression comparison workflows; that is handled by Tool 3.

* Tool 1 treats authentication failures as normal HTTP responses (e.g., 401 or 403) and evaluates them through assertions.

* Tool 1 returns a failure bundle when execution cannot proceed, including missing suite file, invalid JSON, or empty test cases.

* A failing test run must be analyzed by reviewing failure messages, response headers, response body, and latency together before drawing conclusions.

* A passing run confirms only the assertions that were explicitly defined; it does not guarantee untested conditions.

* Tool 1 must remain isolated from Tool 2 and Tool 3 logic, except for shared core utilities.

* Proper Tool 1 operation follows a loop: execute tests -> review results -> refine assertions -> rerun -> preserve artifacts as evidence.
```

