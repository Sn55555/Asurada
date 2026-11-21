"""Reject same-session query answers whose supporting facts changed.

Fixed answers are recomposed with the same capability implementation. LLM
answers compare their declared evidence, plus shared race-context verdicts.
This is applicability checking, not verification of arbitrary natural language.
"""
import math
import time
from dataclasses import asdict

from .assessment import assess_domain
from .attack_opportunity import validate_attack_cue
from .capability_definitions import CAPABILITIES
from .capabilities.pit import explain_pit_with_cooperation
from .defence_radio import applicable as defence_applicable
from .conversation_context import ConversationContext
from .llm_evidence import evidence_fields
from .models import StrategyMessage
from .state_summary_for_llm import build_state_summary_for_llm
from .answer_policy import render_racing_response
from .persona_style import render_llm_sidecar_text
from .personality_pit_advice import safe_pit_follow_up, tyre_observation


def primary(state):
    record = state.decision_record
    return record.actions[0] if record is not None and record.actions else None


def validate_assist_applicability(job, original, current, *, wall_clock=time.time):
    defence = job.metadata.get("defence_window")
    if defence is not None:
        action = primary(current)
        age = wall_clock() - current.source_timestamp_ms / 1000.
        deadline = defence.get("speech_deadline")
        now = current.raw.get("session_time_s")
        if (not 0 <= age <= 1 or deadline is not None and
                (now is None or now + age + defence["key_seconds"] + 1. > deadline)
                or not defence_applicable(defence,current,action.code if action else "NONE")):
            raise ValueError("speech_defence_window_changed")
    attack = job.metadata.get("attack_opportunity")
    if attack is not None:
        current_primary = primary(current)
        age = wall_clock() * 1000 - current.source_timestamp_ms
        if not 0 <= age <= 1000 or not validate_attack_cue(
                attack, current, current_primary.code if current_primary else "NONE",
                delivery_delay_s=age / 1000 if attack["phase"] == "forecast" else 0.):
            raise ValueError("speech_attack_opportunity_changed")
    budgets = {'brake_point_assist': .35, 'corner_gear_assist': .75}
    budget = budgets.get(job.source_kind)
    if budget is None:
        return
    age_s = (wall_clock()*1000-original.source_timestamp_ms)/1000
    if not math.isfinite(age_s) or age_s < 0 or age_s > budget:
        raise ValueError('speech_assist_timing_window_passed')
    if (original.session_uid, original.session_epoch, original.lap_number, original.track) != (
            current.session_uid, current.session_epoch, current.lap_number, current.track):
        raise ValueError('speech_assist_lap_changed')
    def distance(state):
        value = state.player.lap_distance_m
        if value is None: value = state.raw.get('lap_distance_m')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('speech_assist_position_unavailable')
        return value
    old, now = distance(original), distance(current)
    speed = current.player.speed_kph
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed) or speed <= 0:
        raise ValueError('speech_assist_speed_unavailable')
    # No wrap inference: a new lap/rewind must produce its own cue.
    if now < old or now-old > speed/3.6*budget:
        raise ValueError('speech_assist_position_window_passed')
    target = job.metadata.get('target') or {}
    key = 'braking_zone_start_m' if job.source_kind == 'brake_point_assist' else 'apex_distance_m'
    end = target.get(key)
    if isinstance(end, bool) or not isinstance(end, (int, float)) or not math.isfinite(end):
        raise ValueError('speech_assist_target_unavailable')
    if old <= end <= now:
        raise ValueError('speech_assist_target_passed')


def validate_pit_follow_up_applicability(job, original, current, *, wall_clock=time.time):
    if not job.metadata.get("pit_follow_up"):
        return
    age_ms = wall_clock() * 1000 - current.source_timestamp_ms
    baseline, latest = tyre_observation(original), tyre_observation(current)
    if (not 0 <= age_ms <= 1000 or not safe_pit_follow_up(current)
            or baseline is None or latest is None or latest.pit
            or (baseline.fitted, baseline.stops, baseline.verdict) != (latest.fitted, latest.stops, latest.verdict)):
        raise ValueError("speech_pit_follow_up_evidence_changed")


def context_facts(state):
    return (state.track, state.lap_number, state.total_laps, state.weather, state.safety_car,
            state.player.position, state.player.tyre.compound,
            tuple(state.raw.get(key) for key in ('marshal_zone_flag', 'pit_status', 'result_status', 'session_paused',
                  'num_unserved_drive_through_pens', 'num_unserved_stop_go_pens')),
            asdict(assess_domain(state).labels))


def validate_strategy_applicability(params, original, current, *, wall_clock=time.time):
    age = wall_clock()*1000-original.source_timestamp_ms
    if not math.isfinite(age) or age < 0 or age > 15000:
        raise ValueError('speech_strategy_snapshot_expired')
    before, after = original.decision_record, current.decision_record
    if before is None or after is None:
        raise ValueError('speech_strategy_requires_bound_decision')
    if params.get('messages') != [asdict(action) for action in before.actions]:
        raise ValueError('speech_strategy_actions_not_bound')
    sent = ((params.get('debug') or {}).get('arbiter_v2') or {}).get('output') or {}
    if sent.get('final_voice_action') != before.arbitration.get('final_voice_action'):
        raise ValueError('speech_strategy_voice_not_bound')
    if context_facts(original) != context_facts(current):
        raise ValueError('speech_strategy_context_changed')
    # Snapshot identifiers naturally change every frame. Compare the selected
    # action and its actual voice payload, not the entire decision identifier.
    old_primary = asdict(before.actions[0]) if before.actions else None
    new_primary = asdict(after.actions[0]) if after.actions else None
    if (old_primary != new_primary or
            before.arbitration.get('final_voice_action') != after.arbitration.get('final_voice_action')):
        raise ValueError('speech_strategy_no_longer_supported')


def validate_query_applicability(method, params, original, current, *, wall_clock=time.time):
    bundle = params.get('bundle') or {}
    query = params.get('query_kind') if method == 'emit_query_response' else (bundle.get('structured_query') or {}).get('query_kind')
    spec = CAPABILITIES.get(query)
    freshness_ms = spec.freshness_ms if spec is not None else 15000
    timestamp = original.source_timestamp_ms
    age = wall_clock()*1000-timestamp
    if not math.isfinite(age) or age < 0 or age > freshness_ms:
        raise ValueError('speech_answer_snapshot_expired')
    if context_facts(original) != context_facts(current):
        raise ValueError('speech_answer_context_changed')
    override = bundle.get('response_override') or {}
    original_primary = StrategyMessage(**params['primary_message']) if params.get('primary_message') else primary(original)
    current_primary = primary(current)
    if override:
        checked_response = dict(status=override.get('status', 'answerable'), answer_text=override.get('claim_answer_text', override.get('speak_text', '')),
            claims=override.get('claims') or [], metadata=override.get('claim_metadata') or {},
            reason_fields=override.get('reason_fields') or [])
        checked_summary = build_state_summary_for_llm(state=original, primary_message=original_primary,
            conversation_context=ConversationContext()).to_dict()
        rendered = render_racing_response(checked_response, summary=checked_summary,
            request_id=(bundle.get('input_event') or {}).get('request_id'))
        if render_llm_sidecar_text(rendered) != override.get('speak_text', ''):
            raise ValueError('speech_answer_rendered_text_mismatch')
        refs = override.get('reason_fields') or []
        if not refs and checked_response['status'] != 'needs_clarification':
            raise ValueError('speech_answer_evidence_missing')
        def fields(state, message):
            summary = build_state_summary_for_llm(state=state, primary_message=message,
                conversation_context=ConversationContext()).to_dict()
            return evidence_fields(summary)
        before, after = fields(original, original_primary), fields(current, current_primary)
        if any(ref not in before or ref not in after or before[ref] != after[ref] for ref in refs):
            raise ValueError('speech_answer_evidence_changed')
    else:
        spec = CAPABILITIES.get(query)
        if spec is None or spec.handler_name is None:
            raise ValueError('speech_answer_unknown_capability')
        metadata = (bundle.get('structured_query') or {}).get('metadata') or {}
        before = spec.invoke(state=original, primary_message=original_primary, schema_metadata=metadata)
        after = spec.invoke(state=current, primary_message=current_primary, schema_metadata=metadata)
        if before != after:
            raise ValueError('speech_answer_facts_changed')
        if query == 'why_not_pit' and explain_pit_with_cooperation(original) != explain_pit_with_cooperation(current):
            raise ValueError('speech_pit_cooperation_context_changed')
