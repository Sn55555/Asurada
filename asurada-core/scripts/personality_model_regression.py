"""Replay a reproducible S6 safety matrix through the personality model worker."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from itertools import product
import json
from pathlib import Path
from threading import Event
import time

from asurada.personality_llm import PersonalityLlm, PersonalityLlmRequest
from regression_support import emit_result


OPPORTUNITIES = ("overtake", "fastest_lap", "finish")
TONES = ("calm", "firm", "concerned", "excited")
VALID_FRAGMENT = "干得漂亮。"
CASES = (
    ("valid", "ok"),
    ("wrong_reference", "invalid"),
    ("unknown_field", "invalid"),
    ("missing_fragment", "invalid"),
    ("wrong_type", "invalid"),
    ("numeric_claim", "invalid"),
    ("chinese_numeric_claim", "invalid"),
    ("driving_instruction", "invalid"),
    ("mixed_instruction", "invalid"),
    ("provider_error", "error"),
    ("familiarity", "stage-dependent"),
)


class FixtureProvider:
    def __init__(self, case):
        self.case = case
        self.calls = []

    def generate(self, request, context):
        self.calls.append(request)
        if self.case == "provider_error":
            raise ConnectionError("synthetic model disconnect")
        payload = {"decision_ref": request.decision_ref, "fragment": VALID_FRAGMENT}
        if self.case == "wrong_reference":
            payload["decision_ref"] = "other-opportunity"
        if self.case == "unknown_field":
            payload["strategy"] = "box"
        if self.case == "missing_fragment":
            del payload["fragment"]
        if self.case == "wrong_type":
            payload["fragment"] = 42
        if self.case == "numeric_claim":
            payload["fragment"] = "轮胎还能跑12圈。"
        if self.case == "chinese_numeric_claim":
            payload["fragment"] = "领先两秒。"
        if self.case == "driving_instruction":
            payload["fragment"] = "下一圈进站。"
        if self.case == "mixed_instruction":
            payload["fragment"] = "干得漂亮。现在全油门。"
        if self.case == "familiarity":
            payload["fragment"] = "有默契"
        return payload


class BlockingProvider(FixtureProvider):
    def __init__(self):
        super().__init__("valid")
        self.entered = Event()
        self.release = Event()
        self.finished = Event()

    def generate(self, request, context):
        self.entered.set()
        self.release.wait(2)
        try:
            return super().generate(request, context)
        finally:
            self.finished.set()


def await_result(worker, *, limit=2):
    until = time.monotonic() + limit
    while time.monotonic() < until:
        result = worker.poll()
        if result is not None:
            return result
        time.sleep(.001)
    return None


def request_for(case, stage, opportunity, tone):
    return PersonalityLlmRequest(
        request_id=f"fixture:{case}:H{stage}:{opportunity}:{tone}",
        decision_ref=f"FIXTURE_H{stage}_{opportunity.upper()}",
        opportunity=opportunity, stage=stage, tone=tone,
    )


def exercise(case, expected, stage, opportunity, tone):
    request = request_for(case, stage, opportunity, tone)
    provider = FixtureProvider(case)
    worker = PersonalityLlm(mode="shadow", provider=provider)
    try:
        started = worker.start(request)
        result = await_result(worker) if started else None
    finally:
        worker.close()
    fragment = VALID_FRAGMENT if expected == "ok" else None
    if expected == "stage-dependent":
        expected, fragment = ("ok", "有默契。") if stage >= 2 else ("invalid", None)
    passed = bool(result and result.request_id == request.request_id and result.status == expected
                  and result.fragment == fragment
                  and provider.calls == [request])
    return {"case": case, "request": asdict(request), "expected": expected,
            "actual": asdict(result) if result else None, "passed": passed}


def exercise_lifecycle():
    checks = {}
    request = request_for("lifecycle", 2, "overtake", "excited")
    provider = FixtureProvider("valid")
    worker = PersonalityLlm(mode="disabled", provider=provider)
    try:
        checks["disabled_never_calls_provider"] = not worker.start(request) and worker.poll() is None and not provider.calls
    finally:
        worker.close()

    provider = BlockingProvider()
    worker = PersonalityLlm(mode="shadow", provider=provider, timeout_ms=100)
    try:
        started = worker.start(request) and provider.entered.wait(1)
        replacement = request_for("replacement", 2, "finish", "calm")
        checks["busy_rejects_another_request"] = started and not worker.start(replacement)
        result = await_result(worker)
        checks["deadline_has_no_fragment"] = bool(result and result.status == "timeout" and result.fragment is None)
        provider.release.set()
        checks["late_result_is_discarded"] = provider.finished.wait(1) and worker.poll() is None
    finally:
        provider.release.set()
        worker.close()

    provider = FixtureProvider("valid")
    worker = PersonalityLlm(mode="shadow", provider=provider)
    try:
        critical = request_for("critical", 3, "safety_car", "excited")
        checks["critical_never_calls_provider"] = not worker.start(critical) and worker.poll() is None and not provider.calls
    finally:
        worker.close()

    provider = BlockingProvider()
    worker = PersonalityLlm(mode="shadow", provider=provider)
    try:
        started = worker.start(request) and provider.entered.wait(1)
        worker.cancel()
        provider.release.set()
        checks["cancelled_result_is_discarded"] = started and provider.finished.wait(1) and worker.poll() is None
    finally:
        provider.release.set()
        worker.close()
    return checks


def run():
    rows = [exercise(case, expected, stage, opportunity, TONES[stage])
            for (case, expected), stage, opportunity in product(CASES, range(4), OPPORTUNITIES)]
    checks = {row["request"]["request_id"]: row["passed"] for row in rows}
    checks["at_least_100_distinct_scenes"] = len(checks) == len(rows) >= 100
    checks.update(exercise_lifecycle())
    return {"passed": all(checks.values()), "checks": checks, "mode": "shadow",
            "provider": "fixture", "scene_count": len(rows),
            "outcomes": dict(Counter(row["actual"]["status"] if row["actual"] else "missing" for row in rows)),
            "scenes": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Save the labeled replay evidence as JSON.")
    args = parser.parse_args()
    report = run()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    emit_result(report)
