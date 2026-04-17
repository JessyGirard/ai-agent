# ChatGPT Collaboration Sync

## Purpose

Use this document to keep external ChatGPT sessions aligned with the live repository state managed in Cursor.

This project uses a human-in-the-loop collaboration model:

- Cursor assistant executes code changes and validation in-repo.
- External ChatGPT provides second-opinion reasoning and correction memos.
- Final implementation decisions are applied through you in this repository.

## Canonical Source Order

When starting any new ChatGPT session, use these docs in order:

1. `README.md` (current runtime + commands)
2. `RELIABILITY_EVIDENCE.md` (gates + evidence + acceptance criteria)
3. `TEST_ENGINEERING_ROADMAP.md` (mission + phase constraints)
4. `HANDOFF_RECENT_WORK.md` (detailed implementation history)
5. `CHANGELOG.md` (milestone chronology)

## Precision Reference Map (If You Need X, Read Y)

- **Current run commands and operator workflow:** `README.md`
- **Reliability claims, acceptance criteria, and bounded scope:** `RELIABILITY_EVIDENCE.md`
- **What we are building now and what is forbidden right now:** `TEST_ENGINEERING_ROADMAP.md`
- **Detailed history of what changed and why:** `HANDOFF_RECENT_WORK.md`
- **Milestone timeline by commit era:** `CHANGELOG.md`
- **Current test harness and gate implementation:** `tests/run_regression.py`, `tests/run_soak.py`
- **Phase 1 system-test runtime path:** `core/system_eval.py`, `tools/system_eval_runner.py`
- **Example suite input shape:** `system_tests/suites/example_http_suite.json`
- **CI/automation policy and schedule:** `.github/workflows/ci.yml`, `.github/workflows/nightly-soak.yml`
- **Core orchestration boundary (must remain decoupled):** `playground.py`

## Ask Templates for External ChatGPT

Use these exact prompt styles when you want precise help:

- **Scope check:** "Based on `TEST_ENGINEERING_ROADMAP.md`, is this proposed change still Phase 1 V0.1 or does it drift into Phase 2+?"
- **Reliability check:** "Validate this proposal against `RELIABILITY_EVIDENCE.md` acceptance criteria and tell me any over-claim risk."
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
- Protected regression gate currently: `173` tests.
- Soak reliability is enforced with chunked runs and artifact outputs.
- CI and nightly automation are configured via:
  - `.github/workflows/ci.yml`
  - `.github/workflows/nightly-soak.yml`
- Test-engineering expansion is under constrained Phase 1 (V0.1).

## Non-Negotiable Constraints

- No scope expansion beyond Phase 1 (V0.1) until acceptance criteria are explicitly met.
- No coupling of `system_tests` runner logic into `playground.py`.
- No bypass of regression/soak gates.
- No over-claims beyond validated conditions in `RELIABILITY_EVIDENCE.md`.

## Conflict-Resolution Priority Rule

If repository docs, current code/tests, and external advice disagree, resolve in this order:

1. `RELIABILITY_EVIDENCE.md` acceptance criteria
2. current passing tests and artifacts
3. current code behavior
4. `TEST_ENGINEERING_ROADMAP.md` intent
5. external ChatGPT advice

## What We Are Building Now

Current mission: evolve this project into an AI-system test-engineering copilot safely.

Current implementation lane (Phase 1 V0.1):

- minimal suite format
- single HTTP execution path
- deterministic assertions
- artifact-backed output
- gate-verified behavior

## Copy/Paste Bootstrap for New ChatGPT Session

Use this block as your first message to external ChatGPT:

```text
You are joining an ongoing repository workflow as a secondary reasoning reviewer.

Ground truth is the local repo docs in this order:
1) README.md
2) RELIABILITY_EVIDENCE.md
3) TEST_ENGINEERING_ROADMAP.md
4) HANDOFF_RECENT_WORK.md
5) CHANGELOG.md

Important constraints:
- Current lane is TEST_ENGINEERING_ROADMAP Phase 1 (V0.1, constrained).
- Do not propose Phase 2+ expansion until V0.1 acceptance criteria are explicitly satisfied.
- Keep system_tests isolated from playground orchestration.
- Keep recommendations bounded to evidence in RELIABILITY_EVIDENCE.md.

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
