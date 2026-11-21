"""Reproducible personality fixtures through the UDP pipeline and shared scheduler."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import statistics
import struct
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from asurada.assessment import assess_domain
from asurada.capture_ingest import CaptureJsonlSource
from asurada.config import AppConfig
from asurada.decode import decode_snapshot
from asurada.interaction import StructuredQuerySchema, render_structured_query_response
from asurada.models import StrategyDecision
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from asurada.tts_backends import resolve_default_speech_backend
from asurada.pdu import PacketEnvelope, RawPacket
from asurada.pdu_decoder import F125PacketDecoder
from asurada.personality_memory import update_database
from asurada.personality_runtime import PersonalityRuntime
from asurada.runtime_pipeline import StrategyRuntimePipeline
from asurada.snapshot_contract import snapshot_payload
from asurada.speech_clock import speech_time
from asurada.speech_client import SharedSpeechClient
from asurada.speech_service import SpeechService
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine
from asurada.udp_capture import RawPacketCaptureRecorder
from asurada.voice_input import VoiceInputCoordinator
from phase3_voice_regression import FakeSpeechBackend, make_state, make_strategy_decision
from phase3_voice_input_regression import _make_turn
from regression_support import emit_result

CORE = Path(__file__).resolve().parents[1]
FIXTURE = CORE / "data/capture_samples/f1_25_udp_frame_fixture.jsonl"
HEADER_SIZE = F125PacketDecoder.HEADER_SIZE
BASE_TIME = 1774000000000
CAR = 3


def capture_rows():
    templates = {packet.payload[6]: packet.payload for packet in CaptureJsonlSource(FIXTURE)}

    def packet(kind, frame, session_s, *, serial=None, code=None, detail=b""):
        if kind in templates:
            payload = bytearray(templates[kind])
        else:
            payload = bytearray(F125PacketDecoder.PACKET_SIZES[kind])
            payload[:HEADER_SIZE] = templates[1][:HEADER_SIZE]
            payload[6] = kind
        struct.pack_into("<QfII", payload, 7, 90000001, session_s, frame, serial or frame)
        if kind == 1:
            payload[HEADER_SIZE + 6] = 10  # Race rather than time trial
        if code is not None:
            payload[HEADER_SIZE:HEADER_SIZE + 4] = code
            payload[HEADER_SIZE + 4:HEADER_SIZE + 4 + len(detail)] = detail
        return bytes(payload)

    groups = (
        (10, 10., None, None, b""),
        (11, 11., None, b"COLL", bytes((CAR, 4))),
        (12, 12., None, b"FTLP", struct.pack("<Bf", CAR, 90.1)),
        (13, 13., None, b"OVTK", bytes((CAR, 4))),
        (14, 42., None, None, b""),
        (15, 43., None, b"FLBK", struct.pack("<If", 10, 10.)),
        (10, 10., 16, None, b""),
    )
    receive = BASE_TIME
    for frame, session_s, serial, code, detail in groups:
        if code is not None:
            event = packet(3, frame, session_s, serial=serial, code=code, detail=detail)
            yield RawPacket(receive, event, "127.0.0.1", 20778)
            if code == b"COLL":
                yield RawPacket(receive, event, "127.0.0.1", 20778)
            receive += 1
        for kind in templates:
            yield RawPacket(receive, packet(kind, frame, session_s, serial=serial), "127.0.0.1", 20778)
            receive += 1
    finish = bytearray(packet(8, 11, 11., serial=17))
    finish[HEADER_SIZE] = 22
    player = HEADER_SIZE + 1 + CAR * 46
    finish[player:player + 6] = bytes((5, 7, 10, 0, 1, 3))
    yield RawPacket(receive, bytes(finish), "127.0.0.1", 20778)


class Rows:
    def __init__(self):
        self.items = []

    def append(self, state, decision):
        self.items.append((state, decision))


def run_capture(personality, *, time_live=False, packets=None):
    config = AppConfig()
    rows = Rows()
    pipeline = StrategyRuntimePipeline(
        state_store=UnifiedStateStore(),
        strategy=StrategyEngine(config.thresholds, config.usage_hooks_path),
        voice_output=ConsoleVoiceOutput(backend=NullSpeechBackend()),
        logger=rows, personality=personality, replay=not time_live,
    )
    for packet in capture_rows() if packets is None else packets:
        pipeline.ingest_packet(packet)
    return rows.items


def low_load_state(stage=0, *, kind="finish", marker="manual", safe=True):
    state = make_state()
    state.source_timestamp_ms = int(time.time() * 1000)
    state.player.gap_ahead_s = 3
    state.player.gap_behind_s = 3
    state.raw.update(session_type="Race", session_time_s=100., brake=0.0, steer=0.0,
                     pit_status_code=0, result_status=2, timing_mode="race_like",
                     timing_support_level="official_preferred")
    runtime = PersonalityRuntime()
    assess_domain(state)
    state.personality = runtime.observe_snapshot(state, StrategyDecision([]))
    assert state.personality.low_load
    state.personality = replace(state.personality, stage=stage, opportunity=kind,
                                event_id=marker, opportunity_age_s=.5, low_load=safe)
    return state


def check_scheduling():
    output = ConsoleVoiceOutput(backend=FakeSpeechBackend())
    state = low_load_state()
    critical = replace(state, safety_car="FULL", personality=None, assessment=None)
    config = AppConfig()
    decision = StrategyEngine(config.thresholds, config.usage_hooks_path).evaluate(critical, [])
    output.emit_query_response(state=state, query_kind="fuel_status", render=False)
    held = output._active_handle
    final_action = decision.debug["arbiter_v2"]["output"]["final_voice_action"]
    output.emit(decision, state=critical, render=False)
    check = (output._active_envelope.job.action_code == "SAFETY_CAR"
             and output._active_envelope.job.speak_text == final_action["speak_text"]
             and not held["active"])
    output.backend.complete_all()
    output.tick()
    first = output.emit_query_response(state=state, query_kind="fuel_status", render=False)
    plain_facts, _ = render_structured_query_response(
        state=state, schema=StructuredQuerySchema(**first["structured_query"]), primary_message=None)
    second = output.emit_query_response(state=state, query_kind="fuel_status", render=False)
    silent = ConsoleVoiceOutput(backend=NullSpeechBackend())
    result = silent.emit_query_response(state=state, query_kind="fuel_status", render=False)
    return {
        "real_safety_arbitration_preempts_query": check,
        "distinct_same_action_request_enqueues": second["output_lifecycle"]["event"]["event_type"] == "enqueue",
        "calm_structured_reply_is_the_unadorned_fact": first["output_lifecycle"]["event"]["speak_text"] == plain_facts,
        "silent_never_plays_or_repeats": (result["output_lifecycle"]["event"]["event_type"] == "silent"
                                       and silent._last_completed_envelope is None and not silent.is_playing()),
    }


def check_opportunities():
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    state = low_load_state()
    quiet = StrategyDecision([])
    blocked = low_load_state(marker="unsafe", safe=False)
    output.emit(quiet, state=blocked, render=False)
    unsafe = not backend._handles
    output.reserve_query_turn("test", speech_time() + 10)
    busy = output.emit(quiet, state=low_load_state(marker="busy"), render=False)
    output.reserve_query_turn("test", None)
    expired = low_load_state(marker="expired")
    expired.personality = replace(expired.personality, opportunity_age_s=2.01)
    output.emit(quiet, state=expired, render=False)
    expiry = not backend._handles
    active = output.emit(quiet, state=state, render=False)
    output.emit(quiet, state=blocked, render=False)
    stopped = bool(backend._handles) and not backend._handles[-1]["active"]
    output.emit(quiet, state=state, render=False)
    safe = low_load_state(stage=3, marker="no-opportunity")
    safe.personality = replace(safe.personality, memory_kind="fastest_lap")
    output = ConsoleVoiceOutput(backend=FakeSpeechBackend())
    turn = replace(_make_turn("开个玩笑"), turn_id="joke-turn")
    reply = VoiceInputCoordinator(enable_llm_sidecar=False).process_completed_turn(
        state=safe, turn=turn, voice_output=output, render=False)
    reply_text = (reply.output_debug or {}).get("output_lifecycle", {}).get("event", {}).get("speak_text", "")
    return {
        "unsafe_never_plays": unsafe,
        "query_blocks_opportunity": busy["event"]["metadata"].get("reason") == "optional_speech_busy",
        "expired_never_plays": expiry,
        "safe_finish_plays_once": active["event"]["action_code"] == "PERSONALITY_FINISH" and len(backend._handles) == 1,
        "context_change_stops_active_humor": stopped,
        "voice_banter_uses_only_verified_callback": reply.reason == "personality_reply" and "最快圈" in reply_text,
    }, {"finish_line": active["event"]["speak_text"], "h3_line": reply_text}


def check_stage_lines():
    def event(stage, kind, *, safe=True):
        output = ConsoleVoiceOutput(backend=FakeSpeechBackend())
        state = low_load_state(stage=stage, kind=kind, safe=safe)
        return output.emit(StrategyDecision([]), state=state, render=False)["event"]

    overtake = [event(stage, "overtake") for stage in range(4)]
    fastest = [event(stage, "fastest_lap") for stage in range(4)]
    offtrack = [event(stage, "minor_offtrack") for stage in range(4)]
    pit = []
    for stage in range(4):
        state = low_load_state(stage=stage)
        decision = make_strategy_decision(
            state=state, code="BOX_WINDOW", priority=92, title="进站窗口", detail="当前磨损 76%，优先评估进站。")
        output = ConsoleVoiceOutput(backend=FakeSpeechBackend())
        original = decision.debug["arbiter_v2"]["output"]["final_voice_action"]["speak_text"]
        emitted = output.emit(decision, state=state, render=False)["event"]
        pit.append((original, emitted))
    with patch.dict(os.environ, {"ASURADA_HUMOR_ENABLED": "0"}):
        neutral = event(3, "minor_offtrack")
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    passes = []
    for index, clock in enumerate((100., 125., 250.)):
        state = low_load_state(2, kind="overtake", marker=f"pass:{index}")
        state.personality = replace(state.personality, clock_s=clock)
        emitted = output.emit(StrategyDecision([]), state=state, render=False)["event"]
        passes.append(emitted)
        backend.complete_all()
        output.tick()
    return {
        "four_distinct_overtake_templates": len({e["speak_text"] for e in overtake}) == 4,
        "four_distinct_offtrack_templates": len({e["speak_text"] for e in offtrack}) == 4,
        "positive_events_use_excited_delivery": all(
            e["metadata"]["personality"]["tone"] == "excited" for e in overtake + fastest),
        "repeated_positive_events_observe_cooldown_and_rotate": (
            passes[0]["event_type"] == "start" and passes[1]["event_type"] == "idle"
            and passes[2]["event_type"] == "start" and passes[0]["speak_text"] != passes[2]["speak_text"]),
        "four_pit_templates_preserve_core_action_and_facts": (
            len({e["speak_text"] for _, e in pit}) == 4
            and all(e["action_code"] == "BOX_WINDOW" and e["speak_text"].startswith(original)
                    for original, e in pit)),
        "humor_switch_retains_neutral_event": neutral["speak_text"] == offtrack[0]["speak_text"],
        "unsafe_offtrack_is_silent": event(3, "minor_offtrack", safe=False)["event_type"] == "idle",
    }


def check_minor_running_wide():
    state = low_load_state()
    runtime = PersonalityRuntime()
    decision = StrategyDecision([])
    runtime.observe_snapshot(state, decision)
    def warning(number, penalty, infringement, vehicle):
        packet = PacketEnvelope("Event", number, state.session_uid, {
            "header": {"session_time_s": 101., "overall_frame_identifier": number},
            "body": {"event_code": "PENA", "event_detail": {
                "penalty_type": penalty, "infringement_type": infringement, "vehicle_idx": vehicle}},
        })
        runtime.observe_packet(packet, state.session_epoch, replay=True)

    warning(1, 4, 27, state.player.car_index)  # Time penalty.
    warning(2, 5, 29, state.player.car_index)  # Extreme infringement.
    warning(3, 5, 27, state.player.car_index + 1)  # Other car.
    only_player_minor = len(runtime.timeline) == 0
    warning(4, 5, 27, state.player.car_index)
    warning(4, 5, 27, state.player.car_index)
    state.raw["session_time_s"] = 101.
    assess_domain(state)
    too_early = runtime.observe_snapshot(state, decision)
    state.raw["session_time_s"] = 102.
    assess_domain(state)
    recovered = runtime.observe_snapshot(state, decision)
    return {
        "minor_warning_only_uses_player_telemetry": only_player_minor and len(runtime.timeline) == 1,
        "minor_warning_waits_for_stable_context": (
            too_early.opportunity is None and recovered.opportunity == "minor_offtrack" and recovered.low_load),
    }


def check_shared_humor():
    state = low_load_state(stage=3)
    config = AppConfig()
    decision = StrategyEngine(config.thresholds, config.usage_hooks_path).evaluate(state, [])
    state.personality = replace(state.personality, memory_kind="overtake")
    assert state.personality.matches(state)
    with TemporaryDirectory(dir="/tmp") as temp:
        latest = Path(temp) / "latest.json"
        latest.write_text(json.dumps(snapshot_payload(state, decision)))
        backend = FakeSpeechBackend()
        output = ConsoleVoiceOutput(backend=backend)
        service = SpeechService(Path(temp) / "voice.sock", output=output, session_source=latest).start()
        try:
            client = SharedSpeechClient(service.path)
            blocked = replace(state, personality=replace(state.personality, low_load=False))
            latest.write_text(json.dumps(snapshot_payload(blocked, decision)))
            reply = client.emit_personality_reply(state=state, text="开个玩笑", request_id="stale-hint")
            safety = reply["output_lifecycle"]["event"]["event_type"] == "suppress" and not backend._handles
            latest.write_text(json.dumps(snapshot_payload(state, decision)))
            reply = client.emit_personality_reply(state=state, text="开个玩笑", request_id="valid-hint")
            event = reply["output_lifecycle"]["event"]
            checks = {"shared_speech_rejects_superseded_safe_hint": safety,
                      "shared_speech_plays_verified_banter": event["event_type"] == "start" and "超车" in event["speak_text"]}
            return checks
        finally:
            service.close()


def check_tyre_recovery():
    runtime = PersonalityRuntime()
    state = low_load_state()
    def update(second, pit, wear, age):
        state.source_timestamp_ms += int(second * 1000)
        state.raw.update(session_time_s=second, pit_status_code=pit,
                         overall_frame_identifier=int(second))
        state.player.tyre.wear_pct = wear
        state.player.tyre.age_laps = age
        assess_domain(state)
        return runtime.observe_snapshot(state, StrategyDecision([]))
    update(1., 0, 30, 5)
    risk = update(2., 0, 66, 5)
    runtime._add("collision", 2.5, "test:collision")
    update(3., 2, 66, 5)
    recovered = update(4., 2, 1, 0)
    return {"wheel_change_only_clears_tyre_concern": (
        risk.tone == "firm" and recovered.tyre_concern == 0 and recovered.concern > .5)}


def fixture_cooperation(race_id: str, *, epoch: int = 0) -> dict:
    from asurada.pit_feedback import driver_profile_id

    return dict(recommendation_id="recommendation-" + race_id, driver_id=driver_profile_id(),
                race_id=race_id, epoch=epoch, recommendation_snapshot_id="recommendation-snapshot",
                reply_snapshot_id="response-snapshot", outcome_snapshot_id="outcome-snapshot",
                wear_before_pct=80., wear_after_pct=1.)


def check_relationship():
    with TemporaryDirectory() as temp:
        path = Path(temp) / "relationship.sqlite3"
        runtime = PersonalityRuntime(relationship_db=path)
        live_rows = run_capture(runtime, time_live=True)
        runtime.close()
        first = update_database(path)
        runtime = PersonalityRuntime(relationship_db=path)
        run_capture(runtime, time_live=True)
        runtime.close()
        duplicate = update_database(path)
        for i in range(2, 17):
            event = dict(id=f"event-{i}", kind="overtake", time_s=43)
            race_id = f"fixture-{i}"
            row = update_database(path, "race", dict(race_id=race_id, epoch=0, positive_events=[event]))
            if i in {4, 5}:
                update_database(path, "pit_cooperation", fixture_cooperation(race_id))
            if i == 3:
                h1 = row.stage
            if i == 8:
                h2 = row.stage
        h3 = update_database(path)
        ack = update_database(path, "acknowledgement", "90000001")
        reset = update_database(path, "reset")
    return {
        "decoded_finish_persisted_without_later_physics_frame": bool(live_rows) and first.races == 1,
        "rewound_positives_not_stored": first.positive_races == 0,
        "repeat_finish_is_idempotent": duplicate == first,
        "progression_survives_restart": (h1, h2, h3.stage) == (1, 2, 3),
        "explicit_ack_is_supported": ack.acknowledgements == 1,
        "reset_returns_h0": reset.stage == reset.races == 0,
    }, {"stages_after_3_8_16_finishes": [h1, h2, h3.stage]}


def check_lapdata_finish_and_risk():
    packets = list(capture_rows())
    source = next(p for p in reversed(packets) if p.payload[6] == 2)
    final_lap = bytearray(source.payload)
    struct.pack_into("<fII", final_lap, 15, 11., 11, 17)
    result = HEADER_SIZE + CAR * F125PacketDecoder.LAP_DATA_CAR_SIZE
    final_lap[result + 32] = 20
    final_lap[result + 33] = 7
    final_lap[result + 45] = 3
    lap_packet = replace(source, received_at_ms=packets[-1].received_at_ms, payload=bytes(final_lap))
    with TemporaryDirectory() as temp:
        path = Path(temp) / "relationship.sqlite3"
        runtime = PersonalityRuntime(relationship_db=path)
        run_capture(runtime, time_live=True, packets=[*packets[:-1], lap_packet])
        runtime.close()
        recorded = update_database(path)
        runtime = PersonalityRuntime(relationship_db=path)
        run_capture(runtime, time_live=True, packets=[*packets[:-1], lap_packet, packets[-1]])
        runtime.close()
        replayed = update_database(path)

    state = low_load_state()
    excited = replace(state.personality, tone="excited", excitement=1.)
    state.personality = excited
    output = ConsoleVoiceOutput(backend=FakeSpeechBackend())
    risk = make_strategy_decision(state=state, code="TYRE_DAMAGE", priority=72,
                                  title="右前轮损伤 39%", detail="轮胎损伤")
    spoken = output.emit(risk, state=state, render=False)["event"]
    return {
        "terminal_lapdata_counts_once_even_with_classification": recorded.races == 1 and replayed == recorded,
        "recorded_excited_tone_cannot_leak_into_risk_audio": (
            spoken["event_type"] == "start" and spoken["metadata"]["personality"]["tone"] == "firm"
            and "干得漂亮" not in spoken["speak_text"]),
    }


def run():
    with patch.dict(os.environ, {"ASURADA_PERSONALITY_ENABLED": "1", "ASURADA_HUMOR_ENABLED": "1"}):
        rows = run_capture(PersonalityRuntime())
        views = [s.personality for s, _ in rows if s.personality is not None]
        restored = decode_snapshot(snapshot_payload(*rows[0]))
        repeated = [s.personality for s, _ in run_capture(PersonalityRuntime()) if s.personality is not None]
        found = {view.trigger for view in views}
        checks = {
            "bound_snapshot_roundtrips": restored.personality == views[0],
            "raw_player_events_reach_personality": {"collision", "fastest_lap", "overtake"} <= found,
            "duplicate_collision_has_single_effect": max(v.concern for v in views) == .85,
            "emotion_decay_uses_replay_clock": any(.30 < v.concern < .50 for v in views),
            "flashback_holds_pre_rewind_intermediate_frame": any(s.personality is None for s, _ in rows),
            "flashback_retracts_future_influence": views[-1].session_epoch > 0 and views[-1].concern == 0,
            "same_replay_same_trajectory": views == repeated,
        }
        checks.update(check_scheduling())
        checks.update(check_lapdata_finish_and_risk())
        checks.update(check_stage_lines())
        checks.update(check_minor_running_wide())
        checks.update(check_tyre_recovery())
        checks.update(check_shared_humor())
        opportunities, lines = check_opportunities()
        checks.update(opportunities)
        memory, stages = check_relationship()
        checks.update(memory)
    return {"passed": all(checks.values()), "checks": checks,
            "examples": {**lines, **stages},
            "trajectory": [{"time": v.clock_s, "epoch": v.session_epoch, "trigger": v.trigger,
                            "tone": v.tone, "concern": v.concern, "excitement": v.excitement} for v in views]}


def benchmark():
    targets = ("strategy_latency_ms", "pipeline_latency_ms")
    samples = {"disabled": [], "enabled": []}
    for i in range(24):
        order = ("enabled", "disabled") if i % 2 else ("disabled", "enabled")
        for mode in order:
            model = PersonalityRuntime() if mode == "enabled" else None
            rows = run_capture(model)
            if i > 1:
                samples[mode].extend(d.debug["runtime_timing"] for _, d in rows)
    return {mode: {"frames": len(rows),
                   **{key: round(statistics.quantiles([r[key] for r in rows], n=100, method="inclusive")[98], 3)
                      for key in targets}}
            for mode, rows in samples.items()}


def listen():
    backend = resolve_default_speech_backend()
    if not backend.audible:
        raise SystemExit("Select an audible ASURADA_TTS_BACKEND before using --listen.")
    with patch.dict(os.environ, {"ASURADA_PERSONALITY_ENABLED": "1", "ASURADA_HUMOR_ENABLED": "1"}):
        output = ConsoleVoiceOutput(backend=backend)
        seen = set()
        for state, _ in run_capture(PersonalityRuntime()):
            hint = state.personality
            if hint is None or hint.tone in seen:
                continue
            seen.add(hint.tone)
            print(f"[PERSONALITY] {hint.tone} at {hint.clock_s}s", flush=True)
            output.emit_query_response(state=state, query_kind="fuel_status")
            wait_for_audio(output)
        output.emit(StrategyDecision([]), state=low_load_state(marker="listen-finish"))
        wait_for_audio(output)
        if not output.shutdown():
            raise SystemExit("Playback shutdown was not confirmed.")


def wait_for_audio(output):
    until = time.monotonic() + 15
    while output.is_playing() and time.monotonic() < until:
        output.tick()
        time.sleep(.02)
    if output.is_playing():
        output.shutdown()
        raise SystemExit("Audio fixture timed out.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-capture", type=Path, help="Write the short F1 replay sample to a new file.")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--listen", action="store_true", help="Play the deterministic replay scenes with the configured TTS.")
    args = parser.parse_args()
    if args.write_capture is not None:
        if args.write_capture.exists():
            parser.error("capture already exists")
        recorder = RawPacketCaptureRecorder(args.write_capture)
        recorder.reset()
        for row in capture_rows():
            recorder.append(row)
    if args.benchmark:
        print(json.dumps(benchmark(), indent=2))
    elif args.listen:
        listen()
    else:
        emit_result(run())
