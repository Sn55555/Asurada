from __future__ import annotations

from .assessment import assess_fuel, assess_domain

from typing import Any

from .attack_taxonomy import (
    attack_method_label,
    infer_attack_commit_method,
    infer_attack_setup_method,
    infer_corner_overtake_class,
)
from .models import SessionState, StrategyMessage
from .persona_registry import render_open_fallback_detail
from .persona_style import (
    render_damage_pit_advice,
    render_damage_recommendation,
    render_engine_damage_detail,
    render_floor_damage_detail,
    render_front_wing_damage_detail,
    render_conclusion_with_reason,
    render_not_supported_answer,
    render_overall_main_risk,
    render_overall_next_focus,
    render_overall_primary_posture,
    render_summary_answer,
    render_tyre_wear_outlook,
    render_unavailable_answer,
    render_verdict_with_numbers,
)


def _format_gap(gap_s: float | None) -> str:
    return "未知" if gap_s is None else f"{gap_s:.3f} 秒"


def _closest_rival(state: SessionState, target_position: int) -> Any | None:
    if target_position <= 0:
        return None
    for rival in state.rivals:
        if rival.position == target_position:
            return rival
    return None


def _front_rival(state: SessionState) -> Any | None:
    return _closest_rival(state, state.player.position - 1)


def _rear_rival(state: SessionState) -> Any | None:
    return _closest_rival(state, state.player.position + 1)


def _gap_quality_hint(rival: Any | None, direction: str) -> str | None:
    if rival is None:
        return None
    confidence = (
        getattr(rival, "gap_confidence_ahead", None)
        if direction == "ahead"
        else getattr(rival, "gap_confidence_behind", None)
    )
    source = (
        getattr(rival, "gap_source_ahead", None)
        if direction == "ahead"
        else getattr(rival, "gap_source_behind", None)
    )
    if confidence == "high":
        return None
    if confidence == "medium":
        return "当前时差属于中可信度估算。"
    if source == "unavailable":
        return "当前相邻车辆时差来源不完整。"
    if source:
        return f"当前时差主要来自 {source}。"
    return None


def _rival_pressure_hint(rival: Any | None) -> str | None:
    if rival is None:
        return None
    pit_status = getattr(rival, "pit_status", None)
    if pit_status in {"PITTING", "IN_PIT_AREA"}:
        return f"{rival.name} 正在进站流程里。"
    engine_damage = getattr(rival, "engine_damage_pct", None)
    aero_damage = getattr(rival, "aero_damage_pct", None)
    if isinstance(engine_damage, int) and engine_damage >= 35:
        return f"{rival.name} 的发动机损伤约 {engine_damage}%。"
    if isinstance(aero_damage, int) and aero_damage >= 25:
        return f"{rival.name} 的空气动力学损伤约 {aero_damage}%。"
    return None


def _rival_context_clause(rival: Any | None, *, role_label: str) -> str | None:
    if rival is None:
        return None
    parts = [f"{role_label} {rival.name}"]
    if getattr(rival, "pit_status", None) in {"PITTING", "IN_PIT_AREA"}:
        parts.append(f"处于 {rival.pit_status}")
    elif getattr(rival, "drs_available", False):
        parts.append("有 DRS")
    damage_hint = _rival_pressure_hint(rival)
    if damage_hint and "正在进站流程里" not in damage_hint:
        parts.append(damage_hint.replace(f"{rival.name} 的", "").replace("。", ""))
    return "，".join(parts)


def _rear_rival_risk_reason(rival: Any | None, gap_behind: float | None, *, defend_state: str) -> str | None:
    if defend_state == "unavailable":
        gap_behind = None
    if rival is None:
        return None
    if getattr(rival, "pit_status", None) in {"PITTING", "IN_PIT_AREA"}:
        return f"后车 {rival.name} 已进入 {rival.pit_status}，当前压力可能自行回落。"
    if getattr(rival, "drs_available", False) and defend_state == "urgent":
        return f"后车 {rival.name} 已带着 DRS 压到 {gap_behind:.3f} 秒内。"
    engine_damage = getattr(rival, "engine_damage_pct", None)
    if isinstance(engine_damage, int) and engine_damage >= 35:
        return f"后车 {rival.name} 虽然接近，但发动机损伤约 {engine_damage}%。"
    if getattr(rival, "gap_confidence_ahead", None) == "medium" and gap_behind is not None:
        return f"后车 {rival.name} 当前 {gap_behind:.3f} 秒的压力只有中可信度。"
    return None


def _front_rival_attack_reason(rival: Any | None, gap_ahead: float | None, *, attack_state: str) -> str | None:
    if attack_state == "unavailable":
        gap_ahead = None
    if rival is None:
        return None
    if getattr(rival, "pit_status", None) in {"PITTING", "IN_PIT_AREA"}:
        return f"前车 {rival.name} 已进入 {rival.pit_status}，当前更像等待窗口自然变化。"
    if getattr(rival, "gap_confidence_behind", None) == "medium" and gap_ahead is not None:
        return f"前车 {rival.name} 当前 {gap_ahead:.3f} 秒的进攻依据只有中可信度。"
    return None


def _attack_method_context(state: SessionState) -> tuple[str, str, str]:
    lap_distance = state.player.lap_distance_m
    if lap_distance is None:
        lap_distance = float(state.raw.get("lap_distance_m", 0.0) or 0.0)
    try:
        from .track_model import load_track_profile

        track_profile = load_track_profile(state.track)
        if track_profile is not None:
            classified = track_profile.classify(float(lap_distance))
            track_zone = classified.zone_type
            track_segment = classified.zone_name
            track_usage = classified.usage
        else:
            return ("general", "none", "none")
    except Exception:
        return ("general", "none", "none")

    corner_class = infer_corner_overtake_class(
        track_zone=track_zone,
        track_segment=track_segment,
        track_usage=track_usage,
    )
    setup_method = infer_attack_setup_method(
        track_zone=track_zone,
        track_usage=track_usage,
        corner_overtake_class=corner_class,
    )
    commit_method = infer_attack_commit_method(
        track_zone=track_zone,
        track_usage=track_usage,
        corner_overtake_class=corner_class,
    )
    return (corner_class, setup_method, commit_method)


def _overall_primary_posture(state: SessionState, primary_message: StrategyMessage | None) -> str:
    return render_overall_primary_posture(
        attack_state=assess_domain(state).labels.attack_state,
        defend_state=assess_domain(state).labels.defend_state,
        primary_code=primary_message.code if primary_message is not None else None,
        primary_detail=primary_message.detail if primary_message is not None else None,
        gap_ahead_s=state.player.gap_ahead_s,
        gap_behind_s=state.player.gap_behind_s,
        drs_available=state.player.drs_available,
    )


def _overall_main_risk(state: SessionState, primary_message: StrategyMessage | None) -> str:
    return render_overall_main_risk(
        tyre_state=assess_domain(state).labels.tyre_state,
        defend_state=assess_domain(state).labels.defend_state,
        primary_code=primary_message.code if primary_message is not None else None,
        primary_detail=primary_message.detail if primary_message is not None else None,
        drive_through=int(state.raw.get("num_unserved_drive_through_pens", 0) or 0),
        stop_go=int(state.raw.get("num_unserved_stop_go_pens", 0) or 0),
        should_serve_penalty=bool(state.raw.get("pit_stop_should_serve_pen", False)),
        fuel_laps_remaining=state.player.fuel_laps_remaining,
        fuel_verdict=assess_fuel(state).verdict,
        fuel_detail=assess_fuel(state).describe(),
        tyre_wear_pct=state.player.tyre.wear_pct,
        gap_behind_s=state.player.gap_behind_s,
        safety_car=state.safety_car,
    )


def _overall_next_focus(state: SessionState, primary_message: StrategyMessage | None) -> str:
    return render_overall_next_focus(
        tyre_state=assess_domain(state).labels.tyre_state,
        primary_code=primary_message.code if primary_message is not None else None,
        drive_through=int(state.raw.get("num_unserved_drive_through_pens", 0) or 0),
        stop_go=int(state.raw.get("num_unserved_stop_go_pens", 0) or 0),
        should_serve_penalty=bool(state.raw.get("pit_stop_should_serve_pen", False)),
        fuel_laps_remaining=state.player.fuel_laps_remaining,
        fuel_verdict=assess_fuel(state).verdict,
        fuel_detail=assess_fuel(state).describe(),
        tyre_wear_pct=state.player.tyre.wear_pct,
        safety_car=state.safety_car,
    )


def _damage_snapshot(state: SessionState) -> dict[str, Any]:
    raw = state.raw
    wing_damage = raw.get("wing_damage_pct") or {}
    front_left = int(wing_damage.get("front_left", 0) or 0)
    front_right = int(wing_damage.get("front_right", 0) or 0)
    engine_components = dict(raw.get("engine_components_damage_pct") or {})
    return {
        "front_wing": max(front_left, front_right),
        "rear_wing": int(wing_damage.get("rear", 0) or 0),
        "floor": int(raw.get("floor_damage_pct", 0) or 0),
        "diffuser": int(raw.get("diffuser_damage_pct", 0) or 0),
        "sidepod": int(raw.get("sidepod_damage_pct", 0) or 0),
        "gearbox": int(raw.get("gearbox_damage_pct", 0) or 0),
        "engine": int(raw.get("engine_damage_pct", 0) or 0),
        "engine_components": engine_components,
        "engine_blown": bool(raw.get("engine_blown", False)),
        "engine_seized": bool(raw.get("engine_seized", False)),
    }


def _damage_recommendation(snapshot: dict[str, Any]) -> str:
    return render_damage_recommendation(
        front_wing_pct=int(snapshot["front_wing"]),
        floor_damage_pct=int(snapshot["floor"]),
        diffuser_damage_pct=int(snapshot["diffuser"]),
        sidepod_damage_pct=int(snapshot["sidepod"]),
        engine_damage_pct=int(snapshot["engine"]),
        engine_blown=bool(snapshot["engine_blown"]),
        engine_seized=bool(snapshot["engine_seized"]),
    )


def _position_trend_snapshot(state: SessionState) -> dict[str, Any] | None:
    lap_positions = (state.raw.get("lap_positions") or {}).get("player_lap_positions") or []
    if not isinstance(lap_positions, list):
        return None
    valid_rows = [
        row for row in lap_positions
        if isinstance(row, dict) and isinstance(row.get("lap_number"), int) and row.get("position") is not None
    ]
    if len(valid_rows) < 2:
        return None
    recent = valid_rows[-3:]
    start = recent[0]
    end = recent[-1]
    start_position = int(start["position"])
    end_position = int(end["position"])
    delta = start_position - end_position
    return {
        "start_lap": int(start["lap_number"]),
        "end_lap": int(end["lap_number"]),
        "start_position": start_position,
        "end_position": end_position,
        "positions": [int(item["position"]) for item in recent],
        "net_gain": delta,
    }


def _position_trend_clause(state: SessionState) -> str | None:
    trend = _position_trend_snapshot(state)
    if trend is None:
        return None
    start_lap = int(trend["start_lap"])
    end_lap = int(trend["end_lap"])
    start_position = int(trend["start_position"])
    end_position = int(trend["end_position"])
    if start_position == end_position:
        return f"最近从第 {start_lap} 圈到第 {end_lap} 圈位置基本维持在 P{end_position}。"
    if start_position > end_position:
        return f"最近从第 {start_lap} 圈到第 {end_lap} 圈已经前进 {start_position - end_position} 位，目前到 P{end_position}。"
    return f"最近从第 {start_lap} 圈到第 {end_lap} 圈回落了 {end_position - start_position} 位，目前在 P{end_position}。"


def _max_abs(values: Any) -> float | None:
    if not isinstance(values, list):
        return None
    normalized = []
    for item in values:
        try:
            normalized.append(abs(float(item)))
        except (TypeError, ValueError):
            continue
    if not normalized:
        return None
    return max(normalized)


def _scalar(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _axis_abs(mapping: Any, key: str) -> float | None:
    if not isinstance(mapping, dict):
        return None
    value = _scalar(mapping.get(key))
    return None if value is None else abs(value)


def _dynamics_snapshot(state: SessionState) -> dict[str, float | None]:
    raw = state.raw
    angular_velocity = raw.get("angular_velocity") or {}
    angular_acceleration = raw.get("angular_acceleration") or {}
    front_aero_height = _scalar(raw.get("front_aero_height")) or 0.0
    rear_aero_height = _scalar(raw.get("rear_aero_height")) or 0.0
    front_roll_angle = _scalar(raw.get("front_roll_angle"))
    rear_roll_angle = _scalar(raw.get("rear_roll_angle"))
    roll_balance = None
    if front_roll_angle is not None and rear_roll_angle is not None:
        roll_balance = abs(front_roll_angle - rear_roll_angle)
    return {
        "max_slip_ratio": _max_abs(raw.get("wheel_slip_ratio")),
        "max_slip_angle": _max_abs(raw.get("wheel_slip_angle")),
        "max_lat_force": _max_abs(raw.get("wheel_lat_force")),
        "max_long_force": _max_abs(raw.get("wheel_long_force")),
        "max_vert_force": _max_abs(raw.get("wheel_vert_force")),
        "yaw_rate": _axis_abs(angular_velocity, "yaw") or 0.0,
        "yaw_accel": _axis_abs(angular_acceleration, "yaw"),
        "pitch_accel": _axis_abs(angular_acceleration, "pitch"),
        "roll_accel": _axis_abs(angular_acceleration, "roll"),
        "front_aero_height": front_aero_height,
        "rear_aero_height": rear_aero_height,
        "aero_rake": rear_aero_height - front_aero_height,
        "front_roll_angle": front_roll_angle,
        "rear_roll_angle": rear_roll_angle,
        "roll_balance": roll_balance,
        "chassis_yaw": _scalar(raw.get("chassis_yaw")),
        "chassis_pitch": _scalar(raw.get("chassis_pitch")),
        "max_camber_abs": _max_abs(raw.get("wheel_camber")),
        "max_camber_gain_abs": _max_abs(raw.get("wheel_camber_gain")),
    }


def _dynamics_clause(state: SessionState) -> str | None:
    motion = _dynamics_snapshot(state)
    max_slip_ratio = motion["max_slip_ratio"]
    max_slip_angle = motion["max_slip_angle"]
    yaw_rate = motion["yaw_rate"]
    yaw_accel = motion["yaw_accel"]
    roll_balance = motion["roll_balance"]
    max_lat_force = motion["max_lat_force"]
    aero_rake = motion["aero_rake"]
    max_camber_gain_abs = motion["max_camber_gain_abs"]
    if max_slip_angle is not None and max_slip_angle >= 0.12:
        return f"当前轮胎侧滑角峰值约 {max_slip_angle:.3f}，车身姿态还不够干净。"
    if max_slip_ratio is not None and max_slip_ratio >= 0.11:
        return f"当前轮胎滑移率峰值约 {max_slip_ratio:.3f}，牵引阶段需要更克制。"
    if yaw_rate is not None and yaw_rate >= 0.85:
        return f"当前偏航角速度约 {yaw_rate:.3f}，车尾姿态波动偏大。"
    if yaw_accel is not None and yaw_accel >= 2.4:
        return f"当前偏航角加速度约 {yaw_accel:.3f}，姿态切换偏急。"
    if roll_balance is not None and roll_balance >= 1.0:
        return f"当前前后滚转角差约 {roll_balance:.3f}，载荷转移还不均匀。"
    if max_lat_force is not None and max_lat_force >= 4.0:
        return f"当前横向载荷峰值约 {max_lat_force:.3f}，中高速侧向负荷已经偏高。"
    if aero_rake >= 2.5:
        return f"当前前后车身高度差约 {aero_rake:.2f}，高速姿态需要更稳。"
    if max_camber_gain_abs is not None and max_camber_gain_abs >= 0.35:
        return f"当前外倾变化幅度约 {max_camber_gain_abs:.3f}，轮胎接地状态还不够稳定。"
    return None


def _engine_component_hotspots(snapshot: dict[str, Any]) -> list[tuple[str, int]]:
    component_map = snapshot.get("engine_components") or {}
    if not isinstance(component_map, dict):
        return []
    normalized = []
    for key, value in component_map.items():
        try:
            normalized.append((str(key), int(value)))
        except (TypeError, ValueError):
            continue
    return sorted(normalized, key=lambda item: item[1], reverse=True)


def _engine_component_clause(snapshot: dict[str, Any]) -> str | None:
    hotspots = [item for item in _engine_component_hotspots(snapshot) if item[1] >= 25]
    if not hotspots:
        return None
    top = hotspots[:2]
    labels = {
        "ice": "ICE",
        "mguk": "MGU-K",
        "mguh": "MGU-H",
        "energy_store": "Energy Store",
        "control_electronics": "Control Electronics",
        "turbo_charger": "Turbo Charger",
    }
    detail = "，".join(f"{labels.get(name, name)} {value}%" for name, value in top)
    return f"动力单元里更需要盯的是 {detail}。"


def _tyre_wear_outlook(state: SessionState, primary_message: StrategyMessage | None) -> str:
    labels = assess_domain(state).labels
    if labels.tyre_state == "unavailable":
        return "轮胎磨损数据不可用，暂不能预测磨损变化。"
    tyre = state.player.tyre
    active_attack = bool(
        primary_message is not None and primary_message.code == "ATTACK_WINDOW"
    ) or (
        labels.attack_state == "available"
    )
    active_defend = bool(
        primary_message is not None and primary_message.code == "DEFEND_WINDOW"
    ) or (labels.defend_state == "urgent")
    return render_tyre_wear_outlook(
        tyre_state=labels.tyre_state,
        wear_pct=tyre.wear_pct,
        age_laps=tyre.age_laps,
        active_attack=active_attack,
        active_defend=active_defend,
    )


def compose_structured_query_response(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    from .capability_definitions import CAPABILITIES
    spec = CAPABILITIES.get(query_kind)
    if spec is not None and spec.handler_name is not None and spec.lane != 'analysis_tool':
        return spec.invoke(state=state, primary_message=primary_message, schema_metadata=schema_metadata)
    return (
        render_not_supported_answer("当前查询类型还未接入模板回答。"),
        "QUERY_SNAPSHOT_STATUS",
    )
