"""Stable fetch entrypoint for ``playground``; delegates to mode-specific backends."""

from __future__ import annotations

import os
import re
from collections.abc import Callable

from tools.fetch_browser import fetch_via_browser
from tools.fetch_http import fetch_via_http

_DEFAULT_BROWSER_TIMEOUT = 20
_MIN_BROWSER_TIMEOUT = 5
_MAX_BROWSER_TIMEOUT = 120


def browser_timeout_seconds_from_env() -> int:
    """
    Seconds for Playwright navigation/extraction budget in browser mode only.

    Set ``FETCH_BROWSER_TIMEOUT_SECONDS`` (integer); clamped to 5–120. Invalid or
    empty values use the default (20).
    """
    raw = os.environ.get("FETCH_BROWSER_TIMEOUT_SECONDS")
    if raw is None or not str(raw).strip():
        return _DEFAULT_BROWSER_TIMEOUT
    try:
        n = int(str(raw).strip(), 10)
    except ValueError:
        return _DEFAULT_BROWSER_TIMEOUT
    return max(_MIN_BROWSER_TIMEOUT, min(n, _MAX_BROWSER_TIMEOUT))


def _browser_adapter(url: str) -> str:
    return fetch_via_browser(url, timeout_seconds=browser_timeout_seconds_from_env())


# ``browser`` = Playwright Chromium headless (public http(s) only). See tools/fetch_browser.py.
_FETCH_BACKENDS: dict[str, Callable[[str], str]] = {
    "http": fetch_via_http,
    "browser": _browser_adapter,
}


def fetch_page(url: str) -> str:
    """
    Public facade: same contract as always (plain text or ``[fetch:<tag>]`` lines).

    ``FETCH_MODE`` selects the backend name (default ``http``). Unknown modes fall
    back to HTTP so runtime behavior matches the historical single-path implementation.
    """
    mode = (os.environ.get("FETCH_MODE") or "http").strip().lower()
    backend = _FETCH_BACKENDS.get(mode, fetch_via_http)
    return backend(url)


def fetch_failure_tag(fetched: str) -> str | None:
    """
    If ``fetched`` is a structured fetch result, return the tag (e.g. ``timeout``).
    Otherwise return None (normal page text).
    """
    if not isinstance(fetched, str):
        return None
    s = fetched.strip()
    m = re.match(r"^\[fetch:([a-z0-9_]+)\]\s", s, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower()
