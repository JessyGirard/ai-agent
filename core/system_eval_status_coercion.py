"""
Status-field coercion helpers for system eval suites.

Extracted from ``core/system_eval.py`` as a behavior-preserving
maintainability refactor.
"""


def coerce_expected_status(raw, case_name):
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_status'; expected integer (JSON number), not boolean."
        )
    return int(raw)


def coerce_expected_status_in(raw, case_name):
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_status_in'; expected a non-empty array of integer status codes."
        )
    out = []
    for i, v in enumerate(raw):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_status_in' item at index {i}; expected integer (JSON number), not boolean."
            )
        out.append(int(v))
    return out


def coerce_expected_status_not(raw, case_name):
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"Case '{case_name}' has invalid 'expected_status_not'; expected a non-empty array of integer status codes."
        )
    out = []
    for i, v in enumerate(raw):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(
                f"Case '{case_name}' has invalid 'expected_status_not' item at index {i}; expected integer (JSON number), not boolean."
            )
        out.append(int(v))
    return out
