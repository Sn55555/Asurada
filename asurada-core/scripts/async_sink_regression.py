import threading
import time
from regression_support import emit_result
from asurada.async_sink import AsyncRuntimeSink


def run():
    entered=threading.Event(); release=threading.Event(); seen=[]
    class Sink:
        def append(self,state,decision):
            entered.set(); release.wait(2); seen.append((state,decision))
    sink=AsyncRuntimeSink(Sink(),capacity=1)
    state={'n':1}; started=time.monotonic(); sink.append(state,{}); elapsed=time.monotonic()-started
    entered.wait(.5); state['n']=99
    sink.append({'n':2},{})
    dropped=not sink.append({'n':3},{})
    checks={'append_does_not_wait_for_writer':elapsed < .1 and not release.is_set(), 'bounded_drop_visible':dropped and sink.snapshot()['dropped']==1 and sink.snapshot()['queued']==1}
    checks['close_timeout_reports_live_worker']=not sink.close(.01) and sink.snapshot()['worker_alive']
    release.set(); checks['close_drains']=sink.close(1) and seen==[({'n':1},{}),({'n':2},{})]
    entered.clear(); release.clear(); seen.clear()
    sink=AsyncRuntimeSink(Sink(),latest_only=True)
    sink.append(1,{}); entered.wait(.5); sink.append(2,{}); sink.append(3,{})
    release.set(); sink.close(1)
    checks['feed_coalesces_latest']=seen==[(1,{}),(3,{})] and sink.snapshot()['coalesced']==1
    class Failing:
        def append(self,state,decision): raise OSError('injected disk failure')
    sink=AsyncRuntimeSink(Failing()); sink.append(1,{}); sink.close(1)
    checks['failure_visible']=sink.snapshot()['failures']==1 and sink.snapshot()['written']==0 and 'injected' in sink.snapshot()['last_error']
    return {'passed':all(checks.values()),'checks':checks,'analysis':{'append_ms':round(elapsed*1000,3)}}

if __name__=='__main__': emit_result(run())
