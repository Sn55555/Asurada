import time
import uuid
from regression_support import emit_result
from phase3_voice_regression import FakeSpeechBackend, make_state, make_strategy_decision
from asurada.output import ConsoleVoiceOutput
from asurada.speech_driver import SpeechOutputDriver
from asurada.speech_service import SpeechService


def run():
    backend=FakeSpeechBackend();output=ConsoleVoiceOutput(backend=backend);state=make_state()
    def emit(code,priority):output.emit(make_strategy_decision(state=state,code=code,priority=priority,title=code,detail=''),render=False)
    with SpeechOutputDriver(output,interval_s=.005) as driver:
        emit('ERS_LOW',60);emit('LOW_FUEL',95);backend.complete_all()
        deadline=time.monotonic()+.5
        # Backend.start publishes the handle before tick returns its event.
        # Wait for both observations instead of racing the scheduler thread.
        while (len(backend._handles)<2 or not any(item['event']['event_type']=='start' for item in driver.events)) and time.monotonic()<deadline:time.sleep(.005)
        checks={'independent_queue_progress':len(backend._handles)==2 and backend._handles[-1]['job']['action_code']=='LOW_FUEL',
                'event_retained':any(item['event']['event_type']=='start' for item in driver.events)}
    checks['driver_and_playback_stop']=not driver._thread.is_alive() and not output.is_playing() and output._pending_envelope is None and driver.last_error is None
    class FlakyObservation(FakeSpeechBackend):
        broken = False
        def is_active(self, handle):
            if self.broken:
                raise OSError('fixture status unavailable')
            return super().is_active(handle)
    backend=FlakyObservation();output=ConsoleVoiceOutput(backend=backend)
    emit('ERS_LOW',60);emit('LOW_FUEL',95)
    active_id=output._active_envelope.job.output_event_id
    backend.broken=True
    with SpeechOutputDriver(output,interval_s=.005) as driver:
        deadline=time.monotonic()+.5
        while output.playback_health['consecutive_failures'] < 2 and time.monotonic()<deadline:time.sleep(.005)
        checks['observation_failure_visible']=output.playback_health['status']=='unknown' and output.playback_health['consecutive_failures']>=2
        checks['unknown_player_retains_owner']=(output._active_envelope.job.output_event_id==active_id
            and len(backend._handles)==1 and driver._thread.is_alive() and driver.last_error is None)
        service=SpeechService('/tmp/asurada-observation-unused.sock',output=output)
        service.driver=driver
        health=service.dispatch(dict(version='speech-ipc-v1',request_id=uuid.uuid4().hex,
            expires_at=time.time()+1,method='health',params={}))
        checks['service_exposes_unknown_playback']=health['playback_health']['status']=='unknown'
        backend.complete_all();backend.broken=False
        deadline=time.monotonic()+.5
        while len(backend._handles)<2 and time.monotonic()<deadline:time.sleep(.005)
        checks['observation_recovers_without_driver_restart']=len(backend._handles)==2 and output.playback_health['status']=='current'
    return {'passed':all(checks.values()),'checks':checks}

if __name__=='__main__':emit_result(run())
