"""
Optional Playwright-backed fetch for public http(s) pages only.

Lazy-imports Playwright so ``FETCH_MODE=http`` users are not forced to install it.
Install: ``pip install playwright`` then ``playwright install chromium``.
"""

from __future__ import annotations

import json

_LOW_CONTENT_THRESHOLD = 80

# Visible main-content landmarks (fixed order; first longer candidate wins on tie via scan order).
_LANDMARK_SELECTORS = (
    "main",
    '[role="main"]',
    "article",
)

# Structured headlines: bounded node counts, deterministic DOM order, compact join.
_MAX_HEADLINE_NODES = 14
_HEADLINE_MERGED_CAP = 1800
_HEADLINE_JOIN = " | "


def _tag_message(tag: str, human: str) -> str:
    return f"[fetch:{tag}] {human}"


def _resolve_sync_playwright():
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ImportError:
        return None


def _chromium_launch_args() -> list[str]:
    """Best-effort transport hints for flaky HTTP/2 / QUIC (Chromium may ignore unknown flags)."""
    return [
        "--disable-http2",
        "--disable-quic",
    ]


def _goto_with_bounded_retries(page, url: str, timeout_ms: int) -> None:
    """
    Navigate with a small deterministic wait-strategy ladder (transport / slow-SPA friendly).

    Uses ``commit`` first (earliest navigation commit), then ``domcontentloaded``, then
    ``load``. Each attempt gets an equal slice of ``timeout_ms`` so total work stays bounded.
    """
    wait_sequence = ("commit", "domcontentloaded", "load")
    n = len(wait_sequence)
    per_attempt_ms = max(1000, timeout_ms // n)
    last_exc: Exception | None = None
    for idx, wait_until in enumerate(wait_sequence):
        try:
            page.goto(url, timeout=per_attempt_ms, wait_until=wait_until)
            return
        except Exception as exc:
            last_exc = exc
            if idx == n - 1:
                raise last_exc


def _bounded_post_goto_waits(page, cap_ms: int) -> None:
    """
    Bounded readiness after navigation. Order favors slow / SPA shells: confirm
    ``domcontentloaded``, try a short ``networkidle`` settle, then a brief ``load`` probe.
    Ignores timeouts so extraction can still run.
    """
    budget = max(2000, min(cap_ms, 12_000))
    third = max(800, budget // 3)
    attempts = (
        ("domcontentloaded", min(2000, third)),
        ("networkidle", min(4500, third * 2)),
        ("load", min(5000, max(1000, budget - third))),
    )
    for state, t in attempts:
        try:
            page.wait_for_load_state(state, timeout=t)
        except Exception:
            pass


def _inner_text_first_locator(page, selector: str, timeout_ms: int) -> str:
    """Best-effort visible text for ``selector`` (``.first``); empty string on miss/timeout."""
    try:
        loc = page.locator(selector).first
        return (loc.inner_text(timeout=timeout_ms) or "").strip()
    except Exception:
        return ""


def _bounded_extract_visible_text(page, inner_timeout: int) -> str:
    """
    Prefer main-content landmarks over a thin ``body`` shell when they yield more text.

    Deterministic: walk ``body`` then each landmark; keep the longest non-empty string.
    Per-selector timeouts are capped so total work stays bounded.
    """
    per = max(800, min(2500, max(500, inner_timeout // 4)))
    body_budget = min(inner_timeout, max(per * 2, 3000))
    chosen = _inner_text_first_locator(page, "body", body_budget)
    for sel in _LANDMARK_SELECTORS:
        t = _inner_text_first_locator(page, sel, per)
        if len(t) > len(chosen):
            chosen = t
    return chosen


def _maybe_one_lazy_scroll(page) -> None:
    """Single bounded scroll to surface lazy below-the-fold text; no clicks."""
    try:
        page.evaluate(
            "window.scrollBy(0, Math.min(1600, Math.floor((window.innerHeight || 600) * 1.25)))"
        )
    except Exception:
        return
    try:
        page.wait_for_timeout(350)
    except Exception:
        pass


def _headline_dedupe_key(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _bounded_extract_headlines(page, inner_timeout: int) -> str:
    """
    Collect visible headline lines (``h1`` / ``h2`` / ``role=heading`` / scoped headers)
    in a fixed deterministic order.

    De-duplicates normalized text, caps node count and merged length. Returns a single
    compact string (empty if nothing usable).
    """
    per = max(500, min(1800, inner_timeout // 10))
    seen: set[str] = set()
    pieces: list[str] = []
    nodes = 0

    headline_specs: tuple[tuple[str, int], ...] = (
        ("h1", 4),
        ("h2", 8),
        ('[role="heading"][aria-level="1"]', 4),
        ('[role="heading"][aria-level="2"]', 6),
        ("header h1", 2),
        ("header h2", 4),
        ("article h1", 2),
        ("article h2", 4),
    )

    def _drain_locator(loc, max_n: int) -> None:
        nonlocal nodes
        try:
            n = min(loc.count(), max_n)
        except Exception:
            return
        for i in range(n):
            if nodes >= _MAX_HEADLINE_NODES:
                return
            try:
                t = (loc.nth(i).inner_text(timeout=per) or "").strip()
                t = " ".join(t.split())
                if len(t) < 2:
                    continue
                key = _headline_dedupe_key(t)
                if key in seen:
                    continue
                seen.add(key)
                pieces.append(t)
                nodes += 1
            except Exception:
                continue

    try:
        for sel, cap in headline_specs:
            if nodes >= _MAX_HEADLINE_NODES:
                break
            _drain_locator(page.locator(sel), cap)
    except Exception:
        pass

    blob = _HEADLINE_JOIN.join(pieces).strip()
    if len(blob) > _HEADLINE_MERGED_CAP:
        blob = blob[:_HEADLINE_MERGED_CAP]
        cut = blob.rfind(_HEADLINE_JOIN)
        if cut > 40:
            blob = blob[:cut].strip()
    return blob


def _prefer_headline_blob_over_visible(headline_blob: str, visible: str) -> bool:
    """True when structured headlines should replace generic visible-text extraction."""
    hb = headline_blob.strip()
    if not hb:
        return False
    v = visible.strip()
    if len(hb) > len(v):
        return True
    # Thin shell pages: prefer even modest headline bundles over near-empty body text.
    if len(v) < _LOW_CONTENT_THRESHOLD and len(hb) >= max(16, len(v) + 4):
        return True
    return False


_DOM_EVAL_TEXT_MAX = 2800
_DOM_EVAL_STACK_MAX = 140

_MAX_DIAG_SUFFIX = 220

_PROBE_KEYS = frozenset({"b", "m", "r", "a", "h1", "h2", "bit", "bct", "js", "fb", "st"})
_MICRO_FB = 2
_PIPE_FB = 1


def _normalize_probe_dict(raw: dict) -> dict[str, int] | None:
    """Coerce Playwright / JSON probe payloads into stable int-only diagnostics."""
    out: dict[str, int] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or k not in _PROBE_KEYS:
            continue
        try:
            iv = int(float(v))
        except (TypeError, ValueError):
            continue
        out[k] = iv
    if not out:
        return None
    if out.get("js") == 0:
        out.pop("js", None)
    if out.get("fb") == 0:
        out.pop("fb", None)
    return out


def _probe_dict_from_evaluate_result(raw) -> dict[str, int] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return _normalize_probe_dict(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            data = json.loads(s)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            return _normalize_probe_dict(data)
    return None


def _bounded_dom_probe_micro_lengths(page, timeout_ms: int) -> dict[str, int] | None:
    """Third-tier: two tiny evaluates (innerText / textContent length only). ``fb=2``."""
    t = max(900, min(2800, int(timeout_ms) // 3))
    js_bit = "() => { try { const b = document.body; return b ? Math.min((b.innerText || '').length, 999999) : 0; } catch (_e) { return -1; } }"
    js_bct = "() => { try { const b = document.body; return b ? Math.min((b.textContent || '').length, 999999) : 0; } catch (_e) { return -1; } }"
    try:
        bit = page.evaluate(js_bit, timeout=t)
        bct = page.evaluate(js_bct, timeout=t)
    except Exception:
        return None
    try:
        ib = int(float(bit))
        ic = int(float(bct))
    except (TypeError, ValueError):
        return None
    if ib < 0 or ic < 0:
        return None
    b = 1 if (ib > 0 or ic > 0) else 0
    return _normalize_probe_dict(
        {"b": b, "bit": ib, "bct": ic, "m": 0, "r": 0, "a": 0, "h1": 0, "h2": 0, "fb": _MICRO_FB}
    )


def _bounded_dom_probe_fallback_pipe(page, timeout_ms: int) -> dict[str, int] | None:
    """
    Minimal second-chance probe: pipe-separated scalars, per-selector try/catch in JS.
    """
    js = """() => {
      try {
        const body = document.body;
        if (!body) return "0|0|0|0|0|0|0|0";
        const btc = Math.min((body.textContent || '').length, 999999);
        const bit = Math.min((body.innerText || '').length, 999999);
        let h1 = 0, h2 = 0;
        try { h1 = Math.min(document.querySelectorAll('h1').length, 30); } catch (_x) {}
        try { h2 = Math.min(document.querySelectorAll('h2').length, 30); } catch (_x) {}
        let m = 0, r = 0, a = 0;
        try { m = document.querySelector('main') ? 1 : 0; } catch (_x) {}
        try { r = document.querySelector('[role="main"]') ? 1 : 0; } catch (_x) {}
        try { a = document.querySelector('article') ? 1 : 0; } catch (_x) {}
        return [1, btc, bit, h1, h2, m, r, a].join('|');
      } catch (_e) {
        return "0|0|0|0|0|0|0|0";
      }
    }"""
    try:
        cut = max(1800, min(int(timeout_ms), 4500))
        raw = page.evaluate(js, timeout=cut)
    except Exception:
        return None
    if not isinstance(raw, str):
        return None
    parts = raw.strip().split("|")
    if len(parts) != 8:
        return None
    try:
        b, bct, bit, h1, h2, m, r, a = (int(float(x)) for x in parts)
    except (TypeError, ValueError):
        return None
    return _normalize_probe_dict(
        {"b": b, "bct": bct, "bit": bit, "h1": h1, "h2": h2, "m": m, "r": r, "a": a, "fb": _PIPE_FB}
    )


def _bounded_dom_probe_via_eval(page, timeout_ms: int) -> dict[str, int] | None:
    """
    Bounded in-page snapshot: landmark presence, headline counts, body text lengths.

    Primary path returns ``JSON.stringify`` output for reliable Playwright deserialization.
    On failure / empty parse: pipe-delimited fallback (``fb=1``), then micro length probe (``fb=2``).
    """
    js_json = """() => {
      try {
        const body = document.body;
        const bi = body ? (body.innerText || '').length : 0;
        const btc = body ? (body.textContent || '').length : 0;
        let m = 0, r = 0, a = 0, h1 = 0, h2 = 0;
        try { m = document.querySelector('main') ? 1 : 0; } catch (_x) {}
        try { r = document.querySelector('[role="main"]') ? 1 : 0; } catch (_x) {}
        try { a = document.querySelector('article') ? 1 : 0; } catch (_x) {}
        try { h1 = Math.min(document.querySelectorAll('h1').length, 30); } catch (_x) {}
        try { h2 = Math.min(document.querySelectorAll('h2').length, 30); } catch (_x) {}
        const payload = {
          b: body ? 1 : 0,
          m: m,
          r: r,
          a: a,
          h1: h1,
          h2: h2,
          bit: Math.min(bi, 999999),
          bct: Math.min(btc, 999999),
        };
        return JSON.stringify(payload);
      } catch (_e) {
        return JSON.stringify({b:0,m:0,r:0,a:0,h1:0,h2:0,bit:0,bct:0,js:1});
      }
    }"""
    cut = max(3000, min(int(timeout_ms), 6500))
    raw_primary = None
    for mult in (1.0, 0.92):
        try:
            raw_primary = page.evaluate(js_json, timeout=max(2800, min(int(cut * mult), 6500)))
        except Exception:
            raw_primary = None
        primary = _probe_dict_from_evaluate_result(raw_primary)
        if primary is not None:
            return primary
    fb = _bounded_dom_probe_fallback_pipe(page, timeout_ms)
    if fb is not None:
        return fb
    micro = _bounded_dom_probe_micro_lengths(page, timeout_ms)
    if micro is not None:
        return micro
    # Navigation reached probe phase but every bounded evaluate path failed in Python/transport.
    return _normalize_probe_dict({"st": 1})


def _nav_exc_class(exc: Exception) -> str:
    """Stable coarse class for operator / logs (not a new fetch tag)."""
    low = str(exc).lower()
    tname = type(exc).__name__.lower()
    if "net::" in low or "err_" in low:
        return "blocked_transport"
    if "goto" in low and ("timeout" in low or "exceeded" in low):
        return "goto_timeout"
    if "goto" in low:
        return "goto_failed"
    if "inner_text" in low or "locator" in low:
        if "timeout" in low or "exceeded" in low or "timeout" in tname:
            return "extract_timeout"
        return "extract_failed"
    if "timeout" in low or "timeout" in tname:
        return "timeout"
    return "error"


def _compact_diag_suffix(
    dom_probe: dict[str, int] | None,
    *,
    exc: Exception | None = None,
    merged_len: int | None = None,
    probe_attempted: bool = False,
) -> str:
    parts: list[str] = []
    if exc is not None:
        parts.append(f"exc={_nav_exc_class(exc)}")
    if merged_len is not None:
        parts.append(f"mrg={merged_len}")
    if dom_probe:
        for k in sorted(dom_probe.keys()):
            parts.append(f"{k}={dom_probe[k]}")
    elif probe_attempted:
        parts.append("probe=failed")
    else:
        parts.append("probe=none")
    s = ";".join(parts)
    if len(s) > _MAX_DIAG_SUFFIX:
        s = s[:_MAX_DIAG_SUFFIX]
    return f" diag={s}"


def _bounded_dom_text_nodes_via_eval(page, timeout_ms: int) -> str:
    """
    Alternate read: bounded depth-first walk of **text nodes** under ``main`` /
    ``[role="main"]`` / ``body``, skipping script/style. Uses ``textContent``-style
    aggregation in-page (not Playwright ``inner_text`` / headline locators).

    Deterministic caps on stack steps and output length; ``page.evaluate`` timeout bounded.
    """
    js = """() => {
      const skip = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE']);
      const root = document.querySelector('main')
        || document.querySelector('[role="main"]')
        || document.body;
      if (!root) return '';
      const chunks = [];
      let total = 0;
      const maxTotal = __MAX__;
      const stack = [root];
      let steps = 0;
      const maxSteps = __STEPS__;
      while (stack.length > 0 && steps < maxSteps && total < maxTotal) {
        steps++;
        const node = stack.pop();
        if (!node) continue;
        if (node.nodeType === 3) {
          const t = (node.textContent || '').replace(/\\s+/g, ' ').trim();
          if (t.length >= 2) {
            chunks.push(t);
            total += t.length + 1;
          }
          continue;
        }
        if (node.nodeType !== 1) continue;
        if (skip.has(node.tagName)) continue;
        const kids = node.childNodes;
        for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
      }
      let out = chunks.join(' ').replace(/\\s+/g, ' ').trim();
      if (out.length > maxTotal) out = out.slice(0, maxTotal);
      return out;
    }""".replace("__MAX__", str(_DOM_EVAL_TEXT_MAX)).replace("__STEPS__", str(_DOM_EVAL_STACK_MAX))
    try:
        cut = max(2000, min(int(timeout_ms), 5000))
        result = page.evaluate(js, timeout=cut)
    except Exception:
        return ""
    if not isinstance(result, str):
        return ""
    return " ".join(result.split()).strip()


def fetch_via_browser(url: str, timeout_seconds: int = 20) -> str:
    """
    Navigate with Chromium (headless), wait in a bounded way, return title + visible page text
    (landmark-biased visible text, optional bounded scroll, structured headlines when they beat
    thin generic text, then a bounded **text-node** ``evaluate`` read when it improves on that
    body text), or a stable ``[fetch:<tag>]`` line on failure. Hard failures and ``low_content``
    may append a compact ``diag=…`` suffix (bounded) from a post-navigation DOM probe.
    Public http(s) only; no login or multi-page flows.
    """
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return _tag_message(
            "browser_invalid_url",
            "Browser fetch supports public http(s) URLs only (no file:// or other schemes).",
        )

    sync_playwright = _resolve_sync_playwright()
    if sync_playwright is None:
        return _tag_message(
            "browser_unavailable",
            "Playwright is not installed. Run: pip install playwright && playwright install chromium",
        )

    timeout_ms = max(3000, min(int(timeout_seconds * 1000), 120_000))
    inner_timeout = min(10_000, timeout_ms)

    title = ""
    body_text = ""
    dom_probe: dict[str, int] | None = None
    probe_attempted = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=_chromium_launch_args())
            try:
                page = browser.new_page()
                _goto_with_bounded_retries(page, url, timeout_ms)
                _bounded_post_goto_waits(page, timeout_ms)
                probe_attempted = True
                dom_probe = _bounded_dom_probe_via_eval(page, inner_timeout)
                title = (page.title() or "").strip()
                headlines_before = _bounded_extract_headlines(page, inner_timeout)
                body_text = _bounded_extract_visible_text(page, inner_timeout)
                if len(body_text) < _LOW_CONTENT_THRESHOLD:
                    _maybe_one_lazy_scroll(page)
                    body_text = _bounded_extract_visible_text(page, inner_timeout)
                    headlines_after = _bounded_extract_headlines(page, inner_timeout)
                    headline_blob = (
                        headlines_after
                        if len(headlines_after) > len(headlines_before)
                        else headlines_before
                    )
                else:
                    headline_blob = headlines_before
                if _prefer_headline_blob_over_visible(headline_blob, body_text):
                    body_text = headline_blob
                dom_eval_blob = _bounded_dom_text_nodes_via_eval(page, inner_timeout)
                if _prefer_headline_blob_over_visible(dom_eval_blob, body_text):
                    body_text = dom_eval_blob
            finally:
                browser.close()
    except Exception as exc:
        low = str(exc).lower()
        tname = type(exc).__name__.lower()
        if "timeout" in low or "timeout" in tname:
            return _tag_message(
                "browser_timeout",
                f"Browser navigation or extraction timed out. Detail: {exc}"
                f"{_compact_diag_suffix(dom_probe, exc=exc, probe_attempted=probe_attempted)}",
            )
        if "executable" in low and "exist" in low:
            return _tag_message(
                "browser_unavailable",
                "Playwright browser binary missing. Run: playwright install chromium",
            )
        return _tag_message(
            "browser_error",
            f"Browser fetch failed. Detail: {exc}"
            f"{_compact_diag_suffix(dom_probe, exc=exc, probe_attempted=probe_attempted)}",
        )

    parts = []
    if title:
        parts.append(title)
    if body_text:
        parts.append(body_text)
    merged = " ".join("\n\n".join(parts).split())

    if not merged:
        return _tag_message(
            "low_content",
            "Browser opened the page but extracted no visible text (empty or highly dynamic body)."
            f"{_compact_diag_suffix(dom_probe, merged_len=0, probe_attempted=probe_attempted)}",
        )
    if len(merged) < _LOW_CONTENT_THRESHOLD:
        snippet = merged if len(merged) <= 240 else merged[:240] + "…"
        return _tag_message(
            "low_content",
            f"Browser extracted very little text ({len(merged)} characters). Snippet: {snippet}"
            f"{_compact_diag_suffix(dom_probe, merged_len=len(merged), probe_attempted=probe_attempted)}",
        )

    return merged[:4000]
