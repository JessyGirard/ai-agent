"""
Tool 1 assertion surface grouping.

Purpose:
- keep engine behavior unchanged
- provide a stable "core vs advanced" map for product/UI shaping
"""

from __future__ import annotations

CORE_ASSERTIONS: tuple[str, ...] = (
    "expected_status",
    "expected_headers",
    "expected_json",
    "expected_json_exists",
    "expected_json_values",
    "expected_body_not_empty",
    "expected_latency_ms_max",
    "retries",
)

ADVANCED_ASSERTIONS: tuple[str, ...] = (
    "expected_status_in",
    "expected_status_not",
    "expected_headers_contains",
    "expected_header_exists",
    "expected_json_absent",
    "expected_body_size_bytes_max",
    "expected_response_time_ms_range",
    "max_duration_ms",
)


def grouped_assertions() -> dict[str, list[str]]:
    return {
        "core": list(CORE_ASSERTIONS),
        "advanced": list(ADVANCED_ASSERTIONS),
    }

