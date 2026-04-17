import re
from os import getenv


META_OVERRIDE_MARKERS = (
    "how is this system built",
    "how is it built",
    "how it works",
    "how does it work",
    "how does your system",
    "how do you work",
    "how are you built",
    "why should i trust",
    "what prevents",
    "mechanically",
    "under the hood",
    "leakage",
    "drift",
    "guarantee",
    "guarantees",
    "override logic",
    "how to improve",
    "improve you",
    "make you better",
    "make this system better",
    "improve this system",
)

META_TRUST_CONTROL_MARKERS = (
    "why should i trust",
    "what prevents",
    "mechanically",
    "under the hood",
    "leakage",
    "drift",
    "guarantee",
    "guarantees",
    "override logic",
    "what exact conditions",
)

ANALYTICAL_SYSTEM_EVAL_MARKERS = (
    "false reinforcement",
    "learning the wrong pattern",
    "wrong pattern",
    "conflicting outcomes",
    "prove changed behavior",
    "are you actually learning",
    "my mistake",
    "one failure was my mistake",
)

VAGUE_RESEARCH_MARKERS = (
    "do the research",
    "research this",
    "research for me",
    "do some research",
    "look into it",
    "investigate this",
)


def _routing_debug_enabled():
    flag = (getenv("DEBUG_ROUTING") or "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def _trace_route(event, detail):
    if _routing_debug_enabled():
        print(f"[routing] {event}: {detail}")


def infer_action_type(user_input, stage):
    text = (user_input or "").strip().lower()
    stage_text = stage.lower()
    if re.search(r"\b(?:error|bug|broken|fix|issue)\b", text):
        _trace_route("infer_action_type", "fix")
        return "fix"
    if any(word in text for word in ["research", "look up", "find", "compare", "read", "website", "url", "webpage"]):
        _trace_route("infer_action_type", "research")
        return "research"
    if any(word in text for word in ["review", "evaluate", "assess", "inspect"]):
        _trace_route("infer_action_type", "review")
        return "review"
    if re.search(r"\b(?:check|test|validate|verify)\b", text):
        _trace_route("infer_action_type", "test")
        return "test"
    if "testing" in stage_text:
        _trace_route("infer_action_type", "test(stage)")
        return "test"
    if "optimization" in stage_text:
        _trace_route("infer_action_type", "review(stage)")
        return "review"
    _trace_route("infer_action_type", "build")
    return "build"


def build_action_guidance(action_type):
    guidance = {
        "build": "The next step should create or add one concrete piece of the system.",
        "test": "The next step should validate one specific part of the current system.",
        "review": "The next step should inspect, assess, or evaluate one part of the system.",
        "research": "The next step should gather only the information needed for the immediate task.",
        "fix": "The next step should address one clear problem or failure point.",
    }
    return guidance.get(action_type, "The next step should be specific and useful.")


def is_agent_purpose_question(text):
    if not isinstance(text, str) or not text.strip():
        return False
    t = re.sub(r"\s+", " ", text.strip().lower())
    if len(t) > 280:
        return False
    purpose_markers = (
        "meant to be",
        "meant to do",
        "meant for",
        "what is your purpose",
        "your purpose",
        "why do you exist",
        "why were you made",
        "why were you built",
        "what are you for",
        "what are you supposed to",
        "finish this sentence",
        "complete this sentence",
        "fill in the blank",
        "being built to",
        "being build to",
        "you are being",
        "you're being",
        "built to be",
        "build to be",
        "intended role",
        "your intended role",
        "what is your role",
        "what's your role",
        "whats your role",
        "your role here",
        "your role in this",
    )
    if any(m in t for m in purpose_markers):
        return True
    return False


def is_agent_meta_question(text):
    if not isinstance(text, str) or not text.strip():
        return False
    t = re.sub(r"\s+", " ", text.strip().lower())
    if len(t) > 220:
        return False
    identity_phrases = (
        "who are you",
        "what are you",
        "what's your name",
        "whats your name",
        "your name",
        "introduce yourself",
    )
    base = t.rstrip("?").strip()
    if base in identity_phrases:
        return True
    if t in identity_phrases or t in {p + "?" for p in identity_phrases}:
        return True
    stack_markers = (
        "language model",
        "llm layer",
        "model layer",
        "what model",
        "which model",
        "anthropic",
        "claude api",
        "what api",
        "core/llm",
        "llm.py",
        "api layer",
    )
    if any(m in t for m in stack_markers):
        return True
    if "your" in t and "model" in t:
        return True
    return False


def is_agent_tools_question(text):
    if not isinstance(text, str) or not text.strip():
        return False
    t = re.sub(r"\s+", " ", text.strip().lower())
    if len(t) > 220:
        return False
    tool_markers = (
        "tools",
        "what tools",
        "any tools",
        "use tools",
        "using tools",
        "tool:",
        "tool support",
        "fetch tool",
        "tool fetch",
    )
    if not any(m in t for m in tool_markers):
        return False
    if any(
        p in t
        for p in (
            "can you",
            "could you",
            "do you",
            "are you able",
            "will you",
            "what tools",
            "any tools",
            "have tools",
            "use tools",
            "using tools",
            "tool fetch",
            "fetch tool",
            "fetch a url",
            "fetch a page",
            "browse the web",
        )
    ):
        return True
    return False


def user_negates_memory_retrieval_phrase(user_input):
    u = (user_input or "").lower()
    if "memory retrieval" not in u:
        return False
    return bool(
        re.search(
            r"\b(?:not|never|without|no|isn't|aren't|don't|won't)\b[\w\s,'\"—-]{0,120}\bmemory\s+retrieval\b",
            u,
        )
    )


def user_negates_recall_memory_phrase(user_input):
    u = (user_input or "").lower()
    if "recall memory" not in u:
        return False
    return bool(
        re.search(
            r"\b(?:not|never|without|no|isn't|aren't|don't|won't)\b[\w\s,'\"—-]{0,120}\brecall\s+memory\b",
            u,
        )
    )


def is_generic_next_step_question(user_input):
    text = user_input.strip().lower()
    generic_patterns = {
        "what should i do next?",
        "what should i do next",
        "what's the next step?",
        "what's the next step",
        "what is the next step?",
        "what is the next step",
        "what should be next?",
        "what should be next",
    }
    return text in generic_patterns


def detect_subtarget(user_input, focus, stage):
    u = re.sub(r"\s+", " ", (user_input or "").strip().lower())
    if is_agent_purpose_question(u):
        _trace_route("detect_subtarget", "agent_purpose")
        return "agent_purpose"
    if is_agent_meta_question(u):
        _trace_route("detect_subtarget", "agent_meta")
        return "agent_meta"
    if is_agent_tools_question(u):
        _trace_route("detect_subtarget", "agent_tools")
        return "agent_tools"

    text = f"{user_input} {focus} {stage}".lower()
    if any(
        term in text
        for term in [
            "regression harness",
            "run_regression",
            "tests/run_regression",
            "keep it safe",
            "keep safe",
            "stay safe",
            "project safe",
            "don't break",
            "dont break",
            "do not break",
            "what do i rely",
            "what i rely",
        ]
    ):
        _trace_route("detect_subtarget", "safety practices")
        return "safety practices"
    if "rely on" in text and any(w in text for w in ("safe", "safety", "stability", "break", "risk", "regression")):
        _trace_route("detect_subtarget", "safety practices(rely)")
        return "safety practices"
    if (
        "biggest risk" in u
        or "failure point" in u
        or re.search(r"\brisk\b", u)
        or re.search(r"\bweakness\b", u)
        or re.search(r"\bfragile\b", u)
        or (
            re.search(r"\bbreak\b", u)
            and re.search(r"\b(risk|weakness|fragile|failure|routing|system|playground|agent|repo|codebase)\b", u)
        )
    ):
        _trace_route("detect_subtarget", "system risk")
        return "system risk"
    memory_workflow_terms = [
        "memory retrieval",
        "retrieve memory",
        "recall memory",
        "remember",
        "stored preference",
    ]
    if any(term in text for term in memory_workflow_terms):
        blocked = set()
        if "memory retrieval" in text and user_negates_memory_retrieval_phrase(user_input):
            blocked.add("memory retrieval")
        if "recall memory" in text and user_negates_recall_memory_phrase(user_input):
            blocked.add("recall memory")
        active = [t for t in memory_workflow_terms if t in text and t not in blocked]
        if active:
            _trace_route("detect_subtarget", "memory retrieval")
            return "memory retrieval"
    if any(
        term in text
        for term in ("how do i prefer", "learning style", "my preferences", "what do i prefer", "which do i prefer")
    ):
        _trace_route("detect_subtarget", "memory behavior")
        return "memory behavior"
    if any(
        term in u
        for term in (
            "state persistence",
            "persist state",
            "after restart",
            "after a restart",
            "survive restart",
            "survives restart",
            "restart the app",
            "restart playground",
            "restart once",
            "relaunch the app",
            "state persisted",
            "does state persist",
            "will state persist",
            "state survive",
            "persist after restart",
        )
    ):
        _trace_route("detect_subtarget", "restart persistence")
        return "restart persistence"
    ui = (user_input or "").strip().lower()
    if ui.startswith("set focus:") or ui.startswith("set stage:") or ui == "show state" or ui == "reset state":
        _trace_route("detect_subtarget", "state commands")
        return "state commands"
    if any(term in text for term in ["format", "formatting", "output format", "titan", "structure", "response format"]):
        _trace_route("detect_subtarget", "titan formatting")
        return "titan formatting"
    if any(term in text for term in ["action type", "action typing", "classification", "build test review", "action classification"]):
        _trace_route("detect_subtarget", "action typing")
        return "action typing"
    if any(term in text for term in ["next step", "specificity", "specific", "too generic", "vague"]):
        _trace_route("detect_subtarget", "next-step specificity")
        return "next-step specificity"
    if any(term in text for term in ["blank input", "empty input", "press enter", "empty line", "no input"]):
        _trace_route("detect_subtarget", "blank-input handling")
        return "blank-input handling"
    if any(term in text for term in ["website", "webpage", "url", "online page", "read site", "fetch"]):
        _trace_route("detect_subtarget", "web research")
        return "web research"
    if any(term in (user_input or "").lower() for term in ("playground.py", "agent behavior", "ai-agent", "agent system")):
        _trace_route("detect_subtarget", "playground.py behavior")
        return "playground.py behavior"
    _trace_route("detect_subtarget", "current behavior")
    return "current behavior"


def uses_strict_forced_reply(user_input, subtarget):
    if is_generic_next_step_question(user_input):
        return True
    return subtarget in {"safety practices", "state commands", "agent tools"}


def is_meta_system_override_question(user_input, focus, stage):
    t = (user_input or "").strip().lower()
    if any(m in t for m in ANALYTICAL_SYSTEM_EVAL_MARKERS):
        return False
    subtarget = detect_subtarget(user_input, focus, stage)
    if subtarget == "agent_meta":
        return True
    return any(m in t for m in META_TRUST_CONTROL_MARKERS) or any(m in t for m in META_OVERRIDE_MARKERS)


def is_vague_research_request(user_input):
    t = (user_input or "").strip().lower()
    if any(m in t for m in VAGUE_RESEARCH_MARKERS):
        return True
    return t in {"research", "do research", "look it up", "investigate"}


def classify_vague_research_intent(user_input):
    t = (user_input or "").strip().lower()
    web_cues = ("website", "websites", "url", "contact", "online", "web", "page", "pages")
    repo_cues = ("repo", "code", "file", "test", "tests", "playground", "memory", "regression")
    if any(c in t for c in web_cues):
        return "web"
    if any(c in t for c in repo_cues):
        return "repo"
    return "general"


def choose_default_test_target(focus, stage):
    stage_text = stage.lower()
    focus_text = focus.lower()
    if "testing" in stage_text:
        if "agent" in focus_text or "ai-agent" in focus_text:
            return "memory retrieval"
        return "current behavior"
    return "current behavior"


def build_specific_next_step(user_input, focus, stage, action_type):
    subtarget = detect_subtarget(user_input, focus, stage)
    if is_meta_system_override_question(user_input, focus, stage):
        return "Open `playground.py`, pick one concrete path (`build_messages` context rules, memory retrieval, or tool fallback), and implement one targeted improvement before re-running `python tests/run_regression.py`."
    if subtarget == "agent_purpose":
        return "Open `HANDOFF_RECENT_WORK.md` or `PROJECT_SPECIFICATION.md`, pick one subsystem (memory, journal, tools, or regression), and ask your next question about only that piece."
    if subtarget == "agent_meta":
        return "Open `core/llm.py` and `config/settings.py` and confirm `ANTHROPIC_MODEL` / `ANTHROPIC_API_KEY` in `.env` match how you want this agent to call Anthropic."
    if subtarget == "agent_tools":
        return "Try one prompt that needs real page text with a full https URL and confirm the first reply is exactly one line: TOOL:fetch <that-url>."
    if subtarget == "system risk":
        return "Pick one prior mis-route in `playground.py` (`detect_subtarget` / `uses_strict_forced_reply`), adjust a single guard or phrase list, and run `python tests/run_regression.py` to confirm nothing regressed."
    if subtarget == "safety practices":
        if action_type == "test":
            return "Run `python tests/run_regression.py` once and confirm every scenario passes before treating the system as safe to extend."
        return "Run `python tests/run_regression.py` after the next edit and confirm exit code 0 so the protected baseline still holds."
    if action_type == "test":
        if is_generic_next_step_question(user_input):
            default_target = choose_default_test_target(focus, stage)
            if default_target == "memory retrieval":
                return "Test memory retrieval with one known preference question, then ask a follow-up that depends on the same detail and verify the answer stays consistent."
            return f"Run one focused test on {default_target} and verify the next step points to one exact check inside `{focus}`."
        if subtarget == "memory retrieval" or subtarget == "memory behavior":
            return "Test memory retrieval with one known preference question, then ask a follow-up that depends on the same detail and verify the answer stays consistent."
        if subtarget == "restart persistence":
            return "Set a new focus and stage, restart the app once, then run `show state` and confirm both values persisted correctly."
        if subtarget == "state commands":
            return "Run one state-command pass: use `set focus`, `set stage`, and `show state`, then confirm the printed state matches exactly what you set."
        if subtarget == "next-step specificity":
            return "Ask `What should I do next?` in the current testing state and verify the reply names one exact feature test instead of a broad or meta-level suggestion."
        if subtarget == "action typing":
            return "Ask one test-oriented prompt and confirm the agent labels the action type as `test` and gives a next step tied to a single behavior."
        if subtarget == "titan formatting":
            return "Ask one normal question and confirm the reply keeps the exact Titan structure with one short answer block and one concrete next step."
        if subtarget == "blank-input handling":
            return "Press Enter on an empty line once and confirm the app prints `⚠️ Please type something.` without generating a malformed response."
        return f"Run one focused test on {subtarget} and verify the next step points to one exact check inside `{focus}`."
    if action_type == "review":
        if subtarget == "titan formatting":
            return "Review the Titan response wording and identify the first place where the format becomes less direct or less consistent."
        if subtarget == "state commands":
            return "Review the state-command logic and identify the first place where command handling becomes less clear or less consistent."
        return f"Review the part of the prompt logic that governs {subtarget} and identify the first place where the wording becomes generic."
    if action_type == "fix":
        return f"Reproduce the problem once in {subtarget}, then adjust only the logic that controls that behavior before retesting the same prompt."
    if action_type == "research":
        if subtarget == "web research":
            return "Use one real page URL, fetch it, and verify the final answer stays grounded in the fetched content."
        return f"Gather one concrete example of stronger {subtarget} wording so the next prompt revision can anchor to a real target shape."
    if subtarget == "next-step specificity":
        return "Tighten the prompt so the `Next step:` line must name one exact task, such as a restart test, a state-command check, or a memory retrieval check."
    if subtarget == "playground.py behavior":
        return "Refine one branch in `playground.py` so the next-step wording points to a single concrete task instead of a project-wide action."
    return f"Add one small refinement that makes the next step point to a single concrete task inside `{focus}` at stage `{stage}`."
