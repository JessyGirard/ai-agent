"""
Append-only JSONL log for Tool 2 prompt/response suite runs.

Path: ``logs/tool2_runs.jsonl`` under the project root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app import system_eval_run_log_common as run_log_common

TOOL2_RUN_LOG_REL_PATH = Path("logs") / "tool2_runs.jsonl"
TOOL2_RUN_LOG_SCHEMA_VERSION = 1


def tool2_run_log_path(project_root: Path | None = None) -> Path:
    root = project_root or run_log_common.PROJECT_ROOT
    return root / TOOL2_RUN_LOG_REL_PATH


def append_tool2_run_record(record: dict[str, Any], *, project_root: Path | None = None) -> tuple[bool, str | None]:
    path = tool2_run_log_path(project_root)
    return run_log_common.append_jsonl_record(path, record)


def build_tool2_run_record_suite(
    *,
    suite_path: str,
    output_dir: str,
    file_stem: str,
    fail_fast: bool,
    default_timeout_seconds: int,
    suite: dict[str, Any] | None,
    result: dict[str, Any] | None,
    artifact_paths: dict[str, Any],
    error: str | None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    rec = run_log_common.build_suite_run_record(
        suite_path=suite_path,
        output_dir=output_dir,
        file_stem=file_stem,
        fail_fast=fail_fast,
        default_timeout_seconds=default_timeout_seconds,
        suite=suite,
        result=result,
        artifact_paths=artifact_paths,
        error=error,
        run_type="tool2_suite_run",
        schema_version=TOOL2_RUN_LOG_SCHEMA_VERSION,
        project_root=project_root,
    )
    return rec


def try_log_tool2_suite_run(
    *,
    suite_path: str,
    output_dir: str,
    file_stem: str,
    fail_fast: bool,
    default_timeout_seconds: int,
    suite: dict[str, Any] | None,
    result: dict[str, Any] | None,
    artifact_paths: dict[str, Any],
    error: str | None,
    project_root: Path | None = None,
) -> str | None:
    rec = build_tool2_run_record_suite(
        suite_path=suite_path,
        output_dir=output_dir,
        file_stem=file_stem,
        fail_fast=fail_fast,
        default_timeout_seconds=default_timeout_seconds,
        suite=suite,
        result=result,
        artifact_paths=artifact_paths,
        error=error,
        project_root=project_root,
    )
    rec = run_log_common.redact_run_record(rec)
    rec["summary"] = run_log_common.compose_run_human_summary(rec)
    ok, err = append_tool2_run_record(rec, project_root=project_root)
    return None if ok else (err or "unknown logging error")

