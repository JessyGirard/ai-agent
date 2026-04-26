import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from os import getenv
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from core.llm import ask_ai, llm_preflight_check
from core.persistence import (
    append_project_journal as persistence_append_project_journal,
    archive_project_journal_entries as persistence_archive_project_journal_entries,
    consume_persistence_health_events as persistence_consume_health_events,
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
from tools.brave_search import brave_search
from tools.fetch_page import fetch_failure_tag, fetch_page

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

# UI-04: treat long or multiline input as content, not bare state commands / outcome cues.
STATE_COMMAND_INPUT_MAX_CHARS = 280
OUTCOME_FEEDBACK_INPUT_MAX_CHARS = 220

# LATENCY-02: cap payload sizes before API calls (playground-only; build_messages is single-turn today).
_LATENCY_LLM_USER_MESSAGE_MAX_CHARS = 28_000
_LATENCY_POST_FETCH_BODY_MAX_CHARS = 14_000

# LATENCY-10: second LLM skip for valid but tiny fetch bodies (chars + words, deterministic).
_LATENCY10_TRIVIAL_MAX_CHARS = 100
_LATENCY10_TRIVIAL_MAX_WORDS = 12

# LATENCY-11: deterministic fetch short-circuit — display cap and empty-body line (compute once per module).
_LATENCY07_DETERMINISTIC_FETCH_ANSWER_CAP = 1200
_LATENCY07_EMPTY_FETCH_ANSWER_LINE = "The fetch did not return usable page text."

current_state = {}
RECENT_ANSWER_HISTORY_MAX = journal_service.RECENT_ANSWER_HISTORY_MAX
recent_answer_history = journal_service.make_recent_answer_history()
recent_answer_step_frames = journal_service.make_recent_answer_step_frames()
_sequence_step_cursor = 0
_last_rendered_step_index = 0


def get_sequence_step_cursor() -> int:
    return _sequence_step_cursor


def set_sequence_step_cursor(value: int) -> None:
    global _sequence_step_cursor
    try:
        _sequence_step_cursor = max(0, int(value))
    except (TypeError, ValueError):
        pass


def get_last_rendered_step_index() -> int:
    return _last_rendered_step_index


def set_last_rendered_step_index(value: int) -> None:
    global _last_rendered_step_index
    try:
        _last_rendered_step_index = max(0, int(value))
    except (TypeError, ValueError):
        pass


def clear_recent_answer_session() -> None:
    """Clear bounded recent-assistant history and parallel indexed-step frames (tests / resets)."""
    recent_answer_history.clear()
    recent_answer_step_frames.clear()
    set_sequence_step_cursor(0)
    set_last_rendered_step_index(0)


def lookup_indexed_steps_for_matched(matched_text, user_input):
    return journal_service.lookup_steps_for_matched_answer(
        matched_text, recent_answer_history, recent_answer_step_frames, user_input=user_input
    )


def _latency_truncate_text(text: str, limit: int, label: str) -> str:
    if not isinstance(text, str) or len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[{label} truncated for model context — {len(text)} chars total.]"


def _latency_limit_message_list(
    messages, *, max_turns: int = 10, max_chars_per_message: Optional[int] = None
):
    """Keep only the last ``max_turns`` chat rows and cap oversized ``content`` strings (Anthropic messages)."""
    if not messages:
        return messages
    cap = max_chars_per_message if max_chars_per_message is not None else _LATENCY_LLM_USER_MESSAGE_MAX_CHARS
    trimmed = messages[-max_turns:]
    out = []
    for m in trimmed:
        if not isinstance(m, dict):
            out.append(m)
            continue
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, str) and len(content) > cap:
            content = _latency_truncate_text(content, cap, "Message")
        elif isinstance(content, list):
            new_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    txt = part.get("text", "")
                    if isinstance(txt, str) and len(txt) > cap:
                        txt = _latency_truncate_text(txt, cap, "Message")
                    new_parts.append({**part, "text": txt})
                else:
                    new_parts.append(part)
            content = new_parts
        out.append({"role": role, "content": content})
    return out


def _merge_vision_into_messages(messages: list, user_text: str, vision_images: list) -> None:
    """Mutates ``messages``: last user turn becomes multimodal content (text + image_url parts)."""
    if not vision_images:
        return
    parts: list = [{"type": "text", "text": user_text}]
    for img in vision_images:
        if not isinstance(img, dict):
            continue
        mime = str(img.get("mime") or "image/png").strip()
        if "/" not in mime:
            mime = f"image/{mime}"
        b64 = str(img.get("b64") or "").strip()
        if not b64:
            continue
        data_url = f"data:{mime};base64,{b64}"
        parts.append(
            {"type": "image_url", "image_url": {"url": data_url, "detail": "auto"}}
        )
    for i in range(len(messages) - 1, -1, -1):
        row = messages[i]
        if isinstance(row, dict) and row.get("role") == "user":
            messages[i] = {**row, "content": parts}
            return


def drain_persistence_health_signals():
    events = persistence_consume_health_events()
    flag = (getenv("DEBUG_PERSISTENCE_HEALTH") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        for event in events:
            print(
                f"[persistence-health] {event.get('event_type')}: {event.get('detail')}"
            )
    return events


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


def _input_shape_allows_direct_state_command(line: str) -> bool:
    """True only for short, single-line input — not pasted documents or long lines."""
    if not line:
        return False
    if "\n" in line or "\r" in line:
        return False
    if len(line) > STATE_COMMAND_INPUT_MAX_CHARS:
        return False
    return True


def _input_shape_allows_outcome_feedback_heuristic(user_input: str) -> bool:
    """Outcome heuristics only for plausibly short, single-line operator reflections."""
    if not user_input:
        return False
    if "\n" in user_input or "\r" in user_input:
        return False
    if len(user_input) > OUTCOME_FEEDBACK_INPUT_MAX_CHARS:
        return False
    return True


def update_state_from_command(user_input):
    line = (user_input or "").strip()
    text = line.lower()

    if _user_discussing_state_command(line):
        return None

    if not _input_shape_allows_direct_state_command(line):
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


def append_recent_answer_history(response_text, user_input=None):
    store_indexed_steps = True
    if user_input is not None:
        ul = re.sub(r"\s+", " ", str(user_input).strip().lower())
        store_indexed_steps = journal_service.user_input_requests_full_steps_list_normalized(ul)
    journal_service.append_recent_answer_history(
        response_text,
        recent_answer_history,
        recent_answer_step_frames,
        store_indexed_steps=store_indexed_steps,
    )
    frame = recent_answer_step_frames[-1] if recent_answer_step_frames else None
    if store_indexed_steps and frame and len(frame) >= 2:
        set_sequence_step_cursor(0)
        # Keep last_rendered aligned with cursor reset (Increment 10 — stale lr + fresh cur
        # made Continue/Next advance from last_rendered while the cursor restarted).
        set_last_rendered_step_index(0)


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


_PROJECT_SNAPSHOT_SECTION_ORDER = (
    "Build / Purpose",
    "Structure / Flow",
    "Responsibilities / Rules",
    "Decisions / Progress",
    "Risks / Priorities",
    "Other Project Memory",
)


def _build_project_snapshot_prefix_rules():
    """Longer prefixes first; on equal length, earlier section in _PROJECT_SNAPSHOT_SECTION_ORDER wins."""
    order_index = {name: i for i, name in enumerate(_PROJECT_SNAPSHOT_SECTION_ORDER)}
    rules = []

    def add(prefixes, section):
        for p in prefixes:
            rules.append((p.lower(), section))

    add(
        (
            "building ",
            "the project is ",
            "this project is ",
            "the system is meant to ",
            "this system is meant to ",
            "the system is being built to ",
            "this system is being built to ",
            "the purpose of this project is ",
            "the purpose of the project is ",
        ),
        "Build / Purpose",
    )
    add(
        (
            "playground.py ",
            "memory.py ",
            "this file ",
            "this system ",
            "this part ",
            "this module ",
            "this function ",
            "the memory system ",
            "the journal ",
            "the state file ",
            "the extracted memory ",
            "the flow is ",
            "the workflow is ",
            "the pipeline is ",
            "the process is ",
            "the path is ",
            "the system flow is ",
            "the memory flow is ",
        ),
        "Structure / Flow",
    )
    add(
        (
            "playground.py is responsible for ",
            "memory.py is responsible for ",
            "this file is responsible for ",
            "this module is responsible for ",
            "this function is responsible for ",
            "the memory system is responsible for ",
            "the journal is responsible for ",
            "the state file is responsible for ",
            "the extracted memory is responsible for ",
            "the rule is ",
            "the rules are ",
            "the constraint is ",
            "the constraints are ",
            "the requirement is ",
            "the requirements are ",
            "the system must ",
            "this system must ",
            "the project must ",
            "this project must ",
        ),
        "Responsibilities / Rules",
    )
    add(
        (
            "the decision is ",
            "the decision was ",
            "the choice is ",
            "the choice was ",
            "we decided to ",
            "we chose to ",
            "the plan is to ",
            "the plan was to ",
            "the milestone is ",
            "the milestone was ",
            "the progress is ",
            "the progress was ",
            "we completed ",
            "we finished ",
            "this is complete ",
            "this is done ",
            "this part is complete ",
            "this part is done ",
        ),
        "Decisions / Progress",
    )
    add(
        (
            "the problem is ",
            "the risk is ",
            "the failure mode is ",
            "the weakness is ",
            "the issue is ",
            "the bug is ",
            "the danger is ",
            "the biggest risk is ",
            "the objective is ",
            "the objective right now is ",
            "the priority is ",
            "the priority right now is ",
            "the main priority is ",
            "the focus is to ",
            "the goal right now is ",
            "what matters most is ",
        ),
        "Risks / Priorities",
    )

    rules.sort(
        key=lambda item: (-len(item[0]), order_index[item[1]], item[0])
    )
    return tuple(rules)


_PROJECT_SNAPSHOT_PREFIX_RULES = _build_project_snapshot_prefix_rules()


def _classify_project_memory_snapshot_section(value):
    value_low = (value or "").strip().lower()
    if not value_low:
        return "Other Project Memory"
    for prefix, section in _PROJECT_SNAPSHOT_PREFIX_RULES:
        if value_low.startswith(prefix):
            return section
    return "Other Project Memory"


def _normalize_project_snapshot_value_for_dedupe(raw_value):
    """Deterministic packaging-only key: lowercase, strip, spaces, hyphen/space, trailing punct."""
    s = (raw_value or "").strip()
    if not s:
        return None
    t = s.lower()
    for ch in ("-", "\u2013", "\u2014"):
        t = t.replace(ch, " ")
    t = re.sub(r"\s+", " ", t).strip()
    trailing_safe = ".,;:!?"
    while t and t[-1] in trailing_safe:
        t = t[:-1].rstrip()
        t = re.sub(r"\s+", " ", t).strip()
    return t if t else None


def _project_snapshot_strength_key(mem):
    """Stronger row = larger tuple (used for sort and dedupe winner)."""
    trend = (mem.get("trend") or "").lower()
    trend_rank = 1 if trend == "reinforced" else 0
    evidence_count = mem.get("evidence_count", 1)
    importance = float(mem.get("importance", 0.0))
    confidence = float(mem.get("confidence", 0.0))
    value = (mem.get("value") or "").strip()
    return (trend_rank, evidence_count, importance, confidence, value)


def _project_snapshot_pick_stronger(mem_a, mem_b):
    ka, kb = _project_snapshot_strength_key(mem_a), _project_snapshot_strength_key(mem_b)
    if ka > kb:
        return mem_a
    if kb > ka:
        return mem_b
    return mem_a


def _dedupe_project_rows_for_snapshot(project_rows):
    """One pass: normalize each value once, dict key -> strongest row, stable first-seen key order."""
    best = {}
    key_order = []
    for mem in project_rows:
        raw = mem.get("value") or ""
        if not raw.strip():
            continue
        key = _normalize_project_snapshot_value_for_dedupe(raw)
        if not key:
            continue
        if key not in best:
            best[key] = mem
            key_order.append(key)
        else:
            best[key] = _project_snapshot_pick_stronger(mem, best[key])
    return [best[k] for k in key_order]


def _project_memory_snapshot_package_context(max_items):
    """Build snapshot text plus packaged mem rows (bullet order) and non-empty section count."""
    memory_items = load_memory()

    if not memory_items:
        return "", [], 0

    project_rows = []
    for mem in memory_items:
        if mem.get("category") != "project":
            continue
        if mem.get("status") != "active":
            continue
        project_rows.append(mem)

    project_rows = _dedupe_project_rows_for_snapshot(project_rows)

    project_rows.sort(key=_project_snapshot_strength_key, reverse=True)
    project_rows = project_rows[:max_items]

    section_buckets = {name: [] for name in _PROJECT_SNAPSHOT_SECTION_ORDER}
    for mem in project_rows:
        value = (mem.get("value") or "").strip()
        if not value:
            continue
        section = _classify_project_memory_snapshot_section(value)
        section_buckets[section].append(mem)

    lines = ["Project memory snapshot:", ""]
    any_bullet = False
    packaged_rows = []
    for section in _PROJECT_SNAPSHOT_SECTION_ORDER:
        mems = section_buckets[section]
        if not mems:
            continue
        lines.append(f"{section}:")
        for mem in mems:
            value = (mem.get("value") or "").strip()
            if not value:
                continue
            packaged_rows.append(mem)
            evidence_count = mem.get("evidence_count", 1)
            confidence = mem.get("confidence", 0.0)
            lines.append(
                f"- {value} [evidence={evidence_count}, confidence={confidence:.2f}]"
            )
            any_bullet = True

    if not any_bullet:
        return "", [], 0

    section_count = sum(1 for sec in _PROJECT_SNAPSHOT_SECTION_ORDER if section_buckets[sec])
    return "\n".join(lines).rstrip(), packaged_rows, section_count


def build_project_memory_snapshot(max_items=12):
    snapshot, _, _ = _project_memory_snapshot_package_context(max_items)
    return snapshot


def show_project_memory_snapshot():
    snapshot = build_project_memory_snapshot()
    return snapshot or "No active project memory available."


def _count_project_memory_snapshot_bullet_lines(snapshot):
    """Count snapshot lines that are project bullet rows (same as visual bullets)."""
    return sum(1 for line in snapshot.splitlines() if line.startswith("- "))


def _count_project_memory_snapshot_strengths(project_rows):
    reinforced = 0
    new = 0

    for mem in project_rows:
        trend = (mem.get("trend") or "").lower()
        if trend == "reinforced":
            reinforced += 1
        elif trend == "new":
            new += 1

    return reinforced, new


def _build_project_memory_package_top_priorities(packaged_rows, max_priority_items=3):
    """PACKAGING-02: first ``max_priority_items`` non-empty ``value`` rows in ``packaged_rows`` order, or ``\"\"``."""
    if not packaged_rows:
        return ""

    lines = ["Top project priorities:"]
    count = 0

    for mem in packaged_rows:
        value = (mem.get("value") or "").strip()
        if not value:
            continue
        lines.append(f"- {value}")
        count += 1
        if count >= max_priority_items:
            break

    if count == 0:
        return ""

    return "\n".join(lines)


def _compile_project_memory_package_risk_patterns():
    """PACKAGING-04: whole-word, case-insensitive patterns; ``problem`` skips idiomatic ``no problem``."""
    out = []
    for kw in (
        "problem",
        "risk",
        "bug",
        "failure mode",
        "blocker",
        "concern",
        "issue",
    ):
        if kw == "failure mode":
            out.append(re.compile(r"\bfailure\s+mode\b", re.I))
        elif kw == "problem":
            out.append(re.compile(r"(?<!no )\bproblem\b", re.I))
        else:
            out.append(re.compile(rf"\b{re.escape(kw)}\b", re.I))
    return tuple(out)


_PROJECT_MEMORY_PACKAGE_RISK_PATTERNS = _compile_project_memory_package_risk_patterns()


def _value_matches_project_memory_risk_keyword(value):
    if not (value or "").strip():
        return False
    return any(p.search(value) for p in _PROJECT_MEMORY_PACKAGE_RISK_PATTERNS)


def _build_project_memory_package_current_risks(packaged_rows, max_risk_items=2):
    """PACKAGING-03/04: first ``max_risk_items`` rows whose ``value`` matches a risk keyword (whole words)."""
    if not packaged_rows:
        return ""

    lines = ["Current project risks:"]
    count = 0

    for mem in packaged_rows:
        value = (mem.get("value") or "").strip()
        if not value:
            continue
        if not _value_matches_project_memory_risk_keyword(value):
            continue
        lines.append(f"- {value}")
        count += 1
        if count >= max_risk_items:
            break

    if count == 0:
        return ""

    return "\n".join(lines)


def _compile_project_memory_package_decision_patterns():
    """PACKAGING-05: whole-word / phrase patterns for decision-like project lines."""
    out = []
    phrases = (
        r"\bgoing\s+with\b",
        r"\bwill\s+use\b",
        r"\bmove\s+to\b",
    )
    for pat in phrases:
        out.append(re.compile(pat, re.I))
    for kw in (
        "decision",
        "decided",
        "chose",
        "chosen",
        "plan",
        "planned",
    ):
        out.append(re.compile(rf"\b{re.escape(kw)}\b", re.I))
    return tuple(out)


_PROJECT_MEMORY_PACKAGE_DECISION_PATTERNS = _compile_project_memory_package_decision_patterns()


def _value_matches_project_memory_decision_keyword(value):
    if not (value or "").strip():
        return False
    return any(p.search(value) for p in _PROJECT_MEMORY_PACKAGE_DECISION_PATTERNS)


def _build_project_memory_package_current_decisions(packaged_rows, max_decision_items=2):
    """PACKAGING-05: first ``max_decision_items`` rows whose ``value`` matches a decision keyword."""
    if not packaged_rows:
        return ""

    lines = ["Current project decisions:"]
    count = 0

    for mem in packaged_rows:
        value = (mem.get("value") or "").strip()
        if not value:
            continue
        if not _value_matches_project_memory_decision_keyword(value):
            continue
        lines.append(f"- {value}")
        count += 1
        if count >= max_decision_items:
            break

    if count == 0:
        return ""

    return "\n".join(lines)


def _compile_project_memory_package_progress_patterns():
    """PACKAGING-06: whole-word patterns for progress / completion-like project lines."""
    out = []
    for kw in (
        "completed",
        "done",
        "finished",
        "milestone",
        "progress",
        "shipped",
        "working",
        "validated",
        "passing",
    ):
        out.append(re.compile(rf"\b{re.escape(kw)}\b", re.I))
    return tuple(out)


_PROJECT_MEMORY_PACKAGE_PROGRESS_PATTERNS = _compile_project_memory_package_progress_patterns()


def _value_matches_project_memory_progress_keyword(value):
    if not (value or "").strip():
        return False
    return any(p.search(value) for p in _PROJECT_MEMORY_PACKAGE_PROGRESS_PATTERNS)


def _build_project_memory_package_current_progress(packaged_rows, max_progress_items=2):
    """PACKAGING-06: first ``max_progress_items`` rows whose ``value`` matches a progress keyword."""
    if not packaged_rows:
        return ""

    lines = ["Current project progress:"]
    count = 0

    for mem in packaged_rows:
        value = (mem.get("value") or "").strip()
        if not value:
            continue
        if not _value_matches_project_memory_progress_keyword(value):
            continue
        lines.append(f"- {value}")
        count += 1
        if count >= max_progress_items:
            break

    if count == 0:
        return ""

    return "\n".join(lines)


def _compile_project_memory_package_next_steps_patterns():
    """PACKAGING-07: whole-word / phrase patterns for upcoming / planned-work lines."""
    out = []
    phrases = (
        r"\bnext\s+steps\b",
        r"\bnext\s+step\b",
        r"\bgoing\s+to\b",
        r"\bneed\s+to\b",
        r"\bto\s+do\b",
    )
    for pat in phrases:
        out.append(re.compile(pat, re.I))
    for kw in (
        "next",
        "plan",
        "planning",
        "upcoming",
        "will",
        "todo",
    ):
        out.append(re.compile(rf"\b{re.escape(kw)}\b", re.I))
    return tuple(out)


_PROJECT_MEMORY_PACKAGE_NEXT_STEPS_PATTERNS = _compile_project_memory_package_next_steps_patterns()


def _value_matches_project_memory_next_steps_keyword(value):
    if not (value or "").strip():
        return False
    return any(p.search(value) for p in _PROJECT_MEMORY_PACKAGE_NEXT_STEPS_PATTERNS)


def _build_project_memory_package_next_steps(packaged_rows, max_next_step_items=2):
    """PACKAGING-07: first ``max_next_step_items`` rows whose ``value`` matches a next-steps keyword."""
    if not packaged_rows:
        return ""

    lines = ["Next project steps:"]
    count = 0

    for mem in packaged_rows:
        value = (mem.get("value") or "").strip()
        if not value:
            continue
        if not _value_matches_project_memory_next_steps_keyword(value):
            continue
        lines.append(f"- {value}")
        count += 1
        if count >= max_next_step_items:
            break

    if count == 0:
        return ""

    return "\n".join(lines)


def _join_project_memory_package_prefaces(
    top_priorities, current_risks, current_decisions, current_progress, next_steps
):
    """Non-empty preface blocks in order; trailing ``\\n\\n`` only when at least one block."""
    parts = []
    for block in (
        top_priorities,
        current_risks,
        current_decisions,
        current_progress,
        next_steps,
    ):
        if block:
            parts.append(block)
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n\n"


def _count_project_memory_snapshot_sections(snapshot):
    if not snapshot:
        return 0

    section_headers = (
        "Build / Purpose:",
        "Structure / Flow:",
        "Responsibilities / Rules:",
        "Decisions / Progress:",
        "Risks / Priorities:",
        "Other Project Memory:",
    )

    count = 0
    for line in snapshot.splitlines():
        if line in section_headers:
            count += 1
    return count


def build_project_memory_package(max_items=12, compact=False):
    snapshot, packaged_rows, section_count = _project_memory_snapshot_package_context(
        max_items
    )
    if not snapshot:
        return ""

    row_count = len(packaged_rows)
    reinforced_count, new_count = _count_project_memory_snapshot_strengths(
        packaged_rows
    )
    top_priorities = _build_project_memory_package_top_priorities(packaged_rows)
    current_risks = _build_project_memory_package_current_risks(packaged_rows)
    current_decisions = _build_project_memory_package_current_decisions(packaged_rows)
    current_progress = _build_project_memory_package_current_progress(packaged_rows)
    next_steps = _build_project_memory_package_next_steps(packaged_rows)
    preface_block = _join_project_memory_package_prefaces(
        top_priorities, current_risks, current_decisions, current_progress, next_steps
    )

    if compact:
        return (
            "Packaged project memory:\n"
            "Use as reliable background context.\n"
            f"Packaged project rows: {row_count}\n"
            f"Packaged sections: {section_count}\n"
            f"Packaged strengths: reinforced={reinforced_count}, new={new_count}\n\n"
            f"{preface_block}"
            f"{snapshot}"
        )

    return (
        "You are given a packaged project memory.\n"
        "Treat it as reliable background context about the system.\n"
        "Use it to guide reasoning, prioritization, and technical decisions.\n"
        "Do not invent facts outside this memory unless explicitly required.\n"
        f"Packaged project rows: {row_count}\n"
        f"Packaged sections: {section_count}\n"
        f"Packaged strengths: reinforced={reinforced_count}, new={new_count}\n\n"
        f"{preface_block}"
        f"{snapshot}"
    )


def show_project_memory_package(compact=False):
    package = build_project_memory_package(compact=compact)
    return package or "No packaged project memory available."


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


def _memory01_explicit_project_runtime_candidate(user_input):
    """
    Narrow second-stage extraction: explicit project/system statements only.
    Runs after memory_service.extract_runtime_memory_candidate (preference, goal,
    identity, and existing project prefixes stay unchanged).
    """
    raw = (user_input or "").strip()
    if not raw or "?" in raw:
        return None
    prefixes = (
        "the project is ",
        "this project is ",
        "the system is meant to ",
        "this system is meant to ",
        "the system is being built to ",
        "this system is being built to ",
        "the purpose of this project is ",
        "the purpose of the project is ",
    )
    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue
        low = text.lower()
        if memory_service.is_transient_identity_statement(low):
            continue
        for p in prefixes:
            if low.startswith(p):
                rest = text[len(p) :].strip()
                if len(rest) < 3:
                    continue
                return memory_service.make_runtime_memory_candidate("project", text, low)
    return None


def _memory02_build_intent_runtime_candidate(user_input):
    raw = (user_input or "").strip()
    if not raw or "?" in raw:
        return None

    prefixes = (
        "i am building ",
        "i'm building ",
    )

    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue

        low = text.lower()

        if memory_service.is_transient_identity_statement(low):
            continue

        for p in prefixes:
            if low.startswith(p):
                rest = text[len(p) :].strip()

                if len(rest) < 5:
                    continue

                if "maybe" in low or "might" in low or "want to" in low:
                    continue

                return memory_service.make_runtime_memory_candidate("project", text, low)

    return None


def _memory03_project_structure_runtime_candidate(user_input):
    raw = (user_input or "").strip()
    if not raw or "?" in raw:
        return None

    prefixes = (
        "playground.py ",
        "memory.py ",
        "this file ",
        "this system ",
        "this part ",
        "this module ",
        "this function ",
        "the memory system ",
        "the journal ",
        "the state file ",
        "the extracted memory ",
    )

    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue

        low = text.lower()

        if memory_service.is_transient_identity_statement(low):
            continue

        for p in prefixes:
            if low.startswith(p):
                rest = text[len(p) :].strip()

                # Lines like "playground.py is responsible for …" are owned by MEMORY-05
                # (stricter tail after the full responsibility prefix).
                if rest.lower().startswith("is responsible for "):
                    continue

                # "this system must …" / similar: owned by MEMORY-06 (rule / constraint prefixes).
                if rest.lower().startswith("must "):
                    continue

                # "this part is done …" / "this part is complete …": owned by MEMORY-08 (milestone prefixes).
                if rest.lower().startswith("is done ") or rest.lower().startswith("is complete "):
                    continue

                if len(rest) < 8:
                    continue

                return memory_service.make_runtime_memory_candidate("project", text, low)

    return None


def _memory04_project_flow_runtime_candidate(user_input):
    raw = (user_input or "").strip()
    if not raw or "?" in raw:
        return None

    prefixes = (
        "the flow is ",
        "the workflow is ",
        "the pipeline is ",
        "the process is ",
        "the path is ",
        "the system flow is ",
        "the memory flow is ",
    )

    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue

        low = text.lower()

        if memory_service.is_transient_identity_statement(low):
            continue

        for p in prefixes:
            if low.startswith(p):
                rest = text[len(p) :].strip()

                if len(rest) < 8:
                    continue

                return memory_service.make_runtime_memory_candidate("project", text, low)

    return None


def _memory05_project_responsibility_runtime_candidate(user_input):
    raw = (user_input or "").strip()
    if not raw or "?" in raw:
        return None

    prefixes = (
        "playground.py is responsible for ",
        "memory.py is responsible for ",
        "this file is responsible for ",
        "this module is responsible for ",
        "this function is responsible for ",
        "the memory system is responsible for ",
        "the journal is responsible for ",
        "the state file is responsible for ",
        "the extracted memory is responsible for ",
    )

    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue

        low = text.lower()

        if memory_service.is_transient_identity_statement(low):
            continue

        for p in prefixes:
            if low.startswith(p):
                rest = text[len(p) :].strip()

                if len(rest) < 8:
                    continue

                return memory_service.make_runtime_memory_candidate("project", text, low)

    return None


def _memory06_project_rule_runtime_candidate(user_input):
    raw = (user_input or "").strip()
    if not raw or "?" in raw:
        return None

    prefixes = (
        "the rule is ",
        "the rules are ",
        "the constraint is ",
        "the constraints are ",
        "the requirement is ",
        "the requirements are ",
        "the system must ",
        "this system must ",
        "the project must ",
        "this project must ",
    )

    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue

        low = text.lower()

        if memory_service.is_transient_identity_statement(low):
            continue

        for p in prefixes:
            if low.startswith(p):
                rest = text[len(p) :].strip()

                if len(rest) < 8:
                    continue

                return memory_service.make_runtime_memory_candidate("project", text, low)

    return None


def _memory07_project_decision_runtime_candidate(user_input):
    raw = (user_input or "").strip()
    if not raw or "?" in raw:
        return None

    prefixes = (
        "the decision is ",
        "the decision was ",
        "the choice is ",
        "the choice was ",
        "we decided to ",
        "we chose to ",
        "the plan is to ",
        "the plan was to ",
    )

    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue

        low = text.lower()

        if memory_service.is_transient_identity_statement(low):
            continue

        for p in prefixes:
            if low.startswith(p):
                rest = text[len(p) :].strip()

                if len(rest) < 8:
                    continue

                return memory_service.make_runtime_memory_candidate("project", text, low)

    return None


def _memory08_project_progress_runtime_candidate(user_input):
    raw = (user_input or "").strip()
    if not raw or "?" in raw:
        return None

    prefixes = (
        "the milestone is ",
        "the milestone was ",
        "the progress is ",
        "the progress was ",
        "we completed ",
        "we finished ",
        "this is complete ",
        "this is done ",
        "this part is complete ",
        "this part is done ",
    )

    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue

        low = text.lower()

        if memory_service.is_transient_identity_statement(low):
            continue

        for p in prefixes:
            if low.startswith(p):
                rest = text[len(p) :].strip()

                if len(rest) < 8:
                    continue

                return memory_service.make_runtime_memory_candidate("project", text, low)

    return None


def _memory09_project_risk_runtime_candidate(user_input):
    raw = (user_input or "").strip()
    if not raw or "?" in raw:
        return None

    prefixes = (
        "the problem is ",
        "the risk is ",
        "the failure mode is ",
        "the weakness is ",
        "the issue is ",
        "the bug is ",
        "the danger is ",
        "the biggest risk is ",
    )

    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue

        low = text.lower()

        if memory_service.is_transient_identity_statement(low):
            continue

        for p in prefixes:
            if low.startswith(p):
                rest = text[len(p) :].strip()

                if len(rest) < 8:
                    continue

                return memory_service.make_runtime_memory_candidate("project", text, low)

    return None


def _memory10_project_priority_runtime_candidate(user_input):
    raw = (user_input or "").strip()
    if not raw or "?" in raw:
        return None

    prefixes = (
        "the objective is ",
        "the objective right now is ",
        "the priority is ",
        "the priority right now is ",
        "the main priority is ",
        "the focus is to ",
        "the goal right now is ",
        "what matters most is ",
    )

    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue

        low = text.lower()

        if memory_service.is_transient_identity_statement(low):
            continue

        for p in prefixes:
            if low.startswith(p):
                rest = text[len(p) :].strip()

                if len(rest) < 8:
                    continue

                return memory_service.make_runtime_memory_candidate("project", text, low)

    return None


def _extract_runtime_memory_candidate_chained(user_input):
    c = memory_service.extract_runtime_memory_candidate(user_input)
    if c:
        return c

    c = _memory01_explicit_project_runtime_candidate(user_input)
    if c:
        return c

    c = _memory02_build_intent_runtime_candidate(user_input)
    if c:
        return c

    c = _memory03_project_structure_runtime_candidate(user_input)
    if c:
        return c

    c = _memory04_project_flow_runtime_candidate(user_input)
    if c:
        return c

    c = _memory05_project_responsibility_runtime_candidate(user_input)
    if c:
        return c

    c = _memory06_project_rule_runtime_candidate(user_input)
    if c:
        return c

    c = _memory07_project_decision_runtime_candidate(user_input)
    if c:
        return c

    c = _memory08_project_progress_runtime_candidate(user_input)
    if c:
        return c

    c = _memory09_project_risk_runtime_candidate(user_input)
    if c:
        return c

    return _memory10_project_priority_runtime_candidate(user_input)


def extract_runtime_memory_candidate(user_input):
    return _extract_runtime_memory_candidate_chained(user_input)


def next_runtime_memory_id(memory_items):
    return memory_service.next_runtime_memory_id(memory_items)


def create_runtime_memory_item(memory_items, category, value):
    return memory_service.create_runtime_memory_item(memory_items, category, value)


def merge_runtime_memory(existing_item):
    return memory_service.merge_runtime_memory(existing_item)


def write_runtime_memory(user_input):
    return memory_service.write_runtime_memory(
        user_input,
        ALLOWED_MEMORY_CATEGORIES,
        load_memory_payload,
        save_memory_payload,
        extract_candidate=_extract_runtime_memory_candidate_chained,
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
    # LATENCY-07: require a single-line, full-string tool invocation (no extra prose).
    if "\n" in response_text or "\r" in response_text:
        return None
    match_fetch = re.fullmatch(r"TOOL:fetch\s+(https?://\S+)", response_text)
    if match_fetch:
        url = match_fetch.group(1)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        return {
            "tool": "fetch",
            "url": url,
        }

    match_brave = re.fullmatch(r"TOOL:brave_search\s+(.+)", response_text)
    if match_brave:
        query = (match_brave.group(1) or "").strip()
        if not query:
            return None
        return {
            "tool": "brave_search",
            "query": query,
        }
    return None


def _format_brave_search_result_for_post_tool(search_result: dict) -> str:
    if not isinstance(search_result, dict):
        return "Brave search failed: invalid tool result."
    if not search_result.get("ok"):
        return str(search_result.get("error") or "Brave search failed.")
    rows = search_result.get("results") or []
    lines = ["BRAVE RESULT", f"Query: {search_result.get('query', '')}".strip()]
    lines.append("Sources:")
    if not rows:
        lines.append("- No sources were available.")
        return "\n".join(lines)

    source_rows: list[tuple[str, str]] = []
    for row in rows:
        title = str((row or {}).get("title") or "").strip() or "(untitled)"
        url = str((row or {}).get("url") or "").strip()
        if not url:
            continue
        source_rows.append((title, url))
        if len(source_rows) >= 3:
            break
    if not source_rows:
        lines.append("- No sources were available.")
    else:
        for title, url in source_rows:
            lines.append(f"- {title} — {url}")

    lines.append("Snippets:")
    for i, row in enumerate(rows[:5], start=1):
        title = str((row or {}).get("title") or "").strip()
        snippet = str((row or {}).get("snippet") or "").strip()
        url = str((row or {}).get("url") or "").strip()
        lines.append(f"{i}. {title or '(untitled)'}")
        if snippet:
            lines.append(f"Snippet: {snippet}")
        lines.append("")
    return "\n".join(lines).strip()


_URL_IN_USER_RE = re.compile(r"https?://[^\s<>\"'\)]+", re.IGNORECASE)
_POST_FETCH_QUOTED_SPAN_RE = re.compile(r'(["“])([^"\n“”]{3,280}?)(["”])')
_RUNTIME_PRIORITY_DIRECT_MARKERS = (
    "revenue",
    "income",
    "earn",
    "earned",
    "paid",
    "client",
    "customer",
    "sale",
    "sales",
    "outreach",
    "prospect",
    "lead",
)


def _extract_first_fetchable_url(text: str) -> str | None:
    """First http(s) URL in user text, validated with urlparse (minimal detector)."""
    if not text or not isinstance(text, str):
        return None
    for m in _URL_IN_USER_RE.finditer(text):
        raw = m.group(0).rstrip(").,;]")
        parsed = urlparse(raw)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return raw
    return None


def _extract_fetchable_urls(text: str, *, max_urls: int = 2) -> list[str]:
    """Ordered unique http(s) URLs in user text, capped for deterministic forced-fetch behavior."""
    if not text or not isinstance(text, str):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _URL_IN_USER_RE.finditer(text):
        raw = m.group(0).rstrip(").,;]")
        parsed = urlparse(raw)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        out.append(raw)
        if len(out) >= max_urls:
            break
    return out


def _merge_fetched_sources_for_prompt(sources: list[tuple[str, str]]) -> str:
    """Label and merge multiple fetched sources for a single post-fetch prompt."""
    blocks: list[str] = []
    for idx, (url, body) in enumerate(sources, start=1):
        blocks.append(f"=== SOURCE {idx}: {url} ===\n{body}")
    return "\n\n".join(blocks).strip()


def _extract_explicit_web_search_query(user_input: str) -> str | None:
    """Routing-level hard trigger for explicit web-search intent (Increment 3D)."""
    if not user_input or not isinstance(user_input, str):
        return None
    ul = re.sub(r"\s+", " ", user_input.strip().lower())
    if not ul:
        return None
    if not (
        re.search(r"\bsearch\s+the\s+web\b", ul)
        or re.search(r"\blook\s+up\b", ul)
        or re.search(r"\bfind\b", ul)
    ):
        return None
    q = ul
    q = re.sub(r"^\s*search\s+the\s+web\s+for\s+", "", q)
    q = re.sub(r"^\s*search\s+the\s+web\s*", "", q)
    q = re.sub(r"^\s*look\s+up\s+", "", q)
    q = re.sub(r"^\s*find\s+", "", q)
    q = re.sub(r"^\s*for\s+", "", q)
    q = q.strip(" .!?")
    return q or None


def _strip_unsupported_quoted_spans(response_text: str, fetched_for_llm: str) -> tuple[str, bool]:
    """Remove quote delimiters for spans that are not literal substrings of fetched content."""
    if not response_text or not fetched_for_llm:
        return response_text, False
    changed = False

    def _replace(match: re.Match) -> str:
        nonlocal changed
        span = (match.group(2) or "").strip()
        if len(span) < 3:
            return match.group(0)
        if span in fetched_for_llm:
            return match.group(0)
        changed = True
        # Keep wording for continuity, but remove verbatim-quote claim.
        return span

    sanitized = _POST_FETCH_QUOTED_SPAN_RE.sub(_replace, response_text)
    return sanitized, changed


def _forced_fetch_preview_and_digest(body: str) -> tuple[str, str]:
    raw = "" if body is None else str(body)
    preview = raw[:400].replace("\n", " ").strip()
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    return preview, digest


def _runtime_decision_or_planning_query(user_input: str) -> bool:
    return prompt_builder.user_input_is_decision_or_planning_question(user_input)


def _runtime_primary_user_priority(user_input: str) -> str:
    """Top high-priority active memory value for runtime decision enforcement."""
    purpose_pool = list(retrieve_user_purpose_memory(user_input, limit=2))
    if not purpose_pool:
        purpose_pool = list(retrieve_memory_for_purpose(user_input, k=6))
    selected = prompt_builder.select_high_priority_active_memories(purpose_pool, top_n=1)
    if not selected:
        return ""
    return str(selected[0].get("value", "")).strip()


def _next_step_supports_user_priority(next_step: str, priority_value: str) -> bool:
    if not next_step or not priority_value:
        return False
    step_low = next_step.lower()
    priority_low = priority_value.lower()
    if any(m in priority_low for m in _RUNTIME_PRIORITY_DIRECT_MARKERS):
        return any(m in step_low for m in _RUNTIME_PRIORITY_DIRECT_MARKERS)
    step_tokens = set(re.findall(r"[a-z0-9$]+", step_low))
    priority_tokens = {
        t
        for t in re.findall(r"[a-z0-9$]+", priority_low)
        if len(t) >= 4 or "$" in t
    }
    if not priority_tokens:
        return False
    return len(step_tokens.intersection(priority_tokens)) >= 2


def _enforce_user_priority_next_step(next_step: str, priority_value: str) -> str:
    """Runtime guard for structured decision/planning outputs."""
    if not priority_value:
        return next_step
    if _next_step_supports_user_priority(next_step, priority_value):
        return next_step
    priority_low = priority_value.lower()
    if any(m in priority_low for m in _RUNTIME_PRIORITY_DIRECT_MARKERS):
        return (
            f"Take one revenue/client-acquisition action today that directly advances USER PRIORITY: "
            f"{priority_value}."
        )
    return f"Take one concrete action today that directly advances USER PRIORITY: {priority_value}."


def _journal_forced_fetch_audit(
    journal_display_user: str,
    *,
    event: str,
    url: str,
    fetch_ok: bool | None,
    failure_tag: str | None,
    preview: str,
    digest: str,
) -> None:
    append_project_journal(
        entry_type="tool_flow",
        user_input=journal_display_user,
        response_text=f"forced_url_fetch_{event}",
        action_type="research",
        extra_fields={
            "forced_fetch_url": url,
            "forced_fetch_event": event,
            "forced_fetch_ok": fetch_ok,
            "forced_fetch_failure_tag": failure_tag,
            "forced_fetch_sha256": digest,
            "forced_fetch_preview": preview,
        },
    )


def _complete_fetch_after_load(
    user_input: str,
    journal_display_user: str,
    focus: str,
    stage: str,
    fetch_url: str,
    fetched_content,
) -> str:
    """Shared tail: normalize fetch payload → deterministic shortcut or post-fetch LLM → journal."""
    fetch_raw_norm = (
        (fetched_content if isinstance(fetched_content, str) else str(fetched_content)).strip()
    )
    fetch_raw_is_empty = not fetch_raw_norm
    fetched_for_llm = _latency_truncate_text(
        fetch_raw_norm,
        _LATENCY_POST_FETCH_BODY_MAX_CHARS,
        "Fetched content",
    )
    fetched_stripped = (fetched_for_llm or "").strip()
    fetched_stripped_is_empty = not fetched_stripped
    fetched_stripped_len = len(fetched_stripped)
    if fetched_stripped_len <= _LATENCY10_TRIVIAL_MAX_CHARS:
        fetched_stripped_word_count = len(fetched_stripped.split())
    else:
        fetched_stripped_word_count = 0
    failure_tag_raw = fetch_failure_tag(fetch_raw_norm)
    failure_tag_stripped = fetch_failure_tag(fetched_stripped)
    fetch_raw_has_failure_tag = failure_tag_raw is not None
    fetch_stripped_has_failure_tag = failure_tag_stripped is not None
    fetch_raw_has_alnum = any(ch.isalnum() for ch in fetch_raw_norm)
    fetch_raw_no_alnum = not fetch_raw_has_alnum
    if _latency08_should_skip_second_llm(
        fetch_raw_norm,
        fetched_stripped,
        fetch_raw_has_failure_tag=fetch_raw_has_failure_tag,
        fetch_stripped_has_failure_tag=fetch_stripped_has_failure_tag,
        fetch_raw_no_alnum=fetch_raw_no_alnum,
        fetched_stripped_is_empty=fetched_stripped_is_empty,
        fetch_raw_is_empty=fetch_raw_is_empty,
    ) or _latency10_is_trivially_small(
        fetch_raw_norm,
        fetched_stripped,
        fetch_raw_has_failure_tag=fetch_raw_has_failure_tag,
        fetch_stripped_has_failure_tag=fetch_stripped_has_failure_tag,
        fetched_stripped_is_empty=fetched_stripped_is_empty,
        fetched_stripped_len=fetched_stripped_len,
        fetched_stripped_word_count=fetched_stripped_word_count,
    ):
        final_response = _latency07_deterministic_fetch_reply(
            fetched_for_llm=fetched_for_llm,
            focus=focus,
            stage=stage,
        )
        append_project_journal(
            entry_type="tool_flow",
            user_input=journal_display_user,
            response_text=final_response,
            action_type="research",
        )
        append_recent_answer_history(final_response, user_input=user_input)
        return final_response
    post_fetch_max_turns = 6
    post_fetch_system_prompt, post_fetch_messages = build_post_fetch_messages(
        user_input=user_input,
        fetched_content=fetched_for_llm,
        focus=focus,
        stage=stage,
        fetch_url=fetch_url,
    )
    post_fetch_messages = _latency_limit_message_list(
        post_fetch_messages, max_turns=post_fetch_max_turns
    )
    try:
        final_response = ask_ai(
            messages=post_fetch_messages,
            system_prompt=post_fetch_system_prompt,
        )
    except RuntimeError as exc:
        return f"LLM configuration error: {exc}"
    final_response, _ = _strip_unsupported_quoted_spans(final_response, fetched_for_llm)
    append_project_journal(
        entry_type="tool_flow",
        user_input=journal_display_user,
        response_text=final_response,
        action_type="research",
    )
    append_recent_answer_history(final_response, user_input=user_input)
    return final_response


def _latency08_should_skip_second_llm(
    fetch_raw_norm: str,
    fetched_stripped: str,
    *,
    fetch_raw_has_failure_tag: bool,
    fetch_stripped_has_failure_tag: bool,
    fetch_raw_no_alnum: bool,
    fetched_stripped_is_empty: bool,
    fetch_raw_is_empty: bool,
) -> bool:
    """LATENCY-08/09: skip second ask_ai when fetch output is unusable after normalization/truncation.

    ``fetched_stripped`` must be ``(fetched_for_llm or "").strip()`` — computed once by the caller
    so this function does not repeat truncate/strip work (LATENCY-09).

    ``fetch_raw_has_failure_tag`` must be ``fetch_failure_tag(fetch_raw_norm) is not None`` (LATENCY-18).
    ``fetch_stripped_has_failure_tag`` must be ``fetch_failure_tag(fetched_stripped) is not None`` (LATENCY-19).
    ``fetch_raw_no_alnum`` must be ``not any(ch.isalnum() for ch in fetch_raw_norm)`` (LATENCY-14 scan + LATENCY-17).
    ``fetched_stripped_is_empty`` must be ``not fetched_stripped`` (LATENCY-15: compute once).
    ``fetch_raw_is_empty`` must be ``not fetch_raw_norm`` (LATENCY-16: compute once).
    """
    if fetch_raw_is_empty:
        return True
    if fetch_raw_has_failure_tag:
        return True
    if fetched_stripped_is_empty:
        return True
    if fetch_stripped_has_failure_tag:
        return True
    # No letters/digits at all — punctuation/whitespace-only blobs are not worth a second pass.
    if fetch_raw_no_alnum:
        return True
    return False


def _latency10_is_trivially_small(
    fetch_raw_norm: str,
    fetched_stripped: str,
    *,
    fetch_raw_has_failure_tag: bool,
    fetch_stripped_has_failure_tag: bool,
    fetched_stripped_is_empty: bool,
    fetched_stripped_len: int,
    fetched_stripped_word_count: int,
) -> bool:
    """True when fetch is valid (no failure tag) but too small for a useful second LLM pass (LATENCY-10).

    ``fetch_raw_has_failure_tag`` must be ``fetch_failure_tag(fetch_raw_norm) is not None`` (LATENCY-18).
    ``fetch_stripped_has_failure_tag`` must be ``fetch_failure_tag(fetched_stripped) is not None`` (LATENCY-19).
    ``fetched_stripped_len`` must be ``len(fetched_stripped)`` (LATENCY-20).
    ``fetched_stripped_word_count`` must be ``len(fetched_stripped.split())`` when
    ``fetched_stripped_len <= _LATENCY10_TRIVIAL_MAX_CHARS``; otherwise a placeholder (never read after char-cap fail) (LATENCY-21).
    ``fetched_stripped_is_empty`` must be ``not fetched_stripped`` (LATENCY-15).
    """
    if fetched_stripped_is_empty:
        return False
    if fetch_raw_has_failure_tag or fetch_stripped_has_failure_tag:
        return False

    if fetched_stripped_len > _LATENCY10_TRIVIAL_MAX_CHARS:
        return False

    if fetched_stripped_word_count > _LATENCY10_TRIVIAL_MAX_WORDS:
        return False
    return True


def _latency07_structured_fetch_reply_tail(*, focus: str, stage: str, next_step: str) -> str:
    """LATENCY-11: ``Current state`` + ``Next step`` block for deterministic post-fetch shape (research)."""
    return (
        "Current state:\n"
        f"Focus: {focus}\n"
        f"Stage: {stage}\n"
        "Action type: research\n\n"
        "Next step:\n"
        f"{next_step}"
    )


def _latency07_deterministic_fetch_reply(*, fetched_for_llm: str, focus: str, stage: str) -> str:
    """Structured reply matching the normal post-fetch shape without a second LLM call (LATENCY-07/08/10)."""
    forced_next_step = choose_post_fetch_next_step(fetched_for_llm)
    body = (fetched_for_llm or "").strip()
    if not body:
        answer_line = _LATENCY07_EMPTY_FETCH_ANSWER_LINE
    else:
        cap = _LATENCY07_DETERMINISTIC_FETCH_ANSWER_CAP
        blen = len(body)
        if blen > cap:
            answer_line = body[:cap] + "…"
        else:
            answer_line = body
    tail = _latency07_structured_fetch_reply_tail(
        focus=focus, stage=stage, next_step=forced_next_step
    )
    return f"Answer:\n{answer_line}\n\n{tail}"


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


def build_post_fetch_messages(user_input, fetched_content, focus, stage, fetch_url=None):
    return prompt_builder.build_post_fetch_messages(
        user_input, fetched_content, focus, stage, fetch_url=fetch_url
    )


# ---------- BUILD ----------

def build_messages(user_input, runtime_context=None):
    return prompt_builder.build_messages(
        user_input,
        runtime_context=runtime_context,
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
        lookup_indexed_steps_for_matched=lookup_indexed_steps_for_matched,
        get_sequence_step_cursor=get_sequence_step_cursor,
        set_sequence_step_cursor=set_sequence_step_cursor,
        get_last_rendered_step_index=get_last_rendered_step_index,
        set_last_rendered_step_index=set_last_rendered_step_index,
    )


# ---------- CORE AGENT FUNCTION ----------

def handle_user_input(
    user_input: str, vision_images: list | None = None, runtime_context=None
) -> str:
    global current_state

    if not current_state:
        current_state.update(load_state())
        drain_persistence_health_signals()

    vision_images = list(vision_images or [])
    stripped = (user_input or "").strip()
    if not stripped and not vision_images:
        return "⚠️ Please type something or attach at least one screenshot."
    if not stripped and vision_images:
        user_input = (
            "Please describe what you see in the screenshot(s) and answer helpfully."
        )
    else:
        user_input = stripped

    if user_input.lower() in {"exit", "quit"}:
        return "Goodbye."

    journal_result = handle_project_journal_command(user_input)
    if journal_result:
        return journal_result

    command_result = update_state_from_command(user_input)
    if command_result:
        append_project_journal(
            entry_type="state_command",
            user_input=stripped,
            response_text=command_result,
            action_type="state",
        )
        append_recent_answer_history(command_result, user_input=stripped)
        return command_result

    write_runtime_memory(user_input)
    journal_display_user = (
        f"{user_input}\n[{len(vision_images)} screenshot(s)]"
        if vision_images
        else user_input
    )
    outcome_signal = None
    if _input_shape_allows_outcome_feedback_heuristic(user_input):
        outcome_signal = detect_outcome_feedback_signal(user_input)
    if outcome_signal:
        append_project_journal(
            entry_type="outcome_feedback",
            user_input=journal_display_user,
            response_text="",
            action_type=infer_action_type(user_input, get_current_stage()),
            extra_fields={"outcome": outcome_signal},
        )

    focus = get_current_focus()
    stage = get_current_stage()
    action_type = infer_action_type(user_input, stage)

    # URL in user message → fetch before any first-pass LLM (no unprompted page prose).
    if (
        not vision_images
        and not user_message_suppresses_tool_fetch(user_input)
    ):
        forced_fetch_urls = _extract_fetchable_urls(user_input, max_urls=2)
        if forced_fetch_urls:
            fetched_sources: list[tuple[str, str]] = []
            for forced_fetch_url in forced_fetch_urls:
                _journal_forced_fetch_audit(
                    journal_display_user,
                    event="started",
                    url=forced_fetch_url,
                    fetch_ok=None,
                    failure_tag=None,
                    preview="",
                    digest="",
                )
                fetched_content = fetch_page(forced_fetch_url)
                fetch_raw_norm = (
                    (fetched_content if isinstance(fetched_content, str) else str(fetched_content)).strip()
                )
                failure_tag = fetch_failure_tag(fetch_raw_norm)
                preview, digest = _forced_fetch_preview_and_digest(fetch_raw_norm)
                _journal_forced_fetch_audit(
                    journal_display_user,
                    event="completed",
                    url=forced_fetch_url,
                    fetch_ok=(failure_tag is None),
                    failure_tag=failure_tag,
                    preview=preview,
                    digest=digest,
                )
                if failure_tag is not None:
                    append_recent_answer_history("Fetch failed", user_input=user_input)
                    return "Fetch failed"
                fetched_sources.append((forced_fetch_url, fetch_raw_norm))
            merged_fetch_url = ", ".join(url for url, _ in fetched_sources)
            merged_fetched_content = _merge_fetched_sources_for_prompt(fetched_sources)
            return _complete_fetch_after_load(
                user_input,
                journal_display_user,
                focus,
                stage,
                merged_fetch_url,
                merged_fetched_content,
            )
        forced_brave_query = _extract_explicit_web_search_query(user_input)
        if forced_brave_query:
            search_result = brave_search(forced_brave_query)
            search_payload = _format_brave_search_result_for_post_tool(search_result)
            return _complete_fetch_after_load(
                user_input,
                journal_display_user,
                focus,
                stage,
                "brave://search",
                search_payload,
            )

    force_structured_override = (
        is_meta_system_override_question(user_input, focus, stage)
        or (action_type == "research" and is_vague_research_request(user_input))
    )
    if force_structured_override:
        forced_next_step = build_specific_next_step(user_input, focus, stage, action_type)
        forced_next_step, _ = apply_recent_negative_outcome_anti_repeat_guard(
            user_input, forced_next_step
        )
        if _runtime_decision_or_planning_query(user_input):
            priority_value = _runtime_primary_user_priority(user_input)
            if priority_value:
                forced_next_step = _enforce_user_priority_next_step(
                    forced_next_step, priority_value
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
            user_input=journal_display_user,
            response_text=response,
            action_type=action_type,
        )
        append_recent_answer_history(response, user_input=user_input)
        return response

    system_prompt, messages = build_messages(
        user_input, runtime_context=runtime_context
    )
    if vision_images:
        _merge_vision_into_messages(messages, user_input, vision_images)
    messages = _latency_limit_message_list(messages, max_turns=10)
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
        fetch_url = tool_command["url"]
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fetch_page, fetch_url)
            fetched_content = future.result()
        return _complete_fetch_after_load(
            user_input,
            journal_display_user,
            focus,
            stage,
            fetch_url,
            fetched_content,
        )
    if tool_command and tool_command["tool"] == "brave_search":
        search_result = brave_search(tool_command["query"])
        search_payload = _format_brave_search_result_for_post_tool(search_result)
        return _complete_fetch_after_load(
            user_input,
            journal_display_user,
            focus,
            stage,
            "brave://search",
            search_payload,
        )

    append_project_journal(
        entry_type="conversation",
        user_input=journal_display_user,
        response_text=response,
        action_type=infer_action_type(user_input, get_current_stage()),
    )
    append_recent_answer_history(response, user_input=user_input)
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