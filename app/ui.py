import sys
import os

# FIX IMPORT PATH (IMPORTANT)
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import tkinter as tk
from tools.fetch_page import fetch_page
from core.llm import ask_ai
from memory.memory import load_memory, save_memory

history = load_memory()

def send_message():
    user = entry.get().strip()
    if not user:
        return

    chat.insert(tk.END, f"You: {user}\n\n")
    entry.delete(0, tk.END)

    history.append({"role": "user", "content": user})

    reply = ask_ai(history)

    if reply.startswith("TOOL:fetch"):
        url = reply.replace("TOOL:fetch", "").strip()
        page = fetch_page(url)

        history.append({"role": "assistant", "content": reply})
        history.append({"role": "user", "content": f"CONTENT FROM {url}:\n\n{page}"})

        final_reply = ask_ai(history)
        history.append({"role": "assistant", "content": final_reply})

        chat.insert(tk.END, f"AI: {final_reply}\n\n")
    else:
        history.append({"role": "assistant", "content": reply})
        chat.insert(tk.END, f"AI: {reply}\n\n")

    save_memory(history)
    chat.see(tk.END)

root = tk.Tk()
root.title("AI Agent")

chat = tk.Text(root, wrap=tk.WORD, height=20, width=60)
chat.pack(padx=10, pady=10)

entry = tk.Entry(root, width=50)
entry.pack(padx=10, pady=(0, 10))
entry.bind("<Return>", lambda event: send_message())

send_btn = tk.Button(root, text="Send", command=send_message)
send_btn.pack(pady=(0, 10))

root.mainloop()