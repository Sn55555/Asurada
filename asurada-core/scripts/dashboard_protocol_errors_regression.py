"""Invalid wire frames must close cleanly; fragmented UTF-8 remains supported."""
import socket
from regression_support import emit_result
from dashboard_protocol_regression import masked, receive
from observation_lane_regression import eventually
from ws_client import ProtocolStateClient
from websockets.server import ServerProtocol
from websockets.protocol import OPEN


def run():
    checks = {}
    cases = [
        ('unmasked', b'\x89\x01x', 1002),
        ('fragmented_ping', bytes([9])+masked(9,b'x')[1:], 1002),
        ('reserved_bit', bytes([0xc9])+masked(9,b'x')[1:], 1002),
        ('unknown_opcode', masked(3,b'x'), 1002),
        ('short_close', masked(8,b'x'), 1002),
        ('invalid_close_utf8', masked(8,b'\x03\xe8\xff'), 1007),
        ('invalid_text_utf8', masked(1,b'\xff'), 1007),
    ]
    for name, wire, code in cases:
        conn, peer = socket.socketpair()
        peer.settimeout(.6)
        client = ProtocolStateClient(conn,ServerProtocol(state=OPEN,max_size=4096),timeout_s=.2)
        try:
            client.start(); peer.sendall(wire)
            reply=receive(peer)
            checks[name+'_code']=len(reply)>=4 and reply[0]==0x88 and int.from_bytes(reply[2:4],'big')==code
            checks[name+'_reaped']=eventually(lambda:client.snapshot()['closed'])
        finally:
            client.close();peer.close()
    conn, peer = socket.socketpair()
    peer.settimeout(.6)
    client = ProtocolStateClient(conn,ServerProtocol(state=OPEN,max_size=4096),timeout_s=.2)
    try:
        client.start()
        encoded='隼'.encode()
        peer.sendall(bytes([1])+masked(1,encoded[:1])[1:])
        peer.sendall(masked(9,b'p'))
        checks['ping_during_text_fragment']=receive(peer)==b'\x8a\x01p'
        peer.sendall(masked(0,encoded[1:]))
        peer.sendall(masked(9,b'q'))
        checks['valid_split_utf8']=receive(peer)==b'\x8a\x01q'
        peer.sendall(masked(8,b'\x03\xe8'));receive(peer)
    finally:
        client.close();peer.close()
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':
    emit_result(run())
