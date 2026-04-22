"""
Redaction helpers for Tool 1 run-log records.

Separated from ``tool1_run_log.py`` to keep logging assembly and
security/sanitization concerns isolated and easier to maintain.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_KEY_TOKENS = ("authorization", "token", "password", "secret", "api_key", "apikey")


def _looks_sensitive_key(key: str) -> bool:
    k = str(key or "").strip().lower().replace("-", "_")
    return any(tok in k for tok in _SENSITIVE_KEY_TOKENS)


def _redact_textual_token(value: Any) -> Any:
    if value is None:
        return None
    return "[REDACTED]"


def _redact_headers_map(headers: Any) -> Any:
    if not isinstance(headers, dict):
        return headers
    out: dict[str, Any] = {}
    for k, v in headers.items():
        ks = str(k)
        if _looks_sensitive_key(ks):
            out[ks] = _redact_textual_token(v)
        else:
            out[ks] = v
    return out


def _redact_free_text(text: Any) -> Any:
    if not isinstance(text, str) or not text:
        return text
    out = text
    out = re.sub(
        r'(?i)\b(authorization\s*:\s*bearer\s+)[^\s,;"]+',
        r"\1[REDACTED]",
        out,
    )
    out = re.sub(
        r'(?i)([?&](?:token|access_token|api_key|apikey|password|secret)=)[^&\s]+',
        r"\1[REDACTED]",
        out,
    )
    out = re.sub(
        r'(?i)("?(?:token|access_token|api_key|apikey|password|secret)"?\s*[:=]\s*"?)([^",\s}]+)',
        r"\1[REDACTED]",
        out,
    )
    return out


def _redact_query_params_json_raw(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    raw = text.strip()
    if not raw:
        return text
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return _redact_free_text(text)
    if not isinstance(obj, dict):
        return _redact_free_text(text)
    redacted: dict[str, Any] = {}
    for k, v in obj.items():
        if _looks_sensitive_key(str(k)):
            redacted[str(k)] = "[REDACTED]"
        else:
            redacted[str(k)] = v
    return json.dumps(redacted, ensure_ascii=False)


def _redact_url_query(url: Any) -> Any:
    if not isinstance(url, str):
        return url
    s = url.strip()
    if not s:
        return url
    try:
        parts = urlsplit(s)
        q = dict(parse_qsl(parts.query, keep_blank_values=True))
    except Exception:
        return url
    if not q:
        return url
    changed = False
    out_q: dict[str, str] = {}
    for k, v in q.items():
        if _looks_sensitive_key(k):
            out_q[k] = "[REDACTED]"
            changed = True
        else:
            out_q[k] = v
    if not changed:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(list(out_q.items())), parts.fragment))


def _redact_request_input_snapshot(snap: Any) -> Any:
    if not isinstance(snap, dict):
        return snap
    out = dict(snap)
    for k in list(out.keys()):
        if _looks_sensitive_key(str(k)):
            out[k] = _redact_textual_token(out.get(k))
    raw_headers = out.get("headers_json_raw")
    if isinstance(raw_headers, str) and raw_headers.strip():
        try:
            hdr_obj = json.loads(raw_headers)
        except (ValueError, TypeError):
            out["headers_json_raw"] = _redact_free_text(raw_headers)
        else:
            if isinstance(hdr_obj, dict):
                out["headers_json_raw"] = json.dumps(_redact_headers_map(hdr_obj), ensure_ascii=False)
            else:
                out["headers_json_raw"] = _redact_free_text(raw_headers)
    out["query_params_json_raw"] = _redact_query_params_json_raw(out.get("query_params_json_raw"))
    out["url"] = _redact_url_query(out.get("url"))
    return out


def redact_tool1_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        return record
    out = copy.deepcopy(record)
    reqs = out.get("requests")
    if isinstance(reqs, list):
        redacted_reqs: list[Any] = []
        for r in reqs:
            if not isinstance(r, dict):
                redacted_reqs.append(r)
                continue
            rr = dict(r)
            rr["headers"] = _redact_headers_map(rr.get("headers"))
            rr["url"] = _redact_url_query(rr.get("url"))
            redacted_reqs.append(rr)
        out["requests"] = redacted_reqs
    outcomes = out.get("cases_outcome")
    if isinstance(outcomes, list):
        redacted_outcomes: list[Any] = []
        for c in outcomes:
            if not isinstance(c, dict):
                redacted_outcomes.append(c)
                continue
            cc = dict(c)
            cc["response_headers"] = _redact_headers_map(cc.get("response_headers"))
            atts = cc.get("attempts")
            if isinstance(atts, list):
                redacted_atts: list[Any] = []
                for a in atts:
                    if not isinstance(a, dict):
                        redacted_atts.append(a)
                        continue
                    aa = dict(a)
                    aa["response_headers"] = _redact_headers_map(aa.get("response_headers"))
                    redacted_atts.append(aa)
                cc["attempts"] = redacted_atts
            redacted_outcomes.append(cc)
        out["cases_outcome"] = redacted_outcomes
    out["request_input_snapshot"] = _redact_request_input_snapshot(out.get("request_input_snapshot"))
    out["query_params_raw_json"] = _redact_query_params_json_raw(out.get("query_params_raw_json"))
    out["error"] = _redact_free_text(out.get("error"))
    if isinstance(out.get("summary"), str):
        out["summary"] = _redact_free_text(out.get("summary"))
    co = out.get("cases_outcome")
    if isinstance(co, list):
        for c in co:
            if not isinstance(c, dict):
                continue
            fails = c.get("failures")
            if isinstance(fails, list):
                c["failures"] = [_redact_free_text(f) for f in fails]
            atts = c.get("attempts")
            if isinstance(atts, list):
                for a in atts:
                    if not isinstance(a, dict):
                        continue
                    af = a.get("failures")
                    if isinstance(af, list):
                        a["failures"] = [_redact_free_text(f) for f in af]
    return out
