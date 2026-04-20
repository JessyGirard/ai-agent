# ai-agent — Memory system reference

**Purpose:** One document describing **everything memory-related** in this repository: what exists today, where it lives, how data flows, how it reaches the LLM, and the **execution plans** tied to memory (verbatim archive in §14; **current coordinated two-lane plan** in §15 + `docs/specs/UX_system.md`).  
**Broader repo context:** See `docs/specs/PROJECT_SPECIFICATION.md` for the full file inventory and system overview.  
**Structure:** §§1–13 = **as-built reference** (current code and files). §14 = **prior verbatim memory-only build plan** (archive). §15 + **`docs/specs/UX_system.md`** = **two-lane plan** (Lane 1 durable memory + Lane 2 operator input UX). When ordering or UX scope differs between §14 and `UX_system.md`, follow **`UX_system.md`** until superseded.

---

## 1. Executive summary

The agent uses **file-backed persistence** so memory survives process restarts and new Streamlit sessions:

| Mechanism | Role |
|-----------|------|
| **`memory/extracted_memory.json`** | Primary **structured long-term memory**: labeled facts (`identity`, `goal`, `preference`, `project`), scores, evidence, merge/dedupe by category+value. |
| **`memory/current_state.json`** | **Short-term “where we are”** labels (`focus`, `stage`) merged with defaults in `playground.py`. **Authoritative over memory** in prompts when they conflict. |
| **`memory/project_journal.jsonl`** | **Append-only session/project log** (conversations, state commands, outcome feedback). Used for retrieval blocks and guards—not the same as structured `memory_items`. |
| **`memory/history.json`** | **Legacy** rolling list (last 10 entries) via `memory/memory.py`; parallel to the structured system; not the main path for `playground` / `prompt_builder`. |

**Important:** Retrieval uses **strength gates** (confidence, evidence count, `memory_kind`). Rows that exist on disk may still **not** appear in “Supporting memory” until they are strong enough (see §6). **MEMORY-QUALITY-01** … **MEMORY-QUALITY-04** additionally drop **low-signal** rows at **`load_memory`** time (substring-only; on-disk JSON unchanged via **`load_memory_payload`**).

**Where to log shipped memory work (operator + Cursor contract):**

1. **`docs/specs/memory_log_system.md`** — **Session increments (logged):** each shipped **MEMORY-NN**, retrieval/packaging slice, or Lane 1 **M*** step gets a dated subsection with **one-line outcome**, **primary files**, and **`python tests/run_regression.py` → X / X** when code changed.
2. **`docs/handoffs/SESSION_SYNC_LOG.md`** — Append a **bottom block** for the same session when the repo or plan changes (ChatGPT cold-start anchor); **newest entry wins** on conflicts.
3. **This file (`MEMORY_SYSTEM.md`)** — Update **§§6–7** (and packaging notes below) when **behavior** or on-disk contracts change, not only when adding a log row.

---

## 2. On-disk files (memory-adjacent)

| Path | Written by | Read by | Notes |
|------|------------|---------|--------|
| `memory/extracted_memory.json` | `core/persistence.save_memory_payload`, offline extractor | `playground` → `load_memory_payload`, `app/ui.py` (snippet preview) | Root object: `meta` + `memory_items[]`. |
| `memory/extracted_memory.pre_extract.json` | `memory/extractors/run_extractor.py` (`backup_extracted_before_write`) | Human recovery | **Rotating** copy before each extractor write. |
| `memory/extracted_memory.json.bak` | Manual / optional | — | Not required by code; optional extra backup. |
| `memory/imported.json` | `memory/import_chat.py` | `run_extractor.py` | Intermediate transcript JSON. |
| `memory/raw_chat.txt` | You | `import_chat.py` | Source lines for import pipeline. |
| `memory/current_state.json` | `playground` / persistence `save_state` | `playground.load_state` | Defaults in `playground.DEFAULT_STATE` if missing. |
| `memory/project_journal.jsonl` | `playground` journal append | `journal_service` + `prompt_builder` | Compaction/archiving via `playground` constants. |
| `memory/project_journal_archive.jsonl` | Persistence archive helper | — | Summary lines when journal is flushed/archived. |
| `memory/history.json` | `memory/memory.py` | `memory/memory.py` | Legacy; last 10 only. |

**Constants in `playground.py` (journal, not `extracted_memory` schema):**  
`JOURNAL_MAX_ACTIVE_ENTRIES` (300), `JOURNAL_KEEP_RECENT_ON_MANUAL_FLUSH` (50), `JOURNAL_RETRIEVAL_WINDOW` (200).

---

## 3. Code map

| Module | Responsibility |
|--------|----------------|
| **`services/memory_service.py`** | Default payload shape, tokenization, scoring, **`load_memory`** (**MEMORY-QUALITY-01**–**04** low-signal filters before retrieval/packaging reads), **`retrieve_relevant_memory`**, **`retrieve_personal_context_memory`**, **`retrieve_user_purpose_memory`**, **`retrieve_memory_for_purpose`**, runtime **`write_runtime_memory`**, dedupe keys, transient-identity filters, conflict rules for runtime writes. |
| **`playground.py`** | Paths: `MEMORY_FILE`, `STATE_FILE`, `JOURNAL_FILE`; **`ALLOWED_MEMORY_CATEGORIES`**; thin wrappers delegating to `memory_service` + persistence; **`handle_user_input`** calls **`write_runtime_memory`** then builds messages. |
| **`core/persistence.py`** | **`load_memory_payload`** / **`save_memory_payload`**: JSON load with repair events, **`dedupe_memory_items`** on load, **`_normalize_memory_items_with_unique_ids`** on save, atomic write via temp file. |
| **`services/prompt_builder.py`** | **`build_messages`**: calls retrieval functions, **`format_memory_block`**, appends “Supporting memory”, personal context, user-purpose blocks; **state-over-memory** rules in system prompt text. **RUNTIME-01–06 + REASONING-01/02/03:** after context assembly and **`_latency_cap_system_prompt`**, appends **`RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`** (execution through correctness/invalid framing + missing-information admission + non-completion/explanation-structure constraints; no task-type branching). **`build_post_fetch_messages`** unchanged. |
| **`services/journal_service.py`** | Journal commands, formatting, outcome feedback, recent-answer history (complements memory in prompts). |
| **`memory/import_chat.py`** | CLI: `raw_chat.txt` → `imported.json` (alternating roles; strips `USER:` / `AI:` / `ASSISTANT:`). |
| **`memory/extractors/run_extractor.py`** | CLI: `imported.json` → merged **`extracted_memory.json`** (OpenAI); categories; noise/`?`/length filters; **`EXTRACT_MESSAGE_LIMIT`**. |
| **`memory/memory.py`** | Legacy load/save **`history.json`** capped at 10. |
| **`app/ui.py`** | Local **`load_memory_items(limit=8)`** for sidebar-style display only; main chat uses **`playground.handle_user_input`**. |

---

## 4. Structured memory payload (`extracted_memory.json`)

### 4.1 Root shape

- **`meta`**: includes e.g. `schema_version`, extractor metadata, `memory_count`, optional `last_extract` summary after extractor runs. **`save_memory_payload`** refreshes **`memory_count`**.
- **`memory_items`**: list of objects (invalid entries dropped; list repaired on load).

### 4.2 Typical `memory_items[]` fields (runtime + extractor)

Fields commonly present (exact set may vary by source):

| Field | Meaning |
|-------|---------|
| `memory_id` | String id (e.g. `mem_0001`). **Save path** may assign unique ids if missing/duplicate (`persistence._normalize_memory_items_with_unique_ids`). |
| `category` | One of **`identity`**, **`goal`**, **`preference`**, **`project`** (same set as `playground.ALLOWED_MEMORY_CATEGORIES` and extractor `ALLOWED_CATEGORIES`). |
| `value` | Human-readable fact (normalized on runtime write). |
| `confidence` | Float; runtime map: 1→**0.40**, 2→**0.60**, 3→**0.75**, 4→**0.85**, else **0.90** (`estimate_runtime_confidence`). |
| `importance` | Set by `estimate_runtime_importance` for new runtime rows. |
| `status` | e.g. `active`. |
| `memory_kind` | **`tentative`** (evidence < 2), **`emerging`** (2–3), **`stable`** (≥ 4) via `classify_memory_kind`. |
| `evidence_count` | Integer; incremented on merge/reinforce. |
| `first_seen` / `last_seen` | e.g. message refs or **`runtime`**. |
| `trend` | e.g. **`new`**, **`reinforced`**. |
| `source_refs` | List of provenance strings. |

### 4.3 Dedupe and merge

- **`build_memory_key(category, value)`** → `category::` + canonicalized value (lower case, punctuation collapsed, hyphen/underscore → space).
- **`dedupe_memory_items`**: merges rows with the same key; combines evidence, max confidence/importance, **`memory_kind`** from total evidence, **`trend`** reinforced, unions `source_refs`.

---

## 5. Offline memory pipeline

**Flow:** `memory/raw_chat.txt` → **`python memory/import_chat.py`** → `memory/imported.json` → **`python memory/extractors/run_extractor.py`** (OpenAI) → **`memory/extracted_memory.json`**.

**Extractor (`run_extractor.py`) highlights:**

- **Input / output paths:** `memory/imported.json` → `memory/extracted_memory.json` (under project root).
- **Categories:** `identity`, `goal`, `preference`, `project` only.
- **Backup:** Before write, copies existing output to **`extracted_memory.pre_extract.json`** when possible.
- **Merge vs replace:** Default behavior merges with existing file on matching keys; **`--replace`**-style behavior documented in project spec wipes/rebuilds per extractor design (see extractor CLI/help in repo).
- **Filters:** Noise list, **no `?` in stored values**, **`MAX_MEMORY_VALUE_CHARS`** (420).
- **Env:** **`OPENAI_API_KEY`** (required for extractor client). **`EXTRACT_MESSAGE_LIMIT`**: default **50**, hard cap **500** (`effective_message_limit()`).

**Import (`import_chat.py`):** one non-empty line per turn; alternates user/assistant; strips leading role prefixes from stored content.

---

## 6. Runtime memory: capture (`write_runtime_memory`)

**When:** Early in **`playground.handle_user_input`**, after journal/state commands, **`write_runtime_memory(user_input)`** runs.

**How:** `playground.write_runtime_memory` uses a **chained** extractor: **`memory_service.extract_runtime_memory_candidate`**, then **`_memory01_explicit_project_runtime_candidate`** through **`_memory10_project_priority_runtime_candidate`** (see `playground._extract_runtime_memory_candidate_chained`). Service rules:

- Skips empty input, any input containing **`?`** (questions are not auto-captured).
- Skips **transient identity** (tired/fine/stressed + temporal markers, etc.) — see `is_transient_identity_statement`.
- **Prefix patterns** (normalized):
  - **`I prefer …`** → `preference`
  - **`My goal is …`** → `goal`
  - **`I am working on` / `I'm working on`** → `project`
  - **`I am …` / `I'm …`** (without working on/building) → `identity`
- **`I am building …` / `I'm building …`** → `project` via **MEMORY-02** in **`playground`** (minimum tail length, rejects lines containing **`maybe` / `might` / `want to`**; per-line scan like MEMORY-01).
- **Explicit structure / file pointers** (e.g. **`playground.py …`**, **`this system …`**, **`the journal …`**) → `project` via **MEMORY-03** (prefix-only, minimum tail length after prefix; per-line scan). Lines whose remainder begins **`is responsible for …`** skip **MEMORY-03** so **MEMORY-05** can apply the responsibility-specific tail rule. Remainders beginning **`must …`** skip **MEMORY-03** so **MEMORY-06** can match **`this system must …`** / **`the project must …`** with the correct tail length. After **`this part `**, remainders beginning **`is done …`** or **`is complete …`** skip **MEMORY-03** so **MEMORY-08** can match **`this part is done …`** / **`this part is complete …`**.
- **Explicit flow / workflow / pipeline** (e.g. **`the flow is …`**, **`the pipeline is …`**, **`the memory flow is …`**) → `project` via **MEMORY-04** (prefix-only, minimum tail length after prefix; per-line scan).
- **Explicit responsibility** (e.g. **`playground.py is responsible for …`**, **`this module is responsible for …`**) → `project` via **MEMORY-05** (prefix-only, minimum tail length after prefix; per-line scan).
- **Explicit rules / constraints / must** (e.g. **`the rule is …`**, **`the constraint is …`**, **`this system must …`**) → `project` via **MEMORY-06** (prefix-only, minimum tail length after prefix; per-line scan).
- **Explicit decisions / choices / plans** (e.g. **`the decision is …`**, **`we decided to …`**, **`the plan is to …`**) → `project` via **MEMORY-07** (prefix-only, minimum tail length after prefix; per-line scan).
- **Explicit milestones / progress / completion** (e.g. **`we completed …`**, **`the milestone is …`**, **`this part is done …`**) → `project` via **MEMORY-08** (prefix-only, minimum tail length after prefix; per-line scan).
- **Explicit problems / risks / failure modes** (e.g. **`the problem is …`**, **`the biggest risk is …`**, **`the bug is …`**) → `project` via **MEMORY-09** (prefix-only, minimum tail length after prefix; per-line scan).
- **Explicit objectives / priorities / current focus** (e.g. **`the priority is …`**, **`the objective right now is …`**, **`what matters most is …`**) → `project` via **MEMORY-10** (prefix-only, minimum tail length after prefix; per-line scan). Distinct from service **`My goal is …`** → **`goal`**.
- **Uncertainty:** If `has_uncertainty_signal` (e.g. “maybe”, “I guess”) → **dropped** except **`project`** (`allows_uncertain_runtime_memory`).

**Persistence:** Loads full payload, merges or appends item, **`save_memory_payload`**.

**Conflicts:** `runtime_memory_write_conflicts_existing` reduces contradictory **`identity`** / **`goal`** writes when negation polarity overlaps strongly with existing rows (`negation_signal_present` + token overlap).

---

## 7. Runtime memory: retrieval

All retrieval ultimately reads **`memory_items`** via **`playground.load_memory`** → `memory_service.load_memory(load_memory_payload_fn)`.

**MEMORY-QUALITY-01 … MEMORY-QUALITY-04 (`load_memory` only):** **`_is_low_signal_memory_item`** (accepts a **`value` string** for MQ-01-only checks, or a **full memory dict** for MQ-02–04) returns **true** when `value` (case-insensitive substring match) hits preference-heavy tokens (**`likes`**, **`prefers`**, **`enjoys`**, **`wants`**), vague tokens (**`something`**, **`various`**, **`general`**, **`things`**), or non-actionable filler (**`no concrete`**, **`nothing specific`**, **`unclear what`**, **`not actionable`**). **MEMORY-QUALITY-02–04:** for **`category == "project"`** only, if `value` contains **any** soft in-progress phrase (**`working on`**, **`ongoing`**, **`in progress`**, **`moving forward`**, **`trying to`**, **`improving`**, **`progressing`**), the row is dropped. **MEMORY-QUALITY-04** implements this as a **hard mixed-row rule** when **both** soft and a concrete marker substring appear (**`_CONCRETE_PROJECT_OVERRIDE_WHEN_SOFT_PRESENT`**: e.g. **`completed`**, **`decided to`**, **`risk identified`**, **`next we will`**, etc.)—contaminated lines cannot be “rescued” by the concrete half. **Fully clean** project lines with **only** concrete phrasing (no soft substring) remain. **`load_memory`** returns **`memory_items`** with those rows removed, **preserving order** among survivors. **`load_memory_payload`** / persistence / **`write_runtime_memory`** still see the **full** list.

### 7.1 `retrieve_relevant_memory(user_input)`

- Scores each item with **`score_memory_item`** (overlap with user tokens, category intent from **`detect_memory_intent`**, recency/staleness bonuses, safety-query boosts, etc.).
- **`keep_for_use(mem)`:** returns **false** if **`confidence < 0.5` and `evidence_count <= 1`**. Otherwise requires **`confidence >= 0.6` or `evidence_count >= 2`**.
  - **Practical effect:** Single-evidence runtime rows start at **0.40** confidence → **excluded** until reinforced **or** confidence raised (e.g. second merge → **0.60** at evidence 2).
- Returns up to **3** items with score ≥ **1.10** after filter; else fallback to first passing item; else **[]**.

### 7.2 `retrieve_personal_context_memory(user_input, limit=3)`

- Triggered when **`is_personal_context_question`** matches cues (“who am i”, “what do you know about me”, etc.).
- **`keep_for_personal_context`:** rejects **`memory_kind == tentative`**; same weak single-evidence rule as above for confidence/evidence; allows categories **`identity`**, **`preference`**, **`goal`**, **`project`**.
- Scoring adds bonuses for **`is_durable_user_memory`**; deprioritizes weak **`project`** rows.

### 7.3 `is_durable_user_memory` / `retrieve_user_purpose_memory`

- **`is_durable_user_memory`:** `identity`/`preference`/`goal` only; requires **`memory_kind`** in **`stable`/`emerging`**, **`evidence_count >= 2`**, **`trend == reinforced`**, **`confidence >= 0.6`**.
- **`retrieve_user_purpose_memory`:** filters to goals/identity whose **value** matches purpose-like markers (survive, income, life, etc.); uses **`keep_strong`** (same threshold idea as `keep_for_use`).

### 7.4 `retrieve_memory_for_purpose(user_input, k=6)`

- Used when the user asks **agent purpose** style questions; broadened scoring with a fixed keyword string; dedupes by **`build_memory_key`**.

### 7.5 `format_memory_block`

Renders selected rows as bullet lines: `- (category) value` for the system prompt.

### 7.6 Project-category retrieval boosts (**RETRIEVAL-04–10**)

Implemented in **`services/memory_service.py`** inside **`score_memory_item`** (and helpers it calls). These apply when scoring **`category == "project"`** rows against the user query (especially when **`is_project_query`** is true). They **do not** replace strength gates in §7.1 — they adjust **ranking** among eligible rows.

| Increment | Behavior (summary) |
|-----------|---------------------|
| **RETRIEVAL-04** | Bonus when **`is_project_query`**, **`evidence_count > 1`**, **`trend != "new"`** (favors reinforced project rows). |
| **RETRIEVAL-05** | Small bonus when project **`value`** matches engineering-discipline substrings (**`step by step`**, **`incremental`**, **`test`**, **`stable`**, **`controlled`**). |
| **RETRIEVAL-06** | Adds **`0.05 * confidence`** to **`score`** for **project** rows (after R05), tightening separation without changing non-project math. |
| **RETRIEVAL-07** | Accumulates earlier project-related line bonuses into **`project_bonus`**, then **`project_bonus = min(project_bonus, 0.8)`** before applying (caps stacked boosts). |
| **RETRIEVAL-08** | **`project_bonus += 0.05`** when the user query matches early **project-query** phrasing (e.g. **my/this/the** + **system/project** signals — see code `project_query_signals`). |
| **RETRIEVAL-09** | **`project_bonus += 0.05`** on explicit **risk / priority / problem** phrasing in the user query (`explicit_project_priority_risk_signals`). |
| **RETRIEVAL-10** | **`project_bonus += 0.05`** on explicit **decision / progress** phrasing (`explicit_project_decision_progress_signals`). |

**Register / dates:** `docs/specs/memory_log_system.md` (session rows **RETRIEVAL-04–06**, **RETRIEVAL-07–10 + PACKAGING-01**, **PACKAGING-02**, **PACKAGING-03**, **PACKAGING-04**, **PACKAGING-05**, **PACKAGING-06**, **PACKAGING-07**) and `docs/handoffs/SESSION_SYNC_LOG.md` (same-day blocks + **bottom** anchors).

### 7.7 Read-only project memory packaging (**PACKAGING-01–10**)

**Location:** **`playground.py`** only (no retrieval scoring changes).

| Increment / helper | Role |
|--------------------|------|
| **PACKAGING-01** — **`build_project_memory_snapshot`**, **`show_project_memory_snapshot`** | Compact **active `project`** rows only, deterministic sort, max item cap — **read-only** snapshot text. |
| **PACKAGING-02** — **`_build_project_memory_package_top_priorities`**, used from **`build_project_memory_package`** | Prepends **`Top project priorities:`** plus up to **3** bullets (**`- {value}`**) built from the **first** non-empty **`packaged_rows`** values in **existing package order** (same order as snapshot bullets). If no non-empty values, **no** extra block or blank section — package body matches pre-PACKAGING-02 layout aside from the optional preface. |
| **PACKAGING-03** — **`_build_project_memory_package_current_risks`**, **`_join_project_memory_package_prefaces`** | After priorities (when present), optional **`Current project risks:`** block: up to **2** bullets from the **first** qualifying packaged rows. Prefaces joined with **`\\n\\n`** only between non-empty blocks, then **`\\n\\n`** before the snapshot. |
| **PACKAGING-04** — **`_compile_project_memory_package_risk_patterns`**, **`_value_matches_project_memory_risk_keyword`** | Risk qualification uses **case-insensitive whole-word** regex (**`\\b…\\b`**); **`failure mode`** allows internal whitespace; **`problem`** uses **`(?<!no )\\bproblem\\b`** so idiomatic **“no problem …”** does not qualify. Avoids substring hits such as **`norisk`** or **`bug`** inside **`debugging`**. |
| **PACKAGING-05** — **`_compile_project_memory_package_decision_patterns`**, **`_value_matches_project_memory_decision_keyword`**, **`_build_project_memory_package_current_decisions`** | After risks (when present), optional **`Current project decisions:`** block: up to **2** bullets from the **first** qualifying **`packaged_rows`** in **existing order** (phrases **`going with`**, **`will use`**, **`move to`**; whole words **`decision`**, **`decided`**, **`chose`**, **`chosen`**, **`plan`**, **`planned`**). **No** block when none qualify. |
| **PACKAGING-06** — **`_compile_project_memory_package_progress_patterns`**, **`_value_matches_project_memory_progress_keyword`**, **`_build_project_memory_package_current_progress`** | After decisions (when present), optional **`Current project progress:`** block: up to **2** bullets from the **first** qualifying **`packaged_rows`** in **existing order** (whole words **`completed`**, **`done`**, **`finished`**, **`milestone`**, **`progress`**, **`shipped`**, **`working`**, **`validated`**, **`passing`**). **No** block when none qualify. |
| **PACKAGING-07** — **`_compile_project_memory_package_next_steps_patterns`**, **`_value_matches_project_memory_next_steps_keyword`**, **`_build_project_memory_package_next_steps`** | After progress (when present), optional **`Next project steps:`** block: up to **2** bullets from the **first** qualifying **`packaged_rows`** in **existing order** (phrases **`next step`**, **`next steps`**, **`going to`**, **`need to`**, **`to do`**; whole words **`next`**, **`plan`**, **`planning`**, **`upcoming`**, **`will`**, **`todo`**). **No** block when none qualify. **`_join_project_memory_package_prefaces`** joins up to **five** optional blocks (priorities, risks, decisions, progress, next steps). |
| **`build_project_memory_package`**, **`show_project_memory_package`** | Full vs **`compact`** instruction prefix, row/section/strength metadata lines, optional **PACKAGING-02** through **PACKAGING-07** prefaced blocks, then **unchanged** snapshot body. Later **PACKAGING-08–10** rows may extend metadata / layout (see regression ids **`packaging04`** … **`packaging15`**). |

**Prompt contract:** By design, **`build_messages`** / **`build_post_fetch_messages`** do **not** automatically inject these strings unless a future increment wires an explicit call site (see §8: post-fetch hop also omits structured memory). **Regression** covers behavior via **`tests/run_regression.py`** (`packaging01` … `packaging15` scenarios; **`packaging10_*`** … **`packaging15_*`** cover prefaces, ordering, **PACKAGING-04** risk word boundaries, **PACKAGING-05** decisions, **PACKAGING-06** progress, and **PACKAGING-07** next steps).

---

## 8. How memory reaches the LLM (`prompt_builder.build_messages`)

1. **Primary block:** **`Supporting memory:`** + **`format_memory_block(memories)`** from **`retrieve_relevant_memory`** (unless empty).
2. **Personal context:** If personal-context question → extra block from **`retrieve_personal_context_memory`** with instructions (durable vs weak, no invention, **do not override focus/stage**).
3. **User purpose:** If personal-context **or** purpose query signals **or** money/context-lock/fallback heuristics → **`retrieve_user_purpose_memory`** and optional rules that **prioritize user purpose** in the answer ordering.
4. **Agent purpose:** Merges **`retrieve_memory_for_purpose`** with general memories for wider recall.

**RUNTIME-01 / RUNTIME-02 / RUNTIME-03 / RUNTIME-04 / RUNTIME-05 / RUNTIME-06 + REASONING-01 / REASONING-02 / REASONING-03 (`build_messages` only):** After dynamic blocks and **`_latency_cap_system_prompt`**, **`services/prompt_builder`** appends **`RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`**: **RUNTIME-01** (execute directly), **RUNTIME-02** (no preamble/framing), **RUNTIME-03** (fixed four sections + order), **RUNTIME-04** (semantic rules per section; strict separation; skip if unsure; no inference beyond explicit text), **RUNTIME-05** (in-progress exclusions and ambiguity omission), **RUNTIME-06** (correctness constraints—wrong section / ambiguous / ongoing items are **incorrect**; explicit INVALID examples; binary “one correct output”; strict omission without forcing category), **REASONING-01** (if information is insufficient, state missing information directly; no guessing), **REASONING-02** (non-completion constraints: no invented filler to complete sections; empty headers are correct when valid items are absent; unsupported completion is incorrect), and **REASONING-03** (when explanation is needed, use **Known / Missing / Conclusion** with grounded, concise separation: Known = supported facts only; Missing = absent required inputs only; Conclusion = only validly implied outcomes, narrower when Missing is large). Same constant, same injection point—no **`if`** routing by task type.

**Governance (system prompt text, paraphrased):**

- **Always prioritize state over memory.**
- Memory may be outdated; **focus/stage** are current truth.
- Memory must **not** rename or override focus/stage.
- **`build_post_fetch_messages`** (after **`TOOL:fetch`**) uses **focus/stage** and fetched content only—**no** structured memory block in that second hop.

---

## 9. Persistence health (debug)

`core/persistence.py` records events (e.g. JSON errors, repairs) into an in-memory list consumed by **`playground.drain_persistence_health_signals`**. Set env **`DEBUG_PERSISTENCE_HEALTH`** to `1` / `true` / `yes` / `on` to print **`[persistence-health]`** lines when those events occur.

---

## 10. Testing and quality gates

| Artifact | Role |
|-----------|------|
| **`tests/run_regression.py`** | **Protected baseline**; includes memory write/retrieval, journal, prompt shaping. Run after any memory behavior change. |
| **`test_playground_memory.py`** | Pytest-style unit tests: normalization, keys, transient identity matrix, dedupe behavior. |

**Command:** `python tests/run_regression.py` (see `README.md` / `PROJECT_SPECIFICATION.md` for current scenario count).

**Offline extractor validation:** `tests/fixtures/extractor_validation_cases.json` + regression scenarios (no live OpenAI).

---

## 11. UI vs CLI

- **Streamlit** (`app/ui.py`): chat calls **`playground.handle_user_input`**; **`init_session_state`** ensures **`playground.current_state`** is loaded from disk if empty. **Session chat** is ephemeral; **disk files** are not.
- **`load_memory_items` in `ui.py`:** reads first **N** items from JSON for display only—not the full retrieval/scoring pipeline.

---

## 12. Known structural notes

1. **Two memory mechanisms coexist:** **`memory/memory.py` + `history.json`** vs **`extracted_memory.json` + services**. The **main agent path** is the structured JSON + `memory_service`.
2. **Strength gates:** Imported or single-shot rows at **0.40 / tentative / evidence 1** may **not** surface in **`retrieve_relevant_memory`** or personal-context paths until **reinforced** or edited to stronger values (see §6–7).
3. **`memory_id` duplicates** in historical data can occur; **save** normalizes ids—prefer fixing source data for clarity.
4. **Post-fetch** prompts intentionally omit the structured memory block; rely on fetched text for that turn.

---

## 13. Quick operator checklist

1. **Backup** `memory/extracted_memory.json` before bulk edits or extractor **`--replace`** runs.
2. **Reinforce** canonical facts (same normalized sentence twice) so **`evidence_count`** and **`confidence`** cross retrieval thresholds.
3. **Run** `python tests/run_regression.py` after changing **`memory_service.py`**, **`prompt_builder.py`**, or persistence.
4. **Repo root** as cwd when launching UI or scripts so **`memory/`** paths resolve correctly.

---



## 14. Authoritative memory build execution plan (verbatim)

The following is the agreed memory build plan, reproduced **word for word** without edits.

````
Absolutely. Here's the execution plan I'd use.

This is built from your memory plan plus the repo architecture/handoff you gave me, and it is aimed at one outcome: **the agent reliably remembers who you are, what this project is, and how you work across sessions, without destabilizing the repo**. 

# Memory Build Execution Plan

**Project:** `ai-agent`
**Mission:** durable cross-session operator memory
**Prepared for:** Cursor execution with ChatGPT review
**Prepared by Jessy and ChatGPT**

---

## 1. Objective

Build a **durable, test-protected memory system** so that on a fresh session the agent can reliably recover:

* operator identity
* project identity
* working style / preferences
* current mission context

This must work without breaking the protected regression baseline and without turning `playground.py` into a logic dump. Memory behavior should remain centered in:

* `services/memory_service.py`
* `services/prompt_builder.py`

with `playground.py` staying primarily orchestration/wiring. 

---

## 2. Core decision

We are **not** relying only on general semantic retrieval.

We will build memory in **two layers**:

### Layer A — canonical durable memory rows

A small set of strong memory rows in `memory/extracted_memory.json` that represent the core operator/project truth.

### Layer B — bootstrap retrieval path

A narrow, explicit mechanism that ensures those canonical rows are available on cold start / first-turn prompt assembly, instead of hoping normal ranking will always surface them.

That second layer is the difference between:

* "memory sometimes shows up"
  and
* "the system actually knows who I am when I come back."

This is the architectural move that makes memory a requirement instead of a wish.  

---

## 3. Build philosophy

We follow these rules throughout execution:

* small increments only
* one behavior class per increment
* regression must stay green after each increment
* full-file replacements only
* keep `playground.py` stable unless absolutely necessary
* prefer data-first, then narrow code changes, then optional capture improvements

This matches the repo discipline already established in the handoff. 

---

## 4. Definition of done

This memory build is considered successful when a **fresh session** can consistently answer:

* who the operator is
* what project this is
* how the operator prefers to work
* what the current mission focus is

and can do so for both:

* direct personal questions (`What do you know about me?`)
* generic openers / workflow prompts (`hi`, `what are we doing`, `what should we do next`)

without breaking regression. 

---

## 5. Execution sequence

# Increment 1 — Memory audit and backup

## Goal

Establish the exact current state of memory on disk before changing behavior.

## Files to inspect

* `memory/extracted_memory.json`
* `memory/current_state.json`
* optionally `memory/project_journal.jsonl`

## Tasks

1. Back up:

   * `memory/extracted_memory.json`
   * `memory/current_state.json`
   * optionally `memory/project_journal.jsonl`
2. Audit `memory/extracted_memory.json`:

   * list all `identity`, `project`, `goal`, `preference` rows
   * note `memory_id`, `confidence`, `evidence_count`, `memory_kind`, `trend`
3. Mark rows:

   * **Canonical** = keep as source of truth
   * **Weak** = useful but below retrieval threshold
   * **Conflicting** = duplicates / contradictions / outdated
4. Confirm current `focus` / `stage` in `memory/current_state.json`
5. Run:

   ```bash
   python tests/run_regression.py
   ```

## Deliverable

A short audit note listing:

* canonical rows to preserve
* weak rows to strengthen
* conflicting rows to avoid or clean later

## Exit criteria

* backups created
* regression green
* canonical memory shortlist agreed

This increment is read-only except for backups. 

---

# Increment 2 — Canonical memory pack hardening

## Goal

Turn a tiny core set of memory rows into strong durable rows that already qualify for retrieval.

## Canonical pack

Create or strengthen only 4 rows:

1. `identity`
2. `project`
3. `preference`
4. `goal`

## Tasks

For each canonical row:

* ensure wording is crisp and stable
* ensure one canonical row per concept
* raise row strength to retrieval-eligible status
* ensure unique `memory_id`
* remove duplicate-id risk if present

## Recommended target state

For each canonical row:

* `evidence_count >= 2`
* `confidence >= 0.60`
* `memory_kind = "emerging"` or stronger
* `trend = "reinforced"` where appropriate

## Important caution

Do **not** do a broad cleanup of all memory yet.
Touch only the canonical pack.

## Test after change

Run:

```bash
python tests/run_regression.py
```

Then manually test in a fresh session:

* `What do you know about me?`
* `What project is this?`
* `How do I like to work?`

## Exit criteria

Canonical memory pack exists and is strong enough to survive current filters. 

---

# Increment 3 — Baseline cold-start validation

## Goal

Measure how far the system already gets with strong canonical rows and no retrieval code change.

## Tasks

Open a fresh session and test prompts like:

* `What do you know about me?`
* `What project is this?`
* `What are we building?`
* `What should we do next?`
* `hi`

## Record results in two buckets

### Pass

Memory surfaces correctly.

### Gap

Memory only appears for explicit personal questions and not for generic cold starts.

## Reason for this increment

We want evidence before modifying retrieval.
If strong rows already solve enough, great.
If not, we proceed with the bootstrap mechanism.

## Exit criteria

Decision made: is a bootstrap path required?

My expectation: **yes**.  

---

# Increment 4 — Bootstrap retrieval design

## Goal

Add a narrow, explicit memory bootstrap path for canonical identity/project rows.

## Chosen design

**Pinned canonical memory IDs**

This is the recommended first implementation because it is:

* explicit
* small
* testable
* reversible
* low-risk

## Behavior

On first-turn or low-context prompts, the prompt-building path will merge in a tiny pinned set of memory rows:

* canonical identity
* canonical project
* optionally canonical preference

This should happen in a narrow, controlled way — not as a global override of all retrieval.

## Preferred implementation surface

Primary files:

* `services/memory_service.py`
* `services/prompt_builder.py`

## Guardrails

* do not inject all memory
* do not weaken global filters for everything
* only merge canonical pinned rows in a narrow bootstrap condition

## Suggested bootstrap conditions

Examples:

* first user turn in session
* very short generic opener
* generic session-orientation prompts like:

  * `hi`
  * `what are we doing`
  * `what should we do next`

## Exit criteria

Bootstrap behavior is implemented with minimal surface area.  

---

# Increment 5 — Memory regression coverage

## Goal

Protect the new bootstrap behavior so future changes do not silently break memory continuity.

## Test targets

Add regression coverage for:

* fresh-session `What do you know about me?`
* fresh-session `What project is this?`
* generic opener `hi`
* generic opener `what are we doing`
* workflow opener `what should I do next`

## Assertions

Tests should confirm the assembled prompt / retrieval result includes the canonical memory rows or their effects.

## Where to add

* `tests/run_regression.py`
* optionally supplemental targeted tests if useful

## Important

Regression remains the primary gate, consistent with repo practice.

---

# Increment 6 — Prompt assembly refinement

## Goal

Make sure memory is not only retrieved, but actually used cleanly in the prompt.

## Focus

Review how `services/prompt_builder.py` assembles memory into prompt messages.

## Tasks

* ensure canonical bootstrap memories appear in a stable place
* avoid duplication if already retrieved normally
* keep memory concise and high-signal
* ensure project identity and operator identity do not crowd out the actual user request

## Success condition

The system feels oriented, not bloated.

This is a quality pass, not a major feature pass. 

---

# Increment 7 — Conflict handling review for canonical memory

## Goal

Protect the canonical pack from accidental contradiction over time.

## Why

The repo already has write-path conflict guards for identity/goal and retrieval filters for stale or weak rows. We do not want the new bootstrap path to accidentally surface bad duplicates.

## Tasks

* confirm canonical rows are unique
* confirm duplicates are not competing with pinned rows
* confirm conflict guards do not accidentally block future reinforcement of the canonical pack
* if needed, document a rule:

  * canonical identity/project rows are reinforced, not replaced casually

## Exit criteria

Canonical memory stays stable under ongoing use.

---

# Increment 8 — Optional capture improvements

## Goal

Only after retrieval is working, improve how new durable memories get written.

## Candidate work

Extend runtime extraction patterns for phrases like:

* `My name is ...`
* `Call me ...`
* `I'm working on ...`
* `I prefer ...`

## Important

This is optional until after bootstrap memory works.
Do **not** start here.

## Why

Writing better memories does not help enough if retrieval remains unreliable.
Retrieval comes first. 

---

## 6. Recommended implementation order for Cursor

This is the exact order I would send to Cursor.

### Start with these increments only

1. **Increment 1 — Memory audit and backup**
2. **Increment 2 — Canonical memory pack hardening**
3. **Increment 3 — Baseline cold-start validation**

Then stop and report results.

### Most likely next step after that

4. **Increment 4 — Bootstrap retrieval design**
5. **Increment 5 — Memory regression coverage**

That is the true spine of the memory build.

---

## 7. What I want Cursor to optimize for

You can paste this directly as implementation guidance:

```md
Memory is now a core requirement.

We are building durable cross-session operator memory for ai-agent.

Do not redesign the entire memory system.
Do not broaden global retrieval aggressively.
Do not dump more logic into playground.py unless unavoidable.

Execution priorities:
1. Audit current memory files and create backups.
2. Identify and strengthen a tiny canonical memory pack:
   - identity
   - project
   - preference
   - goal
3. Validate fresh-session behavior with current retrieval.
4. If cold-start memory is still inconsistent, implement a narrow bootstrap mechanism using pinned canonical memory IDs.
5. Protect that behavior with regression coverage.

Implementation constraints:
- full-file replacements only
- one increment at a time
- regression must stay green after every increment
- prefer changes in services/memory_service.py and services/prompt_builder.py
- keep playground.py as orchestration/wiring

Definition of done:
Fresh session reliably recovers operator identity, project identity, work preference, and current mission context on both direct personal questions and generic openers.
```

---

## 8. My recommendation on first execution batch

This is the batch I recommend you execute first with Cursor:

### Batch 1

* Increment 1
* Increment 2
* Increment 3

That gives us:

* a safe baseline
* strong canonical rows
* real evidence about whether retrieval alone is enough

Then you bring me the results.

If cold-start memory is still weak, we immediately move to:

### Batch 2

* Increment 4
* Increment 5

And that is where memory becomes real.

---

## 9. Final call

So the answer is: **yes, we have a plan now**.

And the plan is not vague anymore.

We are not "trying memory."
We are building:

1. a canonical durable memory pack,
2. then a controlled bootstrap path,
3. then regression protection around it. 

Send Cursor **Batch 1** first. Then bring me what it says or what it changes, and I'll help you evaluate the next increment.
````

## 15. Two-lane execution plan (memory + operator input UX)

Operator input UX (large paste, microphone) is **not separate** from memory: it is the same mission — **usable continuity** for a real operator. Implementation stays split: **`app/ui.py`** for UI, **`services/memory_service.py`** and **`services/prompt_builder.py`** for memory, **`playground.py`** primarily orchestration.

The **full revised** two-lane execution plan (Lane 1 M1–M5, Lane 2 U1–U6, batches A–D, and the “What to send Cursor” block) is reproduced **verbatim** in **`docs/specs/UX_system.md`**.

§14 above remains the earlier **memory-only** verbatim plan (numbered increments / Batch 1–2 from Jessy + ChatGPT) for archive reference.

*End of memory system reference.*
