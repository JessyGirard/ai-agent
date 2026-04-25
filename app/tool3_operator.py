"""
Operator-side scaffold for Tool 3 regression lane.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app import tool3_run_log
from core import system_eval

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TOOL3_REGRESSION_LANE = "regression"
TOOL3_COMMAND_TIMEOUT_SECONDS = 1800
TOOL3_DEFAULT_COMMAND = [sys.executable, "tests/run_regression.py"]


def _resolve_under_root(path_str: str, root: Path) -> Path:
    p = Path(path_str.strip())
    if p.is_absolute():
        return p
    return (root / p).resolve()


def _slugify(text: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (text or "").strip())
    return safe.strip("_") or "tool3_regression_run"


def _failure_bundle(*, error: str, run_log_error: str | None, run_log_path: str) -> dict:
    return {
        "ok": False,
        "result": None,
        "artifact_paths": {},
        "json_preview": "",
        "markdown_preview": "",
        "error": error,
        "run_log_error": run_log_error,
        "run_log_path": run_log_path,
    }


def _tool3_markdown_header_summary(result: dict) -> str:
    total = int(result.get("executed_cases") or 0)
    passed = int(result.get("passed_cases") or 0)
    failed = int(result.get("failed_cases") or 0)
    return (
        "# Tool 3 Regression Summary\n\n"
        f"- Total tests: {total}\n"
        f"- Passed: {passed}\n"
        f"- Failed: {failed}\n\n"
        "---\n\n"
    )


def _prepend_tool3_markdown_summary(markdown_path: Path, result: dict) -> str:
    original = markdown_path.read_text(encoding="utf-8")
    merged = _tool3_markdown_header_summary(result) + original
    markdown_path.write_text(merged, encoding="utf-8")
    return merged


def _resolve_tool3_command(command_override: str | None) -> tuple[list[str], str]:
    raw = str(command_override or "").strip()
    if not raw:
        cmd = list(TOOL3_DEFAULT_COMMAND)
        return cmd, " ".join(cmd)
    parts = shlex.split(raw, posix=(os.name != "nt"))
    if not parts:
        cmd = list(TOOL3_DEFAULT_COMMAND)
        return cmd, " ".join(cmd)
    return parts, raw


def run_tool3_regression_eval(
    suite_path: str,
    output_dir: str,
    file_stem: str = "",
    command_override: str = "",
    *,
    project_root: Path | None = None,
):
    root = project_root or PROJECT_ROOT
    run_log_path = str(tool3_run_log.tool3_run_log_path(root))
    suite_file = _resolve_under_root(suite_path, root)
    if not suite_file.is_file():
        err = f"Suite file not found: {suite_file}"
        log_err = tool3_run_log.try_log_tool3_suite_run(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=False,
            default_timeout_seconds=0,
            suite=None,
            result=None,
            artifact_paths={},
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, run_log_path=run_log_path)

    try:
        raw_suite = json.loads(suite_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        err = f"Failed to read suite JSON: {type(exc).__name__}: {exc}"
        log_err = tool3_run_log.try_log_tool3_suite_run(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=False,
            default_timeout_seconds=0,
            suite=None,
            result=None,
            artifact_paths={},
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, run_log_path=run_log_path)

    cases = raw_suite.get("cases") if isinstance(raw_suite, dict) else None
    if not isinstance(cases, list) or not cases:
        err = "Tool 3 requires a non-empty 'cases' array."
        log_err = tool3_run_log.try_log_tool3_suite_run(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=False,
            default_timeout_seconds=0,
            suite=raw_suite if isinstance(raw_suite, dict) else None,
            result=None,
            artifact_paths={},
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, run_log_path=run_log_path)

    lanes = {str((c or {}).get("lane") or "") for c in cases if isinstance(c, dict)}
    if lanes != {TOOL3_REGRESSION_LANE}:
        err = (
            "Tool 3 requires all cases to use lane='regression'. "
            f"Found lanes: {sorted(lanes)}"
        )
        log_err = tool3_run_log.try_log_tool3_suite_run(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=False,
            default_timeout_seconds=0,
            suite=raw_suite if isinstance(raw_suite, dict) else None,
            result=None,
            artifact_paths={},
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, run_log_path=run_log_path)

    started = time.perf_counter()
    cmd, cmd_label = _resolve_tool3_command(command_override)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=TOOL3_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        err = f"Regression command timed out after {TOOL3_COMMAND_TIMEOUT_SECONDS}s: {exc}"
        log_err = tool3_run_log.try_log_tool3_suite_run(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=False,
            default_timeout_seconds=0,
            suite=raw_suite if isinstance(raw_suite, dict) else None,
            result=None,
            artifact_paths={},
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, run_log_path=run_log_path)
    except Exception as exc:
        err = f"Regression command invocation failed: {type(exc).__name__}: {exc}"
        log_err = tool3_run_log.try_log_tool3_suite_run(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=False,
            default_timeout_seconds=0,
            suite=raw_suite if isinstance(raw_suite, dict) else None,
            result=None,
            artifact_paths={},
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, run_log_path=run_log_path)
    elapsed = round(time.perf_counter() - started, 3)
    ok = int(proc.returncode) == 0
    out = str(proc.stdout or "")
    err = str(proc.stderr or "")

    case_rows = []
    for idx, case in enumerate(cases):
        if not isinstance(case, dict):
            continue
        name = str(case.get("name") or f"regression_case_{idx}")
        row = {
            "name": name,
            "lane": TOOL3_REGRESSION_LANE,
            "ok": ok,
            "failures": [] if ok else [f"regression_command_failed: exit_code={proc.returncode}"],
            "command": cmd_label,
        }
        case_rows.append(row)

    finished_utc = datetime.now(timezone.utc).isoformat()
    for row in case_rows:
        row["ran_at_utc"] = finished_utc
    result = {
        "suite_name": str(raw_suite.get("suite_name") or "tool3-regression-suite"),
        "target_name": str(raw_suite.get("target_name") or "tool3-regression-target"),
        "executed_cases": len(case_rows),
        "passed_cases": len(case_rows) if ok else 0,
        "failed_cases": 0 if ok else len(case_rows),
        "ok": ok,
        "elapsed_seconds": elapsed,
        "ran_at_utc": finished_utc,
        "cases": case_rows,
        "command_exit_code": int(proc.returncode),
    }
    max_json = 14_000
    max_md = 20_000
    json_preview = out[:max_json] + "\n\n... (truncated for preview)" if len(out) > max_json else out
    markdown_preview = err[:max_md] + "\n\n... (truncated for preview)" if len(err) > max_md else err
    artifact_paths: dict = {}
    if ok:
        out_dir = _resolve_under_root(output_dir, root)
        stem = file_stem.strip() or _slugify(str(result.get("suite_name") or "tool3_regression"))
        try:
            artifact_paths = system_eval.write_result_artifacts(result, str(out_dir), file_stem=stem)
            md_path_raw = artifact_paths.get("markdown_path")
            if md_path_raw:
                md_path = Path(str(md_path_raw))
                markdown_preview = _prepend_tool3_markdown_summary(md_path, result)
                if len(markdown_preview) > max_md:
                    markdown_preview = markdown_preview[:max_md] + "\n\n... (truncated for preview)"
        except (OSError, KeyError) as exc:
            bundle_err = f"Artifact write/read failed: {type(exc).__name__}: {exc}"
            log_err = tool3_run_log.try_log_tool3_suite_run(
                suite_path=suite_path,
                output_dir=output_dir,
                file_stem=file_stem,
                fail_fast=False,
                default_timeout_seconds=0,
                suite=raw_suite if isinstance(raw_suite, dict) else None,
                result=result,
                artifact_paths={},
                error=bundle_err,
                project_root=root,
            )
            return _failure_bundle(error=bundle_err, run_log_error=log_err, run_log_path=run_log_path)
    result_bundle = {
        "ok": ok,
        "result": result,
        "artifact_paths": artifact_paths,
        "json_preview": json_preview,
        "markdown_preview": markdown_preview,
        "error": None if ok else f"Regression command failed with exit code {proc.returncode}.",
    }
    log_err = tool3_run_log.try_log_tool3_suite_run(
        suite_path=suite_path,
        output_dir=output_dir,
        file_stem=file_stem,
        fail_fast=False,
        default_timeout_seconds=0,
        suite=raw_suite if isinstance(raw_suite, dict) else None,
        result=result,
        artifact_paths=artifact_paths,
        error=result_bundle.get("error"),
        project_root=root,
    )
    result_bundle["run_log_error"] = log_err
    result_bundle["run_log_path"] = run_log_path
    return result_bundle

