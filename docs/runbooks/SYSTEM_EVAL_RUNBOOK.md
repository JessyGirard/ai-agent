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
   - `assertions`: see **Assertion keys** below.

Treat secrets (API keys) like production credentials: prefer env-specific keys, rotate after sharing, and avoid committing real tokens into git.

## Command (from repo root)

```bash
python tools/system_eval_runner.py --suite "path/to/your_suite.json" --output-dir "logs/system_eval" --file-stem "my_run"
```

Operator UI (same runs, no terminal): from repo root run `streamlit run app/ui.py` and open the **Tool 1 — System eval (HTTP)** tab.

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

1. In Explorer, **right-click** `Launch-Agent-UI.cmd` → **Show more options** (Windows 11) / **Create shortcut** (Windows 10).
2. Optionally **drag** the new shortcut to the **Desktop** or rename it (e.g. **Jessy UI**).
3. **Right-click** the shortcut → **Pin to taskbar** (or drag the shortcut onto the taskbar).

Later, **one click** on that taskbar icon starts the UI the same way as double-clicking the `.cmd`.

### Relaunch later

- Use the **pinned shortcut** or double-click **`Launch-Agent-UI.cmd`** again.
- If the browser did not open automatically, go to **`http://localhost:8501`** (default Streamlit port). If something else is using that port, watch the console for the URL Streamlit prints.

## Manual operator verification (Tool 1 Streamlit UI)

Use this once after a UI change (or anytime you want to trust the operator path).

### 1. Command to launch Streamlit

**Windows:** Prefer **`Launch-Agent-UI.cmd`** (see **Windows one-click launch** above).

From the **repository root** (folder that contains `app/`, `tools/`, `system_tests/`):

```bash
streamlit run app/ui.py
```

If Streamlit is not on `PATH`, use the same Python you use for the project, e.g. `python -m streamlit run app/ui.py`.

### 2. Tab / panel to open

In the browser, open the tab named **Tool 1 — System eval (HTTP)** (next to **Assistant**). The sidebar is still the agent sidebar; Tool 1 controls are in the main area on that tab.

### 3. Recommended first pass (reachable local target + starter suite)

For a **reliable PASS** on the first manual run, use the repo’s tiny verify server and starter suite together.

**Terminal A — start the verify server** (from repo root):

```bash
python tools/tool1_verify_server.py
```

You should see `listening on http://127.0.0.1:37641`. The process binds **127.0.0.1 only** (not exposed to the LAN). Leave this terminal running.

**Optional:** set `TOOL1_VERIFY_PORT` to use another port; if you do, edit the three `url` values in the starter suite JSON to match.

**Terminal B — Streamlit** (same as §1).

**Suite JSON path** in the Tool 1 tab:

- `system_tests/suites/tool1_local_starter_suite.json`

That is the **UI default** on a fresh session. It POSTs to the three paths above on port **37641**.

**Expected PASS:** Overall **PASS**; all three cases `ok` true; artifacts under your output directory (default `logs/system_eval`) with stem derived from `tool1-local-starter`.

**If the server is not running:** you get transport/connection failure for the cases — that is expected and means “start Terminal A first,” not a broken UI.

### 4. Template suite vs real endpoints

`system_tests/suites/example_http_suite.json` remains a **copy/edit template** with placeholder URLs and auth. Use it when you are wiring a real API; expect failures until `url`, `headers`, `payload`, and `assertions` match your target.

For a **custom real target**, copy that file to a new path, edit each case, and paste the new path into **Suite JSON path**.

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

## Assertion keys (deterministic)

Supported on response **body text** (and `status_code`):

| Key | Meaning |
|-----|--------|
| `status_code` | Integer HTTP status must match. |
| `contains_all` | List of substrings that must all appear in the body. |
| `not_contains` | List of substrings that must not appear. |
| `equals` | Body text must equal this string (after strip on both sides). |
| `regex` | Body must match this pattern (multiline). |

Implementation reference: `core/system_eval.py` (`_assert_output_matches`).

## Quality gates (unchanged)

After any code change to the runner or `core/system_eval.py`:

```bash
python tests/run_regression.py
```

Acceptance criteria and recorded status: `docs/reliability/RELIABILITY_EVIDENCE.md`.

## Optional next step (operational, not required for the repo)

Run your edited suite against a **staging** endpoint you control and archive the resulting `.json` / `.md` as a real-world proof run.
