# Session sync log (living handoff)

**Why this file exists:** ChatGPT starts with a blank slate every day. This log is the **fastest way** to resurrect shared context without re-explaining the project. Cursor (or Jessy) appends **one block per work session** after code/docs change or after alignment with ChatGPT.

**Rules**

- **Append only** — never delete old entries; newest entry is always at the **bottom**.
- One session block = one dated increment (even if the increment is “planning only”).
- After every Cursor session that changes the repo or the plan, **this file must be updated** before the day is “closed.”
- **Cursor assistant:** default is to **append a new bottom entry** after each completed task that touches the repo or agreed scope (summary, files, regression X/Y, next step). If Jessy says “docs only / no log,” skip.
- Regression count must reflect **actual** `python tests/run_regression.py` output (number changes as tests are added).

**How ChatGPT should use it**

1. Read **this entire file** if it is short; if long, read the **last 3 entries** (from bottom upward) first, then scan older entries only if something contradicts.
2. Read `docs/handoffs/PROJECT_STORY_AND_SOURCES.md` for the **human-readable arc** and a **table of where every kind of history lives** (the log does not contain the whole story by design).
3. Then read `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md` (protocol + paste order).
4. Then deeper docs only if needed (`docs/reliability/RELIABILITY_EVIDENCE.md`, roadmap, handoff, etc.).

---

## Log entries (oldest → newest)

### 2026-04-17 — Alignment: AI Testing Workbench + PR #1 scope (planning; code not started)

**Source:** Jessy + ChatGPT agreement, confirmed with Cursor.

**Product lock:** One **shared testing spine** (`core/system_eval.py`, `tools/system_eval_runner.py`, `system_tests/suites/*.json`) + **three tool profiles**: (1) API reliability, (2) prompt↔response, (3) regression (`tests/run_regression.py`).

**Approved next increment — PR #1 “API reliability mode”**

- Add **reliability lanes** to the HTTP suite (conceptual lanes: stability, correctness, consistency — exact schema/behavior to be implemented in Cursor next).
- **Touch:** `core/system_eval.py`, `system_tests/suites/example_http_suite.json`, `tests/run_regression.py`, minimal `README.md`.
- **Must not:** prompt-response schema work, new adapters, model judge, `playground.py` coupling.

**Validation:** `python tests/run_regression.py` after every change.

**Cursor status at time of entry:** PR #1 **not yet implemented** in repo; next session is implementation.

**Open detail for implementer:** Clarify whether “lanes” are (a) metadata/tags for reporting only or (b) execution behavior (e.g. repeated calls for consistency). Default assumption for PR #1: start with **explicit lane field + reporting in artifacts**; add minimal **repeat-N** behavior only if it fits one small PR with tests.

---

### 2026-04-17 — Repo hygiene: daily bootstrap + this log created

**What changed:** Added `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md` (paste message + protocol) and this append-only log so new ChatGPT sessions can sync instantly.

**Files:** `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/README.md` (index link).

**Tests:** Not run (documentation-only commit).

**Next:** Implement PR #1 (API reliability lanes) in Cursor; append new entry here with files touched + regression X/Y.

---

### 2026-04-17 — Project story + source map (documentation)

**What changed:** Added `docs/handoffs/PROJECT_STORY_AND_SOURCES.md`: readable project arc + table pointing to every canonical history doc (handoff, changelog, spec, reliability, roadmap, sync log). Updated daily bootstrap and `CHATGPT_COLLAB_SYNC.md` read order to include it. **Rationale:** Session log stays lean; “full history” stays distributed so nothing goes stale in one giant file.

**Files:** `docs/handoffs/PROJECT_STORY_AND_SOURCES.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`, `docs/README.md`

**Tests:** Not run (docs only).

**Next:** Implement PR #1 (API reliability lanes) when Jessy says go; update this log with regression counts + files touched.

---

### 2026-04-17 — Daily bootstrap: ChatGPT role + handoff + loop

**What changed:** Expanded `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md` paste block and body: explicit ChatGPT duties (reject bundling, name tests), handoff recovery file list, no-silent-changes rule, core principle, operating loop (6 steps), source-of-truth slot for latest SESSION_SYNC_LOG.

**Tests:** Not run (docs only).

**Next:** PR #1 implementation when Jessy confirms; or paste further ChatGPT requests into Cursor to merge into bootstrap.

---

### 2026-04-17 — Bootstrap: explicit latest target line (ChatGPT)

**What changed:** `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md` now states **Latest target: PR #1 — API reliability lanes (stability, correctness, consistency)** in the page header and inside the paste block; log still overrides if we advance.

**Tests:** Not run (docs only).

**Next:** Implement PR #1 in code when Jessy says go.

---

### 2026-04-17 — PR #1 increment 1: suite `lane` field (schema + artifacts + regression)

**Implemented:** Optional per-case `lane` in HTTP suites (`stability` | `correctness` | `consistency`), validated in `validate_suite`, stored on each case, passed through `execute_suite` results, shown in JSON + Markdown artifacts. Invalid lane values raise `ValueError`. No repeat calls, no new assertions, no `playground.py` coupling.

**Files touched:** `core/system_eval.py`, `system_tests/suites/example_http_suite.json`, `tests/run_regression.py`, `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`, `README.md`

**Regression:** `175 / 175` PASS (`python tests/run_regression.py`).

**Soak / system_eval:** Not run this session (harness only).

**Scope:** Matches PR #1 first increment only; prompt-response and lane *behavior* (repetition/scoring) explicitly not done.

**Next proposed step:** PR #1 increment 2 *only if agreed* — e.g. repeat-N consistency behavior behind `lane=consistency` — or pause until ChatGPT/Jessy approve.

---

### 2026-04-17 — Session log rule: Cursor default append

**What changed:** `SESSION_SYNC_LOG.md` **Rules** now state that the Cursor assistant should **append a bottom entry** by default after each completed repo/scope task (unless Jessy says skip).

**Tests:** Not applicable.

**Next:** Continue normal work; Jessy can remind Cursor if a log append was missed.

---

### 2026-04-17 — PR #1 increment 2: `lane=consistency` + `repeat_count`

**Implemented:** Optional `repeat_count` (1–50, default **3**) only when `lane == "consistency"`. Same HTTP case executed N times; each attempt uses existing assertion rules; case passes only if **all** attempts pass. Per-attempt rows in JSON (`attempts`); summary fields `attempts_passed`, `attempts_total`, `repeat_count`. Markdown lists consistency summary + per-attempt lines. Non-consistency lanes unchanged (single call, no `repeat_count` on case). Invalid `repeat_count` or `repeat_count` without consistency lane → `ValueError`.

**Files:** `core/system_eval.py`, `system_tests/suites/example_http_suite.json`, `tests/run_regression.py`, `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`, `README.md`

**Regression:** `180 / 180` PASS.

**Soak:** Not run. Runner smoke still covered by regression.

**Scope:** No latency scoring, no judge, no new assertion types, no prompt-response schema, no `playground.py`.

**Next:** PR #2 (prompt↔response) or PR #3 (regression operator surface) only when Jessy/ChatGPT approve — not bundled here.

---

### 2026-04-17 — Docs: “three anchors” table in project story

**What changed:** `docs/handoffs/PROJECT_STORY_AND_SOURCES.md` now has a short section **How to read the three anchors** (roadmap vs session log vs SYNC block) plus a conflict rule of thumb. Stale “right now” line in that file now points at the sync log bottom.

**Tests:** Not applicable.

**Next:** Continue work per roadmap / ChatGPT alignment.

---

### 2026-04-17 — PR #1 increment 3: `lane=stability` + `stability_attempts`

**Implemented:** Optional **`stability_attempts`** (1–50, default **3**) only when `lane == "stability"`. Same HTTP case executed N times; each attempt must pass transport + existing assertions. Results include `stability_attempts`, `attempts`, `attempts_passed`, `attempts_total` (same shape as consistency repeats). **`repeat_count` forbidden on stability** (clear error: use `stability_attempts`). **`stability_attempts` forbidden on consistency** (error: use `repeat_count`). Refactored shared `_run_n_attempts`. Markdown lists stability summary + per-attempt lines.

**Files:** `core/system_eval.py`, `system_tests/suites/example_http_suite.json`, `tests/run_regression.py`, `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`, `README.md`

**Regression:** `184 / 184` PASS.

**Scope:** No latency thresholds, retry/backoff, new assertion types, prompt-response schema, or `playground.py`.

**Next:** PR #2 / PR #3 per alignment; or further PR #1 polish only if agreed.

---

### 2026-04-17 — SYNC template: explicit system_eval_runner smoke line

**What changed:** `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md` SYNC MESSAGE **Test Status** section now includes **`system_eval_runner smoke: yes/no`** (separate from soak). Cursor will use this in future SYNC blocks.

**Tests:** Not applicable.

**Next:** Normal work.

---

### 2026-04-17 — Tool 1 operator UI (Streamlit slice)

**Implemented:** Streamlit **Tool 1 — System eval (HTTP)** tab in `app/ui.py` (alongside Assistant). New `app/system_eval_operator.py` exposes `run_tool1_system_eval_http` (same flow as CLI runner: load suite → `HttpTargetAdapter` → `execute_suite` → artifacts + previews). UI: suite path, output dir, optional stem, fail-fast, timeout, Run; shows overall PASS/FAIL, per-case table (lane, attempts summary), artifact paths, MD/JSON previews. Added `app/__init__.py` for imports. Regression tests for helper + missing suite path.

**Files:** `app/ui.py`, `app/system_eval_operator.py`, `app/__init__.py`, `tests/run_regression.py`, `README.md`, `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`

**Regression:** `186 / 186` PASS. `system_eval_runner` smoke: yes (via regression). **Manual Streamlit:** not run in this session — run `streamlit run app/ui.py` from repo root and exercise Tool 1 tab.

**Scope:** No PR #2, no regression UI, no prompt-response UI, no `playground.py` coupling in eval path.

**Next:** Jessy manual UI smoke; then ChatGPT/Cursor decide next slice (still not PR #2 unless approved).

---

### 2026-04-17 — Manual Tool 1 UI verification guide (docs only)

**What changed:** Added **Manual operator verification (Tool 1 Streamlit UI)** section to `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md` (launch command, tab name, default suite, how to fix placeholders, success vs failure expectations, artifact paths, preview truncation). No code changes.

**Regression:** Not re-run (documentation only).

**Next:** Jessy performs one real UI pass per that section; report any tiny blocker if found.

---

### 2026-04-17 — Tool 1 operator target: local verify server + starter suite

**What changed:** Added `tools/tool1_verify_server.py` (127.0.0.1:37641, three POST paths with fixed JSON), `system_tests/suites/tool1_local_starter_suite.json` (stability / correctness / consistency cases matching that server; distinct markers to avoid substring false positives). Streamlit Tool 1 default suite path now points at the starter file. Runbook §3 documents Terminal A/B launch and expected PASS; README notes first-pass flow and corrects regression count to 186.

**Files:** `tools/tool1_verify_server.py`, `system_tests/suites/tool1_local_starter_suite.json`, `app/ui.py`, `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`, `README.md`, `docs/handoffs/SESSION_SYNC_LOG.md`

**Regression:** `186 / 186` PASS. `system_eval_runner` smoke: yes (via regression). **Manual Streamlit:** not run in this session — Jessy: start verify server, then `streamlit run app/ui.py`, Tool 1 tab, Run (see runbook).

**Next:** Jessy manual Tool 1 UI pass with local server + default suite.

---

### 2026-04-17 — Fetch lane increment 1: failure classification + messaging

**What changed:** `tools/fetch_page.py` now returns stable `[fetch:<tag>]` lines for timeout, network, 401/403/429, other 4xx/5xx/non-200, request errors, parse errors, and low-content HTML (empty or under 80 characters of text). Successful substantial fetches still return plain text only (unchanged for the LLM). Added `fetch_failure_tag()` helper. `services/prompt_builder.choose_post_fetch_next_step` routes tagged failures and `low_content` to clearer forced next steps; keeps legacy `[fetch error]` handling. Eight new regression scenarios (mocked `requests.get`). `playground.py` unchanged (still passes tool output through).

**Files:** `tools/fetch_page.py`, `services/prompt_builder.py`, `tests/run_regression.py`, `docs/handoffs/SESSION_SYNC_LOG.md`

**Regression:** `194 / 194` PASS. `system_eval_runner` smoke: yes (via regression). Tool 1 / system_eval / UI: not touched.

**Next:** Optional fetch lane increment 2 (e.g. heuristics for login-like HTML) only if agreed; Tool 1 expansion remains paused.

---

### 2026-04-17 — ChatGPT handoff: bootstrap + HANDOFF aligned to log

**What changed:** `docs/handoffs/HANDOFF_RECENT_WORK.md` — added top “Aligned (2026-04-17)” summary (194 regression, Tool 1 + verify server + fetch tags + dev shell helpers, paused scope); replaced stale **173** counts in verify section and file list. `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md` — “Latest target” now defers to log bottom and lists current shipped slices + 194 baseline + pause lines.

**Regression:** Not re-run (documentation only).

**Next:** Jessy starts new ChatGPT chat with paste order unchanged; Cursor awaits pasted “first increment” spec — **no code increment until Jessy confirms.**

---

### 2026-04-17 — FETCH capability upgrade: Increment 1 (diagnosis + boundary, planning only)

**What changed:** No code or behavior change. Cursor produced end-to-end trace, failure/success contract, limitations, plug-in boundary (delegate behind `fetch_page` or registry), Increment 2 file list + risks, SYNC MESSAGE (chat). Validates baseline still green.

**Regression:** `194 / 194` PASS (confirmatory run; no code diff).

**Next:** ChatGPT/Jessy approve **Increment 2** (single slice): e.g. introduce `FetchBackend` protocol + default `requests` impl wiring from `playground` injectable for tests — **not** browser automation until explicitly approved.

---

### 2026-04-17 — FETCH upgrade Increment 2: internal boundary (HTTP extracted, facade dispatch)

**What changed:** Moved HTTP implementation to **`tools/fetch_http.py`** as **`fetch_via_http(url)`** (unchanged logic and `[fetch:…]` strings). **`tools/fetch_page.py`** is facade only: **`fetch_page(url)`** reads **`FETCH_MODE`** (default `http`), dispatches via **`_FETCH_BACKENDS`** map (HTTP registered; unknown modes fall back to HTTP for identical runtime behavior). **`fetch_failure_tag`** unchanged on facade. **`playground.py`**, Tool 1, system_eval: not touched. Regression tests patch **`tools.fetch_http.requests`** instead of `fetch_page`.

**Files:** `tools/fetch_http.py` (new), `tools/fetch_page.py`, `tests/run_regression.py`, `docs/handoffs/SESSION_SYNC_LOG.md`

**Regression:** `194 / 194` PASS.

**Next:** Optional Increment 3 — register a non-HTTP backend when browser (or other) mode is approved; keep single-slice discipline.

---

### 2026-04-17 — FETCH upgrade Increment 3: optional Playwright browser backend

**What changed:** New **`tools/fetch_browser.py`** — **`fetch_via_browser(url, timeout_seconds=20)`** uses Playwright sync Chromium headless: public **http(s)** only, **`domcontentloaded`** goto with bounded ms timeout, **`page.inner_text("body")`**, title + body merged, **4000** char cap; failures **`[fetch:browser_unavailable|browser_timeout|browser_error|browser_invalid_url]`** or **`[fetch:low_content]`** when thin/empty. Lazy Playwright import. **`tools/fetch_page.py`** registers **`browser`** in **`_FETCH_BACKENDS`** (toggle: **`FETCH_MODE=browser`**). **`services/prompt_builder.py`** routes new browser tags like other hard failures. **`requirements.txt`**: `playwright`. **`README.md`**: fetch modes + install note; regression count **198**. Four focused regression tests (mocks; no live browser). **`playground.py`**, Tool 1, system_eval: unchanged.

**Regression:** `198 / 198` PASS.

**Next:** CI/images: if jobs ever run real browser fetches, add `playwright install chromium` (or `--with-deps`) to the workflow; optional env `RUN_BROWSER_FETCH_TESTS` for manual live checks only.

---

### 2026-04-17 — FETCH Increment 4: manual browser smoke (validation note only)

**What changed:** No architecture or product code. Added **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`** — three-row manual set (example.com, reuters.com front, washingtonpost.com front), commands for **`FETCH_MODE=browser`**, and **Cursor host results**: Playwright **not installed** → all three returned **`[fetch:browser_unavailable]`** (same string). Regression confirmatory run green.

**Regression:** `198 / 198` PASS.

**Next:** Jessy re-runs the same three URLs locally after `pip install playwright` + `playwright install chromium`; append outcomes to the runbook table. Optional later: wire **`FETCH_BROWSER_TIMEOUT_SECONDS`** into facade if real runs show **`browser_timeout`** on news fronts.

---

### 2026-04-17 — FETCH Increment 4 completion: real browser smoke + runbook update

**What changed:** **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`** — replaced placeholder with **venv Playwright** results for `https://example.com` (success), `https://www.reuters.com` (`[fetch:low_content]`), `https://www.washingtonpost.com` (`[fetch:browser_error]` HTTP2). Documented **unset `FETCH_MODE` before regression** (browser mode breaks HTTP-mocked fetch tests). No product code / playground / Tool1 / system_eval edits.

**Regression:** `198 / 198` PASS (with `FETCH_MODE` cleared for the gate).

**Next:** Optional fetch tuning increment (wait strategy / HTTP2 retry) if approved.

---

### 2026-04-17 — FETCH Increment 5: browser navigation / wait stabilization (fetch_browser only)

**What changed:** **`tools/fetch_browser.py`** — `_goto_with_bounded_retries` (`domcontentloaded` then **`load`** on failure); `_bounded_post_goto_waits` (capped **`load`** + **`networkidle`**); Chromium **`--disable-http2`** / **`--disable-quic`**; `_chromium_launch_args()` testable. Title + `inner_text("body")` unchanged. **`playground.py`**, Tool 1, system_eval: untouched. Three mocked regression tests.

**Manual smoke (venv, `FETCH_MODE=browser`):** example.com success; reuters.com still `low_content`; washingtonpost.com **`browser_timeout`** (was `browser_error` / HTTP2 in prior run) — see **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`**.

**Regression:** `201 / 201` PASS with `FETCH_MODE` unset for gate.

**Next:** Env-driven browser timeout shipped as **Increment 6**; optional later: extraction heuristics for SPA fronts if approved.

---

### 2026-04-17 — FETCH Increment 6: env-driven browser timeout (facade only)

**What changed:** **`tools/fetch_page.py`** — **`browser_timeout_seconds_from_env()`** reads **`FETCH_BROWSER_TIMEOUT_SECONDS`** (default **20**, clamp **5–120**); **`_browser_adapter`** passes it to **`fetch_via_browser`**. **`fetch_page(url) -> str`**, **`[fetch:tag]`** grammar, **`prompt_builder`**: unchanged. **`tools/fetch_browser.py`**, extraction, routing, **`playground.py`**, Tool 1, system_eval: untouched. **`README.md`**: env note + baseline **204**. Three regression tests registered in **`tests/run_regression.py`**.

**Manual smoke (venv, `FETCH_MODE=browser`):** same three URLs as Increment 5 — example success, reuters `low_content`, washingtonpost **`browser_timeout`** at default 20s; with **`FETCH_BROWSER_TIMEOUT_SECONDS=90`**, WaPo **still `browser_timeout`** (detail shows 90000ms). See **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`**.

**Regression:** `204 / 204` PASS with **`FETCH_MODE`** unset for gate.

**Next:** SPA / `load` strategy tweaks shipped as **Increment 7** (bounded wait ladder in **`fetch_browser`** only).

---

### 2026-04-17 — FETCH Increment 7: bounded browser wait-strategy tuning (fetch_browser only)

**What changed:** **`tools/fetch_browser.py`** — **`_goto_with_bounded_retries`**: three-step ladder **`commit` → `domcontentloaded` → `load`**, each with **equal slice** of navigation **`timeout_ms`** (deterministic, no extra round-trips beyond three tries). **`_bounded_post_goto_waits`**: order **`domcontentloaded` → `networkidle` → `load`** with adjusted caps (still bounded, failures ignored). Title + **`inner_text("body")`** and merge/cap unchanged. **`fetch_page`**, **`prompt_builder`**, **`playground.py`**, Tool 1, system_eval: untouched. Regression: replaced two goto tests with three aligned to the ladder.

**Manual smoke (venv, `FETCH_MODE=browser`, default timeout):** example.com success; reuters.com still **`low_content`**; washingtonpost.com still **`browser_timeout`** — tag **did not** change; detail now shows **third-step `load`** with **~6666ms** slice (per-attempt budget), slightly clearer operator signal vs single full-timeout `goto`+`load`. See **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`**.

**Regression:** `205 / 205` PASS with **`FETCH_MODE`** unset for gate.

**Next:** Extraction-side landmark pass shipped as **Increment 8** (`fetch_browser` only).

---

### 2026-04-17 — FETCH Increment 8: bounded landmark extraction + optional scroll (fetch_browser only)

**What changed:** **`tools/fetch_browser.py`** — **`_bounded_extract_visible_text`**: take **`body`** then **`main`**, **`[role="main"]`**, **`article`** (``.first`` each); keep longest visible **`inner_text`** (deterministic). If merged length still below **`_LOW_CONTENT_THRESHOLD`**, **`_maybe_one_lazy_scroll`** (single **`scrollBy`**, **350 ms** `wait_for_timeout`) then **one** repeat extract. Title + merge + **4000** cap + **`[fetch:tag]`** paths unchanged. **`fetch_page`**, **`prompt_builder`**, **`playground.py`**, Tool 1, system_eval, timeout/env: untouched. One regression test (**`bounded_extract_prefers_main_landmark_over_thin_body`**).

**Manual smoke (venv, `FETCH_MODE=browser`, default timeout):** example.com success; **reuters.com still `low_content`** (snippet still **11** visible chars — landmark/scroll did not surface ≥80 merged chars on this host); washingtonpost.com still **`browser_timeout`**. See **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`**.

**Regression:** `206 / 206` PASS with **`FETCH_MODE`** unset for gate.

**Next:** Structured headline extraction shipped as **Increment 9** (`fetch_browser` only).

---

### 2026-04-17 — FETCH Increment 9: structured headline extraction (fetch_browser only)

**What changed:** **`tools/fetch_browser.py`** — **`_bounded_extract_headlines`**: deterministic pass over **`h1`**, **`h2`**, **`[role="heading"]`** (levels 1–2), **`header h1/h2`**, **`article h1/h2`** (capped counts, de-dupe by normalized text, **` | `** join, **1800** char cap). **`_prefer_headline_blob_over_visible`**: use headline blob when longer than visible, or when visible is below **`_LOW_CONTENT_THRESHOLD`** and headlines add material (**≥ max(16, len(visible)+4)**). Headlines sampled **before** visible path; when visible is thin, after lazy scroll take the **longer** of pre/post headline passes then prefer vs visible. Merge with title + **4000** cap + tags unchanged. **`fetch_page`**, timeout/env, **`prompt_builder`**, **`playground.py`**, Tool 1, system_eval: untouched. Regression: **`prefer_headline_blob_when_visible_thin_or_shorter`**.

**Manual smoke (venv, `FETCH_MODE=browser`, default timeout):** **`https://www.bbc.com/news`** — success (large text, **4000** cap hit); **`https://www.reuters.com`** — still **`low_content`** (merged visible **11** chars on this host — no headline **`inner_text`** bundle beat the threshold); **`https://www.washingtonpost.com`** — still **`browser_timeout`**. See **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`**.

**Regression:** `207 / 207` PASS with **`FETCH_MODE`** unset for gate.

**Next:** Bounded alternate DOM read (**text-node evaluate**) shipped as **Increment 10**.

---

### 2026-04-17 — FETCH Increment 10: bounded alternate DOM read (`evaluate` text-node walk)

**What changed:** **`tools/fetch_browser.py`** — **`_bounded_dom_text_nodes_via_eval`**: single **`page.evaluate`** script, DFS over child nodes from **`main` → `[role="main"]` → `body`**, collects **text nodes** only (skips **SCRIPT** / **STYLE** / **NOSCRIPT** / **TEMPLATE**), caps **140** stack pops and **2800** output chars, **`evaluate`** timeout **`min(inner_timeout, 5000)`** floor **2000** ms. After headline preference, if **`_prefer_headline_blob_over_visible(dom_eval, body_text)`** then replace **`body_text`**. Not **`inner_text`** / not headline locators. Navigation/timeouts unchanged. **`fetch_page`**, **`prompt_builder`**, **`playground.py`**, Tool 1, system_eval: untouched. Regression: **`bounded_dom_text_nodes_via_eval_calls_evaluate_with_timeout`**.

**Manual smoke (venv, `FETCH_MODE=browser`):** BBC news — success (**4000** cap); Reuters — still **`low_content`** (merged **11** chars — text-node walk did not yield a longer qualifying blob on this host); WaPo — still **`browser_timeout`** (failure mode unchanged). **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`**.

**Regression:** `208 / 208` PASS with **`FETCH_MODE`** unset for gate.

**Next:** Hard-target diagnostic classification shipped as **Increment 11**.

---

### 2026-04-17 — FETCH Increment 11: hard-target diagnostic classification (fetch_browser only)

**What changed:** **`tools/fetch_browser.py`** — After post-goto waits, **`_bounded_dom_probe_via_eval`** (single bounded **`evaluate`**) records **`b/m/r/a`** (body, main, role=main, article present), **`h1`/`h2`** counts (capped), **`bit`/`bct`** (body **innerText** / **textContent** lengths capped). **`probe_attempted`** distinguishes **`probe=none`** (navigation never reached probe) vs **`probe=failed`** (probe **`evaluate`** error/empty parse) vs full key=value probe. **`_nav_exc_class`** maps exceptions to stable **`exc=`** tokens (**`goto_timeout`**, **`blocked_transport`**, **`extract_timeout`**, etc.). **`_compact_diag_suffix`** appends **` diag=…`** (≤**220** chars) to **`browser_timeout`**, **`browser_error`**, and **`low_content`** human lines — **tag names unchanged**; **`fetch_failure_tag`** still parses. **`prompt_builder`**, **`playground.py`**, Tool 1, system_eval: untouched. Regressions: **`nav_exc_class_blocked_transport_and_goto_timeout`**, **`fetch_failure_tag_parses_low_content_with_diag_suffix`**.

**Manual smoke (venv, `FETCH_MODE=browser`):** Reuters **`low_content`** now includes **`diag=mrg=11;probe=failed`** (navigation completed; probe did not return a snapshot — classify separately from “thin DOM with numbers”). WaPo **`browser_timeout`** includes **`diag=exc=goto_timeout;probe=none`** (timeout during **`goto`**, no post-nav probe). BBC unchanged success.

**Regression:** `210 / 210` PASS with **`FETCH_MODE`** unset for gate.

**Next:** Probe resilience shipped as **Increment 12**.

---

### 2026-04-17 — FETCH Increment 12: probe resilience (fetch_browser only)

**What changed:** **`tools/fetch_browser.py`** — DOM probe hardened only: **`JSON.stringify`** primary with per-selector **`try/catch`** in JS; **`json.loads`** / **`int(float())`** normalization in **`_normalize_probe_dict`** / **`_probe_dict_from_evaluate_result`**; **two** primary **`evaluate`** attempts (slightly different timeouts); **pipe** fallback (**`fb=1`**); **micro** tier (**`fb=2`**) two tiny length-only evaluates; if all tiers return nothing usable, synthetic **`st=1`** (Python-side “all bounded probe evaluates exhausted”) so post-nav **`low_content`** no longer ends with misleading **`probe=failed`** when navigation completed. **`diag=`** format and **`[fetch:tag]`** grammar unchanged. No extraction/navigation/env edits. Regressions: **`probe_dict_from_evaluate_result_accepts_json_string`**, **`normalize_probe_dict_coerces_floaty_values`**, **`bounded_dom_probe_fallback_pipe_parses`**, **`bounded_dom_probe_micro_lengths_sets_fb2`**, **`bounded_dom_probe_via_eval_sets_st_when_all_evaluate_fail`**.

**Manual smoke (venv, `FETCH_MODE=browser`):** Reuters **`low_content`** line now **`diag=mrg=11;st=1`** (replaces prior **`probe=failed`** on this host — signals all bounded **`evaluate`** probe paths unusable after navigation, distinct from WaPo pre-probe timeout). WaPo / BBC unchanged vs Increment 11.

**Regression:** `215 / 215` PASS with **`FETCH_MODE`** unset for gate.

**Next:** Operator-facing **`diag=`** glossary shipped as **Increment 13** (runbook + README pointer only).

---

### 2026-04-17 — FETCH Increment 13: operator-facing fetch diagnostics polish (docs only)

**What changed:** **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`** — new **Operator reference: `diag=` suffix** section (table: **`mrg`**, **`b`/`m`/`r`/`a`**, **`h1`/`h2`**, **`bit`/`bct`**, **`fb`**, **`js`**, **`st`**, **`probe=none`/`probe=failed`**, **`exc=`**); quick-read patterns; Increment 13 cross-link under Increment 12 notes. **`README.md`** — one sentence pointing to that runbook section. **No** **`tools/fetch_browser.py`**, **`playground.py`**, Tool 1, or system_eval edits; no new probe tiers.

**Regression:** unchanged **215 / 215** (no code changes).

**Next:** As needed — further FETCH slices only when approved.

---

### 2026-04-17 — UI Increment 1: Windows one-click Streamlit launcher (no UI redesign)

**What changed:** **`Launch-Agent-UI.cmd`** — `cd` to repo root, require **`.venv-win\Scripts\python.exe`**, run **`python -m streamlit run app\ui.py`** (absolute path to `app\ui.py`). **`README.md`** — pointer to launcher + runbook pinning section. **`docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`** — new **Windows one-click launch** (launch, pin via shortcut, relaunch); manual verification §1 prefers launcher on Windows.

**Not changed:** `app/ui.py` layout/tabs, Tool 1, `system_eval`, fetch, `playground.py`.

**Regression:** not required (no Python product code); gate unchanged **215 / 215**.

**Next:** Open UI with Jessy; follow-up UI increments for layout/operator clarity when approved.

---

### 2026-04-17 — Doc sweep: FETCH closure + UI lane (operator-readable handoffs)

**What changed:** Single alignment pass across **`docs/handoffs/HANDOFF_RECENT_WORK.md`** (lanes + FETCH/UI sections), **`CHATGPT_DAILY_BOOTSTRAP.md`**, **`CHATGPT_COLLAB_SYNC.md`** (snapshot **215**, precision map, paste order), **`PROJECT_STORY_AND_SOURCES.md`** (narrative snapshot + map row for fetch runbook), **`docs/specs/PROJECT_SPECIFICATION.md`** (fetch facade, `fetch_http`/`fetch_browser`, launcher + dev shell rows, **215** baseline), **`docs/reliability/RELIABILITY_EVIDENCE.md`** (**215**), **`CHANGELOG.md`** (merged 2026-04-17 milestone bullets), **`docs/README.md`** (index). **No** `playground.py`, fetch behavior, Tool 1 logic, or `app/ui.py` product edits.

**Intent:** Any reader (Jessy, ChatGPT, Cursor) can see that **FETCH (browser) shipped through Increment 13**, hard sites may still be thin/timeout, **`diag=`** + **`FETCH_BROWSER_MANUAL_VALIDATION`** explain tokens, and the **active lane is UI** (Increment 1 launcher done; cockpit design next).

**Regression:** unchanged **215 / 215** (docs only).

**Next:** UI Increment 2+ when approved (Streamlit operator UX); FETCH only if explicitly reopened.

---

*(Add new entries below this line.)*
