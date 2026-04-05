from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .asr_fast import FastIntentASR, FastIntentResult, KeywordFastIntentASR
from .conversation_context import ConversationContext
from .models import SessionState, StrategyMessage
from .output import ConsoleVoiceOutput
from .semantic_normalizer import SemanticNormalizer
from .voice_nlu import VoiceQueryBundle, build_voice_query_bundle
from .voice_turn import VoiceTurn


CONTROL_QUERY_KINDS = {"repeat_last", "stop", "cancel"}


@dataclass(frozen=True)
class VoiceInputProcessingResult:
    """End-to-end result of one completed voice turn."""

    status: str
    reason: str
    fast_intent: dict[str, Any]
    voice_turn: dict[str, Any]
    bundle: dict[str, Any] | None = None
    output_debug: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VoiceInputCoordinator:
    """Bridge completed voice turns into the existing interaction/output path."""

    def __init__(
        self,
        *,
        fast_intent_asr: FastIntentASR | None = None,
        semantic_normalizer: SemanticNormalizer | None = None,
        conversation_context: ConversationContext | None = None,
    ) -> None:
        self.fast_intent_asr = fast_intent_asr or KeywordFastIntentASR()
        self.semantic_normalizer = semantic_normalizer or SemanticNormalizer()
        self.conversation_context = conversation_context or ConversationContext()

    def process_completed_turn(
        self,
        *,
        state: SessionState,
        turn: VoiceTurn,
        voice_output: ConsoleVoiceOutput,
        primary_message: StrategyMessage | None = None,
        render: bool = True,
    ) -> VoiceInputProcessingResult:
        self.conversation_context.observe_strategy_message(primary_message, state=state)
        fast_intent = self.fast_intent_asr.recognize_turn(turn)
        semantic_intent = self.semantic_normalizer.normalize(
            state=state,
            voice_turn=turn,
            fast_intent=fast_intent,
            conversation_context=self.conversation_context,
            primary_message=primary_message,
        )
        if semantic_intent.status != "matched" or semantic_intent.query_kind is None:
            return VoiceInputProcessingResult(
                status="fallback",
                reason=semantic_intent.reason,
                fast_intent=fast_intent.to_dict(),
                voice_turn=turn.to_dict(),
            )

        bundle = build_voice_query_bundle(
            state=state,
            voice_turn=turn,
            fast_intent=fast_intent,
            semantic_intent=semantic_intent,
        )
        self.conversation_context.observe_user_query(
            request_id=bundle.input_event["request_id"],
            transcript_text=semantic_intent.normalized_query_text,
            query_kind=semantic_intent.query_kind,
            timestamp_ms=int(bundle.input_event["created_at_ms"]),
            metadata={"reason": semantic_intent.reason},
        )
        if semantic_intent.query_kind in CONTROL_QUERY_KINDS:
            output_debug = voice_output.emit_control_query_bundle(
                state=state,
                bundle=bundle,
                primary_message=primary_message,
                render=render,
            )
            self._record_response(bundle=bundle, output_debug=output_debug)
            return VoiceInputProcessingResult(
                status="control_executed",
                reason="control_query_emitted",
                fast_intent=fast_intent.to_dict(),
                voice_turn=turn.to_dict(),
                bundle=bundle.to_dict(),
                output_debug=output_debug,
            )

        output_debug = voice_output.emit_voice_query_bundle(
            state=state,
            bundle=bundle,
            primary_message=primary_message,
            render=render,
        )
        self._record_response(bundle=bundle, output_debug=output_debug)
        return VoiceInputProcessingResult(
            status="spoken",
            reason="query_response_emitted",
            fast_intent=fast_intent.to_dict(),
            voice_turn=turn.to_dict(),
            bundle=bundle.to_dict(),
            output_debug=output_debug,
        )

    def _record_response(self, *, bundle: VoiceQueryBundle, output_debug: dict[str, Any]) -> None:
        event = ((output_debug.get("output_lifecycle") or {}).get("event") or {})
        self.conversation_context.observe_response(
            request_id=str(bundle.input_event.get("request_id") or "req:unknown"),
            query_kind=str(bundle.structured_query.get("query_kind") or ""),
            action_code=event.get("action_code"),
            speak_text=event.get("speak_text"),
            timestamp_ms=int(bundle.input_event.get("created_at_ms") or 0),
            metadata={"event_type": event.get("event_type"), "reason": event.get("metadata", {}).get("reason")},
        )
