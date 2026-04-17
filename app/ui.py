import json
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import playground

from app import system_eval_operator as tool1_operator


MEMORY_FILE = Path("memory/extracted_memory.json")
QUICK_PROMPTS = [
    "What should I do next?",
    "How do I prefer to learn?",
    "show state",
]


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


def render_sidebar():
    st.sidebar.title("Agent Control")

    current_focus = playground.get_current_focus()
    current_stage = playground.get_current_stage()

    st.sidebar.markdown("### Current State")
    st.sidebar.write(f"Focus: `{current_focus}`")
    st.sidebar.write(f"Stage: `{current_stage}`")

    st.sidebar.markdown("### Quick Actions")
    col1, col2 = st.sidebar.columns(2)

    if col1.button("Show State", use_container_width=True):
        push_assistant_message(playground.handle_user_input("show state"))

    if col2.button("Reset State", use_container_width=True):
        push_assistant_message(playground.handle_user_input("reset state"))

    st.sidebar.markdown("### Update Focus / Stage")
    with st.sidebar.form("state_form"):
        new_focus = st.text_input("Focus", value=current_focus)
        new_stage = st.text_input("Stage", value=current_stage)
        submitted = st.form_submit_button("Apply")
        if submitted:
            if new_focus.strip() and new_focus.strip() != current_focus:
                playground.handle_user_input(f"set focus: {new_focus.strip()}")
            if new_stage.strip() and new_stage.strip() != current_stage:
                playground.handle_user_input(f"set stage: {new_stage.strip()}")
            push_assistant_message(playground.handle_user_input("show state"))

    st.sidebar.markdown("### Memory Snapshot")
    for item in load_memory_items():
        category = item.get("category", "unknown")
        value = item.get("value", "")
        st.sidebar.caption(f"- ({category}) {value}")


def _tool1_attempts_summary(case_row):
    if case_row.get("attempts_total"):
        return f"{case_row.get('attempts_passed')}/{case_row.get('attempts_total')}"
    return "1"


def render_tool1_panel():
    st.title("Tool 1 — HTTP system eval")
    st.caption(
        "Operator console: same path as `python tools/system_eval_runner.py` "
        "(suite JSON → HTTP adapter → artifacts). Does not use playground chat logic."
    )

    st.text_input(
        "Suite JSON path (repo-relative or absolute)",
        key="tool1_suite_path",
    )
    st.text_input("Output directory for artifacts", key="tool1_output_dir")
    st.text_input("Optional file stem (blank = derive from suite_name)", key="tool1_file_stem")
    st.checkbox("Fail fast (stop at first failing case)", key="tool1_fail_fast")
    st.number_input("HTTP timeout (seconds)", min_value=1, max_value=300, key="tool1_timeout")

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

    bundle = st.session_state.get("tool1_last_bundle")
    if not bundle:
        st.info("Configure paths above and click **Run system eval**.")
        return

    if bundle.get("error"):
        st.error(bundle["error"])
        return

    result = bundle.get("result") or {}
    overall_ok = bundle.get("ok", False)
    st.subheader("Overall")
    st.success("PASS") if overall_ok else st.error("FAIL")
    st.write(
        f"Suite: `{result.get('suite_name')}` · Target label: `{result.get('target_name')}` · "
        f"Cases executed: `{result.get('executed_cases')}` · "
        f"Passed: `{result.get('passed_cases')}` · Failed: `{result.get('failed_cases')}`"
    )

    st.subheader("Per-case results")
    rows = []
    for c in result.get("cases", []):
        rows.append(
            {
                "case": c.get("name"),
                "ok": c.get("ok"),
                "lane": c.get("lane") or "—",
                "attempts": _tool1_attempts_summary(c),
                "status": c.get("status_code"),
                "latency_ms": c.get("latency_ms"),
            }
        )
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Artifacts")
    paths = bundle.get("artifact_paths") or {}
    st.code(paths.get("json_path", ""), language="text")
    st.code(paths.get("markdown_path", ""), language="text")

    with st.expander("Markdown preview", expanded=False):
        st.markdown(bundle.get("markdown_preview") or "_empty_")

    with st.expander("JSON preview", expanded=False):
        st.code(bundle.get("json_preview") or "", language="json")


def render_chat():
    st.title("Mimi AI Agent")
    st.caption("A focused, state-aware agent that grows with you.")
    st.markdown(f'<span class="status-pill">Status: {st.session_state.status}</span>', unsafe_allow_html=True)

    top_col1, top_col2 = st.columns([4, 1])
    with top_col2:
        if st.button("New Chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    st.markdown("Quick prompts:")
    qp_col1, qp_col2, qp_col3 = st.columns(3)
    for i, prompt in enumerate(QUICK_PROMPTS):
        col = [qp_col1, qp_col2, qp_col3][i]
        if col.button(prompt, key=f"quick_prompt_{i}", use_container_width=True):
            run_query(prompt)
            st.rerun()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                render_formatted_assistant_message(message["content"])
            else:
                st.markdown(message["content"])

    user_input = st.chat_input("Ask Mimi anything...")
    if not user_input:
        return

    with st.spinner("Thinking..."):
        run_query(user_input)
    st.rerun()


def main():
    st.set_page_config(
        page_title="Mimi AI Agent",
        page_icon="✨",
        layout="wide",
    )

    init_session_state()
    apply_theme()
    render_sidebar()
    tab_chat, tab_tool1 = st.tabs(["Assistant", "Tool 1 — System eval (HTTP)"])
    with tab_chat:
        render_chat()
    with tab_tool1:
        render_tool1_panel()


if __name__ == "__main__":
    main()