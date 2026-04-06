from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .asr_fast import FastIntentResult
from .conversation_context import ConversationContext
from .models import SessionState, StrategyMessage
from .voice_turn import VoiceTurn


@dataclass(frozen=True)
class SemanticIntentResult:
    status: str
    query_kind: str | None
    normalized_query_text: str
    response_style: str
    confidence: float
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SemanticNormalizer:
    """Normalize natural language voice input into structured query intents."""

    def normalize(
        self,
        *,
        state: SessionState,
        voice_turn: VoiceTurn,
        fast_intent: FastIntentResult,
        conversation_context: ConversationContext,
        primary_message: StrategyMessage | None = None,
    ) -> SemanticIntentResult:
        transcript_text = fast_intent.transcript_text.strip()
        normalized_text = fast_intent.normalized_text.strip()
        if fast_intent.status == "matched" and fast_intent.query_kind is not None:
            return SemanticIntentResult(
                status="matched",
                query_kind=fast_intent.query_kind,
                normalized_query_text=transcript_text or normalized_text,
                response_style="structured",
                confidence=fast_intent.confidence,
                reason="fast_intent_matched",
                metadata={
                    "source_query_kind": fast_intent.query_kind,
                    "matched_phrase": fast_intent.matched_phrase,
                    "lane": fast_intent.lane,
                },
            )

        semantic_query_kind = self._infer_query_kind(
            normalized_text=normalized_text,
            conversation_context=conversation_context,
            primary_message=primary_message,
        )
        if semantic_query_kind is None:
            fallback_text = transcript_text or normalized_text
            if not fallback_text:
                return SemanticIntentResult(
                    status="fallback",
                    query_kind=None,
                    normalized_query_text="",
                    response_style="fallback",
                    confidence=fast_intent.confidence,
                    reason="semantic_unmatched",
                    metadata={
                        "lane": fast_intent.lane,
                        "source_query_kind": fast_intent.query_kind,
                        "context": conversation_context.snapshot(),
                    },
                )
            return SemanticIntentResult(
                status="matched",
                query_kind="open_fallback",
                normalized_query_text=fallback_text,
                response_style="fallback",
                confidence=max(fast_intent.confidence, 0.55),
                reason="open_fallback",
                metadata={
                    "lane": fast_intent.lane,
                    "source_query_kind": fast_intent.query_kind,
                    "domain_hint": self._infer_domain_hint(normalized_text),
                    "context": conversation_context.snapshot(),
                },
            )

        response_style = "explanation" if semantic_query_kind.startswith("why_") else "structured"
        return SemanticIntentResult(
            status="matched",
            query_kind=semantic_query_kind,
            normalized_query_text=transcript_text or normalized_text,
            response_style=response_style,
            confidence=max(fast_intent.confidence, 0.72),
            reason="semantic_normalized",
            metadata={
                "source_query_kind": fast_intent.query_kind,
                "context": conversation_context.snapshot(),
            },
        )

    def _infer_query_kind(
        self,
        *,
        normalized_text: str,
        conversation_context: ConversationContext,
        primary_message: StrategyMessage | None,
    ) -> str | None:
        if not normalized_text:
            return None

        if self._contains_any(normalized_text, ("为什么", "为啥", "怎么会", "怎么不", "为何")):
            if self._contains_any(normalized_text, ("不进攻", "不让我进攻", "没让我进攻", "不攻击", "没攻击")):
                return "why_not_attack"
            if self._contains_any(normalized_text, ("进站", "pit", "box", "维修区")):
                return "why_not_pit"
            if self._contains_any(normalized_text, ("防守", "防住")):
                return "why_defend"
            if self._contains_unhandled_topic(normalized_text):
                return None
            if (
                self._contains_any(normalized_text, ("策略", "战术", "当前", "现在", "刚才", "刚刚", "这样", "这个", "那样"))
                and (primary_message is not None or conversation_context.last_strategy_code())
            ):
                code = primary_message.code if primary_message is not None else conversation_context.last_strategy_code()
                if code == "DEFEND_WINDOW":
                    return "why_defend"
                return "why_current_strategy"

        if self._contains_any(normalized_text, ("现在呢", "现在还", "现在怎么样", "还一样吗", "那现在呢")):
            last_query_kind = conversation_context.last_non_control_query_kind()
            if last_query_kind is not None:
                return last_query_kind

        if self._contains_any(normalized_text, ("那这个风险大吗", "这个风险严重吗", "风险大不大")):
            last_query_kind = conversation_context.last_non_control_query_kind()
            if last_query_kind in {"main_risk_summary", "overall_situation", "attack_or_defend_summary", "next_lap_focus"}:
                return "risk_severity_followup"

        if self._contains_any(normalized_text, ("这个风险多久会变严重", "风险多久会变严重", "这个风险什么时候会更严重")):
            last_query_kind = conversation_context.last_non_control_query_kind()
            if last_query_kind in {"main_risk_summary", "risk_severity_followup", "overall_situation", "attack_or_defend_summary", "next_lap_focus"}:
                return "risk_escalation_timing"
            return "risk_escalation_timing"

        if self._contains_any(normalized_text, ("后车压力会不会自己降下去", "后车压力会不会自己缓解", "后车压力会不会自己掉下去")):
            return "rear_pressure_relief_outlook"

        if self._contains_any(normalized_text, ("那前车呢", "前车呢", "前面呢")):
            return "front_gap"

        if self._contains_any(normalized_text, ("那后车呢", "后车呢", "后面呢", "后方呢")):
            return "rear_gap"

        if self._contains_any(normalized_text, ("前翼", "鼻翼")):
            return "front_wing_damage_status"

        if self._contains_any(normalized_text, ("底板", "地板", "floor", "diffuser", "扩散器")):
            return "floor_damage_status"

        if self._contains_any(normalized_text, ("发动机", "引擎", "engine", "动力单元")):
            return "engine_damage_status"

        if self._contains_any(normalized_text, ("车损", "损伤", "损坏", "坏了吗", "坏了没")):
            if self._contains_any(normalized_text, ("进站", "pit", "box", "修", "处理", "要不要")):
                return "damage_pit_advice"
            return "damage_status"

        if self._contains_any(normalized_text, ("后面", "后方", "后车", "后边")) and self._contains_any(
            normalized_text,
            ("多近", "多远", "贴多近", "差距", "到 drs", "到drs", "追多快"),
        ):
            return "rear_gap"

        if self._contains_any(normalized_text, ("前面", "前方", "前车", "前边")) and self._contains_any(
            normalized_text,
            ("多近", "多远", "贴多近", "差距", "到 drs", "到drs", "追多快"),
        ):
            return "front_gap"

        if self._contains_any(normalized_text, ("前面", "前方", "前车", "前边")) and self._contains_any(
            normalized_text,
            ("有drs", "有没有drs", "能开drs", "drs吗"),
        ):
            return "front_rival_drs_status"

        if self._contains_any(normalized_text, ("后面", "后方", "后车", "后边")) and self._contains_any(
            normalized_text,
            ("有drs", "有没有drs", "到drs", "进drs", "drs吗"),
        ):
            return "rear_rival_drs_status"

        if self._contains_any(normalized_text, ("燃油", "油量", "油")) and self._contains_any(
            normalized_text,
            ("还够", "还能跑", "还剩", "够不够", "要不要省", "紧张"),
        ):
            return "fuel_status"

        if self._contains_any(normalized_text, ("轮胎", "胎", "胎况")) and self._contains_any(
            normalized_text,
            ("状态", "怎么样", "撑得住", "能跑吗", "磨损", "温度"),
        ):
            return "tyre_status"

        if self._contains_any(normalized_text, ("轮胎", "胎", "胎况")) and self._contains_any(
            normalized_text,
            ("未来几圈", "接下来几圈", "还能撑几圈", "还能撑多久", "会怎么掉", "预计损耗", "掉多快"),
        ):
            return "tyre_wear_outlook"

        if self._contains_any(normalized_text, ("天气", "下雨", "雨", "路面", "赛道温度", "路况")):
            return "weather_status"

        if self._contains_any(normalized_text, ("处罚", "罚时", "警告", "stop go", "stop-go", "drive through", "穿越维修区")):
            if self._contains_any(normalized_text, ("怎么处理", "处理最好", "最好的处理方式", "怎么办")):
                return "penalty_handling_strategy"
            if self._contains_any(normalized_text, ("进站", "pit", "box", "服刑", "处理")):
                return "pit_penalty_plan"
            return "penalty_status"

        if self._contains_any(normalized_text, ("drs", "尾翼", "开尾翼")):
            return "drs_status"

        if self._contains_any(normalized_text, ("ers", "电量", "电池", "部署")):
            return "ers_status"

        if self._contains_any(normalized_text, ("赛道状态", "赛道管制", "安全车状态", "安全车", "虚拟安全车", "vsc", "红旗")):
            return "race_control_status"

        if self._contains_any(normalized_text, ("赛道", "前面")) and self._contains_any(
            normalized_text,
            ("怎么了", "什么情况", "出什么事", "出事", "事故", "有管制"),
        ):
            return "race_control_status"

        if self._contains_any(normalized_text, ("进站", "pit", "box", "维修区")):
            if self._contains_any(normalized_text, ("等一圈", "下一圈再", "下一圈")):
                return "pit_one_lap_delay_consequence"
            if self._contains_any(normalized_text, ("不进站", "继续不进站", "如果不进站", "如果继续不进站")):
                return "pit_delay_consequence"
            return "pit_status"

        if self._contains_any(normalized_text, ("服刑", "处理处罚")):
            return "pit_penalty_plan"

        if self._contains_any(normalized_text, ("整体形势", "整体情况", "局势怎么样", "整体局势")):
            return "overall_situation"

        if self._contains_any(normalized_text, ("该攻还是守", "该防还是攻", "现在该攻还是守", "现在该防还是攻")):
            return "attack_or_defend_summary"

        if self._contains_any(normalized_text, ("守和攻哪个代价更低", "攻守哪个代价更低", "现在守和攻哪个代价更低", "现在攻守哪个代价更低")):
            return "attack_defend_tradeoff"

        if self._contains_any(normalized_text, ("主要风险", "还要注意什么", "现在最该注意什么", "还有别的吗")):
            return "main_risk_summary"

        if self._contains_any(normalized_text, ("下一圈", "这几圈", "接下来")) and self._contains_any(
            normalized_text,
            ("注意什么", "该注意什么", "要注意什么", "重点是什么"),
        ):
            return "next_lap_focus"

        if self._contains_any(normalized_text, ("守住", "防住", "防守")) and self._contains_any(
            normalized_text,
            ("会怎样", "会怎么样", "结果会怎样", "结果会怎么样"),
        ):
            return "defend_outcome_projection"

        if self._contains_any(normalized_text, ("进攻", "攻击", "上去", "追上去")) and self._contains_any(
            normalized_text,
            ("会怎样", "会怎么样", "结果会怎样", "结果会怎么样"),
        ):
            return "attack_outcome_projection"

        if self._contains_any(normalized_text, ("保胎",)) and self._contains_any(
            normalized_text,
            ("要不要", "该不该", "现在", "需不需要"),
        ):
            return "tyre_management_advice"

        if self._contains_any(normalized_text, ("省油", "省燃油", "省一点油")) and self._contains_any(
            normalized_text,
            ("要不要", "该不该", "现在", "需不需要"),
        ):
            return "fuel_management_advice"

        if self._contains_any(normalized_text, ("策略", "战术", "现在该", "现在怎么跑")):
            return "current_strategy"

        return None

    def _contains_any(self, normalized_text: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in normalized_text for phrase in phrases)

    def _contains_unhandled_topic(self, normalized_text: str) -> bool:
        return self._contains_any(
            normalized_text,
            (
                "安全车",
                "红旗",
            ),
        )

    def _infer_domain_hint(self, normalized_text: str) -> str:
        if self._contains_any(normalized_text, ("进站", "pit", "box", "维修区")):
            return "pit"
        if self._contains_any(normalized_text, ("天气", "下雨", "雨", "路面", "路况")):
            return "weather"
        if self._contains_any(normalized_text, ("处罚", "罚时", "警告", "stop go", "drive through")):
            return "penalty"
        if self._contains_any(normalized_text, ("车损", "损伤", "损坏", "前翼", "底板", "地板", "发动机", "引擎")):
            return "damage"
        if self._contains_any(normalized_text, ("策略", "战术")):
            return "strategy"
        return "general"
