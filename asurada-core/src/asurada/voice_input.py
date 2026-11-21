from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from typing import Any
import time
from .task_runtime import TaskContext, TaskCancelled
from .delivery_receipt import delivery_receipt
from .delivery_context import DeliveryContext

from .asr_fast import FastIntentASR, FastIntentResult, KeywordFastIntentASR
from .capability_registry import CapabilityRegistry
from .capability_definitions import CAPABILITIES, CONTROL_QUERY_KINDS
from .conversation_context import ConversationContext
from .llm_explainer import (
    LlmExplainer,
    build_llm_explainer_request,
    llm_sidecar_enabled_from_env,
    llm_timeout_ms_from_env,
)
from .models import SessionState, StrategyMessage
from .runtime_context import RuntimeContextDetector
from .output import ConsoleVoiceOutput
from .personality_dialogue import banter_requested
from .personality_runtime import personality_enabled
from .driver_experience import radio_experience_command
from .pit_feedback import pit_feedback_intent
from .fuel_feedback import fuel_feedback_intent
from .speech_clock import speech_time
from .persona_registry import get_default_persona, render_companion_mode_fallback
from .persona_style import render_llm_sidecar_text
from .semantic_normalizer import SemanticNormalizer
from .transcript_router import TranscriptRouter
from .voice_nlu import VoiceQueryBundle, build_voice_query_bundle
from .voice_turn import VoiceTurn
from .radio_grounding import explicit_advice_choice
from .radio_understanding import RaceRadio, radio_intent
from .wake_word import WakeWordGate, WakeWordResult
from .review_voice import ReviewVoiceService




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
    delivery: dict[str, Any] | None = None
    contract_version: str = 'voice-input-v2'

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pit_feedback_provenance(turn, choice):
    """Keep ambiguous audio out of the explicit recommendation evidence."""
    metadata = turn.metadata
    recognition = metadata.get(turn.source, {})
    if not isinstance(recognition, dict):
        recognition = {}
    confidence = recognition.get("confidence", metadata.get("asr_confidence"))
    if (turn.completion_reason == "recognized_partial"
            or confidence is not None and (type(confidence) not in (int, float)
                or not math.isfinite(confidence) or not .65 <= confidence <= 1)):
        return "pit_feedback_asr_not_confident"
    alternative = metadata.get("transcript_hint")
    other = (pit_feedback_intent(alternative) or fuel_feedback_intent(alternative)) if isinstance(alternative, str) else None
    if other is not None and other != choice:
        return "pit_feedback_hypotheses_conflict"
    return None


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
        review_service=None,
        race_radio: RaceRadio | None = None,
    ) -> None:
        self.race_radio = race_radio
        self.fast_intent_asr = fast_intent_asr or KeywordFastIntentASR()
        self.semantic_normalizer = semantic_normalizer or SemanticNormalizer()
        self.conversation_context = conversation_context or ConversationContext()
        self.delivery_context = DeliveryContext()
        self.wake_word_gate = wake_word_gate or WakeWordGate()
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.transcript_router = transcript_router or TranscriptRouter(capability_registry=self.capability_registry)
        self.llm_explainer = llm_explainer or LlmExplainer.from_env()
        self.enable_llm_sidecar = (
            llm_sidecar_enabled_from_env() if enable_llm_sidecar is None else enable_llm_sidecar
        )
        self.llm_timeout_ms = llm_timeout_ms_from_env() if llm_timeout_ms is None else llm_timeout_ms
        self.review_service = review_service if review_service is not None else ReviewVoiceService.from_env()

    def process_completed_turn(
        self, *, state, turn, voice_output, primary_message=None, render=True,
        context: TaskContext | None = None,
    ) -> VoiceInputProcessingResult:
        reserve = getattr(voice_output, "reserve_query_turn", None) if personality_enabled() else None
        try:
            if reserve is not None:
                try:
                    reserve(turn.turn_id, speech_time() + 60)
                except (OSError, RuntimeError, ValueError):
                    pass
            if context is not None:
                context.remaining()
            return self._process_completed_turn(state=state, turn=turn, voice_output=voice_output,
                                                primary_message=primary_message, render=render, context=context)
        except (TaskCancelled, TimeoutError) as exc:
            return VoiceInputProcessingResult(status='cancelled' if isinstance(exc,TaskCancelled) else 'expired',
                reason='voice_turn_cancelled' if isinstance(exc,TaskCancelled) else 'voice_turn_deadline',
                fast_intent={}, voice_turn=turn.to_dict())
        finally:
            if reserve is not None:
                try:
                    reserve(turn.turn_id, None)
                except (OSError, RuntimeError, ValueError):
                    pass

    def _process_completed_turn(
        self,
        *,
        state: SessionState,
        turn: VoiceTurn,
        voice_output: ConsoleVoiceOutput,
        primary_message: StrategyMessage | None = None,
        render: bool = True,
        context: TaskContext | None = None,
    ) -> VoiceInputProcessingResult:
        self.conversation_context.bind(state)
        if not RuntimeContextDetector().detect(state=state).racing_active:
            self.conversation_context.expire_racing()
            primary_message = None
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
        reply = getattr(voice_output, "emit_personality_reply", None)
        text = str(effective_turn.metadata.get("transcript_text") or "")
        radio_command = radio_experience_command(text)
        if personality_enabled() and radio_command:
            try:
                if radio_command == "correct_habit":
                    record = voice_output.correct_last_brake_habit()
                else:
                    record = voice_output.set_radio_preference(radio_command == "enable")
            except (AttributeError, OSError, RuntimeError, ValueError):
                record = {"status": "unavailable", "reason": "radio_experience_delivery_failed"}
            applied = record["status"] == "applied"
            return VoiceInputProcessingResult(
                status="processed" if applied else "rejected",
                reason="radio_experience_applied" if applied else record["reason"],
                fast_intent=fast_intent.to_dict(), voice_turn=effective_turn.to_dict(),
                wake_word=wake_word.to_dict(), output_debug={"radio_experience": record},
            )
        record_feedback = getattr(voice_output, "record_pit_feedback", None)
        choice = pit_feedback_intent(text) or fuel_feedback_intent(text)
        if personality_enabled() and record_feedback is not None and choice:
            issue = _pit_feedback_provenance(effective_turn, choice)
            if issue:
                record = {"status": "rejected", "reason": issue}
            else:
                try:
                    record = record_feedback(state=state, text=text, request_id=turn.turn_id)
                except (AttributeError, OSError, RuntimeError, ValueError):
                    record = {"status": "unavailable", "reason": "pit_feedback_delivery_failed"}
            accepted = record["status"] in ("queued", "already_recorded")
            return VoiceInputProcessingResult(
                status="processed" if accepted else "rejected",
                reason="pit_feedback_received" if accepted else record["reason"],
                fast_intent=fast_intent.to_dict(), voice_turn=effective_turn.to_dict(),
                wake_word=wake_word.to_dict(), output_debug={"pit_feedback": record})
        if personality_enabled() and reply is not None and banter_requested(text):
            debug = reply(state=state, text=text, request_id=turn.turn_id, render=render)
            return VoiceInputProcessingResult(
                status="processed", reason="personality_reply", fast_intent=fast_intent.to_dict(),
                voice_turn=effective_turn.to_dict(), wake_word=wake_word.to_dict(), output_debug=debug,
                delivery=delivery_receipt(debug, turn.turn_id))
        clean = text.strip().strip("。！？,.!?，").strip().lower()
        exact_command = (fast_intent.query_kind in CONTROL_QUERY_KINDS
                         and clean == fast_intent.matched_phrase)
        use_radio = (self.race_radio is not None and text and not exact_command
                     and RuntimeContextDetector().detect(state=state).racing_active
                     and not self.capability_registry.is_disallowed_domain(text))
        if use_radio or fast_intent.query_kind not in CONTROL_QUERY_KINDS:
            budget = min(.1, context.remaining()) if context is not None else .1
            end = time.monotonic() + budget
            health = self.refresh_delivery(state=state, voice_output=voice_output, timeout_s=budget)
            while use_radio and health == "catching_up" and time.monotonic() < end:
                health = self.refresh_delivery(state=state, voice_output=voice_output,
                                               timeout_s=max(.001, end - time.monotonic()))
            if context is not None:
                context.remaining()
        semantic_intent = self.semantic_normalizer.normalize(
            state=state,
            voice_turn=effective_turn,
            fast_intent=fast_intent,
            conversation_context=self.conversation_context,
            primary_message=primary_message,
        )
        if use_radio:
            literal = clean == fast_intent.matched_phrase and semantic_intent.query_kind not in CONTROL_QUERY_KINDS
            # Existing assist commands with their own semantic matcher remain on that path.
            if (semantic_intent.reason == "semantic_normalized" and semantic_intent.query_kind in CONTROL_QUERY_KINDS
                    and semantic_intent.query_kind not in {"stop", "cancel", "repeat_last"}
                    and not any(mark in clean for mark in "，,；;。")):
                literal = True
            if not literal:
                heard = self.delivery_context.radio.values() if self.delivery_context.health == "current" else ()
                interpretation = self.race_radio.interpret(text, state, self.conversation_context, heard, effective_turn, context)
                if context:
                    context.remaining()
                if self.race_radio.latest is not None:
                    latest, latest_message = self.race_radio.latest()
                    if ((latest.session_uid, latest.session_epoch) != (state.session_uid, state.session_epoch)
                            or not RuntimeContextDetector().detect(state=latest).racing_active):
                        return VoiceInputProcessingResult("expired", "radio_session_changed", fast_intent.to_dict(), turn.to_dict())
                    state, primary_message = latest, latest_message
                if interpretation is None:
                    if semantic_intent.query_kind in CONTROL_QUERY_KINDS or semantic_intent.query_kind == "open_fallback":
                        interpretation = dict(act="clarify", topic="other", query="none", anchor=None)
                if interpretation is not None:
                    interpretation = self._validate_radio_choice(interpretation, effective_turn, text, state, record_feedback)
                    semantic_intent = radio_intent(text, interpretation, state)
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
            metadata={"reason": semantic_intent.reason, "lane": route_decision.lane,
                      "radio_act": semantic_intent.metadata.get("radio_act"),
                      "radio_topic": semantic_intent.metadata.get("radio_topic"),
                      "strategy_follow_up_target": semantic_intent.metadata.get("strategy_follow_up_target")},
        )
        if semantic_intent.reason != "local_radio_understanding":
            bundle = self._apply_llm_sidecar(
                state=state, bundle=bundle, normalized_query_text=semantic_intent.normalized_query_text,
                route_decision=route_decision, primary_message=primary_message, context=context,
            )
        if context is not None:
            context.remaining()
        if semantic_intent.query_kind in CONTROL_QUERY_KINDS:
            output_debug = voice_output.emit_control_query_bundle(
                state=state,
                bundle=bundle,
                primary_message=primary_message,
                render=render,
            )
            self._record_response(bundle=bundle, output_debug=output_debug)
            return VoiceInputProcessingResult(
                status="processed",
                reason="control_submission_processed",
                fast_intent=fast_intent.to_dict(),
                voice_turn=effective_turn.to_dict(),
                wake_word=wake_word.to_dict(),
                route_decision=route_decision.to_dict(),
                bundle=bundle.to_dict(),
                output_debug=output_debug,
                delivery=delivery_receipt(output_debug, bundle.input_event['request_id']),
            )

        output_debug = voice_output.emit_voice_query_bundle(
            state=state,
            bundle=bundle,
            primary_message=primary_message,
            render=render,
        )
        self._record_response(bundle=bundle, output_debug=output_debug)
        return VoiceInputProcessingResult(
            status="processed",
            reason="query_submission_processed",
            fast_intent=fast_intent.to_dict(),
            voice_turn=effective_turn.to_dict(),
            wake_word=wake_word.to_dict(),
            route_decision=route_decision.to_dict(),
            bundle=bundle.to_dict(),
            output_debug=output_debug,
            delivery=delivery_receipt(output_debug, bundle.input_event['request_id']),
        )

    @staticmethod
    def _validate_radio_choice(decision, turn, text, state, record_feedback):
        act, topic = decision["act"], decision["topic"]
        if act not in {"hold", "commit", "decline"}:
            return decision
        unclear = dict(act="clarify", topic=topic, query="none", anchor=None)
        choice = {"hold": "defer", "commit": "accept", "decline": "decline"}[act]
        alternative = turn.metadata.get("transcript_hint")
        if (_pit_feedback_provenance(turn, choice) is not None
                or alternative and alternative.strip() != text.strip()):
            return unclear
        if topic in {"attack", "defend"}:
            return decision
        if (topic not in {"pit", "fuel"} or not personality_enabled() or record_feedback is None
                or not explicit_advice_choice(text, topic, choice)):
            return unclear
        anchor = decision.get("anchor") or {}
        identity = anchor.get(topic + "_id")
        if anchor.get("status") != "complete" or not identity:
            return unclear
        try:
            result = record_feedback(state=state, text=text, request_id=turn.turn_id,
                interpretation={"id": identity, "topic": topic, "choice": choice})
        except (OSError, RuntimeError, ValueError):
            return unclear
        return decision if result.get("status") in {"queued", "already_recorded"} else unclear

    def _record_response(self, *, bundle: VoiceQueryBundle, output_debug: dict[str, Any]) -> None:
        receipt = delivery_receipt(output_debug, bundle.input_event['request_id'])
        self.delivery_context.track(bundle, self.conversation_context._scope, receipt['status'] in {'started', 'completed'})
        if receipt['status'] not in {'started', 'completed'}:
            return
        event = ((output_debug.get("output_lifecycle") or {}).get("event") or {})
        self.conversation_context.observe_response(
            request_id=str(bundle.input_event.get("request_id") or "req:unknown"),
            query_kind=str(bundle.structured_query.get("query_kind") or ""),
            action_code=event.get("action_code"),
            speak_text=event.get("speak_text"),
            timestamp_ms=int(bundle.input_event.get("created_at_ms") or 0),
                metadata={"event_type": event.get("event_type"), "delivery_status": receipt['status'], "reason": (event.get("metadata") or {}).get("reason")},
        )

    def refresh_delivery(self, *, state, voice_output, timeout_s=.1):
        self.conversation_context.bind(state)
        self.delivery_context.refresh(voice_output, self.conversation_context, (state.session_uid, state.session_epoch), timeout_s=timeout_s)
        return self.delivery_context.health

    def _apply_llm_sidecar(
        self,
        *,
        state: SessionState,
        bundle: VoiceQueryBundle,
        normalized_query_text: str,
        route_decision: Any,
        primary_message: StrategyMessage | None,
        context: TaskContext | None = None,
    ) -> VoiceQueryBundle:
        lane = str(getattr(route_decision, "lane", "") or "")
        if lane == 'companion' and self.review_service is not None and self.review_service.accepts(normalized_query_text):
            task = context or TaskContext.start(str(bundle.input_event['request_id']), self.llm_timeout_ms)
            try:
                analysis = self.review_service.analyze(question=normalized_query_text,
                    request_id=str(bundle.input_event['request_id']), context=task)
                task.remaining()
                if analysis['status'] in {'cancelled', 'expired'}:
                    if analysis['status'] == 'cancelled': raise TaskCancelled(task.task_id)
                    raise TimeoutError(task.task_id)
                text = (analysis.get('answer') or {}).get('text') if analysis['status'] in {'completed', 'insufficient_data'} else None
                text = text or '这次复盘分析未能完成，请稍后重试。'
            except (ValueError, KeyError, PermissionError) as exc:
                analysis = {'status': 'rejected', 'error': {'type': type(exc).__name__}}
                text = '当前复盘数据不可用，请检查所选复盘和访问权限。'
            return replace(bundle, response_override={'speak_text': text, 'action_code': 'QUERY_REVIEW_ANALYSIS',
                'source': 'review_analysis', 'status': analysis['status'], 'requires_confirmation': False},
                llm_explainer={'request': None, 'result': analysis})
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
        spec = CAPABILITIES.get(route_decision.query_kind) if lane == "explainer" else None
        timeout_ms = min(self.llm_timeout_ms, spec.deadline_ms) if spec is not None else self.llm_timeout_ms
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
            timeout_ms=timeout_ms,
        )
        if context is None:
            llm_result = self.llm_explainer.run(request=request)
        else:
            child = TaskContext(context.task_id, min(context.deadline, time.monotonic()+request.timeout_ms/1000), context.cancellation)
            llm_result = self.llm_explainer.run(request=request, context=child)
            context.remaining()
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
            "claims": response.get('claims') or [],
            "claim_metadata": response.get('metadata') or {},
            "claim_answer_text": response.get('answer_text') or '',
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
