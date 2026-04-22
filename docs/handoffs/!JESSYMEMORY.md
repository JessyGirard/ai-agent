## Deep Technical Assessment — Memory System

This is the **memory-focused technical assessment only**.

## Scope And Method

Assessment basis:

- Implementation: `playground.py`, `services/memory_service.py`, `services/prompt_builder.py`, `core/persistence.py`, `services/journal_service.py`, `memory/extractors/run_extractor.py`, `memory/import_chat.py`, `app/ui.py`
- Memory specs/logs: `docs/specs/MEMORY_SYSTEM.md`, `docs/specs/memory_log_system.md`, `docs/specs/PROJECT_SPECIFICATION.md`
- Runtime data: `memory/extracted_memory.json`, `memory/current_state.json`, `memory/project_journal.jsonl`, `memory/project_journal_archive.jsonl`
- Tests: `tests/run_regression.py`, `test_playground_memory.py`

---

## 1) Memory Architecture (What Exists)

There are **four memory-adjacent stores** with distinct roles:

- `memory/extracted_memory.json`
  Structured long-term memory (`memory_items`) with category, confidence, evidence, kind, trend, provenance.
- `memory/current_state.json`
  Short-term authoritative operational state (`focus`, `stage`), used for current-turn control.
- `memory/project_journal.jsonl`
  Append-only interaction/event log.
- `memory/history.json` via `memory/memory.py`
  Legacy memory list (last 10), not the main active path.

### Critical architectural point

The system intentionally splits:

- semantic memory (`extracted_memory.json`)
- control-state truth (`current_state.json`)
- interaction trace (`project_journal.jsonl`)

So memory informs responses, but state remains authoritative for active routing.

---

## 2) How It Was Built (Implementation Evolution)

From logs and code:

- Started with baseline runtime/offline memory storage/retrieval.
- Extracted memory logic into `services/memory_service.py`, persistence into `core/persistence.py`.
- Added runtime pattern chain (`MEMORY-01` ... `MEMORY-10`) in `playground.py`.
- Added retrieval boosts (`RETRIEVAL-04` ... `RETRIEVAL-10`) in scoring.
- Added project packaging helpers (`PACKAGING-01` ... `PACKAGING-07`) as read-only views.
- Added quality filters (`MEMORY-QUALITY-01` ... `MEMORY-QUALITY-04`) on `load_memory`.
- Added prompt enforcement/routing structure (`RUNTIME-*`, `REASONING-*`) in `prompt_builder`.

Net: from "store rows" to a **gated, scored, filtered, prompt-shaped memory subsystem**.

---

## 3) Why It Was Built This Way (Design Rationale)

Major design decisions:

- **File-backed persistence, no DB**: transparency, portability, restart durability.
- **Category+canonical value dedupe**: normalize concept repeats.
- **Evidence/confidence progression**: trust grows with reinforcement.
- **State over memory**: protects live context against stale memory.
- **Read-time quality filtering**: keep full payload, gate what is used.
- **Prompt-injected memory blocks**: contextual support, not full replay.
- **Regression-centric discipline**: memory changes protected by scenario tests.

---

## 4) Data Contracts And Core Mechanics

### Memory item shape

`memory_items[]` rows typically include:

- `memory_id`, `category`, `value`
- `confidence`, `importance`
- `memory_kind`, `evidence_count`, `trend`
- `first_seen`, `last_seen`, `source_refs`

### Dedupe key and canonicalization

```python
def canonicalize_memory_key_value(value):
    if not isinstance(value, str):
        return ""
    canonical = value.lower()
    canonical = re.sub(r"[-_]+", " ", canonical)
    canonical = re.sub(r"[^\w\s]+", " ", canonical)
    canonical = re.sub(r"\s+", " ", canonical).strip()
    return canonical

def build_memory_key(category, value):
    canonical = canonicalize_memory_key_value(value)
    return f"{category}::{canonical}"
```

### Persistence semantics

- Load repairs malformed payload shape where possible.
- Load dedupes `memory_items`.
- Save normalizes duplicate/missing IDs and updates `meta.memory_count`.
- Save is atomic (temp file + replace) to reduce corruption risk.

---

## 5) Runtime Write Path (How New Memory Is Captured)

`playground.handle_user_input` calls `write_runtime_memory` early.

Candidate extraction is chained:

1. generic extraction in `memory_service.extract_runtime_memory_candidate`
2. fallback explicit stages `_memory01_...` through `_memory10_...`

```python
def _extract_runtime_memory_candidate_chained(user_input):
    c = memory_service.extract_runtime_memory_candidate(user_input)
    if c:
        return c
    c = _memory01_explicit_project_runtime_candidate(user_input)
    if c:
        return c
    ...
    c = _memory09_project_risk_runtime_candidate(user_input)
    if c:
        return c
    return _memory10_project_priority_runtime_candidate(user_input)
```

Write safeguards include:

- skip question-like input (`?`)
- skip transient identity statements
- uncertainty suppression (except allowed `project` path)
- conflict checks for contradictory identity/goal writes
- merge-on-key reinforcement (evidence bump, trend/kind updates)

---

## 6) Runtime Read Path (How Memory Is Trusted)

Read flow:

1. `load_memory_payload` loads full memory payload.
2. `memory_service.load_memory` filters low-signal rows.
3. Retrieval functions score and select memory for prompt blocks.

Low-signal filter logic (substring-based) drops:

- vague/filler rows
- project soft in-progress phrasing
- mixed soft+concrete contaminated project rows

```python
def _is_low_signal_memory_item(value_or_mem) -> bool:
    ...
    if any(s in low for s in _LOW_SIGNAL_PREFERENCE_SUBSTRINGS):
        return True
    ...
    if category == "project":
        has_soft = any(s in low for s in _SOFT_PROJECT_STATE_SUBSTRINGS)
        has_concrete = any(s in low for s in _CONCRETE_PROJECT_OVERRIDE_WHEN_SOFT_PRESENT)
        if has_soft and has_concrete:
            return True
        if has_soft:
            return True
```

`retrieve_relevant_memory` then applies:

- confidence/evidence strength gates
- score thresholding
- lexical grounding (`is_memory_item_grounded`) to current input text

Meaning: rows may exist on disk but still not be eligible for active use.

---

## 7) How Memory Reaches The LLM

In `services/prompt_builder.build_messages`, memory can be appended as:

- `Supporting memory`
- `Stable user context`
- `User core purpose`
- plus journal/outcome/recent-answer blocks

Then runtime/reasoning enforcement block is appended.

```python
memory_block = _latency_trim_block(
    format_memory_block(memories), LATENCY_MEMORY_BLOCK_MAX_CHARS
)
if memory_block:
    system_prompt += "\n\nSupporting memory:\n" + memory_block

if personal_context_block:
    system_prompt += "\n\nStable user context:\n" + personal_context_block
```

Important: post-fetch second-hop prompt (`build_post_fetch_messages`) intentionally does **not** add the same structured memory block.

---

## 8) Offline Memory Pipeline

Pipeline:

- `memory/raw_chat.txt` -> `memory/import_chat.py` -> `memory/imported.json`
- `memory/extractors/run_extractor.py` (OpenAI) -> `memory/extracted_memory.json`

Extractor behavior:

- category whitelist
- noise filters
- no question-mark values
- max value length
- merge-by-key default, `--replace` optional reset mode
- pre-write backup to `memory/extracted_memory.pre_extract.json`

---

## 9) Current State (As-Is Snapshot)

From current `memory/extracted_memory.json`:

- total rows: **114**
- category counts: project 26, goal 36, preference 39, identity 13
- memory kind: tentative 90, emerging 17, stable 7
- trend: new 90, reinforced 24
- rows with confidence >= 0.6: 24
- rows with evidence >= 2: 24
- runtime-sourced rows: 5

After low-signal filter (`load_memory` path):

- kept: **96**
- dropped: **18**

Rows passing baseline retrieval strength gate:

- **23** rows, largely goal/preference heavy, minimal identity, near-zero project presence in eligible set snapshot.

So raw memory volume is moderate, but trusted/usable memory is significantly narrower.

---

## 10) Interactions And Non-Interactions

### Strongly coupled to memory subsystem

- `playground.py` (runtime orchestration)
- `services/memory_service.py` (core memory logic)
- `services/prompt_builder.py` (memory-to-prompt bridge)
- `core/persistence.py` (durability)
- `memory/extractors/run_extractor.py` (offline memory enrichment)
- `tests/run_regression.py` (behavioral guarantees)

### Weak / display-only memory interaction

- `app/ui.py` `load_memory_items(limit=8)` is preview-only, not full retrieval pipeline.

### Largely independent of structured memory

- Tool 1 / `system_eval` execution path is mostly orthogonal to memory.
- Fetch implementation (`tools/fetch_*`) is operationally separate; memory affects prompt context around usage, not fetch mechanics themselves.

---

## 11) Strengths

- Clear separation: state vs memory vs journal.
- Strong incremental hardening with traceable named increments.
- Durable and recoverable persistence strategy.
- Rich runtime capture pattern chain for project-specific statements.
- Mature prompt assembly that can blend multiple context layers.
- High test culture around regressions.

---

## 12) Risks And Technical Debt

- **Over-aggressive substring filtering risk** for some preference rows.
- **High tentative ratio** means most memory remains weak/non-durable.
- **Some noisy runtime captures** still enter the payload.
- **Spec/document drift risk** due to large fast-moving docs.
- **Legacy path (`memory/history.json`)** still present, increasing conceptual overhead.

---

## 13) Practical Positioning ("Where Memory Is Now")

Current memory system is:

- **Architecturally mature** (clear layers, gates, persistence, tests),
- **Operationally selective** (strict trust gates),
- **Data-heavy but signal-constrained** (many rows, fewer trusted rows).

It behaves more like a **controlled memory substrate** than a broad-recall semantic memory engine.

---

## 14) Final Technical Verdict

The memory subsystem is robustly engineered for control and reliability:

1. canonical structured store,
2. runtime capture chain,
3. quality filtering,
4. scored retrieval with trust thresholds,
5. prompt-level integration under state authority,
6. regression-protected evolution.

The main next frontier is **signal quality optimization** (promoting truly useful rows and reducing false negatives/over-filtering), not foundational architecture redesign.

---

## 15) Forensic Memory Audit (Row-Level)

### Snapshot

- Total rows: **114**
- Strong rows (retrieval-ready profile): **24**
- Weak rows (tentative/new/low confidence/evidence): **90**
- Exact canonical duplicates by key: **0**
- Near-duplicate pairs (semantic overlap in same category): **33**
- Noisy runtime identity rows detected: **2**

### What this means

- Your memory is **not suffering from exact-key duplicates** right now.
- It **is** suffering from **semantic duplication drift** (same idea, slightly different wording).
- Most rows are weak, so effective memory quality is constrained by signal strength.
- Some runtime identity captures are too long/noisy and should be cleaned.

### Canonical vs Weak vs Conflicting

#### Canonical (keep as source-of-truth)

Strong rows are mostly in:

- `preference` (**12**)
- `goal` (**11**)
- `identity` (**1**)

These are your best anchor rows and should be preserved/reinforced.

#### Weak (needs hardening or pruning)

- **90 weak rows** (mostly `tentative` + `new`)

These should be triaged into:

1. upgrade by reinforcement,
2. rewrite to canonical wording,
3. archive/drop if low utility.

#### Conflicting/Redundant clusters (high priority)

Not hard contradictions, but repeated variants of the same meaning appear across rows, for example:

- regression harness as safety mechanism/check,
- clear alignment before proceeding,
- step-by-step with validation,
- deep/specific answers over generic answers,
- challenge me if something feels off,
- honestly say no solution when none exists,
- narrow to one best move when unsure,
- new but learning quickly.

These should each become **one canonical row per concept**.

### Exact cleanup actions

1. **Create canonical set first (8-12 rows max)**  
   - 1-2 identity  
   - 3-4 preference  
   - 2-3 goal  
   - 2-3 project
2. **Collapse semantic variants into canonical wording**  
   - Keep strongest member of each cluster  
   - Map weaker variants to the same canonical sentence
3. **Promote canonical rows to durable state**  
   - `evidence_count >= 2`  
   - `confidence >= 0.60`  
   - `memory_kind in {emerging, stable}`  
   - `trend = reinforced`
4. **Prune noisy runtime identity rows**  
   - Remove long transcript/code-like identity entries  
   - Keep identity statements short and stable
5. **Apply ongoing writing discipline**  
   - One concept = one sentence pattern  
   - Avoid stylistic re-phrasing that creates near-duplicates
6. **Validate with regression**  
   - Run `python tests/run_regression.py` after memory edits

### Bottom line

Your memory architecture is strong, but current row quality is fragmented by near-duplicate phrasing and a large weak tail. The fastest practical improvement is **canonical consolidation + reinforcement**, not architecture redesign.

---

## 16) Full Project-Wide Assessment

### 1) System shape

The repository is organized as a **stateful local-agent platform** with three major lanes:

- **Agent runtime lane**: `playground.py` + `services/*` + `core/*`
- **Operator/UI lane**: `app/ui.py` + launch scripts + UX/handoff docs
- **Evaluation/tooling lane**: `core/system_eval.py` + Tool 1 operator/run-log + test harness scripts

This separation is healthy: orchestration, UX, and validation are distinct but coordinated.

### 2) Core runtime interaction map

Primary execution path:

1. Input arrives via CLI or Streamlit.
2. `playground.handle_user_input` orchestrates turn flow.
3. State/journal/memory operations execute early.
4. `prompt_builder.build_messages` assembles system + context blocks.
5. `core/llm.py` sends model request.
6. Optional `TOOL:fetch` path runs and may trigger a post-fetch second pass.
7. Output and metadata are journaled.

This gives deterministic control with bounded dynamic behavior.

### 3) Component responsibilities

- `playground.py`: orchestrator/glue layer.
- `services/memory_service.py`: memory scoring/filtering/write conflict logic.
- `services/journal_service.py`: journal append/compaction/outcome/recent-answer behavior.
- `services/routing_service.py`: intent/subtarget classification and next-step shaping.
- `services/prompt_builder.py`: prompt assembly and output enforcement.
- `core/persistence.py`: durable file IO and repair behavior.
- `core/llm.py`: model bridge and preflight checks.
- `app/ui.py`: operator shell reusing the same `playground` runtime path.

### 4) Strong vs weak interactions

#### Strong interactions

- `playground.py` <-> all `services/*`
- `prompt_builder` <-> memory/journal outputs
- `persistence` <-> state/memory/journal files
- `tests/run_regression.py` <-> behavior-critical modules

#### Weak/one-way interactions

- `app/ui.py` memory preview (`load_memory_items`) is display-only vs scoring pipeline.
- Legacy `memory/memory.py` path does not drive main retrieval behavior.

#### Mostly isolated subsystem

- Tool 1 evaluation engine (`system_eval`) remains largely independent from memory internals.

### 5) Architectural strengths

- Strong modular decomposition for a local-agent codebase.
- Clear state-over-memory rule to avoid stale-memory override.
- Durable, inspectable file-backed persistence model.
- High regression discipline (critical strength).
- UI and CLI share runtime path, reducing behavior divergence.

### 6) Primary cross-project risks

- **Prompt-rule complexity**: enforcement blocks are large and can become harder to maintain.
- **Routing sensitivity**: phrase/gate-based routing can be brittle at edge cases.
- **Doc sync pressure**: large handoff/spec surface can drift.
- **Memory signal debt**: row quality still limits practical recall quality.
- **Legacy overlap**: older memory path can create ambiguity for contributors.

### 7) Maturity read

Overall maturity is **high for an actively evolving local-agent project**:

- foundation: strong
- reliability posture: strong
- operational clarity: medium-high
- complexity risk: medium
- strongest next leverage: simplify behavior layers + harden canonical data quality

### 8) Recommended next moves (non-disruptive)

1. Consolidate canonical memory rows and reduce semantic duplication.
2. Add targeted regression tests for known routing ambiguity patterns.
3. Gradually reduce duplicated/overlapping prompt enforcement language.
4. Maintain one explicit runtime control hierarchy map (state > routing > memory > extras).
5. Keep Tool 1 lane isolated while continuing operator UX hardening.

---

## 17) Execution Roadmap Report (Strict Order)

This roadmap is written for controlled execution with minimal break risk.  
Rule of operation: **one phase at a time, regression after each phase, no parallel feature drift**.

### Phase 0 - Safety baseline lock (Do first)

Objective: freeze a known-safe baseline before changing behavior.

1. Run `python tests/run_regression.py`.
2. Record pass count and date in your working notes.
3. Backup memory files:
   - `memory/extracted_memory.json`
   - `memory/current_state.json`
   - `memory/project_journal.jsonl` (optional but recommended)
4. Confirm current runtime state:
   - `focus` and `stage` in `memory/current_state.json`.

Exit criteria:

- Regression baseline is green.
- Backups exist.
- Current state is confirmed.

---

### Phase 1 - Canonical memory stabilization (Highest leverage)

Objective: convert memory from noisy/fragmented into a stable canonical set.

1. Define canonical rows (target 8-12):
   - identity: 1-2
   - preference: 3-4
   - goal: 2-3
   - project: 2-3
2. For each near-duplicate cluster, pick one canonical sentence.
3. Rewrite or remove variants that duplicate the same meaning.
4. Promote canonical rows to durable thresholds:
   - `evidence_count >= 2`
   - `confidence >= 0.60`
   - `memory_kind` = `emerging` or `stable`
   - `trend` = `reinforced`
5. Remove noisy runtime identity rows that are transcript-like or oversized.

Exit criteria:

- Canonical set is clean and explicit.
- Redundant semantic variants are collapsed.
- Strong-row ratio improves materially.

Validation:

- Run `python tests/run_regression.py`.

---

### Phase 2 - Retrieval quality hardening

Objective: ensure good rows are selected and weak rows stay suppressed.

1. Validate `load_memory` filtered output against expected canonical rows.
2. Test representative prompts for:
   - personal context retrieval
   - purpose retrieval
   - project-context retrieval
3. Verify strength gates are allowing canonical rows and excluding weak tail.
4. Check that lexical grounding is not accidentally dropping important canonical responses.

Exit criteria:

- Canonical rows reliably surface when relevant.
- Weak/noisy rows do not dominate retrieval.
- No regressions in existing behavior.

Validation:

- Run `python tests/run_regression.py`.

---

### Phase 3 - Prompt and routing stabilization

Objective: reduce response drift and improve deterministic behavior.

1. Audit routing ambiguity hotspots in `services/routing_service.py`:
   - overlapping markers
   - generic phrase collisions
2. Audit output-shape pressure in `services/prompt_builder.py`:
   - avoid conflicting enforcement instructions
   - keep hierarchy clear for reasoning mode vs structured mode
3. Add or tighten regression scenarios for known misroutes.
4. Keep changes small and isolated per routing/prompt slice.

Exit criteria:

- Fewer ambiguous route outcomes.
- More consistent output structure under similar prompts.
- Existing green baseline preserved.

Validation:

- Run `python tests/run_regression.py`.

---

### Phase 4 - Documentation synchronization

Objective: align technical truth and operator-facing docs after behavior changes.

1. Update `docs/specs/MEMORY_SYSTEM.md` where behavior changed.
2. Append increment entry in `docs/specs/memory_log_system.md`.
3. Add a bottom sync block in `docs/handoffs/SESSION_SYNC_LOG.md` when appropriate.
4. Keep `docs/handoffs/!JESSY.md` as operator report archive.

Exit criteria:

- Behavior docs and logs match code reality.
- Future sessions can restart with correct context.

---

### Phase 5 - Optional expansion (only after phases 0-4)

Objective: extend capability without destabilizing core memory behavior.

Candidate work:

- refine runtime extraction precision,
- improve canonical row tooling,
- add targeted analytics for memory quality trends.

Constraint:

- do not begin expansion until baseline, canonical quality, and retrieval stability are proven.

---

## Ordered execution checklist

1. Phase 0 - Safety baseline lock
2. Phase 1 - Canonical memory stabilization
3. Phase 2 - Retrieval quality hardening
4. Phase 3 - Prompt and routing stabilization
5. Phase 4 - Documentation synchronization
6. Phase 5 - Optional expansion

---

## Hard rules during execution

- One phase at a time.
- No broad refactor and behavior change in the same step.
- Regression run after each phase.
- If regression fails, fix before continuing.
- Prefer service-layer edits over orchestration bloat.
- Keep memory canonicalization decisions explicit and documented.

---

## 18) Prompt and Routing Deep Diagnostic

This is the fourth report in regular format.

## Purpose

Identify why response behavior can drift, become inconsistent, or choose the wrong output style, then define the safest correction path.

---

## 1) Where Behavior Is Controlled

Primary control points:

- `services/routing_service.py`
  - decides intent/subtarget/action shape
  - controls strict/override style paths
- `services/prompt_builder.py`
  - constructs system prompt and dynamic blocks
  - appends enforcement blocks (`RUNTIME-*`, `REASONING-*`, interaction modes)
- `playground.py`
  - orchestrates pre-routing/write-memory/state command flow
  - can force structured output on specific branches

If behavior drifts, root cause is usually one of:

1. route classification mismatch,
2. enforcement block over-constraint or overlap,
3. orchestration override path bypassing expected prompt logic.

---

## 2) Routing Risk Analysis

### A) Marker overlap and phrase collisions

`routing_service` uses many phrase markers and substring checks.  
Risk: one phrase can trigger multiple intents, where a less-appropriate branch wins.

Common failure mode:

- user asks an analytical question,
- text contains a keyword that maps to a strict template route,
- answer becomes formally structured but semantically wrong.

### B) Negation handling brittleness

Some paths use negation phrase checks (for memory retrieval cues).  
Risk: natural language variation can bypass negation detection and route incorrectly.

### C) Default-fallback branch pressure

When prompt does not strongly match a specialized route, generic fallback applies.  
Risk: this can produce safe but generic output that feels disconnected from the request.

---

## 3) Prompt Builder Risk Analysis

### A) Enforcement layering density

`prompt_builder` appends large, multi-rule enforcement tails.  
Risk: multiple rule families can be active together and compete for output shape.

Observed pattern risk:

- structure demands one format,
- reasoning mode asks for another,
- conversation mode can selectively waive structure,
- result may become inconsistent turn-to-turn for similar prompts.

### B) Context block stacking

Prompt can include memory block, personal context, purpose context, journal context, recent answer context, then enforcement.

Risk:

- relevant signal can be diluted by excessive instruction text,
- output obeys format but misses user intent priority.

### C) Strong formatting pressure vs answer utility

Strict format can improve consistency but can also suppress natural, directly useful answers.

Risk:

- technically compliant response,
- practically unhelpful response.

---

## 4) Orchestration-Level Drift Sources

In `playground.py`, response can be shaped by:

- direct state commands,
- forced structured override logic,
- tool fetch branch and post-fetch branch,
- pre-prompt memory writes and journal logging.

Risk:

- same user intent can hit different orchestration paths depending on minor phrasing,
- leading to seemingly inconsistent behavior.

---

## 5) Highest-Impact Diagnostic Findings

1. **Routing ambiguity is the largest root-cause risk** for wrong response style.
2. **Prompt enforcement density is the largest maintainability risk**.
3. **Strict output correctness does not always equal useful answer correctness**.
4. **Behavior stability depends on marker tuning quality**, not only model quality.
5. **Current architecture is strong**, but complexity now sits in policy/routing wording.

---

## 6) Correction Strategy (Safe Sequence)

### Step 1 - Route map normalization

- Build a single priority map for route families:
  1) explicit commands,
  2) hard diagnostic reasoning routes,
  3) strict structured routes,
  4) conversation/simple clarification,
  5) fallback.
- Ensure each branch has one clear winner rule.

### Step 2 - Marker set cleanup

- Remove overlapping or redundant markers.
- Convert broad markers into narrower phrase sets for high-risk branches.
- Add tests for known collision prompts.

### Step 3 - Enforcement simplification

- Keep one primary structure policy active per route.
- Reduce duplicated instructions across RUNTIME/REASONING blocks.
- Preserve strictness, but reduce contradictory wording.

### Step 4 - Add route-specific regression pack

Add scenarios for:

- near-identical prompts that should route differently,
- negated prompts,
- diagnostic prompts with incomplete info,
- casual prompts that should avoid rigid templates.

### Step 5 - Re-verify with baseline

- Run `python tests/run_regression.py`.
- Compare style consistency across a fixed prompt set before/after.

---

## 7) Recommended New Regression Cases

Minimum additions:

1. ambiguous prompt pair differing by one keyword,
2. negation phrase variants (`not`/`don't`/`without`),
3. reasoning-required prompt with missing inputs,
4. conversation prompt with tool keyword but no tool intent,
5. same intent in short and long form to test route stability.

---

## 8) What Success Looks Like

Success criteria:

- same intent -> same route, reliably,
- no accidental template enforcement on conversational prompts,
- no generic fallback on clearly diagnostic prompts,
- fewer style oscillations across semantically similar inputs,
- regression baseline remains green.

---

## 9) Practical Bottom Line

You do not have a weak architecture problem.  
You have a **policy complexity and routing precision problem**.

The right fix is not large refactor first.  
The right fix is:

1. route priority cleanup,
2. marker de-overlap,
3. enforcement simplification,
4. regression hardening around route behavior.

That sequence gives the highest behavior gain with the lowest break risk.
