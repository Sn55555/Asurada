from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from phase3_companion_mode_regression import _make_state
from regression_support import emit_result, report_passed, runtime_clock
from run_regressions import parse_report
from asurada.runtime_context import RuntimeContextDetector


@runtime_clock(1_777_200_000_000)
def run_regression() -> dict:
    state = _make_state(source_timestamp_ms=1_777_200_000_000)
    detector = RuntimeContextDetector()
    env = os.environ.copy()
    core = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join([str(core / "src"), str(core / "scripts")])
    failed = subprocess.run(
        [sys.executable, "-c", "from regression_support import emit_result; emit_result({'passed': False})"],
        capture_output=True, text=True, env=env, check=False,
    )
    checks = {
        "fixed_clock_keeps_fixture_fresh": detector.detect(state=state).racing_active,
        "expiry_boundary_still_fresh": detector.detect(state=state, now_ms=state.source_timestamp_ms + 15_000).racing_active,
        "expired_snapshot_still_rejected": not detector.detect(state=state, now_ms=state.source_timestamp_ms + 15_001).racing_active,
        "missing_timestamp_rejected": not detector.detect(state=_make_state(source_timestamp_ms=0)).racing_active,
        "business_false_not_failure": report_passed({"passed": True, "requires_confirmation": False}),
        "explicit_failure_wins": not report_passed({"passed": False, "checks": {"success": True}}),
        "malformed_status_rejected": not report_passed({"passed": "true"}),
        "empty_report_rejected": not report_passed({}),
        "flat_assertions_supported": report_passed({"first": True, "second": True}),
        "group_failure_detected": not report_passed({"first": {"passed": True}, "second": {"passed": False}}),
        "prefix_log_supported": parse_report("log: {not json}\n{\"passed\": true}\n")["passed"] is True,
        "failure_exits_nonzero": failed.returncode == 1 and parse_report(failed.stdout)["passed"] is False,
    }
    return {"passed": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    emit_result(run_regression())
