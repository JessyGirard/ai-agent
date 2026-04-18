# Handoff: recent architecture, memory, and reliability work (for ChatGPT or other assistants)

**Purpose:** Paste this whole file into another chat so the other model knows **where the project is** after the last several increments, without needing full conversation logs.

**Project:** `ai-agent` (Python). Core loop: `playground.py`. Protected baseline tests: `python tests/run_regression.py` (documented in `README.md` as the release gate; pytest is supplemental).
**Current mission anchor:** `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md` (authoritative plan for building the AI-system test-engineering copilot).
**External collaboration sync:** `docs/handoffs/CHATGPT_COLLAB_SYNC.md` (copy/paste bootstrap + guardrails for external ChatGPT sessions).

**User preferences we followed:** small increments, low risk, no scope creep, regression must stay green before trusting changes.

**Aligned for new ChatGPT session (2026-04-17):** Protected baseline is **`297 / 297`** (`python tests/run_regression.py`) — confirm **`SESSION_SYNC_LOG.md` (bottom)** if newer. Before the gate, **`FETCH_MODE`** should be **unset** in the shell (leaking **`browser`** breaks HTTP fetch regression cases). **Tool 1 engine:** **`core/system_eval.py`** now supports **`steps`** scenarios, **`step_templates`** / **`use`**, **`{{variable}}`** substitution, **`step_results`** on case rows, and **`### Steps`** in markdown artifacts (see **`README.md`** and **`docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`**).

**Milestone (same day):** **`tool1_demo_public_smoke.json`** (3 cases) was run successfully against **live JSONPlaceholder** (**PASS 3/3**). Tool 1 is **operationally proven** end-to-end (suite path, UI, summaries, durable log + **`summary`**). **Phase lock:** next priority is **engine / assertion strength** (**Increment 20** and follow-ons), not additional demo fixtures unless explicitly requested.

**Lanes:** **FETCH (browser)** is **closed at Increment 13** (code path through **`tools/fetch_browser.py`**; Inc 13 = operator **`diag=`** glossary **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`** only). **UI lane** includes **UI Increments 1–8** (launcher, cockpit, top bar) **plus Tool 1 operator UX 10–17** in **`app/ui.py`** (see below). **Tool 1 log + fixtures:** **`app/tool1_run_log.py`** — schema still v1; each line now includes a shareable plain-text **`summary`** (Increment **18**). **Public demo suites** for practice/portfolio: **`system_tests/suites/tool1_public_demo/`** (Increment **19**; JSONPlaceholder + httpbin, no secrets). **Top surface bar:** **Agent / API / Prompt / Regression / Terminal** → same internal **`ui_surface`** keys; **agent-first** center (**`st.popover("⋯")`**); **minimal sidebar** (**Surface · backup** + **Advanced** with **Show state** / **Reset state** — still **`playground`**, unchanged this arc). Windows: **`Launch-Agent-UI.cmd`**, **`Create-Agent-UI-Shortcut.ps1`**, **`Open-DevShell.cmd`** / **`.venv-win`**, **`docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`**. **Durable run log:** append-only **`logs/tool1_runs.jsonl`** (full JSON + **`summary`**). **PR #2** (prompt↔response) not started unless the log says otherwise.

Also in repo: **HTTP system_eval** (`core/system_eval.py`, **`tools/system_eval_runner.py`**), **`tools/tool1_verify_server.py`**, **`FETCH_MODE=browser`** (Playwright) behind **`tools/fetch_page.py`**, **`[fetch:tag]`**, optional **`FETCH_BROWSER_TIMEOUT_SECONDS`**.

---

## What was done (rough chronological / thematic)

### FETCH lane — browser mode + operator diagnostics (2026-04-17, Increments 4–13)

- **`tools/fetch_page.py`** remains the facade: default **HTTP** (`tools/fetch_http.py`); set **`FETCH_MODE=browser`** for headless Chromium via **`tools/fetch_browser.py`** (public `http`/`https` only).
- **Navigation:** bounded **`goto`** retry ladder (**`commit` → `domcontentloaded` → `load`**), post-goto waits, optional **`FETCH_BROWSER_TIMEOUT_SECONDS`** (5–120s, browser nav budget only).
- **Extraction:** landmark preference (**`main` / `[role="main"]` / `article`**), optional bounded scroll, structured **headlines**, alternate **text-node** `evaluate` pass, deterministic merge/title cap; **`[fetch:tag]`** names unchanged for **`prompt_builder`** / regression.
- **Diagnostics:** compact **`diag=…`** suffix on **`browser_timeout`**, **`browser_error`**, **`low_content`** (probe snapshot keys, **`exc=`** classes like **`goto_timeout`**, **`fb=1`/`fb=2`** fallbacks, **`st=1`** when all bounded probe evaluates exhausted). Operator token glossary: **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`** (*Operator reference: `diag=` suffix*).
- **Manual validation** for hard sites (Reuters/WaPo/BBC, etc.): same runbook file.

### UI lane — operator cockpit (started 2026-04-17)

- **UI Increment 1:** **`Launch-Agent-UI.cmd`** at repo root; **`docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`** → *Windows one-click launch* (launch, **`Create-Agent-UI-Shortcut.ps1`** → taskbar pin, relaunch). **Increments 2–8** then evolved **`app/ui.py`** only (see bullets + log); no **`playground.py`** coupling.
- **UI Increment 2:** **`app/ui.py`** — operator cockpit scaffolding: **Assistant** tab first (quick prompts + **Agent access** chat region), **Tool 1** unchanged, **Tool 2/3** placeholders, **Terminal access** tab; see **`SESSION_SYNC_LOG.md`** (bottom).
- **UI Increment 3:** **`app/ui.py`** — sidebar + main status strip: **Current state** / **Environment** (fetch mode from env), operator hints, **Focus · Stage · Fetch** line above tabs; see log.
- **UI Increment 4:** **`app/ui.py`** — tab/panel copy only: Assistant **Shortcuts** vs **Conversation**, Tool 1 “when to use”, Tools 2–3 intentional placeholders + shorter tab labels, Terminal wording; see log.
- **UI Increment 5:** **`app/ui.py`** — agent-first layout: sidebar **radio** navigation replaces tabs; center defaults to **Agent**; context in sidebar expanders; see log.
- **UI Increment 6:** **`app/ui.py`** — minimal sidebar rail: radio + tiny status + secondary Show/Reset; state/fetch/memory only under **Advanced**; see log.
- **UI Increment 7:** **`app/ui.py`** — agent center: status/new chat/shortcuts into **`st.popover("⋯")`** (or expander fallback); conversation + input dominate; see log.
- **UI Increment 8:** **`app/ui.py`** — top surface bar (Agent/API/Prompt/Regression/Terminal) → same router keys; sidebar backup buttons; README + system eval runbook **API** wording; see log.

### Tool 1 — API tab operator slices (**`app/ui.py`** + **`app/system_eval_operator.py`**, **`app/tool1_run_log.py`**; **`core/system_eval.py`** for Inc 10 only)

- **Increment 10 (`core/system_eval.py` + harness):** minimal assertions **`expected_status`**, **`body_contains`**, **`header_contains`**; suite validation + regression coverage (engine; not repeated here).
- **Increment 11 (`app/ui.py`):** single-request **auth helpers** — None / Bearer / Basic / **API key**; merged headers (helper wins over JSON **`Authorization`** / same-named API key header).
- **Increment 12 (`app/ui.py`):** per-case **PASS/FAIL** clarity — run summary, transport vs assertion hints, failure text, **`run_log_error`**-style surfacing patterns; table **outcome** column.
- **Increment 13 (`app/ui.py`):** **API key** mode (header name + value) on top of Inc 11.
- **Increment 14 (`app/ui.py`):** **customer-readable** run summary + per-case “at a glance” lines; technical expanders preserved.
- **Increment 15 (`app/ui.py`):** **Rerun last request** (session snapshot), **copyable** plain request summary + approximate **curl** (`shlex`).
- **Increment 17 (`app/tool1_run_log.py` + wiring):** append-only **`logs/tool1_runs.jsonl`** — one JSON record per suite or single-request completion (or best-effort on early failure); bundle may include **`run_log_error`** if disk append fails; UI warns without blocking results.
- **Increment 18 (`app/tool1_run_log.py` only):** each log record gains a plain-text **`summary`** (readable paragraph: what was tested, pass/fail, tallies, first failure line, timing). **`compose_tool1_run_human_summary()`**; no removal of structured fields.
- **Increment 19 (fixtures + docs only):** **`system_tests/suites/tool1_public_demo/`** — three client-style demo suites (smoke PASS, intentional FAIL, header/Bearer echo PASS); **`README.md`** in folder; runbook §4a + **`README.md`** pointer. No engine/UI changes.

### Tool 1 — scenario engine + reporting (`core/system_eval.py` + harness only; 2026-04-17, Increments 42–46)

- **42 — Variable substitution:** `{{variable_name}}` in request **`url`** / header values / **`payload`** strings; variables from **`extract`** in the same case; missing → `variable not found` + JSON detail; without **`steps`**, optional **`request_url_initial`** / **`payload_initial`** / **`headers_initial`** for implicit two-hop; **`stability`**/**`consistency`** reject placeholders in requests.
- **43 — `steps`:** explicit ordered steps; per-step assertions + **`extract`**; shared **`variables`**; **`step failed`** + step id on failure; **`stability`**/**`consistency`** reject **`steps`**.
- **44 — `step_templates`:** reusable templates + **`use`**; merge / override rules; **`template not found`** when **`use`** is invalid (validate time).
- **45 — `step_results`:** JSON case output lists per-step **`PASS`**/**`FAIL`**, substituted **`url`**, **`latency_ms`**, optional **`reason`**.
- **46 — Markdown artifacts:** **`write_result_artifacts`** adds **`### Steps`** under each multi-step case in the **`.md`** file.

**Harness:** all coverage in **`tests/run_regression.py`**; baseline **`297 / 297`**.

### Structural stabilization sequence (architecture extraction; earlier phase)
- Extracted persistence/file I/O helpers into `core/persistence.py`.
- Extracted journal/outcome-feedback/recent-answer helpers into `services/journal_service.py`.
- Extracted memory scoring/retrieval/runtime-write logic into `services/memory_service.py`.
- Extracted routing/control-path logic into `services/routing_service.py`.
- Extracted prompt/answer assembly logic into `services/prompt_builder.py`.
- Kept orchestration and deterministic call ordering in `playground.py`.
- Preserved behavior through each step under the protected regression gate (baseline grew afterward; see top “Aligned” note — **297 / 297** at last full run).
- Added resilient soak execution in `tests/run_soak.py`:
  - progress checkpoints
  - chunked mode (`--chunk-size`)
  - synchronized final result/checkpoint/aggregate artifact writes
  - stable long-run proof execution (`10000` chunked pass)
- Added GitHub Actions automation:
  - `.github/workflows/ci.yml` (PR/push: regression + quick chunked soak)
  - `.github/workflows/nightly-soak.yml` (scheduled/manual: 10k chunked soak)

### Normalization & dedupe (earlier in thread)
- Stronger **canonical memory keys** (`canonicalize_memory_key_value`) so variants like hyphen vs space / punctuation don’t create duplicate memories.
- **Transient identity** filtering expanded (mood/state/temporal phrasing) so short-lived “I am …” lines don’t become durable identity memory.
- **Uncertainty phrases** initially blocked all runtime memory; then refined to **category-specific** behavior:
  - **preference / goal / identity:** uncertain phrasing still **skipped**
  - **project:** uncertain phrasing **allowed** (work-in-progress is often tentative)
- **Legacy duplicate merge** on memory load (`dedupe_memory_items`) so old JSON doesn’t keep near-duplicate rows forever.
- Explicit naming: **`normalize_memory_display_value`** vs **`canonicalize_memory_key_value`** (display vs dedupe).

### Display normalization tweak
- `normalize_memory_display_value`: normalize `-` / `_` to spaces **before** collapsing whitespace (avoids double spaces).

### Regression tests (harness)
- Most new behavior is locked in **`tests/run_regression.py`** (not only pytest).
- Examples of covered areas: memory key equivalence, transient / uncertain / question skips, display normalization, uncertain project allowed, uncertain goal skipped, retrieval ranking, conflicts, journal, tool fetch mocks, missing LLM key handling.

### Retrieval “smarts” (score-only, no schema migration)
- **Recency bonus** in `score_memory_item`: slight boost for `last_seen == "runtime"` and `trend == "reinforced"`.
- **Staleness penalty** (retrieval only): downrank imported / tentative / weak-evidence items so prompts don’t over-prefer stale rows. **Does not rewrite** stored `confidence` in JSON.

### Write-path conflict guard (identity / goal)
- Before writing runtime memory, if **same category** is `identity` or `goal`, detect **negation cue mismatch** vs an existing item with enough **token overlap** (Jaccard ≥ 0.35) → **skip write** (`write_runtime_memory` returns `None`). Avoids contradictory goals/identities piling up.

### Repo hygiene
- **`requirements.txt`:** added `requests`, `openai` (used by `tools/fetch_page.py` and `memory/extractors/run_extractor.py`).
- **`test_openai.py` / `test_claude.py`:** refactored so API calls run only under `main()`; if `RUN_LIVE_API_TESTS` is not `1`, scripts **exit without network** (safer for accidental `pytest` / imports).
- **`README.md`:** notes live API scripts + env gate.

### Documentation
- **`docs/specs/PROJECT_SPECIFICATION.md`** exists as a repo inventory/spec (separate from this handoff).

### Offline memory import / extract (latest)
- **`memory/import_chat.py`:** strips leading `USER:` / `AI:` / `ASSISTANT:` from each line (regex uses `re.IGNORECASE`, not inline `(?i)` after `^`). Still assigns roles by **line order** (user, assistant, user, …).
- **`memory/extractors/run_extractor.py`:**
  - **Merge by default:** loads existing `extracted_memory.json` and merges new extractions; same category+value key **reinforces** evidence. **`--replace`** wipes the in-memory map first (old full-replace behavior).
  - **Safety:** copies prior `extracted_memory.json` → **`memory/extracted_memory.pre_extract.json`** before each write (rotating). `.gitignore` ignores `pre_extract` and `extracted_memory.json.bak`.
  - **`EXTRACT_MESSAGE_LIMIT`** in `.env` (default 50, max 500) caps how many `imported.json` messages are processed per run.
  - **Stricter rows:** `validate_candidate` rejects values containing **`?`** or over **`MAX_MEMORY_VALUE_CHARS` (420)**; prompt tightened for declarative user facts.
  - **`meta.last_extract`** records merge stats (new vs reinforced, row counts).

### Playground: safety / “what keeps this safe?”
- **`project_safety_conversation_query`** + **`safety_signal_memory`** detect safety-style questions and memory that mentions regression / harness / `run_regression` / pytest / etc.
- **Retrieval:** extra score bonus so those memories surface.
- **Routing:** `detect_subtarget` → **`safety practices`** → forced **Answer** / **Next step** lines point at **`python tests/run_regression.py`** when appropriate; system prompt adds a rule to **connect testing to safety** without overriding focus/stage.

### Recent routing / control-surface hardening (latest)
- **Substring trap reductions:** removed/limited broad phrase matches that misrouted prompts (`memory system`, broad state-command text, `debugging`→`bug`, etc.).
- **Command interpretation guard:** command execution only applies to direct command lines (`set focus:`, `set stage:`, exact `show state` / `reset state`), not narrative examples (e.g. *"if I type 'set focus: ...'"*).
- **Tool-meta guard:** assistant `TOOL:fetch` output no longer triggers real fetch when user input clearly forbids tools or quotes/references literal tool syntax.
- **Strict/open mode tuning:** strict canned workflow now reserved for explicit next-step asks and narrow actionable subtargets; broader analytical questions default to open conversation.
- **System-risk branch:** dedicated risk reasoning path grounds answers in `playground.py` behavior (`detect_subtarget`, routing gates, strict-mode activation failure modes).

### Recent answer-quality / reasoning updates
- **Primary-intent focus in `build_answer_line`:** mixed prompts prioritize one intent (risk → goal → command → identity) and avoid splitting attention across secondary threads.
- **Grounded reasoning shape:** risk/weakness/architecture/system-behavior answers now explicitly use repo mechanisms (`detect_subtarget`, routing logic, strict-mode gating, state-over-memory priority) with cause→mechanism→consequence wording.
- **Sharper fallback phrasing:** generic answer fallbacks now reference concrete repo components (`playground.py`, regression harness) instead of broad project-language templates.

### Recent memory retrieval quality updates
- **Use-time filtering only:** `retrieve_relevant_memory` now ignores weak rows (`confidence < 0.5` and `evidence_count <= 1`) and keeps stronger rows (`confidence >= 0.6` or `evidence_count >= 2`).
- **Reinforced-pattern bonus:** `score_memory_item` adds a small `+0.10` when `evidence_count >= 3` and `trend == "reinforced"` (keeps intent/recency dominant while nudging stable patterns upward).

### Regression fixtures
- **`tests/fixtures/extractor_validation_cases.json`** — offline accept/reject cases for `validate_candidate` (no OpenAI).
- Harness also covers extractor merge helpers, `effective_message_limit`, and safety routing tests.

---

## Important clarifications (common confusion)

- **Cursor IDE chat** does **not** auto-feed into `memory/extracted_memory.json`. Runtime memory updates happen when **`playground.py` / Streamlit UI** runs and processes user lines, or via import/extractor pipelines.
- **Git** is visible to the IDE assistant when helping code; the **agent app** does not automatically read git state unless you add that later.

---

## How to verify current health

From repo root:

```bash
python tests/run_regression.py
```

At last full Cursor alignment (see `SESSION_SYNC_LOG.md` bottom), regression was **297 / 297** PASS. Re-run after any local edits.

---

## Files most touched in this phase

- `playground.py` — now narrowed to orchestration/runtime control flow and service wiring
- `core/persistence.py` — extracted state/memory/journal file I/O helpers
- `services/memory_service.py` — extracted memory retrieval/scoring/runtime write logic
- `services/journal_service.py` — extracted journal/outcome/recent-answer logic
- `services/routing_service.py` — extracted action/routing/control-path logic
- `services/prompt_builder.py` — extracted answer-line and prompt/message assembly logic
- `tests/run_regression.py` — regression harness **297** scenarios at last recorded run (see log)
- `tests/run_soak.py` — chunked soak and artifact synchronization
- `.github/workflows/ci.yml`, `.github/workflows/nightly-soak.yml` — automated reliability gates
- `tests/fixtures/extractor_validation_cases.json` — offline extractor validation cases
- `memory/import_chat.py`, `memory/extractors/run_extractor.py`
- `docs/specs/PROJECT_SPECIFICATION.md`, `.gitignore`
- `requirements.txt`
- `test_openai.py`, `test_claude.py`
- `README.md`
- **FETCH / browser:** `tools/fetch_page.py`, `tools/fetch_http.py`, `tools/fetch_browser.py`; operator runbook `docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`
- **UI / operator launch:** `app/ui.py` (Increments 2–8 + Tool 1 UX Inc 11–17: auth, summaries, rerun, logging), `app/system_eval_operator.py`, `app/tool1_run_log.py` (Inc 17–18: durable log + **`summary`**), `Launch-Agent-UI.cmd`, `Create-Agent-UI-Shortcut.ps1`, `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`
- **Tool 1 demo fixtures:** `system_tests/suites/tool1_public_demo/*.json`, folder `README.md` (Inc 19)

---

## Suggested “next moves” (not implemented here; optional)

- **Tool 1 engine (priority):** **Increment 20** — precision assertions: validate + regression-harden existing **`equals`** / **`regex`** body checks in **`core/system_eval.py`**, then thin follow-ups (e.g. JSON-canonical body equality or header-precision keys) **one slice at a time**. See **`SESSION_SYNC_LOG.md` (bottom)** milestone entry.
- **UI lane (Inc 9+):** `try`/`except` around **`run_query`** and sidebar **`playground.handle_user_input`** (graceful errors, state reset UX unchanged); optional **`st.segmented_control`** instead of five top buttons if desired.
- **Tool 1 log (optional):** read-only UI list of recent **`tool1_runs.jsonl`** rows (showing **`summary`** + timestamp) — keep thin; no dashboard explosion.
- **FETCH lane:** further slices only when approved (hard sites may still yield `low_content` / `browser_timeout`; use **`diag=`** + runbook to interpret).
- Tune negation / overlap thresholds if real usage shows false positives/negatives.
- Optional: score-only “time decay” if you add real timestamps later (still avoid silent JSON mutation unless intended).
- Optional: golden **live** extractor snapshots (mocked OpenAI) if you want prompt changes fully regression-gated without API cost.
- Optional: introduce a lightweight service context/container to reduce verbose dependency injection between `playground.py` and service modules while keeping behavior unchanged.

---

*End of handoff. Copy from the title through here into ChatGPT as needed.*
