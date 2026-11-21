"""Real loopback stream server, fake provider; no cloud or audio device."""
import json
import socket
import threading
import time
from types import SimpleNamespace

from regression_support import emit_result
from asurada.voice_sidecar_server import VoiceSidecarServer, VoiceSidecarServerConfig
from asurada.voice_sidecar_protocol import AsrRealtimeStartRequest, build_asr_realtime_start_request_envelope


def run():
    checks = {}
    start = (json.dumps(build_asr_realtime_start_request_envelope(
        AsrRealtimeStartRequest(locale='zh-CN', audio_format='pcm')).to_dict()) + '\n').encode()
    for phase in ('duplicate', 'disconnect', 'deadline', 'oversize', 'overload', 'shutdown'):
        entered, release = threading.Event(), threading.Event()
        contexts, sessions = [], []

        class Session:
            request_id = 'test-stream'
            closed = False
            def close(self): self.closed = True

        class Backend:
            supports_task_context = True
            def open_realtime_session(self, *, context, **kwargs):
                contexts.append(context)
                entered.set()
                if phase == 'overload':
                    release.wait(3)  # Deliberately ignores cancellation.
                elif phase in ('disconnect', 'shutdown'):
                    while not context.cancellation.wait(.01):
                        context.remaining()
                    context.remaining()
                session = Session()
                sessions.append(session)
                return session

        outer = object.__new__(VoiceSidecarServer)
        outer.config = VoiceSidecarServerConfig(asr_stream_port=0,
            asr_stream_timeout_ms=120 if phase == 'deadline' else 1000)
        outer.asr_backend = Backend()
        outer._shutdown_requested = threading.Event()
        server = outer._build_asr_stream_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        clients = []

        def connect():
            client = socket.create_connection(server.server_address, timeout=1)
            clients.append(client)
            return client

        try:
            client = connect()
            if phase == 'oversize':
                client.sendall(b'x' * (4 * 1024 * 1024 + 1))
                checks['oversize_rejected_before_provider'] = b'asr_stream_size_limit' in client.recv(4096) and not contexts
            else:
                client.sendall(start)
                assert entered.wait(1)
                if phase == 'duplicate':
                    assert b'started' in client.recv(4096)
                    client.sendall(start)
                    checks['duplicate_rejected'] = b'realtime_asr_already_started' in client.recv(4096)
                elif phase == 'disconnect':
                    client.close()
                    checks['disconnect_cancels_open'] = contexts[0].cancellation.wait(.6)
                elif phase == 'shutdown':
                    outer._shutdown_requested.set()
                    checks['service_stop_cancels_open'] = contexts[0].cancellation.wait(.6)
                elif phase == 'deadline':
                    assert b'started' in client.recv(4096)
                    checks['total_deadline_closes_idle_stream'] = client.recv(4096) == b'' and contexts[0].cancellation.is_set()
                elif phase == 'overload':
                    for _ in range(7): connect().sendall(start)
                    until = time.monotonic() + 1
                    while len(contexts) < 8 and time.monotonic() < until: time.sleep(.005)
                    assert len(contexts) == 8
                    for item in clients: item.close()
                    assert all(ctx.cancellation.wait(.6) for ctx in contexts)
                    ninth = connect()
                    checks['cancelled_uncooperative_calls_retain_capacity'] = ninth.recv(1) == b'' and len(contexts) == 8
            release.set()
            for item in clients: item.close()
            until = time.monotonic() + 1
            while time.monotonic() < until:
                if all(s.closed for s in sessions) and not any(t.name == 'sidecar-stream-cancel' for t in threading.enumerate()): break
                time.sleep(.005)
            checks[phase + '_session_and_monitor_cleanup'] = all(s.closed for s in sessions) and not any(t.name == 'sidecar-stream-cancel' for t in threading.enumerate())
        finally:
            release.set()
            outer._shutdown_requested.set()
            for item in clients: item.close()
            server.shutdown()
            server.server_close()
            thread.join(1)
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__': emit_result(run())
