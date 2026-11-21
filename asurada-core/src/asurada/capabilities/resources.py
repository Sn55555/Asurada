from __future__ import annotations

from ..response_composer import (
    Any,
    SessionState,
    StrategyMessage,
    _tyre_wear_outlook,
    assess_domain,
    assess_fuel,
    render_summary_answer,
    render_verdict_with_numbers,
)


def _handle_fuel_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    return (render_summary_answer(assess_fuel(state).describe()), "QUERY_FUEL_STATUS")



def _handle_tyre_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    tyre = state.player.tyre
    if assess_domain(state).labels.tyre_state == "unavailable":
        return (render_summary_answer("轮胎磨损数据不可用，暂不能判断轮胎状态。"), "QUERY_TYRE_STATUS")
    if assess_domain(state).labels.tyre_state == "box_now":
        verdict = "轮胎磨损已经偏高。"
    elif assess_domain(state).labels.tyre_state == "manage":
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



def _handle_ers_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    ers_pct = state.player.ers_pct
    if assess_domain(state).labels.ers_state == "unavailable":
        return (render_summary_answer("ERS 数据不可用，暂不能判断剩余电量。"), "QUERY_ERS_STATUS")
    if assess_domain(state).labels.ers_state == "low":
        verdict = "ERS 已经偏低。"
    else:
        verdict = "ERS 余量暂不紧张。"
    return (
        render_verdict_with_numbers(verdict, f"当前剩余 {ers_pct:.1f}%。"),
        "QUERY_ERS_STATUS",
    )



def _handle_tyre_wear_outlook(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    detail = _tyre_wear_outlook(state, primary_message)
    return (render_summary_answer(detail), "QUERY_TYRE_WEAR_OUTLOOK")



def _handle_tyre_management_advice(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    tyre_wear = state.player.tyre.wear_pct
    if assess_domain(state).labels.tyre_state == "unavailable":
        return (render_summary_answer("轮胎磨损数据不可用，暂不能给出保胎判断。"), "QUERY_TYRE_MANAGEMENT_ADVICE")
    if assess_domain(state).labels.tyre_state in {"manage", "box_now"}:
        detail = f"现在要开始保胎，当前磨损已经到 {tyre_wear:.1f}%。"
    elif primary_message is not None and primary_message.code == "DEFEND_WINDOW":
        detail = "现在先以防守优先，不建议为了保胎牺牲掉直接防守窗口。"
    else:
        detail = f"现在不用明显保胎，当前磨损 {tyre_wear:.1f}%，更适合先稳住正常节奏。"
    return (render_summary_answer(detail), "QUERY_TYRE_MANAGEMENT_ADVICE")



def _handle_fuel_management_advice(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    return (render_summary_answer(assess_fuel(state).describe()), "QUERY_FUEL_MANAGEMENT_ADVICE")
