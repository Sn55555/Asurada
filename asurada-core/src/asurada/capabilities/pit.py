from __future__ import annotations

from ..race_control import race_control_active
from ..pit_feedback import driver_profile_id
from ..personality_pit_advice import tyre_observation

from ..response_composer import (
    Any,
    SessionState,
    StrategyMessage,
    assess_domain,
    render_conclusion_with_reason,
    render_summary_answer,
)


def _handle_penalty_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
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



def _handle_pit_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
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



def _handle_pit_penalty_plan(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
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



def _handle_penalty_handling_strategy(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
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



def _handle_pit_delay_consequence(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
    stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
    should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
    if drive_through > 0:
        detail = "如果继续不进站，这条 drive-through 会继续挂着，处罚风险会持续存在。"
    elif stop_go > 0 or should_serve:
        detail = "如果继续不进站，这条 stop-go 会继续留到后面，后续进站窗口会更被动。"
    elif assess_domain(state).labels.tyre_state in {"manage", "box_now"}:
        detail = f"如果继续不进站，轮胎压力会继续上升，当前磨损已经到 {state.player.tyre.wear_pct:.1f}%。"
    else:
        detail = "如果继续不进站，短期不会立刻出硬性处罚问题，但会继续消耗轮胎和策略弹性。"
    return (render_summary_answer(detail), "QUERY_PIT_DELAY_CONSEQUENCE")



def _handle_pit_one_lap_delay_consequence(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    drive_through = int(state.raw.get("num_unserved_drive_through_pens", 0) or 0)
    stop_go = int(state.raw.get("num_unserved_stop_go_pens", 0) or 0)
    should_serve = bool(state.raw.get("pit_stop_should_serve_pen", False))
    tyre_wear = state.player.tyre.wear_pct
    if drive_through > 0:
        detail = "如果只再等一圈，这条 drive-through 仍然会继续挂着，风险不会自己消失。"
    elif stop_go > 0 or should_serve:
        detail = "如果只再等一圈，下一次进站窗口会更紧，stop-go 处理空间会变差。"
    elif assess_domain(state).labels.tyre_state in {"manage", "box_now"}:
        detail = f"如果再等一圈进站，轮胎压力会继续往上走，当前磨损已经到 {tyre_wear:.1f}%。"
    else:
        detail = "如果只等一圈，短期代价还可控，但会少一层策略缓冲。"
    return (render_summary_answer(detail), "QUERY_PIT_ONE_LAP_DELAY_CONSEQUENCE")



def _handle_why_not_pit(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    target = ((schema_metadata or {}).get("semantic_metadata") or {}).get("strategy_follow_up_target") or {}
    if target.get("expired"):
        return ("刚才那条建议已过期，你可以直接问现在要不要进站。", "QUERY_WHY_NOT_PIT")
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
    elif race_control_active(state.safety_car):
        reason = f"当前赛道处于 {state.safety_car} 阶段，但当前快照没有 active pit 状态。"
    else:
        sample = tyre_observation(state)
        if sample is not None:
            if sample.verdict == "box_now":
                return ("轮胎磨损达到进站评估条件。"
                        f"当前磨损 {tyre.wear_pct:.0f}%。进站时机还要看交通。"
                        "如果有效磨损读数回落，我会重算。", "QUERY_WHY_NOT_PIT")
            if sample.verdict == "manage":
                return ("先管理轮胎，暂不建议立即进站。"
                        f"当前磨损 {tyre.wear_pct:.0f}%。再升到进站条件时我会重算。", "QUERY_WHY_NOT_PIT")
            if sample.verdict == "stable":
                return (f"当前磨损 {tyre.wear_pct:.0f}%，先继续比赛。磨损风险上来再评估进站。",
                        "QUERY_WHY_NOT_PIT")
        reason = (
            "目前没有确认处于进站流程，且缺少一致的四轮磨损数据，无法判断是否该进站。"
        )
    return (
        render_conclusion_with_reason(
            "现在没有进入进站流程",
            reason,
            connector="因为",
        ),
        "QUERY_WHY_NOT_PIT",
    )


def explain_pit_with_cooperation(state: SessionState) -> tuple[str, str | None] | None:
    """Trim a routine reason only when the current and prior situations are attributable."""
    hint = state.personality
    if (hint is None or not hint.matches(state) or not hint.low_load
            or state.raw.get("pit_stop_should_serve_pen")
            or state.raw.get("num_unserved_drive_through_pens")
            or state.raw.get("num_unserved_stop_go_pens")):
        return None
    sample = tyre_observation(state)
    if sample is None or sample.pit or sample.verdict != "stable":
        return None
    advice = f"磨损 {state.player.tyre.wear_pct:.0f}%，正常，先继续。"
    prior = hint.pit_cooperation
    if prior and prior["driver_id"] == driver_profile_id() and prior["race_id"] != state.session_uid:
        return f"{advice} 上次换胎后磨损风险解除了。这次磨损升高再评估。", prior["recommendation_id"]
    return (
        f"{advice} 我会继续对照四轮磨损。要是连续读数显示轮胎风险升高，再重新评估进站。",
        None,
    )

