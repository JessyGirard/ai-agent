from config.settings import get_api_key, get_max_tokens, get_model_name, load_environment

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


def llm_preflight_check():
    load_environment()

    issues = []
    api_key = get_api_key()

    if not api_key:
        issues.append("Missing ANTHROPIC_API_KEY environment variable.")

    try:
        from anthropic import Anthropic  # noqa: F401
    except Exception:
        issues.append("Missing dependency: anthropic (install with `pip install -r requirements.txt`).")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
    }


def _build_client():
    load_environment()

    try:
        from anthropic import Anthropic
    except Exception as exc:
        raise RuntimeError(
            "Anthropic SDK is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    api_key = get_api_key()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is missing. Add it to your environment or .env file."
        )

    return Anthropic(api_key=api_key)


def ask_ai(messages, system_prompt=None):
    final_system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    client = _build_client()

    response = client.messages.create(
        model=get_model_name(),
        max_tokens=get_max_tokens(),
        system=final_system_prompt,
        messages=messages
    )
    return response.content[0].text.strip()


def chat(system_prompt, user_message):
    return ask_ai(
        messages=[{"role": "user", "content": user_message}],
        system_prompt=system_prompt,
    )