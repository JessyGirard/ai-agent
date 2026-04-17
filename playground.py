import re
from pathlib import Path

from core.llm import ask_ai, llm_preflight_check
from core.persistence import (
    append_project_journal as persistence_append_project_journal,
    archive_project_journal_entries as persistence_archive_project_journal_entries,
    load_memory_payload as persistence_load_memory_payload,
    load_project_journal as persistence_load_project_journal,
    load_state as persistence_load_state,
    save_memory_payload as persistence_save_memory_payload,
    save_state as persistence_save_state,
    write_project_journal as persistence_write_project_journal,
)
from services import journal_service, memory_service
from services import prompt_builder
from services import routing_service
from tools.fetch_page import fetch_page

MEMORY_FILE = Path("memory/extracted_memory.json")
STATE_FILE = Path("memory/current_state.json")
JOURNAL_FILE = Path("memory/project_journal.jsonl")
JOURNAL_ARCHIVE_FILE = Path("memory/project_journal_archive.jsonl")
JOURNAL_MAX_ACTIVE_ENTRIES = 300
JOURNAL_KEEP_RECENT_ON_MANUAL_FLUSH = 50
JOURNAL_RETRIEVAL_WINDOW = 200

DEFAULT_STATE = {
    "focus": "ai-agent project",
    "stage": "Phase 4 action-layer refinement",
}

ACTION_TYPES = ["build", "test", "review", "research", "fix"]

ALLOWED_MEMORY_CATEGORIES = {"identity", "goal", "preference", "project"}

current_state = {}
RECENT_ANSWER_HISTORY_MAX = journal_service.RECENT_ANSWER_HISTORY_MAX
recent_answer_history = journal_service.make_recent_answer_history()


# ---------- STATE ----------

def load_state():
    return persistence_load_state(STATE_FILE, DEFAULT_STATE)


def save_state():
    persistence_save_state(STATE_FILE, current_state)


def _user_discussing_state_command(line: str) -> bool:
    """True when the user is talking about commands, not issuing a bare line."""
    raw = (line or "").strip()
    if not raw:
        return False
    text = raw.lower()

    if text.startswith("set focus:") or text.startswith("set stage:"):
        return False
    if text in ("show state", "reset state"):
        return False

    meta_phrases = (
        "if i type",
        "if i say",
        "what happens if",
        "treat this as",
        "example:",
        "this is",
    )
    if any(p in text for p in meta_phrases):
        return True

    if re.search(
        r'["\'][^"\']*(?:set\s+focus\s*:|set\s+stage\s*:)[^"\']*["\']',
        raw,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r'["\'][^"\']*(?:show\s+state|reset\s+state)[^"\']*["\']',
        raw,
        re.IGNORECASE,
    ):
        return True

    return False


def update_state_from_command(user_input):
    line = (user_input or "").strip()
    text = line.lower()

    if _user_discussing_state_command(line):
        return None

    if text.startswith("set stage:"):
        new_stage = line.split(":", 1)[1].strip()
        if not new_stage:
            return "❌ Stage cannot be empty."

        current_state["stage"] = new_stage
        save_state()
        return f"✅ Stage updated to: {new_stage}"

    if text.startswith("set focus:"):
        new_focus = line.split(":", 1)[1].strip()
        if not new_focus:
            return "❌ Focus cannot be empty."

        current_state["focus"] = new_focus
        save_state()
        return f"✅ Focus updated to: {new_focus}"

    if text == "show state":
        return (
            "📌 Current state:\n"
            f"- Focus: {current_state.get('focus', DEFAULT_STATE['focus'])}\n"
            f"- Stage: {current_state.get('stage', DEFAULT_STATE['stage'])}"
        )

    if text == "reset state":
        current_state.clear()
        current_state.update(DEFAULT_STATE.copy())
        save_state()
        return "✅ State reset to default."

    return None


def get_current_focus():
    return current_state.get("focus", DEFAULT_STATE["focus"])


def get_current_stage():
    return current_state.get("stage", DEFAULT_STATE["stage"])


# ---------- PROJECT JOURNAL ----------

def load_project_journal(max_entries=None):
    return persistence_load_project_journal(JOURNAL_FILE, max_entries=max_entries)


def write_project_journal(entries):
    persistence_write_project_journal(JOURNAL_FILE, entries)


def archive_project_journal_entries(entries, reason):
    persistence_archive_project_journal_entries(JOURNAL_ARCHIVE_FILE, entries, reason)


def flush_project_journal(keep_recent):
    return journal_service.flush_project_journal(
        keep_recent, load_project_journal, archive_project_journal_entries, write_project_journal
    )


def compact_project_journal_if_needed():
    return journal_service.compact_project_journal_if_needed(
        JOURNAL_MAX_ACTIVE_ENTRIES,
        load_project_journal,
        archive_project_journal_entries,
        write_project_journal,
    )


def append_project_journal(entry_type, user_input, response_text, action_type, extra_fields=None):
    journal_service.append_project_journal(
        entry_type,
        user_input,
        response_text,
        action_type,
        get_current_focus,
        get_current_stage,
        persistence_append_project_journal,
        JOURNAL_FILE,
        compact_project_journal_if_needed,
        extra_fields=extra_fields,
    )


def retrieve_relevant_journal_entries(user_input, limit=3):
    return journal_service.retrieve_relevant_journal_entries(
        user_input, load_project_journal, tokenize_text, JOURNAL_RETRIEVAL_WINDOW, limit=limit
    )


def format_journal_block(entries):
    return journal_service.format_journal_block(entries)


def retrieve_recent_outcome_feedback_entries(limit=3):
    return journal_service.retrieve_recent_outcome_feedback_entries(
        load_project_journal, limit=limit
    )


def format_outcome_feedback_block(entries):
    return journal_service.format_outcome_feedback_block(entries)


def is_outcome_feedback_context_relevant(user_input):
    return journal_service.is_outcome_feedback_context_relevant(user_input)


def apply_recent_negative_outcome_anti_repeat_guard(user_input, candidate_next_step):
    return journal_service.apply_recent_negative_outcome_anti_repeat_guard(
        user_input, candidate_next_step, retrieve_recent_outcome_feedback_entries, tokenize_text
    )


def append_recent_answer_history(response_text):
    journal_service.append_recent_answer_history(response_text, recent_answer_history)


def format_recent_answer_history_block():
    return journal_service.format_recent_answer_history_block(recent_answer_history)


def filter_recent_answer_match_tokens(tokens):
    return journal_service.filter_recent_answer_match_tokens(tokens)


def get_recent_answer_match_tokens(text):
    return journal_service.get_recent_answer_match_tokens(text, tokenize_text)


def get_best_recent_answer_match(user_input):
    return journal_service.get_best_recent_answer_match(
        user_input, recent_answer_history, tokenize_text
    )


def detect_recent_answer_relevance(user_input):
    return journal_service.detect_recent_answer_relevance(
        user_input, recent_answer_history, tokenize_text
    )


def is_strong_recent_answer_match(match_info):
    return journal_service.is_strong_recent_answer_match(match_info)


def detect_recent_answer_contradiction_cue(user_input, matched_text):
    return journal_service.detect_recent_answer_contradiction_cue(user_input, matched_text)


def detect_recent_answer_followup_type(user_input, matched_text):
    return journal_service.detect_recent_answer_followup_type(
        user_input, matched_text, detect_recent_answer_relevance
    )


def handle_project_journal_command(user_input):
    return journal_service.handle_project_journal_command(
        user_input,
        flush_project_journal,
        JOURNAL_KEEP_RECENT_ON_MANUAL_FLUSH,
        load_project_journal,
        JOURNAL_MAX_ACTIVE_ENTRIES,
        JOURNAL_RETRIEVAL_WINDOW,
    )


# ---------- MEMORY ----------

def default_memory_payload():
    return memory_service.default_memory_payload()


def load_memory_payload():
    return persistence_load_memory_payload(
        MEMORY_FILE, default_memory_payload, dedupe_memory_items
    )


def save_memory_payload(payload):
    persistence_save_memory_payload(MEMORY_FILE, payload)


def load_memory():
    return memory_service.load_memory(load_memory_payload)


def tokenize_text(text):
    return memory_service.tokenize_text(text)


def project_safety_conversation_query(user_input):
    return memory_service.project_safety_conversation_query(user_input)


def safety_signal_memory(mem):
    return memory_service.safety_signal_memory(mem)


def detect_memory_intent(user_input):
    return memory_service.detect_memory_intent(user_input)


def estimate_memory_recency_bonus(mem):
    return memory_service.estimate_memory_recency_bonus(mem)


def estimate_memory_staleness_penalty(mem):
    return memory_service.estimate_memory_staleness_penalty(mem)


def negation_signal_present(text_low):
    return memory_service.negation_signal_present(text_low)


def runtime_memory_write_conflicts_existing(category, value, memory_items):
    return memory_service.runtime_memory_write_conflicts_existing(category, value, memory_items)


def score_memory_item(mem, user_input):
    return memory_service.score_memory_item(mem, user_input)


def retrieve_relevant_memory(user_input):
    return memory_service.retrieve_relevant_memory(user_input, load_memory)


def is_durable_user_memory(mem):
    return memory_service.is_durable_user_memory(mem)


def is_personal_context_question(user_input):
    return memory_service.is_personal_context_question(user_input)


def is_user_purpose_memory(mem):
    return memory_service.is_user_purpose_memory(mem)


def is_user_purpose_query_signal(user_input):
    return memory_service.is_user_purpose_query_signal(user_input)


def retrieve_user_purpose_memory(user_input, limit=2):
    return memory_service.retrieve_user_purpose_memory(user_input, load_memory, limit=limit)


def score_personal_memory_temporal_strength(mem):
    return memory_service.score_personal_memory_temporal_strength(mem)


def personal_memory_stale_import_penalty(mem):
    return memory_service.personal_memory_stale_import_penalty(mem)


def prefer_stronger_personal_memory(mem_a, mem_b):
    return memory_service.prefer_stronger_personal_memory(mem_a, mem_b)


def personal_memory_rows_heavily_overlap(mem_a, mem_b):
    return memory_service.personal_memory_rows_heavily_overlap(mem_a, mem_b)


def retrieve_personal_context_memory(user_input, limit=3):
    return memory_service.retrieve_personal_context_memory(user_input, load_memory, limit=limit)


def retrieve_memory_for_purpose(user_input, k=6):
    return memory_service.retrieve_memory_for_purpose(user_input, build_memory_key, load_memory, k=k)


def format_memory_block(memories):
    return memory_service.format_memory_block(memories)


def estimate_runtime_importance(category, value):
    return memory_service.estimate_runtime_importance(category, value)


def estimate_runtime_confidence(evidence_count):
    return memory_service.estimate_runtime_confidence(evidence_count)


def classify_memory_kind(evidence_count):
    return memory_service.classify_memory_kind(evidence_count)


def build_memory_key(category, value):
    return memory_service.build_memory_key(category, value)


def canonicalize_memory_key_value(value):
    return memory_service.canonicalize_memory_key_value(value)


def normalize_memory_display_value(value):
    return memory_service.normalize_memory_display_value(value)


def dedupe_memory_items(memory_items):
    return memory_service.dedupe_memory_items(memory_items)


def normalize_runtime_memory_value(value):
    return memory_service.normalize_runtime_memory_value(value)


def is_transient_identity_statement(low_text):
    return memory_service.is_transient_identity_statement(low_text)


def has_uncertainty_signal(low_text):
    return memory_service.has_uncertainty_signal(low_text)


def allows_uncertain_runtime_memory(category):
    return memory_service.allows_uncertain_runtime_memory(category)


def make_runtime_memory_candidate(category, text, low):
    return memory_service.make_runtime_memory_candidate(category, text, low)


def extract_runtime_memory_candidate(user_input):
    return memory_service.extract_runtime_memory_candidate(user_input)


def next_runtime_memory_id(memory_items):
    return memory_service.next_runtime_memory_id(memory_items)


def create_runtime_memory_item(memory_items, category, value):
    return memory_service.create_runtime_memory_item(memory_items, category, value)


def merge_runtime_memory(existing_item):
    return memory_service.merge_runtime_memory(existing_item)


def write_runtime_memory(user_input):
    return memory_service.write_runtime_memory(
        user_input, ALLOWED_MEMORY_CATEGORIES, load_memory_payload, save_memory_payload
    )


# ---------- ACTION STRUCTURE ----------

def infer_action_type(user_input, stage):
    return routing_service.infer_action_type(user_input, stage)


def detect_outcome_feedback_signal(user_input):
    return journal_service.detect_outcome_feedback_signal(user_input)


def build_action_guidance(action_type):
    return routing_service.build_action_guidance(action_type)


# ---------- ROUTING ----------

def is_agent_purpose_question(text):
    return routing_service.is_agent_purpose_question(text)


def is_agent_meta_question(text):
    return routing_service.is_agent_meta_question(text)


def is_agent_tools_question(text):
    return routing_service.is_agent_tools_question(text)


def _user_negates_memory_retrieval_phrase(user_input: str) -> bool:
    return routing_service.user_negates_memory_retrieval_phrase(user_input)


def _user_negates_recall_memory_phrase(user_input: str) -> bool:
    return routing_service.user_negates_recall_memory_phrase(user_input)


def is_generic_next_step_question(user_input):
    return routing_service.is_generic_next_step_question(user_input)


def detect_subtarget(user_input, focus, stage):
    return routing_service.detect_subtarget(user_input, focus, stage)


def uses_strict_forced_reply(user_input, subtarget):
    return routing_service.uses_strict_forced_reply(user_input, subtarget)


def is_meta_system_override_question(user_input, focus, stage):
    return routing_service.is_meta_system_override_question(user_input, focus, stage)


def is_vague_research_request(user_input):
    return routing_service.is_vague_research_request(user_input)


def classify_vague_research_intent(user_input):
    return routing_service.classify_vague_research_intent(user_input)


def choose_default_test_target(focus, stage):
    return routing_service.choose_default_test_target(focus, stage)


def build_specific_next_step(user_input, focus, stage, action_type):
    return routing_service.build_specific_next_step(user_input, focus, stage, action_type)


# ---------- ANSWER LINE ----------

def build_answer_line(user_input, focus, stage, action_type, next_step, memories=None):
    return prompt_builder.build_answer_line(
        user_input,
        focus,
        stage,
        action_type,
        next_step,
        memories=memories,
        detect_subtarget=detect_subtarget,
        is_meta_system_override_question=is_meta_system_override_question,
        is_vague_research_request=is_vague_research_request,
        classify_vague_research_intent=classify_vague_research_intent,
        safety_signal_memory=safety_signal_memory,
        is_generic_next_step_question=is_generic_next_step_question,
    )


# ---------- TOOL HANDLING ----------

def parse_tool_command(response_text):
    if not isinstance(response_text, str):
        return None

    response_text = response_text.strip()
    match = re.fullmatch(r"TOOL:fetch\s+(https?://\S+)", response_text)

    if not match:
        return None

    return {
        "tool": "fetch",
        "url": match.group(1)
    }


def user_message_suppresses_tool_fetch(user_input: str) -> bool:
    """True when the user forbids tools or quotes/references TOOL:fetch as syntax — skip real fetch."""
    if not user_input or not isinstance(user_input, str):
        return False
    text = user_input.strip()
    low = text.lower()

    if re.search(r'["\'][^"\']*TOOL:fetch[^"\']*["\']', text, re.IGNORECASE):
        return True
    if re.search(r'["\']\s*TOOL:fetch', text, re.IGNORECASE):
        return True
    if re.search(r'TOOL:fetch\s*["\']', text, re.IGNORECASE):
        return True

    forbid_or_exact_message = (
        "i forbid tools",
        "do not use tools",
        "don't fetch",
        "not asking you to fetch",
        "message is exactly tool:fetch",
    )
    if any(p in low for p in forbid_or_exact_message):
        return True

    return False


def choose_post_fetch_next_step(fetched_content):
    return prompt_builder.choose_post_fetch_next_step(fetched_content)


def build_post_fetch_messages(user_input, fetched_content, focus, stage):
    return prompt_builder.build_post_fetch_messages(user_input, fetched_content, focus, stage)


# ---------- BUILD ----------

def build_messages(user_input):
    return prompt_builder.build_messages(
        user_input,
        is_agent_meta_question=is_agent_meta_question,
        is_agent_tools_question=is_agent_tools_question,
        retrieve_relevant_memory=retrieve_relevant_memory,
        is_personal_context_question=is_personal_context_question,
        retrieve_personal_context_memory=retrieve_personal_context_memory,
        is_user_purpose_query_signal=is_user_purpose_query_signal,
        retrieve_user_purpose_memory=retrieve_user_purpose_memory,
        is_agent_purpose_question=is_agent_purpose_question,
        retrieve_memory_for_purpose=retrieve_memory_for_purpose,
        build_memory_key=build_memory_key,
        retrieve_relevant_journal_entries=retrieve_relevant_journal_entries,
        is_outcome_feedback_context_relevant=is_outcome_feedback_context_relevant,
        retrieve_recent_outcome_feedback_entries=retrieve_recent_outcome_feedback_entries,
        get_current_focus=get_current_focus,
        get_current_stage=get_current_stage,
        infer_action_type=infer_action_type,
        build_action_guidance=build_action_guidance,
        detect_subtarget=detect_subtarget,
        uses_strict_forced_reply=uses_strict_forced_reply,
        is_meta_system_override_question=is_meta_system_override_question,
        is_vague_research_request=is_vague_research_request,
        build_specific_next_step=build_specific_next_step,
        apply_recent_negative_outcome_anti_repeat_guard=apply_recent_negative_outcome_anti_repeat_guard,
        build_answer_line=build_answer_line,
        project_safety_conversation_query=project_safety_conversation_query,
        format_memory_block=format_memory_block,
        format_journal_block=format_journal_block,
        format_outcome_feedback_block=format_outcome_feedback_block,
        format_recent_answer_history_block=format_recent_answer_history_block,
        get_best_recent_answer_match=get_best_recent_answer_match,
        detect_recent_answer_relevance=detect_recent_answer_relevance,
        is_strong_recent_answer_match=is_strong_recent_answer_match,
        detect_recent_answer_followup_type=detect_recent_answer_followup_type,
        detect_recent_answer_contradiction_cue=detect_recent_answer_contradiction_cue,
    )


# ---------- CORE AGENT FUNCTION ----------

def handle_user_input(user_input: str) -> str:
    global current_state

    if not current_state:
        current_state.update(load_state())

    user_input = user_input.strip()

    if not user_input:
        return "⚠️ Please type something."

    if user_input.lower() in {"exit", "quit"}:
        return "Goodbye."

    journal_result = handle_project_journal_command(user_input)
    if journal_result:
        return journal_result

    command_result = update_state_from_command(user_input)
    if command_result:
        append_project_journal(
            entry_type="state_command",
            user_input=user_input,
            response_text=command_result,
            action_type="state",
        )
        append_recent_answer_history(command_result)
        return command_result

    write_runtime_memory(user_input)
    outcome_signal = detect_outcome_feedback_signal(user_input)
    if outcome_signal:
        append_project_journal(
            entry_type="outcome_feedback",
            user_input=user_input,
            response_text="",
            action_type=infer_action_type(user_input, get_current_stage()),
            extra_fields={"outcome": outcome_signal},
        )

    focus = get_current_focus()
    stage = get_current_stage()
    action_type = infer_action_type(user_input, stage)
    force_structured_override = (
        is_meta_system_override_question(user_input, focus, stage)
        or (action_type == "research" and is_vague_research_request(user_input))
    )
    if force_structured_override:
        forced_next_step = build_specific_next_step(user_input, focus, stage, action_type)
        forced_next_step, _ = apply_recent_negative_outcome_anti_repeat_guard(
            user_input, forced_next_step
        )
        forced_answer_line = build_answer_line(
            user_input, focus, stage, action_type, forced_next_step, memories=retrieve_relevant_memory(user_input)
        )
        response = (
            "Answer:\n"
            f"{forced_answer_line}\n\n"
            "Current state:\n"
            f"Focus: {focus}\n"
            f"Stage: {stage}\n"
            f"Action type: {action_type}\n\n"
            "Next step:\n"
            f"{forced_next_step}"
        )
        append_project_journal(
            entry_type="conversation",
            user_input=user_input,
            response_text=response,
            action_type=action_type,
        )
        append_recent_answer_history(response)
        return response

    system_prompt, messages = build_messages(user_input)
    try:
        response = ask_ai(messages=messages, system_prompt=system_prompt)
    except RuntimeError as exc:
        return f"LLM configuration error: {exc}"

    tool_command = parse_tool_command(response)
    if (
        tool_command
        and tool_command["tool"] == "fetch"
        and not user_message_suppresses_tool_fetch(user_input)
    ):
        fetched_content = fetch_page(tool_command["url"])
        focus = get_current_focus()
        stage = get_current_stage()
        post_fetch_system_prompt, post_fetch_messages = build_post_fetch_messages(
            user_input=user_input,
            fetched_content=fetched_content,
            focus=focus,
            stage=stage,
        )
        try:
            final_response = ask_ai(
                messages=post_fetch_messages,
                system_prompt=post_fetch_system_prompt,
            )
        except RuntimeError as exc:
            return f"LLM configuration error: {exc}"
        append_project_journal(
            entry_type="tool_flow",
            user_input=user_input,
            response_text=final_response,
            action_type="research",
        )
        append_recent_answer_history(final_response)
        return final_response

    append_project_journal(
        entry_type="conversation",
        user_input=user_input,
        response_text=response,
        action_type=infer_action_type(user_input, get_current_stage()),
    )
    append_recent_answer_history(response)
    return response


# ---------- MAIN ----------

def main():
    global current_state

    current_state = load_state()

    check = llm_preflight_check()
    if not check["ok"]:
        print("Agent preflight failed:")
        for issue in check["issues"]:
            print(f"- {issue}")
        print()

    print("Agent ready")

    while True:
        user_input = input("You: ")

        if user_input.lower().strip() in {"exit", "quit"}:
            print("Goodbye.")
            break

        result = handle_user_input(user_input)

        print("\nAI:\n")
        print(result)
        print()


if __name__ == "__main__":
    main()