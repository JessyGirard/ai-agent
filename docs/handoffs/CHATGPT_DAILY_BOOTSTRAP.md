# ChatGPT daily bootstrap — reply + protocol (Cursor ↔ ChatGPT)

**The problem we are solving:** Every ChatGPT session is empty memory. Jessy needs **zero friction** daily: paste once, get an assistant that is **as current as Cursor** on what we are building and what we did last.

**The solution:** A **living log** plus this page. ChatGPT does not “remember” yesterday; the **repo remembers** in `docs/handoffs/SESSION_SYNC_LOG.md`.

**Latest target (ChatGPT sync):** **`SESSION_SYNC_LOG.md` (bottom entries) always wins.** As of last alignment: **FETCH (browser) lane** complete through **Increment 13** (**`FETCH_MODE=browser`**, **`diag=`** glossary **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`**). **UI + Tool 1 (API surface):** **`Launch-Agent-UI.cmd`** + **`app/ui.py`** — top bar surfaces, single-request **auth helpers** (Bearer/Basic/API key), **customer run summary**, **rerun last request** + copyable request + approximate **curl**, per-case outcome detail; **durable run log** append-only **`logs/tool1_runs.jsonl`** via **`app/tool1_run_log.py`** (each record includes a plain-text **`summary`**; **`run_log_error`** on bundle if append fails). **Milestone:** live run **`tool1_demo_public_smoke.json`** → **PASS 3/3** — Tool 1 **proven on real public HTTP**. **Demo suites:** **`system_tests/suites/tool1_public_demo/`** (runbook §4a). **Engine:** **`core/system_eval.py`** — includes **`steps`** scenarios, **`step_templates`** / **`use`**, **`{{variable}}`** substitution, **`step_results`** in JSON + **`### Steps`** in **`.md`** artifacts (Increments 42–46; see log). Regression **297 / 297**. **PR #2** not started unless the log says otherwise.

---

## What Jessy pastes at the start of a new ChatGPT chat (copy below)

```text
You are the planning + scope copilot for the ai-agent repo. You have NO memory of prior chats.

MANDATORY — read in this order before advising:
1) docs/handoffs/SESSION_SYNC_LOG.md (read last 3 entries from the bottom if the file is long; otherwise read whole file)
2) docs/handoffs/PROJECT_STORY_AND_SOURCES.md (project narrative + where full history lives — not everything is duplicated in the log)
3) docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md (this protocol)
4) docs/handoffs/THREE_TOOLS_ALIGNMENT_BRIEF.md (three tools + decisions)
5) docs/roadmaps/TEST_ENGINEERING_ROADMAP.md (north star + phase rules)
6) docs/reliability/RELIABILITY_EVIDENCE.md (gates + evidence paths)

Product we are building: an “AI Testing Workbench” — ONE shared testing spine (system_eval + suites + runner) and THREE tool profiles: (1) API reliability, (2) prompt↔response, (3) regression. Not three separate systems.

Hard rules:
- ONE small increment at a time; reject bundling (adapters + evaluation + reporting together).
- Keep system_eval isolated from playground.py unless we explicitly decide otherwise with tests.
- Regression must pass before commit: python tests/run_regression.py
- If docs conflict: docs/reliability/RELIABILITY_EVIDENCE.md and passing tests beat opinions.

Latest target (verify bottom of docs/handoffs/SESSION_SYNC_LOG.md — log wins):
- FETCH lane (browser): shipped through Incr. 13; `diag=` + `docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`
- UI + Tool 1 (API): `app/ui.py` — auth helpers, summaries, rerun/copy, outcomes; `app/system_eval_operator.py` logs suite runs
- Tool 1 durable log: `app/tool1_run_log.py` + `logs/tool1_runs.jsonl` — full JSON plus human `summary` per line (Inc 18); public demo suites `system_tests/suites/tool1_public_demo/` (Inc 19); runbook §4a
- **Milestone:** `tool1_demo_public_smoke.json` ran live **PASS 3/3** — Tool 1 operationally proven; **next focus = engine/assertion power (Inc 20+)**, not demo expansion
- HTTP system_eval: `core/system_eval.py` — assertions + **`steps`** / **`step_templates`** / **`{{var}}`** substitution + **`step_results`** (see `README.md` and `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`)
- Fetch facade: HTTP default; optional `FETCH_MODE=browser`; `[fetch:…]` tags; unset `FETCH_MODE` before regression gate
- Regression gate: 297 / 297 at last recorded run
- Not started unless log updates: PR #2 prompt↔response; optional = Tool 1 recent-log UI / chat try/except (see log)

Your job each session:
- Confirm scope: no phase drift, no unsafe bundling.
- Suggest the single smallest next step if Jessy asks.
- Reject proposals that bundle adapters + evaluation + reporting in one step.
- For any code change, name files to touch and what regression/scenarios prove it.
- If Jessy pastes a Cursor SYNC block, validate it and reply with approve / adjust / reject + why.

Handoff recovery (if Jessy cannot attach everything): insist on at least `docs/handoffs/SESSION_SYNC_LOG.md` (read from bottom) plus `README.md`, `docs/reliability/RELIABILITY_EVIDENCE.md`, `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md`, and the latest Cursor SYNC MESSAGE if Jessy has it.

No silent changes rule: do not assume Cursor changed architecture or scope without a matching bottom entry in SESSION_SYNC_LOG and a green regression claim.

Core principle: one small provable slice at a time; do not trust claims not backed by tests or artifacts.

Acknowledge by summarizing the latest log entry in 3–5 bullets, then wait for Jessy’s question.
```

---

## Cursor ↔ ChatGPT communication protocol (strict)

**Reality check:** Cursor cannot post to ChatGPT by itself. **Jessy** is the transport: copy sync blocks both directions.

### After every Cursor work session (Cursor → Jessy → ChatGPT)

Jessy asks Cursor for a **SYNC MESSAGE** in this shape (Cursor must provide this when work stops):

```
[SYNC MESSAGE]

1. Current State
- What was implemented (or “planning only”)
- Files touched (paths)

2. Test Status
- Regression: X / Y PASS (from latest python tests/run_regression.py)
- system_eval_runner smoke: yes/no (e.g. `yes` if regression includes `system_eval_runner_script_smoke_with_fake_http`, else `not run` or `manual`)
- Soak / other long runs: yes/no + note

3. Scope Check
- Still within agreed PR scope? (yes/no)
- Phase drift risk? (low/med/high)

4. Next Proposed Step
- ONE increment only

5. Risks / Uncertainty
- Open questions

[END]
```

**Immediately after:** Jessy (or Cursor in the same session) appends a matching summary to **`docs/handoffs/SESSION_SYNC_LOG.md`** (bottom of file). That append is what makes ChatGPT “come alive” tomorrow.

### ChatGPT → Cursor

ChatGPT replies with: **approve** / **adjust: …** / **reject: …** and a single recommended next step. Jessy pastes that into Cursor when implementation continues.

### Source of truth priority (if conflict)

1. `docs/reliability/RELIABILITY_EVIDENCE.md`
2. Passing tests + artifacts
3. Current code
4. `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md`
5. Latest bottom entries in `docs/handoffs/SESSION_SYNC_LOG.md` (what we last agreed / did)
6. ChatGPT advice

### Operating loop (repeat)

1. Agree **one** small change (Cursor + ChatGPT + Jessy as needed).
2. Implement in Cursor.
3. Run `python tests/run_regression.py` (record **actual** X / Y).
4. Cursor gives Jessy a **SYNC MESSAGE**; Jessy may paste it to ChatGPT for approve/adjust/reject.
5. Append the same summary to **`docs/handoffs/SESSION_SYNC_LOG.md`** (bottom).
6. Repeat.

### No silent changes

- No architecture or scope expansion without an updated **SESSION_SYNC_LOG** entry and explicit alignment.
- No merging work that skips regression when code changed.
- Cursor cannot message ChatGPT directly — **Jessy** carries sync both ways.

---

## Operator checklist (Jessy — end of day)

- [ ] Latest Cursor session has a SYNC MESSAGE
- [ ] `SESSION_SYNC_LOG.md` has a new bottom entry (same day as work)
- [ ] If regression was run, log shows **actual** X / Y counts

---

## Related files

- `docs/handoffs/SESSION_SYNC_LOG.md` — **append-only** project heartbeat
- `docs/handoffs/PROJECT_STORY_AND_SOURCES.md` — **story + map** to all historical sources (full history is distributed on purpose)
- `docs/handoffs/THREE_TOOLS_ALIGNMENT_BRIEF.md` — three-tool framing + ChatGPT paste for decisions
- `docs/handoffs/CHATGPT_COLLAB_SYNC.md` — longer collaboration guardrails + canonical doc order

---

*This file is stable protocol; day-to-day truth lives in `SESSION_SYNC_LOG.md`.*
