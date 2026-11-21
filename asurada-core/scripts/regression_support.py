from __future__ import annotations

import json
from functools import wraps
from typing import Any
from unittest.mock import patch

from asurada.runtime_context import RuntimeContextDetector


def runtime_clock(fixed_now_ms: int):
    """Freeze only race freshness checks, leaving audio/timeout clocks running."""
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            original = RuntimeContextDetector.detect

            def detect(detector, *, state, now_ms=None):
                return original(
                    detector,
                    state=state,
                    now_ms=fixed_now_ms if now_ms is None else now_ms,
                )

            with patch.object(RuntimeContextDetector, "detect", detect):
                return function(*args, **kwargs)
        return run
    return decorate


def report_passed(report: Any) -> bool:
    """Read acceptance status without interpreting business booleans as checks."""
    if not isinstance(report, dict) or not report:
        return False
    if "passed" in report:
        return report["passed"] is True
    if all(isinstance(value, bool) for value in report.values()):
        return all(report.values())
    # A few suites group independently reported subtests at the top level.
    return all(
        isinstance(value, dict) and "passed" in value and report_passed(value)
        for value in report.values()
    )


def emit_result(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report_passed(report) else 1)


class ImmediateSpeechBackend:
    """Fixture with synchronous successful completion; no physical audio."""

    def start(self, job):
        return job

    def is_active(self, handle):
        return False

    def completion_error(self, handle):
        return None

    def stop(self, handle):
        pass
