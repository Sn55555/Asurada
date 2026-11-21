import socket
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from asurada.task_runtime import TaskContext, TaskCancelled, TaskCapacityExceeded, BoundedTaskExecutor
from asurada.voice_sidecar_server import VoiceSidecarServer, VoiceSidecarServerConfig
from regression_support import emit_result


def run():
    server = object.__new__(VoiceSidecarServer)
    server.config = VoiceSidecarServerConfig(tts_timeout_ms=500)
    server._shutdown_requested = threading.Event()
    checks = {}; observed = []
    def render(request, *, context):
        observed.append(context)
        return 'audio'
    server.tts_renderer = SimpleNamespace(supports_task_context=True, render=render,
        stream_render=lambda request, frame_size_bytes, context: render(request, context=context))
    for streamed in (False, True):
        left, right = socket.socketpair(); delivered = []
        try:
            response = server._tts_request(None, left, '100', streamed=streamed, deliver=delivered.append)
            checks['stream' if streamed else 'buffered'] = response == 'audio' and delivered == ['audio'] and observed[-1].cancellation.is_set()
        finally: left.close(); right.close()
    left, right = socket.socketpair(); started = threading.Event(); stopped = threading.Event(); errors = []
    def blocked(request, *, context):
        started.set()
        try:
            while True: context.remaining(); time.sleep(.005)
        finally: stopped.set()
    server.tts_renderer.render = blocked
    def work():
        try: server._tts_request(None, left)
        except Exception as exc: errors.append(exc)
    thread = threading.Thread(target=work); thread.start(); assert started.wait(1)
    right.close(); thread.join(1)
    checks['peer_disconnect_cancels_renderer'] = not thread.is_alive() and isinstance(errors[0], TaskCancelled) and stopped.wait(1)
    left.close()
    slots = BoundedTaskExecutor(1); release = threading.Event()
    future = slots.submit(TaskContext.start('occupied', 2000), lambda: release.wait(1))
    left, right = socket.socketpair()
    try:
        with patch('asurada.voice_sidecar_server.TTS_EXECUTOR', slots):
            try: server._tts_request(None, left); checks['capacity_bounded'] = False
            except TaskCapacityExceeded: checks['capacity_bounded'] = True
        try: server._tts_request(None, left, '0'); checks['invalid_budget_rejected'] = False
        except ValueError: checks['invalid_budget_rejected'] = True
    finally:
        release.set(); future.result(timeout=1); left.close(); right.close()
    return {'passed': all(checks.values()), 'checks': checks, 'scope': 'request helper and actual socketpair EOF; no HTTP listener or audio device'}


if __name__ == '__main__': emit_result(run())
