from __future__ import annotations

from ..wheel_telemetry import tyre_alert
from ..response_composer import (
    Any,
    SessionState,
    StrategyMessage,
    _damage_recommendation,
    _damage_snapshot,
    _engine_component_clause,
    render_damage_pit_advice,
    render_engine_damage_detail,
    render_floor_damage_detail,
    render_front_wing_damage_detail,
    render_summary_answer,
)


def _handle_damage_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    damage = _damage_snapshot(state)
    recommendation = _damage_recommendation(damage)
    tyre = tyre_alert(state.raw.get("tyres_damage_pct"), state.raw.get("tyres_wear_pct"))
    return (
        render_summary_answer(
            f"当前主要车损是前翼 {damage['front_wing']}%，底板 {damage['floor']}%，扩散器 {damage['diffuser']}%，发动机 {damage['engine']}%。",
            tyre[1] if tyre else None,
            _engine_component_clause(damage),
            recommendation,
        ),
        "QUERY_DAMAGE_STATUS",
    )



def _handle_damage_pit_advice(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    damage = _damage_snapshot(state)
    recommendation = _damage_recommendation(damage)
    detail = render_damage_pit_advice(
        front_wing_pct=int(damage["front_wing"]),
        floor_damage_pct=int(damage["floor"]),
        diffuser_damage_pct=int(damage["diffuser"]),
        engine_damage_pct=int(damage["engine"]),
        engine_blown=bool(damage["engine_blown"]),
        engine_seized=bool(damage["engine_seized"]),
    )
    return (
        render_summary_answer(detail, _engine_component_clause(damage), recommendation),
        "QUERY_DAMAGE_PIT_ADVICE",
    )



def _handle_front_wing_damage_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    context = (schema_metadata or {}).get("semantic_metadata", {})
    side = context.get("radio_wing_side")
    if side in ("front_left", "front_right"):
        from ..wing_damage import SIDES, wing_values
        value = wing_values(state).get(side)
        detail = f"{SIDES[side]}损伤 {value:g}%。" if value is not None else f"{SIDES[side]}读数暂不可用。"
        return detail, "QUERY_FRONT_WING_DAMAGE_STATUS"
    damage = _damage_snapshot(state)
    detail = render_front_wing_damage_detail(int(damage["front_wing"]))
    return (render_summary_answer(detail), "QUERY_FRONT_WING_DAMAGE_STATUS")



def _handle_floor_damage_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    damage = _damage_snapshot(state)
    detail = render_floor_damage_detail(
        int(damage["floor"]),
        int(damage["diffuser"]),
        int(damage["sidepod"]),
    )
    return (render_summary_answer(detail), "QUERY_FLOOR_DAMAGE_STATUS")



def _handle_engine_damage_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    damage = _damage_snapshot(state)
    detail = render_engine_damage_detail(
        engine_damage_pct=int(damage["engine"]),
        engine_blown=bool(damage["engine_blown"]),
        engine_seized=bool(damage["engine_seized"]),
    )
    return (render_summary_answer(detail, _engine_component_clause(damage)), "QUERY_ENGINE_DAMAGE_STATUS")

