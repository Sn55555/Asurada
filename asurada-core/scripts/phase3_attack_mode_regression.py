from __future__ import annotations

from regression_support import emit_result

import json
import tempfile
from pathlib import Path

from asurada.attack_mode import AttackModeController
from asurada.audio_io import AudioFormat
from asurada.models import (
    ContextProfile,
    DriverState,
    SessionState,
    StrategyDecision,
    StrategyMessage,
    TyreState,
)
from asurada.output import ConsoleVoiceOutput
from asurada.semantic_normalizer import SemanticNormalizer
from asurada.tts_backends import NullSpeechBackend
from asurada.voice_turn import VoiceTurn


def _state(*, gap_ahead: float, drs_available: bool, tags: list[str] | None = None) -> SessionState:
    return SessionState(
        session_uid="session-attack-mode",
        track="Shanghai",
        lap_number=12,
        total_laps=56,
        weather="Clear",
        safety_car="NONE",
        source_timestamp_ms=0,
        player=DriverState(
            car_index=0,
            name="Player",
            position=2,
            lap=12,
            gap_ahead_s=gap_ahead,
            gap_behind_s=1.3,
            fuel_laps_remaining=25.0,
            ers_pct=60.0,
            drs_available=drs_available,
            tyre=TyreState(compound="M", wear_pct=20.0, age_laps=5),
            speed_kph=295.0,
            status_tags=tags or [],
            lap_distance_m=3400.0,
        ),
        rivals=[],
        raw={"lap_distance_m": 3400.0},
    )


def _decision(*, code: str, detail: str, setup_method: str, commit_method: str) -> StrategyDecision:
    return StrategyDecision(
        messages=[StrategyMessage(code=code, priority=70, title=code, detail=detail)],
        debug={
            "context": {
                "track_segment": "Back Straight Primary Deploy",
                "track_zone": "deployment_straight",
                "track_usage": "primary_overtake_deploy",
                "attack_setup_method": setup_method,
                "attack_commit_method": commit_method,
            },
            "interaction_input_event": {
                "interaction_session_id": "runtime:test",
                "turn_id": "turn:test",
                "request_id": "req:test",
                "snapshot_binding_id": "snap:test",
            },
            "task_handle": {"request_id": "req:test"},
            "arbiter_v2": {"output": {"final_voice_action": {"priority": 70, "speak_text": detail}}},
        },
    )


def run_phase3_attack_mode_regression() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "attack_mode_state.json"
        import os

        os.environ["ASURADA_ATTACK_MODE_STATE_PATH"] = str(state_path)

        normalizer = SemanticNormalizer()
        turn = VoiceTurn(
            turn_id="voice-turn:attack-mode",
            started_at_ms=0,
            ended_at_ms=1000,
            audio_format=AudioFormat(),
            pcm_s16le=b"",
            chunk_count=0,
            source="regression",
            completion_reason="synthetic",
            metadata={},
        )
        semantic = normalizer.normalize(
            state=_state(gap_ahead=0.7, drs_available=True),
            voice_turn=turn,
            fast_intent=type(
                "FastIntent",
                (),
                {
                    "status": "fallback",
                    "query_kind": None,
                    "transcript_text": "开启进攻模式",
                    "normalized_text": "开启进攻模式",
                    "confidence": 0.8,
                    "lane": "unknown",
                    "matched_phrase": None,
                },
            )(),
            conversation_context=type(
                "Ctx",
                (),
                {
                    "snapshot": lambda self=None: {},
                    "last_non_control_query_kind": lambda self=None: None,
                    "last_strategy_code": lambda self=None: None,
                },
            )(),
            primary_message=None,
        )

        controller = AttackModeController()
        enable_result = controller.enable(state=_state(gap_ahead=0.7, drs_available=True))
        attack_reminder = controller.maybe_build_reminder(
            state=_state(gap_ahead=0.7, drs_available=True),
            decision=_decision(
                code="ATTACK_WINDOW",
                detail="前车差距 0.7s，DRS 可用。",
                setup_method="drs_tow",
                commit_method="none",
            ),
        )

        controller.enable(state=_state(gap_ahead=0.7, drs_available=True))
        hold_reminder = controller.maybe_build_reminder(
            state=_state(gap_ahead=0.7, drs_available=False),
            decision=_decision(
                code="NONE",
                detail="当前不建议进攻。",
                setup_method="drs_tow",
                commit_method="none",
            ),
        )

        voice_output = ConsoleVoiceOutput(backend=NullSpeechBackend())
        controller_for_output = voice_output._attack_mode
        controller_for_output.enable(state=_state(gap_ahead=0.7, drs_available=True))
        output_decision = _decision(
            code="ATTACK_WINDOW",
            detail="前车差距 0.7s，DRS 可用。",
            setup_method="drs_tow",
            commit_method="none",
        )
        output_lifecycle = voice_output.emit(
            output_decision,
            state=_state(gap_ahead=0.7, drs_available=True),
            render=False,
        )
        event = (output_lifecycle.get("event") or {})
        runtime_voice_assists = (output_decision.debug.get("runtime_voice_assists") or {})
        hold_output_decision = _decision(
            code="NONE",
            detail="当前不建议进攻。",
            setup_method="drs_tow",
            commit_method="none",
        )
        hold_output_lifecycle = voice_output.emit(
            hold_output_decision,
            state=_state(gap_ahead=0.7, drs_available=False),
            render=False,
        )
        hold_event = (hold_output_lifecycle.get("event") or {})
        return {
            "semantic_enable_attack_mode": semantic.query_kind == "enable_attack_mode",
            "control_enable_succeeds": enable_result.enabled and enable_result.reason == "enabled",
            "attack_reminder_built": attack_reminder is not None and attack_reminder.reminder_type == "attack",
            "hold_reminder_built": hold_reminder is not None and hold_reminder.reminder_type == "hold",
            "output_uses_attack_mode": event.get("action_code") == "ATTACK_MODE_REMINDER",
            "output_source_kind_attack_mode": event.get("metadata", {}).get("source_kind") == "attack_mode",
            "attack_mode_runtime_debug_present": "attack_mode" in runtime_voice_assists,
            "output_uses_attack_mode_hold": hold_event.get("action_code") == "ATTACK_MODE_HOLD",
        }


if __name__ == "__main__":
    emit_result(run_phase3_attack_mode_regression())
