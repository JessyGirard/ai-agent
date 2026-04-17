import copy
import json
import os
import re
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

_client = None


def _get_client():
    global _client
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY is missing from .env")
    if _client is None:
        _client = OpenAI(api_key=key)
    return _client

INPUT_FILE = PROJECT_ROOT / "memory" / "imported.json"
OUTPUT_FILE = PROJECT_ROOT / "memory" / "extracted_memory.json"

ALLOWED_CATEGORIES = {"identity", "goal", "preference", "project"}
DEFAULT_MESSAGE_LIMIT = 50
MAX_MESSAGE_LIMIT = 500
MAX_MEMORY_VALUE_CHARS = 420
PRE_EXTRACT_BACKUP = PROJECT_ROOT / "memory" / "extracted_memory.pre_extract.json"


def effective_message_limit():
    raw = os.getenv("EXTRACT_MESSAGE_LIMIT", str(DEFAULT_MESSAGE_LIMIT)).strip()
    try:
        n = int(raw, 10)
    except ValueError:
        n = DEFAULT_MESSAGE_LIMIT
    return max(1, min(n, MAX_MESSAGE_LIMIT))


def backup_extracted_before_write():
    """One rotating on-disk copy before each extract write (never blocks on failure)."""
    if not OUTPUT_FILE.exists():
        return False
    try:
        if OUTPUT_FILE.stat().st_size < 4:
            return False
        shutil.copy2(OUTPUT_FILE, PRE_EXTRACT_BACKUP)
        return True
    except OSError:
        return False


def load_messages():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(text):
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_category(category):
    if not isinstance(category, str):
        return None

    category = category.strip().lower()

    if category in ALLOWED_CATEGORIES:
        return category

    return None


def looks_like_noise(value):
    if not value:
        return True

    low = value.lower().strip()

    banned_exact = {
        "yes",
        "no",
        "maybe",
        "okay",
        "ok",
        "sure",
        "thanks",
        "thank you",
        "hello",
        "hi",
        "good",
        "fine",
        "cool",
        "all right",
    }

    if low in banned_exact:
        return True

    if len(low) < 8:
        return True

    if len(low.split()) < 3:
        return True

    banned_substrings = [
        "the system begins with your mic",
        "processing tiny slices of sound",
        "wait → record → process",
        "wait -> record -> process",
        "my browsing tool",
        "chat transcript",
        "good night",
        "go to bed",
        "i'm tired",
        "just testing",
        "can you hear me",
    ]

    for phrase in banned_substrings:
        if phrase in low:
            return True

    return False


def estimate_importance(category, value):
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


def classify_memory_kind(evidence_count):
    if evidence_count >= 4:
        return "stable"
    if evidence_count >= 2:
        return "emerging"
    return "tentative"


def estimate_confidence(evidence_count):
    confidence_map = {
        1: 0.40,
        2: 0.60,
        3: 0.75,
        4: 0.85,
    }
    return confidence_map.get(evidence_count, 0.90)


def build_memory_key(category, value):
    return f"{category}::{value.lower()}"


def extract_memory_with_ai(text):
    prompt = f"""
Extract durable long-term memory about the USER (the human speaking in INPUT).

Categories (value strings must be concise declarative facts, never questions):
- identity — stable facts about who they are in this context
- goal — outcomes they are pursuing
- preference — how they like to work or decide
- project — concrete thing they are building or maintaining

Do NOT extract: moods, greetings, filler, one-off reactions, assistant-only content,
generic tech trivia with no clear tie to this user's work, transcript/meta noise.

Each "value": no question marks; grounded in the user's statements; max ~{MAX_MEMORY_VALUE_CHARS} characters of prose.

Return ONLY valid JSON — either one object or an array of objects:
{{ "category": "goal", "value": "Ship a reliable memory layer before adding agent features" }}
[
  {{ "category": "preference", "value": "Prefer small changes verified by automated regression tests" }}
]

Allowed categories: identity, goal, preference, project

INPUT:
{text}
"""

    try:
        response = _get_client().chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "Extract durable user memory only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )

        content = response.choices[0].message.content.strip()
        data = json.loads(content)

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []

    except Exception as e:
        print(f"❌ Error during extraction: {e}")
        return []


def validate_candidate(result):
    if not isinstance(result, dict):
        return None

    category = normalize_category(result.get("category"))
    value = result.get("value")

    if not isinstance(value, str):
        return None

    value = normalize_text(value)

    if not category:
        return None

    if "?" in value:
        return None

    if len(value) > MAX_MEMORY_VALUE_CHARS:
        return None

    if looks_like_noise(value):
        return None

    return {
        "category": category,
        "value": value
    }


def new_memory_item(memory_id, msg_idx, category, value):
    evidence_count = 1

    return {
        "memory_id": memory_id,
        "category": category,
        "value": value,
        "confidence": estimate_confidence(evidence_count),
        "importance": estimate_importance(category, value),
        "status": "active",
        "memory_kind": classify_memory_kind(evidence_count),
        "evidence_count": evidence_count,
        "first_seen": f"msg_{msg_idx}",
        "last_seen": f"msg_{msg_idx}",
        "trend": "new",
        "source_refs": [f"msg_{msg_idx}"]
    }


def merge_memory(existing_item, msg_idx):
    if not isinstance(existing_item.get("source_refs"), list):
        existing_item["source_refs"] = []
    if not isinstance(existing_item.get("evidence_count"), int) or existing_item["evidence_count"] < 1:
        existing_item["evidence_count"] = 1

    existing_item["evidence_count"] += 1
    existing_item["last_seen"] = f"msg_{msg_idx}"
    existing_item["confidence"] = estimate_confidence(existing_item["evidence_count"])
    existing_item["memory_kind"] = classify_memory_kind(existing_item["evidence_count"])
    existing_item["trend"] = "reinforced"

    msg_ref = f"msg_{msg_idx}"
    if msg_ref not in existing_item["source_refs"]:
        existing_item["source_refs"].append(msg_ref)

    return existing_item


def allocate_memory_id(memory_map):
    used = set()
    for item in memory_map.values():
        mid = item.get("memory_id")
        if isinstance(mid, str):
            used.add(mid)
    n = 0
    while True:
        cand = f"mem_{n:04d}"
        if cand not in used:
            return cand
        n += 1


def load_existing_memory_map():
    """Load prior extracted rows keyed by category::value for merge-on-extract."""
    memory_map = {}
    if not OUTPUT_FILE.exists():
        return memory_map
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return memory_map

    items = data.get("memory_items")
    if not isinstance(items, list):
        return memory_map

    for item in items:
        if not isinstance(item, dict):
            continue
        cat = normalize_category(item.get("category"))
        val = item.get("value")
        if not cat or not isinstance(val, str):
            continue
        val = normalize_text(val)
        if not val:
            continue
        key = build_memory_key(cat, val)
        stored = copy.deepcopy(item)
        stored["category"] = cat
        stored["value"] = val
        memory_map[key] = stored

    return memory_map


def run(replace=False):
    messages = load_messages()
    memory_map = {} if replace else load_existing_memory_map()
    limit = effective_message_limit()
    initial_rows = len(memory_map)
    merge_hits = 0
    new_inserts = 0

    for i, msg in enumerate(messages[:limit]):
        if msg.get("role") != "user":
            continue

        content = msg.get("content", "")
        if not isinstance(content, str):
            continue

        content = normalize_text(content)

        if not content or len(content.split()) < 5:
            continue

        print(f"➡️ Processing message {i}")

        results = extract_memory_with_ai(content)

        for raw_result in results:
            candidate = validate_candidate(raw_result)
            if not candidate:
                continue

            category = candidate["category"]
            value = candidate["value"]
            memory_key = build_memory_key(category, value)

            if memory_key in memory_map:
                merge_hits += 1
                memory_map[memory_key] = merge_memory(memory_map[memory_key], i)
            else:
                new_inserts += 1
                mid = allocate_memory_id(memory_map)
                memory_map[memory_key] = new_memory_item(mid, i, category, value)

    memory_items = list(memory_map.values())

    output = {
        "meta": {
            "schema_version": "2.0",
            "extractor_version": "AI-V2-filter-merge",
            "source": "imported.json",
            "message_limit": limit,
            "memory_count": len(memory_items),
            "last_extract": {
                "mode": "replace" if replace else "merge",
                "rows_before": initial_rows,
                "rows_after": len(memory_items),
                "new_keys_this_run": new_inserts,
                "reinforcements_this_run": merge_hits,
            },
        },
        "memory_items": memory_items
    }

    did_backup = backup_extracted_before_write()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    mode = "replace" if replace else "merge"
    print(f"\n✅ Extracted {len(memory_items)} filtered memory items ({mode}).")
    print(
        f"   This run: +{new_inserts} new, {merge_hits} reinforced "
        f"(was {initial_rows} rows → now {len(memory_items)})."
    )
    if did_backup:
        print(f"   Prior extract saved as {PRE_EXTRACT_BACKUP.name}")


if __name__ == "__main__":
    replace = "--replace" in sys.argv
    if replace:
        print("⚠️  --replace: existing extracted_memory.json rows are discarded before this run.")
    run(replace=replace)