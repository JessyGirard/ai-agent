import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import playground


def run_test(name, fn):
    try:
        fn()
        print(f"[PASS] {name}")
        return True
    except AssertionError as e:
        print(f"[FAIL] {name}: {e}")
        return False
    except Exception as e:
        print(f"[FAIL] {name}: Unexpected error: {e}")
        return False


def reset_agent_state():
    playground.current_state.clear()
    playground.current_state.update(playground.DEFAULT_STATE.copy())


@contextmanager
def isolated_runtime_files():
    original_memory_file = playground.MEMORY_FILE
    original_state_file = playground.STATE_FILE
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_memory_path = Path(temp_dir) / "extracted_memory.json"
        temp_state_path = Path(temp_dir) / "current_state.json"
        playground.MEMORY_FILE = temp_memory_path
        playground.STATE_FILE = temp_state_path
        try:
            yield temp_memory_path, temp_state_path
        finally:
            playground.MEMORY_FILE = original_memory_file
            playground.STATE_FILE = original_state_file


@contextmanager
def isolated_state_file():
    original_state_file = playground.STATE_FILE
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_state_path = Path(temp_dir) / "current_state.json"
        playground.STATE_FILE = temp_state_path
        try:
            yield temp_state_path
        finally:
            playground.STATE_FILE = original_state_file


def test_blank_input():
    reset_agent_state()
    result = playground.handle_user_input("   ")
    assert result == "⚠️ Please type something.", f"Unexpected result: {result}"


def test_show_state():
    reset_agent_state()
    result = playground.handle_user_input("show state")
    assert "📌 Current state:" in result, "Missing state header"
    assert "Focus: ai-agent project" in result, "Missing default focus"
    assert "Stage: Phase 4 action-layer refinement" in result, "Missing default stage"


def test_set_focus():
    reset_agent_state()
    result = playground.handle_user_input("set focus: memory system")
    assert result == "✅ Focus updated to: memory system", f"Unexpected result: {result}"
    assert playground.current_state["focus"] == "memory system", "Focus not updated in state"


def test_set_stage():
    reset_agent_state()
    result = playground.handle_user_input("set stage: Phase 5 testing")
    assert result == "✅ Stage updated to: Phase 5 testing", f"Unexpected result: {result}"
    assert playground.current_state["stage"] == "Phase 5 testing", "Stage not updated in state"


def test_generic_next_step():
    reset_agent_state()
    playground.current_state["focus"] = "ai-agent project"
    playground.current_state["stage"] = "Phase 5 testing"

    result = playground.handle_user_input("What should I do next?")

    assert "Answer:" in result, "Missing Answer section"
    assert "Current state:" in result, "Missing Current state section"
    assert "Next step:" in result, "Missing Next step section"
    assert "Action type: test" in result, "Expected test action type"
    assert "Test memory retrieval first." in result, "Expected focused answer line"
    assert "Test memory retrieval with one known preference question" in result, "Expected memory retrieval next step"


def test_memory_test():
    reset_agent_state()
    playground.current_state["focus"] = "ai-agent project"
    playground.current_state["stage"] = "Phase 5 testing"

    result = playground.handle_user_input("How do I prefer to learn?")

    assert "Answer:" in result, "Missing Answer section"
    assert "You prefer step-by-step learning with validation before moving forward." in result, "Preference answer missing"
    assert "Current state:" in result, "Missing Current state section"
    assert "Action type: test" in result, "Expected test action type"
    assert "Next step:" in result, "Missing Next step section"
    assert "Test memory retrieval with one known preference question" in result, "Expected memory retrieval next step"


def test_formatting_review():
    reset_agent_state()
    playground.current_state["focus"] = "ai-agent project"
    playground.current_state["stage"] = "Phase 5 testing"

    result = playground.handle_user_input("Review formatting")

    assert "Answer:" in result, "Missing Answer section"
    assert "Current state:" in result, "Missing Current state section"
    assert "Next step:" in result, "Missing Next step section"
    assert "Action type: review" in result, "Expected review action type"
    assert "Review Titan formatting first." in result, "Expected review answer line"


def test_state_command_test():
    reset_agent_state()

    focus_result = playground.handle_user_input("set focus: ai-agent project")
    stage_result = playground.handle_user_input("set stage: Phase 5 testing")
    state_result = playground.handle_user_input("show state")

    assert focus_result == "✅ Focus updated to: ai-agent project", f"Unexpected focus result: {focus_result}"
    assert stage_result == "✅ Stage updated to: Phase 5 testing", f"Unexpected stage result: {stage_result}"
    assert "Focus: ai-agent project" in state_result, "Focus not shown correctly"
    assert "Stage: Phase 5 testing" in state_result, "Stage not shown correctly"


def test_direct_preference_answer():
    reset_agent_state()
    playground.current_state["focus"] = "ai-agent project"
    playground.current_state["stage"] = "Phase 5 testing"

    result = playground.handle_user_input("How do I prefer to learn?")

    assert "Answer:" in result, "Missing Answer section"
    assert "You prefer step-by-step learning with validation before moving forward." in result, "Direct preference answer missing"
    assert "Test memory retrieval now." not in result, "Old incorrect answer line still present"


def test_state_over_memory_guard():
    reset_agent_state()
    playground.current_state["focus"] = "ai-agent project"
    playground.current_state["stage"] = "Phase 5 testing"

    result = playground.handle_user_input("What should I do next?")

    assert "Focus: ai-agent project" in result, "Focus drifted away from current state"
    assert "Stage: Phase 5 testing" in result, "Stage drifted away from current state"
    assert "Action type: test" in result, "Expected test action type"
    assert "Test memory retrieval first." in result, "Expected current-state-anchored answer line"


def test_tool_fetch_routing():
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "TOOL:fetch https://example.com"
            return (
                "Answer:\n"
                "This is a fetched summary.\n\n"
                "Current state:\n"
                "Focus: ai-agent project\n"
                "Stage: Phase 4 action-layer refinement\n"
                "Action type: research\n\n"
                "Next step:\n"
                "Use another real page URL and verify the fetched summary stays grounded in the page content."
            )

        playground.ask_ai = fake_ask_ai
        playground.fetch_page = lambda url: f"FAKE FETCH OK: {url}"

        result = playground.handle_user_input("Read https://example.com")

        assert "Answer:" in result, "Missing Answer section"
        assert "This is a fetched summary." in result, "Missing final post-fetch answer"
        assert "Action type: research" in result, "Expected research action type"
        assert call_count["n"] == 2, f"Expected 2 LLM calls, got {call_count['n']}"

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_post_fetch_next_step_quality():
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "TOOL:fetch https://example.com"
            return (
                "Answer:\n"
                "The page is the standard Example Domain placeholder.\n\n"
                "Current state:\n"
                "Focus: ai-agent project\n"
                "Stage: Phase 5 testing\n"
                "Action type: research\n\n"
                "Next step:\n"
                "Use one second real page URL and verify the answer stays grounded in fetched content."
            )

        playground.ask_ai = fake_ask_ai
        playground.fetch_page = lambda url: (
            "Example Domain This domain is for use in documentation examples "
            "without needing permission. Avoid use in operations."
        )

        result = playground.handle_user_input("Read https://example.com and tell me what it says")

        assert "Answer:" in result, "Missing Answer section"
        assert "Action type: research" in result, "Expected research action type"
        assert (
            "Use one second real page URL and verify the answer stays grounded in fetched content."
            in result
        ), "Post-fetch next step did not stay concrete and grounded"
        assert call_count["n"] == 2, f"Expected 2 LLM calls, got {call_count['n']}"

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_memory_write_creation():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text('{"meta": {}, "memory_items": []}', encoding="utf-8")

        playground.write_runtime_memory("I prefer step-by-step learning")

        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert len(items) == 1, "Memory was not created"
        assert items[0]["category"] == "preference", "Wrong category"
        assert items[0]["evidence_count"] == 1, "Wrong evidence count"


def test_memory_write_reinforcement():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text('{"meta": {}, "memory_items": []}', encoding="utf-8")

        playground.write_runtime_memory("I prefer step-by-step learning")
        playground.write_runtime_memory("I prefer step-by-step learning")

        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert len(items) == 1, "Duplicate memory created instead of reinforcing"
        assert items[0]["evidence_count"] == 2, "Reinforcement did not increase evidence count"
        assert items[0]["confidence"] >= 0.6, "Confidence did not increase properly"


def test_missing_llm_configuration_handling():
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    try:
        def fake_ask_ai(messages, system_prompt=None):
            raise RuntimeError("ANTHROPIC_API_KEY is missing.")

        playground.ask_ai = fake_ask_ai
        result = playground.handle_user_input("What should I do next?")
        assert result.startswith("LLM configuration error:"), f"Unexpected result: {result}"
        assert "ANTHROPIC_API_KEY is missing." in result, "Missing specific preflight error"
    finally:
        playground.ask_ai = original_ask_ai


def main():
    print("Running regression tests...\n")

    tests = [
        ("blank_input", test_blank_input),
        ("show_state", test_show_state),
        ("set_focus", test_set_focus),
        ("set_stage", test_set_stage),
        ("generic_next_step", test_generic_next_step),
        ("memory_test", test_memory_test),
        ("formatting_review", test_formatting_review),
        ("state_command_test", test_state_command_test),
        ("direct_preference_answer", test_direct_preference_answer),
        ("state_over_memory_guard", test_state_over_memory_guard),
        ("tool_fetch_routing", test_tool_fetch_routing),
        ("post_fetch_next_step_quality", test_post_fetch_next_step_quality),
        ("memory_write_creation", test_memory_write_creation),
        ("memory_write_reinforcement", test_memory_write_reinforcement),
        ("missing_llm_configuration_handling", test_missing_llm_configuration_handling),
    ]

    passed = 0
    total = len(tests)

    for name, fn in tests:
        with isolated_state_file():
            if run_test(name, fn):
                passed += 1

    print(f"\nPassed {passed} / {total} tests")

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()