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
            return SemanticIntentResult(
                status="fallback",
                query_kind=None,
                normalized_query_text=transcript_text or normalized_text,
                response_style="fallback",
                confidence=fast_intent.confidence,
                reason="semantic_unmatched",
                metadata={
                    "lane": fast_intent.lane,
                    "source_query_kind": fast_intent.query_kind,
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
            last_query_kind = conversation_context.last_query_kind()
            if last_query_kind is not None:
                return last_query_kind

        if self._contains_any(normalized_text, ("后面", "后方", "后车", "后边")) and self._contains_any(
            normalized_text,
            ("多近", "多远", "贴多近", "差距", "到 drs", "到drs", "追多快"),
        ):
            return "rear_gap"

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

        if self._contains_any(normalized_text, ("策略", "战术", "现在该", "现在怎么跑")):
            return "current_strategy"

        return None

    def _contains_any(self, normalized_text: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in normalized_text for phrase in phrases)

    def _contains_unhandled_topic(self, normalized_text: str) -> bool:
        return self._contains_any(
            normalized_text,
            (
                "进站",
                "pit",
                "安全车",
                "红旗",
                "处罚",
                "罚时",
                "天气",
                "下雨",
                "轮胎",
                "胎",
                "燃油",
                "油量",
            ),
        )
