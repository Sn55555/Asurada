from __future__ import annotations

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
        position=int(payload["position"]),
        lap=int(payload["lap"]),
        gap_ahead_s=_optional_float(payload.get("gap_ahead_s")),
        gap_behind_s=_optional_float(payload.get("gap_behind_s")),
        fuel_laps_remaining=float(payload["fuel_laps_remaining"]),
        ers_pct=float(payload["ers_pct"]),
        drs_available=bool(payload["drs_available"]),
        tyre=tyre,
        speed_kph=float(payload["speed_kph"]),
        status_tags=list(payload.get("status_tags", [])),
    )


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def decode_snapshot(payload: dict) -> SessionState:
    """Convert a normalized snapshot dict into the internal state model."""
    return SessionState(
        session_uid=payload["session_uid"],
        track=payload["track"],
        lap_number=int(payload["lap_number"]),
        total_laps=int(payload["total_laps"]),
        weather=payload["weather"],
        safety_car=payload["safety_car"],
        player=_decode_driver(payload["player"]),
        rivals=[_decode_driver(item) for item in payload.get("rivals", [])],
        source_timestamp_ms=int(payload["source_timestamp_ms"]),
        raw=dict(payload.get("raw", {})),
    )
