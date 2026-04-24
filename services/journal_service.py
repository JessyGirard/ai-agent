import re
from collections import deque
from datetime import datetime, timezone


RECENT_ANSWER_HISTORY_MAX = 8

# User wants every step in one reply (not one-by-one / not anchored to a prior short list).
FULL_STEPS_LIST_REQUEST_MARKERS = (
    "all the proper steps",
    "all proper steps",
    "all the steps",
    "steps in order",
    "proper steps in order",
    "what are the steps",
    "full process",
    "entire process",
    "complete process",
    "whole process",
    "professional manner",
    "in a professional manner",
    "full list of steps",
    "complete list of steps",
    "every step",
    "all steps",
)


def user_input_requests_full_steps_list_normalized(ul_norm: str) -> bool:
    if not ul_norm:
        return False
    return any(m in ul_norm for m in FULL_STEPS_LIST_REQUEST_MARKERS)


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


def _is_line_separated_step_list(text: str) -> bool:
    """Unnumbered multi-line answers where each line is a distinct step (live: 12-item list)."""
    raw = str(text or "").strip()
    if not raw:
        return False
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) < 3:
        return False
    substantial = [ln for ln in lines if len(ln) >= 10]
    if len(substantial) < 3:
        return False
    stepish = (
        "test",
        "valid",
        "verif",
        "check",
        "defin",
        "ensur",
        "autom",
        "perform",
        "review",
        "document",
        "setup",
        "send",
        "request",
        "assert",
        "monitor",
        "log",
        "auth",
        "schema",
        "contract",
        "endpoint",
        "payload",
        "header",
        "response",
        "curl",
        "http",
    )
    hits = sum(1 for ln in substantial if any(w in ln.lower() for w in stepish))
    return hits >= max(3, (len(substantial) + 1) // 2)


def _is_list_like_ordered_sentence(text: str) -> bool:
    raw = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not raw:
        return False
    comma_parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(comma_parts) < 3:
        return False
    order_markers = (" and ", " then ", " after ", " before ", " finally ", " lastly ")
    if not any(m in raw for m in order_markers):
        return False
    stepish_words = (
        "step",
        "testing",
        "validate",
        "validating",
        "check",
        "checking",
        "define",
        "defining",
        "understand",
        "understanding",
        "perform",
        "performing",
        "automate",
        "automating",
    )
    return sum(1 for p in comma_parts if any(w in p for w in stepish_words)) >= 3


def text_has_structured_or_list_like_sequence(text: str) -> bool:
    low = str(text or "").lower()
    if re.search(r"(^|\n)\s*(?:\d+[.)]|[-*])\s+\S", low):
        return True
    if _is_line_separated_step_list(text):
        return True
    return _is_list_like_ordered_sentence(low)


def detect_requested_output_language(user_input: str) -> str | None:
    """ISO-ish language codes from explicit user phrasing (sequence / general)."""
    raw = (user_input or "").strip().lower()
    raw = raw.replace("\u2019", "'").replace("\u2018", "'")
    ul = re.sub(r"\s+", " ", raw)
    if not ul:
        return None
    patterns = (
        (
            "fr",
            r"\b(en français|en francais|in french|langue\s+français|langue\s+francais|français\s+svp|francais\s+svp|fr\s*svp|french\s+please)\b",
        ),
        (
            "en",
            r"\b(back to english|in english|en anglais|reply in english|use english|english)\b",
        ),
        ("es", r"\b(en español|en espagnol|in spanish|in español)\b"),
        ("de", r"\b(auf deutsch|in german)\b"),
        ("it", r"\b(in italiano|in italian|en italiano)\b"),
        ("pt", r"\b(em português|em portugues|in portuguese)\b"),
        ("zh", r"\b(用中文|in chinese|en chinois)\b"),
        ("ja", r"\b(日本語で|in japanese)\b"),
    )
    for code, pat in patterns:
        if re.search(pat, ul, flags=re.IGNORECASE):
            return code
    return None


def user_input_is_short_output_language_switch(user_input: str) -> bool:
    if not detect_requested_output_language(user_input):
        return False
    raw = (user_input or "").strip().lower()
    raw = raw.replace("\u2019", "'").replace("\u2018", "'")
    ul = re.sub(r"\s+", " ", raw)
    return len(ul.split()) <= 18


def user_input_is_explain_step_request(user_input, ul_norm: str | None = None) -> bool:
    """True when the user asked to explain a specific step (cursor may stay ahead of last_rendered)."""
    if ul_norm is not None:
        ul = (ul_norm or "").strip().lower()
    else:
        ul = re.sub(r"\s+", " ", (user_input or "").strip().lower())
    return bool(re.search(r"\bexplain\s+(?:step|number)\s*\d+\b", ul))


def user_input_signals_sequence_list_followup(user_input: str) -> bool:
    """User references prior multi-point answer (those N points, one-by-one, start with number 1)."""
    raw = (user_input or "").strip().lower()
    raw = raw.replace("\u2019", "'").replace("\u2018", "'")
    ul = re.sub(r"\s+", " ", raw)
    if not ul:
        return False
    if "one by one" in ul and ("point" in ul or "step" in ul):
        return True
    if "elaborate on those" in ul and ("point" in ul or "step" in ul):
        return True
    if ("those " in ul or "these " in ul) and ("point" in ul or "step" in ul):
        return True
    if re.search(r"\bthose\s+\d+\s+points?\b", ul):
        return True
    if re.search(r"\bthese\s+\d+\s+points?\b", ul):
        return True
    if ("starting with number" in ul or "starting with step" in ul) and (
        "point" in ul or "step" in ul
    ):
        return True
    return False


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


def make_recent_answer_history():
    return deque(maxlen=RECENT_ANSWER_HISTORY_MAX)


def make_recent_answer_step_frames():
    """Parallel to recent_answer_history: each entry is None or list[{index, content}, ...]."""
    return deque(maxlen=RECENT_ANSWER_HISTORY_MAX)


def extract_indexed_steps_from_text(text: str) -> list[dict]:
    """Parse list-like assistant answers into 1-based ordered steps (positional order in source)."""
    raw = str(text or "").strip()
    if not raw:
        return []
    low = raw.lower()

    if re.search(r"(?m)^\s*\d+[.)]\s+\S", raw):
        out = []
        for m in re.finditer(r"(?m)^\s*\d+[.)]\s*(.+?)\s*$", raw):
            c = m.group(1).strip()
            if c:
                out.append({"index": len(out) + 1, "content": c})
        if out:
            return out

    if re.search(r"(?m)^\s*[-*•]\s+\S", raw):
        out = []
        for m in re.finditer(r"(?m)^\s*[-*•]\s*(.+?)\s*$", raw):
            c = m.group(1).strip()
            if c:
                out.append({"index": len(out) + 1, "content": c})
        if out:
            return out

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if _is_line_separated_step_list(raw):
        out = []
        for ln in lines:
            if len(ln) >= 10:
                out.append({"index": len(out) + 1, "content": ln})
        if out:
            return out

    if _is_list_like_ordered_sentence(low):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) >= 3:
            return [{"index": i + 1, "content": p} for i, p in enumerate(parts)]

    return []


def _continue_next_only_core(ul: str) -> str:
    """Normalize one-line Continue/Next commands while preserving existing progression semantics."""
    s = (ul or "").strip().lower()
    s = s.rstrip(".!?\u3002\uff01\uff1f\u061f")
    # Increment 1D: tolerate noisy separators before language cues.
    s = re.sub(r"[,\-:;]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    m = re.match(r"^(continue|next)\b", s, flags=re.IGNORECASE)
    if m and re.search(r"\b(?:in\s+french|in\s+english|en\s+français|en\s+francais|en\s+anglais)\b", s, flags=re.IGNORECASE):
        return m.group(1).lower()
    # Increment 1B: allow one-line progression + language commands:
    # "continue en français", "next in french", "continue in english", etc.
    s = re.sub(
        r"\s+(?:in\s+(?:french|english)|en\s+(?:français|francais|anglais))\s*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = s.rstrip(".!?\u3002\uff01\uff1f\u061f")
    return s.strip()


def _user_needs_prior_list_step_anchor(user_input, ul_norm: str) -> bool:
    """True when the user is in a step/continuation flow and we may re-anchor to an earlier indexed list."""
    if user_input_is_short_output_language_switch(user_input):
        return True
    if user_input_signals_sequence_list_followup(user_input):
        return True
    uln = (ul_norm or "").strip()
    if not uln:
        return False
    core = _continue_next_only_core(uln)
    if re.fullmatch(r"continue|next", core, flags=re.IGNORECASE):
        return True
    if re.search(r"\b(?:step|number|étape|etape)\s*\d+\b", uln):
        return True
    if re.search(r"\bstart(?:ing)?\s+with\s+(?:number|step)\s*\d+\b", uln):
        return True
    return False


def _aligned_history_step_frames(recent_answer_history, recent_answer_step_frames):
    hist = list(recent_answer_history)
    frames = list(recent_answer_step_frames)
    if not hist:
        return hist, frames
    if len(frames) < len(hist):
        frames = [None] * (len(hist) - len(frames)) + frames
    elif len(frames) > len(hist):
        frames = frames[-len(hist) :]
    return hist, frames


def _one_by_one_sequence_entry_target_1based(ul: str, steps_len: int) -> int | None:
    """Increment 11: pace + explicit start/only-include anchor (not generic step|number).

    Long one-by-one prompts may mention another step earlier (e.g. 'read step 2'); the
    generic ``(?:step|number)\\s*(\\d+)`` branch would bind that first. When the user
    also signals one-by-one / step-by-step pacing, prefer ``starting with`` or
    ``only include`` as the entry index so cursor/last_rendered initialize at N only.
    """
    if steps_len <= 0 or not ul:
        return None
    pace = (
        "one by one" in ul
        or "one-by-one" in ul
        or "step by step" in ul
        or "step-by-step" in ul
    )
    if not pace:
        return None
    m = re.search(
        r"\bstarting\s+with\s+(?:the\s+)?(?:number|step)\s*(\d+)\b",
        ul,
        flags=re.IGNORECASE,
    )
    if m:
        try:
            v = int(m.group(1))
        except ValueError:
            v = None
        if v is not None and 1 <= v <= steps_len:
            return v
    m2 = re.search(
        r"\bonly\s+include\s+(?:the\s+)?(?:number|step)\s*(\d+)\b",
        ul,
        flags=re.IGNORECASE,
    )
    if m2:
        try:
            v = int(m2.group(1))
        except ValueError:
            v = None
        if v is not None and 1 <= v <= steps_len:
            return v
    return None


def lookup_steps_for_matched_answer(
    matched_text, recent_answer_history, recent_answer_step_frames, user_input=None
):
    if not matched_text or recent_answer_step_frames is None:
        return None
    mt = str(matched_text).strip()
    if not mt:
        return None
    hist, frames = _aligned_history_step_frames(recent_answer_history, recent_answer_step_frames)
    if not hist:
        return None

    def _prefer_longest_indexed(require_matched_text: bool):
        """Increment 13: among candidates, prefer the longest frame (tie → more recent)."""

        def _ok(a: str) -> bool:
            if not require_matched_text:
                return True
            return a == mt or (len(mt) >= 24 and (mt in a or a in mt))

        best_steps = None
        best_len = -1
        best_i = None
        for i, (ans, steps) in enumerate(zip(reversed(hist), reversed(frames))):
            if not steps:
                continue
            a = str(ans).strip()
            if not a or not _ok(a):
                continue
            ln = len(steps)
            if best_steps is None or ln > best_len or (ln == best_len and best_i is not None and i < best_i):
                best_steps = steps
                best_len = ln
                best_i = i
        return best_steps

    matched = _prefer_longest_indexed(require_matched_text=True)
    if matched is not None and user_input:
        uln = re.sub(r"\s+", " ", (user_input or "").strip().lower())
        core = _continue_next_only_core(uln)
        max_len = max((len(s) for _, s in zip(reversed(hist), reversed(frames)) if s), default=0)
        if (
            max_len > len(matched)
            and re.fullmatch(r"continue|next", core, flags=re.IGNORECASE)
            and _user_needs_prior_list_step_anchor(user_input, uln)
        ):
            matched = _prefer_longest_indexed(require_matched_text=False)
    if matched:
        return matched
    if user_input:
        uln = re.sub(r"\s+", " ", (user_input or "").strip().lower())
        if _user_needs_prior_list_step_anchor(user_input, uln):
            return _prefer_longest_indexed(require_matched_text=False)
    return None


def resolve_sequence_step_navigation(
    user_input,
    ul_norm: str,
    *,
    cursor_before: int,
    last_rendered_step_index: int,
    steps_len: int,
) -> tuple[int | None, int, int | None]:
    """Return (target_1based, new_cursor, last_rendered_update).

    ``last_rendered_update`` is the new 1-based last-displayed step index when it should
    change; ``None`` means leave ``last_rendered_step_index`` unchanged (e.g. language pivot).
    """
    if steps_len <= 0:
        return None, cursor_before, None
    ul = (ul_norm or "").strip()
    if not ul:
        return None, cursor_before, None

    if any(
        p in ul
        for p in (
            "what should i do next",
            "what is the next step",
            "what's the next step",
            "what do i do next",
        )
    ):
        return None, cursor_before, None

    m = re.search(r"\b(?:you\s+)?(?:forgot|forgotten)\s+step\s*(\d+)\b", ul)
    if not m:
        m = re.search(r"\b(?:missing|missed|skipped)\s+step\s*(\d+)\b", ul)
    if m:
        try:
            v = int(m.group(1))
        except ValueError:
            v = None
        if v is not None and 1 <= v <= steps_len:
            return v, v, v

    m = re.search(r"\bgive\s+me\s+step\s*(\d+)\b", ul)
    if m:
        try:
            v = int(m.group(1))
        except ValueError:
            v = None
        if v is not None and 1 <= v <= steps_len:
            return v, cursor_before, v
    m = re.search(r"\bdonne(?:-|\s*)moi\s+l[’']?(?:étape|etape)\s*(\d+)\b", ul)
    if m:
        try:
            v = int(m.group(1))
        except ValueError:
            v = None
        if v is not None and 1 <= v <= steps_len:
            return v, cursor_before, v

    m = re.search(r"\bexplain\s+(?:step|number)\s*(\d+)\b", ul)
    if m:
        try:
            v = int(m.group(1))
        except ValueError:
            v = None
        if v is not None and 1 <= v <= steps_len:
            return v, cursor_before, v

    core = _continue_next_only_core(ul)
    if user_input_is_short_output_language_switch(user_input) and not re.fullmatch(
        r"continue|next", core, flags=re.IGNORECASE
    ):
        # Stabilization invariant: sequence position comes only from last_rendered_step_index.
        # After explicit give-me / explain step picks so phrases like "… in French" do not steal priority.
        anchor = last_rendered_step_index if last_rendered_step_index > 0 else 0
        if anchor > 0 and 1 <= anchor <= steps_len:
            return anchor, anchor, anchor
        return None, cursor_before, None

    # Start / starting with number|step must precede generic (?:step|number)\d+ so longer
    # prompts cannot bind an earlier "step N" / "number N" before the user's start intent.
    m = re.search(r"\bstarting\s+with\s+(?:number|step)\s*(\d+)\b", ul)
    if m:
        try:
            v = int(m.group(1))
        except ValueError:
            v = None
        if v is not None and 1 <= v <= steps_len:
            return v, v, v

    m = re.search(r"\bstart\s+with\s+(?:number|step)\s*(\d+)\b", ul)
    if m:
        try:
            v = int(m.group(1))
        except ValueError:
            v = None
        if v is not None and 1 <= v <= steps_len:
            return v, v, v

    obo = _one_by_one_sequence_entry_target_1based(ul, steps_len)
    if obo is not None:
        return obo, obo, obo

    m = re.search(r"\b(?:step|number|étape|etape)\s*(\d+)\b", ul)
    if m:
        try:
            v = int(m.group(1))
        except ValueError:
            v = None
        if v is not None and 1 <= v <= steps_len:
            return v, v, v

    if re.fullmatch(r"continue|next", core, flags=re.IGNORECASE):
        # Increment 12: advance strictly from last displayed step (no mixed cursor base).
        nxt = min(max(0, int(last_rendered_step_index)) + 1, steps_len)
        return nxt, nxt, nxt

    return None, cursor_before, None


def append_recent_answer_history(
    response_text,
    recent_answer_history,
    recent_answer_step_frames=None,
    *,
    store_indexed_steps=True,
):
    if not isinstance(response_text, str):
        return
    cleaned = str(response_text).strip()
    if not cleaned:
        return
    # Preserve newlines so line-separated step lists stay anchorable; normalize spaces only.
    cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned).strip()
    max_chars = 2000
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 40].rstrip() + "\n…[truncated]"
    if store_indexed_steps:
        extracted = extract_indexed_steps_from_text(cleaned)
    else:
        extracted = []
    frame = extracted if extracted else None
    recent_answer_history.append(cleaned)
    if recent_answer_step_frames is not None:
        recent_answer_step_frames.append(frame)


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

    raw_user = (user_input or "").strip().lower()
    user_tokens = get_recent_answer_match_tokens(user_input, tokenize_text)
    if len(user_tokens) < 2:
        short_continuation_cues = (
            "continue",
            "next",
            "start with",
            "starting with",
            "number 1",
            "step 1",
            "first one",
            "first step",
            "start from",
        )
        if any(c in raw_user for c in short_continuation_cues):
            for answer in reversed(recent_answer_history):
                if text_has_structured_or_list_like_sequence(answer):
                    return {
                        "matched_text": answer,
                        "overlap_count": 0,
                        "overlap_ratio": 0.0,
                    }
        if user_input_signals_sequence_list_followup(user_input):
            for answer in reversed(recent_answer_history):
                if text_has_structured_or_list_like_sequence(answer):
                    return {
                        "matched_text": answer,
                        "overlap_count": 3,
                        "overlap_ratio": 0.5,
                    }
        if user_input_is_short_output_language_switch(user_input):
            for answer in reversed(recent_answer_history):
                if text_has_structured_or_list_like_sequence(answer):
                    return {
                        "matched_text": answer,
                        "overlap_count": 3,
                        "overlap_ratio": 0.5,
                    }
        if re.search(r"\b(?:step|number)\s*\d+\b", raw_user):
            for answer in reversed(recent_answer_history):
                if text_has_structured_or_list_like_sequence(answer):
                    return {
                        "matched_text": answer,
                        "overlap_count": 3,
                        "overlap_ratio": 0.5,
                    }
        return None

    if user_input_signals_sequence_list_followup(user_input):
        for answer in reversed(recent_answer_history):
            if text_has_structured_or_list_like_sequence(answer):
                return {
                    "matched_text": answer,
                    "overlap_count": max(3, len(user_tokens)),
                    "overlap_ratio": 0.5,
                }

    if user_input_is_short_output_language_switch(user_input):
        for answer in reversed(recent_answer_history):
            if text_has_structured_or_list_like_sequence(answer):
                return {
                    "matched_text": answer,
                    "overlap_count": max(3, len(user_tokens)),
                    "overlap_ratio": 0.5,
                }

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

    if user_input_signals_sequence_list_followup(user_input):
        if not text_has_structured_or_list_like_sequence(best.get("matched_text", "")):
            for answer in reversed(recent_answer_history):
                if text_has_structured_or_list_like_sequence(answer):
                    return {
                        "matched_text": answer,
                        "overlap_count": max(best.get("overlap_count", 0), 3),
                        "overlap_ratio": max(float(best.get("overlap_ratio", 0.0)), 0.5),
                    }
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
    ul_norm = re.sub(r"\s+", " ", t)
    if user_input_requests_full_steps_list_normalized(ul_norm):
        return None
    matched_has_structure = text_has_structured_or_list_like_sequence(matched_text)
    if matched_has_structure:
        if user_input_signals_sequence_list_followup(user_input):
            return "continuation"
        if user_input_is_short_output_language_switch(user_input):
            return "continuation"
        if re.search(r"\bexplain\s+(?:step|number)\b", t):
            return "continuation"
        if re.search(r"\bgive\s+me\s+step\b", t):
            return "continuation"

    correction_cues = (
        "wrong",
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
    if re.search(r"\bbut\b", t):
        return "correction"
    # Avoid substring false positives: "number" contains "no"; "not all" is not a correction.
    if re.match(r"^\s*no[,.]\s", t):
        return "correction"

    sequence_continuation_cues = (
        "continue",
        "next",
        "start with",
        "starting with",
        "number 1",
        "step 1",
        "first one",
        "first step",
        "start from",
    )
    has_sequence_cue = any(c in t for c in sequence_continuation_cues)
    if has_sequence_cue and matched_has_structure:
        return "continuation"

    clarification_cues = (
        "what do you mean",
        "clarify",
        "more precisely",
        "be specific",
        "which part",
        "how exactly",
    )
    if any(c in t for c in clarification_cues):
        return "clarification"
    # "elaborate ..." must not route here; exclude targeted step explanations.
    if re.search(r"\bexplain\b", t) and not re.search(
        r"\bexplain\s+(?:step|number)\b", t
    ):
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
