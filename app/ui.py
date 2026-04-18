import base64
import html
import json
import os
import shlex
import platform
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import playground

from app import system_eval_operator as tool1_operator
from app import tool1_run_log
from core import system_eval


MEMORY_FILE = Path("memory/extracted_memory.json")
OPEN_DEVSHELL = PROJECT_ROOT / "Open-DevShell.cmd"
LAUNCH_AGENT_UI = PROJECT_ROOT / "Launch-Agent-UI.cmd"
QUICK_PROMPTS = [
    "What should I do next?",
    "How do I prefer to learn?",
    "show state",
]

# Operator-facing labels (top bar + sidebar backup) → internal router keys (unchanged behavior).
_SURFACE_NAV: tuple[tuple[str, str], ...] = (
    ("Agent", "Agent"),
    ("API", "Tool 1"),
    ("Prompt", "Tool 2"),
    ("Regression", "Tool 3"),
    ("Terminal", "Terminal"),
)


def load_memory_items(limit=8):
    if not MEMORY_FILE.exists():
        return []

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    items = data.get("memory_items", [])
    if not isinstance(items, list):
        return []

    return items[:limit]


def _fetch_mode_effective() -> str:
    """Display-only: same effective mode as ``fetch_page`` (browser only when set exactly)."""
    raw = (os.environ.get("FETCH_MODE") or "").strip().lower()
    return "browser" if raw == "browser" else "http"


def init_session_state():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "status" not in st.session_state:
        st.session_state.status = "Ready"

    # Ensure playground starts from persisted state.
    if not playground.current_state:
        playground.current_state.update(playground.load_state())

    st.session_state.setdefault(
        "tool1_suite_path", "system_tests/suites/tool1_local_starter_suite.json"
    )
    st.session_state.setdefault("tool1_output_dir", "logs/system_eval")
    st.session_state.setdefault("tool1_file_stem", "")
    st.session_state.setdefault("tool1_fail_fast", False)
    st.session_state.setdefault("tool1_timeout", 20)
    st.session_state.setdefault("ui_surface", "Agent")


def apply_theme():
    st.markdown(
        """
        <style>
        .status-pill {
            display: inline-block;
            padding: 0.25rem 0.6rem;
            border-radius: 999px;
            font-size: 0.8rem;
            border: 1px solid #2e3b5c;
            background: #111a2e;
            color: #b8d2ff;
            margin-bottom: 0.8rem;
        }
        .section-title {
            margin-top: 0.4rem;
            margin-bottom: 0.3rem;
            font-weight: 600;
            color: #c9d8f7;
            font-size: 0.95rem;
            letter-spacing: 0.01em;
        }
        .assistant-card {
            background: rgba(26, 34, 56, 0.55);
            border: 1px solid rgba(105, 135, 206, 0.25);
            border-radius: 12px;
            padding: 0.8rem 0.9rem;
            margin-bottom: 0.4rem;
        }
        .cockpit-slot {
            border: 1px solid rgba(105, 135, 206, 0.2);
            border-radius: 10px;
            padding: 0.6rem 0.75rem;
            margin: 0.35rem 0 0.75rem 0;
            background: rgba(18, 26, 44, 0.35);
        }
        .sidebar-status-line {
            font-size: 0.72rem;
            opacity: 0.68;
            line-height: 1.3;
            margin: 0.1rem 0 0.45rem 0;
            word-break: break-word;
        }
        .top-surface-bar {
            margin: 0 0 0.45rem 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def push_assistant_message(content):
    st.session_state.messages.append({"role": "assistant", "content": content})


def run_query(user_input):
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.session_state.status = "Thinking"
    response = playground.handle_user_input(user_input)
    st.session_state.status = "Ready"
    push_assistant_message(response)


def render_formatted_assistant_message(content):
    blocks = [b.strip() for b in content.split("\n\n") if b.strip()]
    if len(blocks) < 2:
        st.markdown(content)
        return

    st.markdown('<div class="assistant-card">', unsafe_allow_html=True)
    for block in blocks:
        if block.startswith("Answer:"):
            st.markdown('<div class="section-title">Answer</div>', unsafe_allow_html=True)
            st.markdown(block.replace("Answer:", "", 1).strip() or "-")
        elif block.startswith("Current state:"):
            st.markdown('<div class="section-title">Current State</div>', unsafe_allow_html=True)
            state_text = block.replace("Current state:", "", 1).strip()
            st.markdown(state_text.replace("\n", "  \n"))
        elif block.startswith("Next step:"):
            st.markdown('<div class="section-title">Next Step</div>', unsafe_allow_html=True)
            st.markdown(block.replace("Next step:", "", 1).strip() or "-")
        else:
            st.markdown(block)
    st.markdown("</div>", unsafe_allow_html=True)


def _go_surface(internal: str) -> None:
    if st.session_state.get("ui_surface") != internal:
        st.session_state.ui_surface = internal
        st.rerun()


def render_top_surface_bar():
    """Compact primary surface switch (main column). Maps labels → existing ui_surface keys."""
    current = st.session_state.get("ui_surface", "Agent")
    st.markdown('<div class="top-surface-bar">', unsafe_allow_html=True)
    cols = st.columns(5, gap="small")
    for i, (label, internal) in enumerate(_SURFACE_NAV):
        with cols[i]:
            selected = current == internal
            if st.button(
                label,
                key=f"top_bar_{internal}",
                use_container_width=True,
                type="primary" if selected else "secondary",
            ):
                if not selected:
                    _go_surface(internal)
    st.markdown("</div>", unsafe_allow_html=True)


def render_sidebar_rail_and_context():
    """Secondary rail: same surfaces as top bar, compact; status + actions + Advanced."""
    st.caption("Surface · backup")
    s1, s2 = st.sidebar.columns(2)
    for idx, (label, internal) in enumerate(_SURFACE_NAV):
        col = s1 if idx % 2 == 0 else s2
        with col:
            selected = st.session_state.get("ui_surface", "Agent") == internal
            if st.button(
                label,
                key=f"side_nav_{internal}",
                use_container_width=True,
                type="primary" if selected else "secondary",
            ):
                if not selected:
                    _go_surface(internal)

    current_focus = playground.get_current_focus()
    current_stage = playground.get_current_stage()
    f_line = " ".join(str(current_focus or "—").split())
    s_line = " ".join(str(current_stage or "—").split())
    st.sidebar.markdown(
        f'<p class="sidebar-status-line">{html.escape(f_line)} · {html.escape(s_line)}</p>',
        unsafe_allow_html=True,
    )

    q1, q2 = st.sidebar.columns(2)
    if q1.button(
        "Show",
        use_container_width=True,
        key="sidebar_show_state",
        help="show state",
        type="secondary",
    ):
        push_assistant_message(playground.handle_user_input("show state"))
    if q2.button(
        "Reset",
        use_container_width=True,
        key="sidebar_reset_state",
        help="reset state",
        type="secondary",
    ):
        push_assistant_message(playground.handle_user_input("reset state"))

    with st.sidebar.expander("Advanced", expanded=False):
        eff = _fetch_mode_effective()
        raw = os.environ.get("FETCH_MODE")

        st.markdown("**Adjust state**")
        with st.form("state_form"):
            new_focus = st.text_input("Focus", value=current_focus)
            new_stage = st.text_input("Stage", value=current_stage)
            submitted = st.form_submit_button("Apply")
            if submitted:
                if new_focus.strip() and new_focus.strip() != current_focus:
                    playground.handle_user_input(f"set focus: {new_focus.strip()}")
                if new_stage.strip() and new_stage.strip() != current_stage:
                    playground.handle_user_input(f"set stage: {new_stage.strip()}")
                push_assistant_message(playground.handle_user_input("show state"))

        st.markdown("**Fetch**")
        if raw is None or not str(raw).strip():
            st.text(f"effective={eff}")
        else:
            st.text(f"effective={eff}  env={str(raw).strip()}")
        if eff == "browser" and os.environ.get("FETCH_BROWSER_TIMEOUT_SECONDS"):
            st.text(f"FETCH_BROWSER_TIMEOUT_SECONDS={os.environ.get('FETCH_BROWSER_TIMEOUT_SECONDS')}")

        st.markdown("**Memory**")
        mem_items = load_memory_items()
        if mem_items:
            for item in mem_items:
                category = item.get("category", "unknown")
                value = item.get("value", "")
                st.caption(f"({category}) {value}")
        else:
            st.caption("— no rows —")


def _tool1_attempts_summary(case_row):
    if case_row.get("attempts_total"):
        return f"{case_row.get('attempts_passed')}/{case_row.get('attempts_total')}"
    return "1"


def _tool1_case_failure_lines(case: dict) -> list[str]:
    raw = case.get("failures")
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if raw is None or raw == "":
        return []
    return [str(raw)]


def _tool1_case_outcome_table_note(case: dict) -> str:
    """Short table cell: PASS / FAIL + coarse cause (uses only bundle fields)."""
    if case.get("ok"):
        return "PASS"
    sc = case.get("status_code")
    if sc is None:
        return "FAIL · transport / no HTTP status"
    return "FAIL · assertions / expectations"


def _tool1_short_failure_reason(case: dict) -> str:
    """Single-line, customer-facing hint; first engine message truncated, or a generic line."""
    lines = _tool1_case_failure_lines(case)
    if lines:
        first = lines[0].strip()
        if len(first) > 160:
            return first[:157] + "…"
        return first
    if case.get("status_code") is None:
        return "No HTTP response was received (connection or client error)."
    return "The HTTP response did not meet the configured checks."


def _tool1_render_customer_run_summary(result: dict, overall_ok: bool) -> None:
    """Compact, shareable summary above technical tables."""
    cases = result.get("cases") or []
    total = int(result.get("executed_cases") if result.get("executed_cases") is not None else len(cases))
    passed = int(result.get("passed_cases") if result.get("passed_cases") is not None else 0)
    failed = int(result.get("failed_cases") if result.get("failed_cases") is not None else 0)
    failed_names = [str(c.get("name") or f"Case {i + 1}") for i, c in enumerate(cases) if not c.get("ok")]

    if overall_ok:
        st.success("Overall: PASS — All checks passed. Every case in this run succeeded.")
    else:
        st.error("Overall: FAIL — Some checks failed. Review failed cases below for full detail.")

    st.markdown(
        f"- **Cases in this run:** {total}\n"
        f"- **Passed:** {passed}\n"
        f"- **Failed:** {failed}"
    )
    if failed_names:
        st.markdown("**Failed case names:**")
        for n in failed_names:
            st.markdown(f"- {html.escape(n)}")
    elif not overall_ok:
        st.caption("This run is marked failed, but no individual case names were attached in the result bundle.")


def _tool1_render_case_at_a_glance(case: dict, *, index: int) -> None:
    """Scannable one-screen case header (name, method, URL, pass/fail, short reason)."""
    nm = case.get("name") or f"case-{index + 1}"
    ok = bool(case.get("ok"))
    method = str(case.get("method") or "—")
    url = str(case.get("url") or "—")
    status_word = "Passed" if ok else "Failed"
    st.markdown(f"#### {html.escape(nm)}")
    st.markdown(f"**Result:** {status_word} · **Method:** `{html.escape(method)}` · **URL:** `{html.escape(url)}`")
    if not ok:
        st.caption("Summary (first issue):")
        st.text(_tool1_short_failure_reason(case))


def _tool1_render_case_outcome_banner(case: dict) -> None:
    """Per-case PASS/FAIL and whether failure looks like transport vs assertions."""
    if case.get("ok"):
        st.success("Outcome: PASS — assertions satisfied for this case.")
        return
    lines = _tool1_case_failure_lines(case)
    sc = case.get("status_code")
    if sc is None:
        st.error(
            "Outcome: FAIL — **likely transport or runtime** (no HTTP status on this case). "
            "See failure messages below."
        )
    else:
        st.warning(
            "Outcome: FAIL — **likely assertions / expectations** (HTTP response was received). "
            "See failure messages below."
        )
    if lines:
        with st.expander("Failure messages", expanded=True):
            for line in lines:
                st.text(line)
    else:
        st.caption("No failure messages were attached to this case in the result bundle.")


def _tool1_parse_custom_headers_json(raw: str) -> tuple[dict[str, str], str | None]:
    """
    Parse optional headers textarea: empty → {}.
    Returns (headers_str_str, error_message_or_None).
    """
    s = (raw or "").strip()
    if not s:
        return {}, None
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError as exc:
        return {}, f"Invalid JSON in headers: {exc}"
    if not isinstance(parsed, dict):
        return {}, "Headers must be a JSON object (e.g. {\"Accept\": \"application/json\"})."
    out: dict[str, str] = {}
    for k, v in parsed.items():
        key = str(k).strip()
        if not key:
            return {}, "Header names must be non-empty strings."
        if v is None:
            out[key] = ""
        elif isinstance(v, (dict, list)):
            return {}, f"Header value for {key!r} must be a string or number, not an object/array."
        else:
            out[key] = str(v)
    return out, None


def _tool1_parse_query_params_json(raw: str) -> tuple[dict[str, str], str | None]:
    """
    Parse optional query-params textarea: empty → {}.
    Returns (param_name_str_value_str, error_message_or_None).
    """
    s = (raw or "").strip()
    if not s:
        return {}, None
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError as exc:
        return {}, f"Invalid JSON in query params: {exc}"
    if not isinstance(parsed, dict):
        return {}, "Query params must be a JSON object (e.g. {\"userId\": 1})."
    out: dict[str, str] = {}
    for k, v in parsed.items():
        key = str(k).strip()
        if not key:
            return {}, "Query param names must be non-empty strings."
        if v is None:
            out[key] = ""
        elif isinstance(v, (dict, list)):
            return {}, f"Query param value for {key!r} must be a primitive, not an object/array."
        else:
            out[key] = str(v)
    return out, None


def _tool1_merge_custom_headers_with_auth(
    custom_headers: dict[str, str],
    *,
    auth_mode: str,
    bearer_token: str,
    basic_username: str,
    basic_password: str,
    api_key_header_name: str = "",
    api_key_value: str = "",
) -> tuple[dict[str, str], str | None]:
    """
    Start from a copy of JSON ``custom_headers``. Active auth helpers set one or more
    headers after that; **helper values win** if the same header name already exists
    in custom JSON (same merge rule for Bearer, Basic, and API key).

    - ``bearer`` / ``basic``: set ``Authorization`` (replaces any from custom JSON).
    - ``api_key``: set ``<stripped header name>: <stripped value>`` (replaces same key from JSON).
    - ``none``: leave headers unchanged.
    """
    merged = dict(custom_headers)
    mode = (auth_mode or "none").strip().lower()
    if mode in ("", "none"):
        return merged, None
    if mode == "bearer":
        token = (bearer_token or "").strip()
        if not token:
            return merged, "Bearer auth requires a non-empty token."
        merged["Authorization"] = f"Bearer {token}"
        return merged, None
    if mode == "basic":
        user_raw = basic_username or ""
        pass_raw = basic_password or ""
        if not str(user_raw).strip():
            return merged, "Basic auth requires a username."
        b64 = base64.b64encode(f"{user_raw}:{pass_raw}".encode("utf-8")).decode("ascii")
        merged["Authorization"] = f"Basic {b64}"
        return merged, None
    if mode == "api_key":
        name = (api_key_header_name or "").strip()
        if not name:
            return merged, "API key mode requires a non-empty header name."
        key_val = (api_key_value or "").strip()
        if not key_val:
            return merged, "API key mode requires a non-empty API key value."
        merged[name] = key_val
        return merged, None
    return merged, f"Unknown auth mode {auth_mode!r}."


def _tool1_merge_url_with_query_params(base_url: str, extra: dict[str, str]) -> str:
    """Merge JSON-derived query params into base_url; existing ?query keys are overridden by ``extra``."""
    if not extra:
        return base_url.strip()
    parts = urlsplit(base_url.strip())
    merged: dict[str, str] = dict(parse_qsl(parts.query, keep_blank_values=True))
    merged.update(extra)
    new_query = urlencode(list(merged.items()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


_TOOL1_AUTH_LABEL_TO_MODE = {
    "None": "none",
    "Bearer token": "bearer",
    "Basic auth": "basic",
    "API key": "api_key",
}

_TOOL1_SINGLE_SNAPSHOT_KEYS = (
    "tool1_single_method",
    "tool1_single_url",
    "tool1_single_query_params",
    "tool1_single_headers",
    "tool1_single_body",
    "tool1_single_auth_mode",
    "tool1_single_bearer_token",
    "tool1_single_basic_user",
    "tool1_single_basic_password",
    "tool1_single_api_key_header",
    "tool1_single_api_key_value",
    "tool1_timeout",
    "tool1_output_dir",
)


def _tool1_capture_single_request_snapshot() -> dict:
    """Session-only snapshot of single-request widget keys for rerun."""
    snap: dict = {}
    for k in _TOOL1_SINGLE_SNAPSHOT_KEYS:
        if k in st.session_state:
            snap[k] = st.session_state[k]
    return snap


def _tool1_apply_single_request_snapshot(snap: dict) -> None:
    for k, v in snap.items():
        st.session_state[k] = v


def _tool1_run_single_request_from_snapshot(snap: dict):
    """Execute single request using a session snapshot (same path as Send Request)."""
    return _tool1_execute_single_request(**_tool1_execute_kwargs_from_snapshot(snap))


def _tool1_execute_kwargs_from_snapshot(snap: dict) -> dict:
    """Build kwargs for ``_tool1_execute_single_request`` from a snapshot dict."""
    auth_label = str(snap.get("tool1_single_auth_mode") or "None")
    auth_mode = _TOOL1_AUTH_LABEL_TO_MODE.get(auth_label, "none")
    method = str(snap.get("tool1_single_method") or "GET")
    body_text = ""
    if method.upper() in ("POST", "PUT", "PATCH"):
        body_text = str(snap.get("tool1_single_body") or "")
    return {
        "url": str(snap.get("tool1_single_url") or ""),
        "method": method,
        "body_text": body_text,
        "headers_text": str(snap.get("tool1_single_headers") or ""),
        "query_params_text": str(snap.get("tool1_single_query_params") or ""),
        "timeout_sec": int(snap.get("tool1_timeout", 20)),
        "output_dir_rel": str(snap.get("tool1_output_dir") or "logs/system_eval"),
        "auth_mode": auth_mode,
        "bearer_token": str(snap.get("tool1_single_bearer_token") or ""),
        "basic_username": str(snap.get("tool1_single_basic_user") or ""),
        "basic_password": str(snap.get("tool1_single_basic_password") or ""),
        "api_key_header_name": str(snap.get("tool1_single_api_key_header") or ""),
        "api_key_value": str(snap.get("tool1_single_api_key_value") or ""),
    }


def _tool1_prepare_single_request(
    *,
    url: str,
    method: str,
    body_text: str,
    headers_text: str,
    query_params_text: str,
    auth_mode: str = "none",
    bearer_token: str = "",
    basic_username: str = "",
    basic_password: str = "",
    api_key_header_name: str = "",
    api_key_value: str = "",
) -> tuple[dict | None, str | None]:
    """
    Validate and merge URL/headers/body for a single-request case (no I/O).
    Returns ``(plan_dict, None)`` or ``(None, error_message)``.
    ``plan_dict`` keys: ``method_u``, ``final_url``, ``headers``, ``payload``, ``suite_dict``.
    """
    url = (url or "").strip()
    if not url:
        return None, "URL is required."
    query_params, q_err = _tool1_parse_query_params_json(query_params_text)
    if q_err:
        return None, q_err
    final_url = _tool1_merge_url_with_query_params(url, query_params) if query_params else url
    method_u = (method or "GET").upper()
    headers, hdr_err = _tool1_parse_custom_headers_json(headers_text)
    if hdr_err:
        return None, hdr_err
    headers, auth_err = _tool1_merge_custom_headers_with_auth(
        headers,
        auth_mode=auth_mode,
        bearer_token=bearer_token,
        basic_username=basic_username,
        basic_password=basic_password,
        api_key_header_name=api_key_header_name,
        api_key_value=api_key_value,
    )
    if auth_err:
        return None, auth_err
    payload: dict = {}
    if method_u in ("POST", "PUT", "PATCH"):
        raw = (body_text or "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                return None, f"Invalid JSON body: {exc}"
            if not isinstance(parsed, dict):
                return None, "JSON body must be a JSON object (e.g. {\"id\": 1})."
            payload = parsed
    suite_dict = {
        "suite_name": "single-request",
        "target_name": "operator",
        "cases": [
            {
                "name": "single request",
                "method": method_u,
                "url": final_url,
                "headers": headers,
                "payload": payload,
                "assertions": {},
            }
        ],
    }
    return {
        "method_u": method_u,
        "final_url": final_url,
        "headers": headers,
        "payload": payload,
        "suite_dict": suite_dict,
    }, None


def _tool1_store_run_log_error(message: str | None) -> None:
    """Non-fatal: ignore if session state is unavailable (e.g. non-Streamlit import)."""
    try:
        st.session_state["tool1_run_log_error"] = message
    except Exception:
        pass


def _tool1_single_input_snapshot_for_log(
    *,
    url: str,
    method: str,
    body_text: str,
    headers_text: str,
    query_params_text: str,
    auth_mode: str,
    bearer_token: str,
    basic_username: str,
    basic_password: str,
    api_key_header_name: str,
    api_key_value: str,
) -> dict:
    """Raw operator inputs for log evidence when a run fails before a full ``prep`` exists."""
    return {
        "url": url,
        "method": method,
        "headers_json_raw": headers_text,
        "query_params_json_raw": query_params_text,
        "body_json_raw": body_text,
        "auth_mode_internal": auth_mode,
        "bearer_token": bearer_token,
        "basic_username": basic_username,
        "basic_password": basic_password,
        "api_key_header_name": api_key_header_name,
        "api_key_value": api_key_value,
    }


def _tool1_format_single_request_plain(prep: dict) -> str:
    """Human-readable, copy-friendly description of the prepared single request."""
    lines = [
        f"Method: {prep['method_u']}",
        f"Final URL: {prep['final_url']}",
        "",
        "Headers sent (merged, including auth helper):",
    ]
    hdrs = prep.get("headers") or {}
    if not hdrs:
        lines.append("  (none)")
    else:
        for name in sorted(hdrs.keys()):
            lines.append(f"  {name}: {hdrs[name]}")
    payload = prep.get("payload") or {}
    if prep["method_u"] in ("POST", "PUT", "PATCH"):
        lines.append("")
        if payload:
            lines.append("JSON body:")
            lines.append(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            lines.append("JSON body: (empty — default {} sent for this method)")
    return "\n".join(lines)


def _tool1_format_single_request_curl(prep: dict) -> str:
    """Approximate curl command; not shell-perfect (operator convenience only)."""
    method_u = prep["method_u"]
    final_url = prep["final_url"]
    hdrs = dict(prep.get("headers") or {})
    payload = prep.get("payload") or {}
    parts = ["curl", "-sS", "-X", method_u, shlex.quote(final_url)]
    for name in sorted(hdrs.keys()):
        hv = f"{name}: {hdrs[name]}"
        parts.append("-H")
        parts.append(shlex.quote(hv))
    if method_u in ("POST", "PUT", "PATCH") and payload:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if not any(str(k).lower() == "content-type" for k in hdrs):
            parts.extend(["-H", shlex.quote("Content-Type: application/json")])
        parts.extend(["--data-binary", shlex.quote(body)])
    return " ".join(parts)


def _tool1_execute_single_request(
    *,
    url: str,
    method: str,
    body_text: str,
    headers_text: str,
    query_params_text: str,
    timeout_sec: int,
    output_dir_rel: str,
    auth_mode: str = "none",
    bearer_token: str = "",
    basic_username: str = "",
    basic_password: str = "",
    api_key_header_name: str = "",
    api_key_value: str = "",
):
    """
    Build a one-case suite, run through system_eval (validate → HttpTargetAdapter → execute_suite),
    write artifacts like suite runs. Returns (bundle_dict, error_message).
    """
    input_snap = _tool1_single_input_snapshot_for_log(
        url=url,
        method=method,
        body_text=body_text,
        headers_text=headers_text,
        query_params_text=query_params_text,
        auth_mode=auth_mode,
        bearer_token=bearer_token,
        basic_username=basic_username,
        basic_password=basic_password,
        api_key_header_name=api_key_header_name,
        api_key_value=api_key_value,
    )
    prep, p_err = _tool1_prepare_single_request(
        url=url,
        method=method,
        body_text=body_text,
        headers_text=headers_text,
        query_params_text=query_params_text,
        auth_mode=auth_mode,
        bearer_token=bearer_token,
        basic_username=basic_username,
        basic_password=basic_password,
        api_key_header_name=api_key_header_name,
        api_key_value=api_key_value,
    )
    if p_err:
        le = tool1_run_log.try_log_single_request_run(
            prep=None,
            result=None,
            artifact_paths={},
            error=p_err,
            timeout_seconds=timeout_sec,
            output_dir_rel=output_dir_rel,
            auth_mode_internal=auth_mode,
            query_params_text=query_params_text,
            input_snapshot=input_snap,
        )
        _tool1_store_run_log_error(le)
        return None, p_err
    st.session_state["tool1_last_single_request_plain"] = _tool1_format_single_request_plain(prep)
    st.session_state["tool1_last_single_request_curl"] = _tool1_format_single_request_curl(prep)
    suite_dict = prep["suite_dict"]
    try:
        suite = system_eval.validate_suite(suite_dict)
    except ValueError as exc:
        ve = str(exc)
        le = tool1_run_log.try_log_single_request_run(
            prep=prep,
            result=None,
            artifact_paths={},
            error=ve,
            timeout_seconds=timeout_sec,
            output_dir_rel=output_dir_rel,
            auth_mode_internal=auth_mode,
            query_params_text=query_params_text,
            input_snapshot=input_snap,
        )
        _tool1_store_run_log_error(le)
        return None, ve
    adapter = system_eval.HttpTargetAdapter(default_timeout_seconds=max(1, int(timeout_sec)))
    result = system_eval.execute_suite(suite, adapter=adapter, fail_fast=False)
    out_path = Path((output_dir_rel or "logs/system_eval").strip())
    if not out_path.is_absolute():
        out_path = PROJECT_ROOT / out_path
    out_path.mkdir(parents=True, exist_ok=True)
    paths = system_eval.write_result_artifacts(result, str(out_path), file_stem="single_request")
    json_path = Path(paths["json_path"])
    md_path = Path(paths["markdown_path"])
    json_text = json_path.read_text(encoding="utf-8") if json_path.is_file() else ""
    md_text = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    max_json = 14_000
    if len(json_text) > max_json:
        json_preview = json_text[:max_json] + "\n\n... (truncated for preview)"
    else:
        json_preview = json_text
    max_md = 20_000
    if len(md_text) > max_md:
        markdown_preview = md_text[:max_md] + "\n\n... (truncated for preview)"
    else:
        markdown_preview = md_text
    bundle = {
        "ok": bool(result.get("ok")),
        "result": result,
        "artifact_paths": paths,
        "json_preview": json_preview,
        "markdown_preview": markdown_preview,
        "error": None,
    }
    le = tool1_run_log.try_log_single_request_run(
        prep=prep,
        result=result,
        artifact_paths=paths,
        error=None,
        timeout_seconds=timeout_sec,
        output_dir_rel=output_dir_rel,
        auth_mode_internal=auth_mode,
        query_params_text=query_params_text,
        input_snapshot=input_snap,
    )
    bundle["run_log_error"] = le
    return bundle, None


def _tool1_render_results(bundle: dict) -> None:
    """Shared Tool 1 results view (suite run or single request)."""
    if bundle.get("error"):
        st.error(bundle["error"])
        return

    log_err = bundle.get("run_log_error")
    if log_err:
        st.warning(f"Run log could not be written (run still shown): {log_err}")
    st.caption(f"Append-only Tool 1 run log: `{tool1_run_log.tool1_run_log_path()}`")

    result = bundle.get("result") or {}
    overall_ok = bundle.get("ok", False)

    st.subheader("Run summary")
    _tool1_render_customer_run_summary(result, overall_ok)
    st.caption(
        f"Suite: `{html.escape(str(result.get('suite_name') or ''))}` · "
        f"Target: `{html.escape(str(result.get('target_name') or ''))}`"
    )

    st.subheader("Detailed results")
    rows = []
    cases = result.get("cases") or []
    for c in cases:
        rows.append(
            {
                "case": c.get("name"),
                "outcome": _tool1_case_outcome_table_note(c),
                "ok": c.get("ok"),
                "lane": c.get("lane") or "—",
                "attempts": _tool1_attempts_summary(c),
                "status": c.get("status_code"),
                "latency_ms": c.get("latency_ms"),
            }
        )
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)

    if cases:
        st.caption(
            "The table is for quick scanning. Under each case: a short **summary**, then technical "
            "**outcome** (transport vs checks), **response** expanders, and **failure messages** when needed."
        )
        for i, c in enumerate(cases):
            nm = c.get("name") or f"case-{i}"
            _tool1_render_case_at_a_glance(c, index=i)
            _tool1_render_case_outcome_banner(c)
            sc = c.get("status_code")
            lat = c.get("latency_ms")
            st.caption(f"HTTP status: **{sc}** · latency: **{lat}** ms")
            _tool1_response_expanders(c, label_suffix=f"{i}: {nm}")
            att_list = c.get("attempts")
            if isinstance(att_list, list) and len(att_list) > 1:
                st.caption("Multi-attempt lane — detail per attempt:")
                for j, att in enumerate(att_list):
                    ax = att.get("attempt", j + 1)
                    st.markdown(f"*Attempt {ax}*")
                    if not att.get("ok"):
                        afl = att.get("failures") if isinstance(att.get("failures"), list) else []
                        afl = [str(x) for x in afl if str(x).strip()]
                        if afl:
                            with st.expander(f"Attempt {ax} — failure messages", expanded=False):
                                for line in afl:
                                    st.text(line)
                    _tool1_response_expanders(att, label_suffix=f"{i}: {nm} · attempt {ax}")
            if i < len(cases) - 1:
                st.divider()

    st.subheader("Artifacts")
    paths = bundle.get("artifact_paths") or {}
    st.code(paths.get("json_path", ""), language="text")
    st.code(paths.get("markdown_path", ""), language="text")

    with st.expander("Markdown preview", expanded=False):
        st.markdown(bundle.get("markdown_preview") or "_empty_")

    with st.expander("JSON preview", expanded=False):
        st.code(bundle.get("json_preview") or "", language="json")


def _tool1_render_response_headers(headers: dict) -> None:
    """Plain key: value lines for operator inspection."""
    if not headers:
        st.caption("No headers captured for this snapshot.")
        return
    for name in sorted(headers.keys()):
        st.text(f"{name}: {headers[name]}")


def _tool1_try_pretty_json_body(text: str | None) -> tuple[str, bool]:
    """
    If stripped text is valid JSON, return (pretty_printed, True).
    Otherwise return (original text, False). Empty/whitespace -> ('— empty —', False).
    """
    raw = "" if text is None else str(text)
    if not raw.strip():
        return "— empty —", False
    try:
        obj = json.loads(raw.strip())
    except (json.JSONDecodeError, TypeError, ValueError):
        return raw, False
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False), True
    except (TypeError, ValueError):
        return raw, False


def _tool1_response_expanders(row: dict, *, label_suffix: str) -> None:
    """Response Headers + Response body expanders for one case or attempt row."""
    raw = row.get("response_headers")
    hdrs = raw if isinstance(raw, dict) else {}
    # Label must be unique per widget (Streamlit expander has no ``key=`` on this version).
    with st.expander(f"Response Headers · {label_suffix}", expanded=False):
        _tool1_render_response_headers(hdrs)
    preview = row.get("output_preview")
    if preview is None:
        preview = ""
    else:
        preview = str(preview)
    full_raw = row.get("output_full")
    full = "" if full_raw is None else str(full_raw)
    with st.expander(f"Response body · {label_suffix}", expanded=False):
        st.caption("Preview (up to 600 characters).")
        pv_disp, _pv_json = _tool1_try_pretty_json_body(preview)
        st.code(pv_disp, language=None)
        st.markdown("**Full response body**")
        if full.endswith("...[truncated]"):
            st.caption("Stored body hit the ~50 KB cap; remainder is not kept in the artifact.")
        else:
            st.caption("Stored full body for this case or attempt (up to ~50 KB).")
        full_disp, _full_json = _tool1_try_pretty_json_body(full)
        st.code(full_disp, language=None)


def render_tool1_panel():
    st.subheader("API — System eval (HTTP)")
    with st.expander("What this tool is", expanded=False):
        st.markdown(
            "Run **HTTP system-eval suites** from JSON — same engine as "
            "`python tools/system_eval_runner.py` (suite → adapter → JSON/Markdown artifacts). "
            "Does not use the Agent chat path."
        )
        st.info(
            "**When to use:** smoke an API, reproduce a suite, or capture evidence without "
            "touching `playground.py`. Configure paths, then **Run system eval**."
        )

    st.session_state.setdefault("tool1_single_method", "GET")
    st.session_state.setdefault("tool1_single_url", "")
    st.session_state.setdefault("tool1_single_query_params", "")
    st.session_state.setdefault("tool1_single_headers", "")
    st.session_state.setdefault("tool1_single_body", "")
    st.session_state.setdefault("tool1_single_auth_mode", "None")
    st.session_state.setdefault("tool1_single_bearer_token", "")
    st.session_state.setdefault("tool1_single_basic_user", "")
    st.session_state.setdefault("tool1_single_basic_password", "")
    st.session_state.setdefault("tool1_single_api_key_header", "")
    st.session_state.setdefault("tool1_single_api_key_value", "")

    st.text_input(
        "Output directory for artifacts (suite + single request)",
        key="tool1_output_dir",
    )
    st.markdown("##### Single request (no suite file)")
    st.caption("Same `HttpTargetAdapter` + `execute_suite` path as suite runs; writes `single_request` artifacts.")
    st.number_input("HTTP timeout (seconds)", min_value=1, max_value=300, key="tool1_timeout")
    st.selectbox("Method", ["GET", "POST", "PUT", "PATCH", "DELETE"], key="tool1_single_method")
    st.text_input("URL", key="tool1_single_url", placeholder="https://api.example.com/v1/resource")
    st.text_area(
        "Query params (optional, JSON object)",
        key="tool1_single_query_params",
        height=90,
        placeholder='{"userId": 1, "limit": 10}',
    )
    st.markdown("**Auth helper** (single request only)")
    st.caption(
        "Optional. Custom JSON headers are applied first; the auth helper then sets its header(s) "
        "and **replaces** any same header name from JSON (Bearer/Basic → `Authorization`; "
        "**API key** → the header name you enter). **None** leaves headers unchanged."
    )
    st.selectbox(
        "Auth mode",
        ["None", "Bearer token", "Basic auth", "API key"],
        key="tool1_single_auth_mode",
    )
    if st.session_state.get("tool1_single_auth_mode") == "Bearer token":
        st.text_input("Bearer token", type="password", key="tool1_single_bearer_token")
    elif st.session_state.get("tool1_single_auth_mode") == "Basic auth":
        st.text_input("Basic username", key="tool1_single_basic_user")
        st.text_input("Basic password", type="password", key="tool1_single_basic_password")
    elif st.session_state.get("tool1_single_auth_mode") == "API key":
        st.text_input("API key header name", key="tool1_single_api_key_header", placeholder="x-api-key")
        st.text_input("API key value", type="password", key="tool1_single_api_key_value")
    st.text_area(
        "Headers (optional, JSON object)",
        key="tool1_single_headers",
        height=100,
        placeholder='{"Accept": "application/json"}',
    )
    if st.session_state.get("tool1_single_method") in ("POST", "PUT", "PATCH"):
        st.text_area(
            "JSON body (optional)",
            key="tool1_single_body",
            height=120,
            placeholder='{"key": "value"}',
        )

    if st.button("Send Request", type="secondary", key="tool1_single_send"):
        st.session_state["tool1_last_single_request_snapshot"] = _tool1_capture_single_request_snapshot()
        with st.spinner("Sending…"):
            snap = st.session_state["tool1_last_single_request_snapshot"]
            bundle, err = _tool1_run_single_request_from_snapshot(snap)
        if err:
            st.error(err)
            le = st.session_state.get("tool1_run_log_error")
            if le:
                st.warning(f"Run log could not be written (details still shown above): {le}")
        elif bundle:
            st.session_state.tool1_last_bundle = bundle

    _snap = st.session_state.get("tool1_last_single_request_snapshot")
    if st.button(
        "Run last request again",
        type="secondary",
        key="tool1_single_rerun",
        disabled=not _snap,
        help="Replays the last captured single-request inputs (this session only).",
    ):
        _tool1_apply_single_request_snapshot(_snap)
        with st.spinner("Re-running last request…"):
            bundle, err = _tool1_run_single_request_from_snapshot(_snap)
        if err:
            st.error(err)
            le = st.session_state.get("tool1_run_log_error")
            if le:
                st.warning(f"Run log could not be written (details still shown above): {le}")
        elif bundle:
            st.session_state.tool1_last_bundle = bundle

    if st.session_state.get("tool1_last_single_request_plain"):
        with st.expander("Last single request — copyable summary", expanded=False):
            st.caption("Plain text (merged URL, headers, body as actually sent after validation).")
            st.code(st.session_state.get("tool1_last_single_request_plain") or "", language=None)
            st.caption("Approximate curl (arguments passed through Python shlex.quote; verify before pasting into a shell).")
            st.code(st.session_state.get("tool1_last_single_request_curl") or "", language="bash")

    st.divider()
    st.markdown("##### Suite run (JSON file)")
    st.text_input(
        "Suite JSON path (repo-relative or absolute)",
        key="tool1_suite_path",
    )
    st.text_input("Optional file stem (blank = derive from suite_name)", key="tool1_file_stem")
    st.checkbox("Fail fast (stop at first failing case)", key="tool1_fail_fast")

    if st.button("Run system eval", type="primary", key="tool1_run_button"):
        with st.spinner("Running suite…"):
            bundle = tool1_operator.run_tool1_system_eval_http(
                st.session_state.tool1_suite_path,
                st.session_state.tool1_output_dir,
                st.session_state.tool1_file_stem,
                fail_fast=bool(st.session_state.tool1_fail_fast),
                default_timeout_seconds=int(st.session_state.tool1_timeout),
            )
        st.session_state.tool1_last_bundle = bundle
        le = bundle.get("run_log_error") if isinstance(bundle, dict) else None
        if le:
            st.warning(f"Run log could not be written (suite result still shown): {le}")

    bundle = st.session_state.get("tool1_last_bundle")
    if not bundle:
        st.info("Use **Send Request** for a quick call without a suite file, or configure a suite path and click **Run system eval**.")
        return

    _tool1_render_results(bundle)


def render_tool_placeholder(tool_id: int):
    if tool_id == 2:
        title = "Prompt — planned"
        role = (
            "**Prompt (placeholder).** Reserved for the second operator profile on the "
            "three-tool roadmap (see `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md`). "
            "**Nothing executes here yet** — same router slot as Tool 2."
        )
    else:
        title = "Regression — planned"
        role = (
            "**Regression (placeholder).** Reserved for the third operator profile; "
            "**inert** until wired — same router slot as Tool 3."
        )

    st.subheader(title)
    st.info(role)
    st.caption("Deliberate placeholder — not broken.")
    st.button("Run (disabled)", key=f"tool{tool_id}_run_disabled", disabled=True, use_container_width=True)


def render_terminal_panel():
    st.subheader("Terminal access")
    st.caption(
        "Opens a **real** shell on your machine (no embedded terminal here). "
        "Use for pip, git, `run_regression.py`, long jobs."
    )
    with st.expander("Why this panel exists", expanded=False):
        st.markdown(
            '<div class="cockpit-slot">Jump to a terminal at the repo root — not for running '
            "fetch logic inside Streamlit.</div>",
            unsafe_allow_html=True,
        )
    st.markdown("##### Launchers")
    if platform.system() == "Windows":
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Open dev shell", type="primary", use_container_width=True, help=str(OPEN_DEVSHELL)):
                if OPEN_DEVSHELL.is_file():
                    os.startfile(str(OPEN_DEVSHELL))  # type: ignore[attr-defined]
                else:
                    st.error(f"Missing file: `{OPEN_DEVSHELL}`")
        with c2:
            if st.button("Open Streamlit launcher", use_container_width=True, help=str(LAUNCH_AGENT_UI)):
                if LAUNCH_AGENT_UI.is_file():
                    os.startfile(str(LAUNCH_AGENT_UI))  # type: ignore[attr-defined]
                else:
                    st.error(f"Missing file: `{LAUNCH_AGENT_UI}`")
    else:
        st.info(
            "On this OS, open a terminal manually at the repository root (folder that contains "
            "`Open-DevShell.cmd`)."
        )

    st.markdown("### Copy / paste (any OS)")
    repo = str(PROJECT_ROOT)
    st.code(f'cd /d "{repo}"\r\nOpen-DevShell.cmd', language="bat")
    st.code(f'cd "{repo}"\nstreamlit run app/ui.py', language="bash")

    st.markdown("### Notes")
    st.caption("Dev shell uses `.venv-win` on Windows (see repo README). Keep heavy work in that terminal, not inside Streamlit callbacks.")


def _render_agent_menu_controls():
    """Status, new chat, shortcuts — lives inside popover or expander (not above chat)."""
    st.caption(f"Status: {html.escape(str(st.session_state.status))}")
    if st.button("New chat", use_container_width=True, key="agent_new_chat"):
        st.session_state.messages = []
        st.rerun()
    st.divider()
    qp_col1, qp_col2, qp_col3 = st.columns(3)
    for i, prompt in enumerate(QUICK_PROMPTS):
        col = [qp_col1, qp_col2, qp_col3][i]
        if col.button(prompt, key=f"quick_prompt_{i}", use_container_width=True):
            run_query(prompt)
            st.rerun()


def render_agent_center_minimal():
    """Agent-first: one minimal menu control, then conversation + input (no dashboard chrome)."""
    if hasattr(st, "popover"):
        with st.popover("⋯"):
            _render_agent_menu_controls()
    else:
        with st.expander("Menu", expanded=False):
            _render_agent_menu_controls()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                render_formatted_assistant_message(message["content"])
            else:
                st.markdown(message["content"])

    user_input = st.chat_input("Message Mimi…")
    if not user_input:
        return

    with st.spinner("Thinking..."):
        run_query(user_input)
    st.rerun()


def render_main_surface():
    surface = st.session_state.get("ui_surface", "Agent")
    if surface == "Tool 1":
        render_tool1_panel()
    elif surface == "Tool 2":
        render_tool_placeholder(2)
    elif surface == "Tool 3":
        render_tool_placeholder(3)
    elif surface == "Terminal":
        render_terminal_panel()
    else:
        render_agent_center_minimal()


def main():
    st.set_page_config(
        page_title="Mimi AI Agent",
        page_icon="✨",
        layout="wide",
    )

    init_session_state()
    apply_theme()
    render_top_surface_bar()
    render_sidebar_rail_and_context()
    render_main_surface()


if __name__ == "__main__":
    main()