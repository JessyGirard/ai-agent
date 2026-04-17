import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import system_eval


def _slugify(text):
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", text.strip()).strip("_")
    return safe or "system_eval_run"


def main():
    parser = argparse.ArgumentParser(description="Run system-level evaluation suite against an HTTP target.")
    parser.add_argument("--suite", required=True, help="Path to suite JSON file.")
    parser.add_argument("--output-dir", default="logs/system_eval", help="Directory for result artifacts.")
    parser.add_argument("--file-stem", default="", help="Optional result file stem.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop at first failing case.")
    parser.add_argument("--default-timeout-seconds", type=int, default=20)
    args = parser.parse_args()

    suite = system_eval.load_suite_file(args.suite)
    adapter = system_eval.HttpTargetAdapter(default_timeout_seconds=max(1, args.default_timeout_seconds))
    result = system_eval.execute_suite(suite, adapter=adapter, fail_fast=args.fail_fast)
    file_stem = args.file_stem.strip() or _slugify(suite.get("suite_name", "system_eval"))
    artifact_paths = system_eval.write_result_artifacts(result, args.output_dir, file_stem=file_stem)

    print(f"SYSTEM_EVAL_STATUS: {'PASS' if result.get('ok') else 'FAIL'}")
    print(f"SYSTEM_EVAL_JSON: {artifact_paths['json_path']}")
    print(f"SYSTEM_EVAL_MARKDOWN: {artifact_paths['markdown_path']}")

    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
