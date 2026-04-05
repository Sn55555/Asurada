from __future__ import annotations

from typing import Any

from .models import SessionState, StrategyMessage


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
            f"{verdict} 当前预计还能跑 {fuel:.1f} 圈，总圈数 {state.total_laps} 圈。",
            "QUERY_FUEL_STATUS",
        )

    if query_kind == "rear_gap":
        if state.player.gap_behind_s is None:
            return ("后车时差当前缺失，不能可靠判断防守压力。", "QUERY_REAR_GAP")
        rear_name = state.rivals[0].name if state.rivals else "后车"
        gap = state.player.gap_behind_s
        if gap <= 1.0:
            verdict = "后车已经进直接防守窗口。"
        elif gap <= 1.5:
            verdict = "后车正在逼近，需要开始准备防守。"
        else:
            verdict = "后车暂时还没进直接防守窗口。"
        return (
            f"{verdict} 后车 {rear_name} 落后 {gap:.3f} 秒。",
            "QUERY_REAR_GAP",
        )

    if query_kind == "tyre_status":
        tyre = state.player.tyre
        if tyre.wear_pct >= 70.0:
            verdict = "轮胎磨损已经偏高。"
        elif tyre.wear_pct >= 40.0:
            verdict = "轮胎处在中段磨损。"
        else:
            verdict = "轮胎状态还比较健康。"
        return (
            f"{verdict} 当前 {tyre.compound}，磨损 {tyre.wear_pct:.1f}%，胎龄 {tyre.age_laps} 圈。",
            "QUERY_TYRE_STATUS",
        )

    if query_kind == "weather_status":
        safety_car = "无赛道管制" if state.safety_car == "NONE" else f"{state.safety_car} 阶段"
        return (
            f"当前天气是 {state.weather}，赛道状态为 {safety_car}。",
            "QUERY_WEATHER_STATUS",
        )

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
        return (detail, "QUERY_PENALTY_STATUS")

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
        return (detail, "QUERY_PIT_STATUS")

    if query_kind == "current_strategy":
        if primary_message is None:
            return ("当前没有高优先级主策略。", "QUERY_CURRENT_STRATEGY")
        return (
            f"当前主策略是 {primary_message.title}。原因是 {primary_message.detail}",
            "QUERY_CURRENT_STRATEGY",
        )

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
        return (f"当前偏向防守，主要因为 {reason}", "QUERY_WHY_DEFEND")

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
        return (f"现在没有给出进攻窗口，因为 {reason}", "QUERY_WHY_NOT_ATTACK")

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
        return (f"现在没有进入进站流程，因为 {reason}", "QUERY_WHY_NOT_PIT")

    if query_kind == "why_current_strategy":
        if primary_message is None:
            return ("当前没有高优先级主策略，所以系统没有额外解释项。", "QUERY_WHY_CURRENT_STRATEGY")
        return (
            f"当前把 {primary_message.title} 放在首位，因为 {primary_message.detail}",
            "QUERY_WHY_CURRENT_STRATEGY",
        )

    if query_kind == "open_fallback":
        query_text = str((schema_metadata or {}).get("query_text") or "").strip()
        semantic_metadata = (schema_metadata or {}).get("semantic_metadata") or {}
        domain_hint = str(semantic_metadata.get("domain_hint") or "general")
        if domain_hint == "pit":
            detail = "这类进站开放式问题我还不能可靠解释长周期决策，但我现在能回答当前进站状态和待执行处罚。"
        elif domain_hint == "weather":
            detail = "这类天气开放式问题我还不能做完整推演，但我现在能回答当前天气和赛道管制状态。"
        elif domain_hint == "penalty":
            detail = "这类处罚开放式问题我还不能解释成因，但我现在能回答当前警告和待执行处罚状态。"
        else:
            detail = "这类开放式问题我还没接完整。当前可以直接回答燃油、后车、轮胎、当前策略、进站状态、天气和处罚状态。"
        prefix = f"关于“{query_text}”，" if query_text else ""
        return (f"{prefix}{detail}", "QUERY_OPEN_FALLBACK")

    return ("当前查询类型还未接入模板回答。", "QUERY_SNAPSHOT_STATUS")
