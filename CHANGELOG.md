# Changelog

This changelog tracks high-level milestones for the project and links them to commit hashes.
It complements:

- `README.md` for current usage/testing guidance
- `PROJECT_SPECIFICATION.md` for current architecture/file inventory
- `HANDOFF_RECENT_WORK.md` for detailed recent context

## 2026-04-17

- `uncommitted` - Reliability gate automation and soak resilience hardening
  - Added `.github/workflows/ci.yml` for PR/push regression + quick chunked soak.
  - Added `.github/workflows/nightly-soak.yml` for scheduled/manual 10k chunked soak.
  - Enhanced `tests/run_soak.py` with chunked execution and synchronized result/checkpoint/aggregate artifact outputs.
  - Produced 10k chunked soak proof artifact with pass status (`logs/test_runs/soak_10000_aggregate.json`).

- `3374882` - Refactor runtime into dedicated services and refresh docs
  - Extracted core runtime responsibilities into:
    - `core/persistence.py`
    - `services/memory_service.py`
    - `services/journal_service.py`
    - `services/routing_service.py`
    - `services/prompt_builder.py`
  - Reduced `playground.py` to orchestration-centric responsibilities.
  - Preserved behavior under the protected regression gate.

## 2026-04-16

- `2577d92` - Update docs and align runtime behavior hardening
- `fe63feb` - Align README/PROJECT_SPECIFICATION with dependency and memory pipeline details
- `835074a` - Refresh handoff with pipeline merge and safety routing context
- `b436b56` - Memory pipeline merge/import cleanup/safety-aware retrieval updates
- `57b7ffa` - Runtime memory hardening (uncertainty/conflict/scoring) plus tests
- `d852e38` - Memory normalization and transient identity filtering improvements
- `70c9b37` - Agent memory/UI/journal retention controls
- `b859411` - Runtime reliability hardening and regression-safety protections

## 2026-04-15

- `33fb0bf` - Memory retrieval/confidence/response-shaping refinements
- `4f51a91` - Initial AI-agent foundation commit

## Notes

- The protected release gate is `python tests/run_regression.py`.
- Use commit history (`git log`) for line-level chronology.
