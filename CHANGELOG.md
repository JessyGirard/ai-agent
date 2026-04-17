# Changelog

This changelog tracks high-level milestones for the project and links them to commit hashes.
It complements:

- `README.md` for current usage/testing guidance
- `docs/specs/PROJECT_SPECIFICATION.md` for current architecture/file inventory
- `docs/handoffs/HANDOFF_RECENT_WORK.md` for detailed recent context

## 2026-04-17

- `uncommitted` - Reliability gate automation, soak resilience, FETCH browser lane, UI launcher, and doc alignment
  - **CI / soak:** `.github/workflows/ci.yml`, `.github/workflows/nightly-soak.yml`; `tests/run_soak.py` chunked execution, synchronized artifacts, compact retention defaults; 10k chunked soak proof artifact (`logs/test_runs/soak_10000_aggregate.json`).
  - **Fetch (browser):** `tools/fetch_browser.py` — bounded Playwright navigation (`goto` ladder, post-goto waits), landmark + scroll extraction, headline and text-node `evaluate` passes, compact **`diag=`** diagnostics (probe tiers, **`exc=`**, **`st=1`** / fallbacks), optional **`FETCH_BROWSER_TIMEOUT_SECONDS`**; **`tools/fetch_page.py`** remains the facade (`FETCH_MODE=browser` vs HTTP). **`[fetch:tag]`** classification preserved for downstream prompt shaping.
  - **Operator docs:** `docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md` (manual sites + **`diag=`** token glossary).
  - **UI lane:** `Launch-Agent-UI.cmd` — Windows one-click Streamlit using **`.venv-win`**; `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md` — *Windows one-click launch* (pin/relaunch).
  - **Handoff / bootstrap / collab sync / project story / spec / reliability evidence / changelog** refreshed for lane status (FETCH through Incr. 13, UI active) and regression count **215**.
  - **Phase 1 system-test runner:** `core/system_eval.py`, `tools/system_eval_runner.py`, `system_tests/suites/example_http_suite.json`; expanded regression for runner/fail-fast/exit-code paths.
  - **Process docs (initial drop):** `docs/reliability/RELIABILITY_EVIDENCE.md`, `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`.

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
