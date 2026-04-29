import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from core import system_eval_status_coercion

SYSTEM_EVAL_LANES = frozenset({"stability", "correctness", "consistency", "prompt_response", "smoke"})
CONSISTENCY_REPEAT_DEFAULT = 3
CONSISTENCY_REPEAT_MAX = 50
STABILITY_ATTEMPTS_DEFAULT = 3
STABILITY_ATTEMPTS_MAX = 50

# HTTP methods that send a JSON body by default (Tool 1 / system_eval suite semantics).
_METHODS_DEFAULT_JSON_BODY = frozenset({"POST", "PUT", "PATCH"})

# Bounds for response header capture (artifacts must stay JSON-safe and reasonably sized).
_RESPONSE_HEADERS_MAX_ITEMS = 64
_RESPONSE_HEADERS_MAX_KEY_LEN = 256
_RESPONSE_HEADERS_MAX_VALUE_LEN = 4096
_RESPONSE_HEADERS_OMITTED_KEY = "__system_eval_omitted_headers__"

# Stored response body cap for artifacts / UI (character count; UTF-8 safe for JSON).
_OUTPUT_FULL_MAX_CHARS = 50 * 1024
_OUTPUT_FULL_TRUNC_MARKER = "...[truncated]"

# `{{variable_name}}` in url / header values / payload string values (Increment 42).
_REQUEST_VAR_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

# Step fields that are HTTP request metadata, not assertions (Increment 43).
_STEP_REQUEST_KEYS = frozenset(
    {
        "name",
        "method",
        "url",
        "headers",
        "payload",
        "timeout_seconds",
        "body",
        "send_json_body",
        "use",
        "assertions",
    }
)


def _template_not_found_message(template_name: str) -> str:
    return "template not found: " + json.dumps({"template": template_name}, ensure_ascii=False)


def _validate_template_step_shape(raw: dict, case_name: str, tmpl_key: str) -> None:
    """``step_templates`` values must look like step bodies (method, url; no ``use``)."""
    method = str(raw.get("method", "")).strip()
    if not method:
        raise ValueError(f"Case '{case_name}' step_templates[{tmpl_key!r}] is missing a non-empty 'method'.")
    url = str(raw.get("url", "")).strip()
    if not url:
        raise ValueError(f"Case '{case_name}' step_templates[{tmpl_key!r}] is missing a non-empty 'url'.")
    if "body" in raw and raw["body"] is not None and not isinstance(raw["body"], str):
        raise ValueError(
            f"Case '{case_name}' step_templates[{tmpl_key!r}]: 'body' must be a string, JSON null, or omitted; "
            f"use 'payload' for JSON object body on POST/PUT/PATCH."
        )
    headers = raw.get("headers", {})
    if headers is not None and not isinstance(headers, dict):
        raise ValueError(
            f"Case '{case_name}' step_templates[{tmpl_key!r}] has invalid 'headers'; expected object."
        )
    payload = raw.get("payload", {})
    if payload is not None and not isinstance(payload, dict):
        raise ValueError(
            f"Case '{case_name}' step_templates[{tmpl_key!r}] has invalid 'payload'; expected object."
        )


def _parse_step_templates(case: dict, case_name: str) -> dict[str, dict]:
    raw = case.get("step_templates")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Case '{case_name}' has invalid 'step_templates'; expected object.")
    out: dict[str, dict] = {}
    for tk, tv in raw.items():
        if not isinstance(tk, str) or not str(tk).strip():
            raise ValueError(
                f"Case '{case_name}' has invalid 'step_templates' key; template names must be non-empty strings."
            )
        key = str(tk).strip()
        if not isinstance(tv, dict):
            raise ValueError(f"Case '{case_name}' step_templates[{key!r}] must be an object.")
        if "use" in tv:
            raise ValueError(
                f"Case '{case_name}' step_templates[{key!r}] must not contain 'use' "
                f"(templates cannot reference other templates in this version)."
            )
        _validate_template_step_shape(tv, case_name, key)
        out[key] = dict(tv)
    return out


def _merge_template_into_step(template: dict, override: dict) -> dict:
    """Copy ``template`` then apply ``override`` on top (override wins). Deep-merge ``headers``, ``payload``, ``extract``."""
    merged = dict(template)
    for k, v in override.items():
        if k == "use":
            continue
        if k in ("headers", "payload") and isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        elif k == "extract" and isinstance(v, dict) and isinstance(merged.get("extract"), dict):
            merged["extract"] = {**merged["extract"], **v}
        else:
            merged[k] = v
    return merged


def _resolve_step_raw_with_templates(
    step_raw: object,
    templates_map: dict[str, dict],
    case_name: str,
    step_index: int,
) -> dict:
    if not isinstance(step_raw, dict):
        raise ValueError(f"Case '{case_name}' step at index {step_index} must be an object.")
    if "use" not in step_raw or step_raw["use"] is None:
        return dict(step_raw)
    use_key = str(step_raw["use"]).strip()
    if not use_key:
        raise ValueError(f"Case '{case_name}' step at index {step_index} has empty 'use'.")
    if use_key not in templates_map:
        raise ValueError(_template_not_found_message(use_key))
    merged = _merge_template_into_step(templates_map[use_key], step_raw)
    if not str(merged.get("name", "")).strip():
        sn = str(step_raw.get("name", "")).strip()
        merged["name"] = sn if sn else use_key
    return merged


def _variable_not_found_message(var_name: str) -> str:
    return "variable not found: " + json.dumps({"variable": var_name}, ensure_ascii=False)


def _str_has_request_placeholder(s: str) -> bool:
    return bool(_REQUEST_VAR_PLACEHOLDER_RE.search(s))


def _headers_contain_request_placeholder(headers) -> bool:
    if not isinstance(headers, dict):
        return False
    for v in headers.values():
        if isinstance(v, str) and _str_has_request_placeholder(v):
            return True
    return False


def _payload_contains_request_placeholder(obj) -> bool:
    if isinstance(obj, str):
        return _str_has_request_placeholder(obj)
    if isinstance(obj, dict):
        return any(_payload_contains_request_placeholder(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_payload_contains_request_placeholder(x) for x in obj)
    return False


def _case_request_templates_have_placeholders(case: dict) -> bool:
    if _str_has_request_placeholder(str(case.get("url", ""))):
        return True
    if _headers_contain_request_placeholder(case.get("headers", {})):
        return True
    if _payload_contains_request_placeholder(case.get("payload", {})):
        return True
    return False


def _substitute_value_fragment(val: object) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False, separators=(",", ":"))
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)


def _substitute_request_string(s: str, variables: dict[str, object]) -> tuple[str, str | None]:
    if not isinstance(s, str):
        s = str(s)
    parts: list[str] = []
    pos = 0
    for m in _REQUEST_VAR_PLACEHOLDER_RE.finditer(s):
        name = m.group(1)
        if name not in variables:
            return s, _variable_not_found_message(name)
        parts.append(s[pos : m.start()])
        parts.append(_substitute_value_fragment(variables[name]))
        pos = m.end()
    parts.append(s[pos:])
    return "".join(parts), None


def _substitute_request_headers(headers: dict, variables: dict[str, object]) -> tuple[dict, str | None]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        ks = str(k)
        if isinstance(v, str):
            nv, err = _substitute_request_string(v, variables)
            if err:
                return {}, err
            out[ks] = nv
        else:
            out[ks] = str(v) if v is not None else ""
    return out, None


def _substitute_request_payload(obj, variables: dict[str, object]) -> tuple[object, str | None]:
    if isinstance(obj, str):
        return _substitute_request_string(obj, variables)
    if isinstance(obj, list):
        out = []
        for x in obj:
            nx, err = _substitute_request_payload(x, variables)
            if err:
                return None, err
            out.append(nx)
        return out, None
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            nv, err = _substitute_request_payload(v, variables)
            if err:
                return None, err
            out[k] = nv
        return out, None
    return obj, None


_DOTENV_LOADED_FOR_SINGLE_REQUEST = False


def ensure_system_eval_dotenv_loaded() -> None:
    """
    Load ``.env`` from the project root (parent of ``core/``) once.

    Used by Tool 1 single-request placeholder resolution so ``{{VAR}}`` can map to
    variables defined only in ``.env``. Does not override keys already set in the process
    environment (standard python-dotenv behavior).
    """
    global _DOTENV_LOADED_FOR_SINGLE_REQUEST
    if _DOTENV_LOADED_FOR_SINGLE_REQUEST:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        _DOTENV_LOADED_FOR_SINGLE_REQUEST = True
        return
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    load_dotenv(dotenv_path=env_path if env_path.is_file() else None)
    _DOTENV_LOADED_FOR_SINGLE_REQUEST = True


def _collect_placeholder_names_from_payload(obj) -> set[str]:
    names: set[str] = set()

    def walk(o):
        if isinstance(o, str):
            for m in _REQUEST_VAR_PLACEHOLDER_RE.finditer(o):
                names.add(m.group(1))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(obj)
    return names


def collect_single_request_placeholder_variable_names(
    *,
    url: str,
    query_params: dict[str, str],
    headers: dict[str, str],
    payload: dict,
) -> set[str]:
    names: set[str] = set()
    for m in _REQUEST_VAR_PLACEHOLDER_RE.finditer(url or ""):
        names.add(m.group(1))
    for v in query_params.values():
        for m in _REQUEST_VAR_PLACEHOLDER_RE.finditer(str(v)):
            names.add(m.group(1))
    for v in headers.values():
        if isinstance(v, str):
            for m in _REQUEST_VAR_PLACEHOLDER_RE.finditer(v):
                names.add(m.group(1))
    names.update(_collect_placeholder_names_from_payload(payload))
    return names


def resolve_placeholder_variables_from_environment(names: set[str]) -> tuple[dict[str, str], str | None]:
    """
    Build substitution values from ``os.environ``. Each name must be present with a
    non-empty value (after strip). Returns ``({}, error)`` on failure.
    """
    if not names:
        return {}, None
    missing = sorted(n for n in names if not (os.environ.get(n) or "").strip())
    if missing:
        return {}, "Unset or empty environment variable(s) for placeholder(s): " + ", ".join(missing)
    return {n: os.environ[n] for n in names}, None


def apply_env_placeholders_single_request(
    *,
    url: str,
    query_params: dict[str, str],
    headers: dict[str, str],
    payload: dict,
) -> tuple[str, dict[str, str], dict[str, str], dict, str | None]:
    """
    Resolve ``{{var}}`` placeholders from the environment (after ``ensure_system_eval_dotenv_loaded``)
    into the URL, query-string values, header string values, and string leaves of the JSON payload.

    Returns ``(url, query_params, headers, payload, error_or_None)``.
    """
    ensure_system_eval_dotenv_loaded()
    names = collect_single_request_placeholder_variable_names(
        url=url, query_params=query_params, headers=headers, payload=payload
    )
    if not names:
        return url, query_params, headers, payload, None
    variables, err = resolve_placeholder_variables_from_environment(names)
    if err:
        return url, query_params, headers, payload, err
    vobj: dict[str, object] = dict(variables)
    url_out, e1 = _substitute_request_string(url, vobj)
    if e1:
        return url, query_params, headers, payload, e1
    qp_out: dict[str, str] = {}
    for k, val in query_params.items():
        nv, e = _substitute_request_string(str(val), vobj)
        if e:
            return url, query_params, headers, payload, e
        qp_out[k] = nv
    hdr_out, e2 = _substitute_request_headers(headers, vobj)
    if e2:
        return url, query_params, headers, payload, e2
    pay_out, e3 = _substitute_request_payload(payload, vobj)
    if e3:
        return url, query_params, headers, payload, e3
    return url_out, qp_out, hdr_out, pay_out, None


def _adapter_case_dict(case: dict, *, url: str, headers: dict, payload) -> dict:
    out = {
        "name": case.get("name", ""),
        "method": case["method"],
        "url": url,
        "headers": headers,
        "payload": payload,
        "timeout_seconds": max(1, int(case.get("timeout_seconds", 20))),
    }
    if "body" in case:
        out["body"] = case["body"]
    if case.get("send_json_body") is True:
        out["send_json_body"] = True
    if case.get("lane") is not None:
        out["lane"] = case["lane"]
    return out


def _build_substituted_adapter_case(case: dict, variables: dict[str, object], *, first_hop: bool) -> tuple[dict | None, str | None]:
    """
    Build the dict passed to ``adapter.run_case`` with ``{{var}}`` substitution.

    When ``first_hop`` is True and the suite url contains placeholders, use
    ``request_url_initial`` for the first request when it is set; otherwise substitute the
    suite ``url`` with the current ``variables`` (empty on the first hop unless pre-seeded).

    For headers or payload that contain placeholders, the first hop uses ``headers_initial``
    (default ``{}``) or ``payload_initial`` (default ``{}``) respectively when those keys exist
    or are defaulted for placeholder-bearing templates.
    """
    url_tmpl = str(case.get("url", "")).strip()
    headers_tmpl = case.get("headers", {})
    if not isinstance(headers_tmpl, dict):
        headers_tmpl = {}
    payload_tmpl = case.get("payload", {})
    if not isinstance(payload_tmpl, dict):
        payload_tmpl = {}

    url_has_ph = _str_has_request_placeholder(url_tmpl)
    hdr_has_ph = _headers_contain_request_placeholder(headers_tmpl)
    pay_has_ph = _payload_contains_request_placeholder(payload_tmpl)

    if first_hop:
        initial_url = str(case.get("request_url_initial", "")).strip()
        if url_has_ph and initial_url:
            u0 = initial_url
        else:
            u0 = url_tmpl
        u1, err = _substitute_request_string(u0, variables)
        if err:
            return None, err

        if hdr_has_ph:
            h_src = case.get("headers_initial")
            if h_src is None:
                h_src = {}
            if not isinstance(h_src, dict):
                h_src = {}
        else:
            h_src = headers_tmpl
        h1, err = _substitute_request_headers(h_src, variables)
        if err:
            return None, err

        if pay_has_ph:
            p_src = case.get("payload_initial")
            if p_src is None:
                p_src = {}
            if not isinstance(p_src, dict):
                p_src = {}
        else:
            p_src = payload_tmpl
        p1, err = _substitute_request_payload(p_src, variables)
        if err:
            return None, err
        if not isinstance(p1, dict):
            p1 = {}
        return _adapter_case_dict(case, url=u1, headers=h1, payload=p1), None

    return _build_substituted_adapter_case_direct(case, variables)


def _build_substituted_adapter_case_direct(
    case: dict, variables: dict[str, object]
) -> tuple[dict | None, str | None]:
    """
    Substitute ``{{var}}`` in url / headers / payload using ``variables`` only.

    Does not use ``request_url_initial`` / ``payload_initial`` / ``headers_initial`` (used for
    legacy implicit two-hop cases without ``steps``).
    """
    url_tmpl = str(case.get("url", "")).strip()
    headers_tmpl = case.get("headers", {})
    if not isinstance(headers_tmpl, dict):
        headers_tmpl = {}
    payload_tmpl = case.get("payload", {})
    if not isinstance(payload_tmpl, dict):
        payload_tmpl = {}
    u2, err = _substitute_request_string(url_tmpl, variables)
    if err:
        return None, err
    h2, err = _substitute_request_headers(headers_tmpl, variables)
    if err:
        return None, err
    p2, err = _substitute_request_payload(payload_tmpl, variables)
    if err:
        return None, err
    if not isinstance(p2, dict):
        p2 = {}
    return _adapter_case_dict(case, url=u2, headers=h2, payload=p2), None


def _substitute_request_string_keep_missing(s: str, variables: dict[str, object]) -> str:
    if not isinstance(s, str):
        s = str(s)
    parts: list[str] = []
    pos = 0
    for m in _REQUEST_VAR_PLACEHOLDER_RE.finditer(s):
        name = m.group(1)
        parts.append(s[pos : m.start()])
        if name in variables:
            parts.append(_substitute_value_fragment(variables[name]))
        else:
            parts.append(m.group(0))
        pos = m.end()
    parts.append(s[pos:])
    return "".join(parts)


def _substitute_request_headers_keep_missing(headers: dict, variables: dict[str, object]) -> dict:
    out: dict[str, str] = {}
    for k, v in headers.items():
        ks = str(k)
        if isinstance(v, str):
            out[ks] = _substitute_request_string_keep_missing(v, variables)
        else:
            out[ks] = str(v) if v is not None else ""
    return out


def _substitute_request_payload_keep_missing(obj, variables: dict[str, object]):
    if isinstance(obj, str):
        return _substitute_request_string_keep_missing(obj, variables)
    if isinstance(obj, list):
        return [_substitute_request_payload_keep_missing(x, variables) for x in obj]
    if isinstance(obj, dict):
        return {k: _substitute_request_payload_keep_missing(v, variables) for k, v in obj.items()}
    return obj


def _build_substituted_adapter_case_direct_keep_missing(case: dict, variables: dict[str, object]) -> dict:
    """
    Steps-only variant: substitute known placeholders and keep unknown ``{{var}}`` unchanged.
    """
    url_tmpl = str(case.get("url", "")).strip()
    headers_tmpl = case.get("headers", {})
    if not isinstance(headers_tmpl, dict):
        headers_tmpl = {}
    payload_tmpl = case.get("payload", {})
    if not isinstance(payload_tmpl, dict):
        payload_tmpl = {}
    u2 = _substitute_request_string_keep_missing(url_tmpl, variables)
    h2 = _substitute_request_headers_keep_missing(headers_tmpl, variables)
    p2 = _substitute_request_payload_keep_missing(payload_tmpl, variables)
    if not isinstance(p2, dict):
        p2 = {}
    return _adapter_case_dict(case, url=u2, headers=h2, payload=p2)


def _step_failure_prefix(step_name: str) -> str:
    return "step failed: " + json.dumps({"step": step_name}, ensure_ascii=False)


def _prefix_failures_for_step(step_name: str, failures: list[str]) -> list[str]:
    p = _step_failure_prefix(step_name)
    return [f"{p} {f}" for f in failures]


def _case_request_shell_for_step(parent: dict, step: dict) -> dict:
    """Merge parent case metadata with one normalized step's HTTP fields (no ``steps`` / *_initial)."""
    merged = {
        "name": parent.get("name", ""),
        "lane": parent.get("lane"),
        "method": step["method"],
        "url": step["url"],
        "headers": step.get("headers", {}),
        "payload": step.get("payload", {}),
        "timeout_seconds": int(step.get("timeout_seconds", parent.get("timeout_seconds", 20))),
    }
    if "body" in step:
        merged["body"] = step["body"]
    elif "body" in parent:
        merged["body"] = parent["body"]
    if step.get("send_json_body") is True:
        merged["send_json_body"] = True
    elif parent.get("send_json_body") is True:
        merged["send_json_body"] = True
    return merged


def _normalize_suite_step(raw: object, case_name: str, idx: int, default_timeout: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"Case '{case_name}' step at index {idx} must be an object.")
    step_name = str(raw.get("name", "")).strip()
    if not step_name:
        raise ValueError(f"Case '{case_name}' step at index {idx} is missing a non-empty 'name'.")
    method = str(raw.get("method", "")).strip().upper()
    if not method:
        raise ValueError(f"Case '{case_name}' step {step_name!r} is missing a non-empty 'method'.")
    url = str(raw.get("url", "")).strip()
    if not url:
        raise ValueError(f"Case '{case_name}' step {step_name!r} is missing a non-empty 'url'.")
    if "body" in raw and raw["body"] is not None and not isinstance(raw["body"], str):
        raise ValueError(
            f"Case '{case_name}' step {step_name!r}: 'body' must be a string, JSON null, or omitted; "
            f"use 'payload' for JSON object body on POST/PUT/PATCH."
        )
    assertions: dict = {}
    for k, v in raw.items():
        if k in _STEP_REQUEST_KEYS:
            continue
        assertions[k] = v
    structured_assertions = raw.get("assertions")
    if structured_assertions is not None:
        if not isinstance(structured_assertions, list):
            raise ValueError(
                f"Case '{case_name}' step {step_name!r} has invalid 'assertions'; expected array of objects."
            )
        json_path_equals: dict[str, object] = {}
        for ai, a in enumerate(structured_assertions):
            if not isinstance(a, dict):
                raise ValueError(
                    f"Case '{case_name}' step {step_name!r} assertion at index {ai} must be an object."
                )
            atype = str(a.get("type", "")).strip()
            if atype != "json_path_equals":
                raise ValueError(
                    f"Case '{case_name}' step {step_name!r} has unsupported assertion type {atype!r}; "
                    "supported: json_path_equals."
                )
            path_raw = str(a.get("path", "")).strip()
            if not path_raw:
                raise ValueError(
                    f"Case '{case_name}' step {step_name!r} assertion at index {ai} is missing non-empty 'path'."
                )
            path_norm = _normalize_json_path_input(path_raw)
            if not path_norm:
                raise ValueError(
                    f"Case '{case_name}' step {step_name!r} assertion at index {ai} has invalid 'path' {path_raw!r}."
                )
            if "expected" not in a:
                raise ValueError(
                    f"Case '{case_name}' step {step_name!r} assertion at index {ai} is missing 'expected'."
                )
            json_path_equals[path_norm] = a.get("expected")
        if json_path_equals:
            existing = assertions.get("body_json_path_equals")
            if isinstance(existing, dict):
                merged = dict(existing)
                merged.update(json_path_equals)
                assertions["body_json_path_equals"] = merged
            else:
                assertions["body_json_path_equals"] = json_path_equals
    _validate_minimal_assertion_keys(assertions, f"{case_name} step '{step_name}'")
    headers = raw.get("headers", {})
    if headers is not None and not isinstance(headers, dict):
        raise ValueError(f"Case '{case_name}' step {step_name!r} has invalid 'headers'; expected object.")
    payload = raw.get("payload", {})
    if payload is not None and not isinstance(payload, dict):
        raise ValueError(f"Case '{case_name}' step {step_name!r} has invalid 'payload'; expected object.")
    out = {
        "step_name": step_name,
        "method": method,
        "url": url,
        "headers": headers if isinstance(headers, dict) else {},
        "payload": payload if isinstance(payload, dict) else {},
        "assertions": assertions,
    }
    if "timeout_seconds" in raw and raw["timeout_seconds"] is not None:
        out["timeout_seconds"] = int(raw["timeout_seconds"])
    else:
        out["timeout_seconds"] = default_timeout
    if "body" in raw:
        out["body"] = raw["body"]
    if raw.get("send_json_body") is True:
        out["send_json_body"] = True
    return out


def _cap_output_full(text: str | None) -> str:
    """Return full response text capped for JSON artifacts; append marker when truncated."""
    if text is None:
        return ""
    s = str(text)
    if len(s) <= _OUTPUT_FULL_MAX_CHARS:
        return s
    keep = _OUTPUT_FULL_MAX_CHARS - len(_OUTPUT_FULL_TRUNC_MARKER)
    if keep < 1:
        return _OUTPUT_FULL_TRUNC_MARKER[: _OUTPUT_FULL_MAX_CHARS]
    return s[:keep] + _OUTPUT_FULL_TRUNC_MARKER


def _normalize_summary_whitespace(text: str) -> str:
    return " ".join(str(text).split()).strip()


def _is_meaningful_summary_text(text: str) -> bool:
    s = _normalize_summary_whitespace(text)
    if len(s) < 20:
        return False
    if s.startswith("{") or s.startswith("["):
        return False
    sl = s.lower()
    if sl.startswith("http://") or sl.startswith("https://") or sl.startswith("www."):
        return False
    return any(ch.isalpha() for ch in s)


def _extract_first_meaningful_text(obj) -> str | None:
    if isinstance(obj, str):
        s = _normalize_summary_whitespace(obj)
        return s if _is_meaningful_summary_text(s) else None
    if isinstance(obj, list):
        for x in obj:
            got = _extract_first_meaningful_text(x)
            if got:
                return got
        return None
    if isinstance(obj, dict):
        for k in ("answer", "response", "summary", "text", "content", "snippet", "description", "title"):
            if k in obj:
                got = _extract_first_meaningful_text(obj[k])
                if got:
                    return got
        for v in obj.values():
            got = _extract_first_meaningful_text(v)
            if got:
                return got
        return None
    return None


def _extract_response_summary(output_text: str | None) -> str:
    """
    Build a short human-readable summary from response text without changing stored raw outputs.
    """
    raw = str(output_text or "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        # Prefer Brave-style grounding snippets first when available.
        grounding = parsed.get("grounding")
        if isinstance(grounding, dict):
            generic = grounding.get("generic")
            got = _extract_first_meaningful_text(generic)
            if got:
                return got[:280]
        got = _extract_first_meaningful_text(parsed)
        if got:
            return got[:280]
    elif isinstance(parsed, list):
        got = _extract_first_meaningful_text(parsed)
        if got:
            return got[:280]
    for line in raw.splitlines():
        s = _normalize_summary_whitespace(line)
        if _is_meaningful_summary_text(s):
            return s[:280]
    s = _normalize_summary_whitespace(raw)
    return s[:280]


def _is_sensitive_request_header_name(name: str) -> bool:
    k = str(name or "").strip().lower().replace("-", "_")
    tokens = (
        "authorization",
        "token",
        "password",
        "secret",
        "api_key",
        "apikey",
        "subscription_key",
    )
    return any(t in k for t in tokens)


def _mask_request_headers_for_output(headers: dict | None) -> dict[str, str]:
    if not isinstance(headers, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in headers.items():
        ks = str(k)
        out[ks] = "[REDACTED]" if _is_sensitive_request_header_name(ks) else str(v)
    return out


def _is_sensitive_body_key(name: str) -> bool:
    k = str(name or "").strip().lower().replace("-", "_")
    tokens = (
        "authorization",
        "token",
        "password",
        "secret",
        "api_key",
        "apikey",
        "subscription_key",
    )
    return any(t in k for t in tokens)


def _mask_request_body_for_output(body):
    if body is None:
        return None
    if isinstance(body, dict):
        out = {}
        for k, v in body.items():
            if _is_sensitive_body_key(str(k)):
                out[k] = "[REDACTED]"
            else:
                out[k] = _mask_request_body_for_output(v)
        return out
    if isinstance(body, list):
        return [_mask_request_body_for_output(x) for x in body]
    return body


def _request_body_for_output(request_case: dict):
    method = str(request_case.get("method", "POST")).upper()
    payload = request_case.get("payload", {})
    body = _raw_body_for_http_request(request_case)
    if body is None:
        body = _json_body_for_http_request(method, request_case, payload)
    return _mask_request_body_for_output(body)


def _normalize_response_headers(headers_obj) -> dict:
    """
    Convert a requests response ``headers`` mapping to a plain ``str -> str`` dict
    with bounded size for stable JSON artifacts.
    """
    if headers_obj is None:
        return {}
    try:
        raw_items = headers_obj.items()
    except (TypeError, AttributeError):
        return {}
    try:
        items = [(str(k), str(v)) for k, v in raw_items]
    except TypeError:
        return {}
    omitted = max(0, len(items) - _RESPONSE_HEADERS_MAX_ITEMS)
    slice_items = items[: _RESPONSE_HEADERS_MAX_ITEMS]
    out: dict[str, str] = {}
    for k, v in slice_items:
        if len(k) > _RESPONSE_HEADERS_MAX_KEY_LEN:
            k = k[: _RESPONSE_HEADERS_MAX_KEY_LEN - 15] + "...[truncated]"
        if len(v) > _RESPONSE_HEADERS_MAX_VALUE_LEN:
            v = v[: _RESPONSE_HEADERS_MAX_VALUE_LEN - 15] + "...[truncated]"
        out[k] = v
    if omitted:
        out[_RESPONSE_HEADERS_OMITTED_KEY] = str(omitted)
    return out


@dataclass
class AdapterResult:
    ok: bool
    status_code: int | None
    output_text: str
    latency_ms: int
    error: str | None = None
    response_headers: dict = field(default_factory=dict)


def _json_body_for_http_request(method: str, case: dict, payload):
    """
    Return the object to pass as requests' ``json=`` argument, or None to omit ``json=``.

    Rules:
    - Explicit ``body: null`` in the suite case → never send JSON body.
    - ``send_json_body: true`` → send ``json=payload`` (escape hatch for GET/HEAD/DELETE).
    - POST / PUT / PATCH → send ``json=payload`` (default payload is {}), unless ``body: null``.
    - GET / HEAD / DELETE (and other verbs) → omit ``json=`` unless ``send_json_body: true``.
    """
    if "body" in case and case["body"] is None:
        return None
    if isinstance(case.get("body"), str):
        return None
    if case.get("send_json_body") is True:
        return payload
    method_u = str(method).upper()
    if method_u in _METHODS_DEFAULT_JSON_BODY:
        return payload
    # GET / HEAD / DELETE / OPTIONS / … — omit ``json=`` unless handled above.
    return None


def _raw_body_for_http_request(case: dict):
    """
    Return the string to pass as requests' ``data=`` argument, or None.

    Raw ``body`` takes precedence over JSON ``payload`` when present.
    """
    body = case.get("body")
    if isinstance(body, str):
        return body
    return None


class HttpTargetAdapter:
    def __init__(self, default_timeout_seconds=20):
        self.default_timeout_seconds = max(1, int(default_timeout_seconds))

    def run_case(self, case):
        method = str(case.get("method", "POST")).upper()
        url = str(case.get("url", "")).strip()
        headers = case.get("headers") if isinstance(case.get("headers"), dict) else {}
        timeout_seconds = max(1, int(case.get("timeout_seconds", self.default_timeout_seconds)))
        payload = case.get("payload", {})
        started = time.perf_counter()
        try:
            req_kwargs = {
                "method": method,
                "url": url,
                "headers": headers,
                "timeout": timeout_seconds,
            }
            raw_body = _raw_body_for_http_request(case)
            if raw_body is not None:
                req_kwargs["data"] = raw_body
            else:
                json_body = _json_body_for_http_request(method, case, payload)
                if json_body is not None:
                    req_kwargs["json"] = json_body
            response = requests.request(**req_kwargs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            text = response.text or ""
            return AdapterResult(
                ok=True,
                status_code=response.status_code,
                output_text=text,
                latency_ms=latency_ms,
                error=None,
                response_headers=_normalize_response_headers(response.headers),
            )
        except requests.RequestException as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return AdapterResult(
                ok=False,
                status_code=None,
                output_text="",
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}",
                response_headers={},
            )


def _coerce_bounded_attempt_field(raw, case_name, field_name, max_n):
    if isinstance(raw, bool):
        raise ValueError(f"Case '{case_name}' has invalid '{field_name}' (boolean not allowed).")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"Case '{case_name}' has invalid '{field_name}'; expected a positive integer."
        ) from None
    if n < 1:
        raise ValueError(f"Case '{case_name}' has invalid '{field_name}' {n}; must be >= 1.")
    if n > max_n:
        raise ValueError(
            f"Case '{case_name}' has '{field_name}' {n}; maximum allowed is {max_n}."
        )
    return n


def _coerce_repeat_count(raw, case_name):
    return _coerce_bounded_attempt_field(raw, case_name, "repeat_count", CONSISTENCY_REPEAT_MAX)


def _coerce_stability_attempts(raw, case_name):
    return _coerce_bounded_attempt_field(raw, case_name, "stability_attempts", STABILITY_ATTEMPTS_MAX)


def _coerce_retries(raw, case_name):
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(
            f"Case '{case_name}' has invalid 'retries'; expected a non-negative integer (JSON number), not boolean."
        )
    if raw < 0:
        raise ValueError(f"Case '{case_name}' has invalid 'retries' {raw}; must be >= 0.")
    return int(raw)


def _coerce_retry_delay_ms(raw, case_name):
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(
            f"Case '{case_name}' has invalid 'retry_delay_ms'; expected a non-negative integer (JSON number), not boolean."
        )
    if raw < 0:
        raise ValueError(f"Case '{case_name}' has invalid 'retry_delay_ms' {raw}; must be >= 0.")
    return int(raw)


def _coerce_expected_headers(raw, case_name):
    if not isinstance(raw, dict):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_headers'; expected object mapping header names to string values."
        )
    out = {}
    for hk, hv in raw.items():
        if not isinstance(hk, str):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_headers' key {hk!r}; header names must be strings."
            )
        if not isinstance(hv, str):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_headers' value for header {hk!r}; expected string."
            )
        if not hk.strip():
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_headers' key; header names must be non-empty strings after strip()."
            )
        out[hk.strip()] = hv
    return out


def _coerce_expected_headers_contains(raw, case_name):
    if not isinstance(raw, dict):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_headers_contains'; expected object mapping header names to substring values."
        )
    out = {}
    for hk, hv in raw.items():
        if not isinstance(hk, str):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_headers_contains' key {hk!r}; header names must be strings."
            )
        if not isinstance(hv, str):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_headers_contains' value for header {hk!r}; expected string."
            )
        if not hk.strip():
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_headers_contains' key; header names must be non-empty strings after strip()."
            )
        out[hk.strip()] = hv
    return out


def _coerce_expected_header_exists(raw, case_name):
    if not isinstance(raw, list):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_header_exists'; expected a JSON array of header-name strings."
        )
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, str):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_header_exists' item at index {i}; expected string header name."
            )
        header_name = item.strip()
        if not header_name:
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_header_exists' header at index {i}; expected non-empty string after strip()."
            )
        out.append(header_name)
    return out


def _coerce_expected_json(raw, case_name):
    if not isinstance(raw, dict):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_json'; expected object mapping dot-path keys to JSON values."
        )
    out = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_json' key {k!r}; keys must be strings."
            )
        if not k.strip():
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_json' path; path keys must be non-empty strings after strip()."
            )
        out[k.strip()] = v
    return out


def _coerce_expected_json_exists(raw, case_name):
    if not isinstance(raw, list):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_json_exists'; expected a JSON array of dot-path strings."
        )
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, str):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_json_exists' item at index {i}; expected string path."
            )
        path = item.strip()
        if not path:
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_json_exists' path at index {i}; expected non-empty string after strip()."
            )
        out.append(path)
    return out


def _coerce_expected_json_values(raw, case_name):
    if not isinstance(raw, dict):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_json_values'; expected object mapping top-level JSON keys to expected values."
        )
    out = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_json_values' key {k!r}; keys must be strings."
            )
        key = k.strip()
        if not key:
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_json_values' key; keys must be non-empty strings after strip()."
            )
        out[key] = v
    return out


def _coerce_expected_json_absent(raw, case_name):
    if not isinstance(raw, list):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_json_absent'; expected a JSON array of top-level key strings."
        )
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, str):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_json_absent' item at index {i}; expected string key."
            )
        key = item.strip()
        if not key:
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_json_absent' key at index {i}; expected non-empty string after strip()."
            )
        out.append(key)
    return out


def _coerce_max_duration_ms(raw, case_name):
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(
            f"Case '{case_name}' has invalid 'max_duration_ms'; expected a non-negative integer (JSON number), not boolean."
        )
    if raw < 0:
        raise ValueError(f"Case '{case_name}' has invalid 'max_duration_ms' {raw}; must be >= 0.")
    return int(raw)


def _coerce_expected_latency_ms_max(raw, case_name):
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_latency_ms_max'; expected a non-negative integer (JSON number), not boolean."
        )
    if raw < 0:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_latency_ms_max' {raw}; must be >= 0."
        )
    return int(raw)


def _coerce_expected_body_not_empty(raw, case_name):
    if not isinstance(raw, bool):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_body_not_empty'; expected boolean."
        )
    return bool(raw)


def _coerce_expected_body_size_bytes_max(raw, case_name):
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_body_size_bytes_max'; expected a non-negative integer (JSON number), not boolean."
        )
    if raw < 0:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_body_size_bytes_max' {raw}; must be >= 0."
        )
    return int(raw)


def _coerce_expected_response_time_ms_range(raw, case_name):
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_time_ms_range'; expected [min, max] with exactly two integer values."
        )
    min_v, max_v = raw[0], raw[1]
    if isinstance(min_v, bool) or not isinstance(min_v, int):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_time_ms_range' min; expected integer (JSON number), not boolean."
        )
    if isinstance(max_v, bool) or not isinstance(max_v, int):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_time_ms_range' max; expected integer (JSON number), not boolean."
        )
    if int(min_v) > int(max_v):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_time_ms_range'; min must be <= max."
        )
    return [int(min_v), int(max_v)]


def _coerce_prompt_input(raw, case_name):
    v = str(raw or "").strip()
    if not v:
        raise ValueError(f"Case '{case_name}' has invalid 'prompt_input'; expected a non-empty string.")
    return v


def _coerce_expected_response_contains(raw, case_name):
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_contains'; expected a non-empty array of strings."
        )
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, str):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_response_contains' item at index {i}; expected string."
            )
        needle = item.strip()
        if not needle:
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_response_contains' item at index {i}; expected non-empty string."
            )
        out.append(needle)
    return out


def _coerce_expected_response_not_contains(raw, case_name):
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_not_contains'; expected a non-empty array of strings."
        )
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, str):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_response_not_contains' item at index {i}; expected string."
            )
        needle = item.strip()
        if not needle:
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_response_not_contains' item at index {i}; expected non-empty string."
            )
        out.append(needle)
    return out


def _coerce_expected_response_regex(raw, case_name):
    if not isinstance(raw, str):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_regex'; expected non-empty string pattern."
        )
    pat = raw.strip()
    if not pat:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_regex'; expected non-empty string pattern."
        )
    try:
        re.compile(pat)
    except re.error as exc:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_regex' pattern {pat!r}: {exc}"
        ) from None
    return pat


def _coerce_expected_response_starts_with(raw, case_name):
    if not isinstance(raw, str):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_starts_with'; expected non-empty string."
        )
    prefix = raw.strip()
    if not prefix:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_starts_with'; expected non-empty string."
        )
    return prefix


def _coerce_expected_response_ends_with(raw, case_name):
    if not isinstance(raw, str):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_ends_with'; expected non-empty string."
        )
    suffix = raw.strip()
    if not suffix:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_ends_with'; expected non-empty string."
        )
    return suffix


def _coerce_expected_response_equals(raw, case_name):
    if not isinstance(raw, str):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_equals'; expected non-empty string."
        )
    exact = raw.strip()
    if not exact:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_equals'; expected non-empty string."
        )
    return exact


def _coerce_expected_response_length_min(raw, case_name):
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_length_min'; expected non-negative integer."
        )
    if raw < 0:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_length_min'; expected non-negative integer."
        )
    return int(raw)


def _coerce_expected_response_length_max(raw, case_name):
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_length_max'; expected non-negative integer."
        )
    if raw < 0:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_response_length_max'; expected non-negative integer."
        )
    return int(raw)


def load_suite_file(suite_path):
    path = Path(suite_path)
    with open(path, "r", encoding="utf-8") as f:
        suite = json.load(f)
    return validate_suite(suite)


def validate_suite(suite):
    if not isinstance(suite, dict):
        raise ValueError("Suite must be a JSON object.")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Suite must include a non-empty 'cases' array.")
    normalized_cases = []
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"Case at index {i} must be an object.")
        name = str(case.get("name", "")).strip()
        if not name:
            raise ValueError(f"Case at index {i} is missing a non-empty 'name'.")
        has_steps = "steps" in case and case["steps"] is not None
        if has_steps:
            if not isinstance(case["steps"], list) or len(case["steps"]) == 0:
                raise ValueError(f"Case '{name}' must have a non-empty 'steps' array.")
        url = str(case.get("url", "")).strip()
        assertions = case.get("assertions", {})
        if not isinstance(assertions, dict):
            raise ValueError(f"Case '{name}' has invalid 'assertions'; expected object.")
        _validate_minimal_assertion_keys(assertions, name)
        lane = "smoke"
        if "lane" in case and case["lane"] is not None:
            lane_raw = str(case["lane"]).strip()
            if lane_raw:
                if lane_raw not in SYSTEM_EVAL_LANES:
                    allowed = ", ".join(sorted(SYSTEM_EVAL_LANES))
                    raise ValueError(
                        f"Case '{name}' has invalid 'lane' {lane_raw!r}; "
                        f"allowed: {allowed}, or omit the field."
                    )
                lane = lane_raw

        is_prompt_response_lane = lane == "prompt_response"
        prompt_response_only_fields = (
            "prompt_input",
            "expected_response_contains",
            "expected_response_not_contains",
            "expected_response_regex",
            "expected_response_starts_with",
            "expected_response_ends_with",
            "expected_response_equals",
            "expected_response_length_min",
            "expected_response_length_max",
        )
        if not is_prompt_response_lane:
            invalid_prompt_fields = [
                field for field in prompt_response_only_fields if case.get(field) is not None
            ]
            if invalid_prompt_fields:
                field_list = ", ".join(invalid_prompt_fields)
                raise ValueError(
                    f"Case '{name}' has prompt-response-only field(s) outside lane "
                    f"'prompt_response': {field_list}"
                )
        if not has_steps and not is_prompt_response_lane and not url:
            raise ValueError(f"Case '{name}' is missing a non-empty 'url'.")
        if has_steps and is_prompt_response_lane:
            raise ValueError(
                f"Case '{name}': 'steps' is not supported for lane 'prompt_response'."
            )
        prompt_input = None
        expected_response_contains = None
        expected_response_not_contains = None
        expected_response_regex = None
        expected_response_starts_with = None
        expected_response_ends_with = None
        expected_response_equals = None
        expected_response_length_min = None
        expected_response_length_max = None
        if is_prompt_response_lane:
            prompt_input = _coerce_prompt_input(case.get("prompt_input"), name)
            expected_response_contains = _coerce_expected_response_contains(
                case.get("expected_response_contains"), name
            )
            if case.get("expected_response_not_contains") is not None:
                expected_response_not_contains = _coerce_expected_response_not_contains(
                    case.get("expected_response_not_contains"), name
                )
            if case.get("expected_response_regex") is not None:
                expected_response_regex = _coerce_expected_response_regex(
                    case.get("expected_response_regex"), name
                )
            if case.get("expected_response_starts_with") is not None:
                expected_response_starts_with = _coerce_expected_response_starts_with(
                    case.get("expected_response_starts_with"), name
                )
            if case.get("expected_response_ends_with") is not None:
                expected_response_ends_with = _coerce_expected_response_ends_with(
                    case.get("expected_response_ends_with"), name
                )
            if case.get("expected_response_equals") is not None:
                expected_response_equals = _coerce_expected_response_equals(
                    case.get("expected_response_equals"), name
                )
            if case.get("expected_response_length_min") is not None:
                expected_response_length_min = _coerce_expected_response_length_min(
                    case.get("expected_response_length_min"), name
                )
            if case.get("expected_response_length_max") is not None:
                expected_response_length_max = _coerce_expected_response_length_max(
                    case.get("expected_response_length_max"), name
                )
            if (
                expected_response_length_min is not None
                and expected_response_length_max is not None
                and int(expected_response_length_min) > int(expected_response_length_max)
            ):
                raise ValueError(
                    f"Case '{name}' has invalid response length bounds; "
                    f"'expected_response_length_min' must be <= 'expected_response_length_max'."
                )

        repeat_count = None
        if "repeat_count" in case and case["repeat_count"] is not None:
            if lane != "consistency":
                raise ValueError(
                    f"Case '{name}' has 'repeat_count' but lane is not 'consistency' "
                    f"(lane is {lane!r})."
                )
            repeat_count = _coerce_repeat_count(case["repeat_count"], name)
        elif lane == "consistency":
            repeat_count = CONSISTENCY_REPEAT_DEFAULT

        if lane == "stability" and "repeat_count" in case and case["repeat_count"] is not None:
            raise ValueError(
                f"Case '{name}' has 'repeat_count' but lane is 'stability'; "
                f"use 'stability_attempts' instead."
            )
        if lane == "consistency" and "stability_attempts" in case and case["stability_attempts"] is not None:
            raise ValueError(
                f"Case '{name}' has 'stability_attempts' but lane is 'consistency'; "
                f"use 'repeat_count' instead."
            )
        if "stability_attempts" in case and case["stability_attempts"] is not None:
            if lane != "stability":
                raise ValueError(
                    f"Case '{name}' has 'stability_attempts' but lane is not 'stability' "
                    f"(lane is {lane!r})."
                )

        stability_attempts = None
        if "stability_attempts" in case and case["stability_attempts"] is not None:
            stability_attempts = _coerce_stability_attempts(case["stability_attempts"], name)
        elif lane == "stability":
            stability_attempts = STABILITY_ATTEMPTS_DEFAULT

        max_duration_ms = None
        if "max_duration_ms" in case and case["max_duration_ms"] is not None:
            max_duration_ms = _coerce_max_duration_ms(case["max_duration_ms"], name)
        expected_latency_ms_max = None
        if "expected_latency_ms_max" in case and case["expected_latency_ms_max"] is not None:
            expected_latency_ms_max = _coerce_expected_latency_ms_max(
                case["expected_latency_ms_max"], name
            )
        expected_body_not_empty = None
        if "expected_body_not_empty" in case and case["expected_body_not_empty"] is not None:
            expected_body_not_empty = _coerce_expected_body_not_empty(
                case["expected_body_not_empty"], name
            )
        expected_body_size_bytes_max = None
        if "expected_body_size_bytes_max" in case and case["expected_body_size_bytes_max"] is not None:
            expected_body_size_bytes_max = _coerce_expected_body_size_bytes_max(
                case["expected_body_size_bytes_max"], name
            )
        expected_response_time_ms_range = None
        if (
            "expected_response_time_ms_range" in case
            and case["expected_response_time_ms_range"] is not None
        ):
            expected_response_time_ms_range = _coerce_expected_response_time_ms_range(
                case["expected_response_time_ms_range"], name
            )
        retries = None
        if "retries" in case and case["retries"] is not None:
            retries = _coerce_retries(case["retries"], name)
        retry_delay_ms = None
        if "retry_delay_ms" in case and case["retry_delay_ms"] is not None:
            retry_delay_ms = _coerce_retry_delay_ms(case["retry_delay_ms"], name)
        expected_status_case = None
        if "expected_status" in case and case["expected_status"] is not None:
            expected_status_case = system_eval_status_coercion.coerce_expected_status(
                case["expected_status"], name
            )
        expected_status_in_case = None
        if "expected_status_in" in case and case["expected_status_in"] is not None:
            expected_status_in_case = system_eval_status_coercion.coerce_expected_status_in(
                case["expected_status_in"], name
            )
        expected_status_not_case = None
        if "expected_status_not" in case and case["expected_status_not"] is not None:
            expected_status_not_case = system_eval_status_coercion.coerce_expected_status_not(
                case["expected_status_not"], name
            )
        if expected_status_case is not None and expected_status_in_case is not None:
            raise ValueError(
                f"Case '{name}' cannot set both 'expected_status' and 'expected_status_in'; choose one."
            )

        if has_steps and lane in ("stability", "consistency"):
            raise ValueError(
                f"Case '{name}': 'steps' is not supported for lane {lane!r} "
                f"(use the default correctness lane or omit 'lane')."
            )

        if "body" in case:
            if case["body"] is not None and not isinstance(case["body"], str):
                raise ValueError(
                    f"Case '{name}': 'body' must be a string, JSON null, or omitted; "
                    f"use 'payload' for JSON object body on POST/PUT/PATCH."
                )

        if case.get("step_templates") is not None and not has_steps:
            raise ValueError(f"Case '{name}': 'step_templates' is only valid when 'steps' is set.")

        default_timeout = int(case.get("timeout_seconds", 20))
        if has_steps:
            templates_map = _parse_step_templates(case, name)
            norm_steps = [
                _normalize_suite_step(
                    _resolve_step_raw_with_templates(s, templates_map, name, si),
                    name,
                    si,
                    default_timeout,
                )
                for si, s in enumerate(case["steps"])
            ]
            first = norm_steps[0]
            norm = {
                "name": name,
                "lane": lane,
                "method": first["method"],
                "url": url if url else first["url"],
                "headers": first["headers"],
                "payload": first["payload"],
                "timeout_seconds": default_timeout,
                "assertions": assertions,
                "steps": norm_steps,
            }
            if "body" in case:
                norm["body"] = case["body"]
            if case.get("send_json_body") is True:
                norm["send_json_body"] = True
        else:
            norm = {
                "name": name,
                "lane": lane,
                "method": str(case.get("method", "POST")).upper(),
                "url": url if url else "prompt://local",
                "headers": case.get("headers", {}),
                "payload": case.get("payload", {}),
                "timeout_seconds": default_timeout,
                "assertions": assertions,
            }
            if "body" in case:
                norm["body"] = case["body"]
            if case.get("send_json_body") is True:
                norm["send_json_body"] = True
        if lane == "consistency":
            norm["repeat_count"] = repeat_count
        if lane == "stability":
            norm["stability_attempts"] = stability_attempts
        if max_duration_ms is not None:
            norm["max_duration_ms"] = max_duration_ms
        if expected_latency_ms_max is not None:
            norm["expected_latency_ms_max"] = expected_latency_ms_max
        if expected_body_not_empty is not None:
            norm["expected_body_not_empty"] = expected_body_not_empty
        if expected_body_size_bytes_max is not None:
            norm["expected_body_size_bytes_max"] = expected_body_size_bytes_max
        if expected_response_time_ms_range is not None:
            norm["expected_response_time_ms_range"] = expected_response_time_ms_range
        if retries is not None:
            norm["retries"] = retries
        if retry_delay_ms is not None:
            norm["retry_delay_ms"] = retry_delay_ms
        if expected_status_case is not None:
            norm["expected_status"] = expected_status_case
        if expected_status_in_case is not None:
            norm["expected_status_in"] = expected_status_in_case
        if expected_status_not_case is not None:
            norm["expected_status_not"] = expected_status_not_case
        if "expected_headers" in case and case["expected_headers"] is not None:
            norm["expected_headers"] = _coerce_expected_headers(case["expected_headers"], name)
        if "expected_headers_contains" in case and case["expected_headers_contains"] is not None:
            norm["expected_headers_contains"] = _coerce_expected_headers_contains(
                case["expected_headers_contains"], name
            )
        if "expected_header_exists" in case and case["expected_header_exists"] is not None:
            norm["expected_header_exists"] = _coerce_expected_header_exists(
                case["expected_header_exists"], name
            )
        if "expected_json" in case and case["expected_json"] is not None:
            norm["expected_json"] = _coerce_expected_json(case["expected_json"], name)
        if "expected_json_exists" in case and case["expected_json_exists"] is not None:
            norm["expected_json_exists"] = _coerce_expected_json_exists(case["expected_json_exists"], name)
        if "expected_json_values" in case and case["expected_json_values"] is not None:
            norm["expected_json_values"] = _coerce_expected_json_values(case["expected_json_values"], name)
        if "expected_json_absent" in case and case["expected_json_absent"] is not None:
            norm["expected_json_absent"] = _coerce_expected_json_absent(case["expected_json_absent"], name)
        if prompt_input is not None:
            norm["prompt_input"] = prompt_input
        if expected_response_contains is not None:
            norm["expected_response_contains"] = expected_response_contains
        if expected_response_not_contains is not None:
            norm["expected_response_not_contains"] = expected_response_not_contains
        if expected_response_regex is not None:
            norm["expected_response_regex"] = expected_response_regex
        if expected_response_starts_with is not None:
            norm["expected_response_starts_with"] = expected_response_starts_with
        if expected_response_ends_with is not None:
            norm["expected_response_ends_with"] = expected_response_ends_with
        if expected_response_equals is not None:
            norm["expected_response_equals"] = expected_response_equals
        if expected_response_length_min is not None:
            norm["expected_response_length_min"] = expected_response_length_min
        if expected_response_length_max is not None:
            norm["expected_response_length_max"] = expected_response_length_max

        if not has_steps:
            if "request_url_initial" in case and case["request_url_initial"] is not None:
                rui = str(case["request_url_initial"]).strip()
                if rui:
                    norm["request_url_initial"] = rui
            if "payload_initial" in case and case["payload_initial"] is not None:
                if not isinstance(case["payload_initial"], dict):
                    raise ValueError(f"Case '{name}' has invalid 'payload_initial'; expected object.")
                norm["payload_initial"] = case["payload_initial"]
            if "headers_initial" in case and case["headers_initial"] is not None:
                if not isinstance(case["headers_initial"], dict):
                    raise ValueError(f"Case '{name}' has invalid 'headers_initial'; expected object.")
                norm["headers_initial"] = case["headers_initial"]

        if lane in ("stability", "consistency") and not has_steps and _case_request_templates_have_placeholders(norm):
            raise ValueError(
                f"Case '{name}' uses {{...}} placeholders in url, headers, or payload; "
                f"not supported for lane {lane!r}."
            )

        normalized_cases.append(norm)
    return {
        "suite_name": str(suite.get("suite_name", "unnamed-suite")).strip() or "unnamed-suite",
        "target_name": str(suite.get("target_name", "unspecified-target")).strip() or "unspecified-target",
        "cases": normalized_cases,
    }


def _serialize_headers_for_assertion(headers: dict) -> str:
    """Stable one-line-per-header text for substring assertions (sorted by header name)."""
    if not isinstance(headers, dict) or not headers:
        return ""
    lines = []
    for k, v in sorted(headers.items(), key=lambda kv: str(kv[0]).lower()):
        lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _response_header_value(headers: dict, name: str) -> str | None:
    """Return the first response header value whose name matches case-insensitively, or None."""
    if not isinstance(headers, dict):
        return None
    want = name.lower()
    for k, v in headers.items():
        if str(k).lower() == want:
            return str(v)
    return None


def _normalize_text(value: str) -> str:
    if not isinstance(value, str):
        value = str(value)
    return " ".join(value.strip().split())


_JSON_PATH_INDEXED_SEGMENT = re.compile(r"^([^[]+)\[(\d+)\]$")


def _split_json_path_segment(part: str) -> tuple[str, int | None] | None:
    """Parse one dot-separated segment: plain key or ``key[index]``. None if malformed."""
    if "[" not in part:
        if "]" in part:
            return None
        return (part, None)
    m = _JSON_PATH_INDEXED_SEGMENT.fullmatch(part)
    if not m:
        return None
    return (m.group(1), int(m.group(2)))


class _JsonPathStepFailed:
    __slots__ = ()


_JSON_PATH_STEP_FAILED = _JsonPathStepFailed()


def _walk_json_path_segment(current: object, part: str) -> object | _JsonPathStepFailed:
    """One step of JSON path traversal. On failure returns ``_JSON_PATH_STEP_FAILED``; else next node (may be ``None`` for JSON null)."""
    parsed = _split_json_path_segment(part)
    if parsed is None:
        return _JSON_PATH_STEP_FAILED
    key, idx = parsed
    if not isinstance(current, dict):
        return _JSON_PATH_STEP_FAILED
    if key not in current:
        return _JSON_PATH_STEP_FAILED
    node = current[key]
    if idx is None:
        return node
    if not isinstance(node, list):
        return _JSON_PATH_STEP_FAILED
    if idx < 0 or idx >= len(node):
        return _JSON_PATH_STEP_FAILED
    return node[idx]


def _resolve_json_path(obj: object, path: str) -> object | None:
    """Walk dot-separated path with optional ``name[i]`` list segments; None if missing or invalid."""
    norm = _normalize_json_path_input(path)
    if norm == "":
        return obj if isinstance(obj, dict) else None
    current = obj
    for part in norm.split("."):
        nxt = _walk_json_path_segment(current, part)
        if nxt is _JSON_PATH_STEP_FAILED:
            return None
        current = nxt
    return current


def _normalize_json_path_input(path: str) -> str:
    s = str(path or "").strip()
    if s == "$":
        return ""
    if s.startswith("$."):
        return s[2:]
    return s


def _json_path_exists(root: object, path: str) -> bool:
    """True if dot path resolves (dict keys and ``name[i]`` list indices); leaf may be JSON null."""
    norm = _normalize_json_path_input(path)
    if norm == "":
        return isinstance(root, dict)
    current = root
    for part in norm.split("."):
        nxt = _walk_json_path_segment(current, part)
        if nxt is _JSON_PATH_STEP_FAILED:
            return False
        current = nxt
    return True


def _body_json_path_missing_failure(path: str) -> str:
    """Structured missing-path detail for body_json_path_equals / body_json_has_key."""
    return "body_json_path missing path: " + json.dumps({"path": path}, ensure_ascii=False)


def _validate_minimal_assertion_keys(assertions, case_name):
    """Type-check Tool 1 minimal assertion keys (Increment 10); legacy keys unchanged."""
    if "expected_status" in assertions:
        v = assertions["expected_status"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_status'; expected integer (JSON number), not boolean."
            )
    if "expected_response_time_ms" in assertions:
        v = assertions["expected_response_time_ms"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_response_time_ms'; expected a non-negative integer (JSON number), not boolean."
            )
        if v < 0:
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_response_time_ms' {v}; must be >= 0."
            )
    for key in ("body_contains", "body_equals", "body_regex", "header_contains"):
        if key not in assertions:
            continue
        v = assertions[key]
        if not isinstance(v, str):
            raise ValueError(
                f"Case '{case_name}' has invalid {key!r}; expected string."
            )
    if "header_equals" in assertions:
        he = assertions["header_equals"]
        if not isinstance(he, dict):
            raise ValueError(
                f"Case '{case_name}' has invalid 'header_equals'; expected object mapping header names to string values."
            )
        for hk, hv in he.items():
            if not isinstance(hk, str):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'header_equals' key {hk!r}; header names must be strings."
                )
            if not isinstance(hv, str):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'header_equals' value for header {hk!r}; expected string."
                )
    if "header_regex" in assertions:
        hr = assertions["header_regex"]
        if not isinstance(hr, dict):
            raise ValueError(
                f"Case '{case_name}' has invalid 'header_regex'; expected object mapping header names to regex pattern strings."
            )
        for hk, hv in hr.items():
            if not isinstance(hk, str):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'header_regex' key {hk!r}; header names must be strings."
                )
            if not isinstance(hv, str):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'header_regex' pattern for header {hk!r}; expected string."
                )
    if "body_json_path_equals" in assertions:
        jpe = assertions["body_json_path_equals"]
        if not isinstance(jpe, dict):
            raise ValueError(
                f"Case '{case_name}' has invalid 'body_json_path_equals'; expected object mapping dot-separated path keys to JSON values."
            )
        for k in jpe.keys():
            if not isinstance(k, str):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_path_equals' key {k!r}; keys must be strings."
                )
            if not k.strip():
                raise ValueError(
                    f"Case '{case_name}': body_json_path_* paths must be non-empty strings"
                )
    if "body_json_has_key" in assertions:
        bjk = assertions["body_json_has_key"]
        if not isinstance(bjk, list):
            raise ValueError(
                f"Case '{case_name}' has invalid 'body_json_has_key'; expected a JSON array of path strings."
            )
        for i, item in enumerate(bjk):
            if not isinstance(item, str):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_has_key' item at index {i}; each path must be a string."
                )
            if not item.strip():
                raise ValueError(
                    f"Case '{case_name}': body_json_path_* paths must be non-empty strings"
                )
    if "body_json_array_length_equals" in assertions:
        ale = assertions["body_json_array_length_equals"]
        if not isinstance(ale, dict):
            raise ValueError(
                f"Case '{case_name}' has invalid 'body_json_array_length_equals'; expected object mapping path keys to non-negative integer lengths."
            )
        for k, v in ale.items():
            if not isinstance(k, str):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_equals' key {k!r}; keys must be strings."
                )
            if not k.strip():
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_equals' path; path keys must be non-empty strings after strip()."
                )
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_equals' value for path {k.strip()!r}; expected a non-negative integer (JSON number), not boolean."
                )
            if v < 0:
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_equals' value for path {k.strip()!r}; length must be >= 0."
                )
    if "body_json_array_length_at_least" in assertions:
        ala = assertions["body_json_array_length_at_least"]
        if not isinstance(ala, dict):
            raise ValueError(
                f"Case '{case_name}' has invalid 'body_json_array_length_at_least'; expected object mapping path keys to non-negative integer minimum lengths."
            )
        for k, v in ala.items():
            if not isinstance(k, str):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_at_least' key {k!r}; keys must be strings."
                )
            if not k.strip():
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_at_least' path; path keys must be non-empty strings after strip()."
                )
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_at_least' value for path {k.strip()!r}; expected a non-negative integer (JSON number), not boolean."
                )
            if v < 0:
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_at_least' value for path {k.strip()!r}; minimum length must be >= 0."
                )
    if "body_json_array_length_at_most" in assertions:
        alm = assertions["body_json_array_length_at_most"]
        if not isinstance(alm, dict):
            raise ValueError(
                f"Case '{case_name}' has invalid 'body_json_array_length_at_most'; expected object mapping path keys to non-negative integer maximum lengths."
            )
        for k, v in alm.items():
            if not isinstance(k, str):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_at_most' key {k!r}; keys must be strings."
                )
            if not k.strip():
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_at_most' path; path keys must be non-empty strings after strip()."
                )
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_at_most' value for path {k.strip()!r}; expected a non-negative integer (JSON number), not boolean."
                )
            if v < 0:
                raise ValueError(
                    f"Case '{case_name}' has invalid 'body_json_array_length_at_most' value for path {k.strip()!r}; maximum length must be >= 0."
                )
    if "extract" in assertions:
        ex = assertions["extract"]
        if not isinstance(ex, dict):
            raise ValueError(
                f"Case '{case_name}' has invalid 'extract'; expected object mapping variable names to JSON path strings."
            )
        for k, v in ex.items():
            if not isinstance(k, str):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'extract' key {k!r}; keys must be strings."
                )
            if not k.strip():
                raise ValueError(
                    f"Case '{case_name}' has invalid 'extract' key; variable names must be non-empty strings after strip()."
                )
            if not isinstance(v, str):
                raise ValueError(
                    f"Case '{case_name}' has invalid 'extract' value for variable {k.strip()!r}; expected a path string."
                )
            if not v.strip():
                raise ValueError(
                    f"Case '{case_name}' has invalid 'extract' path for variable {k.strip()!r}; paths must be non-empty strings after strip()."
                )


def _run_extract(extract_spec: dict, output_text: str) -> tuple[list[str], dict[str, object]]:
    """Parse JSON body and map path strings to variable names. Failures use ``extract missing path`` / invalid json."""
    failures: list[str] = []
    variables: dict[str, object] = {}
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        failures.append("extract invalid json: response body is not valid JSON")
        return failures, variables
    if not isinstance(parsed, dict):
        failures.append("extract invalid json: response body JSON must be an object at the root")
        return failures, variables
    for var_name, path_key in extract_spec.items():
        if not isinstance(var_name, str) or not isinstance(path_key, str):
            continue
        vn = var_name.strip()
        path_resolved = _normalize_json_path_input(path_key.strip())
        if not vn or not path_resolved:
            continue
        val = _resolve_json_path(parsed, path_resolved)
        if val is None:
            failures.append("extract missing path: " + json.dumps({"path": path_resolved}, ensure_ascii=False))
        else:
            variables[vn] = val
    return failures, variables


def _maybe_extract(case: dict, adapter_result: AdapterResult) -> tuple[list[str], dict[str, object]]:
    """Run extract spec after a successful attempt (transport ok + caller verified assertions passed)."""
    if not adapter_result.ok:
        return [], {}
    assertions = case.get("assertions", {})
    if not isinstance(assertions, dict):
        return [], {}
    spec = assertions.get("extract")
    if spec is None:
        return [], {}
    if not isinstance(spec, dict):
        return [], {}
    return _run_extract(spec, adapter_result.output_text or "")


def _assert_output_matches(assertions, adapter_result):
    failures = []
    output_text = adapter_result.output_text or ""
    if "status_code" in assertions and adapter_result.status_code != int(assertions["status_code"]):
        failures.append(
            f"expected status_code={int(assertions['status_code'])}, got {adapter_result.status_code}"
        )
    if "expected_status" in assertions:
        exp = assertions["expected_status"]
        if adapter_result.status_code != exp:
            failures.append(f"expected expected_status={exp}, got {adapter_result.status_code}")
    if "expected_response_time_ms" in assertions:
        exp_rt = assertions["expected_response_time_ms"]
        if isinstance(exp_rt, int) and not isinstance(exp_rt, bool):
            actual_rt = int(adapter_result.latency_ms)
            if actual_rt > int(exp_rt):
                failures.append(
                    "expected_response_time_ms exceeded: "
                    + json.dumps({"expected": int(exp_rt), "actual": actual_rt}, ensure_ascii=False)
                )
    contains_all = assertions.get("contains_all", [])
    if isinstance(contains_all, list):
        for token in contains_all:
            token_text = str(token)
            if token_text not in output_text:
                failures.append(f"missing required token: {token_text!r}")
    not_contains = assertions.get("not_contains", [])
    if isinstance(not_contains, list):
        for token in not_contains:
            token_text = str(token)
            if token_text in output_text:
                failures.append(f"forbidden token present: {token_text!r}")
    if "equals" in assertions:
        if output_text.strip() != str(assertions["equals"]).strip():
            failures.append("output text did not match expected equality assertion")
    if "regex" in assertions:
        pattern = str(assertions["regex"])
        if not re.search(pattern, output_text, flags=re.MULTILINE):
            failures.append(f"regex did not match: {pattern!r}")
    if "body_contains" in assertions:
        needle = assertions["body_contains"]
        if needle not in output_text:
            failures.append(f"body did not contain substring {needle!r}")
    if "body_equals" in assertions:
        expected_raw = assertions["body_equals"]
        expected = _normalize_text(expected_raw)
        actual = _normalize_text(output_text)
        if actual != expected:
            failures.append(f"body_equals mismatch: expected {expected!r}, got {actual!r}")
    if "body_regex" in assertions:
        pattern = assertions["body_regex"]
        pattern_str = str(pattern)
        try:
            if not re.search(pattern_str, output_text, flags=re.MULTILINE):
                failures.append(f"body_regex mismatch: pattern {pattern_str!r} did not match response body")
        except re.error as exc:
            failures.append(f"body_regex invalid pattern: {pattern_str!r}: {exc}")
    if "body_json_path_equals" in assertions:
        expected_map = assertions["body_json_path_equals"]
        if isinstance(expected_map, dict):
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                failures.append("body_json_path_equals invalid json: response body is not valid JSON")
            else:
                if not isinstance(parsed, dict):
                    failures.append(
                        "body_json_path_equals invalid json: response body JSON must be an object at the root"
                    )
                else:
                    for path_key, expected_value in expected_map.items():
                        if not isinstance(path_key, str):
                            continue
                        path_resolved = path_key.strip()
                        actual_value = _resolve_json_path(parsed, path_resolved)
                        if actual_value is None:
                            failures.append(_body_json_path_missing_failure(path_resolved))
                        elif actual_value != expected_value:
                            failures.append(
                                f"body_json_path_equals mismatch: key {path_resolved!r} expected {expected_value!r}, got {actual_value!r}"
                            )
    if "body_json_has_key" in assertions:
        paths = assertions["body_json_has_key"]
        if isinstance(paths, list):
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                failures.append("body_json_has_key invalid json: response body is not valid JSON")
            else:
                if not isinstance(parsed, dict):
                    failures.append(
                        "body_json_has_key invalid json: response body JSON must be an object at the root"
                    )
                else:
                    for path in paths:
                        if not isinstance(path, str):
                            continue
                        path_resolved = path.strip()
                        if not path_resolved:
                            continue
                        if not _json_path_exists(parsed, path_resolved):
                            failures.append(_body_json_path_missing_failure(path_resolved))
    if "body_json_array_length_equals" in assertions:
        expected_lens = assertions["body_json_array_length_equals"]
        if isinstance(expected_lens, dict):
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                failures.append("body_json_array_length_equals invalid json: response body is not valid JSON")
            else:
                if not isinstance(parsed, dict):
                    failures.append(
                        "body_json_array_length_equals invalid json: response body JSON must be an object at the root"
                    )
                else:
                    for path_key, expected_n in expected_lens.items():
                        if not isinstance(path_key, str):
                            continue
                        path_resolved = path_key.strip()
                        if not path_resolved:
                            continue
                        if isinstance(expected_n, bool) or not isinstance(expected_n, int):
                            continue
                        actual_value = _resolve_json_path(parsed, path_resolved)
                        if actual_value is None:
                            failures.append(_body_json_path_missing_failure(path_resolved))
                        elif not isinstance(actual_value, list):
                            failures.append(
                                "body_json_array_length_equals not array: "
                                + json.dumps(
                                    {"path": path_resolved, "type": type(actual_value).__name__},
                                    ensure_ascii=False,
                                )
                            )
                        elif len(actual_value) != int(expected_n):
                            failures.append(
                                "body_json_array_length_equals mismatch: "
                                + json.dumps(
                                    {
                                        "path": path_resolved,
                                        "expected": int(expected_n),
                                        "actual_length": len(actual_value),
                                    },
                                    ensure_ascii=False,
                                )
                            )
    if "body_json_array_length_at_least" in assertions:
        min_lens = assertions["body_json_array_length_at_least"]
        if isinstance(min_lens, dict):
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                failures.append("body_json_array_length_at_least invalid json: response body is not valid JSON")
            else:
                if not isinstance(parsed, dict):
                    failures.append(
                        "body_json_array_length_at_least invalid json: response body JSON must be an object at the root"
                    )
                else:
                    for path_key, expected_min in min_lens.items():
                        if not isinstance(path_key, str):
                            continue
                        path_resolved = path_key.strip()
                        if not path_resolved:
                            continue
                        if isinstance(expected_min, bool) or not isinstance(expected_min, int):
                            continue
                        actual_value = _resolve_json_path(parsed, path_resolved)
                        if actual_value is None:
                            failures.append(_body_json_path_missing_failure(path_resolved))
                        elif not isinstance(actual_value, list):
                            failures.append(
                                "body_json_array_length_at_least not array: "
                                + json.dumps(
                                    {"path": path_resolved, "type": type(actual_value).__name__},
                                    ensure_ascii=False,
                                )
                            )
                        elif len(actual_value) < int(expected_min):
                            failures.append(
                                "body_json_array_length_at_least mismatch: "
                                + json.dumps(
                                    {
                                        "path": path_resolved,
                                        "expected_minimum": int(expected_min),
                                        "actual_length": len(actual_value),
                                    },
                                    ensure_ascii=False,
                                )
                            )
    if "body_json_array_length_at_most" in assertions:
        max_lens = assertions["body_json_array_length_at_most"]
        if isinstance(max_lens, dict):
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                failures.append("body_json_array_length_at_most invalid json: response body is not valid JSON")
            else:
                if not isinstance(parsed, dict):
                    failures.append(
                        "body_json_array_length_at_most invalid json: response body JSON must be an object at the root"
                    )
                else:
                    for path_key, expected_max in max_lens.items():
                        if not isinstance(path_key, str):
                            continue
                        path_resolved = path_key.strip()
                        if not path_resolved:
                            continue
                        if isinstance(expected_max, bool) or not isinstance(expected_max, int):
                            continue
                        actual_value = _resolve_json_path(parsed, path_resolved)
                        if actual_value is None:
                            failures.append(_body_json_path_missing_failure(path_resolved))
                        elif not isinstance(actual_value, list):
                            failures.append(
                                "body_json_array_length_at_most not array: "
                                + json.dumps(
                                    {"path": path_resolved, "type": type(actual_value).__name__},
                                    ensure_ascii=False,
                                )
                            )
                        elif len(actual_value) > int(expected_max):
                            failures.append(
                                "body_json_array_length_at_most mismatch: "
                                + json.dumps(
                                    {
                                        "path": path_resolved,
                                        "expected_maximum": int(expected_max),
                                        "actual_length": len(actual_value),
                                    },
                                    ensure_ascii=False,
                                )
                            )
    if "header_equals" in assertions:
        expected_headers = assertions["header_equals"]
        hdrs = adapter_result.response_headers or {}
        if isinstance(expected_headers, dict):
            for hname, expected_value in expected_headers.items():
                actual_value = _response_header_value(hdrs, hname)
                if actual_value is None:
                    failures.append(f"header_equals missing header: {hname!r}")
                elif actual_value.strip() != str(expected_value).strip():
                    failures.append(
                        f"header_equals mismatch: header {hname!r} expected {str(expected_value).strip()!r}, got {actual_value.strip()!r}"
                    )
    if "header_regex" in assertions:
        header_patterns = assertions["header_regex"]
        hdrs = adapter_result.response_headers or {}
        if isinstance(header_patterns, dict):
            for hname, pattern in header_patterns.items():
                pattern_str = str(pattern)
                actual_value = _response_header_value(hdrs, hname)
                if actual_value is None:
                    failures.append(f"header_regex missing header: {hname!r}")
                else:
                    try:
                        if not re.search(pattern_str, actual_value):
                            failures.append(
                                f"header_regex mismatch: header {hname!r} pattern {pattern_str!r} did not match value {actual_value!r}"
                            )
                    except re.error as exc:
                        failures.append(
                            f"header_regex invalid pattern: header {hname!r} pattern {pattern_str!r}: {exc}"
                        )
    if "header_contains" in assertions:
        needle = assertions["header_contains"]
        hdr_blob = _serialize_headers_for_assertion(adapter_result.response_headers or {})
        if needle not in hdr_blob:
            failures.append(f"response headers did not contain substring {needle!r}")
    return failures


def _evaluate_single_attempt(case, adapter_result):
    failures = []
    if not adapter_result.ok:
        failures.append(adapter_result.error or "transport failure")
    else:
        output_text = adapter_result.output_text or ""
        if case.get("expected_status") is not None:
            exp_status = int(case["expected_status"])
            if adapter_result.status_code != exp_status:
                failures.append(
                    f"expected_status mismatch: expected {exp_status}, got {adapter_result.status_code}"
                )
        if case.get("expected_status_in") is not None:
            exp_statuses = [int(x) for x in case["expected_status_in"]]
            if adapter_result.status_code not in exp_statuses:
                failures.append(
                    "expected_status_in mismatch: "
                    + json.dumps(
                        {
                            "expected_any_of": exp_statuses,
                            "actual": adapter_result.status_code,
                        },
                        ensure_ascii=False,
                    )
                )
        if case.get("expected_status_not") is not None:
            exp_statuses_not = [int(x) for x in case["expected_status_not"]]
            if adapter_result.status_code in exp_statuses_not:
                failures.append(
                    "expected_status_not mismatch: "
                    + json.dumps(
                        {
                            "expected_not_any_of": exp_statuses_not,
                            "actual": adapter_result.status_code,
                        },
                        ensure_ascii=False,
                    )
                )
        if (
            case.get("expected_status") is None
            and case.get("expected_status_in") is None
            and case.get("expected_status_not") is None
        ):
            sc = adapter_result.status_code
            if not isinstance(sc, int) or sc < 200 or sc > 299:
                failures.append(f"default status check failed: expected 2xx, got {sc}")
        if case.get("expected_headers") is not None:
            expected_headers = case["expected_headers"]
            hdrs = adapter_result.response_headers or {}
            if isinstance(expected_headers, dict):
                for hname, expected_value in expected_headers.items():
                    actual_value = _response_header_value(hdrs, hname)
                    if actual_value is None:
                        failures.append(
                            f"expected_headers missing header: {hname!r} (expected {str(expected_value).strip()!r}, got missing)"
                        )
                    elif actual_value.strip() != str(expected_value).strip():
                        failures.append(
                            f"expected_headers mismatch: header {hname!r} expected {str(expected_value).strip()!r}, got {actual_value.strip()!r}"
                        )
        if case.get("expected_headers_contains") is not None:
            expected_headers_contains = case["expected_headers_contains"]
            hdrs = adapter_result.response_headers or {}
            if isinstance(expected_headers_contains, dict):
                for hname, expected_substring in expected_headers_contains.items():
                    actual_value = _response_header_value(hdrs, hname)
                    if actual_value is None:
                        failures.append(
                            f"expected_headers_contains missing header: {hname!r} (expected substring {str(expected_substring)!r}, got missing)"
                        )
                    elif str(expected_substring) not in actual_value:
                        failures.append(
                            f"expected_headers_contains mismatch: header {hname!r} expected to contain {str(expected_substring)!r}, got {actual_value!r}"
                        )
        if case.get("expected_header_exists") is not None:
            expected_header_exists = case["expected_header_exists"]
            hdrs = adapter_result.response_headers or {}
            if isinstance(expected_header_exists, list):
                for hname in expected_header_exists:
                    actual_value = _response_header_value(hdrs, str(hname))
                    if actual_value is None:
                        failures.append(f"expected_header_exists missing header: {str(hname)!r}")
        if case.get("expected_json") is not None:
            expected_json = case["expected_json"]
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                failures.append("expected_json invalid json: response body is not valid JSON")
            else:
                if not isinstance(parsed, dict):
                    failures.append("expected_json invalid json: response body JSON must be an object at the root")
                else:
                    for path_key, expected_value in expected_json.items():
                        path_resolved = str(path_key).strip()
                        actual_value = _resolve_simple_json_dot_path(parsed, path_resolved)
                        if actual_value is _SIMPLE_JSON_PATH_MISSING:
                            failures.append(
                                "expected_json missing path: "
                                + json.dumps({"path": path_resolved}, ensure_ascii=False)
                            )
                        elif actual_value != expected_value:
                            failures.append(
                                "expected_json mismatch: "
                                + json.dumps(
                                    {
                                        "path": path_resolved,
                                        "expected": expected_value,
                                        "actual": actual_value,
                                    },
                                    ensure_ascii=False,
                                )
                            )
        if case.get("expected_json_exists") is not None:
            expected_json_exists = case["expected_json_exists"]
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                failures.append("expected_json_exists invalid json: response body is not valid JSON")
            else:
                if not isinstance(parsed, dict):
                    failures.append(
                        "expected_json_exists invalid json: response body JSON must be an object at the root"
                    )
                else:
                    for path_key in expected_json_exists:
                        path_resolved = str(path_key).strip()
                        actual_value = _resolve_simple_json_dot_path(parsed, path_resolved)
                        if actual_value is _SIMPLE_JSON_PATH_MISSING:
                            failures.append(
                                "expected_json_exists missing path: "
                                + json.dumps({"path": path_resolved}, ensure_ascii=False)
                            )
        if case.get("expected_json_values") is not None:
            expected_json_values = case["expected_json_values"]
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                failures.append("expected_json_values invalid json: response body is not valid JSON")
            else:
                if not isinstance(parsed, dict):
                    failures.append(
                        "expected_json_values invalid json: response body JSON must be an object at the root"
                    )
                else:
                    for key, expected_value in expected_json_values.items():
                        if key not in parsed:
                            failures.append(f"missing_json_key: {key}")
                        else:
                            actual_value = parsed.get(key)
                            if actual_value != expected_value:
                                failures.append(
                                    "json_value_mismatch: "
                                    f"{key}, expected={json.dumps(expected_value, ensure_ascii=False)}, "
                                    f"got={json.dumps(actual_value, ensure_ascii=False)}"
                                )
        if case.get("expected_json_absent") is not None:
            expected_json_absent = case["expected_json_absent"]
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                failures.append("expected_json_absent invalid json: response body is not valid JSON")
            else:
                if not isinstance(parsed, dict):
                    failures.append(
                        "expected_json_absent invalid json: response body JSON must be an object at the root"
                    )
                else:
                    for key in expected_json_absent:
                        if key in parsed:
                            failures.append(f"json_key_present_but_expected_absent: {key}")
        if case.get("max_duration_ms") is not None:
            max_duration_ms = int(case["max_duration_ms"])
            actual_duration_ms = int(adapter_result.latency_ms)
            if actual_duration_ms > max_duration_ms:
                failures.append(
                    "max_duration_ms exceeded: "
                    + json.dumps(
                        {"max_duration_ms": max_duration_ms, "actual_duration_ms": actual_duration_ms},
                        ensure_ascii=False,
                    )
                )
        if case.get("expected_latency_ms_max") is not None:
            expected_latency_ms_max = int(case["expected_latency_ms_max"])
            actual_latency_ms = int(adapter_result.latency_ms)
            if actual_latency_ms > expected_latency_ms_max:
                failures.append(
                    "expected_latency_ms_max exceeded: "
                    + json.dumps(
                        {
                            "expected_latency_ms_max": expected_latency_ms_max,
                            "actual_latency_ms": actual_latency_ms,
                        },
                        ensure_ascii=False,
                    )
                )
        if case.get("expected_body_not_empty") is True:
            body_val = adapter_result.output_text
            if body_val is None or body_val == "":
                failures.append("expected_body_not_empty failed: response body is empty or null")
        if case.get("expected_body_size_bytes_max") is not None:
            expected_body_size_bytes_max = int(case["expected_body_size_bytes_max"])
            body_text = adapter_result.output_text or ""
            actual_body_size_bytes = len(body_text.encode("utf-8"))
            if actual_body_size_bytes > expected_body_size_bytes_max:
                failures.append(
                    "expected_body_size_bytes_max exceeded: "
                    + json.dumps(
                        {
                            "expected_body_size_bytes_max": expected_body_size_bytes_max,
                            "actual_body_size_bytes": actual_body_size_bytes,
                        },
                        ensure_ascii=False,
                    )
                )
        if case.get("expected_response_time_ms_range") is not None:
            min_ms = int(case["expected_response_time_ms_range"][0])
            max_ms = int(case["expected_response_time_ms_range"][1])
            actual_latency_ms = int(adapter_result.latency_ms)
            if actual_latency_ms < min_ms or actual_latency_ms > max_ms:
                failures.append(
                    "expected_response_time_ms_range mismatch: "
                    + json.dumps(
                        {
                            "expected_min": min_ms,
                            "expected_max": max_ms,
                            "actual": actual_latency_ms,
                        },
                        ensure_ascii=False,
                    )
                )
        failures.extend(_assert_output_matches(case["assertions"], adapter_result))
    return failures


class _SimpleJsonPathMissing:
    __slots__ = ()


_SIMPLE_JSON_PATH_MISSING = _SimpleJsonPathMissing()


def _resolve_simple_json_dot_path(root: object, path: str):
    """
    Resolve simple dot-path keys only (no array indexing) for expected_json.
    Returns _SIMPLE_JSON_PATH_MISSING when not found / invalid traversal.
    """
    current = root
    for part in path.split("."):
        key = part.strip()
        if not key or not isinstance(current, dict) or key not in current:
            return _SIMPLE_JSON_PATH_MISSING
        current = current[key]
    return current


def _is_transient_retry_candidate(adapter_result: AdapterResult) -> bool:
    if not adapter_result.ok:
        return True
    sc = adapter_result.status_code
    return isinstance(sc, int) and 500 <= sc <= 599


def _run_case_with_optional_retries(
    request_case: dict, adapter, *, retries: int | None = None, retry_delay_ms: int | None = None
) -> tuple[AdapterResult, list[dict], str | None]:
    """Run one request with optional transient-only retries; returns final result, attempt summaries, optional exhausted reason."""
    retry_n = int(retries) if retries is not None else 0
    delay_ms = int(retry_delay_ms) if retry_delay_ms is not None else 0
    max_attempts = 1 + max(0, retry_n)
    attempts: list[dict] = []
    last: AdapterResult | None = None
    for i in range(max_attempts):
        result = adapter.run_case(request_case)
        last = result
        transient = _is_transient_retry_candidate(result)
        summary = ""
        if not result.ok:
            summary = result.error or "transport failure"
        elif transient and result.status_code is not None:
            summary = f"http {int(result.status_code)}"
        attempts.append(
            {
                "attempt": i + 1,
                "status_code": result.status_code,
                "latency_ms": int(result.latency_ms),
                "transient_failure": bool(transient),
                "failure_summary": summary,
            }
        )
        if not transient:
            return result, attempts, None
        if retry_n <= 0:
            return result, attempts, None
        if i < max_attempts - 1 and delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
    assert last is not None
    exhausted_reason = "retries exhausted after transient failures: " + json.dumps(
        {
            "attempts": max_attempts,
            "last_status_code": last.status_code,
            "last_error": last.error,
        },
        ensure_ascii=False,
    )
    return last, attempts, exhausted_reason


def _run_n_attempts(case, adapter, n):
    attempts_out = []
    all_ok = True
    last_adapter_result = None
    for attempt_idx in range(n):
        adapter_result = adapter.run_case(case)
        last_adapter_result = adapter_result
        failures = _evaluate_single_attempt(case, adapter_result)
        attempt_ok = len(failures) == 0
        all_ok = all_ok and attempt_ok
        attempts_out.append(
            {
                "attempt": attempt_idx + 1,
                "ok": attempt_ok,
                "failures": failures,
                "status_code": adapter_result.status_code,
                "latency_ms": adapter_result.latency_ms,
                "output_preview": (adapter_result.output_text or "")[:600],
                "output_full": _cap_output_full(adapter_result.output_text or ""),
                "response_headers": dict(adapter_result.response_headers),
            }
        )
        if case.get("max_duration_ms") is not None:
            attempts_out[-1]["max_duration_ms"] = int(case["max_duration_ms"])
    case_failures = []
    if not all_ok:
        for a in attempts_out:
            if not a["ok"]:
                for f in a["failures"]:
                    case_failures.append(f"attempt {a['attempt']}/{n}: {f}")
    attempts_passed = sum(1 for a in attempts_out if a["ok"])
    return attempts_out, all_ok, last_adapter_result, case_failures, attempts_passed


def _execute_correctness_case(
    case, adapter
) -> tuple[list[str], AdapterResult | None, dict[str, object], list[dict], dict, object]:
    """Default lane: optional second HTTP hop after successful extract when templates use {{var}}."""
    variables: dict[str, object] = {}
    needs_second = _case_request_templates_have_placeholders(case)

    run1, err1 = _build_substituted_adapter_case(case, {}, first_hop=True)
    if err1:
        return [err1], None, {}, [], {}, None
    r1, attempts1, exhausted1 = _run_case_with_optional_retries(
        run1, adapter, retries=case.get("retries"), retry_delay_ms=case.get("retry_delay_ms")
    )
    if exhausted1:
        return [exhausted1], r1, {}, attempts1, dict(run1.get("headers", {})), _request_body_for_output(run1)
    failures = _evaluate_single_attempt(case, r1)
    if failures:
        return failures, r1, {}, attempts1, dict(run1.get("headers", {})), _request_body_for_output(run1)
    exf, variables = _maybe_extract(case, r1)
    failures.extend(exf)
    if failures:
        return failures, r1, variables, attempts1, dict(run1.get("headers", {})), _request_body_for_output(run1)

    adapter_result = r1
    attempts_out = list(attempts1)
    request_headers = dict(run1.get("headers", {}))
    request_body = _request_body_for_output(run1)
    if needs_second:
        run2, err2 = _build_substituted_adapter_case(case, variables, first_hop=False)
        if err2:
            return [err2], r1, variables, attempts_out, request_headers, request_body
        r2, attempts2, exhausted2 = _run_case_with_optional_retries(
            run2, adapter, retries=case.get("retries"), retry_delay_ms=case.get("retry_delay_ms")
        )
        attempts_out.extend(attempts2)
        request_headers = dict(run2.get("headers", {}))
        request_body = _request_body_for_output(run2)
        if exhausted2:
            return [exhausted2], r2, variables, attempts_out, request_headers, request_body
        failures = _evaluate_single_attempt(case, r2)
        adapter_result = r2
        if failures:
            return failures, adapter_result, variables, attempts_out, request_headers, request_body
        # Variables for {{...}} substitution are taken from the first hop only (Increment 42).

    return failures, adapter_result, variables, attempts_out, request_headers, request_body


def _step_result_reason(failures: list[str]) -> str:
    if not failures:
        return ""
    if len(failures) == 1:
        return failures[0]
    return " | ".join(failures)


def _execute_steps_case(
    case, adapter
) -> tuple[list[str], AdapterResult | None, dict[str, object], str, str, dict, object, list[dict]]:
    """Run ordered ``steps`` with shared variables; prefix failures with ``step failed`` JSON.

    Returns ``step_results`` (Increment 45): one entry per executed step, PASS or FAIL with url
    (after substitution when available) and ``latency_ms``.
    """
    variables: dict[str, object] = {}
    last_result: AdapterResult | None = None
    last_method = str(case.get("method", "POST")).upper()
    last_url = str(case.get("url", ""))
    last_headers: dict = dict(case.get("headers", {})) if isinstance(case.get("headers", {}), dict) else {}
    last_body = _request_body_for_output(case if isinstance(case, dict) else {})
    step_results: list[dict] = []
    for st in case["steps"]:
        step_name = st["step_name"]
        shell = _case_request_shell_for_step(case, st)
        step_expected_status = _expected_status_code_for_assertions(st.get("assertions"))
        run_dict = _build_substituted_adapter_case_direct_keep_missing(shell, variables)
        last_result, step_attempts, step_exhausted = _run_case_with_optional_retries(
            run_dict, adapter, retries=case.get("retries"), retry_delay_ms=case.get("retry_delay_ms")
        )
        last_method = str(run_dict.get("method", last_method)).upper()
        last_url = str(run_dict.get("url", last_url))
        last_headers = dict(run_dict.get("headers", {})) if isinstance(run_dict.get("headers", {}), dict) else {}
        last_body = _request_body_for_output(run_dict)
        if step_exhausted:
            step_failures = [step_exhausted]
            row = {
                "step": step_name,
                "status": "FAIL",
                "method": str(run_dict.get("method", "")).upper(),
                "url": str(run_dict.get("url", "")),
                "request_headers": _mask_request_headers_for_output(run_dict.get("headers", {})),
                "request_body": _request_body_for_output(run_dict),
                "status_code": last_result.status_code,
                "expected_status_code": step_expected_status,
                "latency_ms": int(last_result.latency_ms),
                "response_headers": dict(last_result.response_headers or {}),
                "response_summary": _extract_response_summary(last_result.output_text or ""),
                "output_preview": (last_result.output_text or "")[:600],
                "output_full": _cap_output_full(last_result.output_text or ""),
                "ok": False,
                "failures": step_failures,
                "error_message": _error_message_for_case(False, step_failures),
                "reason": step_exhausted,
            }
            if case.get("retries") is not None:
                row["attempts_total"] = len(step_attempts)
                row["attempts"] = step_attempts
            step_results.append(row)
            return (
                _prefix_failures_for_step(step_name, [step_exhausted]),
                last_result,
                variables,
                last_method,
                last_url,
                last_headers,
                last_body,
                step_results,
            )
        ev_case = {"assertions": st["assertions"]}
        failures = _evaluate_single_attempt(ev_case, last_result)
        if failures:
            reason = _step_result_reason(failures)
            row = {
                "step": step_name,
                "status": "FAIL",
                "method": str(run_dict.get("method", "")).upper(),
                "url": str(run_dict.get("url", "")),
                "request_headers": _mask_request_headers_for_output(run_dict.get("headers", {})),
                "request_body": _request_body_for_output(run_dict),
                "status_code": last_result.status_code,
                "expected_status_code": step_expected_status,
                "latency_ms": int(last_result.latency_ms),
                "response_headers": dict(last_result.response_headers or {}),
                "response_summary": _extract_response_summary(last_result.output_text or ""),
                "output_preview": (last_result.output_text or "")[:600],
                "output_full": _cap_output_full(last_result.output_text or ""),
                "ok": False,
                "failures": list(failures),
                "error_message": _error_message_for_case(False, failures),
                "reason": reason,
            }
            if case.get("retries") is not None:
                row["attempts_total"] = len(step_attempts)
                row["attempts"] = step_attempts
            step_results.append(row)
            return (
                _prefix_failures_for_step(step_name, failures),
                last_result,
                variables,
                last_method,
                last_url,
                last_headers,
                last_body,
                step_results,
            )
        exf, new_vars = _maybe_extract(ev_case, last_result)
        variables.update(new_vars)
        if exf:
            reason = _step_result_reason(exf)
            row = {
                "step": step_name,
                "status": "FAIL",
                "method": str(run_dict.get("method", "")).upper(),
                "url": str(run_dict.get("url", "")),
                "request_headers": _mask_request_headers_for_output(run_dict.get("headers", {})),
                "request_body": _request_body_for_output(run_dict),
                "status_code": last_result.status_code,
                "expected_status_code": step_expected_status,
                "latency_ms": int(last_result.latency_ms),
                "response_headers": dict(last_result.response_headers or {}),
                "response_summary": _extract_response_summary(last_result.output_text or ""),
                "output_preview": (last_result.output_text or "")[:600],
                "output_full": _cap_output_full(last_result.output_text or ""),
                "ok": False,
                "failures": list(exf),
                "error_message": _error_message_for_case(False, exf),
                "reason": reason,
            }
            if case.get("retries") is not None:
                row["attempts_total"] = len(step_attempts)
                row["attempts"] = step_attempts
            step_results.append(row)
            return (
                _prefix_failures_for_step(step_name, exf),
                last_result,
                variables,
                last_method,
                last_url,
                last_headers,
                last_body,
                step_results,
            )
        row = {
            "step": step_name,
            "status": "PASS",
            "method": str(run_dict.get("method", "")).upper(),
            "url": str(run_dict.get("url", "")),
            "request_headers": _mask_request_headers_for_output(run_dict.get("headers", {})),
            "request_body": _request_body_for_output(run_dict),
            "status_code": last_result.status_code,
            "expected_status_code": step_expected_status,
            "latency_ms": int(last_result.latency_ms),
            "response_headers": dict(last_result.response_headers or {}),
            "response_summary": _extract_response_summary(last_result.output_text or ""),
            "output_preview": (last_result.output_text or "")[:600],
            "output_full": _cap_output_full(last_result.output_text or ""),
            "ok": True,
            "failures": [],
            "error_message": None,
        }
        if case.get("retries") is not None:
            row["attempts_total"] = len(step_attempts)
            row["attempts"] = step_attempts
        step_results.append(row)
    return [], last_result, variables, last_method, last_url, last_headers, last_body, step_results


def _execute_prompt_response_case(case: dict, adapter) -> tuple[bool, list[str], AdapterResult]:
    if not hasattr(adapter, "run_prompt_case"):
        return (
            False,
            ["prompt_response_adapter_missing: adapter must implement run_prompt_case(case)"],
            AdapterResult(
                ok=False,
                status_code=None,
                output_text="",
                latency_ms=0,
                error="prompt_response_adapter_missing",
                response_headers={},
            ),
        )
    try:
        adapter_result = adapter.run_prompt_case(case)
    except Exception as exc:
        return (
            False,
            [f"prompt_response_adapter_exception: {type(exc).__name__}: {exc}"],
            AdapterResult(
                ok=False,
                status_code=None,
                output_text="",
                latency_ms=0,
                error="prompt_response_adapter_exception",
                response_headers={},
            ),
        )
    if not isinstance(adapter_result, AdapterResult):
        return (
            False,
            ["prompt_response_adapter_invalid_result: run_prompt_case(case) must return AdapterResult"],
            AdapterResult(
                ok=False,
                status_code=None,
                output_text="",
                latency_ms=0,
                error="prompt_response_adapter_invalid_result",
                response_headers={},
            ),
        )
    failures: list[str] = []
    if not adapter_result.ok:
        failures.append(f"adapter_error: {adapter_result.error or 'unknown prompt adapter failure'}")
    raw_text = adapter_result.output_text
    text = raw_text if isinstance(raw_text, str) else ("" if raw_text is None else str(raw_text))
    if text != (adapter_result.output_text or ""):
        adapter_result = AdapterResult(
            ok=adapter_result.ok,
            status_code=adapter_result.status_code,
            output_text=text,
            latency_ms=adapter_result.latency_ms,
            error=adapter_result.error,
            response_headers=dict(adapter_result.response_headers or {}),
        )
    for needle in case.get("expected_response_contains", []):
        if needle not in text:
            failures.append(f"expected_response_missing_substring: {needle}")
    for needle in case.get("expected_response_not_contains", []):
        if needle in text:
            failures.append(f"expected_response_forbidden_substring_present: {needle}")
    pattern = case.get("expected_response_regex")
    if pattern is not None:
        try:
            if re.search(str(pattern), text, flags=re.MULTILINE) is None:
                failures.append(f"expected_response_regex_mismatch: {pattern}")
        except re.error as exc:
            failures.append(f"expected_response_regex_invalid: {pattern}: {exc}")
    starts_with = case.get("expected_response_starts_with")
    if starts_with is not None and not text.startswith(str(starts_with)):
        failures.append(f"expected_response_prefix_mismatch: expected_prefix={starts_with!r}")
    ends_with = case.get("expected_response_ends_with")
    if ends_with is not None and not text.endswith(str(ends_with)):
        failures.append(f"expected_response_suffix_mismatch: expected_suffix={ends_with!r}")
    equals = case.get("expected_response_equals")
    if equals is not None and text != str(equals):
        failures.append("expected_response_exact_mismatch")
    length_min = case.get("expected_response_length_min")
    if length_min is not None and len(text) < int(length_min):
        failures.append(f"expected_response_length_too_short: min={int(length_min)}, got={len(text)}")
    length_max = case.get("expected_response_length_max")
    if length_max is not None and len(text) > int(length_max):
        failures.append(f"expected_response_length_too_long: max={int(length_max)}, got={len(text)}")
    return len(failures) == 0, failures, adapter_result


def _expected_status_code_for_case(case: dict) -> int:
    """
    Report-friendly expected status code.
    Uses explicit expected status when present; otherwise defaults to 200.
    """
    if case.get("expected_status") is not None:
        try:
            return int(case["expected_status"])
        except (TypeError, ValueError):
            return 200
    assertions = case.get("assertions")
    if isinstance(assertions, dict) and assertions.get("status_code") is not None:
        try:
            return int(assertions["status_code"])
        except (TypeError, ValueError):
            return 200
    return 200


def _expected_status_code_for_assertions(assertions: dict | None) -> int:
    if isinstance(assertions, dict):
        if assertions.get("expected_status") is not None:
            try:
                return int(assertions["expected_status"])
            except (TypeError, ValueError):
                return 200
        if assertions.get("status_code") is not None:
            try:
                return int(assertions["status_code"])
            except (TypeError, ValueError):
                return 200
    return 200


def _error_message_for_case(case_ok: bool, failures: list[str] | None) -> str | None:
    if case_ok:
        return None
    if isinstance(failures, list):
        for f in failures:
            s = str(f).strip()
            if s:
                return s
    return "case failed"


def execute_suite(suite, adapter, fail_fast=False):
    started = time.perf_counter()
    case_results = []
    passed = 0
    failed = 0
    for case in suite["cases"]:
        if case.get("lane") == "prompt_response":
            case_ok, case_failures, adapter_result = _execute_prompt_response_case(case, adapter)
            if case_ok:
                passed += 1
            else:
                failed += 1
            case_results.append(
                {
                    "name": case["name"],
                    "lane": case.get("lane"),
                    "ok": case_ok,
                    "failures": case_failures,
                    "error_message": _error_message_for_case(case_ok, case_failures),
                    "status_code": adapter_result.status_code,
                    "expected_status_code": _expected_status_code_for_case(case),
                    "latency_ms": adapter_result.latency_ms,
                    "output_preview": (adapter_result.output_text or "")[:600],
                    "output_full": _cap_output_full(adapter_result.output_text or ""),
                    "response_summary": _extract_response_summary(adapter_result.output_text or ""),
                    "request_headers": _mask_request_headers_for_output({}),
                    "request_body": None,
                    "response_headers": dict(adapter_result.response_headers or {}),
                    "method": "PROMPT",
                    "url": "prompt://local",
                    "prompt_input": case.get("prompt_input", ""),
                    "expected_response_contains": list(case.get("expected_response_contains") or []),
                    "expected_response_not_contains": list(case.get("expected_response_not_contains") or []),
                    "expected_response_regex": case.get("expected_response_regex"),
                    "expected_response_starts_with": case.get("expected_response_starts_with"),
                    "expected_response_ends_with": case.get("expected_response_ends_with"),
                    "expected_response_equals": case.get("expected_response_equals"),
                    "expected_response_length_min": case.get("expected_response_length_min"),
                    "expected_response_length_max": case.get("expected_response_length_max"),
                }
            )
        elif case.get("lane") == "stability":
            n = int(case["stability_attempts"])
            attempts_out, case_ok, last_adapter_result, case_failures, attempts_passed = _run_n_attempts(
                case, adapter, n
            )
            variables: dict[str, object] = {}
            if case_ok and last_adapter_result is not None:
                exf, variables = _maybe_extract(case, last_adapter_result)
                if exf:
                    case_ok = False
                    case_failures = list(exf)
            if case_ok:
                passed += 1
            else:
                failed += 1
            row = {
                "name": case["name"],
                "lane": case.get("lane"),
                "stability_attempts": n,
                "attempts_passed": attempts_passed,
                "attempts_total": n,
                "attempts": attempts_out,
                "ok": case_ok,
                "failures": case_failures,
                "error_message": _error_message_for_case(case_ok, case_failures),
                "status_code": last_adapter_result.status_code if last_adapter_result else None,
                "expected_status_code": _expected_status_code_for_case(case),
                "latency_ms": last_adapter_result.latency_ms if last_adapter_result else 0,
                "output_preview": (last_adapter_result.output_text or "")[:600]
                if last_adapter_result
                else "",
                "output_full": _cap_output_full(last_adapter_result.output_text or "")
                if last_adapter_result
                else "",
                "response_summary": _extract_response_summary(last_adapter_result.output_text or "")
                if last_adapter_result
                else "",
                "request_headers": _mask_request_headers_for_output(case.get("headers", {})),
                "request_body": _request_body_for_output(case),
                "response_headers": dict(last_adapter_result.response_headers)
                if last_adapter_result
                else {},
                "method": case["method"],
                "url": case["url"],
            }
            if isinstance(case.get("assertions"), dict) and case["assertions"].get("extract") is not None:
                row["variables"] = variables
            if case.get("max_duration_ms") is not None:
                row["max_duration_ms"] = int(case["max_duration_ms"])
            case_results.append(row)
        elif case.get("lane") == "consistency":
            n = int(case["repeat_count"])
            attempts_out, case_ok, last_adapter_result, case_failures, attempts_passed = _run_n_attempts(
                case, adapter, n
            )
            variables: dict[str, object] = {}
            if case_ok and last_adapter_result is not None:
                exf, variables = _maybe_extract(case, last_adapter_result)
                if exf:
                    case_ok = False
                    case_failures = list(exf)
            if case_ok:
                passed += 1
            else:
                failed += 1
            row = {
                "name": case["name"],
                "lane": case.get("lane"),
                "repeat_count": n,
                "attempts_passed": attempts_passed,
                "attempts_total": n,
                "attempts": attempts_out,
                "ok": case_ok,
                "failures": case_failures,
                "error_message": _error_message_for_case(case_ok, case_failures),
                "status_code": last_adapter_result.status_code if last_adapter_result else None,
                "expected_status_code": _expected_status_code_for_case(case),
                "latency_ms": last_adapter_result.latency_ms if last_adapter_result else 0,
                "output_preview": (last_adapter_result.output_text or "")[:600]
                if last_adapter_result
                else "",
                "output_full": _cap_output_full(last_adapter_result.output_text or "")
                if last_adapter_result
                else "",
                "response_summary": _extract_response_summary(last_adapter_result.output_text or "")
                if last_adapter_result
                else "",
                "request_headers": _mask_request_headers_for_output(case.get("headers", {})),
                "request_body": _request_body_for_output(case),
                "response_headers": dict(last_adapter_result.response_headers)
                if last_adapter_result
                else {},
                "method": case["method"],
                "url": case["url"],
            }
            if isinstance(case.get("assertions"), dict) and case["assertions"].get("extract") is not None:
                row["variables"] = variables
            if case.get("max_duration_ms") is not None:
                row["max_duration_ms"] = int(case["max_duration_ms"])
            case_results.append(row)
        else:
            if case.get("steps"):
                failures, adapter_result, variables, row_method, row_url, row_headers, row_body, step_results = _execute_steps_case(
                    case, adapter
                )
                retry_attempts = []
            else:
                failures, adapter_result, variables, retry_attempts, row_headers, row_body = _execute_correctness_case(case, adapter)
                row_method = case["method"]
                row_url = case["url"]
                step_results = []
            if adapter_result is None:
                adapter_result = AdapterResult(
                    ok=False,
                    status_code=None,
                    output_text="",
                    latency_ms=0,
                    error=None,
                    response_headers={},
                )
            case_ok = len(failures) == 0
            if case_ok:
                passed += 1
            else:
                failed += 1
            row = {
                "name": case["name"],
                "lane": case.get("lane"),
                "ok": case_ok,
                "failures": failures,
                "error_message": _error_message_for_case(case_ok, failures),
                "status_code": adapter_result.status_code,
                "expected_status_code": _expected_status_code_for_case(case),
                "latency_ms": adapter_result.latency_ms,
                "output_preview": (adapter_result.output_text or "")[:600],
                "output_full": _cap_output_full(adapter_result.output_text or ""),
                "response_summary": _extract_response_summary(adapter_result.output_text or ""),
                "request_headers": _mask_request_headers_for_output(row_headers),
                "request_body": row_body,
                "response_headers": dict(adapter_result.response_headers),
                "method": row_method,
                "url": row_url,
            }
            if case.get("steps"):
                row["variables"] = variables
                row["steps"] = step_results
            elif isinstance(case.get("assertions"), dict) and case["assertions"].get("extract") is not None:
                row["variables"] = variables
            if case.get("max_duration_ms") is not None:
                row["max_duration_ms"] = int(case["max_duration_ms"])
            if case.get("retries") is not None:
                row["retry_attempts_total"] = len(retry_attempts)
                row["retry_attempts"] = retry_attempts
            case_results.append(row)
        if fail_fast and not case_results[-1].get("ok"):
            break
    elapsed_seconds = round(time.perf_counter() - started, 3)
    finished_utc = datetime.now(timezone.utc).isoformat()
    for row in case_results:
        row["ran_at_utc"] = finished_utc
    return {
        "suite_name": suite["suite_name"],
        "target_name": suite["target_name"],
        "executed_cases": len(case_results),
        "passed_cases": passed,
        "failed_cases": failed,
        "ok": failed == 0,
        "elapsed_seconds": elapsed_seconds,
        "ran_at_utc": finished_utc,
        "cases": case_results,
    }


def _utc_iso_to_filename_timestamp(iso: str | None) -> str:
    """Turn ``result['ran_at_utc']`` into a Windows-safe ``YYYY-MM-DD_HHMMSS`` fragment (UTC)."""
    if iso:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%d_%H%M%S")
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def build_timestamped_artifact_stem(base_stem: str, result: dict | None) -> str:
    """
    Return ``<slug>_<YYYY-MM-DD_HHMMSS>`` so each run gets a unique pair of files in Explorer.

    Uses ``result['ran_at_utc']`` when present so the stem matches the JSON timestamp.
    """
    raw = (base_stem or "system_eval").strip() or "system_eval"
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw).strip("._-") or "system_eval"
    iso = result.get("ran_at_utc") if isinstance(result, dict) else None
    suffix = _utc_iso_to_filename_timestamp(iso)
    return f"{safe}_{suffix}"


def write_result_artifacts(result, output_dir, file_stem):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    stem = build_timestamped_artifact_stem(file_stem, result)
    json_path = output_path / f"{stem}.json"
    md_path = output_path / f"{stem}.md"
    latest_json_path = output_path / f"{file_stem}.json"
    latest_md_path = output_path / f"{file_stem}.md"
    latest_universal_json_path = output_path / "LATEST_SYSTEM_EVAL.json"
    latest_universal_md_path = output_path / "LATEST_SYSTEM_EVAL.md"

    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    # Keep a stable "latest" artifact alongside timestamped history for easy discovery in Explorer.
    json_path_text = json_path.read_text(encoding="utf-8")
    latest_json_path.write_text(json_path_text, encoding="utf-8")
    latest_universal_json_path.write_text(json_path_text, encoding="utf-8")

    ran_at = result.get("ran_at_utc", "") if isinstance(result, dict) else ""
    lines = [
        f"# System Eval Report: {result.get('suite_name')}",
        "",
        f"- Target: `{result.get('target_name')}`",
        f"- Status: `{'PASS' if result.get('ok') else 'FAIL'}`",
        f"- Run at (UTC): `{ran_at}`",
        f"- Executed cases: `{result.get('executed_cases')}`",
        f"- Passed: `{result.get('passed_cases')}`",
        f"- Failed: `{result.get('failed_cases')}`",
        f"- Elapsed seconds: `{result.get('elapsed_seconds')}`",
        "",
        "## Case Results",
        "",
    ]
    for case in result.get("cases", []):
        status = "PASS" if case.get("ok") else "FAIL"
        lane = case.get("lane")
        lane_part = f" lane=`{lane}`" if lane else " lane=(none)"
        lines.append(
            f"- `{status}` `{case.get('name')}`{lane_part} ({case.get('method')} {case.get('url')})"
        )
        failures = case.get("failures") or []
        if failures:
            for failure in failures:
                lines.append(f"  - {failure}")
        step_results = case.get("steps")
        if not step_results:
            step_results = case.get("step_results")
        if step_results:
            lines.append("  ### Steps")
            lines.append("")
            for sr in step_results:
                if not isinstance(sr, dict):
                    continue
                sn = sr.get("step", "")
                st = sr.get("status", "")
                lat = sr.get("latency_ms", 0)
                url = sr.get("url", "")
                lines.append(f"  - {sn} — {st} — {int(lat)} ms — {url}")
                reason = sr.get("reason")
                if reason is not None and str(reason).strip():
                    lines.append(f"    - Reason: {reason}")
            lines.append("")
        if case.get("lane") == "stability":
            sa = case.get("stability_attempts")
            ap = case.get("attempts_passed")
            at = case.get("attempts_total")
            if sa is not None and ap is not None and at is not None:
                lines.append(
                    f"  - stability: `{ap}/{at}` attempts passed (stability_attempts=`{sa}`)"
                )
            for att in case.get("attempts") or []:
                att_status = "ok" if att.get("ok") else "fail"
                lines.append(
                    f"  - attempt `{att.get('attempt')}`: `{att_status}` "
                    f"(status `{att.get('status_code')}`, latency_ms `{att.get('latency_ms')}`)"
                )
        if case.get("lane") == "consistency":
            rp = case.get("repeat_count")
            ap = case.get("attempts_passed")
            at = case.get("attempts_total")
            if rp is not None and ap is not None and at is not None:
                lines.append(f"  - consistency: `{ap}/{at}` attempts passed (repeat_count=`{rp}`)")
            for att in case.get("attempts") or []:
                att_status = "ok" if att.get("ok") else "fail"
                lines.append(
                    f"  - attempt `{att.get('attempt')}`: `{att_status}` "
                    f"(status `{att.get('status_code')}`, latency_ms `{att.get('latency_ms')}`)"
                )
    lines.append("")
    md_text = "\n".join(lines)
    md_path.write_text(md_text, encoding="utf-8")
    latest_md_path.write_text(md_text, encoding="utf-8")
    latest_universal_md_path.write_text(md_text, encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(md_path)}
