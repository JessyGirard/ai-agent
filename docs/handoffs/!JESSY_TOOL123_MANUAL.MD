Tool 1 UI Manual (Precise Navigation + Field Map)
1) How to get to Tool 1 screen
If you already see top buttons, click API (this opens Tool 1).
If you are on Agent screen and top buttons are hidden:
Open left sidebar
Open Tools · navigation · state
Click Tool 1 / API from that navigation block
When you are in the right place, page header is:

API — System eval (HTTP)
2) Tool 1 page layout (top to bottom)
A) Intro/Help area (top)
Expander: What this tool is
Expander: Assertion surface (Core vs Advanced)
These are informational only (not execution inputs).

B) Shared output setting (applies to both single request + suite)
Input: Output directory for artifacts (suite + single request)
Stores JSON/Markdown artifacts for runs.
C) Single request section
Section title: Single request (no suite file)

Input: HTTP timeout (seconds)

Input: Method (GET, POST, PUT, PATCH, DELETE)

Input: URL

Input: Query params (optional, JSON object)

Auth block title: Auth helper (single request only)

Input: Auth mode (None, Bearer token, Basic auth, API key)

If Bearer token:
Bearer token
If Basic auth:
Basic username
Basic password
If API key:
API key header name
API key value
Input: Headers (optional, JSON object)

Input: JSON body (optional) (only visible for POST/PUT/PATCH)

Button: Send Request

Executes one request immediately via Tool 1 engine.
Button: Run last request again
Replays last single-request snapshot in current session.
Expander: Last single request — copyable summary
Plain text summary of final request
Approximate curl preview
D) Suite run section
Divider
Section title: Suite run (JSON file)
Input: Suite JSON path (repo-relative or absolute)
Input: Optional file stem (blank = derive from suite_name)
Checkbox: Fail fast (stop at first failing case)
Button: Run system eval
Executes suite through Tool 1 operator path.
3) Where results appear after running
After either Send Request or Run system eval, results render below in this order:

Run log line:
Append-only run log: <path>
Run summary
Overall pass/fail style summary
Suite + target line
Detailed results
Table of cases (case, outcome, ok, lane, attempts, status, latency_ms)
Per-case detail blocks under table
Expanders per case:
Response Headers · ...
Response body · ...
Failure messages show under failed cases/attempts
Artifacts
JSON artifact path
Markdown artifact path
Expander: Markdown preview
Expander: JSON preview
4) Exact “what to fill” quick recipe
For a basic API smoke test in Tool 1 UI:

Output directory...: keep default or set custom folder
Method: GET
URL: endpoint URL
Optional:
Auth mode + auth values
Headers JSON
Query params JSON
Click Send Request
For suite execution:

Suite JSON path...: path to suite file
Optional file stem
Optional Fail fast
Click Run system eval
5) Important behavior notes (for ChatGPT/AI agent instructions)
Single request and suite both use the Tool 1 evaluation path.
Auth helper is only for single-request UI flow.
Tool 1 screen can run HTTP and also supports prompt-response lane via shared operator, but for clean usage:
HTTP/API checks → Tool 1
Prompt/response checks → Tool 2
Regression command runs → Tool 3

--------------------------------------------------

--------------------------------------------------

Tool 1 Manual (Detailed + Easy to Use)
1) What Tool 1 is
Tool 1 is your API truth checker.

It sends real HTTP requests to real endpoints, then checks whether the response matches what you expected (status code, headers, JSON fields, timing, etc.).
If something is wrong, it tells you exactly what failed.

Think of Tool 1 as:
“Did the API really behave the way I said it should?”

2) What Tool 1 is for (and not for)
Use Tool 1 when:

You want to test REST/API endpoints.
You want proof (artifacts + logs) of pass/fail results.
You want reliable debugging for integration issues.
Do NOT use Tool 1 when:

You’re testing prompt/AI text responses (that is Tool 2).
You’re running full regression command workflows (that is Tool 3).
3) How Tool 1 works (simple flow)
You define one request or a suite of test cases.
Tool 1 executes the HTTP call(s).
It evaluates assertions (rules you set).
It builds a result bundle (pass/fail + details).
It writes artifacts (JSON + Markdown) and run logs.
So the rhythm is basically: configure → run → inspect failures → refine → rerun.

4) Main things Tool 1 can validate
Tool 1 supports practical checks like:

Status checks

expected_status
expected_status_not
Header checks

expected_headers (exact/equality behavior)
expected_headers_contains
expected_header_exists
JSON checks

expected_json
expected_json_exists
expected_json_values
expected_json_absent
Body checks

expected_body_not_empty
body contains/equals/regex style checks (if present in your suite format)
Timing checks

max_duration_ms
expected_latency_ms_max
expected_response_time_ms_range
The key idea: each case has explicit rules, and Tool 1 compares reality to those rules.

5) What to put in a Tool 1 test case
At minimum, a case usually needs:

name
lane (Tool 1 HTTP lane)
request method/url (and headers/body if needed)
expected assertions (what must be true)
A typical case says:

“Call this endpoint”
“Expect status 200”
“Expect JSON object field”
“Expect response in acceptable time”
6) Authentication (very important)
Do not hardcode secrets in suite files.

Use runtime/config/operator-supported auth injection (for example headers supplied at run time).
This keeps credentials safe and portable.

7) What results you get back
Tool 1 returns a structured bundle with fields such as:

ok
result
artifact_paths
json_preview
markdown_preview
error (if run-level failure)
run_log_path
run_log_error
Inside result, you get:

suite summary (executed/passed/failed)
per-case outcomes
failure reasons
timing data
8) Artifacts and logs
Tool 1 writes evidence so runs are auditable:

JSON artifact: machine-readable full result
Markdown artifact: human-readable summary/report
Run log (logs/tool1_runs.jsonl): append-only operational history
This is how you build trust and proof over time.

9) Failure behavior (what happens when things go wrong)
Tool 1 can fail at two levels:

Case-level fail: request executed, but assertion(s) failed.
Run-level fail: suite cannot run correctly (missing file, invalid JSON, etc.).
Failures are explicit and usually include clear failure strings (example: missing key, mismatch, latency too high).

10) Beginner-friendly way to use Tool 1 daily
Use this lightweight routine:

Start with 1-2 critical endpoints.
Keep assertions minimal first (status + key JSON fields).
Run and confirm green baseline.
Add stricter assertions gradually.
Save artifacts/logs each run.
Investigate only failing lines first, then full body/header context.
Repeat.
This avoids noise and gives stable progress.

11) Practical operator tips
Keep one suite per purpose (smoke vs deep checks).
Name cases clearly (account_info_smoke, etc.).
Use timing thresholds that are realistic (not too tight at first).
Use negative checks (expected_status_not, expected_json_absent) for safety.
Treat artifacts as client-proof evidence.
12) Quick mental model (non-technical)
If Tool 1 were a person, it would be a strict inspector:

It doesn’t guess.
It doesn’t “feel” quality.
It checks facts.
It writes receipts.
That’s exactly why it’s powerful.

If you want, next I can format this into a ready-to-paste file version for docs/handoffs/!JESSY_TOOL1_MANUAL_AND_TEMPLATES.md in your preferred style.


--------------------------------------------------

--------------------------------------------------

