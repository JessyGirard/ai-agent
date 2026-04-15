import json
import os

MEMORY_FILE = "memory/history.json"

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return []
    with open(MEMORY_FILE, "r") as f:
        return json.load(f)

def save_memory(history):
    with open(MEMORY_FILE, "w") as f:
        json.dump(history[-10:], f, indent=2)