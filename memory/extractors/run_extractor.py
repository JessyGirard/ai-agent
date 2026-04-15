import json
import os
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


def load_messages():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_memory_with_ai(text):
    prompt = f"""
Extract meaningful long-term memory about the user.

Return ONLY JSON.

Either:
{{ "category": "...", "value": "..." }}

OR:
[{{ "category": "...", "value": "..." }}]

Categories:
identity, goal, preference, project

INPUT:
{text}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "Extract user memory."},
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
        print(f"❌ Error: {e}")
        return []


def build_memory_item(idx, category, value):
    return {
        "memory_id": f"mem_{idx:04d}",
        "category": category,
        "value": value,
        "confidence": 0.9,
        "importance": 0.8,
        "stability": "medium",
        "status": "active",
        "source_refs": [f"msg_{idx}"]
    }


def run():
    messages = load_messages()
    memory_items = []

    LIMIT = 50

    for i, msg in enumerate(messages[:LIMIT]):
        if msg.get("role") != "user":
            continue

        print(f"➡️ Processing message {i}")

        content = msg.get("content", "").strip()

        if not content or len(content.split()) < 5:
            continue

        results = extract_memory_with_ai(content)

        for result in results:
            category = result.get("category")
            value = result.get("value")

            if not category or not value:
                continue

            item = build_memory_item(i, category, value)
            memory_items.append(item)

    output = {
        "meta": {
            "schema_version": "1.0",
            "extractor_version": "AI-1.4",
            "source": "imported.json"
        },
        "memory_items": memory_items
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Extracted {len(memory_items)} intelligent memory items.")


if __name__ == "__main__":
    run()