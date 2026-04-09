from __future__ import annotations

from typing import Any

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


def _overall_primary_posture(state: SessionState, primary_message: StrategyMessage | None) -> str:
    return render_overall_primary_posture(
        primary_code=primary_message.code if primary_message is not None else None,
        primary_detail=primary_message.detail if primary_message is not None else None,
        gap_ahead_s=state.player.gap_ahead_s,
        gap_behind_s=state.player.gap_behind_s,
        drs_available=state.player.drs_available,
    )


def _overall_main_risk(state: SessionState, primary_message: StrategyMessage | None) -> str:
    return render_overall_main_risk(
        primary_code=primary_message.code if primary_message is not None else None,
        primary_detail=primary_message.detail if primary_message is not None else None,
        drive_through=int(state.raw.get("num_unserved_drive_through_pens", 0) or 0),
        stop_go=int(state.raw.get("num_unserved_stop_go_pens", 0) or 0),
        should_serve_penalty=bool(state.raw.get("pit_stop_should_serve_pen", False)),
        fuel_laps_remaining=state.player.fuel_laps_remaining,
        tyre_wear_pct=state.player.tyre.wear_pct,
        gap_behind_s=state.player.gap_behind_s,
        safety_car=state.safety_car,
    )


def _overall_next_focus(state: SessionState, primary_message: StrategyMessage | None) -> str:
    return render_overall_next_focus(
        primary_code=primary_message.code if primary_message is not None else None,
        drive_through=int(state.raw.get("num_unserved_drive_through_pens", 0) or 0),
        stop_go=int(state.raw.get("num_unserved_stop_go_pens", 0) or 0),
        should_serve_penalty=bool(state.raw.get("pit_stop_should_serve_pen", False)),
        fuel_laps_remaining=state.player.fuel_laps_remaining,
        tyre_wear_pct=state.player.tyre.wear_pct,
        safety_car=state.safety_car,
    )


def _damage_snapshot(state: SessionState) -> dict[str, Any]:
    raw = state.raw
    wing_damage = raw.get("wing_damage_pct") or {}
    front_left = int(wing_damage.get("front_left", 0) or 0)
    front_right = int(wing_damage.get("front_right", 0) or 0)
    return {
        "front_wing": max(front_left, front_right),
        "rear_wing": int(wing_damage.get("rear", 0) or 0),
        "floor": int(raw.get("floor_damage_pct", 0) or 0),
        "diffuser": int(raw.get("diffuser_damage_pct", 0) or 0),
        "sidepod": int(raw.get("sidepod_damage_pct", 0) or 0),
        "gearbox": int(raw.get("gearbox_damage_pct", 0) or 0),
        "engine": int(raw.get("engine_damage_pct", 0) or 0),
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


def _tyre_wear_outlook(state: SessionState, primary_message: StrategyMessage | None) -> str:
    tyre = state.player.tyre
    gap_ahead = state.player.gap_ahead_s
    gap_behind = state.player.gap_behind_s
    active_attack = bool(
        primary_message is not None and primary_message.code == "ATTACK_WINDOW"
    ) or (
        gap_ahead is not None and gap_ahead <= 1.0 and state.player.drs_available
    )
    active_defend = bool(
        primary_message is not None and primary_message.code == "DEFEND_WINDOW"
    ) or (gap_behind is not None and gap_behind <= 1.1)
    return render_tyre_wear_outlook(
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
    if query_kind == "fuel_status":
        fuel = state.player.fuel_laps_remaining
        if fuel <= 3.0:
            verdict = "燃油已经偏紧。"
        elif fuel <= 8.0:
            verdict = "燃油还有余量，但需要开始关注节奏。"
        else:
            verdict = "燃油余量正常。"
        return (
            render_verdict_with_numbers(
                verdict,
                f"当前预计还能跑 {fuel:.1f} 圈，总圈数 {state.total_laps} 圈。",
            ),
            "QUERY_FUEL_STATUS",
        )

    if query_kind == "damage_status":
        damage = _damage_snapshot(state)
        recommendation = _damage_recommendation(damage)
        return (
            render_summary_answer(
                f"当前主要车损是前翼 {damage['front_wing']}%，底板 {damage['floor']}%，扩散器 {damage['diffuser']}%，发动机 {damage['engine']}%。",
                recommendation,
            ),
            "QUERY_DAMAGE_STATUS",
        )

    if query_kind == "damage_pit_advice":
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
            render_summary_answer(detail, recommendation),
            "QUERY_DAMAGE_PIT_ADVICE",
        )

    if query_kind == "front_wing_damage_status":
        damage = _damage_snapshot(state)
        detail = render_front_wing_damage_detail(int(damage["front_wing"]))
        return (render_summary_answer(detail), "QUERY_FRONT_WING_DAMAGE_STATUS")

    if query_kind == "floor_damage_status":
        damage = _damage_snapshot(state)
        detail = render_floor_damage_detail(
            int(damage["floor"]),
            int(damage["diffuser"]),
            int(damage["sidepod"]),
        )
        return (render_summary_answer(detail), "QUERY_FLOOR_DAMAGE_STATUS")

    if query_kind == "engine_damage_status":
        damage = _damage_snapshot(state)
        detail = render_engine_damage_detail(
            engine_damage_pct=int(damage["engine"]),
            engine_blown=bool(damage["engine_blown"]),
            engine_seized=bool(damage["engine_seized"]),
        )
        return (render_summary_answer(detail), "QUERY_ENGINE_DAMAGE_STATUS")

    if query_kind == "front_gap":
        if state.player.gap_ahead_s is None:
            return (
                render_unavailable_answer("前车时差", "当前不能可靠判断进攻距离。"),
                "QUERY_FRONT_GAP",
            )
        front_name = state.rivals[0].name if state.rivals else "前车"
        gap = state.player.gap_ahead_s
        if gap <= 1.0 and state.player.drs_available:
            verdict = "前车已经进直接进攻观察窗口。"
        elif gap <= 1.2:
            verdict = "前车正在进入可施压距离。"
        else:
            verdict = "前车还没进直接进攻窗口。"
        drs_hint = "当前有 DRS。" if state.player.drs_available else "当前没有 DRS。"
        return (
            render_verdict_with_numbers(
                verdict,
                f"前车 {front_name} 领先 {gap:.3f} 秒。",
                drs_hint,
            ),
            "QUERY_FRONT_GAP",
        )

    if query_kind == "front_rival_drs_status":
        if not state.rivals:
            return (
                render_not_supported_answer("当前没有可靠前车对象，不能判断前车 DRS 状态。"),
                "QUERY_FRONT_RIVAL_DRS_STATUS",
            )
        front_rival = state.rivals[0]
        if front_rival.drs_available:
            detail = f"前车 {front_rival.name} 当前有 DRS。"
        else:
            detail = f"前车 {front_rival.name} 当前没有 DRS。"
        if state.player.gap_ahead_s is not None:
            detail += f" 你与前车差距 {state.player.gap_ahead_s:.3f} 秒。"
        return (render_summary_answer(detail), "QUERY_FRONT_RIVAL_DRS_STATUS")

    if query_kind == "rear_gap":
        if state.player.gap_behind_s is None:
            return (
                render_unavailable_answer("后车时差", "当前不能可靠判断防守压力。"),
                "QUERY_REAR_GAP",
            )
        rear_name = state.rivals[0].name if state.rivals else "后车"
        gap = state.player.gap_behind_s
        if gap <= 1.0:
            verdict = "后车已经进直接防守窗口。"
        elif gap <= 1.5:
            verdict = "后车正在逼近，需要开始准备防守。"
        else:
            verdict = "后车暂时还没进直接防守窗口。"
        return (
            render_verdict_with_numbers(
                verdict,
                f"后车 {rear_name} 落后 {gap:.3f} 秒。",
            ),
            "QUERY_REAR_GAP",
        )

    if query_kind == "rear_rival_drs_status":
        if state.player.gap_behind_s is None:
            return (
                render_unavailable_answer("后车时差", "当前不能可靠判断后车是否进 DRS 线。"),
                "QUERY_REAR_RIVAL_DRS_STATUS",
            )
        rear_name = state.rivals[0].name if state.rivals else "后车"
        gap = state.player.gap_behind_s
        if gap <= 1.0:
            detail = f"后车 {rear_name} 已经进 DRS 线，当前差距 {gap:.3f} 秒。"
        else:
            detail = f"后车 {rear_name} 还没进 DRS 线，当前差距 {gap:.3f} 秒。"
        return (render_summary_answer(detail), "QUERY_REAR_RIVAL_DRS_STATUS")

    if query_kind == "tyre_status":
        tyre = state.player.tyre
        if tyre.wear_pct >= 70.0:
            verdict = "轮胎磨损已经偏高。"
        elif tyre.wear_pct >= 40.0:
            verdict = "轮胎处在中段磨损。"
        else:
            verdict = "轮胎状态还比较健康。"
        return (
            render_verdict_with_numbers(
                verdict,
                f"当前 {tyre.compound}，磨损 {tyre.wear_pct:.1f}%，胎龄 {tyre.age_laps} 圈。",
            ),
            "QUERY_TYRE_STATUS",
        )

    if query_kind == "drs_status":
        if state.player.drs_available:
            detail = "当前 DRS 可用。"
            if state.player.gap_ahead_s is not None:
                detail += f" 前车时差 {state.player.gap_ahead_s:.3f} 秒。"
        else:
            detail = "当前 DRS 不可用。"
            if state.player.gap_ahead_s is not None:
                detail += f" 前车时差 {state.player.gap_ahead_s:.3f} 秒。"
        return (render_summary_answer(detail), "QUERY_DRS_STATUS")

    if query_kind == "ers_status":
        ers_pct = state.player.ers_pct
        if ers_pct <= 20.0:
            verdict = "ERS 已经偏低。"
        elif ers_pct <= 55.0:
            verdict = "ERS 处在中段。"
        else:
            verdict = "ERS 余量还比较充足。"
        return (
            render_verdict_with_numbers(verdict, f"当前剩余 {ers_pct:.1f}%。"),
            "QUERY_ERS_STATUS",
        )

    if query_kind == "weather_status":
        safety_car = "无赛道管制" if state.safety_car == "NONE" else f"{state.safety_car} 阶段"
        return (
            render_summary_answer(f"当前天气是 {state.weather}，赛道状态为 {safety_car}。"),
            "QUERY_WEATHER_STATUS",
        )

    if query_kind == "race_control_status":
        if state.safety_car == "NONE":
            detail = f"当前没有赛道管制，天气是 {state.weather}。"
        else:
            detail = f"当前赛道处于 {state.safety_car} 阶段，天气是 {state.weather}。"
        return (render_summary_answer(detail), "QUERY_RACE_CONTROL_STATUS")

    if query_kind == "penalty_status":
        warnings = int(state.raw.get("total_warnings", 0) or 0)
        corner_cutting = int(state.raw.get("corner_cutting_warnings", 0) or 0)
        drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
        stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
        should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
        if drive_through or stop_go:
            detail = f"待执行处罚：穿越维修区 {drive_through} 条，stop-go {stop_go} 条。"
        elif warnings or corner_cutting:
            detail = f"当前有 {warnings} 次警告，其中切弯警告 {corner_cutting} 次。"
        else:
            detail = "当前没有待执行处罚，也没有警告。"
        if should_serve:
            detail += " 下一次进站需要处理处罚。"
        return (render_summary_answer(detail), "QUERY_PENALTY_STATUS")

    if query_kind == "pit_status":
        pit_status = str(state.raw.get("pit_status") or "NONE")
        num_stops = int(state.raw.get("num_pit_stops", 0) or 0)
        pit_timer_active = bool(state.raw.get("pit_lane_timer_active", False))
        pit_stop_timer_ms = int(state.raw.get("pit_stop_timer_ms", 0) or 0)
        serve_pen = bool(state.raw.get("pit_stop_should_serve_pen", False))
        if pit_status in {"PITTING", "IN_PIT_AREA"}:
            detail = f"当前处于进站流程，状态 {pit_status}。"
            if pit_timer_active:
                detail += f" 站内计时 {pit_stop_timer_ms / 1000.0:.1f} 秒。"
        else:
            detail = f"当前没有处于进站流程，累计已进站 {num_stops} 次。"
        if serve_pen:
            detail += " 这次进站需要处理处罚。"
        return (render_summary_answer(detail), "QUERY_PIT_STATUS")

    if query_kind == "pit_penalty_plan":
        drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
        stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
        should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
        if drive_through or stop_go or should_serve:
            detail = (
                f"下次进站需要处理处罚。当前待执行处罚：穿越维修区 {drive_through} 条，"
                f"stop-go {stop_go} 条。"
            )
        else:
            detail = "下次进站当前不需要处理处罚。现在没有待执行 drive-through 或 stop-go。"
        return (render_summary_answer(detail), "QUERY_PIT_PENALTY_PLAN")

    if query_kind == "penalty_handling_strategy":
        drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
        stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
        should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
        if drive_through > 0:
            detail = "当前最优先的是尽快完成穿越维修区处罚，这类处罚不能拖成一次普通进站。"
        elif stop_go > 0 or should_serve:
            detail = "当前最好的处理方式是把下一次进站明确用来处理 stop-go，不要把这次进站浪费成普通换胎。"
        else:
            detail = "当前没有待处理处罚，不需要专门围绕处罚调整进站。"
        return (render_summary_answer(detail), "QUERY_PENALTY_HANDLING_STRATEGY")

    if query_kind == "current_strategy":
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

    if query_kind == "overall_situation":
        gap_ahead = _format_gap(state.player.gap_ahead_s)
        gap_behind = _format_gap(state.player.gap_behind_s)
        safety_car = "无赛道管制" if state.safety_car == "NONE" else state.safety_car
        posture = _overall_primary_posture(state, primary_message)
        main_risk = _overall_main_risk(state, primary_message)
        next_focus = _overall_next_focus(state, primary_message)
        return (
            render_summary_answer(
                posture,
                main_risk,
                next_focus,
                f"前车差距 {gap_ahead}，后车差距 {gap_behind}，"
                f"燃油预计 {state.player.fuel_laps_remaining:.1f} 圈，轮胎磨损 {state.player.tyre.wear_pct:.1f}%，"
                f"ERS {state.player.ers_pct:.1f}%，天气 {state.weather}，赛道状态 {safety_car}。",
            ),
            "QUERY_OVERALL_SITUATION",
        )

    if query_kind == "attack_or_defend_summary":
        gap_ahead = state.player.gap_ahead_s
        gap_behind = state.player.gap_behind_s
        if primary_message is not None and primary_message.code == "DEFEND_WINDOW":
            detail = f"当前更偏向防守，因为 {primary_message.detail}"
        elif primary_message is not None and primary_message.code == "ATTACK_WINDOW":
            detail = f"当前更偏向进攻，因为 {primary_message.detail}"
        elif gap_behind is not None and gap_behind <= 1.2:
            detail = f"当前更偏向防守，后车差距只有 {gap_behind:.3f} 秒。"
        elif gap_ahead is not None and gap_ahead <= 1.0 and state.player.drs_available:
            detail = f"当前更偏向进攻，前车差距 {gap_ahead:.3f} 秒且 DRS 可用。"
        else:
            detail = "当前更偏向中性管理，前后车都还没把攻防窗口压到最强。"
        return (render_summary_answer(detail), "QUERY_ATTACK_OR_DEFEND_SUMMARY")

    if query_kind == "attack_defend_tradeoff":
        gap_ahead = state.player.gap_ahead_s
        gap_behind = state.player.gap_behind_s
        fuel = state.player.fuel_laps_remaining
        tyre_wear = state.player.tyre.wear_pct
        if gap_behind is not None and gap_behind <= 1.0:
            detail = f"当前防守代价更低，因为后车已经压到 {gap_behind:.3f} 秒内，贸然进攻更容易把位置暴露出去。"
        elif gap_ahead is not None and gap_ahead <= 1.0 and state.player.drs_available and (gap_behind is None or gap_behind > 1.2):
            detail = f"当前进攻代价更低，因为前车只有 {gap_ahead:.3f} 秒且 DRS 可用，后车压力相对可控。"
        elif fuel <= 3.0 or tyre_wear >= 65.0:
            detail = "当前两边代价都不低，但更大的成本来自资源消耗，优先稳住资源比强攻或强守更划算。"
        else:
            detail = "当前攻守代价接近，更适合跟着下一段前后车变化再决定。"
        return (render_summary_answer(detail), "QUERY_ATTACK_DEFEND_TRADEOFF")

    if query_kind == "main_risk_summary":
        drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
        stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
        should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
        fuel = state.player.fuel_laps_remaining
        tyre_wear = state.player.tyre.wear_pct
        gap_behind = state.player.gap_behind_s
        if drive_through or stop_go or should_serve:
            detail = (
                f"当前最大风险是处罚处理，下一次进站需要处理。待执行穿越维修区 {drive_through} 条，"
                f"stop-go {stop_go} 条。"
            )
        elif primary_message is not None and primary_message.code == "DEFEND_WINDOW":
            detail = f"当前最大风险是后车压力，因为 {primary_message.detail}"
        elif gap_behind is not None and gap_behind <= 1.1:
            detail = f"当前最大风险是后车逼近，差距只有 {gap_behind:.3f} 秒。"
        elif fuel <= 3.0:
            detail = f"当前最大风险是燃油偏紧，预计只剩 {fuel:.1f} 圈。"
        elif tyre_wear >= 65.0:
            detail = f"当前最大风险是轮胎磨损偏高，已经到 {tyre_wear:.1f}%。"
        elif state.safety_car != "NONE":
            detail = f"当前最大变量是赛道管制，赛道处于 {state.safety_car} 阶段。"
        else:
            detail = "当前没有单一压倒性风险，主要还是控制前后车差距并稳定资源消耗。"
        return (render_summary_answer(detail), "QUERY_MAIN_RISK_SUMMARY")

    if query_kind == "next_lap_focus":
        drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
        stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
        should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
        if drive_through or stop_go or should_serve:
            detail = "接下来几圈先把处罚处理优先级放高，别错过下一次合适的处理窗口。"
        elif primary_message is not None and primary_message.code == "DEFEND_WINDOW":
            detail = "接下来几圈先守住后车，重点看后车 DRS 线和出弯稳定性。"
        elif primary_message is not None and primary_message.code == "ATTACK_WINDOW":
            detail = "接下来几圈先盯前车差距和 DRS 兑现，避免在资源不足时硬上。"
        elif state.player.fuel_laps_remaining <= 3.0:
            detail = f"接下来几圈先控燃油，当前预计只剩 {state.player.fuel_laps_remaining:.1f} 圈。"
        elif state.player.tyre.wear_pct >= 65.0:
            detail = f"接下来几圈先保护轮胎，当前磨损已经到 {state.player.tyre.wear_pct:.1f}%。"
        elif state.safety_car != "NONE":
            detail = f"接下来几圈重点看赛道管制变化，当前赛道处于 {state.safety_car} 阶段。"
        else:
            detail = "接下来几圈先稳住节奏，优先管理前后车差距、ERS 和轮胎消耗。"
        return (render_summary_answer(detail), "QUERY_NEXT_LAP_FOCUS")

    if query_kind == "tyre_wear_outlook":
        detail = _tyre_wear_outlook(state, primary_message)
        return (render_summary_answer(detail), "QUERY_TYRE_WEAR_OUTLOOK")

    if query_kind == "risk_severity_followup":
        drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
        stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
        should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
        fuel = state.player.fuel_laps_remaining
        tyre_wear = state.player.tyre.wear_pct
        gap_behind = state.player.gap_behind_s
        if drive_through > 0:
            detail = "这个风险很高，因为 drive-through 不能拖延处理。"
        elif stop_go > 0 or should_serve:
            detail = "这个风险偏高，因为下一次进站必须专门处理 stop-go。"
        elif gap_behind is not None and gap_behind <= 1.0:
            detail = f"这个风险偏高，后车已经压到 {gap_behind:.3f} 秒内。"
        elif fuel <= 3.0:
            detail = f"这个风险偏高，燃油只剩 {fuel:.1f} 圈。"
        elif tyre_wear >= 65.0:
            detail = f"这个风险中高，轮胎磨损已经到 {tyre_wear:.1f}%。"
        else:
            detail = "这个风险目前是中等，还没有压到必须立刻处理。"
        return (render_summary_answer(detail), "QUERY_RISK_SEVERITY")

    if query_kind == "risk_escalation_timing":
        drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
        stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
        should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
        gap_behind = state.player.gap_behind_s
        fuel = state.player.fuel_laps_remaining
        tyre_wear = state.player.tyre.wear_pct
        if drive_through > 0:
            detail = "这个风险已经是立即要处理的级别，当前就不能再继续拖。"
        elif stop_go > 0 or should_serve:
            detail = "这个风险已经偏高，最晚到下一次进站窗口就会变成强约束。"
        elif gap_behind is not None and gap_behind <= 1.0:
            detail = f"这个风险已经在高位，下一段到下一圈内就可能继续升级，当前后车只有 {gap_behind:.3f} 秒。"
        elif fuel <= 3.0:
            detail = f"这个风险已经很近了，接下来一两圈内就会继续恶化，当前燃油只剩 {fuel:.1f} 圈。"
        elif tyre_wear >= 65.0:
            detail = f"这个风险会在接下来两三圈继续放大，当前轮胎磨损已经到 {tyre_wear:.1f}%。"
        else:
            detail = "这个风险短期不会立刻跳变，当前更像需要持续观察而不是马上处理。"
        return (render_summary_answer(detail), "QUERY_RISK_ESCALATION_TIMING")

    if query_kind == "rear_pressure_relief_outlook":
        gap_behind = state.player.gap_behind_s
        if gap_behind is not None and gap_behind <= 1.0:
            detail = f"后车压力不太会自己消下去，当前差距只有 {gap_behind:.3f} 秒，还是要主动把防守窗口管住。"
        elif gap_behind is not None and gap_behind <= 1.4:
            detail = f"后车压力可能小幅波动，但短期未必会自己解除，当前差距 {gap_behind:.3f} 秒。"
        else:
            detail = "后车压力有机会自己回落，因为它还没压进最强直接窗口。"
        return (render_summary_answer(detail), "QUERY_REAR_PRESSURE_RELIEF_OUTLOOK")

    if query_kind == "pit_delay_consequence":
        drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
        stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
        should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
        if drive_through > 0:
            detail = "如果继续不进站，这条 drive-through 会继续挂着，处罚风险会持续存在。"
        elif stop_go > 0 or should_serve:
            detail = "如果继续不进站，这条 stop-go 会继续留到后面，后续进站窗口会更被动。"
        elif state.player.tyre.wear_pct >= 65.0:
            detail = f"如果继续不进站，轮胎压力会继续上升，当前磨损已经到 {state.player.tyre.wear_pct:.1f}%。"
        else:
            detail = "如果继续不进站，短期不会立刻出硬性处罚问题，但会继续消耗轮胎和策略弹性。"
        return (render_summary_answer(detail), "QUERY_PIT_DELAY_CONSEQUENCE")

    if query_kind == "pit_one_lap_delay_consequence":
        drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
        stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
        should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
        tyre_wear = state.player.tyre.wear_pct
        if drive_through > 0:
            detail = "如果只再等一圈，这条 drive-through 仍然会继续挂着，风险不会自己消失。"
        elif stop_go > 0 or should_serve:
            detail = "如果只再等一圈，下一次进站窗口会更紧，stop-go 处理空间会变差。"
        elif tyre_wear >= 65.0:
            detail = f"如果再等一圈进站，轮胎压力会继续往上走，当前磨损已经到 {tyre_wear:.1f}%。"
        else:
            detail = "如果只等一圈，短期代价还可控，但会少一层策略缓冲。"
        return (render_summary_answer(detail), "QUERY_PIT_ONE_LAP_DELAY_CONSEQUENCE")

    if query_kind == "tyre_management_advice":
        tyre_wear = state.player.tyre.wear_pct
        if tyre_wear >= 65.0:
            detail = f"现在要开始保胎，当前磨损已经到 {tyre_wear:.1f}%。"
        elif primary_message is not None and primary_message.code == "DEFEND_WINDOW":
            detail = "现在先以防守优先，不建议为了保胎牺牲掉直接防守窗口。"
        else:
            detail = f"现在不用明显保胎，当前磨损 {tyre_wear:.1f}%，更适合先稳住正常节奏。"
        return (render_summary_answer(detail), "QUERY_TYRE_MANAGEMENT_ADVICE")

    if query_kind == "fuel_management_advice":
        fuel = state.player.fuel_laps_remaining
        if fuel <= 3.0:
            detail = f"现在需要开始省油，当前预计只剩 {fuel:.1f} 圈。"
        elif fuel <= 6.0:
            detail = f"现在建议轻度省油，当前预计剩余 {fuel:.1f} 圈。"
        else:
            detail = f"现在不用明显省油，当前预计还能跑 {fuel:.1f} 圈。"
        return (render_summary_answer(detail), "QUERY_FUEL_MANAGEMENT_ADVICE")

    if query_kind == "defend_outcome_projection":
        gap_behind = state.player.gap_behind_s
        if primary_message is not None and primary_message.code == "DEFEND_WINDOW":
            detail = "如果现在先守住，最直接的收益是先保住位置，但接下来还要继续顶住后车 DRS 线和出弯压力。"
        elif gap_behind is not None and gap_behind <= 1.1:
            detail = f"如果现在先守住，短期最可能是保住当前位置，但后车 {gap_behind:.3f} 秒的压力还会继续存在。"
        else:
            detail = "如果现在主动转成防守，短期收益不会特别大，因为后车还没把直接窗口压到最强。"
        return (render_summary_answer(detail), "QUERY_DEFEND_OUTCOME_PROJECTION")

    if query_kind == "attack_outcome_projection":
        gap_ahead = state.player.gap_ahead_s
        gap_behind = state.player.gap_behind_s
        if gap_ahead is not None and gap_ahead <= 1.0 and state.player.drs_available:
            detail = f"如果现在进攻，短期有机会把前车压进直接对抗，但要避免把后车 {gap_behind:.3f} 秒的压力一起放大。"
        elif gap_ahead is not None and gap_ahead <= 1.2:
            detail = f"如果现在进攻，能形成施压，但兑现条件还不完整，当前前车差距 {gap_ahead:.3f} 秒。"
        else:
            detail = "如果现在主动进攻，短期收益有限，更像是在提前消耗轮胎和资源。"
        return (render_summary_answer(detail), "QUERY_ATTACK_OUTCOME_PROJECTION")

    if query_kind == "why_defend":
        gap = state.player.gap_behind_s
        if primary_message is not None and primary_message.code == "DEFEND_WINDOW":
            reason = primary_message.detail
        elif gap is not None and gap <= 1.0:
            reason = f"后车已经压到 {gap:.3f} 秒内，属于直接防守窗口。"
        elif gap is not None:
            reason = f"后车差距是 {gap:.3f} 秒，系统更看重后车压力而不是进攻机会。"
        else:
            reason = "后车官方时差不稳定，系统暂时按保守防守口径处理。"
        return (
            render_conclusion_with_reason("当前偏向防守", reason),
            "QUERY_WHY_DEFEND",
        )

    if query_kind == "why_not_attack":
        gap = state.player.gap_ahead_s
        drs = "有" if state.player.drs_available else "没有"
        if gap is None:
            reason = "前车时差缺失，系统没有拿到可靠的进攻窗口依据。"
        elif gap > 1.0:
            reason = f"前车差距还有 {gap:.3f} 秒，没进直接进攻窗口。"
        elif not state.player.drs_available:
            reason = f"前车差距 {gap:.3f} 秒，但当前没有 DRS，加速兑现条件不够。"
        else:
            reason = f"前车差距 {gap:.3f} 秒且 DRS={drs}，但当前综合条件还不足以让进攻优先于稳定性。"
        return (
            render_conclusion_with_reason(
                "现在没有给出进攻窗口",
                reason,
                connector="因为",
            ),
            "QUERY_WHY_NOT_ATTACK",
        )

    if query_kind == "why_not_pit":
        pit_status = str(state.raw.get("pit_status") or "NONE")
        drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
        stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
        serve_pen = bool(state.raw.get("pit_stop_should_serve_pen", False))
        tyre = state.player.tyre
        if pit_status in {"PITTING", "IN_PIT_AREA"}:
            reason = f"当前已经在进站流程里，状态是 {pit_status}。"
        elif drive_through or stop_go or serve_pen:
            reason = (
                f"当前还没有处于进站流程，但存在待处理处罚：穿越维修区 {drive_through} 条，"
                f"stop-go {stop_go} 条。"
            )
        elif state.safety_car != "NONE":
            reason = f"当前赛道处于 {state.safety_car} 阶段，但当前快照没有 active pit 状态。"
        else:
            reason = (
                f"当前没有 active pit 状态，轮胎磨损 {tyre.wear_pct:.1f}% ，"
                "也没有待执行进站处罚。更长周期的进站决策解释当前还未接入。"
            )
        return (
            render_conclusion_with_reason(
                "现在没有进入进站流程",
                reason,
                connector="因为",
            ),
            "QUERY_WHY_NOT_PIT",
        )

    if query_kind == "why_current_strategy":
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

    if query_kind == "open_fallback":
        query_text = str((schema_metadata or {}).get("query_text") or "").strip()
        semantic_metadata = (schema_metadata or {}).get("semantic_metadata") or {}
        domain_hint = str(semantic_metadata.get("domain_hint") or "general")
        detail = render_open_fallback_detail(domain_hint)
        prefix = f"关于“{query_text}”，" if query_text else ""
        return (render_summary_answer(f"{prefix}{detail}"), "QUERY_OPEN_FALLBACK")

    return (
        render_not_supported_answer("当前查询类型还未接入模板回答。"),
        "QUERY_SNAPSHOT_STATUS",
    )
