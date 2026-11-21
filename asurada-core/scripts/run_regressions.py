from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

from regression_runner import CORE_ROOT, discover_regressions, parse_report, run_cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Run regression contracts and preserve their evidence.")
    parser.add_argument("--suite", choices=("contracts", "all", "critical"), default="contracts")
    parser.add_argument("--only", action="append", help="Exact script stem; repeat to select multiple scripts.")
    parser.add_argument("--timeout", type=float, default=120.0, help="Seconds allowed for each script.")
    parser.add_argument("--parallel", type=int, default=1, help="Concurrent isolated children; sensitive cases stay serial.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--list", action="store_true", help="Print selected script IDs and isolation policy, without running.")
    args = parser.parse_args()
    if args.timeout <= 0 or args.parallel < 1:
        parser.error("--timeout and --parallel must be positive")
    try:
        cases = discover_regressions(args.suite, args.only)
    except ValueError as exc:
        parser.error(str(exc))
    if args.list:
        print(json.dumps([{"script": case.name, "serial_reason": case.serial_reason} for case in cases], indent=2))
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (args.output or CORE_ROOT / "runtime_logs" / "regression" / stamp).resolve()
    results = run_cases(
        cases, output=output, timeout=args.timeout, parallel=args.parallel,
        on_result=lambda row: print(f"{row['status'].upper()} {row['script']} ({row['seconds']}s)", flush=True),
    )
    counts = {status: sum(row["status"] == status for row in results) for status in ("passed", "failed", "skipped")}
    report = {
        "passed": bool(results) and counts["failed"] == 0,
        "scope": args.suite if not args.only else "selected",
        "python": sys.executable,
        "parallel": args.parallel,
        "serial_cases": sum(bool(case.serial_reason) for case in cases),
        "lightgbm_available": importlib.util.find_spec("lightgbm") is not None,
        "counts": counts,
        "results": results,
    }
    path = output / "summary.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {path}")
    print(json.dumps({"passed": report["passed"], "counts": counts}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
