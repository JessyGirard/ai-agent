import json
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
    original_journal_file = playground.JOURNAL_FILE
    original_journal_archive_file = playground.JOURNAL_ARCHIVE_FILE
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_memory_path = Path(temp_dir) / "extracted_memory.json"
        temp_state_path = Path(temp_dir) / "current_state.json"
        temp_journal_path = Path(temp_dir) / "project_journal.jsonl"
        temp_journal_archive_path = Path(temp_dir) / "project_journal_archive.jsonl"
        playground.MEMORY_FILE = temp_memory_path
        playground.STATE_FILE = temp_state_path
        playground.JOURNAL_FILE = temp_journal_path
        playground.JOURNAL_ARCHIVE_FILE = temp_journal_archive_path
        try:
            yield temp_memory_path, temp_state_path, temp_journal_path, temp_journal_archive_path
        finally:
            playground.MEMORY_FILE = original_memory_file
            playground.STATE_FILE = original_state_file
            playground.JOURNAL_FILE = original_journal_file
            playground.JOURNAL_ARCHIVE_FILE = original_journal_archive_file


@contextmanager
def isolated_state_file():
    original_state_file = playground.STATE_FILE
    original_journal_file = playground.JOURNAL_FILE
    original_journal_archive_file = playground.JOURNAL_ARCHIVE_FILE
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_state_path = Path(temp_dir) / "current_state.json"
        temp_journal_path = Path(temp_dir) / "project_journal.jsonl"
        temp_journal_archive_path = Path(temp_dir) / "project_journal_archive.jsonl"
        playground.STATE_FILE = temp_state_path
        playground.JOURNAL_FILE = temp_journal_path
        playground.JOURNAL_ARCHIVE_FILE = temp_journal_archive_path
        try:
            yield temp_state_path
        finally:
            playground.STATE_FILE = original_state_file
            playground.JOURNAL_FILE = original_journal_file
            playground.JOURNAL_ARCHIVE_FILE = original_journal_archive_file


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


def test_memory_retrieval_prefers_recent_reinforced_item():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_1",
                    "category": "preference",
                    "value": "I prefer step-by-step learning",
                    "confidence": 0.75,
                    "importance": 0.75,
                    "memory_kind": "emerging",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_2",
                    "category": "preference",
                    "value": "I prefer step by step learning",
                    "confidence": 0.75,
                    "importance": 0.75,
                    "memory_kind": "emerging",
                    "evidence_count": 3,
                    "last_seen": "msg_8",
                    "trend": "new",
                    "source_refs": ["msg_8"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(str(payload).replace("'", '"'), encoding="utf-8")

        memories = playground.retrieve_relevant_memory("How do I prefer to learn?")
        assert memories, "Expected at least one retrieved memory"
        assert memories[0]["memory_id"] == "mem_1", "Recent reinforced memory should rank first"


def test_memory_retrieval_keeps_intent_priority_with_recency_bonus():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_pref",
                    "category": "preference",
                    "value": "I prefer step-by-step learning",
                    "confidence": 0.60,
                    "importance": 0.75,
                    "memory_kind": "emerging",
                    "evidence_count": 2,
                    "last_seen": "msg_2",
                    "trend": "new",
                    "source_refs": ["msg_2"],
                },
                {
                    "memory_id": "mem_proj",
                    "category": "project",
                    "value": "I am working on memory retrieval",
                    "confidence": 0.85,
                    "importance": 1.0,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(str(payload).replace("'", '"'), encoding="utf-8")

        memories = playground.retrieve_relevant_memory("How do I prefer to learn?")
        assert memories, "Expected retrieved memory results"
        assert memories[0]["memory_id"] == "mem_pref", "Intent-aligned preference should rank above unrelated project memory"


def test_memory_retrieval_prefers_fresh_over_stale_import():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_fresh",
                    "category": "preference",
                    "value": "I prefer hands-on building with validation",
                    "confidence": 0.75,
                    "importance": 0.75,
                    "memory_kind": "emerging",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_stale",
                    "category": "preference",
                    "value": "I prefer hands-on building with validation",
                    "confidence": 0.75,
                    "importance": 0.75,
                    "memory_kind": "tentative",
                    "evidence_count": 1,
                    "last_seen": "msg_1",
                    "trend": "new",
                    "source_refs": ["msg_1"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        memories = playground.retrieve_relevant_memory(
            "How do I prefer to learn when building things?"
        )
        assert memories, "Expected retrieved memories"
        assert memories[0]["memory_id"] == "mem_fresh", "Fresh runtime memory should rank above stale import"


def test_runtime_memory_skips_conflicting_goal_write():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(
            json.dumps(
                {
                    "meta": {},
                    "memory_items": [
                        {
                            "memory_id": "mem_g1",
                            "category": "goal",
                            "value": "My goal is to ship stable memory",
                            "confidence": 0.6,
                            "importance": 0.95,
                            "memory_kind": "emerging",
                            "evidence_count": 2,
                            "last_seen": "runtime",
                            "trend": "reinforced",
                            "source_refs": ["runtime"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = playground.write_runtime_memory(
            "My goal is to never ship unstable memory"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result is None, "Conflicting goal should not be written"
        assert len(items) == 1, "Conflicting goal should not add a second item"


def test_runtime_memory_skips_conflicting_identity_write():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(
            json.dumps(
                {
                    "meta": {},
                    "memory_items": [
                        {
                            "memory_id": "mem_i1",
                            "category": "identity",
                            "value": "I am a backend engineer",
                            "confidence": 0.6,
                            "importance": 0.85,
                            "memory_kind": "emerging",
                            "evidence_count": 2,
                            "last_seen": "runtime",
                            "trend": "reinforced",
                            "source_refs": ["runtime"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = playground.write_runtime_memory("I am not a backend engineer")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result is None, "Conflicting identity should not be written"
        assert len(items) == 1, "Conflicting identity should not add a second item"


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
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
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
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
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


def test_runtime_memory_skips_transient_identity():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text('{"meta": {}, "memory_items": []}', encoding="utf-8")

        result = playground.write_runtime_memory("I am fine")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result is None, "Transient identity phrase should not be stored as memory"
        assert len(items) == 0, "Transient identity phrase created memory unexpectedly"


def test_runtime_memory_skips_questions():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text('{"meta": {}, "memory_items": []}', encoding="utf-8")

        result = playground.write_runtime_memory("Am I doing this right?")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result is None, "Questions should not be stored as runtime memory"
        assert len(items) == 0, "Question created memory unexpectedly"


def test_runtime_memory_skips_uncertain_preference():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text('{"meta": {}, "memory_items": []}', encoding="utf-8")

        result = playground.write_runtime_memory("Maybe I prefer step-by-step learning")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result is None, "Uncertain preference should not be stored as runtime memory"
        assert len(items) == 0, "Uncertain preference created memory unexpectedly"


def test_runtime_memory_skips_uncertain_identity():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text('{"meta": {}, "memory_items": []}', encoding="utf-8")

        result = playground.write_runtime_memory("I guess I'm a backend engineer")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result is None, "Uncertain identity should not be stored as runtime memory"
        assert len(items) == 0, "Uncertain identity created memory unexpectedly"


def test_runtime_memory_stores_certain_preference_control():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text('{"meta": {}, "memory_items": []}', encoding="utf-8")

        result = playground.write_runtime_memory("I prefer step-by-step learning")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result is not None, "Certain preference should be stored as runtime memory"
        assert len(items) == 1, "Certain preference did not create memory as expected"
        assert items[0]["category"] == "preference", "Certain preference stored with wrong category"


def test_runtime_memory_allows_uncertain_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text('{"meta": {}, "memory_items": []}', encoding="utf-8")

        result = playground.write_runtime_memory("I'm working on memory retrieval I guess")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result is not None, "Tentative project line should still be stored as runtime memory"
        assert len(items) == 1, "Uncertain project phrase did not create memory as expected"
        assert items[0]["category"] == "project", "Uncertain project stored with wrong category"


def test_runtime_memory_skips_uncertain_goal():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text('{"meta": {}, "memory_items": []}', encoding="utf-8")

        result = playground.write_runtime_memory("My goal is maybe to ship stable memory")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result is None, "Uncertain goal should not be stored as runtime memory"
        assert len(items) == 0, "Uncertain goal created memory unexpectedly"


def test_memory_key_punctuation_equivalence():
    key_a = playground.build_memory_key("identity", "I'm detail-oriented")
    key_b = playground.build_memory_key("identity", "I am detail oriented")
    assert key_a != key_b, "Different semantic phrasing should not collapse to same key"

    key_c = playground.build_memory_key("identity", "I'm detail-oriented")
    key_d = playground.build_memory_key("identity", "I'm detail oriented")
    assert key_c == key_d, "Hyphen punctuation variant should canonicalize to same key"


def test_memory_key_repeated_punctuation_equivalence():
    key_a = playground.build_memory_key("preference", "I prefer step...by...step learning!!!")
    key_b = playground.build_memory_key("preference", "I prefer step by step learning")
    assert key_a == key_b, "Repeated punctuation variant should canonicalize to same key"


def test_runtime_memory_identity_edge_not_tired_anymore():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text('{"meta": {}, "memory_items": []}', encoding="utf-8")

        result = playground.write_runtime_memory("I am not tired anymore")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result is None, "Negated transient identity should not be stored as memory"
        assert len(items) == 0, "Negated transient identity created memory unexpectedly"


def test_runtime_memory_mixed_clause_transient_and_identity():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text('{"meta": {}, "memory_items": []}', encoding="utf-8")

        result = playground.write_runtime_memory("I am tired, but I am a backend engineer")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result is None, "Mixed clause with transient identity should be skipped for safety"
        assert len(items) == 0, "Mixed clause created memory unexpectedly"
def test_memory_display_normalization_separators():
    raw = "  I prefer step---by___step learning  "
    normalized = playground.normalize_memory_display_value(raw)
    assert normalized == "I prefer step by step learning", (
        f"Unexpected normalized value: {normalized}"
    )

def test_project_journal_records_events():
    reset_agent_state()
    with isolated_runtime_files():
        original_ask_ai = playground.ask_ai
        try:
            playground.ask_ai = lambda messages, system_prompt=None: (
                "Answer:\n"
                "Test memory retrieval now.\n\n"
                "Current state:\n"
                "Focus: ai-agent project\n"
                "Stage: Phase 5 testing\n"
                "Action type: test\n\n"
                "Next step:\n"
                "Test memory retrieval with one known preference question."
            )

            _ = playground.handle_user_input("set focus: memory reliability")
            _ = playground.handle_user_input("How do I prefer to learn?")
            entries = playground.load_project_journal()

            assert len(entries) >= 2, "Journal did not record expected events"
            assert any(e.get("entry_type") == "state_command" for e in entries), "Missing state_command journal entry"
            assert any(e.get("entry_type") == "conversation" for e in entries), "Missing conversation journal entry"
        finally:
            playground.ask_ai = original_ask_ai


def test_project_journal_auto_compaction():
    reset_agent_state()
    with isolated_runtime_files():
        original_max = playground.JOURNAL_MAX_ACTIVE_ENTRIES
        try:
            playground.JOURNAL_MAX_ACTIVE_ENTRIES = 3
            for i in range(5):
                playground.append_project_journal(
                    entry_type="conversation",
                    user_input=f"msg {i}",
                    response_text="ok",
                    action_type="test",
                )

            active_entries = playground.load_project_journal()
            assert len(active_entries) == 3, "Auto compaction did not keep expected active journal size"
            assert playground.JOURNAL_ARCHIVE_FILE.exists(), "Archive file was not created on compaction"
        finally:
            playground.JOURNAL_MAX_ACTIVE_ENTRIES = original_max


def test_project_journal_manual_flush_command():
    reset_agent_state()
    with isolated_runtime_files():
        original_keep_recent = playground.JOURNAL_KEEP_RECENT_ON_MANUAL_FLUSH
        try:
            playground.JOURNAL_KEEP_RECENT_ON_MANUAL_FLUSH = 2
            for i in range(4):
                playground.append_project_journal(
                    entry_type="conversation",
                    user_input=f"manual msg {i}",
                    response_text="ok",
                    action_type="test",
                )

            result = playground.handle_user_input("flush journal")
            active_entries = playground.load_project_journal()

            assert result.startswith("✅ Journal flushed."), "Flush command did not return success"
            assert len(active_entries) == 2, "Manual flush did not keep expected recent entries"
            assert playground.JOURNAL_ARCHIVE_FILE.exists(), "Archive file missing after manual flush"
        finally:
            playground.JOURNAL_KEEP_RECENT_ON_MANUAL_FLUSH = original_keep_recent


def main():
    print("Running regression tests...\n")

    tests = [
        ("blank_input", test_blank_input),
        ("show_state", test_show_state),
        ("set_focus", test_set_focus),
        ("set_stage", test_set_stage),
        ("generic_next_step", test_generic_next_step),
        ("memory_test", test_memory_test),
        ("memory_retrieval_prefers_recent_reinforced_item", test_memory_retrieval_prefers_recent_reinforced_item),
        ("memory_retrieval_keeps_intent_priority_with_recency_bonus", test_memory_retrieval_keeps_intent_priority_with_recency_bonus),
        ("memory_retrieval_prefers_fresh_over_stale_import", test_memory_retrieval_prefers_fresh_over_stale_import),
        ("runtime_memory_skips_conflicting_goal_write", test_runtime_memory_skips_conflicting_goal_write),
        ("runtime_memory_skips_conflicting_identity_write", test_runtime_memory_skips_conflicting_identity_write),
        ("formatting_review", test_formatting_review),
        ("state_command_test", test_state_command_test),
        ("direct_preference_answer", test_direct_preference_answer),
        ("state_over_memory_guard", test_state_over_memory_guard),
        ("tool_fetch_routing", test_tool_fetch_routing),
        ("post_fetch_next_step_quality", test_post_fetch_next_step_quality),
        ("memory_write_creation", test_memory_write_creation),
        ("memory_write_reinforcement", test_memory_write_reinforcement),
        ("runtime_memory_skips_transient_identity", test_runtime_memory_skips_transient_identity),
        ("runtime_memory_skips_questions", test_runtime_memory_skips_questions),
        ("runtime_memory_skips_uncertain_preference", test_runtime_memory_skips_uncertain_preference),
        ("runtime_memory_skips_uncertain_identity", test_runtime_memory_skips_uncertain_identity),
        ("runtime_memory_stores_certain_preference_control", test_runtime_memory_stores_certain_preference_control),
        ("runtime_memory_allows_uncertain_project", test_runtime_memory_allows_uncertain_project),
        ("runtime_memory_skips_uncertain_goal", test_runtime_memory_skips_uncertain_goal),
        ("memory_display_normalization_separators", test_memory_display_normalization_separators),
        ("memory_key_punctuation_equivalence", test_memory_key_punctuation_equivalence),
        ("memory_key_repeated_punctuation_equivalence", test_memory_key_repeated_punctuation_equivalence),
        ("runtime_memory_identity_edge_not_tired_anymore", test_runtime_memory_identity_edge_not_tired_anymore),
        ("runtime_memory_mixed_clause_transient_and_identity", test_runtime_memory_mixed_clause_transient_and_identity),
        ("project_journal_records_events", test_project_journal_records_events),
        ("project_journal_auto_compaction", test_project_journal_auto_compaction),
        ("project_journal_manual_flush_command", test_project_journal_manual_flush_command),
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