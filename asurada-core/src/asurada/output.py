"""Compatibility facade and the single owner of speech queue/session state.

Adapters only prepare inputs and evidence; this class owns locking, arbitration,
backend handles, cancellation acknowledgement and session retirement.
"""
from __future__ import annotations
from .retired_identities import RetiredIdentities
from .capability_definitions import capability_speech_priority
from dataclasses import asdict, dataclass, field
from collections import deque
import time
from .speech_clock import speech_time
from .wheel_telemetry import TYRE_DAMAGE, TYRE_WEAR_ALERT, TYRE_DAMAGE_WARNING_PCT, tyre_alert, tyre_damage_values
from .defence_radio import DefenceRadio
from .wing_damage import (
    FRONT_WING_DAMAGE, FRONT_WING_ENTRY_COMPENSATION, FRONT_WING_WARNING_PCT, SIDES, approaching_wing_corner,
    compensation_allowed, has_wing_compensation, wing_advice_current, wing_radio_text, wing_values,
)
import threading
from functools import wraps
from contextlib import contextmanager
from typing import Any
from .analysis import LapAnalysisSummary, SegmentAnalysis
from .attack_mode import AttackModeController
from .attack_opportunity import validate_attack_cue
from .brake_point_assist import BrakePointAssistController
from .corner_gear_assist import CornerGearAssistController
from .interaction import (
    InteractionInputEvent,
    OutputLifecycleEvent,
    SpeechJob,
    StructuredQuerySchema,
    build_asr_stage_event,
    build_confirmation_policy,
    build_query_normalization_event,
    build_snapshot_query_input_event,
    build_structured_query_schema,
    build_task_handle,
    build_task_lifecycle_event,
    build_tts_stage_event,
    render_structured_query_response,
    route_structured_query,
)
from .models import SessionState, StrategyDecision, StrategyMessage
from .persona_registry import get_default_persona
from .personality_llm import PersonalityLlm, PersonalityLlmRequest, SUPPORTED_OPPORTUNITIES
from .pit_feedback import PitFeedbackTracker
from .tts_backends import (
    MacOSSayBackend,
    NullSpeechBackend,
    PiperBackend,
    PiperBackendConfig,
    SpeechBackend,
    resolve_default_speech_backend,
)
from .output_contracts import EPISODE_CUES, EPISODE_RECOVERY, _SpeechEnvelope, _OutputProcessingResult, _serialized
from .output_lap import ConsoleLapSummaryOutput
from .output_envelopes import OutputEnvelopeBuilder
from .output_queries import OutputQueryAdapter
from .output_controls import OutputControlAdapter
from .output_events import OutputEventRenderer


class ConsoleVoiceOutput(OutputEnvelopeBuilder, OutputQueryAdapter, OutputControlAdapter, OutputEventRenderer):
    """Temporary stand-in for voice copilot and HUD output.

    备注:
    控制台输出同时承担当前阶段的策略调试视图。
    当策略引擎完成分层推理后，这里会把“状态评估 -> 风险评分 ->
    候选策略 -> 最终播报”按可读格式打印出来，便于快速校验策略逻辑。
    """


    def __init__(self, *, backend: SpeechBackend | None = None, pit_feedback: PitFeedbackTracker | None = None,
                 personality_llm: PersonalityLlm | None = None) -> None:
        from .speech_events import SpeechEventStream
        self._event_stream = SpeechEventStream()
        self._output_lock = threading.RLock()
        self.output_session_id = "voice-output:console"
        self.backend = backend or self._default_backend()
        self.persona = get_default_persona()
        self._event_counter = 0
        self._session_scope = None
        # Preserve every retired UID; spill to disk after the memory bound.
        self._retired_sessions = RetiredIdentities()
        self.session_events = []
        self._active_envelope: _SpeechEnvelope | None = None
        self._active_handle: Any = None
        self.playback_health = {"status": "current", "error_type": None, "consecutive_failures": 0}
        self._pending_envelope: _SpeechEnvelope | None = None
        self._last_completed_envelope: _SpeechEnvelope | None = None
        self._repeatable_history: deque[_SpeechEnvelope] = deque(maxlen=8)
        self._last_fuel_broadcast_at: float | None = None
        self._driver_attack_choice = None
        self._announced_episodes: dict[str, float | None] = {}
        self._wing_completed: dict[str, float] = {}
        self._wing_corner_completed: dict[tuple[str, bool], float] = {}
        self._wing_clear_samples: dict[str, int] = {}
        self._last_repeat_state = None
        self._microphone_status = ("unknown", 0.)
        self._brake_point_assist = BrakePointAssistController()
        self._corner_gear_assist = CornerGearAssistController()
        self._attack_mode = AttackModeController()
        self._defence_radio = DefenceRadio()
        self._submission_guard = None
        self._query_turns: dict[str, float] = {}
        self.personality_live = False
        self.pit_feedback = pit_feedback
        from .personality_dialogue import PersonalityDialogue
        from .driver_experience import RadioExperience
        self._personality_dialogue = PersonalityDialogue()
        self._radio_experience = RadioExperience.from_env()
        self._personality_llm = personality_llm if personality_llm is not None else PersonalityLlm()
        self._personality_generation: _SpeechEnvelope | None = None



    @contextmanager
    def submission_guard(self, guard):
        """Bind validation to newly submitted work while preserving queued work."""
        with self._output_lock:
            previous = self._submission_guard
            self._submission_guard = guard
            try:
                yield
            finally:
                self._submission_guard = previous


    @_serialized
    def bind_session(self, state: SessionState) -> bool:
        scope = (state.session_uid, state.session_epoch)
        previous = self._session_scope
        invalid=isinstance(scope[1],bool) or not isinstance(scope[1],int) or scope[1]<0
        stale=not invalid and previous is not None and ((scope[0]==previous[0] and scope[1]<previous[1]) or (scope[0]!=previous[0] and scope[0] in self._retired_sessions))
        if invalid or stale:
            self.session_events.append({"contract_version":"session-event-v1","type":"speech_scope_rejected","current":previous,"incoming":scope,"reason":"invalid_or_stale_scope"})
            self.session_events[:]=self.session_events[-32:]
            return False
        if self._session_scope == scope:
            return True
        previous = self._session_scope
        if previous is not None and previous[0]!=scope[0]:
            self._retired_sessions.add(previous[0])
        self._session_scope = scope
        self._radio_experience.bind(scope)
        self._cancel_personality_generation("session_scope_changed")
        if self.pit_feedback is not None:
            self.pit_feedback.end("session_scope_changed")
        self._personality_dialogue.bind(replay=not self.personality_live)
        if previous is None:
            return True
        event = {"contract_version": "session-event-v1", "type": "speech_scope_changed",
                 "previous": previous, "current": scope, "cancelled_pending": None,
                 "active_stop_requested": None}
        if self._pending_envelope is not None:
            event["cancelled_pending"] = self._pending_envelope.job.output_event_id
            self._publish_transition(self._pending_envelope, "cancel", "session_scope_changed")
            self._pending_envelope = None
        self._last_completed_envelope = None
        self._repeatable_history.clear()
        self._last_fuel_broadcast_at = None
        self._driver_attack_choice = None
        self._announced_episodes.clear()
        self._wing_completed.clear()
        self._wing_corner_completed.clear()
        self._wing_clear_samples.clear()
        self._last_repeat_state = None
        self._brake_point_assist = BrakePointAssistController()
        self._corner_gear_assist = CornerGearAssistController()
        self._attack_mode = AttackModeController()
        self._defence_radio = DefenceRadio()
        if self._active_envelope is not None:
            self._active_envelope.job.metadata["cancel_requested"] = True
            self._active_envelope.job.metadata["cancel_reason"] = "session_scope_changed"
            event["active_stop_requested"] = self._active_envelope.job.output_event_id
            self._request_stop_confirmation(self._active_envelope)
            self._publish_transition(self._active_envelope, "cancel_requested", "session_scope_changed")
            # Keep ownership until _poll_completed_active sees actual completion.
        self.session_events.append(event)
        self.session_events[:] = self.session_events[-32:]
        return True


    def _scope_rejection(self):
        debug={}
        event=self._build_event_from_envelope(None,"suppress",metadata={"reason":"stale_session_scope"})
        self._write_debug_payload(debug=debug,result=_OutputProcessingResult(lifecycle_event=event,event_envelope=None))
        return debug


    @_serialized
    def emit(self, decision: StrategyDecision, *, state: SessionState | None = None, render: bool = True) -> dict:
        """Emit one lifecycle-aware output step and return the lifecycle event."""

        if state is not None and not self.bind_session(state):
            rejected=self._scope_rejection()
            decision.debug.update(rejected)
            return rejected["output_lifecycle"]
        if state is not None:
            if self._driver_attack_choice and self._attack_subject(state) != self._driver_attack_choice[0]:
                self._driver_attack_choice = None
            self._update_wing_recovery(state)
            self._last_repeat_state = state
            active = self._active_envelope
            if (active is not None and has_wing_compensation(active.job)
                    and not wing_advice_current(state, active.job, playing=True)):
                self._request_personality_stop(active, "wing_compensation_no_longer_applicable")
            self._radio_experience.observe(state, decision.messages[0].code if decision.messages else "NONE")
            self._personality_dialogue.observe_pit_advice(state, live=self.personality_live)
            if self.pit_feedback is not None and not self.personality_live:
                self.pit_feedback.observe(state)
            previous = self._last_completed_envelope
            if (previous is not None and previous.job.metadata.get("tyre_pit_original")
                    and self._personality_dialogue.pit_advice.withdraws_repeat()):
                self._last_completed_envelope = None
        if state is not None and self._announced_episodes:
            current_code = decision.messages[0].code if decision.messages else None
            self._observe_cue_recovery(state, current_code)
        interaction_input_event = decision.debug.get("interaction_input_event", {}) or {}
        task_handle = decision.debug.get("task_handle", {}) or {}
        arbiter_output = (decision.debug.get("arbiter_v2", {}) or {}).get("output", {}) or {}
        final_voice_action = arbiter_output.get("final_voice_action") or {}
        envelope = self._build_strategy_envelope(
            decision=decision,
            interaction_input_event=interaction_input_event,
            task_handle=task_handle,
            final_voice_action=final_voice_action,
            state=state,
        )
        if envelope is not None and envelope.job.action_code == FRONT_WING_DAMAGE:
            title = decision.messages[0].title
            sides = tuple(side for side, label in SIDES.items() if label in title)
            levels = wing_values(state) if state is not None else {}
            reported = {side: levels[side] for side in sides if levels.get(side) is not None}
            active = self._active_envelope
            active_meta = active.job.metadata if active and not active.job.metadata.get("cancel_requested") else {}
            in_flight = {side: active_meta["wing_levels"][side]
                         for side in active_meta.get("wing_report_sides", ())}
            new_sides = tuple(side for side, value in reported.items()
                              if value > max(self._wing_completed.get(side, -1), in_flight.get(side, -1)))
            covered = not new_sides
            corner = approaching_wing_corner(state)
            compensation = corner is not None and corner["high_speed"]
            if compensation:
                radio_clear = (self._active_envelope is None and self._pending_envelope is None
                               and not self.query_busy() and compensation_allowed(state, corner))
                if not radio_clear or (not covered and (len(new_sides) != 1
                                                       or approaching_wing_corner(state, combined=True) != corner)):
                    corner = None
                    compensation = False
            needs_corner = (corner is not None and not in_flight and all(
                value <= self._wing_completed.get(side, -1) for side, value in reported.items()
            ) and any(value > self._wing_corner_completed.get((side, corner["high_speed"]), -1)
                      for side, value in reported.items()))
            if not sides or len(reported) != len(sides) or (covered and not needs_corner):
                envelope = None
            else:
                relevant_sides = sides if corner is not None else new_sides
                envelope.job.metadata.update(wing_sides=relevant_sides,
                                             wing_levels={side: reported[side] for side in relevant_sides},
                                             wing_report_sides=new_sides, wing_corner=corner)
                if corner is None:
                    envelope.job.metadata["semantic_subject"] = tuple((side, reported[side]) for side in new_sides)
                envelope.job.speak_text = wing_radio_text(new_sides or sides, corner, levels=reported, corner_only=covered)
                if compensation:
                    if covered:
                        envelope.job.action_code = FRONT_WING_ENTRY_COMPENSATION
                    else:
                        envelope.job.metadata["wing_compensation"] = "combined"
                    envelope.job.priority = 60
                    envelope.job.metadata["interrupt"] = False
                    envelope.job.metadata["repeatable"] = False
        if state is not None and "defence_forecast" in decision.debug:
            defence = self._build_defence_envelope(state, decision, interaction_input_event, task_handle)
            if defence is not None and (envelope is None or defence.rank > envelope.rank):
                envelope = defence
        brake_assist_envelope = None
        corner_gear_envelope = None
        attack_mode_envelope = None
        if state is not None:
            brake_assist_envelope = self._build_brake_point_assist_envelope(
                state=state,
                interaction_input_event=interaction_input_event,
                task_handle=task_handle,
            )
            corner_gear_envelope = self._build_corner_gear_assist_envelope(
                state=state,
                interaction_input_event=interaction_input_event,
                task_handle=task_handle,
            )
            attack_mode_envelope = self._build_attack_mode_envelope(
                state=state,
                decision=decision,
                interaction_input_event=interaction_input_event,
                task_handle=task_handle,
            )
        if brake_assist_envelope is not None and (
            envelope is None or brake_assist_envelope.rank > envelope.rank
        ):
            envelope = brake_assist_envelope
        if corner_gear_envelope is not None and (
            envelope is None or corner_gear_envelope.rank > envelope.rank
        ):
            envelope = corner_gear_envelope
        if attack_mode_envelope is not None and (
            envelope is None or attack_mode_envelope.rank > envelope.rank
        ):
            envelope = attack_mode_envelope
        if state is not None:
            if (envelope is None or envelope.rank[0] < 3) and not self._personality_dialogue.context_current(
                    state, live=self.personality_live):
                self._cancel_optional_personality("personality_context_changed")
            generation = self._personality_generation
            if generation is not None and not self._generation_matches(generation, state):
                self._cancel_personality_generation("personality_opportunity_changed")
            if (envelope is None and not decision.debug.get("pit_broadcast_muted")
                    and final_voice_action.get("code") in {"NONE", "BOX_WINDOW"}
                    and self._active_envelope is None and self._pending_envelope is None and not self.query_busy()):
                envelope = self._personality_dialogue.pit_follow_up(
                    state, event=interaction_input_event, task=task_handle,
                    output_id=self._next_output_event_id, persona=self.persona)
            if (envelope is None and not self._personality_dialogue.quiet and not self.query_busy()
                    and self._active_envelope is None and self._pending_envelope is None):
                envelope = self._radio_experience.build_envelope(
                    state, live=self.personality_live, event=interaction_input_event, task=task_handle,
                    output_id=self._next_output_event_id, persona=self.persona)
            if envelope is None:
                envelope = self._build_personality_opportunity(state, interaction_input_event, task_handle)
                if envelope is not None and self._begin_personality_generation(envelope):
                    envelope = None
        result = self._process_submission(
            submitted_envelope=envelope,
            fallback_input_event=interaction_input_event,
            fallback_task_handle=task_handle,
        )
        self._write_debug_payload(
            debug=decision.debug,
            result=result,
        )
        pipeline_log = decision.debug.setdefault("voice_pipeline_log", {})
        lifecycle_event = result.lifecycle_event

        if lifecycle_event.event_type == "idle":
            if render:
                print("[ASURADA] 状态稳定，无高优先级播报。")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type == "complete":
            if render:
                print(f"[ASURADA][COMPLETE] {lifecycle_event.action_code}")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type in {"suppress", "failed", "silent"}:
            if render:
                print(f"[ASURADA][{lifecycle_event.event_type.upper()}] {lifecycle_event.action_code}: {lifecycle_event.metadata.get('reason', lifecycle_event.event_type)}")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type == "enqueue":
            if render:
                print(f"[ASURADA][QUEUE] {lifecycle_event.action_code}")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type == "replace_pending":
            if render:
                print(f"[ASURADA][QUEUE-REPLACE] {lifecycle_event.action_code}")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type == "cancel":
            if render:
                print(f"[ASURADA][CANCEL] {lifecycle_event.action_code}")
            return decision.debug["output_lifecycle"]

        if lifecycle_event.action_code.startswith("PERSONALITY_") or not decision.messages:
            if render and lifecycle_event.event_type == "start":
                print(f"[ASURADA][PERSONALITY] {lifecycle_event.speak_text}")
            return decision.debug["output_lifecycle"]
        top = decision.messages[0]
        prefix = f"P{top.priority}"
        if render:
            print(f"[ASURADA][{prefix}] {top.title}: {top.detail}")
            for extra in decision.messages[1:3]:
                print(f"  - {extra.title}: {extra.detail}")
            self._emit_debug(decision)
        return decision.debug["output_lifecycle"]


    def _default_backend(self) -> SpeechBackend:
        return resolve_default_speech_backend()


    @_serialized
    def _process_submission(
        self,
        *,
        submitted_envelope: _SpeechEnvelope | None,
        fallback_input_event: dict[str, Any],
        fallback_task_handle: dict[str, Any],
    ) -> _OutputProcessingResult:
        if submitted_envelope is not None:
            if not submitted_envelope.job.metadata.get("optional_personality") or submitted_envelope.rank[0] > 0:
                self._cancel_personality_generation("higher_priority_submission")
            if self._submission_guard is not None:
                submitted_envelope.start_guard = self._submission_guard
        if submitted_envelope is not None and self._session_scope is not None:
            submitted_envelope.job.metadata["session_scope"] = self._session_scope
        completed_event_published = False
        expired_pending = None
        if self._pending_envelope is not None and self._expired(self._pending_envelope):
            expired_pending = self._pending_envelope
            self._pending_envelope = None
            if submitted_envelope is not None:
                self._publish_transition(expired_pending, "cancel", "expired_before_start")
        if submitted_envelope is not None and self._expired(submitted_envelope):
            return _OutputProcessingResult(
                lifecycle_event=self._build_event_from_envelope(submitted_envelope, "cancel", metadata={"reason": "expired_before_start"}),
                event_envelope=submitted_envelope,
            )
        pending = self._pending_envelope
        if pending is not None and submitted_envelope is not None:
            old, new = pending.job, submitted_envelope.job
            if (self._ordinary_wing(old) and self._ordinary_wing(new)
                    and old.metadata["wing_levels"] != new.metadata["wing_levels"]):
                # The new candidate carries the latest confirmed sides and its
                # own authoritative snapshot. Keep the queue's original expiry.
                submitted_envelope.created_monotonic = pending.created_monotonic
                self._pending_envelope = submitted_envelope
                self._publish_transition(pending, "cancel", "wing_report_updated_before_start")
                self._publish_transition(submitted_envelope, "replace_pending", "wing_report_updated_before_start")
                submitted_envelope = None
        active = self._active_envelope
        if (submitted_envelope is not None and active is not None
                and not (self._wing_job(active.job) and self._wing_job(submitted_envelope.job))
                and (submitted_envelope.rank[0] == 4 or submitted_envelope.job.metadata.get("interrupt")
                     or (has_wing_compensation(active.job) and submitted_envelope.rank[0] >= 3)
                     or active.job.metadata.get("optional_personality") and not submitted_envelope.job.metadata.get("optional_personality"))
                and submitted_envelope.rank > active.rank and active.job.cancelable
                and submitted_envelope.dedup_key != active.dedup_key):
            active.job.metadata.setdefault("stop_requested_at", speech_time())
            active.job.metadata["cancel_requested"] = True
            active.job.metadata["cancel_reason"] = "preempted_by_higher_priority"
            # Retain ownership until the backend confirms it stopped.
            if self._request_stop_confirmation(active):
                self._active_envelope = None
                self._active_handle = None
                return _OutputProcessingResult(
                    lifecycle_event=self._start_envelope(submitted_envelope),
                    event_envelope=submitted_envelope,
                    cancelled_output_event=self._build_event_from_envelope(active, "cancel", metadata={"reason": "preempted_by_higher_priority"}),
                    cancelled_envelope=active,
                )
            self._publish_transition(active, "cancel_requested", "preempted_by_higher_priority")
        completed_envelope = self._poll_completed_active()
        completed_output_event = self._build_event_from_envelope(completed_envelope,
            "cancel" if completed_envelope.job.metadata.get("cancel_requested") else
            "failed" if completed_envelope.job.metadata.get("playback_error") else "complete",
            metadata={"reason": completed_envelope.job.metadata["playback_error"]} if completed_envelope.job.metadata.get("playback_error") else None,
        ) if completed_envelope is not None else None
        auto_started_envelope = None
        auto_started_event = None

        if (self._active_envelope is None and self._pending_envelope is not None
                and (submitted_envelope is None or self._pending_envelope.rank >= submitted_envelope.rank)):
            pending_to_start = self._pending_envelope
            self._pending_envelope = None
            auto_started_envelope = pending_to_start
            auto_started_event = self._start_envelope(pending_to_start)
            if submitted_envelope is not None:
                # This submission's result describes the new request, so retain
                # the older completion/start before returning that result.
                if completed_output_event is not None:
                    self._event_stream.append(completed_output_event.to_dict())
                    completed_event_published = True
                self._event_stream.append(auto_started_event.to_dict())

        if submitted_envelope is None:
            if expired_pending is not None and auto_started_event is None:
                return _OutputProcessingResult(
                    lifecycle_event=self._build_event_from_envelope(expired_pending, "cancel", metadata={"reason": "expired_before_start"}),
                    event_envelope=expired_pending,
                    completed_output_event=completed_output_event, completed_event_published=completed_event_published, completed_envelope=completed_envelope,
                )
            if auto_started_event is not None and auto_started_envelope is not None:
                return _OutputProcessingResult(
                    lifecycle_event=auto_started_event,
                    event_envelope=auto_started_envelope,
                    completed_output_event=completed_output_event, completed_event_published=completed_event_published,
                    completed_envelope=completed_envelope,
                )
            if completed_output_event is not None:
                return _OutputProcessingResult(
                    lifecycle_event=completed_output_event,
                    event_envelope=completed_envelope,
                    completed_output_event=completed_output_event, completed_event_published=completed_event_published,
                    completed_envelope=completed_envelope,
                )
            return _OutputProcessingResult(
                lifecycle_event=self._build_fallback_event(
                    event_type="idle",
                    input_event=fallback_input_event,
                    task_handle=fallback_task_handle,
                    action_code=self._active_action_code() or "NONE",
                    metadata={"reason": "no_submission"},
                ),
                event_envelope=None,
            )

        if submitted_envelope.job.metadata.get("optional_personality") and (
                self._active_envelope is not None or self._pending_envelope is not None
                or submitted_envelope.rank[0] == 0 and self.query_busy()):
            return _OutputProcessingResult(
                lifecycle_event=self._build_event_from_envelope(
                    submitted_envelope, "suppress", metadata={"reason": "optional_speech_busy"}),
                event_envelope=submitted_envelope,
                completed_output_event=completed_output_event, completed_event_published=completed_event_published,
                completed_envelope=completed_envelope,
            )

        if self._is_duplicate_submission(submitted_envelope):
            return _OutputProcessingResult(
                lifecycle_event=self._build_event_from_envelope(
                    submitted_envelope,
                    "suppress",
                    metadata={"reason": "duplicate_active_or_pending_submission", "source_kind": submitted_envelope.job.source_kind},
                ),
                event_envelope=submitted_envelope,
                completed_output_event=completed_output_event, completed_event_published=completed_event_published,
                completed_envelope=completed_envelope,
            )

        if self._active_envelope is None:
            return _OutputProcessingResult(
                lifecycle_event=self._start_envelope(submitted_envelope),
                event_envelope=submitted_envelope,
                completed_output_event=completed_output_event, completed_event_published=completed_event_published,
                completed_envelope=completed_envelope,
            )

        if self._pending_envelope is None:
            self._pending_envelope = submitted_envelope
            return _OutputProcessingResult(
                lifecycle_event=self._build_event_from_envelope(
                    submitted_envelope,
                    "enqueue",
                    metadata={"source_kind": submitted_envelope.job.source_kind},
                ),
                event_envelope=submitted_envelope,
                completed_output_event=completed_output_event, completed_event_published=completed_event_published,
                completed_envelope=completed_envelope,
            )

        if submitted_envelope.rank > self._pending_envelope.rank:
            cancelled_envelope = self._pending_envelope
            cancelled_output_event = self._build_event_from_envelope(
                cancelled_envelope,
                "cancel",
                metadata={"reason": "replaced_by_higher_priority_pending", "source_kind": cancelled_envelope.job.source_kind},
            )
            self._pending_envelope = submitted_envelope
            return _OutputProcessingResult(
                lifecycle_event=self._build_event_from_envelope(
                    submitted_envelope,
                    "replace_pending",
                    metadata={
                        "source_kind": submitted_envelope.job.source_kind,
                        "replaced_output_event_id": cancelled_envelope.job.output_event_id,
                    },
                ),
                event_envelope=submitted_envelope,
                completed_output_event=completed_output_event, completed_event_published=completed_event_published,
                completed_envelope=completed_envelope,
                cancelled_output_event=cancelled_output_event,
                cancelled_envelope=cancelled_envelope,
            )

        return _OutputProcessingResult(
            lifecycle_event=self._build_event_from_envelope(
                submitted_envelope,
                "suppress",
                metadata={"reason": "lower_priority_than_pending", "source_kind": submitted_envelope.job.source_kind},
            ),
            event_envelope=submitted_envelope,
            completed_output_event=completed_output_event, completed_event_published=completed_event_published,
            completed_envelope=completed_envelope,
        )


    @_serialized
    def is_playing(self) -> bool:
        return self.playback_status()['status'] != 'idle'


    @_serialized
    def playback_status(self) -> dict:
        if self._active_envelope is None:
            return {'version': 'playback-status-v1', 'status': 'idle', 'error_type': None}
        try:
            active = self.backend.is_active(self._active_handle)
        except Exception as exc:
            return {'version': 'playback-status-v1', 'status': 'unknown', 'error_type': type(exc).__name__}
        return {'version': 'playback-status-v1', 'status': 'playing' if active else 'idle', 'error_type': None}


    @_serialized
    def shutdown(self, timeout_s: float = 1.0) -> bool:
        """Discard pending work and wait briefly for actual playback termination."""
        self._cancel_personality_generation("shutdown")
        self._radio_experience.cancel()
        self._personality_llm.close()
        if self._pending_envelope is not None:
            self._publish_transition(self._pending_envelope, "cancel", "shutdown")
        self._pending_envelope = None
        if self._active_envelope is None:
            return True
        self._active_envelope.job.metadata["cancel_requested"] = True
        self._active_envelope.job.metadata["cancel_reason"] = "shutdown"
        active = self._active_envelope
        stopped = self._request_stop_confirmation(active)
        self._publish_transition(active, "cancel_requested", "shutdown")
        deadline = time.monotonic() + max(timeout_s, 0)
        while not stopped and time.monotonic() < deadline:
            stopped = self._poll_completed_active() is not None
            if stopped:
                break
            time.sleep(.01)
        if not stopped:
            return False
        self._publish_transition(active, "cancel", "shutdown")
        self._active_envelope = None
        self._active_handle = None
        return True


    def _request_stop_confirmation(self, envelope) -> bool:
        envelope.job.metadata.pop('stop_error_type', None)
        try:
            self.backend.stop(self._active_handle)
            return not self.backend.is_active(self._active_handle)
        except Exception as exc:
            envelope.job.metadata['stop_error_type'] = type(exc).__name__
            return False


    def _publish_transition(self, envelope, event_type, reason):
        """Publish ownership transitions that do not produce a submission debug result."""
        self._event_stream.append(self._build_event_from_envelope(
            envelope, event_type, metadata={"reason": reason}).to_dict())


    def _expired(self, envelope: _SpeechEnvelope) -> bool:
        if envelope.job.metadata.get("defence_window"):
            return time.monotonic() - envelope.created_monotonic >= 1.0
        ttl_s = 2.0 if envelope.job.metadata.get("optional_personality") else (
            3.0 if envelope.job.source_kind == "strategy_broadcast" else 15.0)
        return time.monotonic() - envelope.created_monotonic >= ttl_s


    @_serialized
    def tick(self) -> dict[str, Any]:
        """Advance completion/expiry without submitting a new telemetry message."""
        result = self._process_submission(submitted_envelope=self._poll_personality_generation(),
                                          fallback_input_event={}, fallback_task_handle={})
        debug: dict[str, Any] = {}
        self._write_debug_payload(debug=debug, result=result)
        return debug["output_lifecycle"]


    def read_events(self, *, cursor=None, limit=64, timeout_s=.1):
        import math
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError('invalid_event_read_timeout')
        if not self._output_lock.acquire(timeout=timeout_s):
            raise TimeoutError('speech_event_reader_busy')
        try:
            return self._event_stream.read(cursor=cursor, limit=limit)
        finally:
            self._output_lock.release()


    def _poll_completed_active(self) -> _SpeechEnvelope | None:
        if self._active_envelope is None:
            return None
        try:
            active = self.backend.is_active(self._active_handle)
        except Exception as exc:
            self.playback_health = {"status": "unknown", "error_type": type(exc).__name__,
                "consecutive_failures": self.playback_health['consecutive_failures'] + 1}
            # A failed observation is not proof that the player stopped.
            return None
        self.playback_health = {"status": "current", "error_type": None, "consecutive_failures": 0}
        if active:
            return None
        completed = self._active_envelope
        if not completed.job.metadata.get("cancel_requested"):
            try:
                error = self.backend.completion_error(self._active_handle)
            except Exception:
                error = 'backend_result_unavailable'
            if error:
                completed.job.metadata['playback_error'] = error
        self._active_envelope = None
        self._active_handle = None
        if not completed.job.metadata.get("cancel_requested") and not completed.job.metadata.get("playback_error"):
            if (completed.job.action_code in {FRONT_WING_DAMAGE, FRONT_WING_ENTRY_COMPENSATION}
                    and self._last_repeat_state is not None):
                current = wing_values(self._last_repeat_state)
                for side, value in completed.job.metadata.get("wing_levels", {}).items():
                    if current.get(side) is not None and current[side] >= FRONT_WING_WARNING_PCT:
                        if side in completed.job.metadata.get("wing_report_sides", ()):
                            self._wing_completed[side] = max(value, self._wing_completed.get(side, -1))
                        corner = completed.job.metadata.get("wing_corner")
                        if corner:
                            key = (side, corner["high_speed"])
                            self._wing_corner_completed[key] = max(value, self._wing_corner_completed.get(key, -1))
            self._personality_dialogue.completed(completed.job)
            self._radio_experience.completed(completed.job)
            self._attack_mode.on_completed(completed.job)
            if self.pit_feedback is not None:
                self.pit_feedback.playback_completed(completed.job)
            if completed.job.metadata.get("repeatable", completed.rank[0] > 0):
                self._last_completed_envelope = completed
                self._repeatable_history.append(completed)
        return completed

    def _attack_subject(self, state):
        from .attack_opportunity import front_target
        rival = front_target(state)
        if rival is not None:
            return state.session_uid, state.session_epoch, state.lap_number, rival.car_index
        return None

    def attack_deferred(self, state):
        subject = self._attack_subject(state)
        return (subject is not None and self._driver_attack_choice is not None
                and self._driver_attack_choice[0] == subject and self._driver_attack_choice[2] in {"hold", "decline"})

    def observe_attack_choice(self, state, meta, timestamp):
        act = meta.get("radio_act")
        if meta.get("radio_topic") != "attack" or act not in {"hold", "decline", "commit"}:
            return
        subject = self._attack_subject(state)
        if subject is None or not isinstance(timestamp, int):
            return
        if self._driver_attack_choice and timestamp < self._driver_attack_choice[1]:
            return
        self._driver_attack_choice = subject, timestamp, act
        pending = self._pending_envelope
        if (act != "commit" and pending is not None
                and pending.job.action_code in {"ATTACK_MODE_FORMING", "ATTACK_MODE_REMINDER","ATTACK_WINDOW","ATTACK_FORECAST"}):
            self._pending_envelope = None
            self._publish_transition(pending, "cancel", "driver_deferred_attack")

    def _update_wing_recovery(self, state):
        for side in tuple(self._wing_completed):
            value = wing_values(state).get(side)
            if value is None or value >= FRONT_WING_WARNING_PCT:
                self._wing_clear_samples.pop(side, None)
                continue
            earlier = self._wing_clear_samples.setdefault(side, state.source_timestamp_ms)
            if earlier < state.source_timestamp_ms:
                del self._wing_completed[side]
                self._wing_corner_completed.pop((side, False), None)
                self._wing_corner_completed.pop((side, True), None)
                del self._wing_clear_samples[side]

    def _repeat_still_applicable(self, job, state) -> bool:
        if state is None:
            return True
        scope = job.metadata.get("session_scope")
        if scope is not None and scope != (state.session_uid, state.session_epoch):
            return False
        if self.personality_live and not 0 <= time.time() * 1000 - state.source_timestamp_ms <= 1500:
            return False
        if job.source_kind != "strategy_broadcast":
            return True
        if job.metadata.get("tyre_pit_original") and self._personality_dialogue.pit_advice.withdraws_repeat():
            return False
        record = state.decision_record
        if job.action_code == "LOCAL_YELLOW":
            return state.raw.get("marshal_zone_flag") == 3
        if job.metadata.get("defence_window"):
            from .defence_radio import applicable
            now = state.raw.get("session_time_s")
            if not isinstance(now, (int,float)):
                return False
            primary = record.actions[0].code if record and record.actions else "NONE"
            return applicable(dict(job.metadata["defence_window"], clock_s=now), state, primary,
                              completed_wing=self._wing_completed)
        if job.action_code == FRONT_WING_DAMAGE:
            return wing_advice_current(state, job)
        if job.metadata.get("paired_tyre_alert"):
            return tyre_alert(state.raw.get("tyres_damage_pct"), state.raw.get("tyres_wear_pct")) == (
                job.action_code, job.speak_text)
        if record is None:
            return not self.personality_live and (self._last_repeat_state is None or state is self._last_repeat_state)
        return any(action.code == job.action_code for action in record.actions)

    def _latest_repeatable(self, state):
        return next((envelope for envelope in reversed(self._repeatable_history)
                     if self._repeat_still_applicable(envelope.job, state)), None)


    def _observe_cue_recovery(self, state: SessionState, current_code: str | None) -> None:
        time_s = state.raw.get("session_time_s")
        labels = state.assessment.labels if state.assessment is not None else None
        can_rearm = labels is not None and not state.raw.get("session_paused") and type(time_s) in (float, int)
        for code, clear_at in tuple(self._announced_episodes.items()):
            if not can_rearm or code == current_code:
                self._announced_episodes[code] = None
                continue
            if code == "LOCAL_YELLOW":
                recovered = state.raw.get("marshal_zone_flag") in (0, 1, 2)
            elif code == TYRE_DAMAGE:
                damage = tyre_damage_values(state.raw.get("tyres_damage_pct"))
                wear = tyre_damage_values(state.raw.get("tyres_wear_pct"))
                alert = tyre_alert(state.raw.get("tyres_damage_pct"), state.raw.get("tyres_wear_pct"))
                recovered = len(damage) == 4 and (
                    max(damage.values()) < TYRE_DAMAGE_WARNING_PCT
                    or len(wear) == 4 and (alert is None or alert[0] != TYRE_DAMAGE)
                )
            elif code == TYRE_WEAR_ALERT:
                wear = tyre_damage_values(state.raw.get("tyres_wear_pct"))
                recovered = len(wear) == 4 and max(wear.values()) < TYRE_DAMAGE_WARNING_PCT
            else:
                field, required = EPISODE_RECOVERY[code]
                recovered = getattr(labels, field) == required
            if not recovered:
                self._announced_episodes[code] = None
            elif clear_at is None or time_s < clear_at:
                self._announced_episodes[code] = time_s
            elif time_s - clear_at >= 3:
                del self._announced_episodes[code]

    @staticmethod
    def _wing_job(job) -> bool:
        return job.action_code == FRONT_WING_DAMAGE or has_wing_compensation(job)

    @staticmethod
    def _ordinary_wing(job) -> bool:
        return (job.action_code == FRONT_WING_DAMAGE and bool(job.metadata.get("wing_levels"))
                and not job.metadata.get("wing_corner"))

    def _start_envelope(self, envelope: _SpeechEnvelope) -> OutputLifecycleEvent:
        job = envelope.job
        attack = job.metadata.get("attack_opportunity")
        if attack and attack["phase"] == "forecast":
            state = self._last_repeat_state
            now = state.raw.get("session_time_s") if state else None
            primary = state.decision_record.actions if state and state.decision_record else ()
            elapsed = max(0., time.monotonic() - envelope.created_monotonic)
            if now is None or not validate_attack_cue(
                    attack, state, primary[0].code if primary else "NONE", completed_wing=self._wing_completed,
                    delivery_delay_s=max(0., elapsed - (now - attack["observed_s"]))):
                return self._build_event_from_envelope(envelope, "suppress", metadata={"reason": "attack_runway_expired"})
        bound = job.metadata.get("defence_window")
        if bound and "contact_s" in bound:
            elapsed = max(0., time.monotonic() - envelope.created_monotonic)
            if elapsed + bound["key_seconds"] + 1. > bound["contact_s"]:
                return self._build_event_from_envelope(envelope, "suppress", metadata={"reason": "defence_runway_expired"})
        if has_wing_compensation(job):
            state = self._last_repeat_state
            if state is None or not wing_advice_current(state, job):
                return self._build_event_from_envelope(envelope, "suppress", metadata={"reason": "wing_compensation_no_longer_applicable"})
        elif job.action_code == FRONT_WING_DAMAGE and job.metadata.get("wing_levels"):
            state = self._last_repeat_state
            if not self._repeat_still_applicable(job, state):
                return self._build_event_from_envelope(envelope, "suppress", metadata={"reason": "wing_advice_no_longer_applicable"})
        if job.metadata.get("paired_tyre_alert") and (
                self._last_repeat_state is None or not self._repeat_still_applicable(job, self._last_repeat_state)):
            return self._build_event_from_envelope(envelope, "suppress", metadata={"reason": "tyre_alert_no_longer_applicable"})
        if (envelope.repeat_target is not None
                and not self._repeat_still_applicable(envelope.repeat_target, self._last_repeat_state)):
            return self._build_event_from_envelope(envelope, "suppress", metadata={"reason": "repeat_no_longer_applicable"})
        if envelope.start_guard is not None:
            try:
                envelope.start_guard(envelope.job)
            except Exception as exc:
                return self._build_event_from_envelope(envelope, 'suppress', metadata={
                    'reason': 'delivery_no_longer_applicable', 'error': f'{type(exc).__name__}: {exc}'})
        audible = getattr(self.backend, "audible", True)
        try:
            handle = self.backend.start(envelope.job) if audible else None
        except Exception as exc:
            return self._build_event_from_envelope(envelope, "failed", metadata={
                "reason": "backend_start_failed", "error_type": type(exc).__name__})
        if (envelope.job.source_kind == "strategy_broadcast"
                and envelope.job.action_code == "LOW_FUEL"
                and self._session_scope is not None):
            self._last_fuel_broadcast_at = time.monotonic()
        if not audible:
            return self._build_event_from_envelope(envelope, "silent", metadata={"reason": "silent_backend"})
        if (self._session_scope is not None and envelope.job.source_kind == "strategy_broadcast"
                and envelope.job.action_code in EPISODE_CUES):
            self._announced_episodes[envelope.job.action_code] = None
        if envelope.job.metadata.get("defence_window"):
            self._defence_radio.started(envelope.job.metadata["defence_window"])
        self._active_envelope = envelope
        self._active_handle = handle
        self._personality_dialogue.started(envelope.job)
        self._attack_mode.on_started(envelope.job)
        if self.pit_feedback is not None and self._session_scope is not None:
            if envelope.job.metadata.get("pit_follow_up") == "admit":
                self.pit_feedback.end("recommendation_withdrawn")
            self.pit_feedback.start(envelope.job, self._session_scope)
        return self._build_event_from_envelope(
            envelope,
            "start",
            metadata={"source_kind": envelope.job.source_kind,
                      "submit_to_backend_start_ms": round((time.monotonic() - envelope.created_monotonic) * 1000, 3)},
        )


    def _active_action_code(self) -> str | None:
        if self._active_envelope is None:
            return None
        return self._active_envelope.job.action_code


    def _is_duplicate_submission(self, envelope: _SpeechEnvelope) -> bool:
        return any(queued is not None and queued.dedup_key == envelope.dedup_key
                   for queued in (self._active_envelope, self._pending_envelope))

    @_serialized
    def reserve_query_turn(self, token: str, expires_at: float | None) -> None:
        self.query_busy()
        if expires_at is None:
            self._query_turns.pop(token, None)
        elif token in self._query_turns or len(self._query_turns) < 64:
            self._query_turns[token] = expires_at
            self._cancel_optional_personality("query_turn_started")
        else:
            raise ValueError("speech_query_turn_limit")

    @_serialized
    def observe_pit_evidence(self, state: SessionState) -> None:
        if self.pit_feedback is not None:
            self.pit_feedback.observe(state)

    @_serialized
    def end_pit_evidence(self, reason: str) -> None:
        if self.pit_feedback is not None:
            self.pit_feedback.end(reason)

    @_serialized
    def record_pit_feedback(self, *, state: SessionState, text: str, request_id: str, interpretation=None) -> dict:
        if self.pit_feedback is None:
            return {"status": "unavailable", "reason": "pit_evidence_disabled"}
        self.tick()
        self.pit_feedback.observe(state)
        result = self.pit_feedback.feedback(state, text, request_id, interpretation=interpretation) if interpretation else self.pit_feedback.feedback(state, text, request_id)
        record = self.pit_feedback.record
        if (result["status"] in {"queued", "already_recorded"} and result.get("advice_kind") != "fuel" and record is not None
                and self._personality_dialogue.record_pit_response(record["output_event_id"])):
            pending = self._pending_envelope
            if pending is not None and pending.job.metadata.get("pit_follow_up") == "insist":
                self._pending_envelope = None
                self._publish_transition(pending, "cancel", "pit_recommendation_answered")
            active = self._active_envelope
            if active is not None and active.job.metadata.get("pit_follow_up") == "insist":
                self._request_personality_stop(active, "pit_recommendation_answered")
        return result

    @_serialized
    def configure_personality(self, params: dict) -> dict:
        preferences = self._personality_dialogue.configure(params)
        if params:
            if preferences["quiet"]:
                self._radio_experience.cancel()
            def blocked(job):
                return self._personality_dialogue.suppresses_job(job) or (
                    preferences["quiet"] and (job.metadata.get("attack_opportunity") or {}).get("phase") in {"forming", "outcome", "forecast"}
                )
            if not preferences["humor_enabled"] or preferences["humor"] != "normal":
                self._cancel_personality_generation("personality_preferences_changed")
            pending = self._pending_envelope
            if pending is not None and blocked(pending.job):
                self._pending_envelope = None
                self._publish_transition(pending, "cancel", "personality_preferences_changed")
            active = self._active_envelope
            if active is not None and blocked(active.job):
                self._request_personality_stop(active, "personality_preferences_changed")
        return preferences

    @_serialized
    def set_radio_preference(self, enabled: bool) -> dict:
        result = self._radio_experience.set_preference(enabled)
        if not enabled and self._active_envelope is not None:
            active = self._active_envelope
            if active.job.metadata.get("experience_kind") == "deferred_reason":
                self._request_personality_stop(active, "radio_preference_revoked")
        return result

    @_serialized
    def correct_last_brake_habit(self) -> dict:
        return self._radio_experience.correct_last_habit()

    @_serialized
    def personality_control_status(self) -> dict:
        state = self._last_repeat_state
        hint = state.personality if state is not None else None
        return {
            **self._personality_dialogue.configure({}),
            "stage": hint.stage if hint is not None else None,
            "microphone": self._microphone_status[0] if speech_time() < self._microphone_status[1] else "unknown",
            "interaction_active": self.query_busy(),
            "playback": self.playback_status()["status"],
        }

    @_serialized
    def report_microphone(self, state: str, ttl_s: float) -> None:
        self._microphone_status = (state, speech_time() + ttl_s)

    def _cancel_optional_personality(self, reason: str) -> None:
        self._cancel_personality_generation(reason)
        active = self._active_envelope
        if active is not None and active.job.metadata.get("optional_personality"):
            self._request_personality_stop(active, reason)

    def _begin_personality_generation(self, envelope: _SpeechEnvelope) -> bool:
        """Return true only when the optional template is deferred."""
        model = self._personality_llm
        dialogue = self._personality_dialogue
        if (model.mode == "disabled" or self.query_busy()
                or self._active_envelope is not None or self._pending_envelope is not None
                or not dialogue.humor_enabled or dialogue.humor_level != "normal"):
            return False
        job = envelope.job
        context = job.metadata["personality"]
        kind = context["opportunity"]
        if not context["humorous"] or context["stage"] < 2 or kind not in SUPPORTED_OPPORTUNITIES:
            return False
        if not model.start(PersonalityLlmRequest(
                request_id=job.output_event_id, decision_ref=job.snapshot_binding_id,
                opportunity=kind, stage=context["stage"], tone=context.get("tone", ""))):
            return False
        if model.mode == "shadow":
            return False
        envelope.start_guard = self._submission_guard
        job.metadata["session_scope"] = self._session_scope
        self._personality_generation = envelope
        return True

    def _generation_matches(self, envelope: _SpeechEnvelope, state: SessionState) -> bool:
        dialogue = self._personality_dialogue
        if self._expired(envelope) or not dialogue.context_current(state, live=self.personality_live):
            return False
        hint = state.personality
        context = envelope.job.metadata["personality"]
        return (
            hint.event_id == context["event_id"]
            and hint.opportunity == context["opportunity"]
            and hint.stage == context["stage"]
            and hint.opportunity_age_s is not None
            and 0 <= hint.opportunity_age_s <= 2
        )

    def _poll_personality_generation(self) -> _SpeechEnvelope | None:
        result = self._personality_llm.poll()
        envelope = self._personality_generation
        if result is None or envelope is None:
            return None
        self._personality_generation = None
        job = envelope.job
        if (self._expired(envelope) or job.metadata["session_scope"] != self._session_scope
                or self.query_busy() or self._personality_dialogue.suppresses_job(job)):
            self._publish_transition(envelope, "cancel", "personality_model_context_expired")
            return None
        status = result.status
        if result.request_id != job.output_event_id or result.decision_ref != job.snapshot_binding_id:
            status = "invalid_binding"
        if status == "ok" and result.fragment:
            job.speak_text = f"{result.fragment} {job.speak_text}"
        job.metadata["personality"]["model"] = {
            "status": status, "elapsed_ms": result.elapsed_ms,
            "used": status == "ok" and bool(result.fragment),
        }
        return envelope

    def _cancel_personality_generation(self, reason: str) -> None:
        self._personality_llm.cancel()
        envelope = self._personality_generation
        if envelope is not None:
            self._personality_generation = None
            self._publish_transition(envelope, "cancel", reason)

    @_serialized
    def personality_model_status(self) -> dict:
        return self._personality_llm.snapshot()

    def _request_personality_stop(self, active: _SpeechEnvelope, reason: str) -> None:
        if active.job.metadata.get("cancel_requested"):
            return
        active.job.metadata.update(cancel_requested=True, cancel_reason=reason, stop_requested_at=speech_time())
        self._request_stop_confirmation(active)
        self._publish_transition(active, "cancel_requested", reason)

    def query_busy(self) -> bool:
        now = speech_time()
        for token, deadline in tuple(self._query_turns.items()):
            if deadline <= now:
                del self._query_turns[token]
        return bool(self._query_turns)


    def _next_output_event_id(self) -> str:
        self._event_counter += 1
        return f"out:{self._event_counter}"
