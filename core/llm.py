import os

from anthropic import Anthropic
from dotenv import load_dotenv


load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

DEFAULT_SYSTEM_PROMPT = """
You are an AI agent.

If the user asks about a website or something you need to read online:

Respond ONLY with:
TOOL:fetch https://url

Do NOT explain.
Do NOT answer yet.

Otherwise:
Respond normally.
""".strip()


def ask_ai(messages, system_prompt=None):
    final_system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=700,
        system=final_system_prompt,
        messages=messages
    )
    return response.content[0].text.strip()