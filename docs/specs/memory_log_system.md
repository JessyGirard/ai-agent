# Memory log — increments

**Purpose:** Readable **chronology of memory-related work** in this repo: what shipped, in **git order**, with **commit dates**. This is a **log**, not the full technical spec — see **`docs/specs/MEMORY_SYSTEM.md`** for behavior, files, and schema.

**Logging contract (Lane 1 — memory):** Treat this file as the **running increment register** for memory work. For **each** memory increment you ship (or approve from a session), **append** a new subsection or table row under **“Session increments (logged)”** below (or extend the chronology tables), with at least: **date**, **increment id** (e.g. `M2`, `Mem-12`, or your own label), **one-line outcome**, **primary files**, and **`python tests/run_regression.py` → X / X** when code changed. Keep spec changes in **`MEMORY_SYSTEM.md`**; keep **this file** for *what happened when*. Cursor assistants working on memory should update **`memory_log_system.md`** the same way unless you say “docs elsewhere only.”

**Semi-automatic (IDE):** The repo **`.cursor/hooks.json`** runs **`python scripts/memory_log_reminder.py --cursor-hook-stdin`** on **`afterFileEdit`**. When you save **`services/memory_service.py`**, any **`.py`** under **`memory/`**, **`docs/specs/MEMORY_SYSTEM.md`**, or **`memory/extracted_memory.json`**, the **Hooks** channel prints a reminder to append here (saving **`memory_log_system.md`** itself does not fire the reminder). The script does **not** auto-append prose — the log stays accurate and readable. Same idea as the UX drift nudge for **`docs/specs/UX_log_system.md`**.

**How dates were chosen:** Each line uses the **author date** from `git log` (`%ad`, short ISO). Same-day commits are listed **oldest → newest** within that day.

**Plan vs shipped:** **Lane 1 (M1–M5)** and batches in **`docs/specs/UX_system.md`** are the **forward execution plan** for durable memory (audit → canonical pack → cold-start → bootstrap → regression). They are **not** 1:1 with git rows below unless you backfill a session note. When the plan says “do M3 next,” use **`UX_system.md`**, not this log alone.

**Last assembled:** From **`git log`**, **`CHANGELOG.md`**, and handoffs. **Wall-calendar “what shipped when” on Jessy’s machine:** use **`docs/handoffs/SESSION_SYNC_LOG.md`** — the **bottom** block with **`→ CHATGPT: READ THIS ENTRY FIRST ←`** (**DOC-SYNC-01** as of last sync) is the **latest pointer**; **RETRIEVAL-07–10 + PACKAGING-01** and **MEMORY-01** blocks sit **above** it. In **Session increments** below, each **`### YYYY-MM-DD — MEMORY-NN`** heading is mainly a **sortable register key** paired with the increment id; if a date reads **after your current “today,”** trust **`MEMORY-NN` order** + **`SESSION_SYNC_LOG`** over the heading date alone.

---

## Session increments (logged)

### 2026-05-02 — MEMORY-10 (explicit objectives, priorities, current focus)

**One-line outcome:** Tenth chained stage **`_memory10_project_priority_runtime_candidate`**: fixed lowercase prefixes (**`the priority is `**, **`the objective right now is `**, **`what matters most is `**, etc.), tail **≥8** characters, per-line; **`project`** category only.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`

**Regression:** `357 / 357` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** **MEMORY-01 … MEMORY-10** runtime extraction chain complete; further memory work = new increment ids or Lane 1 **`M*`** steps per **`docs/specs/UX_system.md`**.

### 2026-05-01 — MEMORY-09 (explicit problems, risks, failure modes)

**One-line outcome:** Ninth chained stage **`_memory09_project_risk_runtime_candidate`**: fixed lowercase prefixes (**`the problem is `**, **`the biggest risk is `**, **`the bug is `**, etc.), tail **≥8** characters, per-line; **`project`** category only.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`

**Regression:** `352 / 352` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** Superseded by **MEMORY-10** (2026-05-02); **MEMORY-01 … MEMORY-10** chain complete.

### 2026-04-30 — MEMORY-08 (explicit milestones, progress, completion)

**One-line outcome:** Eighth chained stage **`_memory08_project_progress_runtime_candidate`**: fixed lowercase prefixes (**`we completed `**, **`the milestone is `**, **`this part is done `**, etc.), tail **≥8** characters, per-line; **`project`** category only. **MEMORY-03** skips **`this part `** remainders beginning **`is done `** or **`is complete `** so **`this part is done …`** is not swallowed early.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`

**Regression:** `346 / 346` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** Superseded by **MEMORY-09** (2026-05-01); then **MEMORY-10**

### 2026-04-29 — MEMORY-07 (explicit decisions, choices, plans)

**One-line outcome:** Seventh chained stage **`_memory07_project_decision_runtime_candidate`**: fixed lowercase prefixes (**`the decision is `**, **`we decided to `**, **`the plan is to `**, etc.), tail **≥8** characters, per-line; **`project`** category only.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`

**Regression:** `341 / 341` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** Superseded by **MEMORY-08** (2026-04-30) and **MEMORY-09** (2026-05-01); then **MEMORY-10**

### 2026-04-28 — MEMORY-06 (explicit rules, constraints, requirements, must)

**One-line outcome:** Sixth chained stage **`_memory06_project_rule_runtime_candidate`**: fixed lowercase prefixes (**`the rule is `**, **`the constraint is `**, **`this system must `**, etc.), tail **≥8** characters, per-line; **`project`** category only. **MEMORY-03** skips when remainder after a structure prefix begins **`must `**, so **`this system must …`** is not swallowed by the generic **`this system `** prefix.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`

**Regression:** `336 / 336` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** Superseded by **MEMORY-07** (2026-04-29); then **MEMORY-08** … **MEMORY-10**

### 2026-04-27 — MEMORY-05 (explicit “is responsible for” prefixes)

**One-line outcome:** Fifth chained stage **`_memory05_project_responsibility_runtime_candidate`**: fixed lowercase prefixes (**`playground.py is responsible for `**, **`this module is responsible for `**, etc.), tail **≥8** characters, per-line; **`project`** category only. **MEMORY-03** skips a line when the text after a structure prefix begins **`is responsible for `**, so responsibility lines are not captured early with a weak tail check.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`

**Regression:** `331 / 331` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** Superseded by **MEMORY-06** (2026-04-28) and **MEMORY-07** (2026-04-29); then **MEMORY-08** … **MEMORY-10**

### 2026-04-26 — MEMORY-04 (explicit flow / workflow / pipeline prefixes)

**One-line outcome:** Fourth chained stage **`_memory04_project_flow_runtime_candidate`**: fixed lowercase prefixes (**`the flow is `**, **`the workflow is `**, **`the pipeline is `**, etc.), tail **≥8** characters, per-line; **`project`** category only.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`

**Regression:** `326 / 326` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** Superseded by **MEMORY-05** (2026-04-27); then **MEMORY-06** … **MEMORY-10**

### 2026-04-25 — MEMORY-03 (explicit project-structure prefixes)

**One-line outcome:** Third chained stage **`_memory03_project_structure_runtime_candidate`**: fixed lowercase prefixes (e.g. **`playground.py `**, **`this system `**, **`the journal `**), tail **≥8** characters, per-line; **`project`** category only.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`

**Regression:** `321 / 321` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** Superseded by **MEMORY-04** (2026-04-26); then **MEMORY-05** … **MEMORY-10**

### 2026-04-24 — MEMORY-02 (`I am building` / `I'm building` → project, stricter)

**One-line outcome:** First-person **building** lines are **`project`** only via **`playground._memory02_build_intent_runtime_candidate`** (after service + MEMORY-01 in the chain): **prefix-only**, tail **≥5** characters, skip lines containing **`maybe` / `might` / `want to`**. **`memory_service.extract_runtime_memory_candidate`** no longer duplicates these prefixes so short or hedged tails are not captured there.

**Primary files:** `playground.py`, `services/memory_service.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`

**Regression:** `316 / 316` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** Superseded by **MEMORY-03** (2026-04-25); then **MEMORY-04** … **MEMORY-10**

### 2026-04-19 — RETRIEVAL-07–10 + PACKAGING-01 (retrieval boosts + project snapshot helpers)

**One-line outcome:** **`memory_service`**: cap **`project_bonus`** (**RETRIEVAL-07**); add small **`project_bonus`** phrase boosts for project-query wording and explicit risk/priority and decision/progress signals (**RETRIEVAL-08**–**10**). **`playground`**: **`build_project_memory_snapshot` / `show_project_memory_snapshot`** — read-only compact **active `project`** view; **not** wired into prompts in this increment.

**Primary files:** `services/memory_service.py`, `playground.py`, `tests/run_regression.py`, `docs/handoffs/SESSION_SYNC_LOG.md`

**Regression:** `391 / 391` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** N/A (retrieval/packaging slice); **MEMORY-02** … **MEMORY-10** continued separately per **`SESSION_SYNC_LOG.md`** / **MEMORY-01** roadmap.

### 2026-04-19 — MEMORY-01 (runtime explicit project statements)

**One-line outcome:** Narrow second-stage runtime extraction so clearly prefixed lines (e.g. **`the project is …`**, **`this system is meant to …`**) can become **`project`** memory after the existing **`memory_service.extract_runtime_memory_candidate`** pass; **`write_runtime_memory`** accepts optional **`extract_candidate`** for chaining.

**Primary files:** `playground.py`, `services/memory_service.py`, `tests/run_regression.py`

**Regression:** `311 / 311` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** Superseded by **MEMORY-02** / **MEMORY-03**; then **MEMORY-04** … **MEMORY-10** — one increment at a time; log each ship here and in **`SESSION_SYNC_LOG.md`**.

### 2026-04-19 — Session bookkeeping (no M increment)

No **memory lane** (`M*`) code or spec behavior shipped this session — only handoff / ChatGPT bootstrap / UX log updates so external sessions stay aligned. **`services/memory_service.py`**, **`playground.py`**, **`extracted_memory.json`** paths: unchanged here. Repo regression gate when last run: **`301 / 301`** (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

*(Add dated MEMORY-NN or M* subsections below when Lane 1 memory work ships.)*

---

## Chronology (commits, memory-focused)

### 2026-04-15 — Foundation + first retrieval wave

| # | Commit | One-line summary |
|---|--------|------------------|
| 1 | `4f51a91` | **Initial commit** — AI agent foundation (memory files, playground, persistence shape as first landed). |
| 2 | `33fb0bf` | **Memory retrieval / shaping** — refine retrieval, confidence weighting, and response shaping. |

### 2026-04-16 — Dense memory + pipeline + docs day

| # | Commit | One-line summary |
|---|--------|------------------|
| 3 | `b859411` | **Regression safety** — harden runtime reliability; protect real data during regression-style runs. |
| 4 | `70c9b37` | **Memory + journal + UI wiring** — advance agent memory, UI, journal retention with safe runtime controls. |
| 5 | `d852e38` | **Normalization + filters** — runtime memory normalization; **transient identity** filtering improvements. |
| 6 | `57b7ffa` | **Runtime memory hardening** — uncertainty handling, conflicts, **retrieval scoring**, harness tests. |
| 7 | `b436b56` | **Offline pipeline + retrieval** — memory pipeline **merge/import** cleanup; **safety-aware** playground retrieval. |
| 8 | `835074a` | **Docs** — refresh `HANDOFF_RECENT_WORK` (pipeline merge, safety routing context). |
| 9 | `fe63feb` | **Docs** — README + `PROJECT_SPECIFICATION` aligned with deps and **memory pipeline** description. |
| 10 | `2577d92` | **Docs + behavior** — update docs; align runtime behavior hardening. |

*Handoff narrative for this period (themes, not separate commits):* stronger **canonical memory keys** and dedupe, **uncertainty** rules refined by category (e.g. tentative project allowed), **staleness / recency** retrieval tuning, **identity/goal conflict** guard on runtime writes, **display vs canonical** naming clarity, more scenarios in **`tests/run_regression.py`**. Details: **`docs/handoffs/HANDOFF_RECENT_WORK.md`** (normalization, retrieval, write-path, offline import/extract bullets).

### 2026-04-17 — Service extraction (major structural milestone)

| # | Commit | One-line summary |
|---|--------|------------------|
| 11 | `3374882` | **Refactor into services** — extract **`services/memory_service.py`**, **`core/persistence.py`**, **`services/journal_service.py`**, **`services/routing_service.py`**, **`services/prompt_builder.py`**; **`playground.py`** thins to orchestration; docs refresh. |

*Same day, adjacent to memory (quality gates / other lanes, not memory logic per se):* `a6e872d`, `fa28bca`, `cfb748b`, `28a4d88` — reliability automation, system-test runner docs, fetch/UI ship, log push + soak gate (`CHANGELOG.md`).

### 2026-04-18 — Outside memory lane

| # | Commit | One-line summary |
|---|--------|------------------|
| 12 | `dfa5268` | **`system_eval`** multi-step / templates / variable substitution — **not** a memory increment; listed so the timeline is contiguous. |

---

## Reference map (where memory lives now)

| Area | Primary modules |
|------|-------------------|
| Retrieval, scoring, runtime write, dedupe keys | `services/memory_service.py` |
| Load/save/repair `extracted_memory.json` | `core/persistence.py` |
| Prompt memory blocks, `build_messages` | `services/prompt_builder.py` |
| Orchestration, paths, `write_runtime_memory` call chain | `playground.py` |
| Offline import / extract | `memory/import_chat.py`, `memory/extractors/run_extractor.py` |
| Spec + archive plans | `docs/specs/MEMORY_SYSTEM.md` (§14 archive, §15 two-lane pointer) |

---

## Lane 1 plan (M1–M5) — checklist, not this log’s rows

For **ordered future work** (audit, canonical pack, cold-start validation, optional bootstrap IDs, regression coverage), use **`docs/specs/UX_system.md`** → *Lane 1 — Memory*. When you complete an M-step, **append a new dated row** under a “Session work” subsection here or in **`docs/handoffs/SESSION_SYNC_LOG.md`** so the plan and the log stay aligned.

---

*End of memory log chronology (through commit `dfa5268`). Append new entries as memory increments ship.*
