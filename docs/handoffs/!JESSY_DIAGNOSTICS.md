# AI Agent Diagnostics - 2026-04-21

Project: AI Agent  
Type: Diagnostic only (no code changes)

---

## Diagnostic 1 - Template Forcing Source Scan

### Scope requested
- Find exact sources of forced template output:
  - `Progress:`
  - `Risks:`
  - `Decisions:`
  - `Next Steps:`
  - `Known:`
  - `Missing:`
  - `Conclusion:`
  - `Current State`
  - `Action type`
  - `Next Step`
- Trace fallback templates, output formatters, post-processing, prompt builders, mode/selector logic, enforcement layers, Joshua triggers, startup defaults.

### Exact matches found (runtime-relevant)

1. `services/prompt_builder.py`
- Constant: `RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`
- Contains exact strings:
  - `Progress:`
  - `Risks:`
  - `Decisions:`
  - `Next Steps:`
  - `Known:`
  - `Missing:`
  - `Conclusion:`
- Role:
  - Hardcoded enforcement block appended to system prompt.
  - Explicitly mandates structure and section headers.

2. `services/prompt_builder.py`
- Constant: `REASONING_06_CONTROL_GATE_BLOCK`
- Contains:
  - `Known:`
  - `Missing:`
  - `Conclusion:`
  - Suppression of `Progress/Risks/Decisions/Next Steps` and `Answer/Current state/Next step`.
- Role:
  - Route-specific enforcement for reasoning mode.

3. `services/prompt_builder.py`
- Function: `build_runtime_01_execution_enforcement_block(...)`
- Role:
  - Runtime selector choosing which enforcement tail is appended:
    - default `RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`
    - or reasoning gate
    - or conversation gate

4. `services/prompt_builder.py`
- Function: `build_messages(...)`
- Role:
  - Appends enforcement block directly to final prompt:
  - `system_prompt += "\n\n" + build_runtime_01_execution_enforcement_block(...)`

5. `services/prompt_builder.py`
- Function: `build_messages(...)` (strict/override branch and open branch)
- Contains explicit output structure instructions with:
  - `Answer:`
  - `Current state:`
  - `Action type:`
  - `Next step:`

6. `playground.py`
- Function: `handle_user_input(...)`
- Contains deterministic override path:
  - `force_structured_override = ...`
  - If true, directly constructs:
    - `Answer:`
    - `Current state:`
    - `Action type:`
    - `Next step:`
- Role:
  - Bypasses normal free-form model behavior in override cases.

7. `playground.py`
- Functions:
  - `_latency07_structured_fetch_reply_tail(...)`
  - `_latency07_deterministic_fetch_reply(...)`
- Contains deterministic template pieces:
  - `Current state:`
  - `Action type: research`
  - `Next step:`
  - plus top-level `Answer:`
- Role:
  - Short-circuit deterministic response in fetch path.

8. `app/ui.py`
- Function: `render_formatted_assistant_message(content)`
- Detects headers:
  - `Answer:`
  - `Current state:`
  - `Next step:`
- Renders UI labels:
  - `Current State`
  - `Next Step`
- Role:
  - Display formatter (does not create content).

9. `app/ui.py`
- Input placeholder:
  - `st.chat_input("Message Joshua…")`
- Role:
  - UI text only; no discovered hard trigger "if Joshua then force template".

10. `core/llm.py`
- Function: `ask_ai(messages, system_prompt=None)`
- Role:
  - Sends assembled system prompt to model; does not add these templates itself.

### Likely trigger path (diagnostic 1)
1. UI input: `app/ui.py` -> `run_query(...)` -> `_process_agent_reply_pending_in_chat(...)`
2. Core handling: `playground.handle_user_input(...)`
3. Prompt assembly: `playground.build_messages(...)` -> `services/prompt_builder.build_messages(...)`
4. Model call: `core/llm.ask_ai(...)`
5. Optional deterministic branches:
   - `force_structured_override` (directly built response in `playground.py`)
   - fetch short-circuit deterministic path
6. UI display formatting: `render_formatted_assistant_message(...)`

### Root cause conclusion (diagnostic 1)
- Structured outputs are enforced by code-level prompt/runtime logic.
- Clearing memory files does not disable these prompt/enforcement blocks or deterministic branches.

---

## Diagnostic 2 - Single Input Trace ("Bonjour Joshua" / "Hello Joshua")

### Test inputs used
- `Bonjour Joshua`
- `Hello Joshua`

### Runtime path traced
1. `app/ui.py` -> `run_query(user_input)`
2. `app/ui.py` -> `_process_agent_reply_pending_in_chat()`
3. `app/ui.py` -> `playground.handle_user_input(pending)`
4. `playground.py` -> `handle_user_input(...)`
5. `playground.py` -> `build_messages(...)` -> `services/prompt_builder.build_messages(...)`
6. `core/llm.py` -> `ask_ai(messages, system_prompt)`
7. `playground.py` -> `parse_tool_command(response)`
8. no tool command path for this greeting case -> direct return
9. UI display through `render_formatted_assistant_message(...)`

### Branch decisions evaluated for both inputs
- `focus`: `ai-agent project`
- `stage`: `Phase 4 action-layer refinement`
- `action_type`: `build`
- `subtarget`: `current behavior`
- `reasoning_mode_candidate`: `false`
- `clarification_override_mode`: `false`
- `reasoning_structure_mode`: `false`
- `conversation_mode`: `false`
- `strict_reply`: `false`
- `is_meta_system_override_question`: `false`
- `is_vague_research_request`: `false`
- `force_structured_override`: `false`
- `enforcement_block_appended`: `RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK`

### Model call vs deterministic construction
- Model called: **Yes**
- Deterministic override path used: **No** for this test input.
- Fetch short-circuit deterministic reply used: **No** for this test input.

### Final system prompt findings for "Bonjour Joshua"
The assembled final system prompt contained:
- Open conversation instruction area with explicit three-section format:
  - `Answer:`
  - `Current state:`
  - `Next step:`
- Then appended execution enforcement block containing:
  - `Progress:`
  - `Risks:`
  - `Decisions:`
  - `Next Steps:`
  - plus `Known:`, `Missing:`, `Conclusion:` guidance.

So for this test case, the model is called with an already heavily structured system prompt.

### Exact reason templated output appears for this test case
- Not from memory.
- Not from `force_structured_override`.
- Not from fetch deterministic short-circuit.
- It appears because `build_messages(...)` for this input appends `RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK` and includes explicit structured output instructions before `ask_ai(...)`.

### Smallest next inspection location (no fixes applied)
- `services/prompt_builder.py`
  - `build_messages(...)` branch that sets `answer_and_step_rules`
  - append point:
    - `system_prompt += "\n\n" + build_runtime_01_execution_enforcement_block(...)`

---

## Diagnostic 3 - Greeting-Only Fix Design (No Code Changes)

### Goal
- Design-only plan for the exact greeting case:
  - `Bonjour Joshua`
  - `Hello Joshua`
- No code edits in this pass.

### 1) Exact code locations

- `services/prompt_builder.py` — greeting detection is narrow in `user_input_needs_conversation_mode()`:
  - only exact matches:
    - `joshua?`
    - `hey joshua?`
    - `hi joshua?`

- `services/prompt_builder.py` — OPEN CONVERSATION MODE branch still injects structured output instructions through `answer_and_step_rules`:
  - requires:
    - `Answer:`
    - `Current state:`
    - `Next step:`

- `services/prompt_builder.py` — runtime enforcement block append in `build_messages(...)`:
  - `system_prompt += "\n\n" + build_runtime_01_execution_enforcement_block(...)`

- `services/prompt_builder.py` — default fallback of `build_runtime_01_execution_enforcement_block(...)`:
  - returns `RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK` when conversation/reasoning modes are not active.

### 2) Greeting-case root cause

For both test greetings, evaluated flags were:
- `conversation_mode = false`
- `reasoning_structure_mode = false`
- `strict_reply = false`
- `force_structured_override = false`

Result:
- Prompt still receives OPEN CONVERSATION MODE `Answer/Current state/Next step` structure.
- Prompt also appends default `RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK` (`Progress/Risks/Decisions/Next Steps`, plus reasoning sections).
- Model is called with these structured instructions already present.

### 3) Option comparison (design only)

1. **True conversation_mode for simple greetings**
   - Risk: low
   - Scope: narrow greeting classifier change
   - Reuses existing tested INTERACTION-01 path

2. **Suppress `answer_and_step_rules` for greeting/chat**
   - Risk: medium
   - Alters central prompt assembly behavior

3. **Suppress `RUNTIME_01` block for greeting/chat**
   - Risk: medium-high
   - Touches broad enforcement semantics

4. **Both 2 and 3**
   - Risk: highest
   - Largest blast radius

### 4) Recommended smallest safe fix option

- Recommended: **Option 1** (route greeting-only inputs into conversation mode).
- Reason:
  - Minimal blast radius
  - Lowest regression risk
  - No broad prompt/enforcement refactor

### 5) Tests likely affected

Most likely requiring update/extension:
- `tests/run_regression.py`
  - `test_interaction01_routes_simple_conversation_to_conversation_mode`
  - likely add greeting variants (`Hello Joshua`, `Bonjour Joshua`)

Likely still pass but should be re-run:
- `test_interaction01_build_messages_contains_conversation_instructions`
- `test_interaction011_routes_conditional_help_tool_prompt_to_conversation_mode`
- `test_interaction012_routes_clarification_prompt_to_conversation_mode`

Likely unaffected (non-greeting runtime enforcement tests):
- `test_runtime01_prompt_includes_execution_enforcement`
- `test_runtime03_prompt_enforces_structure`

---

## Notes
- This file is diagnostic record only.
- No code edits were applied as part of any diagnostic pass documented here.

---

## Diagnostic 4 - Project Viability Forecast (Copy/Paste Friendly)

Project: AI Agent  
Type: Full viability diagnostic (design/assessment only, no code edits)

### Executive forecast
- Success probability: **72%**
- Failure probability: **28%**
- Forecast confidence: **61%**

### How the percentages were computed
Weighted viability model (0-100 score per factor):

1. Architecture and modularity  
   - Weight: 20%  
   - Score: 78  
   - Contribution: 15.6

2. Testing and reliability discipline  
   - Weight: 25%  
   - Score: 82  
   - Contribution: 20.5

3. Operational maintainability  
   - Weight: 15%  
   - Score: 67  
   - Contribution: 10.1

4. Product behavior consistency  
   - Weight: 20%  
   - Score: 58  
   - Contribution: 11.6

5. Execution momentum and delivery readiness  
   - Weight: 20%  
   - Score: 71  
   - Contribution: 14.2

Total weighted score: **72.0 / 100**  
Mapped forecast: **72% success**, **28% failure**

### Evidence basis used
- Repo architecture split exists and is clear (`playground.py`, `services/*`, `core/*`, `app/ui.py`).
- Regression gate is substantial (current run file enumerates a large set of scenarios).
- CI/nightly workflows and reliability docs exist.
- Known risk from this morning diagnostics: greeting inputs can still route into structured template behavior.
- Working tree shows active changes and ongoing iteration, indicating momentum but also in-flight volatility.

### Why success is above 50%
- Strong engineering foundation and modular separation.
- Established test/reliability culture with explicit gates.
- Active diagnostics and documented operational runbooks.
- Clear ability to trace runtime behavior to exact branches.

### Why failure risk is still significant (28%)
- Prompt/routing collisions can degrade user-facing behavior quality.
- Increasing rule complexity raises maintenance and debugging load.
- Some documentation baseline drift suggests process synchronization risk.
- Product-fit/adoption risk remains separate from technical correctness.

### Failure-risk split (28% total)
- Behavior quality drift persists: 10%
- Operational complexity slows iteration: 7%
- Delivery consistency drops: 6%
- External/market mismatch: 5%

### Practical interpretation
- This is a **promising but not guaranteed** project.
- If behavior consistency and routing edge cases are tightened while keeping regression discipline, success odds can improve materially.
- If prompt/routing complexity keeps growing faster than control mechanisms, failure odds increase.

---

## Plans and Recommendations

### Plan Submitted (Behavior Stabilization Game Plan v1)

Project name: AI Agent

BEHAVIOR STABILIZATION GAME PLAN (v1)  
DESIGN REVIEW ONLY — DO NOT IMPLEMENT YET

This is a structured plan based on full diagnostics (prompt_builder, runtime enforcement, deterministic overrides, and viability assessment).

Your task:
- Evaluate this plan
- Validate risks
- Suggest improvements
- Identify blind spots
- DO NOT implement yet
- DO NOT modify code yet

---

OBJECTIVE

Restore predictable, context-appropriate behavior in AI Agent before continuing:
- knowledge ingestion
- extraction format
- atomic memory system

We are fixing:
-> behavior control layer ONLY

We are NOT touching:
-> memory system
-> extractor
-> architecture
-> core LLM transport

---

PHASE 0 — CONSTRAINTS (STRICT)

- No large refactors
- No rewriting architecture
- No changes to memory or extractor
- No broad suppression of templates globally

- Only modify:
  -> routing logic
  -> mode selection
  -> prompt assembly gating

---

PHASE 1 — CONFIRM TARGET

Primary file:
- services/prompt_builder.py

Confirmed issues:
1) Greeting inputs do NOT trigger conversation_mode
2) Structured templates injected regardless of context
3) Multiple enforcement blocks stack in same prompt

---

PHASE 2 — FIX #1 (LOW RISK / HIGH IMPACT)

GOAL:
Route greeting inputs into true conversation_mode

CURRENT LIMITATION:
user_input_needs_conversation_mode(...) only matches:
- "joshua?"
- "hey joshua?"
- "hi joshua?"

PROPOSED CHANGE:
Expand detection to include:
- "hello joshua"
- "bonjour joshua"
- "hi joshua"
- "hey joshua"
- "yo joshua"
- "good morning joshua"
- similar greeting patterns

EXPECTED RESULT:
For greeting inputs:
- No Answer / Current state / Next step
- No Progress / Risks / Decisions / Next Steps
- Natural conversational response via INTERACTION_01

---

PHASE 3 — TEST GATE 1

Test inputs:
- Hello Joshua
- Bonjour Joshua
- Hi Joshua
- Hey Joshua

Expected:
- clean conversational response
- no structured templates

---

PHASE 4 — FIX #2 (CONTROL TEMPLATE INJECTION)

PROBLEM:
Even outside greetings:
- answer_and_step_rules injected unconditionally
- RUNTIME_01 enforcement always appended

GOAL:
Prevent structured templates when not contextually required

TARGET BEHAVIOR MODEL:

Input Type -> Mode
- Greeting -> Conversation
- Simple question -> Direct answer (no template)
- Complex reasoning -> Reasoning block
- Task / execution -> Structured output
- System query -> Structured output

IMPORTANT:
Do NOT build full mode system yet
Only introduce minimal gating

---

PHASE 5 — MINIMAL GATING OPTIONS (EVALUATE)

Option A (preferred):
- Only inject answer_and_step_rules when:
  - NOT conversation_mode
  - AND input classified as task-oriented

Option B:
- Suppress RUNTIME_01 block for:
  - greeting inputs
  - simple questions

Option C:
- Hybrid of A + B

TASK:
Evaluate which option has:
- lowest blast radius
- lowest regression risk
- highest alignment with current architecture

---

PHASE 6 — TEST GATE 2

Test cases:

1) Simple factual:
"What is the capital of France?"
Expected:
- "Paris"
- no Known/Missing
- no Progress/Risks

2) Simple explanation:
"What does Tool 1 do?"
Expected:
- clean explanation
- no forced template

3) Task-oriented:
"What should I do next?"
Expected:
- structured output allowed

4) Complex reasoning:
"Analyze this system failure"
Expected:
- reasoning structure allowed

---

PHASE 7 — COLLISION CHECK

Ensure:
- Only ONE output mode is active per response

No mixing:
- Answer + Progress
- Known + Current State
- Multiple template systems in same response

---

PHASE 8 — STABILITY VALIDATION

Run:
- regression tests
- relevant flows

Verify:
- no broken structured outputs
- no missing required formats in task flows

---

PHASE 9 — LOCK BEHAVIOR LAYER

After stabilization:
- Freeze prompt behavior logic
- Document mode activation rules clearly

---

PHASE 10 — RESUME ROADMAP

ONLY AFTER behavior is stable:

Resume:
1) Knowledge Ingestion Template
2) Extraction Format (Q/A)
3) Atomic Memory Packaging

---

RISK CONTROL

We are targeting:
-> Product behavior consistency (currently weakest score)

We are preserving:
-> Architecture (strong)
-> Testing discipline (strong)
-> Execution momentum (good)

---

SUCCESS CRITERIA

System is considered stable when:

- Greetings produce natural responses
- Simple questions produce direct answers
- Structured output appears ONLY when appropriate
- No template leakage
- No mode collisions

---

YOUR TASK

Evaluate this plan and answer:

1) Is this the correct minimal path forward?
2) Which gating option (A, B, or C) is safest?
3) What risks are not accounted for?
4) What tests should be added before implementation?
5) Any hidden interactions in prompt_builder or playground that could break this plan?

DO NOT IMPLEMENT YET  
DESIGN REVIEW ONLY

### Review and Recommendations (Design Review Only)

- Overall assessment: the plan is strong, constrained, and follows an appropriate low-blast-radius sequence.

1) Is this the correct minimal path forward?
- Yes. Starting with greeting routing, then adding minimal gating, then collision checks is the right order.

2) Which gating option (A, B, or C) is safest?
- Safest first move: **Option A** (with a narrow definition of "task-oriented").
- Rationale:
  - Lower blast radius than suppressing runtime enforcement globally.
  - Keeps existing enforcement behavior for task/system paths.
  - Avoids broad semantic changes to RUNTIME_01.
- Option B is riskier because suppressing RUNTIME_01 for broad "simple questions" can break assumptions in existing tests and behavior contracts.
- Option C may be useful later only if A is insufficient.

3) Risks not fully accounted for
- Ambiguous intent classification:
  - short prompts can look conversational but be task intent.
- Deterministic non-prompt paths:
  - `force_structured_override` and fetch short-circuit paths in `playground.py` can still produce structured responses.
- Prompt stacking interactions:
  - memory/journal appends may still bias model formatting even after gating changes.
- Overbroad greeting detection:
  - loose patterns could swallow legitimate non-greeting inputs.
- Regression coupling:
  - tests currently validate many structured prompt assumptions.

4) Tests to add before implementation
- Greeting positives:
  - `Hello Joshua`, `Bonjour Joshua`, `Hi Joshua`, `Hey Joshua`.
- Greeting + task disambiguation:
  - `Hello Joshua, what should I do next?` should preserve task-appropriate mode.
- Simple direct-answer behavior:
  - `What is the capital of France?` -> no template sections.
  - `What does Tool 1 do?` -> direct explanation, no template sections.
- Collision checks:
  - assert single active mode per prompt (no mixed template families).
- Deterministic branch checks:
  - ensure `force_structured_override` and fetch deterministic behavior remain intentional.

5) Hidden interactions to watch (`prompt_builder` / `playground`)
- `services/prompt_builder.py`:
  - OPEN CONVERSATION branch currently injects `Answer/Current state/Next step`.
  - Runtime enforcement append currently always executes.
- `services/routing_service.py`:
  - action/subtarget inference can steer mode unexpectedly.
- `playground.py`:
  - deterministic bypass branches can bypass prompt-mode expectations.
- `app/ui.py`:
  - formatter is display-only but can mask upstream structured leakage if not explicitly checked in tests.

### Recommended Implementation Order (Still Design-Only)

1. Implement greeting-mode routing expansion only.
2. Run Gate 1 tests + regression subset.
3. If leakage persists, implement Option A minimal gating.
4. Add collision assertions.
5. Run full regression and targeted flow checks.
6. Only then consider Option C if A does not fully stabilize behavior.

### Plans and Recommendations — Brain integration manual test checklist

Date: 2026-04-21  
Context: Brain toggle is implemented in `core/llm.py`; `USE_BRAIN=true` can be active; behavior layer remains locked—this checklist is **manual validation only** (no code changes in the request).

**Goal:** Confirm “brain is active **and** the system is still stable.”

1. **Preflight / env**  
   - **Action:** Start Joshua the usual way.  
   - **Expect:** No startup/preflight errors about missing `OPENAI_API_KEY_BRAIN` or `OPENAI_BRAIN_MODEL` when `USE_BRAIN=true`.

2. **Brain actually in use**  
   - **Input:** “In one sentence, name the exact model answering this message.”  
   - **Expect:** Reply aligns with the configured brain model (or clearly isn’t the old baseline label if you know it); no API/auth error text.

3. **Plain conversation (routing + format)**  
   - **Input:** “Hello Joshua”  
   - **Expect:** Short natural reply; **no** `Known` / `Missing` / `Conclusion` or `Answer:` / `Current state:` / `Next step:` blocks.

4. **Plain-answer override**  
   - **Input:** “Can you answer that normally?”  
   - **Expect:** Brief plain agreement; **not** only “What would you like to know?” as the whole message; still no structured headers.

5. **Task path still structured when appropriate**  
   - **Input:** “What should I do next?”  
   - **Expect:** Task-style reply with clear next-step guidance (structured **allowed** here); no LLM configuration errors.

6. **Meta-format question**  
   - **Input:** “Why do you give me answers in that format?”  
   - **Expect:** Plain prose explanation; **no** `Known` / `Missing` / `Conclusion` unless you explicitly asked for those headers.

7. **Rollback sanity (optional)**  
   - **Action:** Set `USE_BRAIN=false`, restart, repeat test **#2**.  
   - **Expect:** Model identity reflects baseline again; still no crashes.

**Pass bar:** Tests **1–3** and **5–6** clean with `USE_BRAIN=true`; **#2** confirms brain; **#7** confirms the toggle really switches.

### Follow-Up Conversation Diagnostic (Post-Greeting Fix, No Code Changes)

#### Input analyzed
`A lot better now that I can get a straight up normal answer`

#### Branch decisions
- `action_type`: `build`
- `conversation_mode`: `false`
- `reasoning_structure_mode`: `false`
- `strict_reply`: `false`
- `force_structured_override`: `false`
- Other key flags:
  - `subtarget`: `current behavior`
  - `conversation_candidate`: `false`
  - `task_oriented_input`: `false`
  - `simple_question_mode`: `false`

#### Why it left conversation mode
- Does not match current conversation markers in `user_input_needs_conversation_mode(...)`.
- Not a wh-question (`what/who/where/when/why/how`), so `simple_question_mode` stays false.
- Final `conversation_mode` remains false, so default runtime structural enforcement remains active.

#### Exact code location
- `services/prompt_builder.py` in `build_messages(...)`:
  - `simple_question_mode = ... re.match(r"^(what|who|where|when|why|how)\b", ul_norm) ...`
  - `conversation_mode = ((conversation_mode or simple_question_mode) and subtarget != "system risk")`

#### Minimal fix idea (no implementation)
- Add a narrow conversational-feedback marker lane (short acknowledgment/feedback phrases) that routes to conversation mode only when no task markers are present.

---

#### Input analyzed
`Be good`

#### Branch decisions
- `action_type`: `build`
- `conversation_mode`: `false`
- `reasoning_structure_mode`: `false`
- `strict_reply`: `false`
- `force_structured_override`: `false`
- Other key flags:
  - `subtarget`: `current behavior`
  - `conversation_candidate`: `false`
  - `task_oriented_input`: `false`
  - `simple_question_mode`: `false`

#### Why it left conversation mode
- Not in existing greeting/help/clarification marker set.
- Not a wh-question, so `simple_question_mode` is false.
- Falls to non-conversation path -> structured runtime enforcement.

#### Exact code location
- `services/prompt_builder.py`:
  - `user_input_needs_conversation_mode(...)` marker checks
  - `simple_question_mode` and final `conversation_mode` assignment in `build_messages(...)`

#### Minimal fix idea (no implementation)
- Add a tiny short-social-utterance check (1-3 token polite/relational prompts), guarded by non-task intent.

---

#### Input analyzed
`That means do your best to help me. Can you do that?`

#### Branch decisions
- `action_type`: `build`
- `conversation_mode`: `false`
- `reasoning_structure_mode`: `false`
- `strict_reply`: `false`
- `force_structured_override`: `false`
- Other key flags:
  - `subtarget`: `current behavior`
  - `conversation_candidate`: `false`
  - `task_oriented_input`: `false`
  - `simple_question_mode`: `false`

#### Why it left conversation mode
- Existing conversation markers are phrase-specific (e.g., `can you help me`), and this wording does not match those conditions.
- `simple_question_mode` is restricted to wh-question starters; this is a yes/no style ask.
- Final `conversation_mode` remains false.

#### Exact code location
- `services/prompt_builder.py`:
  - `user_input_needs_conversation_mode(...)` phrase list
  - `simple_question_mode` rule in `build_messages(...)`

#### Minimal fix idea (no implementation)
- Add a narrow conversational yes/no-support pattern (`can you do that`, `do your best to help me`) when no task markers are present.

---

#### Decision ownership confirmation
- Primary decision point: `services/prompt_builder.py` (`build_messages` + `user_input_needs_conversation_mode`).
- `routing_service.py` contributes `action_type` / `subtarget`.
- `playground.py` orchestrates calls but is not the primary classifier for this specific behavior.

#### Current-input-only confirmation
- `conversation_mode` is mostly based on current input text.
- It also uses current-turn routing context (`subtarget`, stage-based action typing).
- It is not directly using previous-turn memory/history to set this specific mode.

#### Single most important code location
- `services/prompt_builder.py` in `build_messages(...)`, specifically:
  - `simple_question_mode` definition
  - final `conversation_mode` assignment

---

### Follow-Up Prompt (Live-Validated Acknowledgment Case)

Confirmed behavior from live test:

1) "That’s much better"
-> Progress / Risks / Decisions / Next Steps

2) "Nice"
-> Progress / Risks / Decisions / Next Steps

3) "Yeah that makes sense now"
-> Progress / Risks / Decisions / Next Steps

4) "That’s better, what should I do next?"
-> structured task/build response

5) "Can you help me with this?"
-> natural conversational reply: "What do you need help with?"

Conclusion:
- help-oriented conversation markers are already partially working
- short conversational feedback / acknowledgment inputs are not
- mixed conversation + task wording routes into task mode

Next diagnostic question:
Based on these live results, identify the SMALLEST safe classifier expansion for conversational feedback acknowledgments only.

Examples to cover:
- "That’s much better"
- "Nice"
- "Yeah that makes sense now"

Requirements:
- DIAGNOSTIC ONLY
- DO NOT CHANGE CODE
- show exact rule location
- show exact pattern type you would add
- explain how to avoid swallowing task inputs
- confirm whether mixed inputs like "That’s better, what should I do next?" should remain task-oriented

### Follow-Up Diagnostic Reply (No Code Changes)

Perfect diagnostic signal. Based on those live results, the smallest safe expansion is:

- add a very narrow acknowledgment-only matcher inside `user_input_needs_conversation_mode(...)` in `services/prompt_builder.py`
- keep existing task-intent guard before that matcher so task text still wins

#### Exact rule location
- `services/prompt_builder.py`
- function: `user_input_needs_conversation_mode(user_input: str)`
- specifically right after current task-intent exclusions and before returning `False`

#### Exact pattern type to add
Use a bounded exact/near-exact phrase set (not broad sentiment NLP), e.g. normalized-lowercase checks for short feedback acknowledgments:

- `"that's much better"` / `"thats much better"`
- `"nice"`
- `"yeah that makes sense now"` / `"that makes sense now"`

Pattern style should be:
- exact normalized match, or very tight regex with optional punctuation
- short length cap (e.g., <= 6–8 tokens)

#### How to avoid swallowing task inputs
Keep this order:

1. task-intent checks first (`next step`, `what should i do next`, `implement`, etc.)
2. then acknowledgment matcher

That guarantees:
- `"That’s better, what should I do next?"` remains task-oriented
- pure acknowledgment phrases route to conversation mode

#### Mixed input confirmation
Yes — mixed inputs like `"That’s better, what should I do next?"` should remain task-oriented.
That behavior is correct and should be preserved.

---

### Conversation Reply Quality Diagnostic (Post-Routing Fixes, No Code Changes)

#### Input analyzed
`That’s much better`

#### Branch decisions
- `action_type`: `build`
- `conversation_mode`: `true`
- `reasoning_structure_mode`: `false`
- `strict_reply`: `false`
- `force_structured_override`: `false`
- Other flags:
  - `subtarget`: `current behavior`
  - `conversation_candidate`: `true`
  - `task_oriented_input`: `false`
  - `simple_question_mode`: `false`
  - `INTERACTION_01 active`: `yes`

#### Why reply sounds unnatural/repetitive
- It is in conversation mode correctly, but prompt still includes broad global guidance (`current focus/stage`, `action rule`, concise/useful emphasis) that can bias toward practical next-step phrasing.
- No explicit acknowledgment-style micro-guidance exists, so model falls back to generic “what next?” style.

#### Exact code location
- `services/prompt_builder.py` -> `build_dynamic_prompt(...)` composition:
  - static `IMPORTANT RULES` + `ACTION RULE` always included.
- plus conversation block in `build_messages(...)`:
  - `answer_and_step_rules` for `CONVERSATION MODE (INTERACTION-01)`.

#### Minimal fix idea (no implementation)
- In conversation mode only, add narrow acknowledgment micro-guidance:
  - for short acknowledgment inputs, reply with acknowledgment sentence only;
  - do not auto-redirect to next-step question unless user asks for next step.

---

#### Input analyzed
`Nice`

#### Branch decisions
- `action_type`: `build`
- `conversation_mode`: `true`
- `reasoning_structure_mode`: `false`
- `strict_reply`: `false`
- `force_structured_override`: `false`
- Other flags:
  - `subtarget`: `current behavior`
  - `conversation_candidate`: `true`
  - `task_oriented_input`: `false`
  - `simple_question_mode`: `false`
  - `INTERACTION_01 active`: `yes`

#### Why reply sounds unnatural/repetitive
- Correct mode, but no dedicated one-word-ack handling, so response tends to generic redirection.

#### Exact code location
- `services/prompt_builder.py`:
  - conversation instruction block (no ack-specific guidance)
  - global static rules from `build_dynamic_prompt(...)`.

#### Minimal fix idea (no implementation)
- Add one narrow rule for 1–3 word acknowledgments in conversation mode:
  - prefer short acknowledgment (`"Nice."`) and stop.

---

#### Input analyzed
`Yeah that makes sense now`

#### Branch decisions
- `action_type`: `build`
- `conversation_mode`: `true`
- `reasoning_structure_mode`: `false`
- `strict_reply`: `false`
- `force_structured_override`: `false`
- Other flags:
  - `subtarget`: `current behavior`
  - `conversation_candidate`: `true`
  - `task_oriented_input`: `false`
  - `simple_question_mode`: `false`
  - `INTERACTION_01 active`: `yes`

#### Why reply sounds unnatural/repetitive
- Routing is correct; repetitive style is response-quality/tone behavior under current prompt wording, not routing failure.

#### Exact code location
- `services/prompt_builder.py` conversation-mode block plus static global prompt text.

#### Minimal fix idea (no implementation)
- Add ack-follow-up style constraint:
  - for acknowledgment phrases, do not automatically pivot to workflow/focus question.

---

#### Input analyzed
`That’s better, what should I do next?`

#### Branch decisions
- `action_type`: `build`
- `conversation_mode`: `false`
- `reasoning_structure_mode`: `false`
- `strict_reply`: `false`
- `force_structured_override`: `false`
- Other flags:
  - `subtarget`: `current behavior`
  - `conversation_candidate`: `false`
  - `task_oriented_input`: `true`
  - `simple_question_mode`: `false`
  - `INTERACTION_01 active`: `no`

#### Why reply sounds unnatural/repetitive
- This is intentionally task-oriented; structured output is expected here.

#### Exact code location
- `services/prompt_builder.py` -> `task_oriented_input` markers include next-step phrases, which blocks conversation mode.

#### Minimal fix idea (no implementation)
- No change needed for this case; keep task-oriented behavior.

---

#### Input analyzed
`Can you help me with this?`

#### Branch decisions
- `action_type`: `build`
- `conversation_mode`: `true`
- `reasoning_structure_mode`: `false`
- `strict_reply`: `false`
- `force_structured_override`: `false`
- Other flags:
  - `subtarget`: `current behavior`
  - `conversation_candidate`: `true`
  - `task_oriented_input`: `false`
  - `simple_question_mode`: `false`
  - `INTERACTION_01 active`: `yes`

#### Why reply sounds unnatural/repetitive
- Routing is correct; generic clarification style appears because conversation rules do not define richer acknowledgment/help tone behavior.

#### Exact code location
- `services/prompt_builder.py` -> conversation-mode instruction text in `answer_and_step_rules`.

#### Minimal fix idea (no implementation)
- Add tiny style guidance in INTERACTION_01:
  - for generic help asks, one short warm acknowledgment + one concrete clarifying question;
  - for acknowledgment-only inputs, no forced clarifying question.

---

#### Decision source confirmation
- Primary source: `prompt_builder` wording (not routing failure for the first three inputs).
- `INTERACTION_01` is active for those acknowledgment inputs.
- No evidence this specific repetitiveness comes from deterministic override branches.
- No exact hardcoded match for phrases like “What would you like to focus on next?” was found in code; behavior is consistent with model tendency under current prompt wording.

#### Single most important code location
- `services/prompt_builder.py` — `answer_and_step_rules` block for `elif conversation_mode:` (`CONVERSATION MODE (INTERACTION-01)` instructions).

---

### Live Runtime Verification Diagnostic (No Code Changes)

Problem snapshot:
- Tests passed for acknowledgment-style prompt guidance.
- Live responses still appeared generic/repetitive in some runs.

#### Input analyzed
`Nice`

#### Runtime path
- `app/ui.py` -> `run_query(...)`
- `app/ui.py` -> `_process_agent_reply_pending_in_chat(...)`
- `playground.py` -> `handle_user_input(...)`
- `playground.py` -> `build_messages(...)`
- `services/prompt_builder.py` -> `build_messages(...)`
- `core/llm.py` -> `ask_ai(messages, system_prompt)`
- return model text -> UI render

#### Final system prompt presence/absence of micro-rule
- Micro-rule present: **yes**
- Conversation mode present: **yes**
- `Structural output (RUNTIME-03)` present: **no**
- `OUTPUT FORMAT RULES:` present: **no**

#### Exact reason live behavior differs
- Not a routing failure for this input.
- Prompt text includes the new micro-rule, but final wording is still model-generated and not deterministically post-constrained.
- Additional practical guidance in the overall prompt can still bias toward “what next” style language.

#### Exact code location
- `services/prompt_builder.py` (conversation-mode `answer_and_step_rules`)
- `core/llm.py` (`ask_ai`) where model generates final wording

#### Minimal next fix idea (no implementation)
- Keep scope tiny: strengthen acknowledgment rule wording to hard constraint language (statement only, no follow-up question) for short acknowledgment inputs.

---

#### Input analyzed
`That’s much better`

#### Runtime path
- Same as above (`app/ui.py` -> `playground.py` -> `prompt_builder.py` -> `core/llm.py`)

#### Final system prompt presence/absence of micro-rule
- Micro-rule present: **yes**
- Conversation mode present: **yes**
- Runtime structured block present for this input: **no**

#### Exact reason live behavior differs
- Same as above: model output quality variance under current prompt wording, not classifier miss for this input.

#### Exact code location
- `services/prompt_builder.py` conversation-mode rule text
- `core/llm.py` generation step

#### Minimal next fix idea (no implementation)
- Narrow prompt hardening for acknowledgment-only responses in INTERACTION_01.

---

#### Input analyzed
`That’s better, what should I do next?`

#### Runtime path
- Same path, different branch outcome in `prompt_builder.build_messages(...)`

#### Final system prompt presence/absence of micro-rule
- Micro-rule present: **no** (expected)
- Conversation mode present: **no**
- `Structural output (RUNTIME-03)` present: **yes**
- `OUTPUT FORMAT RULES:` present: **yes**

#### Exact reason live behavior differs
- This input is intentionally task-oriented by classifier rules (`task_oriented_input = true`) due explicit next-step phrasing.

#### Exact code location
- `services/prompt_builder.py` -> `task_oriented_input` markers + final `conversation_mode` assignment

#### Minimal next fix idea (no implementation)
- No change needed for this mixed/task input.

---

#### A/B/D/E/F/G summary

- **A) Live path uses modified `services/prompt_builder.py`:**
  - Current runtime assembly checks confirm micro-rule text exists for acknowledgment-only inputs.

- **B) Runtime path confirmed:**
  - `app/ui.py` -> `playground.py` -> `services/prompt_builder.py` -> `core/llm.py`

- **D) Micro-rule text present at runtime (for acknowledgment-only inputs):**
  - **Yes**

- **E) If missing:**
  - Not missing in current assembled prompts for those two acknowledgment inputs.
  - If observed missing in future: likely stale process/reload mismatch.

- **F) If present but still generic:**
  - Most likely model tendency under overall prompt framing.

- **G) Single most important runtime chokepoint:**
  - `core/llm.py` generation step (`ask_ai`) because there is no deterministic post-validation/rewriter for conversational style.

---

### Structured Format Leak Diagnostic (No Code Changes)

#### Input analyzed
`That’s better, what should I do next?`

#### Branch decisions
- `action_type`: `build`
- `conversation_mode`: `false`
- `reasoning_structure_mode`: `false`
- `strict_reply`: `false`
- `force_structured_override`: `false`
- `task_oriented_input`: `true`
- `simple_question_mode`: `false`
- Other relevant:
  - `subtarget`: `current behavior`
  - `conversation_candidate`: `false`
  - `reasoning_mode_candidate`: `false`

#### Active prompt blocks
- `INTERACTION_01`: inactive
- `RUNTIME_01`: active
- `RUNTIME_03`: active
- `REASONING_06`: inactive
- `OUTPUT FORMAT RULES`: active
- strict/meta override block: inactive

#### Why structured format leaked
- This behavior is currently intentional in code path:
  - next-step phrasing sets `task_oriented_input = true`
  - conversation mode is therefore bypassed
  - structured output guidance remains active

#### Exact code location
- `services/prompt_builder.py` in `build_messages(...)`:
  - `task_oriented_input` marker checks
  - final `conversation_mode` assignment

#### Minimal fix idea (no implementation)
- If desired, add a narrow mixed-ack+task override:
  - allow brief plain-prose task guidance when input begins with acknowledgment and includes next-step ask.
  - keep this highly constrained to avoid broader regressions.

---

#### Input analyzed
`Why do you give me answers in that format?`

#### Branch decisions
- `action_type`: `build`
- `conversation_mode`: `true` (via `simple_question_mode = true`)
- `reasoning_structure_mode`: `false`
- `strict_reply`: `false`
- `force_structured_override`: `false`
- `task_oriented_input`: `false`
- `simple_question_mode`: `true`
- Other relevant:
  - `subtarget`: `titan formatting`
  - `conversation_candidate`: `false`
  - `reasoning_mode_candidate`: `false`

#### Active prompt blocks
- `INTERACTION_01`: active
- `RUNTIME_01`: active (lead + conversation tail)
- `RUNTIME_03`: inactive
- `REASONING_06`: inactive
- `OUTPUT FORMAT RULES`: inactive
- strict/meta override block: inactive

#### Why structured format leaked
- Current runtime classification is conversation mode, not reasoning mode.
- If live output still appears as `Known / Missing / Conclusion`, this is likely model-side non-compliance / interpretation drift under current prompt wording.
- The line allowing structure “unless explicitly asked” can be over-interpreted on a format complaint question.

#### Exact code location
- `services/prompt_builder.py`:
  - `answer_and_step_rules` for `elif conversation_mode:`
  - especially the phrasing: “unless the user explicitly asks for that structure.”

#### Minimal fix idea (no implementation)
- Tighten that one INTERACTION_01 line:
  - questions about answer format should still be answered in plain prose unless user explicitly requests exact section headers.

---

#### Classification confirmation (second input)
- Reasoning request: no
- System/meta override: no
- Strict reply: no
- Classified as: conversation-mode question via `simple_question_mode` (`why` + `?`), with `subtarget = titan formatting`

---

## Diagnostic — Plain-answer quality review (incoming brief + assistant reply)

Date: 2026-04-21  
Type: Design / diagnostic review only (no code changes in that exchange).

Below: the **incoming brief** as provided in-session (user indicated this may reflect or accompany content from ChatGPT), followed by the **assistant reply** verbatim in substance (markdown structure preserved for readability).

### Incoming brief (user / ChatGPT-oriented message)

Project name: AI Agent

PLAIN-ANSWER QUALITY REVIEW  
DESIGN / DIAGNOSTIC REVIEW ONLY — DO NOT IMPLEMENT YET

Current state:

Recent fixes improved behavior significantly.

Live results now:

- "Can you answer that normally?" -> "Sure! What would you like to know?"
- "Answer that normally." -> "What would you like to know?"
- "Talk normally." -> "What would you like to know?"
- "Stop using that format." -> "Understood. I'll adjust my responses accordingly."

Assessment:  
This is much better than before.  
The plain-answer override is working.  
Responses are now plain prose and no longer leaking structured formats.

However:  
The system still tends to collapse several plain-answer override inputs into the same generic fallback:

- "What would you like to know?"

So the problem is no longer formatting failure.  
The remaining issue is conversational sharpness / specificity.

GOAL:  
Review whether there is one more SMALL, SAFE refinement that would make these responses feel more natural, specific, and less repetitive — without reopening broader routing or formatting problems.

QUESTIONS FOR REVIEW:

1) Do you agree with this assessment?  
- The system is no longer "broken" in the earlier sense  
- The remaining issue is mostly generic reply repetition / lack of specificity

2) Based on current prompt behavior, what is the SINGLE safest next refinement?  
Not a broad rewrite.  
Not a new system.  
Only a narrow improvement if justified.

3) Would it be safe to make plain-answer override replies slightly more intent-specific?  
Examples of desired direction:  
- "Can you answer that normally?" -> "Yes. I'll keep it plain."  
- "Answer that normally." -> "Alright. I'll answer directly."  
- "Talk normally." -> "Got it. I'll keep it natural."  
- "Stop using that format." -> "Understood. I'll stop using it."

4) If yes:  
What is the SMALLEST way to steer that behavior?  
Choose only one:  
- tighter wording in INTERACTION_01  
- tiny plain-answer micro-guidance  
- tiny banned generic fallback phrase guidance  
- something else

5) What are the risks?  
Especially:  
- making responses too scripted  
- breaking helpfulness  
- causing regressions in normal conversation mode  
- overfitting to a few example phrases

6) Would you recommend:  
A) stop here because behavior is now good enough  
B) do one final micro-refinement for specificity  
C) something else

OUTPUT FORMAT:

1. overall assessment  
2. safest next move  
3. risks  
4. recommended option (A/B/C)  
5. if B, exact minimal change idea  
6. no code changes

---

### Assistant reply (Cursor / design review)

#### 1. Overall assessment

Yes, I agree with your assessment.

- **Earlier failure mode (structured leakage)** is largely addressed: plain-answer override plus conversation / meta-format work means the system is **no longer “broken”** in the sense of forcing Known/Missing/Conclusion or rigid headers for these inputs.
- What you are seeing now—**plain prose but repetitive, low-specificity lines** like “What would you like to know?”—is a **different class of problem**: under-specified *style* in the model’s default for “short + helpful + conversational,” not a routing/format bug.

So: **healthier system**, **residual issue = conversational sharpness and repetition**, not format integrity.

---

#### 2. Safest next move (single, narrow)

The **single safest** next step—if you want any change at all—is **a tiny addition only inside the existing PLAIN ANSWER OVERRIDE (narrow) block** in INTERACTION-01 (not global conversation mode, not routing, not reasoning).

Purpose of that addition: **tie the reply to what they literally asked for** (plain answer / talk normally / stop that format) in **one short sentence**, and **discourage the generic inventory question** as the *whole* reply for this slice only.

That stays aligned with what already works (override is already a narrow silo) and avoids reopening routing or global INTERACTION-01 behavior.

---

#### 3. Risks

| Risk | Why it matters |
|------|----------------|
| **Too scripted** | Hard “say X for phrase Y” rules or long examples can make Joshua sound like a template. |
| **Breaking helpfulness** | If you over-restrict questions, users who *do* need a clarifier after “answer normally” might get a dead-end. Mitigation: allow a clarifier **only** when the user’s message is genuinely ambiguous—not for these four clear meta-requests. |
| **Regression in normal conversation** | Any change **outside** the plain-override block increases blast radius; global “never ask X” can harm normal chat. |
| **Overfitting** | Tuning to four English phrases can miss variants (“plain English please”) unless wording stays **principle-based** (“reflect their wording briefly”) not example-list-based. |

---

#### 4. Recommended option (A / B / C)

**B) One final micro-refinement for specificity** — **if** you care about polish beyond “good enough.” The behavior is already acceptable for production sanity; this would be **quality-of-life**, not stability.

**A) Stop here** is also reasonable if your priority is **zero regression risk** and you accept occasional generic follow-ups.

I would **not** pick a vague “C” unless you later add **telemetry** or **user preference**—that’s a different scope than “one small safe refinement.”

---

#### 5. If B: exact minimal change idea (no code)

**Concept only:** In the **PLAIN ANSWER OVERRIDE (narrow)** appendix (same place you already inject override rules), add **1–2 bullets**, not a paragraph:

- **Mirror intent in one sentence:** e.g. acknowledge *plain / direct / natural / dropping that format* in words that echo theirs (not a fixed script—**principle**: “name what they asked you to change”).
- **Do not end with a generic open-ended prompt** as the entire message for this override class—e.g. avoid making **“What would you like to know?”** (or the same idea) the **whole** reply when they already stated a clear meta-request.

Optionally add **one** negative example in the prompt (“Don’t only reply with a generic ‘what would you like…’”) **without** a long menu of banned phrases—keeps it from feeling like a brittle ban-list.

That is **tighter wording / tiny micro-guidance confined to the override block**—not a new system, not routing, not a broad INTERACTION-01 rewrite.

---

#### 6. No code changes

Confirmed: **design/diagnostic review only** — no implementation in that exchange.

---

## Diagnostic — Model upgrade planning (incoming brief + assistant reply)

Date: 2026-04-21  
Type: Read-only architecture / planning analysis (no code changes in that exchange).

### Incoming brief (user / ChatGPT-oriented message)

# READ-ONLY INSTRUCTION — MODEL UPGRADE PLANNING (NO CHANGES)

**Prepared by Jessy and ChatGPT**

---

## IMPORTANT — DO NOT MODIFY ANY CODE

Cursor, your role for this step is:

* Do NOT edit files
* Do NOT refactor anything
* Do NOT “improve” or “optimize”
* Do NOT suggest implementation yet

You are in **READ + ANALYZE MODE ONLY**

---

## CURRENT CONTEXT

The agent (**Joshua**) is now:

* Behavior-stable
* Routing is correct
* Output formatting is controlled
* No structural leaks

The **behavior layer is LOCKED**

We are **NOT touching it**

---

## WHAT WE ARE ABOUT TO DO

We are preparing a **model-layer upgrade only**

Current state:

* One OpenAI API key already connected (baseline LLM)

New plan:

* Introduce a **second OpenAI API key**
* This key will power a **higher-quality reasoning model (“brain”)**

---

## GOAL

We want to evolve Joshua from:

* Controlled but basic reasoning

To:

* Strong reasoning
* Better phrasing
* More natural responses

**WITHOUT** breaking behavior stability

---

## ARCHITECTURE QUESTION (THIS IS YOUR TASK)

We want your analysis on the **best way to introduce the second key + model**

Specifically:

### 1. Key Strategy

* Should we:
  * Replace the existing key?
  * OR run **dual-key setup** (baseline + brain)?

### 2. Model Routing

* Should the system:
  * Always use the “brain” model?
  * OR selectively route (simple vs complex tasks)?

### 3. Integration Point

* Where is the safest place to inject this:
  * `core/llm.py`?
  * inside `ask_ai(...)`?
  * or a wrapper layer?

### 4. Risk Analysis

* What could break:
  * latency
  * cost
  * behavior drift
  * formatting regressions

### 5. Recommended Approach

* Give a **clear, minimal, safe plan**
* No overengineering
* Respect current architecture

---

## CRITICAL CONSTRAINT

You must respect:

> Behavior layer = LOCKED  
> Model layer = ONLY target

---

## SUCCESS CONDITION

Your answer should give us:

* A clean architecture decision
* A safe integration path
* Zero risk to current stability

---

## THINK LIKE THIS

You are not coding.

You are:

* reviewing the system
* protecting stability
* designing a safe upgrade path

---

## YOUR OUTPUT

Provide:

* Clear recommendation
* Short reasoning
* No code yet

---

**End of instruction — awaiting your analysis**

---

### Assistant reply (Cursor / read-only analysis)

**Summary recommendation:** Use a **dual-key** setup (keep the current key as default / fallback), add **second env-backed key + model name (+ optional max tokens)** in `config/settings.py`, and make **`core/llm.py` the single choke point** where `ask_ai` (or a tiny helper it calls) chooses which client + model to use. **Do not** put routing logic in `services/prompt_builder.py` (behavior layer). Roll out **selective** use of the “brain” model behind a **simple policy**, or a temporary **env-only** “all traffic on brain” switch for soak testing—not “always brain” on day one.

---

#### 1) Key strategy — replace vs dual-key

**Prefer dual-key**, not replacing the existing key.

- **Replace:** simple, but you lose a cheap baseline, harder A/B and rollback; other code paths using `OPENAI_API_KEY` (e.g. `memory/extractors/run_extractor.py`) need an explicit decision.
- **Dual-key:** matches baseline + brain; **fallback** if brain key unset; predictable cost for chatty traffic.

Keep **`OPENAI_API_KEY`** as today’s contract; add a **separate** variable for the brain (e.g. `OPENAI_BRAIN_API_KEY` + `OPENAI_BRAIN_MODEL`) so nothing changes until routing is wired.

---

#### 2) Model routing — always brain vs selective

**Prefer selective (or phased: env switch → selective), not “always brain” on first ship.**

- **Always brain:** simplest code path, but **highest** cost/latency and **highest** “capable model ignores small prompt constraints” drift risk—behavior is locked in *text*, not in model weights.
- **Selective:** route only turns that benefit most (e.g. post-fetch synthesis, long answers); keep short / cheap paths on baseline if desired.

**Practical compromise:** ship **one global env** first (all Joshua `ask_ai` calls use brain) to validate quality; then narrow to selective using **one** policy function **outside** `prompt_builder` (e.g. only `playground.py` or `core/llm.py`).

---

#### 3) Integration point

Current stack is already centralized:

- `config/settings.py` — `get_openai_api_key()`, `get_openai_model_name()`, `get_openai_max_tokens()`
- `core/llm.py` — `_build_client()`, `ask_ai(...)` → `client.chat.completions.create(...)`
- `playground.py` — imports `ask_ai`, calls it for main path and post-fetch

**Safest injection:** **`core/llm.py`** for which key + model, **`config/settings.py`** for getters. Optionally `ask_ai(..., llm_profile=...)` defaulting to **current behavior**.

**Avoid:** scattering `OpenAI(...)` across the repo.

**Note:** `memory/extractors/run_extractor.py` uses `OPENAI_API_KEY` directly—decide explicitly whether extraction stays on **baseline** (recommended for cost/stability).

---

#### 4) Risk analysis

| Risk | Notes |
|------|--------|
| **Latency** | Brain models often slower; **two** `ask_ai` paths (e.g. fetch) double impact—consider tiering only second pass or only main chat. |
| **Cost** | Selective routing is the main mitigation. |
| **Behavior drift** | Stronger models can be **more** creative about format despite prompts—soak test same regression prompts after any model change. |
| **Formatting regressions** | Usually model non-compliance; mitigate with **unchanged** system prompts and **same** tests. |
| **Ops / secrets** | Two keys in `.env`; `llm_preflight_check` should reflect modes you care about. |

---

#### 5) Minimal safe plan (behavior locked, model only)

1. **Config (conceptually):** second key + second model (+ optional max tokens); baseline vars unchanged.  
2. **`core/llm.py`:** one place builds client(s) and selects model; `ask_ai` stays the public API.  
3. **Rollout:** env-driven “all Joshua LLM calls use brain” vs baseline to validate **without** new task taxonomy.  
4. **Then** selective routing from **one** non–`prompt_builder` layer, still no prompt-string routing coupling.  
5. **Preflight:** misconfiguration fails loudly.  
6. **Regression:** re-run existing `ask_ai`-exercising tests after model-layer changes only.

---

#### 6) “Zero risk”

No architecture can guarantee **zero** risk: **any** model swap can change compliance with the same prompt. This plan minimizes **structural** risk: single integration point, dual-key fallback, no prompt-layer coupling, phased rollout.

---

**Bottom line:** **Dual-key + settings getters + `core/llm.py` as the only routing surface for Joshua’s chat completions**, with **selective (or env-gated) brain use**—not replacing the first key blindly, and not always-on brain until soak evidence exists. **No code** was written in that exchange, per instruction.

---

## Diagnostic — Light task mode still leaking into heavy structure (incoming brief + analysis)

Date: 2026-04-21  
Type: Analysis only (no code changes in that exchange).

### Incoming brief (user / ChatGPT-oriented message)

ANALYSIS REQUEST — LIGHT TASK MODE STILL LEAKING INTO HEAVY STRUCTURE

**Prepared by Jessy and ChatGPT**

---

## IMPORTANT

* Do NOT implement anything yet
* Do NOT modify code
* Do NOT propose a full refactor

You are in **ANALYSIS MODE ONLY**

---

## CONTEXT

We recently implemented:

* Conversation vs structure fix → working
* Light task mode → partially working

Goal:

* Simple “next step” questions should produce **light responses**
* Heavy structured output should only appear when truly needed

---

## TEST RESULTS (REAL OUTPUT)

### Case 1 — PASS (light mode works)

**Input:**  
"What should I do next?"

**Output:**  
(Add or enhance a specific piece of the action layer…)  
→ Natural response, no heavy structure ✔

---

### Case 2 — FAIL (still heavy structure)

**Input:**  
"That’s better, what should I do next?"

**Output:**

Answer  
Add or enhance a specific piece...

Current State  
Focus: I prefer testing  
Stage: Phase 4 action-layer refinement  
Action type: build  

Next Step  
Choose one testing improvement...

→ This is WRONG (too heavy for this input)

---

### Case 3 — PASS (complex task)

**Input:**  
"Help me debug an API failure step by step"

**Output:**  
Step-by-step natural explanation ✔

---

## PROBLEM

Light task mode correctly handles:

* short direct next-step questions

But fails when:

* a short conversational prefix is added
* example: “That’s better, what should I do next?”

This should still be **light task**, but it falls into **heavy structured mode**

---

## TASK

Analyze:

### 1. Why this is happening

* Which condition or heuristic is causing the fallback to heavy structure?

### 2. What is the minimal fix

* Without breaking:

  * conversation mode (already working)
  * light task mode (already partially working)
  * complex task handling

### 3. What is the safest adjustment

* Prefer extending light task detection
* Avoid adding complexity or full reclassification systems

---

## CONSTRAINT

We want:

> Mixed casual + simple next-step = LIGHT

NOT:

> Mixed input = heavy structure

---

## OUTPUT

Return:

1. root cause (clear and precise)
2. minimal fix approach (no code yet)
3. why it is safe
4. what edge cases to watch

---

End goal:  
Light task mode behaves naturally even with casual conversational prefixes.

---

### Assistant reply (Cursor / analysis)

#### 1. Root cause (clear and precise)

**Light task mode is intentionally turned off whenever the raw user message contains a comma.**

In `user_input_needs_light_task_mode`, there is a guard equivalent to: **if `","` appears in the user input → not light task.**

The string **“That’s better, what should I do next?”** contains a comma, so **`light_task_mode` is forced `False`**. The line still matches **task-oriented** markers (`what should i do next`, etc.), so `build_messages` falls through to the **heavy** branch: **`elif task_oriented_input`** → **OPEN CONVERSATION MODE** with **`OUTPUT FORMAT RULES`** and **Answer / Current state / Next step**.

So this is **not** a mysterious model bug; it is **exactly that comma heuristic** (added so comma‑joined lines would not be classified as light, which at the time matched a test that expected **heavy** structure for that example).

---

#### 2. Minimal fix approach (no code yet)

**Prefer narrowing or removing the blanket comma veto**, not adding a new classifier system.

Concrete directions (pick one; all are small):

- **A (smallest):** Drop the **“any comma ⇒ not light”** rule and **re-point the regression test** that currently expects heavy output for **“That’s better, what should I do next?”** to a case that should **stay** heavy (e.g. same prefix + **`implement` / `.py` / debug / step‑by‑step`** in the second clause).

- **B (still small):** Replace the blanket comma rule with **“comma + heavy hint anywhere ⇒ not light”**; allow comma when the **tail after the last comma** is still a **pure light next-step phrase** (no heavy substrings).

- **C (slightly more logic):** If the line matches a **light next-step phrase** and **no heavy hints** in the **whole** message, treat as **light**, even with a short acknowledgment prefix before a comma (optionally require the tail after the comma to contain the light phrase).

All preserve **conversation mode** as-is (that path is separate) and **complex / heavy** behavior whenever **heavy markers** are present.

---

#### 3. Why it is safe

- **Single choke point:** only **`user_input_needs_light_task_mode`** (and the one test that encoded the old assumption) need to align with the new product rule.
- **Heavy path stays:** anything with **implement / debug / .py / traceback / …** (existing **heavy_hints**) still **fails** light classification and keeps **OPEN CONVERSATION + structure**.
- **Pure conversation** stays on **`conversation_mode`** first; no rework of the big `elif` ladder beyond light detection.

---

#### 4. Edge cases to watch

| Case | Risk |
|------|------|
| **“Sounds good, what should I do next?”** | Same comma pattern; should become **light** if you relax the comma rule—confirm that’s desired. |
| **“OK, what should I do next to implement X?”** | Must stay **heavy**; **`implement`** (and friends) must keep it out of light mode. |
| **Curly vs straight apostrophe** in “That’s” | Usually normalized; **comma** is the real switch today, not the apostrophe. |
| **Two tasks in one line** | Comma‑joined **two** concrete asks—may look “light + light”; use **heavy hints** or length to avoid mis‑lighting. |
| **Tests / docs** | Any test that **asserted** heavy structure **specifically** for the comma + next-step example must be **updated** in the same change, or it will fight the new rule. |

---

**Bottom line:** the leak is **by design of the current light-task heuristic (comma exclusion)**, not random behavior. **Relaxing that rule (and adjusting the one test that locked the old behavior)** is the minimal way to get **mixed casual + simple next-step → LIGHT** without a reclassification system.

---

## ANALYSIS REQUEST — SOURCE OF “PHASE 4 ACTION-LAYER REFINEMENT” + TIMING FOR MEMORY INGESTION

**Prepared by Jesse and ChatGPT (Chad GPT)** — forwarded for Cursor diagnostics.

### IMPORTANT (original constraints)

* Do NOT implement anything yet
* Do NOT modify code
* Analysis only

### PROBLEM

Joshua repeatedly produces answers like:

* “since you're working on Phase 4 action-layer refinement”
* “within the action layer of your testing framework”

This happens even when the user does NOT explicitly mention this context.

### GOAL

Understand:

1. **Where this is coming from**
2. **Why it keeps appearing**
3. **Whether it is correct behavior or a leak**

### QUESTIONS (summary)

1. Source of the repeated context — system prompt (`prompt_builder`)? runtime context assembly? residual chat? test scaffolding? hidden memory?
2. Why it persists on generic questions (“What should I do next?”).
3. Desirable behavior: anchor to assumed project state vs only when grounded and relevant.
4. Minimal fix direction (no code): stop irrelevant injection; preserve useful context when needed.
5. Strategic timing: finalize **knowledge ingestion + extraction** (atomic memory) **now** vs first **stabilize behavior and context control** (eliminate leakage / unwanted anchoring).

### OUTPUT REQUESTED

1. Root cause of the repeated “Phase 4” context  
2. Why it persists  
3. Correct or bug  
4. Minimal fix direction  
5. Recommendation on timing for memory ingestion pipeline  

**End goal:** Know whether Joshua uses valid context or leaks internal/project state before proceeding to memory ingestion.

---

### Assistant reply (Cursor / analysis) — Phase 4 & action-layer anchoring

#### 1. Root cause of the repeated “Phase 4” context

**Primary source: persisted agent state + mandatory system prompt header (by design), not a separate “memory leak.”**

* **`playground.py`** — `DEFAULT_STATE` sets **`"stage": "Phase 4 action-layer refinement"`** and **`"focus": "ai-agent project"`**. Values merge with **`memory/current_state.json`** via `load_state()` / `get_current_focus()` / `get_current_stage()`.
* **`services/prompt_builder.py`** — `build_dynamic_prompt` **always** prefixes the system message with **`Current focus:`**, **`Current stage:`**, **`Current action type:`** (e.g. “You are a focused AI agent…” block).
* **Static IMPORTANT rules** — instruct the model to **anchor “what to do next” to focus and stage** and **not to claim lack of context** when focus/stage exist; that **encourages** natural-language reuse of those labels.
* **Secondary** — journal, memory blocks, action guidance, forced next-step builders can repeat focus/stage; the headline string is already fixed by **header + rules** even with **empty extracted memory**.

So: **not** mainly residual transcript; **not** primarily extractor output — it is **live `current_state` + prompt assembly every turn**.

#### 2. Why it persists

* **State** often unchanged unless **`set stage:`** / **`set focus:`** (or tooling) updates **`memory/current_state.json`** — same string across sessions.
* **Instructions** treat focus/stage as authoritative and bias generic next-step questions toward **grounding** in them — stronger models (e.g. gpt‑4o) **paraphrase** (“since you’re in Phase 4…”) even when the user never said those words.
* **LIGHT TASK** changes reduced heavy **Answer / Current state / Next step** *templates* in the rules slice but **did not remove** the **global** `Current focus` / `Current stage` lines at the **top** of the system prompt — the model still sees Phase 4 on every call.

#### 3. Correct behavior or bug?

* **Technically correct** for today’s spec: a **stateful agent** with **always-on** focus/stage in system text and rules favoring anchoring.
* **Product-wise** it can feel like **over-anchoring** or a “leak” if the user wanted context-free answers — then it is **undesirable emphasis**, not a random implementation bug.

#### 4. Minimal fix direction (no code in this doc)

Pick one narrow layer:

* **Prompt-only:** For LIGHT / conversation, add one rule: **do not mention focus/stage/action type in the reply unless the user asked about state or used those terms** — keep header for internal grounding if desired.
* **Header gating:** For light/casual paths, **omit or shorten** opening `Current focus/stage` lines (or move to internal-only context — product decision).
* **State hygiene:** If Phase 4 is **stale**, update **`current_state.json`** / commands so labels match reality.

**Memory ingestion alone** will not remove “Phase 4” if the **prompt header + rules** still inject it every turn.

#### 5. Recommendation — memory ingestion pipeline timing

* **Ingestion / atomic memory** improves **long-term recall** (goals, preferences, facts); it **does not replace** the **always-on focus/stage channel** unless **state writes** and **prompt citation policy** change too.
* **Suggested order:** (1) Decide **when the model should verbally surface** focus/stage (prompt / light-path policy). (2) Keep **behavior/routing** stable while adjusting **context surfacing**. (3) **Then** add ingestion so memory **adds** grounded facts **without** stacking more harness jargon on the same header.

**Bottom line:** the repeated “Phase 4” / action-layer framing is **mostly default/live state + system prompt + anchoring rules**, not ghost context from extraction. **Tighten surfacing policy or state** before expecting **ingestion** to fix this specific annoyance.

---

## DIAGNOSIS — LIGHT TASK ANSWERS ARE TOO GENERIC

**Prepared by Jessy and ChatGPT** (request captured from chat; “PTC” read as product/ChatGPT-side brief.)

### MODE (original constraints)

* Analysis only  
* Do NOT implement  
* Do NOT modify code  

### CURRENT STATE (from brief)

We fixed:

* Over-structured output  
* Context overexposure (Phase 4 / testing framework references)  

The assistant now responds naturally.

### NEW PROBLEM

Light task answers (e.g. “What should I do next?”) are:

* grammatically correct  
* clean  
* but **too generic and low-value**  

**Example answer shapes called out:** “Focus on refining a specific element…”, “Choose something small and manageable…”, “Improve functionality or performance…” — vague, not actionable.

### GOAL

Understand why the model avoids giving **one concrete next action** or a **specific suggestion**.

### QUESTIONS

1. **Root cause** — Why does light task mode default to generic guidance? Prompt wording? Lack of concrete context? Safety rules? Fallback behavior?  
2. **Decision pattern** — What rule is the model following when it chooses generic advice vs concrete suggestion?  
3. **Minimal improvement strategy** — Without adding structure or complexity: smallest change to encourage **one concrete action** OR **one clarifying question** if context is insufficient.  
4. **Constraint** — Do NOT want: heavy structure back, fake specificity, hallucinated details.

### OUTPUT REQUESTED

1. root cause  
2. why model chooses generic phrasing  
3. minimal fix direction  
4. risks / edge cases  

**End goal:** Light task answers become useful, not just clean.

---

### Assistant reply (Cursor / analysis) — light task generic answers

#### 1. Root cause

**The light path removes the machinery that used to force concreteness, and stacks rules that make “abstract but safe” the easiest compliance.**

* **No forced next step in the light-task prompt slice** — `build_messages` may still compute `forced_next_step` / `forced_answer_line`, but the **LIGHT TASK MODE** `answer_and_step_rules` branch does **not** inject them. Unlike **strict / structured** paths (SPECIFICITY RULE, verbatim Next step / Answer), the model only gets the usual header, static rules, `action_guidance`, optional memory/journal, and the short light block. There is **no single anchored artifact** (file, command, harness step) the model is instructed to use.

* **Context surfacing (light/conversation)** tells the model **not** to mention focus, stage, action type, phase names, or project labels from the header, and to infer “**silently**” without “narrating harness labels.” That reduces Phase-4-style leakage but also **removes obvious lexical hooks** for sounding specific—so answers drift toward **domain-neutral coaching**.

* **LIGHT TASK MODE** text frames the user ask as “**in generic terms**” and pairs with **LATENCY-05** brevity (one short paragraph / tight bullets). That nudges toward **short, non-committal** guidance.

* **Tension:** static IMPORTANT rules still say anchor / ground in project; surfacing says do not say those labels out loud; light rules do not supply a mandated concrete step. The model resolves that with **vague, confident-sounding** advice that avoids invented file names and forbidden labels.

* **Thin context:** empty or trimmed **memory / journal** gives less to ground on **without** naming the header.

**Safety rules** are not the primary driver; **prompt shape + surfacing + no injected step** are.

#### 2. Why the model chooses generic phrasing

A rational compliance order:

1. Satisfy “natural chat,” no Answer/Current state/Next step, no pasted metadata.  
2. Satisfy surfacing: do not name phase/focus/stage/action-type strings from the header.  
3. Avoid inventing repo-specific details (hallucination risk).  
4. Stay within LATENCY-05 length.

→ **Default: generic coaching** (high confidence, low falsifiable content). Concrete steps appear mainly when the model risks naming **memory/journal** content or “standard” project paths—and that material may be absent.

#### 3. Minimal fix direction (conceptual; not implemented in this doc)

* Add **2–3 bullets only inside LIGHT TASK MODE**: deliver **exactly one** executable micro-step when grounded in supplied context (or a **standard** documented path); **or** **one** narrow clarifying question if insufficient—no menus, no invented paths.

* **Narrow surfacing wording** so “do not recite harness labels” does **not** discourage **concrete artifacts** (real paths/commands) that are not the same as repeating **Current stage** verbatim.

* **Optional:** one internal non-header hint line (same *source* as today’s forced next step) as “do not mirror as a template”—gives a single anchor without restoring heavy structure; must be guarded against fake specificity.

#### 4. Risks / edge cases

| Risk | Note |
|------|------|
| Fake specificity | “Name a file” without context increases wrong paths. |
| Structure creep | Mandatory sections or mirrored Next step fields re-heavy output. |
| Conflict with user-purpose guidance | Long blocks reference Next step-style fields while light forbids headers—model can be pulled two ways. |
| Over-specific for novices | Sometimes one clarifying question is better than a command. |
| Latency-trimmed blocks | Less memory/journal text → more generic replies. |

**Bottom line:** Light answers are clean because the prompt **optimized for de-templating and de-labeling**; usefulness needs a **small, light-only** instruction that **concrete steps are allowed when grounded**, and/or **permission for one sharp question**—without restoring full structured mode.

---

## DIAGNOSIS — LIGHT TASK STILL LOSES TO IMPLEMENT / UNDEFINED-TARGET PATH

**Prepared by Jessy and ChatGPT** (request from chat; filed under Jessy / JC diagnostics.)

### IMPORTANT (original constraints)

* Analysis only  
* Do not implement yet  
* Do not refactor  

### OBSERVED RESULTS (from brief)

**Improved**

* “That’s better, what should I do next?” → one concrete action  
* “Alright, what should I try?” → one concrete action  

**Still weak**

* “What should I do next?” still starts with generic coaching (“Focus on refining…”) before the action.

**Failed**

* “What should I do next to implement X?” should have produced one clarifying question because X is undefined.  
* Instead: guessed action, then **Current state** / **Next step** style structured output.

### QUESTIONS (from brief)

1. Why does “implement X” bypass the new light-task rule requiring one clarifying question when context is insufficient?  
2. Which branch or override takes precedence?  
3. Minimal fix so undefined-target prompts (“What should I do next to implement X?”, “How should I build Y?” when Y is undefined) produce one precise clarifying question instead of guessed advice or structured fallback?  
4. Separately: how to tighten light-task phrasing so it starts directly with the action, not generic coaching lead-ins like “Focus on…”?

### GOAL (from brief)

* One direct action when grounded  
* One clarifying question when the target is undefined  
* No Current state / Next step leakage  
* No coaching fluff  

### RETURN REQUESTED

1. root cause  
2. minimal fix direction  
3. why it is safe  
4. edge cases to watch  

---

### Assistant reply (Cursor / analysis) — implement path vs light task; undefined target

#### 1. Root cause

**A) “What should I do next to implement X?” never enters LIGHT TASK MODE — by design in code, not a model “bypass.”**

`user_input_needs_light_task_mode` returns `False` if any **`heavy_hints`** substring matches normalized input. That list includes **`"implement "`** (with trailing space), so lines like *what should i do next to implement x?* match and **light task (including DECISIVENESS / one-question-when-thin rules) is not applied.**

**B) After light is off, routing uses the task-oriented structured path.**

The line still satisfies **`task_oriented_input`** (markers include **what should i do next** and **implement**). **`uses_strict_forced_reply`** is typically **false** for this variant because **`is_generic_next_step_question`** only returns true for a **small exact string set** — not longer “…to implement X?” forms — so the flow commonly lands on **`elif task_oriented_input` → OPEN CONVERSATION MODE** with **OUTPUT FORMAT RULES** requiring **Answer:** / **Current state:** / **Next step:**. That is **intended template behavior** for that branch, not accidental “leakage.”

**C) Forced next-step / answer machinery still runs.**

`build_specific_next_step` / `build_answer_line` are computed regardless of light task; on the open-task branch the model gets **concrete next-step pressure** plus the three-section template, which favors **guessed** repo steps even when **X** is undefined in the user text.

**D) Bare “What should I do next?” + coaching opener.**

That input **does** use LIGHT TASK + DECISIVENESS + context surfacing. Coaching lead-ins are **not** explicitly banned; only **vague-only** coaching is called out. **Static IMPORTANT** rules still bias toward confident project-grounded tone, so the model often **preambles** then gives the action. **Gap:** no **“sentence one = imperative or question only”** rule in the light slice.

#### 2. Minimal fix direction

**Undefined implement / build (implement X, build Y undefined):**

* **Routing (tightest lever):** Add a **narrow** condition: next-step intent **plus** implement/build **plus** target **clearly unspecified** in context → use a path with **light-style** natural rules (one question or one grounded action), **or** a small **clarify-first** slice — **without** the open-conversation three-section template for that slice — **or** narrow **`heavy_hints`** only for a well-bounded pattern (higher mis-route risk).

* **Prompt-only on OPEN CONVERSATION:** Add bullets when the build target is not in supplied context: **Answer** = one clarifying question — but **Current state / Next step** still exist unless that template is **relaxed** for this subcase (product tradeoff vs “no leakage” goal).

**Coaching fluff on bare light task:**

* **One** LIGHT-only line: **open** with the action or the question; **no** generic preamble (“Focus on…”, “Consider…”) unless functionally necessary.

#### 3. Why a minimal fix can be safe

* **Scoped** undefined-target detection preserves real implementation asks with real anchors (`implement parser.py`, prior thread context).  
* **Clarify-first** aligns with anti-hallucination when **X/Y** are not in context.  
* **Preamble rule** in light only does not reintroduce **Answer / Current state / Next step**.

#### 4. Edge cases to watch

| Case | Note |
|------|------|
| Short real names (“implement memory”) | Placeholder heuristics can mis-route. |
| Pronouns (“implement it”) | Ambiguous referent → may default to one question. |
| Open conversation template | True “no Current state / Next step” requires **changing** that branch’s format rules, not light task alone. |
| Exact generic “what should i do next?” | **`uses_strict_forced_reply`** / strict path can still differ from **light** — tune both if comparing “no fluff.” |
| **“build Y”** | **`build `** is also in **`heavy_hints`**; same routing story as **implement**. |

**Bottom line:** **Implement X** does not bypass light-task rules — **`heavy_hints`** **excludes** it from light task, then **`task_oriented_input`** yields **OPEN CONVERSATION + template + forced steps**, which encourages guesses and **mandates** labeled sections. **Bare light** allows coaching preambles because **DECISIVENESS** does not yet require **leading with** the action or question.
