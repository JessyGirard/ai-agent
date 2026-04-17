import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core.llm import ask_ai, llm_preflight_check
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


# ---------- STATE ----------

def load_state():
    if not STATE_FILE.exists():
        return DEFAULT_STATE.copy()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return DEFAULT_STATE.copy()

        merged = DEFAULT_STATE.copy()
        merged.update(data)
        return merged

    except (json.JSONDecodeError, OSError):
        return DEFAULT_STATE.copy()


def save_state():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(current_state, f, indent=2, ensure_ascii=False)


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
    if not JOURNAL_FILE.exists():
        return []

    entries = []
    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError:
        return []

    if max_entries is not None and max_entries > 0:
        return entries[-max_entries:]
    return entries


def write_project_journal(entries):
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(JOURNAL_FILE, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return


def archive_project_journal_entries(entries, reason):
    if not entries:
        return

    JOURNAL_ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    first_ts = entries[0].get("timestamp", "")
    last_ts = entries[-1].get("timestamp", "")
    by_type = {}

    for entry in entries:
        etype = entry.get("entry_type", "unknown")
        by_type[etype] = by_type.get(etype, 0) + 1

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "archived_count": len(entries),
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "entry_type_counts": by_type,
    }

    try:
        with open(JOURNAL_ARCHIVE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except OSError:
        return


def flush_project_journal(keep_recent):
    entries = load_project_journal()
    if len(entries) <= keep_recent:
        return 0

    to_archive = entries[:-keep_recent]
    remaining = entries[-keep_recent:]
    archive_project_journal_entries(to_archive, reason="manual_flush")
    write_project_journal(remaining)
    return len(to_archive)


def compact_project_journal_if_needed():
    entries = load_project_journal()
    if len(entries) <= JOURNAL_MAX_ACTIVE_ENTRIES:
        return 0

    to_archive = entries[:-JOURNAL_MAX_ACTIVE_ENTRIES]
    remaining = entries[-JOURNAL_MAX_ACTIVE_ENTRIES:]
    archive_project_journal_entries(to_archive, reason="auto_compaction")
    write_project_journal(remaining)
    return len(to_archive)


def append_project_journal(entry_type, user_input, response_text, action_type):
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
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

    try:
        with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return

    compact_project_journal_if_needed()


def retrieve_relevant_journal_entries(user_input, limit=3):
    entries = load_project_journal(max_entries=JOURNAL_RETRIEVAL_WINDOW)
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


def handle_project_journal_command(user_input):
    text = user_input.strip().lower()
    if text == "flush journal":
        archived = flush_project_journal(JOURNAL_KEEP_RECENT_ON_MANUAL_FLUSH)
        return f"✅ Journal flushed. Archived {archived} entries and kept the most recent {JOURNAL_KEEP_RECENT_ON_MANUAL_FLUSH}."

    if text == "show journal stats":
        active_entries = load_project_journal()
        return (
            "🧠 Journal stats:\n"
            f"- Active entries: {len(active_entries)}\n"
            f"- Max active entries: {JOURNAL_MAX_ACTIVE_ENTRIES}\n"
            f"- Retrieval window: {JOURNAL_RETRIEVAL_WINDOW}"
        )

    return None


# ---------- MEMORY ----------

def default_memory_payload():
    return {
        "meta": {
            "schema_version": "2.0",
            "extractor_version": "AI-V2-filter-merge",
            "source": "runtime+imported",
            "message_limit": None,
            "memory_count": 0,
        },
        "memory_items": []
    }


def load_memory_payload():
    if not MEMORY_FILE.exists():
        return default_memory_payload()

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return default_memory_payload()

    if not isinstance(data, dict):
        return default_memory_payload()

    if "memory_items" not in data or not isinstance(data["memory_items"], list):
        data["memory_items"] = []
    else:
        data["memory_items"] = dedupe_memory_items(data["memory_items"])

    if "meta" not in data or not isinstance(data["meta"], dict):
        data["meta"] = default_memory_payload()["meta"]

    return data


def save_memory_payload(payload):
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload["meta"]["memory_count"] = len(payload.get("memory_items", []))

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_memory():
    payload = load_memory_payload()
    return payload.get("memory_items", [])


def tokenize_text(text):
    if not isinstance(text, str):
        return set()

    return set(re.findall(r"[a-z0-9]+", text.lower()))


def project_safety_conversation_query(user_input):
    """User is asking about safety, stability, or what they rely on to avoid breakage."""
    if not isinstance(user_input, str) or not user_input.strip():
        return False
    t = user_input.lower()
    if any(p in t for p in ("regression harness", "run_regression", "tests/run_regression")):
        return True
    if any(
        p in t
        for p in (
            "keep it safe",
            "keep safe",
            "stay safe",
            "project safe",
            "don't break",
            "dont break",
            "do not break",
            "stability",
            "stable enough",
            "what do i rely",
            "what i rely",
        )
    ):
        return True
    if "rely on" in t and any(w in t for w in ("safe", "safety", "stability", "break", "risk", "regression")):
        return True
    if "safe" in t and "project" in t:
        return True
    return False


def safety_signal_memory(mem):
    """Memory row that names automated regression / testing as a practice."""
    if not isinstance(mem, dict):
        return False
    v = (mem.get("value") or "").lower()
    if not v:
        return False
    markers = (
        "regression",
        "harness",
        "run_regression",
        "tests/run_regression",
        "pytest",
        "automated test",
        "test suite",
        "regression test",
    )
    return any(m in v for m in markers)


def detect_memory_intent(user_input):
    text = user_input.lower()

    if any(term in text for term in ["prefer", "preference", "learning style", "how do i prefer"]):
        return "preference"
    if any(term in text for term in ["goal", "goals", "my goal", "aim", "purpose"]):
        return "goal"
    if any(term in text for term in ["working on", "building", "project", "system"]):
        return "project"
    if any(term in text for term in ["who am i", "about me", "my identity"]):
        return "identity"
    return "general"


def estimate_memory_recency_bonus(mem):
    bonus = 0.0

    if mem.get("last_seen") == "runtime":
        bonus += 0.08

    if mem.get("trend") == "reinforced":
        bonus += 0.07

    return bonus


def estimate_memory_staleness_penalty(mem):
    """Score-only: downrank stale / weak evidence items without mutating stored memory."""
    penalty = 0.0

    if mem.get("last_seen") != "runtime":
        penalty += 0.05

    if mem.get("trend") == "new" and mem.get("evidence_count", 1) <= 1:
        penalty += 0.04

    if mem.get("memory_kind") == "tentative":
        penalty += 0.03

    return min(penalty, 0.12)


def negation_signal_present(text_low):
    """Lightweight cue for opposing statements (identity / goal conflict guard)."""
    collapsed = re.sub(r"\s+", " ", text_low)
    normalized = f" {collapsed} "
    cues = (
        " not ",
        " never ",
        " no longer ",
        " don't ",
        " dont ",
        " nothing ",
    )
    return any(c in normalized for c in cues)


def runtime_memory_write_conflicts_existing(category, value, memory_items):
    """
    Skip writes that contradict an existing identity/goal on the same topic
    (negation mismatch + enough token overlap). Does not apply to preference/project.
    """
    if category not in {"identity", "goal"}:
        return False

    new_low = value.lower()
    new_neg = negation_signal_present(new_low)
    new_tok = tokenize_text(value)

    for item in memory_items:
        if not isinstance(item, dict):
            continue
        if item.get("category") != category:
            continue

        old_val = item.get("value", "")
        old_low = old_val.lower()
        old_neg = negation_signal_present(old_low)
        if old_neg == new_neg:
            continue

        old_tok = tokenize_text(old_val)
        union = old_tok | new_tok
        if not union:
            continue
        jaccard = len(old_tok & new_tok) / len(union)
        if jaccard >= 0.35:
            return True

    return False


def score_memory_item(mem, user_input):
    score = mem.get("confidence", 0) + mem.get("importance", 0)

    memory_value = mem.get("value", "")
    memory_kind = mem.get("memory_kind", "")
    category = mem.get("category", "")
    evidence_count = int(mem.get("evidence_count", 0) or 0)
    trend = (mem.get("trend") or "").lower()

    user_tokens = tokenize_text(user_input)
    memory_tokens = tokenize_text(memory_value)

    overlap = user_tokens.intersection(memory_tokens)
    score += len(overlap) * 0.35

    if memory_kind == "stable":
        score += 0.25
    elif memory_kind == "emerging":
        score += 0.10

    if category == "preference" and any(
        phrase in user_input.lower()
        for phrase in ["prefer", "preference", "how do i prefer", "learning style"]
    ):
        score += 0.30

    intent = detect_memory_intent(user_input)
    if intent != "general":
        if category == intent:
            score += 0.35
        else:
            score -= 0.10

    # If no lexical overlap and low confidence, downrank to reduce noisy retrieval.
    if not overlap and mem.get("confidence", 0) < 0.75:
        score -= 0.20

    # Prefer recently reinforced memory when relevance is otherwise similar.
    score += estimate_memory_recency_bonus(mem)

    if evidence_count >= 3 and trend == "reinforced":
        score += 0.10

    # Downrank items that look stale or weakly supported (retrieval only).
    score -= estimate_memory_staleness_penalty(mem)

    if project_safety_conversation_query(user_input) and safety_signal_memory(mem):
        score += 0.95

    return score


def retrieve_relevant_memory(user_input):
    memory_items = load_memory()

    if not memory_items:
        return []

    def keep_for_use(mem):
        confidence = float(mem.get("confidence", 0) or 0)
        evidence_count = int(mem.get("evidence_count", 0) or 0)

        # Ignore weak rows.
        if confidence < 0.5 and evidence_count <= 1:
            return False

        # Keep only strong rows.
        return confidence >= 0.6 or evidence_count >= 2

    scored = []
    for mem in memory_items:
        score = score_memory_item(mem, user_input)
        scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    filtered = [m for score, m in scored if score >= 1.10 and keep_for_use(m)]

    if filtered:
        return filtered[:3]

    # Fallback: keep one strongest memory if everything scored low.
    for _, mem in scored:
        if keep_for_use(mem):
            return [mem]
    return []


def retrieve_memory_for_purpose(user_input, k=6):
    """Broader retrieval for role/purpose prompts so the forced line can quote real rows."""
    memory_items = load_memory()
    if not memory_items:
        return []
    broaden = (
        "goal project memory regression harness journal tools preference identity "
        "agent testing safety merge extract"
    )
    scored = []
    for mem in memory_items:
        s = score_memory_item(mem, user_input) + 0.4 * score_memory_item(mem, broaden)
        scored.append((s, mem))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    seen = set()
    for _, mem in scored:
        key = build_memory_key(mem.get("category", ""), mem.get("value", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(mem)
        if len(out) >= k:
            break
    return out


def format_memory_block(memories):
    if not memories:
        return ""

    return "\n".join(
        f"- ({m.get('category')}) {m.get('value')}" for m in memories
    )


def estimate_runtime_importance(category, value):
    value_low = value.lower()

    if category == "goal":
        return 0.95

    if category == "project":
        if "ai" in value_low or "agent" in value_low or "memory" in value_low:
            return 1.00
        return 0.90

    if category == "identity":
        return 0.85

    if category == "preference":
        if "always" in value_low or "never" in value_low:
            return 0.85
        return 0.75

    return 0.70


def estimate_runtime_confidence(evidence_count):
    confidence_map = {
        1: 0.40,
        2: 0.60,
        3: 0.75,
        4: 0.85,
    }
    return confidence_map.get(evidence_count, 0.90)


def classify_memory_kind(evidence_count):
    if evidence_count >= 4:
        return "stable"
    if evidence_count >= 2:
        return "emerging"
    return "tentative"


def build_memory_key(category, value):
    canonical = canonicalize_memory_key_value(value)
    return f"{category}::{canonical}"


def canonicalize_memory_key_value(value):
    if not isinstance(value, str):
        return ""
    canonical = value.lower()
    canonical = re.sub(r"[-_]+", " ", canonical)
    canonical = re.sub(r"[^\w\s]+", " ", canonical)
    canonical = re.sub(r"\s+", " ", canonical).strip()
    return canonical


def normalize_memory_display_value(value):
    if not isinstance(value, str):
        return ""

    value = value.strip()

    # Light normalization only (not full canonicalization)
    value = re.sub(r"[-_]+", " ", value)

    # Normalize common separator cases
    value = re.sub(r"\s+", " ", value)

    return value


def dedupe_memory_items(memory_items):
    deduped = {}
    order = []

    for item in memory_items:
        if not isinstance(item, dict):
            continue

        category = item.get("category", "")
        value = item.get("value", "")
        if not category or not value:
            continue

        key = build_memory_key(category, value)
        if key not in deduped:
            deduped[key] = item.copy()
            order.append(key)
            continue

        existing = deduped[key]
        existing["evidence_count"] = existing.get("evidence_count", 1) + item.get("evidence_count", 1)
        existing["confidence"] = max(existing.get("confidence", 0), item.get("confidence", 0))
        existing["importance"] = max(existing.get("importance", 0), item.get("importance", 0))
        existing["memory_kind"] = classify_memory_kind(existing["evidence_count"])
        existing["trend"] = "reinforced"

        source_refs = existing.get("source_refs", [])
        incoming_refs = item.get("source_refs", [])
        if not isinstance(source_refs, list):
            source_refs = []
        if not isinstance(incoming_refs, list):
            incoming_refs = []
        existing["source_refs"] = list(dict.fromkeys(source_refs + incoming_refs))

    return [deduped[key] for key in order]


def normalize_runtime_memory_value(value):
    # Backward-compatible alias retained for existing callers.
    return normalize_memory_display_value(value)


def is_transient_identity_statement(low_text):
    transient_identity_phrases = [
        "i am good",
        "i am fine",
        "i'm fine",
        "i'm good",
        "i am okay",
        "i'm okay",
        "i am tired",
        "i'm tired",
    ]
    if any(low_text.startswith(p) for p in transient_identity_phrases):
        return True

    transient_state_terms = {
        "tired", "stressed", "exhausted", "sleepy", "sick", "ill",
        "hungry", "angry", "upset", "anxious", "burned out", "burnt out",
    }
    temporal_markers = {
        "today", "tonight", "lately", "right now", "at the moment", "this week",
    }

    normalized = re.sub(r"\s+", " ", low_text).strip()
    if normalized.startswith("i am ") or normalized.startswith("i'm "):
        if any(term in normalized for term in transient_state_terms):
            return True
        if any(marker in normalized for marker in temporal_markers):
            return True

    return False


def has_uncertainty_signal(low_text):
    uncertainty_phrases = [
        "maybe ",
        "i guess",
        "not sure",
        "for now",
        "i think",
    ]
    normalized = re.sub(r"\s+", " ", low_text).strip()
    return any(phrase in normalized for phrase in uncertainty_phrases)


def allows_uncertain_runtime_memory(category):
    """Project updates are allowed to stay tentative; other categories should be stated clearly."""
    return category == "project"


def make_runtime_memory_candidate(category, text, low):
    if has_uncertainty_signal(low) and not allows_uncertain_runtime_memory(category):
        return None
    return {
        "category": category,
        "value": normalize_runtime_memory_value(text),
    }


def extract_runtime_memory_candidate(user_input):
    text = user_input.strip()
    low = text.lower()

    if not text or "?" in text:
        return None

    if is_transient_identity_statement(low):
        return None

    if low.startswith("i prefer "):
        return make_runtime_memory_candidate("preference", text, low)

    if low.startswith("my goal is "):
        return make_runtime_memory_candidate("goal", text, low)

    if low.startswith("i am working on ") or low.startswith("i'm working on "):
        return make_runtime_memory_candidate("project", text, low)

    if low.startswith("i am building ") or low.startswith("i'm building "):
        return make_runtime_memory_candidate("project", text, low)

    if low.startswith("i am ") or low.startswith("i'm "):
        if "working on" not in low and "building" not in low:
            return make_runtime_memory_candidate("identity", text, low)

    return None


def next_runtime_memory_id(memory_items):
    max_id = 0

    for item in memory_items:
        memory_id = item.get("memory_id", "")
        match = re.fullmatch(r"mem_(\d{4})", memory_id)
        if match:
            max_id = max(max_id, int(match.group(1)))

    return f"mem_{max_id + 1:04d}"


def create_runtime_memory_item(memory_items, category, value):
    evidence_count = 1

    return {
        "memory_id": next_runtime_memory_id(memory_items),
        "category": category,
        "value": value,
        "confidence": estimate_runtime_confidence(evidence_count),
        "importance": estimate_runtime_importance(category, value),
        "status": "active",
        "memory_kind": classify_memory_kind(evidence_count),
        "evidence_count": evidence_count,
        "first_seen": "runtime",
        "last_seen": "runtime",
        "trend": "new",
        "source_refs": ["runtime"],
    }


def merge_runtime_memory(existing_item):
    existing_item["evidence_count"] = existing_item.get("evidence_count", 1) + 1
    existing_item["last_seen"] = "runtime"
    existing_item["confidence"] = estimate_runtime_confidence(existing_item["evidence_count"])
    existing_item["memory_kind"] = classify_memory_kind(existing_item["evidence_count"])
    existing_item["trend"] = "reinforced"

    source_refs = existing_item.get("source_refs", [])
    if "runtime" not in source_refs:
        source_refs.append("runtime")
    existing_item["source_refs"] = source_refs

    return existing_item


def write_runtime_memory(user_input):
    candidate = extract_runtime_memory_candidate(user_input)
    if not candidate:
        return None

    category = candidate.get("category")
    value = candidate.get("value")

    if category not in ALLOWED_MEMORY_CATEGORIES or not value:
        return None

    payload = load_memory_payload()
    memory_items = payload.get("memory_items", [])

    if runtime_memory_write_conflicts_existing(category, value, memory_items):
        return None

    memory_key = build_memory_key(category, value)

    for item in memory_items:
        existing_key = build_memory_key(item.get("category", ""), item.get("value", ""))
        if existing_key == memory_key:
            merge_runtime_memory(item)
            save_memory_payload(payload)
            return {
                "status": "reinforced",
                "category": category,
                "value": value,
            }

    new_item = create_runtime_memory_item(memory_items, category, value)
    memory_items.append(new_item)
    payload["memory_items"] = memory_items
    save_memory_payload(payload)

    return {
        "status": "created",
        "category": category,
        "value": value,
    }


# ---------- ACTION STRUCTURE ----------

def infer_action_type(user_input, stage):
    text = (user_input or "").strip().lower()
    stage_text = stage.lower()

    # Whole words only — "debugging" must not match "bug".
    if re.search(r"\b(?:error|bug|broken|fix|issue)\b", text):
        return "fix"

    if any(word in text for word in ["research", "look up", "find", "compare", "read", "website", "url", "webpage"]):
        return "research"

    if any(word in text for word in ["review", "evaluate", "assess", "inspect"]):
        return "review"

    # Whole words only — "testing" must not match "test".
    if re.search(r"\b(?:check|test|validate|verify)\b", text):
        return "test"

    if "testing" in stage_text:
        return "test"

    if "optimization" in stage_text:
        return "review"

    return "build"


def build_action_guidance(action_type):
    guidance = {
        "build": "The next step should create or add one concrete piece of the system.",
        "test": "The next step should validate one specific part of the current system.",
        "review": "The next step should inspect, assess, or evaluate one part of the system.",
        "research": "The next step should gather only the information needed for the immediate task.",
        "fix": "The next step should address one clear problem or failure point."
    }
    return guidance.get(action_type, "The next step should be specific and useful.")


# ---------- ROUTING ----------

def is_agent_purpose_question(text):
    """Why this agent exists / what it is for — not the API stack (user message only)."""
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
    """Who/what is this assistant, or what model/API stack powers replies (user message only)."""
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
    """Whether this assistant can use tools (e.g. web fetch) — user message only."""
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


def _user_negates_memory_retrieval_phrase(user_input: str) -> bool:
    """True when the user is clearly dismissing memory retrieval (substring false positives)."""
    u = (user_input or "").lower()
    if "memory retrieval" not in u:
        return False
    return bool(
        re.search(
            r"\b(?:not|never|without|no|isn't|aren't|don't|won't)\b[\w\s,'\"—-]{0,120}\bmemory\s+retrieval\b",
            u,
        )
    )


def _user_negates_recall_memory_phrase(user_input: str) -> bool:
    """Same idea as memory-retrieval negation, for 'not doing recall memory today' style lines."""
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
        return "agent_purpose"
    if is_agent_meta_question(u):
        return "agent_meta"
    if is_agent_tools_question(u):
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
        return "safety practices"

    if "rely on" in text and any(
        w in text for w in ("safe", "safety", "stability", "break", "risk", "regression")
    ):
        return "safety practices"

    # User text only — avoid focus/stage noise; runs after safety so harness/reliability questions win.
    if (
        "biggest risk" in u
        or "failure point" in u
        or re.search(r"\brisk\b", u)
        or re.search(r"\bweakness\b", u)
        or re.search(r"\bfragile\b", u)
        or (
            re.search(r"\bbreak\b", u)
            and re.search(
                r"\b(risk|weakness|fragile|failure|routing|system|playground|agent|repo|codebase)\b",
                u,
            )
        )
    ):
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
        if "memory retrieval" in text and _user_negates_memory_retrieval_phrase(user_input):
            blocked.add("memory retrieval")
        if "recall memory" in text and _user_negates_recall_memory_phrase(user_input):
            blocked.add("recall memory")
        active = [t for t in memory_workflow_terms if t in text and t not in blocked]
        if active:
            return "memory retrieval"

    # Do not match bare "preference" — it fires on taxonomy prompts ("GOAL not a preference") and
    # on literal "preference: ..." strings inside the question.
    if any(
        term in text
        for term in (
            "how do i prefer",
            "learning style",
            "my preferences",
            "what do i prefer",
            "which do i prefer",
        )
    ):
        return "memory behavior"

    # User text only — broad words like "reopen" in "journal vs state" questions hijacked this branch.
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
        return "restart persistence"

    # Match only real commands (same surface forms as `update_state_from_command`), not phrases like "my show state focus".
    ui = (user_input or "").strip().lower()
    if (
        ui.startswith("set focus:")
        or ui.startswith("set stage:")
        or ui == "show state"
        or ui == "reset state"
    ):
        return "state commands"

    if any(term in text for term in [
        "format", "formatting", "output format",
        "titan", "structure", "response format"
    ]):
        return "titan formatting"

    if any(term in text for term in [
        "action type", "action typing", "classification",
        "build test review", "action classification"
    ]):
        return "action typing"

    if any(term in text for term in [
        "next step", "specificity", "specific",
        "too generic", "vague"
    ]):
        return "next-step specificity"

    if any(term in text for term in [
        "blank input", "empty input", "press enter",
        "empty line", "no input"
    ]):
        return "blank-input handling"

    if any(term in text for term in [
        "website", "webpage", "url", "online page", "read site", "fetch"
    ]):
        return "web research"

    # Only the user's words — do not let focus/stage (e.g. "ai-agent" in focus) hijack unrelated questions.
    if any(
        term in (user_input or "").lower()
        for term in (
            "playground.py",
            "agent behavior",
            "ai-agent",
            "agent system",
        )
    ):
        return "playground.py behavior"

    return "current behavior"


def uses_strict_forced_reply(user_input, subtarget):
    """Strict canned Answer/Next-step only for explicit next-step asks or a few actionable subtargets."""
    if is_generic_next_step_question(user_input):
        return True
    return subtarget in {
        "safety practices",
        "state commands",
        "agent tools",
    }


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

    if subtarget == "agent_purpose":
        return (
            "Open `HANDOFF_RECENT_WORK.md` or `PROJECT_SPECIFICATION.md`, pick one subsystem (memory, journal, tools, or regression), and ask your next question about only that piece."
        )

    if subtarget == "agent_meta":
        return (
            "Open `core/llm.py` and `config/settings.py` and confirm `ANTHROPIC_MODEL` / `ANTHROPIC_API_KEY` in `.env` match how you want this agent to call Anthropic."
        )

    if subtarget == "agent_tools":
        return (
            "Try one prompt that needs real page text with a full https URL and confirm the first reply is exactly one line: TOOL:fetch <that-url>."
        )

    if subtarget == "system risk":
        return (
            "Pick one prior mis-route in `playground.py` (`detect_subtarget` / `uses_strict_forced_reply`), adjust a single guard or phrase list, and run `python tests/run_regression.py` to confirm nothing regressed."
        )

    if subtarget == "safety practices":
        if action_type == "test":
            return (
                "Run `python tests/run_regression.py` once and confirm every scenario passes before treating the system as safe to extend."
            )
        return (
            "Run `python tests/run_regression.py` after the next edit and confirm exit code 0 so the protected baseline still holds."
        )

    if action_type == "test":
        if is_generic_next_step_question(user_input):
            default_target = choose_default_test_target(focus, stage)

            if default_target == "memory retrieval":
                return (
                    "Test memory retrieval with one known preference question, then ask a follow-up that depends on the same detail and verify the answer stays consistent."
                )

            return (
                f"Run one focused test on {default_target} and verify the next step points to one exact check inside `{focus}`."
            )

        if subtarget == "memory retrieval" or subtarget == "memory behavior":
            return (
                "Test memory retrieval with one known preference question, then ask a follow-up that depends on the same detail and verify the answer stays consistent."
            )

        if subtarget == "restart persistence":
            return (
                "Set a new focus and stage, restart the app once, then run `show state` and confirm both values persisted correctly."
            )

        if subtarget == "state commands":
            return (
                "Run one state-command pass: use `set focus`, `set stage`, and `show state`, then confirm the printed state matches exactly what you set."
            )

        if subtarget == "next-step specificity":
            return (
                "Ask `What should I do next?` in the current testing state and verify the reply names one exact feature test instead of a broad or meta-level suggestion."
            )

        if subtarget == "action typing":
            return (
                "Ask one test-oriented prompt and confirm the agent labels the action type as `test` and gives a next step tied to a single behavior."
            )

        if subtarget == "titan formatting":
            return (
                "Ask one normal question and confirm the reply keeps the exact Titan structure with one short answer block and one concrete next step."
            )

        if subtarget == "blank-input handling":
            return (
                "Press Enter on an empty line once and confirm the app prints `⚠️ Please type something.` without generating a malformed response."
            )

        return (
            f"Run one focused test on {subtarget} and verify the next step points to one exact check inside `{focus}`."
        )

    if action_type == "review":
        if subtarget == "titan formatting":
            return (
                "Review the Titan response wording and identify the first place where the format becomes less direct or less consistent."
            )

        if subtarget == "state commands":
            return (
                "Review the state-command logic and identify the first place where command handling becomes less clear or less consistent."
            )

        return (
            f"Review the part of the prompt logic that governs {subtarget} and identify the first place where the wording becomes generic."
        )

    if action_type == "fix":
        return (
            f"Reproduce the problem once in {subtarget}, then adjust only the logic that controls that behavior before retesting the same prompt."
        )

    if action_type == "research":
        if subtarget == "web research":
            return (
                "Use one real page URL, fetch it, and verify the final answer stays grounded in the fetched content."
            )

        return (
            f"Gather one concrete example of stronger {subtarget} wording so the next prompt revision can anchor to a real target shape."
        )

    if subtarget == "next-step specificity":
        return (
            "Tighten the prompt so the `Next step:` line must name one exact task, such as a restart test, a state-command check, or a memory retrieval check."
        )

    if subtarget == "playground.py behavior":
        return (
            "Refine one branch in `playground.py` so the next-step wording points to a single concrete task instead of a project-wide action."
        )

    return (
        f"Add one small refinement that makes the next step point to a single concrete task inside `{focus}` at stage `{stage}`."
    )


# ---------- ANSWER LINE ----------

def build_answer_line(user_input, focus, stage, action_type, next_step, memories=None):
    text = user_input.strip().lower()
    subtarget = detect_subtarget(user_input, focus, stage)
    memories = memories or []

    def primary_intent_from_text(t):
        # Priority order: risk > goal > command > identity.
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

    # For mixed prompts, answer only the primary intent and keep secondary ideas out.
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
    if not isinstance(fetched_content, str):
        return "Try one reachable page URL and verify the final answer is based on fetched content."

    content = fetched_content.strip()
    low = content.lower()

    if not content:
        return "Try one reachable page URL and verify the final answer is based on fetched content."

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


# ---------- BUILD ----------

def build_messages(user_input):
    ul_norm = re.sub(r"\s+", " ", user_input.strip().lower())
    memories = retrieve_relevant_memory(user_input)
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

    focus = get_current_focus()
    stage = get_current_stage()
    action_type = infer_action_type(user_input, stage)
    action_guidance = build_action_guidance(action_type)
    subtarget = detect_subtarget(user_input, focus, stage)
    strict_reply = uses_strict_forced_reply(user_input, subtarget)

    forced_next_step = build_specific_next_step(user_input, focus, stage, action_type)
    forced_answer_line = build_answer_line(
        user_input, focus, stage, action_type, forced_next_step, memories=memories
    )

    safety_rules = ""
    if project_safety_conversation_query(user_input):
        safety_rules = """
- PROJECT SAFETY / STABILITY: If supporting memory mentions regression harnesses, automated tests, or similar, connect that explicitly to how the repo stays safe. Do not treat testing discipline as unrelated to safety. Focus and stage labels stay authoritative, but answer the substance of the safety question using those practices when they appear in supporting memory.
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
    elif strict_reply:
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
{safety_rules}{meta_rules}

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

    journal_block = format_journal_block(journal_entries)
    if journal_block:
        system_prompt += "\n\nRecent project journal:\n" + journal_block

    messages = [{"role": "user", "content": user_input}]
    return system_prompt, messages


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
        return command_result

    write_runtime_memory(user_input)

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
        return final_response

    append_project_journal(
        entry_type="conversation",
        user_input=user_input,
        response_text=response,
        action_type=infer_action_type(user_input, get_current_stage()),
    )
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