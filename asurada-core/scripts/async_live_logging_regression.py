import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from regression_support import emit_result
from phase3_voice_regression import make_state
from asurada.app import AsuradaApp
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from asurada.config import UdpConfig
from asurada.models import StrategyDecision
from asurada.pdu import RawPacket
from asurada.replay import ReplayLogger
from asurada.live_dashboard_feed import DashboardFeedWriter


def run():
    health=[]
    class FakeLive:
        def __init__(self,source,**kwargs):
            self.logger=kwargs['logger']
            self.recorder=kwargs['packet_recorder']
        def run(self):
            self.recorder.append(RawPacket(1000,b'abc','test',1))
            state=make_state(); state.session_epoch=2
            self.logger.append(state,StrategyDecision(messages=[],debug={}))
            health.append(self.logger)
    with TemporaryDirectory() as temp:
        app=AsuradaApp.__new__(AsuradaApp)
        app.logger=ReplayLogger(Path(temp))
        app.live_dashboard_feed=DashboardFeedWriter(Path(temp)/'dashboard')
        app.state_store=None
        class FakeStrategy:
            observation_lane=None
            planning_lane=None
            def enable_background_observations(self):pass
            def enable_background_planning(self):pass
        app.strategy=FakeStrategy()
        app.voice_output=ConsoleVoiceOutput(backend=NullSpeechBackend())
        with patch('asurada.app.LiveRuntime',FakeLive):
            app.run_live_udp(UdpConfig(), capture_path=Path(temp)/'raw.jsonl')
        rows=[json.loads(line) for line in app.logger.path.read_text().splitlines()]
        feed=json.loads(app.live_dashboard_feed.path.read_text())
        capture_health=json.loads((Path(temp)/'raw.jsonl.health.json').read_text())
        checks={'capture_uses_async_and_drains':capture_health['finalized'] and capture_health['sink']['written']==1 and not capture_health['sink']['worker_alive'],
                'live_entry_uses_async_sinks':len(health[0].snapshot())==3,
                'exit_flushes_replay':len(rows)==1 and rows[0]['session_epoch']==2,
                'exit_flushes_dashboard':bool(feed),
                'workers_closed':all(not item['worker_alive'] and item['written']==1 and item['failures']==0 for item in health[0].snapshot().values())}
    return {'passed':all(checks.values()),'checks':checks}

if __name__=='__main__': emit_result(run())
