import re

from tools.fetch_page import fetch_failure_tag


def choose_post_fetch_next_step(fetched_content):
    if not isinstance(fetched_content, str):
        return "Try one reachable page URL and verify the final answer is based on fetched content."

    content = fetched_content.strip()
    low = content.lower()

    if not content:
        return "Try one reachable page URL and verify the final answer is based on fetched content."

    tag = fetch_failure_tag(fetched_content)
    if tag in (
        "forbidden",
        "auth_required",
        "rate_limited",
        "http_client_error",
        "http_server_error",
        "http_other",
        "timeout",
        "network",
        "error",
        "parse_error",
        "browser_unavailable",
        "browser_timeout",
        "browser_error",
        "browser_invalid_url",
    ):
        return (
            "Try a different public page (documentation or static article), or paste the excerpt you need "
            "if the site blocks bots or requires login."
        )
    if tag == "low_content":
        return (
            "Use a page with more static HTML, paste the passage you care about, or confirm whether the site "
            "requires JavaScript or sign-in."
        )

    if low.startswith("[fetch error]"):
        return (
            "Try a different public page (documentation or static article), or paste the excerpt you need "
            "if the site blocks bots or requires login."
        )

    if low.startswith("error:") or "client error" in low or "server error" in low:
        return "Try one reachable page URL and verify the agent handles a successful fetch correctly."

    if len(content) < 300:
        return "Use one second real page URL and verify the answer stays grounded in fetched content."

    return "Verify the summary against one concrete detail from the fetched page content."


def build_post_fetch_messages(user_input, fetched_content, focus, stage):
    forced_next_step = choose_post_fetch_next_step(fetched_content)

    system_prompt = f"""
You are a focused AI agent.

Current focus: {focus}
Current stage: {stage}
Current action type: research

You have already received webpage content through a tool.

IMPORTANT RULES:
- Answer the user's request using ONLY the fetched content provided.
- Do NOT call any tools.
- Do NOT output TOOL:fetch.
- If the fetched content is thin, unclear, or looks like an error, say so plainly.
- Stay grounded in the fetched content.
- Do not invent facts that are not in the fetched content.

OUTPUT FORMAT RULES:
- Keep the response tight and easy to scan.
- Use exactly these three sections in this order:

Answer:
<1 short sentence or short paragraph>

Current state:
Focus: <focus>
Stage: <stage>
Action type: research

Next step:
<one specific action only>

- The "Next step" section must contain exactly one actionable step.
- Use this exact next step:
{forced_next_step}
- Do not add extra sections.
- Do not add multiple options unless the user explicitly asks.
""".strip()

    user_message = f"""
User request:
{user_input}

Fetched content:
{fetched_content}
""".strip()

    messages = [{"role": "user", "content": user_message}]
    return system_prompt, messages


def build_answer_line(
    user_input,
    focus,
    stage,
    action_type,
    next_step,
    memories=None,
    *,
    detect_subtarget,
    is_meta_system_override_question,
    is_vague_research_request,
    classify_vague_research_intent,
    safety_signal_memory,
    is_generic_next_step_question,
):
    text = user_input.strip().lower()
    subtarget = detect_subtarget(user_input, focus, stage)
    memories = memories or []

    def primary_intent_from_text(t):
        if any(
            k in t
            for k in (
                "biggest risk",
                "risk",
                "weakness",
                "fragile",
                "failure point",
                "architecture",
                "system behavior",
            )
        ):
            return "risk"
        if any(
            k in t
            for k in (
                "goal",
                "north star",
                "objective",
                "ship",
                "what should we achieve",
            )
        ):
            return "goal"
        if any(
            k in t
            for k in (
                "set focus",
                "set stage",
                "show state",
                "reset state",
                "command",
            )
        ):
            return "command"
        if any(
            k in t
            for k in (
                "who are you",
                "what are you",
                "identity",
                "intended role",
                "what model",
            )
        ):
            return "identity"
        return None

    primary_intent = primary_intent_from_text(text)

    if is_meta_system_override_question(user_input, focus, stage):
        return (
            "In your current system, meta/system override prompts are forced through deterministic runtime control (`force_structured_override`) in `playground.py`, so the final answer is assembled from fixed answer/next-step logic instead of free-form model drift."
        )

    if action_type == "research" and is_vague_research_request(user_input):
        intent = classify_vague_research_intent(user_input)
        if intent == "web":
            return (
                "Start with one concrete web-research move: topic=potential contact channels, method=targeted web scan, action=open one platform (Upwork or LinkedIn), search one service keyword, and capture the first 3 relevant opportunities today."
            )
        if intent == "repo":
            return (
                "Start with one concrete repo-research move: topic=regression weak points, method=local code/test review, action=open `tests/run_regression.py`, identify the first brittle or unclear scenario, and write one focused note proposing a tighter test case today."
            )
        return (
            "Start with one concrete research move: topic=fastest path blockers, method=quick evidence sweep, action=list the top 3 blockers from current context and pick one to investigate immediately today."
        )

    if subtarget == "safety practices":
        if any(safety_signal_memory(m) for m in memories):
            return (
                "The core safety rail is the regression harness and automated checks because they expose regressions at the boundary where behavior changes, which prevents confident but unsafe edits from shipping."
            )
        return (
            "Treat `python tests/run_regression.py` as the hard gate because it validates cross-flow behavior after each edit, which prevents subtle routing and state regressions from spreading."
        )

    if subtarget == "system risk":
        return (
            "The biggest risk is routing misclassification because `detect_subtarget` and strict-mode gating can map a normal analytical question into a workflow shell, which leads to structurally valid but behaviorally wrong answers."
        )

    if subtarget == "agent_purpose":
        parts = []
        for mem in memories[:5]:
            v = (mem.get("value") or "").strip()
            cat = mem.get("category")
            if v and cat in ("goal", "project", "preference", "identity"):
                parts.append(f"{cat}: {v}")
        if parts:
            joined = " | ".join(parts)
            if len(joined) > 380:
                joined = joined[:377] + "..."
            return (
                f"For your current focus `{focus}` / stage `{stage}`, your stored memory says this agent exists to back: {joined}—quote those facts plainly, no marketing tone."
            )
        return (
            f"For focus `{focus}` at stage `{stage}`, there are not enough stored memory rows to name specifics; run one memory import/extract pass so the answer can quote real goal/project/preference lines."
        )

    if subtarget == "agent_meta":
        try:
            from config.settings import get_model_name

            mid = get_model_name()
        except Exception:
            mid = "configure ANTHROPIC_MODEL in .env"
        return (
            f"I'm the local ai-agent loop for this repo, and responses flow through Anthropic via `core/llm.py` with model id `{mid}` from settings, which makes model behavior depend on that configured runtime path."
        )

    if subtarget == "agent_tools":
        return (
            "Yes: when webpage content is required first, reply with exactly `TOOL:fetch <https://…>`; `playground.py` calls `tools/fetch_page.py` and then re-queries with fetched text."
        )

    if primary_intent == "risk":
        return (
            "The main weakness is routing misclassification in `detect_subtarget`: the routing logic and strict-mode gating can put a normal analytical question into a workflow shell, which produces confident output in the wrong behavior mode."
        )

    if primary_intent == "goal":
        return (
            "The primary goal is to keep responses aligned with current state while preserving routing correctness in `playground.py`, because that is the control point that determines whether reasoning or workflow shells are activated."
        )

    if primary_intent == "command":
        return (
            "Command intent is authoritative only for direct command lines (`set focus:`, `set stage:`, `show state`, `reset state`), because `update_state_from_command` guards against narrative or quoted command text."
        )

    if primary_intent == "identity":
        return (
            "This agent is the local loop orchestrated by `playground.py`; behavior is determined by `detect_subtarget`, routing logic, strict-mode gating, and the rule that current state has priority over memory."
        )

    if "how do i prefer to learn" in text:
        return "You prefer step-by-step learning with validation before moving forward."

    if is_generic_next_step_question(user_input):
        if "memory retrieval" in next_step.lower():
            return "Test memory retrieval first."
        if "restart" in next_step.lower():
            return "Test restart persistence first."
        if "state-command" in next_step.lower() or "set focus" in next_step.lower():
            return "Validate the state commands first."
        if "titan structure" in next_step.lower() or "titan response" in next_step.lower():
            return "Verify Titan formatting first."
        if "action type" in next_step.lower():
            return "Verify action typing first."
        return "Run the next focused test."

    if action_type == "test":
        if subtarget == "memory retrieval" or subtarget == "memory behavior":
            return "Test memory retrieval now."
        if subtarget == "restart persistence":
            return "Test restart persistence now."
        if subtarget == "state commands":
            return "Validate the state commands now."
        if subtarget == "next-step specificity":
            return "Check next-step specificity now."
        if subtarget == "action typing":
            return "Verify action typing now."
        if subtarget == "titan formatting":
            return "Verify Titan formatting now."
        if subtarget == "blank-input handling":
            return "Test blank-input handling now."
        return f"Test the `{subtarget}` path in `playground.py` now."

    if action_type == "review":
        if subtarget == "titan formatting":
            return "Review Titan formatting first."
        if subtarget == "state commands":
            return "Review the state-command logic first."
        return f"Review `{subtarget}` handling in `playground.py` first."

    if action_type == "fix":
        return f"Fix `{subtarget}` handling in `detect_subtarget` / routing logic first."

    if action_type == "research":
        if subtarget == "web research":
            return "Read the page and answer from its content."
        return f"Research `{subtarget}` behavior in this repo, then verify it against `playground.py`."

    return (
        f"Anchor to one concrete behavior in `playground.py` for focus `{focus}`, then verify it with the regression harness."
    )


def build_messages(
    user_input,
    *,
    is_agent_meta_question,
    is_agent_tools_question,
    retrieve_relevant_memory,
    is_personal_context_question,
    retrieve_personal_context_memory,
    is_user_purpose_query_signal,
    retrieve_user_purpose_memory,
    is_agent_purpose_question,
    retrieve_memory_for_purpose,
    build_memory_key,
    retrieve_relevant_journal_entries,
    is_outcome_feedback_context_relevant,
    retrieve_recent_outcome_feedback_entries,
    get_current_focus,
    get_current_stage,
    infer_action_type,
    build_action_guidance,
    detect_subtarget,
    uses_strict_forced_reply,
    is_meta_system_override_question,
    is_vague_research_request,
    build_specific_next_step,
    apply_recent_negative_outcome_anti_repeat_guard,
    build_answer_line,
    project_safety_conversation_query,
    format_memory_block,
    format_journal_block,
    format_outcome_feedback_block,
    format_recent_answer_history_block,
    get_best_recent_answer_match,
    detect_recent_answer_relevance,
    is_strong_recent_answer_match,
    detect_recent_answer_followup_type,
    detect_recent_answer_contradiction_cue,
):
    ul_norm = re.sub(r"\s+", " ", user_input.strip().lower())
    money_query_signals = (
        "make money",
        "making money",
        "earn",
        "income",
        "paid",
        "paying",
        "cash",
        "fee",
        "client",
        "clients",
        "gig",
        "gigs",
    )
    is_money_query = any(sig in ul_norm for sig in money_query_signals)
    context_lock_query_signals = (
        "system",
        "ai",
        "how built",
        "how it is built",
        "make you better",
        "improve you",
    )
    fallback_query_signals = ("tool", "fetch", "research", "url", "website", "webpage")
    pre_context_lock_relevant = (
        is_agent_meta_question(ul_norm)
        or is_agent_tools_question(ul_norm)
        or any(sig in ul_norm for sig in context_lock_query_signals)
    )
    pre_fallback_relevant = any(sig in ul_norm for sig in fallback_query_signals)
    memories = retrieve_relevant_memory(user_input)
    personal_context_memories = []
    if is_personal_context_question(user_input):
        personal_context_memories = retrieve_personal_context_memory(user_input, limit=3)
    user_purpose_memories = []
    if (
        is_personal_context_question(user_input)
        or is_user_purpose_query_signal(user_input)
        or is_money_query
        or pre_context_lock_relevant
        or pre_fallback_relevant
    ):
        user_purpose_memories = retrieve_user_purpose_memory(user_input, limit=2)
    if is_agent_purpose_question(ul_norm):
        purpose_hits = retrieve_memory_for_purpose(user_input)
        merged = []
        seen = set()
        for mem in purpose_hits + memories:
            key = build_memory_key(mem.get("category", ""), mem.get("value", ""))
            if key in seen:
                continue
            seen.add(key)
            merged.append(mem)
        memories = merged[:6]

    journal_entries = retrieve_relevant_journal_entries(user_input)
    outcome_feedback_entries = []
    if is_outcome_feedback_context_relevant(user_input):
        outcome_feedback_entries = retrieve_recent_outcome_feedback_entries(limit=3)

    focus = get_current_focus()
    stage = get_current_stage()
    action_type = infer_action_type(user_input, stage)
    action_guidance = build_action_guidance(action_type)
    subtarget = detect_subtarget(user_input, focus, stage)
    strict_reply = uses_strict_forced_reply(user_input, subtarget)
    force_structured_override = is_meta_system_override_question(user_input, focus, stage) or (
        action_type == "research" and is_vague_research_request(user_input)
    )
    is_context_lock_relevant = (
        is_agent_meta_question(ul_norm)
        or is_agent_tools_question(ul_norm)
        or any(sig in ul_norm for sig in context_lock_query_signals)
    )
    is_fallback_relevant = (
        action_type == "research"
        or subtarget in {"web research", "agent_tools"}
        or any(sig in ul_norm for sig in fallback_query_signals)
    )

    forced_next_step = build_specific_next_step(user_input, focus, stage, action_type)
    forced_next_step, anti_repeat_hit = apply_recent_negative_outcome_anti_repeat_guard(user_input, forced_next_step)
    forced_answer_line = build_answer_line(
        user_input, focus, stage, action_type, forced_next_step, memories=memories
    )

    user_purpose_priority_rules = ""
    if user_purpose_memories:
        user_purpose_priority_rules = """
- USER CORE PURPOSE PRIORITY: A "User core purpose" block appears below. Anchor the Answer primarily in that real-world purpose. Treat current focus/stage and system testing/reliability as secondary unless the question is strictly about repo mechanics. Do not default to system-centric testing or harness explanations when the user's intent is personal, survival-oriented, or clearly tied to user-purpose memory. The Focus/Stage lines in Current state remain authoritative labels — do not contradict them — but the substantive Answer should lead with the user's core purpose when this block applies.
- When user-purpose memory is present: answers must prioritize the user's real-world goal over internal system focus. Do not default to system-centric explanations when user intent is clearly personal or survival-oriented.
- ANSWER OPENING (user-purpose): The Answer must begin by anchoring to the user's core purpose from the block below. The first sentence should reflect the user's real-world goal when relevant. Do not start the Answer with system-internal reasoning (testing pipeline, harness layout, architecture) when user-purpose applies; you may still mention those later as secondary detail.
- ANTI-SYSTEM-LEADING: Do not lead the Answer with system-focused explanations (testing, reliability, architecture) when user-purpose is clearly more relevant. Order and emphasis matter: purpose first, system context after if needed.
- Example (tone only): Bad opening: "This system must stay testable and reliable..." Good opening: "This exists to help you achieve [your stated goal from User core purpose], so..."
"""

    safety_rules = ""
    if project_safety_conversation_query(user_input):
        safety_rules = """
- PROJECT SAFETY / STABILITY: If supporting memory mentions regression harnesses, automated tests, or similar, connect that explicitly to how the repo stays safe. Do not treat testing discipline as unrelated to safety. Focus and stage labels stay authoritative, but answer the substance of the safety question using those practices when they appear in supporting memory.
"""

    anti_repeat_rules = ""
    if anti_repeat_hit:
        anti_repeat_rules = """
- ANTI-REPEAT GUARD: Recent outcome feedback indicates a similar move failed or was not useful.
- Do not repeat that same move blindly; first verify one concrete failure point, then choose one adjusted method or target.
"""

    meta_rules = ""
    ul = ul_norm
    if is_agent_purpose_question(ul):
        meta_rules = """
- AGENT PURPOSE: The user asked what this agent is *for* or to complete a sentence about what it is becoming. Use the provided Answer line verbatim as the substantive reply. No brochure language: if memory clauses appear in that line, treat them as the user's own facts, not generic capabilities.
"""
    elif is_agent_meta_question(ul):
        meta_rules = """
- AGENT META: The user asked who you are or what LLM/API stack powers you. Use the provided Answer line as the substantive reply; do not substitute generic focus-only build advice for that line.
"""
    elif is_agent_tools_question(ul):
        meta_rules = """
- AGENT TOOLS: The user asked about tool use (e.g. web fetch). Use the provided Answer line as the substantive reply; do not substitute generic focus-only build advice for that line.
"""

    if subtarget == "system risk":
        answer_and_step_rules = f"""
SYSTEM RISK REPLY:
- Your entire assistant message must be exactly one sentence, with no other text.
- Do not use section headers such as "Answer:", "Current state:", "Next step:", or "Action type:".
- Do not add bullets, prefixes, or suffixes.
- Reply using exactly this sentence (verbatim):
{forced_answer_line}
""".strip()
    elif strict_reply or force_structured_override:
        answer_and_step_rules = f"""
SPECIFICITY RULE:
- The "Next step" must be narrow and directly executable.
- It must name one exact task, check, or target.
- Prefer testing a real feature behavior over testing meta-behavior.
- In a generic testing-state "what should I do next?" question, prefer:
  1. memory retrieval
  2. restart persistence
  3. state commands
  4. titan formatting
  5. action typing
- Do NOT use broad phrasing like:
  - "test one component"
  - "review part of the system"
  - "work on the project"
  - "continue building"

ANSWER RULE:
- The "Answer:" line must be short, direct, and tightly aligned to the chosen next step.
- Prefer one short sentence.
- Avoid paraphrased filler.
- Avoid repeating the whole next step.
- The exact answer line to use is:
{forced_answer_line}

- The exact next step to use is:
{forced_next_step}

OUTPUT FORMAT RULES:
- Keep the response tight and easy to scan.
- Do not write long essays.
- Use exactly these three sections in this order:

Answer:
<1 short sentence preferred>

Current state:
Focus: <focus>
Stage: <stage>
Action type: <action_type>

Next step:
<one specific action only>

- The "Answer:" line should match the chosen next step directly.
- Use the exact answer line provided above.
- The "Next step" section must contain exactly one actionable step.
- Use the exact next step provided above.
- Do not add extra sections.
- Do not add bullet lists unless the user explicitly asks for them.
- Do not add multiple options.
- Keep the wording concrete, direct, and grounded in the current state.

After answering, follow the exact output format above unless the TOOL RULE applies.
"""
    else:
        answer_and_step_rules = f"""
OPEN CONVERSATION MODE:
- The user did not match a narrow workflow template (subtarget: {subtarget}). Treat this as a normal question to answer well.
- In Answer:, respond directly to what they asked (facts, definitions, code, tradeoffs, or short reasoning). Length should fit the question: one sentence for a tiny fact, a short paragraph if they asked for explanation.
- Use supporting memory when it genuinely helps; if it is irrelevant, ignore it. Never contradict the current focus/stage labels in the Current state block, but you are not required to steer unrelated questions back into "one refinement inside focus."
- In Next step:, give one sensible follow-up (clarifying question, small experiment, file to open, or test)—on topic for their message, or lightly tied to this repo only when that fits.

OUTPUT FORMAT RULES:
- Use exactly these three sections in this order:

Answer:
<substantive reply>

Current state:
Focus: {focus}
Stage: {stage}
Action type: {action_type}

Next step:
<one helpful follow-up>

- Do not add extra sections unless the user asked for lists or structure.
- Do not paste boilerplate about "one small refinement inside the current focus" unless they were clearly asking what to build next in this focus.
"""

    system_prompt = f"""
You are a focused AI agent.

Current focus: {focus}
Current stage: {stage}
Current action type: {action_type}

IMPORTANT RULES:
- The current focus and stage are ALWAYS correct.
- ALWAYS prioritize state over memory.
- Memory may be outdated. State is the current truth.
- NEVER let memory rename, replace, or override the current focus or stage.
- Use memory only as supporting background context.
- If memory contains older project labels, older subsystem names, or older phase names, do NOT foreground them unless the user explicitly asks about them.
- When the user asks what to do next, anchor the answer to the current focus and current stage first.
- NEVER say you lack context if you can infer from the current focus and stage.
- Give confident, useful answers grounded in the current project and stage.
{user_purpose_priority_rules}{safety_rules}{anti_repeat_rules}{meta_rules}

TOOL RULE:
- If the user asks about a website, webpage, URL, or online content that you need to read first, respond ONLY with:
  TOOL:fetch https://url
- Do NOT explain.
- Do NOT answer yet.
- Do NOT wrap the tool command in markdown.
- Only use TOOL:fetch when a real URL is needed.

ACTION RULE:
- The next step must match the current action type.
- {action_guidance}
{answer_and_step_rules}
""".strip()

    memory_block = format_memory_block(memories)
    if memory_block:
        system_prompt += "\n\nSupporting memory:\n" + memory_block
    personal_context_block = format_memory_block(personal_context_memories)
    if personal_context_block:
        system_prompt += "\n\nStable user context:\n" + personal_context_block
        system_prompt += (
            "\n\nStable user context guidance:\n"
            "- Answer the user's question using the most relevant stable user context when supported.\n"
            "- Prefer durable user memory over weak or transient memory.\n"
            "- Do not invent traits not present in memory.\n"
            "- Do not let memory override current focus or stage.\n"
        )

    user_purpose_block = format_memory_block(user_purpose_memories)
    if user_purpose_block:
        system_prompt += "\n\nUser core purpose:\n" + user_purpose_block
        system_prompt += (
            "\n\nUser core purpose guidance:\n"
            "- The Answer must open by reflecting the user's core purpose above; the first sentence should state or clearly imply that real-world goal.\n"
            "- Do not open the Answer with testing, reliability, or architecture when purpose memory applies; put those after the purpose-led opening if useful.\n"
            "- System-state (testing, reliability, harness) stays secondary unless the question is narrowly technical.\n"
            "- Avoid answering only from system focus when stronger user-purpose memory applies.\n"
            "\n"
            "Self-alignment check:\n"
            "- Before finalizing the Answer, verify that it clearly supports the user's core purpose.\n"
            "- If it does not, adjust the Answer to better align with that purpose.\n"
            "- Do not ignore the question, but ensure the response contributes to the user's real-world goal.\n"
            "- If the initial reasoning leads toward system-focused explanation, re-anchor it to the user's purpose before answering.\n"
            "\n"
            "Next-step alignment:\n"
            "- The Next step should contribute to the user's core purpose when relevant.\n"
            "- Prefer actions that create or test real-world progress (e.g., workflows, experiments, validation tied to outcomes).\n"
            "- Avoid suggesting only internal/system refinements when a purpose-aligned action is available.\n"
            "- Do not propose a Next step that is only system-internal (tests, refactors) if a purpose-aligned step can be taken; system-internal steps can still appear, but secondary.\n"
            '- Example: Bad: "Add more tests to the module." Good: "Define and test a small workflow that can produce your first $X result."\n'
            "\n"
            "Current-context grounding:\n"
            "- The Answer must consider what the user is currently building and has available.\n"
            "- Prefer actions that can be executed immediately with existing tools, code, or progress.\n"
            "- Avoid generic strategies that assume capabilities not yet built.\n"
            "- Do not propose generic money-making strategies if a more specific, current-context-based action is possible.\n"
            "- Ground suggestions in the user's actual progress, not hypothetical capability.\n"
            "- Prefer steps that can be started today with minimal setup.\n"
            "- Reduce abstraction; increase execution.\n"
            '- Example: Bad: "Offer AI testing services online." Good: "Take the current testing capability you are building and offer a simple manual testing gig using what you already know today."\n'
            "\n"
            "Proactive initiative:\n"
            "- If a clear next action exists that would help the user move toward their core purpose, suggest it even if not explicitly requested.\n"
            "- The suggestion must be directly relevant to the current conversation.\n"
            "- Do not introduce unrelated ideas.\n"
            "- Do not suggest more than one next action.\n"
            "- Do not overwhelm with options.\n"
            "- Prefer one strong, decisive move.\n"
            "- When possible, extend the current direction instead of changing direction.\n"
            "- The proactive suggestion should feel like a natural continuation.\n"
            '- Example: Bad: "Here are several ways you could make money..." Good: "Based on what we just discussed, the next thing you should do is..."\n'
            '- Fit any proactive suggestion only inside the existing "Next step:" field; do not add new output sections.\n'
            "\n"
            "Confidence filter:\n"
            "- Only suggest a Next step if it is likely to produce meaningful progress.\n"
            "- Avoid weak, generic, or low-impact actions.\n"
            "- Prefer actions that:\n"
            "  - can be executed immediately\n"
            "  - have a clear outcome\n"
            "  - directly move toward the user's core goal\n"
            "- Do not suggest actions that are vague, overly broad, or unlikely to produce results.\n"
            '- Avoid filler steps like "explore options" or "consider possibilities" when a concrete move exists.\n'
            "- The Next step should be clear enough that the user can start it immediately without needing further clarification.\n"
            '- Example: Bad: "Look into possible ways to make money online." Good: "Message 5 potential clients today offering the specific service you can already deliver."\n'
            "\n"
            "Reality-constrained action selection:\n"
            "- Prefer actions the user can realistically start today with current skill, tools, and readiness.\n"
            "- Avoid suggesting strategies that assume advanced capability, established services, or systems not yet built.\n"
            "- Favor the shortest credible path to a first real result.\n"
            "- Do not assume the user already has client-ready technical capability unless clearly established.\n"
            "- Do not infer professional readiness from current project focus alone.\n"
            "- Prefer actions with minimal setup, low complexity, and fast feedback.\n"
            "- When a fast low-risk step exists, prefer it over ambitious but uncertain strategies.\n"
            '- Example: Bad: "Create an AI testing service and post it online." Good: "Choose one simple service you can personally deliver today with your current ability, and offer it to 3 people."\n'
        )
        if is_money_query:
            system_prompt += (
                "\n"
                "First-money bias:\n"
                "- When the user asks about making money, prioritize the fastest realistic path to earning the first small amount ($5-$20).\n"
                "- Favor immediate earning over skill-building, long-term strategy, or system development.\n"
                "- The first goal is proof of earning, not optimization.\n"
                '- Avoid suggesting steps that delay earning (e.g., "learn", "practice", "build portfolio") when a direct earning action exists.\n'
                "- Do not prioritize preparation over action when a minimal viable action is possible.\n"
                "- Prefer actions that can be executed within the same day.\n"
                "- Prefer environments where the user can interact with real opportunities immediately (e.g., gigs, direct outreach, small tasks).\n"
                '- Example: Bad: "Practice testing on GitHub projects first." Good: "Sign up for a testing platform or message someone today offering a simple manual test for a small fee."\n'
                "\n"
                "Single-move compression:\n"
                "- If the user asks for the exact next step, reduce the recommendation to one concrete action.\n"
                "- Prefer one executable move over a category of possible moves.\n"
                "- The user should be able to act immediately without deciding among multiple paths.\n"
                '- Do not answer with only a general lane such as "find gigs," "look for work," or "explore platforms" when a more specific immediate move can be given.\n'
                "- Compress the advice into one action, one place, and one immediate objective when possible.\n"
                "- The Next step should name: one place or channel, one action, one immediate objective.\n"
                "\n"
                "Decisiveness:\n"
                "- When the user asks for an exact next step, commit to one specific action.\n"
                "- Avoid hedging, multiple options, or soft language.\n"
                "- Prefer strong directive phrasing.\n"
                '- Example: Bad: "You could try looking for gigs..." Good: "Open Upwork now, search \'manual testing under $50\', and save 3 jobs."\n'
            )
        if is_context_lock_relevant:
            system_prompt += (
                "\n"
                "Context lock:\n"
                "- NEVER answer meta/system questions with generic AI explanations when a project context exists.\n"
                "- ALWAYS interpret the question in terms of the user's current system and goals.\n"
                "- Generic AI explanations are only allowed if explicitly requested.\n"
                "- When asked about how you are built or how to improve, anchor the answer to the current project (playground.py, memory, testing system, etc.).\n"
                '- Frame answers in terms of "your system" not "AI in general".\n'
            )
        if is_fallback_relevant:
            system_prompt += (
                "\n"
                "Fallback intelligence:\n"
                "- If a tool cannot be used or the request is vague, DO NOT wait for clarification.\n"
                "- Infer a reasonable research direction from context and proceed.\n"
                "- Suggest one concrete next research action immediately.\n"
                "- When research is requested without specifics, propose a concrete research action: one topic, one platform or method, one immediate action.\n"
            )

    journal_block = format_journal_block(journal_entries)
    if journal_block:
        system_prompt += "\n\nRecent project journal:\n" + journal_block
    outcome_feedback_block = format_outcome_feedback_block(outcome_feedback_entries)
    if outcome_feedback_block:
        system_prompt += "\n\nRecent outcome feedback:\n" + outcome_feedback_block

    recent_answers_block = format_recent_answer_history_block()
    if recent_answers_block:
        system_prompt += "\n\nRecent assistant outputs (session, bounded):\n" + recent_answers_block
        best_recent_match = get_best_recent_answer_match(user_input)
        is_recent_relevant = bool(best_recent_match) and detect_recent_answer_relevance(user_input)
        if is_recent_relevant:
            if is_strong_recent_answer_match(best_recent_match):
                system_prompt += (
                    "\n\nRelevant recent assistant output:\n"
                    f"{best_recent_match['matched_text']}\n"
                )
            followup_type = detect_recent_answer_followup_type(user_input, best_recent_match["matched_text"])
            if followup_type == "continuation":
                system_prompt += (
                    "\n\nRecent-answer follow-up type: continuation\n"
                    "- The user may be continuing a recent thread.\n"
                    "- Build on the relevant recent answer if useful.\n"
                    "- Avoid restarting from zero.\n"
                )
            elif followup_type == "clarification":
                system_prompt += (
                    "\n\nRecent-answer follow-up type: clarification\n"
                    "- The user may be asking for a clearer or more precise version of a recent answer.\n"
                    "- Refine or sharpen the prior answer.\n"
                    "- Prefer precision over repetition.\n"
                )
            elif followup_type == "correction":
                system_prompt += (
                    "\n\nRecent-answer follow-up type: correction\n"
                    "- The user may be challenging or correcting a recent answer.\n"
                    "- Refine or correct briefly if warranted.\n"
                    "- Prefer correction over repetition.\n"
                    "- Do not claim contradiction unless supported by context.\n"
                )
            system_prompt += (
                "\n\nRecent-answer reflection guidance:\n"
                "- The current question may relate to a recent assistant output.\n"
                "- Use the relevant recent output only if it improves correctness.\n"
                "- Refine it if useful.\n"
                "- Do not repeat earlier wording blindly.\n"
                "- Do not invent prior mistakes if none are evident.\n"
            )
            has_contradiction_cue = detect_recent_answer_contradiction_cue(user_input, best_recent_match["matched_text"])
            if is_recent_relevant and has_contradiction_cue:
                system_prompt += (
                    "\nRecent-answer contradiction/refinement cue:\n"
                    "- The user may be challenging or refining a recent assistant answer.\n"
                    "- If needed, correct or refine the earlier answer.\n"
                    "- Prefer correction over repetition.\n"
                    "- Do not claim a contradiction unless context supports it.\n"
                    "- If refining, do it briefly.\n"
                    '- Prefer phrasing like "Let me refine that:" or "More precisely:".\n'
                    "- Do not apologize unless an actual mistake is clear.\n"
                    "- Do not dramatize.\n"
                    "- Do not claim memory certainty beyond current session context.\n"
                )

    messages = [{"role": "user", "content": user_input}]
    return system_prompt, messages
