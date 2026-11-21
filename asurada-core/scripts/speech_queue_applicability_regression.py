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


def run():
    checks = {}
    for changed in (True, False):
        with TemporaryDirectory(dir='/tmp', prefix='speech-queue-') as temp:
            writer = LatestSnapshotWriter(Path(temp))
            state = make_state()
            state.source_timestamp_ms = int(time.time()*1000)
            writer.append(state, StrategyDecision([]))
            backend = FakeSpeechBackend()
            service = SpeechService(Path(temp)/'voice.sock', output=ConsoleVoiceOutput(backend=backend), session_source=writer.path).start()
            try:
                client = SharedSpeechClient(service.path)
                client.emit_query_response(state=state, query_kind='fuel_status')
                result = client.emit_query_response(state=state, query_kind='tyre_status')
                checks[f'{changed}_initially_queued'] = result['output_lifecycle']['event']['event_type']=='enqueue' and len(backend._handles)==1
                latest = deepcopy(state)
                if changed: latest.player.tyre.wear_pct += .2
                else: latest.player.speed_kph += 1
                writer.append(latest, StrategyDecision([]))
                backend.complete_all()
                deadline = time.monotonic()+.6
                while service.output._pending_envelope is not None and time.monotonic()<deadline: time.sleep(.005)
                if changed:
                    checks['changed_pending_never_starts'] = len(backend._handles)==1 and service.output._active_envelope is None
                    deadline = time.monotonic()+.3
                    while not any(e['event'].get('metadata',{}).get('reason')=='delivery_no_longer_applicable' for e in service.driver.events) and time.monotonic()<deadline: time.sleep(.005)
                    checks['suppression_is_observable'] = any(e['event'].get('metadata',{}).get('reason')=='delivery_no_longer_applicable' for e in service.driver.events)
                else:
                    checks['unchanged_pending_can_start'] = len(backend._handles)==2 and service.output._active_envelope is not None
                checks[f'{changed}_scheduler_keeps_running'] = service.driver.last_error is None and service.driver._thread.is_alive()
            finally: checks[f'{changed}_closed'] = service.close()
    return {'passed':all(checks.values()), 'checks':checks}


if __name__=='__main__': emit_result(run())
