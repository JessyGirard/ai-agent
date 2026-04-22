"""
Shared run-log helpers for system-eval tools.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import tool1_log_redaction

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve_path_str(path_str: str, root: Path) -> str:
    p = Path(path_str.strip())
    if p.is_absolute():
        return str(p.resolve())
    return str((root / p).resolve())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl_record(log_path: Path, record: dict[str, Any]) -> tuple[bool, str | None]:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
        return True, None
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def redact_run_record(record: dict[str, Any]) -> dict[str, Any]:
    return tool1_log_redaction.redact_tool1_record(record)


def requests_from_suite_cases(suite: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cases = suite.get("cases") if isinstance(suite, dict) else None
    if not isinstance(cases, list):
        return out
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            continue
        out.append(
            {
                "case_index": i,
                "case_name": str(case.get("name") or ""),
                "method": str(case.get("method") or ""),
                "url": str(case.get("url") or ""),
                "prompt_input": str(case.get("prompt_input") or ""),
                "expected_response_contains": list(case.get("expected_response_contains") or [])
                if isinstance(case.get("expected_response_contains"), list)
                else [],
                "expected_response_not_contains": list(case.get("expected_response_not_contains") or [])
                if isinstance(case.get("expected_response_not_contains"), list)
                else [],
                "expected_response_regex": case.get("expected_response_regex"),
                "expected_response_starts_with": case.get("expected_response_starts_with"),
                "expected_response_ends_with": case.get("expected_response_ends_with"),
                "expected_response_equals": case.get("expected_response_equals"),
                "expected_response_length_min": case.get("expected_response_length_min"),
                "expected_response_length_max": case.get("expected_response_length_max"),
                "headers": dict(case.get("headers") or {}),
                "payload": case.get("payload") if isinstance(case.get("payload"), dict) else {},
                "assertions": case.get("assertions") if isinstance(case.get("assertions"), dict) else {},
                "lane": case.get("lane"),
                "repeat_count": case.get("repeat_count"),
                "stability_attempts": case.get("stability_attempts"),
            }
        )
    return out


def cases_outcome_from_result(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    cases = result.get("cases")
    if not isinstance(cases, list):
        return []
    out: list[dict[str, Any]] = []
    for c in cases:
        if not isinstance(c, dict):
            continue
        row: dict[str, Any] = {
            "name": c.get("name"),
            "ok": c.get("ok"),
            "lane": c.get("lane"),
            "prompt_input": c.get("prompt_input"),
            "expected_response_contains": list(c.get("expected_response_contains") or [])
            if isinstance(c.get("expected_response_contains"), list)
            else [],
            "expected_response_not_contains": list(c.get("expected_response_not_contains") or [])
            if isinstance(c.get("expected_response_not_contains"), list)
            else [],
            "expected_response_regex": c.get("expected_response_regex"),
            "expected_response_starts_with": c.get("expected_response_starts_with"),
            "expected_response_ends_with": c.get("expected_response_ends_with"),
            "expected_response_equals": c.get("expected_response_equals"),
            "expected_response_length_min": c.get("expected_response_length_min"),
            "expected_response_length_max": c.get("expected_response_length_max"),
            "status_code": c.get("status_code"),
            "latency_ms": c.get("latency_ms"),
            "failures": list(c.get("failures") or []) if isinstance(c.get("failures"), list) else [],
            "response_headers": dict(c.get("response_headers") or {})
            if isinstance(c.get("response_headers"), dict)
            else {},
            "output_preview": c.get("output_preview"),
            "output_full": c.get("output_full"),
            "attempts_total": c.get("attempts_total"),
            "attempts_passed": c.get("attempts_passed"),
            "repeat_count": c.get("repeat_count"),
            "stability_attempts": c.get("stability_attempts"),
        }
        out.append(row)
    return out


def result_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {
            "overall_ok": False,
            "executed_cases": 0,
            "passed_cases": 0,
            "failed_cases": 0,
            "elapsed_seconds": None,
            "ran_at_utc": None,
        }
    return {
        "overall_ok": bool(result.get("ok")),
        "executed_cases": int(result.get("executed_cases") or 0),
        "passed_cases": int(result.get("passed_cases") or 0),
        "failed_cases": int(result.get("failed_cases") or 0),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "ran_at_utc": result.get("ran_at_utc"),
    }


def compose_run_human_summary(record: dict[str, Any]) -> str:
    rs = record.get("result_summary") if isinstance(record.get("result_summary"), dict) else {}
    suite_label = str(record.get("suite_name") or "").strip() or "unnamed suite"
    passed = int(rs.get("passed_cases") or 0)
    failed = int(rs.get("failed_cases") or 0)
    total = int(rs.get("executed_cases") or 0)
    overall_ok = bool(rs.get("overall_ok"))
    outcome_word = "passed" if overall_ok else "failed"
    return (
        f'Suite "{suite_label}": {total} case(s) executed, {passed} passed, '
        f"{failed} failed. Overall run {outcome_word}."
    )


def build_suite_run_record(
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
    run_type: str,
    schema_version: int,
    project_root: Path | None = None,
) -> dict[str, Any]:
    root = project_root or PROJECT_ROOT
    sn = str(suite.get("suite_name") or "") if isinstance(suite, dict) else ""
    tn = str(suite.get("target_name") or "") if isinstance(suite, dict) else ""
    src = resolve_path_str(suite_path, root) if (suite_path or "").strip() else None
    out_resolved = None
    if (output_dir or "").strip():
        try:
            out_resolved = resolve_path_str(output_dir, root)
        except OSError:
            out_resolved = output_dir
    rec: dict[str, Any] = {
        "schema_version": schema_version,
        "run_timestamp_utc": utc_now_iso(),
        "run_type": run_type,
        "suite_source_path": src,
        "suite_name": sn or None,
        "target_name": tn or None,
        "configuration": {
            "output_dir": out_resolved,
            "file_stem": file_stem or None,
            "fail_fast": bool(fail_fast),
            "timeout_seconds": int(default_timeout_seconds),
        },
        "requests": requests_from_suite_cases(suite) if suite else [],
        "auth_mode": None,
        "query_params_raw_json": None,
        "result_summary": result_summary(result),
        "cases_outcome": cases_outcome_from_result(result),
        "artifact_paths": dict(artifact_paths) if isinstance(artifact_paths, dict) else {},
        "error": error,
        "project_root": str(root.resolve()),
    }
    rec["summary"] = compose_run_human_summary(rec)
    return rec

