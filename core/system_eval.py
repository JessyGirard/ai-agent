import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

SYSTEM_EVAL_LANES = frozenset({"stability", "correctness", "consistency"})
CONSISTENCY_REPEAT_DEFAULT = 3
CONSISTENCY_REPEAT_MAX = 50
STABILITY_ATTEMPTS_DEFAULT = 3
STABILITY_ATTEMPTS_MAX = 50


@dataclass
class AdapterResult:
    ok: bool
    status_code: int | None
    output_text: str
    latency_ms: int
    error: str | None = None


class HttpTargetAdapter:
    def __init__(self, default_timeout_seconds=20):
        self.default_timeout_seconds = max(1, int(default_timeout_seconds))

    def run_case(self, case):
        method = str(case.get("method", "POST")).upper()
        url = str(case.get("url", "")).strip()
        headers = case.get("headers") if isinstance(case.get("headers"), dict) else {}
        timeout_seconds = max(1, int(case.get("timeout_seconds", self.default_timeout_seconds)))
        payload = case.get("payload", {})
        started = time.perf_counter()
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=payload,
                timeout=timeout_seconds,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            text = response.text or ""
            return AdapterResult(
                ok=True,
                status_code=response.status_code,
                output_text=text,
                latency_ms=latency_ms,
                error=None,
            )
        except requests.RequestException as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return AdapterResult(
                ok=False,
                status_code=None,
                output_text="",
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}",
            )


def _coerce_bounded_attempt_field(raw, case_name, field_name, max_n):
    if isinstance(raw, bool):
        raise ValueError(f"Case '{case_name}' has invalid '{field_name}' (boolean not allowed).")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"Case '{case_name}' has invalid '{field_name}'; expected a positive integer."
        ) from None
    if n < 1:
        raise ValueError(f"Case '{case_name}' has invalid '{field_name}' {n}; must be >= 1.")
    if n > max_n:
        raise ValueError(
            f"Case '{case_name}' has '{field_name}' {n}; maximum allowed is {max_n}."
        )
    return n


def _coerce_repeat_count(raw, case_name):
    return _coerce_bounded_attempt_field(raw, case_name, "repeat_count", CONSISTENCY_REPEAT_MAX)


def _coerce_stability_attempts(raw, case_name):
    return _coerce_bounded_attempt_field(raw, case_name, "stability_attempts", STABILITY_ATTEMPTS_MAX)


def load_suite_file(suite_path):
    path = Path(suite_path)
    with open(path, "r", encoding="utf-8") as f:
        suite = json.load(f)
    return validate_suite(suite)


def validate_suite(suite):
    if not isinstance(suite, dict):
        raise ValueError("Suite must be a JSON object.")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Suite must include a non-empty 'cases' array.")
    normalized_cases = []
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"Case at index {i} must be an object.")
        name = str(case.get("name", "")).strip()
        url = str(case.get("url", "")).strip()
        if not name:
            raise ValueError(f"Case at index {i} is missing a non-empty 'name'.")
        if not url:
            raise ValueError(f"Case '{name}' is missing a non-empty 'url'.")
        assertions = case.get("assertions", {})
        if not isinstance(assertions, dict):
            raise ValueError(f"Case '{name}' has invalid 'assertions'; expected object.")
        lane = None
        if "lane" in case and case["lane"] is not None:
            lane_raw = str(case["lane"]).strip()
            if lane_raw:
                if lane_raw not in SYSTEM_EVAL_LANES:
                    allowed = ", ".join(sorted(SYSTEM_EVAL_LANES))
                    raise ValueError(
                        f"Case '{name}' has invalid 'lane' {lane_raw!r}; "
                        f"allowed: {allowed}, or omit the field."
                    )
                lane = lane_raw

        repeat_count = None
        if "repeat_count" in case and case["repeat_count"] is not None:
            if lane != "consistency":
                raise ValueError(
                    f"Case '{name}' has 'repeat_count' but lane is not 'consistency' "
                    f"(lane is {lane!r})."
                )
            repeat_count = _coerce_repeat_count(case["repeat_count"], name)
        elif lane == "consistency":
            repeat_count = CONSISTENCY_REPEAT_DEFAULT

        if lane == "stability" and "repeat_count" in case and case["repeat_count"] is not None:
            raise ValueError(
                f"Case '{name}' has 'repeat_count' but lane is 'stability'; "
                f"use 'stability_attempts' instead."
            )
        if lane == "consistency" and "stability_attempts" in case and case["stability_attempts"] is not None:
            raise ValueError(
                f"Case '{name}' has 'stability_attempts' but lane is 'consistency'; "
                f"use 'repeat_count' instead."
            )
        if "stability_attempts" in case and case["stability_attempts"] is not None:
            if lane != "stability":
                raise ValueError(
                    f"Case '{name}' has 'stability_attempts' but lane is not 'stability' "
                    f"(lane is {lane!r})."
                )

        stability_attempts = None
        if "stability_attempts" in case and case["stability_attempts"] is not None:
            stability_attempts = _coerce_stability_attempts(case["stability_attempts"], name)
        elif lane == "stability":
            stability_attempts = STABILITY_ATTEMPTS_DEFAULT

        norm = {
            "name": name,
            "lane": lane,
            "method": str(case.get("method", "POST")).upper(),
            "url": url,
            "headers": case.get("headers", {}),
            "payload": case.get("payload", {}),
            "timeout_seconds": int(case.get("timeout_seconds", 20)),
            "assertions": assertions,
        }
        if lane == "consistency":
            norm["repeat_count"] = repeat_count
        if lane == "stability":
            norm["stability_attempts"] = stability_attempts
        normalized_cases.append(norm)
    return {
        "suite_name": str(suite.get("suite_name", "unnamed-suite")).strip() or "unnamed-suite",
        "target_name": str(suite.get("target_name", "unspecified-target")).strip() or "unspecified-target",
        "cases": normalized_cases,
    }


def _assert_output_matches(assertions, adapter_result):
    failures = []
    output_text = adapter_result.output_text or ""
    if "status_code" in assertions and adapter_result.status_code != int(assertions["status_code"]):
        failures.append(
            f"expected status_code={int(assertions['status_code'])}, got {adapter_result.status_code}"
        )
    contains_all = assertions.get("contains_all", [])
    if isinstance(contains_all, list):
        for token in contains_all:
            token_text = str(token)
            if token_text not in output_text:
                failures.append(f"missing required token: {token_text!r}")
    not_contains = assertions.get("not_contains", [])
    if isinstance(not_contains, list):
        for token in not_contains:
            token_text = str(token)
            if token_text in output_text:
                failures.append(f"forbidden token present: {token_text!r}")
    if "equals" in assertions:
        if output_text.strip() != str(assertions["equals"]).strip():
            failures.append("output text did not match expected equality assertion")
    if "regex" in assertions:
        pattern = str(assertions["regex"])
        if not re.search(pattern, output_text, flags=re.MULTILINE):
            failures.append(f"regex did not match: {pattern!r}")
    return failures


def _evaluate_single_attempt(case, adapter_result):
    failures = []
    if not adapter_result.ok:
        failures.append(adapter_result.error or "transport failure")
    else:
        failures.extend(_assert_output_matches(case["assertions"], adapter_result))
    return failures


def _run_n_attempts(case, adapter, n):
    attempts_out = []
    all_ok = True
    last_adapter_result = None
    for attempt_idx in range(n):
        adapter_result = adapter.run_case(case)
        last_adapter_result = adapter_result
        failures = _evaluate_single_attempt(case, adapter_result)
        attempt_ok = len(failures) == 0
        all_ok = all_ok and attempt_ok
        attempts_out.append(
            {
                "attempt": attempt_idx + 1,
                "ok": attempt_ok,
                "failures": failures,
                "status_code": adapter_result.status_code,
                "latency_ms": adapter_result.latency_ms,
                "output_preview": (adapter_result.output_text or "")[:600],
            }
        )
    case_failures = []
    if not all_ok:
        for a in attempts_out:
            if not a["ok"]:
                for f in a["failures"]:
                    case_failures.append(f"attempt {a['attempt']}/{n}: {f}")
    attempts_passed = sum(1 for a in attempts_out if a["ok"])
    return attempts_out, all_ok, last_adapter_result, case_failures, attempts_passed


def execute_suite(suite, adapter, fail_fast=False):
    started = time.perf_counter()
    case_results = []
    passed = 0
    failed = 0
    for case in suite["cases"]:
        if case.get("lane") == "stability":
            n = int(case["stability_attempts"])
            attempts_out, case_ok, last_adapter_result, case_failures, attempts_passed = _run_n_attempts(
                case, adapter, n
            )
            if case_ok:
                passed += 1
            else:
                failed += 1
            case_results.append(
                {
                    "name": case["name"],
                    "lane": case.get("lane"),
                    "stability_attempts": n,
                    "attempts_passed": attempts_passed,
                    "attempts_total": n,
                    "attempts": attempts_out,
                    "ok": case_ok,
                    "failures": case_failures,
                    "status_code": last_adapter_result.status_code if last_adapter_result else None,
                    "latency_ms": last_adapter_result.latency_ms if last_adapter_result else 0,
                    "output_preview": (last_adapter_result.output_text or "")[:600]
                    if last_adapter_result
                    else "",
                    "method": case["method"],
                    "url": case["url"],
                }
            )
        elif case.get("lane") == "consistency":
            n = int(case["repeat_count"])
            attempts_out, case_ok, last_adapter_result, case_failures, attempts_passed = _run_n_attempts(
                case, adapter, n
            )
            if case_ok:
                passed += 1
            else:
                failed += 1
            case_results.append(
                {
                    "name": case["name"],
                    "lane": case.get("lane"),
                    "repeat_count": n,
                    "attempts_passed": attempts_passed,
                    "attempts_total": n,
                    "attempts": attempts_out,
                    "ok": case_ok,
                    "failures": case_failures,
                    "status_code": last_adapter_result.status_code if last_adapter_result else None,
                    "latency_ms": last_adapter_result.latency_ms if last_adapter_result else 0,
                    "output_preview": (last_adapter_result.output_text or "")[:600]
                    if last_adapter_result
                    else "",
                    "method": case["method"],
                    "url": case["url"],
                }
            )
        else:
            adapter_result = adapter.run_case(case)
            failures = _evaluate_single_attempt(case, adapter_result)
            case_ok = len(failures) == 0
            if case_ok:
                passed += 1
            else:
                failed += 1
            case_results.append(
                {
                    "name": case["name"],
                    "lane": case.get("lane"),
                    "ok": case_ok,
                    "failures": failures,
                    "status_code": adapter_result.status_code,
                    "latency_ms": adapter_result.latency_ms,
                    "output_preview": (adapter_result.output_text or "")[:600],
                    "method": case["method"],
                    "url": case["url"],
                }
            )
        if fail_fast and not case_results[-1].get("ok"):
            break
    elapsed_seconds = round(time.perf_counter() - started, 3)
    return {
        "suite_name": suite["suite_name"],
        "target_name": suite["target_name"],
        "executed_cases": len(case_results),
        "passed_cases": passed,
        "failed_cases": failed,
        "ok": failed == 0,
        "elapsed_seconds": elapsed_seconds,
        "ran_at_utc": datetime.now(timezone.utc).isoformat(),
        "cases": case_results,
    }


def write_result_artifacts(result, output_dir, file_stem):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    json_path = output_path / f"{file_stem}.json"
    md_path = output_path / f"{file_stem}.md"

    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# System Eval Report: {result.get('suite_name')}",
        "",
        f"- Target: `{result.get('target_name')}`",
        f"- Status: `{'PASS' if result.get('ok') else 'FAIL'}`",
        f"- Executed cases: `{result.get('executed_cases')}`",
        f"- Passed: `{result.get('passed_cases')}`",
        f"- Failed: `{result.get('failed_cases')}`",
        f"- Elapsed seconds: `{result.get('elapsed_seconds')}`",
        "",
        "## Case Results",
        "",
    ]
    for case in result.get("cases", []):
        status = "PASS" if case.get("ok") else "FAIL"
        lane = case.get("lane")
        lane_part = f" lane=`{lane}`" if lane else " lane=(none)"
        lines.append(
            f"- `{status}` `{case.get('name')}`{lane_part} ({case.get('method')} {case.get('url')})"
        )
        failures = case.get("failures") or []
        if failures:
            for failure in failures:
                lines.append(f"  - {failure}")
        if case.get("lane") == "stability":
            sa = case.get("stability_attempts")
            ap = case.get("attempts_passed")
            at = case.get("attempts_total")
            if sa is not None and ap is not None and at is not None:
                lines.append(
                    f"  - stability: `{ap}/{at}` attempts passed (stability_attempts=`{sa}`)"
                )
            for att in case.get("attempts") or []:
                att_status = "ok" if att.get("ok") else "fail"
                lines.append(
                    f"  - attempt `{att.get('attempt')}`: `{att_status}` "
                    f"(status `{att.get('status_code')}`, latency_ms `{att.get('latency_ms')}`)"
                )
        if case.get("lane") == "consistency":
            rp = case.get("repeat_count")
            ap = case.get("attempts_passed")
            at = case.get("attempts_total")
            if rp is not None and ap is not None and at is not None:
                lines.append(f"  - consistency: `{ap}/{at}` attempts passed (repeat_count=`{rp}`)")
            for att in case.get("attempts") or []:
                att_status = "ok" if att.get("ok") else "fail"
                lines.append(
                    f"  - attempt `{att.get('attempt')}`: `{att_status}` "
                    f"(status `{att.get('status_code')}`, latency_ms `{att.get('latency_ms')}`)"
                )
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(md_path)}
