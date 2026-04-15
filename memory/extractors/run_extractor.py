import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is missing from .env")

client = OpenAI(api_key=OPENAI_API_KEY)

INPUT_FILE = PROJECT_ROOT / "memory" / "imported.json"
OUTPUT_FILE = PROJECT_ROOT / "memory" / "extracted_memory.json"

ALLOWED_CATEGORIES = {"identity", "goal", "preference", "project"}
LIMIT = 50


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
Extract meaningful long-term memory about the user.

Only extract durable things that could matter later:
- identity
- goals
- preferences
- projects

Do NOT extract:
- temporary moods
- greetings
- filler
- one-off reactions
- assistant information
- generic technical statements unless they clearly describe the user's real project
- raw transcript artifacts

Return ONLY valid JSON.

Either:
{{ "category": "...", "value": "..." }}

OR:
[
  {{ "category": "...", "value": "..." }}
]

Categories allowed:
identity, goal, preference, project

INPUT:
{text}
"""

    try:
        response = client.chat.completions.create(
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

    if looks_like_noise(value):
        return None

    return {
        "category": category,
        "value": value
    }


def new_memory_item(idx, category, value):
    evidence_count = 1

    return {
        "memory_id": f"mem_{idx:04d}",
        "category": category,
        "value": value,
        "confidence": estimate_confidence(evidence_count),
        "importance": estimate_importance(category, value),
        "status": "active",
        "memory_kind": classify_memory_kind(evidence_count),
        "evidence_count": evidence_count,
        "first_seen": f"msg_{idx}",
        "last_seen": f"msg_{idx}",
        "trend": "new",
        "source_refs": [f"msg_{idx}"]
    }


def merge_memory(existing_item, msg_idx):
    existing_item["evidence_count"] += 1
    existing_item["last_seen"] = f"msg_{msg_idx}"
    existing_item["confidence"] = estimate_confidence(existing_item["evidence_count"])
    existing_item["memory_kind"] = classify_memory_kind(existing_item["evidence_count"])
    existing_item["trend"] = "reinforced"

    msg_ref = f"msg_{msg_idx}"
    if msg_ref not in existing_item["source_refs"]:
        existing_item["source_refs"].append(msg_ref)

    return existing_item


def run():
    messages = load_messages()
    memory_map = {}

    for i, msg in enumerate(messages[:LIMIT]):
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
                memory_map[memory_key] = merge_memory(memory_map[memory_key], i)
            else:
                memory_map[memory_key] = new_memory_item(i, category, value)

    memory_items = list(memory_map.values())

    output = {
        "meta": {
            "schema_version": "2.0",
            "extractor_version": "AI-V2-filter-merge",
            "source": "imported.json",
            "message_limit": LIMIT,
            "memory_count": len(memory_items)
        },
        "memory_items": memory_items
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Extracted {len(memory_items)} filtered memory items.")


if __name__ == "__main__":
    run()