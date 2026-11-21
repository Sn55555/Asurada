import socket
from types import SimpleNamespace
from regression_support import emit_result
from dashboard_transport_regression import server


def receive_frame(stream):
    header=stream.read(2)
    if len(header)!=2:raise ValueError('missing_frame')
    length=header[1]&127
    if length==126:length=int.from_bytes(stream.read(2),'big')
    elif length==127:length=int.from_bytes(stream.read(8),'big')
    return stream.read(length)


def run():
    source=SimpleNamespace(latest_payload_bytes=lambda:b'{"session":"current"}')
    service=server.DashboardWebSocketServer('127.0.0.1',0,source)
    service.start()
    try:
        with socket.create_connection(('127.0.0.1',service.port),timeout=1) as client:
            client.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n')
            with client.makefile('rb') as stream:
                headers=[]
                while True:
                    line=stream.readline()
                    if line in (b'\r\n',b''):break
                    headers.append(line)
                checks={'real_handshake':headers[0].startswith(b'HTTP/1.1 101'),
                        'new_client_receives_current_state':receive_frame(stream)==b'{"session":"current"}'}
                service._broadcast_text(b'{"sequence":2}')
                checks['real_frame_delivery']=receive_frame(stream)==b'{"sequence":2}'
    finally:
        closed=service.close()
    checks['service_shutdown']=closed and not service.snapshot()['clients']
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())
