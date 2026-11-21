from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from regression_support import emit_result
from phase3_voice_regression import make_state
from asurada.app import AsuradaApp
from asurada.config import UdpConfig
from asurada.live_dashboard_feed import DashboardFeedWriter
from asurada.models import StrategyDecision
from asurada.pdu import RawPacket
from asurada.replay import ReplayLogger
from asurada.runtime_pipeline import StrategyRuntimePipeline
from asurada.snapshot_contract import snapshot_payload
from asurada.speech_submission import LiveSpeechSubmission
from asurada.state import UnifiedStateStore


def until(predicate):
    deadline = time.monotonic() + 2
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.002)
    assert predicate(), 'worker did not reach expected state'


class Backend:
    externally_driven = True
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.fail = False
    def emit(self, decision, *, state, render):
        self.calls.append((state.lap_number, deepcopy(decision.debug)))
        self.entered.set()
        assert self.release.wait(3), 'test backend release missing'
        decision.debug['late_mutation'] = True
        if self.fail:
            raise ConnectionError('owner_disconnected')
        return {'event': {'event_type': 'start'}}
    def shutdown(self):
        return True


def run():
    checks = {}
    state = make_state()
    backend = Backend()
    submit = LiveSpeechSubmission(backend, max_age_s=.05)
    try:
        decision = StrategyDecision([], debug={})
        receipt = submit.emit(decision, state=state, render=False)
        assert backend.entered.wait(1)
        started = time.monotonic()
        for lap in range(20, 120):
            state.lap_number = lap
            submit.emit(StrategyDecision([], debug={}), state=state, render=False)
        checks['slow_owner_does_not_block_producer'] = time.monotonic()-started < .25
        health = submit.snapshot()
        checks['one_worker_one_pending'] = health['pending']==1 and health['in_flight']==1 and health['counts']['superseded']==99
        checks['submission_is_not_playback'] = receipt['event']['event_type']=='submission_accepted'
        time.sleep(.06)
        backend.release.set()
        until(lambda: submit.snapshot()['counts'].get('expired')==1)
        checks['expired_pending_not_sent'] = len(backend.calls)==1
        checks['worker_cannot_mutate_logged_decision'] = 'late_mutation' not in decision.debug
        checks['state_is_frozen'] = backend.calls[0][0]==8
        backend.fail = True
        submit.emit(StrategyDecision([]), state=state, render=False)
        until(lambda: submit.snapshot()['counts'].get('delivery_unknown')==1)
        checks['failed_delivery_not_retried'] = len(backend.calls)==2
        backend.fail = False
        submit.emit(StrategyDecision([]), state=state, render=False)
        until(lambda: submit.snapshot()['counts'].get('acknowledged')==2)
        checks['next_fresh_submission_recovers'] = len(backend.calls)==3
    finally:
        backend.release.set()
        checks['submission_worker_closes'] = submit.close()

    backend = Backend()
    submit = LiveSpeechSubmission(backend)
    try:
        submit.emit(StrategyDecision([]), state=state, render=False)
        assert backend.entered.wait(1)
        submit.emit(StrategyDecision([]), state=state, render=False)
        started = time.monotonic()
        stopped = submit.close(timeout_s=.01)
        checks['unconfirmed_close_is_bounded_and_reported'] = not stopped and time.monotonic()-started < .1
        result = submit.emit(StrategyDecision([]), state=state, render=False)
        checks['close_discards_pending_and_rejects_new_work'] = result['event']['event_type']=='submission_rejected' and submit.snapshot()['pending']==0
    finally:
        backend.release.set()
        checks['inflight_finishes_without_replaying_closed_queue'] = submit.close() and len(backend.calls)==1

    # Execute the production pipeline and app wiring, without sockets or audio.
    backend = Backend()
    class Strategy:
        observation_lane = planning_lane = None
        def enable_background_observations(self): pass
        def enable_background_planning(self): pass
        def evaluate(self, state, history): return StrategyDecision([], debug={})
    class Source:
        def close(self): return True
        def snapshot(self): return {}
    seen = []
    class Live:
        def __init__(self, source, **kwargs):
            self.kwargs = kwargs
        def run(self):
            k = self.kwargs
            checks['actual_live_entry_wired'] = isinstance(k['voice_output'], LiveSpeechSubmission)
            pipeline = StrategyRuntimePipeline(**{name:k[name] for name in ('state_store','strategy','voice_output','logger')})
            payload = snapshot_payload(make_state(), StrategyDecision([]))
            pipeline.decoder = SimpleNamespace(decode_raw=lambda packet: object())
            pipeline.assembler = SimpleNamespace(push=lambda envelope: deepcopy(payload))
            result = pipeline.ingest_packet(RawPacket(1000,b'', 'test', 1))
            assert backend.entered.wait(1)
            started = time.monotonic()
            for index in range(20):
                payload['source_timestamp_ms'] += 1
                seen.append(pipeline.ingest_packet(RawPacket(1000,b'', 'test', 1)))
            checks['pipeline_keeps_processing_during_blocked_ipc'] = time.monotonic()-started < .3 and all(s.submitted and not s.emitted for s in seen)
            backend.fail = True
            backend.release.set()
            until(lambda: k['voice_output'].snapshot()['counts'].get('delivery_unknown',0)>=1)
            result = pipeline.ingest_packet(RawPacket(1000,b'', 'test', 1))
            checks['pipeline_survives_connection_error'] = result.submitted and not result.emitted
            until(lambda: k['voice_output'].snapshot()['pending']==0 and k['voice_output'].snapshot()['in_flight']==0)
    with TemporaryDirectory() as temp:
        app = AsuradaApp.__new__(AsuradaApp)
        app.logger = ReplayLogger(Path(temp))
        app.live_dashboard_feed = DashboardFeedWriter(Path(temp)/'dashboard')
        app.state_store = UnifiedStateStore()
        app.strategy = Strategy()
        app.voice_output = backend
        try:
            with patch('asurada.app.LiveRuntime', Live), patch('asurada.app.BufferedPacketSource', lambda *a,**k:Source()):
                app.run_live_udp(UdpConfig())
            checks['all_pipeline_frames_logged'] = len(app.logger.path.read_text().splitlines())==22
        finally:
            backend.release.set()
    return dict(passed=all(checks.values()), checks=checks)


if __name__=='__main__': emit_result(run())
