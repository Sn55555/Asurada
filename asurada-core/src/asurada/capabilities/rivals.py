from __future__ import annotations

from ..attack_opportunity import front_target
from ..response_composer import (
    Any,
    SessionState,
    StrategyMessage,
    _attack_method_context,
    _dynamics_clause,
    _front_rival,
    _format_gap,
    _front_rival_attack_reason,
    _gap_quality_hint,
    _position_trend_snapshot,
    _rear_rival,
    _rear_rival_risk_reason,
    _rival_context_clause,
    _rival_pressure_hint,
    assess_domain,
    assess_fuel,
    attack_method_label,
    render_conclusion_with_reason,
    render_not_supported_answer,
    render_summary_answer,
    render_unavailable_answer,
    render_verdict_with_numbers,
)


def _handle_front_gap(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    domain = assess_domain(state)
    front_rival = _front_rival(state)
    if domain.labels.attack_state == "unavailable":
        return (
            render_unavailable_answer("前车时差", "当前不能可靠判断进攻距离。"),
            "QUERY_FRONT_GAP",
        )
    front_name = front_rival.name if front_rival is not None else "前车"
    gap = state.player.gap_ahead_s
    if domain.labels.attack_state == "available":
        verdict = "前车已经进直接进攻观察窗口。"
    elif gap <= domain.thresholds["rival_gap_attack"]:
        verdict = "前车正在进入可施压距离。"
    else:
        verdict = "前车还没进直接进攻窗口。"
    drs_hint = "当前有 DRS。" if state.player.drs_available else "当前没有 DRS。"
    gap_quality = _gap_quality_hint(front_rival, "ahead")
    rival_pressure = _rival_pressure_hint(front_rival)
    return (
        render_verdict_with_numbers(
            verdict,
            f"前车 {front_name} 领先 {gap:.3f} 秒。",
            drs_hint,
            gap_quality,
            rival_pressure,
        ),
        "QUERY_FRONT_GAP",
    )



def _handle_front_rival_drs_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    front_rival = _front_rival(state)
    if front_rival is None:
        return (
            render_not_supported_answer("当前没有可靠前车对象，不能判断前车 DRS 状态。"),
            "QUERY_FRONT_RIVAL_DRS_STATUS",
        )
    if front_rival.drs_available:
        detail = f"前车 {front_rival.name} 当前有 DRS。"
    else:
        detail = f"前车 {front_rival.name} 当前没有 DRS。"
    if state.player.gap_ahead_s is not None:
        detail += f" 你与前车差距 {state.player.gap_ahead_s:.3f} 秒。"
    gap_quality = _gap_quality_hint(front_rival, "ahead")
    if gap_quality:
        detail += f" {gap_quality}"
    return (render_summary_answer(detail), "QUERY_FRONT_RIVAL_DRS_STATUS")



def _handle_rear_gap(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    domain = assess_domain(state)
    rear_rival = _rear_rival(state)
    if domain.labels.defend_state == "unavailable":
        return (
            render_unavailable_answer("后车时差", "当前不能可靠判断防守压力。"),
            "QUERY_REAR_GAP",
        )
    rear_name = rear_rival.name if rear_rival is not None else "后车"
    gap = state.player.gap_behind_s
    if domain.labels.defend_state == "urgent":
        verdict = "后车已经进直接防守窗口。"
    else:
        verdict = "后车暂时还没进直接防守窗口。"
    gap_quality = _gap_quality_hint(rear_rival, "behind")
    rival_pressure = _rival_pressure_hint(rear_rival)
    return (
        render_verdict_with_numbers(
            verdict,
            f"后车 {rear_name} 落后 {gap:.3f} 秒。",
            gap_quality,
            rival_pressure,
        ),
        "QUERY_REAR_GAP",
    )



def _handle_rear_rival_drs_status(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    rear_rival = _rear_rival(state)
    if state.player.gap_behind_s is None:
        return (
            render_unavailable_answer("后车时差", "当前不能可靠判断后车是否进 DRS 线。"),
            "QUERY_REAR_RIVAL_DRS_STATUS",
        )
    rear_name = rear_rival.name if rear_rival is not None else "后车"
    gap = state.player.gap_behind_s
    if gap <= 1.0:
        detail = f"后车 {rear_name} 已经进 DRS 线，当前差距 {gap:.3f} 秒。"
    else:
        detail = f"后车 {rear_name} 还没进 DRS 线，当前差距 {gap:.3f} 秒。"
    gap_quality = _gap_quality_hint(rear_rival, "behind")
    if gap_quality:
        detail += f" {gap_quality}"
    return (render_summary_answer(detail), "QUERY_REAR_RIVAL_DRS_STATUS")



def _handle_attack_or_defend_summary(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    gap_ahead = state.player.gap_ahead_s
    gap_behind = state.player.gap_behind_s
    front_rival = _front_rival(state)
    rear_rival = _rear_rival(state)
    if primary_message is not None and primary_message.code == "DEFEND_WINDOW":
        detail = f"当前更偏向防守，因为 {primary_message.detail}"
    elif primary_message is not None and primary_message.code == "ATTACK_WINDOW":
        detail = f"当前更偏向进攻，因为 {primary_message.detail}"
    elif assess_domain(state).labels.defend_state == "urgent":
        detail = f"当前更偏向防守，后车差距只有 {gap_behind:.3f} 秒。"
    elif assess_domain(state).labels.attack_state == "available":
        detail = f"当前更偏向进攻，前车差距 {gap_ahead:.3f} 秒且 DRS 可用。"
    else:
        detail = "当前更偏向中性管理，前后车都还没把攻防窗口压到最强。"
    return (
        render_summary_answer(
            detail,
            _rival_context_clause(front_rival, role_label="前车"),
            _rival_context_clause(rear_rival, role_label="后车"),
        ),
        "QUERY_ATTACK_OR_DEFEND_SUMMARY",
    )



def _handle_attack_defend_tradeoff(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    gap_ahead = state.player.gap_ahead_s
    gap_behind = state.player.gap_behind_s
    front_rival = _front_rival(state)
    rear_rival = _rear_rival(state)
    rear_reason = _rear_rival_risk_reason(rear_rival, gap_behind, defend_state=assess_domain(state).labels.defend_state)
    front_reason = _front_rival_attack_reason(front_rival, gap_ahead, attack_state=assess_domain(state).labels.attack_state)
    fuel = state.player.fuel_laps_remaining
    tyre_wear = state.player.tyre.wear_pct
    if rear_reason and "带着 DRS" in rear_reason:
        detail = f"当前防守代价更低，因为{rear_reason} 贸然进攻更容易把位置暴露出去。"
    elif assess_domain(state).labels.defend_state == "urgent":
        detail = f"当前防守代价更低，因为后车已经压到 {gap_behind:.3f} 秒内，贸然进攻更容易把位置暴露出去。"
    elif front_reason and "等待窗口自然变化" in front_reason:
        detail = f"当前进攻代价不低，因为{front_reason}"
    elif assess_domain(state).labels.attack_state == "available" and assess_domain(state).labels.defend_state == "clear":
        detail = f"当前进攻代价更低，因为前车只有 {gap_ahead:.3f} 秒且 DRS 可用，后车压力相对可控。"
    elif assess_fuel(state).verdict == "critical" or assess_domain(state).labels.tyre_state in {"manage", "box_now"}:
        detail = "当前两边代价都不低，但更大的成本来自资源消耗，优先稳住资源比强攻或强守更划算。"
    else:
        detail = "当前攻守代价接近，更适合跟着下一段前后车变化再决定。"
    return (render_summary_answer(detail), "QUERY_ATTACK_DEFEND_TRADEOFF")



def _handle_rear_pressure_relief_outlook(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    gap_behind = state.player.gap_behind_s
    rear_rival = _rear_rival(state)
    if rear_rival is not None and getattr(rear_rival, "pit_status", None) in {"PITTING", "IN_PIT_AREA"}:
        detail = f"后车压力很可能自己回落，因为 {rear_rival.name} 已经进站。"
    elif rear_rival is not None and isinstance(getattr(rear_rival, "engine_damage_pct", None), int) and rear_rival.engine_damage_pct >= 35:
        detail = f"后车压力有机会自己回落，因为 {rear_rival.name} 的发动机损伤已经到 {rear_rival.engine_damage_pct}%。"
    elif assess_domain(state).labels.defend_state == "urgent":
        detail = f"后车压力不太会自己消下去，当前差距只有 {gap_behind:.3f} 秒，还是要主动把防守窗口管住。"
    elif assess_domain(state).labels.defend_state == "unavailable":
        detail = "后车时差数据不可用，暂不能预测防守压力是否会回落。"
    else:
        detail = "后车尚未进入当前直接防守窗口，后续压力是否回落需要结合连续时差变化判断。"
    return (render_summary_answer(detail), "QUERY_REAR_PRESSURE_RELIEF_OUTLOOK")



def _handle_defend_outcome_projection(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    gap_behind = state.player.gap_behind_s
    rear_rival = _rear_rival(state)
    if rear_rival is not None and getattr(rear_rival, "pit_status", None) in {"PITTING", "IN_PIT_AREA"}:
        detail = f"如果现在先守住，短期最直接的收益可能有限，因为 {rear_rival.name} 已经在进站流程里。"
    elif primary_message is not None and primary_message.code == "DEFEND_WINDOW":
        detail = "如果现在先守住，最直接的收益是先保住位置，但接下来还要继续顶住后车 DRS 线和出弯压力。"
    elif assess_domain(state).labels.defend_state == "urgent":
        detail = f"如果现在先守住，短期最可能是保住当前位置，但后车 {gap_behind:.3f} 秒的压力还会继续存在。"
    elif assess_domain(state).labels.defend_state == "unavailable":
        detail = "后车时差数据不可用，暂不能预测主动防守的收益。"
    else:
        detail = "如果现在主动转成防守，短期收益不会特别大，因为后车还没把直接窗口压到最强。"
    return (render_summary_answer(detail), "QUERY_DEFEND_OUTCOME_PROJECTION")



def _handle_attack_outcome_projection(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    domain = assess_domain(state)
    gap_ahead = state.player.gap_ahead_s
    gap_behind = state.player.gap_behind_s
    front_rival = _front_rival(state)
    corner_class, setup_method, commit_method = _attack_method_context(state)
    method_bits = []
    if setup_method != "none":
        method_bits.append(f"当前更像 {attack_method_label(setup_method)} 的铺垫")
    if commit_method != "none":
        method_bits.append(f"兑现方式更像 {attack_method_label(commit_method)}")
    if corner_class != "general":
        method_bits.append(f"弯型属于 {corner_class}")
    method_clause = "；".join(method_bits)
    if front_rival is not None and getattr(front_rival, "pit_status", None) in {"PITTING", "IN_PIT_AREA"}:
        detail = f"如果现在进攻，短期收益会受限，因为前车 {front_rival.name} 已经在进站流程里，局面可能自己变化。"
    elif domain.labels.attack_state == "available":
        detail = f"如果现在进攻，短期有机会把前车压进直接对抗，但要避免把后车时差 {_format_gap(gap_behind if domain.labels.defend_state != 'unavailable' else None)} 对应的压力一起放大。"
    elif domain.labels.attack_state != "unavailable" and gap_ahead <= domain.thresholds["rival_gap_attack"]:
        detail = f"如果现在进攻，能形成施压，但兑现条件还不完整，当前前车差距 {gap_ahead:.3f} 秒。"
    elif domain.labels.attack_state == "unavailable":
        detail = "前车时差数据不可用，暂不能预测主动进攻的收益。"
    else:
        detail = "如果现在主动进攻，短期收益有限，更像是在提前消耗轮胎和资源。"
    if method_clause:
        detail = f"{detail} {method_clause}。"
    return (render_summary_answer(detail), "QUERY_ATTACK_OUTCOME_PROJECTION")



def _handle_why_defend(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    labels = assess_domain(state).labels
    gap = state.player.gap_behind_s
    rear_rival = _rear_rival(state)
    position_trend = _position_trend_snapshot(state)
    dynamics_clause = _dynamics_clause(state)
    if rear_rival is not None and getattr(rear_rival, "drs_available", False) and labels.defend_state == "urgent":
        reason = f"后车 {rear_rival.name} 已经带着 DRS 压到 {gap:.3f} 秒内，属于直接防守窗口。"
    elif primary_message is not None and primary_message.code == "DEFEND_WINDOW":
        reason = primary_message.detail
    elif dynamics_clause:
        reason = f"{dynamics_clause} 当前先把车身姿态稳定住，比主动进攻更重要。"
    elif position_trend is not None and int(position_trend["net_gain"]) < 0:
        reason = f"最近几圈已经从 P{position_trend['start_position']} 回落到 P{position_trend['end_position']}，当前更需要先止血。"
    elif labels.defend_state == "urgent":
        reason = f"后车已经压到 {gap:.3f} 秒内，属于直接防守窗口。"
    elif labels.defend_state == "clear":
        reason = f"后车差距是 {gap:.3f} 秒，尚未触发当前配置的直接防守窗口。"
    else:
        reason = "后车时差数据不可用，暂不能据此确认防守压力。"
    return (
        render_conclusion_with_reason(
            "当前偏向防守" if primary_message is not None and primary_message.code == "DEFEND_WINDOW"
            else "后车处于直接防守窗口" if labels.defend_state == "urgent"
            else "当前未确认防守决策", reason),
        "QUERY_WHY_DEFEND",
    )



def _handle_why_not_attack(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
    schema_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    domain = assess_domain(state)
    context = (schema_metadata or {}).get("semantic_metadata", {})
    target = context.get("strategy_follow_up_target") or {}
    current_front = front_target(state)
    if target.get("ambiguous"):
        return "你问的是前车进攻，还是进站？", "QUERY_WHY_NOT_ATTACK"
    if target.get("expired"):
        return "刚才的进攻判断已过期。要重新看现在的前车吗？", "QUERY_WHY_NOT_ATTACK"
    expected_front = target.get("front_car_index")
    if expected_front is not None and (current_front is None or current_front.car_index != expected_front):
        return "刚才的前车已不是当前目标。要重新看现在的前车吗？", "QUERY_WHY_NOT_ATTACK"
    if target.get("follow_up") and expected_front is None:
        return "前车身份没有确认。等前车和时差都能核对，再评估。", "QUERY_WHY_NOT_ATTACK"
    if primary_message is not None and primary_message.code == "ATTACK_WINDOW":
        return (render_conclusion_with_reason("当前已经给出进攻窗口", primary_message.detail), "QUERY_WHY_NOT_ATTACK")
    gap = state.player.gap_ahead_s
    drs = "有" if state.player.drs_available else "没有"
    front_rival = _front_rival(state)
    position_trend = _position_trend_snapshot(state)
    dynamics_clause = _dynamics_clause(state)
    _corner_class, setup_method, commit_method = _attack_method_context(state)
    method_reason = None
    if setup_method != "none" and commit_method == "none":
        method_reason = f"当前更像 {attack_method_label(setup_method)} 的铺垫，还没到直接兑现窗口。"
    elif commit_method != "none":
        method_reason = f"当前最像的兑现方式是 {attack_method_label(commit_method)}，但执行条件还没完整。"
    if front_rival is not None and getattr(front_rival, "pit_status", None) in {"PITTING", "IN_PIT_AREA"}:
        reason = f"前车 {front_rival.name} 已经在进站流程里，当前更适合先观察窗口自己变化。"
    elif domain.labels.race_state == "controlled":
        reason = "赛道正在管制。先按管制行驶，绿旗后再评估。"
    elif dynamics_clause:
        reason = f"{dynamics_clause} 现在先把车稳住，比强行进攻更划算。"
    elif position_trend is not None and int(position_trend["net_gain"]) < 0:
        reason = f"最近几圈位置还在下滑，已经从 P{position_trend['start_position']} 掉到 P{position_trend['end_position']}，当前先稳住更重要。"
    elif domain.labels.defend_state == "urgent":
        reason = "后车正在接近。先守住位置，后车压力缓解再看前车。"
    elif front_rival is not None and getattr(front_rival, "gap_confidence_behind", None) == "medium" and domain.labels.attack_state != "unavailable":
        reason = f"前车差距估算为 {gap:.3f} 秒，只有中等把握。先跟住，等可靠时差和直道条件。"
    elif domain.labels.attack_state == "unavailable":
        reason = "前车时差缺失。保持节奏，等到可靠时差再判断。"
    elif method_reason is not None and gap <= domain.thresholds["rival_gap_attack"]:
        reason = method_reason
    elif gap > domain.thresholds["rival_gap_attack"]:
        reason = f"前车差距还有 {gap:.3f} 秒，没进直接进攻窗口。"
    elif not state.player.drs_available:
        reason = f"前车差距 {gap:.3f} 秒，但当前没有 DRS，加速兑现条件不够。"
    elif primary_message is None:
        reason = f"前车差距 {gap:.3f} 秒且 DRS={drs}，距离条件已满足；但未提供当前策略决定，不能据此确认最终行动。"
    else:
        reason = f"前车差距 {gap:.3f} 秒且 DRS={drs}，但当前综合条件还不足以让进攻优先于稳定性。"
    return (
        render_conclusion_with_reason(
            "现在没有给出进攻窗口" if primary_message is not None else "当前进攻条件说明",
            reason,
            connector="因为",
        ),
        "QUERY_WHY_NOT_ATTACK",
    )

