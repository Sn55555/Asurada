from __future__ import annotations

from ..race_control import race_control_active, normalize_race_control, describe_race_control

from ..response_composer import (
    Any,
    SessionState,
    StrategyMessage,
    _damage_snapshot,
    _dynamics_clause,
    _engine_component_hotspots,
    _format_gap,
    _front_rival,
    _front_rival_attack_reason,
    _overall_main_risk,
    _overall_next_focus,
    _overall_primary_posture,
    _position_trend_clause,
    _position_trend_snapshot,
    _rear_rival,
    _rear_rival_risk_reason,
    assess_domain,
    assess_fuel,
    render_conclusion_with_reason,
    render_not_supported_answer,
    render_open_fallback_detail,
    render_summary_answer,
)


def _handle_drs_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if state.player.drs_available:
        detail = "当前 DRS 可用。"
        if state.player.gap_ahead_s is not None:
            detail += f" 前车时差 {state.player.gap_ahead_s:.3f} 秒。"
    else:
        detail = "当前 DRS 不可用。"
        if state.player.gap_ahead_s is not None:
            detail += f" 前车时差 {state.player.gap_ahead_s:.3f} 秒。"
    return (render_summary_answer(detail), "QUERY_DRS_STATUS")



def _handle_weather_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    safety_car = describe_race_control(state.safety_car)
    return (
        render_summary_answer(f"当前天气是 {state.weather}，赛道状态为 {safety_car}。"),
        "QUERY_WEATHER_STATUS",
    )



def _handle_race_control_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if state.raw.get("marshal_zone_flag") == 3:
        return ("本区黄旗，减速，禁止超车。", "QUERY_RACE_CONTROL_STATUS")
    if normalize_race_control(state.safety_car) is None:
        detail = "赛道管制数据不可用，暂不能判断当前管制状态。"
    elif state.safety_car == "NONE":
        detail = f"当前没有赛道管制，天气是 {state.weather}。"
    else:
        detail = f"当前赛道处于 {state.safety_car} 阶段，天气是 {state.weather}。"
    return (render_summary_answer(detail), "QUERY_RACE_CONTROL_STATUS")



def _handle_current_strategy(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if primary_message is None:
        return (
            render_not_supported_answer("当前没有高优先级主策略。"),
            "QUERY_CURRENT_STRATEGY",
        )
    return (
        render_conclusion_with_reason(
            f"当前主策略是 {primary_message.title}",
            primary_message.detail,
            connector="原因是",
        ),
        "QUERY_CURRENT_STRATEGY",
    )



def _handle_overall_situation(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    gap_ahead = _format_gap(state.player.gap_ahead_s)
    gap_behind = _format_gap(state.player.gap_behind_s)
    safety_car = describe_race_control(state.safety_car)
    posture = _overall_primary_posture(state, primary_message)
    main_risk = _overall_main_risk(state, primary_message)
    next_focus = _overall_next_focus(state, primary_message)
    front_rival = _front_rival(state)
    rear_rival = _rear_rival(state)
    rival_context_parts: list[str] = []
    if front_rival is not None:
        rival_context_parts.append(
            f"前车 {front_rival.name}"
            + (
                f" 处于 {front_rival.pit_status}"
                if getattr(front_rival, "pit_status", None) in {"PITTING", "IN_PIT_AREA"}
                else ""
            )
        )
    if rear_rival is not None:
        rear_part = f"后车 {rear_rival.name}"
        if getattr(rear_rival, "drs_available", False):
            rear_part += " 有 DRS"
        rival_context_parts.append(rear_part)
    rival_context = "，".join(rival_context_parts)
    position_trend = _position_trend_clause(state)
    dynamics_clause = _dynamics_clause(state)
    return (
        render_summary_answer(
            posture,
            main_risk,
            next_focus,
            f"前车差距 {gap_ahead}，后车差距 {gap_behind}，"
            f"燃油预计 {state.player.fuel_laps_remaining:.1f} 圈，轮胎磨损 {state.player.tyre.wear_pct:.1f}%，"
            f"ERS {state.player.ers_pct:.1f}%，天气 {state.weather}，赛道状态 {safety_car}。"
            + (f" {rival_context}。" if rival_context else "")
            + (f" {position_trend}" if position_trend else "")
            + (f" {dynamics_clause}" if dynamics_clause else ""),
        ),
        "QUERY_OVERALL_SITUATION",
    )



def _handle_main_risk_summary(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
    stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
    should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
    fuel = state.player.fuel_laps_remaining
    tyre_wear = state.player.tyre.wear_pct
    gap_behind = state.player.gap_behind_s
    rear_rival = _rear_rival(state)
    rear_reason = _rear_rival_risk_reason(rear_rival, gap_behind, defend_state=assess_domain(state).labels.defend_state)
    damage = _damage_snapshot(state)
    component_hotspots = _engine_component_hotspots(damage)
    dynamics_clause = _dynamics_clause(state)
    if drive_through or stop_go or should_serve:
        detail = (
            f"当前最大风险是处罚处理，下一次进站需要处理。待执行穿越维修区 {drive_through} 条，"
            f"stop-go {stop_go} 条。"
        )
    elif rear_reason and "带着 DRS" in rear_reason:
        detail = f"当前最大风险是后车直接进攻窗口，因为{rear_reason}"
    elif primary_message is not None and primary_message.code == "DEFEND_WINDOW":
        detail = f"当前最大风险是后车压力，因为 {primary_message.detail}"
    elif rear_reason and "中可信度" in rear_reason:
        detail = f"当前最大变量仍是后车压力，但{rear_reason}"
    elif assess_domain(state).labels.defend_state == "urgent":
        detail = f"当前最大风险是后车逼近，差距只有 {gap_behind:.3f} 秒。"
    elif assess_fuel(state).verdict == "critical":
        detail = "当前最大风险是燃油偏紧。" + assess_fuel(state).describe()
    elif assess_domain(state).labels.tyre_state in {"manage", "box_now"}:
        detail = f"当前最大风险是轮胎磨损偏高，已经到 {tyre_wear:.1f}%。"
    elif component_hotspots and component_hotspots[0][1] >= 45:
        label = {
            "ice": "ICE",
            "mguk": "MGU-K",
            "mguh": "MGU-H",
            "energy_store": "Energy Store",
            "control_electronics": "Control Electronics",
            "turbo_charger": "Turbo Charger",
        }.get(component_hotspots[0][0], component_hotspots[0][0])
        detail = f"当前最大风险开始转向动力单元，{label} 损伤已经到 {component_hotspots[0][1]}%。"
    elif dynamics_clause:
        detail = f"当前最大风险开始转向车辆姿态，因为{dynamics_clause}"
    elif race_control_active(state.safety_car):
        detail = f"当前最大变量是赛道管制，赛道处于 {state.safety_car} 阶段。"
    else:
        detail = "当前没有单一压倒性风险，主要还是控制前后车差距并稳定资源消耗。"
    return (render_summary_answer(detail), "QUERY_MAIN_RISK_SUMMARY")



def _handle_next_lap_focus(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
    stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
    should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
    front_rival = _front_rival(state)
    rear_rival = _rear_rival(state)
    front_reason = _front_rival_attack_reason(front_rival, state.player.gap_ahead_s, attack_state=assess_domain(state).labels.attack_state)
    rear_reason = _rear_rival_risk_reason(rear_rival, state.player.gap_behind_s, defend_state=assess_domain(state).labels.defend_state)
    position_trend = _position_trend_snapshot(state)
    dynamics_clause = _dynamics_clause(state)
    if drive_through or stop_go or should_serve:
        detail = "接下来几圈先把处罚处理优先级放高，别错过下一次合适的处理窗口。"
    elif rear_reason and "带着 DRS" in rear_reason:
        detail = f"接下来几圈先守住后车 DRS 压力，因为{rear_reason}"
    elif primary_message is not None and primary_message.code == "DEFEND_WINDOW":
        detail = "接下来几圈先守住后车，重点看后车 DRS 线和出弯稳定性。"
    elif front_reason and "等待窗口自然变化" in front_reason:
        detail = f"接下来几圈先观察前车窗口变化，因为{front_reason}"
    elif dynamics_clause:
        detail = f"接下来几圈先把车辆姿态稳住，因为{dynamics_clause}"
    elif position_trend is not None and int(position_trend["net_gain"]) < 0:
        detail = f"接下来几圈先止住位置下滑，最近从 P{position_trend['start_position']} 掉到 P{position_trend['end_position']}。"
    elif position_trend is not None and int(position_trend["net_gain"]) > 0:
        detail = f"接下来几圈先稳住刚拿到的位置，最近已经从 P{position_trend['start_position']} 提到 P{position_trend['end_position']}。"
    elif primary_message is not None and primary_message.code == "ATTACK_WINDOW":
        detail = "接下来几圈先盯前车差距和 DRS 兑现，避免在资源不足时硬上。"
    elif assess_fuel(state).verdict == "critical":
        detail = "接下来几圈先控燃油。" + assess_fuel(state).describe()
    elif assess_domain(state).labels.tyre_state in {"manage", "box_now"}:
        detail = f"接下来几圈先保护轮胎，当前磨损已经到 {state.player.tyre.wear_pct:.1f}%。"
    elif race_control_active(state.safety_car):
        detail = f"接下来几圈重点看赛道管制变化，当前赛道处于 {state.safety_car} 阶段。"
    else:
        detail = "接下来几圈先稳住节奏，优先管理前后车差距、ERS 和轮胎消耗。"
    return (render_summary_answer(detail), "QUERY_NEXT_LAP_FOCUS")



def _handle_risk_severity_followup(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
    stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
    should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
    fuel = state.player.fuel_laps_remaining
    tyre_wear = state.player.tyre.wear_pct
    gap_behind = state.player.gap_behind_s
    rear_rival = _rear_rival(state)
    rear_reason = _rear_rival_risk_reason(rear_rival, gap_behind, defend_state=assess_domain(state).labels.defend_state)
    if drive_through > 0:
        detail = "这个风险很高，因为 drive-through 不能拖延处理。"
    elif stop_go > 0 or should_serve:
        detail = "这个风险偏高，因为下一次进站必须专门处理 stop-go。"
    elif rear_reason and "带着 DRS" in rear_reason:
        detail = f"这个风险偏高，因为{rear_reason}"
    elif assess_domain(state).labels.defend_state == "urgent":
        detail = f"这个风险偏高，后车已经压到 {gap_behind:.3f} 秒内。"
    elif assess_fuel(state).verdict == "critical":
        detail = "这个风险偏高。" + assess_fuel(state).describe()
    elif assess_domain(state).labels.tyre_state in {"manage", "box_now"}:
        detail = f"这个风险中高，轮胎磨损已经到 {tyre_wear:.1f}%。"
    else:
        detail = "这个风险目前是中等，还没有压到必须立刻处理。"
    return (render_summary_answer(detail), "QUERY_RISK_SEVERITY")



def _handle_risk_escalation_timing(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
    stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
    should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
    gap_behind = state.player.gap_behind_s
    fuel = state.player.fuel_laps_remaining
    tyre_wear = state.player.tyre.wear_pct
    rear_rival = _rear_rival(state)
    rear_reason = _rear_rival_risk_reason(rear_rival, gap_behind, defend_state=assess_domain(state).labels.defend_state)
    if drive_through > 0:
        detail = "这个风险已经是立即要处理的级别，当前就不能再继续拖。"
    elif stop_go > 0 or should_serve:
        detail = "这个风险已经偏高，最晚到下一次进站窗口就会变成强约束。"
    elif rear_reason and "中可信度" in rear_reason:
        detail = f"这个风险短期仍要观察，因为{rear_reason}"
    elif rear_reason and "带着 DRS" in rear_reason:
        detail = f"这个风险已经在高位，因为{rear_reason} 下一段就可能继续升级。"
    elif assess_domain(state).labels.defend_state == "urgent":
        detail = f"这个风险已经在高位，下一段到下一圈内就可能继续升级，当前后车只有 {gap_behind:.3f} 秒。"
    elif assess_fuel(state).verdict == "critical":
        detail = "燃油风险需要当前就关注。" + assess_fuel(state).describe()
    elif assess_domain(state).labels.tyre_state in {"manage", "box_now"}:
        detail = f"这个风险会在接下来两三圈继续放大，当前轮胎磨损已经到 {tyre_wear:.1f}%。"
    else:
        detail = "这个风险短期不会立刻跳变，当前更像需要持续观察而不是马上处理。"
    return (render_summary_answer(detail), "QUERY_RISK_ESCALATION_TIMING")



def _handle_why_current_strategy(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if primary_message is None:
        return (
            render_summary_answer("当前没有高优先级主策略。", "所以系统没有额外解释项。"),
            "QUERY_WHY_CURRENT_STRATEGY",
        )
    return (
        render_conclusion_with_reason(
            f"当前把 {primary_message.title} 放在首位",
            primary_message.detail,
            connector="因为",
        ),
        "QUERY_WHY_CURRENT_STRATEGY",
    )



def _handle_open_fallback(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    query_text = str((schema_metadata or {}).get("query_text") or "").strip()
    semantic_metadata = (schema_metadata or {}).get("semantic_metadata") or {}
    domain_hint = str(semantic_metadata.get("domain_hint") or "general")
    detail = render_open_fallback_detail(domain_hint)
    prefix = f"关于“{query_text}”，" if query_text else ""
    return (render_summary_answer(f"{prefix}{detail}"), "QUERY_OPEN_FALLBACK")

