# AI-Agent Chronological Change Report

This report summarizes what changed over time, why it changed, and how stable the system is right now.

Evidence used:
- Git commit history (`git log`)
- `CHANGELOG.md`
- `docs/handoffs/SESSION_SYNC_LOG.md`
- `docs/handoffs/HANDOFF_RECENT_WORK.md`
- Recent Tool 1 run artifacts under `logs/system_eval/`

## Current verdict

- **Immediate breakage risk:** Not imminent
- **Overall structure health:** Stable with controlled complexity
- **Main risk area:** Prompt/routing rule accumulation (policy collisions), not architecture collapse
- **Increment strategy quality:** Mostly healthy (small, test-gated slices)

## System architecture diagram

```text
Jessy / Operator
    |
    v
Streamlit UI (app/ui.py)
    |
    +--> Tool 1: API / System Eval
    |       |
    |       v
    |   core/system_eval.py
    |       |
    |       +--> HttpTargetAdapter / requests
    |       +--> logs/system_eval/*.json + *.md artifacts
    |       +--> app/tool1_run_log.py -> logs/tool1_runs.jsonl
    |
    +--> Tool 2: Prompt/Response lane
    |
    +--> Tool 3: Regression lane
    |
    v
Runtime orchestrator (playground.py)
    |
    +--> services/routing_service.py
    +--> services/prompt_builder.py
    |       |
    |       v
    |   core/llm.py (OpenAI path)
    |
    +--> services/memory_service.py
    |       |
    |       v
    |   memory/extracted_memory.json
    |
    +--> services/journal_service.py
    |       |
    |       v
    |   memory/project_journal*.jsonl
    |
    +--> tools/fetch_page.py facade
            |
            +--> tools/fetch_http.py
            +--> tools/fetch_browser.py

Regression release gate:
    tests/run_regression.py validates playground + prompt_builder + system_eval + UI
```

## Chronological timeline (what changed and why)

## 2026-04-15 to 2026-04-16
- **What changed:** Foundation and early hardening (memory runtime controls, reliability protections, retrieval shaping, docs alignment).
- **Why:** Stabilize the core loop before scaling features.
- **Signals:** Early commits from initial foundation through memory/reliability hardening.

## 2026-04-17 (architecture phase)
- **What changed:** Runtime refactored from one large control file into dedicated modules:
  - `core/persistence.py`
  - `services/memory_service.py`
  - `services/journal_service.py`
  - `services/routing_service.py`
  - `services/prompt_builder.py`
- **Why:** Reduce monolith risk and isolate responsibilities so changes are safer.
- **Result:** Better maintainability and lower blast radius per change.

## 2026-04-17 (Tool 1 + system-eval growth)
- **What changed:** Tool 1 operator UI and engine capabilities expanded (lanes, repeats, assertions, operator UX, run logging).
- **Why:** Turn system-eval from internal harness into a usable API testing workflow.
- **Result:** Tool 1 became operationally usable with artifacts and summaries.

## 2026-04-17 (FETCH browser lane, increments 1-13)
- **What changed:** Browser fetch backend, bounded navigation/wait strategies, extraction refinements, and `diag=` diagnostics.
- **Why:** Handle hard websites while preserving consistent failure tags for downstream prompt routing.
- **Result:** Better observability on fetch failures; hard targets still intentionally bounded.

## 2026-04-18
- **What changed:** Multi-step scenario engine landed in `core/system_eval.py` (steps, templates, variables, step results, markdown steps section).
- **Why:** Support realistic chained API scenarios and reusable suite authoring.
- **Result:** Tool 1 testing power expanded substantially.

## 2026-04-19
- **What changed:** Retrieval tuning series, packaging snapshot helpers, runtime/reasoning enforcement blocks, memory quality filters, and docs sync anchors.
- **Why:** Improve grounding, reduce speculative outputs, and keep handoffs coherent across sessions.
- **Result:** Better control over output structure and memory contamination, with increased complexity in prompt policy layers.

## 2026-04-19 (provider migration)
- **What changed:** Live LLM path migrated from Anthropic constraints to OpenAI path while preserving call contracts.
- **Why:** Restore uninterrupted assistant operation during provider cap window.
- **Result:** Runtime remained functional with minimal architectural churn.

## 2026-04-22 to 2026-04-25
- **What changed:** Runtime grounding, tool-roadmap locking, API runner awareness and response-quality hardening, and recent system-eval reporting upgrades.
- **Why:** Make Joshua context-aware inside API runner workflows and reduce generic/chatty replies.
- **Result:** More workflow-specific diagnostics and clearer next-test guidance.

## Is the structure in danger of breaking?

Short answer: **No, not currently.**

Why:
- Service split reduced structural fragility.
- Regressions were repeatedly used as a release gate.
- Increments were usually narrow and scoped.
- Operational runbooks/handoffs are unusually detailed.

What to watch:
- Prompt/routing instruction density can produce overlap or rigid behavior if not periodically simplified.
- Documentation count drift can confuse "current truth" unless one anchor is continuously updated.

## Did you add too many increments?

Short answer: **Not inherently.**

Many increments is fine when:
- each increment is small,
- tested,
- and logged with intent.

That pattern is visible in this repo. The quality risk now is **rule accumulation**, not increment count alone.

## System status right now

- **Architecture:** Good
- **Testing discipline:** Strong
- **Operator workflow maturity:** Improving (especially Tool 1/API runner)
- **Primary technical risk:** Prompt/routing complexity drift
- **Overall:** Stable and viable, but due for a consolidation sweep

## Recommended next 3 actions

1. Run the full current regression gate and write one fresh baseline anchor in handoff docs.
2. Perform a prompt/routing consolidation pass to remove redundant or overlapping enforcement rules.
3. Add/maintain a few end-to-end workflow smoke tests (not only prompt-unit assertions) for Tool 1/2 runner continuity.

