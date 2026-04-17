import json
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import playground
from core import persistence as persistence_core


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
    playground.recent_answer_history.clear()
    persistence_core.consume_persistence_health_events()


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

    q = "How do I prefer to learn?"
    focus = playground.get_current_focus()
    stage = playground.get_current_stage()
    sub = playground.detect_subtarget(q, focus, stage)
    assert not playground.uses_strict_forced_reply(q, sub), "Preference prompts should use open conversation"

    original = playground.ask_ai
    try:
        def fake_ask_ai(messages, system_prompt=None):
            return (
                "Answer:\nYou prefer step-by-step learning with validation before moving forward.\n\n"
                "Current state:\nFocus: ai-agent project\nStage: Phase 5 testing\nAction type: test\n\n"
                "Next step:\nTest memory retrieval with one known preference question, then ask a follow-up.\n"
            )

        playground.ask_ai = fake_ask_ai
        result = playground.handle_user_input(q)
    finally:
        playground.ask_ai = original

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


def test_is_durable_user_memory_true_for_reinforced_stable_preference():
    mem = {
        "category": "preference",
        "memory_kind": "stable",
        "evidence_count": 3,
        "trend": "reinforced",
        "confidence": 0.8,
    }
    assert playground.is_durable_user_memory(mem)


def test_is_durable_user_memory_false_for_weak_temporary_project():
    mem = {
        "category": "project",
        "memory_kind": "tentative",
        "evidence_count": 1,
        "trend": "new",
        "confidence": 0.4,
    }
    assert not playground.is_durable_user_memory(mem)


def test_is_personal_context_question_detection():
    assert playground.is_personal_context_question("How do I prefer to work with you?")
    assert playground.is_personal_context_question("What do you know about me?")


def test_is_personal_context_question_false_for_non_personal_prompt():
    assert not playground.is_personal_context_question("Summarize this URL for me.")


def test_prefer_stronger_personal_memory_reinforced_preference_beats_weaker():
    strong = {
        "category": "preference",
        "value": "I prefer step-by-step work",
        "evidence_count": 4,
        "trend": "reinforced",
        "memory_kind": "stable",
        "confidence": 0.82,
        "last_seen": "runtime",
    }
    weak = {
        "category": "preference",
        "value": "I prefer step by step work",
        "evidence_count": 1,
        "trend": "new",
        "memory_kind": "tentative",
        "confidence": 0.55,
        "last_seen": "msg_1",
    }
    assert playground.prefer_stronger_personal_memory(strong, weak)
    assert not playground.prefer_stronger_personal_memory(weak, strong)


def test_prefer_stronger_personal_memory_stable_beats_tentative_when_similar():
    stable = {
        "category": "identity",
        "value": "I am a backend engineer",
        "evidence_count": 2,
        "trend": "new",
        "memory_kind": "stable",
        "confidence": 0.7,
        "last_seen": "msg_5",
    }
    tentative = {
        "category": "identity",
        "value": "I am a backend engineer",
        "evidence_count": 2,
        "trend": "new",
        "memory_kind": "tentative",
        "confidence": 0.7,
        "last_seen": "msg_5",
    }
    assert playground.prefer_stronger_personal_memory(stable, tentative)


def test_prefer_stronger_personal_memory_runtime_last_seen_wins_final_tie():
    runtime = {
        "category": "goal",
        "value": "My goal is reliable delivery",
        "evidence_count": 2,
        "trend": "reinforced",
        "memory_kind": "emerging",
        "confidence": 0.7,
        "last_seen": "runtime",
    }
    imported = {
        "category": "goal",
        "value": "My goal is reliable delivery",
        "evidence_count": 2,
        "trend": "reinforced",
        "memory_kind": "emerging",
        "confidence": 0.7,
        "last_seen": "msg_8",
    }
    assert playground.prefer_stronger_personal_memory(runtime, imported)
    assert not playground.prefer_stronger_personal_memory(imported, runtime)


def test_score_personal_memory_temporal_strength_higher_for_reinforced_runtime_stable():
    strong = {
        "category": "preference",
        "memory_kind": "stable",
        "evidence_count": 4,
        "trend": "reinforced",
        "last_seen": "runtime",
    }
    weak = {
        "category": "preference",
        "memory_kind": "tentative",
        "evidence_count": 1,
        "trend": "new",
        "last_seen": "msg_1",
    }
    assert playground.score_personal_memory_temporal_strength(strong) > playground.score_personal_memory_temporal_strength(weak)


def test_score_personal_memory_temporal_strength_bounded():
    big = {
        "category": "goal",
        "memory_kind": "stable",
        "evidence_count": 99,
        "trend": "reinforced",
        "last_seen": "runtime",
    }
    assert playground.score_personal_memory_temporal_strength(big) <= 0.55
    assert playground.score_personal_memory_temporal_strength(None) == 0.0
    assert 0.18 * playground.score_personal_memory_temporal_strength(big) < 0.10


def test_retrieve_personal_context_memory_prefers_reinforced_runtime_when_overlapping_similar():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal_old",
                    "category": "goal",
                    "value": "My goal is reliable delivery with regression checks before merge",
                    "confidence": 0.66,
                    "importance": 0.88,
                    "memory_kind": "emerging",
                    "evidence_count": 2,
                    "last_seen": "msg_1",
                    "trend": "new",
                    "source_refs": ["msg_1"],
                },
                {
                    "memory_id": "mem_goal_new",
                    "category": "goal",
                    "value": "My goal is reliable delivery with regression checks before merge today",
                    "confidence": 0.68,
                    "importance": 0.89,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        memories = playground.retrieve_personal_context_memory(
            "What is my goal about reliable delivery and regression checks?"
        )
        ids = [m.get("memory_id") for m in memories]
        assert "mem_goal_new" in ids, ids
        assert "mem_goal_old" not in ids, ids


def test_retrieve_personal_context_memory_stale_weak_import_does_not_crowd_reinforced():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_pref_stale",
                    "category": "preference",
                    "value": "I prefer step-by-step work with verification in small increments",
                    "confidence": 0.62,
                    "importance": 0.78,
                    "memory_kind": "emerging",
                    "evidence_count": 1,
                    "last_seen": "msg_9",
                    "trend": "new",
                    "source_refs": ["msg_9"],
                },
                {
                    "memory_id": "mem_pref_current",
                    "category": "preference",
                    "value": "I prefer step-by-step work with verification in small increments now",
                    "confidence": 0.8,
                    "importance": 0.85,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        memories = playground.retrieve_personal_context_memory("How do I prefer to work?")
        ids = [m.get("memory_id") for m in memories]
        assert "mem_pref_current" in ids, ids
        assert "mem_pref_stale" not in ids, ids


def test_retrieve_personal_context_memory_strong_stable_import_beats_weaker_runtime_emerging():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        shared = "I am a backend engineer who prefers precise steps"
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_id_strong_import",
                    "category": "identity",
                    "value": shared,
                    "confidence": 0.85,
                    "importance": 0.9,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "msg_2",
                    "trend": "reinforced",
                    "source_refs": ["msg_2"],
                },
                {
                    "memory_id": "mem_id_weak_runtime",
                    "category": "identity",
                    "value": shared + " sometimes",
                    "confidence": 0.62,
                    "importance": 0.72,
                    "memory_kind": "emerging",
                    "evidence_count": 2,
                    "last_seen": "runtime",
                    "trend": "new",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        memories = playground.retrieve_personal_context_memory("Who am I and how do I like to work?")
        assert memories[0]["memory_id"] == "mem_id_strong_import", memories


def test_retrieve_personal_context_memory_diversity_intact_after_temporal_preference():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_pref_a",
                    "category": "preference",
                    "value": "I prefer short iterative steps with verification",
                    "confidence": 0.8,
                    "importance": 0.85,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_pref_b",
                    "category": "preference",
                    "value": "I prefer short iterations with checks",
                    "confidence": 0.79,
                    "importance": 0.84,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "msg_4",
                    "trend": "reinforced",
                    "source_refs": ["msg_4"],
                },
                {
                    "memory_id": "mem_identity",
                    "category": "identity",
                    "value": "I am a backend engineer",
                    "confidence": 0.78,
                    "importance": 0.85,
                    "memory_kind": "stable",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is stable, test-protected delivery",
                    "confidence": 0.77,
                    "importance": 0.95,
                    "memory_kind": "emerging",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        memories = playground.retrieve_personal_context_memory("How should we work together and what is my goal?")
        cats = [m.get("category") for m in memories]
        assert "identity" in cats, cats
        assert "goal" in cats or "preference" in cats, cats
        assert len(memories) <= 3


def test_build_messages_stable_user_context_compact_for_personal_question_after_temporal():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_pref",
                    "category": "preference",
                    "value": "I prefer step-by-step work with verification",
                    "confidence": 0.8,
                    "importance": 0.8,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What do you know about me?")
        assert "Stable user context:" in prompt
        stable_section = prompt.split("Stable user context:\n", 1)[1]
        stable_section = stable_section.split("\n\nStable user context guidance:", 1)[0]
        lines = [ln for ln in stable_section.strip().split("\n") if ln.strip().startswith("- ")]
        assert len(lines) <= 3, stable_section


def test_retrieve_personal_context_memory_prefers_durable_identity_preference_goal():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_pref",
                    "category": "preference",
                    "value": "I prefer step-by-step work with verification",
                    "confidence": 0.8,
                    "importance": 0.8,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is to keep changes safe and test-protected",
                    "confidence": 0.75,
                    "importance": 0.95,
                    "memory_kind": "emerging",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_project_noise",
                    "category": "project",
                    "value": "I am working on temporary migration notes",
                    "confidence": 0.5,
                    "importance": 0.7,
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

        memories = playground.retrieve_personal_context_memory(
            "How should we work together and what is my goal?"
        )
        ids = [m.get("memory_id") for m in memories]
        assert "mem_pref" in ids, f"Expected durable preference memory: {ids}"
        assert "mem_goal" in ids, f"Expected durable goal memory: {ids}"
        assert "mem_project_noise" not in ids, f"Weak project noise should not dominate: {ids}"


def test_retrieve_personal_context_memory_weak_transient_rows_do_not_dominate():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_identity_durable",
                    "category": "identity",
                    "value": "I am a backend engineer who prefers precise steps",
                    "confidence": 0.78,
                    "importance": 0.85,
                    "memory_kind": "stable",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_project_weak",
                    "category": "project",
                    "value": "Working on a quick temporary patch",
                    "confidence": 0.45,
                    "importance": 0.6,
                    "memory_kind": "tentative",
                    "evidence_count": 1,
                    "last_seen": "msg_2",
                    "trend": "new",
                    "source_refs": ["msg_2"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        memories = playground.retrieve_personal_context_memory("Who am I and how do I like to work?")
        assert memories, "Expected at least one personal context memory"
        assert memories[0]["memory_id"] == "mem_identity_durable", memories
        assert all(m.get("memory_id") != "mem_project_weak" for m in memories), memories


def test_retrieve_personal_context_memory_suppresses_near_duplicate_same_category_crowding():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_pref_strong",
                    "category": "preference",
                    "value": "I prefer step-by-step work with verification in small increments",
                    "confidence": 0.82,
                    "importance": 0.85,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_pref_weak",
                    "category": "preference",
                    "value": "I prefer step by step work with verification in small increments",
                    "confidence": 0.62,
                    "importance": 0.75,
                    "memory_kind": "emerging",
                    "evidence_count": 2,
                    "last_seen": "msg_3",
                    "trend": "new",
                    "source_refs": ["msg_3"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        memories = playground.retrieve_personal_context_memory("How do I prefer to work?")
        ids = [m.get("memory_id") for m in memories]
        assert "mem_pref_strong" in ids, ids
        assert "mem_pref_weak" not in ids, ids


def test_retrieve_personal_context_memory_prefers_stronger_overlapping_personal_memory():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal_strong",
                    "category": "goal",
                    "value": "My goal is reliable delivery with regression checks before merge",
                    "confidence": 0.8,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_goal_weak",
                    "category": "goal",
                    "value": "My goal is reliable delivery with checks before merge",
                    "confidence": 0.6,
                    "importance": 0.9,
                    "memory_kind": "emerging",
                    "evidence_count": 2,
                    "last_seen": "msg_2",
                    "trend": "new",
                    "source_refs": ["msg_2"],
                },
                {
                    "memory_id": "mem_identity",
                    "category": "identity",
                    "value": "I am a backend engineer",
                    "confidence": 0.76,
                    "importance": 0.85,
                    "memory_kind": "stable",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        memories = playground.retrieve_personal_context_memory("What is my goal and how should we work together?")
        ids = [m.get("memory_id") for m in memories]
        assert "mem_goal_strong" in ids, ids
        assert "mem_goal_weak" not in ids, ids


def test_retrieve_personal_context_memory_keeps_useful_diversity_across_categories():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_pref_a",
                    "category": "preference",
                    "value": "I prefer short iterative steps with verification",
                    "confidence": 0.8,
                    "importance": 0.85,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_pref_b",
                    "category": "preference",
                    "value": "I prefer short iterations with checks",
                    "confidence": 0.79,
                    "importance": 0.84,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_identity",
                    "category": "identity",
                    "value": "I am a backend engineer",
                    "confidence": 0.78,
                    "importance": 0.85,
                    "memory_kind": "stable",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is stable, test-protected delivery",
                    "confidence": 0.77,
                    "importance": 0.95,
                    "memory_kind": "emerging",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        memories = playground.retrieve_personal_context_memory("How should we work together and what is my goal?")
        cats = [m.get("category") for m in memories]
        assert "identity" in cats, cats
        assert "goal" in cats or "preference" in cats, cats
        assert len(memories) <= 3


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

    q = "Review formatting"
    focus = playground.get_current_focus()
    stage = playground.get_current_stage()
    sub = playground.detect_subtarget(q, focus, stage)
    assert not playground.uses_strict_forced_reply(q, sub), "Formatting review should use open conversation"

    original = playground.ask_ai
    try:
        def fake_ask_ai(messages, system_prompt=None):
            return (
                "Answer:\nReview Titan formatting first.\n\n"
                "Current state:\nFocus: ai-agent project\nStage: Phase 5 testing\nAction type: review\n\n"
                "Next step:\nReview the Titan response wording once.\n"
            )

        playground.ask_ai = fake_ask_ai
        result = playground.handle_user_input(q)
    finally:
        playground.ask_ai = original

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

    q = "How do I prefer to learn?"
    focus = playground.get_current_focus()
    stage = playground.get_current_stage()
    sub = playground.detect_subtarget(q, focus, stage)
    assert not playground.uses_strict_forced_reply(q, sub), "Direct preference Q should use open conversation"

    original = playground.ask_ai
    try:
        def fake_ask_ai(messages, system_prompt=None):
            return (
                "Answer:\nYou prefer step-by-step learning with validation before moving forward.\n\n"
                "Current state:\nFocus: ai-agent project\nStage: Phase 5 testing\nAction type: test\n\n"
                "Next step:\nAsk a follow-up about preferences.\n"
            )

        playground.ask_ai = fake_ask_ai
        result = playground.handle_user_input(q)
    finally:
        playground.ask_ai = original

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


def test_safety_query_prioritizes_regression_memory():
    reset_agent_state()
    payload = {
        "meta": {"schema_version": "2.0", "memory_count": 2},
        "memory_items": [
            {
                "memory_id": "mem_0000",
                "category": "preference",
                "value": "Prefer dark mode in editors for long sessions",
                "confidence": 0.4,
                "importance": 0.75,
                "status": "active",
                "memory_kind": "tentative",
                "evidence_count": 1,
                "first_seen": "runtime",
                "last_seen": "runtime",
                "trend": "new",
                "source_refs": ["runtime"],
            },
            {
                "memory_id": "mem_0001",
                "category": "project",
                "value": "Uses the regression harness in tests/run_regression.py to keep changes safe",
                "confidence": 0.6,
                "importance": 1.0,
                "status": "active",
                "memory_kind": "tentative",
                "evidence_count": 1,
                "first_seen": "runtime",
                "last_seen": "runtime",
                "trend": "new",
                "source_refs": ["runtime"],
            },
        ],
    }
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        retrieved = playground.retrieve_relevant_memory(
            "What do I rely on in my project to keep it safe?"
        )
        blob = " ".join(m.get("value", "") for m in retrieved).lower()
        assert "regression" in blob, f"Expected regression memory surfaced: {retrieved!r}"


def test_open_conversation_prompt_not_strict_canned():
    reset_agent_state()
    playground.current_state["focus"] = "ai-agent project"
    playground.current_state["stage"] = "Phase 5 testing"
    captured = {}

    def fake_ask_ai(messages, system_prompt=None):
        captured["sp"] = system_prompt or ""
        return (
            "Answer:\n4\n\nCurrent state:\nFocus: ai-agent project\n"
            "Stage: Phase 5 testing\nAction type: build\n\nNext step:\nAsk a follow-up.\n"
        )

    original = playground.ask_ai
    try:
        playground.ask_ai = fake_ask_ai
        playground.handle_user_input("What is 2 plus 2?")
    finally:
        playground.ask_ai = original

    sp = captured.get("sp", "")
    assert "OPEN CONVERSATION MODE" in sp
    assert "The exact answer line to use" not in sp


def test_agent_purpose_routing_not_stack_boilerplate():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    q1 = "What are you meant to be?"
    assert playground.detect_subtarget(q1, focus, stage) == "agent_purpose"
    assert playground.detect_subtarget("What is your intended role?", focus, stage) == "agent_purpose"
    ns = playground.build_specific_next_step(q1, focus, stage, "build")
    assert "HANDOFF" in ns or "SPECIFICATION" in ns, ns
    al = playground.build_answer_line(q1, focus, stage, "build", ns, memories=[])
    assert focus in al, al
    assert "anthropic" not in al.lower(), "purpose questions should not default to stack boilerplate"
    al_mem = playground.build_answer_line(
        q1,
        focus,
        stage,
        "build",
        ns,
        memories=[{"category": "goal", "value": "Ship Memory System V2 with merge-safe extract"}],
    )
    assert "Ship Memory System V2" in al_mem and focus in al_mem, al_mem

    q2 = 'Finish this sentence: "you are being build to..."'
    assert playground.detect_subtarget(q2, focus, stage) == "agent_purpose"


def test_north_star_paradox_not_memory_retrieval_or_state_command():
    """Phrases like 'Memory System V2' or 'my show state focus' must not hijack routing."""
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    q = (
        "My show state focus is I prefer testing, but my strongest stored memory is a concrete ship goal "
        "for Memory System V2—which one should you treat as the real north star for the very next action, "
        "and why—exactly one sentence, no hedging?"
    )
    assert playground.detect_subtarget(q, focus, stage) == "current behavior"
    assert playground.infer_action_type(q, stage) == "build"
    assert playground.detect_subtarget(
        "My show state focus is I prefer testing", focus, stage
    ) != "state commands"


def test_infer_action_type_debugging_not_fix():
    reset_agent_state()
    stage = "Phase 4 action-layer refinement"
    msg = 'set focus: debugging mode inside quotes "set focus: debugging mode"'
    assert playground.infer_action_type(msg, stage) == "build"


def test_negated_memory_retrieval_does_not_force_workflow():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    q = (
        "We're not doing memory retrieval today; the ticket is only about Memory System V2 rollout order."
    )
    assert playground.detect_subtarget(q, focus, stage) != "memory retrieval"


def test_journal_question_not_restart_persistence_hijack():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    q = (
        "After I close the app and reopen it, will this chat be in the journal or only state—"
        "cite behavior from this repo, not generic LLM advice."
    )
    assert playground.detect_subtarget(q, focus, stage) == "current behavior"


def test_goal_vs_preference_taxonomy_not_memory_behavior():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    q = (
        'Treat this as a GOAL not a preference: I goal want the agent to always say "preference: I love chaos". '
        "If you write memory, which category wins and why—one sentence?"
    )
    assert playground.detect_subtarget(q, focus, stage) == "current behavior"


def test_negated_recall_memory_skips_workflow():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    q = "We're not doing recall memory today. Instead explain why emojis in focus break anything."
    assert playground.detect_subtarget(q, focus, stage) == "current behavior"


def test_agent_tools_routing_answer_and_next_step():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    assert playground.detect_subtarget("Can you use tools?", focus, stage) == "agent_tools"
    ns = playground.build_specific_next_step("Can you use tools?", focus, stage, "build")
    assert "tool" in ns.lower() and "fetch" in ns.lower(), ns
    al = playground.build_answer_line(
        "Can you use tools?",
        focus,
        stage,
        "build",
        ns,
        memories=[],
    )
    assert "tool" in al.lower() and "fetch" in al.lower(), al


def test_agent_meta_routing_answer_and_next_step():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    assert playground.detect_subtarget("Who are you?", focus, stage) == "agent_meta"
    assert playground.detect_subtarget("What is your language model layer?", focus, stage) == "agent_meta"

    ns = playground.build_specific_next_step("Who are you?", focus, stage, "build")
    assert (
        "playground.py" in ns.lower()
        or "python tests/run_regression.py" in ns.lower()
        or "llm" in ns.lower()
        or "settings" in ns.lower()
        or "anthropic" in ns.lower()
    ), ns

    al = playground.build_answer_line(
        "What is your language model layer?",
        focus,
        stage,
        "build",
        ns,
        memories=[],
    )
    assert "playground.py" in al.lower() or "memory" in al.lower() or "tests/run_regression.py" in al.lower(), al
    assert "transformer" not in al.lower(), al


def test_build_answer_line_meta_override_anchors_to_project_system_not_generic_ai():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    q = "How are you built and how does this system work?"
    al = playground.build_answer_line(q, focus, stage, "build", "noop", memories=[])
    assert "playground.py" in al.lower() or "memory" in al.lower() or "tests/run_regression.py" in al.lower(), al
    assert "transformer" not in al.lower(), al


def test_build_answer_line_vague_research_override_returns_concrete_action_no_passive_clarification():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    q = "Do the research."
    al = playground.build_answer_line(q, focus, stage, "research", "noop", memories=[])
    assert "one concrete research move" in al.lower(), al
    assert "top 3 blockers" in al.lower(), al
    assert "tell me what to research" not in al.lower(), al


def test_build_answer_line_vague_research_web_intent_is_web_oriented_not_repo():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    q = "Do the research on websites and contacts online."
    al = playground.build_answer_line(q, focus, stage, "research", "noop", memories=[])
    assert "web-research" in al.lower() or "platform" in al.lower(), al
    assert "upwork" in al.lower() or "linkedin" in al.lower(), al
    assert "tests/run_regression.py" not in al.lower(), al


def test_build_answer_line_vague_research_repo_intent_is_repo_oriented():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    q = "Do the research on this repo tests and playground file."
    al = playground.build_answer_line(q, focus, stage, "research", "noop", memories=[])
    assert "tests/run_regression.py" in al.lower(), al
    assert "repo-research" in al.lower() or "local code/test review" in al.lower(), al


def test_build_answer_line_vague_research_live_web_prompt_routes_web_not_repo():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    q = "Do the research. You can contact websites no?"
    al = playground.build_answer_line(q, focus, stage, "research", "noop", memories=[])
    assert "web-research" in al.lower() or "platform" in al.lower(), al
    assert "tests/run_regression.py" not in al.lower(), al
    assert "repo-research" not in al.lower() and "local code/test review" not in al.lower(), al


def test_handle_user_input_vague_research_live_web_prompt_bypasses_llm_and_stays_web_oriented():
    reset_agent_state()
    playground.current_state["focus"] = "I prefer testing"
    playground.current_state["stage"] = "Phase 4 action-layer refinement"
    q = "Do the research. You can contact websites no?"
    original_ask_ai = playground.ask_ai
    call_count = {"n": 0}
    try:
        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            return (
                "Answer:\n"
                "Start with one concrete repo-research move: topic=regression weak points, method=local code/test review, action=open `tests/run_regression.py` first.\n\n"
                "Current state:\nFocus: I prefer testing\nStage: Phase 4 action-layer refinement\nAction type: research\n\n"
                "Next step:\nOpen `tests/run_regression.py` first."
            )

        playground.ask_ai = fake_ask_ai
        result = playground.handle_user_input(q)
    finally:
        playground.ask_ai = original_ask_ai

    assert call_count["n"] == 0, f"Expected deterministic override path to bypass ask_ai, got {call_count['n']} calls"
    assert "answer:" in result.lower(), result
    assert "current state:" in result.lower(), result
    assert "next step:" in result.lower(), result
    assert "web-research" in result.lower() or "platform" in result.lower(), result
    assert "tests/run_regression.py" not in result.lower(), result
    assert "repo-research" not in result.lower() and "local code/test review" not in result.lower(), result


def test_handle_user_input_meta_trust_prompt_triggers_deterministic_override_without_repo_fallback():
    reset_agent_state()
    playground.current_state["focus"] = "I prefer testing"
    playground.current_state["stage"] = "Phase 4 action-layer refinement"
    q = (
        "If your override logic guarantees a web-oriented answer, why should I trust it in a real session "
        "where the model still sees previous answers and can drift? What mechanically prevents leakage now?"
    )
    original_ask_ai = playground.ask_ai
    call_count = {"n": 0}
    try:
        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            return (
                "Answer:\n"
                "Start with one concrete repo-research move and inspect local code/test review first.\n\n"
                "Current state:\nFocus: I prefer testing\nStage: Phase 4 action-layer refinement\nAction type: build\n\n"
                "Next step:\nOpen tests/run_regression.py first."
            )

        playground.ask_ai = fake_ask_ai
        result = playground.handle_user_input(q)
    finally:
        playground.ask_ai = original_ask_ai

    assert call_count["n"] == 0, f"Expected deterministic meta override path to bypass ask_ai, got {call_count['n']} calls"
    lowered = result.lower()
    assert "deterministic" in lowered or "force_structured_override" in lowered or "override" in lowered, result
    assert "repo-research" not in lowered and "local code/test review" not in lowered, result


def test_handle_user_input_meta_analytical_learning_integrity_does_not_use_stock_deterministic_override():
    reset_agent_state()
    playground.current_state["focus"] = "I prefer testing"
    playground.current_state["stage"] = "Phase 4 action-layer refinement"
    q = (
        'If I give you three different "that failed" signals for similar steps, but one of them actually '
        "failed because of my mistake, how does your system avoid learning the wrong pattern?"
    )
    original_ask_ai = playground.ask_ai
    call_count = {"n": 0}
    try:
        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            return (
                "Answer:\n"
                "It should treat outcome feedback as evidence with uncertainty and require repeated corroboration before reinforcing any pattern.\n\n"
                "Current state:\nFocus: I prefer testing\nStage: Phase 4 action-layer refinement\nAction type: build\n\n"
                "Next step:\nReview one failed outcome_feedback entry and add a note that distinguishes user mistake from system failure."
            )

        playground.ask_ai = fake_ask_ai
        result = playground.handle_user_input(q)
    finally:
        playground.ask_ai = original_ask_ai

    assert call_count["n"] == 1, f"Expected analytical path to use normal ask_ai call, got {call_count['n']} calls"
    lowered = result.lower()
    assert "deterministic runtime control" not in lowered, result
    assert "learning the wrong pattern" in lowered or "uncertainty" in lowered or "corroboration" in lowered, result


def test_build_specific_next_step_meta_override_is_concrete_repo_action():
    reset_agent_state()
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    ns = playground.build_specific_next_step("How is this system built?", focus, stage, "build")
    assert "playground.py" in ns.lower(), ns
    assert "python tests/run_regression.py" in ns.lower(), ns
    assert "add one small refinement" not in ns.lower(), ns


def test_safety_routing_answer_and_next_step():
    reset_agent_state()
    q = "What do I rely on in my project to keep it safe?"
    focus = "I prefer testing"
    stage = "Phase 4 action-layer refinement"
    memories = [
        {
            "category": "project",
            "value": "Uses the regression harness in tests/run_regression.py to keep changes safe",
        }
    ]
    ns = playground.build_specific_next_step(q, focus, stage, "build")
    assert "run_regression" in ns.lower(), ns

    al = playground.build_answer_line(q, focus, stage, "build", ns, memories=memories)
    assert "regression" in al.lower(), al


def test_extractor_validation_fixtures():
    from memory.extractors import run_extractor as rx

    path = PROJECT_ROOT / "tests" / "fixtures" / "extractor_validation_cases.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for case in data["cases"]:
        got = rx.validate_candidate(case["candidate"])
        want = case["expect_accept"]
        if want:
            assert got is not None, f"{case['id']}: expected accept"
            assert got["category"] == rx.normalize_category(case["candidate"]["category"])
        else:
            assert got is None, f"{case['id']}: expected reject, got {got!r}"

    long_val = "word " * 120
    assert rx.validate_candidate({"category": "project", "value": long_val}) is None


def test_extractor_effective_message_limit():
    import os

    from memory.extractors import run_extractor as rx

    old = os.environ.get("EXTRACT_MESSAGE_LIMIT")
    try:
        os.environ.pop("EXTRACT_MESSAGE_LIMIT", None)
        assert rx.effective_message_limit() == rx.DEFAULT_MESSAGE_LIMIT
        os.environ["EXTRACT_MESSAGE_LIMIT"] = "120"
        assert rx.effective_message_limit() == 120
        os.environ["EXTRACT_MESSAGE_LIMIT"] = "99999"
        assert rx.effective_message_limit() == rx.MAX_MESSAGE_LIMIT
        os.environ["EXTRACT_MESSAGE_LIMIT"] = "not-a-number"
        assert rx.effective_message_limit() == rx.DEFAULT_MESSAGE_LIMIT
    finally:
        if old is None:
            os.environ.pop("EXTRACT_MESSAGE_LIMIT", None)
        else:
            os.environ["EXTRACT_MESSAGE_LIMIT"] = old


def test_extractor_merge_load_and_allocate():
    """Extractor merges into existing file; unique ids for new keys (no OpenAI)."""
    import copy

    from memory.extractors import run_extractor as rx

    existing = {
        "memory_id": "mem_0005",
        "category": "goal",
        "value": "build a stable ai agent",
        "confidence": 0.60,
        "importance": 0.95,
        "status": "active",
        "memory_kind": "emerging",
        "evidence_count": 2,
        "first_seen": "msg_0",
        "last_seen": "msg_2",
        "trend": "reinforced",
        "source_refs": ["msg_0", "msg_2"],
    }
    key = rx.build_memory_key("goal", "build a stable ai agent")
    mem_map = {key: copy.deepcopy(existing)}
    rx.merge_memory(mem_map[key], 10)
    assert mem_map[key]["evidence_count"] == 3, "merge should bump evidence"
    assert "msg_10" in mem_map[key]["source_refs"], "merge should append msg ref"

    new_id = rx.allocate_memory_id(mem_map)
    assert new_id == "mem_0000", f"expected first free id, got {new_id}"
    mem_map["preference::i prefer dark mode"] = rx.new_memory_item(
        new_id, 0, "preference", "I prefer dark mode"
    )
    next_id = rx.allocate_memory_id(mem_map)
    assert next_id == "mem_0001", f"expected next free id, got {next_id}"


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


def test_save_memory_payload_repairs_missing_meta_and_items_shape():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        broken_payload = {"meta": "not-a-dict", "memory_items": "not-a-list"}
        playground.save_memory_payload(broken_payload)
        saved = playground.load_memory_payload()
        assert isinstance(saved.get("meta"), dict), saved
        assert isinstance(saved.get("memory_items"), list), saved
        assert saved["meta"].get("memory_count") == 0, saved


def test_save_memory_payload_enforces_unique_memory_ids():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {"memory_id": "mem_0001", "category": "goal", "value": "a"},
                {"memory_id": "mem_0001", "category": "goal", "value": "b"},
                {"category": "goal", "value": "c"},
            ],
        }
        playground.save_memory_payload(payload)
        saved = playground.load_memory_payload()
        ids = [m.get("memory_id") for m in saved.get("memory_items", [])]
        assert len(ids) == len(set(ids)), ids
        assert all(isinstance(i, str) and i.startswith("mem_") for i in ids), ids


def test_load_state_corrupt_json_uses_default_and_emits_health_event():
    reset_agent_state()
    with isolated_runtime_files() as (_, temp_state_path, _, _):
        temp_state_path.parent.mkdir(exist_ok=True)
        temp_state_path.write_text("{broken", encoding="utf-8")
        state = playground.load_state()
        events = persistence_core.consume_persistence_health_events()
        assert state == playground.DEFAULT_STATE.copy(), state
        assert any(e.get("event_type") == "state_load_fallback" for e in events), events


def test_load_project_journal_skips_malformed_lines_and_emits_health_event():
    reset_agent_state()
    with isolated_runtime_files() as (_, _, temp_journal_path, _):
        temp_journal_path.parent.mkdir(exist_ok=True)
        temp_journal_path.write_text(
            '{"entry_type":"conversation","user_input":"ok"}\n{bad json}\n{"entry_type":"state_command"}\n',
            encoding="utf-8",
        )
        entries = playground.load_project_journal()
        events = persistence_core.consume_persistence_health_events()
        assert len(entries) == 2, entries
        assert any(e.get("event_type") == "journal_malformed_lines_skipped" for e in events), events


def test_persistence_state_roundtrip_stress():
    reset_agent_state()
    with isolated_runtime_files():
        for i in range(120):
            playground.current_state["focus"] = f"focus-{i}"
            playground.current_state["stage"] = f"stage-{i}"
            playground.save_state()
            reloaded = playground.load_state()
            assert reloaded.get("focus") == f"focus-{i}", reloaded
            assert reloaded.get("stage") == f"stage-{i}", reloaded


def test_persistence_memory_roundtrip_stress_repairs_duplicates():
    reset_agent_state()
    with isolated_runtime_files():
        for i in range(60):
            payload = {
                "meta": {},
                "memory_items": [
                    {"memory_id": "mem_0001", "category": "goal", "value": f"goal-{i}"},
                    {"memory_id": "mem_0001", "category": "goal", "value": f"goal-{i}-b"},
                    {"category": "project", "value": f"project-{i}"},
                ],
            }
            playground.save_memory_payload(payload)
            loaded = playground.load_memory_payload()
            ids = [m.get("memory_id") for m in loaded.get("memory_items", [])]
            assert len(ids) == 3, ids
            assert len(ids) == len(set(ids)), ids
            assert loaded.get("meta", {}).get("memory_count") == 3, loaded


def test_project_journal_append_reload_stress():
    reset_agent_state()
    with isolated_runtime_files():
        original_max = playground.JOURNAL_MAX_ACTIVE_ENTRIES
        try:
            playground.JOURNAL_MAX_ACTIVE_ENTRIES = 1000
            for i in range(220):
                playground.append_project_journal(
                    entry_type="conversation",
                    user_input=f"load-test-{i}",
                    response_text="ok",
                    action_type="test",
                )
            rows = playground.load_project_journal()
            assert len(rows) == 220, len(rows)
            assert rows[-1].get("user_input") == "load-test-219", rows[-1]
        finally:
            playground.JOURNAL_MAX_ACTIVE_ENTRIES = original_max


def test_save_state_write_failure_emits_health_event():
    reset_agent_state()
    with isolated_runtime_files():
        original_atomic_write = persistence_core._atomic_write_text
        try:
            def fail_write(*args, **kwargs):
                raise OSError("simulated-state-write-failure")

            persistence_core._atomic_write_text = fail_write
            playground.current_state["focus"] = "fault-test-focus"
            playground.current_state["stage"] = "fault-test-stage"
            playground.save_state()
            events = persistence_core.consume_persistence_health_events()
            assert any(e.get("event_type") == "state_save_failure" for e in events), events
        finally:
            persistence_core._atomic_write_text = original_atomic_write


def test_save_memory_payload_write_failure_emits_health_event():
    reset_agent_state()
    with isolated_runtime_files():
        original_atomic_write = persistence_core._atomic_write_text
        try:
            def fail_write(*args, **kwargs):
                raise OSError("simulated-memory-write-failure")

            persistence_core._atomic_write_text = fail_write
            payload = {"meta": {}, "memory_items": [{"memory_id": "mem_0001", "category": "goal", "value": "x"}]}
            playground.save_memory_payload(payload)
            events = persistence_core.consume_persistence_health_events()
            assert any(e.get("event_type") == "memory_save_failure" for e in events), events
        finally:
            persistence_core._atomic_write_text = original_atomic_write


def test_handle_user_input_soak_stability_with_mocked_llm():
    reset_agent_state()
    with isolated_runtime_files():
        original_ask_ai = playground.ask_ai
        original_max = playground.JOURNAL_MAX_ACTIVE_ENTRIES
        try:
            playground.JOURNAL_MAX_ACTIVE_ENTRIES = 1000
            playground.ask_ai = lambda messages, system_prompt=None: (
                "Answer:\nStable response.\n\n"
                "Current state:\nFocus: ai-agent project\nStage: Phase 5 testing\nAction type: test\n\n"
                "Next step:\nRun one focused validation."
            )
            prompts = [
                "What should I do next?",
                "How do I prefer to learn?",
                "Set focus: ai-agent project",
                "Show state",
                "How is this system built?",
                "This failed for me.",
            ]
            for i in range(120):
                msg = prompts[i % len(prompts)]
                _ = playground.handle_user_input(msg)
            rows = playground.load_project_journal()
            assert len(rows) >= 80, len(rows)
        finally:
            playground.ask_ai = original_ask_ai
            playground.JOURNAL_MAX_ACTIVE_ENTRIES = original_max


def test_routing_snapshot_core_paths_stable():
    cases = [
        (
            "what should i do next?",
            "ai-agent project",
            "Phase 5 testing",
            "current behavior",
            "test",
        ),
        (
            "How is this system built mechanically and what prevents drift?",
            "ai-agent project",
            "Phase 5 testing",
            "current behavior",
            "test",
        ),
        (
            "Can you fetch a webpage with tools?",
            "ai-agent project",
            "Phase 5 testing",
            "agent_tools",
            "research",
        ),
    ]
    for text, focus, stage, expected_subtarget, expected_action in cases:
        assert playground.detect_subtarget(text, focus, stage) == expected_subtarget
        assert playground.infer_action_type(text, stage) == expected_action


def test_run_soak_script_smoke():
    cmd = [sys.executable, str(PROJECT_ROOT / "tests" / "run_soak.py"), "--iterations", "300", "--quiet"]
    completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    assert completed.returncode == 0, (
        f"run_soak.py smoke failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


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


def test_outcome_feedback_worked_is_detected_and_journaled():
    reset_agent_state()
    with isolated_runtime_files():
        original_ask_ai = playground.ask_ai
        try:
            playground.ask_ai = lambda messages, system_prompt=None: (
                "Answer:\nAck.\n\nCurrent state:\nFocus: ai-agent project\n"
                "Stage: Phase 4 action-layer refinement\nAction type: build\n\nNext step:\nContinue."
            )
            _ = playground.handle_user_input("That worked, thanks.")
            entries = playground.load_project_journal()
            outcome_entries = [e for e in entries if e.get("entry_type") == "outcome_feedback"]
            assert outcome_entries, "Expected outcome_feedback journal entry for explicit worked feedback"
            assert outcome_entries[-1].get("outcome") == "worked", outcome_entries[-1]
            assert outcome_entries[-1].get("focus") == playground.get_current_focus(), outcome_entries[-1]
            assert outcome_entries[-1].get("stage") == playground.get_current_stage(), outcome_entries[-1]
        finally:
            playground.ask_ai = original_ask_ai


def test_outcome_feedback_failed_is_detected_and_journaled():
    reset_agent_state()
    with isolated_runtime_files():
        original_ask_ai = playground.ask_ai
        try:
            playground.ask_ai = lambda messages, system_prompt=None: (
                "Answer:\nAck.\n\nCurrent state:\nFocus: ai-agent project\n"
                "Stage: Phase 4 action-layer refinement\nAction type: build\n\nNext step:\nContinue."
            )
            _ = playground.handle_user_input("This didn't work for me.")
            entries = playground.load_project_journal()
            outcome_entries = [e for e in entries if e.get("entry_type") == "outcome_feedback"]
            assert outcome_entries, "Expected outcome_feedback journal entry for explicit failed feedback"
            assert outcome_entries[-1].get("outcome") == "failed", outcome_entries[-1]
        finally:
            playground.ask_ai = original_ask_ai


def test_outcome_feedback_unrelated_input_does_not_create_outcome_entry():
    reset_agent_state()
    with isolated_runtime_files():
        original_ask_ai = playground.ask_ai
        try:
            playground.ask_ai = lambda messages, system_prompt=None: (
                "Answer:\nAck.\n\nCurrent state:\nFocus: ai-agent project\n"
                "Stage: Phase 4 action-layer refinement\nAction type: build\n\nNext step:\nContinue."
            )
            _ = playground.handle_user_input("What should I build next in playground.py?")
            entries = playground.load_project_journal()
            outcome_entries = [e for e in entries if e.get("entry_type") == "outcome_feedback"]
            assert not outcome_entries, f"Unexpected outcome_feedback entry for unrelated input: {outcome_entries}"
        finally:
            playground.ask_ai = original_ask_ai


def test_outcome_feedback_capture_keeps_existing_response_shape_intact():
    reset_agent_state()
    with isolated_runtime_files():
        original_ask_ai = playground.ask_ai
        try:
            playground.ask_ai = lambda messages, system_prompt=None: (
                "Answer:\nThis was useful.\n\nCurrent state:\nFocus: ai-agent project\n"
                "Stage: Phase 4 action-layer refinement\nAction type: build\n\nNext step:\nContinue."
            )
            result = playground.handle_user_input("That was useful.")
            assert "Answer:" in result, "Missing Answer section"
            assert "Current state:" in result, "Missing Current state section"
            assert "Next step:" in result, "Missing Next step section"
        finally:
            playground.ask_ai = original_ask_ai


def test_retrieve_recent_outcome_feedback_entries_returns_most_recent_only():
    reset_agent_state()
    with isolated_runtime_files():
        playground.append_project_journal(
            entry_type="conversation",
            user_input="normal note",
            response_text="ok",
            action_type="build",
        )
        playground.append_project_journal(
            entry_type="outcome_feedback",
            user_input="it worked",
            response_text="",
            action_type="build",
            extra_fields={"outcome": "worked"},
        )
        playground.append_project_journal(
            entry_type="outcome_feedback",
            user_input="not useful",
            response_text="",
            action_type="review",
            extra_fields={"outcome": "not_useful"},
        )
        playground.append_project_journal(
            entry_type="outcome_feedback",
            user_input="this failed",
            response_text="",
            action_type="fix",
            extra_fields={"outcome": "failed"},
        )
        rows = playground.retrieve_recent_outcome_feedback_entries(limit=2)
        assert len(rows) == 2, rows
        assert rows[0].get("outcome") == "failed", rows
        assert rows[1].get("outcome") == "not_useful", rows


def test_format_outcome_feedback_block_is_compact_and_stable():
    rows = [
        {"outcome": "worked", "user_input": "That worked for me."},
        {"outcome": "failed", "user_input": "This did not work after restart."},
    ]
    block = playground.format_outcome_feedback_block(rows)
    assert "- outcome=worked; user='That worked for me.'" in block, block
    assert "- outcome=failed; user='This did not work after restart.'" in block, block
    assert "\n" in block, block


def test_build_messages_includes_recent_outcome_feedback_for_relevant_prompt():
    reset_agent_state()
    with isolated_runtime_files():
        playground.append_project_journal(
            entry_type="outcome_feedback",
            user_input="That worked when I retried",
            response_text="",
            action_type="build",
            extra_fields={"outcome": "worked"},
        )
        playground.append_project_journal(
            entry_type="outcome_feedback",
            user_input="This failed for me",
            response_text="",
            action_type="fix",
            extra_fields={"outcome": "failed"},
        )
        prompt, _ = playground.build_messages("What should I do next to improve this?")
        assert "Recent outcome feedback:" in prompt, prompt
        assert "outcome=failed" in prompt or "outcome=worked" in prompt, prompt


def test_build_messages_omits_recent_outcome_feedback_for_irrelevant_prompt():
    reset_agent_state()
    with isolated_runtime_files():
        playground.append_project_journal(
            entry_type="outcome_feedback",
            user_input="That worked when I retried",
            response_text="",
            action_type="build",
            extra_fields={"outcome": "worked"},
        )
        prompt, _ = playground.build_messages("What is 2 plus 2?")
        assert "Recent outcome feedback:" not in prompt, prompt


def test_anti_repeat_guard_failed_feedback_avoids_blind_repeat():
    reset_agent_state()
    with isolated_runtime_files():
        playground.append_project_journal(
            entry_type="outcome_feedback",
            user_input="Open tests/run_regression.py first and inspect local code/test review",
            response_text="",
            action_type="research",
            extra_fields={"outcome": "failed"},
        )
        candidate = "Open tests/run_regression.py first and inspect local code/test review."
        adjusted, hit = playground.apply_recent_negative_outcome_anti_repeat_guard(
            "What should I do next?", candidate
        )
        assert hit is not None, "Expected failed feedback to trigger anti-repeat guard"
        assert adjusted != candidate, adjusted
        assert "failed move" in adjusted.lower() or "failure point" in adjusted.lower(), adjusted


def test_anti_repeat_guard_not_useful_feedback_avoids_blind_repeat():
    reset_agent_state()
    with isolated_runtime_files():
        playground.append_project_journal(
            entry_type="outcome_feedback",
            user_input="Review part of the system and continue building",
            response_text="",
            action_type="build",
            extra_fields={"outcome": "not_useful"},
        )
        candidate = "Review part of the system and continue building."
        adjusted, hit = playground.apply_recent_negative_outcome_anti_repeat_guard(
            "What should I do next?", candidate
        )
        assert hit is not None, "Expected not_useful feedback to trigger anti-repeat guard"
        assert adjusted != candidate, adjusted


def test_anti_repeat_guard_unrelated_negative_feedback_does_not_suppress_good_step():
    reset_agent_state()
    with isolated_runtime_files():
        playground.append_project_journal(
            entry_type="outcome_feedback",
            user_input="Use Upwork outreach for web contacts",
            response_text="",
            action_type="research",
            extra_fields={"outcome": "failed"},
        )
        candidate = "Run one state-command pass with set focus, set stage, and show state."
        adjusted, hit = playground.apply_recent_negative_outcome_anti_repeat_guard(
            "What should I do next?", candidate
        )
        assert hit is None, f"Unexpected anti-repeat trigger for unrelated feedback: {hit}"
        assert adjusted == candidate, adjusted


def test_anti_repeat_guard_positive_feedback_does_not_trigger():
    reset_agent_state()
    with isolated_runtime_files():
        playground.append_project_journal(
            entry_type="outcome_feedback",
            user_input="Run one state-command pass with set focus, set stage, and show state",
            response_text="",
            action_type="test",
            extra_fields={"outcome": "worked"},
        )
        candidate = "Run one state-command pass with set focus, set stage, and show state."
        adjusted, hit = playground.apply_recent_negative_outcome_anti_repeat_guard(
            "What should I do next?", candidate
        )
        assert hit is None, f"Positive outcomes should not trigger anti-repeat guard: {hit}"
        assert adjusted == candidate, adjusted


def test_recent_answer_history_is_bounded_and_latest_first():
    reset_agent_state()
    playground.recent_answer_history.clear()

    total = playground.RECENT_ANSWER_HISTORY_MAX + 3
    for i in range(total):
        playground.append_recent_answer_history(f"answer-{i}")

    assert len(playground.recent_answer_history) == playground.RECENT_ANSWER_HISTORY_MAX
    assert playground.recent_answer_history[-1] == f"answer-{total - 1}"

    block = playground.format_recent_answer_history_block()
    assert f"(recent_1) answer-{total - 1}" in block, block
    assert "answer-0" not in block, "Oldest entries should be evicted when history is full"


def test_build_messages_includes_recent_assistant_outputs_context():
    reset_agent_state()
    playground.append_recent_answer_history("Answer: first result")
    playground.append_recent_answer_history("Answer: second result")

    system_prompt, _ = playground.build_messages("Why did the last response shift?")

    assert "Recent assistant outputs (session, bounded):" in system_prompt
    assert "(recent_1) Answer: second result" in system_prompt
    assert "(recent_2) Answer: first result" in system_prompt


def test_build_messages_includes_stable_user_context_for_personal_question():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_pref",
                    "category": "preference",
                    "value": "I prefer step-by-step work with verification",
                    "confidence": 0.8,
                    "importance": 0.8,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                }
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("How do I prefer to work?")
        assert "Stable user context:" in prompt
        assert "Stable user context guidance:" in prompt
        assert "I prefer step-by-step work with verification" in prompt


def test_build_messages_omits_stable_user_context_for_unrelated_prompt():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_pref",
                    "category": "preference",
                    "value": "I prefer step-by-step work with verification",
                    "confidence": 0.8,
                    "importance": 0.8,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                }
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("Summarize this URL content.")
        assert "Stable user context:" not in prompt
        assert "Stable user context guidance:" not in prompt


def test_is_user_purpose_memory_detects_goal_with_income_signal():
    mem = {
        "category": "goal",
        "value": "My goal is stable income and survival in real life",
    }
    assert playground.is_user_purpose_memory(mem)
    assert not playground.is_user_purpose_memory({"category": "preference", "value": "I prefer dark mode"})


def test_build_messages_includes_user_core_purpose_when_emotional_signal_and_purpose_memory():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_purpose",
                    "category": "goal",
                    "value": "My goal is income and survival; this work must support real-life progress",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_safety",
                    "category": "project",
                    "value": "Uses the regression harness in tests/run_regression.py to keep changes safe",
                    "confidence": 0.75,
                    "importance": 1.0,
                    "memory_kind": "emerging",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages(
            "I need to depend on this: does my income and survival matter for how you answer?"
        )
        assert "User core purpose:" in prompt
        assert "User core purpose guidance:" in prompt
        assert "USER CORE PURPOSE PRIORITY" in prompt
        assert "income and survival" in prompt
        assert "real-world goal" in prompt


def test_build_messages_personal_context_reflects_user_purpose_survival_alignment():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "I rely on shipping work that protects my ability to survive and earn money",
                    "confidence": 0.8,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What matters to me in life?")
        assert "User core purpose:" in prompt
        assert "survive" in prompt or "money" in prompt


def test_build_messages_does_not_drop_user_core_purpose_for_strong_purpose_memory():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_id",
                    "category": "identity",
                    "value": "I am someone for whom this project is important to life stability",
                    "confidence": 0.78,
                    "importance": 0.88,
                    "memory_kind": "stable",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What is important about me?")
        assert "User core purpose:" in prompt
        assert "life stability" in prompt


def test_build_messages_unrelated_prompt_does_not_trigger_user_core_purpose_block():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What is 2 plus 2?")
        assert "User core purpose:" not in prompt
        assert "USER CORE PURPOSE PRIORITY" not in prompt
        assert "ANSWER OPENING (user-purpose):" not in prompt
        assert "ANTI-SYSTEM-LEADING:" not in prompt
        assert "Self-alignment check:" not in prompt
        assert "Next-step alignment:" not in prompt
        assert "Current-context grounding:" not in prompt
        assert "Proactive initiative:" not in prompt
        assert "Confidence filter:" not in prompt
        assert "Reality-constrained action selection:" not in prompt


def test_build_messages_confidence_filter_when_user_purpose_present():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages(
            "I need income progress—what high-impact step should I take?"
        )
        assert "Confidence filter:" in prompt
        assert "meaningful progress" in prompt
        assert "explore options" in prompt
        assert "consider possibilities" in prompt
        assert "without needing further clarification" in prompt
        assert "Look into possible ways to make money online" in prompt
        assert "Message 5 potential clients today" in prompt
        assert prompt.count("Use exactly these three sections in this order:") == 1


def test_build_messages_reality_constrained_action_selection_when_user_purpose_present():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("I need realistic money progress right now.")
        assert "Reality-constrained action selection:" in prompt
        assert "client-ready technical capability" in prompt
        assert "Do not infer professional readiness from current project focus alone." in prompt
        assert "minimal setup" in prompt
        assert "fast feedback" in prompt
        assert "Create an AI testing service and post it online." in prompt
        assert "offer it to 3 people" in prompt
        assert prompt.count("Use exactly these three sections in this order:") == 1


def test_build_messages_first_money_bias_appears_for_money_query_with_user_purpose():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("How can I make money today?")
        assert "First-money bias:" in prompt
        assert "first small amount ($5-$20)" in prompt
        assert "delay earning" in prompt
        assert "same day" in prompt
        assert "Practice testing on GitHub projects first." in prompt
        assert "simple manual test for a small fee" in prompt
        assert prompt.count("Use exactly these three sections in this order:") == 1


def test_build_messages_first_money_bias_not_added_for_non_money_query():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What matters to me in life?")
        assert "User core purpose:" in prompt
        assert "First-money bias:" not in prompt


def test_build_messages_single_move_compression_for_exact_next_step_money_prompt():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages(
            "What is the exact next step I should take to make money today?"
        )
        assert "Single-move compression:" in prompt
        assert "general lane" in prompt
        assert "one action, one place, and one immediate objective" in prompt
        assert "Open Upwork now" in prompt
        assert prompt.count("Use exactly these three sections in this order:") == 1


def test_build_messages_single_move_compression_not_added_for_non_money_query():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What matters to me in life?")
        assert "Single-move compression:" not in prompt


def test_build_messages_decisiveness_context_lock_fallback_present_for_money_exact_step_prompt():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages(
            "What is the exact next step to make money now, and how does this system help?"
        )
        assert "Decisiveness:" in prompt
        assert "Avoid hedging, multiple options, or soft language." in prompt
        assert "Context lock:" in prompt
        assert "NEVER answer meta/system questions with generic AI explanations" in prompt
        assert "Fallback intelligence:" not in prompt
        assert prompt.count("Use exactly these three sections in this order:") == 1


def test_build_messages_decisiveness_not_added_for_non_money_query():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What matters to me in life?")
        assert "Decisiveness:" not in prompt


def test_build_messages_context_lock_added_for_meta_non_money_query():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("How is this AI system built right now?")
        assert "Context lock:" in prompt
        assert "NEVER answer meta/system questions with generic AI explanations" in prompt
        assert "Generic AI explanations are only allowed if explicitly requested." in prompt
        assert "Frame answers in terms of \"your system\" not \"AI in general\"." in prompt
        assert "Decisiveness:" not in prompt
        assert "transformer" not in prompt.lower()


def test_build_messages_fallback_intelligence_added_for_research_tool_non_money_query():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("Can you fetch this website and summarize it?")
        assert "Fallback intelligence:" in prompt
        assert "DO NOT wait for clarification." in prompt
        assert "Infer a reasonable research direction from context and proceed." in prompt
        assert "Suggest one concrete next research action immediately." in prompt
        assert "one topic, one platform or method, one immediate action." in prompt
        assert "Decisiveness:" not in prompt
        assert "tell me what to research" not in prompt.lower()


def test_build_messages_meta_override_forces_structured_answer_path_in_open_mode():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("How is this system built and how does it work?")
        assert "The exact answer line to use is:" in prompt
        assert "playground.py" in prompt.lower() or "tests/run_regression.py" in prompt.lower()
        assert "OPEN CONVERSATION MODE" not in prompt


def test_build_messages_vague_research_override_forces_structured_answer_path_in_open_mode():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("Do the research.")
        assert "The exact answer line to use is:" in prompt
        assert "one concrete research move" in prompt
        assert "OPEN CONVERSATION MODE" not in prompt


def test_build_messages_normal_open_conversation_still_unchanged_without_override_trigger():
    reset_agent_state()
    prompt, _ = playground.build_messages("What is 2 plus 2?")
    assert "OPEN CONVERSATION MODE" in prompt
    assert "The exact answer line to use is:" not in prompt


def test_build_messages_proactive_initiative_when_user_purpose_present():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What matters to me for income?")
        assert "Proactive initiative:" in prompt
        assert "more than one next action" in prompt
        assert "extend the current direction" in prompt
        assert "natural continuation" in prompt
        assert "Here are several ways you could make money" in prompt
        assert "Based on what we just discussed" in prompt
        assert 'existing "Next step:" field' in prompt


def test_build_messages_proactive_no_extra_titan_output_sections():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What matters to me in life?")
        assert prompt.count("Use exactly these three sections in this order:") == 1


def test_build_messages_current_context_grounding_when_user_purpose_present():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("I need income progress—what should I do?")
        assert "Current-context grounding:" in prompt
        assert "generic money-making strategies" in prompt
        assert "hypothetical capability" in prompt
        assert "started today" in prompt
        assert "Reduce abstraction" in prompt
        assert "Offer AI testing services online" in prompt
        assert "manual testing gig" in prompt


def test_build_messages_next_step_alignment_present_when_user_purpose_memory_present():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("I need to know what matters for my income progress.")
        assert "Next-step alignment:" in prompt
        assert "only system-internal" in prompt
        assert "Bad:" in prompt and "Add more tests to the module" in prompt
        assert "Good:" in prompt and "first $X result" in prompt


def test_build_messages_next_step_alignment_preserves_prior_sections():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What matters to me in life?")
        assert "User core purpose:" in prompt
        assert "Self-alignment check:" in prompt
        assert "Next-step alignment:" in prompt
        assert "Current-context grounding:" in prompt
        assert "Proactive initiative:" in prompt
        assert "Confidence filter:" in prompt
        assert "Reality-constrained action selection:" in prompt
        assert "OUTPUT FORMAT RULES:" in prompt
        pos_self = prompt.find("Self-alignment check:")
        pos_next = prompt.find("Next-step alignment:")
        assert pos_self != -1 and pos_next != -1
        assert pos_self < pos_next
        pos_ctx = prompt.find("Current-context grounding:")
        assert pos_ctx != -1
        assert pos_next < pos_ctx
        pos_pro = prompt.find("Proactive initiative:")
        assert pos_pro != -1
        assert pos_ctx < pos_pro
        pos_conf = prompt.find("Confidence filter:")
        assert pos_conf != -1
        assert pos_pro < pos_conf
        pos_real = prompt.find("Reality-constrained action selection:")
        assert pos_real != -1
        assert pos_conf < pos_real


def test_build_messages_self_alignment_check_present_when_user_purpose_memory_present():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("I need to know what matters for my survival.")
        assert "Self-alignment check:" in prompt
        assert "re-anchor it to the user's purpose" in prompt


def test_build_messages_self_alignment_preserves_prior_user_purpose_sections():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What matters to me and why is progress important?")
        assert "User core purpose:" in prompt
        assert "User core purpose guidance:" in prompt
        assert "ANSWER OPENING (user-purpose):" in prompt
        assert "Self-alignment check:" in prompt
        pos_guidance = prompt.find("User core purpose guidance:")
        pos_align = prompt.find("Self-alignment check:")
        assert pos_guidance != -1 and pos_align != -1
        assert pos_guidance < pos_align


def test_build_messages_user_purpose_prompt_includes_answer_anchoring_anti_leading_and_example():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_purpose",
                    "category": "goal",
                    "value": "My goal is income and survival; this work must support real-life progress",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_safety",
                    "category": "project",
                    "value": "Uses the regression harness in tests/run_regression.py to keep changes safe",
                    "confidence": 0.75,
                    "importance": 1.0,
                    "memory_kind": "emerging",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages(
            "I need to know: does my survival depend on how reliable this system is?"
        )
        assert "ANSWER OPENING (user-purpose):" in prompt
        assert "ANTI-SYSTEM-LEADING:" in prompt
        assert "Bad opening:" in prompt and "Good opening:" in prompt
        assert "first sentence" in prompt.lower()


def test_build_messages_user_purpose_answer_shaping_precedes_supporting_memory_block():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_purpose",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_safety",
                    "category": "project",
                    "value": "Uses the regression harness in tests/run_regression.py",
                    "confidence": 0.75,
                    "importance": 1.0,
                    "memory_kind": "emerging",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What matters to me and why is progress important?")
        pos_opening = prompt.find("ANSWER OPENING (user-purpose):")
        pos_support = prompt.find("Supporting memory:")
        assert pos_opening != -1 and pos_support != -1
        assert pos_opening < pos_support


def test_build_messages_user_purpose_prompt_keeps_system_detail_secondary_not_removed():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_purpose",
                    "category": "goal",
                    "value": "My goal is income and survival in real life",
                    "confidence": 0.85,
                    "importance": 0.95,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("I rely on this work for important progress. Explain.")
        assert "secondary" in prompt.lower()
        assert "later" in prompt.lower() or "after" in prompt.lower()


def test_build_messages_stable_user_context_avoids_same_lane_duplicate_crowding():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_pref_strong",
                    "category": "preference",
                    "value": "I prefer step-by-step work with verification in small increments",
                    "confidence": 0.82,
                    "importance": 0.85,
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_pref_weak",
                    "category": "preference",
                    "value": "I prefer step by step work with verification in small increments",
                    "confidence": 0.62,
                    "importance": 0.75,
                    "memory_kind": "emerging",
                    "evidence_count": 2,
                    "last_seen": "msg_3",
                    "trend": "new",
                    "source_refs": ["msg_3"],
                },
                {
                    "memory_id": "mem_goal",
                    "category": "goal",
                    "value": "My goal is stable, test-protected delivery",
                    "confidence": 0.77,
                    "importance": 0.95,
                    "memory_kind": "emerging",
                    "evidence_count": 3,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("How should we work together and what is my goal?")
        assert "Stable user context:" in prompt
        stable_section = prompt.split("Stable user context:\n", 1)[1]
        stable_section = stable_section.split("\n\nStable user context guidance:", 1)[0]
        assert stable_section.count("(preference)") == 1, prompt


def test_detect_recent_answer_relevance_false_when_history_empty():
    reset_agent_state()
    playground.recent_answer_history.clear()
    assert not playground.detect_recent_answer_relevance("Why did the last answer change?")


def test_get_best_recent_answer_match_none_when_history_empty():
    reset_agent_state()
    playground.recent_answer_history.clear()
    assert playground.get_best_recent_answer_match("Why did the last answer change?") is None


def test_get_best_recent_answer_match_selects_more_relevant_output():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history("State persistence survives restart and reopen.")
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    q = "Why does detect_subtarget routing trigger strict mode here?"
    best = playground.get_best_recent_answer_match(q)
    assert best is not None
    assert "detect_subtarget" in best["matched_text"], best
    assert best["overlap_count"] >= 3, best


def test_get_best_recent_answer_match_prefers_more_recent_on_equal_strength():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "detect_subtarget routing issues can trigger strict mode behavior."
    )
    playground.append_recent_answer_history(
        "strict mode routing issues can trigger detect_subtarget behavior."
    )
    q = "detect_subtarget routing strict mode issues"
    best = playground.get_best_recent_answer_match(q)
    assert best is not None
    assert (
        best["matched_text"]
        == "strict mode routing issues can trigger detect_subtarget behavior."
    ), best


def test_get_best_recent_answer_match_relevance_beats_recency():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "detect_subtarget routing strict mode gating behavior details."
    )
    playground.append_recent_answer_history("detect_subtarget routing details.")
    q = "detect_subtarget routing strict mode gating behavior details"
    best = playground.get_best_recent_answer_match(q)
    assert best is not None
    assert (
        best["matched_text"]
        == "detect_subtarget routing strict mode gating behavior details."
    ), best


def test_detect_recent_answer_relevance_unchanged_with_equal_strength_candidates():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "detect_subtarget routing issues can trigger strict mode behavior."
    )
    playground.append_recent_answer_history(
        "strict mode routing issues can trigger detect_subtarget behavior."
    )
    q = "detect_subtarget routing strict mode issues"
    assert playground.detect_recent_answer_relevance(q)


def test_detect_recent_answer_relevance_true_on_related_followup():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    q = "Why does detect_subtarget routing trigger strict mode here?"
    assert playground.detect_recent_answer_relevance(q)


def test_detect_recent_answer_relevance_false_for_short_unrelated_shared_token():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    q = "routing weather"
    assert not playground.detect_recent_answer_relevance(q)


def test_detect_recent_answer_relevance_false_for_generic_tokens_only():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Project system agent memory test stage focus current next step."
    )
    q = "project system agent memory test next step"
    assert not playground.detect_recent_answer_relevance(q)


def test_detect_recent_answer_relevance_true_after_generic_token_filtering():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    q = "detect_subtarget strict mode routing"
    assert playground.detect_recent_answer_relevance(q)


def test_is_strong_recent_answer_match_false_for_none():
    reset_agent_state()
    assert not playground.is_strong_recent_answer_match(None)


def test_is_strong_recent_answer_match_true_for_high_overlap():
    reset_agent_state()
    match = {"matched_text": "x", "overlap_count": 3, "overlap_ratio": 0.4}
    assert playground.is_strong_recent_answer_match(match)


def test_is_strong_recent_answer_match_false_for_weak_but_relevant():
    reset_agent_state()
    match = {"matched_text": "x", "overlap_count": 2, "overlap_ratio": 0.4}
    assert not playground.is_strong_recent_answer_match(match)


def test_build_messages_adds_reflection_guidance_only_when_relevant():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )

    related_prompt, _ = playground.build_messages(
        "Can you refine why detect_subtarget routing triggers strict mode?"
    )
    assert "Recent-answer reflection guidance:" in related_prompt

    unrelated_prompt, _ = playground.build_messages("What color is the sky in this context?")
    assert "Recent-answer reflection guidance:" not in unrelated_prompt


def test_build_messages_includes_relevant_recent_output_only_when_relevant():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )

    related_prompt, _ = playground.build_messages(
        "Can you refine why detect_subtarget routing triggers strict mode?"
    )
    assert "Relevant recent assistant output:" in related_prompt
    assert "detect_subtarget can trigger strict-mode gating" in related_prompt

    unrelated_prompt, _ = playground.build_messages("Summarize the weather forecast briefly.")
    assert "Relevant recent assistant output:" not in unrelated_prompt


def test_build_messages_includes_matched_output_for_strong_match():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    prompt, _ = playground.build_messages(
        "Can you refine why detect_subtarget routing triggers strict mode?"
    )
    assert "Relevant recent assistant output:" in prompt
    assert "detect_subtarget can trigger strict-mode gating" in prompt


def test_build_messages_omits_matched_output_for_weak_but_relevant_followup():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    weak_relevant_q = "strict mode weather climate today"
    assert playground.detect_recent_answer_relevance(weak_relevant_q)
    best = playground.get_best_recent_answer_match(weak_relevant_q)
    assert best is not None
    assert not playground.is_strong_recent_answer_match(best)

    prompt, _ = playground.build_messages(weak_relevant_q)
    assert "Relevant recent assistant output:" not in prompt


def test_build_messages_keeps_followup_guidance_when_matched_output_omitted():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    weak_relevant_q = "strict mode weather climate today"
    prompt, _ = playground.build_messages(weak_relevant_q)
    assert "Relevant recent assistant output:" not in prompt
    assert "Recent-answer follow-up type: continuation" in prompt


def test_detect_recent_answer_contradiction_cue_false_for_normal_followup():
    reset_agent_state()
    matched = "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    q = "Can you clarify detect_subtarget routing for this case?"
    assert not playground.detect_recent_answer_contradiction_cue(q, matched)


def test_detect_recent_answer_contradiction_cue_false_for_unrelated_but():
    reset_agent_state()
    matched = "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    q = "But what color is the sky today?"
    assert playground.detect_recent_answer_contradiction_cue(q, matched)
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(matched)
    prompt, _ = playground.build_messages(q)
    assert "Recent-answer contradiction/refinement cue:" not in prompt


def test_detect_recent_answer_contradiction_cue_false_for_unrelated_no():
    reset_agent_state()
    matched = "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    q = "No, tell me about weather patterns."
    assert playground.detect_recent_answer_contradiction_cue(q, matched)
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(matched)
    prompt, _ = playground.build_messages(q)
    assert "Recent-answer contradiction/refinement cue:" not in prompt


def test_detect_recent_answer_contradiction_cue_true_for_revision_followup():
    reset_agent_state()
    matched = "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    q = "You said that before, but that's wrong after we changed that."
    assert playground.detect_recent_answer_contradiction_cue(q, matched)


def test_detect_recent_answer_followup_type_none_without_match():
    reset_agent_state()
    q = "Can you refine that?"
    assert playground.detect_recent_answer_followup_type(q, None) is None


def test_detect_recent_answer_followup_type_continuation_for_related_followup():
    reset_agent_state()
    playground.recent_answer_history.clear()
    matched = "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    playground.append_recent_answer_history(matched)
    q = "Continue on detect_subtarget strict mode routing behavior."
    assert playground.detect_recent_answer_followup_type(q, matched) == "continuation"


def test_detect_recent_answer_followup_type_clarification_for_precision_prompt():
    reset_agent_state()
    playground.recent_answer_history.clear()
    matched = "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    playground.append_recent_answer_history(matched)
    q = "Can you clarify that and be specific about detect_subtarget?"
    assert playground.detect_recent_answer_followup_type(q, matched) == "clarification"


def test_detect_recent_answer_followup_type_correction_for_revision_prompt():
    reset_agent_state()
    playground.recent_answer_history.clear()
    matched = "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    playground.append_recent_answer_history(matched)
    q = "You said that earlier, but that's wrong now."
    assert playground.detect_recent_answer_followup_type(q, matched) == "correction"


def test_build_messages_adds_continuation_guidance_only_for_continuation():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    prompt, _ = playground.build_messages(
        "Continue on detect_subtarget strict mode routing behavior."
    )
    assert "Recent-answer follow-up type: continuation" in prompt
    assert "Recent-answer follow-up type: clarification" not in prompt
    assert "Recent-answer follow-up type: correction" not in prompt


def test_build_messages_adds_clarification_guidance_only_for_clarification():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    prompt, _ = playground.build_messages(
        "Can you clarify and explain more precisely the detect_subtarget routing strict mode gating issue?"
    )
    assert "Recent-answer follow-up type: clarification" in prompt
    assert "Recent-answer follow-up type: continuation" not in prompt
    assert "Recent-answer follow-up type: correction" not in prompt


def test_build_messages_adds_correction_guidance_only_for_correction():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    prompt, _ = playground.build_messages(
        "You said that earlier, but that's wrong for detect_subtarget routing strict mode gating now."
    )
    assert "Recent-answer follow-up type: correction" in prompt
    assert "Recent-answer follow-up type: continuation" not in prompt
    assert "Recent-answer follow-up type: clarification" not in prompt


def test_build_messages_adds_no_followup_type_guidance_for_unrelated_prompt():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    prompt, _ = playground.build_messages("What is the weather this weekend?")
    assert "Recent-answer follow-up type:" not in prompt


def test_build_messages_adds_contradiction_guidance_and_self_correction_rule():
    reset_agent_state()
    playground.recent_answer_history.clear()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    prompt, _ = playground.build_messages(
        "You said that before, but detect_subtarget routing strict mode is wrong."
    )
    assert "Recent-answer contradiction/refinement cue:" in prompt
    assert 'Prefer phrasing like "Let me refine that:" or "More precisely:".' in prompt

    neutral_prompt, _ = playground.build_messages(
        "Can you clarify detect_subtarget routing for this case?"
    )
    assert "Recent-answer contradiction/refinement cue:" not in neutral_prompt
    assert 'Prefer phrasing like "Let me refine that:" or "More precisely:".' not in neutral_prompt


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
        ("is_durable_user_memory_true_for_reinforced_stable_preference", test_is_durable_user_memory_true_for_reinforced_stable_preference),
        ("is_durable_user_memory_false_for_weak_temporary_project", test_is_durable_user_memory_false_for_weak_temporary_project),
        ("is_personal_context_question_detection", test_is_personal_context_question_detection),
        ("is_personal_context_question_false_for_non_personal_prompt", test_is_personal_context_question_false_for_non_personal_prompt),
        ("prefer_stronger_personal_memory_reinforced_preference_beats_weaker", test_prefer_stronger_personal_memory_reinforced_preference_beats_weaker),
        ("prefer_stronger_personal_memory_stable_beats_tentative_when_similar", test_prefer_stronger_personal_memory_stable_beats_tentative_when_similar),
        ("prefer_stronger_personal_memory_runtime_last_seen_wins_final_tie", test_prefer_stronger_personal_memory_runtime_last_seen_wins_final_tie),
        ("score_personal_memory_temporal_strength_higher_for_reinforced_runtime_stable", test_score_personal_memory_temporal_strength_higher_for_reinforced_runtime_stable),
        ("score_personal_memory_temporal_strength_bounded", test_score_personal_memory_temporal_strength_bounded),
        ("retrieve_personal_context_memory_prefers_reinforced_runtime_when_overlapping_similar", test_retrieve_personal_context_memory_prefers_reinforced_runtime_when_overlapping_similar),
        ("retrieve_personal_context_memory_stale_weak_import_does_not_crowd_reinforced", test_retrieve_personal_context_memory_stale_weak_import_does_not_crowd_reinforced),
        ("retrieve_personal_context_memory_strong_stable_import_beats_weaker_runtime_emerging", test_retrieve_personal_context_memory_strong_stable_import_beats_weaker_runtime_emerging),
        ("retrieve_personal_context_memory_diversity_intact_after_temporal_preference", test_retrieve_personal_context_memory_diversity_intact_after_temporal_preference),
        ("build_messages_stable_user_context_compact_for_personal_question_after_temporal", test_build_messages_stable_user_context_compact_for_personal_question_after_temporal),
        ("retrieve_personal_context_memory_prefers_durable_identity_preference_goal", test_retrieve_personal_context_memory_prefers_durable_identity_preference_goal),
        ("retrieve_personal_context_memory_weak_transient_rows_do_not_dominate", test_retrieve_personal_context_memory_weak_transient_rows_do_not_dominate),
        ("retrieve_personal_context_memory_suppresses_near_duplicate_same_category_crowding", test_retrieve_personal_context_memory_suppresses_near_duplicate_same_category_crowding),
        ("retrieve_personal_context_memory_prefers_stronger_overlapping_personal_memory", test_retrieve_personal_context_memory_prefers_stronger_overlapping_personal_memory),
        ("retrieve_personal_context_memory_keeps_useful_diversity_across_categories", test_retrieve_personal_context_memory_keeps_useful_diversity_across_categories),
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
        ("safety_query_prioritizes_regression_memory", test_safety_query_prioritizes_regression_memory),
        ("open_conversation_prompt_not_strict_canned", test_open_conversation_prompt_not_strict_canned),
        ("agent_purpose_routing_not_stack_boilerplate", test_agent_purpose_routing_not_stack_boilerplate),
        ("north_star_paradox_not_memory_retrieval_or_state_command", test_north_star_paradox_not_memory_retrieval_or_state_command),
        ("infer_action_type_debugging_not_fix", test_infer_action_type_debugging_not_fix),
        ("negated_memory_retrieval_does_not_force_workflow", test_negated_memory_retrieval_does_not_force_workflow),
        ("journal_question_not_restart_persistence_hijack", test_journal_question_not_restart_persistence_hijack),
        ("goal_vs_preference_taxonomy_not_memory_behavior", test_goal_vs_preference_taxonomy_not_memory_behavior),
        ("negated_recall_memory_skips_workflow", test_negated_recall_memory_skips_workflow),
        ("agent_tools_routing_answer_and_next_step", test_agent_tools_routing_answer_and_next_step),
        ("agent_meta_routing_answer_and_next_step", test_agent_meta_routing_answer_and_next_step),
        ("build_answer_line_meta_override_anchors_to_project_system_not_generic_ai", test_build_answer_line_meta_override_anchors_to_project_system_not_generic_ai),
        ("build_answer_line_vague_research_override_returns_concrete_action_no_passive_clarification", test_build_answer_line_vague_research_override_returns_concrete_action_no_passive_clarification),
        ("build_answer_line_vague_research_web_intent_is_web_oriented_not_repo", test_build_answer_line_vague_research_web_intent_is_web_oriented_not_repo),
        ("build_answer_line_vague_research_repo_intent_is_repo_oriented", test_build_answer_line_vague_research_repo_intent_is_repo_oriented),
        ("build_answer_line_vague_research_live_web_prompt_routes_web_not_repo", test_build_answer_line_vague_research_live_web_prompt_routes_web_not_repo),
        ("handle_user_input_vague_research_live_web_prompt_bypasses_llm_and_stays_web_oriented", test_handle_user_input_vague_research_live_web_prompt_bypasses_llm_and_stays_web_oriented),
        ("handle_user_input_meta_trust_prompt_triggers_deterministic_override_without_repo_fallback", test_handle_user_input_meta_trust_prompt_triggers_deterministic_override_without_repo_fallback),
        ("handle_user_input_meta_analytical_learning_integrity_does_not_use_stock_deterministic_override", test_handle_user_input_meta_analytical_learning_integrity_does_not_use_stock_deterministic_override),
        ("build_specific_next_step_meta_override_is_concrete_repo_action", test_build_specific_next_step_meta_override_is_concrete_repo_action),
        ("safety_routing_answer_and_next_step", test_safety_routing_answer_and_next_step),
        ("extractor_validation_fixtures", test_extractor_validation_fixtures),
        ("extractor_effective_message_limit", test_extractor_effective_message_limit),
        ("extractor_merge_load_and_allocate", test_extractor_merge_load_and_allocate),
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
        ("save_memory_payload_repairs_missing_meta_and_items_shape", test_save_memory_payload_repairs_missing_meta_and_items_shape),
        ("save_memory_payload_enforces_unique_memory_ids", test_save_memory_payload_enforces_unique_memory_ids),
        ("load_state_corrupt_json_uses_default_and_emits_health_event", test_load_state_corrupt_json_uses_default_and_emits_health_event),
        ("load_project_journal_skips_malformed_lines_and_emits_health_event", test_load_project_journal_skips_malformed_lines_and_emits_health_event),
        ("persistence_state_roundtrip_stress", test_persistence_state_roundtrip_stress),
        ("persistence_memory_roundtrip_stress_repairs_duplicates", test_persistence_memory_roundtrip_stress_repairs_duplicates),
        ("project_journal_append_reload_stress", test_project_journal_append_reload_stress),
        ("save_state_write_failure_emits_health_event", test_save_state_write_failure_emits_health_event),
        ("save_memory_payload_write_failure_emits_health_event", test_save_memory_payload_write_failure_emits_health_event),
        ("handle_user_input_soak_stability_with_mocked_llm", test_handle_user_input_soak_stability_with_mocked_llm),
        ("routing_snapshot_core_paths_stable", test_routing_snapshot_core_paths_stable),
        ("run_soak_script_smoke", test_run_soak_script_smoke),
        ("project_journal_records_events", test_project_journal_records_events),
        ("project_journal_auto_compaction", test_project_journal_auto_compaction),
        ("project_journal_manual_flush_command", test_project_journal_manual_flush_command),
        ("outcome_feedback_worked_is_detected_and_journaled", test_outcome_feedback_worked_is_detected_and_journaled),
        ("outcome_feedback_failed_is_detected_and_journaled", test_outcome_feedback_failed_is_detected_and_journaled),
        ("outcome_feedback_unrelated_input_does_not_create_outcome_entry", test_outcome_feedback_unrelated_input_does_not_create_outcome_entry),
        ("outcome_feedback_capture_keeps_existing_response_shape_intact", test_outcome_feedback_capture_keeps_existing_response_shape_intact),
        ("retrieve_recent_outcome_feedback_entries_returns_most_recent_only", test_retrieve_recent_outcome_feedback_entries_returns_most_recent_only),
        ("format_outcome_feedback_block_is_compact_and_stable", test_format_outcome_feedback_block_is_compact_and_stable),
        ("build_messages_includes_recent_outcome_feedback_for_relevant_prompt", test_build_messages_includes_recent_outcome_feedback_for_relevant_prompt),
        ("build_messages_omits_recent_outcome_feedback_for_irrelevant_prompt", test_build_messages_omits_recent_outcome_feedback_for_irrelevant_prompt),
        ("anti_repeat_guard_failed_feedback_avoids_blind_repeat", test_anti_repeat_guard_failed_feedback_avoids_blind_repeat),
        ("anti_repeat_guard_not_useful_feedback_avoids_blind_repeat", test_anti_repeat_guard_not_useful_feedback_avoids_blind_repeat),
        ("anti_repeat_guard_unrelated_negative_feedback_does_not_suppress_good_step", test_anti_repeat_guard_unrelated_negative_feedback_does_not_suppress_good_step),
        ("anti_repeat_guard_positive_feedback_does_not_trigger", test_anti_repeat_guard_positive_feedback_does_not_trigger),
        ("recent_answer_history_is_bounded_and_latest_first", test_recent_answer_history_is_bounded_and_latest_first),
        ("build_messages_includes_recent_assistant_outputs_context", test_build_messages_includes_recent_assistant_outputs_context),
        ("build_messages_includes_stable_user_context_for_personal_question", test_build_messages_includes_stable_user_context_for_personal_question),
        ("build_messages_omits_stable_user_context_for_unrelated_prompt", test_build_messages_omits_stable_user_context_for_unrelated_prompt),
        ("is_user_purpose_memory_detects_goal_with_income_signal", test_is_user_purpose_memory_detects_goal_with_income_signal),
        ("build_messages_includes_user_core_purpose_when_emotional_signal_and_purpose_memory", test_build_messages_includes_user_core_purpose_when_emotional_signal_and_purpose_memory),
        ("build_messages_personal_context_reflects_user_purpose_survival_alignment", test_build_messages_personal_context_reflects_user_purpose_survival_alignment),
        ("build_messages_does_not_drop_user_core_purpose_for_strong_purpose_memory", test_build_messages_does_not_drop_user_core_purpose_for_strong_purpose_memory),
        ("build_messages_unrelated_prompt_does_not_trigger_user_core_purpose_block", test_build_messages_unrelated_prompt_does_not_trigger_user_core_purpose_block),
        ("build_messages_self_alignment_check_present_when_user_purpose_memory_present", test_build_messages_self_alignment_check_present_when_user_purpose_memory_present),
        ("build_messages_self_alignment_preserves_prior_user_purpose_sections", test_build_messages_self_alignment_preserves_prior_user_purpose_sections),
        ("build_messages_next_step_alignment_present_when_user_purpose_memory_present", test_build_messages_next_step_alignment_present_when_user_purpose_memory_present),
        ("build_messages_current_context_grounding_when_user_purpose_present", test_build_messages_current_context_grounding_when_user_purpose_present),
        ("build_messages_proactive_initiative_when_user_purpose_present", test_build_messages_proactive_initiative_when_user_purpose_present),
        ("build_messages_confidence_filter_when_user_purpose_present", test_build_messages_confidence_filter_when_user_purpose_present),
        ("build_messages_reality_constrained_action_selection_when_user_purpose_present", test_build_messages_reality_constrained_action_selection_when_user_purpose_present),
        ("build_messages_first_money_bias_appears_for_money_query_with_user_purpose", test_build_messages_first_money_bias_appears_for_money_query_with_user_purpose),
        ("build_messages_first_money_bias_not_added_for_non_money_query", test_build_messages_first_money_bias_not_added_for_non_money_query),
        ("build_messages_single_move_compression_for_exact_next_step_money_prompt", test_build_messages_single_move_compression_for_exact_next_step_money_prompt),
        ("build_messages_single_move_compression_not_added_for_non_money_query", test_build_messages_single_move_compression_not_added_for_non_money_query),
        ("build_messages_decisiveness_context_lock_fallback_present_for_money_exact_step_prompt", test_build_messages_decisiveness_context_lock_fallback_present_for_money_exact_step_prompt),
        ("build_messages_decisiveness_not_added_for_non_money_query", test_build_messages_decisiveness_not_added_for_non_money_query),
        ("build_messages_context_lock_added_for_meta_non_money_query", test_build_messages_context_lock_added_for_meta_non_money_query),
        ("build_messages_fallback_intelligence_added_for_research_tool_non_money_query", test_build_messages_fallback_intelligence_added_for_research_tool_non_money_query),
        ("build_messages_meta_override_forces_structured_answer_path_in_open_mode", test_build_messages_meta_override_forces_structured_answer_path_in_open_mode),
        ("build_messages_vague_research_override_forces_structured_answer_path_in_open_mode", test_build_messages_vague_research_override_forces_structured_answer_path_in_open_mode),
        ("build_messages_normal_open_conversation_still_unchanged_without_override_trigger", test_build_messages_normal_open_conversation_still_unchanged_without_override_trigger),
        ("build_messages_proactive_no_extra_titan_output_sections", test_build_messages_proactive_no_extra_titan_output_sections),
        ("build_messages_next_step_alignment_preserves_prior_sections", test_build_messages_next_step_alignment_preserves_prior_sections),
        ("build_messages_user_purpose_prompt_includes_answer_anchoring_anti_leading_and_example", test_build_messages_user_purpose_prompt_includes_answer_anchoring_anti_leading_and_example),
        ("build_messages_user_purpose_answer_shaping_precedes_supporting_memory_block", test_build_messages_user_purpose_answer_shaping_precedes_supporting_memory_block),
        ("build_messages_user_purpose_prompt_keeps_system_detail_secondary_not_removed", test_build_messages_user_purpose_prompt_keeps_system_detail_secondary_not_removed),
        ("build_messages_stable_user_context_avoids_same_lane_duplicate_crowding", test_build_messages_stable_user_context_avoids_same_lane_duplicate_crowding),
        ("detect_recent_answer_relevance_false_when_history_empty", test_detect_recent_answer_relevance_false_when_history_empty),
        ("get_best_recent_answer_match_none_when_history_empty", test_get_best_recent_answer_match_none_when_history_empty),
        ("get_best_recent_answer_match_selects_more_relevant_output", test_get_best_recent_answer_match_selects_more_relevant_output),
        ("get_best_recent_answer_match_prefers_more_recent_on_equal_strength", test_get_best_recent_answer_match_prefers_more_recent_on_equal_strength),
        ("get_best_recent_answer_match_relevance_beats_recency", test_get_best_recent_answer_match_relevance_beats_recency),
        ("detect_recent_answer_relevance_unchanged_with_equal_strength_candidates", test_detect_recent_answer_relevance_unchanged_with_equal_strength_candidates),
        ("detect_recent_answer_relevance_true_on_related_followup", test_detect_recent_answer_relevance_true_on_related_followup),
        ("detect_recent_answer_relevance_false_for_short_unrelated_shared_token", test_detect_recent_answer_relevance_false_for_short_unrelated_shared_token),
        ("detect_recent_answer_relevance_false_for_generic_tokens_only", test_detect_recent_answer_relevance_false_for_generic_tokens_only),
        ("detect_recent_answer_relevance_true_after_generic_token_filtering", test_detect_recent_answer_relevance_true_after_generic_token_filtering),
        ("is_strong_recent_answer_match_false_for_none", test_is_strong_recent_answer_match_false_for_none),
        ("is_strong_recent_answer_match_true_for_high_overlap", test_is_strong_recent_answer_match_true_for_high_overlap),
        ("is_strong_recent_answer_match_false_for_weak_but_relevant", test_is_strong_recent_answer_match_false_for_weak_but_relevant),
        ("build_messages_adds_reflection_guidance_only_when_relevant", test_build_messages_adds_reflection_guidance_only_when_relevant),
        ("build_messages_includes_relevant_recent_output_only_when_relevant", test_build_messages_includes_relevant_recent_output_only_when_relevant),
        ("build_messages_includes_matched_output_for_strong_match", test_build_messages_includes_matched_output_for_strong_match),
        ("build_messages_omits_matched_output_for_weak_but_relevant_followup", test_build_messages_omits_matched_output_for_weak_but_relevant_followup),
        ("build_messages_keeps_followup_guidance_when_matched_output_omitted", test_build_messages_keeps_followup_guidance_when_matched_output_omitted),
        ("detect_recent_answer_contradiction_cue_false_for_normal_followup", test_detect_recent_answer_contradiction_cue_false_for_normal_followup),
        ("detect_recent_answer_contradiction_cue_false_for_unrelated_but", test_detect_recent_answer_contradiction_cue_false_for_unrelated_but),
        ("detect_recent_answer_contradiction_cue_false_for_unrelated_no", test_detect_recent_answer_contradiction_cue_false_for_unrelated_no),
        ("detect_recent_answer_contradiction_cue_true_for_revision_followup", test_detect_recent_answer_contradiction_cue_true_for_revision_followup),
        ("detect_recent_answer_followup_type_none_without_match", test_detect_recent_answer_followup_type_none_without_match),
        ("detect_recent_answer_followup_type_continuation_for_related_followup", test_detect_recent_answer_followup_type_continuation_for_related_followup),
        ("detect_recent_answer_followup_type_clarification_for_precision_prompt", test_detect_recent_answer_followup_type_clarification_for_precision_prompt),
        ("detect_recent_answer_followup_type_correction_for_revision_prompt", test_detect_recent_answer_followup_type_correction_for_revision_prompt),
        ("build_messages_adds_continuation_guidance_only_for_continuation", test_build_messages_adds_continuation_guidance_only_for_continuation),
        ("build_messages_adds_clarification_guidance_only_for_clarification", test_build_messages_adds_clarification_guidance_only_for_clarification),
        ("build_messages_adds_correction_guidance_only_for_correction", test_build_messages_adds_correction_guidance_only_for_correction),
        ("build_messages_adds_no_followup_type_guidance_for_unrelated_prompt", test_build_messages_adds_no_followup_type_guidance_for_unrelated_prompt),
        ("build_messages_adds_contradiction_guidance_and_self_correction_rule", test_build_messages_adds_contradiction_guidance_and_self_correction_rule),
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