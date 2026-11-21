"""Registered speech priority must reach the actual playback scheduler."""
from dataclasses import replace
import time
from asurada.capability_definitions import CAPABILITIES
from asurada.interaction import build_snapshot_query_input_event
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from phase3_voice_regression import make_state
from regression_support import emit_result


class Capture(NullSpeechBackend):
    audible = True
    def __init__(self):
        self.jobs = []

    def start(self, job):
        self.jobs.append(job)
        return None


def run():
    originals = {name:CAPABILITIES[name] for name in ('fuel_status','repeat_last')}
    try:
        CAPABILITIES['fuel_status'] = replace(originals['fuel_status'],speech_priority=77)
        CAPABILITIES['repeat_last'] = replace(originals['repeat_last'],speech_priority=81)
        state = make_state()
        state.source_timestamp_ms = int(time.time()*1000)
        state.raw['source_timestamp_ms'] = state.source_timestamp_ms
        backend = Capture()
        output = ConsoleVoiceOutput(backend=backend)
        output.emit_query_response(state=state,query_kind='fuel_status',render=False)
        checks = {
            'input_uses_declared_priority':build_snapshot_query_input_event(state=state,query_kind='fuel_status').priority==77,
            'played_query_uses_declared_priority':[job.priority for job in backend.jobs]==[77],
        }
        output.emit_query_response(state=state,query_kind='repeat_last',render=False)
        checks['repeat_uses_own_policy'] = len(backend.jobs)==2 and backend.jobs[-1].priority==81
        return {'passed':all(checks.values()),'checks':checks}
    finally:
        CAPABILITIES.update(originals)


if __name__=='__main__':
    emit_result(run())
