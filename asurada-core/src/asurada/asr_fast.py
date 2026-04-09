from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .voice_turn import VoiceTurn


@dataclass(frozen=True)
class FastIntentResult:
    """Structured output of the fast intent lane."""

    lane: str
    status: str
    transcript_text: str
    normalized_text: str
    query_kind: str | None
    confidence: float
    matched_phrase: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FastIntentASR:
    """Abstract fast-lane recognizer for structured racing queries."""

    def recognize_turn(self, turn: VoiceTurn) -> FastIntentResult:
        raise NotImplementedError


class KeywordFastIntentASR(FastIntentASR):
    """Text-first recognizer using constrained phrases and aliases."""

    DEFAULT_ALIASES: dict[str, tuple[str, ...]] = {
        "fuel_status": ("燃油", "油量", "还剩多少油", "燃油怎么样"),
        "damage_status": ("车损情况", "车损怎么样", "损伤情况", "现在车损怎么样", "车坏了吗"),
        "damage_pit_advice": ("这车损要不要进站", "车损要不要进站", "要不要修车损", "这损伤要不要进站"),
        "front_wing_damage_status": ("前翼坏了吗", "前翼伤了多少", "前翼车损怎么样"),
        "floor_damage_status": ("底板伤了多少", "地板伤了多少", "底板损伤怎么样"),
        "engine_damage_status": ("发动机有损伤吗", "引擎有损伤吗", "发动机车损怎么样"),
        "front_gap": ("前车", "前面", "前车差距", "前车多近"),
        "rear_gap": ("后车", "后面", "后方差距", "后车差距", "后车多近"),
        "tyre_status": ("轮胎", "胎况", "轮胎状态", "胎怎么样", "胎温"),
        "tyre_wear_outlook": (
            "未来几圈轮胎预计损耗",
            "接下来几圈轮胎会怎么掉",
            "未来几圈轮胎会怎么掉",
            "轮胎还能撑几圈",
            "轮胎还能撑多久",
            "这套胎未来几圈会怎么样",
        ),
        "drs_status": ("drs", "现在有drs吗", "能开drs吗"),
        "front_rival_drs_status": ("前车有没有drs", "前车有drs吗", "前面有drs吗"),
        "rear_rival_drs_status": ("后车到drs了吗", "后车有drs吗", "后面到drs了吗", "后车进drs了吗"),
        "ers_status": ("ers", "电量", "还有多少电", "ers还有多少"),
        "race_control_status": (
            "赛道状态",
            "赛道管制",
            "安全车状态",
            "现在什么状态",
            "现在有安全车吗",
            "现在有虚拟安全车吗",
            "赛道出什么事儿了",
            "赛道怎么了",
            "现在赛道什么情况",
            "前面出什么事了",
            "是不是有管制",
            "是不是出事故了",
        ),
        "pit_penalty_plan": ("这次进站要不要服刑", "下次进站要不要处理处罚", "进站要不要处理处罚", "要不要服刑"),
        "penalty_handling_strategy": ("这次处罚现在最好的处理方式是什么", "这条处罚怎么处理最好", "处罚怎么处理最好"),
        "main_risk_summary": ("主要风险", "还要注意什么", "还有别的吗", "现在最该注意什么"),
        "next_lap_focus": ("下一圈该注意什么", "这几圈该注意什么", "接下来该注意什么", "下一圈要注意什么"),
        "risk_severity_followup": ("那这个风险大吗", "这个风险严重吗", "风险大不大"),
        "risk_escalation_timing": ("这个风险多久会变严重", "风险多久会变严重", "这个风险什么时候会更严重"),
        "pit_delay_consequence": ("如果继续不进站会怎样", "如果不进站会怎样", "继续不进站会怎么样"),
        "pit_one_lap_delay_consequence": ("如果等一圈再进站会怎样", "等一圈再进站会怎样", "如果下一圈再进站会怎样"),
        "tyre_management_advice": ("现在要不要保胎", "要不要保胎", "现在该不该保胎"),
        "fuel_management_advice": ("现在要不要省油", "要不要省油", "现在该不该省油"),
        "defend_outcome_projection": ("如果我现在守住会怎样", "如果现在守住会怎样", "现在守住会怎样"),
        "attack_outcome_projection": ("如果我现在进攻会怎样", "如果现在进攻会怎样", "现在进攻会怎样"),
        "attack_defend_tradeoff": ("现在守和攻哪个代价更低", "守和攻哪个代价更低", "现在攻守哪个代价更低"),
        "rear_pressure_relief_outlook": ("后车压力会不会自己降下去", "后车压力会不会自己缓解", "后车压力会不会自己掉下去"),
        "overall_situation": ("整体形势", "整体情况", "局势怎么样"),
        "attack_or_defend_summary": ("该攻还是守", "该防还是攻", "现在该攻还是守", "现在该防还是攻"),
        "current_strategy": ("当前策略", "当前战术", "现在策略", "现在怎么跑", "策略怎么样"),
        "repeat_last": ("重复", "再说一遍", "重说", "重复上一条"),
        "stop": ("停止", "停下", "别说了", "闭嘴"),
        "cancel": ("取消", "算了", "不用了", "不用回答"),
    }

    def __init__(self, *, aliases: dict[str, tuple[str, ...]] | None = None, threshold: float = 0.6) -> None:
        self.aliases = aliases or self.DEFAULT_ALIASES
        self.threshold = threshold

    def recognize_turn(self, turn: VoiceTurn) -> FastIntentResult:
        transcript_text = str(turn.metadata.get("transcript_text") or "").strip()
        transcript_hint = str(turn.metadata.get("transcript_hint") or "").strip()
        primary_text = transcript_text or transcript_hint
        primary_normalized = " ".join(primary_text.lower().split())
        if not primary_normalized:
            return FastIntentResult(
                lane="fast_intent",
                status="no_transcript",
                transcript_text=primary_text,
                normalized_text=primary_normalized,
                query_kind=None,
                confidence=0.0,
                matched_phrase=None,
                metadata={"turn_id": turn.turn_id},
            )

        chosen_text = primary_text
        chosen_normalized = primary_normalized
        chosen_source = "transcript_text" if transcript_text else "transcript_hint"
        best_query_kind, best_phrase, best_score = self._best_match_for_text(primary_normalized)

        if transcript_hint:
            hint_normalized = " ".join(transcript_hint.lower().split())
            hint_query_kind, hint_phrase, hint_score = self._best_match_for_text(hint_normalized)
            if hint_score > best_score:
                chosen_text = transcript_hint
                chosen_normalized = hint_normalized
                chosen_source = "transcript_hint"
                best_query_kind = hint_query_kind
                best_phrase = hint_phrase
                best_score = hint_score

        status = "matched" if best_query_kind is not None and best_score >= self.threshold else "fallback"
        return FastIntentResult(
            lane="fast_intent",
            status=status,
            transcript_text=chosen_text,
            normalized_text=chosen_normalized,
            query_kind=best_query_kind if status == "matched" else None,
            confidence=round(best_score, 4),
            matched_phrase=best_phrase if status == "matched" else None,
            metadata={
                "turn_id": turn.turn_id,
                "threshold": self.threshold,
                "transcript_source": chosen_source,
                "original_transcript_text": transcript_text,
                "transcript_hint": transcript_hint,
            },
        )

    def _best_match_for_text(self, normalized_text: str) -> tuple[str | None, str | None, float]:
        best_query_kind: str | None = None
        best_phrase: str | None = None
        best_score = 0.0
        for query_kind, phrases in self.aliases.items():
            for phrase in phrases:
                score = self._score_phrase(normalized_text, phrase.lower())
                if score > best_score:
                    best_score = score
                    best_query_kind = query_kind
                    best_phrase = phrase
        return best_query_kind, best_phrase, best_score

    def _score_phrase(self, normalized_text: str, phrase: str) -> float:
        if normalized_text == phrase:
            return 1.0
        if phrase in normalized_text:
            return min(0.95, max(len(phrase) / max(len(normalized_text), 1), 0.65))
        overlap = len(set(normalized_text) & set(phrase))
        union = len(set(normalized_text) | set(phrase)) or 1
        return overlap / union
