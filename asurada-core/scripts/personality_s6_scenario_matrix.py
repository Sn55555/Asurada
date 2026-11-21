"""Compare 108 labeled race contexts across the three S6 speech-owner modes."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from itertools import product
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

from asurada.config import AppConfig
from asurada.models import StrategyDecision
from asurada.output import ConsoleVoiceOutput
from asurada.personality_llm import OllamaProvider, PersonalityLlm, validate_fragment
from asurada.speech_clock import speech_time
from asurada.strategy import StrategyEngine
from benchmark_personality_model import percentile_metrics
from personality_acceptance_regression import low_load_state
from personality_model_delivery_regression import stop, wait_for
from personality_model_regression import FixtureProvider, OPPORTUNITIES, request_for
from phase3_voice_regression import FakeSpeechBackend
from regression_support import emit_result


CONDITIONS = ("safe", "unsafe", "busy", "quiet", "expired", "repeat", "stop", "session_change", "risk")
MODES = ("disabled", "shadow", "enabled")


def scenario(mode, provider, stage, opportunity, condition, strategy):
    output = ConsoleVoiceOutput(backend=FakeSpeechBackend(), personality_llm=PersonalityLlm(mode, provider=provider))
    try:
        state = low_load_state(stage=stage, kind=opportunity, marker=f"matrix:{condition}", safe=condition != "unsafe")
        expected_risk_text = None
        decision = StrategyDecision([])
        if condition == "expired":
            state.personality = replace(state.personality, opportunity_age_s=2.01)
        if condition == "quiet":
            output.configure_personality({"quiet": True})
        if condition == "busy":
            output.reserve_query_turn("matrix-query", speech_time() + 10)
        if condition == "risk":
            state = replace(state, safety_car="FULL", assessment=None)
            decision = strategy.evaluate(state, [])
            expected_risk_text = decision.debug["arbiter_v2"]["output"]["final_voice_action"]["speak_text"]

        started = time.perf_counter()
        first = output.emit(decision, state=state, render=False)["event"]
        submit_ms = (time.perf_counter() - started) * 1000
        if condition == "stop":
            stop(output, state)
        if condition == "session_change":
            output.bind_session(replace(state, session_uid="matrix-new-session", personality=None))
        wait_for(lambda: not output.personality_model_status()["pending"], output.tick)
        if condition == "repeat":
            output.backend.complete_all()
            output.tick()
            output.emit(StrategyDecision([]), state=state, render=False)
            wait_for(lambda: not output.personality_model_status()["pending"], output.tick)

        jobs = [handle["job"] for handle in output.backend._handles]
        spoken = [{"action": job["action_code"], "text": job["speak_text"], "model":
                   job["metadata"].get("personality", {}).get("model")} for job in jobs]
        optional_active = any(handle["active"] and handle["job"]["metadata"].get("optional_personality")
                              for handle in output.backend._handles)
        stats = output.personality_model_status()["counts"]
        return {"mode": mode, "event": first["event_type"], "speech": spoken, "optional_active": optional_active,
                "stats": stats, "submit_ms": submit_ms, "expected_risk_text": expected_risk_text}
    finally:
        output.shutdown()


def check_case(stage, opportunity, condition, results):
    baseline, shadow, enabled = results
    model_eligible = stage >= 2 and condition in {"safe", "repeat", "stop", "session_change"}
    counters_match = (baseline["stats"].get("started", 0) == 0
                      and all(row["stats"].get("started", 0) == int(model_eligible) for row in results[1:]))
    if condition == "risk":
        return counters_match and all(
            row["speech"] == [{"action": "SAFETY_CAR", "text": row["expected_risk_text"], "model": None}]
            and bool(row["expected_risk_text"]) and not row["optional_active"] for row in results)
    if condition in {"unsafe", "busy", "quiet", "expired"}:
        return counters_match and all(not row["speech"] and not row["optional_active"] for row in results)
    if condition in {"stop", "session_change"}:
        return (counters_match and all(not row["optional_active"] and len(row["speech"]) <= 1 for row in results)
                and (not model_eligible or not enabled["speech"] and enabled["stats"].get("cancelled") == 1))

    # Repeat includes two submissions but allows only the first to start.
    if not counters_match or not all(len(row["speech"]) == 1 for row in results):
        return False
    original = baseline["speech"][0]
    if original["action"] != f"PERSONALITY_{opportunity.upper()}" or shadow["speech"][0] != original:
        return False
    submitted = enabled["speech"][0]
    if submitted["action"] != original["action"]:
        return False
    model = submitted["model"]
    if not model_eligible:
        return submitted == original
    if not model:
        return False
    if not model.get("used"):
        return model["status"] in {"invalid", "timeout", "error"} and submitted["text"] == original["text"]
    if not submitted["text"].endswith(" " + original["text"]):
        return False
    prefix = submitted["text"][:-(len(original["text"]) + 1)]
    request = request_for("speech-matrix", stage, opportunity, "calm")
    return validate_fragment({"decision_ref": request.decision_ref, "fragment": prefix}, request) == prefix


def run(provider, provider_name):
    config = AppConfig()
    strategy = StrategyEngine(config.thresholds, config.usage_hooks_path)
    rows = []
    checks = {}
    with patch.dict(os.environ, {"ASURADA_PERSONALITY_ENABLED": "1", "ASURADA_HUMOR_ENABLED": "1"}):
        for stage, opportunity, condition in product(range(4), OPPORTUNITIES, CONDITIONS):
            results = [scenario(mode, provider, stage, opportunity, condition, strategy) for mode in MODES]
            case = f"H{stage}:{opportunity}:{condition}"
            checks[case] = check_case(stage, opportunity, condition, results)
            rows.append({"id": case, "stage": stage, "opportunity": opportunity, "condition": condition, "modes": results})
    checks["all_108_distinct_cases"] = len(checks) == 108
    summaries = {}
    for index, mode in enumerate(MODES):
        results = [row["modes"][index] for row in rows]
        counts = Counter()
        for result in results:
            counts.update(result["stats"])
        summaries[mode] = {"stats": dict(counts), "submit_ms": percentile_metrics(row["submit_ms"] for row in results)}
    return {"passed": all(checks.values()), "checks": checks, "provider": provider_name, "deadline_ms": 600,
            "scene_count": len(rows), "speech_owner_comparisons": len(rows) * len(MODES), "summaries": summaries,
            "scope": "Synthetic context through ConsoleVoiceOutput and fake audio, real Ollama only when selected.", "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", help="Exact tag to exercise on loopback or private tunnel. Omit for the no-network fixture.")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    provider = OllamaProvider(args.base_url, args.model, seed=42) if args.model else FixtureProvider("valid")
    report = run(provider, args.model or "fixture")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    emit_result({key: value for key, value in report.items() if key != "rows"})
