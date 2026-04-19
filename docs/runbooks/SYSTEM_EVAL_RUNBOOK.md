# System eval runbook (Phase 1, HTTP)

Use this when you want to **run a suite against a real HTTP API** and keep **JSON + Markdown artifacts** as evidence.

## What this is (and is not)

- **Is:** Your machine runs `tools/system_eval_runner.py`, which sends HTTP requests defined in a suite JSON and checks responses with deterministic rules.
- **Is not:** Remote control of someone’s computer, disk scanning, or access beyond URLs the customer (or you) expose and authorize.

## Before you run

1. Have a **reachable URL** (staging, localhost with tunnel, or public API).
2. Copy `system_tests/suites/example_http_suite.json` to a new file (keep the original as a template).
3. Edit the copy:
   - `suite_name`, `target_name` — labels for the report.
   - Each case: `method`, `url`, optional `headers`, `payload`, `timeout_seconds`.
   - Optional **`lane`** per case (for reporting / reliability modes): `stability`, `correctness`, or `consistency`. Omitted is allowed (`lane` shows as none in artifacts).
   - **`stability_attempts`** (optional): only when `lane` is **`stability`**. Same request is executed that many times; transport must succeed and assertions must pass on **every** attempt. Omitted defaults to **3**. Integer **1**–**50** only. Do not use `repeat_count` on stability cases (use `stability_attempts`).
   - **`repeat_count`** (optional): only when `lane` is **`consistency`**. Same rules as stability repeats. Omitted defaults to **3**. Integer **1**–**50** only. Do not use `stability_attempts` on consistency cases.
   - `assertions`: see **Assertion Keys (Minimal Tool 1)** and **Additional assertion keys (legacy)** below.

Treat secrets (API keys) like production credentials: prefer env-specific keys, rotate after sharing, and avoid committing real tokens into git.

## Command (from repo root)

```bash
python tools/system_eval_runner.py --suite "path/to/your_suite.json" --output-dir "logs/system_eval" --file-stem "my_run"
```

Operator UI (same runs, no terminal): from repo root run `streamlit run app/ui.py` and choose **API** in the **top surface bar** (or **API** under *Surface · backup* in the sidebar) — system eval panel in the main area.

## Windows one-click launch (operator)

Use this for **daily access** without typing commands. Same Python venv as the dev shell (**`.venv-win`** at the repo root).

### Launch

1. In **File Explorer**, open the repo folder (the one that contains `app/`, `tools/`, and **`Launch-Agent-UI.cmd`**).
2. **Double-click** `Launch-Agent-UI.cmd`.
3. A console window titled **ai-agent Streamlit UI** starts Streamlit; your **default browser** should open to the app (usually `http://localhost:8501`). Leave that window open while you use the UI. **Stop:** press **Ctrl+C** in the console window, then close it if you like.

If you see a message about missing **`.venv-win\Scripts\python.exe`**, create/activate the Windows venv at the repo root (same expectation as `Open-DevShell.cmd`), install dependencies (`pip install -r requirements.txt`), then try again.

**Manual equivalent** (same effect as the launcher): from repo root, with venv activated,

`python -m streamlit run app/ui.py`

### Pin to the taskbar (recommended)

Windows pins **shortcuts**, not raw `.cmd` files, cleanly to the taskbar.

**Preferred (repo-maintained shortcut):** from the repo root, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Create-Agent-UI-Shortcut.ps1
```

This creates **Mimi AI Agent UI.lnk** under **Start Menu → Programs** and on your **Desktop**. **LAUNCH-08:** the shortcut **Target** is **`chrome.exe`** (Google Chrome under Program Files) with **Arguments** **`--app=http://localhost:8501`**. It does **not** start Streamlit — no black console from the shortcut. **Working directory** is the repo root (harmless metadata). **First:** start the server on port **8501**, e.g. double-click **`Start-Agent-Server.cmd`** (visible console, **Ctrl+C** to stop) or use **`Launch-Agent-UI-App.bat`** / **`launch_ui.py`** for other silent paths — then use the **`.lnk`** to open the Chrome app window.

**Re-create shortcuts** after pulling launcher updates (run the script again). If you **pinned an older** shortcut that still pointed at a `.cmd`, **Unpin from taskbar** first, then **right-click** the newly created `.lnk` → **Pin to taskbar** (pinned items keep their old executable target until replaced).

**Manual fallback:** In Explorer, **right-click** `Launch-Agent-UI.cmd` → **Show more options** (Windows 11) / **Create shortcut** (Windows 10), move or rename it if you like, then **right-click** the shortcut → **Pin to taskbar**. That path keeps a **visible console** (same as double-clicking the `.cmd`) — **not** the Chrome-only demo path.

**Script-only silent path:** `Launch-Agent-UI-Silent.ps1` (e.g. hidden PowerShell `-File`) still starts Streamlit with **pythonw** when available; it is separate from the **Chrome-only** `.lnk`.

**Taskbar shortcut:** opens **Chrome app mode** only. **Backend:** run **`Start-Agent-Server.cmd`** (or **`Launch-Agent-UI.cmd`**) when you need a visible Streamlit console; **`Launch-Agent-UI.cmd`** does not force port **8501** unless you pass flags yourself.

### Relaunch later

- **Chrome pinned shortcut:** opens the app URL only — start **`Start-Agent-Server.cmd`** (or your usual server launcher) first if Streamlit is not already running.
- **Full dev console:** double-click **`Launch-Agent-UI.cmd`** again (or **`Start-Agent-Server.cmd`** for fixed **8501**).
- If the browser did not open automatically, go to **`http://localhost:8501`** when using the **8501** server. If something else is using that port, watch the server console for the URL Streamlit prints.

## Manual operator verification (Tool 1 Streamlit UI)

Use this once after a UI change (or anytime you want to trust the operator path).

### 1. Command to launch Streamlit

**Windows:** Prefer **`Launch-Agent-UI.cmd`** (see **Windows one-click launch** above). For **fixed port 8501**, use **`Start-Agent-Server.cmd`**.

From the **repository root** (folder that contains `app/`, `tools/`, `system_tests/`):

```bash
streamlit run app/ui.py
```

If Streamlit is not on `PATH`, use the same Python you use for the project, e.g. `python -m streamlit run app/ui.py`.

### 2. Surface to open

In the browser, use the **top bar** (Agent · API · Prompt · Regression · Terminal) and pick **API**. Default landing is **Agent**. The same choice is available as **Surface · backup** in the sidebar. Optional detail lives under sidebar **Advanced** (collapsed by default).

### 3. Recommended first pass (reachable local target + starter suite)

For a **reliable PASS** on the first manual run, use the repo’s tiny verify server and starter suite together.

**Terminal A — start the verify server** (from repo root):

```bash
python tools/tool1_verify_server.py
```

You should see `listening on http://127.0.0.1:37641`. The process binds **127.0.0.1 only** (not exposed to the LAN). Leave this terminal running.

**Optional:** set `TOOL1_VERIFY_PORT` to use another port; if you do, edit the three `url` values in the starter suite JSON to match.

**Terminal B — Streamlit** (same as §1).

**Suite JSON path** when **API** is selected:

- `system_tests/suites/tool1_local_starter_suite.json`

That is the **UI default** on a fresh session. It POSTs to the three paths above on port **37641**.

**Expected PASS:** Overall **PASS**; all three cases `ok` true; artifacts under your output directory (default `logs/system_eval`) with stem derived from `tool1-local-starter`.

**If the server is not running:** you get transport/connection failure for the cases — that is expected and means “start Terminal A first,” not a broken UI.

### 4. Template suite vs real endpoints

`system_tests/suites/example_http_suite.json` remains a **copy/edit template** with placeholder URLs and auth. Use it when you are wiring a real API; expect failures until `url`, `headers`, `payload`, and `assertions` match your target.

For a **custom real target**, copy that file to a new path, edit each case, and paste the new path into **Suite JSON path**.

### 4a. Public demo scenario pack (portfolio / practice)

Ready-made suites (JSONPlaceholder + httpbin, no secrets) live under **`system_tests/suites/tool1_public_demo/`**. See that folder’s **`README.md`** for a table of files.

**UI:** **API** → set **Suite JSON path** to one of:

- `system_tests/suites/tool1_public_demo/tool1_demo_public_smoke.json` (expect **PASS**)
- `system_tests/suites/tool1_public_demo/tool1_demo_public_validation_failures.json` (expect **FAIL** — intentional)
- `system_tests/suites/tool1_public_demo/tool1_demo_public_headers_and_echo.json` (expect **PASS**)

**CLI** (from repo root, needs outbound HTTPS):

```bash
python tools/system_eval_runner.py --suite "system_tests/suites/tool1_public_demo/tool1_demo_public_smoke.json" --output-dir "logs/system_eval" --file-stem "tool1_demo_smoke"
```

### 5. What to expect on success vs failure

- **Success (PASS):** green **PASS** under Overall; per-case table shows `ok` true for every row; artifact paths point to files that exist; previews show JSON/MD with `PASS` / passing case lines.
- **Failure (FAIL):** red **FAIL** under Overall; one or more rows with `ok` false; failures are still written to artifacts; previews show failing case details and `FAIL` in the markdown-style preview.

A failed run is still a **successful verification** of the UI if you see coherent results, paths, and previews (the suite failed, not the app).

### 6. Where artifact files are written

Whatever you put in **Output directory** (repo-relative or absolute), the run writes:

- `<file_stem>.json` — full result object  
- `<file_stem>.md` — human-readable summary  

If **Optional file stem** is empty, `file_stem` is derived from `suite_name` in the JSON (slugified). The UI shows both full paths under **Artifacts**.

### 7. Truncated previews in the UI

Expand **Markdown preview** and **JSON preview**. Large JSON is truncated in the UI (suffix `... (truncated for preview)`). Open the `.json` file on disk for the full content. Markdown is usually short enough to show in full.

---

Optional:

- `--fail-fast` — stop after the first failing case.
- `--default-timeout-seconds 20` — default timeout when a case omits `timeout_seconds`.

## What you get

- **Console:** `SYSTEM_EVAL_STATUS: PASS|FAIL` plus paths to artifacts.
- **Artifacts** (under `--output-dir`):
  - `<file_stem>.json` — full structured result.
  - `<file_stem>.md` — short human-readable summary.

Exit code: **0** if all cases pass, **non-zero** if any case fails (or transport error is treated as failure for that case).

## Multi-step scenarios (`steps`), variables, templates, and markdown detail

Use these on the **default / correctness** lane (omit **`lane`** or set **`correctness`**). **`stability`** and **`consistency`** do not support **`steps`** or request **`{{…}}`** placeholders.

- **`steps`:** non-empty array of objects. Each step must include **`name`**, **`method`**, **`url`**, optional **`headers`**, **`payload`**, **`timeout_seconds`**, **`body`:** `null`, **`send_json_body`:** `true`. All other keys on the step are treated like a case’s **`assertions`** (including **`extract`** to bind JSON paths into shared **`variables`**).
- **`{{variable_name}}`:** after **`extract`**, substitute into the next step’s **`url`**, header **values**, and string leaves inside **`payload`**.
- **`step_templates`:** optional object mapping template names → partial step bodies (must include **`method`** and **`url`**; templates may not use **`use`**). A step may set **`"use": "template_name"`** and override any field; **`headers`**, **`payload`**, and **`extract`** merge one level deep when both sides are objects.
- **Legacy single-case two-hop** (when **`steps` is absent):** optional **`request_url_initial`**, **`payload_initial`**, **`headers_initial`** so the first HTTP call can run before **`{{…}}`** placeholders are filled.
- **Results:** JSON case rows include **`step_results`** (per step: **`step`**, **`status`** `PASS`/`FAIL`, **`url`** after substitution, **`latency_ms`**, optional **`reason`**). The **`.md`** artifact adds a **`### Steps`** subsection under each multi-step case for quick operator review.

## Assertion Keys (Minimal Tool 1)

These keys live under each case’s **`assertions`** object. They are the **recommended** surface for new Tool 1 suites (single-request and suite runner share the same engine).

**String vs structured body checks:** **`body_equals`** compares the response body **as one string** (after whitespace normalization).

**JSON presence vs value:** **`body_json_has_key`** checks that each listed path (**dot segments** and optional **`name[n]`** list steps) **exists** in the parsed JSON (**presence only**). **`body_json_path_equals`** checks **value equality** at each path after `json.loads`. **`body_json_array_length_equals`**, **`body_json_array_length_at_least`**, and **`body_json_array_length_at_most`** check the **list at each path** against an **exact**, **minimum**, or **maximum** allowed length (non-negative integers). Use **`body_json_has_key`** for shape/schema smoke checks; use **`body_json_path_equals`** when the exact value must match; use the array-length keys when you care about **collection size** or bounds (e.g. result counts, pagination caps).

**Operators — JSON path / array checks at a glance:** **`body_json_has_key`** → path **exists**. **`body_json_path_equals`** → value at path **equals** expected. **`body_json_array_length_equals`** → array length **equals** expected. **`body_json_array_length_at_least`** → length is **≥** minimum. **`body_json_array_length_at_most`** → length is **≤** maximum.

- **Missing path:** for **`body_json_path_equals`**, **`body_json_has_key`**, **`body_json_array_length_equals`**, **`body_json_array_length_at_least`**, and **`body_json_array_length_at_most`**, a path must resolve along **JSON objects** and, where **`name[n]`** is used, **JSON arrays** (as Python dicts and lists); otherwise the engine reports **`body_json_path missing path`** with the full asserted path in the failure detail (for example **`{"path": "user.id"}`** or **`{"path": "items[0].id"}`** in the message text).
- **Example (object path):** **`user.id`** fails if **`user`** is missing **or** **`id`** is missing under **`user`** (or a segment expected an object key but hit a non-object).

| Assertion key | Type | Description |
|-----------------|------|-------------|
| `expected_status` | int | Expected HTTP status code for the response. |
| `body_contains` | string | Substring must appear somewhere in the response body text. |
| `body_equals` | string | Entire response body must match after **whitespace normalization** (leading/trailing trim; internal runs of whitespace collapsed to a single space). |
| `body_regex` | string | Python **regex** must match the response body (multiline search). Invalid patterns fail the case with a clear error. |
| `body_json_path_equals` | `dict[str, any]` | **Top-level and path JSON equality check** — response body must be **valid JSON** whose root is an **object**; each assertion key is a path using **dot notation** and optional **`name[n]`** list segments (e.g. **`userId`**, **`user.id`**, **`items[0].id`**); resolved leaf must equal the expected value using **exact JSON / Python equality** after `json.loads`. |
| `body_json_has_key` | `list[str]` | **JSON path existence** check (**dot paths** and **`name[n]`** indexing supported): response body must be **valid JSON** with an **object** root; every string in the array is a path that must resolve (objects and indexed lists along the path). Does **not** compare values. |
| `body_json_array_length_equals` | `dict[str, int]` | **JSON array length check** at path — response body must be **valid JSON** with an **object** root; each key is a path using the same **dot** and **`name[n]`** rules as above; the resolved value must be a **JSON array** (Python **`list`**); each mapped value is the **expected length** as a **non-negative integer** (JSON number; not boolean). |
| `body_json_array_length_at_most` | `dict[str, int]` | **JSON array maximum length** at path — same **valid JSON** / **object** root and path rules as **`body_json_array_length_equals`**; resolved value must be a **`list`**; each mapped value is the **maximum allowed length** (non-negative integer; not boolean); failure if **`len(list)`** is **greater** than that maximum. |
| `header_contains` | string | Substring must appear in a **serialized** view of response headers (sorted by name, `Name: value` per line). |
| `header_equals` | object (`string` → `string`) | For each header name, the response must include that header (name matched **case-insensitively**) and its value must match **exactly** after **`.strip()`** on both expected and actual. |
| `header_regex` | object (`string` → `string`) | For each header name, the response must include that header; the header’s value must match the given **regex** pattern string. Missing header, mismatch, or invalid regex each produce a distinct failure message. |

**Short examples** (each block is a full `assertions` object you can merge into a case):

`expected_status` + `body_contains`:

```json
{
  "expected_status": 200,
  "body_contains": "\"userId\":"
}
```

`body_equals`:

```json
{
  "body_equals": "hello world"
}
```

`body_regex`:

```json
{
  "body_regex": "userId:\\s*\\d+"
}
```

`body_json_path_equals` (top-level key):

```json
{
  "body_json_path_equals": {
    "userId": 1
  }
}
```

`body_json_path_equals` (nested path, dot notation):

```json
{
  "body_json_path_equals": {
    "user.id": 1
  }
}
```

`body_json_path_equals` (array index in path):

```json
{
  "body_json_path_equals": {
    "items[0].id": 1
  }
}
```

`body_json_has_key`:

```json
{
  "body_json_has_key": [
    "user.id",
    "meta.version"
  ]
}
```

`body_json_array_length_equals`:

```json
{
  "body_json_array_length_equals": {
    "items": 3,
    "data.users": 2
  }
}
```

`body_json_array_length_equals` (path with array index segment):

```json
{
  "body_json_array_length_equals": {
    "items[0].subitems": 1
  }
}
```

`body_json_array_length_at_most`:

```json
{
  "body_json_array_length_at_most": {
    "items": 5,
    "data.users": 10
  }
}
```

`body_json_array_length_at_most` (path with array index segment):

```json
{
  "body_json_array_length_at_most": {
    "items[0].subitems": 2
  }
}
```

`header_equals`:

```json
{
  "header_equals": {
    "Content-Type": "application/json"
  }
}
```

`header_regex`:

```json
{
  "header_regex": {
    "Content-Type": "application/json.*"
  }
}
```

**Operator notes**

- All assertions in the same case are **AND**ed: **every** listed check must pass for the case to pass.
- You may combine multiple keys (for example `expected_status` + `body_contains` + `header_regex`) when you need both status and content proof.
- **Prefer:** **`body_contains` / `header_contains`** for quick smoke checks; **`body_equals` / `header_equals`** when you need strict equality; **`body_regex` / `header_regex`** when the response shape varies slightly but must still match a pattern.
- **`body_json_path_equals` / `body_json_has_key` —** response body must be **valid JSON**; decoded root must be a JSON **object** (not an array or primitive at the top level).
- **`body_json_path_equals` / `body_json_has_key` —** **Paths** use **dot-separated segments**: plain keys (**`a.b.c`**) and optional **`name[n]`** list steps (**`items[0]`**). Traversal is **JSON objects** (dicts) and **JSON arrays** (lists) only — **no wildcards**, **no slicing**, **no escape** for a literal dot in a key name (a dot always starts the next segment).
- **`body_json_path_equals` / `body_json_has_key` —** **Array indexing:** **`items[0]`** form; the index must be a **non-negative integer**; the segment before **`[`** must resolve to a **list** before indexing; the index must **exist** (**out of range** → missing path).
- **`body_json_path_equals` / `body_json_has_key` —** **Chained** paths are supported (e.g. **`items[0].sub[1]`**): at most **one** **`[n]`** per segment; chain further segments with dots — not slicing.
- **`body_json_path_equals` / `body_json_has_key` —** any **invalid segment or index** (missing key, wrong container type, malformed **`[n]`**, out-of-range index) is reported as **`body_json_path missing path`** with the **full asserted path** in the failure detail.
- **`body_json_path_equals` —** comparison uses **exact JSON equality** on the resolved leaf (engine: `json.loads` then `==`; watch **`int` vs `float`** if APIs emit decimals).
- **`body_json_has_key` —** checks **existence only** — it does **not** assert the leaf value.
- **`body_json_has_key` —** a path whose leaf value is JSON **`null`** still **counts as present** (the path resolves).
- **`body_json_array_length_equals` —** response body must be **valid JSON**; decoded root must be a JSON **object** (same top-level rule as the other JSON body assertions).
- **`body_json_array_length_equals` —** **Path resolution** follows the same **dot** / **`name[n]`** rules documented above for **`body_json_path_equals`** / **`body_json_has_key`**.
- **`body_json_array_length_equals` —** the value at each path must resolve to a **list**; if the path is missing or unresolvable, the failure is **`body_json_path missing path`** (same detail shape as other JSON path assertions).
- **`body_json_array_length_equals` —** if the path resolves but the value is **not** a list, the engine fails with **`body_json_array_length_equals not array`** (message includes path and actual type).
- **`body_json_array_length_equals` —** if **`len(list)`** does not equal the expected integer, the engine fails with **`body_json_array_length_equals mismatch`** (message includes path, expected length, and actual length).
- **`body_json_array_length_at_most` —** response body must be **valid JSON**; decoded root must be a JSON **object** (same top-level rule as the other JSON body assertions).
- **`body_json_array_length_at_most` —** **Path resolution** follows the same **dot** / **`name[n]`** rules as **`body_json_path_equals`** / **`body_json_has_key`** / **`body_json_array_length_equals`**.
- **`body_json_array_length_at_most` —** the value at each path must resolve to a **list**; if the path is missing or unresolvable, the failure is **`body_json_path missing path`** (same detail shape as other JSON path assertions).
- **`body_json_array_length_at_most` —** if the path resolves but the value is **not** a list, the engine fails with **`body_json_array_length_at_most not array`** (message includes path and actual type).
- **`body_json_array_length_at_most` —** if **`len(list)`** is **greater than** the expected maximum, the engine fails with **`body_json_array_length_at_most mismatch`** (message includes path, expected maximum, and actual length).

Implementation reference: `core/system_eval.py` (`_validate_minimal_assertion_keys`, `_assert_output_matches`).

## Additional assertion keys (legacy)

Older suites may still use these keys on the **body** (and `status_code`). They remain supported:

| Key | Meaning |
|-----|--------|
| `status_code` | Integer HTTP status must match. |
| `contains_all` | List of substrings that must all appear in the body. |
| `not_contains` | List of substrings that must not appear. |
| `equals` | Body text must equal this string (after strip on both sides; no whitespace normalization like `body_equals`). |
| `regex` | Body must match this pattern (multiline). |

Same implementation module: `core/system_eval.py` (`_assert_output_matches`).

## Quality gates (unchanged)

After any code change to the runner or `core/system_eval.py`:

```bash
python tests/run_regression.py
```

Acceptance criteria and recorded status: `docs/reliability/RELIABILITY_EVIDENCE.md`.

## Optional next step (operational, not required for the repo)

Run your edited suite against a **staging** endpoint you control and archive the resulting `.json` / `.md` as a real-world proof run.
