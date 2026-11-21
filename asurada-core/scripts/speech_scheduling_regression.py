from regression_support import emit_result
from phase3_voice_regression import FakeSpeechBackend, make_state, make_strategy_decision
from asurada.output import ConsoleVoiceOutput
from asurada.tts_backends import MacOSSayBackend
import tempfile
from pathlib import Path


def check_tyre_damage_episode():
    from asurada.assessment import assess_domain

    backend = FakeSpeechBackend()
    voice = ConsoleVoiceOutput(backend=backend)
    state = make_state()

    def frame(second, damage, code="NONE", *, paused=False):
        state.raw.update(session_time_s=second, session_paused=paused, tyres_damage_pct=damage)
        state.player.status_tags = ["front_tyre_overload"] if code == "FRONT_LOAD" else []
        assess_domain(state)
        result = voice.emit(make_strategy_decision(
            state=state, code=code, priority=72 if code != "NONE" else 0,
            title="右前轮损伤 39%", detail="轮胎损伤"),
            state=state, render=False)
        backend.complete_all()
        voice.tick()
        return result["event"]["event_type"]

    damaged = [30, 35, 31, 39]
    clear = [0, 0, 0, 0]
    cue = "TYRE_DAMAGE"
    return {
        "historical_front_load_is_silent": frame(9, clear, "FRONT_LOAD") != "start",
        "tyre_damage_first_alert_starts": frame(10, damaged, cue) == "start",
        "tyre_damage_does_not_repeat_after_completion": frame(11, damaged, cue) != "start",
        "tyre_damage_does_not_rearm_on_one_clear_frame": (
            frame(12, clear) != "start" and frame(13, damaged, cue) != "start"),
        "missing_wheel_does_not_rearm": (
            frame(14, clear) != "start" and frame(18, [0, 0, 0]) != "start"
            and frame(19, damaged, cue) != "start"),
        "paused_frames_do_not_rearm": (
            frame(20, clear) != "start" and frame(24, clear, paused=True) != "start"
            and frame(25, damaged, cue) != "start"),
        "tyre_damage_rearms_after_four_clear_wheels": (
            frame(26, clear) != "start" and frame(29, clear) != "start"
            and frame(30, damaged, cue) == "start" and len(backend._handles) == 2),
    }


def check_defend_episode():
    from asurada.assessment import assess_domain

    backend = FakeSpeechBackend()
    voice = ConsoleVoiceOutput(backend=backend)
    state = make_state()

    def frame(second, gap, *, force_defend=False):
        state.raw["session_time_s"] = second
        state.player.gap_behind_s = gap
        assess_domain(state)
        defend = force_defend or (gap is not None and gap < 1.0)
        decision = make_strategy_decision(
            state=state, code="DEFEND_WINDOW" if defend else "NONE",
            priority=92 if defend else 0, title="防守窗口", detail="后车追近")
        event = voice.emit(decision, state=state, render=False)["event"]
        backend.complete_all()
        voice.tick()
        return event['event_type']

    return {
        "defend_first_alert_starts": frame(10, .4) == "start",
        "defend_does_not_repeat_after_completion": frame(11, .3) != "start",
        "missing_gap_does_not_rearm_defend": (
            frame(12, None) != "start" and frame(16, None) != "start" and frame(17, .4) != "start"),
        "defend_rearms_after_clear_gap": (
            frame(18, 3.) != "start" and frame(21, 3.) != "start"
            and frame(22, .4) == "start" and len(backend._handles) == 2),
        "ongoing_tactical_defense_does_not_rearm_on_clear_raw_gap": (
            frame(23, 3., force_defend=True) != "start"
            and frame(27, 3., force_defend=True) != "start"),

    }


def run():
    state=make_state()
    def decision(code, priority, interrupt=False):
        result=make_strategy_decision(state=state,code=code,priority=priority,title=code,detail='')
        result.debug['arbiter_v2']['output']['final_voice_action']['interrupt']=interrupt
        return result
    backend=FakeSpeechBackend(); voice=ConsoleVoiceOutput(backend=backend)
    voice.emit(decision('ERS_LOW',60),render=False)
    urgent=voice.emit(decision('SAFETY_CAR',130,True),render=False)
    checks={'urgent_preempts':urgent['event']['event_type']=='start' and not backend._handles[0]['active'] and voice._active_envelope.job.action_code=='SAFETY_CAR'}
    voice.emit(decision('LOW_FUEL',95),render=False)
    voice._pending_envelope.created_monotonic -= 4
    backend.complete_all()
    event=voice.tick()
    checks['expired_pending_never_starts']=event['event']['metadata']['reason']=='expired_before_start' and len(backend._handles)==2 and voice._active_envelope is None
    voice.emit(decision('ERS_LOW',60),render=False)
    voice.emit(decision('LOW_FUEL',95),render=False)
    backend.complete_all()
    event=voice.tick()
    checks['tick_advances_without_submission']=event['event']['event_type']=='start' and voice._active_envelope.job.action_code=='LOW_FUEL'
    class Unstoppable(FakeSpeechBackend):
        def stop(self, handle): pass
    backend=Unstoppable(); voice=ConsoleVoiceOutput(backend=backend)
    voice.emit(decision('ERS_LOW',60),render=False)
    event=voice.emit(decision('SAFETY_CAR',130,True),render=False)
    checks['no_overlap_without_stop_ack']=len(backend._handles)==1 and event['event']['event_type']=='enqueue' and voice._active_envelope.job.action_code=='ERS_LOW'
    stopped=voice._emit_stop_cancel_control(query_kind='stop', input_event=decision('ERS_LOW',60).debug['interaction_input_event'], structured_query={}, query_route={}, confirmation_policy={}, task_handle={}, normalization_event={}, render=False)
    checks['stop_waits_for_ack']=stopped['output_lifecycle']['event']['event_type']=='cancel_requested' and voice._active_envelope is not None and voice._pending_envelope is None
    backend.complete_all()
    stopped=voice.tick()
    checks['stop_ack_is_cancel_not_complete']=stopped['event']['event_type']=='cancel' and voice._active_envelope is None and voice._last_completed_envelope is None
    backend=FakeSpeechBackend(); voice=ConsoleVoiceOutput(backend=backend)
    voice.emit(decision('ERS_LOW',60),render=False)
    voice.emit(decision('LOW_FUEL',95),render=False)
    pending_id=voice._pending_envelope.job.output_event_id
    voice._pending_envelope.created_monotonic -= 4
    cursor=voice.read_events()['cursor']
    voice.emit(decision('SAFETY_CAR',130,True),render=False)
    events=[r['event'] for r in voice.read_events(cursor=cursor)['events']]
    checks['expired_pending_recorded_during_preemption']=sum(e['output_event_id']==pending_id and e['event_type']=='cancel' for e in events)==1
    backend=FakeSpeechBackend(); voice=ConsoleVoiceOutput(backend=backend)
    voice.emit(decision('ERS_LOW',60),render=False)
    voice.emit(decision('LOW_FUEL',95),render=False)
    pending_id=voice._pending_envelope.job.output_event_id
    backend.complete_all()
    cursor=voice.read_events()['cursor']
    simultaneous=voice.emit(decision('ERS_LOW',60),render=False)
    events=[r['event'] for r in voice.read_events(cursor=cursor)['events']]
    checks['completion_debug_retained']=simultaneous['completed_output']['event_type']=='complete'
    checks['queued_start_not_lost_on_new_submission']=([e['event_type'] for e in events]==['complete','start','enqueue']
        and events[1]['output_event_id']==pending_id)
    backend=Unstoppable(); voice=ConsoleVoiceOutput(backend=backend)
    voice.emit(decision('ERS_LOW',60),render=False)
    cursor=voice.read_events()['cursor']
    voice.emit(decision('SAFETY_CAR',130,True),render=False)
    backend.complete_all(); voice.tick()
    events=[r['event'] for r in voice.read_events(cursor=cursor)['events']]
    checks['deferred_preemption_is_cancellation']=([e['event_type'] for e in events]==['cancel_requested','enqueue','cancel','start']
        and events[2]['metadata']['cancel_reason']=='preempted_by_higher_priority'
        and voice._last_completed_envelope is None)
    with tempfile.TemporaryDirectory() as directory:
        voice=ConsoleVoiceOutput(backend=MacOSSayBackend(say_binary=str(Path(directory)/'missing-player')))
        failed=decision('ERS_LOW',60)
        result=voice.emit(failed,render=False)
        checks['real_spawn_failure_classified']=(result['event']['event_type']=='failed'
            and result['event']['metadata']['error_type']=='FileNotFoundError'
            and failed.debug['task_lifecycle']['event']['status']=='failed'
            and voice._active_envelope is None)
        voice.tick()
        checks['spawn_failure_never_becomes_completion']=[r['event']['event_type'] for r in voice.read_events()['events']]==['failed']
    backend = FakeSpeechBackend()
    voice = ConsoleVoiceOutput(backend=backend)
    damage = voice.emit(decision("TYRE_DAMAGE", 72), state=state, render=False)["event"]
    unstable = voice.emit(decision("DYNAMICS_UNSTABLE", 90), state=state, render=False)["event"]
    checks["urgent_instability_preempts_tyre_damage"] = (
        damage["event_type"] == unstable["event_type"] == "start"
        and unstable["action_code"] == "DYNAMICS_UNSTABLE"
        and not backend._handles[0]["active"])
    checks.update(check_tyre_damage_episode())
    checks.update(check_defend_episode())
    return {'passed':all(checks.values()),'checks':checks}

if __name__=='__main__': emit_result(run())
