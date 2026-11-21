from __future__ import annotations

from .race_control import race_control_active

import re

from .persona_registry import get_persona


_TERMINAL_PUNCTUATION = ("。", "！", "？", ".", "!", "?")
_CHATTER_PREFIXES = (
    "好的，",
    "好的。",
    "明白了，",
    "明白了。",
    "明白，",
    "结论：",
    "总结：",
    "当前来看，",
    "当前来看。",
    "目前来看，",
    "目前来看。",
)


def _normalize_clause(text: str | None) -> str:
    clause = str(text or "").strip()
    if not clause:
        return ""
    if clause.endswith(_TERMINAL_PUNCTUATION):
        return clause
    return f"{clause}。"


def join_persona_clauses(*clauses: str | None, persona_id: str | None = None) -> str:
    persona = get_persona(persona_id)
    normalized = [_normalize_clause(clause) for clause in clauses if str(clause or "").strip()]
    return persona.clause_separator.join(normalized)


def render_verdict_with_numbers(
    verdict: str,
    *number_clauses: str | None,
    persona_id: str | None = None,
) -> str:
    return join_persona_clauses(verdict, *number_clauses, persona_id=persona_id)


def render_conclusion_with_reason(
    conclusion: str,
    reason: str,
    *,
    connector: str | None = None,
    persona_id: str | None = None,
) -> str:
    persona = get_persona(persona_id)
    prefix = connector or persona.reason_connector
    return join_persona_clauses(f"{conclusion} {prefix} {reason}", persona_id=persona_id)


def render_summary_answer(*clauses: str | None, persona_id: str | None = None) -> str:
    return join_persona_clauses(*clauses, persona_id=persona_id)


def render_unavailable_answer(
    subject: str,
    reason: str | None = None,
    *,
    persona_id: str | None = None,
) -> str:
    lead = f"{subject}当前缺失，不能可靠回答。"
    if reason:
        return join_persona_clauses(lead, reason, persona_id=persona_id)
    return lead


def render_not_supported_answer(
    detail: str,
    *,
    persona_id: str | None = None,
) -> str:
    return join_persona_clauses(detail, persona_id=persona_id)


def render_overall_primary_posture(
    *,
    attack_state: str,
    defend_state: str,
    primary_code: str | None,
    primary_detail: str | None,
    gap_ahead_s: float | None,
    gap_behind_s: float | None,
    drs_available: bool,
) -> str:
    if primary_code == "DEFEND_WINDOW" and primary_detail:
        return f"当前整体先以防守为主，因为 {primary_detail}"
    if primary_code == "ATTACK_WINDOW" and primary_detail:
        return f"当前整体先以进攻施压为主，因为 {primary_detail}"
    if defend_state == "urgent":
        return f"当前整体更偏向防守，后车只落后 {gap_behind_s:.3f} 秒。"
    if attack_state == "available":
        return f"当前整体更偏向进攻，前车只领先 {gap_ahead_s:.3f} 秒且 DRS 可用。"
    return "当前整体以中性管理为主。"


def render_overall_main_risk(
    *,
    tyre_state: str,
    defend_state: str,
    primary_code: str | None,
    primary_detail: str | None,
    drive_through: int,
    stop_go: int,
    should_serve_penalty: bool,
    fuel_laps_remaining: float,
    fuel_verdict: str = "unavailable",
    fuel_detail: str = "",
    tyre_wear_pct: float,
    gap_behind_s: float | None,
    safety_car: str,
) -> str:
    if drive_through or stop_go or should_serve_penalty:
        return f"最大风险还是处罚处理，当前穿越维修区 {drive_through} 条，stop-go {stop_go} 条。"
    if primary_code == "DEFEND_WINDOW" and primary_detail:
        return f"最大风险是后车压力，{primary_detail}"
    if defend_state == "urgent":
        return f"最大风险是后车逼近，当前差距只有 {gap_behind_s:.3f} 秒。"
    if fuel_verdict == "critical":
        return f"最大风险是燃油偏紧。{fuel_detail}"
    if tyre_state in {"manage", "box_now"}:
        return f"最大风险是轮胎磨损偏高，已经到 {tyre_wear_pct:.1f}%。"
    if race_control_active(safety_car):
        return f"当前最大变量是赛道管制，赛道处于 {safety_car} 阶段。"
    return "当前没有单一压倒性风险。"


def render_overall_next_focus(
    *,
    tyre_state: str,
    primary_code: str | None,
    drive_through: int,
    stop_go: int,
    should_serve_penalty: bool,
    fuel_laps_remaining: float,
    fuel_verdict: str = "unavailable",
    fuel_detail: str = "",
    tyre_wear_pct: float,
    safety_car: str,
) -> str:
    if drive_through or stop_go or should_serve_penalty:
        return "下一步先把处罚处理窗口放在最前面。"
    if primary_code == "DEFEND_WINDOW":
        return "下一步优先守住后车 DRS 线并稳住出弯。"
    if primary_code == "ATTACK_WINDOW":
        return "下一步优先盯前车差距和 DRS 兑现，别在资源不足时硬上。"
    if fuel_verdict == "critical":
        return "下一步优先控燃油。"
    if tyre_state in {"manage", "box_now"}:
        return "下一步优先保护轮胎。"
    if race_control_active(safety_car):
        return "下一步优先看赛道管制是否变化。"
    return "下一步优先稳住前后车差距和资源消耗。"


def render_damage_recommendation(
    *,
    front_wing_pct: int,
    floor_damage_pct: int,
    diffuser_damage_pct: int,
    sidepod_damage_pct: int,
    engine_damage_pct: int,
    engine_blown: bool,
    engine_seized: bool,
) -> str:
    aero_core = max(front_wing_pct, floor_damage_pct, diffuser_damage_pct)
    if engine_blown or engine_seized:
        return "当前已经是故障级车损，优先考虑立刻退赛或最低风险收车。"
    if engine_damage_pct >= 70 or front_wing_pct >= 40 or aero_core >= 45:
        return "建议优先保守节奏，并尽快评估进站修复窗口。"
    if (
        engine_damage_pct >= 35
        or front_wing_pct >= 15
        or aero_core >= 20
        or sidepod_damage_pct >= 15
    ):
        return "建议减少无谓缠斗，先观察节奏损失，再决定是否专门进站处理。"
    return "暂时不需要专门为车损改变整段策略，先继续观察。"


def render_damage_pit_advice(
    *,
    front_wing_pct: int,
    floor_damage_pct: int,
    diffuser_damage_pct: int,
    engine_damage_pct: int,
    engine_blown: bool,
    engine_seized: bool,
) -> str:
    aero_core = max(floor_damage_pct, diffuser_damage_pct)
    if engine_blown or engine_seized:
        return "这份车损已经不是普通进站能优雅解决的级别，优先考虑收车或最低风险返回。"
    if engine_damage_pct >= 70 or front_wing_pct >= 40 or aero_core >= 45:
        return "建议优先找最近的可控进站窗口处理车损，不要继续拿正常节奏硬扛。"
    if engine_damage_pct >= 35 or front_wing_pct >= 15 or aero_core >= 20:
        return "还不一定要立刻进站，但如果接下来有便宜窗口，处理车损会比继续拖更稳。"
    return "暂时不建议专门为了这份车损立刻进站，先继续观察节奏损失。"


def render_front_wing_damage_detail(front_wing_pct: int) -> str:
    if front_wing_pct >= 40:
        return f"前翼损伤已经很重，当前约 {front_wing_pct}%，会明显影响前端抓地。建议尽快考虑修复窗口。"
    if front_wing_pct >= 15:
        return f"前翼有中等损伤，当前约 {front_wing_pct}%。建议减少激进压路肩和无谓近身缠斗。"
    return f"前翼损伤不重，当前约 {front_wing_pct}%，短期还不需要专门改策略。"


def render_floor_damage_detail(
    floor_damage_pct: int,
    diffuser_damage_pct: int,
    sidepod_damage_pct: int,
) -> str:
    aero_core = max(floor_damage_pct, diffuser_damage_pct)
    if aero_core >= 45:
        return f"底板和尾部气动损伤已经偏重，底板 {floor_damage_pct}% 、扩散器 {diffuser_damage_pct}% 。建议尽快转保守节奏。"
    if aero_core >= 20 or sidepod_damage_pct >= 15:
        return f"底板区域有中等损伤，底板 {floor_damage_pct}% 、扩散器 {diffuser_damage_pct}% 、侧箱 {sidepod_damage_pct}% 。高速稳定性会先受影响。"
    return f"底板区域损伤目前不重，底板 {floor_damage_pct}% 、扩散器 {diffuser_damage_pct}% 、侧箱 {sidepod_damage_pct}% 。"


def render_engine_damage_detail(
    *,
    engine_damage_pct: int,
    engine_blown: bool,
    engine_seized: bool,
) -> str:
    if engine_blown or engine_seized:
        return "发动机已经进入故障状态，当前不适合继续正常推进。"
    if engine_damage_pct >= 70:
        return f"发动机损伤已经很重，当前约 {engine_damage_pct}%。建议立刻保守运行，并准备处理。"
    if engine_damage_pct >= 35:
        return f"发动机有中等损伤，当前约 {engine_damage_pct}%。建议降低无谓负荷，优先把比赛带回可控区间。"
    return f"发动机损伤目前不高，当前约 {engine_damage_pct}%，短期更像需要继续观察。"


def render_tyre_wear_outlook(
    *,
    wear_pct: float,
    age_laps: int,
    active_attack: bool,
    active_defend: bool,
    tyre_state: str,
) -> str:
    if tyre_state == "unavailable":
        return "轮胎磨损数据不可用，暂不能预测磨损变化。"
    if tyre_state == "box_now":
        detail = f"当前轮胎磨损 {wear_pct:.1f}%，已经触发进站磨损阈值，不适合继续高强度攻防。"
    elif tyre_state == "manage":
        detail = f"当前轮胎磨损 {wear_pct:.1f}%，已经触发保胎阈值，建议先控制额外消耗。"
    else:
        detail = f"当前轮胎磨损 {wear_pct:.1f}%，胎龄 {age_laps} 圈，尚未触发保胎阈值。"
    if active_attack or active_defend:
        detail += " 当前还在直接攻防窗口，持续对抗可能增加轮胎消耗。"
    return detail + " 仅凭当前磨损无法准确预测未来可跑圈数，需要结合连续圈的实际磨损变化。"


def render_llm_sidecar_text(answer_text: str, *, persona_id: str | None = None) -> str:
    text = re.sub(r"\s+", " ", str(answer_text or "").replace("\n", " ")).strip()
    if not text:
        return ""
    for prefix in _CHATTER_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    clauses = [clause.strip() for clause in re.split(r"[。！？!?]+", text) if clause.strip()]
    if not clauses:
        return _normalize_clause(text)
    return join_persona_clauses(*clauses, persona_id=persona_id)
