# AI System Test Engineering Roadmap

## Mission

Evolve `ai-agent` into a reliable, fast, evidence-first assistant for testing other AI systems.

Primary outcome: help the operator act as a strong test engineer by generating, running, and evaluating reproducible AI-system tests with clear troubleshooting artifacts.

## Product Direction

- **Core role:** AI test-engineering copilot
- **Primary domain:** test design, execution, evaluation, and failure triage for external AI systems
- **Non-goal (for now):** broad autonomous operations outside the testing mission

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
- Phase 2+ work is not allowed until Phase 1 V0.1 acceptance criteria are satisfied and recorded in `RELIABILITY_EVIDENCE.md`.
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

First implementation slice to start now:

1. Define test suite schema for external targets
2. Implement adapter interface and first HTTP adapter
3. Implement `system_eval_runner` with artifact output
4. Add regression tests for runner correctness and failure handling
5. Document runbook usage and acceptance criteria

Current enforcement: no Phase 2+ scope may start until Phase 1 V0.1 acceptance criteria are explicitly met and recorded.

## Session Continuity

If a session is interrupted, resume from this file and continue Phase 1 from the current implementation slice.
