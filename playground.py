import json
from pathlib import Path

from core.llm import ask_ai

MEMORY_FILE = Path("memory/extracted_memory.json")


def load_memory():
    if not MEMORY_FILE.exists():
        return []

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("memory_items", [])


def detect_question_type(user_input):
    user_text = user_input.lower()

    preference_keywords = [
        "prefer", "preference", "preferences", "learn", "learning",
        "style", "like to", "best for me", "how do i"
    ]
    project_keywords = [
        "working on", "building", "project", "creating", "developing",
        "making", "what am i working on"
    ]
    goal_keywords = [
        "goal", "goals", "want", "future", "long-term", "long term",
        "trying to", "aim", "purpose"
    ]

    if any(keyword in user_text for keyword in preference_keywords):
        return "preference"
    if any(keyword in user_text for keyword in project_keywords):
        return "project"
    if any(keyword in user_text for keyword in goal_keywords):
        return "goal"

    return "general"


def score_memory(memory, user_input, question_type):
    score = 0.0

    value = memory.get("value", "").lower()
    category = memory.get("category", "").lower()
    importance = memory.get("importance", 0.0)
    confidence = memory.get("confidence", 0.0)

    user_text = user_input.lower()

    for word in value.split():
        clean_word = word.strip(".,;:!?()[]{}\"'").lower()
        if clean_word and clean_word in user_text:
            score += 1.0

    score += importance
    score += (confidence * 2.0)

    if category == "project":
        score += 1.0
    elif category == "goal":
        score += 0.7
    elif category == "preference":
        score += 0.3

    if question_type == "preference" and category == "preference":
        score += 4.0
    elif question_type == "project" and category == "project":
        score += 4.0
    elif question_type == "goal" and category == "goal":
        score += 4.0

    if question_type == "preference" and category in {"project", "goal"}:
        score -= 1.5
    elif question_type == "project" and category in {"preference", "goal"}:
        score -= 1.5
    elif question_type == "goal" and category in {"project", "preference"}:
        score -= 1.5

    return score


def retrieve_relevant_memory(user_input, top_k=6):
    memory_items = load_memory()

    if not memory_items:
        return []

    question_type = detect_question_type(user_input)

    scored = []
    for mem in memory_items:
        score = score_memory(mem, user_input, question_type)
        scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)

    primary_memories = [mem for score, mem in scored if score >= 5.0][:3]

    if len(primary_memories) < 3:
        primary_memories = [mem for _, mem in scored[:3]]

    return primary_memories


def format_memory_block(memories):
    if not memories:
        return ""

    memories = sorted(memories, key=lambda m: m.get("confidence", 0.0), reverse=True)

    lines = []
    for mem in memories:
        category = mem.get("category", "unknown")
        value = mem.get("value", "")
        confidence = mem.get("confidence", 0.0)
        lines.append(f"- ({category}, confidence={confidence}) {value}")

    return "\n".join(lines)


def build_style_instruction(question_type):
    if question_type == "preference":
        return (
            "Answer in a personal, reflective, precise way. "
            "Focus on how the user tends to think, learn, or operate. "
            "Keep it direct and natural."
        )
    elif question_type == "project":
        return (
            "Answer in a concrete, grounded, practical way. "
            "State clearly what the user is building or working on. "
            "Favor specificity over abstraction."
        )
    elif question_type == "goal":
        return (
            "Answer in a strategic, higher-level way. "
            "Focus on direction, purpose, and long-term intent. "
            "Connect the current work to the bigger picture."
        )
    else:
        return (
            "Answer clearly, naturally, and concisely. "
            "Stay grounded in relevant memory."
        )


def build_messages(user_input):
    question_type = detect_question_type(user_input)
    memories = retrieve_relevant_memory(user_input)
    memory_block = format_memory_block(memories)
    style_instruction = build_style_instruction(question_type)

    system_prompt = f"""
You are the user's personal AI agent.

You have access to stored memory about the user.

If memory is provided, you MUST use it to answer when possible.
Prioritize high-confidence memory over weak signals.
Do NOT treat all memory equally.
If some memory is stronger, lean on it more.
Do NOT say you lack information if relevant memory is present.

Question type: {question_type}

Response style:
{style_instruction}

Answer naturally, clearly, and concisely.
Do not list things unnecessarily.
Focus on what matters most.
""".strip()

    if memory_block:
        system_prompt += "\n\nKnown memory about the user:\n" + memory_block

    messages = [
        {"role": "user", "content": user_input}
    ]

    return system_prompt, messages


def main():
    print("Agent ready")

    while True:
        user_input = input("You: ").strip()

        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        system_prompt, messages = build_messages(user_input)

        response = ask_ai(messages=messages, system_prompt=system_prompt)

        print("\nAI:\n")
        print(response)
        print()


if __name__ == "__main__":
    main()