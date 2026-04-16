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
