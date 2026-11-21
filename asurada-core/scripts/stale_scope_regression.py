from copy import deepcopy
from regression_support import emit_result
from phase3_voice_regression import make_state, FakeSpeechBackend, make_strategy_decision
from asurada.state import UnifiedStateStore
from asurada.output import ConsoleVoiceOutput
from asurada.decode import decode_snapshot
from asurada.interaction import build_snapshot_query_input_event
from asurada.snapshot_contract import snapshot_payload


def run():
    checks={};state=make_state();decision=make_strategy_decision(state=state,code='LOW_FUEL',priority=95,title='fuel',detail='')
    def decoded(uid,epoch,overall):
        payload=snapshot_payload(state,decision);payload['decision_record']=None
        payload.update(session_uid=uid,session_epoch=epoch,raw={'overall_frame_identifier':overall,'frame_identifier':overall})
        return decode_snapshot(payload)
    store=UnifiedStateStore();current=decoded('a',2,100);store.update(current)
    checks['explicit_old_epoch_with_newer_counter_rejected']=not store.update(decoded('a',1,101)) and store.latest is current
    missing=decoded('a',2,101);missing.raw={};store.update(missing)
    checks['missing_counter_does_not_erase_watermark']=not store.update(decoded('a',2,99))
    store.update(decoded('b',0,1));before=list(store.history())
    checks['retired_uid_cannot_reopen']=not store.update(decoded('a',3,200)) and store.history()==before
    payload=snapshot_payload(state,decision);payload['decision_record']=None
    for epoch in (-1,True,1.5,'1'):
        try:decode_snapshot(dict(payload,session_epoch=epoch));checks['invalid_epoch_'+str(epoch)]=False
        except ValueError:checks['invalid_epoch_'+str(epoch)]=True
    backend=FakeSpeechBackend();voice=ConsoleVoiceOutput(backend=backend)
    now=decoded('speech',2,100);old=decoded('speech',1,101)
    current_decision=make_strategy_decision(state=now,code='ERS_LOW',priority=60,title='ers',detail='')
    voice.emit(current_decision,state=now,render=False)
    active=voice._active_envelope;handle_count=len(backend._handles)
    old_decision=make_strategy_decision(state=old,code='LOW_FUEL',priority=95,title='old',detail='')
    result=voice.emit(old_decision,state=old,render=False)
    checks['old_strategy_suppressed']=result['event']['event_type']=='suppress' and voice._active_envelope is active and voice._pending_envelope is None
    query=voice.emit_query_response(state=old,query_kind='fuel_status',render=False)
    bundle=voice.emit_voice_query_bundle(state=old,bundle={},render=False)
    checks['old_queries_never_start_or_enqueue']=query['output_lifecycle']['event']['metadata']['reason']=='stale_session_scope' and bundle['output_lifecycle']['event']['event_type']=='suppress' and len(backend._handles)==handle_count
    newer=decoded('new-speech',0,1);voice.bind_session(newer)
    checks['old_speech_uid_cannot_rebind']=voice.bind_session(now) is False and voice._session_scope==('new-speech',0)
    invalid=deepcopy(newer);invalid.session_epoch=None
    checks['invalid_speech_epoch_rejected_without_crash']=voice.bind_session(invalid) is False
    # Global stop must remain possible with an old telemetry snapshot.
    voice.emit(make_strategy_decision(state=newer,code='LOW_FUEL',priority=95,title='fuel',detail=''),state=newer,render=False)
    stopped=voice.emit_control_query_bundle(state=old,bundle={'structured_query':{'query_kind':'stop'},'input_event':build_snapshot_query_input_event(state=old,query_kind='stop').to_dict()},render=False)
    checks['stale_telemetry_does_not_block_stop']=voice._active_envelope is None and voice._pending_envelope is None and voice._session_scope==('new-speech',0)
    voice.shutdown(timeout_s=0)
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())
