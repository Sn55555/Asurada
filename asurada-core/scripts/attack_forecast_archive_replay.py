"""Replay a single archived race through the strategy and voice scheduler, in file order."""

import argparse
import hashlib
import json
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from asurada.attack_opportunity import _block, forecast_primary
from asurada.attack_outcome import relative_position
from asurada.config import StrategyThresholds
from asurada.context_window import CONTEXT_WINDOW_SECONDS
from asurada.decode import decode_snapshot
from asurada.model_admission import MODEL_NAMES, ModelAdmissionPolicy
from asurada.output import ConsoleVoiceOutput
from asurada.output_contracts import _SpeechEnvelope
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine
from asurada.tts_backends import SpeechBackend


class RadioClock(SpeechBackend):
    def __init__(self, durations):
        self.durations = durations
        self.now = 0.0
        self.index = 0
        self.starts = []
        self.unmeasured = set()

    def start(self, job):
        meta = job.metadata.get("attack_opportunity") or {}
        if job.speak_text not in self.durations:
            self.unmeasured.add(job.speak_text)
        duration = self.durations[job.speak_text]
        record = dict(
            i=self.index,
            wall=self.now,
            code=job.action_code,
            text=job.speak_text,
            duration=duration,
            forecast=meta.get("forecast"),
            defence=job.metadata.get("defence_window"),
        )
        self.starts.append(record)
        return record

    def is_active(self, job):
        return "cut" not in job and self.now < job["wall"] + job["duration"]

    def stop(self, job):
        if self.is_active(job):
            job["cut"] = self.index


def replay(logs, uid, durations, output):
    radio = RadioClock(durations)
    files = {}
    clock = SimpleNamespace(monotonic=lambda: radio.now, time=lambda: radio.now, sleep=lambda _: None)

    def envelope(**kwargs):
        return _SpeechEnvelope(**kwargs, created_monotonic=radio.now)

    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "ASURADA_PERSONALITY_ENABLED": "1",
                    "ASURADA_PERSONALITY_LLM_MODE": "disabled",
                    "ASURADA_TRAINING_MEMORY_DB": tmp + "/training.db",
                    "ASURADA_ATTACK_MODE_STATE_PATH": tmp + "/mode.json",
                    "ASURADA_RELATIONSHIP_DB": tmp + "/growth.db",
                    "ASURADA_PIT_EVIDENCE_DB": tmp + "/pit.db",
                },
            )
        )
        for module in ("output", "output_envelopes", "output_events"):
            stack.enter_context(patch("asurada." + module + ".time", clock))
        for module in ("output", "output_envelopes"):
            stack.enter_context(patch("asurada." + module + "._SpeechEnvelope", envelope))
        store = UnifiedStateStore()
        engine = StrategyEngine(
            StrategyThresholds(),
            model_policy=ModelAdmissionPolicy(modes={model: "disabled" for model in MODEL_NAMES}),
        )
        voice = ConsoleVoiceOutput(backend=radio)
        assembler = CaptureSnapshotAssembler()
        out = stack.enter_context(output.with_suffix(".jsonl").open("w"))
        member = ('"session_uid": "' + uid + '"').encode()
        for file in sorted(logs.glob("session_log.*.jsonl")) + [logs / "session_log.jsonl"]:
            with file.open("rb") as source:
                for line, data in enumerate(source, 1):
                    if member not in data[:150]:
                        continue
                    original = json.loads(data)
                    s = decode_snapshot(original)
                    assert str(s.session_uid) == uid
                    digest = files.setdefault(file.name, hashlib.sha256())
                    digest.update(data)
                    raw = s.raw
                    radio.now = s.source_timestamp_ms / 1000
                    s.player.status_tags = assembler._build_status_tags(
                        speed_kph=s.player.speed_kph,
                        throttle=raw.get("throttle"),
                        brake=raw.get("brake"),
                        steer=raw.get("steer"),
                        g_force_lateral=raw.get("g_force_lateral", 0),
                        g_force_longitudinal=raw.get("g_force_longitudinal", 0),
                        wheel_slip_ratio=raw.get("wheel_slip_ratio") or [],
                    )
                    s.assessment = s.decision_record = None
                    if not store.update(s):
                        raise ValueError((file, line, store.last_transition))
                    decision = engine.evaluate(s, store.recent_seconds(CONTEXT_WINDOW_SECONDS))
                    s.decision_record = decision.record
                    lifecycle = voice.emit(decision, state=s, render=False)
                    if radio.unmeasured:
                        raise ValueError(f"Missing PCM timing for {radio.unmeasured}")
                    code = decision.messages[0].code if decision.messages else "NONE"
                    forecast = decision.debug.get("attack_forecast")
                    row = dict(
                        i=radio.index,
                        src=[file.name, line],
                        t=raw["session_time_s"],
                        wall=radio.now,
                        epoch=s.session_epoch,
                        lap=s.player.lap,
                        pos=s.player.position,
                        dist=s.player.lap_distance_m,
                        brake=raw.get("brake"),
                        gap=s.player.gap_ahead_s,
                        rear_gap=s.player.gap_behind_s,
                        rear_confidence=s.player.gap_confidence_behind,
                        threats=decision.debug.get("defence_threats", []),
                        defence=decision.debug.get("defence_forecast"),
                        defend_state=s.assessment.labels.defend_state,
                        effective_primary=forecast_primary(s, code, voice._wing_completed),
                        race_state=s.assessment.labels.race_state,
                        dynamics=s.assessment.labels.dynamics_state,
                        pit=raw.get("pit_status_code"),
                        flag=raw.get("marshal_zone_flag"),
                        paused=raw.get("session_paused"),
                        result=raw.get("result_status"),
                        safety_car=s.safety_car,
                        track=s.track,
                        player=s.player.car_index,
                        forecast=forecast,
                        code=code,
                        lifecycle=[lifecycle["event"]["event_type"], lifecycle["event"]["action_code"]],
                        spoken_wing=dict(voice._wing_completed),
                        wing=raw.get("wing_damage_pct"),
                        block=_block(s, forecast_primary(s, code, voice._wing_completed)) if forecast else None,
                        rivals=[
                            [
                                v.car_index,
                                v.name,
                                v.position,
                                v.pit_status,
                                relative_position(s.player, v, raw.get("world_forward_dir") or {}),
                            ]
                            for v in s.rivals
                        ],
                        event=raw.get("event_detail") if raw.get("event_code") == "OVTK" else None,
                        event_ms=(raw.get("cache_quality", {}).get("Event") or {}).get("observed_at_ms"),
                    )
                    print(json.dumps(row, ensure_ascii=False), file=out)
                    radio.index += 1
    output.with_suffix(".json").write_text(
        json.dumps(
            dict(
                frames=radio.index,
                starts=radio.starts,
                archive_sha256={k: v.hexdigest() for k, v in files.items()},
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path)
    parser.add_argument("uid")
    parser.add_argument("durations", type=Path)
    parser.add_argument("output", type=Path, help="Prefix for the frame and playback evidence files")
    args = parser.parse_args()
    replay(args.logs, args.uid, json.loads(args.durations.read_text()), args.output)
