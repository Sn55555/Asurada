"""Construct immutable submission envelopes; never own playback."""
from __future__ import annotations
from dataclasses import asdict
from .fuel_feedback import fuel_observation
from .capability_definitions import capability_speech_priority
from .defence_radio import applicable as defence_applicable
from .defence_field import rear_gap_view
from .battle_speech import defence_line
from .attack_outcome import relative_position
from .attack_mode import AttackModeReminder
from .attack_opportunity import PlayingForecast, validate_attack_cue
import time
from typing import Any
from .interaction import SpeechJob
from .models import SessionState, StrategyDecision
from .output_contracts import _SpeechEnvelope, strategy_speech_band
from .wheel_telemetry import TYRE_DAMAGE, TYRE_WEAR_ALERT, tyre_alert


class OutputEnvelopeBuilder:
    """Construct immutable submission envelopes; never own playback. Shared state lives on ConsoleVoiceOutput."""

    def _build_strategy_envelope(
        self,
        *,
        decision: StrategyDecision,
        interaction_input_event: dict[str, Any],
        task_handle: dict[str, Any],
        final_voice_action: dict[str, Any],
        state: SessionState | None = None,
    ) -> _SpeechEnvelope | None:
        if not decision.messages or not final_voice_action:
            return None

        top = decision.messages[0]
        if decision.debug.get("pit_broadcast_muted") and top.code in {"BOX_WINDOW", "BOX_NOW", "PIT_NOW"}:
            return None
        if state is not None and top.code == "DEFEND_WINDOW" and "defence_forecast" in decision.debug:
            return None  # The target-bound radio path owns this action.
        if top.code == "ATTACK_WINDOW" and state is not None and self.attack_deferred(state):
            return None
        if top.code == "ATTACK_WINDOW" and state is not None and self._attack_mode.manages_opportunities(
                automatic=self._personality_dialogue.enabled, live_decision=decision.record is not None):
            return None
        if top.code in {"NONE", "FRONT_LOAD"} or top.code in self._announced_episodes:
            return None
        # Fuel is a persistent condition: changing decimal text is not a new alert.
        # Scope changes reset this bounded, monotonic reminder interval.
        if top.code == "LOW_FUEL" and state is not None:
            now = time.monotonic()
            if self._last_fuel_broadcast_at is not None and now - self._last_fuel_broadcast_at < 60.0:
                return None
        pit_metadata = self._personality_dialogue.pit_original_metadata() if state is not None and top.code == "BOX_WINDOW" else {}
        active = self._active_envelope
        if state is not None and top.code == "BOX_WINDOW" and (
                pit_metadata.get("tyre_pit_original", {}).get("pit")
                or self._personality_dialogue.pit_advice.original is not None
                or (active is not None and active.job.metadata.get("tyre_pit_original"))):
            return None
        interrupt = bool(final_voice_action.get("interrupt", False))
        protected = strategy_speech_band(top.code, interrupt) >= 3
        speak_text, personality = self._personality_dialogue.personalize(
            state, str(final_voice_action.get("speak_text") or top.title), protected=protected, strategy_code=top.code)
        paired_tyre_alert = state is not None and top.code in {TYRE_DAMAGE, TYRE_WEAR_ALERT} and (
            top.code, top.title) == tyre_alert(state.raw.get("tyres_damage_pct"), state.raw.get("tyres_wear_pct"))
        if paired_tyre_alert:
            speak_text = top.title
        fuel = fuel_observation(state) if (
            state is not None and top.code == "LOW_FUEL"
            and self._personality_dialogue.enabled and not protected
        ) else None
        if fuel is not None:
            speak_text = f'{speak_text.rstrip("。")}。安全时可提前收油。'
        output_event_id = self._next_output_event_id()
        return _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=output_event_id,
                interaction_session_id=str(interaction_input_event.get("interaction_session_id") or "runtime:unknown"),
                turn_id=str(interaction_input_event.get("turn_id") or "turn:unknown"),
                request_id=str(interaction_input_event.get("request_id") or "req:unknown"),
                snapshot_binding_id=str(interaction_input_event.get("snapshot_binding_id") or "snap:unknown"),
                source_kind="strategy_broadcast",
                action_code=top.code,
                priority=int(final_voice_action.get("priority") or top.priority or 0),
                speak_text=speak_text,
                cancelable=strategy_speech_band(top.code) != 4,
                persona_id=self.persona.persona_id,
                voice_profile_id=self.persona.voice_profile_id,
                metadata={
                    "source": "strategy_broadcast",
                    **({"paired_tyre_alert": True} if paired_tyre_alert else {}),
                    **pit_metadata,
                    **({"fuel_original": asdict(fuel)} if fuel is not None else {}),
                    **({"pit_decision_id": decision.record.decision_id if decision.record else None,
                        "pit_source_timestamp_ms": state.source_timestamp_ms} if pit_metadata else {}),
                    "interrupt": interrupt,
                    "semantic_subject": final_voice_action.get("semantic_subject") or top.title,
                    **({"personality": personality} if personality else {}),
                    "persona_id": self.persona.persona_id,
                    "voice_profile_id": self.persona.voice_profile_id,
                },
            ),
            interaction_input_event=interaction_input_event,
            task_handle=task_handle,
        )


    def _build_query_envelope(
        self,
        *,
        input_event: dict[str, Any],
        task_handle: dict[str, Any],
        schema: dict[str, Any],
        speak_text: str,
        action_code: str,
        personality: dict[str, Any] | None = None,
    ) -> _SpeechEnvelope:
        return _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=self._next_output_event_id(),
                interaction_session_id=str(input_event.get("interaction_session_id") or "runtime:unknown"),
                turn_id=str(input_event.get("turn_id") or "turn:unknown"),
                request_id=str(input_event.get("request_id") or "req:unknown"),
                snapshot_binding_id=str(input_event.get("snapshot_binding_id") or "snap:unknown"),
                source_kind="query_response",
                action_code=action_code,
                priority=capability_speech_priority(schema.get("query_kind")),
                speak_text=speak_text,
                cancelable=True,
                persona_id=self.persona.persona_id,
                voice_profile_id=self.persona.voice_profile_id,
                metadata={
                    "source": "query_response",
                    "query_kind": schema.get("query_kind"),
                    **({"personality": personality} if personality else {}),
                    "persona_id": self.persona.persona_id,
                    "voice_profile_id": self.persona.voice_profile_id,
                },
            ),
            interaction_input_event=input_event,
            task_handle=task_handle,
        )


    def _build_personality_opportunity(self, state, input_event, task_handle):
        if self._attack_mode.opportunities.owns_overtake_announcement(state.personality):
            return None
        return self._personality_dialogue.opportunity(
            state, live=self.personality_live, event=input_event, task=task_handle,
            output_id=self._next_output_event_id, persona=self.persona)

    def _build_brake_point_assist_envelope(
        self,
        *,
        state: SessionState,
        interaction_input_event: dict[str, Any],
        task_handle: dict[str, Any],
    ) -> _SpeechEnvelope | None:
        reminder = self._brake_point_assist.maybe_build_reminder(state=state)
        if reminder is None:
            return None
        assist_snapshot = self._brake_point_assist.snapshot()
        return _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=self._next_output_event_id(),
                interaction_session_id=str(interaction_input_event.get("interaction_session_id") or f"runtime:{state.session_uid}"),
                turn_id=str(interaction_input_event.get("turn_id") or f"turn:brake-assist:{state.session_uid}"),
                request_id=f"req:brake-assist:{state.session_uid}:{self._event_counter + 1}",
                snapshot_binding_id=str(interaction_input_event.get("snapshot_binding_id") or f"snap:{state.session_uid}:unknown"),
                source_kind="brake_point_assist",
                action_code=reminder.action_code,
                priority=93,
                speak_text=reminder.speak_text,
                cancelable=True,
                persona_id=self.persona.persona_id,
                voice_profile_id=self.persona.voice_profile_id,
                metadata={
                    "source": "brake_point_assist",
                    "target": reminder.target.to_dict(),
                    "countdown_value": reminder.countdown_value,
                    "assist_state": assist_snapshot,
                    "persona_id": self.persona.persona_id,
                    "voice_profile_id": self.persona.voice_profile_id,
                },
            ),
            interaction_input_event=interaction_input_event,
            task_handle=task_handle,
        )


    def _build_corner_gear_assist_envelope(
        self,
        *,
        state: SessionState,
        interaction_input_event: dict[str, Any],
        task_handle: dict[str, Any],
    ) -> _SpeechEnvelope | None:
        reminder = self._corner_gear_assist.maybe_build_reminder(state=state)
        if reminder is None:
            return None
        assist_snapshot = self._corner_gear_assist.snapshot()
        return _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=self._next_output_event_id(),
                interaction_session_id=str(interaction_input_event.get("interaction_session_id") or f"runtime:{state.session_uid}"),
                turn_id=str(interaction_input_event.get("turn_id") or f"turn:corner-gear:{state.session_uid}"),
                request_id=f"req:corner-gear:{state.session_uid}:{self._event_counter + 1}",
                snapshot_binding_id=str(interaction_input_event.get("snapshot_binding_id") or f"snap:{state.session_uid}:unknown"),
                source_kind="corner_gear_assist",
                action_code=reminder.action_code,
                priority=91,
                speak_text=reminder.speak_text,
                cancelable=True,
                persona_id=self.persona.persona_id,
                voice_profile_id=self.persona.voice_profile_id,
                metadata={
                    "source": "corner_gear_assist",
                    "target": reminder.target.to_dict(),
                    "assist_state": assist_snapshot,
                    "persona_id": self.persona.persona_id,
                    "voice_profile_id": self.persona.voice_profile_id,
                },
            ),
            interaction_input_event=interaction_input_event,
            task_handle=task_handle,
        )

    def _build_defence_envelope(self, state, decision, event, task):
        primary = decision.messages[0].code if decision.messages else "NONE"
        forecast = decision.debug.get("defence_forecast")
        meta = self._defence_radio.observe(
            state,
            decision,
            self._wing_completed,
            quiet=self._personality_dialogue.quiet,
        )
        for envelope, starting in ((self._pending_envelope, True), (self._active_envelope, False)):
            bound = envelope.job.metadata.get("defence_window") if envelope else None
            if not bound:
                continue
            now = state.raw.get("session_time_s")
            view, rear = rear_gap_view(state, bound["target"])
            geo = (relative_position(state.player, rear, state.raw.get("world_forward_dir") or {})
                   if rear and rear.car_index == bound["target"] else None)
            previous = envelope.rear_observation
            if previous is None and bound.get("rear_distance_m") is not None:
                previous = (bound["clock_s"], bound["rear_distance_m"])
            fresh = previous is not None and now is not None and 0 <= now - previous[0] <= .25
            distance = -geo[0] if geo else None
            converging = bool(fresh and distance is not None and 0 < distance < previous[1] - .05)
            tracker = self._defence_radio.pursuers.get(bound["target"])
            track_sample = tracker.pace.rear_sample if tracker else None
            track_closing = (bound.get("closing") and not bound.get("forecast")
                             and track_sample and track_sample[:2] == (bound["target"], now)
                             and track_sample[2] < bound["closing"]["distance_m"]
                             and tracker.pace.confirmed_track_closure)
            valid = defence_applicable(
                bound, state, primary, starting=starting, completed_wing=self._wing_completed,
                bridge_geometry=not starting and distance is None and (fresh or track_closing),
            )
            if not starting and distance is not None and now is not None:
                envelope.rear_observation = (now, distance)
            f = bound.get("forecast")
            if starting and bound.get("threats"):
                valid = valid and [m["target"] for m in bound["threats"]] == [
                    m["target"] for m in self._defence_radio.threats]
            if f and self._personality_dialogue.quiet:
                valid = False
            if valid and starting and f:
                valid = bool(forecast and forecast["recommended"] and forecast["id"] == f["id"])
            if valid and not starting:
                if envelope.playing_forecast is None:
                    envelope.playing_forecast = PlayingForecast(bound["clock_s"], bound["gap_s"])
                # An immediate alert needs current pressure, without a new corner forecast.
                current = (
                    forecast
                    if f
                    else (
                        {"id": "urgent", "recommended": True}
                        if view.player.gap_behind_s is not None
                        else None
                    )
                )
                if f and not (current and current["recommended"]) and view.player.gap_behind_s is not None:
                    # Do not clip a named sentence during a brief threshold fluctuation.
                    # A genuine missing-gap recovery still follows PlayingForecast's stricter contract.
                    continuity = envelope.playing_forecast
                    # A pursuer can stop gaining while still sitting on our gearbox.
                    # Keep this location cue if independent distance and timing agree.
                    initial_distance = bound.get("rear_distance_m")
                    close_behind = (distance is not None and initial_distance is not None
                                    and 0 < distance <= min(12, initial_distance - 2)
                                    and view.player.gap_behind_s <= .3)
                    if ((converging or close_behind) and (not current or current["id"] == f["id"])
                            and 0 < view.player.gap_behind_s <= bound["gap_s"] + .1):
                        continue
                    if (continuity.missing_at is None
                            and 0 <= state.raw["session_time_s"] - continuity.observed_s <= 0.5
                            and 0 < view.player.gap_behind_s <= min(0.6, bound["gap_s"] + 0.1)
                            and (not current or current["id"] == f["id"])):
                        continue
                valid = envelope.playing_forecast.supported(view, f or {"id": "urgent"}, current, rear=True)
            if valid:
                continue
            if starting:
                self._pending_envelope = None
                self._publish_transition(envelope, "cancel", "defence_context_changed")
            elif not envelope.job.metadata.get("cancel_requested"):
                try:
                    playing = self.backend.is_active(self._active_handle)
                except Exception:
                    playing = True
                if playing:
                    self._request_personality_stop(envelope, "defence_context_changed")
        if meta is None:
            return None
        f = meta["forecast"]
        line = defence_line(meta)
        if line is None:
            return None
        text, core, seconds = line
        meta.update(key_seconds=seconds, key_phrase=core, speech_deadline=meta["clock_s"] + meta["contact_s"])
        if not defence_applicable(meta, state, primary, completed_wing=self._wing_completed):
            return None
        text, personality = self._personality_dialogue.battle(state, "defence", meta, text)
        return _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=self._next_output_event_id(),
                interaction_session_id=event.get("interaction_session_id") or f"runtime:{state.session_uid}",
                turn_id=event.get("turn_id") or "turn:defence",
                request_id=event.get("request_id") or "req:defence",
                snapshot_binding_id=event.get("snapshot_binding_id") or "snap:defence",
                source_kind="strategy_broadcast",
                action_code="DEFEND_WINDOW",
                priority=92,
                speak_text=text,
                cancelable=True,
                persona_id=self.persona.persona_id,
                voice_profile_id=self.persona.voice_profile_id,
                metadata={
                    "source": "strategy_broadcast",
                    "defence_window": meta,
                    **({"personality": personality} if personality else {}),
                    "repeatable": f is None and not meta.get("approach"),
                    "interrupt": primary == "DEFEND_WINDOW",
                    "semantic_subject": f"defence:{meta['target']}",
                },
            ),
            interaction_input_event=event,
            task_handle=task,
        )

    def _build_attack_mode_envelope(
        self,
        *,
        state: SessionState,
        decision: StrategyDecision,
        interaction_input_event: dict[str, Any],
        task_handle: dict[str, Any],
    ) -> _SpeechEnvelope | None:
        opportunities = self._attack_mode.opportunities
        cue = opportunities.observe(state, decision, completed_wing=self._wing_completed)
        decision.debug["attack_opportunity"] = opportunities.snapshot()
        if self._attack_mode.manages_opportunities(
                automatic=self._personality_dialogue.enabled, live_decision=decision.record is not None
        ) or (cue is not None and cue.state == "outcome"):
            self._refresh_attack_advisories(state, decision)
            if cue is None or self.query_busy() or self._personality_dialogue.quiet and cue.state in {"forming", "outcome", "forecast"}:
                return None
            # A withdrawal replaces stale attack advice. Defense and higher safety calls retain precedence.
            if decision.messages and decision.messages[0].code == "DEFEND_WINDOW":
                return None
            text, personality = self._personality_dialogue.battle(state, "attack", cue.metadata, cue.text)
            if text is None:
                return None
            if personality:
                cue.metadata["key_seconds"] = personality["key_seconds"]
                cue.metadata["speech_deadline"] = cue.metadata["observed_s"] + personality["runway_s"]
            reminder = AttackModeReminder(text, {
                "forecast": "ATTACK_FORECAST", "forming": "ATTACK_MODE_FORMING", "actionable": "ATTACK_MODE_REMINDER",
                "withdrawal": "ATTACK_MODE_WITHDRAW", "outcome": "ATTACK_OUTCOME",
            }[cue.state], cue.state, {"attack_opportunity": cue.metadata, "repeatable": False,
                                     **({"personality": personality} if personality else {}), "semantic_subject": cue.metadata["id"]})
        else:
            reminder = self._attack_mode.maybe_build_reminder(state=state, decision=decision)
        if reminder is None:
            return None
        if reminder.action_code in {"ATTACK_MODE_FORMING", "ATTACK_MODE_REMINDER", "ATTACK_FORECAST"} and self.attack_deferred(state):
            return None
        assist_snapshot = self._attack_mode.snapshot()
        return _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=self._next_output_event_id(),
                interaction_session_id=str(interaction_input_event.get("interaction_session_id") or f"runtime:{state.session_uid}"),
                turn_id=str(interaction_input_event.get("turn_id") or f"turn:attack-mode:{state.session_uid}"),
                request_id=f"req:attack-mode:{state.session_uid}:{self._event_counter + 1}",
                snapshot_binding_id=str(interaction_input_event.get("snapshot_binding_id") or f"snap:{state.session_uid}:unknown"),
                source_kind="attack_mode",
                action_code=reminder.action_code,
                priority=94 if reminder.reminder_type in {"attack", "actionable"} else 72,
                speak_text=reminder.speak_text,
                cancelable=True,
                persona_id=self.persona.persona_id,
                voice_profile_id=self.persona.voice_profile_id,
                metadata={
                    "source": "attack_mode",
                    "assist_state": assist_snapshot,
                    "reminder_type": reminder.reminder_type,
                    **dict(reminder.metadata or {}),
                    "persona_id": self.persona.persona_id,
                    "voice_profile_id": self.persona.voice_profile_id,
                },
            ),
            interaction_input_event=interaction_input_event,
            task_handle=task_handle,
        )

    def _refresh_attack_advisories(self, state, decision):
        code = decision.messages[0].code if decision.messages else "NONE"
        opportunities = self._attack_mode.opportunities

        def expired(envelope, *, starting):
            if envelope is None:
                return False
            metadata = envelope.job.metadata.get("attack_opportunity")
            if metadata is None:
                return False
            if self._personality_dialogue.quiet and metadata["phase"] in {"forming", "outcome", "forecast"}:
                return True
            if not starting and metadata["phase"] == "forecast":
                # A queued cue must always pass strict validation before it starts.
                if not validate_attack_cue(metadata, state, code, starting=False,
                                           single_gap=state.player.gap_ahead_s is None,
                                           completed_wing=self._wing_completed):
                    return True
                if envelope.playing_forecast is None:
                    envelope.playing_forecast = PlayingForecast(metadata["observed_s"], metadata["forecast"]["gap_s"])
                return not envelope.playing_forecast.supported(state, metadata, decision.debug.get("attack_forecast"))
            return (not opportunities.still_current(metadata, starting=starting)
                    or not validate_attack_cue(metadata, state, code, starting=starting,
                                               completed_wing=self._wing_completed))

        pending = self._pending_envelope
        if expired(pending, starting=True):
            self._pending_envelope = None
            self._publish_transition(pending, "cancel", "attack_context_changed")
        active = self._active_envelope
        if expired(active, starting=False):
            # A physically completed cue will be consumed by the normal completion poll.
            try:
                playing = self.backend.is_active(self._active_handle)
            except Exception:
                playing = True
            if playing:
                self._request_personality_stop(active, "attack_context_changed")


