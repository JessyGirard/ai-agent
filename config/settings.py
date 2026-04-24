import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


def load_environment():
    load_dotenv(dotenv_path=ENV_FILE if ENV_FILE.exists() else None)


def get_model_name():
    return os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-0")


def get_max_tokens():
    raw = os.getenv("ANTHROPIC_MAX_TOKENS", "700")
    try:
        return int(raw)
    except ValueError:
        return 700


def get_api_key():
    return os.getenv("ANTHROPIC_API_KEY", "").strip()


def get_openai_api_key():
    return os.getenv("OPENAI_API_KEY", "").strip()


def get_openai_model_name():
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def get_openai_max_tokens():
    raw = os.getenv("OPENAI_MAX_TOKENS", "700")
    try:
        return int(raw)
    except ValueError:
        return 700


def get_use_brain() -> bool:
    raw = os.getenv("USE_BRAIN", "").strip().lower()
    return raw in ("true", "1", "yes", "on")


def get_openai_api_key_brain() -> str:
    return os.getenv("OPENAI_API_KEY_BRAIN", "").strip()


def get_openai_brain_model_name() -> str:
    return os.getenv("OPENAI_BRAIN_MODEL", "").strip()


def get_brave_api_key() -> str:
    return os.getenv("BRAVE_API_KEY", "").strip()
