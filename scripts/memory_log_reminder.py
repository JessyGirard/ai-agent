#!/usr/bin/env python3
"""Remind operators to append ``docs/specs/memory_log_system.md`` after memory-adjacent edits.

Cursor afterFileEdit hook (stdin JSON with file_path):
  python scripts/memory_log_reminder.py --cursor-hook-stdin

This does **not** auto-edit the memory log (narrative rows stay human/assistant authored).
It prints to **stderr** so the Hooks output channel shows a nudge when memory-related paths change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MEMORY_LOG = REPO_ROOT / "docs" / "specs" / "memory_log_system.md"


def _norm_path(fp: str) -> str:
    return str(fp).replace("\\", "/").lower()


def _is_memory_adjacent_edit(low: str) -> bool:
    if not low:
        return False
    if low.endswith("/docs/specs/memory_log_system.md"):
        return False
    if low.endswith("/services/memory_service.py"):
        return True
    if low.endswith("/docs/specs/memory_system.md"):
        return True
    if "/memory/" in low and low.endswith(".py"):
        return True
    if low.endswith("/memory/extracted_memory.json"):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cursor-hook-stdin",
        action="store_true",
        help="Read Cursor afterFileEdit JSON from stdin; warn when a memory-adjacent path was saved.",
    )
    args = parser.parse_args()

    if args.cursor_hook_stdin:
        try:
            payload = json.load(sys.stdin)
        except json.JSONDecodeError:
            return 0
        fp = payload.get("file_path") or payload.get("filePath") or ""
        if not fp:
            return 0
        low = _norm_path(fp)
        if not _is_memory_adjacent_edit(low):
            return 0

        msg = (
            "memory_log_reminder: memory-adjacent file was edited.\n"
            f"  → Append a dated row under “Session increments (logged)” in:\n"
            f"     {MEMORY_LOG.as_posix()}\n"
            "  See the file’s **Logging contract** block for required fields (date, id, outcome, files, regression)."
        )
        print(msg, file=sys.stderr)
        return 0

    print(
        "Run with --cursor-hook-stdin from Cursor afterFileEdit, or edit memory-adjacent files and check Hooks output.\n"
        f"Memory increment register: {MEMORY_LOG.as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
