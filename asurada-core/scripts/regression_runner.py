"""Shared discovery, evidence validation and isolated subprocess execution.

The CLI and pytest adapter deliberately execute existing scripts unchanged.
Only named assertion containers are interpreted; diagnostic business booleans
must never turn into assertions. Each child has its own temp/runtime paths and
process group, so timeouts cannot leave ordinary subprocesses running.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Callable, Iterable

CORE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CORE_ROOT.parent
SUITE_FILE = Path(__file__).with_name("regression_suites.json")


@dataclass(frozen=True)
class RegressionCase:
    path: Path
    serial_reason: str = ""

    @property
    def name(self) -> str:
        return self.path.stem


def discover_regressions(
    suite: str = "contracts", only: Iterable[str] | None = None,
    *, scripts_dir: Path | None = None, manifest: dict | None = None,
) -> list[RegressionCase]:
    """Stable IDs and fail-closed selection shared by all entry points."""
    if suite not in {"contracts", "all", "critical"}:
        raise ValueError(f"Unknown suite: {suite}")
    policy = manifest if manifest is not None else json.loads(SUITE_FILE.read_text())
    paths = sorted((scripts_dir or CORE_ROOT / "scripts").glob("*regression.py"))
    known = {path.stem for path in paths}
    requested = set(only or ())
    if not requested and suite == "critical":
        requested = set(policy["critical"])
    if requested - known:
        raise ValueError(f"Unknown regression scripts: {sorted(requested - known)}")
    if requested:
        paths = [path for path in paths if path.stem in requested]
    elif suite == "contracts":
        paths = [path for path in paths if path.name != "phase1_regression.py"]
    if not paths:
        raise ValueError("No regression scripts selected")
    reasons = policy.get("serial", {})
    rules = policy.get("serial_name_contains", {})
    return [RegressionCase(path, reasons.get(path.stem) or next(
        (reason for token, reason in rules.items() if token in path.stem), ""
    )) for path in paths]


def parse_report(output: str) -> dict:
    decoder = json.JSONDecoder()
    for index, char in enumerate(output):
        if char != "{":
            continue
        try:
            payload, end = decoder.raw_decode(output, index)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and not output[end:].strip():
            return payload
    raise ValueError("No final JSON report in stdout")


def _check_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict) and value.get("passed") is True:
        # Legacy voice checks attach diagnostic fields to a passed assertion.
        return "checks" not in value or _check_map(value["checks"])
    return False


def _check_map(checks: object) -> bool:
    return isinstance(checks, dict) and bool(checks) and all(
        _check_value(value) for value in checks.values()
    )


def evaluate_report(report: dict) -> tuple[str, object]:
    """Require executable assertion evidence as well as a successful exit code.

    Accept the repository's four existing schemas: named checks, flat checks,
    grouped reports, and per-track checks. A naked {passed: true} is insufficient.
    An outer passed:true cannot mask a false or malformed inner assertion.
    """
    if not report:
        return "failed", {}
    if "passed" not in report:
        if all(isinstance(value, bool) for value in report.values()):
            return ("passed" if all(report.values()) else "failed"), report
        if all(isinstance(value, dict) for value in report.values()):
            statuses = [evaluate_report(value)[0] for value in report.values()]
            status = "failed" if "failed" in statuses else (
                "skipped" if all(item == "skipped" for item in statuses) else "passed"
            )
            return status, report
        return "failed", report
    if report["passed"] is not True:
        return "failed", report.get("checks", {})
    if "checks" in report:
        checks = report["checks"]
        if not _check_map(checks):
            return "failed", checks
        return ("skipped" if checks.get("skipped") is True else "passed"), checks
    tracks = report.get("tracks")
    if isinstance(tracks, list) and tracks:
        if not all(isinstance(row, dict) and row.get("passed") is True for row in tracks):
            return "failed", tracks
        return ("skipped" if all(row.get("skipped") is True for row in tracks) else "passed"), tracks
    return "failed", {}


@contextmanager
def resource_gate(serial: bool):
    """Protect fixed-port and timing-sensitive contracts across CLI/xdist runs.

    Ordinary cases hold shared locks; exclusive cases run without other suite
    children. Works with pytest's default --dist=load and -n auto. Locks are
    OS-released on runner failure and do not touch live service locks.
    """
    key = hashlib.sha256(str(REPO_ROOT).encode()).hexdigest()[:16]
    directory = Path("/tmp") / f"asurada-regression-locks-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    with (directory / f"{key}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if serial else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _child_environment(directory: Path) -> dict[str, str]:
    # Never inherit live runtime paths, sockets, providers or model activation.
    env = {key: value for key, value in os.environ.items() if not key.startswith("ASURADA_")}
    env["PYTHONPATH"] = os.pathsep.join([str(CORE_ROOT / "src"), str(CORE_ROOT / "scripts")])
    env["ASURADA_RUNTIME_DIR"] = str(directory / "runtime")
    env["ASURADA_SPEECH_SOCKET"] = str(directory / "voice.sock")
    for key in ("TMPDIR", "TMP", "TEMP"):
        env[key] = str(directory)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    return env


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_case(case: RegressionCase, *, output: Path, timeout: float = 120.0) -> dict:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    output.mkdir(parents=True, exist_ok=True)
    result = {"script": case.name, "status": "failed", "serial_reason": case.serial_reason}
    started = time.perf_counter()
    stdout = stderr = ""
    with resource_gate(bool(case.serial_reason)):
        result["resource_wait_seconds"] = round(time.perf_counter() - started, 3)
        with tempfile.TemporaryDirectory(prefix="asurada-reg-", dir="/tmp") as directory:
            command = [sys.executable, str(case.path)]
            if case.name == "phase1_regression":
                command += ["--report-path", str(output / "phase1-full.json")]
            try:
                process = subprocess.Popen(
                    command, cwd=REPO_ROOT, env=_child_environment(Path(directory)),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    encoding="utf-8", errors="replace", start_new_session=True,
                )
                try:
                    stdout, stderr = process.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    _kill_group(process)
                    stdout, stderr = process.communicate(timeout=5)
                    result["error"] = f"Timed out after {timeout}s"
                finally:
                    # Reap descendants even when a buggy script fails to close
                    # them. This is the child's group, never the live service's.
                    _kill_group(process)
                    process.wait()
                result["exit_code"] = process.returncode
                if "error" not in result:
                    status, checks = evaluate_report(parse_report(stdout))
                    result["reported_passed"] = status != "failed"
                    result["checks"] = checks
                    if process.returncode == 0:
                        result["status"] = status
                    if status == "failed":
                        result["error"] = "Report assertions missing, malformed or failed"
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                result["error"] = str(exc)
    (output / f"{case.name}.stdout.txt").write_text(stdout, encoding="utf-8")
    (output / f"{case.name}.stderr.txt").write_text(stderr, encoding="utf-8")
    result["seconds"] = round(time.perf_counter() - started, 3)
    (output / f"{case.name}.result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def run_cases(
    cases: list[RegressionCase], *, output: Path, timeout: float = 120.0,
    parallel: int = 1, on_result: Callable[[dict], None] | None = None,
) -> list[dict]:
    if parallel < 1:
        raise ValueError("parallel must be positive")
    results = []

    def record(row: dict) -> None:
        results.append(row)
        if on_result:
            on_result(row)

    if parallel == 1:
        for case in cases:
            record(run_case(case, output=output, timeout=timeout))
    else:
        # Avoid occupying pool slots with exclusive-lock waiters. The OS lock
        # still protects against other CLI invocations and pytest workers.
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = [pool.submit(run_case, case, output=output, timeout=timeout)
                       for case in cases if not case.serial_reason]
            for future in as_completed(futures):
                record(future.result())
        for case in cases:
            if case.serial_reason:
                record(run_case(case, output=output, timeout=timeout))
    return sorted(results, key=lambda row: row["script"])
