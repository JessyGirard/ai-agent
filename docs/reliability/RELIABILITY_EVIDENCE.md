# Reliability Evidence

This document is the primary reliability record for `ai-agent`.
It captures release gates, required evidence artifacts, and the latest validated outcomes.

## Reliability Standard

- **Primary quality gate:** `python tests/run_regression.py`
- **Quick stability gate (change-level):** chunked soak, 1000 iterations
- **Deep stability gate (periodic):** chunked soak, 10000 iterations
- **Automation:** GitHub Actions workflows execute and archive gate results

## Scope of Reliability Evidence

This evidence reflects stability under controlled local execution with deterministic model responses and file-system-backed persistence.

It does not guarantee behavior under:

- arbitrary external inputs
- different hardware environments
- future code changes without passing the same gates

All reliability claims are bounded to the validated conditions described above.

## Required Evidence Artifacts

- **Regression run output:** terminal log from `python tests/run_regression.py`
- **Quick soak artifacts:**
  - `logs/test_runs/ci_soak_1000.json`
  - `logs/test_runs/ci_soak_1000_checkpoint.json`
  - `logs/test_runs/ci_soak_1000_aggregate.json`
- **Deep soak artifacts:**
  - `logs/test_runs/nightly_soak_10000.json`
  - `logs/test_runs/nightly_soak_10000_checkpoint.json`
  - `logs/test_runs/nightly_soak_10000_aggregate.json`
- **Local proof artifact (validated run):**
  - `logs/test_runs/soak_10000_aggregate.json`

## Pass/Fail Acceptance Criteria

### Regression Gate

- Pass condition: all scenarios pass and process exits `0`.
- Current protected baseline size: **`215`** scenarios (confirm with latest `python tests/run_regression.py` output if this drifts).

### Soak Gate (Chunked)

- Pass condition:
  - aggregate `status` is `pass`
  - aggregate `all_ok` is `true`
  - `completed_iterations == iterations`
  - each chunk has `ok: true`
  - no unexpected persistence health events
- Fail condition: any chunk fails, run is interrupted, or artifact status is not `pass`.

## Latest Verified Evidence Snapshot

### Regression

- **Result:** `215 / 215` passing (last Cursor alignment; re-run to refresh)
- **Gate status:** PASS

### Deep Soak (10000, chunked)

- **Artifact:** `logs/test_runs/soak_10000_aggregate.json`
- **Result fields:**
  - `mode: "chunked"`
  - `iterations: 10000`
  - `chunk_size: 1000`
  - `completed_iterations: 10000`
  - `chunks_completed: 10`
  - `all_ok: true`
  - `status: "pass"`
- **Observed behavior:** all chunks passed with `health_event_count: 0`

### Phase 1 System-Test Runner (V0.1)

- **Result:** system-test slice implemented and regression-covered
- **Gate status:** PASS
- **Verification points:**
  - deterministic assertion behavior verified by regression tests
  - runner writes JSON + markdown artifacts
  - runner exits non-zero on failures
  - system-test layer remains isolated from `playground.py` orchestration

## Reproduction Commands

Run from repository root.

### Regression Gate

`python tests/run_regression.py`

### Quick Soak Gate (1000)

`python tests/run_soak.py --iterations 1000 --chunk-size 250 --progress-interval 125 --result-path "logs/test_runs/ci_soak_1000.json" --checkpoint-path "logs/test_runs/ci_soak_1000_checkpoint.json" --aggregate-path "logs/test_runs/ci_soak_1000_aggregate.json"`

### Deep Soak Gate (10000)

`python tests/run_soak.py --iterations 10000 --chunk-size 1000 --progress-interval 250 --result-path "logs/test_runs/nightly_soak_10000.json" --checkpoint-path "logs/test_runs/nightly_soak_10000_checkpoint.json" --aggregate-path "logs/test_runs/nightly_soak_10000_aggregate.json"`

## Automation Coverage

- `.github/workflows/ci.yml`
  - runs regression gate
  - runs quick chunked soak gate
  - uploads quick soak artifacts
- `.github/workflows/nightly-soak.yml`
  - runs deep chunked soak gate (scheduled + manual)
  - uploads deep soak artifacts

## Operational Notes

- Treat regression as release-blocking.
- Treat soak failures as release-blocking until root cause is identified and corrected.
- Prefer artifact-backed decisions over ad-hoc terminal observations.
- Preserve this file as the authoritative reliability audit entry point.
- Enforce constrained execution for test-engineering expansion:
  - Phase 1 (V0.1) acceptance criteria for the HTTP system-eval slice are recorded above as PASS
  - further Phase 2+ work must proceed one small vertical slice at a time; avoid bundling adapter/evaluation/reporting expansion into a single increment
