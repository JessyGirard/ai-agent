"""
Operator-side helpers for Tool 2 prompt/response system eval lane.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import tool2_run_log
from core import llm, system_eval


def _slugify(text):
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", text.strip()).strip("_")
    return safe or "system_eval_run"


def _resolve_under_root(path_str: str, root: Path) -> Path:
    p = Path(path_str.strip())
    if p.is_absolute():
        return p
    return (root / p).resolve()


def _coerce_default_timeout_seconds(raw) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError("Invalid 'default_timeout_seconds': expected integer >= 1.")
    if raw < 1:
        raise ValueError("Invalid 'default_timeout_seconds': expected integer >= 1.")
    return int(raw)


def _failure_bundle(
    *,
    error: str,
    run_log_error: str | None,
    run_log_path: str | None,
    result: dict | None = None,
) -> dict:
    return {
        "ok": False,
        "result": result,
        "artifact_paths": {},
        "json_preview": "",
        "markdown_preview": "",
        "error": error,
        "run_log_error": run_log_error,
        "run_log_path": run_log_path,
    }


def _log_suite_failure(
    *,
    suite_path: str,
    output_dir: str,
    file_stem: str,
    fail_fast: bool,
    default_timeout_seconds: int,
    suite: dict | None,
    result: dict | None,
    error: str,
    project_root: Path,
    artifact_paths: dict | None = None,
) -> str | None:
    return tool2_run_log.try_log_tool2_suite_run(
        suite_path=suite_path,
        output_dir=output_dir,
        file_stem=file_stem,
        fail_fast=fail_fast,
        default_timeout_seconds=default_timeout_seconds,
        suite=suite,
        result=result,
        artifact_paths=artifact_paths or {},
        error=error,
        project_root=project_root,
    )


def _default_prompt_executor(prompt_input: str) -> str:
    return llm.ask_ai(messages=[{"role": "user", "content": prompt_input}], system_prompt=None)


class _Tool2PromptAdapter:
    def __init__(self, prompt_executor):
        self._prompt_executor = prompt_executor

    def run_prompt_case(self, case):
        prompt_input = str(case.get("prompt_input", ""))
        started = time.perf_counter()
        try:
            text = str(self._prompt_executor(prompt_input) or "")
            latency_ms = int((time.perf_counter() - started) * 1000)
            return system_eval.AdapterResult(
                ok=True,
                status_code=200,
                output_text=text,
                latency_ms=latency_ms,
                error=None,
                response_headers={},
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return system_eval.AdapterResult(
                ok=False,
                status_code=None,
                output_text="",
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}",
                response_headers={},
            )


def run_tool2_prompt_response_eval(
    suite_path: str,
    output_dir: str,
    file_stem: str = "",
    *,
    project_root: Path | None = None,
    adapter=None,
    fail_fast: bool = False,
    default_timeout_seconds: int = 20,
):
    root = project_root or PROJECT_ROOT
    run_log_path = str(tool2_run_log.tool2_run_log_path(root))
    try:
        timeout_seconds = _coerce_default_timeout_seconds(default_timeout_seconds)
    except ValueError as exc:
        err = str(exc)
        log_err = _log_suite_failure(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=fail_fast,
            default_timeout_seconds=20,
            suite=None,
            result=None,
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, run_log_path=run_log_path)
    suite_file = _resolve_under_root(suite_path, root)
    if not suite_file.is_file():
        err = f"Suite file not found: {suite_file}"
        log_err = _log_suite_failure(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=fail_fast,
            default_timeout_seconds=timeout_seconds,
            suite=None,
            result=None,
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, run_log_path=run_log_path)

    try:
        suite = system_eval.load_suite_file(str(suite_file))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        err = str(exc)
        log_err = _log_suite_failure(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=fail_fast,
            default_timeout_seconds=timeout_seconds,
            suite=None,
            result=None,
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, run_log_path=run_log_path)

    lanes = {str((c or {}).get("lane") or "") for c in (suite.get("cases") or [])}
    if lanes != {"prompt_response"}:
        err = (
            "Tool 2 requires all cases to use lane='prompt_response'. "
            f"Found lanes: {sorted(lanes)}"
        )
        log_err = _log_suite_failure(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=fail_fast,
            default_timeout_seconds=timeout_seconds,
            suite=suite,
            result=None,
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, run_log_path=run_log_path)

    out_dir = _resolve_under_root(output_dir, root)
    if adapter is None:
        adapter = _Tool2PromptAdapter(prompt_executor=_default_prompt_executor)

    try:
        result = system_eval.execute_suite(suite, adapter=adapter, fail_fast=fail_fast)
    except Exception as exc:
        err = f"Suite execution failed: {type(exc).__name__}: {exc}"
        log_err = _log_suite_failure(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=fail_fast,
            default_timeout_seconds=timeout_seconds,
            suite=suite,
            result=None,
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, run_log_path=run_log_path)

    stem = file_stem.strip() or _slugify(str(suite.get("suite_name", "system_eval")))
    try:
        artifact_paths = system_eval.write_result_artifacts(result, str(out_dir), file_stem=stem)
        json_path = Path(artifact_paths["json_path"])
        md_path = Path(artifact_paths["markdown_path"])
        json_text = json_path.read_text(encoding="utf-8") if json_path.is_file() else ""
        md_text = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    except (OSError, KeyError) as exc:
        err = f"Artifact write/read failed: {type(exc).__name__}: {exc}"
        log_err = _log_suite_failure(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=fail_fast,
            default_timeout_seconds=timeout_seconds,
            suite=suite,
            result=result,
            error=err,
            project_root=root,
        )
        return _failure_bundle(
            error=err,
            run_log_error=log_err,
            run_log_path=run_log_path,
            result=result,
        )

    max_json = 14_000
    json_preview = json_text[:max_json] + "\n\n... (truncated for preview)" if len(json_text) > max_json else json_text
    max_md = 20_000
    markdown_preview = md_text[:max_md] + "\n\n... (truncated for preview)" if len(md_text) > max_md else md_text

    log_err = tool2_run_log.try_log_tool2_suite_run(
        suite_path=suite_path,
        output_dir=output_dir,
        file_stem=file_stem,
        fail_fast=fail_fast,
        default_timeout_seconds=timeout_seconds,
        suite=suite,
        result=result,
        artifact_paths=artifact_paths,
        error=None,
        project_root=root,
    )
    return {
        "ok": bool(result.get("ok")),
        "result": result,
        "artifact_paths": artifact_paths,
        "json_preview": json_preview,
        "markdown_preview": markdown_preview,
        "error": None,
        "run_log_error": log_err,
        "run_log_path": run_log_path,
    }

