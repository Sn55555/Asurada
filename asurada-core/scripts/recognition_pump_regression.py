"""A blocked coordinator does not block wake-qualified spoken stop recognition."""
import queue
import threading
import time
from types import SimpleNamespace
from asurada.recognition_pump import RecognitionPump
from asurada.voice_interrupt import VoiceTurnInterruption
from asurada.voice_input import VoiceInputCoordinator
from asurada.llm_explainer import LlmExplainer
from asurada.output import ConsoleVoiceOutput
from asurada.task_runtime import TaskContext
from phase3_voice_regression import FakeSpeechBackend
from phase3_llm_sidecar_integration_regression import _make_state, _make_turn
from regression_support import emit_result, runtime_clock


@runtime_clock(1777200000000)
def run():
    source=queue.Queue();entered=threading.Event();release=threading.Event()
    class Recognizer:
        supports_task_context=True
        def listen_once(self,context):
            while True:
                context.remaining()
                try:return source.get(timeout=.01)
                except queue.Empty:pass
    class Slow:
        name='blocked-fixture'
        def explain(self,request):entered.set();release.wait(3);return {}
    backend=FakeSpeechBackend();output=ConsoleVoiceOutput(backend=backend);state=_make_state()
    output.emit_query_response(state=state,query_kind='fuel_status',render=False)
    gate=VoiceTurnInterruption(output);context=gate.begin(state=state);stopped=threading.Event()
    def stop():gate.stop(state);stopped.set()
    scope=[('scope',0)]
    pump=RecognitionPump(Recognizer(),wake_phrases=('阿斯拉',),on_stop=stop,scope_probe=lambda:scope[0]).start()
    coordinator=VoiceInputCoordinator(llm_explainer=LlmExplainer(backend=Slow()),enable_llm_sidecar=True,llm_timeout_ms=2000)
    results=[]
    worker=threading.Thread(target=lambda:results.append(coordinator.process_completed_turn(state=state,
        turn=_make_turn('整体形势怎么样','pump-llm'),voice_output=gate.output_for(context),context=context,render=False)))
    checks={}
    try:
        worker.start();assert entered.wait(1)
        source.put(SimpleNamespace(status='recognized',transcript_text='阿斯拉停止'))
        assert stopped.wait(1);worker.join(.5)
        checks['spoken_stop_while_llm_waits']=not worker.is_alive() and not release.is_set() and results[0].status=='cancelled'
        checks['spoken_stop_clears_playback']=not output.is_playing() and output._pending_envelope is None
        checks['no_late_delivery']=len(backend._handles)==1
        for n in range(5):source.put(SimpleNamespace(status='recognized',transcript_text=str(n)))
        deadline=time.monotonic()+1
        while pump.dropped<4 and time.monotonic()<deadline:time.sleep(.01)
        checks['single_pending_result']=pump._results.qsize()==1 and pump.dropped==4
        result=pump.next_result(TaskContext.start('read',1000))
        checks['newest_pending_result']=result.transcript_text=='4'
        pump.invalidate()
        source.put(SimpleNamespace(status='recognized',transcript_text='old-scope'))
        deadline=time.monotonic()+1
        while pump._results.empty() and time.monotonic()<deadline:time.sleep(.01)
        scope[0]=('new-scope',0)
        try:pump.next_result(TaskContext.start('scope-read',60));checks['stale_scope_dropped']=False
        except TimeoutError:checks['stale_scope_dropped']=True
    finally:
        release.set();worker.join(1)
        checks['pump_closes']=pump.close();output.shutdown(timeout_s=.1)
    return {'passed':all(checks.values()),'checks':checks,'scope':'real recognition pump and coordinator with queued transcripts; no acoustic or cloud ASR acceptance'}


if __name__=='__main__':emit_result(run())
