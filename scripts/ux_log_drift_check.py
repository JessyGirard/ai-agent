#!/usr/bin/env python3
"""Compare UX increment tags in app/ui.py + playground.py to docs/specs/UX_log_system.md.

Run manually from repo root:
  python scripts/ux_log_drift_check.py

Cursor afterFileEdit hook (stdin JSON with file_path):
  python scripts/ux_log_drift_check.py --cursor-hook-stdin
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UX_LOG = REPO_ROOT / "docs" / "specs" / "UX_log_system.md"
WATCH_FILES = (
    REPO_ROOT / "app" / "ui.py",
    REPO_ROOT / "playground.py",
)

TAG_PATTERN = re.compile(r"\b(UI-\d{2}[A-Z]?|LATENCY-\d+|LAUNCH-\d+)\b")


def collect_tags() -> set[str]:
    found: set[str] = set()
    for path in WATCH_FILES:
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in TAG_PATTERN.finditer(text):
            raw = m.group(1)
            mu = re.fullmatch(r"(UI-\d{2})([A-Za-z]?)", raw)
            if mu:
                num = mu.group(1)[3:]
                suf = (mu.group(2) or "").upper()
                found.add(f"UI-{num}{suf}")
                continue
            ml = re.fullmatch(r"LATENCY-(\d+)", raw, re.I)
            if ml:
                found.add(f"LATENCY-{ml.group(1)}")
                continue
            mk = re.fullmatch(r"LAUNCH-(\d+)", raw, re.I)
            if mk:
                found.add(f"LAUNCH-{mk.group(1)}")
                continue
            found.add(raw)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cursor-hook-stdin",
        action="store_true",
        help="Read Cursor afterFileEdit JSON from stdin; only check when file_path is ui.py or playground.py.",
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
        low = str(fp).replace("\\", "/").lower()
        if not (low.endswith("/app/ui.py") or low.endswith("/playground.py")):
            return 0

    if not UX_LOG.is_file():
        print("ux_log_drift_check: missing UX log at docs/specs/UX_log_system.md", file=sys.stderr)
        return 1

    ux_text = UX_LOG.read_text(encoding="utf-8", errors="replace")
    tags = collect_tags()
    missing = sorted(t for t in tags if t not in ux_text)

    if not missing:
        return 0

    msg = (
        "ux_log_drift_check: increment tag(s) in app/ui.py or playground.py "
        f"not found in docs/specs/UX_log_system.md: {', '.join(missing)}\n"
        "  → Add a table row or Log updated line to the UX log."
    )
    print(msg, file=sys.stderr)
    # Hook mode: warn only (do not fail the edit pipeline).
    if args.cursor_hook_stdin:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
