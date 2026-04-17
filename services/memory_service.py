import re


USER_PURPOSE_VALUE_MARKERS = (
    "survive",
    "income",
    "money",
    "real-life",
    "real life",
    "important",
    "life",
    "rely",
    "progress",
)

USER_PURPOSE_QUERY_SIGNALS = (
    "important",
    "survive",
    "rely",
    "need",
    "depend",
)


def tokenize_text(text):
    if not isinstance(text, str):
        return set()
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def default_memory_payload():
    return {
        "meta": {
            "schema_version": "2.0",
            "extractor_version": "AI-V2-filter-merge",
            "source": "runtime+imported",
            "message_limit": None,
            "memory_count": 0,
        },
        "memory_items": [],
    }


def load_memory(load_memory_payload_fn):
    payload = load_memory_payload_fn()
    return payload.get("memory_items", [])


def project_safety_conversation_query(user_input):
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
    penalty = 0.0
    if mem.get("last_seen") != "runtime":
        penalty += 0.05
    if mem.get("trend") == "new" and mem.get("evidence_count", 1) <= 1:
        penalty += 0.04
    if mem.get("memory_kind") == "tentative":
        penalty += 0.03
    return min(penalty, 0.12)


def negation_signal_present(text_low):
    collapsed = re.sub(r"\s+", " ", text_low)
    normalized = f" {collapsed} "
    cues = (" not ", " never ", " no longer ", " don't ", " dont ", " nothing ")
    return any(c in normalized for c in cues)


def runtime_memory_write_conflicts_existing(category, value, memory_items):
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
        phrase in user_input.lower() for phrase in ["prefer", "preference", "how do i prefer", "learning style"]
    ):
        score += 0.30
    intent = detect_memory_intent(user_input)
    if intent != "general":
        if category == intent:
            score += 0.35
        else:
            score -= 0.10
    if not overlap and mem.get("confidence", 0) < 0.75:
        score -= 0.20
    score += estimate_memory_recency_bonus(mem)
    if evidence_count >= 3 and trend == "reinforced":
        score += 0.10
    score -= estimate_memory_staleness_penalty(mem)
    if project_safety_conversation_query(user_input) and safety_signal_memory(mem):
        score += 0.95
    return score


def retrieve_relevant_memory(user_input, load_memory_fn):
    memory_items = load_memory_fn()
    if not memory_items:
        return []

    def keep_for_use(mem):
        confidence = float(mem.get("confidence", 0) or 0)
        evidence_count = int(mem.get("evidence_count", 0) or 0)
        if confidence < 0.5 and evidence_count <= 1:
            return False
        return confidence >= 0.6 or evidence_count >= 2

    scored = []
    for mem in memory_items:
        score = score_memory_item(mem, user_input)
        scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    filtered = [m for score, m in scored if score >= 1.10 and keep_for_use(m)]
    if filtered:
        return filtered[:3]
    for _, mem in scored:
        if keep_for_use(mem):
            return [mem]
    return []


def is_durable_user_memory(mem):
    if not isinstance(mem, dict):
        return False
    category = mem.get("category", "")
    memory_kind = mem.get("memory_kind", "")
    evidence_count = int(mem.get("evidence_count", 0) or 0)
    trend = (mem.get("trend") or "").lower()
    confidence = float(mem.get("confidence", 0) or 0)
    if category not in {"identity", "preference", "goal"}:
        return False
    if memory_kind not in {"stable", "emerging"}:
        return False
    if evidence_count < 2:
        return False
    if trend != "reinforced":
        return False
    if confidence < 0.6:
        return False
    return True


def is_personal_context_question(user_input):
    if not isinstance(user_input, str) or not user_input.strip():
        return False
    text = re.sub(r"\s+", " ", user_input.strip().lower())
    cues = (
        "how do i prefer",
        "what do you know about me",
        "what should you remember about me",
        "how do i like to work",
        "what matters to me",
        "what is my goal",
        "who am i",
        "what kind of pace do i want",
        "how should we work together",
    )
    return any(cue in text for cue in cues)


def is_user_purpose_memory(mem):
    if not isinstance(mem, dict):
        return False
    if mem.get("category") not in {"goal", "identity"}:
        return False
    v = (mem.get("value") or "").lower()
    return any(marker in v for marker in USER_PURPOSE_VALUE_MARKERS)


def is_user_purpose_query_signal(user_input):
    if not isinstance(user_input, str) or not user_input.strip():
        return False
    text = re.sub(r"\s+", " ", user_input.strip().lower())
    return any(sig in text for sig in USER_PURPOSE_QUERY_SIGNALS)


def retrieve_user_purpose_memory(user_input, load_memory_fn, limit=2):
    memory_items = load_memory_fn()
    if not memory_items:
        return []

    def keep_strong(mem):
        confidence = float(mem.get("confidence", 0) or 0)
        evidence_count = int(mem.get("evidence_count", 0) or 0)
        if confidence < 0.5 and evidence_count <= 1:
            return False
        return confidence >= 0.6 or evidence_count >= 2

    scored = []
    for mem in memory_items:
        if not is_user_purpose_memory(mem):
            continue
        if not keep_strong(mem):
            continue
        scored.append((score_memory_item(mem, user_input), mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    filtered = [m for s, m in scored if s >= 1.10]
    if filtered:
        return filtered[:limit]
    for _, mem in scored:
        return [mem]
    return []


def score_personal_memory_temporal_strength(mem):
    if not isinstance(mem, dict):
        return 0.0
    s = 0.0
    if (mem.get("trend") or "").lower() == "reinforced":
        s += 0.22
    if mem.get("last_seen") == "runtime":
        s += 0.18
    mk = mem.get("memory_kind", "")
    if mk == "stable":
        s += 0.12
    elif mk == "emerging":
        s += 0.07
    else:
        s += 0.03
    ev = int(mem.get("evidence_count", 0) or 0)
    s += min(0.12, ev * 0.03)
    return min(s, 0.55)


def personal_memory_stale_import_penalty(mem):
    if not isinstance(mem, dict):
        return 0.0
    if mem.get("category") not in {"identity", "preference", "goal"}:
        return 0.0
    if mem.get("last_seen") == "runtime":
        return 0.0
    if (mem.get("trend") or "").lower() == "reinforced":
        return 0.0
    weak = mem.get("memory_kind") == "tentative" or int(mem.get("evidence_count", 0) or 0) <= 1
    if not weak:
        return 0.0
    return 0.12


def prefer_stronger_personal_memory(mem_a, mem_b):
    if not isinstance(mem_a, dict):
        return False
    if not isinstance(mem_b, dict):
        return True
    kind_rank = {"stable": 2, "emerging": 1, "tentative": 0}
    a_evidence = int(mem_a.get("evidence_count", 0) or 0)
    b_evidence = int(mem_b.get("evidence_count", 0) or 0)
    if a_evidence != b_evidence:
        return a_evidence > b_evidence
    a_reinforced = (mem_a.get("trend") or "").lower() == "reinforced"
    b_reinforced = (mem_b.get("trend") or "").lower() == "reinforced"
    if a_reinforced != b_reinforced:
        return a_reinforced
    a_kind = kind_rank.get(mem_a.get("memory_kind", ""), -1)
    b_kind = kind_rank.get(mem_b.get("memory_kind", ""), -1)
    if a_kind != b_kind:
        return a_kind > b_kind
    a_conf = float(mem_a.get("confidence", 0) or 0)
    b_conf = float(mem_b.get("confidence", 0) or 0)
    if a_conf != b_conf:
        return a_conf > b_conf
    a_runtime = mem_a.get("last_seen") == "runtime"
    b_runtime = mem_b.get("last_seen") == "runtime"
    if a_runtime != b_runtime:
        return a_runtime
    return False


def personal_memory_rows_heavily_overlap(mem_a, mem_b):
    if not isinstance(mem_a, dict) or not isinstance(mem_b, dict):
        return False
    if mem_a.get("category") != mem_b.get("category"):
        return False
    a_tokens = tokenize_text(mem_a.get("value", ""))
    b_tokens = tokenize_text(mem_b.get("value", ""))
    if not a_tokens or not b_tokens:
        return False
    overlap = len(a_tokens.intersection(b_tokens))
    if overlap < 3:
        return False
    jaccard = overlap / max(1, len(a_tokens.union(b_tokens)))
    containment = overlap / max(1, min(len(a_tokens), len(b_tokens)))
    return jaccard >= 0.6 or containment >= 0.75


def retrieve_personal_context_memory(user_input, load_memory_fn, limit=3):
    memory_items = load_memory_fn()
    if not memory_items:
        return []

    def keep_for_personal_context(mem):
        confidence = float(mem.get("confidence", 0) or 0)
        evidence_count = int(mem.get("evidence_count", 0) or 0)
        if confidence < 0.5 and evidence_count <= 1:
            return False
        if mem.get("memory_kind") == "tentative":
            return False
        return mem.get("category") in {"identity", "preference", "goal", "project"}

    scored = []
    for idx, mem in enumerate(memory_items):
        score = score_memory_item(mem, user_input)
        if is_durable_user_memory(mem):
            score += 1.0
        elif mem.get("category") in {"identity", "preference", "goal"}:
            score += 0.20
        if mem.get("category") == "project":
            score -= 0.30
            if int(mem.get("evidence_count", 0) or 0) <= 1:
                score -= 0.20
        score += 0.18 * score_personal_memory_temporal_strength(mem)
        score -= personal_memory_stale_import_penalty(mem)
        scored.append((score, idx, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    filtered = [(score, idx, m) for score, idx, m in scored if score >= 1.10 and keep_for_personal_context(m)]

    def compact_same_lane(records):
        compacted = []
        for score, idx, mem in records:
            overlap_idx = None
            for i, (_, _, kept_mem) in enumerate(compacted):
                if personal_memory_rows_heavily_overlap(mem, kept_mem):
                    overlap_idx = i
                    break
            if overlap_idx is None:
                compacted.append((score, idx, mem))
                continue
            kept_score, kept_idx, kept_mem = compacted[overlap_idx]
            if prefer_stronger_personal_memory(mem, kept_mem):
                compacted[overlap_idx] = (score, idx, mem)
            elif not prefer_stronger_personal_memory(kept_mem, mem):
                compacted[overlap_idx] = (kept_score, kept_idx, kept_mem)
        return compacted

    def choose_diverse(records, max_items):
        chosen = []
        remaining = list(records)
        while remaining and len(chosen) < max_items:
            best_idx = None
            best_adjusted = None
            for i, (score, idx, mem) in enumerate(remaining):
                cat = mem.get("category")
                repeat_count = sum(1 for _, _, c_mem in chosen if c_mem.get("category") == cat)
                adjusted = score - (0.22 * repeat_count)
                if best_adjusted is None or adjusted > best_adjusted:
                    best_adjusted = adjusted
                    best_idx = i
            chosen.append(remaining.pop(best_idx))
        return [mem for _, _, mem in chosen]

    if filtered:
        compacted = compact_same_lane(filtered)
        return choose_diverse(compacted, limit)
    for _, _, mem in scored:
        if keep_for_personal_context(mem):
            return [mem]
    return []


def retrieve_memory_for_purpose(user_input, build_memory_key, load_memory_fn, k=6):
    memory_items = load_memory_fn()
    if not memory_items:
        return []
    broaden = "goal project memory regression harness journal tools preference identity agent testing safety merge extract"
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
    return "\n".join(f"- ({m.get('category')}) {m.get('value')}" for m in memories)


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
    confidence_map = {1: 0.40, 2: 0.60, 3: 0.75, 4: 0.85}
    return confidence_map.get(evidence_count, 0.90)


def classify_memory_kind(evidence_count):
    if evidence_count >= 4:
        return "stable"
    if evidence_count >= 2:
        return "emerging"
    return "tentative"


def canonicalize_memory_key_value(value):
    if not isinstance(value, str):
        return ""
    canonical = value.lower()
    canonical = re.sub(r"[-_]+", " ", canonical)
    canonical = re.sub(r"[^\w\s]+", " ", canonical)
    canonical = re.sub(r"\s+", " ", canonical).strip()
    return canonical


def build_memory_key(category, value):
    canonical = canonicalize_memory_key_value(value)
    return f"{category}::{canonical}"


def normalize_memory_display_value(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    value = re.sub(r"[-_]+", " ", value)
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
        "tired",
        "stressed",
        "exhausted",
        "sleepy",
        "sick",
        "ill",
        "hungry",
        "angry",
        "upset",
        "anxious",
        "burned out",
        "burnt out",
    }
    temporal_markers = {"today", "tonight", "lately", "right now", "at the moment", "this week"}
    normalized = re.sub(r"\s+", " ", low_text).strip()
    if normalized.startswith("i am ") or normalized.startswith("i'm "):
        if any(term in normalized for term in transient_state_terms):
            return True
        if any(marker in normalized for marker in temporal_markers):
            return True
    return False


def has_uncertainty_signal(low_text):
    uncertainty_phrases = ["maybe ", "i guess", "not sure", "for now", "i think"]
    normalized = re.sub(r"\s+", " ", low_text).strip()
    return any(phrase in normalized for phrase in uncertainty_phrases)


def allows_uncertain_runtime_memory(category):
    return category == "project"


def make_runtime_memory_candidate(category, text, low):
    if has_uncertainty_signal(low) and not allows_uncertain_runtime_memory(category):
        return None
    return {"category": category, "value": normalize_runtime_memory_value(text)}


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


def write_runtime_memory(user_input, allowed_memory_categories, load_memory_payload_fn, save_memory_payload_fn):
    candidate = extract_runtime_memory_candidate(user_input)
    if not candidate:
        return None
    category = candidate.get("category")
    value = candidate.get("value")
    if category not in allowed_memory_categories or not value:
        return None
    payload = load_memory_payload_fn()
    memory_items = payload.get("memory_items", [])
    if runtime_memory_write_conflicts_existing(category, value, memory_items):
        return None
    memory_key = build_memory_key(category, value)
    for item in memory_items:
        existing_key = build_memory_key(item.get("category", ""), item.get("value", ""))
        if existing_key == memory_key:
            merge_runtime_memory(item)
            save_memory_payload_fn(payload)
            return {"status": "reinforced", "category": category, "value": value}
    new_item = create_runtime_memory_item(memory_items, category, value)
    memory_items.append(new_item)
    payload["memory_items"] = memory_items
    save_memory_payload_fn(payload)
    return {"status": "created", "category": category, "value": value}
