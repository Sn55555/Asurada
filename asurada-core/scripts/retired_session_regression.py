"""Retired identities must stay retired for the lifetime of a runtime."""
from asurada.state import UnifiedStateStore
from asurada.output import ConsoleVoiceOutput
from phase3_voice_regression import make_state, FakeSpeechBackend, make_strategy_decision
from regression_support import emit_result


def run():
    checks={};store=UnifiedStateStore();backend=FakeSpeechBackend()
    voice=ConsoleVoiceOutput(backend=backend)
    states=[]
    try:
        for index in range(64):
            state=make_state();state.session_uid='long-run-'+str(index)
            state.raw={'overall_frame_identifier':1,'frame_identifier':1}
            assert store.update(state) and voice.bind_session(state)
            states.append(state)
        latest=store.latest;scope=voice._session_scope
        for index in (0,1,15,16,31,47,62):
            state=states[index];state.session_epoch=10
            state.raw={'overall_frame_identifier':1000,'frame_identifier':1000}
            checks[str(index)+'_state_rejected']=not store.update(state) and store.latest is latest
            checks[str(index)+'_speech_rejected']=not voice.bind_session(state) and voice._session_scope==scope
            decision=make_strategy_decision(state=state,code='LOW_FUEL',priority=95,title='old',detail='old')
            handles=len(backend._handles)
            voice.emit(decision,state=state,render=False)
            checks[str(index)+'_no_old_playback']=len(backend._handles)==handles
        new=make_state();new.session_uid='new-after-long-run'
        checks['new_session_still_accepted']=store.update(new) and voice.bind_session(new)
        # New instances intentionally begin a new lifetime (e.g. explicit replay).
        checks['fresh_runtime_can_replay_old_uid']=UnifiedStateStore().update(states[0])
    finally:voice.shutdown(timeout_s=0)
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())
