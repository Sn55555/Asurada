from __future__ import annotations

from .race_control import normalize_race_control

from .models import DriverState, SessionState, TyreState


def _decode_driver(payload: dict) -> DriverState:
    # 备注:
    # 这里假设上游 snapshot 已完成字段归一化；本层只负责把 dict
    # 转成 dataclass，不再做策略语义判断。
    tyre = TyreState(
        compound=payload["tyre"]["compound"],
        wear_pct=float(payload["tyre"]["wear_pct"]),
        age_laps=int(payload["tyre"]["age_laps"]),
        surface_temperature_c=[int(item) for item in payload["tyre"].get("surface_temperature_c", [])],
        inner_temperature_c=[int(item) for item in payload["tyre"].get("inner_temperature_c", [])],
    )
    return DriverState(
        car_index=int(payload["car_index"]),
        name=payload["name"],
        team_id=_optional_int(payload.get("team_id")),
        race_number=_optional_int(payload.get("race_number")),
        position=int(payload["position"]),
        lap=int(payload["lap"]),
        gap_ahead_s=_optional_float(payload.get("gap_ahead_s")),
        gap_behind_s=_optional_float(payload.get("gap_behind_s")),
        gap_source=_optional_str(payload.get("gap_source")),
        gap_confidence=_optional_str(payload.get("gap_confidence")),
        gap_source_ahead=_optional_str(payload.get("gap_source_ahead")),
        gap_source_behind=_optional_str(payload.get("gap_source_behind")),
        gap_confidence_ahead=_optional_str(payload.get("gap_confidence_ahead")),
        gap_confidence_behind=_optional_str(payload.get("gap_confidence_behind")),
        estimated_gap_source=_optional_str(payload.get("estimated_gap_source")),
        estimated_gap_confidence=_optional_str(payload.get("estimated_gap_confidence")),
        fuel_laps_remaining=float(payload["fuel_laps_remaining"]),
        ers_pct=float(payload["ers_pct"]),
        drs_available=bool(payload["drs_available"]),
        pit_status=_optional_str(payload.get("pit_status")),
        tyre=tyre,
        tyre_damage_pct=_optional_float(payload.get("tyre_damage_pct")),
        engine_damage_pct=_optional_int(payload.get("engine_damage_pct")),
        aero_damage_pct=_optional_int(payload.get("aero_damage_pct")),
        speed_kph=float(payload["speed_kph"]),
        lap_distance_m=_optional_float(payload.get("lap_distance_m")),
        world_position_x=_optional_float(payload.get("world_position_x")),
        world_position_y=_optional_float(payload.get("world_position_y")),
        world_position_z=_optional_float(payload.get("world_position_z")),
        status_tags=list(payload.get("status_tags", [])),
    )


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def decode_snapshot(payload: dict) -> SessionState:
    """Convert a normalized snapshot dict into the internal state model."""
    if payload.get("contract_version", "telemetry-v1") != "telemetry-v1":
        raise ValueError("unsupported_telemetry_contract")
    epoch=payload.get("session_epoch",0)
    if isinstance(epoch,bool) or not isinstance(epoch,int) or epoch<0:
        raise ValueError("invalid_session_epoch")
    state = SessionState(
        session_uid=payload["session_uid"],
        track=payload["track"],
        lap_number=int(payload["lap_number"]),
        total_laps=int(payload["total_laps"]),
        weather=payload["weather"],
        safety_car=normalize_race_control(payload.get("safety_car")),
        player=_decode_driver(payload["player"]),
        rivals=[_decode_driver(item) for item in payload.get("rivals", [])],
        source_timestamp_ms=int(payload["source_timestamp_ms"]),
        raw=dict(payload.get("raw", {})),
        session_epoch=epoch,
        session_epoch_explicit="session_epoch" in payload,
    )
    from .snapshot_contract import restore_decision
    restore_decision(state, payload)
    return state
