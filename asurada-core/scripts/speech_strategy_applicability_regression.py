from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from regression_support import emit_result
from phase3_voice_regression import FakeSpeechBackend, make_state
from asurada.strategy import StrategyEngine
from asurada.config import StrategyThresholds
from asurada.output import ConsoleVoiceOutput
from asurada.speech_service import SpeechService
from asurada.speech_client import SharedSpeechClient
from asurada.live_dashboard_feed import LatestSnapshotWriter


def run():
    checks = {}
    engine = StrategyEngine(StrategyThresholds())
    for changed in (True, False):
        with TemporaryDirectory(dir='/tmp', prefix='speech-strategy-') as temp:
            state = make_state()
            state.source_timestamp_ms = int(time.time()*1000)
            state.player.ers_pct = 5
            state.raw.update(timing_mode='session_type_estimated', session_type='race')
            decision = engine.evaluate(state)
            assert decision.messages[0].code == 'ERS_LOW'
            writer = LatestSnapshotWriter(Path(temp))
            writer.append(state, decision)
            backend = FakeSpeechBackend()
            service = SpeechService(Path(temp)/'voice.sock', output=ConsoleVoiceOutput(backend=backend), session_source=writer.path).start()
            try:
                client = SharedSpeechClient(service.path)
                for field in ('messages', 'voice'):
                    altered = deepcopy(decision)
                    if field == 'messages': altered.messages[0].title = '伪造动作'
                    else: altered.debug['arbiter_v2']['output']['final_voice_action']['speak_text'] = '伪造播报'
                    try:
                        client.emit(altered, state=state)
                        checks[f'{changed}_{field}_tamper_rejected'] = False
                    except RuntimeError as exc:
                        checks[f'{changed}_{field}_tamper_rejected'] = 'not_bound' in str(exc) and len(backend._handles)==0
                client.emit_query_response(state=state, query_kind='fuel_status')
                queued = client.emit(decision, state=state)
                checks[f'{changed}_real_strategy_queued'] = queued['event']['event_type']=='enqueue'
                latest = deepcopy(state)
                latest.source_timestamp_ms += 1
                if changed: latest.player.ers_pct = 67
                else: latest.player.speed_kph += 1
                current = engine.evaluate(latest)
                writer.append(latest, current)
                backend.complete_all()
                until = time.monotonic()+.6
                while service.output._pending_envelope is not None and time.monotonic()<until: time.sleep(.005)
                checks[f'{changed}_queued_decision_revalidated'] = len(backend._handles)==(1 if changed else 2)
                checks[f'{changed}_scheduler_healthy'] = service.driver.last_error is None
            finally: checks[f'{changed}_closed'] = service.close()
    return {'passed':all(checks.values()), 'checks':checks}


if __name__=='__main__': emit_result(run())
