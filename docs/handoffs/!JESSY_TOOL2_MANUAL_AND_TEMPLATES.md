# !JESSY Tool 2 Manual and Templates

Project: AI Agent  
Scope: Tool 2 prompt/response operator reference and extraction content

---

## 1) ChatGPT request (exact archived prompt)

```text
Project name: AI Agent

TOOL 2 — FULL EXTRACTION DATA REQUEST
DIAGNOSTIC ONLY — DO NOT CHANGE ANY CODE

Do not edit, refactor, or modify anything.
Do not summarize loosely.
Return exact structures, field names, and real behavior.

Goal:
Provide complete factual data required to build knowledge ingestion entries for Tool 2 (prompt/response testing system).

---

1. TOOL 2 IDENTITY

* What is Tool 2 in this system?
* What is its exact purpose?
* What type of problems does it solve?

---

2. ENTRYPOINT AND FUNCTION SIGNATURE

* What is the main Tool 2 execution function?
* Show exact function name and full signature
* Include parameter names, types, and defaults

---

3. INPUT CONTRACT

* What inputs does Tool 2 accept?

* List all fields required to run:

  * prompt
  * expected output
  * test cases
  * evaluation config
  * any optional parameters

* Show exact structure for:

  * single test
  * multi-case evaluation (if exists)

---

4. OUTPUT CONTRACT

* What does Tool 2 return?
* Show full return structure with keys and types

Example:

* ok
* score
* passed_cases
* failed_cases
* evaluation_details
* error

(Use real structure, not guess)

---

5. EVALUATION MODEL

* How does Tool 2 evaluate responses?

List all evaluation types implemented:

* exact match

* contains

* semantic similarity

* regex

* scoring system

* ranking

* etc.

* Where is evaluation logic implemented (file + function)?

---

6. RESPONSE ANALYSIS STRUCTURE

* For each test case, what fields are produced?

Example:

* input prompt
* model output
* expected output
* pass/fail
* score
* mismatch explanation

Provide exact structure.

---

7. ARTIFACTS (IF ANY)

* Does Tool 2 generate artifacts?
* If yes:

  * JSON structure
  * Markdown structure

---

8. LOGGING

* Does Tool 2 log runs?
* If yes:

  * file path
  * structure of log entry
  * example entry

---

9. EXECUTION FLOW

Confirm full pipeline:

UI → ? → ? → evaluation engine → ? → logs → UI

List exact file paths and function calls.

---

10. FAILURE MODES

What happens when:

* invalid input
* missing expected output
* model error
* empty result
* evaluation crash

Show exact returned structure.

---

11. TOOL BOUNDARIES

* What Tool 2 does NOT do
* When Tool 2 should NOT be used
* How it differs from:

  * Tool 1
  * Tool 3

---

12. REAL EXAMPLE

Provide ONE real example:

Input:

* prompt
* expected output

Output:

* actual result structure

---

IMPORTANT RULES:

* No assumptions
* No paraphrasing
* Use exact field names from code
* If unsure, say "unsure"
* Prefer real examples over explanations
```

---

## 2) Diagnostic reply (exact archived output)

```text
Project name: AI Agent

TOOL 2 — FULL EXTRACTION DATA REQUEST
DIAGNOSTIC ONLY — DO NOT CHANGE ANY CODE

1) TOOL 2 IDENTITY

- Tool 2 is the prompt/response evaluation path that runs suite cases where lane == "prompt_response".
- Exact purpose: execute prompt inputs through a prompt adapter, validate response text against configured response expectations, and produce artifacts/logs.
- Problems solved:
  - contract testing of prompt outputs
  - pass/fail validation for response content/format/length
  - repeatable evidence logging for prompt-response checks

2) ENTRYPOINT AND FUNCTION SIGNATURE

Main execution function:
- app/tool2_operator.py :: run_tool2_prompt_response_eval

Exact signature:
def run_tool2_prompt_response_eval(
    suite_path: str,
    output_dir: str,
    file_stem: str = "",
    *,
    project_root: Path | None = None,
    adapter=None,
    fail_fast: bool = False,
    default_timeout_seconds: int = 20,
)

3) INPUT CONTRACT

Tool 2 operator inputs:
- suite_path: str
- output_dir: str
- file_stem: str (default "")
- project_root: Path | None (kw-only, default None)
- adapter: object | None (kw-only, default None)
- fail_fast: bool (kw-only, default False)
- default_timeout_seconds: int (kw-only, default 20, must be integer >= 1)

Suite-level requirements (after load/validate):
- suite must be JSON object
- suite.cases must be non-empty array
- all cases must have lane == "prompt_response"

Per-case required fields for prompt_response lane:
- name: non-empty string
- lane: "prompt_response"
- prompt_input: non-empty string
- expected_response_contains: non-empty array of non-empty strings

Per-case optional prompt_response fields:
- expected_response_not_contains: array of non-empty strings
- expected_response_regex: non-empty regex string
- expected_response_starts_with: non-empty string
- expected_response_ends_with: non-empty string
- expected_response_equals: non-empty string
- expected_response_length_min: non-negative integer
- expected_response_length_max: non-negative integer
- assertions: object (can be {})
- headers: object (optional, typically {})
- payload: object (optional, typically {})

Validation bound:
- if both length min/max provided: expected_response_length_min <= expected_response_length_max

Single test case structure example (real file style):
{
  "name": "hello_world_smoke",
  "lane": "prompt_response",
  "prompt_input": "Say exactly: hello world",
  "expected_response_contains": ["hello", "world"],
  "assertions": {}
}

Multi-case suite structure example (real file):
{
  "suite_name": "tool2_prompt_response_smoke",
  "target_name": "llm_prompt_response",
  "cases": [
    { ...case1... },
    { ...case2... }
  ]
}

4) OUTPUT CONTRACT

run_tool2_prompt_response_eval(...) return bundle keys:
{
  "ok": bool,
  "result": dict | null,
  "artifact_paths": dict,
  "json_preview": str,
  "markdown_preview": str,
  "error": str | null,
  "run_log_error": str | null,
  "run_log_path": str | null
}

Failure bundle exact shape:
{
  "ok": false,
  "result": dict | null,
  "artifact_paths": {},
  "json_preview": "",
  "markdown_preview": "",
  "error": "<message>",
  "run_log_error": "<message|null>",
  "run_log_path": "<path|null>"
}

result object (from core/system_eval.execute_suite):
{
  "suite_name": str,
  "target_name": str,
  "executed_cases": int,
  "passed_cases": int,
  "failed_cases": int,
  "ok": bool,
  "elapsed_seconds": float,
  "ran_at_utc": str,
  "cases": [ ... ]
}

5) EVALUATION MODEL

Where logic is implemented:
- core/system_eval.py :: _execute_prompt_response_case
- called via core/system_eval.py :: execute_suite

Evaluation types actually implemented for Tool 2:
- contains check:
  - expected_response_contains
  - failure: "expected_response_missing_substring: <needle>"
- not-contains check:
  - expected_response_not_contains
  - failure: "expected_response_forbidden_substring_present: <needle>"
- regex match:
  - expected_response_regex
  - mismatch: "expected_response_regex_mismatch: <pattern>"
  - invalid regex: "expected_response_regex_invalid: <pattern>: <exc>"
- prefix check:
  - expected_response_starts_with
  - failure: "expected_response_prefix_mismatch: expected_prefix='<...>'"
- suffix check:
  - expected_response_ends_with
  - failure: "expected_response_suffix_mismatch: expected_suffix='<...>'"
- exact equality:
  - expected_response_equals
  - failure: "expected_response_exact_mismatch"
- length min:
  - expected_response_length_min
  - failure: "expected_response_length_too_short: min=<n>, got=<m>"
- length max:
  - expected_response_length_max
  - failure: "expected_response_length_too_long: max=<n>, got=<m>"

Not implemented for Tool 2 lane:
- semantic similarity scoring: not implemented
- ranking model: not implemented
- per-case numeric score field: not implemented

6) RESPONSE ANALYSIS STRUCTURE

Per-case output row for prompt_response lane:
{
  "name": str,
  "lane": "prompt_response",
  "ok": bool,
  "failures": [str, ...],
  "status_code": int | null,
  "latency_ms": int,
  "output_preview": str,
  "output_full": str,
  "response_headers": dict,
  "method": "PROMPT",
  "url": "prompt://local",
  "prompt_input": str,
  "expected_response_contains": [str, ...],
  "expected_response_not_contains": [str, ...],
  "expected_response_regex": str | null,
  "expected_response_starts_with": str | null,
  "expected_response_ends_with": str | null,
  "expected_response_equals": str | null,
  "expected_response_length_min": int | null,
  "expected_response_length_max": int | null
}

7) ARTIFACTS (IF ANY)

Yes, Tool 2 generates artifacts via core/system_eval.write_result_artifacts.

Artifact path keys in bundle:
- artifact_paths.json_path
- artifact_paths.markdown_path

JSON artifact:
- full serialized result object (same as section 4 result)

Markdown artifact structure:
- title line: "# System Eval Report: <suite_name>"
- summary bullets:
  - target
  - status
  - executed cases
  - passed
  - failed
  - elapsed seconds
- "## Case Results"
- one line per case with pass/fail + lane + method/url
- indented failure bullets for failed cases

8) LOGGING

Yes, Tool 2 logs runs.

Log file path:
- logs/tool2_runs.jsonl

Logger entrypoint:
- app/tool2_run_log.py :: try_log_tool2_suite_run
- underlying shared builder:
  - app/system_eval_run_log_common.py :: build_suite_run_record(... run_type="tool2_suite_run"...)

Log entry top-level fields (actual):
- schema_version
- run_timestamp_utc
- run_type
- suite_source_path
- suite_name
- target_name
- configuration
- requests
- auth_mode
- query_params_raw_json
- result_summary
- cases_outcome
- artifact_paths
- error
- project_root
- summary
- request_input_snapshot (present as null in suite logs)

Real example entry (from logs/tool2_runs.jsonl):
{
  "schema_version": 1,
  "run_timestamp_utc": "2026-04-22T17:08:47.764251+00:00",
  "run_type": "tool2_suite_run",
  "suite_source_path": "C:\\Users\\User\\Documents\\ai-agent\\system_tests\\suites\\tool2_prompt_demo\\tool2_prompt_response_smoke.json",
  "suite_name": "tool2_prompt_response_smoke",
  "target_name": "llm_prompt_response",
  "configuration": {
    "output_dir": "C:\\Users\\User\\Documents\\ai-agent\\logs\\system_eval",
    "file_stem": "tool2_diag_example",
    "fail_fast": false,
    "timeout_seconds": 20
  },
  "requests": [ ... ],
  "auth_mode": null,
  "query_params_raw_json": null,
  "result_summary": {
    "overall_ok": false,
    "executed_cases": 2,
    "passed_cases": 1,
    "failed_cases": 1,
    "elapsed_seconds": 8.188,
    "ran_at_utc": "2026-04-22T17:08:47.729759+00:00"
  },
  "cases_outcome": [ ... ],
  "artifact_paths": {
    "json_path": "C:\\Users\\User\\Documents\\ai-agent\\logs\\system_eval\\tool2_diag_example.json",
    "markdown_path": "C:\\Users\\User\\Documents\\ai-agent\\logs\\system_eval\\tool2_diag_example.md"
  },
  "error": null,
  "project_root": "C:\\Users\\User\\Documents\\ai-agent",
  "summary": "Suite \"tool2_prompt_response_smoke\": 2 case(s) executed, 1 passed, 1 failed. Overall run failed.",
  "request_input_snapshot": null
}

9) EXECUTION FLOW

Confirmed pipeline:
- UI: app/ui.py :: render_tool2_panel
  - button -> tool2_operator.run_tool2_prompt_response_eval(...)
- Operator: app/tool2_operator.py
  - system_eval.load_suite_file(...)
  - lane guard (all prompt_response)
  - adapter setup (_Tool2PromptAdapter if none passed)
  - system_eval.execute_suite(...)
  - system_eval.write_result_artifacts(...)
  - tool2_run_log.try_log_tool2_suite_run(...)
- Logs:
  - logs/tool2_runs.jsonl
- UI render:
  - app/ui.py :: _tool1_render_results(bundle) (shared renderer)

10) FAILURE MODES

a) invalid input: default_timeout_seconds invalid
- condition: non-int, bool, or <1
- returned:
{
  "ok": false,
  "result": null,
  "artifact_paths": {},
  "json_preview": "",
  "markdown_preview": "",
  "error": "Invalid 'default_timeout_seconds': expected integer >= 1.",
  "run_log_error": "<nullable>",
  "run_log_path": "<path>"
}

b) missing expected output (Tool 2 required expected_response_contains missing/empty)
- raised in suite validation:
  "Case '<name>' has invalid 'expected_response_contains'; expected a non-empty array of strings."
- operator returns failure bundle shape above with error set

c) model error / prompt executor exception
- _Tool2PromptAdapter catches exception and returns AdapterResult(ok=False, error="<Type>: <msg>")
- evaluation adds failure:
  "adapter_error: <error text>"
- case fails, run may continue unless fail_fast true

d) empty result text
- adapter normalizes output to string (None -> "")
- then expectation checks run; contains/regex/length checks may fail
- no dedicated "empty result" top-level error unless assertions cause case failure

e) evaluation crash (unexpected exception in execute_suite path)
- operator catches and returns failure bundle:
  error = "Suite execution failed: <Type>: <msg>"

f) suite file missing
- error: "Suite file not found: <resolved path>"
- failure bundle returned

g) invalid suite JSON
- load/validation exception text returned in failure bundle

h) lane mismatch
- if lanes != {"prompt_response"}:
  error = "Tool 2 requires all cases to use lane='prompt_response'. Found lanes: [...]"

11) TOOL BOUNDARIES

Tool 2 does NOT do:
- HTTP API endpoint verification
- HTTP header/body transport truth checks as primary mission
- regression suite orchestration role of Tool 3
- semantic similarity scoring/ranking models

When Tool 2 should NOT be used:
- API contract/status/header/body endpoint testing -> use Tool 1
- historical/full regression pass orchestration -> use Tool 3

Difference from Tool 1:
- Tool 1 executes HTTP request cases and HTTP assertions
- Tool 2 executes prompt_input cases and response-text assertions

Difference from Tool 3:
- Tool 3 runs regression command profile (test-runner execution lane)
- Tool 2 evaluates prompt-response case assertions

12) REAL EXAMPLE

Real run input:
- suite file:
  system_tests/suites/tool2_prompt_demo/tool2_prompt_response_smoke.json
- contains two cases:
  1) prompt_input: "Say exactly: hello world"
     expected_response_contains: ["hello", "world"]
  2) prompt_input: "In one short sentence, explain what onboarding means."
     expected_response_contains: ["onboarding"]

Real output result (logs/system_eval/tool2_diag_example.json):
{
  "suite_name": "tool2_prompt_response_smoke",
  "target_name": "llm_prompt_response",
  "executed_cases": 2,
  "passed_cases": 1,
  "failed_cases": 1,
  "ok": false,
  "elapsed_seconds": 8.188,
  "ran_at_utc": "2026-04-22T17:08:47.729759+00:00",
  "cases": [
    {
      "name": "hello_world_smoke",
      "lane": "prompt_response",
      "ok": true,
      "failures": [],
      "status_code": 200,
      "latency_ms": 5513,
      "output_preview": "hello world",
      "output_full": "hello world",
      "response_headers": {},
      "method": "PROMPT",
      "url": "prompt://local",
      "prompt_input": "Say exactly: hello world",
      "expected_response_contains": ["hello", "world"],
      "expected_response_not_contains": [],
      "expected_response_regex": null,
      "expected_response_starts_with": null,
      "expected_response_ends_with": null,
      "expected_response_equals": null,
      "expected_response_length_min": null,
      "expected_response_length_max": null
    },
    {
      "name": "short_explanation_smoke",
      "lane": "prompt_response",
      "ok": false,
      "failures": ["expected_response_missing_substring: onboarding"],
      "status_code": 200,
      "latency_ms": 2674,
      "output_preview": "Onboarding is the process of integrating and familiarizing new employees with a company and its culture.",
      "output_full": "Onboarding is the process of integrating and familiarizing new employees with a company and its culture.",
      "response_headers": {},
      "method": "PROMPT",
      "url": "prompt://local",
      "prompt_input": "In one short sentence, explain what onboarding means.",
      "expected_response_contains": ["onboarding"],
      "expected_response_not_contains": [],
      "expected_response_regex": null,
      "expected_response_starts_with": null,
      "expected_response_ends_with": null,
      "expected_response_equals": null,
      "expected_response_length_min": null,
      "expected_response_length_max": null
    }
  ]
}

UNSURE:
- None for structures listed above.
```

---

## 3) Tool 2 system understanding block (user-provided archive)

```text
SYSTEM UNDERSTANDING — TOOL 2 PROMPT RESPONSE EVALUATION

USER: What is Tool 2 in this system?
AI: Tool 2 is the prompt/response evaluation system that runs test suites where prompts are executed and responses are validated against defined expectations.

USER: What is the purpose of Tool 2?
AI: Tool 2 evaluates the correctness and structure of model responses by applying assertion rules to generated text outputs.

USER: What problems does Tool 2 solve?
AI: Tool 2 enables contract testing of prompt outputs, validation of response content and format, and generation of repeatable evidence for prompt-response behavior.

USER: What function executes Tool 2?
AI: Tool 2 is executed through the function run_tool2_prompt_response_eval located in app/tool2_operator.py.

USER: What inputs does Tool 2 require?
AI: Tool 2 requires:

* suite_path (string): path to suite JSON file
* output_dir (string): directory for artifacts
* file_stem (string, optional)
* project_root (optional Path)
* adapter (optional)
* fail_fast (boolean)
* default_timeout_seconds (integer >= 1)

USER: What is required for each Tool 2 test case?
AI: Each test case must include:

* name (string)
* lane = "prompt_response"
* prompt_input (string)
* expected_response_contains (array of strings)

USER: What optional validation rules can Tool 2 apply?
AI: Tool 2 supports:

* expected_response_not_contains
* expected_response_regex
* expected_response_starts_with
* expected_response_ends_with
* expected_response_equals
* expected_response_length_min
* expected_response_length_max

USER: What does Tool 2 return after execution?
AI: Tool 2 returns a structured bundle containing:

* ok (boolean)
* result (object or null)
* artifact_paths (object)
* json_preview (string)
* markdown_preview (string)
* error (string or null)
* run_log_error (string or null)
* run_log_path (string or null)

USER: What is inside the result object?
AI: The result object contains:

* suite_name
* target_name
* executed_cases
* passed_cases
* failed_cases
* ok
* elapsed_seconds
* ran_at_utc
* cases (list of evaluated cases)

USER: What data is stored for each evaluated case?
AI: Each case includes:

* name
* lane = "prompt_response"
* ok
* failures (list)
* latency_ms
* output_preview
* output_full
* prompt_input
* all expected response constraints used for validation

USER: How does Tool 2 evaluate responses?
AI: Tool 2 evaluates responses using assertion checks including:

* substring presence (contains)
* forbidden substring detection (not_contains)
* regex matching
* prefix and suffix checks
* exact equality checks
* minimum and maximum length checks

USER: Does Tool 2 use semantic similarity or scoring models?
AI: No. Tool 2 does not implement semantic similarity scoring, ranking, or numeric scoring systems.

USER: What artifacts does Tool 2 generate?
AI: Tool 2 generates:

* JSON artifact containing full evaluation results
* Markdown report summarizing results and failures

USER: Where are Tool 2 runs logged?
AI: Tool 2 logs runs in logs/tool2_runs.jsonl with structured entries for each execution.

USER: What data is stored in Tool 2 logs?
AI: Each log entry includes:

* run timestamp
* suite information
* configuration
* request data
* result summary
* case outcomes
* artifact paths
* error information

USER: What is the execution flow of Tool 2?
AI: The execution flow is:
UI → run_tool2_prompt_response_eval → load suite → execute suite → evaluate responses → generate artifacts → log run → display results

USER: What happens when Tool 2 receives invalid input?
AI: Tool 2 returns a failure bundle with ok = false and an error message describing the invalid input condition.

USER: What happens if a test case is missing expected_response_contains?
AI: Tool 2 returns a validation error indicating that expected_response_contains must be a non-empty array of strings.

USER: What happens if the model execution fails?
AI: Tool 2 captures the error as an adapter_error and records it as a failure in the case results.

USER: When should Tool 2 be used?
AI: Tool 2 should be used when validating prompt outputs, checking response content, and enforcing response structure rules.

USER: When should Tool 2 NOT be used?
AI: Tool 2 should not be used for:

* HTTP API testing (use Tool 1)
* regression execution workflows (use Tool 3)

USER: What is the difference between Tool 2 and Tool 1?
AI: Tool 1 validates HTTP responses from real API calls, while Tool 2 validates text responses generated from prompts.

USER: What is the difference between Tool 2 and Tool 3?
AI: Tool 3 handles regression execution workflows, while Tool 2 evaluates prompt-response correctness at the case level.

SUMMARY: Tool 2 is a deterministic prompt-response evaluation system that executes prompt inputs, validates generated outputs against explicit assertion rules, produces structured results, generates artifacts, and logs runs for verification.
```
