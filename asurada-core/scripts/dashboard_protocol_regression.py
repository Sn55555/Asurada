"""Exercise dashboard wire behavior over a connected socket pair, without a listener."""
import socket
import threading
from types import SimpleNamespace
from regression_support import emit_result
from dashboard_transport_regression import server
from ws_client import ProtocolStateClient
from websockets.server import ServerProtocol
from websockets.protocol import OPEN
from observation_lane_regression import eventually

REQUEST = (b'GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n'
           b'Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
           b'Sec-WebSocket-Version: 13\r\n\r\n')


def masked(opcode, payload):
    mask = b'abcd'
    return bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + bytes(
        byte ^ mask[index % 4] for index, byte in enumerate(payload))


def receive(sock):
    try:
        return sock.recv(4096)
    except socket.timeout:
        return b''


def run():
    service = server.DashboardWebSocketServer('127.0.0.1', 0, SimpleNamespace(latest_payload_bytes=lambda:b'{}'))
    checks = {}
    service._broadcast_text(b'x'*(ProtocolStateClient.MAX_PAYLOAD+1))
    checks['oversized_broadcast_rejected_observably'] = service.snapshot()['oversized_payloads']==1
    connection, peer = socket.socketpair()
    connection.settimeout(.5); peer.settimeout(.5)
    client = None
    try:
        peer.sendall(REQUEST)
        protocol = service._handshake(connection)
        checks['valid_handshake'] = protocol is not None
        checks['upgrade_response'] = receive(peer).startswith(b'HTTP/1.1 101')
        client = ProtocolStateClient(connection, protocol)
        client.start()
        client.offer(b'{}')
        checks['state_delivery'] = receive(peer) == b'\x81\x02{}'
        peer.sendall(masked(9, b'probe'))
        checks['ping_gets_matching_pong'] = receive(peer) == b'\x8a\x05probe'
        peer.sendall(masked(8, b'\x03\xe8'))
        checks['close_gets_close_reply'] = receive(peer) == b'\x88\x02\x03\xe8'
    finally:
        if client is not None:
            client.close()
        connection.close(); peer.close()
    connection, peer = socket.socketpair()
    connection.settimeout(.5); peer.settimeout(.5)
    result = []
    entered = threading.Event()
    def handshake():
        entered.set()
        result.append(service._handshake(connection) is not None)
    thread = threading.Thread(target=handshake, daemon=True)
    try:
        thread.start(); entered.wait(1)
        peer.sendall(b'GET / HTTP/1.1\r\n')
        # If the partial request is incorrectly considered complete, this worker exits.
        thread.join(.05)
        peer.sendall(REQUEST[len(b'GET / HTTP/1.1\r\n'):])
        thread.join(1)
        checks['fragmented_handshake'] = result == [True]
    finally:
        connection.close(); peer.close(); thread.join(1)
    slow_conn, slow_peer = socket.socketpair()
    fast_conn, fast_peer = socket.socketpair()
    slow_conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    fast_peer.settimeout(1)
    slow = ProtocolStateClient(slow_conn, ServerProtocol(state=OPEN), timeout_s=.3)
    fast = ProtocolStateClient(fast_conn, ServerProtocol(state=OPEN), timeout_s=.3)
    try:
        slow.start(); fast.start()
        slow.offer(b'x'*1024*1024)
        checks['slow_send_in_flight'] = eventually(lambda:slow.snapshot()['queued']==0)
        for index in range(100):
            slow.offer(str(index).encode())
        fast.offer(b'latest')
        checks['fast_independent_of_slow'] = receive(fast_peer)==b'\x81\x06latest'
        checks['slow_pending_bounded'] = slow.snapshot()['queued']==1 and slow.snapshot()['coalesced']>=99
        checks['slow_send_timeout_reaped'] = eventually(lambda:slow.snapshot()['closed']) and 'deadline' in (slow.error or '')
        checks['incomplete_send_not_counted'] = slow.sent==0
        fast_peer.sendall(masked(8,b'\x03\xe8'))
        checks['fast_graceful_peer_close'] = receive(fast_peer)==b'\x88\x02\x03\xe8'
        checks['peer_close_worker_reaped'] = eventually(lambda:fast.snapshot()['closed'])
    finally:
        slow.close(); fast.close(); slow_peer.close(); fast_peer.close()
    return {'passed':all(checks.values()),'checks':checks,
            'scope':'connected socketpair; no TCP listener, browser or real gameplay'}


if __name__=='__main__':
    emit_result(run())
