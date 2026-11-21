"""Exercise the optional model through the actual speech owner and authority."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
from statistics import median, quantiles
from tempfile import TemporaryDirectory
import threading
import time
from unittest.mock import patch

from asurada.buffered_ingest import BufferedPacketSource
from asurada.config import AppConfig
from asurada.interaction import build_snapshot_query_input_event
from asurada.models import StrategyDecision
from asurada.output import ConsoleVoiceOutput
from asurada.personality_llm import OllamaProvider, PersonalityLlm, PersonalityLlmRequest
from asurada.personality_runtime import PersonalityRuntime
from asurada.snapshot_contract import snapshot_payload
from asurada.speech_client import SharedSpeechClient
from asurada.speech_service import SpeechService
from asurada.strategy import StrategyEngine
from personality_acceptance_regression import capture_rows, low_load_state, run_capture
from phase3_voice_regression import FakeSpeechBackend
from regression_support import emit_result


class HeldProvider:
    def __init__(self, fragment="干得漂亮"):
        self.fragment = fragment
        self.entered = threading.Event()
        self.release = threading.Event()

    def generate(self, request, context):
        self.entered.set()
        if not self.release.wait(context.remaining()):
            raise TimeoutError
        return {"decision_ref": request.decision_ref, "fragment": self.fragment}


def wait_for(predicate, tick=lambda: None):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        tick()
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("speech/model transition timed out")


def make_output(mode="enabled", timeout=600, fragment="干得漂亮"):
    provider = HeldProvider(fragment)
    output = ConsoleVoiceOutput(
        backend=FakeSpeechBackend(),
        personality_llm=PersonalityLlm(mode=mode, provider=provider, timeout_ms=timeout),
    )
    return output, provider


def optional_case(mode, *, fragment="干得漂亮", timeout=600, release=True):
    output, provider = make_output(mode, timeout, fragment)
    try:
        state = low_load_state(stage=2, kind="overtake")
        before = output.emit(StrategyDecision([]), state=state, render=False)["event"]
        if mode == "disabled":
            assert not provider.entered.is_set()
        else:
            assert provider.entered.wait(.25)
            if release:
                provider.release.set()
        wait_for(lambda: output._active_envelope is not None, output.tick)
        wait_for(lambda: not output.personality_model_status()["pending"], output.tick)
        job = output._active_envelope.job
        return before["event_type"], job.speak_text, job.metadata["personality"]
    finally:
        provider.release.set()
        output.shutdown()


def interrupted_case(interrupt):
    output, provider = make_output()
    state = low_load_state(stage=2, kind="overtake")
    try:
        output.emit(StrategyDecision([]), state=state, render=False)
        assert provider.entered.wait(.25)
        interrupt(output, state)
        provider.release.set()
        output.tick()
        assert output._personality_generation is None
        assert output.personality_model_status()["counts"].get("cancelled") == 1
        assert not any(handle["job"]["action_code"] == "PERSONALITY_OVERTAKE" for handle in output.backend._handles)
    finally:
        provider.release.set()
        output.shutdown()


def stop(output, state):
    event = build_snapshot_query_input_event(state=state, query_kind="stop")
    output.emit_control_query_bundle(
        state=state, bundle={"structured_query": {"query_kind": "stop"}, "input_event": event.to_dict()},
        render=False,
    )


def urgent(output, state):
    config = AppConfig()
    critical = replace(state, safety_car="FULL", personality=None, assessment=None)
    decision = StrategyEngine(config.thresholds, config.usage_hooks_path).evaluate(critical, [])
    text = decision.debug["arbiter_v2"]["output"]["final_voice_action"]["speak_text"]
    event = output.emit(decision, state=critical, render=False)["event"]
    assert event["action_code"] == "SAFETY_CAR" and event["speak_text"] == text


def latest_authority_case():
    output, provider = make_output()
    config = AppConfig()
    state = low_load_state(stage=2, kind="overtake")
    decision = StrategyEngine(config.thresholds, config.usage_hooks_path).evaluate(state, [])
    with TemporaryDirectory(dir="/tmp") as temp:
        latest = Path(temp) / "latest.json"
        latest.write_text(json.dumps(snapshot_payload(state, decision)))
        service = SpeechService(Path(temp) / "voice.sock", output=output, session_source=latest).start()
        try:
            client = SharedSpeechClient(service.path)
            client.emit(decision, state=state, render=False)
            assert provider.entered.wait(.25)
            changed = replace(state, personality=replace(state.personality, low_load=False))
            next_snapshot = latest.with_suffix(".tmp")
            next_snapshot.write_text(json.dumps(snapshot_payload(changed, decision)))
            next_snapshot.replace(latest)
            provider.release.set()
            wait_for(lambda: not output.personality_model_status()["pending"])
            events = [entry["event"] for entry in output.read_events(limit=32)["events"]]
            assert any(row["event_type"] == "suppress"
                       and row["metadata"].get("reason") == "delivery_no_longer_applicable" for row in events)
            assert not output.backend._handles
        finally:
            provider.release.set()
            service.close()


def run():
    baseline = optional_case("disabled")
    shadow = optional_case("shadow")
    enabled = optional_case("enabled")
    invalid = optional_case("enabled", fragment="本圈进站")
    timed_out = optional_case("enabled", timeout=80, release=False)
    interrupted_case(stop)
    interrupted_case(urgent)
    interrupted_case(lambda output, state: output.emit(
        StrategyDecision([]), state=replace(state, personality=replace(state.personality, low_load=False)),
        render=False,
    ))
    latest_authority_case()
    return {
        "disabled_and_shadow_play_template_immediately": baseline[:2] == shadow[:2] and shadow[0] == "start",
        "enabled_retains_template_and_adds_approved_fragment": enabled[0] == "idle"
        and enabled[1] == "干得漂亮。 " + baseline[1] and enabled[2]["model"]["used"],
        "invalid_and_timeout_fall_back": invalid[1] == timed_out[1] == baseline[1]
        and invalid[2]["model"]["status"] == "invalid" and timed_out[2]["model"]["status"] == "timeout",
        "stop_urgent_and_changed_context_discard": True,
        "owner_revalidates_published_authority_before_backend_start": True,
    }


def benchmark():
    fields = ("decode_latency_ms", "strategy_latency_ms", "pipeline_latency_ms")
    sample_sets = {"disabled": [], "shadow": []}
    ingress = {mode: [] for mode in sample_sets}
    packets = tuple(capture_rows())
    llm = PersonalityLlm("shadow", provider=OllamaProvider())

    def paced_packets():
        for packet in packets:
            yield packet
            time.sleep(.001)

    try:
        for index in range(30):
            modes = ("disabled", "shadow") if index % 2 else ("shadow", "disabled")
            for mode in modes:
                if mode == "shadow":
                    request = PersonalityLlmRequest(
                        f"bench:{index}", f"fixture:{index}", "overtake", 2, "excited",
                    )
                    wait_for(lambda: llm.start(request))
                source = BufferedPacketSource(paced_packets())
                rows = run_capture(PersonalityRuntime(), packets=source)
                if index >= 2:
                    sample_sets[mode].extend(decision.debug["runtime_timing"] for _, decision in rows)
                    ingress[mode].append(source.snapshot())
                wait_for(lambda: not llm.pending, llm.poll)
        generation_counts = llm.snapshot()["counts"]
    finally:
        llm.close()

    def describe(values):
        percentiles = quantiles(values, n=100, method="inclusive")
        return {"p50": round(median(values), 4), "p95": round(percentiles[94], 4),
                "p99": round(percentiles[98], 4)}

    return {
        "scope": "Paced packet replay into the UDP receive queue with a concurrent local Ollama worker",
        "producer_interval_ms": 1,
        "generation_counts": generation_counts,
        "receive_queue": {
            mode: {"received": sum(row["received"] for row in rows),
                   "delivered": sum(row["delivered"] for row in rows),
                   "dropped": sum(row["dropped_oldest"] for row in rows),
                   "max_depth": max(row["max_depth"] for row in rows),
                   "max_remaining_at_end": max(row["queued"] for row in rows)}
            for mode, rows in ingress.items()
        },
        "timing": {
            mode: {
                "snapshots": len(rows),
                **{field: describe([row[field] for row in rows]) for field in fields},
            }
            for mode, rows in sample_sets.items()
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    with patch.dict(os.environ, {"ASURADA_PERSONALITY_ENABLED": "1", "ASURADA_HUMOR_ENABLED": "1"}):
        if args.benchmark:
            print(json.dumps(benchmark(), ensure_ascii=False, indent=2))
        else:
            emit_result(run())
