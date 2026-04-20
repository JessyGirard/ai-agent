from config.settings import (
    get_openai_api_key,
    get_openai_max_tokens,
    get_openai_model_name,
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


def llm_preflight_check():
    load_environment()

    issues = []
    api_key = get_openai_api_key()

    if not api_key:
        issues.append("Missing OPENAI_API_KEY environment variable.")

    try:
        from openai import OpenAI  # noqa: F401
    except Exception:
        issues.append("Missing dependency: openai (install with `pip install -r requirements.txt`).")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
    }


def _build_client():
    load_environment()

    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(
            "OpenAI SDK is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Add it to your environment or .env file."
        )

    return OpenAI(api_key=api_key)


def ask_ai(messages, system_prompt=None):
    final_system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    client = _build_client()

    api_messages = [{"role": "system", "content": final_system_prompt}]
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            continue
        api_messages.append({"role": role, "content": content})

    response = client.chat.completions.create(
        model=get_openai_model_name(),
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
