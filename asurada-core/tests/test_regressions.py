"""Adapt script evidence to pytest; exit zero alone never passes a contract."""
import json

import pytest

from regression_runner import run_case


@pytest.mark.regression
def test_regression(regression_case, request):
    result = run_case(
        regression_case,
        output=request.config._asurada_evidence_dir,
        timeout=request.config.getoption("regression_timeout"),
    )
    if result["status"] == "skipped":
        pytest.skip(f"Contract reported unavailable dependency/evidence: {result['checks']}")
    assert result["status"] == "passed", json.dumps(result, ensure_ascii=False, indent=2)
