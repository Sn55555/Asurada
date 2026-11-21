"""Local lifecycle checks with socketpairs; no listening port is opened."""
import socket
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from regression_support import emit_result
from dashboard_transport_regression import server
from observation_lane_regression import eventually


def run():
    source = SimpleNamespace(latest_payload_bytes=lambda:b'{"current":true}')
    service = server.DashboardHttpServer(0,source,max_clients=1)
    first, peer = socket.socketpair()
    second, other = socket.socketpair()
    peer.settimeout(1);other.settimeout(1)
    try:
        checks={'first_request_admitted':service._dispatch(first)}
        checks['capacity_refused']=not service._dispatch(second) and other.recv(1)==b''
        checks['active_request_tracked']=service.snapshot()['active_connections']==1
        checks['close_interrupts_pending_request']=service.close() and peer.recv(1)==b''
        checks['workers_drained']=service.snapshot()['workers']==0 and service.snapshot()['active_connections']==0
        checks['close_idempotent']=service.close()
    finally:
        service.close();peer.close();other.close()
    conn, peer = socket.socketpair()
    service = server.DashboardHttpServer(0,source)
    peer.settimeout(1)
    try:
        service._dispatch(conn)
        peer.sendall(b'GET /api/latest HTTP/1.1\r\nHost: localhost\r\n\r\n')
        data=b''
        while True:
            chunk=peer.recv(4096)
            if not chunk:break
            data+=chunk
        checks['http_response_preserved']=data.startswith(b'HTTP/1.1 200') and data.endswith(b'{"current":true}')
        checks['completed_request_removed']=eventually(lambda:service.snapshot()['workers']==0)
    finally:
        service.close();peer.close()
    meter = server.VoiceMeterSocketCache()
    conn, peer = socket.socketpair(type=socket.SOCK_DGRAM)
    conn.settimeout(.2)
    meter._socket=conn
    meter._thread=threading.Thread(target=meter._run,daemon=True)
    meter._thread.start()
    try:
        checks['meter_receiver_stopped']=meter.close()
    finally:
        meter.close();peer.close()
    closed=[]
    class Meter:
        host='local';port=0
        def start(self):pass
        def close(self):closed.append('meter')
    class BrokenWebSocket:
        def __init__(self,*args):pass
        def start(self):raise OSError('fixture startup failure')
        def close(self):closed.append('websocket')
    args=SimpleNamespace(feed_path=Path('unused'),ws_port=0,http_port=0)
    with patch.object(server,'parse_args',return_value=args), patch.object(server,'VoiceMeterSocketCache',Meter), patch.object(server,'DashboardWebSocketServer',BrokenWebSocket):
        try:server.main()
        except OSError:pass
    checks['startup_failure_cleans_started_services']=closed==['websocket','meter']
    class FailedSocket:
        closed=False
        def setsockopt(self,*args):pass
        def bind(self,*args):raise OSError('fixture bind failure')
        def close(self):self.closed=True
    failed=FailedSocket()
    with patch.object(server.socket,'socket',return_value=failed):
        server.VoiceMeterSocketCache().start()
    checks['meter_bind_failure_closes_socket']=failed.closed
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':
    emit_result(run())
