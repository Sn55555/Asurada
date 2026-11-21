import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from regression_support import emit_result, runtime_clock
from phase3_llm_sidecar_integration_regression import _make_state, _make_turn
from asurada.live_dashboard_feed import LatestSnapshotWriter
from asurada.models import StrategyDecision
from asurada.published_session import PublishedSessionProbe
from asurada.voice_interrupt import VoiceTurnInterruption
from asurada.voice_input import VoiceInputCoordinator
from asurada.llm_explainer import LlmExplainer
from asurada.task_runtime import TaskCancelled


@runtime_clock(1777200000000)
def run():
    checks = {}
    state = _make_state()
    state.source_timestamp_ms = 1777200000000
    calls = []
    class Output:
        def emit_voice_query_bundle(self, **kwargs): calls.append('voice');return {}
        def emit_control_query_bundle(self, **kwargs): calls.append('control');return {}
    with TemporaryDirectory() as directory:
        writer = LatestSnapshotWriter(Path(directory))
        def publish(uid=None, epoch=None):
            if uid is not None: state.session_uid=uid
            if epoch is not None: state.session_epoch=epoch
            writer.append(state, StrategyDecision([]))
        publish('race-a', 0)
        probe = PublishedSessionProbe(writer.path, wall_clock=lambda:1777200000)
        checks['reads_actual_atomic_publication'] = probe()==('race-a',0)
        with VoiceTurnInterruption(Output(), scope_probe=probe) as gate:
            context=gate.begin(state=state)
            publish()
            gate._check_scope(context)
            checks['same_scope_updates_keep_turn'] = not context.cancellation.is_set()
            publish('race-b',0)
            checks['watcher_cancels_without_completed_turn'] = context.cancellation.wait(.3) and gate.cancel_reason=='session_scope_changed'
            checks['scope_change_does_not_stop_new_scene_audio'] = calls==[]
            context=gate.begin(state=state)
            publish(epoch=1)
            checks['rewind_epoch_cancels'] = context.cancellation.wait(.3)
            context=gate.begin(state=state)
            writer.reset()
            checks['publisher_reset_cancels'] = context.cancellation.wait(.3)
            publish()
            context=gate.begin(state=state)
            state.source_timestamp_ms-=15001
            publish()
            checks['stale_publication_cancels'] = context.cancellation.wait(.3)
            state.source_timestamp_ms=1777200000000
            publish()
            context=gate.begin(state=state)
            writer.path.write_text('{broken')
            checks['invalid_publication_cancels'] = context.cancellation.wait(.3)
        checks['watcher_closes'] = not gate._watcher.is_alive()
        # No watcher: the delivery gate must independently re-read authority.
        publish('delivery-a',0)
        gate=VoiceTurnInterruption(Output(), scope_probe=probe)
        context=gate.begin(state=state)
        publish('delivery-b',0)
        try:
            gate.output_for(context).emit_voice_query_bundle()
            checks['delivery_rechecks_even_without_watcher_tick']=False
        except TaskCancelled:
            checks['delivery_rechecks_even_without_watcher_tick']=calls==[]
        # Verify actual LLM wait terminates on publication change, not only a flag.
        entered=threading.Event(); release=threading.Event()
        class Slow:
            name='scope-test-llm'
            def explain(self, request): entered.set();release.wait(3);return {}
        coordinator=VoiceInputCoordinator(llm_explainer=LlmExplainer(backend=Slow()), enable_llm_sidecar=True, llm_timeout_ms=2000)
        results=[]
        with VoiceTurnInterruption(Output(), scope_probe=probe) as gate:
            context=gate.begin(state=state)
            worker=threading.Thread(target=lambda:results.append(coordinator.process_completed_turn(
                state=state,turn=_make_turn('整体形势怎么样','scope-llm'),voice_output=gate.output_for(context),context=context,render=False)))
            worker.start()
            try:
                assert entered.wait(1)
                # Publish a new scope without mutating the worker's input object.
                row=json.loads(writer.path.read_text());row['session_epoch']+=1
                temp=writer.path.with_suffix('.json.tmp');temp.write_text(json.dumps(row));temp.replace(writer.path)
                worker.join(.3)
                checks['real_coordinator_cancels_slow_llm_on_epoch_change']=not worker.is_alive() and results[0].status=='cancelled' and not release.is_set() and calls==[]
            finally:
                release.set();worker.join(1)
    return dict(passed=all(checks.values()), checks=checks)


if __name__=='__main__': emit_result(run())
