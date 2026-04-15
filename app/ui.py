import json
from pathlib import Path

from core.llm import chat


MEMORY_FILE = Path("memory/extracted_memory.json")


def load_memory():
    if not MEMORY_FILE.exists():
        return []

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("memory_items", [])


def score_memory(memory, user_input):
    score = 0

    value = memory.get("value", "").lower()
    category = memory.get("category", "")
    confidence = memory.get("confidence", 0.5)

    user_input = user_input.lower()

    # keyword overlap
    for word in value.split():
        if word in user_input:
            score += 1

    # boost by confidence
    score += confidence

    # category boost
    if category == "goal":
        score += 0.5
    if category == "project":
        score += 0.4

    return score


def retrieve_relevant_memory(user_input, top_k=5):
    memory_items = load_memory()

    if not memory_items:
        return []

    scored = []

    for mem in memory_items:
        score = score_memory(mem, user_input)
        if score > 0:
            scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [m for _, m in scored[:top_k]]


def format_memory_context(memories):
    if not memories:
        return ""

    lines = []
    for mem in memories:
        lines.append(f"- ({mem['category']}) {mem['value']}")

    return "\n".join(lines)


def build_prompt(user_input):
    memories = retrieve_relevant_memory(user_input)

    memory_block = format_memory_context(memories)

    system_prompt = "You are a helpful AI assistant."

    if memory_block:
        system_prompt += "\n\nRelevant known user context:\n"
        system_prompt += memory_block

    return system_prompt, user_input


def main():
    print("Agent ready")

    while True:
        user_input = input("You: ").strip()

        if user_input.lower() in {"exit", "quit"}:
            break

        system_prompt, user_message = build_prompt(user_input)

        response = chat(
            system_prompt=system_prompt,
            user_message=user_message
        )

        print("\nAI:\n")
        print(response)
        print()


if __name__ == "__main__":
    main()