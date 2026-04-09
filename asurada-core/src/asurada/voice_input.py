from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from .asr_fast import FastIntentASR, FastIntentResult, KeywordFastIntentASR
from .capability_registry import CapabilityRegistry
from .conversation_context import ConversationContext
from .llm_explainer import (
    LlmExplainer,
    build_llm_explainer_request,
    llm_sidecar_enabled_from_env,
    llm_timeout_ms_from_env,
)
from .models import SessionState, StrategyMessage
from .output import ConsoleVoiceOutput
from .persona_registry import get_default_persona, render_companion_mode_fallback
from .persona_style import render_llm_sidecar_text
from .semantic_normalizer import SemanticNormalizer
from .transcript_router import TranscriptRouter
from .voice_nlu import VoiceQueryBundle, build_voice_query_bundle
from .voice_turn import VoiceTurn
from .wake_word import WakeWordGate, WakeWordResult


CONTROL_QUERY_KINDS = {"repeat_last", "stop", "cancel"}


@dataclass(frozen=True)
class VoiceInputProcessingResult:
    """End-to-end result of one completed voice turn."""

    status: str
    reason: str
    fast_intent: dict[str, Any]
    voice_turn: dict[str, Any]
    wake_word: dict[str, Any] | None = None
    route_decision: dict[str, Any] | None = None
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
        wake_word_gate: WakeWordGate | None = None,
        transcript_router: TranscriptRouter | None = None,
        capability_registry: CapabilityRegistry | None = None,
        llm_explainer: LlmExplainer | None = None,
        enable_llm_sidecar: bool | None = None,
        llm_timeout_ms: int | None = None,
    ) -> None:
        self.fast_intent_asr = fast_intent_asr or KeywordFastIntentASR()
        self.semantic_normalizer = semantic_normalizer or SemanticNormalizer()
        self.conversation_context = conversation_context or ConversationContext()
        self.wake_word_gate = wake_word_gate or WakeWordGate()
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.transcript_router = transcript_router or TranscriptRouter(capability_registry=self.capability_registry)
        self.llm_explainer = llm_explainer or LlmExplainer.from_env()
        self.enable_llm_sidecar = (
            llm_sidecar_enabled_from_env() if enable_llm_sidecar is None else enable_llm_sidecar
        )
        self.llm_timeout_ms = llm_timeout_ms_from_env() if llm_timeout_ms is None else llm_timeout_ms

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
        wake_word = self.wake_word_gate.evaluate(turn)
        if wake_word.status == "ignored_missing_wake_word":
            return VoiceInputProcessingResult(
                status="ignored",
                reason=wake_word.reason,
                fast_intent=self._build_wake_word_fast_intent(wake_word=wake_word).to_dict(),
                voice_turn=turn.to_dict(),
                wake_word=wake_word.to_dict(),
            )
        if wake_word.status == "wake_only":
            return VoiceInputProcessingResult(
                status="wake_armed",
                reason=wake_word.reason,
                fast_intent=self._build_wake_word_fast_intent(wake_word=wake_word).to_dict(),
                voice_turn=turn.to_dict(),
                wake_word=wake_word.to_dict(),
            )

        effective_turn = self._apply_wake_word(turn=turn, wake_word=wake_word)
        fast_intent = self.fast_intent_asr.recognize_turn(effective_turn)
        semantic_intent = self.semantic_normalizer.normalize(
            state=state,
            voice_turn=effective_turn,
            fast_intent=fast_intent,
            conversation_context=self.conversation_context,
            primary_message=primary_message,
        )
        route_decision = self.transcript_router.route(
            state=state,
            fast_intent=fast_intent,
            semantic_intent=semantic_intent,
        )
        if route_decision.status != "routed" or route_decision.query_kind is None:
            return VoiceInputProcessingResult(
                status="rejected",
                reason=route_decision.reason,
                fast_intent=fast_intent.to_dict(),
                voice_turn=effective_turn.to_dict(),
                wake_word=wake_word.to_dict(),
                route_decision=route_decision.to_dict(),
            )

        bundle = build_voice_query_bundle(
            state=state,
            voice_turn=effective_turn,
            fast_intent=fast_intent,
            semantic_intent=semantic_intent,
            route_decision=route_decision,
        )
        self.conversation_context.observe_user_query(
            request_id=bundle.input_event["request_id"],
            transcript_text=semantic_intent.normalized_query_text,
            query_kind=semantic_intent.query_kind,
            timestamp_ms=int(bundle.input_event["created_at_ms"]),
            metadata={"reason": semantic_intent.reason},
        )
        bundle = self._apply_llm_sidecar(
            state=state,
            bundle=bundle,
            normalized_query_text=semantic_intent.normalized_query_text,
            route_decision=route_decision,
            primary_message=primary_message,
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
                voice_turn=effective_turn.to_dict(),
                wake_word=wake_word.to_dict(),
                route_decision=route_decision.to_dict(),
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
            voice_turn=effective_turn.to_dict(),
            wake_word=wake_word.to_dict(),
            route_decision=route_decision.to_dict(),
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

    def _apply_llm_sidecar(
        self,
        *,
        state: SessionState,
        bundle: VoiceQueryBundle,
        normalized_query_text: str,
        route_decision: Any,
        primary_message: StrategyMessage | None,
    ) -> VoiceQueryBundle:
        lane = str(getattr(route_decision, "lane", "") or "")
        if lane not in {"explainer", "companion"}:
            return bundle
        if not self.enable_llm_sidecar:
            if lane == "companion":
                return replace(
                    bundle,
                    response_override=self._build_companion_fallback_override(),
                    llm_explainer={
                        "request": None,
                        "result": {
                            "status": "fallback",
                            "backend_name": self.llm_explainer.backend.name,
                            "llm_used": False,
                            "response": None,
                            "fallback_reason": "llm_sidecar_disabled",
                            "duration_ms": 0,
                            "metadata": {"lane": lane},
                        },
                    },
                )
            return bundle
        request = build_llm_explainer_request(
            interaction_session_id=str(bundle.input_event.get("interaction_session_id") or ""),
            turn_id=str(bundle.input_event.get("turn_id") or ""),
            request_id=str(bundle.input_event.get("request_id") or ""),
            normalized_query_text=normalized_query_text,
            route_decision=route_decision,
            state=state,
            primary_message=primary_message,
            conversation_context=self.conversation_context,
            capability_snapshot=(route_decision.metadata or {}).get("capability_check"),
            timeout_ms=self.llm_timeout_ms,
        )
        llm_result = self.llm_explainer.run(request=request)
        if lane == "companion" and llm_result.status != "completed" and llm_result.fallback_reason == "llm_timeout":
            relaxed_timeout_ms = max(int(request.timeout_ms or 0), 3200)
            retry_request = replace(
                request,
                timeout_ms=relaxed_timeout_ms,
                metadata={
                    **dict(request.metadata or {}),
                    "companion_retry": True,
                    "initial_timeout_ms": int(request.timeout_ms or 0),
                },
            )
            llm_result = self.llm_explainer.run(request=retry_request)
            request = retry_request
        response_override = self._build_llm_response_override(
            route_decision=route_decision,
            llm_result=llm_result,
        )
        if response_override is None and lane == "companion":
            response_override = self._build_companion_fallback_override()
        return replace(
            bundle,
            response_override=response_override,
            llm_explainer={
                "request": request.to_dict(),
                "result": llm_result.to_dict(),
            },
        )

    def _build_llm_response_override(
        self,
        *,
        route_decision: Any,
        llm_result: Any,
    ) -> dict[str, Any] | None:
        response = dict(llm_result.response or {})
        if llm_result.status != "completed":
            return None
        if response.get("status") not in {"answerable", "needs_clarification"}:
            return None
        speak_text = render_llm_sidecar_text(str(response.get("answer_text") or ""))
        if not speak_text:
            return None
        action_code = (
            "QUERY_COMPANION_CHAT"
            if getattr(route_decision, "lane", "") == "companion"
            else f"QUERY_{str(route_decision.query_kind or 'LLM_EXPLAINER').upper()}"
        )
        return {
            "speak_text": speak_text,
            "action_code": action_code,
            "source": "llm_sidecar",
            "status": response.get("status"),
            "backend_name": llm_result.backend_name,
            "fallback_reason": llm_result.fallback_reason,
            "confidence": response.get("confidence"),
            "reason_fields": response.get("reason_fields") or [],
            "requires_confirmation": bool(response.get("requires_confirmation", False)),
        }

    def _build_companion_fallback_override(self) -> dict[str, Any]:
        persona = get_default_persona()
        return {
            "speak_text": render_companion_mode_fallback(persona_id=persona.persona_id),
            "action_code": "QUERY_COMPANION_CHAT",
            "source": "companion_fallback",
            "status": "unsupported",
            "backend_name": self.llm_explainer.backend.name,
            "fallback_reason": "companion_llm_unavailable",
            "confidence": 0.0,
            "reason_fields": [],
            "requires_confirmation": False,
        }

    def _apply_wake_word(self, *, turn: VoiceTurn, wake_word: WakeWordResult) -> VoiceTurn:
        if wake_word.status not in {"inline_query", "active_window", "disabled_passthrough"}:
            return turn
        if wake_word.status == "disabled_passthrough":
            return turn
        metadata = dict(turn.metadata)
        metadata["original_transcript_text"] = metadata.get("transcript_text") or ""
        metadata["transcript_text"] = wake_word.transcript_text
        metadata["wake_word"] = wake_word.to_dict()
        return replace(turn, metadata=metadata)

    def _build_wake_word_fast_intent(self, *, wake_word: WakeWordResult) -> FastIntentResult:
        return FastIntentResult(
            lane="wake_word",
            status=wake_word.status,
            transcript_text=wake_word.transcript_text,
            normalized_text=wake_word.normalized_text,
            query_kind=None,
            confidence=1.0 if wake_word.matched_phrase is not None else 0.0,
            matched_phrase=wake_word.matched_phrase,
            metadata={
                "reason": wake_word.reason,
                "activation_expires_at_ms": wake_word.activation_expires_at_ms,
            },
        )
