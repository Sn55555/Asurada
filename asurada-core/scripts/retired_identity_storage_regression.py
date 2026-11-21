"""More than 256 sessions still reject delayed old identities exactly."""
from asurada.retired_identities import RetiredIdentities
from asurada.state import UnifiedStateStore
from asurada.output import ConsoleVoiceOutput
from phase3_voice_regression import make_state, FakeSpeechBackend
from regression_support import emit_result


def run():
    checks = {}; identities = RetiredIdentities()
    for i in range(300):
        identities.add(str(i))
    checks['bounded_memory'] = identities.health()['memory_count'] == 256
    checks['spilled_exactly_44'] = identities.health()['spilled_count'] == 44
    checks['nothing_forgotten'] = all(str(i) in identities for i in range(300)) and 'never-seen' not in identities
    identities.add('299')
    checks['duplicate_does_not_grow'] = len(identities) == 300
    store = UnifiedStateStore(); voice = ConsoleVoiceOutput(backend=FakeSpeechBackend())
    try:
        for i in range(301):
            state = make_state(); state.session_uid = f'spill-{i}'
            assert store.update(state) and voice.bind_session(state)
        for i in (0, 1, 255, 256, 299):
            state = make_state(); state.session_uid = f'spill-{i}'; state.session_epoch = 99
            checks[f'old_{i}_rejected'] = not store.update(state) and not voice.bind_session(state)
        checks['speech_memory_bounded'] = voice._retired_sessions.health()['memory_count'] == 256
    finally:
        voice.shutdown(timeout_s=0)
        identities.close()
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())
