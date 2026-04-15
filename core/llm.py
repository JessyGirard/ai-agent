import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """
You are an AI agent.

If the user asks about a website or something you need to read online:

Respond ONLY with:
TOOL:fetch https://url

Do NOT explain.
Do NOT answer yet.

Otherwise:
Respond normally.
"""

def ask_ai(messages):
    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=700,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    return response.content[0].text.strip()