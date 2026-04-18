import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

SYSTEM_EVAL_LANES = frozenset({"stability", "correctness", "consistency"})
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
    {"name", "method", "url", "headers", "payload", "timeout_seconds", "body", "send_json_body", "use"}
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
    if "body" in raw and raw["body"] is not None:
        raise ValueError(
            f"Case '{case_name}' step_templates[{tmpl_key!r}]: 'body' must be JSON null or omitted; "
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
    if "body" in raw and raw["body"] is not None:
        raise ValueError(
            f"Case '{case_name}' step {step_name!r}: 'body' must be JSON null or omitted; "
            f"use 'payload' for JSON object body on POST/PUT/PATCH."
        )
    assertions: dict = {}
    for k, v in raw.items():
        if k in _STEP_REQUEST_KEYS:
            continue
        assertions[k] = v
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
    if "body" in raw and raw["body"] is None:
        out["body"] = None
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
    if case.get("send_json_body") is True:
        return payload
    method_u = str(method).upper()
    if method_u in _METHODS_DEFAULT_JSON_BODY:
        return payload
    # GET / HEAD / DELETE / OPTIONS / … — omit ``json=`` unless handled above.
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
        if not has_steps and not url:
            raise ValueError(f"Case '{name}' is missing a non-empty 'url'.")
        assertions = case.get("assertions", {})
        if not isinstance(assertions, dict):
            raise ValueError(f"Case '{name}' has invalid 'assertions'; expected object.")
        _validate_minimal_assertion_keys(assertions, name)
        lane = None
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

        if has_steps and lane in ("stability", "consistency"):
            raise ValueError(
                f"Case '{name}': 'steps' is not supported for lane {lane!r} "
                f"(use the default correctness lane or omit 'lane')."
            )

        if "body" in case:
            if case["body"] is not None:
                raise ValueError(
                    f"Case '{name}': 'body' must be JSON null (no HTTP JSON body) or omitted; "
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
            if "body" in case and case["body"] is None:
                norm["body"] = None
            if case.get("send_json_body") is True:
                norm["send_json_body"] = True
        else:
            norm = {
                "name": name,
                "lane": lane,
                "method": str(case.get("method", "POST")).upper(),
                "url": url,
                "headers": case.get("headers", {}),
                "payload": case.get("payload", {}),
                "timeout_seconds": default_timeout,
                "assertions": assertions,
            }
            if "body" in case and case["body"] is None:
                norm["body"] = None
            if case.get("send_json_body") is True:
                norm["send_json_body"] = True
        if lane == "consistency":
            norm["repeat_count"] = repeat_count
        if lane == "stability":
            norm["stability_attempts"] = stability_attempts

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
    current = obj
    for part in path.split("."):
        nxt = _walk_json_path_segment(current, part)
        if nxt is _JSON_PATH_STEP_FAILED:
            return None
        current = nxt
    return current


def _json_path_exists(root: object, path: str) -> bool:
    """True if dot path resolves (dict keys and ``name[i]`` list indices); leaf may be JSON null."""
    current = root
    for part in path.split("."):
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
        path_resolved = path_key.strip()
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
        failures.extend(_assert_output_matches(case["assertions"], adapter_result))
    return failures


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
    case_failures = []
    if not all_ok:
        for a in attempts_out:
            if not a["ok"]:
                for f in a["failures"]:
                    case_failures.append(f"attempt {a['attempt']}/{n}: {f}")
    attempts_passed = sum(1 for a in attempts_out if a["ok"])
    return attempts_out, all_ok, last_adapter_result, case_failures, attempts_passed


def _execute_correctness_case(case, adapter) -> tuple[list[str], AdapterResult | None, dict[str, object]]:
    """Default lane: optional second HTTP hop after successful extract when templates use {{var}}."""
    variables: dict[str, object] = {}
    needs_second = _case_request_templates_have_placeholders(case)

    run1, err1 = _build_substituted_adapter_case(case, {}, first_hop=True)
    if err1:
        return [err1], None, {}
    r1 = adapter.run_case(run1)
    failures = _evaluate_single_attempt(case, r1)
    if failures:
        return failures, r1, {}
    exf, variables = _maybe_extract(case, r1)
    failures.extend(exf)
    if failures:
        return failures, r1, variables

    adapter_result = r1
    if needs_second:
        run2, err2 = _build_substituted_adapter_case(case, variables, first_hop=False)
        if err2:
            return [err2], r1, variables
        r2 = adapter.run_case(run2)
        failures = _evaluate_single_attempt(case, r2)
        adapter_result = r2
        if failures:
            return failures, adapter_result, variables
        # Variables for {{...}} substitution are taken from the first hop only (Increment 42).

    return failures, adapter_result, variables


def _step_result_reason(failures: list[str]) -> str:
    if not failures:
        return ""
    if len(failures) == 1:
        return failures[0]
    return " | ".join(failures)


def _execute_steps_case(
    case, adapter
) -> tuple[list[str], AdapterResult | None, dict[str, object], str, str, list[dict]]:
    """Run ordered ``steps`` with shared variables; prefix failures with ``step failed`` JSON.

    Returns ``step_results`` (Increment 45): one entry per executed step, PASS or FAIL with url
    (after substitution when available) and ``latency_ms``.
    """
    variables: dict[str, object] = {}
    last_result: AdapterResult | None = None
    last_method = str(case.get("method", "POST")).upper()
    last_url = str(case.get("url", ""))
    step_results: list[dict] = []
    for st in case["steps"]:
        step_name = st["step_name"]
        shell = _case_request_shell_for_step(case, st)
        run_dict, err = _build_substituted_adapter_case_direct(shell, variables)
        if err:
            step_results.append(
                {
                    "step": step_name,
                    "status": "FAIL",
                    "url": str(shell.get("url", "")).strip(),
                    "latency_ms": 0,
                    "reason": err,
                }
            )
            return (
                _prefix_failures_for_step(step_name, [err]),
                last_result,
                variables,
                last_method,
                last_url,
                step_results,
            )
        last_result = adapter.run_case(run_dict)
        last_method = str(run_dict.get("method", last_method)).upper()
        last_url = str(run_dict.get("url", last_url))
        ev_case = {"assertions": st["assertions"]}
        failures = _evaluate_single_attempt(ev_case, last_result)
        if failures:
            reason = _step_result_reason(failures)
            step_results.append(
                {
                    "step": step_name,
                    "status": "FAIL",
                    "url": str(run_dict.get("url", "")),
                    "latency_ms": int(last_result.latency_ms),
                    "reason": reason,
                }
            )
            return (
                _prefix_failures_for_step(step_name, failures),
                last_result,
                variables,
                last_method,
                last_url,
                step_results,
            )
        exf, new_vars = _maybe_extract(ev_case, last_result)
        variables.update(new_vars)
        if exf:
            reason = _step_result_reason(exf)
            step_results.append(
                {
                    "step": step_name,
                    "status": "FAIL",
                    "url": str(run_dict.get("url", "")),
                    "latency_ms": int(last_result.latency_ms),
                    "reason": reason,
                }
            )
            return (
                _prefix_failures_for_step(step_name, exf),
                last_result,
                variables,
                last_method,
                last_url,
                step_results,
            )
        step_results.append(
            {
                "step": step_name,
                "status": "PASS",
                "url": str(run_dict.get("url", "")),
                "latency_ms": int(last_result.latency_ms),
            }
        )
    return [], last_result, variables, last_method, last_url, step_results


def execute_suite(suite, adapter, fail_fast=False):
    started = time.perf_counter()
    case_results = []
    passed = 0
    failed = 0
    for case in suite["cases"]:
        if case.get("lane") == "stability":
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
                "status_code": last_adapter_result.status_code if last_adapter_result else None,
                "latency_ms": last_adapter_result.latency_ms if last_adapter_result else 0,
                "output_preview": (last_adapter_result.output_text or "")[:600]
                if last_adapter_result
                else "",
                "output_full": _cap_output_full(last_adapter_result.output_text or "")
                if last_adapter_result
                else "",
                "response_headers": dict(last_adapter_result.response_headers)
                if last_adapter_result
                else {},
                "method": case["method"],
                "url": case["url"],
            }
            if isinstance(case.get("assertions"), dict) and case["assertions"].get("extract") is not None:
                row["variables"] = variables
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
                "status_code": last_adapter_result.status_code if last_adapter_result else None,
                "latency_ms": last_adapter_result.latency_ms if last_adapter_result else 0,
                "output_preview": (last_adapter_result.output_text or "")[:600]
                if last_adapter_result
                else "",
                "output_full": _cap_output_full(last_adapter_result.output_text or "")
                if last_adapter_result
                else "",
                "response_headers": dict(last_adapter_result.response_headers)
                if last_adapter_result
                else {},
                "method": case["method"],
                "url": case["url"],
            }
            if isinstance(case.get("assertions"), dict) and case["assertions"].get("extract") is not None:
                row["variables"] = variables
            case_results.append(row)
        else:
            if case.get("steps"):
                failures, adapter_result, variables, row_method, row_url, step_results = _execute_steps_case(
                    case, adapter
                )
            else:
                failures, adapter_result, variables = _execute_correctness_case(case, adapter)
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
                "status_code": adapter_result.status_code,
                "latency_ms": adapter_result.latency_ms,
                "output_preview": (adapter_result.output_text or "")[:600],
                "output_full": _cap_output_full(adapter_result.output_text or ""),
                "response_headers": dict(adapter_result.response_headers),
                "method": row_method,
                "url": row_url,
            }
            if case.get("steps"):
                row["variables"] = variables
                row["step_results"] = step_results
            elif isinstance(case.get("assertions"), dict) and case["assertions"].get("extract") is not None:
                row["variables"] = variables
            case_results.append(row)
        if fail_fast and not case_results[-1].get("ok"):
            break
    elapsed_seconds = round(time.perf_counter() - started, 3)
    return {
        "suite_name": suite["suite_name"],
        "target_name": suite["target_name"],
        "executed_cases": len(case_results),
        "passed_cases": passed,
        "failed_cases": failed,
        "ok": failed == 0,
        "elapsed_seconds": elapsed_seconds,
        "ran_at_utc": datetime.now(timezone.utc).isoformat(),
        "cases": case_results,
    }


def write_result_artifacts(result, output_dir, file_stem):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    json_path = output_path / f"{file_stem}.json"
    md_path = output_path / f"{file_stem}.md"

    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# System Eval Report: {result.get('suite_name')}",
        "",
        f"- Target: `{result.get('target_name')}`",
        f"- Status: `{'PASS' if result.get('ok') else 'FAIL'}`",
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
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(md_path)}
