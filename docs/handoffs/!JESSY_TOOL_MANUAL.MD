Complete Instruction Manual (Tools 1, 2, 3)
Introduction
This system is a 3-tool testing machine.
Each tool has a strict role:

Tool 1 = HTTP/API truth checking
Tool 2 = Prompt/response output checking
Tool 3 = Regression command execution
Use the right tool for the right job. Do not mix purposes.

Tool 1 — HTTP System Evaluation
What it is

Tool 1 runs real HTTP requests and validates real API behavior using assertions.

What it can do

Validate status codes
Validate headers (exact, contains, exists)
Validate JSON keys and JSON values
Validate absent keys
Validate response timing and latency bounds
Validate response body presence/content patterns
Write JSON/Markdown artifacts and run logs
When to use Tool 1

You need real API verification
You are debugging endpoint integration issues
You need proof artifacts for API behavior
When NOT to use Tool 1

Prompt-response model quality checks (use Tool 2)
Project-wide regression command workflows (use Tool 3)
Basic instruction flow

Open Tool 1 panel in UI.
Set suite path / single request inputs.
Configure output directory and file stem.
Provide auth safely at runtime/config (do not hardcode secrets in suite).
Run evaluation.
Review:
pass/fail summary
failure reasons
artifacts
run log entry
Expected result shape (high level)

ok
result (cases, counts, timing)
artifact_paths
json_preview, markdown_preview
error (if any)
run_log_path, run_log_error
Tool 2 — Prompt/Response Evaluation
What it is

Tool 2 runs prompt test cases and validates generated text outputs against deterministic assertions.

What it can do

Check expected substring presence
Check forbidden substring absence
Regex checks
Starts-with / ends-with checks
Exact equals checks
Min/max response length checks
Capture case-level output and failures
Write artifacts and run logs
When to use Tool 2

You need contract-style validation for prompt outputs
You need repeatable evidence for prompt behavior
When NOT to use Tool 2

Real HTTP endpoint testing (use Tool 1)
Regression command execution (use Tool 3)
Basic instruction flow

Open Tool 2 panel in UI.
Select suite with lane = "prompt_response" cases.
Ensure each case includes:
name
prompt_input
expected_response_contains (required)
Set output directory, file stem, and execution options.
Run prompt-response evaluation.
Review case outputs, failures, and artifacts.
Expected result shape (high level)

ok
result (suite/case outcomes)
artifact_paths
json_preview, markdown_preview
error (if any)
run_log_path, run_log_error
Tool 3 — Regression Execution
What it is

Tool 3 runs regression commands (default or override command), captures execution outcome, and packages results as structured artifacts/logs.

What it can do

Execute regression command profile
Capture exit status, stdout/stderr, runtime behavior
Produce pass/fail summary
Produce readable JSON/Markdown artifacts
Persist run logs consistently
When to use Tool 3

You need full regression run evidence
You need stability checks across the project
When NOT to use Tool 3

Endpoint-level assertion testing (use Tool 1)
Prompt output correctness testing (use Tool 2)
Basic instruction flow

Open Tool 3 panel in UI.
Set suite path/output settings.
Use default command or provide safe override.
Click run regression.
Review:
run status
pass/fail summary
short failing list
artifact bundle
run log record
Expected result shape (high level)

ok
result (regression lane summary/cases)
artifact_paths
json_preview, markdown_preview
error (if command/load/execution fails)
run_log_path, run_log_error
Conclusion
This project is a controlled, reliable testing machine when used with strict boundaries:

Use Tool 1 for real APIs
Use Tool 2 for prompt-response contracts
Use Tool 3 for regression execution
If you keep tool ownership clean, run artifacts/logs every time, and review failures systematically, the system stays professional, trustworthy, and production-usable.