# Three-tool alignment brief (Cursor ↔ ChatGPT ↔ operator)

**Purpose:** We are paused on *what to build next*. This file states the operator’s minimum product intent, maps it to the repo **today**, and lists **decisions** we must agree on before writing more code. Share this whole file (or the paste block at the end) with ChatGPT.

**Constraints (non-negotiable):**

- Small vertical slices only; no bundling “API + prompt/response + regression redesign” in one PR.
- Keep `system_tests` / system eval **isolated** from `playground.py` orchestration unless we explicitly decide otherwise with tests.
- Release gate stays: `python tests/run_regression.py` (plus existing soak/CI policy in `docs/reliability/RELIABILITY_EVIDENCE.md`).

---

## Operator intent: three tools (minimum skeleton)

We want **three capabilities** to exist in a usable, coherent form as soon as is safely possible:

| # | Tool (working name) | Plain-language job |
|---|---------------------|--------------------|
| **1** | **API reliability testing** | Run structured checks against **HTTP/API targets** (timeouts, status, response shape/text), produce **artifacts** (pass/fail, traces, timing), support **repeatable** runs. |
| **2** | **Prompt ↔ response testing** | Run cases that send a **prompt** (or request body) and **assert on the model/API response** (deterministic rules first: contains, regex, JSON fragments, status). Same transport may be HTTP; the *intent* is “conversation-shaped” or LLM-shaped tests, not only generic REST health checks. |
| **3** | **Regression testing** | A **protected suite** that locks behavior so refactors don’t silently break memory, routing, journal, system eval, etc.; **one command**, clear pass/fail, CI-aligned. |

**“Skeleton” means:** each tool has a defined entry point, one clear artifact or output contract, and documentation for how *you* run it—without claiming full Phase 2+ features (judges, multi-target benchmarks, remote hardening, etc.).

---

## What already exists in this repo (ground truth)

Use this table to avoid arguing from memory.

| Tool | What we have now | Where |
|------|------------------|--------|
| **API reliability (HTTP slice)** | Suite JSON + HTTP adapter + runner + JSON/MD artifacts + regression tests | `core/system_eval.py`, `tools/system_eval_runner.py`, `system_tests/suites/example_http_suite.json`, `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md` |
| **Prompt ↔ response** | **Partially the same stack:** cases already use `payload` + assertions on **response body text**. There is **no** separate “prompt/response” schema or runner name yet—**naming and any extra fields are TBD.** | Same as above until we split or extend the suite format |
| **Regression** | **Mature harness** (many scenarios), documented as release gate | `tests/run_regression.py`, `README.md`, CI workflows under `.github/workflows/` |

So: **regression and the HTTP system-eval path are real.** The gap is mostly **clarity and product shape** for “prompt/response” as its own tool (even if it reuses the same engine underneath).

---

## Why we feel stuck

- Phase 1 HTTP eval is **implemented**, but the **roadmap north star** (personal assistant) and the **three-tool framing** are not spelled out in one place—until this file.
- “Prompt/response testing” overlaps API testing; we need an **explicit decision**: same suite format with conventions vs. a second suite type vs. a thin wrapper CLI.
- “As soon as possible” conflicts with “safe”: we need a **ordered backlog** of 2–4 tiny increments ChatGPT and Cursor both accept.

---

## Decisions to agree on (answer in ChatGPT or Cursor replies)

1. **Prompt/response tool:** Is it **(A)** the current HTTP suite with documented conventions for “prompt in payload, assert on body” only, **(B)** a small schema extension (e.g. `prompt` / `expected` aliases), or **(C)** a separate `prompt_response_suite.json` format that compiles to the same executor?
2. **API reliability:** Beyond single-request cases, do we need **v1 skeleton** features: retries, rate-limit hooks, or **only** documented timeouts + fail artifacts (current behavior)?
3. **Regression:** Is the **skeleton** simply “document the three commands” (regression + quick soak + system eval), or do we need a **single meta script** (e.g. `tools/run_all_gates.py`) that orchestrates them with one stem?
4. **Order of implementation:** Confirm stack rank: e.g. *(i)* lock prompt/response semantics in docs + one example suite → *(ii)* optional schema tweak + tests → *(iii)* meta runner if desired—**one item per change set.**

---

## Suggested next safe increments (for discussion—not committed until agreed)

1. **Docs + example only:** Add `system_tests/suites/example_prompt_response_suite.json` (or rename copy of example) with comments in README/runbook: “this is the prompt/response pattern.”
2. **Tiny schema extension (if 1B wins):** Optional fields in `core/system_eval.py` validation only; regression tests; no new adapters.
3. **Optional orchestration:** One small script or documented `Makefile`/PowerShell snippet to run regression + one system eval suite locally (no behavior change).

---

## Related canonical docs

- Roadmap and North Star: `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md`
- Reliability gates: `docs/reliability/RELIABILITY_EVIDENCE.md`
- Collaboration order: `docs/handoffs/CHATGPT_COLLAB_SYNC.md`
- System eval how-to: `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md`

---

## Paste block for ChatGPT (copy from here through end marker)

```text
You are helping align the next development steps for the ai-agent repo.

Context file (read fully if available): docs/handoffs/THREE_TOOLS_ALIGNMENT_BRIEF.md

Goal: We need three minimum “tools” to feel real, without unsafe bundling:
1) API reliability testing (HTTP suite + runner + artifacts — largely exists)
2) Prompt ↔ response testing (overlaps HTTP; we need a clear product shape: same format vs small schema extension vs separate suite type)
3) Regression testing (tests/run_regression.py — exists; may need clearer “operator surface” or a tiny orchestrator)

Hard rules:
- Propose ONE small next increment only (one vertical slice).
- Do not merge adapter work + evaluation + reporting in one step.
- Keep system_tests/system_eval isolated from playground.py unless we explicitly justify coupling.
- Every code proposal must name files to touch and new/updated regression tests.

Deliverables from you:
A) Answer the four numbered decisions in the brief with a clear recommendation each.
B) Pick a single “next PR” scope (max ~1–2 files of logic + tests + docs).
C) List risks and how we validate (commands).

We will compare your answer with Cursor’s recommendation and pick one path.
```

**End paste block.**

---

*Maintainer: update this file when decisions 1–4 are resolved so we don’t re-litigate.*
