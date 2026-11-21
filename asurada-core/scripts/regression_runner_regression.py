"""Regression runner acceptance using actual child processes and bad reports."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

import regression_runner as runner
from regression_support import emit_result


def run() -> dict:
    checks = {}
    examples = [
        ({}, "failed"),
        ({"passed": True}, "failed"),
        ({"passed": "true", "checks": {"ok": True}}, "failed"),
        ({"passed": True, "checks": {}}, "failed"),
        ({"passed": True, "checks": {"bad": False}}, "failed"),
        ({"passed": False, "checks": {"ok": True}}, "failed"),
        ({"passed": True, "checks": {"ok": 1}}, "failed"),
        ({"passed": True, "checks": {"ok": True}, "business_flag": False}, "passed"),
        ({"first": True, "second": True}, "passed"),
        ({"passed": True, "checks": {"nested": {"passed": True, "value": False}}}, "passed"),
        ({"passed": True, "checks": {"nested": {"passed": True, "checks": {"bad": False}}}}, "failed"),
        ({"group": {"passed": True, "checks": {"ok": True}}}, "passed"),
        ({"group": {"passed": True}}, "failed"),
        ({"passed": True, "checks": {"skipped": True}}, "skipped"),
        ({"passed": True, "tracks": [{"passed": True, "track": "Shanghai"}]}, "passed"),
        ({"passed": True, "tracks": [{"passed": False}]}, "failed"),
        ({"passed": True, "tracks": [{"passed": True, "skipped": True}]}, "skipped"),
    ]
    for index, (report, expected) in enumerate(examples):
        checks[f"report_schema_{index}"] = runner.evaluate_report(report)[0] == expected
    checks["log_prefix_supported"] = runner.parse_report('log {not json}\n{"passed":true}\n') == {"passed": True}
    for label, text in (("trailing_noise", '{"passed":true}\nnoise'), ("missing_json", "exit zero only")):
        try:
            runner.parse_report(text)
            checks[label] = False
        except ValueError:
            checks[label] = True

    with tempfile.TemporaryDirectory(prefix="asurada-runner-contract-") as temporary:
        root = Path(temporary)
        scripts = root / "scripts"
        scripts.mkdir()
        output = root / "evidence"

        def script(name: str, code: str) -> runner.RegressionCase:
            path = scripts / f"{name}_regression.py"
            path.write_text(code)
            return runner.RegressionCase(path)

        cases = [
            script("exit_only", "print('no report')"),
            script("fake_pass", "print('{\"passed\": true}')"),
            script("inner_fail", "print('{\"passed\": true, \"checks\": {\"bad\": false}}')"),
            script("nonzero", "print('{\"passed\": true, \"checks\": {\"ok\": true}}'); raise SystemExit(7)"),
            script("good", "print('{\"passed\": true, \"checks\": {\"ok\": true}}')"),
        ]
        script("phase1", "raise AssertionError('external suite must not run')")
        # Use a separate resource-lock key for nested runner acceptance so the
        # outer runner's exclusive lock cannot deadlock its own test children.
        with patch.object(runner, "REPO_ROOT", root):
            results = runner.run_cases(cases, output=output, parallel=2)
            checks["exit_and_assertions_both_required"] = {
                row["script"]: row["status"] for row in results
            } == {case.name: "passed" if case.name == "good_regression" else "failed" for case in cases}
            checks["nonzero_preserved"] = next(row for row in results if row["script"] == "nonzero_regression")["exit_code"] == 7
            checks["stdout_stderr_results_preserved"] = all(
                (output / f"{case.name}.{suffix}").is_file()
                for case in cases for suffix in ("stdout.txt", "stderr.txt", "result.json")
            )

            policy = {"critical": ["good_regression"], "serial": {"good_regression": "fixture"}}
            discovered = runner.discover_regressions(scripts_dir=scripts, manifest=policy)
            checks["contracts_exclude_external_replay"] = [case.name for case in discovered] == sorted(case.name for case in cases)
            checks["critical_same_discovery"] = [case.name for case in runner.discover_regressions("critical", scripts_dir=scripts, manifest=policy)] == ["good_regression"]
            checks["serial_policy_attached"] = next(case for case in discovered if case.name == "good_regression").serial_reason == "fixture"
            try:
                runner.discover_regressions(only=["misspelled"], scripts_dir=scripts, manifest=policy)
                checks["unknown_selection_rejected"] = False
            except ValueError:
                checks["unknown_selection_rejected"] = True

            timing = []
            for name in ("parallel_a", "parallel_b", "exclusive"):
                record = root / f"{name}.json"
                code = (
                    "import json,os,pathlib,tempfile,time\n"
                    "start=time.time(); temporary=pathlib.Path(tempfile.gettempdir())/'shared-name.txt'\n"
                    f"temporary.write_text({name!r}); time.sleep(.25)\n"
                    f"ok=temporary.read_text()=={name!r} and 'ASURADA_SECRET_TEST' not in os.environ\n"
                    "runtime=os.environ['ASURADA_RUNTIME_DIR']\n"
                    f"pathlib.Path({str(record)!r}).write_text(json.dumps(dict(start=start,end=time.time(),temp=str(temporary),runtime=runtime)))\n"
                    "print(json.dumps(dict(passed=ok,checks=dict(isolated=ok))))\n"
                )
                case = script(name, code)
                timing.append(runner.RegressionCase(case.path, "exclusive fixture" if name == "exclusive" else ""))
            with patch.dict(os.environ, ASURADA_SECRET_TEST="must-not-inherit"):
                rows = runner.run_cases(timing, output=output, parallel=2)
            records = [json.loads((root / f"{name}.json").read_text()) for name in ("parallel_a", "parallel_b", "exclusive")]
            checks["isolated_children_pass"] = all(row["status"] == "passed" for row in rows)
            checks["parallel_children_actually_overlap"] = max(row["start"] for row in records[:2]) < min(row["end"] for row in records[:2])
            checks["exclusive_child_waits_for_pool"] = records[2]["start"] >= max(row["end"] for row in records[:2])
            checks["unique_temp_and_runtime_paths"] = len({row["temp"] for row in records}) == len({row["runtime"] for row in records}) == 3
            checks["temporary_paths_cleaned"] = all(not Path(row["temp"]).parent.exists() for row in records)

            marker = root / "orphan-wrote"
            child_code = f"import time,pathlib; time.sleep(.6); pathlib.Path({str(marker)!r}).write_text('orphan')"
            timeout_case = script("timeout", (
                "import subprocess,sys,time\n"
                f"subprocess.Popen([sys.executable,'-c',{child_code!r}])\n"
                "print('descendant_started',flush=True); time.sleep(30)\n"
            ))
            row = runner.run_case(timeout_case, output=output, timeout=.3)
            time.sleep(.6)
            checks["timeout_failed"] = row["status"] == "failed" and row.get("error") == "Timed out after 0.3s"
            checks["timeout_partial_output_kept"] = "descendant_started" in (output / "timeout_regression.stdout.txt").read_text()
            checks["timeout_process_group_stopped"] = not marker.exists()
    return {"passed": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    emit_result(run())
