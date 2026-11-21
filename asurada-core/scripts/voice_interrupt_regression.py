import threading
import time
from unittest.mock import patch
from regression_support import emit_result, runtime_clock
from phase3_llm_sidecar_integration_regression import _make_state, _make_turn
from phase3_voice_regression import FakeSpeechBackend
from phase3_macos_voice_loop import _ControlChannel
from asurada.output import ConsoleVoiceOutput
from asurada.llm_explainer import LlmExplainer
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_interrupt import VoiceTurnInterruption
from asurada.task_runtime import TaskCancelled


@runtime_clock(1777200000000)
def run():
    checks = {}
    entered = threading.Event()
    release = threading.Event()
    class Slow:
        name = 'controlled_slow_llm'
        def explain(self, request):
            entered.set()
            release.wait(3)
            return {'status':'answerable', 'answer_text':'late', 'confidence':.8,
                    'reason_fields':[], 'requires_confirmation':False, 'metadata':{}}
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    state = _make_state()
    output.emit_query_response(state=state, query_kind='fuel_status', render=False)
    control = VoiceTurnInterruption(output)
    context = control.begin()
    coordinator = VoiceInputCoordinator(llm_explainer=LlmExplainer(backend=Slow()),
                                         enable_llm_sidecar=True, llm_timeout_ms=2000)
    results = []
    def process():
        results.append(coordinator.process_completed_turn(state=state,
            turn=_make_turn('整体形势怎么样','interrupt-test'), voice_output=control.output_for(context),
            render=False, context=context))
    worker = threading.Thread(target=process)
    worker.start()
    try:
        assert entered.wait(1), 'LLM not entered'
        import os
        read_fd, write_fd = os.pipe()
        channel = _ControlChannel(on_stop=lambda:control.stop(state), input_fd=read_fd)
        started = time.monotonic()
        # Exercise the same independent stdin reader used by the live loop.
        try:
            channel.start()
            os.write(write_fd, b's\nq\n')
            channel._thread.join(1)
        finally:
            channel.close()
            os.close(read_fd); os.close(write_fd)
        worker.join(.3)
        checks['stop_reader_runs_while_llm_blocked'] = not channel._thread.is_alive() and time.monotonic()-started < .4
        checks['cancel_returns_before_backend_finishes'] = not worker.is_alive() and results[0].status=='cancelled' and not release.is_set()
        checks['stop_clears_current_playback'] = not output.is_playing() and output._pending_envelope is None
        count = len(backend._handles)
        release.set()
        worker.join(1)
        checks['no_fallback_or_late_reply_spoken'] = len(backend._handles)==count==1 and results[0].output_debug is None
        # A recognized result arriving after stop must not enter routing/LLM.
        result = coordinator.process_completed_turn(state=state, turn=_make_turn('油量如何','late-asr'),
            voice_output=control.output_for(context), context=context, render=False)
        checks['late_recognition_discarded'] = result.status=='cancelled' and len(backend._handles)==1
        fresh = control.begin()
        result = coordinator.process_completed_turn(state=state, turn=_make_turn('油量如何','fresh-asr'),
            voice_output=control.output_for(fresh), context=fresh, render=False)
        checks['new_turn_after_stop_can_speak'] = result.status=='processed' and result.delivery['status']=='started' and len(backend._handles)==2
    finally:
        release.set()
        worker.join(1)
        output.shutdown()

    started = threading.Event()
    finish = threading.Event()
    events = []
    class BlockingDelivery:
        def emit_voice_query_bundle(self, **kwargs):
            started.set()
            finish.wait(2)
            events.append('deliver')
        def emit_control_query_bundle(self, **kwargs): events.append('stop')
    gate = VoiceTurnInterruption(BlockingDelivery())
    context = gate.begin()
    delivery = threading.Thread(target=lambda:gate.output_for(context).emit_voice_query_bundle())
    delivery.start()
    assert started.wait(1)
    stopper = threading.Thread(target=lambda:gate.stop(state))
    stopper.start()
    assert context.cancellation.wait(1)
    checks['cancellation_immediate_during_delivery'] = not finish.is_set()
    finish.set()
    delivery.join(1)
    stopper.join(1)
    checks['stop_ordered_after_inflight_delivery'] = events==['deliver','stop']
    try:
        gate.output_for(context).emit_voice_query_bundle()
        checks['cancelled_turn_cannot_deliver_after_stop'] = False
    except TaskCancelled:
        checks['cancelled_turn_cannot_deliver_after_stop'] = events==['deliver','stop']
    channel = _ControlChannel()
    for _ in range(100): channel.accept('r')
    checks['control_queue_bounded'] = channel._commands.qsize()==8
    channel.accept('q')
    checks['quit_not_lost_behind_reload_flood'] = channel.poll_command()=='q' and channel.poll_command() is None
    return dict(passed=all(checks.values()), checks=checks)


if __name__=='__main__': emit_result(run())
