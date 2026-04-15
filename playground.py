import os
from dotenv import load_dotenv
from tools.fetch_page import fetch_page
from core.llm import ask_ai
from memory.memory import load_memory, save_memory

load_dotenv()

print("Agent ready")

history = load_memory()

while True:
    user = input("You: ").strip()

    if user in ["exit", "quit"]:
        break

    history.append({"role": "user", "content": user})

    # FIRST AI CALL (decides what to do)
    reply = ask_ai(history)

    # TOOL DETECTION
    if reply.startswith("TOOL:fetch"):
        url = reply.replace("TOOL:fetch", "").strip()

        page = fetch_page(url)

        tool_msg = f"CONTENT FROM {url}:\n\n{page}"
        history.append({"role": "assistant", "content": reply})
        history.append({"role": "user", "content": tool_msg})

        # SECOND AI CALL (uses the data)
        final_reply = ask_ai(history)

        history.append({"role": "assistant", "content": final_reply})
        save_memory(history)

        print("\nAI:\n")
        print(final_reply)
        print()
        continue

    # NORMAL RESPONSE
    history.append({"role": "assistant", "content": reply})
    save_memory(history)

    print("\nAI:\n")
    print(reply)
    print()