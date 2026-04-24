import requests

from config.settings import get_brave_api_key, load_environment

BRAVE_WEB_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def brave_search(query: str) -> dict:
    """Minimal Brave Web Search client.

    Returns a small normalized payload with:
    - ok (bool)
    - status_code (int | None)
    - query (str)
    - results (list[{title, snippet, url}])
    - error (str | None)
    """
    load_environment()
    api_key = get_brave_api_key()
    q = (query or "").strip()
    if not q:
        return {
            "ok": False,
            "status_code": None,
            "query": q,
            "results": [],
            "error": "Missing query: provide a non-empty search query.",
        }
    if not api_key:
        return {
            "ok": False,
            "status_code": None,
            "query": q,
            "results": [],
            "error": "Missing BRAVE_API_KEY: add it to your environment or .env file.",
        }

    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }
    params = {
        "q": q,
        "count": 5,
    }

    try:
        response = requests.get(
            BRAVE_WEB_SEARCH_ENDPOINT,
            headers=headers,
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status_code": None,
            "query": q,
            "results": [],
            "error": f"Brave request failed: {exc}",
        }

    status_code = int(response.status_code)
    if status_code != 200:
        body_preview = (response.text or "").strip()
        if len(body_preview) > 300:
            body_preview = body_preview[:300] + "..."
        return {
            "ok": False,
            "status_code": status_code,
            "query": q,
            "results": [],
            "error": f"Brave API error ({status_code}): {body_preview}",
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "ok": False,
            "status_code": status_code,
            "query": q,
            "results": [],
            "error": "Brave API returned non-JSON response.",
        }

    raw_results = ((payload or {}).get("web") or {}).get("results") or []
    results = []
    for row in raw_results[:5]:
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("description") or "").strip()
        url = str(row.get("url") or "").strip()
        if not (title or snippet or url):
            continue
        results.append(
            {
                "title": title,
                "snippet": snippet,
                "url": url,
            }
        )

    return {
        "ok": True,
        "status_code": status_code,
        "query": q,
        "results": results,
        "error": None,
    }
