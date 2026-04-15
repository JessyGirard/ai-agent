import json

RAW_FILE = "memory/raw_chat.txt"
OUT_FILE = "memory/imported.json"


def parse_chat(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    messages = []
    current_role = "user"  # alternate user → assistant → user → assistant

    for line in lines:
        messages.append({
            "role": current_role,
            "content": line
        })

        # flip role each time
        current_role = "assistant" if current_role == "user" else "user"

    return messages


def main():
    with open(RAW_FILE, "r", encoding="utf-8") as f:
        raw = f.read()

    messages = parse_chat(raw)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=2)

    print(f"Imported {len(messages)} messages.")


if __name__ == "__main__":
    main()