"""HTTP-only fetch implementation (requests + BeautifulSoup). Used by ``fetch_page`` facade."""

import requests
from bs4 import BeautifulSoup
from requests import ConnectionError as RequestsConnectionError
from requests import Timeout
from requests.exceptions import RequestException

_LOW_CONTENT_THRESHOLD = 80


def _tag_message(tag: str, human: str) -> str:
    return f"[fetch:{tag}] {human}"


def fetch_via_http(url: str) -> str:
    """
    GET url, strip scripts/styles, return plain text (capped) or a tagged explanation.

    Success returns raw extracted text (no prefix). Failures and thin fetches use
    a stable ``[fetch:<tag>]`` prefix so operators and the post-fetch LLM can see why.
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MimiAgent/1.0)"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
    except Timeout:
        return _tag_message(
            "timeout",
            "The request exceeded the 10 second limit (server slow or stalled).",
        )
    except RequestsConnectionError as exc:
        return _tag_message(
            "network",
            "Could not reach the host (DNS failure, connection refused, or TLS problem). "
            f"Detail: {exc}",
        )
    except RequestException as exc:
        return _tag_message(
            "error",
            f"Request failed before a usable HTTP response. Detail: {exc}",
        )

    code = r.status_code
    if code == 401:
        return _tag_message(
            "auth_required",
            "HTTP 401 Unauthorized. The page expects login, cookies, or credentials; "
            "this fetcher cannot authenticate.",
        )
    if code == 403:
        return _tag_message(
            "forbidden",
            "HTTP 403 Forbidden. The server denied access (bot filter, geo block, WAF, or permission).",
        )
    if code == 429:
        return _tag_message(
            "rate_limited",
            "HTTP 429 Too Many Requests. Try again later or use a lighter URL.",
        )
    if 400 <= code < 500:
        return _tag_message(
            "http_client_error",
            f"HTTP {code} client error. The origin rejected this request for this URL or client.",
        )
    if code >= 500:
        return _tag_message(
            "http_server_error",
            f"HTTP {code} server error. The origin failed while handling the request.",
        )
    if code != 200:
        return _tag_message(
            "http_other",
            f"HTTP {code} response. This path expects a normal 200 HTML page; try another URL or paste the text you need.",
        )

    try:
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        text = " ".join(text.split())
    except Exception as exc:  # noqa: BLE001 — surface parse failures to caller as text
        return _tag_message("parse_error", f"Could not parse response as HTML. Detail: {exc}")

    if not text:
        return _tag_message(
            "low_content",
            "No readable text after removing scripts/styles. "
            "Common causes: JavaScript-only UI, login wall, CAPTCHA, or non-HTML body.",
        )

    if len(text) < _LOW_CONTENT_THRESHOLD:
        snippet = text if len(text) <= 240 else text[:240] + "…"
        return _tag_message(
            "low_content",
            f"Very little text was extracted ({len(text)} characters). "
            "The page may be mostly JavaScript, images, or gated content. Snippet: "
            f"{snippet}",
        )

    return text[:4000]
