"""Exercise the actual CLI main loop while an existing voice is playing."""
import contextlib
import io
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import phase3_macos_voice_loop as loop
from asurada.output import ConsoleVoiceOutput
from phase3_voice_regression import make_state, FakeSpeechBackend
from regression_support import emit_result


def run():
    stopped=threading.Event();controls=[];seen=[];errors=[];results=[]
    class Backend(FakeSpeechBackend):
        def stop(self, handle):
            if threading.current_thread().name=='voice-recognition-pump':stopped.set()
            super().stop(handle)
    backend=Backend();output=ConsoleVoiceOutput(backend=backend)
    state=make_state();state.source_timestamp_ms=int(time.time()*1000)
    output.emit_query_response(state=state,query_kind='fuel_status',render=False)
    class Recognizer:
        supports_task_context=True
        def listen_once(self,context):
            if not seen:
                seen.append(output.is_playing())
                return SimpleNamespace(status='recognized',transcript_text='阿斯拉停止')
            while True:context.remaining();time.sleep(.005)
    class Control(loop._ControlChannel):
        def start(self):controls.append(self)
    def invoke():
        try:results.append(loop.main())
        except BaseException as exc:errors.append(repr(exc))
    argv=['voice-loop','--spoken-interrupt','--wake-phrase','阿斯拉','--row','first','--no-auto-refresh','--loop-idle-ms','0']
    with patch('sys.argv',argv),patch.object(loop,'live_speech_client',return_value=output),\
         patch.object(loop,'wait_for_state_and_message',return_value=(state,None)),\
         patch.object(loop,'_build_recognizer',return_value=Recognizer()),\
         patch.object(loop,'_ControlChannel',Control),\
         patch.object(loop,'_is_downlink_playback_active',return_value=False),\
         contextlib.redirect_stdout(io.StringIO()):
        worker=threading.Thread(target=invoke,daemon=True)
        worker.start()
        did_stop=stopped.wait(1)
        deadline=time.monotonic()+2
        while worker.is_alive() and time.monotonic()<deadline:
            if controls:controls[0].accept('q')
            worker.join(.02)
    checks={'main_listens_during_playback':seen==[True],
            'main_spoken_stop_reaches_backend':did_stop,
            'main_exits_cleanly':not worker.is_alive() and results==[0] and not errors,
            'no_late_playback':len(backend._handles)==1 and not output.is_playing(),
            'recognition_pump_closed':not any(t.name=='voice-recognition-pump' for t in threading.enumerate())}
    return {'passed':all(checks.values()),'checks':checks,'errors':errors,
            'scope':'Real CLI main with fake recognizer/playback and controlled stdin; no physical audio or ASR accuracy acceptance'}


if __name__=='__main__':emit_result(run())
