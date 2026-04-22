# JESSY Operations Log

Project: AI Agent  
Purpose: Track operational implementation actions in plain language.

---

## Latest Implemented Fix (Behavior Stabilization - Narrow Scope)

Date: 2026-04-21

### What was implemented

Implemented only the requested narrow behavior-control work:

1. **Phase 2 + Phase 3 (Greeting routing fix + tests)**
2. **Phase 5 Option A only (minimal gating)**

No memory/extractor/architecture/core-transport refactors were made.

---

## Files changed

- `services/prompt_builder.py`
- `tests/run_regression.py`

---

## Exact logic changes made

### 1) Greeting routing fix
In `services/prompt_builder.py` (`user_input_needs_conversation_mode`):

- Added narrow greeting full-match support for:
  - `hello joshua`
  - `bonjour joshua`
  - `hi joshua`
  - `hey joshua`
- Added task-intent guard so greeting + task prompts do **not** route as pure casual greeting mode.
  - Example preserved: `"Hello Joshua, what should I do next?"` is not treated as pure casual greeting.

### 2) Option A minimal gating
In `services/prompt_builder.py` (`build_messages`):

- Added `task_oriented_input` (narrow classification from existing action/strict/override signals plus explicit task markers).
- Added `simple_question_mode` for short non-task wh-questions.
- Updated final conversation-mode decision to include `simple_question_mode` while preserving `system risk` exclusion.
- Kept structured path for clearly task-oriented prompts.
- Did **not** suppress `RUNTIME_01` globally.
- Did **not** implement Option B or Option C.

---

## Tests added/updated

Added in `tests/run_regression.py`:

- `test_interaction01_routes_greeting_variants_to_conversation_mode`
- `test_interaction01_greeting_with_task_intent_not_pure_conversation_mode`
- `test_optiona_simple_factual_routes_to_direct_answer_mode`
- `test_optiona_simple_explanation_routes_to_direct_answer_mode`
- `test_optiona_task_oriented_prompt_keeps_structured_path`
- `test_optiona_no_mode_collision_for_simple_factual_prompt`

Adjusted assertions in two new simple-question tests to align with final prompt mode behavior.

---

## Test execution results

### Targeted subset (first pass)
Command:

`python -m pytest "tests/run_regression.py" -k "interaction01 or optiona"`

Result:

- 12 passed
- 493 deselected

### Broader related subset
Command:

`python -m pytest "tests/run_regression.py" -k "runtime01 or runtime03 or reasoning06 or interaction01"`

Result:

- 16 passed
- 489 deselected

### Lint check

- No linter errors in changed files.

---

## Outcome summary

- Greeting fix worked for requested greeting examples.
- Option A worked in narrow scope.
- Structured behavior still exists in deterministic `playground.py` branches by design:
  - `force_structured_override`
  - fetch short-circuit deterministic reply

These were intentionally left unchanged per scope constraints.

---

## Operator note

If later real-world checks still show leakage in non-task conversational follow-ups, escalation discussion can consider Option C.  
Current state does **not** require immediate escalation.

---

## Latest Implemented Fix (Acknowledgment Follow-Up Classifier Expansion)

Date: 2026-04-21

### What was implemented

Implemented only the requested narrow follow-up classifier expansion:

- Route short conversational acknowledgment/follow-up phrases into conversation mode.
- Keep task-oriented behavior unchanged.

Scope remained tightly limited to classifier logic and minimal related tests.

---

## Files changed

- `services/prompt_builder.py`
- `tests/run_regression.py`

---

## Exact logic change made

In `services/prompt_builder.py` -> `user_input_needs_conversation_mode(user_input: str)`:

- Added a narrow acknowledgment-only matcher after task-intent exclusions and before final `return False`.
- Matcher uses normalized exact matching (`ul.rstrip(".!?").strip()`) for only:
  - `that's much better`
  - `thats much better`
  - `nice`
  - `yeah that makes sense now`
  - `that makes sense now`

No broad sentiment logic, fuzzy matching, or NLP classifier was added.

---

## Tests added/updated

Added in `tests/run_regression.py`:

- `test_interaction013_routes_acknowledgment_followups_to_conversation_mode`
- `test_interaction013_acknowledgment_with_task_intent_stays_task_oriented`
- `test_interaction013_help_prompt_remains_conversational`

These cover:
- acknowledgment phrases (including punctuation/case variants),
- mixed acknowledgment + task prompt behavior,
- preservation of existing help-oriented conversational behavior.

---

## Test execution results

Command:

`python -m pytest "tests/run_regression.py" -k "interaction01 or interaction011 or interaction012 or interaction013"`

Result:

- 11 passed
- 497 deselected

Lint:

- No linter errors in changed files.

---

## Expected behavior after this fix

1. `"That’s much better"` -> conversational mode  
2. `"Nice"` -> conversational mode  
3. `"Yeah that makes sense now"` -> conversational mode  
4. `"That’s better, what should I do next?"` -> remains task-oriented  
5. `"Can you help me with this?"` -> remains conversational

---

## No extra refactors

Confirmed:
- No memory/extractor changes
- No architecture refactor
- No global runtime-enforcement suppression
- Only targeted classifier expansion + minimal tests

---

## Latest Implemented Fix (Acknowledgment Style Micro-Rule in INTERACTION_01)

Date: 2026-04-21

### What was implemented

Implemented an extremely narrow conversation-style tweak:

- Added acknowledgment reply-style guidance inside `INTERACTION_01` prompt instructions.
- Kept routing logic unchanged.
- Kept all non-conversation modes unchanged.

---

## Files changed

- `services/prompt_builder.py`
- `tests/run_regression.py`

---

## Exact change made

In `services/prompt_builder.py`, in `build_messages(...)`, inside:
- `elif conversation_mode:`
- `answer_and_step_rules` (`CONVERSATION MODE (INTERACTION-01)`)

Added micro-guidance:

1. For short acknowledgment follow-ups (about 1-8 tokens, no task intent), reply with one short acknowledgment sentence only.
2. For those short acknowledgment follow-ups, do not ask a follow-up question and do not redirect to workflow/task planning.
3. For generic help asks (example: `"Can you help me with this?"`), one short clarifying question is allowed.

No routing classifiers were changed in this step.
No runtime enforcement blocks were changed in this step.

---

## Tests updated

Updated existing targeted tests in `tests/run_regression.py`:

- `test_interaction013_routes_acknowledgment_followups_to_conversation_mode`
  - now also asserts acknowledgment micro-rule text exists in prompt.
- `test_interaction013_help_prompt_remains_conversational`
  - now also asserts clarifying-question allowance text exists in prompt.

---

## Test execution results

### Minimal subset
Command:

`python -m pytest "tests/run_regression.py" -k "interaction013"`

Result:

- 3 passed
- 505 deselected

### Broader interaction subset
Command:

`python -m pytest "tests/run_regression.py" -k "interaction01 or interaction011 or interaction012 or interaction013"`

Result:

- 11 passed
- 497 deselected

### Lint check

- No linter errors in changed files.

---

## Expected behavior after this fix

1. `"Nice"` -> short acknowledgment reply, no forced follow-up question.
2. `"That’s much better"` -> short acknowledgment reply, no forced workflow redirect.
3. `"Yeah that makes sense now"` -> short acknowledgment reply.
4. `"That’s better, what should I do next?"` -> unchanged task-oriented behavior.
5. `"Can you help me with this?"` -> unchanged conversational behavior with clarifying question allowed.

---

## No extra refactors

Confirmed:
- No routing logic changes in this step
- No memory/extractor changes
- No architecture refactor
- No runtime enforcement global suppression
- Only INTERACTION_01 style micro-guidance + minimal test assertion updates

---

## Latest Implemented Fix (Acknowledgment Hard Constraint in INTERACTION_01)

Date: 2026-04-21

### What was implemented

Implemented a strict output-control upgrade for acknowledgment-only conversation replies:

- Replaced soft acknowledgment wording with hard MUST/MUST NOT constraints.
- Kept scope extremely tight (prompt instruction text only).
- Did not alter routing or non-conversation modes.

---

## Files changed

- `services/prompt_builder.py`
- `tests/run_regression.py`

---

## Exact change made

In `services/prompt_builder.py`, inside `build_messages(...)` -> `elif conversation_mode:` -> `answer_and_step_rules` (`CONVERSATION MODE (INTERACTION-01)`):

Replaced prior soft acknowledgment guidance with hard constraints:

1. Reply **MUST be exactly one short sentence** for short acknowledgment follow-ups (1-8 tokens, no task intent).
2. Reply **MUST NOT contain a question**.
3. Reply **MUST NOT contain a question mark ("?")**.
4. Reply **MUST NOT include task redirection**.
5. Reply **MUST NOT include phrases** like:
   - `"what would you like"`
   - `"what's next"`
   - `"what should"`
   - `"focus on next"`
6. Reply **MUST end as a statement**.

Retained existing help behavior rule:
- For generic help asks (example: `"Can you help me with this?"`), one short clarifying question is allowed.

---

## Tests updated

Updated `tests/run_regression.py`:

- `test_interaction013_routes_acknowledgment_followups_to_conversation_mode`
  - now asserts prompt contains:
    - `"MUST be exactly one short sentence"`
    - `"MUST NOT contain a question mark"`

No new test suites introduced.

---

## Test execution results

Command:

`python -m pytest "tests/run_regression.py" -k "interaction013"`

Result:

- 3 passed
- 505 deselected

Lint:

- No linter errors in changed files.

---

## Expected behavior after this fix

1. `"Nice"` -> one short statement acknowledgment, no question.  
2. `"That’s much better"` -> one short statement acknowledgment, no redirect question.  
3. `"Yeah that makes sense now"` -> one short statement acknowledgment.  
4. `"That’s better, what should I do next?"` -> unchanged task-oriented behavior.  
5. `"Can you help me with this?"` -> unchanged conversational help behavior (clarifying question allowed).  

---

## No scope expansion

Confirmed:
- No routing changes
- No task-mode changes
- No memory/extractor changes
- No runtime-enforcement block changes
- No deterministic override changes
- Only INTERACTION_01 acknowledgment hard-constraint wording + minimal test assertion update

---

## Latest Implemented Fix (Meta-Format Plain-Prose in INTERACTION_01)

Date: 2026-04-21

### What was implemented

Tightened conversation-mode prompt wording so questions about Joshua’s answer **format**, **style**, or **why a format was used** are instructed to be answered in **normal plain prose**, not structured headers, unless the user explicitly asks for those exact headers.

Explicitly unchanged in this pass (by design):

- `"That’s better, what should I do next?"` — remains task-oriented; no routing or task-mode edits.

---

## Files changed

- `services/prompt_builder.py`
- `tests/run_regression.py`

---

## Exact change made

In `services/prompt_builder.py`, inside `build_messages(...)` → `elif conversation_mode:` → `answer_and_step_rules` (`CONVERSATION MODE (INTERACTION-01)`):

- Added a line stating that questions about answer format, style, or why a format was used **MUST** still be answered in plain prose.
- Replaced the looser “unless the user explicitly asks for that structure” framing for the listed headers with stricter wording: do **not** use those headers **unless the user explicitly requests those exact headers** (same header list as before: Progress/Risks/Decisions/Next Steps, Answer/Current state/Next step, Known/Missing/Conclusion).

No routing, runtime enforcement, or deterministic override code was changed—prompt text only inside conversation mode.

---

## Tests added/updated

Added in `tests/run_regression.py`:

- `test_interaction014_format_style_questions_require_plain_prose_guidance`

This test uses the prompt: `"Why do you give me answers in that format?"` and asserts the system prompt contains the new plain-prose meta-format line, the “exact headers” explicit-request line, and that structured output / reasoning-gate blocks are not present for this path.

---

## Test execution results

Command:

`python -m pytest "tests/run_regression.py" -k "interaction014 or interaction013"`

Result:

- 4 passed
- 505 deselected

Lint:

- No linter errors in changed files.

---

## Expected behavior after this fix

1. `"Why do you give me answers in that format?"` — conversation mode with stronger instructions to answer in plain prose; structured headers less likely unless the user explicitly requests those exact headers.
2. `"That’s better, what should I do next?"` — unchanged task-oriented behavior (no change in this pass).

---

## No scope expansion

Confirmed:

- No routing changes
- No task-mode changes
- No runtime enforcement block changes
- No deterministic override changes
- No broad rewrite of INTERACTION_01—only the meta-format / header-permissiveness lines tightened as specified

---

## Latest Implemented Fix (Plain Answer Override)

Date: 2026-04-21

### What was implemented

Very narrow **plain answer override** so short meta-requests (e.g. answer/talk “normally,” stop using a rigid format) route to **conversation mode** and get explicit **plain-prose / no-analysis-framing** instructions, instead of drifting into reasoning-style (Known/Missing/Conclusion) or other structured reply shapes.

Task-bearing lines (same direct-action and task-intent gates as existing conversation routing) are **not** treated as plain override.

---

## Files changed

- `services/prompt_builder.py`
- `tests/run_regression.py`

---

## Exact changes made

1. **New helper:** `user_input_needs_plain_answer_override(user_input)` in `services/prompt_builder.py`  
   After the same **direct-action** and **task-intent** exclusions used for conversation routing, returns true only if the normalized input contains one of:
   - `answer normally`
   - `answer that normally`
   - `talk normally`
   - `stop using that format`

2. **`user_input_needs_conversation_mode(...)`**  
   Normalizes once, applies direct-action + task-intent gates, then if plain override matches **returns true before** the `user_input_needs_reasoning_structure_mode` early exit—so these phrases are not blocked from conversation mode by the reasoning gate.

3. **`build_messages(...)`**  
   - Sets `plain_answer_override_mode = user_input_needs_plain_answer_override(user_input)`.  
   - Extends `reasoning_structure_mode` with `and not plain_answer_override_mode` (same pattern as clarification override vs reasoning).  
   - When `conversation_mode` and `plain_answer_override_mode`, appends **PLAIN ANSWER OVERRIDE (narrow)** under INTERACTION-01: MUST plain prose; MUST NOT use Known/Missing/Conclusion, Answer/Current state/Next step, other listed headers; MUST NOT analysis/Known–Missing-style framing; keep reply simple and direct.

No changes to task-mode branches, runtime enforcement block definitions, or deterministic overrides.

---

## Tests added

- `test_interaction015_plain_answer_override_routes_to_conversation_mode` in `tests/run_regression.py`  
  Uses `"Can you answer that normally?"` and asserts conversation mode, plain-override prompt lines, and absence of reasoning-output / output-format-rule / Known-section template snippets for that built prompt path.

---

## Test execution results

Command:

`python -m pytest "tests/run_regression.py" -k "interaction015 or interaction014 or interaction013"`

Result:

- 5 passed
- 505 deselected

Lint:

- No linter errors in changed files.

---

## Expected behavior after this fix

1. `"Can you answer that normally?"` → conversation mode + plain-override block; steer toward short normal prose, not Known/Missing/Conclusion scaffolding.  
2. Same for other listed phrases when not combined with task/direct-action cues.  
3. `"That’s better, what should I do next?"` (and similar task-intent) → still excluded from plain override / pure casual path by existing task markers.

---

## No scope expansion

Confirmed:

- No routing overhaul—only this narrow detector, conversation-mode ordering fix, reasoning gate when override matches, and INTERACTION-01 append for that case
- No new systems beyond the small helper + prompt slice + one test

---

## Latest Implemented Fix (Plain-answer specificity micro-refinement)

Date: 2026-04-21

### What was implemented

Final polish for **plain-answer override only** (generic / repetitive replies like “What would you like to know?” as the whole message).

Two additional **principle-only** bullets were added inside **`PLAIN ANSWER OVERRIDE (narrow)`** in `build_messages(...)` → `elif conversation_mode:` (no changes outside that block).

**Exact new prompt lines (verbatim intent):**

1. Briefly mirror what they asked for (plain, normal, direct, natural tone, or dropping that format) in your own words—reflect their intent, not a fixed script or role-play quote.

2. Do not let the entire reply be only a generic open-ended question (for example replying solely with `"What would you like to know?"` or the same idea in different words); answer their meta-request in plain prose first.

No phrase→reply scripts, no routing changes, no changes to help prompts or task mode.

---

### Files changed

- `services/prompt_builder.py` — only `_interaction01_plain_override` string extended.
- `tests/run_regression.py` — `test_interaction015_plain_answer_override_routes_to_conversation_mode` extended.

---

### Tests updated

`test_interaction015_plain_answer_override_routes_to_conversation_mode` now also asserts the built system prompt for `"Can you answer that normally?"` contains:

- `Briefly mirror what they asked for`
- `Do not let the entire reply be only a generic open-ended question`
- `What would you like to know?` (as the named negative example inside override guidance)

Existing assertions in that test (conversation mode, plain override block, no reasoning/output-format/Known-template path) unchanged in purpose.

---

### Test execution results

Command:

`python -m pytest "tests/run_regression.py" -k "interaction015"`

Result:

- **1 passed**
- **509 deselected**

Lint:

- No linter errors in changed files.

---

### Expected behavior after this fix

- Plain-answer override inputs (e.g. “Can you answer that normally?”, “Answer that normally.”, “Talk normally.”, “Stop using that format.” when not mixed with task/direct-action cues) get stronger steering toward a **short, intent-aligned** reply and away from **question-only** generic fallbacks.
- Routing, formatting integrity, and non-override conversation behavior stay as before this micro-step.

---

### Scope confirmation (no expansion)

- **Only** the `PLAIN ANSWER OVERRIDE (narrow)` appendix text was extended (two bullets).
- No routing, task mode, help rules, runtime enforcement definitions, deterministic overrides, fixed response mappings, or new systems.

---

## Latest Implemented Fix (Brain toggle — model layer only)

Date: 2026-04-21

### What was implemented

Env-driven **baseline vs brain** OpenAI usage for Joshua’s **`ask_ai` / `chat`** path. **No** `prompt_builder.py` changes, **no** behavior-layer or routing taxonomy changes, **no** extractor changes.

### Env contract (user `.env`)

- `USE_BRAIN=true` (or `1`, `yes`, `on` — case-insensitive) → use **`OPENAI_API_KEY_BRAIN`** + **`OPENAI_BRAIN_MODEL`** (both required when brain is on).
- Otherwise → unchanged baseline: **`OPENAI_API_KEY`** + **`OPENAI_MODEL`** (via existing `get_openai_model_name()` default).

### Files changed

- `core/llm.py` — added **`_active_openai_key_and_model()`** as the **single** decision point; **`ask_ai`** uses returned `(api_key, model)` for client + API `model=`; **`llm_preflight_check`** validates via the same resolver; **`_build_client(api_key)`** takes the resolved key.
- `config/settings.py` — added **`get_use_brain()`**, **`get_openai_api_key_brain()`**, **`get_openai_brain_model_name()`** (read env only; same pattern as other OpenAI getters).

### Rollback

Set **`USE_BRAIN=false`** (or unset / empty), restart the process so `.env` reloads → baseline key + default model again.

### Test / validation run

- `python -m pytest tests/run_regression.py::test_missing_llm_configuration_handling -q` → **1 passed**
- Manual import + `_active_openai_key_and_model()` with `USE_BRAIN=true` in `.env` confirmed brain key + model resolve.

### Lint

- No linter issues reported on the touched Python files for this increment.

### Scope confirmation

- Model layer only; **`max_tokens`** still from **`get_openai_max_tokens()`** for both modes unless a future increment adds a brain-specific cap.

---

## Latest Implemented Fix (Conversation vs structure — default natural)

Date: 2026-04-21

### What changed

- **`user_input_needs_conversation_mode`:** Removed early “reasoning ⇒ not conversation” cut-off **before** greetings/help/acks; reasoning is evaluated **last** so salutations and other conversation signals win. Dropped **`explain `** from this function’s task-intent guard so ordinary “Explain …” asks can route conversational. Added a narrow **bare salutation** list (`hello`, `hi`, `hey`, `bonjour`, `good morning/afternoon/evening`).
- **`build_messages`:** Introduced **`conversation_signals`** (same predicate as the first conversation pass). **`reasoning_structure_mode`** is now **`reasoning_mode_candidate` ∧ … ∧ ¬conversation_signals** so Known/Missing/Conclusion does **not** apply when the message already qualifies for conversation mode.
- **Prompt text:** One **DEFAULT** line in **INTERACTION-01** base (ambiguous ⇒ unstructured chat) and one in **DIRECT ANSWER MODE** (ambiguous ⇒ natural prose, no K/M/C or Answer/Current state/Next step scaffolding).

### Files changed

- `services/prompt_builder.py` only.

### Why minimal / safe

- No new classifiers or model-layer edits; one gate ties existing conversation detection to suppress reasoning **only** when conversation already matched.
- Task / strict / structured paths unchanged; **`pytest -k "reasoning06 or interaction01 or interaction013 or interaction014 or interaction015 or optiona"`** → **23 passed**; **`reasoning05 or reasoning061 or reasoning062`** → **3 passed**.

### Revert

- Restore prior `user_input_needs_conversation_mode` order (reasoning `return False` immediately after plain-answer / before greetings), remove **`conversation_signals`** / **`not conversation_signals`** from **`reasoning_structure_mode`**, remove salutation list and **`explain `** restore in task-intent tuple, strip the two new DEFAULT prompt lines.

### Success criteria (from increment)

- **“Hello”** (and bare salutations above) → natural / conversation path, not Known/Missing/Conclusion.
- **“Explain X”**-style asks → conversational where appropriate (no **`explain `** in conversation task-intent guard).
- **“What should I do next?”** (bare generic ask) → superseded by **light task mode** (see next operations entry); comma‑joined or technical follow‑ups still use full structured **OPEN CONVERSATION** path.

### Commands run (verification)

```text
python -m pytest tests/run_regression.py -k "reasoning06 or interaction01 or interaction013 or interaction014 or interaction015 or optiona" -q
python -m pytest tests/run_regression.py -k "reasoning05 or reasoning061 or reasoning062" -q
```

---

## Latest Implemented Fix (Light task mode — reduce over-structure)

Date: 2026-04-21

### What changed

- Added **`user_input_needs_light_task_mode(...)`** in `services/prompt_builder.py`: short, generic next-step / guidance lines (fixed phrase list), **no comma** in the raw message (avoids “…, what should I do next?” blends), **no `joshua`**, no **heavy** technical substrings (`implement `, `debug`, `.py`, `traceback`, etc.), length cap, not `test`/`fix`/`review` action-type lane, not `force_structured_override`, not URL-style research task.
- New **`LIGHT TASK MODE`** `answer_and_step_rules` block: natural prose / tight bullets; **forbidden** Answer/Current state/Next step and other system header blocks; no pasted focus/stage/action metadata block.
- **Branch order:** **`elif light_task_mode`** is evaluated **before** **`elif strict_reply or force_structured_override`**, so generic “what should I do next?” is no longer captured only by strict structured templates.
- **`build_runtime_01_execution_enforcement_block`:** passes **`conversation_mode or light_task_mode`** so runtime tail uses the **conversation-style waiver** (no default structural RUNTIME-03 tail) for light task.

### Files changed

- `services/prompt_builder.py`
- `tests/run_regression.py` — updated **`test_optiona_task_oriented_prompt_keeps_structured_path`** for light output; added **`test_light_task_mode_false_when_comma_joined_task`**, **`test_heavy_next_step_stays_open_conversation_structure`**.

### Why it is safe

- **Narrow** classification; **complex** next-step asks (comma joins, `implement`, `.py`, etc.) still hit **OPEN CONVERSATION MODE** with **OUTPUT FORMAT RULES**.
- **Conversation mode** unchanged (separate `elif` still first).

### Commands run (verification)

```text
python -m pytest tests/run_regression.py -k "optiona or light_task or interaction01 or interaction013 or reasoning06" -q
```

Result: **24 passed** (includes updated **`test_optiona_task_oriented_prompt_keeps_structured_path`**, new light/heavy tests, and related interaction/reasoning checks).

Additional spot checks:

- `tests/run_regression.py::test_heavy_next_step_stays_open_conversation_structure`
- `tests/run_regression.py::test_interaction01_preserves_action_path`

### Test note (same increment)

- **`test_build_messages_next_step_alignment_preserves_prior_sections`**: dropped the hard requirement that **`OUTPUT FORMAT RULES:`** appear in the prompt for **“What matters to me in life?”**, because that input can route via **conversation / wh-question** mode while still containing all **user-purpose** alignment subsections; **relative ordering assertions** for those subsections are unchanged.

### How to revert

- Remove **`user_input_needs_light_task_mode`**, **`light_task_mode`** variable, the **`elif light_task_mode`** branch, restore **`build_runtime_01...`** to **`conversation_mode=`** only, restore branch order (strict before any light slot), restore **`test_optiona_task_oriented_prompt_keeps_structured_path`** assertions to expect **OUTPUT FORMAT RULES** / three-section template, delete the two new tests, restore the **`OUTPUT FORMAT RULES:`** assertion in **`test_build_messages_next_step_alignment_preserves_prior_sections`** if you want the old strict coupling.

---

## Latest Implemented Fix (Light task — relax comma veto)

Date: 2026-04-21

### What changed

- Removed the blanket **`if "," in user_input: return False`** from **`user_input_needs_light_task_mode`** so short acknowledgments + comma + generic next-step (e.g. “That’s better, what should I do next?”) can still classify as **LIGHT** when **no heavy hints** and other light guards pass.
- **`task_oriented_input`** markers and **`user_input_needs_conversation_mode`** task-intent list: added **`what should i try`**, **`what do i do next`**, **`what's the next step`**, **`what is the next step`** so those lines stay **task-oriented** (and align with existing **light_phrases**).

### Files changed

- `services/prompt_builder.py`
- `tests/run_regression.py`

### Tests

- **Renamed / replaced:** **`test_light_task_mode_false_when_comma_joined_task`** → **`test_light_task_mode_accepts_short_prefix_with_comma_before_next_step`** (expects **LIGHT TASK MODE**, no **OUTPUT FORMAT RULES**).
- **Added:** **`test_light_task_mode_okay_whats_next_step_with_prefix`**, **`test_light_task_mode_alright_what_should_i_try_with_prefix`**, **`test_light_task_comma_still_heavy_when_implement_follows`** (expects **HEAVY** when **`implement`** present).
- **Updated:** **`test_interaction013_acknowledgment_with_task_intent_stays_task_oriented`** to expect light task for the mixed ack + next-step string.

### Commands run

`python -m pytest tests/run_regression.py -k "light_task or interaction013_acknowledgment_with_task or optiona_task_oriented or heavy_next_step"` → **7 passed**  
`python -m pytest tests/run_regression.py -k "optiona or interaction01 or interaction013"` → **17 passed**

### Revert

- Re-add the comma **`return False`** in **`user_input_needs_light_task_mode`**, remove the extra task-intent / **`task_oriented_input`** markers added in this pass, restore/rename tests to the pre–comma-relax expectations.

### Goal / examples (from Jessy + ChatGPT brief)

**Intended LIGHT (after this fix):**

- “What should I do next?”
- “That’s better, what should I do next?”
- “Okay, what’s the next step?”
- “Alright, what should I try?”

**Must stay HEAVY:**

- “OK, what should I do next to implement X?”
- Any line that hits existing **heavy hints** (technical / implementation / debugging per `heavy_hints` in code)

### Implementation report (numbered)

1. **What changed** — Removed blanket comma exclusion in **`user_input_needs_light_task_mode`**; added **`what should i try`**, **`what do i do next`**, **`what's the next step`**, **`what is the next step`** to **`task_oriented_input`** and to **`user_input_needs_conversation_mode`** task-intent markers so those prompts remain task-oriented and can match **light_phrases**.
2. **Where** — `services/prompt_builder.py`, `tests/run_regression.py` only.
3. **Why safe** — **Heavy hints** unchanged; **`implement`** still forces **OPEN CONVERSATION** + **OUTPUT FORMAT RULES**; conversation branch untouched; **`joshua`** / override / action-type guards unchanged.
4. **Revert** — Restore comma **`return False`**, strip the four added markers from both tuples, restore old test names/assertions.
5. **Tests** — **`test_light_task_mode_accepts_short_prefix_with_comma_before_next_step`**, **`test_light_task_mode_okay_whats_next_step_with_prefix`**, **`test_light_task_mode_alright_what_should_i_try_with_prefix`**, **`test_light_task_comma_still_heavy_when_implement_follows`**; **`test_interaction013_acknowledgment_with_task_intent_stays_task_oriented`** updated for **LIGHT** on mixed ack + next-step.

---

## Latest Implemented Fix (Context surfacing control — focus/stage)

Date: 2026-04-21

### Brief (Jessy + ChatGPT increment)

Keep **Current focus / Current stage / Current action type** in the system prompt for internal grounding, but **stop the model from verbally surfacing** those labels on generic or casual turns (**light task** and **conversation** paths). On **task-oriented** paths, allow context only when relevant: **minimal**, not leading every answer, not repetitive boilerplate.

### What changed

- Added **`CONTEXT_SURFACING_LIGHT_CONVERSATION`** and **`CONTEXT_SURFACING_TASK_ORIENTED`** string blocks in **`services/prompt_builder.py`** (documented in-file as revertible).
- Extended **`build_dynamic_prompt(..., *, context_surfacing_block="")`** to insert the chosen block **immediately after** the static **IMPORTANT RULES** block so it **overrides** generic “anchor to focus/stage first” phrasing for that request, without removing the header lines.
- In **`build_messages`**, before composing the system prompt:
  - **`subtarget == "system risk"`** → **`context_surfacing_block=""`** (verbatim forced sentence unchanged).
  - **`conversation_mode or light_task_mode`** → **LIGHT_CONVERSATION** block.
  - **Else** → **TASK_ORIENTED** block (softer anti-repetition / don’t-lead-with-labels guidance for structured and open-task replies).

### Files changed

- `services/prompt_builder.py` only (no new regression tests in this minimal pass).

### Why it is safe

- **No architecture or routing refactor**; no removal of focus/stage from the prompt.
- **Structured templates** that require labeled **Current state** lines are unchanged; the task-oriented text limits **free prose**, not required template lines.
- **System risk** path explicitly skips extra rules.

### Commands run (verification)

```text
python -m pytest tests/run_regression.py -k "prompt_builder or reasoning06 or build_messages_stable or light_task or conversation_mode" -q
```

Result: **19 passed** (496 deselected).

### How to revert

- Remove **`CONTEXT_SURFACING_LIGHT_CONVERSATION`**, **`CONTEXT_SURFACING_TASK_ORIENTED`**, the **`context_surfacing_block`** plumbing in **`build_dynamic_prompt`**, the **`if subtarget == "system risk"` / `elif conversation_mode or light_task_mode` / `else`** assignment before **`build_dynamic_prompt`**, and the **`context_surfacing_block=`** keyword argument on the call; or pass **`context_surfacing_block=""`** unconditionally to disable behavior without deleting the constant strings.

### Success criteria (from increment)

- **“What should I do next?”** → model instructed **not** to mention Phase 4 / focus / stage / action type / project labels unless the user asked.
- **“That’s better, what should I do next?”** (light path when classified **LIGHT**) → same **CONTEXT SURFACING (LIGHT OR CONVERSATION)** rules.
- **Project-specific / heavy** work → may still use context **naturally** and in required **Current state** blocks; task-oriented block discourages leading every answer with the same labels.

---

## Latest Implemented Fix (Light task mode — one concrete action or one question)

Date: 2026-04-21

### Brief (Jessy + ChatGPT increment)

Light task replies had become **clean and natural** but **too generic**. This pass tightens **LIGHT TASK MODE** prompt text only: require **exactly one** concrete immediate next action **or** **one** precise clarifying question when context is too thin—**no** menus, **no** vague-only coaching, **no** invented repo paths; **no** return of **Answer / Current state / Next step** templates.

### What changed

- In **`services/prompt_builder.py`**, the **`elif light_task_mode:`** **`answer_and_step_rules`** string now includes a **DECISIVENESS** block:
  - **(1)** One actionable step in plain prose (run a check, inspect an outcome, one small experiment); name files/modules/commands **only** when they appear in supplied context (user message, Supporting memory, Recent project journal, recent assistant outputs in the prompt); **do not invent** repo-specific details.
  - **(2)** If that is unsafe, **one** clarifying question only—no list of questions.
  - Explicit ban on vague-only lines (examples: “refine a component”, “optimize performance”, “improve functionality” without a specific move).
  - Reminder to follow existing **CONTEXT SURFACING (LIGHT OR CONVERSATION)** (harness labels stay internal) while still obeying decisiveness.
- **`tests/run_regression.py`**: added **`test_light_task_mode_prompt_requires_one_concrete_action_or_one_question`** (asserts new prompt phrases for **“What should I do next?”**, **“That’s better, what should I do next?”**, **“Alright, what should I try?”**).

### Files changed

- `services/prompt_builder.py`
- `tests/run_regression.py`

### Why it is safe

- **Routing unchanged**; only the **LIGHT TASK MODE** rule slice grew.
- **Structured / heavy** paths unchanged; **CONTEXT SURFACING** unchanged.
- **Anti-hallucination** and **single-question** escape hatch spelled out in prompt text.

### Commands run (verification)

```text
python -m pytest tests/run_regression.py -k "light_task or interaction013_acknowledgment_with_task or optiona_task_oriented" -q
```

Result: **7 passed** (509 deselected).

### How to revert

- Restore the previous shorter **LIGHT TASK MODE** `answer_and_step_rules` block (pre-**DECISIVENESS** wording) in **`prompt_builder.py`**.
- Remove **`test_light_task_mode_prompt_requires_one_concrete_action_or_one_question`** from **`tests/run_regression.py`**.

### Success criteria (from increment)

- **“What should I do next?”** → prompt instructs **one** clear action or **one** sharp question.
- **“That’s better, what should I do next?”** / **“Alright, what should I try?”** → same decisiveness rules in **LIGHT TASK MODE** text.

---

## Latest Implemented Fix (Clarify-first for undefined implement/build + no coaching preamble in light task)

Date: 2026-04-21

### Brief (Jessy + ChatGPT increment)

**Problem:** Lines like **“What should I do next to implement X?”** never hit **LIGHT TASK** because **`heavy_hints`** includes **`implement `** / **`build `**, so they fell through to **OPEN CONVERSATION** with **Answer / Current state / Next step**. Bare light-task replies could still open with generic coaching (**“Focus on…”**, **“Consider…”**) before the real move.

**Goal:** **(A)** Undefined placeholder **implement/build** targets → **exactly one** clarifying question, **no** guessed work, **no** structured **Current state / Next step** instructions. **(B)** Standard light-task → **first sentence =** the action or the question; **no** generic preamble.

### What changed

- **`services/prompt_builder.py`**
  - **`user_input_needs_clarify_first_undefined_implement_build(ul_norm)`** plus module-level regexes **`_CLARIFY_FIRST_*`**: only **`implement` / `build` + `x`/`y`/`z`**-style placeholders, with **`(?![a-z0-9_-])`** to avoid false matches (e.g. **`implement xml`**, **`z-index`**). **`.py`**, **`file:`**, **`joshua`**, or **>22 words** → not this path.
  - **`how should i build (x|y|z)`** matches without requiring a separate “next step” phrase; **`implement`/`build` + placeholder** requires **next-step-ish** wording (or **`how should i`**).
  - New **`elif clarify_first_undefined_implement_build:`** **`answer_and_step_rules`** block **`CLARIFY-FIRST (UNDEFINED IMPLEMENT/BUILD TARGET):`** — one question, no section headers, **FIRST SENTENCE** = the question, no preamble list.
  - **LIGHT TASK MODE:** new **FIRST SENTENCE** bullet (no **Focus on** / **Consider** / **Try to** / **It helps to** lead-ins before the single action or question).
  - **`context_surfacing_block`** and **`build_runtime_01_execution_enforcement_block(..., conversation_mode=...)`** now OR in **`clarify_first_undefined_implement_build`** with conversation/light so surfacing + runtime tail stay **light-style**.

- **`tests/run_regression.py`**
  - **`test_light_task_comma_still_heavy_when_implement_follows`** — now expects **CLARIFY-FIRST** and **no** **OUTPUT FORMAT RULES** for **“OK, what should I do next to implement X?”**
  - **`test_light_task_mode_prompt_requires_one_concrete_action_or_one_question`** — asserts **FIRST SENTENCE:** in prompt
  - **New:** **`test_clarify_first_undefined_implement_placeholder_routes_without_structured_template`**, **`test_implement_with_py_path_stays_heavy_not_clarify_first`**

### Files changed

- `services/prompt_builder.py`
- `tests/run_regression.py`

### Why it is safe

- **Narrow** placeholder detection (**`x`/`y`/`z`** only + continuation guard); real lines like **`parser.py`** stay **heavy** (**.py** guard).
- **Conversation mode** unchanged (still **earlier** **`elif`** than clarify-first).
- **No** new structured templates for clarify-first; **no** architecture refactor.

### Commands run (verification)

```text
python -m pytest tests/run_regression.py -k "light_task or clarify_first or implement or heavy_next or interaction013_acknowledgment_with_task or optiona_task_oriented" -q
python -m pytest tests/run_regression.py -k "interaction01 or interaction013 or optiona or reasoning06" -q
```

Results: **10 passed** (508 deselected) on the first line; **23 passed** (495 deselected) on the broader slice.

### How to revert

- Remove **`_CLARIFY_FIRST_*`**, **`user_input_needs_clarify_first_undefined_implement_build`**, **`clarify_first_undefined_implement_build`** wiring, the **`elif clarify_first_undefined_implement_build`** **`answer_and_step_rules`** block, revert **LIGHT TASK** **FIRST SENTENCE** bullet, revert **`context_surfacing_block`** / **runtime** ORs, restore **`test_light_task_comma_still_heavy_when_implement_follows`** to expect **OUTPUT FORMAT RULES** + no **CLARIFY-FIRST**, remove the two new tests and the **FIRST SENTENCE:** assertion from the light decisiveness test.

### Success criteria (from increment)

- **“What should I do next to implement X?”** / **“How should I build Y?”** → **CLARIFY-FIRST** path, **no** **OUTPUT FORMAT RULES** in the rule slice.
- **“What should I do next to implement … parser.py”** → stays **heavy** (structured path), **not** clarify-first.
- **Standard light-task** prompts → **FIRST SENTENCE** anti-preamble guidance in system text.
