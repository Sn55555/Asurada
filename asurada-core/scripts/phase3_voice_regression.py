from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from asurada.interaction import (
    build_confirmation_policy,
    build_structured_query_schema,
    build_system_strategy_input_event,
    build_task_handle,
    route_structured_query,
)
from asurada.models import DriverState, SessionState, StrategyDecision, StrategyMessage, TyreState
from asurada.output import ConsoleVoiceOutput, SpeechBackend


class FakeSpeechBackend(SpeechBackend):
    def __init__(self) -> None:
        self._handles: list[dict[str, Any]] = []

    def start(self, job) -> dict[str, Any]:
        handle = {"job": job.to_dict(), "active": True}
        self._handles.append(handle)
        return handle

    def is_active(self, handle: dict[str, Any] | None) -> bool:
        return bool(handle and handle.get("active"))

    def stop(self, handle: dict[str, Any] | None) -> None:
        if handle is not None:
            handle["active"] = False

    def complete_all(self) -> None:
        for handle in self._handles:
            handle["active"] = False


def make_state() -> SessionState:
    tyre = TyreState(compound="Medium", wear_pct=18.0, age_laps=5)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=3,
        lap=8,
        gap_ahead_s=0.842,
        gap_behind_s=0.611,
        fuel_laps_remaining=12.4,
        ers_pct=67.0,
        drs_available=True,
        tyre=tyre,
        speed_kph=247.0,
        status_tags=[],
    )
    rival = DriverState(
        car_index=1,
        name="Norris",
        position=4,
        lap=8,
        gap_ahead_s=0.611,
        gap_behind_s=0.924,
        fuel_laps_remaining=11.8,
        ers_pct=54.0,
        drs_available=True,
        tyre=tyre,
        speed_kph=245.0,
        status_tags=[],
    )
    return SessionState(
        session_uid="regression-session",
        track="Suzuka",
        lap_number=8,
        total_laps=20,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rival],
        source_timestamp_ms=1_777_000_000_000,
        raw={
            "frame_identifier": 320,
            "overall_frame_identifier": 640,
            "session_time_s": 412.35,
            "source_timestamp_ms": 1_777_000_000_000,
        },
    )


def make_strategy_decision(
    *,
    state: SessionState,
    code: str,
    priority: int,
    title: str,
    detail: str,
) -> StrategyDecision:
    message = StrategyMessage(code=code, priority=priority, title=title, detail=detail)
    input_event = build_system_strategy_input_event(
        state=state,
        primary_message=message,
        session_mode="race_strategy",
    )
    schema = build_structured_query_schema(input_event)
    route = route_structured_query(schema)
    confirmation_policy = build_confirmation_policy(
        input_event=input_event,
        schema=schema,
        route=route,
    )
    task_handle = build_task_handle(
        input_event=input_event,
        route=route,
        confirmation_policy=confirmation_policy,
    )
    return StrategyDecision(
        messages=[message],
        debug={
            "interaction_input_event": input_event.to_dict(),
            "task_handle": task_handle.to_dict(),
            "voice_pipeline_log": {},
            "arbiter_v2": {
                "output": {
                    "final_voice_action": {
                        "priority": priority,
                        "speak_text": f"{title}。{detail}",
                    }
                }
            },
        },
    )


def make_idle_decision(state: SessionState) -> StrategyDecision:
    input_event = build_system_strategy_input_event(
        state=state,
        primary_message=None,
        session_mode="race_strategy",
    )
    schema = build_structured_query_schema(input_event)
    route = route_structured_query(schema)
    confirmation_policy = build_confirmation_policy(
        input_event=input_event,
        schema=schema,
        route=route,
    )
    task_handle = build_task_handle(
        input_event=input_event,
        route=route,
        confirmation_policy=confirmation_policy,
    )
    return StrategyDecision(
        messages=[],
        debug={
            "interaction_input_event": input_event.to_dict(),
            "task_handle": task_handle.to_dict(),
            "voice_pipeline_log": {},
            "arbiter_v2": {"output": {}},
        },
    )


def main() -> int:
    report = run_regression()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def run_regression() -> dict[str, Any]:
    state = make_state()
    checks = {
        "start_complete": check_start_complete(state),
        "enqueue_pending": check_enqueue_pending(state),
        "replace_pending": check_replace_pending(state),
        "duplicate_suppress": check_duplicate_suppress(state),
        "query_response_same_path": check_query_response_same_path(state),
    }
    return {"passed": all(item["passed"] for item in checks.values()), "checks": checks}


def check_start_complete(state: SessionState) -> dict[str, Any]:
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    start = output.emit(
        make_strategy_decision(
            state=state,
            code="DEFEND_WINDOW",
            priority=90,
            title="防守窗口",
            detail="后车已进入贴身防守区间。",
        ),
        render=False,
    )
    backend.complete_all()
    complete = output.emit(make_idle_decision(state), render=False)
    return {
        "passed": start["event"]["event_type"] == "start" and complete["event"]["event_type"] == "complete",
        "start_event": start["event"]["event_type"],
        "complete_event": complete["event"]["event_type"],
    }


def check_enqueue_pending(state: SessionState) -> dict[str, Any]:
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    output.emit(
        make_strategy_decision(
            state=state,
            code="LOW_FUEL",
            priority=88,
            title="低油量",
            detail="需要开始节油。",
        ),
        render=False,
    )
    queued = output.emit(
        make_strategy_decision(
            state=state,
            code="ATTACK_WINDOW",
            priority=70,
            title="进攻窗口",
            detail="前车已经进入攻击区。",
        ),
        render=False,
    )
    return {
        "passed": queued["event"]["event_type"] == "enqueue" and queued["pending_output"]["action_code"] == "ATTACK_WINDOW",
        "event_type": queued["event"]["event_type"],
        "pending_output": queued["pending_output"],
    }


def check_replace_pending(state: SessionState) -> dict[str, Any]:
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    output.emit(
        make_strategy_decision(
            state=state,
            code="LOW_FUEL",
            priority=88,
            title="低油量",
            detail="需要开始节油。",
        ),
        render=False,
    )
    output.emit(
        make_strategy_decision(
            state=state,
            code="ATTACK_WINDOW",
            priority=70,
            title="进攻窗口",
            detail="前车已经进入攻击区。",
        ),
        render=False,
    )
    replaced = output.emit_query_response(
        state=state,
        query_kind="current_strategy",
        primary_message=StrategyMessage(
            code="LOW_FUEL",
            priority=88,
            title="低油量",
            detail="需要开始节油。",
        ),
        render=False,
    )
    return {
        "passed": replaced["output_lifecycle"]["event"]["event_type"] == "replace_pending"
        and replaced["output_lifecycle"]["cancelled_output"] is not None
        and replaced["output_lifecycle"]["pending_output"]["source_kind"] == "query_response",
        "event_type": replaced["output_lifecycle"]["event"]["event_type"],
        "cancelled_output": replaced["output_lifecycle"]["cancelled_output"],
    }


def check_duplicate_suppress(state: SessionState) -> dict[str, Any]:
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    output.emit(
        make_strategy_decision(
            state=state,
            code="LOW_FUEL",
            priority=88,
            title="低油量",
            detail="需要开始节油。",
        ),
        render=False,
    )
    duplicate = output.emit(
        make_strategy_decision(
            state=state,
            code="LOW_FUEL",
            priority=88,
            title="低油量",
            detail="需要开始节油。",
        ),
        render=False,
    )
    return {
        "passed": duplicate["event"]["event_type"] == "suppress",
        "event_type": duplicate["event"]["event_type"],
        "reason": duplicate["event"]["metadata"].get("reason"),
    }


def check_query_response_same_path(state: SessionState) -> dict[str, Any]:
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    query = output.emit_query_response(
        state=state,
        query_kind="fuel_status",
        render=False,
    )
    return {
        "passed": query["output_lifecycle"]["event"]["event_type"] == "start"
        and query["query_route"]["response_channel"] == "voice"
        and query["voice_pipeline_log"]["tts"]["event_type"] == "start",
        "query_event": query["output_lifecycle"]["event"]["event_type"],
        "query_route": query["query_route"],
        "tts_event": query["voice_pipeline_log"]["tts"]["event_type"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
