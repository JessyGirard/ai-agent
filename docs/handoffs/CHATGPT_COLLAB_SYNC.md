# ChatGPT Collaboration Sync

## Purpose

Use this document to keep external ChatGPT sessions aligned with the live repository state managed in Cursor.

This project uses a human-in-the-loop collaboration model:

- Cursor assistant executes code changes and validation in-repo.
- External ChatGPT provides second-opinion reasoning and correction memos.
- Final implementation decisions are applied through you in this repository.

## Canonical Source Order

When starting any new ChatGPT session, use these docs in order:

0. `docs/handoffs/SESSION_SYNC_LOG.md` (latest entries: what we did last; read last 3 from bottom if long)
0a. `docs/handoffs/PROJECT_STORY_AND_SOURCES.md` (project story + where full history lives)
0b. `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md` (paste message + Cursor↔ChatGPT protocol)
1. `README.md` (current runtime + commands)
2. `docs/reliability/RELIABILITY_EVIDENCE.md` (gates + evidence + acceptance criteria)
3. `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md` (mission + phase constraints)
4. `docs/handoffs/HANDOFF_RECENT_WORK.md` (detailed implementation history)
5. `CHANGELOG.md` (milestone chronology)

## Precision Reference Map (If You Need X, Read Y)

- **Current run commands and operator workflow:** `README.md`
- **Reliability claims, acceptance criteria, and bounded scope:** `docs/reliability/RELIABILITY_EVIDENCE.md`
- **What we are building now and what is forbidden right now:** `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md`
- **Detailed history of what changed and why:** `docs/handoffs/HANDOFF_RECENT_WORK.md`
- **Milestone timeline by commit era:** `CHANGELOG.md`
- **Current test harness and gate implementation:** `tests/run_regression.py`, `tests/run_soak.py`
- **Phase 1 system-test runtime path:** `core/system_eval.py`, `tools/system_eval_runner.py`
- **Example suite input shape:** `system_tests/suites/example_http_suite.json`
- **Operator runbook (HTTP system eval + Streamlit + top bar surfaces on Windows):** `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`
- **Tool 1 durable run log (append-only JSONL):** `app/tool1_run_log.py` → `logs/tool1_runs.jsonl` (gitignored under `logs/`); each record includes plain-text **`summary`** plus full structured fields. **Public demo suites:** `system_tests/suites/tool1_public_demo/` (runbook §4a).
- **Browser fetch manual checks + `diag=` token glossary:** `docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`
- **One-click Streamlit (Windows):** `Launch-Agent-UI.cmd` (repo root; uses `.venv-win`); taskbar shortcuts: `Create-Agent-UI-Shortcut.ps1`
- **CI/automation policy and schedule:** `.github/workflows/ci.yml`, `.github/workflows/nightly-soak.yml`
- **Core orchestration boundary (must remain decoupled):** `playground.py`

## Ask Templates for External ChatGPT

Use these exact prompt styles when you want precise help:

- **Scope check:** "Based on `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md`, is this proposed change still Phase 1 V0.1 or does it drift into Phase 2+?"
- **Reliability check:** "Validate this proposal against `docs/reliability/RELIABILITY_EVIDENCE.md` acceptance criteria and tell me any over-claim risk."
- **Implementation review:** "Given `core/system_eval.py` and `tools/system_eval_runner.py`, suggest the smallest safe next step that preserves isolation from `playground.py`."
- **Test adequacy review:** "Given `tests/run_regression.py`, what minimum additional deterministic tests are needed for this change?"
- **Release gate review:** "List the exact commands and artifacts required before this change is considered acceptable."

## Current Project Snapshot

- Runtime architecture is modularized and stabilized:
  - `core/persistence.py`
  - `services/memory_service.py`
  - `services/journal_service.py`
  - `services/routing_service.py`
  - `services/prompt_builder.py`
- Protected regression gate currently: **`297`** scenarios (`python tests/run_regression.py`). Confirm with latest log if this drifts.
- **Fetch:** `tools/fetch_page.py` facades HTTP (`tools/fetch_http.py`) and optional browser mode (`FETCH_MODE=browser` → `tools/fetch_browser.py`); operator diagnostics use compact **`diag=`** suffixes documented in `docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`.
- **Operator UI:** Streamlit `app/ui.py` (Agent + **API** Tool 1: single-request auth merge, summaries, rerun/copy, run-log warnings); Windows daily launch via `Launch-Agent-UI.cmd` (see `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`). **Tool 1 evidence:** `tool1_runs.jsonl` human **`summary`** lines; runnable **`system_tests/suites/tool1_public_demo/`** packs for demos.
- Soak reliability is enforced with chunked runs and artifact outputs.
- CI and nightly automation are configured via:
  - `.github/workflows/ci.yml`
  - `.github/workflows/nightly-soak.yml`
- Phase 1 (V0.1) system eval is implemented; further test-engineering work must stay one small vertical slice at a time. **Active product attention:** Tool 1 **proven on live public smoke suite** (PASS 3/3); engine now includes **`steps`**, **`step_templates`**, **`{{var}}`** substitution, **`step_results`**, and markdown **`.md`** step summaries (Inc 42–46); operator polish + durable log + **`summary`** remain shipped; UI cockpit (FETCH lane closed at Incr. 13).

## Non-Negotiable Constraints

- No large multi-area jumps (adapters + evaluation + reporting in one increment).
- No coupling of `system_tests` runner logic into `playground.py`.
- No bypass of regression/soak gates.
- No over-claims beyond validated conditions in `docs/reliability/RELIABILITY_EVIDENCE.md`.

## Conflict-Resolution Priority Rule

If repository docs, current code/tests, and external advice disagree, resolve in this order:

1. `docs/reliability/RELIABILITY_EVIDENCE.md` acceptance criteria
2. current passing tests and artifacts
3. current code behavior
4. `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md` intent
5. external ChatGPT advice

## What We Are Building Now

Current mission: evolve this project into an AI-system test-engineering copilot safely (see long-term North Star in `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md`).

Phase 1 (V0.1) foundation is in place:

- minimal suite format
- single HTTP execution path
- deterministic assertions
- artifact-backed output
- gate-verified behavior

Optional near-term: real staging runs per `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`; next code increments only as small, explicit slices.

## Copy/Paste Bootstrap for New ChatGPT Session

Use this block as your first message to external ChatGPT:

```text
You are joining an ongoing repository workflow as a secondary reasoning reviewer.

Ground truth is the local repo docs in this order:
1) docs/handoffs/SESSION_SYNC_LOG.md (bottom entries)
2) README.md
3) docs/reliability/RELIABILITY_EVIDENCE.md
4) docs/roadmaps/TEST_ENGINEERING_ROADMAP.md
5) docs/handoffs/HANDOFF_RECENT_WORK.md
6) CHANGELOG.md

Important constraints:
- Phase 1 (V0.1) HTTP system eval is implemented and recorded in docs/reliability/RELIABILITY_EVIDENCE.md; optional next steps are real staging runs (docs/runbooks/SYSTEM_EVAL_RUNBOOK.md) or deliberately small Phase 2 slices.
- FETCH browser work is documented in docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md (lane closed at Inc 13 per SESSION_SYNC_LOG). UI: Launch-Agent-UI.cmd + runbook; **API** = Tool 1 (system eval + single-request helpers + append-only logs/tool1_runs.jsonl with human summary per line + demo suites under system_tests/suites/tool1_public_demo/). **Milestone:** live smoke suite PASS 3/3 — next engine/assertion increments per SESSION_SYNC_LOG bottom. **Prompt** / **Regression** = placeholders until approved increments.
- Regression gate: unset FETCH_MODE in the shell before python tests/run_regression.py unless a test intentionally sets it. Latest baseline: 297 scenarios — confirm SESSION_SYNC_LOG.md bottom if drift.
- Do not bundle adapter expansion, evaluation expansion, and reporting redesign in one change.
- Keep system_tests isolated from playground orchestration.
- Keep recommendations bounded to evidence in docs/reliability/RELIABILITY_EVIDENCE.md.

Task:
- Review the current proposed next step for over-scope risk.
- Provide correction guidance only if it preserves these constraints.
- Keep outputs practical, testable, and artifact-driven.
```

## How to Use This in Practice

- Before asking ChatGPT for advice, share this file plus the roadmap and reliability docs.
- If ChatGPT proposes changes, validate against:
  - V0.1 constraints
  - gate requirements
  - coupling boundaries
- Only then apply approved changes in Cursor and re-run gates.
