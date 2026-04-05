from __future__ import annotations

from .models import SessionState, StrategyMessage


def compose_structured_query_response(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
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

    if query_kind == "why_current_strategy":
        if primary_message is None:
            return ("当前没有高优先级主策略，所以系统没有额外解释项。", "QUERY_WHY_CURRENT_STRATEGY")
        return (
            f"当前把 {primary_message.title} 放在首位，因为 {primary_message.detail}",
            "QUERY_WHY_CURRENT_STRATEGY",
        )

    return ("当前查询类型还未接入模板回答。", "QUERY_SNAPSHOT_STATUS")
