from config.settings import (
    get_openai_api_key,
    get_openai_api_key_brain,
    get_openai_brain_model_name,
    get_openai_max_tokens,
    get_openai_model_name,
    get_use_brain,
    load_environment,
)

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


def _active_openai_key_and_model():
    """Single env decision: baseline OpenAI vs brain (USE_BRAIN)."""
    load_environment()
    if get_use_brain():
        api_key = get_openai_api_key_brain()
        model = get_openai_brain_model_name()
        if not api_key:
            raise RuntimeError(
                "USE_BRAIN is enabled but OPENAI_API_KEY_BRAIN is missing or empty."
            )
        if not model:
            raise RuntimeError(
                "USE_BRAIN is enabled but OPENAI_BRAIN_MODEL is missing or empty."
            )
        return api_key, model
    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Add it to your environment or .env file."
        )
    return api_key, get_openai_model_name()


def llm_preflight_check():
    load_environment()

    issues = []
    try:
        _active_openai_key_and_model()
    except RuntimeError as exc:
        issues.append(str(exc))

    try:
        from openai import OpenAI  # noqa: F401
    except Exception:
        issues.append("Missing dependency: openai (install with `pip install -r requirements.txt`).")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
    }


def _build_client(api_key: str):
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(
            "OpenAI SDK is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    return OpenAI(api_key=api_key)


def ask_ai(messages, system_prompt=None):
    final_system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    api_key, model_name = _active_openai_key_and_model()
    client = _build_client(api_key)

    api_messages = [{"role": "system", "content": final_system_prompt}]
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            continue
        api_messages.append({"role": role, "content": content})

    response = client.chat.completions.create(
        model=model_name,
        max_tokens=get_openai_max_tokens(),
        messages=api_messages,
    )
    choice = response.choices[0].message
    text = (choice.content or "").strip()
    return text


def chat(system_prompt, user_message):
    return ask_ai(
        messages=[{"role": "user", "content": user_message}],
        system_prompt=system_prompt,
    )
