import requests
from bs4 import BeautifulSoup

def fetch_page(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text = soup.get_text(" ", strip=True)
        text = " ".join(text.split())

        return text[:4000] if text else "[No text]"
    except Exception as e:
        return f"[fetch error] {e}"