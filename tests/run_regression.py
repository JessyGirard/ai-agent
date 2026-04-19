import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import threading
from unittest.mock import MagicMock, Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from requests import ConnectionError as RequestsConnectionError
from requests import Timeout

import tools.fetch_http as fetch_http_module
from services import prompt_builder
from tools.fetch_page import fetch_failure_tag, fetch_page

import playground
from core import persistence as persistence_core
from app.system_eval_operator import run_tool1_system_eval_http
from core import system_eval as system_eval_core


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
                    "confidence": 0.80,
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


def test_runtime_memory_memory01_explicit_project_line():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "The project is to create a stable AI agent that understands my work."
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items
        assert items[0].get("category") == "project"


def test_runtime_memory_memory01_this_system_is_meant_to():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "This system is meant to help me build something reliable."
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory01_skips_short_tail():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("The project is x")
        assert result is None


def test_runtime_memory_memory01_does_not_override_preference():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "I prefer the project is documented clearly in the README."
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "preference", result
        assert len(items) == 1, items
        assert items[0].get("category") == "preference"


def test_runtime_memory_memory02_i_am_building_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I am building an AI agent system")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory02_im_building_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I'm building a memory pipeline")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory02_rejects_want_to_build():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        assert playground.write_runtime_memory("I want to build a giant system") is None


def test_runtime_memory_memory02_rejects_might_build():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        assert playground.write_runtime_memory("I might build a giant system") is None


def test_runtime_memory_memory02_rejects_short_tail():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        assert playground.write_runtime_memory("I am building tiny") is None


def test_runtime_memory_memory03_playground_py_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "playground.py orchestrates memory retrieval and routing"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory03_this_system_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "this system uses extracted memory and current state"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory03_this_function_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "this function scores memory items for retrieval"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory03_rejects_short_tail():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        assert playground.write_runtime_memory("this file is ok") is None


def test_runtime_memory_memory03_i_prefer_this_system_stays_preference():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I prefer this system to be fast")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "preference", result
        assert len(items) == 1, items
        assert items[0].get("category") == "preference"


def test_runtime_memory_memory04_the_flow_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the flow is user input to memory to retrieval to response"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory04_the_workflow_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the workflow is extract then dedupe then retrieve"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory04_the_pipeline_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the pipeline is journal to extracted memory to prompt"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory04_rejects_short_tail():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        assert playground.write_runtime_memory("the flow is tiny") is None


def test_runtime_memory_memory04_i_prefer_workflow_stays_preference():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I prefer the workflow to be simple")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "preference", result
        assert len(items) == 1, items
        assert items[0].get("category") == "preference"


def test_runtime_memory_memory05_playground_responsible_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "playground.py is responsible for orchestration and routing"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory05_this_module_responsible_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "this module is responsible for memory retrieval"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory05_extracted_memory_responsible_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the extracted memory is responsible for durable project facts"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory05_rejects_short_tail():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        assert (
            playground.write_runtime_memory(
                "playground.py is responsible for tiny"
            )
            is None
        )


def test_runtime_memory_memory05_i_prefer_module_stays_preference():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I prefer this module to be simple")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "preference", result
        assert len(items) == 1, items
        assert items[0].get("category") == "preference"


def test_runtime_memory_memory06_the_rule_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the rule is keep the system test-protected and predictable"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory06_the_constraint_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the constraint is do not break existing behavior"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory06_this_system_must_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "this system must stay aligned with the project purpose"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory06_rejects_short_tail():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        assert playground.write_runtime_memory("the rule is tiny") is None


def test_runtime_memory_memory06_i_prefer_system_stays_preference():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I prefer the system to be simple")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "preference", result
        assert len(items) == 1, items
        assert items[0].get("category") == "preference"


def test_runtime_memory_memory07_the_decision_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the decision is keep the system test-protected"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory07_we_decided_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "we decided to use the chained extractor"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory07_the_plan_is_to_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the plan is to improve project awareness first"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory07_rejects_short_tail():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        assert playground.write_runtime_memory("the decision is tiny") is None


def test_runtime_memory_memory07_i_prefer_plan_stays_preference():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I prefer the plan to be simple")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "preference", result
        assert len(items) == 1, items
        assert items[0].get("category") == "preference"


def test_runtime_memory_memory08_we_completed_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "we completed the chained extractor refactor"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory08_the_milestone_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the milestone is stable project awareness capture"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory08_this_part_is_done_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "this part is done and regression-safe"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory08_rejects_short_tail():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        assert playground.write_runtime_memory("we completed short") is None


def test_runtime_memory_memory08_i_prefer_progress_stays_preference():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I prefer progress to be steady")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "preference", result
        assert len(items) == 1, items
        assert items[0].get("category") == "preference"


def test_runtime_memory_memory09_the_problem_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the problem is routing misclassification"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory09_the_biggest_risk_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the biggest risk is losing project awareness"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory09_the_failure_mode_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the failure mode is generic but shallow answers"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory09_the_bug_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the bug is incorrect memory classification"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory09_rejects_short_tail():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        assert playground.write_runtime_memory("the problem is tiny") is None


def test_runtime_memory_memory09_i_prefer_risk_stays_preference():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I prefer risk to be low")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "preference", result
        assert len(items) == 1, items
        assert items[0].get("category") == "preference"


def test_runtime_memory_memory10_the_priority_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the priority is strengthen project awareness first"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory10_objective_right_now_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "the objective right now is stable memory behavior"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory10_what_matters_most_writes_project():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory(
            "what matters most is preserving regression safety"
        )
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items


def test_runtime_memory_memory10_rejects_short_tail():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        assert playground.write_runtime_memory("the priority is tiny") is None


def test_runtime_memory_memory10_i_prefer_priorities_stays_preference():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I prefer priorities to be clear")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "preference", result
        assert len(items) == 1, items
        assert items[0].get("category") == "preference"


def test_retrieval01_project_query_boosts_project_memory_score():
    reset_agent_state()
    mem = {
        "category": "project",
        "value": "alphabetuniquestringforretrieval",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 1,
        "trend": "reinforced",
        "last_seen": "runtime",
    }
    neutral = "hello world"
    project_q = "what does this do"
    s_neutral = playground.score_memory_item(mem, neutral)
    s_project = playground.score_memory_item(mem, project_q)
    assert abs((s_project - s_neutral) - 0.4) < 1e-9, (s_neutral, s_project)


def test_retrieval01_non_project_query_does_not_boost_project_category():
    reset_agent_state()
    mem = {
        "category": "project",
        "value": "alphabetuniquestringforretrieval",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 3,
        "trend": "reinforced",
        "last_seen": "runtime",
    }
    a = "hello world"
    b = "goodbye moon"
    assert playground.score_memory_item(mem, a) == playground.score_memory_item(mem, b)


def test_retrieval01_project_query_does_not_boost_non_project_category():
    reset_agent_state()
    mem = {
        "category": "preference",
        "value": "abcuniqueprefxyz",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 3,
        "trend": "reinforced",
        "last_seen": "runtime",
    }
    neutral = "hello world"
    project_q = "how does this work"
    assert playground.score_memory_item(mem, neutral) == playground.score_memory_item(mem, project_q)


def test_retrieval02_project_evidence_boost_increases_with_count():
    reset_agent_state()
    base = {
        "category": "project",
        "value": "retrieval02uniquevalue",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "trend": "new",
        "last_seen": "runtime",
    }
    # evidence_count 1 triggers extra staleness penalty vs >1; compare 2 vs 4 so only RETRIEVAL-02 differs.
    m2 = {**base, "evidence_count": 2}
    m4 = {**base, "evidence_count": 4}
    q = "hello world"
    s2 = playground.score_memory_item(m2, q)
    s4 = playground.score_memory_item(m4, q)
    assert abs((s4 - s2) - 0.10) < 1e-9, (s2, s4)


def test_retrieval02_project_evidence_boost_caps_at_point_three():
    reset_agent_state()
    base = {
        "category": "project",
        "value": "retrieval02uniquevalue",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "trend": "new",
        "last_seen": "runtime",
    }
    m7 = {**base, "evidence_count": 7}
    m99 = {**base, "evidence_count": 99}
    q = "hello world"
    assert abs(playground.score_memory_item(m7, q) - playground.score_memory_item(m99, q)) < 1e-9


def test_retrieval02_non_project_unaffected_by_project_evidence_boost():
    reset_agent_state()
    q = "hello world"
    m1 = {
        "category": "identity",
        "value": "retrieval02identityuniq",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    m2 = {**m1, "evidence_count": 50}
    assert playground.score_memory_item(m1, q) == playground.score_memory_item(m2, q)


def test_retrieval03_project_evidence_two_scores_higher_than_one():
    reset_agent_state()
    base = {
        "category": "project",
        "value": "retrieval03uniquevalue",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "trend": "reinforced",
        "last_seen": "runtime",
    }
    m1 = {**base, "evidence_count": 1}
    m2 = {**base, "evidence_count": 2}
    q = "hello world"
    assert playground.score_memory_item(m2, q) > playground.score_memory_item(m1, q)
    assert abs(
        playground.score_memory_item(m2, q) - playground.score_memory_item(m1, q) - 0.10
    ) < 1e-9


def test_retrieval03_high_confidence_project_one_off_still_strong():
    reset_agent_state()
    mem = {
        "category": "project",
        "value": "retrieval03highconf",
        "confidence": 0.99,
        "importance": 0.99,
        "memory_kind": "stable",
        "evidence_count": 1,
        "trend": "reinforced",
        "last_seen": "runtime",
    }
    q = "hello world"
    assert playground.score_memory_item(mem, q) > 2.2


def test_retrieval03_non_project_evidence_one_not_penalized():
    reset_agent_state()
    q = "hello world"
    mem = {
        "category": "preference",
        "value": "retrieval03prefuniq",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 1,
        "trend": "new",
        "last_seen": "runtime",
    }
    base = playground.score_memory_item(mem, q)
    mem_proj = {**mem, "category": "project"}
    proj = playground.score_memory_item(mem_proj, q)
    c = float(mem.get("confidence", 0) or 0)
    # RETRIEVAL-03 project evidence_count==1 penalty; RETRIEVAL-06 adds 0.05*c for project only.
    assert abs(base - proj - (0.05 - 0.05 * c)) < 1e-9


def test_retrieval04_reinforced_project_beats_new_on_project_query():
    reset_agent_state()
    base = {
        "category": "project",
        "value": "retrieval04isolatedtoken",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "last_seen": "runtime",
    }
    m_rein = {**base, "trend": "reinforced"}
    m_new = {**base, "trend": "new"}
    project_q = "what does this do"
    s_rein = playground.score_memory_item(m_rein, project_q)
    s_new = playground.score_memory_item(m_new, project_q)
    assert s_rein > s_new
    # RETRIEVAL-04 (+0.1) plus existing recency bonus for reinforced trend (+0.07).
    assert abs((s_rein - s_new) - 0.17) < 1e-9


def test_retrieval04_neutral_query_no_reinforced_project_bonus():
    reset_agent_state()
    mem = {
        "category": "project",
        "value": "retrieval04isolatedtoken",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "reinforced",
        "last_seen": "runtime",
    }
    neutral = "hello world"
    project_q = "what does this do"
    s_neutral = playground.score_memory_item(mem, neutral)
    s_project = playground.score_memory_item(mem, project_q)
    assert abs((s_project - s_neutral - 0.4 - 0.1)) < 1e-9, (s_neutral, s_project)


def test_retrieval04_non_project_category_no_reinforced_bonus():
    reset_agent_state()
    mem = {
        "category": "preference",
        "value": "retrieval04prefuniq",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "reinforced",
        "last_seen": "runtime",
    }
    neutral = "hello world"
    project_q = "what does this do"
    assert playground.score_memory_item(mem, neutral) == playground.score_memory_item(mem, project_q)


def test_retrieval05_project_pref_alignment_tokens_boost_score():
    reset_agent_state()
    base = {
        "category": "project",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    m_plain = {**base, "value": "retrieval05pjbase qqqzz"}
    m_aligned = {**base, "value": "retrieval05pjbase incremental qqqzz"}
    q = "hello world"
    s_plain = playground.score_memory_item(m_plain, q)
    s_aligned = playground.score_memory_item(m_aligned, q)
    assert abs((s_aligned - s_plain) - 0.08) < 1e-9, (s_plain, s_aligned)


def test_retrieval05_project_without_pref_tokens_no_alignment_boost():
    reset_agent_state()
    base = {
        "category": "project",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    a = {**base, "value": "retrieval05noprefaaa"}
    b = {**base, "value": "retrieval05noprefbbb"}
    q = "hello world"
    assert abs(playground.score_memory_item(a, q) - playground.score_memory_item(b, q)) < 1e-9


def test_retrieval05_preference_category_not_pref_alignment_boosted():
    reset_agent_state()
    base = {
        "category": "preference",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    with_token = {**base, "value": "retrieval05prefsame incremental tail"}
    without = {**base, "value": "retrieval05prefsame plainword tail"}
    q = "hello world"
    assert abs(playground.score_memory_item(with_token, q) - playground.score_memory_item(without, q)) < 1e-9


def test_retrieval06_project_confidence_boost_orders_high_confidence():
    reset_agent_state()
    base = {
        "category": "project",
        "value": "retrieval06overlaptoken projectvalue only",
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    m_low = {**base, "confidence": 0.2}
    m_high = {**base, "confidence": 0.8}
    q = "retrieval06overlaptoken xyz"
    s_low = playground.score_memory_item(m_low, q)
    s_high = playground.score_memory_item(m_high, q)
    assert s_high > s_low
    # Base score includes confidence once; RETRIEVAL-06 adds 0.05 * confidence for project.
    assert abs((s_high - s_low) - (0.8 - 0.2) - 0.05 * (0.8 - 0.2)) < 1e-9, (s_low, s_high)


def test_retrieval06_non_project_confidence_not_extra_boosted():
    reset_agent_state()
    base = {
        "category": "preference",
        "value": "retrieval06overlaptoken prefvalue only",
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    m_low = {**base, "confidence": 0.2}
    m_high = {**base, "confidence": 0.8}
    q = "retrieval06overlaptoken xyz"
    assert abs(
        playground.score_memory_item(m_high, q) - playground.score_memory_item(m_low, q) - (0.8 - 0.2)
    ) < 1e-9


def test_retrieval07_project_boost_cap_total_point_eight():
    reset_agent_state()
    project_q = "what does this do"
    shared = {
        "category": "project",
        "confidence": 1.0,
        "importance": 0.75,
        "memory_kind": "stable",
        "last_seen": "runtime",
        "trend": "settled",
    }
    m_light = {
        **shared,
        "value": "retrieval07lightuniq this plainx",
        "evidence_count": 2,
    }
    m_heavy = {
        **shared,
        "value": "retrieval07heavyuniq this incremental",
        "evidence_count": 7,
    }
    s_heavy = playground.score_memory_item(m_heavy, project_q)
    s_light = playground.score_memory_item(m_light, project_q)
    # project_bonus uncapped: heavy 0.93 vs light 0.60 (diff 0.33); cap clips heavy to 0.80 (diff 0.20).
    # Same trend / recency / evidence_count>=3 line so only project_bonus cap differs materially.
    assert abs((s_heavy - s_light) - 0.2) < 1e-9, (s_light, s_heavy)


def test_retrieval07_non_project_category_cap_does_not_apply():
    reset_agent_state()
    project_q = "what does this do"
    base = {
        "category": "goal",
        "value": "retrieval07goaluniq this incremental tail",
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 7,
        "trend": "reinforced",
        "last_seen": "runtime",
    }
    m_low = {**base, "confidence": 0.2}
    m_high = {**base, "confidence": 0.8}
    assert abs(
        playground.score_memory_item(m_high, project_q) - playground.score_memory_item(m_low, project_q) - (0.8 - 0.2)
    ) < 1e-9


def test_retrieval07_below_cap_project_same_as_uncapped():
    reset_agent_state()
    mem = {
        "category": "project",
        "value": "alphabetuniquestringforretrieval",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 1,
        "trend": "reinforced",
        "last_seen": "runtime",
    }
    neutral = "hello world"
    project_q = "what does this do"
    s_neutral = playground.score_memory_item(mem, neutral)
    s_project = playground.score_memory_item(mem, project_q)
    assert abs((s_project - s_neutral) - 0.4) < 1e-9, (s_neutral, s_project)


def test_retrieval08_explicit_project_phrase_boosts_project_memory():
    reset_agent_state()
    mem = {
        "category": "project",
        "value": "retrieval08projuniq zz",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 1,
        "trend": "new",
        "last_seen": "runtime",
    }
    q_vague = "what does this do"
    q_explicit = "how does this project work"
    s_vague = playground.score_memory_item(mem, q_vague)
    s_explicit = playground.score_memory_item(mem, q_explicit)
    # RETRIEVAL-08 +0.05; explicit wording also triggers intent "project" (+0.35) vs general on vague query.
    assert abs((s_explicit - s_vague) - 0.4) < 1e-9, (s_vague, s_explicit)


def test_retrieval08_preference_not_boosted_by_explicit_phrase():
    reset_agent_state()
    mem = {
        "category": "preference",
        "value": "retrieval08prefuniq zz",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    q_vague = "what does this do"
    q_explicit = "how it works"
    assert abs(playground.score_memory_item(mem, q_vague) - playground.score_memory_item(mem, q_explicit)) < 1e-9


def test_retrieval09_priority_risk_phrase_boosts_project_memory():
    reset_agent_state()
    mem = {
        "category": "project",
        "value": "retrieval09projuniq zz",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    q_neutral = "what does this do"
    q_risk = "what does this do about the problem"
    s_neutral = playground.score_memory_item(mem, q_neutral)
    s_risk = playground.score_memory_item(mem, q_risk)
    assert s_risk > s_neutral
    assert abs((s_risk - s_neutral) - 0.05) < 1e-9, (s_neutral, s_risk)


def test_retrieval09_preference_not_boosted_by_priority_risk_phrase():
    reset_agent_state()
    mem = {
        "category": "preference",
        "value": "retrieval09prefuniq zz",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    q_neutral = "what does this do"
    q_risk = "what does this do about the problem"
    assert abs(playground.score_memory_item(mem, q_neutral) - playground.score_memory_item(mem, q_risk)) < 1e-9


def test_retrieval09_max_project_bonus_cap_unchanged_with_risk_phrase():
    reset_agent_state()
    project_q_plain = "what does this do"
    project_q_risk = "what does this do the problem is recorded"
    shared = {
        "category": "project",
        "confidence": 1.0,
        "importance": 0.75,
        "memory_kind": "stable",
        "last_seen": "runtime",
        "trend": "settled",
    }
    m_heavy = {
        **shared,
        "value": "retrieval09heavyuniq this incremental",
        "evidence_count": 7,
    }
    s_plain = playground.score_memory_item(m_heavy, project_q_plain)
    s_risk = playground.score_memory_item(m_heavy, project_q_risk)
    # Raw project_bonus already >= 0.8 before RETRIEVAL-09; +0.05 risk phrase still caps at 0.8.
    assert abs(s_plain - s_risk) < 1e-9, (s_plain, s_risk)


def test_retrieval10_decision_progress_phrase_boosts_project_memory():
    reset_agent_state()
    mem = {
        "category": "project",
        "value": "retrieval10projuniq zz",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    q_neutral = "what does this do"
    q_progress = "what does this do about the decision"
    s_neutral = playground.score_memory_item(mem, q_neutral)
    s_progress = playground.score_memory_item(mem, q_progress)
    assert s_progress > s_neutral
    assert abs((s_progress - s_neutral) - 0.05) < 1e-9, (s_neutral, s_progress)


def test_retrieval10_preference_not_boosted_by_decision_progress_phrase():
    reset_agent_state()
    mem = {
        "category": "preference",
        "value": "retrieval10prefuniq zz",
        "confidence": 0.7,
        "importance": 0.75,
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    q_neutral = "what does this do"
    q_progress = "what does this do about the decision"
    assert abs(playground.score_memory_item(mem, q_neutral) - playground.score_memory_item(mem, q_progress)) < 1e-9


def test_retrieval10_max_project_bonus_cap_unchanged_with_decision_phrase():
    reset_agent_state()
    project_q_plain = "what does this do"
    project_q_decision = "what does this do the decision is final"
    shared = {
        "category": "project",
        "confidence": 1.0,
        "importance": 0.75,
        "memory_kind": "stable",
        "last_seen": "runtime",
        "trend": "settled",
    }
    m_heavy = {
        **shared,
        "value": "retrieval10heavyuniq this incremental",
        "evidence_count": 7,
    }
    s_plain = playground.score_memory_item(m_heavy, project_q_plain)
    s_decision = playground.score_memory_item(m_heavy, project_q_decision)
    assert abs(s_plain - s_decision) < 1e-9, (s_plain, s_decision)


def test_packaging01_snapshot_only_active_project_rows():
    reset_agent_state()
    payload = {
        "meta": {"schema_version": "2.0", "memory_count": 3},
        "memory_items": [
            {
                "memory_id": "p1",
                "category": "project",
                "value": "packaging01activeproject",
                "confidence": 0.7,
                "importance": 0.75,
                "status": "active",
                "memory_kind": "stable",
                "evidence_count": 2,
                "trend": "new",
                "last_seen": "runtime",
            },
            {
                "memory_id": "p2",
                "category": "project",
                "value": "packaging01inactiveproject",
                "confidence": 0.9,
                "importance": 0.9,
                "status": "reinforced",
                "memory_kind": "stable",
                "evidence_count": 5,
                "trend": "reinforced",
                "last_seen": "runtime",
            },
            {
                "memory_id": "pref1",
                "category": "preference",
                "value": "packaging01prefonly",
                "confidence": 0.8,
                "importance": 0.8,
                "status": "active",
                "memory_kind": "stable",
                "evidence_count": 2,
                "trend": "new",
                "last_seen": "runtime",
            },
        ],
    }
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        snap = playground.build_project_memory_snapshot()
    assert "packaging01activeproject" in snap
    assert "packaging01inactiveproject" not in snap
    assert "packaging01prefonly" not in snap


def test_packaging01_snapshot_orders_stronger_project_rows_first():
    reset_agent_state()
    payload = {
        "meta": {"schema_version": "2.0", "memory_count": 2},
        "memory_items": [
            {
                "memory_id": "weak",
                "category": "project",
                "value": "packaging01weakrow",
                "confidence": 0.9,
                "importance": 0.9,
                "status": "active",
                "memory_kind": "stable",
                "evidence_count": 5,
                "trend": "new",
                "last_seen": "runtime",
            },
            {
                "memory_id": "strong",
                "category": "project",
                "value": "packaging01strongrow",
                "confidence": 0.5,
                "importance": 0.5,
                "status": "active",
                "memory_kind": "stable",
                "evidence_count": 1,
                "trend": "reinforced",
                "last_seen": "runtime",
            },
        ],
    }
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        snap = playground.build_project_memory_snapshot()
    lines = snap.strip().split("\n")
    assert lines[0] == "Project memory snapshot:"
    assert lines[1] == ""
    assert lines[2] == "Other Project Memory:"
    assert "packaging01strongrow" in lines[3]
    assert "packaging01weakrow" in lines[4]


def test_packaging01_snapshot_respects_max_items():
    reset_agent_state()
    items = []
    for i in range(4):
        items.append(
            {
                "memory_id": f"p{i}",
                "category": "project",
                "value": f"packaging01slot{i}",
                "confidence": 0.7,
                "importance": 0.75,
                "status": "active",
                "memory_kind": "stable",
                "evidence_count": 1,
                "trend": "new",
                "last_seen": "runtime",
            }
        )
    payload = {"meta": {"schema_version": "2.0", "memory_count": 4}, "memory_items": items}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        snap = playground.build_project_memory_snapshot(max_items=2)
    assert snap.count("- packaging01slot") == 2


def test_packaging01_non_project_rows_excluded():
    reset_agent_state()
    payload = {
        "meta": {"schema_version": "2.0", "memory_count": 1},
        "memory_items": [
            {
                "memory_id": "g1",
                "category": "goal",
                "value": "packaging01goalonly",
                "confidence": 0.8,
                "importance": 0.8,
                "status": "active",
                "memory_kind": "stable",
                "evidence_count": 2,
                "trend": "new",
                "last_seen": "runtime",
            },
        ],
    }
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_snapshot() == ""


def test_packaging01_empty_project_memory_returns_empty_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_snapshot() == ""


def test_packaging01_show_project_memory_snapshot_fallback():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.show_project_memory_snapshot() == "No active project memory available."


def _packaging02_row(memory_id, value, **overrides):
    base = {
        "memory_id": memory_id,
        "category": "project",
        "confidence": 0.7,
        "importance": 0.75,
        "status": "active",
        "memory_kind": "stable",
        "evidence_count": 2,
        "trend": "new",
        "last_seen": "runtime",
    }
    base.update(overrides)
    base["value"] = value
    return base


def test_packaging02_snapshot_groups_rows_into_sections():
    reset_agent_state()
    payload = {
        "meta": {"schema_version": "2.0", "memory_count": 6},
        "memory_items": [
            _packaging02_row("b1", "the project is packaging02build"),
            _packaging02_row("s1", "the flow is packaging02flow"),
            _packaging02_row("r1", "the rule is packaging02rule"),
            _packaging02_row("d1", "we completed packaging02done"),
            _packaging02_row("x1", "the risk is packaging02risk"),
            _packaging02_row("o1", "packaging02otheruniq"),
        ],
    }
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        snap = playground.build_project_memory_snapshot()
    assert "Build / Purpose:" in snap
    assert "the project is packaging02build" in snap
    assert "Structure / Flow:" in snap
    assert "the flow is packaging02flow" in snap
    assert "Responsibilities / Rules:" in snap
    assert "the rule is packaging02rule" in snap
    assert "Decisions / Progress:" in snap
    assert "we completed packaging02done" in snap
    assert "Risks / Priorities:" in snap
    assert "the risk is packaging02risk" in snap
    assert "Other Project Memory:" in snap
    assert "packaging02otheruniq" in snap
    assert snap.index("Build / Purpose:") < snap.index("Structure / Flow:")
    assert snap.index("Structure / Flow:") < snap.index("Responsibilities / Rules:")
    assert snap.index("Responsibilities / Rules:") < snap.index("Decisions / Progress:")
    assert snap.index("Decisions / Progress:") < snap.index("Risks / Priorities:")
    assert snap.index("Risks / Priorities:") < snap.index("Other Project Memory:")


def test_packaging02_snapshot_omits_empty_sections():
    reset_agent_state()
    payload = {
        "meta": {"schema_version": "2.0", "memory_count": 2},
        "memory_items": [
            _packaging02_row("o1", "packaging02onlyothera"),
            _packaging02_row("o2", "packaging02onlyotherb"),
        ],
    }
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        snap = playground.build_project_memory_snapshot()
    assert "Other Project Memory:" in snap
    assert "Build / Purpose:" not in snap
    assert "Structure / Flow:" not in snap
    assert "Responsibilities / Rules:" not in snap
    assert "Decisions / Progress:" not in snap
    assert "Risks / Priorities:" not in snap


def test_packaging02_snapshot_max_items_trims_before_grouping():
    reset_agent_state()
    items = []
    for i in range(4):
        items.append(
            _packaging02_row(
                f"p{i}",
                f"the project is packaging02slot{i}",
                evidence_count=4 - i,
                trend="new",
            )
        )
    payload = {"meta": {"schema_version": "2.0", "memory_count": 4}, "memory_items": items}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        snap = playground.build_project_memory_snapshot(max_items=2)
    assert snap.count("- the project is packaging02slot") == 2
    assert "packaging02slot2" not in snap
    assert "packaging02slot3" not in snap


def test_packaging02_responsible_prefix_beats_generic_playground_prefix():
    reset_agent_state()
    payload = {
        "meta": {"schema_version": "2.0", "memory_count": 1},
        "memory_items": [
            _packaging02_row(
                "resp",
                "playground.py is responsible for packaging02respuniq",
            ),
        ],
    }
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        snap = playground.build_project_memory_snapshot()
    assert "Responsibilities / Rules:" in snap
    assert "Structure / Flow:" not in snap
    assert "playground.py is responsible for packaging02respuniq" in snap


def test_packaging02_show_project_memory_snapshot_fallback_unchanged():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.show_project_memory_snapshot() == "No active project memory available."


def test_packaging03_near_duplicate_values_collapse_to_one_bullet():
    reset_agent_state()
    # Bypass persistence dedupe (load_memory_payload merges same build_memory_key first).
    rows = [
        _packaging02_row(
            "w1",
            "the project is packaging03collapseuniq",
            evidence_count=2,
            trend="new",
        ),
        _packaging02_row(
            "w2",
            "THE  project is packaging03collapseuniq.",
            evidence_count=2,
            trend="new",
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
    assert snap.count("packaging03collapseuniq") == 1
    assert snap.count("- ") == 1


def test_packaging03_stronger_near_duplicate_wins():
    reset_agent_state()
    rows = [
        _packaging02_row(
            "weak",
            "the project is packaging03winneruniq",
            evidence_count=1,
            trend="new",
            confidence=0.5,
            importance=0.5,
        ),
        _packaging02_row(
            "strong",
            "THE project is packaging03winneruniq",
            evidence_count=9,
            trend="reinforced",
            confidence=0.95,
            importance=0.95,
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
    assert snap.count("packaging03winneruniq") == 1
    assert "[evidence=9," in snap
    assert "[evidence=1," not in snap
    assert "THE project is packaging03winneruniq" in snap


def test_packaging03_distinct_normalized_rows_both_remain():
    reset_agent_state()
    payload = {
        "meta": {"schema_version": "2.0", "memory_count": 2},
        "memory_items": [
            _packaging02_row("a", "the project is packaging03distinctA"),
            _packaging02_row("b", "the project is packaging03distinctB"),
        ],
    }
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        snap = playground.build_project_memory_snapshot()
    assert "packaging03distinctA" in snap
    assert "packaging03distinctB" in snap
    assert snap.count("- the project is packaging03distinct") == 2


def test_packaging03_sections_stable_after_dedupe():
    reset_agent_state()
    payload = {
        "meta": {"schema_version": "2.0", "memory_count": 3},
        "memory_items": [
            _packaging02_row("d1", "the project is packaging03samebuild", evidence_count=1),
            _packaging02_row("d2", "THE  project is packaging03samebuild.", evidence_count=1),
            _packaging02_row("f1", "the flow is packaging03afterflow", evidence_count=2),
        ],
    }
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        snap = playground.build_project_memory_snapshot()
    assert snap.count("Build / Purpose:") == 1
    assert snap.count("Structure / Flow:") == 1
    assert snap.count("packaging03samebuild") == 1
    assert "the flow is packaging03afterflow" in snap


def test_packaging03_show_project_memory_snapshot_fallback_unchanged():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.show_project_memory_snapshot() == "No active project memory available."


def _packaging_snapshot_bullet_row_count(snap):
    return sum(1 for line in snap.splitlines() if line.startswith("- "))


def _packaging_snapshot_section_count(snap):
    if not snap:
        return 0
    section_headers = (
        "Build / Purpose:",
        "Structure / Flow:",
        "Responsibilities / Rules:",
        "Decisions / Progress:",
        "Risks / Priorities:",
        "Other Project Memory:",
    )
    return sum(1 for line in snap.splitlines() if line in section_headers)


def test_packaging04_package_wraps_snapshot_with_header_text():
    reset_agent_state()
    payload = {
        "meta": {"schema_version": "2.0", "memory_count": 1},
        "memory_items": [
            _packaging02_row("p1", "the project is packaging04wrapuniq", evidence_count=2),
        ],
    }
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        snap = playground.build_project_memory_snapshot()
        pkg = playground.build_project_memory_package()
    assert "You are given a packaged project memory." in pkg
    assert "Treat it as reliable background context about the system." in pkg
    assert (
        "Use it to guide reasoning, prioritization, and technical decisions." in pkg
    )
    assert (
        "Do not invent facts outside this memory unless explicitly required." in pkg
    )
    assert "Packaged project rows: 1" in pkg
    assert "Packaged sections: 1" in pkg
    assert "Packaged strengths: reinforced=0, new=1" in pkg
    assert snap in pkg
    assert pkg.endswith(snap)


def test_packaging04_empty_snapshot_returns_empty_package_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_package() == ""


def test_packaging04_show_project_memory_package_fallback():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert (
            playground.show_project_memory_package()
            == "No packaged project memory available."
        )


def test_packaging04_snapshot_body_unchanged_inside_package():
    reset_agent_state()
    rows = [
        _packaging02_row("a", "the project is packaging04bodyuniq", evidence_count=3),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        pkg = playground.build_project_memory_package()
        _, pr, sc = playground._project_memory_snapshot_package_context(12)
        n = len(pr)
        s = sc
        r_cnt, new_cnt = playground._count_project_memory_snapshot_strengths(pr)
        assert n == _packaging_snapshot_bullet_row_count(snap)
        assert s == _packaging_snapshot_section_count(snap)
        top_block = _packaging_top_priorities_block(pr)
        assert pkg == _packaging05_instruction_prefix(n, s, r_cnt, new_cnt) + top_block + snap
        assert playground.build_project_memory_snapshot() == snap


def _packaging05_instruction_prefix(row_count, section_count, reinforced_count, new_count):
    return (
        "You are given a packaged project memory.\n"
        "Treat it as reliable background context about the system.\n"
        "Use it to guide reasoning, prioritization, and technical decisions.\n"
        "Do not invent facts outside this memory unless explicitly required.\n"
        f"Packaged project rows: {row_count}\n"
        f"Packaged sections: {section_count}\n"
        f"Packaged strengths: reinforced={reinforced_count}, new={new_count}\n\n"
    )


def _packaging_top_priorities_block(packaged_rows):
    top_priorities = playground._build_project_memory_package_top_priorities(packaged_rows)
    return f"{top_priorities}\n\n" if top_priorities else ""


def test_packaging05_package_contains_instruction_header():
    reset_agent_state()
    rows = [
        _packaging02_row("x", "the project is packaging05instruniq", evidence_count=1),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        pkg = playground.build_project_memory_package()
        _, pr, sc = playground._project_memory_snapshot_package_context(12)
        r_cnt, new_cnt = playground._count_project_memory_snapshot_strengths(pr)
    n = len(pr)
    s = sc
    assert pkg.startswith(_packaging05_instruction_prefix(n, s, r_cnt, new_cnt))
    assert "Packaged project rows:" in pkg
    assert "Packaged sections:" in pkg
    assert "Packaged strengths:" in pkg


def test_packaging05_snapshot_body_unchanged_in_package():
    reset_agent_state()
    rows = [
        _packaging02_row("y", "the project is packaging05bodyuniq", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        pkg = playground.build_project_memory_package()
        _, pr, sc = playground._project_memory_snapshot_package_context(12)
        r_cnt, new_cnt = playground._count_project_memory_snapshot_strengths(pr)
    n = len(pr)
    s = sc
    top_block = _packaging_top_priorities_block(pr)
    assert pkg == _packaging05_instruction_prefix(n, s, r_cnt, new_cnt) + top_block + snap


def test_packaging05_empty_package_returns_empty_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_package() == ""


def test_packaging05_show_package_fallback_unchanged():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert (
            playground.show_project_memory_package()
            == "No packaged project memory available."
        )


def _packaging06_compact_instruction_prefix(
    row_count, section_count, reinforced_count, new_count
):
    return (
        "Packaged project memory:\n"
        "Use as reliable background context.\n"
        f"Packaged project rows: {row_count}\n"
        f"Packaged sections: {section_count}\n"
        f"Packaged strengths: reinforced={reinforced_count}, new={new_count}\n\n"
    )


def test_packaging06_full_package_unchanged_by_default():
    reset_agent_state()
    rows = [
        _packaging02_row("f", "the project is packaging06fulluniq", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        default_pkg = playground.build_project_memory_package()
        explicit_pkg = playground.build_project_memory_package(compact=False)
    assert default_pkg == explicit_pkg


def test_packaging06_compact_package_uses_short_prefix():
    reset_agent_state()
    rows = [
        _packaging02_row("c", "the project is packaging06compactuniq", evidence_count=1),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        pkg = playground.build_project_memory_package(compact=True)
        _, pr, sc = playground._project_memory_snapshot_package_context(12)
        r_cnt, new_cnt = playground._count_project_memory_snapshot_strengths(pr)
    n = len(pr)
    s = sc
    pfx = _packaging06_compact_instruction_prefix(n, s, r_cnt, new_cnt)
    assert pkg.startswith(pfx)
    assert "You are given a packaged project memory." not in pkg


def test_packaging06_snapshot_body_same_in_full_and_compact_modes():
    reset_agent_state()
    rows = [
        _packaging02_row("b", "the project is packaging06bothuniq", evidence_count=3),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        full = playground.build_project_memory_package(compact=False)
        compact = playground.build_project_memory_package(compact=True)
        _, pr, sc = playground._project_memory_snapshot_package_context(12)
        r_cnt, new_cnt = playground._count_project_memory_snapshot_strengths(pr)
    n = len(pr)
    s = sc
    top_block = _packaging_top_priorities_block(pr)
    assert full == _packaging05_instruction_prefix(n, s, r_cnt, new_cnt) + top_block + snap
    assert compact == _packaging06_compact_instruction_prefix(n, s, r_cnt, new_cnt) + top_block + snap
    assert snap in full and snap in compact


def test_packaging06_empty_package_compact_returns_empty_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_package(compact=True) == ""


def test_packaging06_show_package_fallback_compact_unchanged():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert (
            playground.show_project_memory_package(compact=True)
            == "No packaged project memory available."
        )


def test_packaging07_full_package_includes_row_count_line():
    reset_agent_state()
    rows = [
        _packaging02_row("u1", "the project is packaging07fullA", evidence_count=1),
        _packaging02_row("u2", "the flow is packaging07fullB", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        pkg = playground.build_project_memory_package(compact=False)
    n = _packaging_snapshot_bullet_row_count(snap)
    sec = _packaging_snapshot_section_count(snap)
    assert n == 2
    assert sec == 2
    assert f"Packaged project rows: {n}" in pkg
    assert f"Packaged sections: {sec}" in pkg
    assert "Packaged strengths: reinforced=0, new=2" in pkg


def test_packaging07_compact_package_includes_row_count_line():
    reset_agent_state()
    rows = [
        _packaging02_row("v1", "the project is packaging07compactA", evidence_count=1),
        _packaging02_row("v2", "the risk is packaging07compactB", evidence_count=1),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        pkg = playground.build_project_memory_package(compact=True)
    n = _packaging_snapshot_bullet_row_count(snap)
    sec = _packaging_snapshot_section_count(snap)
    assert n == 2
    assert sec == 2
    assert f"Packaged project rows: {n}" in pkg
    assert f"Packaged sections: {sec}" in pkg
    assert "Packaged strengths: reinforced=0, new=2" in pkg


def test_packaging07_snapshot_body_unchanged_after_metadata():
    reset_agent_state()
    rows = [
        _packaging02_row("w", "the project is packaging07metauniq", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        full = playground.build_project_memory_package(compact=False)
        compact = playground.build_project_memory_package(compact=True)
    assert full.endswith(snap)
    assert compact.endswith(snap)


def test_packaging07_empty_package_returns_empty_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_package() == ""
        assert playground.build_project_memory_package(compact=True) == ""


def test_packaging07_show_package_fallback_unchanged():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert (
            playground.show_project_memory_package()
            == "No packaged project memory available."
        )
        assert (
            playground.show_project_memory_package(compact=True)
            == "No packaged project memory available."
        )


def test_packaging08_full_package_includes_section_count_line():
    reset_agent_state()
    rows = [
        _packaging02_row("e1", "the project is packaging08fullS", evidence_count=1),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Packaged sections:" in pkg


def test_packaging08_compact_package_includes_section_count_line():
    reset_agent_state()
    rows = [
        _packaging02_row("e2", "the rule is packaging08compactS", evidence_count=1),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=True)
    assert "Packaged sections:" in pkg


def test_packaging08_section_count_matches_non_empty_snapshot_sections():
    reset_agent_state()
    rows = [
        _packaging02_row("m1", "the project is packaging08matchA", evidence_count=1),
        _packaging02_row("m2", "the flow is packaging08matchB", evidence_count=1),
        _packaging02_row("m3", "packaging08matchCother", evidence_count=1),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        sec = _packaging_snapshot_section_count(snap)
        pkg = playground.build_project_memory_package()
    assert sec == 3
    assert f"Packaged sections: {sec}" in pkg


def test_packaging08_snapshot_body_unchanged_after_metadata():
    reset_agent_state()
    rows = [
        _packaging02_row("z", "the project is packaging08enduniq", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        full = playground.build_project_memory_package(compact=False)
        compact = playground.build_project_memory_package(compact=True)
    assert full.endswith(snap)
    assert compact.endswith(snap)


def test_packaging08_empty_package_returns_empty_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_package() == ""
        assert playground.build_project_memory_package(compact=True) == ""


def test_packaging08_show_package_fallback_unchanged():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert (
            playground.show_project_memory_package()
            == "No packaged project memory available."
        )
        assert (
            playground.show_project_memory_package(compact=True)
            == "No packaged project memory available."
        )


def test_packaging09_full_package_includes_strength_line():
    reset_agent_state()
    rows = [
        _packaging02_row(
            "p1", "the project is packaging09fullstrength", evidence_count=1
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Packaged strengths: reinforced=0, new=1" in pkg


def test_packaging09_compact_package_includes_strength_line():
    reset_agent_state()
    rows = [
        _packaging02_row(
            "p2", "the project is packaging09compactstrength", evidence_count=1
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=True)
    assert "Packaged strengths: reinforced=0, new=1" in pkg


def test_packaging09_strength_counts_match_packaged_rows():
    reset_agent_state()
    rows = [
        _packaging02_row(
            "a", "the project is packaging09mixA", trend="reinforced"
        ),
        _packaging02_row("b", "the flow is packaging09mixB", trend="new"),
        _packaging02_row("c", "packaging09otheruniq", trend="stable"),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package()
        _, pr, _ = playground._project_memory_snapshot_package_context(12)
    r_cnt, new_cnt = playground._count_project_memory_snapshot_strengths(pr)
    assert len(pr) == 3
    assert r_cnt == 1
    assert new_cnt == 1
    assert f"Packaged strengths: reinforced={r_cnt}, new={new_cnt}" in pkg


def test_packaging09_strength_reflects_surviving_row_after_dedupe():
    reset_agent_state()
    rows = [
        _packaging02_row(
            "w1",
            "the project is packaging09dedupe",
            evidence_count=1,
            trend="new",
        ),
        _packaging02_row(
            "w2",
            "THE project is packaging09dedupe",
            evidence_count=9,
            trend="reinforced",
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        pkg = playground.build_project_memory_package()
        _, pr, _ = playground._project_memory_snapshot_package_context(12)
    assert snap.count("packaging09dedupe") == 1
    assert len(pr) == 1
    r_cnt, new_cnt = playground._count_project_memory_snapshot_strengths(pr)
    assert r_cnt == 1
    assert new_cnt == 0
    assert f"Packaged strengths: reinforced={r_cnt}, new={new_cnt}" in pkg


def test_packaging09_snapshot_body_unchanged_after_metadata():
    reset_agent_state()
    rows = [
        _packaging02_row(
            "w", "the project is packaging09snapmeta", evidence_count=2
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        full = playground.build_project_memory_package(compact=False)
        compact = playground.build_project_memory_package(compact=True)
    assert full.endswith(snap)
    assert compact.endswith(snap)


def test_packaging09_empty_package_returns_empty_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_package() == ""
        assert playground.build_project_memory_package(compact=True) == ""


def test_packaging09_show_package_fallback_unchanged():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert (
            playground.show_project_memory_package()
            == "No packaged project memory available."
        )
        assert (
            playground.show_project_memory_package(compact=True)
            == "No packaged project memory available."
        )


def test_packaging10_full_package_includes_top_priorities_block():
    reset_agent_state()
    rows = [
        _packaging02_row("t1", "the project is packaging10fullprioA", evidence_count=3),
        _packaging02_row("t2", "the flow is packaging10fullprioB", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Top project priorities:" in pkg
    assert "- the project is packaging10fullprioA" in pkg
    assert "- the flow is packaging10fullprioB" in pkg


def test_packaging10_compact_package_includes_top_priorities_block():
    reset_agent_state()
    rows = [
        _packaging02_row(
            "t3", "the project is packaging10compactprioA", evidence_count=3
        ),
        _packaging02_row("t4", "the flow is packaging10compactprioB", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=True)
    assert "Top project priorities:" in pkg
    assert "- the project is packaging10compactprioA" in pkg
    assert "- the flow is packaging10compactprioB" in pkg


def test_packaging10_top_priorities_use_first_packaged_rows_order():
    reset_agent_state()
    rows = [
        _packaging02_row("a", "the project is packaging10orderA", evidence_count=9),
        _packaging02_row("b", "the flow is packaging10orderB", evidence_count=8),
        _packaging02_row("c", "the rule is packaging10orderC", evidence_count=7),
        _packaging02_row("d", "we completed packaging10orderD", evidence_count=6),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        _, pr, _ = playground._project_memory_snapshot_package_context(12)
        top = playground._build_project_memory_package_top_priorities(pr)
    assert top == (
        "Top project priorities:\n"
        "- the project is packaging10orderA\n"
        "- the flow is packaging10orderB\n"
        "- the rule is packaging10orderC"
    )


def test_packaging10_snapshot_body_unchanged_after_priorities_preface():
    reset_agent_state()
    rows = [
        _packaging02_row("u", "the project is packaging10snapbody", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        snap = playground.build_project_memory_snapshot()
        full = playground.build_project_memory_package(compact=False)
        compact = playground.build_project_memory_package(compact=True)
    assert full.endswith(snap)
    assert compact.endswith(snap)


def test_packaging10_empty_package_returns_empty_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_package() == ""
        assert playground.build_project_memory_package(compact=True) == ""


def test_packaging10_show_package_fallback_unchanged():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert (
            playground.show_project_memory_package()
            == "No packaged project memory available."
        )
        assert (
            playground.show_project_memory_package(compact=True)
            == "No packaged project memory available."
        )


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


def test_multiline_paste_starting_with_set_focus_does_not_mutate_state():
    """UI-04: pasted blocks must not run set focus / set stage as commands."""
    reset_agent_state()
    with isolated_runtime_files():
        original_ask_ai = playground.ask_ai
        try:
            playground.handle_user_input("set focus: baseline-focus")
            playground.ask_ai = lambda messages, system_prompt=None: (
                "Answer:\nAck.\n\nCurrent state:\nFocus: baseline-focus\n"
                "Stage: Phase 4 action-layer refinement\nAction type: build\n\nNext step:\nContinue."
            )
            blob = "set focus: evil-hijack\nsecond line of pasted content\n"
            result = playground.handle_user_input(blob)
            assert playground.current_state["focus"] == "baseline-focus", "Multiline paste must not change focus"
            assert "✅ Focus updated" not in result
        finally:
            playground.ask_ai = original_ask_ai


def test_oversized_single_line_set_focus_is_ignored_as_command():
    """UI-04: one very long line is not a direct command."""
    reset_agent_state()
    with isolated_runtime_files():
        original_ask_ai = playground.ask_ai
        try:
            playground.handle_user_input("set focus: baseline2")
            long_tail = "x" * 300
            payload = "set focus: " + long_tail
            assert "\n" not in payload
            assert len(payload) > playground.STATE_COMMAND_INPUT_MAX_CHARS
            playground.ask_ai = lambda messages, system_prompt=None: (
                "Answer:\nAck.\n\nCurrent state:\nFocus: baseline2\n"
                "Stage: Phase 4 action-layer refinement\nAction type: build\n\nNext step:\nContinue."
            )
            _ = playground.handle_user_input(payload)
            assert playground.current_state["focus"] == "baseline2"
        finally:
            playground.ask_ai = original_ask_ai


def test_long_multiline_log_no_false_outcome_feedback():
    """UI-04: logs containing 'failed' must not create outcome_feedback rows."""
    reset_agent_state()
    with isolated_runtime_files():
        original_ask_ai = playground.ask_ai
        try:
            playground.ask_ai = lambda messages, system_prompt=None: (
                "Answer:\nAck.\n\nCurrent state:\nFocus: ai-agent project\n"
                "Stage: Phase 4 action-layer refinement\nAction type: build\n\nNext step:\nContinue."
            )
            lines = ["line %s failed to compile" % i for i in range(30)]
            blob = "\n".join(lines)
            assert len(blob) > playground.OUTCOME_FEEDBACK_INPUT_MAX_CHARS
            _ = playground.handle_user_input(blob)
            entries = playground.load_project_journal()
            outcome_entries = [e for e in entries if e.get("entry_type") == "outcome_feedback"]
            assert not outcome_entries, outcome_entries
        finally:
            playground.ask_ai = original_ask_ai


def test_outcome_feedback_skipped_when_single_line_exceeds_length_cap():
    """UI-04: very long single-line text is not treated as operator outcome feedback."""
    reset_agent_state()
    with isolated_runtime_files():
        original_ask_ai = playground.ask_ai
        try:
            playground.ask_ai = lambda messages, system_prompt=None: (
                "Answer:\nAck.\n\nCurrent state:\nFocus: ai-agent project\n"
                "Stage: Phase 4 action-layer refinement\nAction type: build\n\nNext step:\nContinue."
            )
            s = ("x" * 200) + " failed " + ("y" * 30)
            assert "\n" not in s
            assert len(s) > playground.OUTCOME_FEEDBACK_INPUT_MAX_CHARS
            _ = playground.handle_user_input(s)
            entries = playground.load_project_journal()
            outcome_entries = [e for e in entries if e.get("entry_type") == "outcome_feedback"]
            assert not outcome_entries, outcome_entries
        finally:
            playground.ask_ai = original_ask_ai


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
        # Body must exceed LATENCY-10 trivial cap so the second post-fetch LLM still runs.
        playground.fetch_page = lambda url: f"FAKE FETCH OK: {url} " + ("a" * 70)

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


def test_fetch_failure_short_circuits_second_llm():
    """LATENCY-07: structured fetch failures skip the post-fetch model call."""
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "TOOL:fetch https://example.com/slow"
            raise AssertionError("Second LLM call should not run for fetch failure short-circuit")

        playground.ask_ai = fake_ask_ai
        playground.fetch_page = lambda url: "[fetch:timeout] Request timed out."

        result = playground.handle_user_input("Read https://example.com/slow")

        assert call_count["n"] == 1, f"Expected 1 LLM call, got {call_count['n']}"
        assert "Answer:" in result
        assert "Action type: research" in result
        assert "[fetch:timeout]" in result
        assert "Try a different public page" in result, "Expected deterministic next step for timeout tag"

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_fetch_whitespace_only_short_circuits_second_llm():
    """LATENCY-08: whitespace-only fetch body skips second ask_ai after normalization."""
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "TOOL:fetch https://example.com/empty"
            raise AssertionError("Second LLM call should not run")

        playground.ask_ai = fake_ask_ai
        playground.fetch_page = lambda url: "   \n\t\r\n  "

        result = playground.handle_user_input("Read https://example.com/empty")

        assert call_count["n"] == 1
        assert "Answer:" in result and "Action type: research" in result

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_fetch_punctuation_only_short_circuits_second_llm():
    """LATENCY-08: no-alphanumeric fetch body skips second ask_ai (deterministic)."""
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "TOOL:fetch https://example.com/x"
            raise AssertionError("Second LLM call should not run")

        playground.ask_ai = fake_ask_ai
        playground.fetch_page = lambda url: "---\n...\n\t…"

        result = playground.handle_user_input("Read https://example.com/x")

        assert call_count["n"] == 1
        assert "Answer:" in result and "Action type: research" in result

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_fetch_trivially_small_short_circuits_second_llm():
    """LATENCY-10: valid tiny fetch skips second ask_ai."""
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "TOOL:fetch https://example.com/"
            raise AssertionError("Second LLM call should not run for trivial fetch")

        playground.ask_ai = fake_ask_ai
        playground.fetch_page = lambda url: "OK — saved."

        result = playground.handle_user_input("Read https://example.com/")

        assert call_count["n"] == 1
        assert "Answer:" in result and "Action type: research" in result

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_fetch_over_trivial_char_cap_still_uses_second_llm():
    """LATENCY-10: body over char cap still runs second ask_ai."""
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "TOOL:fetch https://example.com/long"
            return (
                "Answer:\n"
                "Summary line.\n\n"
                "Current state:\n"
                "Focus: ai-agent project\n"
                "Stage: Phase 4 action-layer refinement\n"
                "Action type: research\n\n"
                "Next step:\n"
                "Use another real page URL and verify the fetched summary stays grounded in the page content."
            )

        playground.ask_ai = fake_ask_ai
        body = "a" * 101
        playground.fetch_page = lambda url: body

        playground.handle_user_input("Read https://example.com/long")

        assert call_count["n"] == 2, f"Expected 2 LLM calls, got {call_count['n']}"

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_fetch_over_trivial_word_cap_still_uses_second_llm():
    """LATENCY-10: many short words still run second ask_ai."""
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "TOOL:fetch https://example.com/manywords"
            return (
                "Answer:\n"
                "Counted words.\n\n"
                "Current state:\n"
                "Focus: ai-agent project\n"
                "Stage: Phase 4 action-layer refinement\n"
                "Action type: research\n\n"
                "Next step:\n"
                "Use another real page URL and verify the fetched summary stays grounded in the page content."
            )

        playground.ask_ai = fake_ask_ai
        body = " ".join(f"w{i}" for i in range(13))
        assert len(body) < playground._LATENCY10_TRIVIAL_MAX_CHARS
        playground.fetch_page = lambda url: body

        playground.handle_user_input("Read https://example.com/manywords")

        assert call_count["n"] == 2, f"Expected 2 LLM calls, got {call_count['n']}"

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_fetch_failure_tag_plain_and_tagged():
    assert fetch_failure_tag("Hello world") is None
    assert fetch_failure_tag("[fetch:timeout] x") == "timeout"
    assert fetch_failure_tag("  [fetch:forbidden] HTTP 403") == "forbidden"


def test_fetch_page_http_403_classified():
    with patch.object(fetch_http_module.requests, "get") as mock_get:
        resp = Mock()
        resp.status_code = 403
        mock_get.return_value = resp
        out = fetch_page("https://example.com/protected")
    assert out.startswith("[fetch:forbidden]")
    assert "403" in out
    assert fetch_failure_tag(out) == "forbidden"


def test_fetch_page_timeout_classified():
    with patch.object(fetch_http_module.requests, "get") as mock_get:
        mock_get.side_effect = Timeout()
        out = fetch_page("https://example.com/slow")
    assert out.startswith("[fetch:timeout]")
    assert fetch_failure_tag(out) == "timeout"


def test_fetch_page_network_classified():
    with patch.object(fetch_http_module.requests, "get") as mock_get:
        mock_get.side_effect = RequestsConnectionError("failed to connect")
        out = fetch_page("https://example.invalid/")
    assert out.startswith("[fetch:network]")
    assert fetch_failure_tag(out) == "network"


def test_fetch_page_401_and_404_classified():
    with patch.object(fetch_http_module.requests, "get") as mock_get:
        r401 = Mock()
        r401.status_code = 401
        r404 = Mock()
        r404.status_code = 404
        mock_get.side_effect = [r401, r404]
        a = fetch_page("https://example.com/login")
        b = fetch_page("https://example.com/missing")
    assert fetch_failure_tag(a) == "auth_required"
    assert "401" in a
    assert fetch_failure_tag(b) == "http_client_error"
    assert "404" in b


def test_fetch_page_200_substantial_html_untagged():
    html = "<html><body><p>" + ("word " * 50) + "</p></body></html>"
    with patch.object(fetch_http_module.requests, "get") as mock_get:
        resp = Mock()
        resp.status_code = 200
        resp.text = html
        mock_get.return_value = resp
        out = fetch_page("https://example.com/doc")
    assert not out.startswith("[fetch:")
    assert "word" in out


def test_fetch_page_200_empty_body_low_content():
    with patch.object(fetch_http_module.requests, "get") as mock_get:
        resp = Mock()
        resp.status_code = 200
        resp.text = "<html><body></body></html>"
        mock_get.return_value = resp
        out = fetch_page("https://example.com/empty")
    assert fetch_failure_tag(out) == "low_content"
    assert "JavaScript" in out or "login" in out.lower()


def test_choose_post_fetch_next_step_recognizes_fetch_tags():
    ns_block = prompt_builder.choose_post_fetch_next_step(
        "[fetch:forbidden] HTTP 403 Forbidden. blocked."
    )
    assert "paste" in ns_block.lower() or "public" in ns_block.lower()
    ns_low = prompt_builder.choose_post_fetch_next_step(
        "[fetch:low_content] Very little text was extracted (3 characters)."
    )
    assert "static" in ns_low.lower() or "javascript" in ns_low.lower() or "paste" in ns_low.lower()


def test_fetch_via_browser_invalid_url():
    from tools.fetch_browser import fetch_via_browser

    out = fetch_via_browser("file:///tmp/x")
    assert fetch_failure_tag(out) == "browser_invalid_url"


def test_fetch_via_browser_unavailable_when_playwright_unresolved():
    from tools.fetch_browser import fetch_via_browser

    with patch("tools.fetch_browser._resolve_sync_playwright", return_value=None):
        out = fetch_via_browser("https://example.com/")
    assert fetch_failure_tag(out) == "browser_unavailable"


def test_chromium_launch_args_include_transport_hints():
    from tools.fetch_browser import _chromium_launch_args

    args = _chromium_launch_args()
    assert "--disable-http2" in args
    assert "--disable-quic" in args


def test_prefer_headline_blob_when_visible_thin_or_shorter():
    from tools.fetch_browser import _prefer_headline_blob_over_visible

    long_h = "Breaking: markets " * 6
    assert _prefer_headline_blob_over_visible(long_h, "reuters.com") is True
    assert _prefer_headline_blob_over_visible(long_h, "x" * 200) is False
    assert _prefer_headline_blob_over_visible("", "anything") is False


def test_bounded_dom_text_nodes_via_eval_calls_evaluate_with_timeout():
    from tools.fetch_browser import _bounded_dom_text_nodes_via_eval

    page = MagicMock()
    page.evaluate = MagicMock(return_value="  alpha   beta  gamma  ")

    out = _bounded_dom_text_nodes_via_eval(page, 4500)
    assert out == "alpha beta gamma"
    page.evaluate.assert_called_once()
    _js, kwargs = page.evaluate.call_args[0][0], page.evaluate.call_args[1]
    assert "textContent" in _js or "nodeType" in _js
    assert kwargs.get("timeout") == 4500


def test_nav_exc_class_blocked_transport_and_goto_timeout():
    from tools.fetch_browser import _nav_exc_class

    e1 = Exception("Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR")
    assert _nav_exc_class(e1) == "blocked_transport"
    e2 = Exception("Page.goto: Timeout 20000ms exceeded")
    assert _nav_exc_class(e2) == "goto_timeout"


def test_probe_dict_from_evaluate_result_accepts_json_string():
    from tools.fetch_browser import _probe_dict_from_evaluate_result

    s = '{"b":1,"m":0,"r":0,"a":0,"h1":2,"h2":3,"bit":11,"bct":4000}'
    d = _probe_dict_from_evaluate_result(s)
    assert d is not None
    assert d["b"] == 1 and d["h1"] == 2 and d["bct"] == 4000


def test_normalize_probe_dict_coerces_floaty_values():
    from tools.fetch_browser import _normalize_probe_dict

    d = _normalize_probe_dict({"b": 1.0, "h1": "2", "x": 99})
    assert d["b"] == 1 and d["h1"] == 2
    assert "x" not in d


def test_bounded_dom_probe_fallback_pipe_parses():
    from tools.fetch_browser import _bounded_dom_probe_fallback_pipe

    page = MagicMock()
    page.evaluate = MagicMock(return_value="1|100|50|2|3|1|0|1")
    d = _bounded_dom_probe_fallback_pipe(page, 5000)
    assert d is not None
    assert d["fb"] == 1
    assert d["bct"] == 100 and d["bit"] == 50


def test_bounded_dom_probe_micro_lengths_sets_fb2():
    from tools.fetch_browser import _bounded_dom_probe_micro_lengths

    page = MagicMock()
    page.evaluate = MagicMock(side_effect=[42, 9000])
    d = _bounded_dom_probe_micro_lengths(page, 9000)
    assert d is not None
    assert d["fb"] == 2
    assert d["bit"] == 42 and d["bct"] == 9000


def test_bounded_dom_probe_via_eval_sets_st_when_all_evaluate_fail():
    from tools.fetch_browser import _bounded_dom_probe_via_eval

    page = MagicMock()
    page.evaluate = MagicMock(side_effect=RuntimeError("blocked"))
    d = _bounded_dom_probe_via_eval(page, 5000)
    assert d is not None
    assert d.get("st") == 1


def test_fetch_failure_tag_parses_low_content_with_diag_suffix():
    from tools.fetch_page import fetch_failure_tag

    s = (
        "[fetch:low_content] Browser extracted very little text (11 characters). "
        "Snippet: x diag=mrg=11;b=1;h1=0;probe=none"
    )
    assert fetch_failure_tag(s) == "low_content"


def test_bounded_extract_prefers_main_landmark_over_thin_body():
    from tools.fetch_browser import _bounded_extract_visible_text

    def locator_for(sel: str):
        layer = MagicMock()
        first = MagicMock()
        mapping = {
            "body": "reuters.com",
            "main": "Daily briefing " * 8,
            '[role="main"]': "",
            "article": "",
        }

        def inner_text(**kwargs):
            return mapping.get(sel, "")

        first.inner_text = inner_text
        layer.first = first
        return layer

    page = MagicMock()
    page.locator = lambda s: locator_for(s)
    out = _bounded_extract_visible_text(page, 10_000)
    assert "Daily briefing" in out
    assert len(out) >= 80


def test_goto_bounded_retries_ladder_commit_then_domcontentloaded():
    from tools.fetch_browser import _goto_with_bounded_retries

    page = MagicMock()
    page.goto.side_effect = [RuntimeError("ERR_HTTP2_PROTOCOL_ERROR"), None]
    _goto_with_bounded_retries(page, "https://example.com/", 30_000)
    assert page.goto.call_count == 2
    assert page.goto.call_args_list[0][1]["wait_until"] == "commit"
    assert page.goto.call_args_list[1][1]["wait_until"] == "domcontentloaded"
    assert page.goto.call_args_list[0][1]["timeout"] == 10_000
    assert page.goto.call_args_list[1][1]["timeout"] == 10_000


def test_goto_bounded_retries_reaches_load_after_two_failures():
    from tools.fetch_browser import _goto_with_bounded_retries

    page = MagicMock()
    page.goto.side_effect = [RuntimeError("a"), RuntimeError("b"), None]
    _goto_with_bounded_retries(page, "https://example.com/", 12_000)
    assert page.goto.call_count == 3
    assert page.goto.call_args_list[0][1]["wait_until"] == "commit"
    assert page.goto.call_args_list[1][1]["wait_until"] == "domcontentloaded"
    assert page.goto.call_args_list[2][1]["wait_until"] == "load"
    assert page.goto.call_args_list[2][1]["timeout"] == 4000


def test_goto_bounded_retries_raises_after_three_failures():
    from tools.fetch_browser import _goto_with_bounded_retries

    page = MagicMock()
    page.goto.side_effect = RuntimeError("blocked")
    try:
        _goto_with_bounded_retries(page, "https://example.com/", 9000)
    except RuntimeError:
        # Ladder (commit, domcontentloaded, load) then one domcontentloaded recovery.
        assert page.goto.call_count == 4
    else:
        raise AssertionError("expected raise after ladder + recovery failures")


def test_fetch_page_browser_mode_dispatches_to_browser_backend():
    old = os.environ.get("FETCH_MODE")
    try:
        os.environ["FETCH_MODE"] = "browser"
        with patch("tools.fetch_page.fetch_via_browser", side_effect=lambda url, timeout_seconds=20: "Title\n\nbody"):
            out = fetch_page("https://example.com/")
        assert out == "Title\n\nbody"
    finally:
        if old is None:
            os.environ.pop("FETCH_MODE", None)
        else:
            os.environ["FETCH_MODE"] = old


def test_browser_timeout_seconds_default_and_clamp():
    from tools.fetch_page import browser_timeout_seconds_from_env

    with patch.dict(os.environ, {"FETCH_BROWSER_TIMEOUT_SECONDS": ""}):
        assert browser_timeout_seconds_from_env() == 20
    with patch.dict(os.environ, {"FETCH_BROWSER_TIMEOUT_SECONDS": "3"}):
        assert browser_timeout_seconds_from_env() == 5
    with patch.dict(os.environ, {"FETCH_BROWSER_TIMEOUT_SECONDS": "999"}):
        assert browser_timeout_seconds_from_env() == 120


def test_browser_timeout_seconds_invalid_env_uses_default():
    from tools.fetch_page import browser_timeout_seconds_from_env

    with patch.dict(os.environ, {"FETCH_BROWSER_TIMEOUT_SECONDS": "x"}):
        assert browser_timeout_seconds_from_env() == 20


def test_browser_adapter_forwards_fetch_browser_timeout_env():
    old_mode = os.environ.get("FETCH_MODE")
    old_to = os.environ.get("FETCH_BROWSER_TIMEOUT_SECONDS")
    try:
        os.environ["FETCH_MODE"] = "browser"
        os.environ["FETCH_BROWSER_TIMEOUT_SECONDS"] = "42"
        with patch("tools.fetch_page.fetch_via_browser", return_value="OK") as m:
            out = fetch_page("https://example.com/z")
        assert out == "OK"
        assert m.call_args[0][0] == "https://example.com/z"
        assert m.call_args[1]["timeout_seconds"] == 42
    finally:
        if old_mode is None:
            os.environ.pop("FETCH_MODE", None)
        else:
            os.environ["FETCH_MODE"] = old_mode
        if old_to is None:
            os.environ.pop("FETCH_BROWSER_TIMEOUT_SECONDS", None)
        else:
            os.environ["FETCH_BROWSER_TIMEOUT_SECONDS"] = old_to


def test_choose_post_fetch_next_step_browser_unavailable_tag():
    ns = prompt_builder.choose_post_fetch_next_step(
        "[fetch:browser_unavailable] Playwright is not installed."
    )
    assert "paste" in ns.lower() or "public" in ns.lower()


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


def test_system_eval_validate_suite_requires_non_empty_cases():
    try:
        system_eval_core.validate_suite({"suite_name": "x", "target_name": "y", "cases": []})
        assert False, "Expected ValueError for empty cases"
    except ValueError as exc:
        assert "non-empty 'cases'" in str(exc), exc


def test_system_eval_validate_suite_rejects_invalid_lane():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "bad-lane",
                "target_name": "t",
                "cases": [
                    {
                        "name": "c1",
                        "lane": "throughput",
                        "method": "POST",
                        "url": "http://fake.local/x",
                        "payload": {},
                        "assertions": {"status_code": 200},
                    }
                ],
            }
        )
        assert False, "Expected ValueError for invalid lane"
    except ValueError as exc:
        assert "lane" in str(exc).lower(), exc
        assert "throughput" in str(exc), exc


def test_system_eval_lane_preserved_in_results_and_artifacts():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "lane-suite",
            "target_name": "fake-target",
            "cases": [
                {
                    "name": "a",
                    "lane": "stability",
                    "method": "POST",
                    "url": "http://fake.local/a",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["ok"]},
                },
                {
                    "name": "b",
                    "lane": "correctness",
                    "method": "POST",
                    "url": "http://fake.local/b",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["ok"]},
                },
                {
                    "name": "c",
                    "lane": "consistency",
                    "method": "POST",
                    "url": "http://fake.local/c",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["ok"]},
                },
                {
                    "name": "no-lane",
                    "method": "POST",
                    "url": "http://fake.local/d",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["ok"]},
                },
            ],
        }
    )

    class FakeAdapter:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=3
            )

    result = system_eval_core.execute_suite(suite, adapter=FakeAdapter())
    assert result["cases"][0]["lane"] == "stability", result["cases"][0]
    assert result["cases"][1]["lane"] == "correctness", result["cases"][1]
    assert result["cases"][2]["lane"] == "consistency", result["cases"][2]
    assert result["cases"][0]["stability_attempts"] == 3, result["cases"][0]
    assert result["cases"][0]["attempts_total"] == 3, result["cases"][0]
    assert result["cases"][0]["attempts_passed"] == 3, result["cases"][0]
    assert len(result["cases"][0]["attempts"]) == 3, result["cases"][0]
    assert result["cases"][2]["repeat_count"] == 3, result["cases"][2]
    assert result["cases"][2]["attempts_total"] == 3, result["cases"][2]
    assert result["cases"][2]["attempts_passed"] == 3, result["cases"][2]
    assert len(result["cases"][2]["attempts"]) == 3, result["cases"][2]
    assert "repeat_count" not in result["cases"][0], result["cases"][0]
    assert "attempts" not in result["cases"][1], result["cases"][1]
    assert result["cases"][3]["lane"] is None, result["cases"][3]

    with tempfile.TemporaryDirectory() as temp_dir:
        paths = system_eval_core.write_result_artifacts(
            result, temp_dir, file_stem="lane_artifact"
        )
        written = json.loads(Path(paths["json_path"]).read_text(encoding="utf-8"))
        assert written["cases"][0]["lane"] == "stability", written
        assert written["cases"][3]["lane"] is None, written
        assert written["cases"][0]["attempts_passed"] == 3, written
        assert written["cases"][2]["attempts_passed"] == 3, written
        md_text = Path(paths["markdown_path"]).read_text(encoding="utf-8")
        assert "lane=`stability`" in md_text, md_text
        assert "lane=`correctness`" in md_text, md_text
        assert "lane=`consistency`" in md_text, md_text
        assert "lane=(none)" in md_text, md_text
        assert "stability:" in md_text, md_text
        assert "stability_attempts=`3`" in md_text, md_text
        assert "consistency:" in md_text, md_text
        assert "attempt `1`:" in md_text, md_text


def test_system_eval_repeat_count_rejected_when_lane_not_consistency():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "x",
                "target_name": "y",
                "cases": [
                    {
                        "name": "c1",
                        "lane": "stability",
                        "repeat_count": 3,
                        "method": "POST",
                        "url": "http://fake.local/x",
                        "payload": {},
                        "assertions": {"status_code": 200},
                    }
                ],
            }
        )
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "repeat_count" in str(exc).lower(), exc
        assert "consistency" in str(exc).lower(), exc


def test_system_eval_invalid_repeat_count_rejected():
    for bad in (0, -1, 51, "x"):
        try:
            system_eval_core.validate_suite(
                {
                    "suite_name": "x",
                    "target_name": "y",
                    "cases": [
                        {
                            "name": "c1",
                            "lane": "consistency",
                            "repeat_count": bad,
                            "method": "POST",
                            "url": "http://fake.local/x",
                            "payload": {},
                            "assertions": {"status_code": 200},
                        }
                    ],
                }
            )
            assert False, f"Expected ValueError for repeat_count={bad!r}"
        except ValueError:
            pass


def test_system_eval_consistency_runs_adapter_exactly_n_times():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "consistency-n",
            "target_name": "t",
            "cases": [
                {
                    "name": "multi",
                    "lane": "consistency",
                    "repeat_count": 5,
                    "method": "POST",
                    "url": "http://fake.local/m",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["ok"]},
                }
            ],
        }
    )

    class CountAdapter:
        def __init__(self):
            self.calls = 0

        def run_case(self, case):
            self.calls += 1
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=1
            )

    adapter = CountAdapter()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert adapter.calls == 5, adapter.calls
    assert result["cases"][0]["attempts_total"] == 5, result["cases"][0]
    assert result["cases"][0]["attempts_passed"] == 5, result["cases"][0]
    assert result["ok"] is True, result


def test_system_eval_consistency_fails_when_one_attempt_fails_assertion():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "consistency-fail",
            "target_name": "t",
            "cases": [
                {
                    "name": "wobble",
                    "lane": "consistency",
                    "repeat_count": 4,
                    "method": "POST",
                    "url": "http://fake.local/w",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["STABLE_MARKER"]},
                }
            ],
        }
    )

    class WobbleAdapter:
        def __init__(self):
            self.n = 0

        def run_case(self, case):
            self.n += 1
            _ = case
            if self.n == 3:
                return system_eval_core.AdapterResult(
                    ok=True, status_code=200, output_text="no marker here", latency_ms=2
                )
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok STABLE_MARKER ok", latency_ms=2
            )

    result = system_eval_core.execute_suite(suite, adapter=WobbleAdapter())
    assert result["ok"] is False, result
    assert result["cases"][0]["attempts_passed"] == 3, result["cases"][0]
    assert result["cases"][0]["attempts_total"] == 4, result["cases"][0]
    assert any("attempt 3/4" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_run_tool1_system_eval_operator_helper_with_fake_adapter():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out = root / "out"
        suite_data = {
            "suite_name": "ui-helper-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "c1",
                    "method": "POST",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["hi"]},
                }
            ],
        }
        suite_path = root / "suite.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")

        class FakeAdapter:
            def run_case(self, case):
                _ = case
                return system_eval_core.AdapterResult(
                    ok=True, status_code=200, output_text="hi there", latency_ms=3
                )

        bundle = run_tool1_system_eval_http(
            str(suite_path),
            str(out),
            "ui_test_run",
            project_root=root,
            adapter=FakeAdapter(),
        )
        assert bundle.get("error") is None, bundle
        assert bundle["ok"] is True, bundle
        assert Path(bundle["artifact_paths"]["json_path"]).is_file(), bundle
        assert Path(bundle["artifact_paths"]["markdown_path"]).is_file(), bundle
        assert "ui-helper-suite" in bundle["json_preview"]
        assert "ui_test_run" in bundle["artifact_paths"]["json_path"]


def test_run_tool1_system_eval_operator_missing_suite_file():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bundle = run_tool1_system_eval_http(
            str(root / "missing.json"),
            str(root / "out"),
            "x",
            project_root=root,
            adapter=None,
        )
        assert bundle.get("error")
        assert "not found" in bundle["error"].lower()


def test_tool1_run_log_jsonl_written_for_suite_success_and_failure():
    from app import tool1_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        log_path = tool1_run_log.tool1_run_log_path(root)
        assert not log_path.exists()

        bundle_bad = run_tool1_system_eval_http(
            str(root / "missing.json"),
            str(root / "out"),
            "x",
            project_root=root,
            adapter=None,
        )
        assert bundle_bad.get("error")
        assert log_path.is_file(), "append-only log should be created on first suite attempt"
        lines_bad = log_path.read_text(encoding="utf-8").strip().splitlines()
        rec_bad = json.loads(lines_bad[-1])
        assert rec_bad["schema_version"] == tool1_run_log.TOOL1_RUN_LOG_SCHEMA_VERSION
        assert rec_bad["run_type"] == "suite_run"
        assert rec_bad["error"] is not None
        assert rec_bad["requests"] == []

        suite_path = root / "suite.json"
        suite_path.write_text(
            json.dumps(
                {
                    "suite_name": "log-test-suite",
                    "target_name": "t",
                    "cases": [
                        {
                            "name": "a",
                            "method": "GET",
                            "url": "http://f/x",
                            "payload": {},
                            "assertions": {},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        class FakeAdapter:
            def run_case(self, case):
                _ = case
                return system_eval_core.AdapterResult(
                    ok=True, status_code=200, output_text="{}", latency_ms=1
                )

        bundle_ok = run_tool1_system_eval_http(
            str(suite_path),
            str(root / "out2"),
            "stem",
            project_root=root,
            adapter=FakeAdapter(),
        )
        assert bundle_ok.get("error") in (None, "")
        lines_all = log_path.read_text(encoding="utf-8").strip().splitlines()
        rec_ok = json.loads(lines_all[-1])
        assert rec_ok["run_type"] == "suite_run"
        assert rec_ok["error"] is None
        assert rec_ok["suite_name"] == "log-test-suite"
        assert rec_ok["result_summary"]["overall_ok"] is True
        assert rec_ok["artifact_paths"].get("json_path")
        assert len(rec_ok.get("requests") or []) == 1
        assert len(rec_ok.get("cases_outcome") or []) == 1


def test_http_target_adapter_get_omits_json_keyword():
    adapter = system_eval_core.HttpTargetAdapter(default_timeout_seconds=5)
    case = {
        "name": "g",
        "method": "GET",
        "url": "http://example.test/get",
        "headers": {},
        "payload": {"must_not": "appear_as_requests_json_kwarg"},
        "timeout_seconds": 5,
        "assertions": {},
    }
    mock_resp = Mock()
    mock_resp.text = "ok"
    mock_resp.status_code = 200
    with patch("core.system_eval.requests.request", return_value=mock_resp) as p_req:
        result = adapter.run_case(case)
    assert result.ok is True, result
    assert result.status_code == 200
    p_req.assert_called_once()
    assert "json" not in p_req.call_args.kwargs, p_req.call_args.kwargs


def test_http_target_adapter_head_omits_json_keyword():
    adapter = system_eval_core.HttpTargetAdapter(default_timeout_seconds=5)
    case = {
        "name": "h",
        "method": "HEAD",
        "url": "http://example.test/r",
        "headers": {},
        "payload": {"x": 1},
        "timeout_seconds": 5,
        "assertions": {},
    }
    mock_resp = Mock()
    mock_resp.text = ""
    mock_resp.status_code = 204
    with patch("core.system_eval.requests.request", return_value=mock_resp) as p_req:
        result = adapter.run_case(case)
    assert result.ok is True
    assert "json" not in p_req.call_args.kwargs


def test_http_target_adapter_post_passes_json_payload():
    adapter = system_eval_core.HttpTargetAdapter(default_timeout_seconds=5)
    payload = {"a": 1, "b": "two"}
    case = {
        "name": "p",
        "method": "POST",
        "url": "http://example.test/post",
        "headers": {},
        "payload": payload,
        "timeout_seconds": 5,
        "assertions": {},
    }
    mock_resp = Mock()
    mock_resp.text = '{"ok":true}'
    mock_resp.status_code = 200
    with patch("core.system_eval.requests.request", return_value=mock_resp) as p_req:
        result = adapter.run_case(case)
    assert result.ok is True
    assert p_req.call_args.kwargs.get("json") == payload


def test_http_target_adapter_post_body_null_omits_json_keyword():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "body-null",
            "target_name": "t",
            "cases": [
                {
                    "name": "no-json-body",
                    "method": "POST",
                    "url": "http://example.test/p",
                    "body": None,
                    "payload": {"ignored": True},
                    "assertions": {"status_code": 200},
                }
            ],
        }
    )
    case = suite["cases"][0]
    adapter = system_eval_core.HttpTargetAdapter(default_timeout_seconds=5)
    mock_resp = Mock()
    mock_resp.text = ""
    mock_resp.status_code = 200
    with patch("core.system_eval.requests.request", return_value=mock_resp) as p_req:
        result = adapter.run_case(case)
    assert result.ok is True
    assert "json" not in p_req.call_args.kwargs


def test_http_target_adapter_get_send_json_body_passes_json():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "get-json-escape",
            "target_name": "t",
            "cases": [
                {
                    "name": "rare-get-json",
                    "method": "GET",
                    "url": "http://example.test/g",
                    "send_json_body": True,
                    "payload": {"q": 1},
                    "assertions": {"status_code": 200},
                }
            ],
        }
    )
    case = suite["cases"][0]
    adapter = system_eval_core.HttpTargetAdapter(default_timeout_seconds=5)
    mock_resp = Mock()
    mock_resp.text = "{}"
    mock_resp.status_code = 200
    with patch("core.system_eval.requests.request", return_value=mock_resp) as p_req:
        result = adapter.run_case(case)
    assert result.ok is True
    assert p_req.call_args.kwargs.get("json") == {"q": 1}


def test_http_target_adapter_populates_response_headers_from_requests():
    adapter = system_eval_core.HttpTargetAdapter(default_timeout_seconds=5)
    case = {
        "name": "h",
        "method": "GET",
        "url": "http://example.test/r",
        "headers": {},
        "payload": {},
        "timeout_seconds": 5,
        "assertions": {},
    }
    mock_resp = Mock()
    mock_resp.text = "ok"
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/json", "X-Custom": "abc"}
    with patch("core.system_eval.requests.request", return_value=mock_resp):
        result = adapter.run_case(case)
    assert result.ok is True
    assert result.response_headers.get("Content-Type") == "application/json"
    assert result.response_headers.get("X-Custom") == "abc"


def test_http_target_adapter_request_exception_has_empty_response_headers():
    adapter = system_eval_core.HttpTargetAdapter(default_timeout_seconds=5)
    case = {
        "name": "x",
        "method": "GET",
        "url": "http://example.test/nope",
        "headers": {},
        "payload": {},
        "timeout_seconds": 5,
        "assertions": {},
    }
    with patch("core.system_eval.requests.request", side_effect=RequestsConnectionError("boom")):
        result = adapter.run_case(case)
    assert result.ok is False
    assert result.response_headers == {}


def test_execute_suite_and_artifact_include_response_headers():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "hdr-suite",
            "target_name": "t",
            "cases": [
                {
                    "name": "one",
                    "method": "POST",
                    "url": "http://fake.local/z",
                    "payload": {},
                    "assertions": {"status_code": 200},
                }
            ],
        }
    )

    class HeaderAdapter:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="ok",
                latency_ms=2,
                response_headers={"X-RateLimit-Remaining": "59", "Content-Type": "text/plain"},
            )

    result = system_eval_core.execute_suite(suite, adapter=HeaderAdapter())
    assert result["cases"][0]["response_headers"].get("X-RateLimit-Remaining") == "59"
    assert result["cases"][0]["response_headers"].get("Content-Type") == "text/plain"

    with tempfile.TemporaryDirectory() as td:
        paths = system_eval_core.write_result_artifacts(result, td, file_stem="hdr_run")
        written = json.loads(Path(paths["json_path"]).read_text(encoding="utf-8"))
        assert written["cases"][0]["response_headers"]["X-RateLimit-Remaining"] == "59"


def test_execute_suite_stability_attempts_include_response_headers():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "hdr-stability",
            "target_name": "t",
            "cases": [
                {
                    "name": "s",
                    "lane": "stability",
                    "stability_attempts": 2,
                    "method": "POST",
                    "url": "http://fake.local/s",
                    "payload": {},
                    "assertions": {"status_code": 200},
                }
            ],
        }
    )

    class H:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="",
                latency_ms=1,
                response_headers={"Etag": '"abc"'},
            )

    result = system_eval_core.execute_suite(suite, adapter=H())
    assert result["cases"][0]["response_headers"].get("Etag") == '"abc"'
    assert len(result["cases"][0]["attempts"]) == 2
    assert result["cases"][0]["attempts"][0]["response_headers"].get("Etag") == '"abc"'
    assert result["cases"][0]["attempts"][1]["response_headers"].get("Etag") == '"abc"'


def test_normalize_response_headers_caps_items_and_truncates_long_values():
    many = {f"Header-{i}": str(i) for i in range(70)}
    capped = system_eval_core._normalize_response_headers(many)
    assert system_eval_core._RESPONSE_HEADERS_OMITTED_KEY in capped
    assert capped[system_eval_core._RESPONSE_HEADERS_OMITTED_KEY] == "6"
    assert len(capped) == 65

    long_val = "z" * 10000
    truncated = system_eval_core._normalize_response_headers({"X": long_val})
    assert len(truncated["X"]) < len(long_val)
    assert "...[truncated]" in truncated["X"]


def test_execute_suite_stores_output_full_for_short_body():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "full-body-short",
            "target_name": "t",
            "cases": [
                {
                    "name": "c1",
                    "method": "POST",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["hello"]},
                }
            ],
        }
    )

    class ShortBodyAdapter:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world payload",
                latency_ms=2,
            )

    result = system_eval_core.execute_suite(suite, adapter=ShortBodyAdapter())
    c0 = result["cases"][0]
    assert c0["output_preview"] == "hello world payload"
    assert c0["output_full"] == "hello world payload"


def test_execute_suite_output_full_truncates_large_body():
    cap = system_eval_core._OUTPUT_FULL_MAX_CHARS
    long_body = "Q" * (cap + 5000)
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "full-body-long",
            "target_name": "t",
            "cases": [
                {
                    "name": "big",
                    "method": "POST",
                    "url": "http://fake.local/big",
                    "payload": {},
                    "assertions": {"status_code": 200},
                }
            ],
        }
    )

    class LongBodyAdapter:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text=long_body, latency_ms=1
            )

    result = system_eval_core.execute_suite(suite, adapter=LongBodyAdapter())
    full = result["cases"][0]["output_full"]
    assert len(full) == cap, len(full)
    assert full.endswith(system_eval_core._OUTPUT_FULL_TRUNC_MARKER), full[-40:]
    assert len(result["cases"][0]["output_preview"]) <= 600


def test_system_eval_validate_suite_rejects_body_non_null():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "bad-body",
                "target_name": "t",
                "cases": [
                    {
                        "name": "c",
                        "method": "POST",
                        "url": "http://x",
                        "body": {},
                        "assertions": {},
                    }
                ],
            }
        )
    except ValueError as exc:
        assert "body" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError for non-null body")


def test_system_eval_stability_runs_default_three_times():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "stability-default",
            "target_name": "t",
            "cases": [
                {
                    "name": "s",
                    "lane": "stability",
                    "method": "POST",
                    "url": "http://fake.local/s",
                    "payload": {},
                    "assertions": {"status_code": 200},
                }
            ],
        }
    )

    class CountAdapter:
        def __init__(self):
            self.calls = 0

        def run_case(self, case):
            self.calls += 1
            _ = case
            return system_eval_core.AdapterResult(ok=True, status_code=200, output_text="", latency_ms=1)

    adapter = CountAdapter()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert adapter.calls == 3, adapter.calls
    assert result["cases"][0]["stability_attempts"] == 3, result["cases"][0]


def test_system_eval_stability_runs_adapter_exactly_n_times():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "stability-n",
            "target_name": "t",
            "cases": [
                {
                    "name": "s",
                    "lane": "stability",
                    "stability_attempts": 6,
                    "method": "POST",
                    "url": "http://fake.local/s",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["ok"]},
                }
            ],
        }
    )

    class CountAdapter:
        def __init__(self):
            self.calls = 0

        def run_case(self, case):
            self.calls += 1
            _ = case
            return system_eval_core.AdapterResult(ok=True, status_code=200, output_text="ok", latency_ms=1)

    adapter = CountAdapter()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert adapter.calls == 6, adapter.calls
    assert result["cases"][0]["attempts_total"] == 6, result["cases"][0]
    assert result["ok"] is True, result


def test_system_eval_stability_attempts_rejected_when_lane_not_stability():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "x",
                "target_name": "y",
                "cases": [
                    {
                        "name": "c1",
                        "lane": "correctness",
                        "stability_attempts": 3,
                        "method": "POST",
                        "url": "http://fake.local/x",
                        "payload": {},
                        "assertions": {"status_code": 200},
                    }
                ],
            }
        )
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "stability_attempts" in str(exc).lower(), exc


def test_system_eval_stability_attempts_rejected_when_lane_consistency():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "x",
                "target_name": "y",
                "cases": [
                    {
                        "name": "c1",
                        "lane": "consistency",
                        "stability_attempts": 3,
                        "method": "POST",
                        "url": "http://fake.local/x",
                        "payload": {},
                        "assertions": {"status_code": 200},
                    }
                ],
            }
        )
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "stability_attempts" in str(exc).lower(), exc
        assert "repeat_count" in str(exc).lower(), exc


def test_system_eval_invalid_stability_attempts_rejected():
    for bad in (0, -1, 51, "x"):
        try:
            system_eval_core.validate_suite(
                {
                    "suite_name": "x",
                    "target_name": "y",
                    "cases": [
                        {
                            "name": "c1",
                            "lane": "stability",
                            "stability_attempts": bad,
                            "method": "POST",
                            "url": "http://fake.local/x",
                            "payload": {},
                            "assertions": {"status_code": 200},
                        }
                    ],
                }
            )
            assert False, f"Expected ValueError for stability_attempts={bad!r}"
        except ValueError:
            pass


def test_system_eval_execute_suite_success_with_fake_adapter():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "unit-suite",
            "target_name": "fake-target",
            "cases": [
                {
                    "name": "case1",
                    "method": "POST",
                    "url": "http://fake.local/test",
                    "payload": {"input": "hello"},
                    "assertions": {"status_code": 200, "contains_all": ["healthy"], "not_contains": ["error"]},
                }
            ],
        }
    )

    class FakeAdapter:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="service healthy",
                latency_ms=11,
            )

    result = system_eval_core.execute_suite(suite, adapter=FakeAdapter())
    assert result["ok"] is True, result
    assert result["failed_cases"] == 0, result
    assert result["passed_cases"] == 1, result
    assert result["cases"][0]["ok"] is True, result["cases"][0]
    assert result["cases"][0]["lane"] is None, result["cases"][0]


def test_system_eval_execute_suite_records_assertion_failures():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "unit-suite",
            "target_name": "fake-target",
            "cases": [
                {
                    "name": "case1",
                    "method": "POST",
                    "url": "http://fake.local/test",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["required-token"]},
                }
            ],
        }
    )

    class FakeAdapter:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="missing expected content",
                latency_ms=7,
            )

    result = system_eval_core.execute_suite(suite, adapter=FakeAdapter())
    assert result["ok"] is False, result
    assert result["failed_cases"] == 1, result
    assert result["cases"][0]["ok"] is False, result["cases"][0]
    assert any("missing required token" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_expected_status_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "exp-status-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"expected_status": 201},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=201, output_text="", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_expected_status_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "exp-status-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"expected_status": 404},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_status=404" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_expected_response_time_ms_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "resp-time-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "response_time_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"expected_response_time_ms": 200},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=100, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_expected_response_time_ms_fail():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "resp-time-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "response_time_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"expected_response_time_ms": 200},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=300, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_response_time_ms exceeded" in f for f in result["cases"][0]["failures"]), (
        result["cases"][0]
    )
    joined = " ".join(result["cases"][0]["failures"])
    assert "200" in joined and "300" in joined, result["cases"][0]


def test_system_eval_expected_response_time_ms_equal():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "resp-time-eq",
            "target_name": "fake",
            "cases": [
                {
                    "name": "response_time_equal",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"expected_response_time_ms": 200},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=200, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_extract_simple():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "extract-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "extract_simple",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {
                        "body_json_has_key": ["user.id"],
                        "extract": {"user_id": "user.id"},
                    },
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"user": {"id": 42}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result
    assert result["cases"][0].get("variables") == {"user_id": 42}, result["cases"][0]


def test_system_eval_extract_missing_path():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "extract-miss",
            "target_name": "fake",
            "cases": [
                {
                    "name": "extract_missing_path",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"extract": {"user_id": "user.id"}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"user": {}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("extract missing path" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_variable_substitution_url_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "var-sub-url",
            "target_name": "fake",
            "cases": [
                {
                    "name": "sub_url_chain",
                    "method": "GET",
                    "request_url_initial": "https://example.com/login",
                    "url": "https://example.com/users/{{user_id}}",
                    "payload": {},
                    "assertions": {
                        "status_code": 200,
                        "extract": {"user_id": "user.id"},
                    },
                }
            ],
        }
    )

    class ChainAdapter:
        def __init__(self):
            self.urls = []

        def run_case(self, case):
            self.urls.append(case["url"])
            if case["url"].endswith("/login"):
                return system_eval_core.AdapterResult(
                    ok=True,
                    status_code=200,
                    output_text='{"user": {"id": 42}}',
                    latency_ms=1,
                    response_headers={},
                )
            if case["url"] == "https://example.com/users/42":
                return system_eval_core.AdapterResult(
                    ok=True,
                    status_code=200,
                    output_text='{"phase":"second-hop","user":{"id":42}}',
                    latency_ms=2,
                    response_headers={},
                )
            return system_eval_core.AdapterResult(
                ok=False,
                status_code=500,
                output_text="unexpected url",
                latency_ms=1,
                response_headers={},
            )

    adapter = ChainAdapter()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert result["ok"] is True, result
    assert adapter.urls == [
        "https://example.com/login",
        "https://example.com/users/42",
    ], adapter.urls
    assert result["cases"][0].get("variables") == {"user_id": 42}, result["cases"][0]


def test_system_eval_variable_substitution_missing_var():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "var-sub-miss",
            "target_name": "fake",
            "cases": [
                {
                    "name": "missing_placeholder",
                    "method": "GET",
                    "url": "https://example.com/{{missing}}",
                    "payload": {},
                    "assertions": {"status_code": 200},
                }
            ],
        }
    )

    class NoCallAdapter:
        def run_case(self, case):
            raise AssertionError("adapter should not run when substitution fails")

    result = system_eval_core.execute_suite(suite, adapter=NoCallAdapter())
    assert result["ok"] is False, result
    fails = result["cases"][0]["failures"]
    assert any("variable not found" in f for f in fails), fails
    assert any('"missing"' in f for f in fails), fails


def test_system_eval_variable_substitution_payload_string_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "var-sub-body-str",
            "target_name": "fake",
            "cases": [
                {
                    "name": "sub_payload_json_string",
                    "method": "POST",
                    "url": "https://example.com/api",
                    "payload_initial": {},
                    "payload": {"raw": '{"user_id": "{{user_id}}"}'},
                    "assertions": {
                        "status_code": 200,
                        "extract": {"user_id": "user_id"},
                    },
                }
            ],
        }
    )

    class PayloadAdapter:
        def __init__(self):
            self.second_payload = None

        def run_case(self, case):
            if case["payload"] == {}:
                return system_eval_core.AdapterResult(
                    ok=True,
                    status_code=200,
                    output_text='{"user_id": 7}',
                    latency_ms=1,
                    response_headers={},
                )
            self.second_payload = case["payload"]
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"status":"applied"}',
                latency_ms=1,
                response_headers={},
            )

    adapter = PayloadAdapter()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert result["ok"] is True, result
    assert adapter.second_payload is not None
    assert adapter.second_payload["raw"] == '{"user_id": "7"}', adapter.second_payload
    assert result["cases"][0].get("variables") == {"user_id": 7}, result["cases"][0]


def test_system_eval_steps_two_step_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "steps-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "scenario_token",
                    "assertions": {},
                    "steps": [
                        {
                            "name": "login",
                            "method": "POST",
                            "url": "https://example.com/login",
                            "payload": {},
                            "extract": {"token": "auth.token"},
                        },
                        {
                            "name": "get_user",
                            "method": "GET",
                            "url": "https://example.com/users/{{token}}",
                            "payload": {},
                            "status_code": 200,
                            "body_json_has_key": ["id"],
                        },
                    ],
                }
            ],
        }
    )

    class StepsAdapter:
        def __init__(self):
            self.urls = []

        def run_case(self, case):
            self.urls.append(case["url"])
            if case["url"].endswith("/login"):
                return system_eval_core.AdapterResult(
                    ok=True,
                    status_code=200,
                    output_text='{"auth": {"token": "tok99"}}',
                    latency_ms=1,
                    response_headers={},
                )
            if case["url"] == "https://example.com/users/tok99":
                return system_eval_core.AdapterResult(
                    ok=True,
                    status_code=200,
                    output_text='{"id": 1, "name": "x"}',
                    latency_ms=2,
                    response_headers={},
                )
            return system_eval_core.AdapterResult(
                ok=False, status_code=500, output_text="bad", latency_ms=1, response_headers={}
            )

    adapter = StepsAdapter()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert result["ok"] is True, result
    assert adapter.urls == [
        "https://example.com/login",
        "https://example.com/users/tok99",
    ], adapter.urls
    assert result["cases"][0].get("variables") == {"token": "tok99"}, result["cases"][0]


def test_system_eval_steps_fail_step1_extract():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "steps-f1",
            "target_name": "fake",
            "cases": [
                {
                    "name": "bad_extract",
                    "assertions": {},
                    "steps": [
                        {
                            "name": "login",
                            "method": "GET",
                            "url": "https://example.com/login",
                            "payload": {},
                            "extract": {"token": "auth.token"},
                        },
                        {
                            "name": "get_user",
                            "method": "GET",
                            "url": "https://example.com/users/{{token}}",
                            "payload": {},
                            "status_code": 200,
                        },
                    ],
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="{}", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    fails = result["cases"][0]["failures"]
    assert any("step failed" in f for f in fails), fails
    assert any("login" in f for f in fails), fails
    assert any("extract missing path" in f for f in fails), fails


def test_system_eval_steps_fail_step2_assertion():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "steps-f2",
            "target_name": "fake",
            "cases": [
                {
                    "name": "bad_assert",
                    "assertions": {},
                    "steps": [
                        {
                            "name": "login",
                            "method": "GET",
                            "url": "https://example.com/login",
                            "payload": {},
                            "extract": {"token": "t"},
                        },
                        {
                            "name": "get_user",
                            "method": "GET",
                            "url": "https://example.com/x",
                            "payload": {},
                            "body_json_has_key": ["missing.leaf"],
                        },
                    ],
                }
            ],
        }
    )

    class A:
        def __init__(self):
            self.n = 0

        def run_case(self, case):
            self.n += 1
            if self.n == 1:
                return system_eval_core.AdapterResult(
                    ok=True, status_code=200, output_text='{"t": "ok"}', latency_ms=1, response_headers={}
                )
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text='{"id": 1}', latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    fails = result["cases"][0]["failures"]
    assert any("step failed" in f for f in fails), fails
    assert any("get_user" in f for f in fails), fails


def test_system_eval_step_templates_use_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "tmpl-use",
            "target_name": "fake",
            "cases": [
                {
                    "name": "with_template",
                    "assertions": {},
                    "step_templates": {
                        "login": {
                            "method": "POST",
                            "url": "https://example.com/login",
                            "payload": {},
                            "extract": {"token": "auth.token"},
                        }
                    },
                    "steps": [
                        {"name": "do_login", "use": "login"},
                        {
                            "name": "get_user",
                            "method": "GET",
                            "url": "https://example.com/users/{{token}}",
                            "payload": {},
                            "status_code": 200,
                            "body_json_has_key": ["id"],
                        },
                    ],
                }
            ],
        }
    )

    class StepsAdapter:
        def __init__(self):
            self.urls = []

        def run_case(self, case):
            self.urls.append(case["url"])
            if case["url"].endswith("/login"):
                return system_eval_core.AdapterResult(
                    ok=True,
                    status_code=200,
                    output_text='{"auth": {"token": "tok99"}}',
                    latency_ms=1,
                    response_headers={},
                )
            if case["url"] == "https://example.com/users/tok99":
                return system_eval_core.AdapterResult(
                    ok=True,
                    status_code=200,
                    output_text='{"id": 1}',
                    latency_ms=2,
                    response_headers={},
                )
            return system_eval_core.AdapterResult(
                ok=False, status_code=500, output_text="bad", latency_ms=1, response_headers={}
            )

    adapter = StepsAdapter()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert result["ok"] is True, result
    assert adapter.urls == [
        "https://example.com/login",
        "https://example.com/users/tok99",
    ], adapter.urls
    assert result["cases"][0].get("variables") == {"token": "tok99"}, result["cases"][0]


def test_system_eval_step_templates_override_url_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "tmpl-override",
            "target_name": "fake",
            "cases": [
                {
                    "name": "override_url",
                    "assertions": {},
                    "step_templates": {
                        "hit": {
                            "method": "GET",
                            "url": "https://example.com/from-template",
                            "payload": {},
                            "status_code": 200,
                        }
                    },
                    "steps": [
                        {
                            "name": "first",
                            "use": "hit",
                            "url": "https://example.com/overridden",
                        },
                    ],
                }
            ],
        }
    )

    class A:
        def __init__(self):
            self.seen_url = None

        def run_case(self, case):
            self.seen_url = case["url"]
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="{}", latency_ms=1, response_headers={}
            )

    adapter = A()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert result["ok"] is True, result
    assert adapter.seen_url == "https://example.com/overridden", adapter.seen_url


def test_system_eval_step_results_all_pass_two_steps():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "step-results-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "two_steps",
                    "assertions": {},
                    "steps": [
                        {
                            "name": "login",
                            "method": "GET",
                            "url": "https://example.com/login",
                            "payload": {},
                            "extract": {"token": "t"},
                        },
                        {
                            "name": "get_user",
                            "method": "GET",
                            "url": "https://example.com/users/{{token}}",
                            "payload": {},
                            "status_code": 200,
                        },
                    ],
                }
            ],
        }
    )

    class A:
        def __init__(self):
            self.n = 0

        def run_case(self, case):
            self.n += 1
            if self.n == 1:
                return system_eval_core.AdapterResult(
                    ok=True, status_code=200, output_text='{"t": "ab"}', latency_ms=10, response_headers={}
                )
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="{}", latency_ms=20, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result
    sr = result["cases"][0].get("step_results")
    assert sr is not None and len(sr) == 2, sr
    assert sr[0]["step"] == "login" and sr[0]["status"] == "PASS", sr[0]
    assert sr[0]["url"] == "https://example.com/login" and sr[0]["latency_ms"] == 10, sr[0]
    assert "reason" not in sr[0], sr[0]
    assert sr[1]["step"] == "get_user" and sr[1]["status"] == "PASS", sr[1]
    assert sr[1]["url"] == "https://example.com/users/ab" and sr[1]["latency_ms"] == 20, sr[1]


def test_system_eval_step_results_second_step_fail():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "step-results-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "fail_on_two",
                    "assertions": {},
                    "steps": [
                        {
                            "name": "login",
                            "method": "GET",
                            "url": "https://example.com/login",
                            "payload": {},
                            "extract": {"token": "t"},
                        },
                        {
                            "name": "get_user",
                            "method": "GET",
                            "url": "https://example.com/x",
                            "payload": {},
                            "body_json_has_key": ["missing.leaf"],
                        },
                    ],
                }
            ],
        }
    )

    class A:
        def __init__(self):
            self.n = 0

        def run_case(self, case):
            self.n += 1
            if self.n == 1:
                return system_eval_core.AdapterResult(
                    ok=True, status_code=200, output_text='{"t": "ok"}', latency_ms=5, response_headers={}
                )
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text='{"id": 1}', latency_ms=7, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    sr = result["cases"][0].get("step_results")
    assert sr is not None and len(sr) == 2, sr
    assert sr[0]["status"] == "PASS" and sr[0]["step"] == "login", sr[0]
    assert sr[1]["status"] == "FAIL" and sr[1]["step"] == "get_user", sr[1]
    assert sr[1].get("reason"), sr[1]
    assert "body_json_path" in sr[1]["reason"] or "missing" in sr[1]["reason"].lower(), sr[1]["reason"]


def test_write_result_artifacts_markdown_includes_step_results_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "md-steps-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "scenario_md",
                    "assertions": {},
                    "steps": [
                        {
                            "name": "login",
                            "method": "GET",
                            "url": "https://example.com/login",
                            "payload": {},
                            "extract": {"token": "t"},
                        },
                        {
                            "name": "get_user",
                            "method": "GET",
                            "url": "https://example.com/users/{{token}}",
                            "payload": {},
                            "status_code": 200,
                        },
                    ],
                }
            ],
        }
    )

    class A:
        def __init__(self):
            self.n = 0

        def run_case(self, case):
            self.n += 1
            if self.n == 1:
                return system_eval_core.AdapterResult(
                    ok=True, status_code=200, output_text='{"t": "ab"}', latency_ms=120, response_headers={}
                )
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="{}", latency_ms=90, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result
    with tempfile.TemporaryDirectory() as td:
        paths = system_eval_core.write_result_artifacts(result, td, file_stem="steps_md_pass")
        md_text = Path(paths["markdown_path"]).read_text(encoding="utf-8")
    assert "### Steps" in md_text, md_text
    assert "login" in md_text and "get_user" in md_text, md_text
    assert "PASS" in md_text, md_text
    assert "https://example.com/login" in md_text, md_text
    assert "https://example.com/users/ab" in md_text, md_text
    assert "120 ms" in md_text and "90 ms" in md_text, md_text


def test_write_result_artifacts_markdown_includes_step_results_fail():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "md-steps-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "scenario_md_fail",
                    "assertions": {},
                    "steps": [
                        {
                            "name": "login",
                            "method": "GET",
                            "url": "https://example.com/login",
                            "payload": {},
                            "extract": {"token": "t"},
                        },
                        {
                            "name": "get_user",
                            "method": "GET",
                            "url": "https://example.com/x",
                            "payload": {},
                            "body_json_has_key": ["missing.leaf"],
                        },
                    ],
                }
            ],
        }
    )

    class A:
        def __init__(self):
            self.n = 0

        def run_case(self, case):
            self.n += 1
            if self.n == 1:
                return system_eval_core.AdapterResult(
                    ok=True, status_code=200, output_text='{"t": "ok"}', latency_ms=5, response_headers={}
                )
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text='{"id": 1}', latency_ms=7, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    with tempfile.TemporaryDirectory() as td:
        paths = system_eval_core.write_result_artifacts(result, td, file_stem="steps_md_fail")
        md_text = Path(paths["markdown_path"]).read_text(encoding="utf-8")
    assert "### Steps" in md_text, md_text
    assert "FAIL" in md_text, md_text
    assert "Reason:" in md_text, md_text
    assert "missing.leaf" in md_text or "body_json_path" in md_text, md_text


def test_system_eval_step_templates_missing_raises():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "tmpl-miss",
                "target_name": "fake",
                "cases": [
                    {
                        "name": "bad_template_ref",
                        "assertions": {},
                        "step_templates": {},
                        "steps": [
                            {"name": "only_use", "use": "ghost"},
                        ],
                    }
                ],
            }
        )
    except ValueError as e:
        msg = str(e)
        assert "template not found" in msg, msg
        assert "ghost" in msg, msg
    else:
        raise AssertionError("expected ValueError for missing template")


def test_system_eval_body_contains_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "body-sub-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_contains": "ell"},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="hello", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_contains_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "body-sub-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_contains": "zzz"},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="hello", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body did not contain substring" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_equals_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "body-eq-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_equals_pass_exact_match",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_equals": "hello world"},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="  hello   world\n",
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_equals_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "body-eq-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_equals_fail_mismatch",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_equals": "hello world!"},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="hello world", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_equals mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_regex_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "body-regex-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_regex_pass",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_regex": r"userId:\s*\d+"},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="userId: 42",
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_regex_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "body-regex-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_regex_fail",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_regex": r"userId:\s*\d+"},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="no match here",
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_regex mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_regex_invalid_pattern():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "body-regex-bad",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_regex_invalid_pattern",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_regex": "[unclosed"},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="anything",
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_regex invalid pattern" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_header_equals_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "hdr-eq-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "header_equals_pass",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"header_equals": {"Content-Type": "application/json"}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="ok",
                latency_ms=1,
                response_headers={"Content-Type": "application/json"},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_header_equals_fail_value():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "hdr-eq-fail-val",
            "target_name": "fake",
            "cases": [
                {
                    "name": "header_equals_fail_value",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"header_equals": {"Content-Type": "application/json"}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="ok",
                latency_ms=1,
                response_headers={"Content-Type": "text/html"},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("header_equals mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_header_equals_fail_missing():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "hdr-eq-fail-miss",
            "target_name": "fake",
            "cases": [
                {
                    "name": "header_equals_fail_missing",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"header_equals": {"Content-Type": "application/json"}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("header_equals missing header" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_header_regex_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "hdr-re-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "header_regex_pass",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"header_regex": {"Content-Type": "application/json"}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="ok",
                latency_ms=1,
                response_headers={"Content-Type": "application/json; charset=utf-8"},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_header_regex_fail_value():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "hdr-re-fail-val",
            "target_name": "fake",
            "cases": [
                {
                    "name": "header_regex_fail_value",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"header_regex": {"Content-Type": "application/json"}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="ok",
                latency_ms=1,
                response_headers={"Content-Type": "text/html"},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("header_regex mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_header_regex_fail_missing():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "hdr-re-fail-miss",
            "target_name": "fake",
            "cases": [
                {
                    "name": "header_regex_fail_missing",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"header_regex": {"Content-Type": "application/json"}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("header_regex missing header" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_header_regex_invalid_pattern():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "hdr-re-bad",
            "target_name": "fake",
            "cases": [
                {
                    "name": "header_regex_invalid_pattern",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"header_regex": {"Content-Type": "[invalid"}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="ok",
                latency_ms=1,
                response_headers={"Content-Type": "application/json"},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("header_regex invalid pattern" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_path_equals_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-path-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_path_equals_pass",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_json_path_equals": {"userId": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"userId": 1, "id": 2}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_json_path_equals_fail_value():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-path-fail-val",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_path_equals_fail_value",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_json_path_equals": {"userId": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"userId": 2}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_path_equals mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_path_equals_fail_missing():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-path-fail-miss",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_path_equals_fail_missing",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_json_path_equals": {"userId": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"id": 2}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_path missing path" in f for f in result["cases"][0]["failures"]), result["cases"][0]
    assert any("userId" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_path_equals_invalid_json():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-path-bad-json",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_path_equals_invalid_json",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_json_path_equals": {"userId": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="not json",
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_path_equals invalid json" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_path_nested_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-path-nested-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_path_nested_pass",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_json_path_equals": {"user.id": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"user": {"id": 1}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_json_path_nested_fail_value():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-path-nested-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_path_nested_fail_value",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_json_path_equals": {"user.id": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"user": {"id": 2}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_path_equals mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_path_nested_missing():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-path-nested-miss",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_path_nested_missing",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_json_path_equals": {"user.id": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"user": {}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_path missing path" in f for f in result["cases"][0]["failures"]), result["cases"][0]
    assert any("user.id" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_has_key_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-has-key-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_has_key_pass",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_json_has_key": ["user.id"]},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"user": {"id": 1}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_json_has_key_fail():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-has-key-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_has_key_fail",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_json_has_key": ["user.id"]},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"user": {}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_path missing path" in f for f in result["cases"][0]["failures"]), result["cases"][0]
    assert any("user.id" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_has_key_invalid_json():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-has-key-bad",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_has_key_invalid_json",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"body_json_has_key": ["user.id"]},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="not json",
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_has_key invalid json" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_path_invalid_empty():
    suite = {
        "suite_name": "json-path-invalid-empty",
        "target_name": "fake",
        "cases": [
            {
                "name": "body_json_path_invalid_empty",
                "method": "GET",
                "url": "https://example.com",
                "payload": {},
                "assertions": {"body_json_has_key": [""]},
            }
        ],
    }
    try:
        system_eval_core.validate_suite(suite)
    except ValueError as e:
        msg = str(e)
        assert "body_json_path_invalid_empty" in msg, msg
        assert "body_json_path_* paths must be non-empty strings" in msg, msg
    else:
        raise AssertionError("expected ValueError for empty JSON path")


def test_system_eval_body_json_path_invalid_whitespace():
    suite = {
        "suite_name": "json-path-invalid-ws",
        "target_name": "fake",
        "cases": [
            {
                "name": "body_json_path_invalid_whitespace",
                "method": "GET",
                "url": "https://example.com",
                "payload": {},
                "assertions": {"body_json_path_equals": {"   ": 1}},
            }
        ],
    }
    try:
        system_eval_core.validate_suite(suite)
    except ValueError as e:
        msg = str(e)
        assert "body_json_path_invalid_whitespace" in msg, msg
        assert "body_json_path_* paths must be non-empty strings" in msg, msg
    else:
        raise AssertionError("expected ValueError for whitespace-only JSON path key")


def test_system_eval_body_json_path_missing_nested():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-path-missing-nested",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_path_missing_nested",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_has_key": ["user.id"]},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"user": {}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    failures_joined = " ".join(result["cases"][0]["failures"])
    assert "missing path" in failures_joined.lower(), result["cases"][0]
    assert "user.id" in failures_joined, result["cases"][0]


def test_system_eval_body_json_array_index_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-idx-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_index_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_path_equals": {"items[0].id": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": [{"id": 1}]}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_json_array_index_fail_range():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-idx-range",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_index_fail_range",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_path_equals": {"items[0].id": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": []}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_path missing path" in f for f in result["cases"][0]["failures"]), result["cases"][0]
    assert any("items[0].id" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_array_index_not_list():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-idx-not-list",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_index_not_list",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_path_equals": {"items[0].id": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": {"id": 1}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_path missing path" in f for f in result["cases"][0]["failures"]), result["cases"][0]
    assert any("items[0].id" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_array_length_equals_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-len-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_equals_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_equals": {"items": 3}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": [1, 2, 3]}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_json_array_length_equals_fail_mismatch():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-len-mismatch",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_equals_fail_mismatch",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_equals": {"items": 3}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": [1, 2]}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_array_length_equals mismatch" in f for f in result["cases"][0]["failures"]), (
        result["cases"][0]
    )
    joined = " ".join(result["cases"][0]["failures"])
    assert "items" in joined and "3" in joined and "2" in joined, result["cases"][0]


def test_system_eval_body_json_array_length_equals_fail_not_array():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-len-not-list",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_equals_fail_not_array",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_equals": {"items": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": {"a": 1}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_array_length_equals not array" in f for f in result["cases"][0]["failures"]), (
        result["cases"][0]
    )
    assert any("items" in f and "dict" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_array_length_equals_fail_missing():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-len-missing",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_equals_fail_missing",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_equals": {"items": 0}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"other": []}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_path missing path" in f for f in result["cases"][0]["failures"]), result["cases"][0]
    assert any("items" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_array_length_equals_nested_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-len-nested",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_equals_nested_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_equals": {"data.users": 2}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"data": {"users": [{"id": 1}, {"id": 2}]}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_json_array_length_at_least_pass_equal():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-min-eq",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_at_least_pass_equal",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_at_least": {"items": 2}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": [1, 2]}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_json_array_length_at_least_pass_greater():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-min-gt",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_at_least_pass_greater",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_at_least": {"items": 2}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": [1, 2, 3]}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_json_array_length_at_least_fail_mismatch():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-min-bad",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_at_least_fail_mismatch",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_at_least": {"items": 2}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": [1]}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any(
        "body_json_array_length_at_least mismatch" in f for f in result["cases"][0]["failures"]
    ), result["cases"][0]
    joined = " ".join(result["cases"][0]["failures"])
    assert "items" in joined and "2" in joined and "1" in joined, result["cases"][0]


def test_system_eval_body_json_array_length_at_least_fail_not_array():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-min-not-list",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_at_least_fail_not_array",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_at_least": {"items": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": {"a": 1}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any(
        "body_json_array_length_at_least not array" in f for f in result["cases"][0]["failures"]
    ), result["cases"][0]
    assert any("items" in f and "dict" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_array_length_at_least_fail_missing():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-min-miss",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_at_least_fail_missing",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_at_least": {"items": 0}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"other": []}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_path missing path" in f for f in result["cases"][0]["failures"]), result["cases"][0]
    assert any("items" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_array_length_at_most_pass_equal():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-max-eq",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_at_most_pass_equal",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_at_most": {"items": 2}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": [1, 2]}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_json_array_length_at_most_pass_less():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-max-less",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_at_most_pass_less",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_at_most": {"items": 2}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": [1]}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_body_json_array_length_at_most_fail():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-max-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_at_most_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_at_most": {"items": 2}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": [1, 2, 3]}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any(
        "body_json_array_length_at_most mismatch" in f for f in result["cases"][0]["failures"]
    ), result["cases"][0]
    joined = " ".join(result["cases"][0]["failures"])
    assert "items" in joined and "3" in joined and "2" in joined, result["cases"][0]


def test_system_eval_body_json_array_length_at_most_not_array():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-max-not-list",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_at_most_not_array",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_at_most": {"items": 1}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"items": {"a": 1}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any(
        "body_json_array_length_at_most not array" in f for f in result["cases"][0]["failures"]
    ), result["cases"][0]
    assert any("items" in f and "dict" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_body_json_array_length_at_most_missing():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "json-array-max-miss",
            "target_name": "fake",
            "cases": [
                {
                    "name": "body_json_array_length_at_most_missing",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_json_array_length_at_most": {"items": 0}},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text='{"other": []}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("body_json_path missing path" in f for f in result["cases"][0]["failures"]), result["cases"][0]
    assert any("items" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_header_contains_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "hdr-sub-ok",
            "target_name": "fake",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"header_contains": "X-Custom: token-value"},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="",
                latency_ms=1,
                response_headers={"X-Custom": "token-value", "Other": "x"},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_header_contains_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "hdr-sub-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"header_contains": "Not-Present-Header-Substring"},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="",
                latency_ms=1,
                response_headers={"X-Custom": "token-value"},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("response headers did not contain substring" in f for f in result["cases"][0]["failures"]), (
        result["cases"][0]
    )


def test_system_eval_minimal_assertion_invalid_types_rejected():
    def case_with(assertions):
        return {
            "suite_name": "bad-types",
            "target_name": "t",
            "cases": [
                {
                    "name": "c",
                    "method": "GET",
                    "url": "http://f/x",
                    "payload": {},
                    "assertions": assertions,
                }
            ],
        }

    for bad_assertions, fragment in (
        ({"expected_status": "200"}, "expected_status"),
        ({"expected_status": True}, "expected_status"),
        ({"expected_response_time_ms": "200"}, "expected_response_time_ms"),
        ({"expected_response_time_ms": True}, "expected_response_time_ms"),
        ({"expected_response_time_ms": -1}, "expected_response_time_ms"),
        ({"body_contains": 99}, "body_contains"),
        ({"body_equals": 99}, "body_equals"),
        ({"body_regex": 99}, "body_regex"),
        ({"header_equals": "not-a-dict"}, "header_equals"),
        ({"header_equals": {"Content-Type": 1}}, "header_equals"),
        ({"header_equals": {1: "a"}}, "header_equals"),
        ({"header_regex": "not-a-dict"}, "header_regex"),
        ({"header_regex": {"Content-Type": 1}}, "header_regex"),
        ({"header_regex": {1: "x"}}, "header_regex"),
        ({"body_json_path_equals": "not-a-dict"}, "body_json_path_equals"),
        ({"body_json_path_equals": {1: 1}}, "body_json_path_equals"),
        ({"body_json_has_key": "not-a-list"}, "body_json_has_key"),
        ({"body_json_has_key": [1]}, "body_json_has_key"),
        ({"body_json_array_length_equals": "not-a-dict"}, "body_json_array_length_equals"),
        ({"body_json_array_length_equals": {1: 0}}, "body_json_array_length_equals"),
        ({"body_json_array_length_equals": {"": 0}}, "body_json_array_length_equals"),
        ({"body_json_array_length_equals": {"   ": 0}}, "body_json_array_length_equals"),
        ({"body_json_array_length_equals": {"items": "3"}}, "body_json_array_length_equals"),
        ({"body_json_array_length_equals": {"items": True}}, "body_json_array_length_equals"),
        ({"body_json_array_length_equals": {"items": -1}}, "body_json_array_length_equals"),
        ({"body_json_array_length_at_least": "not-a-dict"}, "body_json_array_length_at_least"),
        ({"body_json_array_length_at_least": {1: 0}}, "body_json_array_length_at_least"),
        ({"body_json_array_length_at_least": {"": 0}}, "body_json_array_length_at_least"),
        ({"body_json_array_length_at_least": {"   ": 0}}, "body_json_array_length_at_least"),
        ({"body_json_array_length_at_least": {"items": "2"}}, "body_json_array_length_at_least"),
        ({"body_json_array_length_at_least": {"items": True}}, "body_json_array_length_at_least"),
        ({"body_json_array_length_at_least": {"items": -1}}, "body_json_array_length_at_least"),
        ({"body_json_array_length_at_most": "not-a-dict"}, "body_json_array_length_at_most"),
        ({"body_json_array_length_at_most": {1: 0}}, "body_json_array_length_at_most"),
        ({"body_json_array_length_at_most": {"": 0}}, "body_json_array_length_at_most"),
        ({"body_json_array_length_at_most": {"   ": 0}}, "body_json_array_length_at_most"),
        ({"body_json_array_length_at_most": {"items": "2"}}, "body_json_array_length_at_most"),
        ({"body_json_array_length_at_most": {"items": True}}, "body_json_array_length_at_most"),
        ({"body_json_array_length_at_most": {"items": -1}}, "body_json_array_length_at_most"),
        ({"extract": "not-a-dict"}, "extract"),
        ({"extract": {"": "user.id"}}, "extract"),
        ({"extract": {"user_id": ""}}, "extract"),
        ({"extract": {"user_id": 1}}, "extract"),
        ({"header_contains": ["a"]}, "header_contains"),
    ):
        try:
            system_eval_core.validate_suite(case_with(bad_assertions))
        except ValueError as e:
            msg = str(e)
            assert "Case 'c'" in msg, msg
            assert fragment in msg, msg
            assert "invalid" in msg.lower(), msg
        else:
            raise AssertionError(f"Expected ValueError for assertions={bad_assertions!r}")


def test_system_eval_runner_script_smoke_with_fake_http():
    suite_payload = {
        "suite_name": "runner-smoke-suite",
        "target_name": "fake-http-target",
        "cases": [
            {
                "name": "status-and-token",
                "lane": "stability",
                "method": "POST",
                "url": "https://fake.local/endpoint",
                "payload": {"prompt": "hello"},
                "assertions": {"status_code": 200, "contains_all": ["pass-token"]},
            }
        ],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        suite_path = temp_root / "suite.json"
        suite_path.write_text(json.dumps(suite_payload, ensure_ascii=False), encoding="utf-8")
        output_dir = temp_root / "artifacts"

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = b'{"result":"pass-token detected"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                _ = (format, args)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            suite_payload["cases"][0]["url"] = f"http://127.0.0.1:{server.server_port}/evaluate"
            suite_path.write_text(json.dumps(suite_payload, ensure_ascii=False), encoding="utf-8")
            cmd = [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "system_eval_runner.py"),
                "--suite",
                str(suite_path),
                "--output-dir",
                str(output_dir),
                "--file-stem",
                "runner_smoke",
            ]
            completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
            assert completed.returncode == 0, (
                f"system_eval_runner smoke failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
            assert (output_dir / "runner_smoke.json").exists(), "Missing JSON artifact"
            assert (output_dir / "runner_smoke.md").exists(), "Missing markdown artifact"
            artifact = json.loads((output_dir / "runner_smoke.json").read_text(encoding="utf-8"))
            assert artifact["cases"][0].get("lane") == "stability", artifact
            assert artifact["cases"][0].get("stability_attempts") == 3, artifact
            assert artifact["cases"][0].get("attempts_total") == 3, artifact
            md_smoke = (output_dir / "runner_smoke.md").read_text(encoding="utf-8")
            assert "lane=`stability`" in md_smoke, md_smoke
            assert "stability:" in md_smoke, md_smoke
        finally:
            server.shutdown()
            server.server_close()


def test_system_eval_execute_suite_multiple_cases_mixed_results():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "multi-case-suite",
            "target_name": "fake-target",
            "cases": [
                {
                    "name": "case-pass",
                    "method": "POST",
                    "url": "http://fake.local/pass",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["ok"]},
                },
                {
                    "name": "case-fail",
                    "method": "POST",
                    "url": "http://fake.local/fail",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["must-not-match"]},
                },
            ],
        }
    )

    class FakeAdapter:
        def run_case(self, case):
            if case["name"] == "case-pass":
                return system_eval_core.AdapterResult(ok=True, status_code=200, output_text="ok payload", latency_ms=5)
            return system_eval_core.AdapterResult(ok=True, status_code=200, output_text="different payload", latency_ms=6)

    result = system_eval_core.execute_suite(suite, adapter=FakeAdapter())
    assert result["executed_cases"] == 2, result
    assert result["passed_cases"] == 1, result
    assert result["failed_cases"] == 1, result
    assert result["ok"] is False, result
    assert result["cases"][0]["ok"] is True, result["cases"][0]
    assert result["cases"][1]["ok"] is False, result["cases"][1]


def test_system_eval_execute_suite_fail_fast_stops_after_first_failure():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "fail-fast-suite",
            "target_name": "fake-target",
            "cases": [
                {
                    "name": "first-fail",
                    "method": "POST",
                    "url": "http://fake.local/one",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["required-token"]},
                },
                {
                    "name": "second-skipped",
                    "method": "POST",
                    "url": "http://fake.local/two",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["ok"]},
                },
            ],
        }
    )

    class FakeAdapter:
        def __init__(self):
            self.calls = []

        def run_case(self, case):
            self.calls.append(case["name"])
            if case["name"] == "first-fail":
                return system_eval_core.AdapterResult(ok=True, status_code=200, output_text="no-match", latency_ms=4)
            return system_eval_core.AdapterResult(ok=True, status_code=200, output_text="ok", latency_ms=4)

    adapter = FakeAdapter()
    result = system_eval_core.execute_suite(suite, adapter=adapter, fail_fast=True)
    assert result["executed_cases"] == 1, result
    assert result["failed_cases"] == 1, result
    assert result["passed_cases"] == 0, result
    assert adapter.calls == ["first-fail"], adapter.calls


def test_system_eval_runner_script_returns_nonzero_on_failure():
    suite_payload = {
        "suite_name": "runner-fail-suite",
        "target_name": "fake-http-target",
        "cases": [
            {
                "name": "status-and-token",
                "method": "POST",
                "url": "https://fake.local/endpoint",
                "payload": {"prompt": "hello"},
                "assertions": {"status_code": 200, "contains_all": ["missing-token"]},
            }
        ],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        suite_path = temp_root / "suite.json"
        suite_path.write_text(json.dumps(suite_payload, ensure_ascii=False), encoding="utf-8")
        output_dir = temp_root / "artifacts"

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = b'{"result":"different-token"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                _ = (format, args)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            suite_payload["cases"][0]["url"] = f"http://127.0.0.1:{server.server_port}/evaluate"
            suite_path.write_text(json.dumps(suite_payload, ensure_ascii=False), encoding="utf-8")
            cmd = [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "system_eval_runner.py"),
                "--suite",
                str(suite_path),
                "--output-dir",
                str(output_dir),
                "--file-stem",
                "runner_fail",
            ]
            completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
            assert completed.returncode != 0, (
                f"system_eval_runner expected non-zero on failure\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
            assert (output_dir / "runner_fail.json").exists(), "Missing JSON artifact on failed run"
            assert (output_dir / "runner_fail.md").exists(), "Missing markdown artifact on failed run"
        finally:
            server.shutdown()
            server.server_close()


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
        ("runtime_memory_memory01_explicit_project_line", test_runtime_memory_memory01_explicit_project_line),
        ("runtime_memory_memory01_this_system_is_meant_to", test_runtime_memory_memory01_this_system_is_meant_to),
        ("runtime_memory_memory01_skips_short_tail", test_runtime_memory_memory01_skips_short_tail),
        ("runtime_memory_memory01_does_not_override_preference", test_runtime_memory_memory01_does_not_override_preference),
        ("runtime_memory_memory02_i_am_building_writes_project", test_runtime_memory_memory02_i_am_building_writes_project),
        ("runtime_memory_memory02_im_building_writes_project", test_runtime_memory_memory02_im_building_writes_project),
        ("runtime_memory_memory02_rejects_want_to_build", test_runtime_memory_memory02_rejects_want_to_build),
        ("runtime_memory_memory02_rejects_might_build", test_runtime_memory_memory02_rejects_might_build),
        ("runtime_memory_memory02_rejects_short_tail", test_runtime_memory_memory02_rejects_short_tail),
        ("runtime_memory_memory03_playground_py_writes_project", test_runtime_memory_memory03_playground_py_writes_project),
        ("runtime_memory_memory03_this_system_writes_project", test_runtime_memory_memory03_this_system_writes_project),
        ("runtime_memory_memory03_this_function_writes_project", test_runtime_memory_memory03_this_function_writes_project),
        ("runtime_memory_memory03_rejects_short_tail", test_runtime_memory_memory03_rejects_short_tail),
        ("runtime_memory_memory03_i_prefer_this_system_stays_preference", test_runtime_memory_memory03_i_prefer_this_system_stays_preference),
        ("runtime_memory_memory04_the_flow_writes_project", test_runtime_memory_memory04_the_flow_writes_project),
        ("runtime_memory_memory04_the_workflow_writes_project", test_runtime_memory_memory04_the_workflow_writes_project),
        ("runtime_memory_memory04_the_pipeline_writes_project", test_runtime_memory_memory04_the_pipeline_writes_project),
        ("runtime_memory_memory04_rejects_short_tail", test_runtime_memory_memory04_rejects_short_tail),
        ("runtime_memory_memory04_i_prefer_workflow_stays_preference", test_runtime_memory_memory04_i_prefer_workflow_stays_preference),
        ("runtime_memory_memory05_playground_responsible_writes_project", test_runtime_memory_memory05_playground_responsible_writes_project),
        ("runtime_memory_memory05_this_module_responsible_writes_project", test_runtime_memory_memory05_this_module_responsible_writes_project),
        ("runtime_memory_memory05_extracted_memory_responsible_writes_project", test_runtime_memory_memory05_extracted_memory_responsible_writes_project),
        ("runtime_memory_memory05_rejects_short_tail", test_runtime_memory_memory05_rejects_short_tail),
        ("runtime_memory_memory05_i_prefer_module_stays_preference", test_runtime_memory_memory05_i_prefer_module_stays_preference),
        ("runtime_memory_memory06_the_rule_writes_project", test_runtime_memory_memory06_the_rule_writes_project),
        ("runtime_memory_memory06_the_constraint_writes_project", test_runtime_memory_memory06_the_constraint_writes_project),
        ("runtime_memory_memory06_this_system_must_writes_project", test_runtime_memory_memory06_this_system_must_writes_project),
        ("runtime_memory_memory06_rejects_short_tail", test_runtime_memory_memory06_rejects_short_tail),
        ("runtime_memory_memory06_i_prefer_system_stays_preference", test_runtime_memory_memory06_i_prefer_system_stays_preference),
        ("runtime_memory_memory07_the_decision_writes_project", test_runtime_memory_memory07_the_decision_writes_project),
        ("runtime_memory_memory07_we_decided_writes_project", test_runtime_memory_memory07_we_decided_writes_project),
        ("runtime_memory_memory07_the_plan_is_to_writes_project", test_runtime_memory_memory07_the_plan_is_to_writes_project),
        ("runtime_memory_memory07_rejects_short_tail", test_runtime_memory_memory07_rejects_short_tail),
        ("runtime_memory_memory07_i_prefer_plan_stays_preference", test_runtime_memory_memory07_i_prefer_plan_stays_preference),
        ("runtime_memory_memory08_we_completed_writes_project", test_runtime_memory_memory08_we_completed_writes_project),
        ("runtime_memory_memory08_the_milestone_writes_project", test_runtime_memory_memory08_the_milestone_writes_project),
        ("runtime_memory_memory08_this_part_is_done_writes_project", test_runtime_memory_memory08_this_part_is_done_writes_project),
        ("runtime_memory_memory08_rejects_short_tail", test_runtime_memory_memory08_rejects_short_tail),
        ("runtime_memory_memory08_i_prefer_progress_stays_preference", test_runtime_memory_memory08_i_prefer_progress_stays_preference),
        ("runtime_memory_memory09_the_problem_writes_project", test_runtime_memory_memory09_the_problem_writes_project),
        ("runtime_memory_memory09_the_biggest_risk_writes_project", test_runtime_memory_memory09_the_biggest_risk_writes_project),
        ("runtime_memory_memory09_the_failure_mode_writes_project", test_runtime_memory_memory09_the_failure_mode_writes_project),
        ("runtime_memory_memory09_the_bug_writes_project", test_runtime_memory_memory09_the_bug_writes_project),
        ("runtime_memory_memory09_rejects_short_tail", test_runtime_memory_memory09_rejects_short_tail),
        ("runtime_memory_memory09_i_prefer_risk_stays_preference", test_runtime_memory_memory09_i_prefer_risk_stays_preference),
        ("runtime_memory_memory10_the_priority_writes_project", test_runtime_memory_memory10_the_priority_writes_project),
        ("runtime_memory_memory10_objective_right_now_writes_project", test_runtime_memory_memory10_objective_right_now_writes_project),
        ("runtime_memory_memory10_what_matters_most_writes_project", test_runtime_memory_memory10_what_matters_most_writes_project),
        ("runtime_memory_memory10_rejects_short_tail", test_runtime_memory_memory10_rejects_short_tail),
        ("runtime_memory_memory10_i_prefer_priorities_stays_preference", test_runtime_memory_memory10_i_prefer_priorities_stays_preference),
        ("retrieval01_project_query_boosts_project_memory_score", test_retrieval01_project_query_boosts_project_memory_score),
        ("retrieval01_non_project_query_does_not_boost_project_category", test_retrieval01_non_project_query_does_not_boost_project_category),
        ("retrieval01_project_query_does_not_boost_non_project_category", test_retrieval01_project_query_does_not_boost_non_project_category),
        ("retrieval02_project_evidence_boost_increases_with_count", test_retrieval02_project_evidence_boost_increases_with_count),
        ("retrieval02_project_evidence_boost_caps_at_point_three", test_retrieval02_project_evidence_boost_caps_at_point_three),
        ("retrieval02_non_project_unaffected_by_project_evidence_boost", test_retrieval02_non_project_unaffected_by_project_evidence_boost),
        ("retrieval03_project_evidence_two_scores_higher_than_one", test_retrieval03_project_evidence_two_scores_higher_than_one),
        ("retrieval03_high_confidence_project_one_off_still_strong", test_retrieval03_high_confidence_project_one_off_still_strong),
        ("retrieval03_non_project_evidence_one_not_penalized", test_retrieval03_non_project_evidence_one_not_penalized),
        ("retrieval04_reinforced_project_beats_new_on_project_query", test_retrieval04_reinforced_project_beats_new_on_project_query),
        ("retrieval04_neutral_query_no_reinforced_project_bonus", test_retrieval04_neutral_query_no_reinforced_project_bonus),
        ("retrieval04_non_project_category_no_reinforced_bonus", test_retrieval04_non_project_category_no_reinforced_bonus),
        ("retrieval05_project_pref_alignment_tokens_boost_score", test_retrieval05_project_pref_alignment_tokens_boost_score),
        ("retrieval05_project_without_pref_tokens_no_alignment_boost", test_retrieval05_project_without_pref_tokens_no_alignment_boost),
        ("retrieval05_preference_category_not_pref_alignment_boosted", test_retrieval05_preference_category_not_pref_alignment_boosted),
        ("retrieval06_project_confidence_boost_orders_high_confidence", test_retrieval06_project_confidence_boost_orders_high_confidence),
        ("retrieval06_non_project_confidence_not_extra_boosted", test_retrieval06_non_project_confidence_not_extra_boosted),
        ("retrieval07_project_boost_cap_total_point_eight", test_retrieval07_project_boost_cap_total_point_eight),
        ("retrieval07_non_project_category_cap_does_not_apply", test_retrieval07_non_project_category_cap_does_not_apply),
        ("retrieval07_below_cap_project_same_as_uncapped", test_retrieval07_below_cap_project_same_as_uncapped),
        ("retrieval08_explicit_project_phrase_boosts_project_memory", test_retrieval08_explicit_project_phrase_boosts_project_memory),
        ("retrieval08_preference_not_boosted_by_explicit_phrase", test_retrieval08_preference_not_boosted_by_explicit_phrase),
        ("retrieval09_priority_risk_phrase_boosts_project_memory", test_retrieval09_priority_risk_phrase_boosts_project_memory),
        ("retrieval09_preference_not_boosted_by_priority_risk_phrase", test_retrieval09_preference_not_boosted_by_priority_risk_phrase),
        ("retrieval09_max_project_bonus_cap_unchanged_with_risk_phrase", test_retrieval09_max_project_bonus_cap_unchanged_with_risk_phrase),
        ("retrieval10_decision_progress_phrase_boosts_project_memory", test_retrieval10_decision_progress_phrase_boosts_project_memory),
        ("retrieval10_preference_not_boosted_by_decision_progress_phrase", test_retrieval10_preference_not_boosted_by_decision_progress_phrase),
        ("retrieval10_max_project_bonus_cap_unchanged_with_decision_phrase", test_retrieval10_max_project_bonus_cap_unchanged_with_decision_phrase),
        ("packaging01_snapshot_only_active_project_rows", test_packaging01_snapshot_only_active_project_rows),
        ("packaging01_snapshot_orders_stronger_project_rows_first", test_packaging01_snapshot_orders_stronger_project_rows_first),
        ("packaging01_snapshot_respects_max_items", test_packaging01_snapshot_respects_max_items),
        ("packaging01_non_project_rows_excluded", test_packaging01_non_project_rows_excluded),
        ("packaging01_empty_project_memory_returns_empty_string", test_packaging01_empty_project_memory_returns_empty_string),
        ("packaging01_show_project_memory_snapshot_fallback", test_packaging01_show_project_memory_snapshot_fallback),
        ("packaging02_snapshot_groups_rows_into_sections", test_packaging02_snapshot_groups_rows_into_sections),
        ("packaging02_snapshot_omits_empty_sections", test_packaging02_snapshot_omits_empty_sections),
        ("packaging02_snapshot_max_items_trims_before_grouping", test_packaging02_snapshot_max_items_trims_before_grouping),
        ("packaging02_responsible_prefix_beats_generic_playground_prefix", test_packaging02_responsible_prefix_beats_generic_playground_prefix),
        ("packaging02_show_project_memory_snapshot_fallback_unchanged", test_packaging02_show_project_memory_snapshot_fallback_unchanged),
        ("packaging03_near_duplicate_values_collapse_to_one_bullet", test_packaging03_near_duplicate_values_collapse_to_one_bullet),
        ("packaging03_stronger_near_duplicate_wins", test_packaging03_stronger_near_duplicate_wins),
        ("packaging03_distinct_normalized_rows_both_remain", test_packaging03_distinct_normalized_rows_both_remain),
        ("packaging03_sections_stable_after_dedupe", test_packaging03_sections_stable_after_dedupe),
        ("packaging03_show_project_memory_snapshot_fallback_unchanged", test_packaging03_show_project_memory_snapshot_fallback_unchanged),
        ("packaging04_package_wraps_snapshot_with_header_text", test_packaging04_package_wraps_snapshot_with_header_text),
        ("packaging04_empty_snapshot_returns_empty_package_string", test_packaging04_empty_snapshot_returns_empty_package_string),
        ("packaging04_show_project_memory_package_fallback", test_packaging04_show_project_memory_package_fallback),
        ("packaging04_snapshot_body_unchanged_inside_package", test_packaging04_snapshot_body_unchanged_inside_package),
        ("packaging05_package_contains_instruction_header", test_packaging05_package_contains_instruction_header),
        ("packaging05_snapshot_body_unchanged_in_package", test_packaging05_snapshot_body_unchanged_in_package),
        ("packaging05_empty_package_returns_empty_string", test_packaging05_empty_package_returns_empty_string),
        ("packaging05_show_package_fallback_unchanged", test_packaging05_show_package_fallback_unchanged),
        ("packaging06_full_package_unchanged_by_default", test_packaging06_full_package_unchanged_by_default),
        ("packaging06_compact_package_uses_short_prefix", test_packaging06_compact_package_uses_short_prefix),
        ("packaging06_snapshot_body_same_in_full_and_compact_modes", test_packaging06_snapshot_body_same_in_full_and_compact_modes),
        ("packaging06_empty_package_compact_returns_empty_string", test_packaging06_empty_package_compact_returns_empty_string),
        ("packaging06_show_package_fallback_compact_unchanged", test_packaging06_show_package_fallback_compact_unchanged),
        ("packaging07_full_package_includes_row_count_line", test_packaging07_full_package_includes_row_count_line),
        ("packaging07_compact_package_includes_row_count_line", test_packaging07_compact_package_includes_row_count_line),
        ("packaging07_snapshot_body_unchanged_after_metadata", test_packaging07_snapshot_body_unchanged_after_metadata),
        ("packaging07_empty_package_returns_empty_string", test_packaging07_empty_package_returns_empty_string),
        ("packaging07_show_package_fallback_unchanged", test_packaging07_show_package_fallback_unchanged),
        ("packaging08_full_package_includes_section_count_line", test_packaging08_full_package_includes_section_count_line),
        ("packaging08_compact_package_includes_section_count_line", test_packaging08_compact_package_includes_section_count_line),
        ("packaging08_section_count_matches_non_empty_snapshot_sections", test_packaging08_section_count_matches_non_empty_snapshot_sections),
        ("packaging08_snapshot_body_unchanged_after_metadata", test_packaging08_snapshot_body_unchanged_after_metadata),
        ("packaging08_empty_package_returns_empty_string", test_packaging08_empty_package_returns_empty_string),
        ("packaging08_show_package_fallback_unchanged", test_packaging08_show_package_fallback_unchanged),
        ("packaging09_full_package_includes_strength_line", test_packaging09_full_package_includes_strength_line),
        ("packaging09_compact_package_includes_strength_line", test_packaging09_compact_package_includes_strength_line),
        ("packaging09_strength_counts_match_packaged_rows", test_packaging09_strength_counts_match_packaged_rows),
        ("packaging09_strength_reflects_surviving_row_after_dedupe", test_packaging09_strength_reflects_surviving_row_after_dedupe),
        ("packaging09_snapshot_body_unchanged_after_metadata", test_packaging09_snapshot_body_unchanged_after_metadata),
        ("packaging09_empty_package_returns_empty_string", test_packaging09_empty_package_returns_empty_string),
        ("packaging09_show_package_fallback_unchanged", test_packaging09_show_package_fallback_unchanged),
        ("packaging10_full_package_includes_top_priorities_block", test_packaging10_full_package_includes_top_priorities_block),
        ("packaging10_compact_package_includes_top_priorities_block", test_packaging10_compact_package_includes_top_priorities_block),
        ("packaging10_top_priorities_use_first_packaged_rows_order", test_packaging10_top_priorities_use_first_packaged_rows_order),
        ("packaging10_snapshot_body_unchanged_after_priorities_preface", test_packaging10_snapshot_body_unchanged_after_priorities_preface),
        ("packaging10_empty_package_returns_empty_string", test_packaging10_empty_package_returns_empty_string),
        ("packaging10_show_package_fallback_unchanged", test_packaging10_show_package_fallback_unchanged),
        ("formatting_review", test_formatting_review),
        ("state_command_test", test_state_command_test),
        ("multiline_paste_starting_with_set_focus_does_not_mutate_state", test_multiline_paste_starting_with_set_focus_does_not_mutate_state),
        ("oversized_single_line_set_focus_is_ignored_as_command", test_oversized_single_line_set_focus_is_ignored_as_command),
        ("long_multiline_log_no_false_outcome_feedback", test_long_multiline_log_no_false_outcome_feedback),
        ("outcome_feedback_skipped_when_single_line_exceeds_length_cap", test_outcome_feedback_skipped_when_single_line_exceeds_length_cap),
        ("direct_preference_answer", test_direct_preference_answer),
        ("state_over_memory_guard", test_state_over_memory_guard),
        ("tool_fetch_routing", test_tool_fetch_routing),
        ("post_fetch_next_step_quality", test_post_fetch_next_step_quality),
        ("fetch_failure_short_circuits_second_llm", test_fetch_failure_short_circuits_second_llm),
        ("fetch_whitespace_only_short_circuits_second_llm", test_fetch_whitespace_only_short_circuits_second_llm),
        ("fetch_punctuation_only_short_circuits_second_llm", test_fetch_punctuation_only_short_circuits_second_llm),
        ("fetch_trivially_small_short_circuits_second_llm", test_fetch_trivially_small_short_circuits_second_llm),
        ("fetch_over_trivial_char_cap_still_uses_second_llm", test_fetch_over_trivial_char_cap_still_uses_second_llm),
        ("fetch_over_trivial_word_cap_still_uses_second_llm", test_fetch_over_trivial_word_cap_still_uses_second_llm),
        ("fetch_failure_tag_plain_and_tagged", test_fetch_failure_tag_plain_and_tagged),
        ("fetch_page_http_403_classified", test_fetch_page_http_403_classified),
        ("fetch_page_timeout_classified", test_fetch_page_timeout_classified),
        ("fetch_page_network_classified", test_fetch_page_network_classified),
        ("fetch_page_401_and_404_classified", test_fetch_page_401_and_404_classified),
        ("fetch_page_200_substantial_html_untagged", test_fetch_page_200_substantial_html_untagged),
        ("fetch_page_200_empty_body_low_content", test_fetch_page_200_empty_body_low_content),
        ("choose_post_fetch_next_step_recognizes_fetch_tags", test_choose_post_fetch_next_step_recognizes_fetch_tags),
        ("fetch_via_browser_invalid_url", test_fetch_via_browser_invalid_url),
        ("fetch_via_browser_unavailable_when_playwright_unresolved", test_fetch_via_browser_unavailable_when_playwright_unresolved),
        ("chromium_launch_args_include_transport_hints", test_chromium_launch_args_include_transport_hints),
        ("prefer_headline_blob_when_visible_thin_or_shorter", test_prefer_headline_blob_when_visible_thin_or_shorter),
        ("bounded_dom_text_nodes_via_eval_calls_evaluate_with_timeout", test_bounded_dom_text_nodes_via_eval_calls_evaluate_with_timeout),
        ("nav_exc_class_blocked_transport_and_goto_timeout", test_nav_exc_class_blocked_transport_and_goto_timeout),
        ("probe_dict_from_evaluate_result_accepts_json_string", test_probe_dict_from_evaluate_result_accepts_json_string),
        ("normalize_probe_dict_coerces_floaty_values", test_normalize_probe_dict_coerces_floaty_values),
        ("bounded_dom_probe_fallback_pipe_parses", test_bounded_dom_probe_fallback_pipe_parses),
        ("bounded_dom_probe_micro_lengths_sets_fb2", test_bounded_dom_probe_micro_lengths_sets_fb2),
        ("bounded_dom_probe_via_eval_sets_st_when_all_evaluate_fail", test_bounded_dom_probe_via_eval_sets_st_when_all_evaluate_fail),
        ("fetch_failure_tag_parses_low_content_with_diag_suffix", test_fetch_failure_tag_parses_low_content_with_diag_suffix),
        ("bounded_extract_prefers_main_landmark_over_thin_body", test_bounded_extract_prefers_main_landmark_over_thin_body),
        ("goto_bounded_retries_ladder_commit_then_domcontentloaded", test_goto_bounded_retries_ladder_commit_then_domcontentloaded),
        ("goto_bounded_retries_reaches_load_after_two_failures", test_goto_bounded_retries_reaches_load_after_two_failures),
        ("goto_bounded_retries_raises_after_three_failures", test_goto_bounded_retries_raises_after_three_failures),
        ("fetch_page_browser_mode_dispatches_to_browser_backend", test_fetch_page_browser_mode_dispatches_to_browser_backend),
        ("browser_timeout_seconds_default_and_clamp", test_browser_timeout_seconds_default_and_clamp),
        ("browser_timeout_seconds_invalid_env_uses_default", test_browser_timeout_seconds_invalid_env_uses_default),
        ("browser_adapter_forwards_fetch_browser_timeout_env", test_browser_adapter_forwards_fetch_browser_timeout_env),
        ("choose_post_fetch_next_step_browser_unavailable_tag", test_choose_post_fetch_next_step_browser_unavailable_tag),
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
        ("run_tool1_system_eval_operator_helper_with_fake_adapter", test_run_tool1_system_eval_operator_helper_with_fake_adapter),
        ("run_tool1_system_eval_operator_missing_suite_file", test_run_tool1_system_eval_operator_missing_suite_file),
        ("tool1_run_log_jsonl_written_for_suite_success_and_failure", test_tool1_run_log_jsonl_written_for_suite_success_and_failure),
        ("http_target_adapter_get_omits_json_keyword", test_http_target_adapter_get_omits_json_keyword),
        ("http_target_adapter_head_omits_json_keyword", test_http_target_adapter_head_omits_json_keyword),
        ("http_target_adapter_post_passes_json_payload", test_http_target_adapter_post_passes_json_payload),
        ("http_target_adapter_post_body_null_omits_json_keyword", test_http_target_adapter_post_body_null_omits_json_keyword),
        ("http_target_adapter_get_send_json_body_passes_json", test_http_target_adapter_get_send_json_body_passes_json),
        ("http_target_adapter_populates_response_headers_from_requests", test_http_target_adapter_populates_response_headers_from_requests),
        ("http_target_adapter_request_exception_has_empty_response_headers", test_http_target_adapter_request_exception_has_empty_response_headers),
        ("execute_suite_and_artifact_include_response_headers", test_execute_suite_and_artifact_include_response_headers),
        ("execute_suite_stability_attempts_include_response_headers", test_execute_suite_stability_attempts_include_response_headers),
        ("normalize_response_headers_caps_items_and_truncates_long_values", test_normalize_response_headers_caps_items_and_truncates_long_values),
        ("execute_suite_stores_output_full_for_short_body", test_execute_suite_stores_output_full_for_short_body),
        ("execute_suite_output_full_truncates_large_body", test_execute_suite_output_full_truncates_large_body),
        ("system_eval_validate_suite_rejects_body_non_null", test_system_eval_validate_suite_rejects_body_non_null),
        ("system_eval_validate_suite_requires_non_empty_cases", test_system_eval_validate_suite_requires_non_empty_cases),
        ("system_eval_validate_suite_rejects_invalid_lane", test_system_eval_validate_suite_rejects_invalid_lane),
        ("system_eval_lane_preserved_in_results_and_artifacts", test_system_eval_lane_preserved_in_results_and_artifacts),
        ("system_eval_repeat_count_rejected_when_lane_not_consistency", test_system_eval_repeat_count_rejected_when_lane_not_consistency),
        ("system_eval_invalid_repeat_count_rejected", test_system_eval_invalid_repeat_count_rejected),
        ("system_eval_consistency_runs_adapter_exactly_n_times", test_system_eval_consistency_runs_adapter_exactly_n_times),
        ("system_eval_consistency_fails_when_one_attempt_fails_assertion", test_system_eval_consistency_fails_when_one_attempt_fails_assertion),
        ("system_eval_stability_runs_default_three_times", test_system_eval_stability_runs_default_three_times),
        ("system_eval_stability_runs_adapter_exactly_n_times", test_system_eval_stability_runs_adapter_exactly_n_times),
        ("system_eval_stability_attempts_rejected_when_lane_not_stability", test_system_eval_stability_attempts_rejected_when_lane_not_stability),
        ("system_eval_stability_attempts_rejected_when_lane_consistency", test_system_eval_stability_attempts_rejected_when_lane_consistency),
        ("system_eval_invalid_stability_attempts_rejected", test_system_eval_invalid_stability_attempts_rejected),
        ("system_eval_execute_suite_success_with_fake_adapter", test_system_eval_execute_suite_success_with_fake_adapter),
        ("system_eval_execute_suite_records_assertion_failures", test_system_eval_execute_suite_records_assertion_failures),
        ("system_eval_expected_status_passes", test_system_eval_expected_status_passes),
        ("system_eval_expected_status_fails", test_system_eval_expected_status_fails),
        ("system_eval_expected_response_time_ms_pass", test_system_eval_expected_response_time_ms_pass),
        ("system_eval_expected_response_time_ms_fail", test_system_eval_expected_response_time_ms_fail),
        ("system_eval_expected_response_time_ms_equal", test_system_eval_expected_response_time_ms_equal),
        ("system_eval_extract_simple", test_system_eval_extract_simple),
        ("system_eval_extract_missing_path", test_system_eval_extract_missing_path),
        ("system_eval_variable_substitution_url_pass", test_system_eval_variable_substitution_url_pass),
        ("system_eval_variable_substitution_missing_var", test_system_eval_variable_substitution_missing_var),
        (
            "system_eval_variable_substitution_payload_string_pass",
            test_system_eval_variable_substitution_payload_string_pass,
        ),
        ("system_eval_steps_two_step_pass", test_system_eval_steps_two_step_pass),
        ("system_eval_steps_fail_step1_extract", test_system_eval_steps_fail_step1_extract),
        ("system_eval_steps_fail_step2_assertion", test_system_eval_steps_fail_step2_assertion),
        ("system_eval_step_templates_use_pass", test_system_eval_step_templates_use_pass),
        ("system_eval_step_templates_override_url_pass", test_system_eval_step_templates_override_url_pass),
        ("system_eval_step_templates_missing_raises", test_system_eval_step_templates_missing_raises),
        ("system_eval_step_results_all_pass_two_steps", test_system_eval_step_results_all_pass_two_steps),
        ("system_eval_step_results_second_step_fail", test_system_eval_step_results_second_step_fail),
        (
            "write_result_artifacts_markdown_includes_step_results_pass",
            test_write_result_artifacts_markdown_includes_step_results_pass,
        ),
        (
            "write_result_artifacts_markdown_includes_step_results_fail",
            test_write_result_artifacts_markdown_includes_step_results_fail,
        ),
        ("system_eval_body_contains_passes", test_system_eval_body_contains_passes),
        ("system_eval_body_contains_fails", test_system_eval_body_contains_fails),
        ("system_eval_body_equals_passes", test_system_eval_body_equals_passes),
        ("system_eval_body_equals_fails", test_system_eval_body_equals_fails),
        ("system_eval_body_regex_passes", test_system_eval_body_regex_passes),
        ("system_eval_body_regex_fails", test_system_eval_body_regex_fails),
        ("system_eval_body_regex_invalid_pattern", test_system_eval_body_regex_invalid_pattern),
        ("system_eval_header_equals_passes", test_system_eval_header_equals_passes),
        ("system_eval_header_equals_fail_value", test_system_eval_header_equals_fail_value),
        ("system_eval_header_equals_fail_missing", test_system_eval_header_equals_fail_missing),
        ("system_eval_header_regex_passes", test_system_eval_header_regex_passes),
        ("system_eval_header_regex_fail_value", test_system_eval_header_regex_fail_value),
        ("system_eval_header_regex_fail_missing", test_system_eval_header_regex_fail_missing),
        ("system_eval_header_regex_invalid_pattern", test_system_eval_header_regex_invalid_pattern),
        ("system_eval_body_json_path_equals_passes", test_system_eval_body_json_path_equals_passes),
        ("system_eval_body_json_path_equals_fail_value", test_system_eval_body_json_path_equals_fail_value),
        ("system_eval_body_json_path_equals_fail_missing", test_system_eval_body_json_path_equals_fail_missing),
        ("system_eval_body_json_path_equals_invalid_json", test_system_eval_body_json_path_equals_invalid_json),
        ("system_eval_body_json_path_nested_pass", test_system_eval_body_json_path_nested_pass),
        ("system_eval_body_json_path_nested_fail_value", test_system_eval_body_json_path_nested_fail_value),
        ("system_eval_body_json_path_nested_missing", test_system_eval_body_json_path_nested_missing),
        ("system_eval_body_json_has_key_pass", test_system_eval_body_json_has_key_pass),
        ("system_eval_body_json_has_key_fail", test_system_eval_body_json_has_key_fail),
        ("system_eval_body_json_has_key_invalid_json", test_system_eval_body_json_has_key_invalid_json),
        ("system_eval_body_json_path_invalid_empty", test_system_eval_body_json_path_invalid_empty),
        ("system_eval_body_json_path_invalid_whitespace", test_system_eval_body_json_path_invalid_whitespace),
        ("system_eval_body_json_path_missing_nested", test_system_eval_body_json_path_missing_nested),
        ("system_eval_body_json_array_index_pass", test_system_eval_body_json_array_index_pass),
        ("system_eval_body_json_array_index_fail_range", test_system_eval_body_json_array_index_fail_range),
        ("system_eval_body_json_array_index_not_list", test_system_eval_body_json_array_index_not_list),
        ("system_eval_body_json_array_length_equals_pass", test_system_eval_body_json_array_length_equals_pass),
        (
            "system_eval_body_json_array_length_equals_fail_mismatch",
            test_system_eval_body_json_array_length_equals_fail_mismatch,
        ),
        (
            "system_eval_body_json_array_length_equals_fail_not_array",
            test_system_eval_body_json_array_length_equals_fail_not_array,
        ),
        (
            "system_eval_body_json_array_length_equals_fail_missing",
            test_system_eval_body_json_array_length_equals_fail_missing,
        ),
        (
            "system_eval_body_json_array_length_equals_nested_pass",
            test_system_eval_body_json_array_length_equals_nested_pass,
        ),
        (
            "system_eval_body_json_array_length_at_least_pass_equal",
            test_system_eval_body_json_array_length_at_least_pass_equal,
        ),
        (
            "system_eval_body_json_array_length_at_least_pass_greater",
            test_system_eval_body_json_array_length_at_least_pass_greater,
        ),
        (
            "system_eval_body_json_array_length_at_least_fail_mismatch",
            test_system_eval_body_json_array_length_at_least_fail_mismatch,
        ),
        (
            "system_eval_body_json_array_length_at_least_fail_not_array",
            test_system_eval_body_json_array_length_at_least_fail_not_array,
        ),
        (
            "system_eval_body_json_array_length_at_least_fail_missing",
            test_system_eval_body_json_array_length_at_least_fail_missing,
        ),
        (
            "system_eval_body_json_array_length_at_most_pass_equal",
            test_system_eval_body_json_array_length_at_most_pass_equal,
        ),
        (
            "system_eval_body_json_array_length_at_most_pass_less",
            test_system_eval_body_json_array_length_at_most_pass_less,
        ),
        ("system_eval_body_json_array_length_at_most_fail", test_system_eval_body_json_array_length_at_most_fail),
        (
            "system_eval_body_json_array_length_at_most_not_array",
            test_system_eval_body_json_array_length_at_most_not_array,
        ),
        (
            "system_eval_body_json_array_length_at_most_missing",
            test_system_eval_body_json_array_length_at_most_missing,
        ),
        ("system_eval_header_contains_passes", test_system_eval_header_contains_passes),
        ("system_eval_header_contains_fails", test_system_eval_header_contains_fails),
        ("system_eval_minimal_assertion_invalid_types_rejected", test_system_eval_minimal_assertion_invalid_types_rejected),
        ("system_eval_runner_script_smoke_with_fake_http", test_system_eval_runner_script_smoke_with_fake_http),
        ("system_eval_execute_suite_multiple_cases_mixed_results", test_system_eval_execute_suite_multiple_cases_mixed_results),
        ("system_eval_execute_suite_fail_fast_stops_after_first_failure", test_system_eval_execute_suite_fail_fast_stops_after_first_failure),
        ("system_eval_runner_script_returns_nonzero_on_failure", test_system_eval_runner_script_returns_nonzero_on_failure),
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