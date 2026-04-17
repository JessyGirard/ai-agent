# AI System Test Engineering Roadmap

## Mission

Evolve `ai-agent` into a reliable, fast, evidence-first assistant for testing other AI systems.

Primary outcome: help the operator act as a strong test engineer by generating, running, and evaluating reproducible AI-system tests with clear troubleshooting artifacts.

## Long-Term North Star

Build a personal AI assistant that grows with the operator over time, retains relevant context, and provides consistent support for important life and work decisions.

This roadmap defines the first mission only: use test-engineering capability as the foundation layer for long-term trust, reliability, and usefulness.

## Product Direction

- **Core role:** AI test-engineering copilot
- **Primary domain:** test design, execution, evaluation, and failure triage for external AI systems
- **Non-goal (for now):** broad autonomous operations outside the testing mission in this roadmap phase

## Build Principles

- Keep reliability gates mandatory (`run_regression.py`, soak gates, CI/nightly workflows).
- Build in small vertical slices with artifact-backed proof at each step.
- Prefer deterministic checks first; use model-based judging as a bounded secondary layer.
- Avoid over-claims; tie all claims to explicit validated conditions.

## Execution Correction Constraints (Mandatory)

This roadmap has a hard execution constraint layer: scope must expand only after the current vertical slice is proven and isolated.

- Build one real, provable slice at a time.
- Do not combine adapter expansion, evaluation expansion, and reporting redesign in the same increment.
- Keep `system_tests` isolated from `playground.py` orchestration and from runtime memory/journal systems.
- Do not alter reliability gates while expanding test-engineering capabilities.
- Phase 2+ work is not allowed until Phase 1 V0.1 acceptance criteria are satisfied and recorded in `docs/reliability/RELIABILITY_EVIDENCE.md`.
- Treat this as a constrained build-up, not a framework expansion race.

## Target Capability Model

### 1) Target Adapters

Support controlled execution against external systems:

- HTTP/API targets (first)
- CLI targets (second)
- Browser/UI targets (later, optional)

### 2) Test Execution Engine

- Run structured suites
- Capture request/response traces
- Measure timing, retries, and failure types
- Emit machine-readable artifacts

### 3) Evaluation Layer

- Deterministic assertions (schema, regex, keyword, exact match, status)
- Optional rubric-based evaluation for nuanced responses
- Confidence + rationale + disagreement reporting

### 4) Reporting and Triage

- JSON and markdown summaries
- Failure taxonomy (timeout, transport, schema, assertion, evaluation disagreement)
- Repro metadata (input, config, seed, runtime context)

## Phased Delivery Plan (Fast and Safe)

## Phase 1: API Test Runner (V0.1, constrained)

Deliver one constrained vertical slice:

- one minimal suite format (JSON)
- one HTTP execution path
- runner that executes suites and writes artifacts
- deterministic assertions and clear pass/fail exits

Exit criteria:

- one test runs successfully end-to-end
- assertions are deterministic and reproducible
- one artifact format is written correctly
- correct process exit codes (`0` pass, non-zero fail)
- regression gate remains green
- `system_tests` layer remains isolated from core agent orchestration

### Phase 1 (V0.1) explicit non-goals

Do not implement yet:

- CLI adapters
- browser/UI adapters
- multi-target execution
- model-based evaluation or judge scoring
- ranking/comparison systems
- dynamic test generation
- coupling between the runner and `playground.py`

## Phase 2: Quality Evaluation Expansion (after V0.1 sign-off)

- add richer assertion types
- add optional bounded model-judge mode
- add side-by-side deterministic vs judge result comparison

Exit criteria:

- no regressions in deterministic mode
- judge mode is optional and clearly bounded

## Phase 3: Comparative Benchmarking (after Phase 2 stability)

- run same suite against multiple targets/models
- diff quality/latency/reliability outputs
- produce ranking and drift signals

Exit criteria:

- one command for multi-target comparison
- artifact-backed comparison report

## Phase 4: Remote and Operational Hardening (after Phase 3 stability)

- authenticated remote targets
- rate-limit aware scheduling/retries/timeouts
- secure handling of target credentials

Exit criteria:

- robust remote execution policy
- failure triage remains deterministic and traceable

## What “Strong and Fast” Means Here

- Fast iteration cadence with protected quality gates
- Directly actionable troubleshooting data every run
- No hidden pass/fail logic; transparent criteria
- Reliability evidence always produced as artifacts

## Current Implementation Intent

Phase 1 (V0.1) implementation status in-repo:

1. Suite schema for HTTP cases — **done** (`system_tests/suites/example_http_suite.json`, validated in `core/system_eval.py`).
2. Adapter interface + HTTP adapter — **done** (`core/system_eval.py`).
3. `system_eval_runner` + artifacts — **done** (`tools/system_eval_runner.py`).
4. Regression coverage — **done** (`tests/run_regression.py`).
5. Runbook + acceptance criteria pointer — **done** (`docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`, `docs/reliability/RELIABILITY_EVIDENCE.md`).

**Safe optional next (no code required):** run a copied suite against a staging endpoint you control and keep the emitted JSON/MD as a real-world evidence run.

**When you choose to extend:** Phase 2+ remains one small vertical slice at a time; do not bundle evaluation expansion, adapters, and reporting in a single change.

Current enforcement: no Phase 2+ scope may start until Phase 1 V0.1 acceptance criteria are explicitly met and recorded.

## Near-term path (product framing + agreed code sequence)

**Framing:** Treat the product as an **AI Testing Workbench** — one shared spine (`core/system_eval.py`, `tools/system_eval_runner.py`, `system_tests/suites/*.json`) and **three tool profiles**: (1) API reliability, (2) prompt↔response testing, (3) regression (`tests/run_regression.py`). Detail: `docs/handoffs/THREE_TOOLS_ALIGNMENT_BRIEF.md`.

**Next code increment (PR #1, when started):** extend the HTTP suite / runner with **API reliability lanes** (stability / correctness / consistency — exact behavior locked in `tests/run_regression.py`). No prompt-response-only schema work, no new adapters, no `playground.py` coupling in the same PR.

**After PR #1:** prompt↔response schema or conventions (PR #2); optional regression “operator surface” wrapper (PR #3). Reconcile this list with `docs/handoffs/SESSION_SYNC_LOG.md` (bottom entries always win for “what we did last”).

## Session Continuity

If a session is interrupted, resume from this file and check the latest entry in `docs/handoffs/SESSION_SYNC_LOG.md`. Phase 1 baseline is complete; forward work follows **Near-term path** above unless the log records a deliberate change.
