"""Pytest uses precisely the CLI's script discovery and isolation policy."""
from datetime import datetime, timezone
import os
from pathlib import Path

import pytest

from regression_runner import CORE_ROOT, discover_regressions


def pytest_addoption(parser):
    group = parser.getgroup("asurada-regressions")
    group.addoption("--regression-suite", choices=("contracts", "critical", "all"), default="contracts")
    group.addoption("--regression-only", action="append", help="Exact script stem; repeat to select multiple contracts.")
    group.addoption("--regression-timeout", type=float, default=120.0)
    group.addoption("--regression-output", type=Path)


def pytest_configure(config):
    if config.getoption("regression_timeout") <= 0:
        raise pytest.UsageError("--regression-timeout must be positive")
    # xdist workers inherit this per-invocation path from the controller;
    # concurrent pytest invocations therefore never overwrite one another.
    path = config.getoption("regression_output")
    if path is None:
        key = "ASURADA_PYTEST_EVIDENCE_DIR"
        if not hasattr(config, "workerinput"):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            os.environ[key] = str(CORE_ROOT / "runtime_logs" / "pytest" / stamp)
        path = Path(os.environ[key])
    config._asurada_evidence_dir = path.resolve()


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_auto_num_workers(config):
    # Models start native threads too. Explicit -n N remains available, while
    # auto has a predictable memory/process budget on large development hosts.
    return min(4, os.cpu_count() or 1)


def pytest_generate_tests(metafunc):
    if "regression_case" not in metafunc.fixturenames:
        return
    try:
        cases = discover_regressions(
            metafunc.config.getoption("regression_suite"),
            metafunc.config.getoption("regression_only"),
        )
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
    metafunc.parametrize("regression_case", [
        pytest.param(case, id=case.name, marks=[pytest.mark.serial] if case.serial_reason else [])
        for case in cases
    ])
