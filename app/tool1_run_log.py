"""
Append-only JSONL log for Tool 1 HTTP runs (single request + suite).

Path: ``logs/tool1_runs.jsonl`` under the project root (created on first write).
Streamlit-free — safe for tests and ``system_eval_operator``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import tool1_log_redaction

TOOL1_RUN_LOG_SCHEMA_VERSION = 1
TOOL1_RUN_LOG_REL_PATH = Path("logs") / "tool1_runs.jsonl"


def tool1_run_log_path(project_root: Path | None = None) -> Path:
    root = project_root or PROJECT_ROOT
    return root / TOOL1_RUN_LOG_REL_PATH


def _resolve_path_str(path_str: str, root: Path) -> str:
    p = Path(path_str.strip())
    if p.is_absolute():
        return str(p.resolve())
    return str((root / p).resolve())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_tool1_run_record(record: dict, *, project_root: Path | None = None) -> tuple[bool, str | None]:
    """
    Append one JSON object as a single line to the log file.
    Returns ``(True, None)`` on success, or ``(False, error_message)`` on failure.
    """
    path = tool1_run_log_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        return True, None
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _redact_tool1_record(record: dict[str, Any]) -> dict[str, Any]:
    return tool1_log_redaction.redact_tool1_record(record)


def _requests_from_suite_cases(suite: dict[str, Any]) -> list[dict[str, Any]]:
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
                "headers": dict(case.get("headers") or {}),
                "payload": case.get("payload") if isinstance(case.get("payload"), dict) else {},
                "assertions": case.get("assertions") if isinstance(case.get("assertions"), dict) else {},
                "lane": case.get("lane"),
                "repeat_count": case.get("repeat_count"),
                "stability_attempts": case.get("stability_attempts"),
            }
        )
    return out


def _cases_outcome_from_result(result: dict[str, Any] | None) -> list[dict[str, Any]]:
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
        att = c.get("attempts")
        if isinstance(att, list) and att:
            row["attempts"] = []
            for a in att:
                if not isinstance(a, dict):
                    continue
                row["attempts"].append(
                    {
                        "attempt": a.get("attempt"),
                        "ok": a.get("ok"),
                        "failures": list(a.get("failures") or [])
                        if isinstance(a.get("failures"), list)
                        else [],
                        "status_code": a.get("status_code"),
                        "latency_ms": a.get("latency_ms"),
                        "response_headers": dict(a.get("response_headers") or {})
                        if isinstance(a.get("response_headers"), dict)
                        else {},
                        "output_preview": a.get("output_preview"),
                        "output_full": a.get("output_full"),
                    }
                )
        out.append(row)
    return out


def _truncate_words(text: str, max_len: int = 220) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _failure_lines_from_cases_outcome(cases_out: list[Any]) -> list[str]:
    lines: list[str] = []
    if not isinstance(cases_out, list):
        return lines
    for c in cases_out:
        if not isinstance(c, dict):
            continue
        for f in c.get("failures") or []:
            s = str(f).strip()
            if s:
                lines.append(s)
        for att in c.get("attempts") or []:
            if not isinstance(att, dict):
                continue
            for f in att.get("failures") or []:
                s = str(f).strip()
                if s:
                    lines.append(s)
    return lines


def _timing_phrase(*, cases_outcome: list[dict[str, Any]], elapsed_seconds: Any) -> str:
    if elapsed_seconds is not None:
        try:
            es = float(elapsed_seconds)
            if es >= 0:
                if es < 1.0:
                    return f"Completed in about {int(es * 1000)} ms."
                return f"Completed in about {es:.1f} s."
        except (TypeError, ValueError):
            pass
    if cases_outcome and isinstance(cases_outcome[0], dict):
        ms = cases_outcome[0].get("latency_ms")
        if ms is not None:
            try:
                n = int(ms)
                return f"Reported request latency about {n} ms."
            except (TypeError, ValueError):
                pass
    return "Timing not recorded for this run."


def compose_tool1_run_human_summary(record: dict[str, Any]) -> str:
    """
    One short plain-text paragraph for operators and non-engineers.
    Safe with missing or partial fields. No HTML or markup.
    """
    run_type = str(record.get("run_type") or "run")
    err_raw = record.get("error")
    err = str(err_raw).strip() if err_raw is not None else ""
    rs = record.get("result_summary") if isinstance(record.get("result_summary"), dict) else {}
    requests = record.get("requests") if isinstance(record.get("requests"), list) else []
    cases_out = record.get("cases_outcome") if isinstance(record.get("cases_outcome"), list) else []
    suite_label = str(record.get("suite_name") or "").strip() or "unnamed suite"

    method = "REQUEST"
    url = "URL not recorded"
    if requests and isinstance(requests[0], dict):
        method = str(requests[0].get("method") or "GET").strip().upper() or "GET"
        url = str(requests[0].get("url") or url).strip() or url
    snap = record.get("request_input_snapshot")
    if url == "URL not recorded" and isinstance(snap, dict):
        method = str(snap.get("method") or method).strip().upper() or method
        u = str(snap.get("url") or "").strip()
        if u:
            url = u

    passed = int(rs.get("passed_cases") or 0)
    failed = int(rs.get("failed_cases") or 0)
    total = int(rs.get("executed_cases") or 0)
    if total <= 0 and cases_out:
        total = len(cases_out)
    overall_ok = bool(rs.get("overall_ok"))

    # Early failure: no HTTP result
    if err and not cases_out:
        tail = " Timing not recorded for this run."
        if run_type == "single_request":
            return (
                f"{method} request to {url} did not complete. "
                f"{_truncate_words(err, 280)} No response checks were recorded.{tail}"
            )
        return (
            f'Suite "{suite_label}" did not run successfully. '
            f"{_truncate_words(err, 280)} No case results were recorded.{tail}"
        )

    fail_lines = _failure_lines_from_cases_outcome(cases_out)
    first_fail = _truncate_words(fail_lines[0], 200) if fail_lines else ""

    status_bits: list[str] = []
    if cases_out and isinstance(cases_out[0], dict):
        sc = cases_out[0].get("status_code")
        if sc is None and not overall_ok:
            status_bits.append("No HTTP status was returned (likely a connection or client error).")
        elif sc is not None:
            status_bits.append(f"HTTP status {sc}.")

    body_note = ""
    if cases_out and isinstance(cases_out[0], dict):
        prev = cases_out[0].get("output_preview")
        full = cases_out[0].get("output_full")
        prev_s = "" if prev is None else str(prev).strip()
        if not prev_s and (full is None or not str(full).strip()):
            body_note = " Response body was empty or not captured."

    co_dicts = [c for c in cases_out if isinstance(c, dict)]
    timing = _timing_phrase(cases_outcome=co_dicts, elapsed_seconds=rs.get("elapsed_seconds"))

    if run_type == "suite_run":
        outcome_word = "passed" if overall_ok else "failed"
        parts = [
            f'Suite "{suite_label}": {total} case(s) executed, {passed} passed, {failed} failed. '
            f"Overall run {outcome_word}.",
        ]
        if requests and isinstance(requests[0], dict) and total <= 1:
            parts.append(f" Request was {method} {url}.")
        if status_bits and total <= 1:
            parts.append(" ")
            parts.extend(status_bits)
        parts.append(body_note)
        if not overall_ok:
            if first_fail:
                parts.append(f" First issue: {first_fail}")
            elif err:
                parts.append(f" {_truncate_words(err, 240)}")
        elif err:
            parts.append(f" Note: {_truncate_words(err, 160)}")
        parts.append(f" {timing}")
        return " ".join("".join(parts).split()).strip()

    # single_request
    outcome_word = "succeeded" if overall_ok else "failed"
    line = [f"{method} request to {url} {outcome_word}."]
    if (passed + failed) > 0 or total > 0:
        line.append(f"Checks recorded: {passed} passed, {failed} failed.")
    if status_bits:
        line.append(" ".join(status_bits))
    if overall_ok:
        if failed == 0:
            line.append("All configured checks passed.")
        else:
            line.append(f"{failed} check(s) or case(s) did not pass.")
    else:
        if first_fail:
            line.append(_truncate_words(first_fail, 240))
        elif err:
            line.append(_truncate_words(err, 240))
        else:
            line.append("One or more checks did not pass.")
    if body_note.strip():
        line.append(body_note.strip())
    line.append(timing)
    return " ".join(" ".join(line).split()).strip()


def _result_summary(result: dict[str, Any] | None) -> dict[str, Any]:
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


def build_tool1_run_record_suite(
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
    """One stable record for a suite-based Tool 1 run."""
    root = project_root or PROJECT_ROOT
    sn = str(suite.get("suite_name") or "") if isinstance(suite, dict) else ""
    tn = str(suite.get("target_name") or "") if isinstance(suite, dict) else ""
    src = _resolve_path_str(suite_path, root) if (suite_path or "").strip() else None
    out_resolved = None
    if (output_dir or "").strip():
        try:
            out_resolved = _resolve_path_str(output_dir, root)
        except OSError:
            out_resolved = output_dir
    rec: dict[str, Any] = {
        "schema_version": TOOL1_RUN_LOG_SCHEMA_VERSION,
        "run_timestamp_utc": _utc_now_iso(),
        "run_type": "suite_run",
        "suite_source_path": src,
        "suite_name": sn or None,
        "target_name": tn or None,
        "configuration": {
            "output_dir": out_resolved,
            "file_stem": file_stem or None,
            "fail_fast": bool(fail_fast),
            "timeout_seconds": int(default_timeout_seconds),
        },
        "requests": _requests_from_suite_cases(suite) if suite else [],
        "auth_mode": None,
        "query_params_raw_json": None,
        "result_summary": _result_summary(result),
        "cases_outcome": _cases_outcome_from_result(result),
        "artifact_paths": dict(artifact_paths) if isinstance(artifact_paths, dict) else {},
        "error": error,
        "project_root": str(root.resolve()),
    }
    rec["summary"] = compose_tool1_run_human_summary(rec)
    return rec


def _resolve_output_dir_for_log(rel: str, root: Path) -> str:
    p = Path((rel or "logs/system_eval").strip())
    if p.is_absolute():
        return str(p.resolve())
    return str((root / p).resolve())


def build_tool1_run_record_single(
    *,
    prep: dict[str, Any] | None,
    result: dict[str, Any] | None,
    artifact_paths: dict[str, Any],
    error: str | None,
    timeout_seconds: int,
    output_dir_rel: str,
    auth_mode_internal: str,
    query_params_text: str,
    input_snapshot: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """One stable record for a single-request Tool 1 run (success, validation error, or prepare error)."""
    root = project_root or PROJECT_ROOT
    if isinstance(prep, dict) and prep.get("suite_dict"):
        suite = prep["suite_dict"]
        sn = str(suite.get("suite_name") or "single-request")
        tn = str(suite.get("target_name") or "operator")
        requests = _requests_from_suite_cases(suite) if isinstance(suite, dict) else []
    else:
        sn, tn = "single-request", "operator"
        requests = []
    artifact_stem = "single_request"
    jp = artifact_paths.get("json_path") if isinstance(artifact_paths, dict) else None
    if jp:
        try:
            artifact_stem = Path(str(jp)).stem
        except (TypeError, ValueError):
            artifact_stem = "single_request"
    rec: dict[str, Any] = {
        "schema_version": TOOL1_RUN_LOG_SCHEMA_VERSION,
        "run_timestamp_utc": _utc_now_iso(),
        "run_type": "single_request",
        "suite_source_path": None,
        "suite_name": sn,
        "target_name": tn,
        "configuration": {
            "output_dir": _resolve_output_dir_for_log(output_dir_rel, root),
            "file_stem": artifact_stem,
            "fail_fast": False,
            "timeout_seconds": int(timeout_seconds),
        },
        "requests": requests,
        "auth_mode": auth_mode_internal,
        "query_params_raw_json": query_params_text if (query_params_text or "").strip() else None,
        "result_summary": _result_summary(result),
        "cases_outcome": _cases_outcome_from_result(result),
        "artifact_paths": dict(artifact_paths) if isinstance(artifact_paths, dict) else {},
        "error": error,
        "request_input_snapshot": input_snapshot,
        "project_root": str(root.resolve()),
    }
    rec["summary"] = compose_tool1_run_human_summary(rec)
    return rec


def try_log_suite_run(
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
    """
    Build and append a suite run record. Returns ``None`` on success, else an error string.
    """
    rec = build_tool1_run_record_suite(
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
    rec = _redact_tool1_record(rec)
    rec["summary"] = compose_tool1_run_human_summary(rec)
    ok, err = append_tool1_run_record(rec, project_root=project_root)
    return None if ok else (err or "unknown logging error")


def try_log_single_request_run(
    *,
    prep: dict[str, Any] | None,
    result: dict[str, Any] | None,
    artifact_paths: dict[str, Any],
    error: str | None,
    timeout_seconds: int,
    output_dir_rel: str,
    auth_mode_internal: str,
    query_params_text: str,
    input_snapshot: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> str | None:
    """Build and append a single-request record. Returns ``None`` on success, else an error string."""
    rec = build_tool1_run_record_single(
        prep=prep,
        result=result,
        artifact_paths=artifact_paths,
        error=error,
        timeout_seconds=timeout_seconds,
        output_dir_rel=output_dir_rel,
        auth_mode_internal=auth_mode_internal,
        query_params_text=query_params_text,
        input_snapshot=input_snapshot,
        project_root=project_root,
    )
    rec = _redact_tool1_record(rec)
    rec["summary"] = compose_tool1_run_human_summary(rec)
    ok, err = append_tool1_run_record(rec, project_root=project_root)
    return None if ok else (err or "unknown logging error")
