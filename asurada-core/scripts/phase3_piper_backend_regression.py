from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from asurada.interaction import SpeechJob
from asurada.models import DriverState, SessionState, StrategyDecision, StrategyMessage, TyreState
from asurada.output import ConsoleVoiceOutput
from asurada.tts_backends import PiperBackend, PiperBackendConfig, SpeechBackend


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_fake_backend(*, sleep_seconds: float) -> PiperBackend:
    temp_dir = Path(tempfile.mkdtemp(prefix="asurada-piper-regression-"))
    model_path = temp_dir / "voice.onnx"
    model_path.write_text("fake-model", encoding="utf-8")

    piper_script = temp_dir / "fake_piper.py"
    _write_executable(
        piper_script,
        """#!/usr/bin/env python3
import pathlib
import sys

args = sys.argv[1:]
output_file = None
for idx, value in enumerate(args):
    if value == "--output_file":
        output_file = pathlib.Path(args[idx + 1])
        break
if output_file is None:
    sys.exit(2)
text = sys.stdin.read()
output_file.write_text(f"fake wav for: {text}", encoding="utf-8")
""",
    )

    player_script = temp_dir / "fake_player.py"
    _write_executable(
        player_script,
        f"""#!/usr/bin/env python3
import pathlib
import sys
import time

time.sleep({sleep_seconds})
audio_path = pathlib.Path(sys.argv[-1])
sys.exit(0 if audio_path.exists() else 3)
""",
    )

    return PiperBackend(
        PiperBackendConfig(
            piper_binary=str(piper_script),
            model_path=str(model_path),
            player_binary=str(player_script),
            python_binary=sys.executable,
        )
    )


def _make_state() -> SessionState:
    tyre = TyreState(compound="Medium", wear_pct=20.0, age_laps=5)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=4,
        lap=6,
        gap_ahead_s=0.812,
        gap_behind_s=1.402,
        fuel_laps_remaining=13.1,
        ers_pct=58.0,
        drs_available=True,
        tyre=tyre,
        speed_kph=274.0,
    )
    return SessionState(
        session_uid="piper-regression",
        track="Suzuka",
        lap_number=6,
        total_laps=20,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[],
        source_timestamp_ms=1_777_200_000_000,
        raw={
            "frame_identifier": 221,
            "overall_frame_identifier": 1221,
            "session_time_s": 301.244,
            "source_timestamp_ms": 1_777_200_000_000,
        },
    )


def _make_decision(state: SessionState) -> StrategyDecision:
    message = StrategyMessage(
        code="LOW_FUEL",
        priority=88,
        title="低油量",
        detail="需要开始节油。",
    )
    return StrategyDecision(
        messages=[message],
        debug={
            "interaction_input_event": {
                "interaction_session_id": "runtime:piper-regression",
                "turn_id": "turn:piper",
                "request_id": "req:piper",
                "snapshot_binding_id": "snap:piper",
                "priority": 88,
                "cancelable": True,
            },
            "task_handle": {
                "task_id": "task:req:piper",
                "request_id": "req:piper",
                "turn_id": "turn:piper",
                "handler": "strategy_output_handler",
                "task_type": "push_broadcast",
            },
            "voice_pipeline_log": {},
            "arbiter_v2": {
                "output": {
                    "final_voice_action": {
                        "priority": 88,
                        "speak_text": "燃油紧张，需要开始节油。",
                    }
                }
            },
        },
    )


def run_phase3_piper_backend_regression() -> dict[str, Any]:
    job = SpeechJob(
        output_event_id="out:piper-test",
        interaction_session_id="runtime:piper-regression",
        turn_id="turn:piper-test",
        request_id="req:piper-test",
        snapshot_binding_id="snap:piper-test",
        source_kind="query_response",
        action_code="QUERY_FUEL_STATUS",
        priority=95,
        speak_text="当前燃油余量充足。",
        cancelable=True,
    )

    short_backend = _make_fake_backend(sleep_seconds=0.2)
    short_handle = short_backend.start(job)
    short_active_initial = short_backend.is_active(short_handle)
    short_completed = _wait_until_inactive(short_backend, short_handle, timeout_s=4.0)

    long_backend = _make_fake_backend(sleep_seconds=2.0)
    long_handle = long_backend.start(job)
    long_active_initial = long_backend.is_active(long_handle)
    long_backend.stop(long_handle)
    long_stopped = _wait_until_inactive(long_backend, long_handle, timeout_s=1.0)

    state = _make_state()
    output = ConsoleVoiceOutput(backend=_make_fake_backend(sleep_seconds=0.2))
    lifecycle = output.emit(_make_decision(state), render=False)
    _wait_until_inactive(output.backend, output._active_handle, timeout_s=4.0)  # type: ignore[attr-defined]
    lifecycle_complete = output.emit(
        StrategyDecision(
            messages=[],
            debug={
                "interaction_input_event": lifecycle["event"],
                "task_handle": {"task_id": "task:idle", "request_id": "req:idle", "turn_id": "turn:idle"},
                "voice_pipeline_log": {},
                "arbiter_v2": {"output": {}},
            },
        ),
        render=False,
    )

    checks = {
        "backend_starts_active": short_active_initial,
        "backend_completes": short_completed,
        "backend_stop_terminates": long_active_initial and long_stopped,
        "output_uses_piper_backend": lifecycle["event"]["event_type"] == "start"
        and lifecycle["event"]["action_code"] == "LOW_FUEL",
        "output_complete_event": lifecycle_complete["event"]["event_type"] == "complete",
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "start_event": lifecycle["event"],
            "complete_event": lifecycle_complete["event"],
        },
    }


def _wait_until_inactive(backend: SpeechBackend, handle: Any, *, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not backend.is_active(handle):
            return True
        time.sleep(0.05)
    return False


if __name__ == "__main__":
    print(json.dumps(run_phase3_piper_backend_regression(), ensure_ascii=False, indent=2))
