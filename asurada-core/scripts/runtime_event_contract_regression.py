"""Versioned session transitions survive snapshots; voice rows carry a version."""
from copy import deepcopy
from dataclasses import replace
from asurada.state import UnifiedStateStore
from asurada.models import StrategyDecision
from asurada.snapshot_contract import snapshot_payload
from asurada.decode import decode_snapshot
from asurada.live_dashboard_payload import build_dashboard_payload
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    def frame(uid, overall, counter):
        return replace(make_state(), session_uid=uid,
                       raw={'overall_frame_identifier': overall, 'frame_identifier': counter})
    store = UnifiedStateStore()
    first = frame('a', 100, 100)
    store.update(first)
    checks = {'start_versioned': first.session_event['contract_version'] == 'session-event-v1'
              and first.session_event['reason'] == 'session_started'}
    rewind = frame('a', 101, 80)
    store.update(rewind)
    event = deepcopy(rewind.session_event)
    checks['rewind_scope'] = event['reason'] == 'rewind' and event['session_epoch'] == 1 and event['previous']['session_epoch'] == 0
    current = frame('a', 102, 81)
    store.update(current)
    checks['last_transition_survives_coalescing'] = current.session_event == event
    decision = StrategyDecision([])
    payload = snapshot_payload(current, decision)
    checks['snapshot_roundtrip'] = decode_snapshot(payload).session_event == event
    checks['dashboard_same_transition'] = build_dashboard_payload(current, decision)['session_event'] == event
    for field, value in [('contract_version', 'unknown'), ('session_uid', 'other'), ('session_epoch', 0), ('session_epoch', True)]:
        bad = deepcopy(payload); bad['session_event'][field] = value
        try:
            decode_snapshot(bad); checks[f'reject_{field}_{value}'] = False
        except ValueError:
            checks[f'reject_{field}_{value}'] = True
    second = frame('b', 1, 1)
    store.update(second)
    checks['new_session_previous_scope'] = second.session_event['previous'] == {'session_uid': 'a', 'session_epoch': 1}
    checks['retired_cannot_replace_event'] = not store.update(first) and store.latest.session_event == second.session_event
    legacy = dict(payload); legacy.pop('session_event')
    checks['legacy_readable'] = decode_snapshot(legacy).session_event is None
    voice = ConsoleVoiceOutput(backend=NullSpeechBackend())
    try:
        voice.emit_query_response(state=second, query_kind='fuel_status', render=False)
        rows = voice.read_events()['events']
        checks['voice_rows_versioned'] = bool(rows) and all(row['event']['contract_version'] == 'voice-event-v1' for row in rows)
    finally:
        voice.shutdown(timeout_s=.1)
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())
