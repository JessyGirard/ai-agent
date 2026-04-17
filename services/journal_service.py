import re
from collections import deque
from datetime import datetime, timezone


RECENT_ANSWER_HISTORY_MAX = 8
RECENT_ANSWER_MATCH_STOPWORDS = {
    "project",
    "system",
    "agent",
    "memory",
    "test",
    "tests",
    "stage",
    "focus",
    "current",
    "next",
    "step",
}


def flush_project_journal(
    keep_recent, load_project_journal, archive_project_journal_entries, write_project_journal
):
    entries = load_project_journal()
    if len(entries) <= keep_recent:
        return 0

    to_archive = entries[:-keep_recent]
    remaining = entries[-keep_recent:]
    archive_project_journal_entries(to_archive, reason="manual_flush")
    write_project_journal(remaining)
    return len(to_archive)


def compact_project_journal_if_needed(
    journal_max_active_entries,
    load_project_journal,
    archive_project_journal_entries,
    write_project_journal,
):
    entries = load_project_journal()
    if len(entries) <= journal_max_active_entries:
        return 0

    to_archive = entries[:-journal_max_active_entries]
    remaining = entries[-journal_max_active_entries:]
    archive_project_journal_entries(to_archive, reason="auto_compaction")
    write_project_journal(remaining)
    return len(to_archive)


def append_project_journal(
    entry_type,
    user_input,
    response_text,
    action_type,
    get_current_focus,
    get_current_stage,
    persistence_append_project_journal,
    journal_file,
    compact_project_journal_if_needed_fn,
    extra_fields=None,
):
    response_preview = (response_text or "").strip().replace("\n", " ")
    response_preview = response_preview[:220]

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry_type": entry_type,
        "focus": get_current_focus(),
        "stage": get_current_stage(),
        "action_type": action_type or "unknown",
        "user_input": user_input,
        "response_preview": response_preview,
    }
    if isinstance(extra_fields, dict):
        entry.update(extra_fields)

    persistence_append_project_journal(journal_file, entry)
    compact_project_journal_if_needed_fn()


def retrieve_relevant_journal_entries(user_input, load_project_journal, tokenize_text, journal_retrieval_window, limit=3):
    entries = load_project_journal(max_entries=journal_retrieval_window)
    if not entries:
        return []

    user_tokens = tokenize_text(user_input)
    scored = []

    for entry in entries:
        haystack = " ".join(
            str(entry.get(key, ""))
            for key in ["entry_type", "focus", "stage", "action_type", "user_input", "response_preview"]
        )
        entry_tokens = tokenize_text(haystack)
        overlap = len(user_tokens.intersection(entry_tokens))
        recency_bonus = 0.02
        score = overlap + recency_bonus
        scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [entry for score, entry in scored if score > 0][:limit]
    if top:
        return top
    return [entries[-1]]


def format_journal_block(entries):
    if not entries:
        return ""

    lines = []
    for entry in entries:
        lines.append(
            f"- [{entry.get('entry_type', 'event')}] "
            f"focus={entry.get('focus', '')}, stage={entry.get('stage', '')}, "
            f"user='{entry.get('user_input', '')}'"
        )
    return "\n".join(lines)


def retrieve_recent_outcome_feedback_entries(load_project_journal, limit=3):
    entries = load_project_journal(max_entries=40)
    if not entries:
        return []
    outcomes = {"worked", "failed", "useful", "not_useful"}
    picked = []
    for entry in reversed(entries):
        if entry.get("entry_type") != "outcome_feedback":
            continue
        if entry.get("outcome") not in outcomes:
            continue
        picked.append(entry)
        if len(picked) >= limit:
            break
    return picked


def format_outcome_feedback_block(entries):
    if not entries:
        return ""
    lines = []
    for entry in entries:
        outcome = entry.get("outcome", "")
        user_preview = re.sub(r"\s+", " ", str(entry.get("user_input", "")).strip())[:100]
        lines.append(f"- outcome={outcome}; user='{user_preview}'")
    return "\n".join(lines)


def is_outcome_feedback_context_relevant(user_input):
    t = re.sub(r"\s+", " ", (user_input or "").strip().lower())
    if not t:
        return False
    signals = (
        "what should i do next",
        "what do i do next",
        "next step",
        "how to improve",
        "improve",
        "make the system better",
        "what worked",
        "what failed",
        "did it work",
        "didn't work",
        "didnt work",
        "did not work",
    )
    return any(sig in t for sig in signals)


def apply_recent_negative_outcome_anti_repeat_guard(
    user_input, candidate_next_step, retrieve_recent_outcome_feedback_entries_fn, tokenize_text
):
    if not candidate_next_step or not is_outcome_feedback_context_relevant(user_input):
        return candidate_next_step, None

    negatives = []
    for entry in retrieve_recent_outcome_feedback_entries_fn(limit=3):
        if entry.get("outcome") in {"failed", "not_useful"}:
            negatives.append(entry)
    if not negatives:
        return candidate_next_step, None

    next_tokens = tokenize_text(candidate_next_step)
    if len(next_tokens) < 2:
        return candidate_next_step, None

    for entry in negatives:
        fb_tokens = tokenize_text(str(entry.get("user_input", "")))
        overlap = next_tokens.intersection(fb_tokens)
        overlap_count = len(overlap)
        overlap_ratio = overlap_count / max(1, len(next_tokens))
        if overlap_count >= 2 and overlap_ratio >= 0.25:
            adjusted = (
                "Before repeating the prior failed move, identify one concrete failure point first, then run one adjusted attempt with a different target or method."
            )
            return adjusted, entry

    return candidate_next_step, None


def append_recent_answer_history(response_text, recent_answer_history):
    if not isinstance(response_text, str):
        return
    cleaned = re.sub(r"\s+", " ", response_text).strip()
    if not cleaned:
        return
    if len(cleaned) > 300:
        cleaned = cleaned[:297] + "..."
    recent_answer_history.append(cleaned)


def format_recent_answer_history_block(recent_answer_history):
    if not recent_answer_history:
        return ""
    lines = []
    for idx, text in enumerate(reversed(recent_answer_history), start=1):
        lines.append(f"- (recent_{idx}) {text}")
    return "\n".join(lines)


def filter_recent_answer_match_tokens(tokens):
    return {t for t in tokens if t not in RECENT_ANSWER_MATCH_STOPWORDS}


def get_recent_answer_match_tokens(text, tokenize_text):
    return filter_recent_answer_match_tokens(tokenize_text(text))


def get_best_recent_answer_match(user_input, recent_answer_history, tokenize_text):
    if not recent_answer_history:
        return None

    user_tokens = get_recent_answer_match_tokens(user_input, tokenize_text)
    if len(user_tokens) < 2:
        return None

    best = None
    for answer in recent_answer_history:
        answer_tokens = get_recent_answer_match_tokens(answer, tokenize_text)
        if not answer_tokens:
            continue
        overlap = user_tokens.intersection(answer_tokens)
        overlap_count = len(overlap)
        overlap_ratio = overlap_count / max(1, len(user_tokens))
        candidate = {
            "matched_text": answer,
            "overlap_count": overlap_count,
            "overlap_ratio": overlap_ratio,
        }
        if best is None:
            best = candidate
            continue
        if overlap_count > best["overlap_count"]:
            best = candidate
            continue
        if overlap_count == best["overlap_count"] and overlap_ratio > best["overlap_ratio"]:
            best = candidate
            continue
        if overlap_count == best["overlap_count"] and overlap_ratio == best["overlap_ratio"]:
            best = candidate

    if not best:
        return None
    return best


def detect_recent_answer_relevance(user_input, recent_answer_history, tokenize_text):
    best = get_best_recent_answer_match(user_input, recent_answer_history, tokenize_text)
    if not best:
        return False
    return best["overlap_count"] >= 2 and best["overlap_ratio"] >= 0.35


def is_strong_recent_answer_match(match_info):
    if not match_info:
        return False
    overlap_count = match_info.get("overlap_count", 0)
    overlap_ratio = match_info.get("overlap_ratio", 0.0)
    return overlap_count >= 3 or (overlap_ratio >= 0.5 and overlap_count >= 2)


def detect_recent_answer_contradiction_cue(user_input, matched_text):
    if not matched_text or not isinstance(matched_text, str):
        return False
    t = (user_input or "").lower()
    if not t.strip():
        return False
    cues = (
        "but",
        "no",
        "not",
        "that's wrong",
        "you said",
        "earlier",
        "before",
        "contradiction",
        "inconsistent",
        "worked",
        "we changed that",
    )
    return any(c in t for c in cues)


def detect_recent_answer_followup_type(user_input, matched_text, detect_recent_answer_relevance_fn):
    if not matched_text or not isinstance(matched_text, str):
        return None
    t = (user_input or "").lower().strip()
    if not t:
        return None

    correction_cues = (
        "wrong",
        "not",
        "no",
        "but",
        "earlier",
        "before",
        "you said",
        "we changed",
        "that's not",
        "that is not",
        "inconsistent",
        "contradiction",
    )
    if any(c in t for c in correction_cues):
        return "correction"

    clarification_cues = (
        "what do you mean",
        "clarify",
        "more precisely",
        "be specific",
        "explain",
        "which part",
        "how exactly",
    )
    if any(c in t for c in clarification_cues):
        return "clarification"

    if detect_recent_answer_relevance_fn(user_input):
        return "continuation"
    return None


def handle_project_journal_command(
    user_input,
    flush_project_journal_fn,
    journal_keep_recent_on_manual_flush,
    load_project_journal,
    journal_max_active_entries,
    journal_retrieval_window,
):
    text = user_input.strip().lower()
    if text == "flush journal":
        archived = flush_project_journal_fn(journal_keep_recent_on_manual_flush)
        return (
            f"✅ Journal flushed. Archived {archived} entries and kept the most recent {journal_keep_recent_on_manual_flush}."
        )

    if text == "show journal stats":
        active_entries = load_project_journal()
        return (
            "🧠 Journal stats:\n"
            f"- Active entries: {len(active_entries)}\n"
            f"- Max active entries: {journal_max_active_entries}\n"
            f"- Retrieval window: {journal_retrieval_window}"
        )

    return None


def detect_outcome_feedback_signal(user_input):
    t = re.sub(r"\s+", " ", (user_input or "").strip().lower())
    if not t:
        return None
    if any(p in t for p in ("didn't work", "didnt work", "did not work", "not working", "failed")):
        return "failed"
    if any(p in t for p in ("not useful", "wasn't useful", "wasnt useful")):
        return "not_useful"
    if any(p in t for p in ("that worked", "it worked", "worked")):
        return "worked"
    if any(p in t for p in ("that was useful", "this was useful", "useful")):
        return "useful"
    return None


def make_recent_answer_history():
    return deque(maxlen=RECENT_ANSWER_HISTORY_MAX)
