# Memory log — increments

**Purpose:** Readable **chronology of memory-related work** in this repo: what shipped, in **git order**, with **commit dates**. This is a **log**, not the full technical spec — see **`docs/specs/MEMORY_SYSTEM.md`** for behavior, files, and schema.

**Logging contract (Lane 1 — memory):** Treat this file as the **running increment register** for memory work. For **each** memory increment you ship (or approve from a session), **append** a new subsection or table row under **“Session increments (logged)”** below (or extend the chronology tables), with at least: **date**, **increment id** (e.g. `M2`, `Mem-12`, or your own label), **one-line outcome**, **primary files**, and **`python tests/run_regression.py` → X / X** when code changed. Keep spec changes in **`MEMORY_SYSTEM.md`**; keep **this file** for *what happened when*. Cursor assistants working on memory should update **`memory_log_system.md`** the same way unless you say “docs elsewhere only.”

**Semi-automatic (IDE):** The repo **`.cursor/hooks.json`** runs **`python scripts/memory_log_reminder.py --cursor-hook-stdin`** on **`afterFileEdit`**. When you save **`services/memory_service.py`**, any **`.py`** under **`memory/`**, **`docs/specs/MEMORY_SYSTEM.md`**, or **`memory/extracted_memory.json`**, the **Hooks** channel prints a reminder to append here (saving **`memory_log_system.md`** itself does not fire the reminder). The script does **not** auto-append prose — the log stays accurate and readable. Same idea as the UX drift nudge for **`docs/specs/UX_log_system.md`**.

**How dates were chosen:** Each line uses the **author date** from `git log` (`%ad`, short ISO). Same-day commits are listed **oldest → newest** within that day.

**Plan vs shipped:** **Lane 1 (M1–M5)** and batches in **`docs/specs/UX_system.md`** are the **forward execution plan** for durable memory (audit → canonical pack → cold-start → bootstrap → regression). They are **not** 1:1 with git rows below unless you backfill a session note. When the plan says “do M3 next,” use **`UX_system.md`**, not this log alone.

**Last assembled:** From **`git log`**, **`CHANGELOG.md`**, and handoffs. **Wall-calendar “what shipped when” on Jessy’s machine:** use **`docs/handoffs/SESSION_SYNC_LOG.md`** — read the **last one to three blocks at the bottom** for current truth (e.g. **OpenAI live LLM migration**, regression **X / Y**). The **newest** **`→ CHATGPT: READ THIS ENTRY FIRST ←`** anchor is **`DOC-SYNC-02`** (**482 / 482** at last recorded run, 2026-04-19); older **`DOC-SYNC-01`** (391 wave) is **history** for counts. **RETRIEVAL-07–10 + PACKAGING-01** … **PACKAGING-07**, **RUNTIME-01** … **RUNTIME-06**, **REASONING-01/02/03**, and **MEMORY-QUALITY-01** … **MEMORY-QUALITY-04** remain valid **behavior** references — **always re-run** `python tests/run_regression.py` after pull. In **Session increments** below, each **`### YYYY-MM-DD — MEMORY-NN`** heading is mainly a **sortable register key** paired with the increment id; if a date reads **after your current “today,”** trust **`MEMORY-NN` order** + **`SESSION_SYNC_LOG` bottom** over the heading date alone.

---

## Session increments (logged)

### 2026-04-19 — REASONING-03 (Known / Missing / Conclusion explanation structure in enforcement block)

**One-line outcome:** Extends **`services/prompt_builder`** enforcement text with **REASONING-03** explanation discipline: when explanation is needed, separate **Known / Missing / Conclusion** with grounding constraints (no guessed Known, no invented Conclusion, no speculation from Missing) and concise non-redundant wording.

**Primary files:** `services/prompt_builder.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`482 / 482`** (`python tests/run_regression.py`, **`reasoning03_prompt_enforces_explanation_structure`**).

**Next in series:** **REASONING-04+** or other lanes per plan.

### 2026-04-19 — REASONING-02 (non-completion constraints in `RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`)

**One-line outcome:** Extends **`services/prompt_builder`** enforcement text with **REASONING-02** to block completion-by-invention: no generic filler or unsupported risks/decisions/next steps; empty headers are explicitly correct when no valid item exists; unsupported completion marked incorrect.

**Primary files:** `services/prompt_builder.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`481 / 481`** (`python tests/run_regression.py`, **`reasoning02_prompt_blocks_completion_by_invention`**) at original ship; see **REASONING-03** for current gate count.

**Next in series:** **REASONING-03+** or other lanes per plan.

### 2026-04-19 — REASONING-01 (missing-information admission in `RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`)

**One-line outcome:** **`services/prompt_builder`** extends the existing **`RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`** with **REASONING-01**: when input is insufficient, say so directly, name missing information, no guessing or feigned certainty; partial answers must separate known vs missing; not chain-of-thought; same append path as **RUNTIME-01–06**.

**Primary files:** `services/prompt_builder.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`480 / 480`** (`python tests/run_regression.py`, **`reasoning01_prompt_enforces_missing_information_admission`**) at original ship; see **REASONING-02** for current gate count.

**Next in series:** **REASONING-02+** or other lanes per plan.

### 2026-04-19 — MEMORY-QUALITY-04 (mixed contaminated project rows on `load_memory`)

**One-line outcome:** **`category == "project"`** rows with **both** a soft in-progress phrase and a concrete marker substring (**`_CONCRETE_PROJECT_OVERRIDE_WHEN_SOFT_PRESENT`**) are **always** low-signal; **any** soft phrase alone remains low-signal; fully clean concrete lines unchanged; substring-only; order preserved; **`load_memory_payload`** unchanged.

**Primary files:** `services/memory_service.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`479 / 479`** (`python tests/run_regression.py`, **`memory_quality04_filters_mixed_contaminated_rows`**) at original ship; see **REASONING-01** for current gate count.

**Next in series:** **MEMORY-QUALITY-05+** or other lanes per plan.

### 2026-04-19 — MEMORY-QUALITY-03 (tighten project soft-state override on `load_memory`)

**One-line outcome:** Soft in-progress project **`value`** phrases are low-signal **unless** a **narrow concrete rescue** substring matches (**`_CONCRETE_PROJECT_OVERRIDE_WHEN_SOFT_PRESENT`**); vague rows mentioning milestone/regression/risk alone no longer bypass the filter; **MEMORY-QUALITY-04** later rejects **mixed** soft+concrete lines in one row; substring-only; order preserved; **`load_memory_payload`** unchanged.

**Primary files:** `services/memory_service.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`478 / 478`** (`python tests/run_regression.py`, **`memory_quality03_blocks_false_high_signal_rows`**) at original ship; see **MEMORY-QUALITY-04** for current gate count.

**Next in series:** Superseded by **MEMORY-QUALITY-04** for mixed-row behavior; see that row.

### 2026-04-19 — MEMORY-QUALITY-02 (vague project-state filter on `load_memory`)

**One-line outcome:** Extends **`_is_low_signal_memory_item`** so **`category == "project"`** rows with soft in-progress **`value`** phrasing are dropped (substring-only; order preserved); superseded by **MEMORY-QUALITY-03** / **MEMORY-QUALITY-04** for follow-on rules—see those rows.

**Primary files:** `services/memory_service.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`477 / 477`** (`python tests/run_regression.py`, **`memory_quality02_filters_vague_project_state_language`**) at original ship; see **MEMORY-QUALITY-04** for current gate count.

**Next in series:** Superseded by **MEMORY-QUALITY-03** / **MEMORY-QUALITY-04** for project soft-state behavior; see those rows.

### 2026-04-19 — MEMORY-QUALITY-01 (low-signal memory filter on `load_memory`)

**One-line outcome:** **`services/memory_service._is_low_signal_memory_item`** + **`load_memory`** drops preference-heavy / vague / simple non-actionable **`value`** rows (substring only; order preserved); **`load_memory_payload`** unchanged; **no** packaging / **`playground.py`** / **`prompt_builder`** edits.

**Primary files:** `services/memory_service.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`476 / 476`** (`python tests/run_regression.py`, **`memory_quality01_filters_low_signal_items`**) at original ship; see **MEMORY-QUALITY-04** for current gate count.

**Next in series:** Superseded by **MEMORY-QUALITY-02** … **MEMORY-QUALITY-04** for the memory-quality filter path; see those rows.

### 2026-04-19 — RUNTIME-06 (correctness / invalid output framing in enforcement block)

**One-line outcome:** Extends **`RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`** with **RUNTIME-06** **Correctness constraints**: mis-placed, ambiguous, or ongoing/in-progress items are **incorrect**; explicit **INVALID** examples; binary one-correct-output rule; strict omission without reinterpretation—same **`build_messages`** append; **no** branching.

**Primary files:** `services/prompt_builder.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`475 / 475`** (`python tests/run_regression.py`, **`runtime06_prompt_enforces_invalidity_constraints`**).

**Next in series:** **RUNTIME-07+** or other lanes per plan.

### 2026-04-19 — RUNTIME-05 (in-progress language exclusion in enforcement block)

**One-line outcome:** Extends **`RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`** with **RUNTIME-05** explicit Progress/Next Steps exclusions for ongoing/in-progress/working phrasing, **strict ambiguity** (ongoing/in-progress items in no section), and **omission** when an item is not clearly one of the four section types; same **`build_messages`** append; **no** branching.

**Primary files:** `services/prompt_builder.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`474 / 474`** (`python tests/run_regression.py`, **`runtime05_prompt_excludes_in_progress_language`**) at original ship; see **RUNTIME-06** for current gate count.

**Next in series:** Superseded by **RUNTIME-06** for enforcement-block evolution; see that row.

### 2026-04-19 — RUNTIME-04 (category integrity in enforcement block)

**One-line outcome:** Extends **`RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`** with **RUNTIME-04** semantic rules per section (what belongs in Progress / Risks / Decisions / Next Steps), **strict separation** (“if unsure, omit”), and reinforced **no-inference** rules; same **`build_messages`** append; **no** branching.

**Primary files:** `services/prompt_builder.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`473 / 473`** (`python tests/run_regression.py`, **`runtime04_prompt_enforces_category_integrity`**) at original ship; see **RUNTIME-06** for current gate count.

**Next in series:** Superseded by **RUNTIME-05** / **RUNTIME-06** for enforcement-block evolution; see those rows.

### 2026-04-19 — RUNTIME-03 (fixed four-section structure in enforcement block)

**One-line outcome:** Extends **`RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`** with **RUNTIME-03**: reply must include exactly **Progress:** → **Risks:** → **Decisions:** → **Next Steps:** in order; **`- item`** bullets only; no extra sections; empty section = header only; same **`build_messages`** append; **no** branching.

**Primary files:** `services/prompt_builder.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`472 / 472`** (`python tests/run_regression.py`, **`runtime03_prompt_enforces_structure`**) at original ship; see **RUNTIME-06** for current gate count.

**Next in series:** Superseded by **RUNTIME-04** for enforcement-block evolution; see that row.

### 2026-04-19 — RUNTIME-02 (strict output shape in enforcement block)

**One-line outcome:** Extends **`RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`** with **RUNTIME-02** output-shape rules (start with answer only; no intro/outro; forbid “Here is…”, “The result is…”, etc.); same append site in **`build_messages`**; **no** branching.

**Primary files:** `services/prompt_builder.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`471 / 471`** (`python tests/run_regression.py`, **`runtime02_prompt_enforces_no_preamble`**) at original ship; see **RUNTIME-06** for current gate count.

**Next in series:** Superseded by **RUNTIME-03** / **RUNTIME-04** for enforcement-block evolution; see those rows.

### 2026-04-19 — RUNTIME-01 (execution enforcement on `build_messages` system prompt)

**One-line outcome:** **`services/prompt_builder.build_messages`** appends a fixed **`RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`** after **`_latency_cap_system_prompt`** (after all dynamic context), with **no** task-type branching; **`build_post_fetch_messages`** unchanged; **no** packaging / retrieval / extraction changes.

**Primary files:** `services/prompt_builder.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`470 / 470`** (`python tests/run_regression.py`, **`runtime01_prompt_includes_execution_enforcement`**) at original ship; see **RUNTIME-06** for current gate count.

**Next in series:** Superseded by **RUNTIME-02** / **RUNTIME-03** / **RUNTIME-04** for enforcement-block evolution; see those rows.

### 2026-04-19 — PACKAGING-07 (next project steps preface)

**One-line outcome:** **`_build_project_memory_package_next_steps`** (max **2** rows; same **packaged row order**; phrase + whole-word regex like **PACKAGING-04**/**05**) + **`_join_project_memory_package_prefaces(..., next_steps)`** so **`build_project_memory_package`** may emit **`Next project steps:`** after progress and before the unchanged snapshot; **no** empty next-steps block.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`469 / 469`** (`python tests/run_regression.py`, **`packaging15_*`**).

**Next in series:** **PACKAGING-08+** or prompt wiring when approved.

### 2026-04-19 — PACKAGING-06 (current project progress preface)

**One-line outcome:** **`_build_project_memory_package_current_progress`** (max **2** rows; same **packaged row order**; whole-word regex like **PACKAGING-04**/**05**) + **`_join_project_memory_package_prefaces(..., current_progress)`** so **`build_project_memory_package`** may emit **Current project progress:** after decisions and before the unchanged snapshot; **no** empty progress block.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`, `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`, `docs/handoffs/CHATGPT_COLLAB_SYNC.md`

**Regression:** **`463 / 463`** (`python tests/run_regression.py`, **`packaging14_*`**).

**Next in series:** Superseded same day by **PACKAGING-07**; see that row for current gate count.

### 2026-04-19 — PACKAGING-04 (precise risk keyword matching)

**One-line outcome:** Replaced naive substring risk detection with **precompiled whole-word** regex patterns (**`\\bkeyword\\b`**, case-insensitive); **`failure mode`** as **`\\bfailure\\s+mode\\b`**; **`problem`** uses **`(?<!no )\\bproblem\\b`** to skip **“no problem …”**; avoids **`norisk`**, **`debugging`**, etc.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`

**Regression:** **`451 / 451`** (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** Superseded same day by **PACKAGING-05**; see that row for current gate count.

### 2026-04-19 — PACKAGING-05 (current project decisions preface)

**One-line outcome:** **`_build_project_memory_package_current_decisions`** (max **2** rows; same **packaged row order** as priorities/risks; whole-word / phrase regex like **PACKAGING-04**) + **`_join_project_memory_package_prefaces(..., current_decisions)`** so **`build_project_memory_package`** may emit **Current project decisions:** after risks and before the unchanged snapshot; **no** empty decisions block.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`

**Regression:** **`457 / 457`** (`python tests/run_regression.py`, **`packaging13_*`**).

**Next in series:** Superseded same day by **PACKAGING-06**; see that row for current gate count.

### 2026-04-19 — PACKAGING-03 (current project risks preface on package)

**One-line outcome:** **`_build_project_memory_package_current_risks`** (max **2** rows; initial substring match **refined** in **PACKAGING-04** to whole-word regex) + **`_join_project_memory_package_prefaces`** so **`build_project_memory_package`** emits **Top project priorities** (if any) then **Current project risks** (if any) then unchanged snapshot; **no** empty risks block.

**Primary files:** `playground.py`, `tests/run_regression.py`, `docs/specs/MEMORY_SYSTEM.md`

**Regression:** **`445 / 445`** at original ship; see **PACKAGING-04** for current gate count.

**Next in series:** **PACKAGING-04+** or prompt wiring when approved.

### 2026-04-19 — MEMORY-DOC-01 (spec + register alignment before next memory lane)

**One-line outcome:** **`MEMORY_SYSTEM.md`** now documents **RETRIEVAL-04–10** and **PACKAGING-01–10** lane (§7.6–7.7) plus a **where to log** contract in §1; **`memory_log_system.md`** gains missing **RETRIEVAL-04–06** row and fixed **SESSION_SYNC_LOG** pointer text. **Follow-on ships:** **PACKAGING-05**–**PACKAGING-07** (preface chain through **Next project steps**), and **`DOC-SYNC-02`** (bootstrap / collab / count anchor) — see newer **Session increments** rows above and **`SESSION_SYNC_LOG.md`** bottom.

**Primary files:** `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/handoffs/SESSION_SYNC_LOG.md`

**Regression:** Docs only — re-run `python tests/run_regression.py` on the machine after pull; expect **≥ 391** scenarios (see **bottom** of **`SESSION_SYNC_LOG.md`** for latest **PASS X / X** after OpenAI migration).

**Next in series:** Next **MEMORY-*** or **Lane 1 M*** increment per **`docs/specs/UX_system.md`** — append a **new** subsection here **and** a **bottom** block in **`SESSION_SYNC_LOG.md`** when code ships.

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

### 2026-04-19 — PACKAGING-02 (top project priorities preface on package)

**One-line outcome:** **`build_project_memory_package`** / **`build_project_memory_package(compact=True)`** prepend **`Top project priorities:`** (up to **3** lines) from the **first** non-empty packaged row **values** in **snapshot bullet order**; **`_build_project_memory_package_top_priorities`** returns **`""`** when nothing qualifies so **no** empty block; snapshot substring **unchanged** after metadata + optional preface.

**Primary files:** `playground.py`, `tests/run_regression.py` (harness ids **`packaging10_*`** and composition checks in **`packaging04`**–**`packaging09`**)

**Regression:** **`438 / 438`** (`python tests/run_regression.py`, **`FETCH_MODE`** unset) — confirmed with docs append; ship commit **`7bdd83e`** on **2026-04-19**.

**Next in series:** **PACKAGING-03**+ per packaging lane plan; still **no** prompt injection until explicitly approved.

### 2026-04-19 — RETRIEVAL-04–06 (`score_memory_item` project retrieval tuning)

**One-line outcome:** **`memory_service`**: **RETRIEVAL-04** reinforced-vs-new project bonus under **`is_project_query`**; **RETRIEVAL-05** substring alignment bump on project **value**; **RETRIEVAL-06** **`0.05 * confidence`** add-on for **project** scores — with **`tests/run_regression.py`** expectation updates so non-project and intent-priority cases stay stable.

**Primary files:** `services/memory_service.py`, `tests/run_regression.py`, `docs/handoffs/SESSION_SYNC_LOG.md`

**Regression:** `374 / 374` (`python tests/run_regression.py`, **`FETCH_MODE`** unset) — as recorded in **`SESSION_SYNC_LOG.md`** for this slice.

**Next in series:** Superseded by **RETRIEVAL-07–10 + PACKAGING-01** (same calendar day, later session).

### 2026-04-19 — MEMORY-01 (runtime explicit project statements)

**One-line outcome:** Narrow second-stage runtime extraction so clearly prefixed lines (e.g. **`the project is …`**, **`this system is meant to …`**) can become **`project`** memory after the existing **`memory_service.extract_runtime_memory_candidate`** pass; **`write_runtime_memory`** accepts optional **`extract_candidate`** for chaining.

**Primary files:** `playground.py`, `services/memory_service.py`, `tests/run_regression.py`

**Regression:** `311 / 311` (`python tests/run_regression.py`, **`FETCH_MODE`** unset).

**Next in series:** Superseded by **MEMORY-02** / **MEMORY-03**; then **MEMORY-04** … **MEMORY-10** — one increment at a time; log each ship here and in **`SESSION_SYNC_LOG.md`**.

### 2026-04-19 — Session bookkeeping (no M increment) — **historical**

**Archive note:** This subsection described a **docs-only** checkpoint early on **2026-04-19** (handoff / bootstrap / UX log alignment) before the **MEMORY-01** chain and later **PACKAGING** increments landed the same calendar day in the repo history. **Do not** use the old **301 / 301** figure here as the current gate.

**Current register:** See **Session increments (logged)** above (**MEMORY-01** … **MEMORY-10**, **RETRIEVAL-***, **PACKAGING-01** … **PACKAGING-07**, etc.) and **`docs/handoffs/SESSION_SYNC_LOG.md`** bottom (**`DOC-SYNC-02`** for latest **X / Y**).

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
