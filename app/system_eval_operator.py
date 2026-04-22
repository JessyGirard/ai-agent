"""
Operator-side helpers for HTTP system eval (Tool 1). Streamlit-free for regression tests.
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import tool1_run_log
from core import system_eval


def _slugify(text):
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", text.strip()).strip("_")
    return safe or "system_eval_run"


def _resolve_under_root(path_str: str, root: Path) -> Path:
    p = Path(path_str.strip())
    if p.is_absolute():
        return p
    return (root / p).resolve()


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
    return tool1_run_log.try_log_suite_run(
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


def _failure_bundle(*, error: str, run_log_error: str | None, result: dict | None = None) -> dict:
    return {
        "ok": False,
        "result": result,
        "artifact_paths": {},
        "json_preview": "",
        "markdown_preview": "",
        "error": error,
        "run_log_error": run_log_error,
    }


def run_tool1_system_eval_http(
    suite_path: str,
    output_dir: str,
    file_stem: str = "",
    *,
    project_root: Path | None = None,
    adapter=None,
    fail_fast: bool = False,
    default_timeout_seconds: int = 20,
):
    """
    Load suite, run against adapter, write artifacts. Returns a dict for UI or tests.

    Keys: ok (bool), result (dict), artifact_paths (dict), json_preview (str),
    markdown_preview (str), error (str|None).
    """
    root = project_root or PROJECT_ROOT
    suite_file = _resolve_under_root(suite_path, root)
    out_dir = _resolve_under_root(output_dir, root)

    if not suite_file.is_file():
        err = f"Suite file not found: {suite_file}"
        log_err = _log_suite_failure(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=fail_fast,
            default_timeout_seconds=default_timeout_seconds,
            suite=None,
            result=None,
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err)

    try:
        suite = system_eval.load_suite_file(str(suite_file))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        err = str(exc)
        log_err = _log_suite_failure(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=fail_fast,
            default_timeout_seconds=default_timeout_seconds,
            suite=None,
            result=None,
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err)

    if adapter is None:
        adapter = system_eval.HttpTargetAdapter(
            default_timeout_seconds=max(1, int(default_timeout_seconds))
        )

    try:
        result = system_eval.execute_suite(suite, adapter=adapter, fail_fast=fail_fast)
    except Exception as exc:  # defensive operator boundary
        err = f"Suite execution failed: {type(exc).__name__}: {exc}"
        log_err = _log_suite_failure(
            suite_path=suite_path,
            output_dir=output_dir,
            file_stem=file_stem,
            fail_fast=fail_fast,
            default_timeout_seconds=default_timeout_seconds,
            suite=suite,
            result=None,
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err)
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
            default_timeout_seconds=default_timeout_seconds,
            suite=suite,
            result=result,
            error=err,
            project_root=root,
        )
        return _failure_bundle(error=err, run_log_error=log_err, result=result)

    max_json = 14_000
    if len(json_text) > max_json:
        json_preview = json_text[:max_json] + "\n\n... (truncated for preview)"
    else:
        json_preview = json_text

    max_md = 20_000
    if len(md_text) > max_md:
        markdown_preview = md_text[:max_md] + "\n\n... (truncated for preview)"
    else:
        markdown_preview = md_text

    log_err = tool1_run_log.try_log_suite_run(
        suite_path=suite_path,
        output_dir=output_dir,
        file_stem=file_stem,
        fail_fast=fail_fast,
        default_timeout_seconds=default_timeout_seconds,
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
    }


