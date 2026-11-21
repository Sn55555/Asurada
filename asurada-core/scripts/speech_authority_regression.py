from dataclasses import replace
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from regression_support import emit_result
from phase3_voice_regression import FakeSpeechBackend, make_state
from asurada.models import StrategyDecision
from asurada.output import ConsoleVoiceOutput
from asurada.speech_service import SpeechService
from asurada.speech_client import SharedSpeechClient
from asurada.live_dashboard_feed import LatestSnapshotWriter
from asurada.interaction import build_snapshot_query_input_event
from asurada.speech_applicability import validate_query_applicability


def run():
    checks = {}
    with TemporaryDirectory(dir='/tmp', prefix='speech-authority-') as temp:
        writer = LatestSnapshotWriter(Path(temp))
        backend = FakeSpeechBackend()
        service = SpeechService(Path(temp)/'voice.sock', output=ConsoleVoiceOutput(backend=backend), session_source=writer.path).start()
        try:
            client = SharedSpeechClient(service.path)
            state = make_state()
            state.source_timestamp_ms = int(time.time()*1000)
            state.session_uid = 'authority-a'
            def rejected(operation):
                try: operation(); return False
                except RuntimeError: return True
            checks['missing_publication_fails_closed'] = rejected(lambda: client.emit_query_response(state=state, query_kind='fuel_status'))
            writer.append(state, StrategyDecision([]))
            checks['current_authority_can_play'] = client.emit_query_response(state=state, query_kind='fuel_status')['output_lifecycle']['event']['event_type']=='start'
            changed = deepcopy(state)
            changed.player.tyre.wear_pct += .2
            writer.append(changed, StrategyDecision([]))
            checks['same_scope_changed_tyre_answer_rejected'] = rejected(lambda: client.emit_query_response(state=state, query_kind='tyre_status'))
            checks['unrelated_tyre_change_keeps_fuel_answer'] = not rejected(lambda: client.emit_query_response(state=state, query_kind='fuel_status'))
            changed = deepcopy(state)
            changed.player.ers_pct += .1
            writer.append(changed, StrategyDecision([]))
            checks['llm_changed_evidence_rejected_at_service'] = rejected(lambda: client.emit_voice_query_bundle(state=state,
                bundle={'structured_query':{'query_kind':'overall_situation'}, 'response_override':{'reason_fields':['state_snapshot.ers_pct']}}))
            unrelated = deepcopy(state)
            unrelated.player.speed_kph += 1
            validate_query_applicability('emit_voice_query_bundle', {'bundle':{'response_override':{'reason_fields':['state_snapshot.ers_pct']}}}, state, unrelated)
            checks['unchanged_llm_evidence_survives_unrelated_change'] = True
            changed = deepcopy(state)
            changed.safety_car = 'FULL'
            writer.append(changed, StrategyDecision([]))
            checks['same_scope_race_control_change_rejected'] = rejected(lambda: client.emit_query_response(state=state, query_kind='fuel_status'))
            writer.append(state, StrategyDecision([]))
            expired = replace(state, source_timestamp_ms=int(time.time()*1000)-16000)
            checks['old_answer_rejected_despite_fresh_authority'] = rejected(lambda: client.emit_query_response(state=expired, query_kind='fuel_status'))
            newer = replace(state, session_uid='authority-b', source_timestamp_ms=int(time.time()*1000))
            writer.append(newer, StrategyDecision([]))
            deadline = time.monotonic()+.6
            while service.output._active_envelope is not None and time.monotonic()<deadline: time.sleep(.01)
            checks['published_transition_stops_old_playback'] = service.output._active_envelope is None and service.output._pending_envelope is None
            checks['client_cannot_bind_old_scope'] = rejected(lambda: client.bind_session(state))
            checks['client_cannot_deliver_old_scope'] = rejected(lambda: client.emit_query_response(state=state, query_kind='fuel_status'))
            checks['new_authority_binds'] = client.bind_session(newer) is True
            writer.reset()
            checks['stop_works_without_current_publication'] = not rejected(lambda: client.emit_control_query_bundle(state=state,
                bundle={'structured_query':{'query_kind':'stop'}, 'input_event':build_snapshot_query_input_event(state=state, query_kind='stop').to_dict()}))
            writer.append(replace(newer, source_timestamp_ms=int(time.time()*1000)-16000), StrategyDecision([]))
            checks['stale_publication_rejects_binding'] = rejected(lambda: client.bind_session(newer))
            checks['health_names_authority'] = client.health()['session_source']==str(writer.path.resolve())
        finally:
            checks['service_and_authority_monitor_close'] = service.close() and not service._authority_thread.is_alive()
    return {'passed':all(checks.values()), 'checks':checks}


if __name__=='__main__': emit_result(run())
