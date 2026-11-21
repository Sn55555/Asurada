import importlib.util
from pathlib import Path
import sys
from threading import Event
import time
from types import SimpleNamespace
from regression_support import emit_result
from observation_lane_regression import eventually

DASHBOARD=Path(__file__).resolve().parents[2]/'live-dashboard'
sys.path.insert(0,str(DASHBOARD))
spec=importlib.util.spec_from_file_location('dashboard_transport_server',DASHBOARD/'server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
from ws_client import LatestStateClient


class Connection:
    def __init__(self,blocked=False):
        self.entered=Event();self.release=Event();self.frames=[];self.closed=False
        if not blocked:self.release.set()
    def settimeout(self,value):self.timeout=value
    def sendall(self,frame):
        self.entered.set();self.release.wait(2)
        if not self.closed:self.frames.append(frame)
    def shutdown(self,*args):self.closed=True;self.release.set()
    def close(self):self.closed=True


def run():
    broadcast=server.DashboardWebSocketServer('127.0.0.1',0,SimpleNamespace(latest_payload_bytes=lambda:b'{}'))
    slow,fast=Connection(True),Connection()
    clients=[LatestStateClient(connection,on_close=broadcast._remove_client) for connection in (slow,fast)]
    broadcast._clients.update(clients)
    for client in clients:client.start()
    broadcast._broadcast_text(b'first')
    slow.entered.wait(1)
    checks={'fast_not_blocked_by_slow':eventually(lambda:bool(fast.frames))}
    started=time.monotonic()
    for index in range(100):broadcast._broadcast_text(str(index).encode())
    checks['broadcast_nonblocking']=time.monotonic()-started<.1
    checks['slow_queue_bounded']=clients[0].snapshot()['queued']==1 and clients[0].snapshot()['coalesced']>=99
    slow.release.set()
    checks['slow_gets_latest_pending_state']=eventually(lambda:len(slow.frames)==2) and slow.frames[-1].endswith(b'99')
    checks['fast_gets_latest_state']=eventually(lambda:fast.frames[-1].endswith(b'99'))
    checks['close_stops_all_senders']=broadcast.close() and all(not client.snapshot()['worker_alive'] for client in clients)
    class Broken(Connection):
        def sendall(self,frame):raise TimeoutError('slow consumer')
    failed=LatestStateClient(Broken(),on_close=broadcast._remove_client)
    broadcast._clients.add(failed);failed.start();failed.offer(b'x')
    checks['send_timeout_disconnects']=eventually(lambda:failed.snapshot()['closed'])
    failed.close()
    checks['failure_health_counted']=broadcast.snapshot()['send_errors']==1
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())
