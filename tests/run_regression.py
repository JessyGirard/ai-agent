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
from services import journal_service
from services import prompt_builder
from tools.fetch_page import fetch_failure_tag, fetch_page

import playground
from core import persistence as persistence_core
from app.system_eval_operator import run_tool1_system_eval_http
from app.tool2_operator import run_tool2_prompt_response_eval
from app.tool3_operator import run_tool3_regression_eval
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
    playground.clear_recent_answer_session()
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
    assert result == "⚠️ Please type something or attach at least one screenshot.", f"Unexpected result: {result}"


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

    structured = (
        "Progress:\n\n"
        "Risks:\n\n"
        "Decisions:\n\n"
        "Next Steps:\n"
        "- Test memory retrieval first.\n"
        "- Test memory retrieval with one known preference question, then ask a follow-up.\n"
    )
    original = playground.ask_ai
    try:

        def fake_ask_ai(messages, system_prompt=None):
            return structured

        playground.ask_ai = fake_ask_ai
        result = playground.handle_user_input("What should I do next?")
    finally:
        playground.ask_ai = original

    assert "Progress:" in result, "Missing Progress section"
    assert "Risks:" in result, "Missing Risks section"
    assert "Decisions:" in result, "Missing Decisions section"
    assert "Next Steps:" in result, "Missing Next Steps section"
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
        shared = "I am a backend engineer who favors precise steps"
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


def test_build_messages_injects_high_priority_active_memory_for_planning():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal_income",
                    "category": "goal",
                    "value": "Achieve $150/day income",
                    "confidence": 0.86,
                    "importance": 0.97,
                    "status": "active",
                    "memory_kind": "stable",
                    "evidence_count": 4,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
                {
                    "memory_id": "mem_project_low",
                    "category": "project",
                    "value": "Refactor internal helper names",
                    "confidence": 0.8,
                    "importance": 0.6,
                    "status": "active",
                    "memory_kind": "emerging",
                    "evidence_count": 2,
                    "last_seen": "runtime",
                    "trend": "reinforced",
                    "source_refs": ["runtime"],
                },
            ],
        }
        temp_memory_path.parent.mkdir(exist_ok=True)
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")

        prompt, _ = playground.build_messages("What should I prioritize next?")

        assert "High-priority active user memory:" in prompt
        assert "USER PRIORITY: Achieve $150/day income" in prompt
        assert "DECISION RULE: For decision/planning questions, evaluate all candidate actions against USER PRIORITY first." in prompt
        assert "CORRECTNESS RULE: If the proposed answer/next step does not support USER PRIORITY, the answer is incorrect and must be revised." in prompt
        assert "NEXT-STEP RULE: If asked what to do next, always prefer actions that directly move toward USER PRIORITY" in prompt
        assert "USER PRIORITY: Refactor internal helper names" not in prompt


def test_build_messages_priority_block_only_for_decision_or_planning_questions():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        payload = {
            "meta": {},
            "memory_items": [
                {
                    "memory_id": "mem_goal_income",
                    "category": "goal",
                    "value": "Achieve $150/day income",
                    "confidence": 0.86,
                    "importance": 0.97,
                    "status": "active",
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

        prompt, _ = playground.build_messages("What file did I open last?")

        assert "High-priority active user memory:" not in prompt


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
                    "value": "I am a backend engineer who favors precise steps",
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


def test_runtime_statement_not_classified_as_identity():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I'm testing the UI right now")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("category") == "project", result
        assert len(items) == 1, items
        assert items[0].get("category") != "identity"


def test_low_confidence_tentative_runtime_memory_not_active_by_default():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        result = playground.write_runtime_memory("I am a backend engineer")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert result and result.get("status") == "created", result
        assert len(items) == 1, items
        assert items[0].get("confidence") < 0.6
        assert items[0].get("memory_kind") == "tentative"
        assert items[0].get("status") != "active"


def test_ephemeral_testing_statement_importance_not_inflated():
    reset_agent_state()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        temp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        temp_memory_path.write_text(
            json.dumps({"meta": {}, "memory_items": []}),
            encoding="utf-8",
        )
        playground.write_runtime_memory("I'm debugging the UI right now")
        payload = playground.load_memory_payload()
        items = payload.get("memory_items", [])

        assert len(items) == 1, items
        assert float(items[0].get("importance", 0) or 0) <= 0.55


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
        pre_block = _packaging_package_preface_block(pr)
        assert pkg == _packaging05_instruction_prefix(n, s, r_cnt, new_cnt) + pre_block + snap
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


def _packaging_package_preface_block(packaged_rows):
    tp = playground._build_project_memory_package_top_priorities(packaged_rows)
    cr = playground._build_project_memory_package_current_risks(packaged_rows)
    cd = playground._build_project_memory_package_current_decisions(packaged_rows)
    cp = playground._build_project_memory_package_current_progress(packaged_rows)
    ns = playground._build_project_memory_package_next_steps(packaged_rows)
    return playground._join_project_memory_package_prefaces(tp, cr, cd, cp, ns)


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
    pre_block = _packaging_package_preface_block(pr)
    assert pkg == _packaging05_instruction_prefix(n, s, r_cnt, new_cnt) + pre_block + snap


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
    pre_block = _packaging_package_preface_block(pr)
    assert full == _packaging05_instruction_prefix(n, s, r_cnt, new_cnt) + pre_block + snap
    assert compact == _packaging06_compact_instruction_prefix(n, s, r_cnt, new_cnt) + pre_block + snap
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


def test_packaging11_full_package_includes_current_risks_block():
    reset_agent_state()
    rows = [
        _packaging02_row("p1", "the project is packaging11fullA", evidence_count=2),
        _packaging02_row("p2", "the risk is packaging11fullB", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Top project priorities:" in pkg
    assert "Current project risks:" in pkg
    assert "- the risk is packaging11fullB" in pkg


def test_packaging11_compact_package_includes_current_risks_block():
    reset_agent_state()
    rows = [
        _packaging02_row("c1", "the project is packaging11compactA", evidence_count=2),
        _packaging02_row("c2", "the bug is packaging11compactB", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=True)
    assert "Top project priorities:" in pkg
    assert "Current project risks:" in pkg
    assert "- the bug is packaging11compactB" in pkg


def test_packaging11_current_risks_follow_first_qualifying_packaged_order():
    reset_agent_state()
    pr = [
        {"value": "the project is packaging11ordPlain", "trend": "new"},
        {"value": "the bug is packaging11ordBug", "trend": "new"},
        {"value": "the issue is packaging11ordIssue", "trend": "new"},
    ]
    risks = playground._build_project_memory_package_current_risks(pr)
    assert risks == (
        "Current project risks:\n"
        "- the bug is packaging11ordBug\n"
        "- the issue is packaging11ordIssue"
    )


def test_packaging11_risks_block_after_priorities_before_snapshot_body():
    reset_agent_state()
    rows = [
        _packaging02_row("a", "the project is packaging11layerA", evidence_count=2),
        _packaging02_row("b", "the concern is packaging11layerB", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
        snap = playground.build_project_memory_snapshot()
    i_top = pkg.index("Top project priorities:")
    i_risk = pkg.index("Current project risks:")
    i_snap = pkg.index("Project memory snapshot:")
    assert i_top < i_risk < i_snap
    assert pkg.endswith(snap)


def test_packaging11_no_risk_keywords_preserves_package_without_risks_section():
    reset_agent_state()
    rows = [
        _packaging02_row("x", "the project is packaging11safeA", evidence_count=2),
        _packaging02_row("y", "the flow is packaging11safeB", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Current project risks:" not in pkg
    assert "Top project priorities:" in pkg


def test_packaging11_empty_package_returns_empty_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_package() == ""
        assert playground.build_project_memory_package(compact=True) == ""


def test_packaging11_priorities_block_unchanged_for_plain_rows():
    reset_agent_state()
    rows = [
        _packaging02_row("u", "the project is packaging11plainprio", evidence_count=2),
        _packaging02_row("v", "the flow is packaging11plainflow", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        _, pr, _ = playground._project_memory_snapshot_package_context(12)
        top = playground._build_project_memory_package_top_priorities(pr)
    assert top == (
        "Top project priorities:\n"
        "- the project is packaging11plainprio\n"
        "- the flow is packaging11plainflow"
    )


def test_packaging12_norisk_token_does_not_trigger_risks_block():
    reset_agent_state()
    rows = [
        _packaging02_row("n1", "the project is packaging12norisktoken", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Current project risks:" not in pkg


def test_packaging12_no_problem_idiom_does_not_trigger():
    reset_agent_state()
    rows = [
        _packaging02_row(
            "p1", "no problem here for packaging12idiom", evidence_count=2
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Current project risks:" not in pkg


def test_packaging12_this_is_a_risk_triggers():
    reset_agent_state()
    rows = [
        _packaging02_row("r1", "this is a risk for packaging12risky", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Current project risks:" in pkg
    assert "- this is a risk for packaging12risky" in pkg


def test_packaging12_critical_bug_found_triggers():
    reset_agent_state()
    rows = [
        _packaging02_row(
            "b1", "critical bug found in packaging12bugpath", evidence_count=2
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Current project risks:" in pkg
    assert "- critical bug found in packaging12bugpath" in pkg


def test_packaging12_debugging_does_not_trigger_bug_keyword():
    reset_agent_state()
    rows = [
        _packaging02_row(
            "d1", "the debugging process for packaging12nodebug", evidence_count=2
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Current project risks:" not in pkg


def test_packaging12_risks_order_unchanged_vs_packaging11_shape():
    reset_agent_state()
    pr = [
        {"value": "the project is packaging12ordPlain", "trend": "new"},
        {"value": "the bug is packaging12ordBug", "trend": "new"},
        {"value": "the issue is packaging12ordIssue", "trend": "new"},
    ]
    risks = playground._build_project_memory_package_current_risks(pr)
    assert risks == (
        "Current project risks:\n"
        "- the bug is packaging12ordBug\n"
        "- the issue is packaging12ordIssue"
    )


def test_packaging13_full_package_includes_current_decisions_block():
    reset_agent_state()
    rows = [
        _packaging02_row("d1", "the project is packaging13fullP", evidence_count=2),
        _packaging02_row(
            "d2", "we decided to packaging13fullD", evidence_count=2
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Current project decisions:" in pkg
    assert "- we decided to packaging13fullD" in pkg


def test_packaging13_compact_package_includes_current_decisions_block():
    reset_agent_state()
    rows = [
        _packaging02_row("c1", "the project is packaging13compactP", evidence_count=2),
        _packaging02_row(
            "c2", "the plan is packaging13compactPlan", evidence_count=2
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=True)
    assert "Current project decisions:" in pkg
    assert "- the plan is packaging13compactPlan" in pkg


def test_packaging13_current_decisions_follow_first_qualifying_order():
    reset_agent_state()
    pr = [
        {"value": "the project is packaging13ordPlain", "trend": "new"},
        {"value": "we chose packaging13ordChose", "trend": "new"},
        {"value": "chosen path packaging13ordChosen", "trend": "new"},
    ]
    dec = playground._build_project_memory_package_current_decisions(pr)
    assert dec == (
        "Current project decisions:\n"
        "- we chose packaging13ordChose\n"
        "- chosen path packaging13ordChosen"
    )


def test_packaging13_decisions_after_risks_before_snapshot_body():
    reset_agent_state()
    rows = [
        _packaging02_row("a", "the project is packaging13layerP", evidence_count=2),
        _packaging02_row("b", "the risk is packaging13layerR", evidence_count=2),
        _packaging02_row("c", "we decided to packaging13layerD", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
        snap = playground.build_project_memory_snapshot()
    assert pkg.index("Top project priorities:") < pkg.index("Current project risks:")
    assert pkg.index("Current project risks:") < pkg.index("Current project decisions:")
    assert pkg.index("Current project decisions:") < pkg.index("Project memory snapshot:")
    assert pkg.endswith(snap)


def test_packaging13_no_decision_keywords_omits_decisions_block():
    reset_agent_state()
    rows = [
        _packaging02_row("x", "the project is packaging13nodecA", evidence_count=2),
        _packaging02_row("y", "the flow is packaging13nodecB", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Current project decisions:" not in pkg


def test_packaging13_empty_package_returns_empty_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_package() == ""
        assert playground.build_project_memory_package(compact=True) == ""


def test_packaging14_full_package_includes_current_progress_block():
    reset_agent_state()
    rows = [
        _packaging02_row("p1", "the project is packaging14fullP", evidence_count=2),
        _packaging02_row(
            "p2", "the milestone is packaging14fullM", evidence_count=2
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Current project progress:" in pkg
    assert "- the milestone is packaging14fullM" in pkg


def test_packaging14_compact_package_includes_current_progress_block():
    reset_agent_state()
    rows = [
        _packaging02_row("q1", "the project is packaging14compactP", evidence_count=2),
        _packaging02_row(
            "q2", "we finished packaging14compactF", evidence_count=2
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=True)
    assert "Current project progress:" in pkg
    assert "- we finished packaging14compactF" in pkg


def test_packaging14_current_progress_follow_first_qualifying_order():
    reset_agent_state()
    pr = [
        {"value": "the project is packaging14ordPlain", "trend": "new"},
        {"value": "the milestone is packaging14ordM", "trend": "new"},
        {"value": "finished step packaging14ordF", "trend": "new"},
    ]
    prog = playground._build_project_memory_package_current_progress(pr)
    assert prog == (
        "Current project progress:\n"
        "- the milestone is packaging14ordM\n"
        "- finished step packaging14ordF"
    )


def test_packaging14_progress_after_decisions_before_snapshot_body():
    reset_agent_state()
    rows = [
        _packaging02_row("a", "the project is packaging14layerP", evidence_count=2),
        _packaging02_row("b", "the risk is packaging14layerR", evidence_count=2),
        _packaging02_row("c", "we decided to packaging14layerD", evidence_count=2),
        _packaging02_row(
            "d", "we completed packaging14layerProg", evidence_count=2
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
        snap = playground.build_project_memory_snapshot()
    assert pkg.index("Top project priorities:") < pkg.index("Current project risks:")
    assert pkg.index("Current project risks:") < pkg.index("Current project decisions:")
    assert pkg.index("Current project decisions:") < pkg.index("Current project progress:")
    assert pkg.index("Current project progress:") < pkg.index("Project memory snapshot:")
    assert pkg.endswith(snap)


def test_packaging14_no_progress_keywords_omits_progress_block():
    reset_agent_state()
    rows = [
        _packaging02_row("x", "the project is packaging14noprogA", evidence_count=2),
        _packaging02_row("y", "the flow is packaging14noprogB", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Current project progress:" not in pkg


def test_packaging14_empty_package_returns_empty_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_package() == ""
        assert playground.build_project_memory_package(compact=True) == ""


def test_packaging15_full_package_includes_next_steps_block():
    reset_agent_state()
    rows = [
        _packaging02_row("n1", "the project is packaging15fullP", evidence_count=2),
        _packaging02_row(
            "n2", "we need to packaging15fullNeed", evidence_count=2
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Next project steps:" in pkg
    assert "- we need to packaging15fullNeed" in pkg


def test_packaging15_compact_package_includes_next_steps_block():
    reset_agent_state()
    rows = [
        _packaging02_row("m1", "the project is packaging15compactP", evidence_count=2),
        _packaging02_row(
            "m2", "next steps packaging15compactNs", evidence_count=2
        ),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=True)
    assert "Next project steps:" in pkg
    assert "- next steps packaging15compactNs" in pkg


def test_packaging15_next_steps_follow_first_qualifying_order():
    reset_agent_state()
    pr = [
        {"value": "the project is packaging15ordPlain", "trend": "new"},
        {"value": "upcoming packaging15ordU", "trend": "new"},
        {"value": "planning phase packaging15ordP", "trend": "new"},
    ]
    ns = playground._build_project_memory_package_next_steps(pr)
    assert ns == (
        "Next project steps:\n"
        "- upcoming packaging15ordU\n"
        "- planning phase packaging15ordP"
    )


def test_packaging15_progress_before_next_steps_before_snapshot_body():
    reset_agent_state()
    rows = [
        _packaging02_row("a", "the project is packaging15layerP", evidence_count=2),
        _packaging02_row("b", "the risk is packaging15layerR", evidence_count=2),
        _packaging02_row("c", "we decided to packaging15layerD", evidence_count=2),
        _packaging02_row("d", "we completed packaging15layerProg", evidence_count=2),
        _packaging02_row("e", "we need to packaging15layerNext", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
        snap = playground.build_project_memory_snapshot()
    assert pkg.index("Current project progress:") < pkg.index("Next project steps:")
    assert pkg.index("Next project steps:") < pkg.index("Project memory snapshot:")
    assert pkg.endswith(snap)


def test_packaging15_no_next_steps_keywords_omits_next_steps_block():
    reset_agent_state()
    rows = [
        _packaging02_row("x", "the project is packaging15nonextA", evidence_count=2),
        _packaging02_row("y", "the flow is packaging15nonextB", evidence_count=2),
    ]
    with patch.object(playground, "load_memory", return_value=list(rows)):
        pkg = playground.build_project_memory_package(compact=False)
    assert "Next project steps:" not in pkg


def test_packaging15_empty_package_returns_empty_string():
    reset_agent_state()
    payload = {"meta": {"schema_version": "2.0", "memory_count": 0}, "memory_items": []}
    with isolated_runtime_files() as (temp_memory_path, *_):
        temp_memory_path.write_text(json.dumps(payload), encoding="utf-8")
        assert playground.build_project_memory_package() == ""
        assert playground.build_project_memory_package(compact=True) == ""


def test_runtime01_prompt_includes_execution_enforcement():
    reset_agent_state()
    q = (
        "Classify each token as X or Y: alpha, beta. "
        "Output only the labels runtime01classuniq."
    )
    system_prompt, messages = playground.build_messages(q)
    assert prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK in system_prompt
    assert messages == [{"role": "user", "content": q}]


def test_runtime02_prompt_enforces_no_preamble():
    reset_agent_state()
    block = prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    assert "You must execute the task directly" in block
    assert "Output shape (RUNTIME-02):" in block
    assert "Your output must begin immediately with the final answer." in block
    assert "Do not include any text before or after the answer." in block
    assert '"Here is..."' in block
    assert '"The result is..."' in block
    q = "runtime02uniq: name two primes under 10, one per line only."
    system_prompt, _ = playground.build_messages(q)
    assert block in system_prompt


def test_runtime03_prompt_enforces_structure():
    reset_agent_state()
    block = prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    assert "Structural output (RUNTIME-03):" in block
    assert "Output shape (RUNTIME-02):" in block
    assert "You must execute the task directly" in block
    structure_snippet = (
        "Progress:\n"
        "Risks:\n"
        "Decisions:\n"
        "Next Steps:"
    )
    assert structure_snippet in block
    p = block.index("Progress:")
    r = block.index("Risks:", p + 1)
    d = block.index("Decisions:", r + 1)
    n = block.index("Next Steps:", d + 1)
    assert p < r < d < n
    assert "Section headers must match exactly:" in block
    q = "runtime03uniq: structural enforcement prompt check."
    system_prompt, _ = playground.build_messages(q)
    assert block in system_prompt


def test_runtime04_prompt_enforces_category_integrity():
    reset_agent_state()
    block = prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    assert "Category integrity (RUNTIME-04):" in block
    assert (
        "Only include completed work, finished tasks, validated systems, or achieved milestones."
        in block
    )
    assert "Only include potential issues, uncertainties, or threats." in block
    assert "Only include explicit choices or conclusions that were made." in block
    assert "Only include future actions, planned work, or upcoming tasks." in block
    assert "Do NOT include future or planned work." in block
    assert "Do NOT include actions or completed items." in block
    assert "Do NOT include speculation or future plans." in block
    assert "Do NOT include completed work." in block
    assert (
        "Do not place any item in a section if it does not strictly match that section's definition."
        in block
    )
    assert "If unsure, do not include the item." in block
    assert "Do not infer meaning beyond what is explicitly stated." in block
    assert "Do not reinterpret ambiguous statements." in block
    assert "Skip ambiguous entries rather than misclassifying." in block
    q = "runtime04uniq: category integrity prompt check."
    system_prompt, _ = playground.build_messages(q)
    assert block in system_prompt


def test_runtime05_prompt_excludes_in_progress_language():
    reset_agent_state()
    block = prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    assert "In-progress exclusion (RUNTIME-05):" in block
    assert "Include ONLY clearly completed or clearly finished items." in block
    assert (
        'EXCLUDE items described with or implying: "ongoing", "in progress", "working", '
        '"currently working", "being worked on".'
    ) in block
    assert "Include ONLY clearly future or clearly planned actions." in block
    assert 'EXCLUDE present-continuous statements that describe ongoing work (e.g. "is working on", "is improving")' in block
    assert "other ongoing work descriptions." in block
    assert (
        "If an item describes ongoing or in-progress work, do not include it in any section."
        in block
    )
    assert (
        "When an item is not clearly completed, clearly a risk, clearly a decision, or clearly a future step, it must be omitted."
        in block
    )
    q = "runtime05uniq: in-progress exclusion prompt check."
    system_prompt, _ = playground.build_messages(q)
    assert block in system_prompt


def test_memory_quality01_filters_low_signal_items():
    from services import memory_service

    assert memory_service._is_low_signal_memory_item("User prefers quiet mornings")
    assert memory_service._is_low_signal_memory_item("We track various loose ideas")
    assert memory_service._is_low_signal_memory_item("Something might change later")
    assert memory_service._is_low_signal_memory_item("No concrete plan yet for rollout")
    assert not memory_service._is_low_signal_memory_item("Ship regression gate before merge")

    rows = [
        {
            "memory_id": "mq01_low",
            "category": "project",
            "value": "User enjoys vague descriptions of various things",
            "confidence": 0.9,
            "importance": 0.9,
            "memory_kind": "stable",
            "evidence_count": 4,
            "last_seen": "runtime",
            "trend": "reinforced",
            "source_refs": ["runtime"],
        },
        {
            "memory_id": "mq01_high",
            "category": "project",
            "value": "memoryquality01highsignaluniq stable delivery",
            "confidence": 0.85,
            "importance": 0.88,
            "memory_kind": "stable",
            "evidence_count": 3,
            "last_seen": "runtime",
            "trend": "reinforced",
            "source_refs": ["runtime"],
        },
        {
            "memory_id": "mq01_high2",
            "category": "project",
            "value": "memoryquality01orderseconduniq regression discipline",
            "confidence": 0.84,
            "importance": 0.87,
            "memory_kind": "stable",
            "evidence_count": 3,
            "last_seen": "runtime",
            "trend": "reinforced",
            "source_refs": ["runtime"],
        },
        {
            "memory_id": "mq01_low2",
            "category": "project",
            "value": "Team wants something general soon",
            "confidence": 0.82,
            "importance": 0.84,
            "memory_kind": "stable",
            "evidence_count": 3,
            "last_seen": "runtime",
            "trend": "reinforced",
            "source_refs": ["runtime"],
        },
    ]

    def _payload():
        return {"meta": {}, "memory_items": list(rows)}

    filtered = memory_service.load_memory(_payload)
    assert [m.get("memory_id") for m in filtered] == ["mq01_high", "mq01_high2"]


def test_memory_quality02_filters_vague_project_state_language():
    from services import memory_service

    assert memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "We are working on improving the system"}
    )
    assert memory_service._is_low_signal_memory_item({"category": "project", "value": "Work is ongoing for the refactor"})
    assert memory_service._is_low_signal_memory_item({"category": "project", "value": "The work is in progress"})
    assert memory_service._is_low_signal_memory_item({"category": "project", "value": "We are trying to improve reliability"})
    assert memory_service._is_low_signal_memory_item({"category": "project", "value": "The project is progressing"})

    assert memory_service._is_low_signal_memory_item(
        {
            "category": "project",
            "value": "We completed the regression gate after working on flaky tests",
        }
    )
    assert not memory_service._is_low_signal_memory_item(
        {
            "category": "project",
            "value": "memoryquality02highuniq milestone achieved with sign-off",
        }
    )
    assert not memory_service._is_low_signal_memory_item(
        {"category": "preference", "value": "I favor trying to learn one topic at a time"}
    )

    base = {
        "confidence": 0.85,
        "importance": 0.88,
        "memory_kind": "stable",
        "evidence_count": 3,
        "last_seen": "runtime",
        "trend": "reinforced",
        "source_refs": ["runtime"],
    }
    rows = [
        {**base, "memory_id": "mq02_vague_a", "category": "project", "value": "We are working on it"},
        {**base, "memory_id": "mq02_vague_b", "category": "project", "value": "Ongoing cleanup only"},
        {
            **base,
            "memory_id": "mq02_ok",
            "category": "project",
            "value": "memoryquality02orderuniq validated in CI",
        },
        {**base, "memory_id": "mq02_vague_c", "category": "project", "value": "Trying to move forward slowly"},
        {
            **base,
            "memory_id": "mq02_ok2",
            "category": "project",
            "value": "memoryquality02seconduniq passing regression harness",
        },
    ]

    def _payload():
        return {"meta": {}, "memory_items": list(rows)}

    filtered = memory_service.load_memory(_payload)
    assert [m.get("memory_id") for m in filtered] == ["mq02_ok", "mq02_ok2"]


def test_memory_quality03_blocks_false_high_signal_rows():
    from services import memory_service

    assert memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "We are working on the milestone plan"}
    )
    assert memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "We are improving regression handling"}
    )
    assert memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "In progress on risk cleanup"}
    )

    assert not memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "completed milestone X with sign-off"}
    )
    assert not memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "decided to do Y before the next release"}
    )
    assert not memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "risk identified in Z during triage"}
    )

    assert memory_service._is_low_signal_memory_item(
        {
            "category": "project",
            "value": "We completed the regression gate after working on flaky tests",
        }
    )

    base = {
        "confidence": 0.85,
        "importance": 0.88,
        "memory_kind": "stable",
        "evidence_count": 3,
        "last_seen": "runtime",
        "trend": "reinforced",
        "source_refs": ["runtime"],
    }
    rows = [
        {**base, "memory_id": "mq03_bad", "category": "project", "value": "improving regression coverage slowly"},
        {
            **base,
            "memory_id": "mq03_ok",
            "category": "project",
            "value": "memoryquality03keepuniq validated in staging",
        },
        {**base, "memory_id": "mq03_bad2", "category": "project", "value": "working on milestone tracking only"},
        {
            **base,
            "memory_id": "mq03_ok2",
            "category": "project",
            "value": "memoryquality03seconduniq risk identified in auth flow",
        },
    ]

    def _payload():
        return {"meta": {}, "memory_items": list(rows)}

    filtered = memory_service.load_memory(_payload)
    assert [m.get("memory_id") for m in filtered] == ["mq03_ok", "mq03_ok2"]


def test_memory_quality04_filters_mixed_contaminated_rows():
    from services import memory_service

    assert memory_service._is_low_signal_memory_item(
        {
            "category": "project",
            "value": "Completed milestone implementation and working on optimization",
        }
    )
    assert memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "Decided to deploy and improving performance"}
    )
    assert memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "Risk identified in system latency and ongoing monitoring"}
    )
    assert memory_service._is_low_signal_memory_item(
        {
            "category": "project",
            "value": "Next, we will finalize deployment and working on fixes",
        }
    )

    assert not memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "Completed milestone implementation"}
    )
    assert not memory_service._is_low_signal_memory_item({"category": "project", "value": "Decided to deploy"})
    assert not memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "Risk identified in system latency"}
    )
    assert not memory_service._is_low_signal_memory_item(
        {"category": "project", "value": "Next, we will finalize deployment"}
    )

    base = {
        "confidence": 0.85,
        "importance": 0.88,
        "memory_kind": "stable",
        "evidence_count": 3,
        "last_seen": "runtime",
        "trend": "reinforced",
        "source_refs": ["runtime"],
    }
    rows = [
        {
            **base,
            "memory_id": "mq04_bad",
            "category": "project",
            "value": "completed rollout and still working on polish",
        },
        {
            **base,
            "memory_id": "mq04_ok",
            "category": "project",
            "value": "memoryquality04keepuniq validated in staging",
        },
        {
            **base,
            "memory_id": "mq04_bad2",
            "category": "project",
            "value": "decided to ship and improving latency",
        },
        {
            **base,
            "memory_id": "mq04_ok2",
            "category": "project",
            "value": "memoryquality04seconduniq risk identified in auth flow",
        },
    ]

    def _payload():
        return {"meta": {}, "memory_items": list(rows)}

    filtered = memory_service.load_memory(_payload)
    assert [m.get("memory_id") for m in filtered] == ["mq04_ok", "mq04_ok2"]


def test_memory_quality05_blocks_contamination_patterns():
    from services import memory_service

    user_input = "How do I run API checks today?"
    rows = [
        {
            "memory_id": "mq05_bad_phase",
            "category": "project",
            "value": "Phase 4 action-layer refinement",
            "confidence": 0.95,
            "importance": 0.90,
            "memory_kind": "stable",
            "evidence_count": 3,
        },
        {
            "memory_id": "mq05_bad_focus",
            "category": "project",
            "value": "Focus: I prefer testing",
            "confidence": 0.95,
            "importance": 0.90,
            "memory_kind": "stable",
            "evidence_count": 3,
        },
        {
            "memory_id": "mq05_bad_testnum",
            "category": "project",
            "value": "Test 5 failed in prior run",
            "confidence": 0.95,
            "importance": 0.90,
            "memory_kind": "stable",
            "evidence_count": 3,
        },
    ]

    got = memory_service.retrieve_relevant_memory(user_input, lambda: list(rows))
    assert got == []


def test_memory_quality05_allows_grounded_memory():
    from services import memory_service

    user_input = "Can Tool 1 run API tests from the UI?"
    rows = [
        {
            "memory_id": "mq05_good_tool1",
            "category": "project",
            "value": "Tool 1 runs API tests from the UI through system_eval_operator",
            "confidence": 0.95,
            "importance": 0.90,
            "memory_kind": "stable",
            "evidence_count": 3,
        },
        {
            "memory_id": "mq05_bad_phase2",
            "category": "project",
            "value": "Phase 4 action-layer refinement",
            "confidence": 0.95,
            "importance": 0.90,
            "memory_kind": "stable",
            "evidence_count": 3,
        },
    ]

    got = memory_service.retrieve_relevant_memory(user_input, lambda: list(rows))
    ids = [m.get("memory_id") for m in got]
    assert "mq05_good_tool1" in ids
    assert "mq05_bad_phase2" not in ids


def test_memory_quality05_does_not_empty_all_memory():
    from services import memory_service

    user_input = "Is Tool 1 connected to the UI?"
    rows = [
        {
            "memory_id": "mq05_relevant",
            "category": "project",
            "value": "Tool 1 is connected to the UI and system_eval_operator",
            "confidence": 0.95,
            "importance": 0.90,
            "memory_kind": "stable",
            "evidence_count": 3,
        },
        {
            "memory_id": "mq05_filtered",
            "category": "project",
            "value": "Stage 2 workflow state from previous runs",
            "confidence": 0.95,
            "importance": 0.90,
            "memory_kind": "stable",
            "evidence_count": 3,
        },
    ]

    got = memory_service.retrieve_relevant_memory(user_input, lambda: list(rows))
    assert got, "Expected relevant memory to survive grounding filter"
    assert [m.get("memory_id") for m in got] == ["mq05_relevant"]


def test_runtime06_prompt_enforces_invalidity_constraints():
    reset_agent_state()
    block = prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    assert "Correctness constraints (RUNTIME-06):" in block
    assert "Including an item in the wrong section is incorrect." in block
    assert "Including an ambiguous item is incorrect." in block
    assert "Including ongoing or in-progress work in any section is incorrect." in block
    assert 'The following are INVALID (examples — do not output items like these):' in block
    assert '"Work is ongoing..." in Progress' in block
    assert '"Work is in progress..." in Next Steps' in block
    assert '"The system is working..." in Progress' in block
    assert "There is only one correct output." in block
    assert "Any inclusion of invalid items makes the entire answer incorrect." in block
    assert (
        "If an item does not clearly belong to exactly one section, it must be omitted."
        in block
    )
    assert "Do not attempt to reinterpret or force it into a category." in block
    low = block.lower()
    assert low.count("incorrect") >= 4
    q = "runtime06uniq: invalidity constraints prompt check."
    system_prompt, _ = playground.build_messages(q)
    assert block in system_prompt


def test_reasoning01_prompt_enforces_missing_information_admission():
    reset_agent_state()
    block = prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    assert "Missing information (REASONING-01):" in block
    assert (
        "If the provided information is not enough to answer reliably, say that directly."
        in block
    )
    assert "State what information is missing." in block
    assert "Do not guess." in block
    assert "Do not act as if missing information is already known." in block
    assert (
        "A partial answer is allowed, but it must clearly distinguish known information from missing information."
        in block
    )
    assert "Do not pretend to know missing facts." in block
    assert "This is not chain-of-thought:" in block
    assert "Execution enforcement (RUNTIME-01):" in block
    assert "Correctness constraints (RUNTIME-06):" in block
    assert "Structural output (RUNTIME-03):" in block
    q = "reasoning01uniq: missing-information admission prompt check."
    system_prompt, _ = playground.build_messages(q)
    assert block in system_prompt


def test_reasoning02_prompt_blocks_completion_by_invention():
    reset_agent_state()
    block = prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    assert "Non-completion constraints (REASONING-02):" in block
    assert "If required information is missing, do NOT complete all sections." in block
    assert "Do NOT add generic or placeholder content to fill sections." in block
    assert "Do NOT invent risks, decisions, or next steps that are not explicitly supported." in block
    assert '"further analysis is needed"' in block
    assert '"identify strategies"' in block
    assert '"improve the system"' in block
    assert '"determine the next steps"' in block
    assert '"additional work is required"' in block
    assert "A section may be left with header only (no bullets) if no valid items exist." in block
    assert "It is correct to leave a section empty rather than include invalid content." in block
    assert "Adding unsupported items to complete the answer is incorrect." in block
    assert "Leaving a section empty when information is insufficient is correct." in block
    assert "Missing information (REASONING-01):" in block
    q = "reasoning02uniq: non-completion constraints prompt check."
    system_prompt, _ = playground.build_messages(q)
    assert block in system_prompt


def test_reasoning03_prompt_enforces_explanation_structure():
    reset_agent_state()
    block = prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    assert "Explanation structure (REASONING-03):" in block
    assert "When explanation is needed, separate the response into:" in block
    assert "- Known:" in block
    assert "- Missing:" in block
    assert "- Conclusion:" in block
    assert '"Known" must contain only facts supported by the provided input.' in block
    assert '"Missing" must contain only the information not provided but needed for a stronger answer.' in block
    assert '"Conclusion" must contain only what can be validly concluded from the Known section.' in block
    assert "Do not place guessed content in Known." in block
    assert "Do not place invented solutions in Conclusion." in block
    assert "Do not use Missing as an excuse to speculate." in block
    assert "The Conclusion must be narrower when the Missing section is large." in block
    assert "Missing information (REASONING-01):" in block
    assert "Non-completion constraints (REASONING-02):" in block
    q = "reasoning03uniq: explanation-structure prompt check."
    system_prompt, _ = playground.build_messages(q)
    assert block in system_prompt


def test_reasoning04_forces_structure_over_runtime():
    reset_agent_state()
    block = prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    assert "Reasoning enforcement (REASONING-04):" in block
    assert (
        "When the response depends on incomplete, ambiguous, or uncertain input,"
        in block
    )
    assert "This structure OVERRIDES all other output formats." in block
    assert "* Known" in block
    assert "* Missing" in block
    assert "* Conclusion" in block
    assert "If required information is not explicitly present in the input," in block
    assert "or multiple interpretations are possible," in block
    assert "the reasoning structure MUST be used." in block
    assert (
        "When the reasoning structure is required, the following are FORBIDDEN:"
        in block
    )
    assert "* Progress" in block
    assert "* Risks" in block
    assert "* Decisions" in block
    assert "* Next Steps" in block
    assert "* generic procedural answers" in block
    assert "* default advice patterns" in block
    assert "A response is INCORRECT if:" in block
    assert "* Known contains inferred or assumed information" in block
    assert "* Missing is empty when information is absent" in block
    assert (
        "* Conclusion provides a complete solution without sufficient Known" in block
    )
    assert "* The reasoning structure is not used when required" in block
    assert "* Each section must be short and direct" in block
    assert "* No repetition across sections" in block
    assert "Conclusion must become more limited as Missing increases" in block
    assert "Structural output (RUNTIME-03):" in block
    assert "Explanation structure (REASONING-03):" in block
    q = "reasoning04uniq: enforcement tail embed without reasoning06 gate triggers."
    system_prompt, _ = playground.build_messages(q)
    assert block in system_prompt


def test_reasoning05_makes_reasoning_structure_mandatory():
    reset_agent_state()
    block = prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    assert "Reasoning structure mandate (REASONING-05):" in block
    assert "Reasoning enforcement (REASONING-04):" in block
    assert "Explanation structure (REASONING-03):" in block
    assert "Non-completion constraints (REASONING-02):" in block
    assert "Missing information (REASONING-01):" in block
    assert "Structural output (RUNTIME-03):" in block
    assert "Execution enforcement (RUNTIME-01):" in block
    assert "**Mandatory structure rule:**" in block
    assert (
        "All analytical, evaluative, diagnostic, ambiguous, incomplete, or uncertainty-bearing responses MUST use exactly this structure:"
        in block
    )
    assert "This is the default reasoning response structure." in block
    assert "**No-choice rule:**" in block
    assert (
        "The model is not allowed to choose another response format when the answer depends on interpreting input, diagnosing issues, evaluating readiness, proposing fixes, explaining causes, or acting under incomplete information."
        in block
    )
    assert "**Override rule:**" in block
    assert "When REASONING-05 applies, it overrides:" in block
    assert "* Answer / Current State / Next Step" in block
    assert "* generic procedural advice" in block
    assert "* generic planning language" in block
    assert "**Invalidity rule:**" in block
    assert "A response is incorrect if it:" in block
    assert "* omits Known / Missing / Conclusion when required" in block
    assert "* includes guessed or inferred facts in Known" in block
    assert "* leaves Missing empty despite absent information" in block
    assert (
        "* gives a full fix, diagnosis, or readiness judgment without sufficient Known"
        in block
    )
    assert (
        "* falls back to a procedural or action template instead of the reasoning structure"
        in block
    )
    assert "**Constraint rule:**" in block
    assert "Known must contain only facts directly supported by the input" in block
    assert (
        "Missing must name the specific absent information that blocks certainty"
        in block
    )
    assert "Conclusion must remain narrow, conditional, and limited by Missing" in block
    assert "As Missing increases, Conclusion must become less decisive" in block
    assert "**Concision rule:**" in block
    assert "* Keep each section short" in block
    assert "* No repetition between sections" in block
    assert "* No emotional, motivational, or persuasive filler" in block
    assert "* No prefacing or framing before the structure" in block
    q = "reasoning05uniq: reasoning-structure mandate prompt check."
    system_prompt, _ = playground.build_messages(q)
    assert block in system_prompt


def test_reasoning06_routes_known_failure_prompts_to_reasoning_mode():
    reset_agent_state()
    prompts = (
        "The system failed after the update. What is the fix?",
        "User says: 'The API returned something weird.' Diagnose it.",
        "We ran 100 tests and some failed. What does this mean?",
        "Is this system production-ready?",
        (
            "A client wants an API reliability report, but they didn't give the API endpoint. "
            "What should the report say?"
        ),
    )
    for q in prompts:
        assert prompt_builder.user_input_needs_reasoning_structure_mode(q), repr(q)
        tail = prompt_builder.build_runtime_01_execution_enforcement_block(
            q, reasoning_structure_mode=True
        )
        assert "Reasoning-structure control gate (REASONING-06):" in tail
        assert "Structural output (RUNTIME-03):" not in tail
        assert "Begin your reply with the first section header line: Progress:" not in tail
        assert "Missing information (REASONING-01):" in tail
        assert "Reasoning structure mandate (REASONING-05):" in tail


def test_reasoning06_preserves_non_reasoning_action_path():
    reset_agent_state()
    q = "Implement a function that returns 1 in utils.py for reasoning06uniq."
    assert not prompt_builder.user_input_needs_reasoning_structure_mode(q)
    tail = prompt_builder.build_runtime_01_execution_enforcement_block(
        q, reasoning_structure_mode=False
    )
    assert tail == prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    assert "Structural output (RUNTIME-03):" in tail
    system_prompt, _ = playground.build_messages(q)
    assert prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK in system_prompt


def test_reasoning06_does_not_remove_existing_reasoning_rules():
    reset_agent_state()
    gated = "The system failed. Fix it for reasoning06uniq."
    tail_g = prompt_builder.build_runtime_01_execution_enforcement_block(
        gated, reasoning_structure_mode=True
    )
    for label in (
        "Missing information (REASONING-01):",
        "Non-completion constraints (REASONING-02):",
        "Explanation structure (REASONING-03):",
        "Reasoning enforcement (REASONING-04):",
        "Reasoning structure mandate (REASONING-05):",
    ):
        assert label in tail_g
    full = prompt_builder.RUNTIME_01_EXECUTION_ENFORCEMENT_BLOCK
    for label in (
        "Missing information (REASONING-01):",
        "Reasoning structure mandate (REASONING-05):",
        "Structural output (RUNTIME-03):",
    ):
        assert label in full


def test_reasoning06_prompt_builder_embeds_selected_structure():
    reset_agent_state()
    gated = "Diagnose this for reasoning06uniq: the API returned something weird."
    sp_g, _ = playground.build_messages(gated)
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" in sp_g
    assert "Reasoning-structure control gate (REASONING-06):" in sp_g
    assert "Structural output (RUNTIME-03):" not in sp_g
    direct = "Add a function add_one in math.py for reasoning06uniq."
    sp_d, _ = playground.build_messages(direct)
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in sp_d
    assert "Structural output (RUNTIME-03):" in sp_d


def test_reasoning061_routes_unknown_plan_prompt_to_reasoning_mode():
    reset_agent_state()
    q = "Build a testing plan for an API you haven't seen."
    assert prompt_builder.user_input_needs_reasoning_structure_mode(q)
    tail = prompt_builder.build_runtime_01_execution_enforcement_block(q)
    assert "Reasoning-structure control gate (REASONING-06):" in tail
    assert "Structural output (RUNTIME-03):" not in tail
    assert "Begin your reply with the first section header line: Progress:" not in tail
    system_prompt, _ = playground.build_messages(q)
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" in system_prompt
    assert "Structural output (RUNTIME-03):" not in system_prompt
    concrete = (
        "Build a testing plan for the documented public API in README.md for reasoning061uniq."
    )
    assert not prompt_builder.user_input_needs_reasoning_structure_mode(concrete)


def test_reasoning062_strengthens_unknown_plan_routing_in_final_prompt():
    reset_agent_state()
    ascii_q = "Build a testing plan for an API you haven't seen."
    curly_q = "Build a testing plan for an API you haven\u2019t seen."
    variant_q = "Create a plan for a system not yet specified."
    for q in (ascii_q, curly_q, variant_q):
        assert prompt_builder.user_input_needs_reasoning_structure_mode(q), repr(q)
        system_prompt, _ = playground.build_messages(q)
        assert "REASONING OUTPUT MODE (REASONING-06 gate active):" in system_prompt
        assert "Structural output (RUNTIME-03):" not in system_prompt
        assert "Use exactly these three sections in this order:\n\nKnown:" in system_prompt
    documented = (
        "Build a testing plan for the documented public API in README.md for reasoning062uniq."
    )
    assert not prompt_builder.user_input_needs_reasoning_structure_mode(documented)
    sp_doc, _ = playground.build_messages(documented)
    assert "Structural output (RUNTIME-03):" in sp_doc


def test_interaction01_routes_simple_conversation_to_conversation_mode():
    reset_agent_state()
    for q in ("Joshua?", "Are you ready to help me every day?"):
        assert prompt_builder.user_input_needs_conversation_mode(q)
        assert not prompt_builder.user_input_needs_reasoning_structure_mode(q)
        system_prompt, _ = playground.build_messages(q)
        assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
        assert "Conversation mode (INTERACTION-01):" in system_prompt
        assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in system_prompt
        assert "OPEN CONVERSATION MODE:" not in system_prompt
        assert "OUTPUT FORMAT RULES:" not in system_prompt
        assert "Structural output (RUNTIME-03):" not in system_prompt


def test_interaction01_routes_greeting_variants_to_conversation_mode():
    reset_agent_state()
    prompts = (
        "Hello Joshua",
        "Bonjour Joshua",
        "Hi Joshua",
        "Hey Joshua",
        "  hello   joshua  ",
        "HELLO JOSHUA",
        "bonjour joshua!",
    )
    for q in prompts:
        assert prompt_builder.user_input_needs_conversation_mode(q), repr(q)
        system_prompt, _ = playground.build_messages(q)
        assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
        assert "Structural output (RUNTIME-03):" not in system_prompt
        assert "OUTPUT FORMAT RULES:" not in system_prompt


def test_interaction01_greeting_with_task_intent_not_pure_conversation_mode():
    reset_agent_state()
    q = "Hello Joshua, what should I do next?"
    assert not prompt_builder.user_input_needs_conversation_mode(q)
    system_prompt, _ = playground.build_messages(q)
    assert "CONVERSATION MODE (INTERACTION-01):" not in system_prompt
    assert "OUTPUT FORMAT RULES:" in system_prompt


def test_interaction01_reasoning_mode_still_wins():
    reset_agent_state()
    q = "The system failed after the update. What is the fix?"
    assert prompt_builder.user_input_needs_reasoning_structure_mode(q)
    assert not prompt_builder.user_input_needs_conversation_mode(q)
    system_prompt, _ = playground.build_messages(q)
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" in system_prompt
    assert "CONVERSATION MODE (INTERACTION-01):" not in system_prompt


def test_interaction01_preserves_action_path():
    reset_agent_state()
    q = "Implement a function that parses JSON input."
    assert not prompt_builder.user_input_needs_conversation_mode(q)
    assert not prompt_builder.user_input_needs_reasoning_structure_mode(q)
    system_prompt, _ = playground.build_messages(q)
    assert "CONVERSATION MODE (INTERACTION-01):" not in system_prompt
    assert "Conversation mode (INTERACTION-01):" not in system_prompt
    assert "Structural output (RUNTIME-03):" in system_prompt


def test_interaction01_build_messages_contains_conversation_instructions():
    reset_agent_state()
    q = "Joshua?"
    system_prompt, _ = playground.build_messages(q)
    assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
    assert prompt_builder.INTERACTION_01_CONVERSATION_ENFORCEMENT_BLOCK in system_prompt
    assert "Do not output Progress:, Risks:, Decisions:, Next Steps:" in system_prompt


def test_interaction011_routes_conditional_help_tool_prompt_to_conversation_mode():
    reset_agent_state()
    prompts = (
        "If I give you the information you need, can you help me use this tool to run the tests?",
        "Can you help me use this tool?",
        "If I give you the details, can you help me run the tests?",
        "Can you help me with this tool?",
        "But if I give you the information you need to run the tests, you can help me use this tool to run them?",
    )
    for q in prompts:
        assert prompt_builder.user_input_needs_conversation_mode(q), repr(q)
        assert not prompt_builder.user_input_needs_reasoning_structure_mode(q), repr(q)
        system_prompt, _ = playground.build_messages(q)
        assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
        assert "Conversation mode (INTERACTION-01):" in system_prompt
        assert "Structural output (RUNTIME-03):" not in system_prompt
        assert "OUTPUT FORMAT RULES:" not in system_prompt


def test_interaction012_routes_clarification_prompt_to_conversation_mode():
    reset_agent_state()
    prompts = (
        "What tool am I talking about?",
        "Which tool?",
        "What do you mean?",
    )
    for q in prompts:
        assert prompt_builder.user_input_is_simple_clarification(q), repr(q)
        assert prompt_builder.user_input_needs_conversation_mode(q), repr(q)
        assert not prompt_builder.user_input_needs_reasoning_structure_mode(q), repr(q)
        system_prompt, _ = playground.build_messages(q)
        assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
        assert "Conversation mode (INTERACTION-01):" in system_prompt
        assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in system_prompt
        assert "Structural output (RUNTIME-03):" not in system_prompt
        assert "OUTPUT FORMAT RULES:" not in system_prompt


def test_interaction013_routes_acknowledgment_followups_to_conversation_mode():
    reset_agent_state()
    prompts = (
        "That's much better",
        "Thats much better",
        "Nice",
        "Yeah that makes sense now",
        "That makes sense now",
        "nice.",
        "NICE!",
    )
    for q in prompts:
        assert prompt_builder.user_input_needs_conversation_mode(q), repr(q)
        system_prompt, _ = playground.build_messages(q)
        assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
        assert "Structural output (RUNTIME-03):" not in system_prompt
        assert "OUTPUT FORMAT RULES:" not in system_prompt
        assert "For short acknowledgment follow-ups (about 1-8 tokens, no task intent), the reply MUST be exactly one short sentence." in system_prompt
        assert "the reply MUST NOT contain a question mark" in system_prompt


def test_interaction013_acknowledgment_with_task_intent_stays_task_oriented():
    reset_agent_state()
    q = "That's better, what should I do next?"
    assert not prompt_builder.user_input_needs_conversation_mode(q)
    system_prompt, _ = playground.build_messages(q)
    assert "CONVERSATION MODE (INTERACTION-01):" not in system_prompt
    assert "LIGHT TASK MODE:" in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt


def test_interaction013_help_prompt_remains_conversational():
    reset_agent_state()
    q = "Can you help me with this?"
    assert prompt_builder.user_input_needs_conversation_mode(q)
    system_prompt, _ = playground.build_messages(q)
    assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
    assert "Structural output (RUNTIME-03):" not in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt
    assert "For generic help asks (for example \"Can you help me with this?\"), a single short clarifying question is allowed." in system_prompt


def test_interaction014_format_style_questions_require_plain_prose_guidance():
    reset_agent_state()
    q = "Why do you give me answers in that format?"
    system_prompt, _ = playground.build_messages(q)
    assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
    assert "Questions about answer format, style, or why a format was used MUST still be answered in plain prose." in system_prompt
    assert "unless the user explicitly requests those exact headers." in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt
    assert "Reasoning-structure control gate (REASONING-06):" not in system_prompt


def test_interaction015_plain_answer_override_routes_to_conversation_mode():
    reset_agent_state()
    q = "Can you answer that normally?"
    assert prompt_builder.user_input_needs_plain_answer_override(q)
    assert prompt_builder.user_input_needs_conversation_mode(q)
    system_prompt, _ = playground.build_messages(q)
    assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
    assert "PLAIN ANSWER OVERRIDE (narrow):" in system_prompt
    assert "The reply MUST be plain prose" in system_prompt
    assert "The reply MUST NOT introduce analysis framing" in system_prompt
    assert "Briefly mirror what they asked for" in system_prompt
    assert "Do not let the entire reply be only a generic open-ended question" in system_prompt
    assert "What would you like to know?" in system_prompt
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt
    assert "Use exactly these three sections in this order:\n\nKnown:" not in system_prompt


def _runtime_context_sample_minimal():
    return {
        "source": "ui_streamlit",
        "active_surface": "Tool 1",
        "tool1": {
            "single_request": {
                "session": {
                    "method": "PUT",
                    "url": "https://httpbin.org/put",
                    "query_params_json": '{"update":"true"}',
                    "headers_json": '{"Content-Type":"application/json"}',
                    "body_json": '{"update":"true","user":"jessy"}',
                    "auth_mode_label": "None",
                    "timeout_seconds": 20,
                    "output_dir": "logs/system_eval",
                }
            },
            "suite": {
                "suite_path": "system_tests/suites/tool1_local_starter_suite.json",
                "fail_fast": False,
                "output_dir": "logs/system_eval",
            },
            "last_bundle": {
                "ok": True,
                "artifact_paths": {
                    "json_path": "logs/system_eval/single_request_2026-04-25_085732.json",
                    "markdown_path": "logs/system_eval/single_request_2026-04-25_085732.md",
                },
                "latest_case": {
                    "status_code": 200,
                    "latency_ms": 1053,
                    "failures": [],
                    "method": "PUT",
                    "url": "https://httpbin.org/put",
                    "output_full": "VERBOSE_BODY_SENTINEL_SHOULD_NOT_APPEAR_IN_PROMPT",
                },
            },
            "recent_runs": [
                {
                    "method": "PUT",
                    "url": "https://httpbin.org/put",
                    "status_code": 200,
                    "failures": [],
                },
                {
                    "method": "PATCH",
                    "url": "https://httpbin.org/patch",
                    "status_code": 405,
                    "failures": ["method_not_allowed"],
                },
            ],
        },
        "tool2": {
            "suite": {
                "suite_path": "system_tests/suites/tool2_prompt_demo/tool2_prompt_response_smoke.json",
                "fail_fast": False,
                "output_dir": "logs/system_eval",
            },
            "last_bundle": {
                "ok": False,
                "artifact_paths": {
                    "json_path": "logs/system_eval/tool2_prompt_response_smoke_2026-04-25_090000.json",
                    "markdown_path": "logs/system_eval/tool2_prompt_response_smoke_2026-04-25_090000.md",
                },
                "latest_case": {
                    "status_code": 200,
                    "failures": ["expected_response_missing_substring: token"],
                },
            },
        },
    }


def test_runtime_context01_prompt_builder_no_context_does_not_inject_api_runner_block():
    reset_agent_state()
    system_prompt, _ = playground.build_messages("Help me continue the API testing workflow.")
    assert "API RUNNER CONTEXT:" not in system_prompt
    assert "Continue the current API runner workflow" not in system_prompt
    assert "Help fill Tool 1/Tool 2 fields" not in system_prompt
    assert "Interpret the latest API runner results" not in system_prompt
    assert "Suggest exactly one next API test" not in system_prompt
    assert "Do not ask generic reset questions" not in system_prompt


def test_runtime_context02_prompt_builder_injects_api_runner_context_block_when_provided():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Help me continue from the current API runner state.",
        runtime_context=runtime_context,
    )
    assert "API RUNNER CONTEXT:" in system_prompt
    assert "Tool 1" in system_prompt
    assert "Tool 2" in system_prompt
    assert "put" in system_prompt.lower()
    assert "httpbin.org/put" in system_prompt.lower()
    assert "system_tests/suites/tool1_local_starter_suite.json" in system_prompt


def test_runtime_context03_prompt_builder_includes_runner_workflow_instructions_when_context_present():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "What should I run next in the API runner?",
        runtime_context=runtime_context,
    )
    assert "Continue the current API runner workflow" in system_prompt
    assert "Help fill Tool 1/Tool 2 fields" in system_prompt
    assert "Interpret the latest API runner results" in system_prompt
    assert "Suggest exactly one next API test" in system_prompt
    assert "Do not ask generic reset questions" in system_prompt
    assert "what would you like to do" not in system_prompt.lower()


def test_runtime_context04_prompt_builder_includes_summary_fields_only_and_excludes_output_full():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Continue API testing from current state.",
        runtime_context=runtime_context,
    )

    assert "put" in system_prompt.lower()
    assert "httpbin.org/put" in system_prompt.lower()
    assert "system_tests/suites/tool1_local_starter_suite.json" in system_prompt
    assert "status_code" in system_prompt or "Status code" in system_prompt
    assert "200" in system_prompt
    assert "failures" in system_prompt or "Failures" in system_prompt
    assert "logs/system_eval/single_request_2026-04-25_085732.json" in system_prompt
    assert "logs/system_eval/single_request_2026-04-25_085732.md" in system_prompt

    assert "output_full" not in system_prompt
    assert "VERBOSE_BODY_SENTINEL_SHOULD_NOT_APPEAR_IN_PROMPT" not in system_prompt


def test_runtime_context05_playground_signatures_accept_optional_runtime_context_none():
    reset_agent_state()

    sp1, msgs1 = playground.build_messages("What is an API?")
    assert isinstance(sp1, str) and sp1.strip()
    assert isinstance(msgs1, list) and msgs1

    sp2, msgs2 = playground.build_messages("What is an API?", runtime_context=None)
    assert isinstance(sp2, str) and sp2.strip()
    assert isinstance(msgs2, list) and msgs2

    original = playground.ask_ai
    try:
        playground.ask_ai = lambda messages, system_prompt=None: (
            "Answer:\nOK.\n\nCurrent state:\nFocus: ai-agent project\n"
            "Stage: Phase 4 action-layer refinement\nAction type: research\n\n"
            "Next step:\nContinue."
        )

        out1 = playground.handle_user_input("Hello")
        assert isinstance(out1, str) and out1.strip()

        out2 = playground.handle_user_input("Hello", runtime_context=None)
        assert isinstance(out2, str) and out2.strip()
    finally:
        playground.ask_ai = original


def test_runtime_context06_prompt_builder_instructs_latest_case_specific_details_and_one_next_test():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Use the latest API runner case and tell me what to run next.",
        runtime_context=runtime_context,
    )
    assert "If latest_case is available, explicitly mention HTTP method, URL, status_code, pass/fail with failures, and latency_ms when present." in system_prompt
    assert "The reply must end with exactly one concrete next API test." in system_prompt


def test_runtime_context07_prompt_builder_prioritizes_latest_case_method_and_url_over_session_values():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["single_request"]["session"]["method"] = "GET"
    runtime_context["tool1"]["single_request"]["session"]["url"] = "https://httpbin.org/get"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["method"] = "PATCH"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["url"] = "https://httpbin.org/patch"
    system_prompt, _ = playground.build_messages(
        "Use latest API case details.",
        runtime_context=runtime_context,
    )
    assert "Tool 1 latest method: PATCH" in system_prompt
    assert "Tool 1 latest URL: https://httpbin.org/patch" in system_prompt


def test_runtime_context08_prompt_builder_includes_api_diagnosis_mode_and_allow_header():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["last_bundle"]["latest_case"]["response_headers"] = {
        "Allow": "PATCH, OPTIONS"
    }
    runtime_context["tool1"]["last_bundle"]["latest_case"]["error_message"] = "method_not_allowed"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["response_summary"] = "method mismatch"
    system_prompt, _ = playground.build_messages(
        "Diagnose this latest API runner result.",
        runtime_context=runtime_context,
    )
    assert "API DIAGNOSIS MODE:" in system_prompt
    assert "Tool 1 latest response_headers.Allow: PATCH, OPTIONS" in system_prompt
    assert "The reply must end with exactly one concrete next API test." in system_prompt
    assert "output_full" not in system_prompt
    assert "VERBOSE_BODY_SENTINEL_SHOULD_NOT_APPEAR_IN_PROMPT" not in system_prompt


def test_runtime_context09_prompt_builder_requires_allow_header_reasoning_for_405_mismatch():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["last_bundle"]["latest_case"]["status_code"] = 405
    runtime_context["tool1"]["last_bundle"]["latest_case"]["method"] = "PATCH"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["url"] = "https://httpbin.org/put"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["response_headers"] = {
        "Allow": "PUT, OPTIONS"
    }
    system_prompt, _ = playground.build_messages(
        "Diagnose this 405 result.",
        runtime_context=runtime_context,
    )
    assert "For HTTP 405 with response_headers.Allow present: explicitly cite the allowed methods from Allow." in system_prompt
    assert 'Must include this form: "This endpoint allows <METHODS>".' in system_prompt
    assert 'Must include this mismatch form: "<USED METHOD> was used, but <ALLOWED METHOD> is required".' in system_prompt
    assert "allowed methods" in system_prompt
    assert "The reply must end with exactly one concrete next API test." in system_prompt
    low = system_prompt.lower()
    assert "verify" not in low
    assert "check supported methods" not in low
    assert "output_full" not in system_prompt
    assert "VERBOSE_BODY_SENTINEL_SHOULD_NOT_APPEAR_IN_PROMPT" not in system_prompt


def test_runtime_context10_prompt_builder_includes_recent_test_pattern_and_pattern_instruction():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["recent_runs"] = [
        {
            "method": "PATCH",
            "url": "https://httpbin.org/put",
            "status_code": 405,
            "failures": ["method not allowed"],
        },
        {
            "method": "PATCH",
            "url": "https://httpbin.org/put",
            "status_code": 405,
            "failures": ["method not allowed"],
        },
        {
            "method": "PATCH",
            "url": "https://httpbin.org/put",
            "status_code": 405,
            "failures": ["method not allowed"],
        },
    ]
    system_prompt, _ = playground.build_messages(
        "Diagnose repeated failures in recent runs.",
        runtime_context=runtime_context,
    )
    assert "RECENT TEST PATTERN:" in system_prompt
    assert "Case 1:" in system_prompt and "Case 2:" in system_prompt
    assert "repeated issue" in system_prompt or "pattern exists" in system_prompt
    assert "output_full" not in system_prompt
    assert "VERBOSE_BODY_SENTINEL_SHOULD_NOT_APPEAR_IN_PROMPT" not in system_prompt


def test_runtime_context13_prompt_builder_recent_runs_shows_mixed_405_and_200():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["recent_runs"] = [
        {
            "method": "PATCH",
            "url": "https://httpbin.org/put",
            "status_code": 405,
            "failures": ["method not allowed"],
        },
        {
            "method": "PATCH",
            "url": "https://httpbin.org/patch",
            "status_code": 200,
            "failures": [],
        },
    ]
    system_prompt, _ = playground.build_messages(
        "Summarize recent API run pattern.",
        runtime_context=runtime_context,
    )
    assert "RECENT TEST PATTERN:" in system_prompt
    assert "PATCH https://httpbin.org/put -> 405" in system_prompt
    assert "PATCH https://httpbin.org/patch -> 200" in system_prompt
    assert "repeated issue" in system_prompt or "pattern exists" in system_prompt


def test_runtime_context14_prompt_builder_disallows_missing_and_vague_and_enforces_single_concrete_next_test():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["recent_runs"] = [
        {
            "method": "PATCH",
            "url": "https://httpbin.org/put",
            "status_code": 405,
            "failures": ["method not allowed"],
        },
        {
            "method": "PATCH",
            "url": "https://httpbin.org/patch",
            "status_code": 200,
            "failures": [],
        },
    ]
    system_prompt, _ = playground.build_messages(
        "Diagnose these mixed API runs and give one next test.",
        runtime_context=runtime_context,
    )
    assert "Do not output Missing:, Additional context needed, or speculative gap sections." in system_prompt
    assert system_prompt.count("Next test: <METHOD> <URL> -> expect <STATUS>.") == 1
    low = system_prompt.lower()
    assert "consider testing" not in low
    assert "you might want to" not in low
    assert "explore" not in low
    assert "evaluate" not in low


def test_runtime_context15_prompt_builder_enables_api_diagnosis_mode_for_last_run_analysis_request():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Analyze my last run.",
        runtime_context=runtime_context,
    )
    assert "API DIAGNOSIS MODE:" in system_prompt


def test_runtime_context16_prompt_builder_does_not_enable_api_diagnosis_mode_for_greeting():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "hello",
        runtime_context=runtime_context,
    )
    assert "API RUNNER CONTEXT:" in system_prompt
    assert "API DIAGNOSIS MODE:" not in system_prompt


def test_runtime_context17_prompt_builder_does_not_enable_api_diagnosis_mode_for_general_unrelated_question():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Can you explain the project architecture at a high level?",
        runtime_context=runtime_context,
    )
    assert "API RUNNER CONTEXT:" in system_prompt
    assert "API DIAGNOSIS MODE:" not in system_prompt


def test_runtime_context18_prompt_builder_requires_expected_status_in_next_test_rules():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["last_bundle"]["latest_case"]["status_code"] = 405
    runtime_context["tool1"]["last_bundle"]["latest_case"]["method"] = "PATCH"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["url"] = "https://httpbin.org/put"
    system_prompt, _ = playground.build_messages(
        "Analyze my last run and suggest the next test.",
        runtime_context=runtime_context,
    )
    assert "Use this exact next-test format once: Next test: <METHOD> <URL> -> expect <STATUS>." in system_prompt
    assert "The next test must always include expected status using '-> expect <STATUS>'." in system_prompt
    assert "If the next test is correcting a method/endpoint mismatch, set expected status to 200." in system_prompt
    assert "If the next test is intentionally testing a failure path, set expected status to 4xx." in system_prompt
    assert system_prompt.count("Next test: <METHOD> <URL> -> expect <STATUS>.") == 1


def test_runtime_context19_prompt_builder_success_case_requires_negative_next_test_generator_rule():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["last_bundle"]["latest_case"]["status_code"] = 200
    runtime_context["tool1"]["last_bundle"]["latest_case"]["failures"] = []
    system_prompt, _ = playground.build_messages(
        "Analyze my last run and suggest next test.",
        runtime_context=runtime_context,
    )
    assert "NEXT TEST GENERATOR: for successful 2xx with no failures, propose a negative-path test next (expected 4xx)." in system_prompt


def test_runtime_context20_prompt_builder_405_case_requires_correct_method_next_test_generator_rule():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["last_bundle"]["latest_case"]["status_code"] = 405
    runtime_context["tool1"]["last_bundle"]["latest_case"]["response_headers"] = {"Allow": "PUT, OPTIONS"}
    system_prompt, _ = playground.build_messages(
        "Analyze my last run and diagnose this 405 mismatch.",
        runtime_context=runtime_context,
    )
    assert "NEXT TEST GENERATOR: for 405 method mismatch, propose the correct allowed method on the same URL next (expected 200)." in system_prompt


def test_runtime_context21_prompt_builder_enforces_exactly_one_next_test_with_expect_format():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Analyze my last run and suggest one next test.",
        runtime_context=runtime_context,
    )
    assert system_prompt.count("Next test: <METHOD> <URL> -> expect <STATUS>.") == 1
    assert "-> expect <STATUS>" in system_prompt


def test_runtime_context22_end_to_end_api_runner_interaction_smoke():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["last_bundle"]["latest_case"]["method"] = "PATCH"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["url"] = "https://httpbin.org/put"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["status_code"] = 405
    runtime_context["tool1"]["last_bundle"]["latest_case"]["response_headers"] = {
        "Allow": "PUT, OPTIONS"
    }

    system_prompt, _ = playground.build_messages(
        "Analyze my last run.",
        runtime_context=runtime_context,
    )
    assert "API DIAGNOSIS MODE:" in system_prompt
    assert "PATCH" in system_prompt
    assert "https://httpbin.org/put" in system_prompt
    assert "405" in system_prompt
    assert "Allow" in system_prompt
    assert "PUT, OPTIONS" in system_prompt
    assert "Next test: <METHOD> <URL> -> expect <STATUS>." in system_prompt
    assert "output_full" not in system_prompt
    assert "VERBOSE_BODY_SENTINEL_SHOULD_NOT_APPEAR_IN_PROMPT" not in system_prompt
    assert "what are you referring to?" not in system_prompt.lower()

    hello_prompt, _ = playground.build_messages(
        "hello",
        runtime_context=runtime_context,
    )
    assert "API DIAGNOSIS MODE:" not in hello_prompt


def test_runtime_context23_prompt_builder_api_diagnosis_suppresses_runtime_template_for_successful_delete():
    """API DIAGNOSIS MODE must override RUNTIME-03 / REASONING-05 tails (no Progress/Risks template)."""
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["last_bundle"]["latest_case"]["method"] = "DELETE"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["url"] = "https://httpbin.org/delete"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["status_code"] = 200
    runtime_context["tool1"]["last_bundle"]["latest_case"]["latency_ms"] = 500
    runtime_context["tool1"]["last_bundle"]["latest_case"]["failures"] = []

    system_prompt, _ = playground.build_messages(
        "Analyze my last successful API runner run.",
        runtime_context=runtime_context,
    )
    assert "API DIAGNOSIS MODE:" in system_prompt
    assert "DELETE" in system_prompt
    assert "https://httpbin.org/delete" in system_prompt
    assert "API diagnosis output dominance (API-DIAG-DC):" in system_prompt
    assert "Your output must contain exactly these sections" not in system_prompt
    assert "Begin your reply with the first section header line: Progress:" not in system_prompt
    assert "Reasoning structure mandate (REASONING-05):" not in system_prompt
    assert "Structural output (RUNTIME-03):" not in system_prompt


def test_runtime_context24_prompt_builder_enables_api_diagnosis_for_analyse_only_my_last_run():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "analyse only my last run",
        runtime_context=runtime_context,
    )
    assert "API DIAGNOSIS MODE:" in system_prompt
    assert "Reasoning-structure control gate (REASONING-06):" not in system_prompt
    assert "Use exactly these three sections in this order:\n\nKnown:" not in system_prompt
    assert "Next test: <METHOD> <URL> -> expect <STATUS>." in system_prompt


def test_runtime_context25_prompt_builder_enables_api_diagnosis_for_analyse_my_last_two_run_please():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "analyse my last two run please",
        runtime_context=runtime_context,
    )
    assert "API DIAGNOSIS MODE:" in system_prompt
    assert "Reasoning-structure control gate (REASONING-06):" not in system_prompt
    assert "Use exactly these three sections in this order:\n\nKnown:" not in system_prompt
    assert "Next test: <METHOD> <URL> -> expect <STATUS>." in system_prompt


def test_runtime_context26_prompt_builder_enables_suite_run_help_mode_for_exact_prompt():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    user_input = (
        "help me run a Suite run (JSON file) in my suite. "
        "Tell me everything I need from the customer, and how to write the script, and run the test."
    )
    system_prompt, _ = playground.build_messages(
        user_input,
        runtime_context=runtime_context,
    )
    assert "SUITE RUN HELP MODE:" in system_prompt
    assert "Suite run help output dominance (SUITE-HELP-DC):" in system_prompt
    assert "Reasoning-structure control gate (REASONING-06):" not in system_prompt
    assert "Use exactly these three sections in this order:\n\nKnown:" not in system_prompt
    assert "platform/tool missing" not in system_prompt.lower()
    assert "provide more details" not in system_prompt.lower()
    assert "base URL" in system_prompt
    assert "endpoint paths" in system_prompt
    assert "methods" in system_prompt
    assert "auth/API key requirements" in system_prompt
    assert "required headers" in system_prompt
    assert "request body examples" in system_prompt
    assert "expected status codes" in system_prompt
    assert "expected JSON fields" in system_prompt
    assert "minimal suite JSON example" in system_prompt
    assert "Tool 1 suite path" in system_prompt
    assert "run steps" in system_prompt or "run the suite test" in system_prompt


def test_runtime_context27_prompt_builder_injects_api_testing_knowledge_lane_for_relevant_prompt():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Explain GET POST PUT PATCH DELETE for API testing",
        runtime_context=runtime_context,
    )
    assert "API testing reference (condensed):" in system_prompt


def test_runtime_context28_prompt_builder_does_not_inject_api_testing_knowledge_lane_for_irrelevant_prompt():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "hello",
        runtime_context=runtime_context,
    )
    assert "API testing reference (condensed):" not in system_prompt


def test_runtime_context29_prompt_builder_knowledge_lane_does_not_require_or_modify_extracted_memory_file():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    with isolated_runtime_files() as (temp_memory_path, _, _, _):
        assert not temp_memory_path.exists()
        system_prompt, _ = playground.build_messages(
            "Explain GET POST PUT PATCH DELETE for API testing",
            runtime_context=runtime_context,
        )
        assert isinstance(system_prompt, str) and system_prompt.strip()
        assert not temp_memory_path.exists()


def test_runtime_context30_prompt_builder_api_testing_knowledge_lane_is_compact_when_injected():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Explain GET POST PUT PATCH DELETE for API testing",
        runtime_context=runtime_context,
    )
    marker = "API testing reference (condensed):"
    assert marker in system_prompt
    block = system_prompt.split(marker, 1)[1]
    block_until_tail = block.split("Execution enforcement (RUNTIME-01):", 1)[0]
    assert len(block_until_tail) <= 1800
    assert len([ln for ln in block_until_tail.splitlines() if ln.strip()]) <= 30


def test_runtime_context31_prompt_builder_knowledge_lane_absent_for_normal_conversation():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "hello there",
        runtime_context=runtime_context,
    )
    assert "API testing reference (condensed):" not in system_prompt


def test_runtime_context32_prompt_builder_knowledge_lane_absent_for_unrelated_technical_prompt():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Explain Python list comprehensions and generators",
        runtime_context=runtime_context,
    )
    assert "API testing reference (condensed):" not in system_prompt


def test_runtime_context33_prompt_builder_knowledge_lane_present_for_simple_api_education_prompt():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "How do I test an API?",
        runtime_context=runtime_context,
    )
    assert "API testing reference (condensed):" in system_prompt


def test_runtime_context34_prompt_builder_knowledge_lane_preserves_key_api_sections():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Explain GET POST PUT PATCH DELETE for API testing",
        runtime_context=runtime_context,
    )
    marker = "API testing reference (condensed):"
    assert marker in system_prompt
    block = system_prompt.split(marker, 1)[1]
    block_until_tail = block.split("Execution enforcement (RUNTIME-01):", 1)[0].lower()
    assert "http methods" in block_until_tail
    assert "status codes" in block_until_tail
    assert "headers" in block_until_tail
    assert "testing strategies" in block_until_tail


def test_runtime_context35_prompt_builder_knowledge_lane_includes_practical_api_testing_guidance():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Teach me practical API testing basics for beginners",
        runtime_context=runtime_context,
    )
    marker = "API testing reference (condensed):"
    assert marker in system_prompt
    block = system_prompt.split(marker, 1)[1]
    block_until_tail = block.split("Execution enforcement (RUNTIME-01):", 1)[0].lower()
    assert "positive testing" in block_until_tail
    assert "negative testing" in block_until_tail
    assert ("content-type" in block_until_tail) or ("authorization" in block_until_tail)
    assert ("put" in block_until_tail and "patch" in block_until_tail) or (
        "get" in block_until_tail and "usually no request body" in block_until_tail
    )


def test_runtime_context36_prompt_builder_knowledge_lane_covers_recent_sections_with_keywords():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Teach me API testing fundamentals and practical guidance",
        runtime_context=runtime_context,
    )
    marker = "API testing reference (condensed):"
    assert marker in system_prompt
    block = system_prompt.split(marker, 1)[1]
    block_until_tail = block.split("Execution enforcement (RUNTIME-01):", 1)[0].lower()

    # Customer Intake Questions
    assert "endpoint" in block_until_tail
    assert "method" in block_until_tail
    assert "authentication" in block_until_tail

    # Authentication Testing
    assert "401" in block_until_tail
    assert "403" in block_until_tail
    assert "authorization" in block_until_tail

    # Request Body Basics
    assert "post" in block_until_tail
    assert "content-type" in block_until_tail
    assert "json" in block_until_tail

    # Error Case Testing
    for code in ("400", "405", "415", "429"):
        assert code in block_until_tail

    # Proof and Client Reporting
    assert ("expected vs actual" in block_until_tail) or ("expected status vs actual status" in block_until_tail)
    assert "latency" in block_until_tail
    assert "report" in block_until_tail


def test_runtime_context37_prompt_builder_knowledge_lane_covers_rate_limit_and_test_case_design_signals():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Give me practical API testing education guidance",
        runtime_context=runtime_context,
    )
    marker = "API testing reference (condensed):"
    assert marker in system_prompt
    block = system_prompt.split(marker, 1)[1]
    block_until_tail = block.split("Execution enforcement (RUNTIME-01):", 1)[0].lower()
    assert ("429" in block_until_tail) or ("rate limit" in block_until_tail)
    assert (
        ("test case" in block_until_tail)
        or ("expected status" in block_until_tail)
        or ("positive" in block_until_tail and "negative" in block_until_tail)
    )


def test_runtime_context38_prompt_builder_knowledge_lane_covers_query_and_path_param_signals():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Explain practical API testing for query params and path params",
        runtime_context=runtime_context,
    )
    marker = "API testing reference (condensed):"
    assert marker in system_prompt
    block = system_prompt.split(marker, 1)[1]
    block_until_tail = block.split("Execution enforcement (RUNTIME-01):", 1)[0].lower()
    assert ("query" in block_until_tail) or ("path" in block_until_tail)
    assert ("limit" in block_until_tail) or ("page" in block_until_tail)
    assert ("filtering" in block_until_tail) or ("pagination" in block_until_tail)


def test_runtime_context39_prompt_builder_knowledge_lane_covers_api_test_plan_response_style_signals():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Give me a practical API testing plan and what to run next",
        runtime_context=runtime_context,
    )
    marker = "API testing reference (condensed):"
    assert marker in system_prompt
    block = system_prompt.split(marker, 1)[1]
    block_until_tail = block.split("Execution enforcement (RUNTIME-01):", 1)[0].lower()
    assert "baseline" in block_until_tail
    assert "expected status" in block_until_tail
    assert ("next test" in block_until_tail) or ("next step" in block_until_tail)
    assert ("keep answers focused" in block_until_tail) or ("focused" in block_until_tail)


def test_runtime_context40_prompt_builder_enforces_api_test_plan_runner_style_for_what_tests_should_i_run():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "I have an API endpoint GET /users. What tests should I run?",
        runtime_context=runtime_context,
    )
    low = system_prompt.lower()
    assert "API TEST PLAN RESPONSE STYLE:" in system_prompt
    assert "baseline test" in low
    assert "expected status" in low
    assert ("exactly one next test" in low) or (
        "exactly one additional follow-up test only" in low
    )
    assert "do not dump long category" in low
    assert "API DIAGNOSIS MODE:" not in system_prompt
    assert "SUITE RUN HELP MODE:" not in system_prompt


def test_runtime_context41_prompt_builder_knowledge_lane_covers_pagination_testing_signals():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Explain practical API testing for pagination",
        runtime_context=runtime_context,
    )
    marker = "API testing reference (condensed):"
    assert marker in system_prompt
    block = system_prompt.split(marker, 1)[1]
    block_until_tail = block.split("Execution enforcement (RUNTIME-01):", 1)[0].lower()
    assert "pagination" in block_until_tail
    assert ("page" in block_until_tail) or ("limit" in block_until_tail)
    assert ("cursor" in block_until_tail) or ("offset" in block_until_tail)


def test_runtime_context42_prompt_builder_knowledge_lane_covers_single_vs_multi_request_signals():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Explain API testing using single requests and suites",
        runtime_context=runtime_context,
    )
    marker = "API testing reference (condensed):"
    assert marker in system_prompt
    block = system_prompt.split(marker, 1)[1]
    block_until_tail = block.split("Execution enforcement (RUNTIME-01):", 1)[0].lower()
    assert "single request" in block_until_tail
    assert ("multi-request" in block_until_tail) or ("suite" in block_until_tail)
    assert ("json suite" in block_until_tail) or ("suite" in block_until_tail and "json" in block_until_tail)
    assert "method" in block_until_tail
    assert "url" in block_until_tail
    assert "expected status" in block_until_tail


def test_runtime_context43_prompt_builder_vague_real_usage_scaffold_for_build_test_plan():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Here\u2019s my API, build me a test plan",
        runtime_context=runtime_context,
    )
    low = system_prompt.lower()
    assert "API VAGUE REAL-USAGE SCAFFOLD MODE:" in system_prompt
    assert "starter structure" in low
    assert "do not stop at 'need more info'" in low
    assert "method" in low
    assert "endpoint" in low or "url" in low
    assert "expected status" in low
    assert "auth requirement" in low
    assert "one line max" in low
    assert "usable starter structure immediately" in low
    assert "ask only minimal follow-up fields" in low


def test_runtime_context44_prompt_builder_vague_real_usage_scaffold_for_failed_response_diagnosis():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Here\u2019s a failed response, diagnose it",
        runtime_context=runtime_context,
    )
    low = system_prompt.lower()
    assert "API VAGUE REAL-USAGE SCAFFOLD MODE:" in system_prompt
    assert "starter structure (failed response diagnosis)" in low
    assert "status code" in low
    assert "headers" in low
    assert "body" in low
    assert "auth" in low
    assert "compare expected vs actual" in low


def test_runtime_context45_prompt_builder_vague_real_usage_scaffold_for_json_suite():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "Help me build a JSON suite",
        runtime_context=runtime_context,
    )
    low = system_prompt.lower()
    assert "API VAGUE REAL-USAGE SCAFFOLD MODE:" in system_prompt
    assert "starter structure (json suite)" in low
    assert "method" in low
    assert "url" in low
    assert "expected status" in low
    assert "checks" in low


def test_runtime_context46_prompt_builder_vague_real_usage_scaffold_for_client_message():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    system_prompt, _ = playground.build_messages(
        "What do I send to this client?",
        runtime_context=runtime_context,
    )
    low = system_prompt.lower()
    assert "API VAGUE REAL-USAGE SCAFFOLD MODE:" in system_prompt
    assert "starter structure (client message)" in low
    assert "checklist" in low
    assert "expected vs actual" in low
    assert "next action" in low
    assert "ask only minimal follow-up fields" in low


def test_runtime_context11_prompt_builder_enforces_direct_405_mismatch_wording():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["last_bundle"]["latest_case"]["status_code"] = 405
    runtime_context["tool1"]["last_bundle"]["latest_case"]["method"] = "PATCH"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["url"] = "https://httpbin.org/put"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["response_headers"] = {
        "Allow": "PUT"
    }
    system_prompt, _ = playground.build_messages(
        "Analyze my last run and diagnose this 405 mismatch directly.",
        runtime_context=runtime_context,
    )
    assert 'Use direct mismatch wording: "You used [METHOD] on [URL] -> mismatch."' in system_prompt
    assert 'Immediately follow with: "This endpoint allows [ALLOWED METHODS]."' in system_prompt
    assert "allowed methods" in system_prompt
    assert "The reply must end with exactly one concrete next API test." in system_prompt
    assert "output_full" not in system_prompt
    assert "VERBOSE_BODY_SENTINEL_SHOULD_NOT_APPEAR_IN_PROMPT" not in system_prompt


def test_runtime_context12_prompt_builder_enforces_confident_success_phrase_for_2xx_no_failures():
    reset_agent_state()
    runtime_context = _runtime_context_sample_minimal()
    runtime_context["tool1"]["last_bundle"]["latest_case"]["status_code"] = 200
    runtime_context["tool1"]["last_bundle"]["latest_case"]["method"] = "PATCH"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["url"] = "https://httpbin.org/patch"
    runtime_context["tool1"]["last_bundle"]["latest_case"]["failures"] = []
    system_prompt, _ = playground.build_messages(
        "Analyze my last run and diagnose this successful request.",
        runtime_context=runtime_context,
    )
    assert 'include this exact sentence: "This request is correct."' in system_prompt
    assert "appears correct" in system_prompt
    assert "looks good" in system_prompt
    assert "seems fine" in system_prompt
    assert "The reply must end with exactly one concrete next API test." in system_prompt
    assert "output_full" not in system_prompt
    assert "VERBOSE_BODY_SENTINEL_SHOULD_NOT_APPEAR_IN_PROMPT" not in system_prompt


def test_optiona_simple_factual_routes_to_direct_answer_mode():
    reset_agent_state()
    q = "What is the capital of France?"
    system_prompt, _ = playground.build_messages(q)
    assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt
    assert "Structural output (RUNTIME-03):" not in system_prompt


def test_optiona_simple_explanation_routes_to_direct_answer_mode():
    reset_agent_state()
    q = "What does Tool 1 do?"
    system_prompt, _ = playground.build_messages(q)
    assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt
    assert "Structural output (RUNTIME-03):" not in system_prompt


def test_optiona_task_oriented_prompt_keeps_structured_path():
    reset_agent_state()
    q = "What should I do next?"
    system_prompt, _ = playground.build_messages(q)
    assert "CONVERSATION MODE (INTERACTION-01):" not in system_prompt
    assert "LIGHT TASK MODE:" in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt
    assert "Use exactly these three sections in this order:\n\nAnswer:" not in system_prompt
    assert "Conversation mode (INTERACTION-01):" in system_prompt


def test_light_task_mode_accepts_short_prefix_with_comma_before_next_step():
    reset_agent_state()
    q = "That's better, what should I do next?"
    system_prompt, _ = playground.build_messages(q)
    assert "LIGHT TASK MODE:" in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt
    assert "Use exactly these three sections in this order:\n\nAnswer:" not in system_prompt


def test_light_task_mode_okay_whats_next_step_with_prefix():
    reset_agent_state()
    q = "Okay, what's the next step?"
    system_prompt, _ = playground.build_messages(q)
    assert "LIGHT TASK MODE:" in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt


def test_light_task_mode_alright_what_should_i_try_with_prefix():
    reset_agent_state()
    q = "Alright, what should I try?"
    system_prompt, _ = playground.build_messages(q)
    assert "LIGHT TASK MODE:" in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt


def test_light_task_mode_prompt_requires_one_concrete_action_or_one_question():
    """LIGHT TASK MODE: decisiveness block (Jessy + ChatGPT increment)."""
    reset_agent_state()
    for q in (
        "What should I do next?",
        "That's better, what should I do next?",
        "Alright, what should I try?",
    ):
        system_prompt, _ = playground.build_messages(q)
        assert "LIGHT TASK MODE:" in system_prompt
        assert "OUTPUT FORMAT RULES:" not in system_prompt
        assert "DECISIVENESS:" in system_prompt
        assert "FIRST SENTENCE:" in system_prompt
        assert "one precise clarifying question" in system_prompt
        assert "vague-only coaching" in system_prompt
        assert "do NOT invent repo paths" in system_prompt


def test_clarify_first_undefined_implement_placeholder_routes_without_structured_template():
    reset_agent_state()
    for q in (
        "What should I do next to implement X?",
        "How should I build Y?",
        "OK, what should I do next to implement z?",
    ):
        system_prompt, _ = playground.build_messages(q)
        assert "CLARIFY-FIRST (UNDEFINED IMPLEMENT/BUILD TARGET):" in system_prompt
        assert "OUTPUT FORMAT RULES:" not in system_prompt
        assert "LIGHT TASK MODE:" not in system_prompt


def test_implement_with_py_path_stays_heavy_not_clarify_first():
    reset_agent_state()
    q = "What should I do next to implement the fix in parser.py?"
    system_prompt, _ = playground.build_messages(q)
    assert "CLARIFY-FIRST (UNDEFINED IMPLEMENT/BUILD TARGET):" not in system_prompt
    assert "OUTPUT FORMAT RULES:" in system_prompt


def test_light_task_comma_still_heavy_when_implement_follows():
    reset_agent_state()
    q = "OK, what should I do next to implement X?"
    system_prompt, _ = playground.build_messages(q)
    assert "LIGHT TASK MODE:" not in system_prompt
    assert "CLARIFY-FIRST (UNDEFINED IMPLEMENT/BUILD TARGET):" in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt


def test_heavy_next_step_stays_open_conversation_structure():
    reset_agent_state()
    q = "What should I do next to implement the fix in parser.py?"
    system_prompt, _ = playground.build_messages(q)
    assert "LIGHT TASK MODE:" not in system_prompt
    assert "OUTPUT FORMAT RULES:" in system_prompt
    assert "Current state:" in system_prompt


def test_optiona_no_mode_collision_for_simple_factual_prompt():
    reset_agent_state()
    q = "What is the capital of France?"
    system_prompt, _ = playground.build_messages(q)
    assert "CONVERSATION MODE (INTERACTION-01):" in system_prompt
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in system_prompt
    assert "OUTPUT FORMAT RULES:" not in system_prompt
    assert "Structural output (RUNTIME-03):" not in system_prompt


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
            # URL-in-message path: fetch runs first; this is the post-fetch LLM call only.
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
        # Body must exceed LATENCY-10 trivial cap so the post-fetch LLM still runs.
        playground.fetch_page = lambda url: f"FAKE FETCH OK: {url} " + ("a" * 70)

        result = playground.handle_user_input("Read https://example.com")

        assert "Answer:" in result, "Missing Answer section"
        assert "This is a fetched summary." in result, "Missing final post-fetch answer"
        assert "Action type: research" in result, "Expected research action type"
        assert call_count["n"] == 1, f"Expected 1 LLM call (post-fetch only), got {call_count['n']}"

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
        assert call_count["n"] == 1, f"Expected 1 LLM call (post-fetch only), got {call_count['n']}"

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_fetch_failure_short_circuits_second_llm():
    """URL-first fetch: tagged failure returns Fetch failed with no LLM calls."""
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            raise AssertionError("LLM should not run when forced fetch returns a failure tag")

        playground.ask_ai = fake_ask_ai
        playground.fetch_page = lambda url: "[fetch:timeout] Request timed out."

        result = playground.handle_user_input("Read https://example.com/slow")

        assert call_count["n"] == 0, f"Expected 0 LLM calls, got {call_count['n']}"
        assert result == "Fetch failed"

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

        assert call_count["n"] == 0
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

        assert call_count["n"] == 0
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

        assert call_count["n"] == 0
        assert "Answer:" in result and "Action type: research" in result

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_brave_search_tool_command_triggers_tool_and_returns_result():
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_brave_search = playground.brave_search
    try:
        call_count = {"n": 0}
        seen = {"query": None}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "TOOL:brave_search what is an API"
            return "Brave result returned."

        def fake_brave_search(query):
            seen["query"] = query
            return {
                "ok": True,
                "status_code": 200,
                "query": query,
                "results": [
                    {
                        "title": "API definition",
                        "snippet": "An API is an application programming interface used to define contracts between clients and services with request and response behaviors for practical integration testing.",
                        "url": "https://example.com/api",
                    }
                ],
                "error": None,
            }

        playground.ask_ai = fake_ask_ai
        playground.brave_search = fake_brave_search

        result = playground.handle_user_input("Can you check this topic?")

        assert seen["query"] == "what is an API", seen
        assert call_count["n"] == 2, call_count
        assert result == "Brave result returned."
    finally:
        playground.ask_ai = original_ask_ai
        playground.brave_search = original_brave_search


def test_increment3d_explicit_web_search_bypasses_first_llm_and_forces_brave():
    reset_agent_state()
    original_ask_ai = playground.ask_ai
    original_brave_search = playground.brave_search
    try:
        call_count = {"n": 0}
        seen = {"query": None}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            return "Brave routed response."

        def fake_brave_search(query):
            seen["query"] = query
            return {
                "ok": True,
                "status_code": 200,
                "query": query,
                "results": [
                    {
                        "title": "API definition",
                        "snippet": "API means application programming interface and this explanation is intentionally long enough to avoid deterministic trivial-short-circuit behavior in the post-tool flow so the second LLM pass is exercised.",
                        "url": "https://example.com/api",
                    }
                ],
                "error": None,
            }

        playground.ask_ai = fake_ask_ai
        playground.brave_search = fake_brave_search

        result = playground.handle_user_input("Search the web for what is an API")
        assert seen["query"] == "what is an api", seen
        # One LLM call only: post-tool answer synthesis, no first-pass memory answer.
        assert call_count["n"] == 1, call_count
        assert result == "Brave routed response."
    finally:
        playground.ask_ai = original_ask_ai
        playground.brave_search = original_brave_search


def test_increment3d_non_search_query_does_not_force_brave():
    reset_agent_state()
    original_ask_ai = playground.ask_ai
    original_brave_search = playground.brave_search
    try:
        seen = {"called": False}

        def fake_ask_ai(messages, system_prompt=None):
            return "Normal model answer."

        def fake_brave_search(query):
            seen["called"] = True
            return {"ok": False, "status_code": None, "query": query, "results": [], "error": "unexpected"}

        playground.ask_ai = fake_ask_ai
        playground.brave_search = fake_brave_search

        result = playground.handle_user_input("What is an API?")
        assert result == "Normal model answer."
        assert seen["called"] is False
    finally:
        playground.ask_ai = original_ask_ai
        playground.brave_search = original_brave_search


def test_increment3e_brave_formatted_payload_includes_sources():
    payload = playground._format_brave_search_result_for_post_tool(
        {
            "ok": True,
            "status_code": 200,
            "query": "what is an api",
            "results": [
                {
                    "title": "API definition",
                    "snippet": "API means application programming interface.",
                    "url": "https://example.com/api",
                },
                {
                    "title": "HTTP API basics",
                    "snippet": "HTTP APIs use methods and status codes.",
                    "url": "https://example.com/http",
                },
            ],
            "error": None,
        }
    )
    assert "BRAVE RESULT" in payload
    assert "Sources:" in payload
    assert "- API definition — https://example.com/api" in payload
    assert "- HTTP API basics — https://example.com/http" in payload


def test_increment3f_brave_sources_skip_missing_urls():
    payload = playground._format_brave_search_result_for_post_tool(
        {
            "ok": True,
            "status_code": 200,
            "query": "api",
            "results": [
                {"title": "No link row", "snippet": "missing url", "url": ""},
                {"title": "Good row", "snippet": "has url", "url": "https://example.com/good"},
            ],
            "error": None,
        }
    )
    assert "Sources:" in payload
    assert "- Good row — https://example.com/good" in payload
    assert "- No link row" not in payload


def test_increment3e_brave_no_sources_reports_unavailable():
    payload = playground._format_brave_search_result_for_post_tool(
        {
            "ok": True,
            "status_code": 200,
            "query": "nothing",
            "results": [],
            "error": None,
        }
    )
    assert "Sources:" in payload
    assert "No sources were available." in payload


def test_increment3f_brave_post_fetch_prompt_adds_source_integrity_and_summary_clarity():
    prompt, _ = playground.build_post_fetch_messages(
        user_input="Search the web for what is an API",
        fetched_content="BRAVE RESULT\nSources:\n- API definition — https://example.com/api",
        focus="ai-agent project",
        stage="Phase 4 action-layer refinement",
        fetch_url="brave://search",
    )
    assert "Source integrity: every listed source must be exactly title — URL; skip any item without a URL." in prompt
    assert "Summary clarity: avoid repeating phrases; keep wording clean, direct, and concise." in prompt
    assert "When helpful, use compact bullet-style phrasing in the Summary section." in prompt


def test_increment3e_brave_post_fetch_prompt_rules_include_language_and_sources():
    prompt, _ = playground.build_post_fetch_messages(
        user_input="Explique-moi ce sujet en français",
        fetched_content="BRAVE RESULT\nSources:\n- API definition — https://example.com/api",
        focus="ai-agent project",
        stage="Phase 4 action-layer refinement",
        fetch_url="brave://search",
    )
    assert "BRAVE SOURCE-BACKED ANSWER RULES:" in prompt
    assert "Include 1-3 sources when available." in prompt
    assert "No sources were available." in prompt
    assert "Respect the user's requested output language for wording; keep source URLs unchanged." in prompt


def test_increment3c_prompt_enforces_brave_for_explicit_web_search_intent():
    reset_agent_state()
    prompt, _ = playground.build_messages("Search the web for what is an API")
    assert "Explicit web-search intent (\"search the web\", \"find\", \"look up\") MUST use TOOL:brave_search" in prompt
    assert "Priority rule: explicit web-search intent > model memory/knowledge." in prompt
    assert "Example mapping: \"Search the web for what is an API\" -> TOOL:brave_search what is an API" in prompt
    assert "Example mapping: \"Find 3 explanations of HTTP status codes\" -> TOOL:brave_search http status codes explained" in prompt


def test_increment3c_prompt_enforces_brave_for_find_request():
    reset_agent_state()
    prompt, _ = playground.build_messages("Find 3 explanations of HTTP status codes")
    assert "Explicit web-search intent (\"search the web\", \"find\", \"look up\") MUST use TOOL:brave_search" in prompt
    assert "Priority rule: explicit web-search intent > model memory/knowledge." in prompt
    assert "TOOL:brave_search http status codes explained" in prompt


def test_fetch_over_trivial_char_cap_still_uses_second_llm():
    """LATENCY-10: body over char/word trivial cap runs post-fetch ask_ai (URL-first: single LLM)."""
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
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

        assert call_count["n"] == 1, f"Expected 1 post-fetch LLM call, got {call_count['n']}"

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_fetch_over_trivial_word_cap_still_uses_second_llm():
    """LATENCY-10: many short words still run post-fetch ask_ai (URL-first: single LLM)."""
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
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

        assert call_count["n"] == 1, f"Expected 1 post-fetch LLM call, got {call_count['n']}"

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_post_fetch_quote_guard_strips_unsupported_verbatim_quotes():
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        call_count = {"n": 0}

        def fake_ask_ai(messages, system_prompt=None):
            call_count["n"] += 1
            return (
                "Answer:\n"
                'The homepage says "THIS QUOTE IS NOT IN FETCHED CONTENT".\n\n'
                "Current state:\n"
                "Focus: ai-agent project\n"
                "Stage: Phase 4 action-layer refinement\n"
                "Action type: research\n\n"
                "Next step:\n"
                "Verify one concrete detail from the fetched page."
            )

        playground.ask_ai = fake_ask_ai
        playground.fetch_page = lambda url: (
            "Example Domain This domain is for use in documentation examples without needing permission. "
            "Use this domain in examples."
        )

        result = playground.handle_user_input("Read https://example.com and quote the headline")

        assert call_count["n"] == 1
        assert '"THIS QUOTE IS NOT IN FETCHED CONTENT"' not in result
        assert "THIS QUOTE IS NOT IN FETCHED CONTENT" in result

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_forced_multi_url_fetch_merges_two_sources_for_post_fetch():
    reset_agent_state()

    original_ask_ai = playground.ask_ai
    original_fetch_page = playground.fetch_page

    try:
        seen_urls = []
        captured_post_fetch_user_message = {"text": ""}

        def fake_fetch_page(url):
            seen_urls.append(url)
            if "bbc" in url:
                return "BBC HOMEPAGE SNAPSHOT " + ("a " * 70)
            if "nytimes" in url:
                return "NYTIMES HOMEPAGE SNAPSHOT " + ("b " * 70)
            return "UNKNOWN SOURCE " + ("x " * 70)

        def fake_ask_ai(messages, system_prompt=None):
            captured_post_fetch_user_message["text"] = str(messages[0].get("content", ""))
            return (
                "Answer:\n"
                "Combined source check.\n\n"
                "Current state:\n"
                "Focus: ai-agent project\n"
                "Stage: Phase 4 action-layer refinement\n"
                "Action type: research\n\n"
                "Next step:\n"
                "Verify one detail from each source."
            )

        playground.fetch_page = fake_fetch_page
        playground.ask_ai = fake_ask_ai

        result = playground.handle_user_input(
            "Compare https://www.bbc.com and https://www.nytimes.com headlines"
        )

        assert seen_urls == ["https://www.bbc.com", "https://www.nytimes.com"]
        joined_prompt = captured_post_fetch_user_message["text"]
        assert "=== SOURCE 1: https://www.bbc.com ===" in joined_prompt
        assert "=== SOURCE 2: https://www.nytimes.com ===" in joined_prompt
        assert "BBC HOMEPAGE SNAPSHOT" in joined_prompt
        assert "NYTIMES HOMEPAGE SNAPSHOT" in joined_prompt
        assert "Combined source check." in result

    finally:
        playground.ask_ai = original_ask_ai
        playground.fetch_page = original_fetch_page


def test_fetch_failure_tag_plain_and_tagged():
    assert fetch_failure_tag("Hello world") is None
    assert fetch_failure_tag("[fetch:timeout] x") == "timeout"
    assert fetch_failure_tag("  [fetch:forbidden] HTTP 403") == "forbidden"


def test_runtime_priority_guard_replaces_unaligned_tool_refine_next_step():
    priority = "Achieve $150/day income"
    initial = "Refine the tool internals for cleaner architecture."
    out = playground._enforce_user_priority_next_step(initial, priority)
    assert out != initial
    assert "USER PRIORITY: Achieve $150/day income" in out
    assert "revenue" in out.lower() or "client" in out.lower()


def test_force_structured_override_enforces_user_priority_on_next_step():
    reset_agent_state()

    original_is_meta = playground.is_meta_system_override_question
    original_build_next = playground.build_specific_next_step
    original_anti_repeat = playground.apply_recent_negative_outcome_anti_repeat_guard
    original_retrieve_user_purpose = playground.retrieve_user_purpose_memory

    try:
        playground.is_meta_system_override_question = lambda user_input, focus, stage: True
        playground.build_specific_next_step = (
            lambda user_input, focus, stage, action_type: "Refine the tool internals."
        )
        playground.apply_recent_negative_outcome_anti_repeat_guard = (
            lambda user_input, next_step: (next_step, False)
        )
        playground.retrieve_user_purpose_memory = lambda user_input, limit=2: [
            {
                "memory_id": "mem_goal_income",
                "category": "goal",
                "value": "Achieve $150/day income",
                "confidence": 0.9,
                "importance": 0.95,
                "status": "active",
                "memory_kind": "stable",
                "evidence_count": 4,
                "last_seen": "runtime",
                "trend": "reinforced",
                "source_refs": ["runtime"],
            }
        ]

        result = playground.handle_user_input("What should I do next?")

        assert "Next step:\nRefine the tool internals." not in result
        assert "USER PRIORITY: Achieve $150/day income" in result
        assert "revenue" in result.lower() or "client" in result.lower()

    finally:
        playground.is_meta_system_override_question = original_is_meta
        playground.build_specific_next_step = original_build_next
        playground.apply_recent_negative_outcome_anti_repeat_guard = original_anti_repeat
        playground.retrieve_user_purpose_memory = original_retrieve_user_purpose


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
            raise RuntimeError("OPENAI_API_KEY is missing.")

        playground.ask_ai = fake_ask_ai
        result = playground.handle_user_input("What should I do next?")
        assert result.startswith("LLM configuration error:"), f"Unexpected result: {result}"
        assert "OPENAI_API_KEY is missing." in result, "Missing specific preflight error"
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


def test_system_eval_prompt_response_lane_requires_prompt_fields():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "pr-missing-fields",
                "target_name": "t",
                "cases": [
                    {
                        "name": "pr1",
                        "lane": "prompt_response",
                        "assertions": {},
                    }
                ],
            }
        )
        assert False, "Expected ValueError for missing prompt_response fields"
    except ValueError as exc:
        msg = str(exc).lower()
        assert "prompt_input" in msg or "expected_response_contains" in msg, exc


def test_system_eval_prompt_response_lane_normalizes_prompt_fields():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-normalize",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "  hello model  ",
                    "expected_response_contains": ["answer", "done"],
                    "assertions": {},
                }
            ],
        }
    )
    case = suite["cases"][0]
    assert case["lane"] == "prompt_response", case
    assert case["prompt_input"] == "hello model", case
    assert case["expected_response_contains"] == ["answer", "done"], case


def test_system_eval_prompt_response_lane_normalizes_not_contains_field():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-normalize-not-contains",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello model",
                    "expected_response_contains": ["hello"],
                    "expected_response_not_contains": ["error", "forbidden"],
                    "assertions": {},
                }
            ],
        }
    )
    case = suite["cases"][0]
    assert case["expected_response_not_contains"] == ["error", "forbidden"], case


def test_system_eval_prompt_response_lane_executes_with_prompt_adapter_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-execute",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_case(self, case):
            _ = case
            assert False, "prompt_response lane should use run_prompt_case, not run_case"

        def run_prompt_case(self, case):
            assert case["prompt_input"] == "hello", case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=7,
                response_headers={"Content-Type": "text/plain"},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert row["lane"] == "prompt_response", row
    assert row["ok"] is True, row
    assert row["failures"] == [], row


def test_system_eval_prompt_response_lane_fails_on_forbidden_substring():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-forbidden-fail",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_not_contains": ["secret-token"],
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world secret-token",
                latency_ms=4,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert row["ok"] is False, row
    assert any("expected_response_forbidden_substring_present: secret-token" in f for f in row["failures"]), row


def test_system_eval_prompt_response_lane_regex_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-regex-pass",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["hello"],
                    "expected_response_regex": r"world\s+2026",
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world 2026",
                latency_ms=3,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is True, result


def test_system_eval_prompt_response_lane_regex_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-regex-fail",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["hello"],
                    "expected_response_regex": r"forbidden\d+",
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=3,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert any("expected_response_regex_mismatch:" in f for f in row["failures"]), row


def test_system_eval_prompt_response_lane_starts_with_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-starts-with-pass",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_starts_with": "hello",
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=2,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert row["expected_response_starts_with"] == "hello", row


def test_system_eval_prompt_response_lane_starts_with_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-starts-with-fail",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_starts_with": "greetings",
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=2,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert row["ok"] is False, row
    assert any("expected_response_prefix_mismatch:" in f for f in row["failures"]), row


def test_system_eval_prompt_response_lane_ends_with_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-ends-with-pass",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_ends_with": "world",
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=2,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert row["expected_response_ends_with"] == "world", row


def test_system_eval_prompt_response_lane_ends_with_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-ends-with-fail",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_ends_with": "goodbye",
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=2,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert row["ok"] is False, row
    assert any("expected_response_suffix_mismatch:" in f for f in row["failures"]), row


def test_system_eval_prompt_response_lane_equals_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-equals-pass",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_equals": "hello world",
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=2,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert row["expected_response_equals"] == "hello world", row


def test_system_eval_prompt_response_lane_equals_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-equals-fail",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_equals": "HELLO WORLD",
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=2,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert row["ok"] is False, row
    assert any("expected_response_exact_mismatch" in f for f in row["failures"]), row


def test_system_eval_prompt_response_lane_length_min_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-length-min-pass",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_length_min": 5,
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=2,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert row["expected_response_length_min"] == 5, row


def test_system_eval_prompt_response_lane_length_min_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-length-min-fail",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_length_min": 20,
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=2,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert row["ok"] is False, row
    assert any("expected_response_length_too_short:" in f for f in row["failures"]), row


def test_system_eval_prompt_response_lane_length_max_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-length-max-pass",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_length_max": 20,
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=2,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert row["expected_response_length_max"] == 20, row


def test_system_eval_prompt_response_lane_length_max_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-length-max-fail",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_length_max": 5,
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=2,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert row["ok"] is False, row
    assert any("expected_response_length_too_long:" in f for f in row["failures"]), row


def test_system_eval_prompt_response_lane_length_bounds_validate_when_ordered():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-length-bounds-valid",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "expected_response_length_min": 5,
                    "expected_response_length_max": 20,
                    "assertions": {},
                }
            ],
        }
    )
    case = suite["cases"][0]
    assert case["expected_response_length_min"] == 5, case
    assert case["expected_response_length_max"] == 20, case


def test_system_eval_prompt_response_lane_length_bounds_reject_inverted_range():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "pr-length-bounds-invalid",
                "target_name": "t",
                "cases": [
                    {
                        "name": "pr1",
                        "lane": "prompt_response",
                        "prompt_input": "hello",
                        "expected_response_contains": ["world"],
                        "expected_response_length_min": 50,
                        "expected_response_length_max": 10,
                        "assertions": {},
                    }
                ],
            }
        )
        assert False, "Expected ValueError for inverted response length bounds"
    except ValueError as exc:
        msg = str(exc)
        assert "expected_response_length_min" in msg and "expected_response_length_max" in msg, msg


def test_system_eval_prompt_response_lane_length_min_rejects_bool():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "pr-length-min-bool",
                "target_name": "t",
                "cases": [
                    {
                        "name": "pr1",
                        "lane": "prompt_response",
                        "prompt_input": "hello",
                        "expected_response_contains": ["world"],
                        "expected_response_length_min": True,
                        "assertions": {},
                    }
                ],
            }
        )
        assert False, "Expected ValueError for bool expected_response_length_min"
    except ValueError as exc:
        msg = str(exc)
        assert "expected_response_length_min" in msg, msg


def test_system_eval_prompt_response_lane_length_max_rejects_bool():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "pr-length-max-bool",
                "target_name": "t",
                "cases": [
                    {
                        "name": "pr1",
                        "lane": "prompt_response",
                        "prompt_input": "hello",
                        "expected_response_contains": ["world"],
                        "expected_response_length_max": False,
                        "assertions": {},
                    }
                ],
            }
        )
        assert False, "Expected ValueError for bool expected_response_length_max"
    except ValueError as exc:
        msg = str(exc)
        assert "expected_response_length_max" in msg, msg


def test_system_eval_prompt_response_fields_rejected_outside_prompt_lane():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "pr-fields-outside-lane",
                "target_name": "t",
                "cases": [
                    {
                        "name": "c1",
                        "lane": "correctness",
                        "method": "GET",
                        "url": "https://example.com/health",
                        "expected_response_contains": ["ok"],
                        "assertions": {"status_code": 200},
                    }
                ],
            }
        )
        assert False, "Expected ValueError for prompt-response-only field outside prompt_response lane"
    except ValueError as exc:
        msg = str(exc)
        assert "prompt-response-only field" in msg and "expected_response_contains" in msg, msg


def test_system_eval_prompt_input_rejected_when_lane_omitted():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "pr-input-without-lane",
                "target_name": "t",
                "cases": [
                    {
                        "name": "c1",
                        "method": "GET",
                        "url": "https://example.com/health",
                        "prompt_input": "hello model",
                        "assertions": {"status_code": 200},
                    }
                ],
            }
        )
        assert False, "Expected ValueError for prompt_input without prompt_response lane"
    except ValueError as exc:
        msg = str(exc)
        assert "prompt-response-only field" in msg and "prompt_input" in msg, msg


def test_system_eval_prompt_response_lane_fails_on_missing_substring():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-execute-fail",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world", "banana"],
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="hello world",
                latency_ms=4,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert row["ok"] is False, row
    assert any("expected_response_missing_substring: banana" in f for f in row["failures"]), row


def test_system_eval_prompt_response_lane_fails_when_prompt_adapter_missing():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-no-adapter",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "assertions": {},
                }
            ],
        }
    )

    class HttpOnlyAdapter:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(ok=True, status_code=200, output_text="ok", latency_ms=1)

    result = system_eval_core.execute_suite(suite, adapter=HttpOnlyAdapter())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert row["ok"] is False, row
    assert any("prompt_response_adapter_missing" in f for f in row["failures"]), row


def test_system_eval_prompt_response_lane_coerces_non_string_output_text():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-non-string-output",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["42"],
                    "expected_response_equals": "42",
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text=42,
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert row["ok"] is True, row
    assert row["output_full"] == "42", row


def test_system_eval_prompt_response_lane_non_string_output_fails_cleanly():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-non-string-output-fail",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["nomatch-token"],
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text={"status": "ok"},
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert row["ok"] is False, row
    assert any("expected_response_missing_substring: nomatch-token" in f for f in row["failures"]), row
    assert "{'status': 'ok'}" in row["output_preview"], row


def test_system_eval_prompt_response_lane_adapter_exception_fails_cleanly():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-adapter-exception",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "assertions": {},
                }
            ],
        }
    )

    class PromptAdapter:
        def run_prompt_case(self, case):
            _ = case
            raise RuntimeError("mock prompt adapter boom")

    result = system_eval_core.execute_suite(suite, adapter=PromptAdapter())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert row["ok"] is False, row
    assert any("prompt_response_adapter_exception:" in f for f in row["failures"]), row


def test_system_eval_prompt_response_lane_fail_fast_stops_after_first_failure():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-fail-fast-true",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "first",
                    "expected_response_contains": ["must-not-match"],
                    "assertions": {},
                },
                {
                    "name": "pr2",
                    "lane": "prompt_response",
                    "prompt_input": "second",
                    "expected_response_contains": ["second"],
                    "assertions": {},
                },
            ],
        }
    )

    class PromptAdapter:
        def __init__(self):
            self.calls = 0

        def run_prompt_case(self, case):
            self.calls += 1
            _ = case
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text="first response",
                latency_ms=1,
                response_headers={},
            )

    adapter = PromptAdapter()
    result = system_eval_core.execute_suite(suite, adapter=adapter, fail_fast=True)
    assert result["ok"] is False, result
    assert result["executed_cases"] == 1, result
    assert adapter.calls == 1, adapter.calls


def test_system_eval_prompt_response_lane_fail_fast_false_runs_all_cases():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "pr-fail-fast-false",
            "target_name": "t",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "first",
                    "expected_response_contains": ["must-not-match"],
                    "assertions": {},
                },
                {
                    "name": "pr2",
                    "lane": "prompt_response",
                    "prompt_input": "second",
                    "expected_response_contains": ["second"],
                    "assertions": {},
                },
            ],
        }
    )

    class PromptAdapter:
        def __init__(self):
            self.calls = 0

        def run_prompt_case(self, case):
            self.calls += 1
            prompt = str(case.get("prompt_input") or "")
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=200,
                output_text=f"{prompt} response",
                latency_ms=1,
                response_headers={},
            )

    adapter = PromptAdapter()
    result = system_eval_core.execute_suite(suite, adapter=adapter, fail_fast=False)
    assert result["ok"] is False, result
    assert result["executed_cases"] == 2, result
    assert adapter.calls == 2, adapter.calls


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
    assert result["cases"][3]["lane"] == "smoke", result["cases"][3]

    with tempfile.TemporaryDirectory() as temp_dir:
        paths = system_eval_core.write_result_artifacts(
            result, temp_dir, file_stem="lane_artifact"
        )
        written = json.loads(Path(paths["json_path"]).read_text(encoding="utf-8"))
        assert written["cases"][0]["lane"] == "stability", written
        assert written["cases"][3]["lane"] == "smoke", written
        assert written["cases"][0]["attempts_passed"] == 3, written
        assert written["cases"][2]["attempts_passed"] == 3, written
        md_text = Path(paths["markdown_path"]).read_text(encoding="utf-8")
        assert "lane=`stability`" in md_text, md_text
        assert "lane=`correctness`" in md_text, md_text
        assert "lane=`consistency`" in md_text, md_text
        assert "lane=`smoke`" in md_text, md_text
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


def test_run_tool1_system_eval_operator_default_adapter_prompt_lane_fails_cleanly():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out = root / "out"
        suite_data = {
            "suite_name": "prompt-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "pr1",
                    "lane": "prompt_response",
                    "prompt_input": "Say hello world",
                    "expected_response_contains": ["hello", "world"],
                    "assertions": {},
                }
            ],
        }
        suite_path = root / "suite_prompt.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")

        bundle = run_tool1_system_eval_http(
            str(suite_path),
            str(out),
            "prompt_run",
            project_root=root,
            adapter=None,
        )
        assert bundle.get("error") in (None, ""), bundle
        assert bundle["ok"] is False, bundle
        row = (bundle.get("result") or {}).get("cases", [{}])[0]
        fails = row.get("failures") or []
        assert any("prompt_response_adapter_missing" in str(f) for f in fails), row
        assert Path(bundle["artifact_paths"]["json_path"]).is_file(), bundle


def test_run_tool1_system_eval_operator_default_adapter_keeps_http_path():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out = root / "out"
        suite_data = {
            "suite_name": "http-suite-default-adapter",
            "target_name": "fake",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {"status_code": 200, "contains_all": ["ok"]},
                }
            ],
        }
        suite_path = root / "suite_http.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")

        fake_res = system_eval_core.AdapterResult(
            ok=True, status_code=200, output_text="ok body", latency_ms=2, response_headers={}
        )
        with patch("core.system_eval.HttpTargetAdapter.run_case", return_value=fake_res):
            bundle = run_tool1_system_eval_http(
                str(suite_path),
                str(out),
                "http_run",
                project_root=root,
                adapter=None,
            )
        assert bundle.get("error") in (None, ""), bundle
        assert bundle["ok"] is True, bundle
        assert Path(bundle["artifact_paths"]["json_path"]).is_file(), bundle


def test_run_tool2_prompt_response_eval_rejects_non_prompt_lane():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool2-bad-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "http-case",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {},
                }
            ],
        }
        suite_path = root / "suite_bad.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        bundle = run_tool2_prompt_response_eval(
            str(suite_path),
            str(root / "out"),
            "tool2_bad",
            project_root=root,
        )
        assert bundle["ok"] is False, bundle
        assert "lane='prompt_response'" in (bundle.get("error") or ""), bundle


def test_run_tool2_prompt_response_eval_missing_suite_logs_failure_record():
    from app import tool2_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        missing_suite = root / "does_not_exist_tool2_suite.json"
        log_path = tool2_run_log.tool2_run_log_path(root)
        bundle = run_tool2_prompt_response_eval(
            str(missing_suite),
            str(root / "out"),
            "tool2_missing_suite",
            project_root=root,
        )
        assert bundle["ok"] is False, bundle
        assert "Suite file not found" in (bundle.get("error") or ""), bundle
        assert bundle.get("run_log_error") in (None, ""), bundle
        assert "tool2_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        assert log_path.is_file(), "missing suite should still write tool2 run log record"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec.get("run_type") == "tool2_suite_run", rec
        assert isinstance(rec.get("error"), str) and "Suite file not found" in rec.get("error"), rec


def test_run_tool2_prompt_response_eval_invalid_json_logs_failure_record():
    from app import tool2_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_path = root / "suite_tool2_invalid.json"
        suite_path.write_text("{ invalid json", encoding="utf-8")
        log_path = tool2_run_log.tool2_run_log_path(root)
        bundle = run_tool2_prompt_response_eval(
            str(suite_path),
            str(root / "out"),
            "tool2_invalid_json",
            project_root=root,
        )
        assert bundle["ok"] is False, bundle
        assert isinstance(bundle.get("error"), str) and bundle.get("error"), bundle
        assert bundle.get("run_log_error") in (None, ""), bundle
        assert "tool2_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        assert log_path.is_file(), "invalid JSON should still write tool2 run log record"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec.get("run_type") == "tool2_suite_run", rec
        assert isinstance(rec.get("error"), str) and rec.get("error"), rec


def test_run_tool2_prompt_response_eval_invalid_timeout_rejected_and_logged():
    from app import tool2_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_path = root / "suite_tool2_timeout_invalid.json"
        suite_path.write_text(
            json.dumps(
                {
                    "suite_name": "tool2-timeout-invalid",
                    "target_name": "fake",
                    "cases": [
                        {
                            "name": "prompt-case",
                            "lane": "prompt_response",
                            "prompt_input": "hello",
                            "expected_response_contains": ["hello"],
                            "assertions": {},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        log_path = tool2_run_log.tool2_run_log_path(root)
        bundle = run_tool2_prompt_response_eval(
            str(suite_path),
            str(root / "out"),
            "tool2_timeout_invalid",
            project_root=root,
            default_timeout_seconds=0,
        )
        assert bundle["ok"] is False, bundle
        assert "default_timeout_seconds" in str(bundle.get("error") or ""), bundle
        assert "tool2_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        assert log_path.is_file(), "invalid timeout should still write tool2 run log record"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec.get("run_type") == "tool2_suite_run", rec
        assert "default_timeout_seconds" in str(rec.get("error") or ""), rec


def test_run_tool2_prompt_response_eval_timeout_bool_rejected():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_path = root / "suite_tool2_timeout_bool.json"
        suite_path.write_text(
            json.dumps(
                {
                    "suite_name": "tool2-timeout-bool",
                    "target_name": "fake",
                    "cases": [
                        {
                            "name": "prompt-case",
                            "lane": "prompt_response",
                            "prompt_input": "hello",
                            "expected_response_contains": ["hello"],
                            "assertions": {},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        bundle = run_tool2_prompt_response_eval(
            str(suite_path),
            str(root / "out"),
            "tool2_timeout_bool",
            project_root=root,
            default_timeout_seconds=True,
        )
        assert bundle["ok"] is False, bundle
        assert "default_timeout_seconds" in str(bundle.get("error") or ""), bundle


def test_run_tool2_prompt_response_eval_default_adapter_passes():
    from app import tool2_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool2-good-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "prompt-case",
                    "lane": "prompt_response",
                    "prompt_input": "say hello world",
                    "expected_response_contains": ["hello", "world"],
                    "assertions": {},
                }
            ],
        }
        suite_path = root / "suite_good.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        tool2_log_path = tool2_run_log.tool2_run_log_path(root)
        with patch("app.tool2_operator._default_prompt_executor", return_value="hello world from tool2"):
            bundle = run_tool2_prompt_response_eval(
                str(suite_path),
                str(root / "out"),
                "tool2_good",
                project_root=root,
                default_timeout_seconds=37,
            )
        assert bundle.get("error") in (None, ""), bundle
        assert bundle["ok"] is True, bundle
        assert Path(bundle["artifact_paths"]["json_path"]).is_file(), bundle
        assert "tool2_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        rec = json.loads(tool2_log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        cfg = rec.get("configuration") or {}
        assert cfg.get("timeout_seconds") == 37, rec


def test_tool2_prompt_response_logging_includes_prompt_fields():
    from app import tool1_run_log, tool2_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool2-log-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "prompt-case",
                    "lane": "prompt_response",
                    "prompt_input": "Explain onboarding",
                    "expected_response_contains": ["onboarding", "steps"],
                    "expected_response_not_contains": ["secret"],
                    "expected_response_regex": r"onboarding\s+steps",
                    "expected_response_starts_with": "onboarding",
                    "expected_response_ends_with": "listed",
                    "expected_response_equals": "onboarding steps are listed",
                    "expected_response_length_min": 10,
                    "expected_response_length_max": 200,
                    "assertions": {},
                }
            ],
        }
        suite_path = root / "suite_tool2_log.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        tool2_log_path = tool2_run_log.tool2_run_log_path(root)
        tool1_log_path = tool1_run_log.tool1_run_log_path(root)

        with patch("app.tool2_operator._default_prompt_executor", return_value="onboarding steps are listed"):
            bundle = run_tool2_prompt_response_eval(
                str(suite_path),
                str(root / "out"),
                "tool2_log",
                project_root=root,
            )
        assert bundle["ok"] is True, bundle
        assert tool2_log_path.is_file(), "tool2 run should be logged to tool2 log"
        assert not tool1_log_path.exists(), "tool2 run should not write tool1 log"
        rec = json.loads(tool2_log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec.get("run_type") == "tool2_suite_run", rec
        req0 = (rec.get("requests") or [{}])[0]
        case0 = (rec.get("cases_outcome") or [{}])[0]
        assert req0.get("prompt_input") == "Explain onboarding", req0
        assert req0.get("expected_response_contains") == ["onboarding", "steps"], req0
        assert req0.get("expected_response_not_contains") == ["secret"], req0
        assert req0.get("expected_response_regex") == r"onboarding\s+steps", req0
        assert req0.get("expected_response_starts_with") == "onboarding", req0
        assert req0.get("expected_response_ends_with") == "listed", req0
        assert req0.get("expected_response_equals") == "onboarding steps are listed", req0
        assert req0.get("expected_response_length_min") == 10, req0
        assert req0.get("expected_response_length_max") == 200, req0
        assert case0.get("prompt_input") == "Explain onboarding", case0
        assert case0.get("expected_response_contains") == ["onboarding", "steps"], case0
        assert case0.get("expected_response_not_contains") == ["secret"], case0
        assert case0.get("expected_response_regex") == r"onboarding\s+steps", case0
        assert case0.get("expected_response_starts_with") == "onboarding", case0
        assert case0.get("expected_response_ends_with") == "listed", case0
        assert case0.get("expected_response_equals") == "onboarding steps are listed", case0
        assert case0.get("expected_response_length_min") == 10, case0
        assert case0.get("expected_response_length_max") == 200, case0


def test_tool2_logging_does_not_depend_on_tool1_build_helpers():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool2-decouple-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "prompt-case",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["hello"],
                    "assertions": {},
                }
            ],
        }
        suite_path = root / "suite_tool2_decouple.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        with patch(
            "app.tool1_run_log.build_tool1_run_record_suite",
            side_effect=RuntimeError("tool1 helper should not be used by tool2 logger"),
        ):
            with patch("app.tool2_operator._default_prompt_executor", return_value="hello from tool2"):
                bundle = run_tool2_prompt_response_eval(
                    str(suite_path),
                    str(root / "out"),
                    "tool2_decouple",
                    project_root=root,
                )
        assert bundle["ok"] is True, bundle


def test_tool2_prompt_response_sample_suite_shape_validates():
    suite_path = PROJECT_ROOT / "system_tests" / "suites" / "tool2_prompt_demo" / "tool2_prompt_response_smoke.json"
    assert suite_path.is_file(), suite_path
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    suite = system_eval_core.validate_suite(raw)
    assert suite.get("suite_name") == "tool2_prompt_response_smoke", suite
    cases = suite.get("cases") or []
    assert len(cases) >= 1, suite
    for c in cases:
        assert c.get("lane") == "prompt_response", c
        assert isinstance(c.get("prompt_input"), str) and c.get("prompt_input").strip(), c
        expected = c.get("expected_response_contains")
        assert isinstance(expected, list) and len(expected) >= 1, c


def test_run_tool2_prompt_response_eval_artifact_failure_is_reported_and_logged():
    from app import tool2_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool2-artifact-fail-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "prompt-case",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "assertions": {},
                }
            ],
        }
        suite_path = root / "suite_tool2_artifact_fail.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        log_path = tool2_run_log.tool2_run_log_path(root)

        with patch("app.tool2_operator._default_prompt_executor", return_value="hello world"):
            with patch("app.tool2_operator.system_eval.write_result_artifacts", side_effect=OSError("disk full")):
                bundle = run_tool2_prompt_response_eval(
                    str(suite_path),
                    str(root / "out"),
                    "tool2_artifact_fail",
                    project_root=root,
                    default_timeout_seconds=37,
                )

        assert bundle["ok"] is False, bundle
        assert "Artifact write/read failed" in (bundle.get("error") or ""), bundle
        assert "tool2_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        assert "run_log_error" in bundle, bundle
        assert log_path.is_file(), "artifact failure should still write tool2 run log"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec.get("run_type") == "tool2_suite_run", rec
        assert rec.get("error"), rec
        cfg = rec.get("configuration") or {}
        assert cfg.get("timeout_seconds") == 37, rec


def test_run_tool2_prompt_response_eval_execution_exception_is_reported_and_logged():
    from app import tool2_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool2-execution-fail-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "prompt-case",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["world"],
                    "assertions": {},
                }
            ],
        }
        suite_path = root / "suite_tool2_execution_fail.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        log_path = tool2_run_log.tool2_run_log_path(root)

        with patch("app.tool2_operator.system_eval.execute_suite", side_effect=RuntimeError("boom")):
            bundle = run_tool2_prompt_response_eval(
                str(suite_path),
                str(root / "out"),
                "tool2_execution_fail",
                project_root=root,
                default_timeout_seconds=37,
            )

        assert bundle["ok"] is False, bundle
        assert "Suite execution failed:" in (bundle.get("error") or ""), bundle
        assert "tool2_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        assert "run_log_error" in bundle, bundle
        assert log_path.is_file(), "execution exception should still write tool2 run log"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec.get("run_type") == "tool2_suite_run", rec
        assert rec.get("error"), rec
        cfg = rec.get("configuration") or {}
        assert cfg.get("timeout_seconds") == 37, rec


def test_run_tool1_system_eval_operator_artifact_failure_is_reported_and_logged():
    from app import tool1_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "artifact-fail-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {},
                }
            ],
        }
        suite_path = root / "suite.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        log_path = tool1_run_log.tool1_run_log_path(root)

        class FakeAdapter:
            def run_case(self, case):
                _ = case
                return system_eval_core.AdapterResult(
                    ok=True, status_code=200, output_text="{}", latency_ms=1
                )

        with patch("app.system_eval_operator.system_eval.write_result_artifacts", side_effect=OSError("disk full")):
            bundle = run_tool1_system_eval_http(
                str(suite_path),
                str(root / "out"),
                "x",
                project_root=root,
                adapter=FakeAdapter(),
            )

        assert bundle["ok"] is False, bundle
        assert "Artifact write/read failed" in (bundle.get("error") or ""), bundle
        assert "run_log_error" in bundle, bundle
        assert log_path.is_file(), "artifact failure should still write suite_run log"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec["run_type"] == "suite_run", rec
        assert rec.get("error"), rec


def test_run_tool1_system_eval_operator_execution_exception_is_reported_and_logged():
    from app import tool1_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "execution-fail-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "http://fake.local/x",
                    "payload": {},
                    "assertions": {},
                }
            ],
        }
        suite_path = root / "suite.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        log_path = tool1_run_log.tool1_run_log_path(root)

        class FakeAdapter:
            def run_case(self, case):
                _ = case
                return system_eval_core.AdapterResult(
                    ok=True, status_code=200, output_text="{}", latency_ms=1
                )

        with patch("app.system_eval_operator.system_eval.execute_suite", side_effect=RuntimeError("boom")):
            bundle = run_tool1_system_eval_http(
                str(suite_path),
                str(root / "out"),
                "x",
                project_root=root,
                adapter=FakeAdapter(),
            )

        assert bundle["ok"] is False, bundle
        assert "Suite execution failed:" in (bundle.get("error") or ""), bundle
        assert "run_log_error" in bundle, bundle
        assert log_path.is_file(), "execution exception should still write suite_run log"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec["run_type"] == "suite_run", rec
        assert rec.get("error"), rec


def test_run_tool1_system_eval_operator_failure_bundle_contract():
    """
    Tool 1 closure guard: all operator failure paths should return a stable bundle shape
    so UI/render code never has to special-case error branches.
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # Case 1: missing suite file
        b_missing = run_tool1_system_eval_http(
            str(root / "missing.json"),
            str(root / "out"),
            "x",
            project_root=root,
            adapter=None,
        )
        for b in (b_missing,):
            assert b["ok"] is False, b
            assert isinstance(b.get("artifact_paths"), dict), b
            assert b.get("artifact_paths") == {}, b
            assert b.get("json_preview") == "", b
            assert b.get("markdown_preview") == "", b
            assert isinstance(b.get("error"), str) and b.get("error"), b
            assert "run_log_error" in b, b

        # Case 2: invalid suite JSON
        bad_suite = root / "bad.json"
        bad_suite.write_text("{ bad json", encoding="utf-8")
        b_bad = run_tool1_system_eval_http(
            str(bad_suite),
            str(root / "out"),
            "x",
            project_root=root,
            adapter=None,
        )
        assert b_bad["ok"] is False, b_bad
        assert isinstance(b_bad.get("artifact_paths"), dict), b_bad
        assert b_bad.get("artifact_paths") == {}, b_bad
        assert b_bad.get("json_preview") == "", b_bad
        assert b_bad.get("markdown_preview") == "", b_bad
        assert isinstance(b_bad.get("error"), str) and b_bad.get("error"), b_bad
        assert "run_log_error" in b_bad, b_bad


def test_run_tool2_prompt_response_eval_failure_bundle_contract():
    """
    Tool 2 closure guard: all operator failure paths should return a stable bundle shape
    so UI/render code never has to special-case error branches.
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # Case 1: missing suite file
        b_missing = run_tool2_prompt_response_eval(
            str(root / "missing_tool2.json"),
            str(root / "out"),
            "x",
            project_root=root,
            adapter=None,
        )
        for b in (b_missing,):
            assert b["ok"] is False, b
            assert isinstance(b.get("artifact_paths"), dict), b
            assert b.get("artifact_paths") == {}, b
            assert b.get("json_preview") == "", b
            assert b.get("markdown_preview") == "", b
            assert isinstance(b.get("error"), str) and b.get("error"), b
            assert "run_log_error" in b, b
            assert "tool2_runs.jsonl" in str(b.get("run_log_path") or ""), b

        # Case 2: invalid suite JSON
        bad_suite = root / "bad_tool2.json"
        bad_suite.write_text("{ bad json", encoding="utf-8")
        b_bad = run_tool2_prompt_response_eval(
            str(bad_suite),
            str(root / "out"),
            "x",
            project_root=root,
            adapter=None,
        )
        assert b_bad["ok"] is False, b_bad
        assert isinstance(b_bad.get("artifact_paths"), dict), b_bad
        assert b_bad.get("artifact_paths") == {}, b_bad
        assert b_bad.get("json_preview") == "", b_bad
        assert b_bad.get("markdown_preview") == "", b_bad
        assert isinstance(b_bad.get("error"), str) and b_bad.get("error"), b_bad
        assert "run_log_error" in b_bad, b_bad
        assert "tool2_runs.jsonl" in str(b_bad.get("run_log_path") or ""), b_bad

        # Case 3: lane rejection (non-prompt lane)
        lane_bad = root / "lane_bad_tool2.json"
        lane_bad.write_text(
            json.dumps(
                {
                    "suite_name": "lane-shape",
                    "target_name": "fake",
                    "cases": [
                        {
                            "name": "http-case",
                            "method": "GET",
                            "url": "http://fake.local/x",
                            "payload": {},
                            "assertions": {},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        b_lane = run_tool2_prompt_response_eval(
            str(lane_bad),
            str(root / "out"),
            "x",
            project_root=root,
        )
        assert b_lane["ok"] is False, b_lane
        assert isinstance(b_lane.get("artifact_paths"), dict), b_lane
        assert b_lane.get("artifact_paths") == {}, b_lane
        assert b_lane.get("json_preview") == "", b_lane
        assert b_lane.get("markdown_preview") == "", b_lane
        assert isinstance(b_lane.get("error"), str) and b_lane.get("error"), b_lane
        assert "run_log_error" in b_lane, b_lane
        assert "tool2_runs.jsonl" in str(b_lane.get("run_log_path") or ""), b_lane

        # Case 4: invalid timeout value
        suite_ok = root / "suite_tool2_ok.json"
        suite_ok.write_text(
            json.dumps(
                {
                    "suite_name": "timeout-shape",
                    "target_name": "fake",
                    "cases": [
                        {
                            "name": "prompt-case",
                            "lane": "prompt_response",
                            "prompt_input": "hello",
                            "expected_response_contains": ["hello"],
                            "assertions": {},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        b_timeout = run_tool2_prompt_response_eval(
            str(suite_ok),
            str(root / "out"),
            "x",
            project_root=root,
            default_timeout_seconds=0,
        )
        assert b_timeout["ok"] is False, b_timeout
        assert isinstance(b_timeout.get("artifact_paths"), dict), b_timeout
        assert b_timeout.get("artifact_paths") == {}, b_timeout
        assert b_timeout.get("json_preview") == "", b_timeout
        assert b_timeout.get("markdown_preview") == "", b_timeout
        assert isinstance(b_timeout.get("error"), str) and b_timeout.get("error"), b_timeout
        assert "run_log_error" in b_timeout, b_timeout
        assert "tool2_runs.jsonl" in str(b_timeout.get("run_log_path") or ""), b_timeout


def test_run_tool3_regression_eval_rejects_non_regression_lane():
    from app import tool3_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool3-bad-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "prompt-case",
                    "lane": "prompt_response",
                    "prompt_input": "hello",
                    "expected_response_contains": ["hello"],
                    "assertions": {},
                }
            ],
        }
        suite_path = root / "suite_tool3_bad.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        log_path = tool3_run_log.tool3_run_log_path(root)
        bundle = run_tool3_regression_eval(
            str(suite_path),
            str(root / "out"),
            "tool3_bad",
            project_root=root,
        )
        assert bundle["ok"] is False, bundle
        assert "lane='regression'" in str(bundle.get("error") or ""), bundle
        assert "tool3_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        assert bundle.get("run_log_error") in (None, ""), bundle
        assert log_path.is_file(), "lane rejection should still write tool3 run log record"


def test_run_tool3_regression_eval_scaffold_contract_on_regression_lane():
    from app import tool3_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool3-scaffold-suite",
            "target_name": "fake",
            "cases": [
                {
                    "name": "reg-case",
                    "lane": "regression",
                    "assertions": {},
                }
            ],
        }
        suite_path = root / "suite_tool3_scaffold.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        log_path = tool3_run_log.tool3_run_log_path(root)
        fake_proc = Mock(returncode=0, stdout="tool3 ok", stderr="")
        with patch("app.tool3_operator.subprocess.run", return_value=fake_proc):
            bundle = run_tool3_regression_eval(
                str(suite_path),
                str(root / "out"),
                "tool3_scaffold",
                project_root=root,
            )
        assert bundle["ok"] is True, bundle
        assert isinstance(bundle.get("artifact_paths"), dict), bundle
        assert Path(bundle["artifact_paths"]["json_path"]).is_file(), bundle
        assert Path(bundle["artifact_paths"]["markdown_path"]).is_file(), bundle
        assert "tool3 ok" in str(bundle.get("json_preview") or ""), bundle
        md_text = Path(bundle["artifact_paths"]["markdown_path"]).read_text(encoding="utf-8")
        assert "# Tool 3 Regression Summary" in md_text, md_text
        assert "- Total tests: 1" in md_text, md_text
        assert "- Passed: 1" in md_text, md_text
        assert "- Failed: 0" in md_text, md_text
        assert "# Tool 3 Regression Summary" in str(bundle.get("markdown_preview") or ""), bundle
        assert bundle.get("error") in (None, ""), bundle
        assert "tool3_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        assert bundle.get("run_log_error") in (None, ""), bundle
        assert log_path.is_file(), "tool3 success run should write tool3 run log record"
        result = bundle.get("result") or {}
        assert result.get("ok") is True, result
        assert result.get("executed_cases") == 1, result
        row = (result.get("cases") or [{}])[0]
        assert row.get("lane") == "regression", row
        assert row.get("ok") is True, row
        assert "tests/run_regression.py" in str(row.get("command") or ""), row


def test_run_tool3_regression_eval_does_not_depend_on_tool1_operator():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool3-no-tool1-coupling",
            "target_name": "fake",
            "cases": [{"name": "reg-case", "lane": "regression", "assertions": {}}],
        }
        suite_path = root / "suite_tool3_no_tool1.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        fake_proc = Mock(returncode=0, stdout="tool3 ok", stderr="")
        with patch(
            "app.system_eval_operator.run_tool1_system_eval_http",
            side_effect=RuntimeError("tool1 operator should not be called by tool3"),
        ):
            with patch("app.tool3_operator.subprocess.run", return_value=fake_proc):
                bundle = run_tool3_regression_eval(
                    str(suite_path),
                    str(root / "out"),
                    "tool3_no_tool1",
                    project_root=root,
                )
        assert bundle["ok"] is True, bundle
        assert "tool1 operator should not be called" not in str(bundle.get("error") or ""), bundle


def test_run_tool3_regression_eval_does_not_depend_on_tool2_operator():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool3-no-tool2-coupling",
            "target_name": "fake",
            "cases": [{"name": "reg-case", "lane": "regression", "assertions": {}}],
        }
        suite_path = root / "suite_tool3_no_tool2.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        fake_proc = Mock(returncode=0, stdout="tool3 ok", stderr="")
        with patch(
            "app.tool2_operator.run_tool2_prompt_response_eval",
            side_effect=RuntimeError("tool2 operator should not be called by tool3"),
        ):
            with patch("app.tool3_operator.subprocess.run", return_value=fake_proc):
                bundle = run_tool3_regression_eval(
                    str(suite_path),
                    str(root / "out"),
                    "tool3_no_tool2",
                    project_root=root,
                )
        assert bundle["ok"] is True, bundle
        assert "tool2 operator should not be called" not in str(bundle.get("error") or ""), bundle


def test_run_tool3_regression_eval_uses_default_command_when_override_blank():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool3-default-command-suite",
            "target_name": "fake",
            "cases": [{"name": "reg-case", "lane": "regression", "assertions": {}}],
        }
        suite_path = root / "suite_tool3_default_cmd.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        fake_proc = Mock(returncode=0, stdout="ok", stderr="")
        with patch("app.tool3_operator.subprocess.run", return_value=fake_proc) as mock_run:
            bundle = run_tool3_regression_eval(
                str(suite_path),
                str(root / "out"),
                "tool3_default_cmd",
                "",
                project_root=root,
            )
        assert bundle["ok"] is True, bundle
        called_cmd = list(mock_run.call_args.args[0])
        assert called_cmd[1:] == ["tests/run_regression.py"], called_cmd
        row = (bundle.get("result") or {}).get("cases", [{}])[0]
        assert "tests/run_regression.py" in str(row.get("command") or ""), row


def test_run_tool3_regression_eval_uses_command_override_when_provided():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool3-override-command-suite",
            "target_name": "fake",
            "cases": [{"name": "reg-case", "lane": "regression", "assertions": {}}],
        }
        suite_path = root / "suite_tool3_override_cmd.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        fake_proc = Mock(returncode=0, stdout="ok", stderr="")
        override = "python tests/run_regression.py --maxfail=1"
        with patch("app.tool3_operator.subprocess.run", return_value=fake_proc) as mock_run:
            bundle = run_tool3_regression_eval(
                str(suite_path),
                str(root / "out"),
                "tool3_override_cmd",
                override,
                project_root=root,
            )
        assert bundle["ok"] is True, bundle
        called_cmd = list(mock_run.call_args.args[0])
        assert called_cmd[0] == "python", called_cmd
        assert called_cmd[1:] == ["tests/run_regression.py", "--maxfail=1"], called_cmd
        row = (bundle.get("result") or {}).get("cases", [{}])[0]
        assert row.get("command") == override, row


def test_run_tool3_regression_eval_execution_failure_contract():
    from app import tool3_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool3-fail-suite",
            "target_name": "fake",
            "cases": [{"name": "reg-case", "lane": "regression", "assertions": {}}],
        }
        suite_path = root / "suite_tool3_fail.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        log_path = tool3_run_log.tool3_run_log_path(root)

        fake_proc = Mock(returncode=1, stdout="failed output", stderr="traceback")
        with patch("app.tool3_operator.subprocess.run", return_value=fake_proc):
            bundle = run_tool3_regression_eval(
                str(suite_path),
                str(root / "out"),
                "tool3_fail",
                project_root=root,
            )

        assert bundle["ok"] is False, bundle
        assert "exit code 1" in str(bundle.get("error") or ""), bundle
        assert bundle.get("artifact_paths") == {}, bundle
        assert "failed output" in str(bundle.get("json_preview") or ""), bundle
        assert "traceback" in str(bundle.get("markdown_preview") or ""), bundle
        assert "tool3_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        assert bundle.get("run_log_error") in (None, ""), bundle
        assert log_path.is_file(), "tool3 failed run should still write tool3 run log record"
        result = bundle.get("result") or {}
        assert result.get("ok") is False, result
        row = (result.get("cases") or [{}])[0]
        assert any("regression_command_failed: exit_code=1" in f for f in row.get("failures", [])), row


def test_run_tool3_regression_eval_artifact_failure_is_reported_and_logged():
    from app import tool3_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool3-artifact-fail-suite",
            "target_name": "fake",
            "cases": [{"name": "reg-case", "lane": "regression", "assertions": {}}],
        }
        suite_path = root / "suite_tool3_artifact_fail.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        log_path = tool3_run_log.tool3_run_log_path(root)

        fake_proc = Mock(returncode=0, stdout="ok output", stderr="")
        with patch("app.tool3_operator.subprocess.run", return_value=fake_proc):
            with patch("app.tool3_operator.system_eval.write_result_artifacts", side_effect=OSError("disk full")):
                bundle = run_tool3_regression_eval(
                    str(suite_path),
                    str(root / "out"),
                    "tool3_artifact_fail",
                    project_root=root,
                )

        assert bundle["ok"] is False, bundle
        assert "Artifact write/read failed" in str(bundle.get("error") or ""), bundle
        assert "tool3_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        assert bundle.get("run_log_error") in (None, ""), bundle
        assert log_path.is_file(), "artifact failure should still write tool3 run log record"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec.get("run_type") == "tool3_suite_run", rec
        assert rec.get("error"), rec


def test_run_tool3_regression_eval_command_invocation_failure_is_reported_and_logged():
    from app import tool3_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool3-invoke-fail-suite",
            "target_name": "fake",
            "cases": [{"name": "reg-case", "lane": "regression", "assertions": {}}],
        }
        suite_path = root / "suite_tool3_invoke_fail.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        log_path = tool3_run_log.tool3_run_log_path(root)

        with patch("app.tool3_operator.subprocess.run", side_effect=OSError("cannot spawn process")):
            bundle = run_tool3_regression_eval(
                str(suite_path),
                str(root / "out"),
                "tool3_invoke_fail",
                project_root=root,
            )

        assert bundle["ok"] is False, bundle
        assert "Regression command invocation failed" in str(bundle.get("error") or ""), bundle
        assert "tool3_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        assert bundle.get("run_log_error") in (None, ""), bundle
        assert log_path.is_file(), "invocation failure should still write tool3 run log record"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec.get("run_type") == "tool3_suite_run", rec
        assert rec.get("error"), rec


def test_run_tool3_regression_eval_command_timeout_is_reported_and_logged():
    from app import tool3_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        suite_data = {
            "suite_name": "tool3-timeout-suite",
            "target_name": "fake",
            "cases": [{"name": "reg-case", "lane": "regression", "assertions": {}}],
        }
        suite_path = root / "suite_tool3_timeout.json"
        suite_path.write_text(json.dumps(suite_data), encoding="utf-8")
        log_path = tool3_run_log.tool3_run_log_path(root)

        timeout_exc = subprocess.TimeoutExpired(cmd=["python", "tests/run_regression.py"], timeout=1)
        with patch("app.tool3_operator.subprocess.run", side_effect=timeout_exc):
            bundle = run_tool3_regression_eval(
                str(suite_path),
                str(root / "out"),
                "tool3_timeout",
                project_root=root,
            )

        assert bundle["ok"] is False, bundle
        assert "timed out" in str(bundle.get("error") or "").lower(), bundle
        assert "tool3_runs.jsonl" in str(bundle.get("run_log_path") or ""), bundle
        assert bundle.get("run_log_error") in (None, ""), bundle
        assert log_path.is_file(), "timeout should still write tool3 run log record"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec.get("run_type") == "tool3_suite_run", rec
        assert rec.get("error"), rec


def test_run_tool3_regression_eval_failure_bundle_contract():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # Case 1: missing suite file
        b_missing = run_tool3_regression_eval(
            str(root / "missing_tool3.json"),
            str(root / "out"),
            "x",
            project_root=root,
        )
        for b in (b_missing,):
            assert b["ok"] is False, b
            assert isinstance(b.get("artifact_paths"), dict), b
            assert b.get("artifact_paths") == {}, b
            assert b.get("json_preview") == "", b
            assert b.get("markdown_preview") == "", b
            assert isinstance(b.get("error"), str) and b.get("error"), b
            assert "run_log_error" in b, b
            assert "tool3_runs.jsonl" in str(b.get("run_log_path") or ""), b

        # Case 2: invalid suite JSON
        bad_suite = root / "bad_tool3.json"
        bad_suite.write_text("{ bad json", encoding="utf-8")
        b_bad = run_tool3_regression_eval(
            str(bad_suite),
            str(root / "out"),
            "x",
            project_root=root,
        )
        assert b_bad["ok"] is False, b_bad
        assert isinstance(b_bad.get("artifact_paths"), dict), b_bad
        assert b_bad.get("artifact_paths") == {}, b_bad
        assert b_bad.get("json_preview") == "", b_bad
        assert b_bad.get("markdown_preview") == "", b_bad
        assert isinstance(b_bad.get("error"), str) and b_bad.get("error"), b_bad
        assert "run_log_error" in b_bad, b_bad
        assert "tool3_runs.jsonl" in str(b_bad.get("run_log_path") or ""), b_bad

        # Case 3: lane rejection
        lane_bad = root / "lane_bad_tool3.json"
        lane_bad.write_text(
            json.dumps(
                {
                    "suite_name": "lane-shape",
                    "target_name": "fake",
                    "cases": [
                        {
                            "name": "prompt-case",
                            "lane": "prompt_response",
                            "assertions": {},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        b_lane = run_tool3_regression_eval(
            str(lane_bad),
            str(root / "out"),
            "x",
            project_root=root,
        )
        assert b_lane["ok"] is False, b_lane
        assert isinstance(b_lane.get("artifact_paths"), dict), b_lane
        assert b_lane.get("artifact_paths") == {}, b_lane
        assert b_lane.get("json_preview") == "", b_lane
        assert b_lane.get("markdown_preview") == "", b_lane
        assert isinstance(b_lane.get("error"), str) and b_lane.get("error"), b_lane
        assert "run_log_error" in b_lane, b_lane
        assert "tool3_runs.jsonl" in str(b_lane.get("run_log_path") or ""), b_lane

        # Case 4: command invocation failure
        ok_suite = root / "suite_tool3_ok.json"
        ok_suite.write_text(
            json.dumps(
                {
                    "suite_name": "invoke-shape",
                    "target_name": "fake",
                    "cases": [
                        {
                            "name": "reg-case",
                            "lane": "regression",
                            "assertions": {},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with patch("app.tool3_operator.subprocess.run", side_effect=OSError("cannot spawn process")):
            b_invoke = run_tool3_regression_eval(
                str(ok_suite),
                str(root / "out"),
                "x",
                project_root=root,
            )
        assert b_invoke["ok"] is False, b_invoke
        assert isinstance(b_invoke.get("artifact_paths"), dict), b_invoke
        assert b_invoke.get("artifact_paths") == {}, b_invoke
        assert b_invoke.get("json_preview") == "", b_invoke
        assert b_invoke.get("markdown_preview") == "", b_invoke
        assert isinstance(b_invoke.get("error"), str) and b_invoke.get("error"), b_invoke
        assert "run_log_error" in b_invoke, b_invoke
        assert "tool3_runs.jsonl" in str(b_invoke.get("run_log_path") or ""), b_invoke

        # Case 5: command timeout
        with patch(
            "app.tool3_operator.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["python", "tests/run_regression.py"], timeout=1),
        ):
            b_timeout = run_tool3_regression_eval(
                str(ok_suite),
                str(root / "out"),
                "x",
                project_root=root,
            )
        assert b_timeout["ok"] is False, b_timeout
        assert isinstance(b_timeout.get("artifact_paths"), dict), b_timeout
        assert b_timeout.get("artifact_paths") == {}, b_timeout
        assert b_timeout.get("json_preview") == "", b_timeout
        assert b_timeout.get("markdown_preview") == "", b_timeout
        assert isinstance(b_timeout.get("error"), str) and b_timeout.get("error"), b_timeout
        assert "run_log_error" in b_timeout, b_timeout
        assert "tool3_runs.jsonl" in str(b_timeout.get("run_log_path") or ""), b_timeout


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


def test_run_tool1_system_eval_operator_invalid_json_logs_failure_record():
    from app import tool1_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        log_path = tool1_run_log.tool1_run_log_path(root)
        bad_suite = root / "bad.json"
        bad_suite.write_text("{ not valid json", encoding="utf-8")

        bundle = run_tool1_system_eval_http(
            str(bad_suite),
            str(root / "out"),
            "bad_json",
            project_root=root,
            adapter=None,
        )
        assert bundle.get("ok") is False, bundle
        assert bundle.get("error"), bundle
        assert log_path.is_file(), "invalid suite json should still write suite_run log"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec.get("run_type") == "suite_run", rec
        assert rec.get("error"), rec
        assert "run_log_error" in bundle, bundle
        assert bundle.get("run_log_error") in (None, ""), bundle


def test_tool1_run_log_single_request_redacts_sensitive_fields():
    from app import tool1_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        log_path = tool1_run_log.tool1_run_log_path(root)
        prep = {
            "suite_dict": {
                "suite_name": "single-request",
                "target_name": "operator",
                "cases": [
                    {
                        "name": "single_request_case",
                        "method": "GET",
                        "url": "https://example.test?token=abc&q=ok",
                        "headers": {
                            "Authorization": "Bearer sk-secret",
                            "X-Api-Key": "key-123",
                            "Content-Type": "application/json",
                        },
                        "payload": {},
                        "assertions": {},
                    }
                ],
            }
        }
        snap = {
            "url": "https://example.test?token=abc&q=ok",
            "headers_json_raw": '{"Authorization":"Bearer sk-secret","X-Api-Key":"key-123"}',
            "query_params_json_raw": '{"q":"ok","token":"abc"}',
            "bearer_token": "sk-secret",
            "basic_password": "pw",
            "api_key_value": "key-123",
        }
        le = tool1_run_log.try_log_single_request_run(
            prep=prep,
            result=None,
            artifact_paths={},
            error="prepare failed",
            timeout_seconds=20,
            output_dir_rel="logs/system_eval",
            auth_mode_internal="bearer",
            query_params_text='{"token":"abc","q":"ok"}',
            input_snapshot=snap,
            project_root=root,
        )
        assert le is None, le
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        req0 = rec["requests"][0]
        assert req0["headers"]["Authorization"] == "[REDACTED]", req0
        assert req0["headers"]["X-Api-Key"] == "[REDACTED]", req0
        assert "token=%5BREDACTED%5D" in req0["url"], req0
        assert rec["request_input_snapshot"]["bearer_token"] == "[REDACTED]", rec
        assert rec["request_input_snapshot"]["basic_password"] == "[REDACTED]", rec
        assert rec["request_input_snapshot"]["api_key_value"] == "[REDACTED]", rec
        assert "token=%5BREDACTED%5D" in rec["request_input_snapshot"]["url"], rec
        assert '"token": "[REDACTED]"' in (rec.get("query_params_raw_json") or ""), rec


def test_tool1_run_log_single_request_redacts_sensitive_fields_in_malformed_raw_text():
    from app import tool1_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        log_path = tool1_run_log.tool1_run_log_path(root)
        snap = {
            "url": "https://example.test",
            "headers_json_raw": 'Authorization: Bearer sk-secret malformed',
            "query_params_json_raw": "token=abc123&x=1",
            "bearer_token": "sk-secret",
        }
        le = tool1_run_log.try_log_single_request_run(
            prep=None,
            result=None,
            artifact_paths={},
            error="prepare failed token=abc123",
            timeout_seconds=20,
            output_dir_rel="logs/system_eval",
            auth_mode_internal="bearer",
            query_params_text="token=abc123&x=1",
            input_snapshot=snap,
            project_root=root,
        )
        assert le is None, le
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        hs = rec["request_input_snapshot"]["headers_json_raw"]
        qp = rec["request_input_snapshot"]["query_params_json_raw"]
        assert "sk-secret" not in hs and "[REDACTED]" in hs, rec
        assert "abc123" not in qp and "[REDACTED]" in qp, rec
        qpr = str(rec.get("query_params_raw_json") or "")
        assert "abc123" not in qpr and "[REDACTED]" in qpr, rec


def test_tool1_run_log_suite_redacts_sensitive_request_fields():
    from app import tool1_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        log_path = tool1_run_log.tool1_run_log_path(root)
        suite = {
            "suite_name": "suite-redaction-test",
            "target_name": "t",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "https://example.test/path?token=abc&q=ok",
                    "headers": {
                        "Authorization": "Bearer sk-secret",
                        "X-Api-Key": "key-123",
                        "Accept": "application/json",
                    },
                    "payload": {},
                    "assertions": {},
                }
            ],
        }
        le = tool1_run_log.try_log_suite_run(
            suite_path="system_tests/suites/fake.json",
            output_dir="logs/system_eval",
            file_stem="x",
            fail_fast=False,
            default_timeout_seconds=20,
            suite=suite,
            result=None,
            artifact_paths={},
            error="mock error",
            project_root=root,
        )
        assert le is None, le
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        req0 = rec["requests"][0]
        assert req0["headers"]["Authorization"] == "[REDACTED]", req0
        assert req0["headers"]["X-Api-Key"] == "[REDACTED]", req0
        assert req0["headers"]["Accept"] == "application/json", req0
        assert "token=%5BREDACTED%5D" in req0["url"], req0


def test_tool1_run_log_redacts_sensitive_tokens_in_error_and_summary_text():
    from app import tool1_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        log_path = tool1_run_log.tool1_run_log_path(root)
        suite = {
            "suite_name": "suite-text-redaction-test",
            "target_name": "t",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "https://example.test/path?token=abc",
                    "headers": {},
                    "payload": {},
                    "assertions": {},
                }
            ],
        }
        err = "Request failed: Authorization: Bearer sk_live_secret token=abc123"
        le = tool1_run_log.try_log_suite_run(
            suite_path="system_tests/suites/fake.json",
            output_dir="logs/system_eval",
            file_stem="x",
            fail_fast=False,
            default_timeout_seconds=20,
            suite=suite,
            result=None,
            artifact_paths={},
            error=err,
            project_root=root,
        )
        assert le is None, le
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        rec_err = str(rec.get("error") or "")
        rec_summary = str(rec.get("summary") or "")
        assert "sk_live_secret" not in rec_err, rec
        assert "abc123" not in rec_err, rec
        assert "[REDACTED]" in rec_err, rec
        assert "sk_live_secret" not in rec_summary, rec
        assert "abc123" not in rec_summary, rec


def test_tool1_run_log_redacts_sensitive_tokens_in_failure_lines():
    from app import tool1_run_log

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        log_path = tool1_run_log.tool1_run_log_path(root)
        suite = {
            "suite_name": "suite-failure-redaction-test",
            "target_name": "t",
            "cases": [
                {
                    "name": "c1",
                    "method": "GET",
                    "url": "https://example.test/path",
                    "headers": {},
                    "payload": {},
                    "assertions": {},
                }
            ],
        }
        result = {
            "ok": False,
            "executed_cases": 1,
            "passed_cases": 0,
            "failed_cases": 1,
            "elapsed_seconds": 0.2,
            "ran_at_utc": "2026-01-01T00:00:00Z",
            "cases": [
                {
                    "name": "c1",
                    "ok": False,
                    "status_code": 500,
                    "latency_ms": 10,
                    "failures": [
                        "Request failed token=abc123 and Authorization: Bearer sk_live_secret"
                    ],
                    "response_headers": {},
                    "output_preview": "",
                    "output_full": "",
                }
            ],
        }
        le = tool1_run_log.try_log_suite_run(
            suite_path="system_tests/suites/fake.json",
            output_dir="logs/system_eval",
            file_stem="x",
            fail_fast=False,
            default_timeout_seconds=20,
            suite=suite,
            result=result,
            artifact_paths={},
            error=None,
            project_root=root,
        )
        assert le is None, le
        rec = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        fail0 = str(rec["cases_outcome"][0]["failures"][0])
        assert "abc123" not in fail0, rec
        assert "sk_live_secret" not in fail0, rec
        assert "[REDACTED]" in fail0, rec


def test_tool1_run_log_redaction_does_not_mutate_input_record():
    from app import tool1_run_log

    rec = {
        "run_type": "single_request",
        "requests": [
            {
                "url": "https://example.test?token=abc",
                "headers": {"Authorization": "Bearer sk-secret", "X-Api-Key": "key-123"},
            }
        ],
        "request_input_snapshot": {"bearer_token": "sk-secret", "url": "https://example.test?token=abc"},
        "query_params_raw_json": '{"token":"abc"}',
        "error": "Authorization: Bearer sk-secret token=abc",
        "summary": "Authorization: Bearer sk-secret token=abc",
        "cases_outcome": [],
    }
    rec_before = json.loads(json.dumps(rec))
    _ = tool1_run_log._redact_tool1_record(rec)
    assert rec == rec_before, rec


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
    assert result["cases"][0]["lane"] == "smoke", result["cases"][0]
    assert result["cases"][0]["method"] == "POST", result["cases"][0]
    assert result["cases"][0]["expected_status_code"] == 200, result["cases"][0]
    assert result["cases"][0]["request_headers"] == {}, result["cases"][0]
    assert result["cases"][0]["request_body"] == {"input": "hello"}, result["cases"][0]
    assert result["cases"][0]["error_message"] is None, result["cases"][0]
    assert "request_method" not in result["cases"][0], result["cases"][0]
    assert result["cases"][0]["response_summary"] == "service healthy", result["cases"][0]


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
    assert isinstance(result["cases"][0].get("error_message"), str), result["cases"][0]
    assert "missing required token" in result["cases"][0]["error_message"], result["cases"][0]


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


def test_system_eval_default_status_check_200_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "default-status-200-pass",
            "target_name": "fake",
            "cases": [
                {"name": "default_status_200", "method": "GET", "url": "https://example.com", "payload": {}, "assertions": {}}
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
    assert result["ok"] is True, result


def test_system_eval_default_status_check_201_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "default-status-201-pass",
            "target_name": "fake",
            "cases": [
                {"name": "default_status_201", "method": "GET", "url": "https://example.com", "payload": {}, "assertions": {}}
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=201, output_text="created", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_default_status_check_401_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "default-status-401-fail",
            "target_name": "fake",
            "cases": [
                {"name": "default_status_401", "method": "GET", "url": "https://example.com", "payload": {}, "assertions": {}}
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=401, output_text="unauthorized", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("default status check failed: expected 2xx, got 401" in f for f in result["cases"][0]["failures"]), (
        result["cases"][0]
    )


def test_system_eval_default_status_check_500_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "default-status-500-fail",
            "target_name": "fake",
            "cases": [
                {"name": "default_status_500", "method": "GET", "url": "https://example.com", "payload": {}, "assertions": {}}
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=500, output_text="server-error", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("default status check failed: expected 2xx, got 500" in f for f in result["cases"][0]["failures"]), (
        result["cases"][0]
    )


def test_system_eval_case_expected_status_exact_match_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-status-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_status_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_status": 200,
                    "assertions": {},
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
    assert result["ok"] is True, result


def test_system_eval_case_expected_status_exact_mismatch_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-status-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_status_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_status": 200,
                    "assertions": {},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=500, output_text="err", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_status mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_status_in_membership_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-status-in-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_status_in_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_status_in": [200, 201, 202],
                    "assertions": {},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=201, output_text="created", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_case_expected_status_in_membership_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-status-in-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_status_in_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_status_in": [200, 201, 202],
                    "assertions": {},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=404, output_text="nf", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_status_in mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_status_not_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-status-not-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_status_not_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_status_not": [400, 401, 500],
                    "assertions": {},
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
    assert result["ok"] is True, result


def test_system_eval_case_expected_status_not_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-status-not-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_status_not_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_status_not": [400, 401, 500],
                    "assertions": {},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=500, output_text="err", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_status_not mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_status_fields_absent_behavior_unchanged():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-status-absent",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_status_absent",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_contains": "ok"},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=503, output_text="ok", latency_ms=1, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert any("default status check failed: expected 2xx, got 503" in f for f in row["failures"]), row


def test_system_eval_case_expected_status_and_expected_status_in_both_present_rejected():
    try:
        system_eval_core.validate_suite(
            {
                "suite_name": "case-expected-status-both",
                "target_name": "fake",
                "cases": [
                    {
                        "name": "case_expected_status_both",
                        "method": "GET",
                        "url": "https://example.com",
                        "payload": {},
                        "expected_status": 200,
                        "expected_status_in": [200, 201],
                        "assertions": {},
                    }
                ],
            }
        )
        assert False, "expected ValueError for both expected_status and expected_status_in"
    except ValueError as exc:
        assert "cannot set both 'expected_status' and 'expected_status_in'" in str(exc), str(exc)


def test_system_eval_case_expected_headers_exact_match_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-headers-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_headers_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_headers": {"content-type": "application/json"},
                    "assertions": {},
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


def test_system_eval_case_expected_headers_missing_required_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-headers-missing",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_headers_missing",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_headers": {"x-request-id": "abc123"},
                    "assertions": {},
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
    assert any("expected_headers missing header" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_headers_mismatch_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-headers-mismatch",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_headers_mismatch",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_headers": {"content-type": "application/json"},
                    "assertions": {},
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
                response_headers={"content-type": "text/plain"},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_headers mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_headers_name_case_insensitive_match():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-headers-case-insensitive",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_headers_case_insensitive",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_headers": {"X-REQUEST-ID": "abc123"},
                    "assertions": {},
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
                response_headers={"x-request-id": " abc123 "},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_case_expected_headers_absent_behavior_unchanged():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-headers-absent",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_headers_absent",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_contains": "ok"},
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
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert all("expected_headers" not in f for f in row["failures"]), row


def test_system_eval_case_expected_headers_contains_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-headers-contains-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_headers_contains_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_headers_contains": {"content-type": "application/json"},
                    "assertions": {},
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


def test_system_eval_case_expected_headers_contains_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-headers-contains-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_headers_contains_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_headers_contains": {"content-type": "application/json"},
                    "assertions": {},
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
                response_headers={"Content-Type": "text/plain"},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_headers_contains mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_header_exists_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-header-exists-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_header_exists_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_header_exists": ["Content-Type", "X-Request-Id"],
                    "assertions": {},
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
                response_headers={"content-type": "application/json", "x-request-id": "abc123"},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_case_expected_header_exists_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-header-exists-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_header_exists_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_header_exists": ["Content-Type", "X-Request-Id"],
                    "assertions": {},
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
                response_headers={"content-type": "application/json"},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_header_exists missing header" in f for f in result["cases"][0]["failures"]), (
        result["cases"][0]
    )


def test_system_eval_case_expected_json_exact_path_value_match_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_json": {"status": "ok", "data.id": 123},
                    "assertions": {},
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
                output_text='{"status":"ok","data":{"id":123}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_case_expected_json_missing_path_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-missing-path",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_missing_path",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_json": {"data.id": 123},
                    "assertions": {},
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
                output_text='{"status":"ok","data":{}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_json missing path" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_json_mismatched_value_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-mismatch",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_mismatch",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_json": {"status": "ok", "data.id": 123},
                    "assertions": {},
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
                output_text='{"status":"ok","data":{"id":999}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_json mismatch" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_json_non_json_response_fails_clearly():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-non-json",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_non_json",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_json": {"status": "ok"},
                    "assertions": {},
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
                output_text="not-json",
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_json invalid json" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_json_absent_behavior_unchanged():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-absent",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_absent",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_contains": "ok"},
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
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert all("expected_json" not in f for f in row["failures"]), row


def test_system_eval_case_expected_json_exists_existing_path_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-exists-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_exists_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_json_exists": ["data.id", "user.profile", "meta.timestamp"],
                    "assertions": {},
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
                output_text='{"data":{"id":123},"user":{"profile":{"name":"x"}},"meta":{"timestamp":"2026-01-01T00:00:00Z"}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_case_expected_json_exists_missing_path_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-exists-missing",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_exists_missing",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_json_exists": ["data.id", "meta.timestamp"],
                    "assertions": {},
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
                output_text='{"data":{"id":123},"meta":{}}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_json_exists missing path" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_json_exists_non_json_response_fails_clearly():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-exists-non-json",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_exists_non_json",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_json_exists": ["data.id"],
                    "assertions": {},
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
                output_text="plain-text",
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_json_exists invalid json" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_json_exists_absent_behavior_unchanged():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-exists-absent",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_exists_absent",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"body_contains": "ok"},
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
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert all("expected_json_exists" not in f for f in row["failures"]), row


def test_system_eval_case_expected_json_values_pass_correct_value():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-values-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_values_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_json_values": {"status": "ok", "count": 3},
                    "assertions": {},
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
                output_text='{"status":"ok","count":3,"extra":"x"}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_case_expected_json_values_fail_wrong_value():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-values-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_values_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_json_values": {"status": "ok", "count": 3},
                    "assertions": {},
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
                output_text='{"status":"ok","count":999}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("json_value_mismatch: count" in f for f in result["cases"][0]["failures"]), result["cases"][0]


def test_system_eval_case_expected_json_absent_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-absent-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_absent_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_json_absent": ["secret", "internal_debug"],
                    "assertions": {},
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
                output_text='{"status":"ok","count":3}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_case_expected_json_absent_fails_when_present():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-json-absent-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_json_absent_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_json_absent": ["secret"],
                    "assertions": {},
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
                output_text='{"status":"ok","secret":"token"}',
                latency_ms=1,
                response_headers={},
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any(
        "json_key_present_but_expected_absent: secret" in f for f in result["cases"][0]["failures"]
    ), result["cases"][0]


def test_system_eval_case_expected_body_not_empty_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-body-not-empty-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_body_not_empty_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_body_not_empty": True,
                    "assertions": {},
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
    assert result["ok"] is True, result


def test_system_eval_case_expected_body_not_empty_fails_on_empty():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-body-not-empty-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_body_not_empty_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_body_not_empty": True,
                    "assertions": {},
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
    assert any("expected_body_not_empty failed" in f for f in result["cases"][0]["failures"]), (
        result["cases"][0]
    )


def test_system_eval_case_expected_body_size_bytes_max_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-body-size-bytes-max-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_body_size_bytes_max_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_body_size_bytes_max": 5,
                    "assertions": {},
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


def test_system_eval_case_expected_body_size_bytes_max_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "case-expected-body-size-bytes-max-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "case_expected_body_size_bytes_max_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_body_size_bytes_max": 4,
                    "assertions": {},
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
    assert any("expected_body_size_bytes_max exceeded" in f for f in result["cases"][0]["failures"]), (
        result["cases"][0]
    )


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


def test_system_eval_max_duration_ms_pass_under_threshold():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "max-duration-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "max_duration_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "max_duration_ms": 800,
                    "assertions": {"expected_status": 200},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=120, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert row["latency_ms"] == 120, row
    assert row["max_duration_ms"] == 800, row


def test_system_eval_max_duration_ms_fail_over_threshold():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "max-duration-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "max_duration_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "max_duration_ms": 800,
                    "assertions": {"expected_status": 200},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=1001, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    row = result["cases"][0]
    assert row["max_duration_ms"] == 800, row
    joined = " ".join(row["failures"])
    assert "max_duration_ms exceeded" in joined, row
    assert "800" in joined and "1001" in joined, row


def test_system_eval_no_max_duration_ms_keeps_behavior():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "max-duration-absent",
            "target_name": "fake",
            "cases": [
                {
                    "name": "no_max_duration",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"expected_status": 200},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=9999, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result
    row = result["cases"][0]
    assert "max_duration_ms" not in row, row


def test_system_eval_expected_latency_ms_max_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "expected-latency-ms-max-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "expected_latency_ms_max_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_latency_ms_max": 150,
                    "assertions": {},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=150, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_expected_latency_ms_max_fail():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "expected-latency-ms-max-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "expected_latency_ms_max_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_latency_ms_max": 150,
                    "assertions": {},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=151, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_latency_ms_max exceeded" in f for f in result["cases"][0]["failures"]), (
        result["cases"][0]
    )


def test_system_eval_expected_response_time_ms_range_pass():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "expected-response-time-ms-range-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "expected_response_time_ms_range_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_response_time_ms_range": [100, 200],
                    "assertions": {},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=150, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result


def test_system_eval_expected_response_time_ms_range_fail():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "expected-response-time-ms-range-fail",
            "target_name": "fake",
            "cases": [
                {
                    "name": "expected_response_time_ms_range_fail",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "expected_response_time_ms_range": [100, 200],
                    "assertions": {},
                }
            ],
        }
    )

    class A:
        def run_case(self, case):
            _ = case
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=250, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    assert any("expected_response_time_ms_range mismatch" in f for f in result["cases"][0]["failures"]), (
        result["cases"][0]
    )


def test_system_eval_retries_absent_behavior_unchanged():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "retry-absent",
            "target_name": "fake",
            "cases": [
                {
                    "name": "retry_absent",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "assertions": {"expected_status": 200},
                }
            ],
        }
    )

    class A:
        def __init__(self):
            self.calls = 0

        def run_case(self, case):
            _ = case
            self.calls += 1
            return system_eval_core.AdapterResult(
                ok=False,
                status_code=None,
                output_text="",
                latency_ms=5,
                error="RequestException: timeout",
                response_headers={},
            )

    adapter = A()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert result["ok"] is False, result
    assert adapter.calls == 1, adapter.calls
    row = result["cases"][0]
    assert "retry_attempts_total" not in row, row
    assert any("RequestException" in f for f in row["failures"]), row


def test_system_eval_retries_transient_then_success_passes():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "retry-then-pass",
            "target_name": "fake",
            "cases": [
                {
                    "name": "retry_then_pass",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "retries": 2,
                    "retry_delay_ms": 0,
                    "assertions": {"expected_status": 200},
                }
            ],
        }
    )

    class A:
        def __init__(self):
            self.calls = 0

        def run_case(self, case):
            _ = case
            self.calls += 1
            if self.calls == 1:
                return system_eval_core.AdapterResult(
                    ok=False,
                    status_code=None,
                    output_text="",
                    latency_ms=7,
                    error="RequestException: temporary network",
                    response_headers={},
                )
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok", latency_ms=9, response_headers={}
            )

    adapter = A()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert result["ok"] is True, result
    assert adapter.calls == 2, adapter.calls
    row = result["cases"][0]
    assert row["retry_attempts_total"] == 2, row
    assert len(row["retry_attempts"]) == 2, row
    assert row["retry_attempts"][0]["transient_failure"] is True, row
    assert row["retry_attempts"][1]["transient_failure"] is False, row


def test_system_eval_retries_exhausted_transient_fails():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "retry-exhausted",
            "target_name": "fake",
            "cases": [
                {
                    "name": "retry_exhausted",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "retries": 2,
                    "retry_delay_ms": 0,
                    "assertions": {"expected_status": 200},
                }
            ],
        }
    )

    class A:
        def __init__(self):
            self.calls = 0

        def run_case(self, case):
            _ = case
            self.calls += 1
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=503,
                output_text="service unavailable",
                latency_ms=11,
                response_headers={},
            )

    adapter = A()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert result["ok"] is False, result
    assert adapter.calls == 3, adapter.calls
    row = result["cases"][0]
    assert row["retry_attempts_total"] == 3, row
    assert all(a["transient_failure"] is True for a in row["retry_attempts"]), row
    assert any("retries exhausted after transient failures" in f for f in row["failures"]), row


def test_system_eval_retries_does_not_retry_4xx():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "retry-no-4xx",
            "target_name": "fake",
            "cases": [
                {
                    "name": "retry_no_4xx",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "retries": 3,
                    "retry_delay_ms": 0,
                    "assertions": {"expected_status": 200},
                }
            ],
        }
    )

    class A:
        def __init__(self):
            self.calls = 0

        def run_case(self, case):
            _ = case
            self.calls += 1
            return system_eval_core.AdapterResult(
                ok=True,
                status_code=404,
                output_text="not found",
                latency_ms=3,
                response_headers={},
            )

    adapter = A()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert result["ok"] is False, result
    assert adapter.calls == 1, adapter.calls
    row = result["cases"][0]
    assert row["retry_attempts_total"] == 1, row
    assert row["retry_attempts"][0]["transient_failure"] is False, row
    assert any("expected_status=200" in f for f in row["failures"]), row


def test_system_eval_retries_does_not_retry_assertion_failure():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "retry-no-assertion-retry",
            "target_name": "fake",
            "cases": [
                {
                    "name": "retry_no_assertion_retry",
                    "method": "GET",
                    "url": "https://example.com",
                    "payload": {},
                    "retries": 2,
                    "retry_delay_ms": 0,
                    "assertions": {"body_contains": "must-have-token"},
                }
            ],
        }
    )

    class A:
        def __init__(self):
            self.calls = 0

        def run_case(self, case):
            _ = case
            self.calls += 1
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text="ok-but-missing", latency_ms=4, response_headers={}
            )

    adapter = A()
    result = system_eval_core.execute_suite(suite, adapter=adapter)
    assert result["ok"] is False, result
    assert adapter.calls == 1, adapter.calls
    row = result["cases"][0]
    assert row["retry_attempts_total"] == 1, row
    assert row["retry_attempts"][0]["transient_failure"] is False, row
    assert any("body did not contain substring" in f for f in row["failures"]), row


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
    sr = result["cases"][0].get("steps")
    assert sr is not None and len(sr) == 2, sr
    assert sr[0]["step"] == "login" and sr[0]["status"] == "PASS", sr[0]
    assert sr[0]["url"] == "https://example.com/login" and sr[0]["latency_ms"] == 10, sr[0]
    assert "reason" not in sr[0], sr[0]
    assert sr[1]["step"] == "get_user" and sr[1]["status"] == "PASS", sr[1]
    assert sr[1]["url"] == "https://example.com/users/ab" and sr[1]["latency_ms"] == 20, sr[1]
    assert "step_results" not in result["cases"][0], result["cases"][0]


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
    sr = result["cases"][0].get("steps")
    assert sr is not None and len(sr) == 2, sr
    assert sr[0]["status"] == "PASS" and sr[0]["step"] == "login", sr[0]
    assert sr[1]["status"] == "FAIL" and sr[1]["step"] == "get_user", sr[1]
    assert sr[1].get("reason"), sr[1]
    assert "body_json_path" in sr[1]["reason"] or "missing" in sr[1]["reason"].lower(), sr[1]["reason"]
    assert "step_results" not in result["cases"][0], result["cases"][0]


def test_write_result_artifacts_filename_includes_utc_timestamp_from_ran_at():
    result = {
        "suite_name": "stem-ts",
        "target_name": "t",
        "executed_cases": 0,
        "passed_cases": 0,
        "failed_cases": 0,
        "ok": True,
        "elapsed_seconds": 0.0,
        "ran_at_utc": "2026-04-25T12:34:56.789012+00:00",
        "cases": [],
    }
    with tempfile.TemporaryDirectory() as td:
        paths = system_eval_core.write_result_artifacts(result, td, file_stem="my_run")
        json_path = Path(paths["json_path"])
        md_path = Path(paths["markdown_path"])
    assert json_path.name == "my_run_2026-04-25_123456.json", json_path.name
    assert md_path.name == "my_run_2026-04-25_123456.md", md_path.name


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
    assert "Run at (UTC):" in md_text, md_text
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


def test_system_eval_steps_two_step_output_contains_single_request_fields():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "steps-fields",
            "target_name": "fake",
            "cases": [
                {
                    "name": "scenario_steps_fields",
                    "assertions": {},
                    "steps": [
                        {
                            "name": "s1",
                            "method": "GET",
                            "url": "https://example.com/one",
                            "payload": {},
                            "extract": {"id": "$.data.id", "token": "$.token"},
                            "status_code": 200,
                        },
                        {
                            "name": "s2",
                            "method": "POST",
                            "url": "https://example.com/two/{{id}}",
                            "headers": {
                                "Content-Type": "application/json",
                                "Authorization": "Bearer {{token}}",
                                "X-Missing": "{{never_set}}",
                            },
                            "payload": {"query": "what is an api", "id": "{{id}}"},
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
                body = '{"token":"tok-123","data":{"id":"42"}}'
            else:
                body = '{"ok":true,"n":2}'
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text=body, latency_ms=5 + self.n, response_headers={"Content-Type": "application/json"}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is True, result
    case0 = result["cases"][0]
    assert case0["ok"] is True, case0
    assert isinstance(case0.get("steps"), list) and len(case0["steps"]) == 2, case0
    s1 = case0["steps"][0]
    s2 = case0["steps"][1]
    for s in (s1, s2):
        for k in (
            "method",
            "url",
            "request_headers",
            "request_body",
            "status_code",
            "expected_status_code",
            "latency_ms",
            "response_headers",
            "response_summary",
            "output_preview",
            "output_full",
            "ok",
            "failures",
            "error_message",
        ):
            assert k in s, (k, s)
    assert s1["request_body"] is None, s1
    assert s2["url"] == "https://example.com/two/42", s2
    assert s2["request_headers"]["Authorization"] == "[REDACTED]", s2
    assert s2["request_headers"]["X-Missing"] == "{{never_set}}", s2
    assert s2["request_body"] == {"query": "what is an api", "id": "42"}, s2


def test_system_eval_steps_structured_json_path_assertions_failures_populated():
    suite = system_eval_core.validate_suite(
        {
            "suite_name": "steps-structured-assertions",
            "target_name": "fake",
            "cases": [
                {
                    "name": "scenario_structured_assertions",
                    "assertions": {},
                    "steps": [
                        {
                            "name": "step_1",
                            "method": "GET",
                            "url": "https://example.com/one",
                            "payload": {},
                            "assertions": [
                                {"type": "json_path_equals", "path": "$.id", "expected": 77},
                                {"type": "json_path_equals", "path": "$.id", "expected": 99},
                            ],
                        },
                        {
                            "name": "step_2",
                            "method": "GET",
                            "url": "https://example.com/two",
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
                text = '{"id":77}'
            else:
                text = '{"ok":true}'
            return system_eval_core.AdapterResult(
                ok=True, status_code=200, output_text=text, latency_ms=9 + self.n, response_headers={}
            )

    result = system_eval_core.execute_suite(suite, adapter=A())
    assert result["ok"] is False, result
    case0 = result["cases"][0]
    assert case0["ok"] is False, case0
    assert isinstance(case0.get("failures"), list) and case0["failures"], case0
    assert any("body_json_path_equals mismatch" in f for f in case0["failures"]), case0
    sr = case0.get("steps") or []
    assert len(sr) == 1, sr  # fail-fast at failing step
    assert sr[0]["ok"] is False, sr[0]
    assert isinstance(sr[0].get("failures"), list) and sr[0]["failures"], sr[0]
    assert any("body_json_path_equals mismatch" in f for f in sr[0]["failures"]), sr[0]


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
            json_line = next(
                (ln for ln in completed.stdout.splitlines() if ln.startswith("SYSTEM_EVAL_JSON:")), ""
            )
            assert json_line, f"missing SYSTEM_EVAL_JSON in stdout:\n{completed.stdout}"
            json_path = Path(json_line.split(":", 1)[1].strip())
            assert json_path.is_file(), json_path
            md_line = next(
                (ln for ln in completed.stdout.splitlines() if ln.startswith("SYSTEM_EVAL_MARKDOWN:")), ""
            )
            assert md_line, completed.stdout
            md_path = Path(md_line.split(":", 1)[1].strip())
            assert md_path.is_file(), md_path
            assert json_path.stem == md_path.stem, (json_path, md_path)
            artifact = json.loads(json_path.read_text(encoding="utf-8"))
            assert artifact["cases"][0].get("lane") == "stability", artifact
            assert artifact["cases"][0].get("stability_attempts") == 3, artifact
            assert artifact["cases"][0].get("attempts_total") == 3, artifact
            md_smoke = md_path.read_text(encoding="utf-8")
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


def test_system_eval_runner_script_requires_suite_argument():
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "system_eval_runner.py"),
    ]
    completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    assert completed.returncode != 0, "runner should fail when required --suite is missing"
    joined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    assert "--suite" in joined, joined


def test_system_eval_runner_script_missing_suite_file_nonzero():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        missing_suite = temp_root / "missing_suite.json"
        out_dir = temp_root / "out"
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "system_eval_runner.py"),
            "--suite",
            str(missing_suite),
            "--output-dir",
            str(out_dir),
        ]
        completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        assert completed.returncode != 0, "runner should fail when suite file path does not exist"
        joined = (completed.stdout or "") + "\n" + (completed.stderr or "")
        assert "No such file" in joined or "not found" in joined.lower() or "missing_suite.json" in joined, joined


def test_tool1_ui_helpers_parse_and_merge_auth_headers():
    from app import ui as app_ui

    hdrs, err = app_ui._tool1_parse_custom_headers_json('{"Accept":"application/json","X-N":1}')
    assert err is None, err
    assert hdrs == {"Accept": "application/json", "X-N": "1"}, hdrs

    merged, aerr = app_ui._tool1_merge_custom_headers_with_auth(
        {"Authorization": "Bearer old", "Accept": "application/json"},
        auth_mode="bearer",
        bearer_token="new-token",
        basic_username="",
        basic_password="",
        api_key_header_name="",
        api_key_value="",
    )
    assert aerr is None, aerr
    assert merged["Authorization"] == "Bearer new-token", merged
    assert merged["Accept"] == "application/json", merged


def test_tool1_ui_prepare_single_request_merges_query_and_headers():
    from app import ui as app_ui

    prep, err = app_ui._tool1_prepare_single_request(
        url="https://example.com/x?a=1",
        method="POST",
        body_text='{"ok":true}',
        headers_text='{"Authorization":"Bearer old","X-A":"1"}',
        query_params_text='{"a":"2","b":"3"}',
        auth_mode="api_key",
        bearer_token="",
        basic_username="",
        basic_password="",
        api_key_header_name="X-API-Key",
        api_key_value="secret-123",
    )
    assert err is None, err
    assert prep is not None
    assert prep["final_url"] in ("https://example.com/x?a=2&b=3", "https://example.com/x?b=3&a=2"), prep
    assert prep["headers"]["Authorization"] == "Bearer old", prep
    assert prep["headers"]["X-API-Key"] == "secret-123", prep
    assert prep["payload"] == {"ok": True}, prep


def test_tool1_prepare_single_request_substitutes_env_placeholders_BRAVE_API_KEY():
    from app import ui as app_ui

    with patch.dict(os.environ, {"BRAVE_API_KEY": "subbed-brave-token"}, clear=False):
        prep, err = app_ui._tool1_prepare_single_request(
            url="https://example.com/base?trace={{BRAVE_API_KEY}}",
            method="POST",
            body_text=json.dumps({"q": "{{BRAVE_API_KEY}}", "nested": {"t": "{{BRAVE_API_KEY}}"}}),
            headers_text=json.dumps(
                {"X-Subscription-Token": "{{BRAVE_API_KEY}}", "Accept": "application/json"}
            ),
            query_params_text=json.dumps({"x": "pre-{{BRAVE_API_KEY}}-post"}),
            auth_mode="none",
            bearer_token="",
            basic_username="",
            basic_password="",
            api_key_header_name="",
            api_key_value="",
        )
    assert err is None, err
    assert prep is not None
    assert prep["headers"]["X-Subscription-Token"] == "subbed-brave-token", prep["headers"]
    assert prep["payload"]["q"] == "subbed-brave-token", prep["payload"]
    assert prep["payload"]["nested"]["t"] == "subbed-brave-token", prep["payload"]
    assert prep["final_url"].count("subbed-brave-token") >= 2, prep["final_url"]


def test_tool1_prepare_single_request_missing_env_placeholder_errors_before_request():
    from app import ui as app_ui

    ghost = "ZZ_TOOL1_MISSING_PLACEHOLDER_VAR_99421"
    assert ghost not in os.environ
    prep, err = app_ui._tool1_prepare_single_request(
        url="https://example.com/h?token={{" + ghost + "}}",
        method="GET",
        body_text="",
        headers_text="{}",
        query_params_text="{}",
        auth_mode="none",
        bearer_token="",
        basic_username="",
        basic_password="",
        api_key_header_name="",
        api_key_value="",
    )
    assert prep is None, prep
    assert err and ghost in err, err
    assert "Unset or empty environment variable" in err, err


def test_tool1_single_request_env_placeholder_execute_suite_local_http_200():
    from app import ui as app_ui

    token = "local-roundtrip-brave-style-token"
    with patch.dict(os.environ, {"BRAVE_API_KEY": token}, clear=False):

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                got = self.headers.get("X-Subscription-Token", "")
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n > 0 else b""
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    body = {}
                ok = got == token and body.get("q") == "what is an API" and body.get("country") == "US"
                out = b'{"ok":true}' if ok else b'{"ok":false}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, format, *args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_port
            prep, err = app_ui._tool1_prepare_single_request(
                url=f"http://127.0.0.1:{port}/res/v1/llm/context",
                method="POST",
                body_text=json.dumps(
                    {"q": "what is an API", "country": "US", "search_lang": "en"},
                ),
                headers_text=json.dumps({"X-Subscription-Token": "{{BRAVE_API_KEY}}"}),
                query_params_text="{}",
                auth_mode="none",
                bearer_token="",
                basic_username="",
                basic_password="",
                api_key_header_name="",
                api_key_value="",
            )
            assert err is None, err
            suite = system_eval_core.validate_suite(prep["suite_dict"])
            adapter = system_eval_core.HttpTargetAdapter(default_timeout_seconds=5)
            result = system_eval_core.execute_suite(suite, adapter=adapter, fail_fast=False)
            assert result.get("ok") is True, result
            assert result["cases"][0]["status_code"] == 200, result["cases"][0]
        finally:
            server.shutdown()
            server.server_close()


def test_tool1_ui_parse_headers_invalid_json_errors():
    from app import ui as app_ui

    hdrs, err = app_ui._tool1_parse_custom_headers_json('{"Accept":')
    assert hdrs == {}, hdrs
    assert err and "Invalid JSON in headers" in err, err


def test_tool1_ui_prepare_single_request_rejects_non_object_json_body():
    from app import ui as app_ui

    prep, err = app_ui._tool1_prepare_single_request(
        url="https://example.com/x",
        method="POST",
        body_text='["not-object"]',
        headers_text="{}",
        query_params_text="{}",
        auth_mode="none",
        bearer_token="",
        basic_username="",
        basic_password="",
        api_key_header_name="",
        api_key_value="",
    )
    assert prep is None, prep
    assert err == 'JSON body must be a JSON object (e.g. {"id": 1}).', err


def test_tool1_ui_prepare_single_request_basic_auth_requires_username():
    from app import ui as app_ui

    prep, err = app_ui._tool1_prepare_single_request(
        url="https://example.com/x",
        method="GET",
        body_text="",
        headers_text="{}",
        query_params_text="{}",
        auth_mode="basic",
        bearer_token="",
        basic_username="",
        basic_password="secret",
        api_key_header_name="",
        api_key_value="",
    )
    assert prep is None, prep
    assert err == "Basic auth requires a username.", err


def test_tool1_ui_single_request_display_redacts_sensitive_headers_and_query():
    from app import ui as app_ui

    prep = {
        "method_u": "GET",
        "final_url": "https://example.com/x?token=abc123&q=ok",
        "headers": {
            "Authorization": "Bearer sk-secret",
            "X-Api-Key": "key-123",
            "Accept": "application/json",
        },
        "payload": {},
    }
    plain = app_ui._tool1_format_single_request_plain(prep)
    curl = app_ui._tool1_format_single_request_curl(prep)
    assert "abc123" not in plain and "sk-secret" not in plain and "key-123" not in plain, plain
    assert "abc123" not in curl and "sk-secret" not in curl and "key-123" not in curl, curl
    assert "[REDACTED]" in plain and "[REDACTED]" in curl, (plain, curl)


def test_tool1_ui_case_outcome_note_prompt_response_lane():
    from app import ui as app_ui

    outcome = app_ui._tool1_case_outcome_table_note(
        {"ok": False, "lane": "prompt_response", "status_code": None}
    )
    assert "prompt checks" in outcome.lower(), outcome


def test_tool3_ui_readability_summary_pass_and_fail_list():
    from app import ui as app_ui

    result = {
        "executed_cases": 4,
        "passed_cases": 2,
        "failed_cases": 2,
        "cases": [
            {"name": "c1", "ok": True},
            {"name": "c2", "ok": False},
            {"name": "c3", "ok": False},
            {"name": "c4", "ok": True},
        ],
    }
    out = app_ui._tool3_readability_summary(result, False)
    assert out["status"] == "FAIL", out
    assert out["total"] == 4 and out["passed"] == 2 and out["failed"] == 2, out
    assert out["failed_names"] == ["c2", "c3"], out
    assert "FAIL:" in out["human_summary"], out


def test_tool3_ui_readability_summary_limits_failing_names_to_five():
    from app import ui as app_ui

    result = {
        "executed_cases": 7,
        "passed_cases": 0,
        "failed_cases": 7,
        "cases": [{"name": f"f{i}", "ok": False} for i in range(1, 8)],
    }
    out = app_ui._tool3_readability_summary(result, False)
    assert len(out["failed_names"]) == 5, out
    assert out["failed_names"] == ["f1", "f2", "f3", "f4", "f5"], out

def test_tool1_assertion_surface_groups_are_disjoint_and_non_empty():
    from app import tool1_assertion_surface as surface

    groups = surface.grouped_assertions()
    core = groups.get("core") or []
    advanced = groups.get("advanced") or []
    assert isinstance(core, list) and core, groups
    assert isinstance(advanced, list) and advanced, groups
    assert set(core).isdisjoint(set(advanced)), groups


def test_tool1_assertion_surface_contains_expected_core_markers():
    from app import tool1_assertion_surface as surface

    groups = surface.grouped_assertions()
    core = set(groups.get("core") or [])
    advanced = set(groups.get("advanced") or [])
    assert "expected_status" in core, groups
    assert "expected_json_exists" in core, groups
    assert "expected_status_not" in advanced, groups
    assert "expected_json_absent" in advanced, groups


def test_system_eval_runner_script_success_prints_status_markers():
    suite_payload = {
        "suite_name": "runner-marker-suite",
        "target_name": "fake-http-target",
        "cases": [
            {
                "name": "status-and-token",
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
                "runner_markers",
            ]
            completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
            assert completed.returncode == 0, completed
            assert "SYSTEM_EVAL_STATUS: PASS" in completed.stdout, completed.stdout
            assert "SYSTEM_EVAL_JSON:" in completed.stdout, completed.stdout
            assert "SYSTEM_EVAL_MARKDOWN:" in completed.stdout, completed.stdout
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
    playground.clear_recent_answer_session()

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
        assert "DIRECT ANSWER MODE:" in prompt


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
        assert "DIRECT ANSWER MODE:" in prompt


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
    assert "The exact answer line to use is:" not in prompt
    assert "Current focus:" in prompt


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
        assert "Use exactly these three sections in this order:" not in prompt


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
        # May route via conversation (wh-question) without OPEN CONVERSATION OUTPUT FORMAT RULES.
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
    playground.clear_recent_answer_session()
    assert not playground.detect_recent_answer_relevance("Why did the last answer change?")


def test_get_best_recent_answer_match_none_when_history_empty():
    reset_agent_state()
    playground.clear_recent_answer_session()
    assert playground.get_best_recent_answer_match("Why did the last answer change?") is None


def test_get_best_recent_answer_match_selects_more_relevant_output():
    reset_agent_state()
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    q = "Why does detect_subtarget routing trigger strict mode here?"
    assert playground.detect_recent_answer_relevance(q)


def test_detect_recent_answer_relevance_false_for_short_unrelated_shared_token():
    reset_agent_state()
    playground.clear_recent_answer_session()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    q = "routing weather"
    assert not playground.detect_recent_answer_relevance(q)


def test_detect_recent_answer_relevance_false_for_generic_tokens_only():
    reset_agent_state()
    playground.clear_recent_answer_session()
    playground.append_recent_answer_history(
        "Project system agent memory test stage focus current next step."
    )
    q = "project system agent memory test next step"
    assert not playground.detect_recent_answer_relevance(q)


def test_detect_recent_answer_relevance_true_after_generic_token_filtering():
    reset_agent_state()
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
    playground.append_recent_answer_history(matched)
    prompt, _ = playground.build_messages(q)
    assert "Recent-answer contradiction/refinement cue:" not in prompt


def test_detect_recent_answer_contradiction_cue_false_for_unrelated_no():
    reset_agent_state()
    matched = "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    q = "No, tell me about weather patterns."
    assert playground.detect_recent_answer_contradiction_cue(q, matched)
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
    matched = "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    playground.append_recent_answer_history(matched)
    q = "Continue on detect_subtarget strict mode routing behavior."
    assert playground.detect_recent_answer_followup_type(q, matched) == "continuation"


def test_detect_recent_answer_followup_type_continuation_for_structured_list_reference():
    reset_agent_state()
    playground.clear_recent_answer_session()
    matched = "1. Validate login flow\n2. Add regression test\n3. Re-run suite"
    playground.append_recent_answer_history(matched)
    q = "Start with number 1"
    assert playground.detect_recent_answer_followup_type(q, matched) == "continuation"


def test_detect_recent_answer_followup_type_continuation_for_continue_with_structured_list():
    reset_agent_state()
    playground.clear_recent_answer_session()
    matched = "1. Validate login flow\n2. Add regression test\n3. Re-run suite"
    playground.append_recent_answer_history(matched)
    q = "Continue"
    assert playground.detect_recent_answer_followup_type(q, matched) == "continuation"


def test_detect_recent_answer_followup_type_continuation_for_next_with_structured_list():
    reset_agent_state()
    playground.clear_recent_answer_session()
    matched = "1. Validate login flow\n2. Add regression test\n3. Re-run suite"
    playground.append_recent_answer_history(matched)
    q = "Next"
    assert playground.detect_recent_answer_followup_type(q, matched) == "continuation"


def test_detect_recent_answer_followup_type_clarification_for_precision_prompt():
    reset_agent_state()
    playground.clear_recent_answer_session()
    matched = "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    playground.append_recent_answer_history(matched)
    q = "Can you clarify that and be specific about detect_subtarget?"
    assert playground.detect_recent_answer_followup_type(q, matched) == "clarification"


def test_detect_recent_answer_followup_type_correction_for_revision_prompt():
    reset_agent_state()
    playground.clear_recent_answer_session()
    matched = "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    playground.append_recent_answer_history(matched)
    q = "You said that earlier, but that's wrong now."
    assert playground.detect_recent_answer_followup_type(q, matched) == "correction"


def test_build_messages_adds_continuation_guidance_only_for_continuation():
    reset_agent_state()
    playground.clear_recent_answer_session()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    prompt, _ = playground.build_messages(
        "Continue on detect_subtarget strict mode routing behavior."
    )
    assert "Recent-answer follow-up type: continuation" in prompt
    assert "Recent-answer follow-up type: clarification" not in prompt
    assert "Recent-answer follow-up type: correction" not in prompt


def test_build_messages_adds_continuation_guidance_for_numbered_followup_reference():
    reset_agent_state()
    playground.clear_recent_answer_session()
    playground.append_recent_answer_history(
        "1. Validate login flow\n2. Add regression test\n3. Re-run suite"
    )
    prompt, _ = playground.build_messages("Start with number 1")
    assert "Recent-answer follow-up type: continuation" in prompt
    assert "continue the sequence directly" in prompt
    assert "Do not ask for clarification in that case" in prompt


def test_build_messages_continuation_override_priority_for_start_with_number_1():
    reset_agent_state()
    playground.clear_recent_answer_session()
    playground.append_recent_answer_history(
        "1. Validate login flow\n2. Add regression test\n3. Re-run suite"
    )
    prompt, _ = playground.build_messages("Start with number 1")
    assert "SEQUENCE DISCIPLINE MODE:" in prompt
    assert "Priority rule: sequence_discipline_mode overrides continuation mode, conversation mode, reasoning mode, fallback clarification, and project/status templates." in prompt
    assert "Do NOT ask for clarification when the prior ordered/list-like answer exists." in prompt
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in prompt
    assert "CLARIFY-FIRST (UNDEFINED IMPLEMENT/BUILD TARGET):" not in prompt


def test_build_messages_continuation_override_priority_for_continue_and_next():
    reset_agent_state()
    playground.clear_recent_answer_session()
    playground.append_recent_answer_history(
        "1. Validate login flow\n2. Add regression test\n3. Re-run suite"
    )
    prompt_continue, _ = playground.build_messages("Continue")
    prompt_next, _ = playground.build_messages("Next")
    assert "SEQUENCE DISCIPLINE MODE:" in prompt_continue
    assert "SEQUENCE DISCIPLINE MODE:" in prompt_next
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in prompt_continue
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in prompt_next


def test_sequence_discipline_mode_exact_requested_flow_enforces_one_step_behavior():
    reset_agent_state()
    playground.clear_recent_answer_session()

    initial_list = (
        "1. Define scope and acceptance criteria.\n"
        "2. Prepare environment and test data.\n"
        "3. Validate authentication and authorization.\n"
        "4. Execute positive-path endpoint tests.\n"
        "5. Execute negative and boundary tests.\n"
        "6. Validate performance, reliability, and retries.\n"
        "7. Report findings with evidence and follow-up actions."
    )

    q1 = "What are all the proper steps in order to test an API in a professional manner?"
    _prompt1, _ = playground.build_messages(q1)
    playground.append_recent_answer_history(initial_list, user_input=q1)

    q2 = "Please, one by one, not all in the same reply, elaborate on those 7 points, starting with number 1. Only include number 1, so if I have questions I can ask please."
    prompt2, _ = playground.build_messages(q2)
    assert "SEQUENCE DISCIPLINE MODE:" in prompt2
    assert "Respond with exactly one step only." in prompt2
    assert "Do NOT dump multiple steps or the full list." in prompt2
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in prompt2
    assert "OUTPUT FORMAT RULES:" not in prompt2

    q3 = "Start with number 1."
    prompt3, _ = playground.build_messages(q3)
    assert "SEQUENCE DISCIPLINE MODE:" in prompt3
    assert "Requested target step: 1. Respond with only step 1." in prompt3
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in prompt3
    assert "OUTPUT FORMAT RULES:" not in prompt3

    q4 = "Continue."
    prompt4, _ = playground.build_messages(q4)
    assert "SEQUENCE DISCIPLINE MODE:" in prompt4
    assert "If the user says Continue/Next, respond with only the next single step in order." in prompt4
    assert "CLARIFY-FIRST (UNDEFINED IMPLEMENT/BUILD TARGET):" not in prompt4

    q5 = "Next."
    prompt5, _ = playground.build_messages(q5)
    assert "SEQUENCE DISCIPLINE MODE:" in prompt5
    assert "If the user says Continue/Next, respond with only the next single step in order." in prompt5

    q6 = "Explain step 2."
    prompt6, _ = playground.build_messages(q6)
    assert "SEQUENCE DISCIPLINE MODE:" in prompt6
    assert "Requested target step: 2. Respond with only step 2." in prompt6
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in prompt6

    q7 = "Give me step 3 only."
    prompt7, _ = playground.build_messages(q7)
    assert "SEQUENCE DISCIPLINE MODE:" in prompt7
    assert "Requested target step: 3. Respond with only step 3." in prompt7
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in prompt7
    assert "OUTPUT FORMAT RULES:" not in prompt7
    assert "Use exactly these three sections in this order:\n\nAnswer:" not in prompt7


def test_detect_recent_answer_followup_type_elaborate_on_those_points_is_continuation():
    reset_agent_state()
    matched = (
        "Review requirements and test entry criteria.\n"
        "Validate sample payloads and check error responses.\n"
        "Verify logging and automate regression coverage.\n"
    )
    q = (
        "Please, one by one, not all in the same reply, elaborate on those 12 points, "
        "starting with number 1. Only include number 1."
    )
    assert playground.detect_recent_answer_followup_type(q, matched) == "continuation"


def test_pronoun_reference_tracking01_all_of_them_followup_guidance():
    reset_agent_state()
    playground.clear_recent_answer_session()
    prior = (
        "- Open APIs\n"
        "- Partner APIs\n"
        "- Internal APIs\n"
        "- Composite APIs"
    )
    playground.append_recent_answer_history(prior)
    prompt, _ = playground.build_messages("Do all of them need testing?")
    assert "Recent-answer follow-up type: continuation" in prompt
    assert "resolve pronouns from the immediately previous assistant output" in prompt.lower()
    assert "what are you referring to?" not in prompt.lower()


def test_pronoun_reference_tracking02_those_followup_guidance():
    reset_agent_state()
    playground.clear_recent_answer_session()
    prior = (
        "- Open APIs\n"
        "- Partner APIs\n"
        "- Internal APIs\n"
        "- Composite APIs"
    )
    playground.append_recent_answer_history(prior)
    prompt, _ = playground.build_messages("Do those need testing?")
    assert "Recent-answer follow-up type: continuation" in prompt
    assert "resolve pronouns from the immediately previous assistant output" in prompt.lower()
    assert "what are you referring to?" not in prompt.lower()


def test_pronoun_reference_tracking03_they_all_followup_guidance():
    reset_agent_state()
    playground.clear_recent_answer_session()
    prior = (
        "- Open APIs\n"
        "- Partner APIs\n"
        "- Internal APIs\n"
        "- Composite APIs"
    )
    playground.append_recent_answer_history(prior)
    prompt, _ = playground.build_messages("Do they all need testing?")
    assert "Recent-answer follow-up type: continuation" in prompt
    assert "resolve pronouns from the immediately previous assistant output" in prompt.lower()
    assert "what are you referring to?" not in prompt.lower()


def test_sequence_discipline_twelve_line_separated_steps_live_failure():
    """Prior answer: unnumbered line-separated list; user references those 12 points — no clarification path."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    lines = [
        "Review the API contract and authentication model.",
        "Define explicit acceptance criteria and negative cases.",
        "Set up isolated test environments and data fixtures.",
        "Create reusable client helpers for auth and headers.",
        "Exercise happy-path requests with representative payloads.",
        "Validate HTTP status codes and error mapping behavior.",
        "Assert response schema, types, and required fields strictly.",
        "Cover pagination, filtering, and idempotency where applicable.",
        "Run concurrency and rate-limit behavior checks safely.",
        "Measure latency and basic performance thresholds on critical paths.",
        "Add security checks for injection, auth bypass, and sensitive data leaks.",
        "Automate the suite in CI with deterministic reporting and artifacts.",
    ]
    playground.append_recent_answer_history("\n".join(lines))
    q = (
        "Please, one by one, not all in the same reply, elaborate on those 12 points, "
        "starting with number 1. Only include number 1, so if I have questions I can ask please."
    )
    prompt, _ = playground.build_messages(q)
    assert "SEQUENCE DISCIPLINE MODE:" in prompt
    assert "Requested target step: 1. Respond with only step 1." in prompt
    assert "CLARIFY-FIRST (UNDEFINED IMPLEMENT/BUILD TARGET):" not in prompt
    assert "OUTPUT FORMAT RULES:" not in prompt


def test_external_api_testing_education_suppresses_three_section_templates():
    reset_agent_state()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    prompt, _ = playground.build_messages(q)
    assert "OUTPUT FORMAT RULES:" not in prompt
    assert "Use exactly these three sections in this order:" not in prompt


def test_sequence_language_switch_mid_flow():
    """Increment 5: language pivot mid sequence — anchor list, continue, then French; no clarify reset."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    _full_steps_q = "What are all the proper steps in order to test an API in a professional manner?"
    playground.append_recent_answer_history(
        "1. First step about API scope\n"
        "2. Second step about test design\n"
        "3. Third step about execution\n",
        user_input=_full_steps_q,
    )
    p1, _ = playground.build_messages("Start with number 1.")
    assert "SEQUENCE DISCIPLINE MODE:" in p1
    playground.append_recent_answer_history(
        "Step 1: define the API surface and environments you will exercise.",
        user_input="Start with number 1.",
    )
    p2, _ = playground.build_messages("Continue.")
    assert "SEQUENCE DISCIPLINE MODE:" in p2 or "CONTINUATION OVERRIDE MODE:" in p2
    playground.append_recent_answer_history(
        "Step 2: design concrete cases including negative paths.",
        user_input="Continue.",
    )
    p3, _ = playground.build_messages("en français svp cette fois si")
    assert "OUTPUT LANGUAGE (sequence flow — increment 5):" in p3
    assert "French (français)" in p3
    assert "Do not refuse" in p3
    assert "CLARIFY-FIRST (UNDEFINED IMPLEMENT/BUILD TARGET):" not in p3
    assert (
        "SEQUENCE DISCIPLINE MODE:" in p3
        or "CONTINUATION OVERRIDE MODE:" in p3
        or "Continuation override mode (INTERACTION-02):" in p3
    )


def test_step_alignment_persistence_across_language_switch():
    """Increment 6: indexed step store + cursor — exact step body survives continue and language pivot."""
    reset_agent_state()

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    initial_list = (
        "1. IDX_STEP_ONE_UNIQUE_PHRASE_ALPHA\n"
        "2. IDX_STEP_TWO_UNIQUE_PHRASE_BETA\n"
        "3. IDX_STEP_THREE_UNIQUE_PHRASE_GAMMA\n"
    )
    _full_steps_q = "What are all the proper steps in order to test an API in a professional manner?"
    playground.append_recent_answer_history(initial_list, user_input=_full_steps_q)
    assert len(playground.recent_answer_step_frames) == len(playground.recent_answer_history)

    p1, _ = playground.build_messages("Start with number 1.")
    assert "INDEXED STEP CONTENT" in p1
    l1 = _indexed_step_line(p1, 1, 3)
    assert "IDX_STEP_ONE_UNIQUE_PHRASE_ALPHA" in l1
    assert "IDX_STEP_TWO_UNIQUE_PHRASE_BETA" not in l1

    playground.append_recent_answer_history("Narration for step one only.", user_input="Start with number 1.")
    p2, _ = playground.build_messages("Continue")
    l2 = _indexed_step_line(p2, 2, 3)
    assert "IDX_STEP_TWO_UNIQUE_PHRASE_BETA" in l2
    assert "IDX_STEP_THREE_UNIQUE_PHRASE_GAMMA" not in l2

    playground.append_recent_answer_history("Narration for step two only.", user_input="Continue")
    p3, _ = playground.build_messages("en français svp cette fois si")
    l3 = _indexed_step_line(p3, 2, 3)
    assert "IDX_STEP_TWO_UNIQUE_PHRASE_BETA" in l3
    assert "IDX_STEP_THREE_UNIQUE_PHRASE_GAMMA" not in l3
    assert "OUTPUT LANGUAGE (sequence flow — increment 5):" in p3

    p4, _ = playground.build_messages("step 3")
    l4 = _indexed_step_line(p4, 3, 3)
    assert "IDX_STEP_THREE_UNIQUE_PHRASE_GAMMA" in l4
    assert "IDX_STEP_ONE_UNIQUE_PHRASE_ALPHA" not in l4

    p5, _ = playground.build_messages("step 2")
    l5 = _indexed_step_line(p5, 2, 3)
    assert "IDX_STEP_TWO_UNIQUE_PHRASE_BETA" in l5
    assert "IDX_STEP_THREE_UNIQUE_PHRASE_GAMMA" not in l5


def test_indexed_sequence_continue_then_next_advances_one_step_at_a_time():
    """Cursor must track last delivered step: Continue → 2, Next → 3 (never skip to 4)."""
    reset_agent_state()
    playground.clear_recent_answer_session()

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    q_list = "What are all the proper steps in order to test an API in a professional manner?"
    lst = (
        "1. CURSOR_ONE_UNIQUE\n"
        "2. CURSOR_TWO_UNIQUE\n"
        "3. CURSOR_THREE_UNIQUE\n"
        "4. CURSOR_FOUR_UNIQUE\n"
    )
    playground.append_recent_answer_history(lst, user_input=q_list)
    p1, _ = playground.build_messages("Start with number 1.")
    assert "CURSOR_ONE_UNIQUE" in _indexed_step_line(p1, 1, 4)
    assert playground.get_sequence_step_cursor() == 1
    playground.append_recent_answer_history("reply step 1", user_input="Start with number 1.")
    p2, _ = playground.build_messages("Continue")
    assert "CURSOR_TWO_UNIQUE" in _indexed_step_line(p2, 2, 4)
    assert "CURSOR_FOUR_UNIQUE" not in _indexed_step_line(p2, 2, 4)
    assert playground.get_sequence_step_cursor() == 2
    playground.append_recent_answer_history("reply step 2", user_input="Continue")
    p3, _ = playground.build_messages("Next")
    assert "CURSOR_THREE_UNIQUE" in _indexed_step_line(p3, 3, 4)
    assert "CURSOR_FOUR_UNIQUE" not in _indexed_step_line(p3, 3, 4)
    assert playground.get_sequence_step_cursor() == 3


def test_language_switch_uses_last_rendered_step_not_cursor():
    """Increment 7: short language pivot must translate last displayed step, not sequence cursor."""
    reset_agent_state()
    playground.clear_recent_answer_session()

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    q_list = "What are all the proper steps in order to test an API in a professional manner?"
    lst = (
        "1. LR_LANG_ONE\n"
        "2. LR_LANG_TWO_RENDER_MARK\n"
        "3. LR_LANG_THREE_OTHER\n"
    )
    playground.append_recent_answer_history(lst, user_input=q_list)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("r1", user_input="Start with number 1.")
    assert playground.get_last_rendered_step_index() == 1
    playground.build_messages("Continue")
    playground.append_recent_answer_history("r2", user_input="Continue")
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2
    playground.build_messages("Next")
    playground.append_recent_answer_history("r3", user_input="Next")
    assert playground.get_sequence_step_cursor() == 3
    assert playground.get_last_rendered_step_index() == 3
    playground.build_messages("Explain step 2.")
    playground.append_recent_answer_history("r4", user_input="Explain step 2.")
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2
    p_fr, _ = playground.build_messages("en français svp cette fois si")
    line = _indexed_step_line(p_fr, 2, 3)
    assert "LR_LANG_TWO_RENDER_MARK" in line
    assert "LR_LANG_THREE_OTHER" not in line
    assert "OUTPUT LANGUAGE" in p_fr


def _inc1_indexed_step_line(prompt: str, step_n: int, total: int) -> str:
    prefix = f"Step {step_n} of {total}:"
    for line in prompt.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    raise AssertionError(f"missing indexed line {prefix!r}")


def test_increment1_french_polish_detect_phrases():
    """Increment 1: common French/English pivot phrases map to output-language codes."""
    assert journal_service.detect_requested_output_language("français svp") == "fr"
    assert journal_service.detect_requested_output_language("Français SVP.") == "fr"
    assert journal_service.detect_requested_output_language("back to English please") == "en"
    assert journal_service.detect_requested_output_language("en anglais maintenant") == "en"


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1_french_polish_transcript_english_french_english(capsys):
    """Transcript A: English → French pivot (same step) → English pivot (same step); DEBUG on."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. IA_FR_EN_ONE\n2. IA_FR_EN_TWO\n3. IA_FR_EN_THREE\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("s1", user_input="Start with number 1.")
    playground.build_messages("Continue")
    playground.append_recent_answer_history("s2", user_input="Continue")
    assert playground.get_last_rendered_step_index() == 2

    p_fr, _ = playground.build_messages("français svp")
    err1 = capsys.readouterr().err
    assert "[DEBUG]" in err1
    assert "resolved_target_idx: 2" in err1
    assert "OUTPUT LANGUAGE" in p_fr and "French (français)" in p_fr
    line_fr = _inc1_indexed_step_line(p_fr, 2, 3)
    assert "IA_FR_EN_TWO" in line_fr
    assert "IA_FR_EN_THREE" not in line_fr

    playground.append_recent_answer_history("s2fr", user_input="français svp")
    p_en, _ = playground.build_messages("back to english")
    err2 = capsys.readouterr().err
    assert "[DEBUG]" in err2
    assert "resolved_target_idx: 2" in err2
    assert "OUTPUT LANGUAGE" in p_en and "English" in p_en
    line_en = _inc1_indexed_step_line(p_en, 2, 3)
    assert "IA_FR_EN_TWO" in line_en
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1_french_polish_continue_next_with_french_pivots(capsys):
    """Transcript B: Continue/Next progression; French OUTPUT LANGUAGE on pivot turns only."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. IA_CN_FR_A\n2. IA_CN_FR_B\n3. IA_CN_FR_C\n4. IA_CN_FR_D\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("a1", user_input="Start with number 1.")
    p_co, _ = playground.build_messages("Continue")
    assert "IA_CN_FR_B" in _inc1_indexed_step_line(p_co, 2, 4)
    capsys.readouterr()
    playground.append_recent_answer_history("a2", user_input="Continue")
    p_piv, _ = playground.build_messages("en français")
    err = capsys.readouterr().err
    assert "[DEBUG]" in err
    assert "OUTPUT LANGUAGE" in p_piv and "French (français)" in p_piv
    assert "IA_CN_FR_B" in _inc1_indexed_step_line(p_piv, 2, 4)
    playground.append_recent_answer_history("a2fr", user_input="en français")
    p_next, _ = playground.build_messages("Next")
    assert "IA_CN_FR_C" in _inc1_indexed_step_line(p_next, 3, 4)
    assert "French (français)" not in p_next
    capsys.readouterr()
    playground.append_recent_answer_history("a3", user_input="Next")
    p_fr3, _ = playground.build_messages("français svp")
    assert "OUTPUT LANGUAGE" in p_fr3 and "French (français)" in p_fr3
    assert "IA_CN_FR_C" in _inc1_indexed_step_line(p_fr3, 3, 4)


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1_french_polish_explain_step_in_french(capsys):
    """Transcript C: explain-step + requested French; same step index, OUTPUT LANGUAGE fr."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. IA_EX_FR_ONE\n2. IA_EX_FR_TWO\n3. IA_EX_FR_THREE\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("r1", user_input="Start with number 1.")
    playground.build_messages("Continue")
    playground.append_recent_answer_history("r2", user_input="Continue")
    p, _ = playground.build_messages("Explain step 2 in French")
    err = capsys.readouterr().err
    assert "[DEBUG]" in err
    assert "OUTPUT LANGUAGE" in p and "French (français)" in p
    assert "IA_EX_FR_TWO" in _inc1_indexed_step_line(p, 2, 3)


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1_french_polish_give_me_step_only_in_french(capsys):
    """Transcript D: give me step N only + in French → that step only + OUTPUT LANGUAGE fr."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. IA_GM_ONE\n2. IA_GM_TWO\n3. IA_GM_THREE\n4. IA_GM_FOUR\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("x1", user_input="Start with number 1.")
    p, _ = playground.build_messages("Give me step 3 only in French please")
    err = capsys.readouterr().err
    assert "[DEBUG]" in err
    assert "OUTPUT LANGUAGE" in p and "French (français)" in p
    assert "IA_GM_THREE" in _inc1_indexed_step_line(p, 3, 4)
    assert "IA_GM_FOUR" not in _inc1_indexed_step_line(p, 3, 4)


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1_french_polish_mixed_language_courtesy_start(capsys):
    """Transcript E: courtesy French tokens + English step cues; progression + FR pivot."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. IA_MX_ONE\n2. IA_MX_TWO\n3. IA_MX_THREE\n"
    playground.append_recent_answer_history(lst, user_input=q)
    p1, _ = playground.build_messages("Start with number 1 s'il vous plaît")
    capsys.readouterr()
    assert "IA_MX_ONE" in _inc1_indexed_step_line(p1, 1, 3)
    playground.append_recent_answer_history("m1", user_input="Start with number 1 s'il vous plaît")
    p2, _ = playground.build_messages("Continue")
    assert "IA_MX_TWO" in _inc1_indexed_step_line(p2, 2, 3)
    capsys.readouterr()
    playground.append_recent_answer_history("m2", user_input="Continue")
    p3, _ = playground.build_messages("français svp")
    err = capsys.readouterr().err
    assert "[DEBUG]" in err
    assert "OUTPUT LANGUAGE" in p3 and "French (français)" in p3
    assert "IA_MX_TWO" in _inc1_indexed_step_line(p3, 2, 3)


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1b_continue_en_francais_progresses_and_sets_language(capsys):
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I1B_CF_ONE\n2. I1B_CF_TWO\n3. I1B_CF_THREE\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("c1", user_input="Start with number 1.")
    p, _ = playground.build_messages("Continue en français")
    err = capsys.readouterr().err
    assert "[DEBUG]" in err
    assert "resolved_target_idx: 2" in err
    assert "OUTPUT LANGUAGE" in p and "French (français)" in p
    assert "I1B_CF_TWO" in _inc1_indexed_step_line(p, 2, 3)
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1b_next_en_francais_progresses_and_sets_language(capsys):
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I1B_NF_ONE\n2. I1B_NF_TWO\n3. I1B_NF_THREE\n4. I1B_NF_FOUR\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("n1", user_input="Start with number 1.")
    playground.build_messages("Continue")
    playground.append_recent_answer_history("n2", user_input="Continue")
    p, _ = playground.build_messages("Next en français")
    err = capsys.readouterr().err
    assert "[DEBUG]" in err
    assert "resolved_target_idx: 3" in err
    assert "OUTPUT LANGUAGE" in p and "French (français)" in p
    assert "I1B_NF_THREE" in _inc1_indexed_step_line(p, 3, 4)
    assert "I1B_NF_FOUR" not in _inc1_indexed_step_line(p, 3, 4)
    assert playground.get_sequence_step_cursor() == 3
    assert playground.get_last_rendered_step_index() == 3


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1b_continue_in_english_progresses_and_sets_language(capsys):
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I1B_CE_ONE\n2. I1B_CE_TWO\n3. I1B_CE_THREE\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("e1", user_input="Start with number 1.")
    p, _ = playground.build_messages("Continue in English")
    err = capsys.readouterr().err
    assert "[DEBUG]" in err
    assert "resolved_target_idx: 2" in err
    assert "OUTPUT LANGUAGE" in p and "English" in p
    assert "I1B_CE_TWO" in _inc1_indexed_step_line(p, 2, 3)
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1b_next_in_french_progresses_and_sets_language(capsys):
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I1B_NIF_ONE\n2. I1B_NIF_TWO\n3. I1B_NIF_THREE\n4. I1B_NIF_FOUR\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("f1", user_input="Start with number 1.")
    playground.build_messages("Continue")
    playground.append_recent_answer_history("f2", user_input="Continue")
    p, _ = playground.build_messages("Next in French")
    err = capsys.readouterr().err
    assert "[DEBUG]" in err
    assert "resolved_target_idx: 3" in err
    assert "OUTPUT LANGUAGE" in p and "French (français)" in p
    assert "I1B_NIF_THREE" in _inc1_indexed_step_line(p, 3, 4)
    assert "I1B_NIF_FOUR" not in _inc1_indexed_step_line(p, 3, 4)
    assert playground.get_sequence_step_cursor() == 3
    assert playground.get_last_rendered_step_index() == 3


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1c_frame_retention_under_stress_transcript(capsys):
    """Increment 1C: keep all sequence pivots anchored to the active API-testing indexed frame."""
    reset_agent_state()
    playground.clear_recent_answer_session()

    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = (
        "1. I1C_API_SCOPE\n"
        "2. I1C_CASE_DESIGN\n"
        "3. I1C_ENV_EXECUTION\n"
        "4. I1C_ANALYZE_REPORT\n"
    )
    playground.append_recent_answer_history(lst, user_input=q)

    obo = (
        "Please, one by one, not all in the same reply, elaborate on those points, "
        "starting with number 1. Only include number 1, so if I have questions I can ask please."
    )
    p1, _ = playground.build_messages(obo)
    d1 = capsys.readouterr().err
    assert "resolved_target_idx: 1" in d1
    assert "I1C_API_SCOPE" in _inc1_indexed_step_line(p1, 1, 4)
    assert "I1C_CASE_DESIGN" not in _inc1_indexed_step_line(p1, 1, 4)
    playground.append_recent_answer_history("i1c-r1", user_input=obo)
    assert playground.get_sequence_step_cursor() == 1
    assert playground.get_last_rendered_step_index() == 1

    p2, _ = playground.build_messages("Start with number 1.")
    d2 = capsys.readouterr().err
    assert "resolved_target_idx: 1" in d2
    assert "I1C_API_SCOPE" in _inc1_indexed_step_line(p2, 1, 4)
    playground.append_recent_answer_history("i1c-r2", user_input="Start with number 1.")
    assert playground.get_sequence_step_cursor() == 1
    assert playground.get_last_rendered_step_index() == 1

    p3, _ = playground.build_messages("Continue en français.")
    d3 = capsys.readouterr().err
    assert "resolved_target_idx: 2" in d3
    assert "OUTPUT LANGUAGE" in p3 and "French (français)" in p3
    assert "I1C_CASE_DESIGN" in _inc1_indexed_step_line(p3, 2, 4)
    playground.append_recent_answer_history("i1c-r3", user_input="Continue en français.")
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2

    p4, _ = playground.build_messages("Next in English.")
    d4 = capsys.readouterr().err
    assert "resolved_target_idx: 3" in d4
    assert "OUTPUT LANGUAGE" in p4 and "English" in p4
    assert "I1C_ENV_EXECUTION" in _inc1_indexed_step_line(p4, 3, 4)
    assert "I1C_ANALYZE_REPORT" not in _inc1_indexed_step_line(p4, 3, 4)
    playground.append_recent_answer_history("i1c-r4", user_input="Next in English.")
    assert playground.get_sequence_step_cursor() == 3
    assert playground.get_last_rendered_step_index() == 3

    p5, _ = playground.build_messages("Explain step 2 in French.")
    d5 = capsys.readouterr().err
    assert "resolved_target_idx: 2" in d5
    assert "OUTPUT LANGUAGE" in p5 and "French (français)" in p5
    assert "I1C_CASE_DESIGN" in _inc1_indexed_step_line(p5, 2, 4)
    playground.append_recent_answer_history("i1c-r5", user_input="Explain step 2 in French.")
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2

    p6, _ = playground.build_messages("Give me step 4 only in French please.")
    d6 = capsys.readouterr().err
    assert "resolved_target_idx: 4" in d6
    assert "OUTPUT LANGUAGE" in p6 and "French (français)" in p6
    assert "I1C_ANALYZE_REPORT" in _inc1_indexed_step_line(p6, 4, 4)
    playground.append_recent_answer_history("i1c-r6", user_input="Give me step 4 only in French please.")
    assert playground.get_sequence_step_cursor() == 4
    assert playground.get_last_rendered_step_index() == 4

    p7, _ = playground.build_messages("Back to English.")
    d7 = capsys.readouterr().err
    assert "resolved_target_idx: 4" in d7
    assert "OUTPUT LANGUAGE" in p7 and "English" in p7
    assert "I1C_ANALYZE_REPORT" in _inc1_indexed_step_line(p7, 4, 4)
    playground.append_recent_answer_history("i1c-r7", user_input="Back to English.")
    assert playground.get_sequence_step_cursor() == 4
    assert playground.get_last_rendered_step_index() == 4

    p8, _ = playground.build_messages("Continue in English.")
    d8 = capsys.readouterr().err
    assert "resolved_target_idx: 4" in d8
    assert "OUTPUT LANGUAGE" in p8 and "English" in p8
    assert "I1C_ANALYZE_REPORT" in _inc1_indexed_step_line(p8, 4, 4)
    assert playground.get_sequence_step_cursor() == 4
    assert playground.get_last_rendered_step_index() == 4


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1d_french_hard_lock_accents_variants_and_repeated_switches(capsys):
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I1D_A_ONE\n2. I1D_A_TWO\n3. I1D_A_THREE\n4. I1D_A_FOUR\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("d1", user_input="Start with number 1.")
    playground.build_messages("Continue")
    playground.append_recent_answer_history("d2", user_input="Continue")
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2

    for phrase in ("francais svp", "en francais", "FRANÇAIS SVP", "fr svp", "french please"):
        p, _ = playground.build_messages(phrase)
        d = capsys.readouterr().err
        assert "resolved_target_idx: 2" in d
        assert "OUTPUT LANGUAGE" in p and "French (français)" in p
        assert "I1D_A_TWO" in _inc1_indexed_step_line(p, 2, 4)
        assert playground.get_sequence_step_cursor() == 2
        assert playground.get_last_rendered_step_index() == 2

    p_en, _ = playground.build_messages("back to English")
    d_en = capsys.readouterr().err
    assert "resolved_target_idx: 2" in d_en
    assert "OUTPUT LANGUAGE" in p_en and "English" in p_en
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2

    p_fr2, _ = playground.build_messages("en français")
    d_fr2 = capsys.readouterr().err
    assert "resolved_target_idx: 2" in d_fr2
    assert "OUTPUT LANGUAGE" in p_fr2 and "French (français)" in p_fr2
    playground.append_recent_answer_history("to-fr", user_input="en français")
    p_en2, _ = playground.build_messages("English")
    d_en2 = capsys.readouterr().err
    assert "resolved_target_idx: 2" in d_en2
    assert "OUTPUT LANGUAGE" in p_en2 and "English" in p_en2
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2


@patch.dict(os.environ, {"DEBUG_SEQUENCE": "1"}, clear=False)
def test_increment1d_french_hard_lock_noise_mid_sentence_and_constraints(capsys):
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I1D_B_ONE\n2. I1D_B_TWO\n3. I1D_B_THREE\n4. I1D_B_FOUR\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("b1", user_input="Start with number 1.")

    p2, _ = playground.build_messages("continue en français!!!")
    d2 = capsys.readouterr().err
    assert "resolved_target_idx: 2" in d2
    assert "OUTPUT LANGUAGE" in p2 and "French (français)" in p2
    assert "I1D_B_TWO" in _inc1_indexed_step_line(p2, 2, 4)
    playground.append_recent_answer_history(_inc1_indexed_step_line(p2, 2, 4), user_input="continue en français!!!")
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2

    p3, _ = playground.build_messages("next en français???")
    d3 = capsys.readouterr().err
    assert "resolved_target_idx: 3" in d3
    assert "OUTPUT LANGUAGE" in p3 and "French (français)" in p3
    assert "I1D_B_THREE" in _inc1_indexed_step_line(p3, 3, 4)
    playground.append_recent_answer_history(_inc1_indexed_step_line(p3, 3, 4), user_input="next en français???")
    assert playground.get_sequence_step_cursor() == 3
    assert playground.get_last_rendered_step_index() == 3

    for txt in ("en français svp...", "continue, en français", "next - en français"):
        p, _ = playground.build_messages(txt)
        d = capsys.readouterr().err
        assert "[DEBUG]" in d
        assert "OUTPUT LANGUAGE" in p and "French (français)" in p

    p4, _ = playground.build_messages("Continue but in French please")
    d4 = capsys.readouterr().err
    assert "resolved_target_idx: 4" in d4
    assert "OUTPUT LANGUAGE" in p4 and "French (français)" in p4
    assert "I1D_B_FOUR" in _inc1_indexed_step_line(p4, 4, 4)

    p4b, _ = playground.build_messages("Next and answer in French")
    d4b = capsys.readouterr().err
    assert "resolved_target_idx: 4" in d4b
    assert "OUTPUT LANGUAGE" in p4b and "French (français)" in p4b
    assert "I1D_B_FOUR" in _inc1_indexed_step_line(p4b, 4, 4)

    p_ex, _ = playground.build_messages("Explain step 2 but answer in French")
    d_ex = capsys.readouterr().err
    assert "resolved_target_idx: 2" in d_ex
    assert "OUTPUT LANGUAGE" in p_ex and "French (français)" in p_ex
    assert "I1D_B_TWO" in _inc1_indexed_step_line(p_ex, 2, 4)
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2

    p_c1, _ = playground.build_messages("Next en français, but only the title")
    d_c1 = capsys.readouterr().err
    assert "resolved_target_idx: 3" in d_c1
    assert "OUTPUT LANGUAGE" in p_c1 and "French (français)" in p_c1
    assert "I1D_B_THREE" in _inc1_indexed_step_line(p_c1, 3, 4)
    assert playground.get_sequence_step_cursor() == 3
    assert playground.get_last_rendered_step_index() == 3

    p_c2, _ = playground.build_messages("Continue in English, keep it short")
    d_c2 = capsys.readouterr().err
    assert "resolved_target_idx: 4" in d_c2
    assert "OUTPUT LANGUAGE" in p_c2 and "English" in p_c2
    assert "I1D_B_FOUR" in _inc1_indexed_step_line(p_c2, 4, 4)
    assert playground.get_sequence_step_cursor() == 4
    assert playground.get_last_rendered_step_index() == 4

    p_c3, _ = playground.build_messages("Donne-moi l’étape 3 seulement, en français, court")
    d_c3 = capsys.readouterr().err
    assert "resolved_target_idx: 3" in d_c3
    assert "OUTPUT LANGUAGE" in p_c3 and "French (français)" in p_c3
    assert "I1D_B_THREE" in _inc1_indexed_step_line(p_c3, 3, 4)
    assert playground.get_sequence_step_cursor() == 3
    assert playground.get_last_rendered_step_index() == 3


def test_increment2_step_quality_template_english_distinct_and_explain():
    """Increment 2: indexed step turns inject concise quality template and distinctness guidance."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I2_SCOPE\n2. I2_CASES\n3. I2_EXECUTION\n4. I2_REPORTING\n"
    playground.append_recent_answer_history(lst, user_input=q)

    p1, _ = playground.build_messages("Start with number 1.")
    assert "I2_SCOPE" in _inc1_indexed_step_line(p1, 1, 4)
    assert "Default step output format (concise): Title | What it means | Why it matters | One concrete API-testing example | What Jessy should do next." in p1
    assert "Keep this step meaningfully distinct from other steps" in p1

    playground.append_recent_answer_history("r1", user_input="Start with number 1.")
    p2, _ = playground.build_messages("Continue.")
    assert "I2_CASES" in _inc1_indexed_step_line(p2, 2, 4)
    assert "I2_EXECUTION" not in _inc1_indexed_step_line(p2, 2, 4)
    assert "Default step output format (concise): Title | What it means | Why it matters | One concrete API-testing example | What Jessy should do next." in p2

    playground.append_recent_answer_history("r2", user_input="Continue.")
    p3, _ = playground.build_messages("Next.")
    assert "I2_EXECUTION" in _inc1_indexed_step_line(p3, 3, 4)
    assert "I2_CASES" not in _inc1_indexed_step_line(p3, 3, 4)

    playground.append_recent_answer_history("r3", user_input="Next.")
    p_explain, _ = playground.build_messages("Explain step 2.")
    assert "I2_CASES" in _inc1_indexed_step_line(p_explain, 2, 4)
    assert "Explain-step request: add one extra clarifying sentence" in p_explain


def test_increment2_step_quality_template_french_title_only_and_short():
    """Increment 2: French mode keeps quality template and applies title-only / short overrides."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I2F_ONE\n2. I2F_TWO\n3. I2F_THREE\n4. I2F_FOUR\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("fr1", user_input="Start with number 1.")
    playground.build_messages("Continue en français")
    playground.append_recent_answer_history("fr2", user_input="Continue en français")

    p_title, _ = playground.build_messages("Next en français, but only the title")
    assert "OUTPUT LANGUAGE" in p_title and "French (français)" in p_title
    assert "I2F_THREE" in _inc1_indexed_step_line(p_title, 3, 4)
    assert "Constraint override: return only the step title line for this turn." in p_title

    playground.append_recent_answer_history("fr3", user_input="Next en français, but only the title")
    p_short, _ = playground.build_messages("Continue in English, keep it short")
    assert "OUTPUT LANGUAGE" in p_short and "English" in p_short
    assert "I2F_FOUR" in _inc1_indexed_step_line(p_short, 4, 4)
    assert "Constraint override: keep the response short (2-3 compact lines) while preserving meaning." in p_short


def test_increment2b_full_list_contract_operator_focused():
    """Increment 2B: full API-testing list contract emphasizes practical operator workflow."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    p, _ = playground.build_messages(
        "What are all the proper steps in order to test an API in a professional manner?"
    )
    assert "ORDERED STEPS OUTPUT PREFERENCE (full multi-step list — this turn):" in p
    assert "API-testing operator contract: prioritize practical workflow language over generic textbook wording." in p
    assert "Across the list, cover concrete endpoint targeting, auth/headers" in p
    assert "Keep step titles specific and operational" in p


def test_increment2e_full_list_contract_is_tight_operator_workflow():
    """Increment 2E: full API list contract is 4-6 steps with required operator flow coverage."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    p, _ = playground.build_messages(
        "What are all the proper steps in order to test an API in a professional manner?"
    )
    assert "ORDERED STEPS OUTPUT PREFERENCE (full multi-step list — this turn):" in p
    assert "with 4-6 high-impact operator steps for a typical API-testing workflow" in p
    assert "Preferred step flow (merge where needed to stay within 4-6): endpoint scope/contract -> positive-negative-boundary cases -> execute requests + capture evidence -> validate status/headers/payload/response body -> defect reporting + retest/regression." in p
    assert "If the user asks for this full list in French (or another language), return the same 4-6 operator workflow in that language." in p


def test_increment2e_full_list_contract_french_request_keeps_same_workflow():
    """Increment 2E: French full-list ask keeps the same 4-6 operator workflow contract."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    p, _ = playground.build_messages(
        "What are all the proper steps in order to test an API in a professional manner, in French?"
    )
    assert "with 4-6 high-impact operator steps for a typical API-testing workflow" in p
    assert "Preferred step flow (merge where needed to stay within 4-6): endpoint scope/contract -> positive-negative-boundary cases -> execute requests + capture evidence -> validate status/headers/payload/response body -> defect reporting + retest/regression." in p
    assert "If the user asks for this full list in French (or another language), return the same 4-6 operator workflow in that language." in p


def test_increment2f_full_list_contract_includes_final_step_regression_en_fr():
    """Increment 2F: full-list contract pins final step wording with regression in EN/FR."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    p_en, _ = playground.build_messages(
        "What are all the proper steps in order to test an API in a professional manner?"
    )
    assert "Preferred final step title (English): Report Defects, Retest Fixes, and Run Regression." in p_en
    assert "Preferred final step title (French): Reporter les défauts, retester les correctifs et lancer la régression." in p_en
    assert "Output hygiene: include the final step exactly once inside the numbered list; do not echo or restate it as a standalone line after the list." in p_en

    p_fr, _ = playground.build_messages(
        "What are all the proper steps in order to test an API in a professional manner, in French?"
    )
    assert "Preferred final step title (English): Report Defects, Retest Fixes, and Run Regression." in p_fr
    assert "Preferred final step title (French): Reporter les défauts, retester les correctifs et lancer la régression." in p_fr
    assert "Output hygiene: include the final step exactly once inside the numbered list; do not echo or restate it as a standalone line after the list." in p_fr


def test_increment2g_full_list_contract_prevents_duplicate_final_step_echo_en_fr():
    """Increment 2G: full-list contract explicitly forbids duplicate final-step echo in EN/FR."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    p_en, _ = playground.build_messages(
        "What are all the proper steps in order to test an API in a professional manner?"
    )
    assert "with 4-6 high-impact operator steps for a typical API-testing workflow" in p_en
    assert "Preferred final step title (English): Report Defects, Retest Fixes, and Run Regression." in p_en
    assert "Output hygiene: include the final step exactly once inside the numbered list; do not echo or restate it as a standalone line after the list." in p_en
    assert "Hard no-postscript rule: output only the numbered list; after the last list item, output nothing else (no paragraph, no summary, no standalone restatement)." in p_en

    p_fr, _ = playground.build_messages(
        "What are all the proper steps in order to test an API in a professional manner, en français ?"
    )
    assert "with 4-6 high-impact operator steps for a typical API-testing workflow" in p_fr
    assert "Preferred final step title (French): Reporter les défauts, retester les correctifs et lancer la régression." in p_fr
    assert "Output hygiene: include the final step exactly once inside the numbered list; do not echo or restate it as a standalone line after the list." in p_fr
    assert "Hard no-postscript rule: output only the numbered list; after the last list item, output nothing else (no paragraph, no summary, no standalone restatement)." in p_fr


def test_increment2f_final_step_elaboration_contract_mentions_retest_and_regression():
    """Increment 2F: final step elaboration prompt requires defect reporting + retest + targeted regression."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I2F_STEP1\n2. I2F_STEP2\n3. I2F_STEP3\n4. I2F_STEP4\n5. I2F_STEP5\n"
    playground.append_recent_answer_history(lst, user_input=q)
    p5, _ = playground.build_messages("Give me step 5 only.")
    assert "I2F_STEP5" in _inc1_indexed_step_line(p5, 5, 5)
    assert "Final-step clarity requirement: explicitly include defect reporting, retesting fixes, and targeted regression testing." in p5


def test_increment2b_step_prompts_include_operator_quality_focus_english_and_french():
    """Increment 2B: step prompts carry operator-focused checklist and preserve language behavior."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I2B_ONE\n2. I2B_TWO\n3. I2B_THREE\n4. I2B_FOUR\n"
    playground.append_recent_answer_history(lst, user_input=q)

    p1, _ = playground.build_messages("Start with number 1.")
    assert "I2B_ONE" in _inc1_indexed_step_line(p1, 1, 4)
    assert "Default step output format (concise): Title | What it means | Why it matters | One concrete API-testing example | What Jessy should do next." in p1
    assert "Operator-focus checklist for this step: include concrete endpoint thinking, auth/headers, expected status codes, payload/response validation, and practical execution evidence" in p1

    playground.append_recent_answer_history("i2b-r1", user_input="Start with number 1.")
    p2, _ = playground.build_messages("Continue.")
    assert "I2B_TWO" in _inc1_indexed_step_line(p2, 2, 4)
    assert "I2B_THREE" not in _inc1_indexed_step_line(p2, 2, 4)

    playground.append_recent_answer_history("i2b-r2", user_input="Continue.")
    p3, _ = playground.build_messages("Next.")
    assert "I2B_THREE" in _inc1_indexed_step_line(p3, 3, 4)
    assert "I2B_TWO" not in _inc1_indexed_step_line(p3, 3, 4)

    playground.append_recent_answer_history("i2b-r3", user_input="Next.")
    pex, _ = playground.build_messages("Explain step 2.")
    assert "I2B_TWO" in _inc1_indexed_step_line(pex, 2, 4)
    assert "Explain-step request: add one extra clarifying sentence" in pex

    pfr, _ = playground.build_messages("Explain step 2 in French.")
    assert "OUTPUT LANGUAGE" in pfr and "French (français)" in pfr
    assert "I2B_TWO" in _inc1_indexed_step_line(pfr, 2, 4)
    assert "Operator-focus checklist for this step: include concrete endpoint thinking, auth/headers, expected status codes, payload/response validation, and practical execution evidence" in pfr

    ptitle, _ = playground.build_messages("Next en français, but only the title")
    assert "OUTPUT LANGUAGE" in ptitle and "French (français)" in ptitle
    assert "Constraint override: return only the step title line for this turn." in ptitle

    pshort, _ = playground.build_messages("Continue in English, keep it short")
    assert "OUTPUT LANGUAGE" in pshort and "English" in pshort
    assert "Constraint override: keep the response short (2-3 compact lines) while preserving meaning." in pshort


def test_increment2d_elaboration_contract_english_no_repeat_and_expand():
    """Increment 2D: elaboration turns must expand beyond list line and avoid verbatim repeat."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I2D_SCOPE_LINE\n2. I2D_CASES_LINE\n3. I2D_EXEC_LINE\n4. I2D_REPORT_LINE\n"
    playground.append_recent_answer_history(lst, user_input=q)

    p1, _ = playground.build_messages("Start with number 1.")
    assert "I2D_SCOPE_LINE" in _inc1_indexed_step_line(p1, 1, 4)
    assert "Elaboration anti-repeat rule: do not repeat the original step line verbatim; expand it with new practical detail." in p1
    assert "For elaboration turns, ensure the response adds these elements (concise): What it means | Why it matters | One concrete API-testing example | What Jessy should do next." in p1
    playground.append_recent_answer_history("i2d-r1", user_input="Start with number 1.")

    p2, _ = playground.build_messages("Continue.")
    assert "I2D_CASES_LINE" in _inc1_indexed_step_line(p2, 2, 4)
    assert "Elaboration anti-repeat rule: do not repeat the original step line verbatim; expand it with new practical detail." in p2
    playground.append_recent_answer_history("i2d-r2", user_input="Continue.")

    p_explain, _ = playground.build_messages("Explain step 2.")
    assert "I2D_CASES_LINE" in _inc1_indexed_step_line(p_explain, 2, 4)
    assert "Explain-step request: add one extra clarifying sentence beyond basic elaboration" in p_explain


def test_increment2d_elaboration_contract_french_and_short_constraints():
    """Increment 2D: same anti-repeat expansion contract in French and with short/title constraints."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. I2D_FR_ONE\n2. I2D_FR_TWO\n3. I2D_FR_THREE\n4. I2D_FR_FOUR\n"
    playground.append_recent_answer_history(lst, user_input=q)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("fr-r1", user_input="Start with number 1.")

    p_fr, _ = playground.build_messages("Continue en français.")
    assert "OUTPUT LANGUAGE" in p_fr and "French (français)" in p_fr
    assert "I2D_FR_TWO" in _inc1_indexed_step_line(p_fr, 2, 4)
    assert "Elaboration anti-repeat rule: do not repeat the original step line verbatim; expand it with new practical detail." in p_fr
    playground.append_recent_answer_history("fr-r2", user_input="Continue en français.")

    p_short, _ = playground.build_messages("Continue in English, keep it short")
    assert "OUTPUT LANGUAGE" in p_short and "English" in p_short
    assert "Constraint override: keep the response short (2-3 compact lines) while preserving meaning." in p_short
    assert "For elaboration turns, ensure the response adds these elements (concise): What it means | Why it matters | One concrete API-testing example | What Jessy should do next." in p_short

    p_title, _ = playground.build_messages("Next en français, title only")
    assert "OUTPUT LANGUAGE" in p_title and "French (français)" in p_title
    assert "Constraint override: return only the step title line for this turn." in p_title


def test_start_with_number_sets_cursor_correctly():
    """Increment 8: Start with number N initializes cursor so Continue returns N+1, not N+2."""
    reset_agent_state()
    playground.clear_recent_answer_session()

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    q_list = "What are all the proper steps in order to test an API in a professional manner?"
    lst = (
        "1. START_ALIGN_ONE\n"
        "2. START_ALIGN_TWO\n"
        "3. START_ALIGN_THREE\n"
    )
    playground.append_recent_answer_history(lst, user_input=q_list)
    p1, _ = playground.build_messages("Start with number 1.")
    assert "START_ALIGN_ONE" in _indexed_step_line(p1, 1, 3)
    assert playground.get_sequence_step_cursor() == 1
    assert playground.get_last_rendered_step_index() == 1
    playground.append_recent_answer_history("reply1", user_input="Start with number 1.")
    p2, _ = playground.build_messages("Continue")
    assert "START_ALIGN_TWO" in _indexed_step_line(p2, 2, 3)
    assert "START_ALIGN_THREE" not in _indexed_step_line(p2, 2, 3)
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2


def test_next_after_continue_returns_step_three_no_skip():
    """Increment 9: Next must advance one step from the same base as Continue (no jump to 4)."""
    reset_agent_state()
    playground.clear_recent_answer_session()

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    q_list = "What are all the proper steps in order to test an API in a professional manner?"
    lst = (
        "1. NEXT_BASE_ONE\n"
        "2. NEXT_BASE_TWO\n"
        "3. NEXT_BASE_THREE\n"
        "4. NEXT_BASE_FOUR\n"
    )
    playground.append_recent_answer_history(lst, user_input=q_list)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("a1", user_input="Start with number 1.")
    playground.build_messages("Continue")
    playground.append_recent_answer_history("a2", user_input="Continue")
    p_next, _ = playground.build_messages("Next")
    line = _indexed_step_line(p_next, 3, 4)
    assert "NEXT_BASE_THREE" in line
    assert "NEXT_BASE_FOUR" not in line
    assert playground.get_sequence_step_cursor() == 3
    assert playground.get_last_rendered_step_index() == 3


def test_append_stores_multi_step_frame_resets_last_rendered_with_cursor_increment_10():
    """New multi-step frames from a full-list append must clear last_rendered, not only cursor."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    q_list = "What are all the proper steps in order to test an API in a professional manner?"
    playground.append_recent_answer_history("1. A\n2. B\n3. C\n", user_input=q_list)
    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("r1", user_input="Start with number 1.")
    playground.build_messages("Continue")
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2
    playground.append_recent_answer_history(
        "1. Xx\n2. Yy\n",
        user_input=q_list,
    )
    assert playground.get_sequence_step_cursor() == 0
    assert playground.get_last_rendered_step_index() == 0


def test_duplicate_reanchor_step_one_then_continue_next_increment_10():
    """Full list → elaborate step 1 → Start with 1 again → Continue is 2, Next is 3 (no skip)."""
    reset_agent_state()
    playground.clear_recent_answer_session()

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    lines = [
        "Review the API contract and authentication model.",
        "Define explicit acceptance criteria and negative cases.",
        "Set up isolated test environments and data fixtures.",
        "Create reusable client helpers for auth and headers.",
        "Exercise happy-path requests with representative payloads.",
        "Validate HTTP status codes and error mapping behavior.",
        "Assert response schema, types, and required fields strictly.",
        "Cover pagination, filtering, and idempotency where applicable.",
        "Run concurrency and rate-limit behavior checks safely.",
        "Measure latency and basic performance thresholds on critical paths.",
        "Add security checks for injection, auth bypass, and sensitive data leaks.",
        "Automate the suite in CI with deterministic reporting and artifacts.",
    ]
    playground.append_recent_answer_history("\n".join(lines))
    q_full = (
        "Please, one by one, not all in the same reply, elaborate on those 12 points, "
        "starting with number 1. Only include number 1, so if I have questions I can ask please."
    )
    p1, _ = playground.build_messages(q_full)
    assert "INDEXED STEP CONTENT" in p1
    assert "Step 1 of 12:" in p1
    assert playground.get_sequence_step_cursor() == 1
    assert playground.get_last_rendered_step_index() == 1

    playground.append_recent_answer_history("Narration for the first point only.", user_input=q_full)
    p2, _ = playground.build_messages("Start with number 1.")
    assert "Step 1 of 12:" in p2
    assert playground.get_sequence_step_cursor() == 1
    assert playground.get_last_rendered_step_index() == 1

    playground.append_recent_answer_history("Again step one summary.", user_input="Start with number 1.")
    p3, _ = playground.build_messages("Continue.")
    line2 = _indexed_step_line(p3, 2, 12)
    assert "Define explicit acceptance criteria and negative cases." in line2
    assert "Create reusable client helpers" not in line2
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2

    playground.append_recent_answer_history("Step two reply.", user_input="Continue.")
    p4, _ = playground.build_messages("Next")
    line3 = _indexed_step_line(p4, 3, 12)
    assert "Set up isolated test environments and data fixtures." in line3
    assert playground.get_sequence_step_cursor() == 3
    assert playground.get_last_rendered_step_index() == 3


def test_increment_14_duplicate_start_with_number_one_resyncs_cursor_and_last_rendered():
    """Re-show step 1 must pin cursor and last_rendered to 1 so Continue→2, Next→3."""
    reset_agent_state()
    playground.clear_recent_answer_session()

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    q_list = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. INC14_ONE\n2. INC14_TWO\n3. INC14_THREE\n"
    playground.append_recent_answer_history(lst, user_input=q_list)
    playground.build_messages("Start with number 1.")
    assert playground.get_sequence_step_cursor() == playground.get_last_rendered_step_index() == 1
    playground.append_recent_answer_history("r1", user_input="Start with number 1.")
    playground.build_messages("Start with number 1.")
    assert playground.get_sequence_step_cursor() == playground.get_last_rendered_step_index() == 1
    playground.append_recent_answer_history("r1b", user_input="Start with number 1.")
    p2, _ = playground.build_messages("Continue.")
    assert "INC14_TWO" in _indexed_step_line(p2, 2, 3)
    assert playground.get_sequence_step_cursor() == playground.get_last_rendered_step_index() == 2
    playground.append_recent_answer_history("r2", user_input="Continue.")
    p3, _ = playground.build_messages("Next")
    assert "INC14_THREE" in _indexed_step_line(p3, 3, 3)
    assert playground.get_sequence_step_cursor() == playground.get_last_rendered_step_index() == 3


def test_one_by_one_entry_only_include_anchors_before_stray_step_number_increment_11():
    """Pace + only-include must initialize at N; generic must not bind an earlier step|number."""
    reset_agent_state()
    playground.clear_recent_answer_session()

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    lines = [
        "Review the API contract and authentication model.",
        "Define explicit acceptance criteria and negative cases.",
        "Set up isolated test environments and data fixtures.",
        "Create reusable client helpers for auth and headers.",
        "Exercise happy-path requests with representative payloads.",
        "Validate HTTP status codes and error mapping behavior.",
        "Assert response schema, types, and required fields strictly.",
        "Cover pagination, filtering, and idempotency where applicable.",
        "Run concurrency and rate-limit behavior checks safely.",
        "Measure latency and basic performance thresholds on critical paths.",
        "Add security checks for injection, auth bypass, and sensitive data leaks.",
        "Automate the suite in CI with deterministic reporting and artifacts.",
    ]
    playground.append_recent_answer_history("\n".join(lines))
    q = (
        "First re-read step 2 and number 3 in the list for context. "
        "Please, one by one, not all in the same reply, elaborate on those 12 points. "
        "Only include number 1, so I can follow up after."
    )
    p1, _ = playground.build_messages(q)
    assert "INDEXED STEP CONTENT" in p1
    line1 = _indexed_step_line(p1, 1, 12)
    assert "Review the API contract and authentication model." in line1
    assert "Define explicit acceptance criteria and negative cases." not in line1
    assert playground.get_sequence_step_cursor() == 1
    assert playground.get_last_rendered_step_index() == 1

    playground.append_recent_answer_history("Narration for point one.", user_input=q)
    p2, _ = playground.build_messages("Continue.")
    assert "Step 2 of 12:" in p2
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2

    playground.append_recent_answer_history("Narration for point two.", user_input="Continue.")
    p3, _ = playground.build_messages("Next")
    assert "Step 3 of 12:" in p3
    assert playground.get_sequence_step_cursor() == 3
    assert playground.get_last_rendered_step_index() == 3


def test_increment_12_cursor_matches_last_rendered_after_each_indexed_step():
    """Continue/Next advance from last_rendered only; cursor stays aligned after each display."""
    reset_agent_state()
    playground.clear_recent_answer_session()

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    q_list = "What are all the proper steps in order to test an API in a professional manner?"
    lst = "1. INC12_STEP_ONE\n2. INC12_STEP_TWO\n3. INC12_STEP_THREE\n"
    playground.append_recent_answer_history(lst, user_input=q_list)
    p1, _ = playground.build_messages("Start with number 1.")
    assert "INC12_STEP_ONE" in _indexed_step_line(p1, 1, 3)
    assert playground.get_sequence_step_cursor() == playground.get_last_rendered_step_index() == 1

    playground.append_recent_answer_history("r1", user_input="Start with number 1.")
    p2, _ = playground.build_messages("Continue.")
    assert "INC12_STEP_TWO" in _indexed_step_line(p2, 2, 3)
    assert playground.get_sequence_step_cursor() == playground.get_last_rendered_step_index() == 2

    playground.append_recent_answer_history("r2", user_input="Continue.")
    p3, _ = playground.build_messages("Next")
    assert "INC12_STEP_THREE" in _indexed_step_line(p3, 3, 3)
    assert playground.get_sequence_step_cursor() == playground.get_last_rendered_step_index() == 3


def test_increment_13_critical_endpoints_list_frame_and_next_after_parasite():
    """Full list frame keeps 4 steps; bare Next must not bind a short numbered aside (live Inc 13)."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    from services import journal_service

    q = "What are all the proper steps in order to test an API in a professional manner?"
    lst = (
        "1. Identify Critical Endpoints\n"
        "2. Define Test Cases\n"
        "3. Set Up the Test Environment\n"
        "4. Execute Tests\n"
    )
    extracted = journal_service.extract_indexed_steps_from_text(lst)
    assert len(extracted) == 4
    step3 = next(s for s in extracted if int(s["index"]) == 3)
    assert step3["content"] == "Set Up the Test Environment"

    playground.append_recent_answer_history(lst, user_input=q)
    frame = playground.recent_answer_step_frames[-1]
    assert len(frame) == 4
    assert next(s for s in frame if int(s["index"]) == 3)["content"] == "Set Up the Test Environment"

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    playground.build_messages("Start with number 1.")
    playground.append_recent_answer_history("r1", user_input="Start with number 1.")
    playground.build_messages("Continue")
    playground.append_recent_answer_history("r2", user_input="Continue")
    # Numbered aside stored as a 1-item frame (store_indexed default True when user_input omitted).
    playground.append_recent_answer_history("Closing thought.\n\n1. lone\n")
    p_next, _ = playground.build_messages("Next")
    line3 = _indexed_step_line(p_next, 3, 4)
    assert "Set Up the Test Environment" in line3
    assert "Execute Tests" not in line3
    assert playground.get_sequence_step_cursor() == playground.get_last_rendered_step_index() == 3


def test_increment_16_exact_transcript_one_by_one_start_continue_next_regression():
    """Exact transcript coverage: full list -> one-by-one(1) -> start 1 -> continue -> next."""
    reset_agent_state()
    playground.clear_recent_answer_session()

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    q0 = "What are all the proper steps in order to test an API in a professional manner?"
    assistant_full_list = (
        "1. Identify Critical Endpoints\n"
        "2. Define Test Cases\n"
        "3. Set Up the Test Environment\n"
        "4. Execute Tests\n"
    )
    playground.append_recent_answer_history(assistant_full_list, user_input=q0)

    q1 = (
        "Please, one by one, not all in the same reply, elaborate on those 4 points, "
        "starting with number 1. Only include number 1, so if I have questions I can ask please."
    )
    p1, _ = playground.build_messages(q1)
    assert "Identify Critical Endpoints" in _indexed_step_line(p1, 1, 4)
    assert playground.get_sequence_step_cursor() == 1
    assert playground.get_last_rendered_step_index() == 1
    playground.append_recent_answer_history("Step 1 of 4: Identify Critical Endpoints", user_input=q1)

    q2 = "Start with number 1"
    p2, _ = playground.build_messages(q2)
    assert "Identify Critical Endpoints" in _indexed_step_line(p2, 1, 4)
    assert playground.get_sequence_step_cursor() == 1
    assert playground.get_last_rendered_step_index() == 1
    playground.append_recent_answer_history("Step 1 of 4: Identify Critical Endpoints", user_input=q2)

    q3 = "Continue"
    p3, _ = playground.build_messages(q3)
    assert "Define Test Cases" in _indexed_step_line(p3, 2, 4)
    assert playground.get_sequence_step_cursor() == 2
    assert playground.get_last_rendered_step_index() == 2
    playground.append_recent_answer_history("Step 2 of 4: Define Test Cases", user_input=q3)

    q4 = "Next"
    p4, _ = playground.build_messages(q4)
    assert "Set Up the Test Environment" in _indexed_step_line(p4, 3, 4)
    assert playground.get_sequence_step_cursor() == 3
    assert playground.get_last_rendered_step_index() == 3


def test_explanatory_template_isolation_waives_progress_runtime_for_api_guidance():
    """INTERACTION-04: general API testing explanation must not append RUNTIME-03 Progress/Risks tail."""
    reset_agent_state()
    q = (
        "Describe contract testing strategies for HTTP APIs in microservices, "
        "including how consumer-driven contracts differ from schema-only checks."
    )
    prompt, _ = playground.build_messages(q)
    assert "Template isolation (INTERACTION-04):" in prompt
    assert "Category integrity (RUNTIME-04):" not in prompt
    assert "Begin your reply with the first section header line: Progress:" not in prompt


def test_sequence_discipline_mode_anchors_to_recent_unnumbered_ordered_steps():
    reset_agent_state()
    playground.clear_recent_answer_session()
    playground.append_recent_answer_history(
        "The proper sequence includes understanding API documentation, defining test cases, checking response status codes, validating response body data, performing performance and security testing, and automating tests."
    )
    q = "Please, one by one, not all in the same reply, elaborate on those 7 points, starting with number 1."
    prompt, _ = playground.build_messages(q)
    assert "SEQUENCE DISCIPLINE MODE:" in prompt
    assert "Requested target step: 1. Respond with only step 1." in prompt
    assert "Do NOT ask for clarification when the prior ordered/list-like answer exists." in prompt
    assert "REASONING OUTPUT MODE (REASONING-06 gate active):" not in prompt
    assert "CLARIFY-FIRST (UNDEFINED IMPLEMENT/BUILD TARGET):" not in prompt


def test_all_proper_steps_request_prefers_numbered_list_output():
    reset_agent_state()
    q = "What are all the proper steps in order to test an API in a professional manner?"
    prompt, _ = playground.build_messages(q)
    assert "ORDERED STEPS OUTPUT PREFERENCE" in prompt
    assert "full multi-step list" in prompt.lower()
    assert "SEQUENCE DISCIPLINE MODE:" not in prompt
    assert "Prefer an explicit numbered list" in prompt


def test_full_steps_api_question_not_one_step_mode_and_indexed_frames_ignore_prior_advisory():
    """After Increment 6: full-list API question must not inherit sequence/continuation from a prior short checklist."""
    reset_agent_state()
    playground.clear_recent_answer_session()
    playground.append_recent_answer_history(
        "Test for: status codes, response body, headers, and error cases.",
        user_input="Quick reminder: what should I sanity-check on an API response?",
    )
    q = "What are all the proper steps in order to test an API in a professional manner?"
    prompt, _ = playground.build_messages(q)
    assert "ORDERED STEPS OUTPUT PREFERENCE" in prompt
    assert "SEQUENCE DISCIPLINE MODE:" not in prompt
    assert "Recent-answer follow-up type: continuation" not in prompt
    sim = (
        "1. PLAN_SCOPE_UNIQUE_X\n"
        "2. DESIGN_CASES_UNIQUE_Y\n"
        "3. EXECUTE_RUNS_UNIQUE_Z\n"
        "4. VALIDATE_RESULTS_UNIQUE_W\n"
    )
    playground.append_recent_answer_history(sim, user_input=q)
    assert playground.recent_answer_step_frames[-1] is not None
    assert len(playground.recent_answer_step_frames[-1]) >= 4
    assert playground.recent_answer_step_frames[-2] is None
    p2, _ = playground.build_messages("step 2")

    def _indexed_step_line(prompt: str, step_n: int, total: int) -> str:
        prefix = f"Step {step_n} of {total}:"
        for line in prompt.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        raise AssertionError(f"missing indexed line {prefix!r}")

    line = _indexed_step_line(p2, 2, 4)
    assert "DESIGN_CASES_UNIQUE_Y" in line
    assert "status codes" not in line.lower()


def test_build_messages_adds_clarification_guidance_only_for_clarification():
    reset_agent_state()
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
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
    playground.clear_recent_answer_session()
    playground.append_recent_answer_history(
        "Routing misclassification in detect_subtarget can trigger strict-mode gating."
    )
    prompt, _ = playground.build_messages("What is the weather this weekend?")
    assert "Recent-answer follow-up type:" not in prompt


def test_build_messages_adds_contradiction_guidance_and_self_correction_rule():
    reset_agent_state()
    playground.clear_recent_answer_session()
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
        ("packaging11_full_package_includes_current_risks_block", test_packaging11_full_package_includes_current_risks_block),
        ("packaging11_compact_package_includes_current_risks_block", test_packaging11_compact_package_includes_current_risks_block),
        ("packaging11_current_risks_follow_first_qualifying_packaged_order", test_packaging11_current_risks_follow_first_qualifying_packaged_order),
        ("packaging11_risks_block_after_priorities_before_snapshot_body", test_packaging11_risks_block_after_priorities_before_snapshot_body),
        ("packaging11_no_risk_keywords_preserves_package_without_risks_section", test_packaging11_no_risk_keywords_preserves_package_without_risks_section),
        ("packaging11_empty_package_returns_empty_string", test_packaging11_empty_package_returns_empty_string),
        ("packaging11_priorities_block_unchanged_for_plain_rows", test_packaging11_priorities_block_unchanged_for_plain_rows),
        ("packaging12_norisk_token_does_not_trigger_risks_block", test_packaging12_norisk_token_does_not_trigger_risks_block),
        ("packaging12_no_problem_idiom_does_not_trigger", test_packaging12_no_problem_idiom_does_not_trigger),
        ("packaging12_this_is_a_risk_triggers", test_packaging12_this_is_a_risk_triggers),
        ("packaging12_critical_bug_found_triggers", test_packaging12_critical_bug_found_triggers),
        ("packaging12_debugging_does_not_trigger_bug_keyword", test_packaging12_debugging_does_not_trigger_bug_keyword),
        ("packaging12_risks_order_unchanged_vs_packaging11_shape", test_packaging12_risks_order_unchanged_vs_packaging11_shape),
        ("packaging13_full_package_includes_current_decisions_block", test_packaging13_full_package_includes_current_decisions_block),
        ("packaging13_compact_package_includes_current_decisions_block", test_packaging13_compact_package_includes_current_decisions_block),
        ("packaging13_current_decisions_follow_first_qualifying_order", test_packaging13_current_decisions_follow_first_qualifying_order),
        ("packaging13_decisions_after_risks_before_snapshot_body", test_packaging13_decisions_after_risks_before_snapshot_body),
        ("packaging13_no_decision_keywords_omits_decisions_block", test_packaging13_no_decision_keywords_omits_decisions_block),
        ("packaging13_empty_package_returns_empty_string", test_packaging13_empty_package_returns_empty_string),
        ("packaging14_full_package_includes_current_progress_block", test_packaging14_full_package_includes_current_progress_block),
        ("packaging14_compact_package_includes_current_progress_block", test_packaging14_compact_package_includes_current_progress_block),
        ("packaging14_current_progress_follow_first_qualifying_order", test_packaging14_current_progress_follow_first_qualifying_order),
        ("packaging14_progress_after_decisions_before_snapshot_body", test_packaging14_progress_after_decisions_before_snapshot_body),
        ("packaging14_no_progress_keywords_omits_progress_block", test_packaging14_no_progress_keywords_omits_progress_block),
        ("packaging14_empty_package_returns_empty_string", test_packaging14_empty_package_returns_empty_string),
        ("packaging15_full_package_includes_next_steps_block", test_packaging15_full_package_includes_next_steps_block),
        ("packaging15_compact_package_includes_next_steps_block", test_packaging15_compact_package_includes_next_steps_block),
        ("packaging15_next_steps_follow_first_qualifying_order", test_packaging15_next_steps_follow_first_qualifying_order),
        ("packaging15_progress_before_next_steps_before_snapshot_body", test_packaging15_progress_before_next_steps_before_snapshot_body),
        ("packaging15_no_next_steps_keywords_omits_next_steps_block", test_packaging15_no_next_steps_keywords_omits_next_steps_block),
        ("packaging15_empty_package_returns_empty_string", test_packaging15_empty_package_returns_empty_string),
        ("runtime01_prompt_includes_execution_enforcement", test_runtime01_prompt_includes_execution_enforcement),
        ("runtime02_prompt_enforces_no_preamble", test_runtime02_prompt_enforces_no_preamble),
        ("runtime03_prompt_enforces_structure", test_runtime03_prompt_enforces_structure),
        ("runtime04_prompt_enforces_category_integrity", test_runtime04_prompt_enforces_category_integrity),
        ("runtime05_prompt_excludes_in_progress_language", test_runtime05_prompt_excludes_in_progress_language),
        ("runtime06_prompt_enforces_invalidity_constraints", test_runtime06_prompt_enforces_invalidity_constraints),
        ("reasoning01_prompt_enforces_missing_information_admission", test_reasoning01_prompt_enforces_missing_information_admission),
        ("reasoning02_prompt_blocks_completion_by_invention", test_reasoning02_prompt_blocks_completion_by_invention),
        ("reasoning03_prompt_enforces_explanation_structure", test_reasoning03_prompt_enforces_explanation_structure),
        ("reasoning04_forces_structure_over_runtime", test_reasoning04_forces_structure_over_runtime),
        ("reasoning05_makes_reasoning_structure_mandatory", test_reasoning05_makes_reasoning_structure_mandatory),
        ("reasoning06_routes_known_failure_prompts_to_reasoning_mode", test_reasoning06_routes_known_failure_prompts_to_reasoning_mode),
        ("reasoning06_preserves_non_reasoning_action_path", test_reasoning06_preserves_non_reasoning_action_path),
        ("reasoning06_does_not_remove_existing_reasoning_rules", test_reasoning06_does_not_remove_existing_reasoning_rules),
        ("reasoning06_prompt_builder_embeds_selected_structure", test_reasoning06_prompt_builder_embeds_selected_structure),
        ("reasoning061_routes_unknown_plan_prompt_to_reasoning_mode", test_reasoning061_routes_unknown_plan_prompt_to_reasoning_mode),
        ("reasoning062_strengthens_unknown_plan_routing_in_final_prompt", test_reasoning062_strengthens_unknown_plan_routing_in_final_prompt),
        ("interaction01_routes_simple_conversation_to_conversation_mode", test_interaction01_routes_simple_conversation_to_conversation_mode),
        ("interaction01_reasoning_mode_still_wins", test_interaction01_reasoning_mode_still_wins),
        ("interaction01_preserves_action_path", test_interaction01_preserves_action_path),
        ("interaction01_build_messages_contains_conversation_instructions", test_interaction01_build_messages_contains_conversation_instructions),
        ("interaction011_routes_conditional_help_tool_prompt_to_conversation_mode", test_interaction011_routes_conditional_help_tool_prompt_to_conversation_mode),
        ("interaction012_routes_clarification_prompt_to_conversation_mode", test_interaction012_routes_clarification_prompt_to_conversation_mode),
        ("memory_quality01_filters_low_signal_items", test_memory_quality01_filters_low_signal_items),
        ("memory_quality02_filters_vague_project_state_language", test_memory_quality02_filters_vague_project_state_language),
        ("memory_quality03_blocks_false_high_signal_rows", test_memory_quality03_blocks_false_high_signal_rows),
        ("memory_quality04_filters_mixed_contaminated_rows", test_memory_quality04_filters_mixed_contaminated_rows),
        ("memory_quality05_blocks_contamination_patterns", test_memory_quality05_blocks_contamination_patterns),
        ("memory_quality05_allows_grounded_memory", test_memory_quality05_allows_grounded_memory),
        ("memory_quality05_does_not_empty_all_memory", test_memory_quality05_does_not_empty_all_memory),
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
        (
            "run_tool1_system_eval_operator_default_adapter_prompt_lane_fails_cleanly",
            test_run_tool1_system_eval_operator_default_adapter_prompt_lane_fails_cleanly,
        ),
        (
            "run_tool1_system_eval_operator_default_adapter_keeps_http_path",
            test_run_tool1_system_eval_operator_default_adapter_keeps_http_path,
        ),
        (
            "run_tool2_prompt_response_eval_rejects_non_prompt_lane",
            test_run_tool2_prompt_response_eval_rejects_non_prompt_lane,
        ),
        (
            "run_tool2_prompt_response_eval_missing_suite_logs_failure_record",
            test_run_tool2_prompt_response_eval_missing_suite_logs_failure_record,
        ),
        (
            "run_tool2_prompt_response_eval_invalid_json_logs_failure_record",
            test_run_tool2_prompt_response_eval_invalid_json_logs_failure_record,
        ),
        (
            "run_tool2_prompt_response_eval_invalid_timeout_rejected_and_logged",
            test_run_tool2_prompt_response_eval_invalid_timeout_rejected_and_logged,
        ),
        (
            "run_tool2_prompt_response_eval_timeout_bool_rejected",
            test_run_tool2_prompt_response_eval_timeout_bool_rejected,
        ),
        (
            "run_tool2_prompt_response_eval_default_adapter_passes",
            test_run_tool2_prompt_response_eval_default_adapter_passes,
        ),
        (
            "run_tool2_prompt_response_eval_artifact_failure_is_reported_and_logged",
            test_run_tool2_prompt_response_eval_artifact_failure_is_reported_and_logged,
        ),
        (
            "run_tool2_prompt_response_eval_execution_exception_is_reported_and_logged",
            test_run_tool2_prompt_response_eval_execution_exception_is_reported_and_logged,
        ),
        (
            "tool2_prompt_response_logging_includes_prompt_fields",
            test_tool2_prompt_response_logging_includes_prompt_fields,
        ),
        (
            "tool2_logging_does_not_depend_on_tool1_build_helpers",
            test_tool2_logging_does_not_depend_on_tool1_build_helpers,
        ),
        (
            "tool2_prompt_response_sample_suite_shape_validates",
            test_tool2_prompt_response_sample_suite_shape_validates,
        ),
        (
            "run_tool1_system_eval_operator_artifact_failure_is_reported_and_logged",
            test_run_tool1_system_eval_operator_artifact_failure_is_reported_and_logged,
        ),
        (
            "run_tool1_system_eval_operator_execution_exception_is_reported_and_logged",
            test_run_tool1_system_eval_operator_execution_exception_is_reported_and_logged,
        ),
        (
            "run_tool1_system_eval_operator_failure_bundle_contract",
            test_run_tool1_system_eval_operator_failure_bundle_contract,
        ),
        (
            "run_tool2_prompt_response_eval_failure_bundle_contract",
            test_run_tool2_prompt_response_eval_failure_bundle_contract,
        ),
        (
            "run_tool3_regression_eval_rejects_non_regression_lane",
            test_run_tool3_regression_eval_rejects_non_regression_lane,
        ),
        (
            "run_tool3_regression_eval_scaffold_contract_on_regression_lane",
            test_run_tool3_regression_eval_scaffold_contract_on_regression_lane,
        ),
        (
            "run_tool3_regression_eval_does_not_depend_on_tool1_operator",
            test_run_tool3_regression_eval_does_not_depend_on_tool1_operator,
        ),
        (
            "run_tool3_regression_eval_does_not_depend_on_tool2_operator",
            test_run_tool3_regression_eval_does_not_depend_on_tool2_operator,
        ),
        (
            "run_tool3_regression_eval_execution_failure_contract",
            test_run_tool3_regression_eval_execution_failure_contract,
        ),
        (
            "run_tool3_regression_eval_artifact_failure_is_reported_and_logged",
            test_run_tool3_regression_eval_artifact_failure_is_reported_and_logged,
        ),
        (
            "run_tool3_regression_eval_command_invocation_failure_is_reported_and_logged",
            test_run_tool3_regression_eval_command_invocation_failure_is_reported_and_logged,
        ),
        (
            "run_tool3_regression_eval_command_timeout_is_reported_and_logged",
            test_run_tool3_regression_eval_command_timeout_is_reported_and_logged,
        ),
        (
            "run_tool3_regression_eval_failure_bundle_contract",
            test_run_tool3_regression_eval_failure_bundle_contract,
        ),
        ("tool1_run_log_jsonl_written_for_suite_success_and_failure", test_tool1_run_log_jsonl_written_for_suite_success_and_failure),
        (
            "run_tool1_system_eval_operator_invalid_json_logs_failure_record",
            test_run_tool1_system_eval_operator_invalid_json_logs_failure_record,
        ),
        (
            "tool1_run_log_single_request_redacts_sensitive_fields",
            test_tool1_run_log_single_request_redacts_sensitive_fields,
        ),
        (
            "tool1_run_log_single_request_redacts_sensitive_fields_in_malformed_raw_text",
            test_tool1_run_log_single_request_redacts_sensitive_fields_in_malformed_raw_text,
        ),
        (
            "tool1_run_log_suite_redacts_sensitive_request_fields",
            test_tool1_run_log_suite_redacts_sensitive_request_fields,
        ),
        (
            "tool1_run_log_redacts_sensitive_tokens_in_error_and_summary_text",
            test_tool1_run_log_redacts_sensitive_tokens_in_error_and_summary_text,
        ),
        (
            "tool1_run_log_redacts_sensitive_tokens_in_failure_lines",
            test_tool1_run_log_redacts_sensitive_tokens_in_failure_lines,
        ),
        (
            "tool1_run_log_redaction_does_not_mutate_input_record",
            test_tool1_run_log_redaction_does_not_mutate_input_record,
        ),
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
        (
            "system_eval_prompt_response_lane_requires_prompt_fields",
            test_system_eval_prompt_response_lane_requires_prompt_fields,
        ),
        (
            "system_eval_prompt_response_lane_normalizes_prompt_fields",
            test_system_eval_prompt_response_lane_normalizes_prompt_fields,
        ),
        (
            "system_eval_prompt_response_lane_normalizes_not_contains_field",
            test_system_eval_prompt_response_lane_normalizes_not_contains_field,
        ),
        (
            "system_eval_prompt_response_lane_executes_with_prompt_adapter_pass",
            test_system_eval_prompt_response_lane_executes_with_prompt_adapter_pass,
        ),
        (
            "system_eval_prompt_response_lane_fails_on_forbidden_substring",
            test_system_eval_prompt_response_lane_fails_on_forbidden_substring,
        ),
        (
            "system_eval_prompt_response_lane_regex_passes",
            test_system_eval_prompt_response_lane_regex_passes,
        ),
        (
            "system_eval_prompt_response_lane_regex_fails",
            test_system_eval_prompt_response_lane_regex_fails,
        ),
        (
            "system_eval_prompt_response_lane_starts_with_passes",
            test_system_eval_prompt_response_lane_starts_with_passes,
        ),
        (
            "system_eval_prompt_response_lane_starts_with_fails",
            test_system_eval_prompt_response_lane_starts_with_fails,
        ),
        (
            "system_eval_prompt_response_lane_ends_with_passes",
            test_system_eval_prompt_response_lane_ends_with_passes,
        ),
        (
            "system_eval_prompt_response_lane_ends_with_fails",
            test_system_eval_prompt_response_lane_ends_with_fails,
        ),
        (
            "system_eval_prompt_response_lane_equals_passes",
            test_system_eval_prompt_response_lane_equals_passes,
        ),
        (
            "system_eval_prompt_response_lane_equals_fails",
            test_system_eval_prompt_response_lane_equals_fails,
        ),
        (
            "system_eval_prompt_response_lane_length_min_passes",
            test_system_eval_prompt_response_lane_length_min_passes,
        ),
        (
            "system_eval_prompt_response_lane_length_min_fails",
            test_system_eval_prompt_response_lane_length_min_fails,
        ),
        (
            "system_eval_prompt_response_lane_length_max_passes",
            test_system_eval_prompt_response_lane_length_max_passes,
        ),
        (
            "system_eval_prompt_response_lane_length_max_fails",
            test_system_eval_prompt_response_lane_length_max_fails,
        ),
        (
            "system_eval_prompt_response_lane_length_bounds_validate_when_ordered",
            test_system_eval_prompt_response_lane_length_bounds_validate_when_ordered,
        ),
        (
            "system_eval_prompt_response_lane_length_bounds_reject_inverted_range",
            test_system_eval_prompt_response_lane_length_bounds_reject_inverted_range,
        ),
        (
            "system_eval_prompt_response_lane_length_min_rejects_bool",
            test_system_eval_prompt_response_lane_length_min_rejects_bool,
        ),
        (
            "system_eval_prompt_response_lane_length_max_rejects_bool",
            test_system_eval_prompt_response_lane_length_max_rejects_bool,
        ),
        (
            "system_eval_prompt_response_fields_rejected_outside_prompt_lane",
            test_system_eval_prompt_response_fields_rejected_outside_prompt_lane,
        ),
        (
            "system_eval_prompt_input_rejected_when_lane_omitted",
            test_system_eval_prompt_input_rejected_when_lane_omitted,
        ),
        (
            "system_eval_prompt_response_lane_fails_on_missing_substring",
            test_system_eval_prompt_response_lane_fails_on_missing_substring,
        ),
        (
            "system_eval_prompt_response_lane_fails_when_prompt_adapter_missing",
            test_system_eval_prompt_response_lane_fails_when_prompt_adapter_missing,
        ),
        (
            "system_eval_prompt_response_lane_coerces_non_string_output_text",
            test_system_eval_prompt_response_lane_coerces_non_string_output_text,
        ),
        (
            "system_eval_prompt_response_lane_non_string_output_fails_cleanly",
            test_system_eval_prompt_response_lane_non_string_output_fails_cleanly,
        ),
        (
            "system_eval_prompt_response_lane_adapter_exception_fails_cleanly",
            test_system_eval_prompt_response_lane_adapter_exception_fails_cleanly,
        ),
        (
            "system_eval_prompt_response_lane_fail_fast_stops_after_first_failure",
            test_system_eval_prompt_response_lane_fail_fast_stops_after_first_failure,
        ),
        (
            "system_eval_prompt_response_lane_fail_fast_false_runs_all_cases",
            test_system_eval_prompt_response_lane_fail_fast_false_runs_all_cases,
        ),
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
        ("system_eval_case_expected_status_not_passes", test_system_eval_case_expected_status_not_passes),
        ("system_eval_case_expected_status_not_fails", test_system_eval_case_expected_status_not_fails),
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
            "write_result_artifacts_filename_includes_utc_timestamp_from_ran_at",
            test_write_result_artifacts_filename_includes_utc_timestamp_from_ran_at,
        ),
        (
            "write_result_artifacts_markdown_includes_step_results_pass",
            test_write_result_artifacts_markdown_includes_step_results_pass,
        ),
        (
            "write_result_artifacts_markdown_includes_step_results_fail",
            test_write_result_artifacts_markdown_includes_step_results_fail,
        ),
        (
            "system_eval_steps_two_step_output_contains_single_request_fields",
            test_system_eval_steps_two_step_output_contains_single_request_fields,
        ),
        (
            "system_eval_steps_structured_json_path_assertions_failures_populated",
            test_system_eval_steps_structured_json_path_assertions_failures_populated,
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
        ("system_eval_case_expected_headers_contains_passes", test_system_eval_case_expected_headers_contains_passes),
        ("system_eval_case_expected_headers_contains_fails", test_system_eval_case_expected_headers_contains_fails),
        ("system_eval_case_expected_header_exists_passes", test_system_eval_case_expected_header_exists_passes),
        ("system_eval_case_expected_header_exists_fails", test_system_eval_case_expected_header_exists_fails),
        ("system_eval_case_expected_json_absent_passes", test_system_eval_case_expected_json_absent_passes),
        ("system_eval_case_expected_json_absent_fails_when_present", test_system_eval_case_expected_json_absent_fails_when_present),
        ("system_eval_case_expected_body_not_empty_passes", test_system_eval_case_expected_body_not_empty_passes),
        ("system_eval_case_expected_body_not_empty_fails_on_empty", test_system_eval_case_expected_body_not_empty_fails_on_empty),
        ("system_eval_case_expected_body_size_bytes_max_passes", test_system_eval_case_expected_body_size_bytes_max_passes),
        ("system_eval_case_expected_body_size_bytes_max_fails", test_system_eval_case_expected_body_size_bytes_max_fails),
        ("system_eval_expected_latency_ms_max_pass", test_system_eval_expected_latency_ms_max_pass),
        ("system_eval_expected_latency_ms_max_fail", test_system_eval_expected_latency_ms_max_fail),
        ("system_eval_expected_response_time_ms_range_pass", test_system_eval_expected_response_time_ms_range_pass),
        ("system_eval_expected_response_time_ms_range_fail", test_system_eval_expected_response_time_ms_range_fail),
        ("system_eval_minimal_assertion_invalid_types_rejected", test_system_eval_minimal_assertion_invalid_types_rejected),
        ("system_eval_runner_script_smoke_with_fake_http", test_system_eval_runner_script_smoke_with_fake_http),
        ("system_eval_execute_suite_multiple_cases_mixed_results", test_system_eval_execute_suite_multiple_cases_mixed_results),
        ("system_eval_execute_suite_fail_fast_stops_after_first_failure", test_system_eval_execute_suite_fail_fast_stops_after_first_failure),
        ("system_eval_runner_script_returns_nonzero_on_failure", test_system_eval_runner_script_returns_nonzero_on_failure),
        ("system_eval_runner_script_requires_suite_argument", test_system_eval_runner_script_requires_suite_argument),
        (
            "system_eval_runner_script_missing_suite_file_nonzero",
            test_system_eval_runner_script_missing_suite_file_nonzero,
        ),
        ("system_eval_runner_script_success_prints_status_markers", test_system_eval_runner_script_success_prints_status_markers),
        ("tool1_ui_helpers_parse_and_merge_auth_headers", test_tool1_ui_helpers_parse_and_merge_auth_headers),
        (
            "tool1_ui_prepare_single_request_merges_query_and_headers",
            test_tool1_ui_prepare_single_request_merges_query_and_headers,
        ),
        (
            "tool1_prepare_single_request_substitutes_env_placeholders_BRAVE_API_KEY",
            test_tool1_prepare_single_request_substitutes_env_placeholders_BRAVE_API_KEY,
        ),
        (
            "tool1_prepare_single_request_missing_env_placeholder_errors_before_request",
            test_tool1_prepare_single_request_missing_env_placeholder_errors_before_request,
        ),
        (
            "tool1_single_request_env_placeholder_execute_suite_local_http_200",
            test_tool1_single_request_env_placeholder_execute_suite_local_http_200,
        ),
        ("tool1_ui_parse_headers_invalid_json_errors", test_tool1_ui_parse_headers_invalid_json_errors),
        (
            "tool1_ui_prepare_single_request_rejects_non_object_json_body",
            test_tool1_ui_prepare_single_request_rejects_non_object_json_body,
        ),
        (
            "tool1_ui_prepare_single_request_basic_auth_requires_username",
            test_tool1_ui_prepare_single_request_basic_auth_requires_username,
        ),
        (
            "tool1_ui_single_request_display_redacts_sensitive_headers_and_query",
            test_tool1_ui_single_request_display_redacts_sensitive_headers_and_query,
        ),
        (
            "tool1_ui_case_outcome_note_prompt_response_lane",
            test_tool1_ui_case_outcome_note_prompt_response_lane,
        ),
        (
            "tool1_assertion_surface_groups_are_disjoint_and_non_empty",
            test_tool1_assertion_surface_groups_are_disjoint_and_non_empty,
        ),
        (
            "tool1_assertion_surface_contains_expected_core_markers",
            test_tool1_assertion_surface_contains_expected_core_markers,
        ),
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