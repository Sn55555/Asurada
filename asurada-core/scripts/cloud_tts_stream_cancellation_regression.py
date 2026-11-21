import base64
import http.client
import json
import socket
import threading
from unittest.mock import patch
from asurada.task_runtime import TaskContext, TaskCancelled
from asurada.voice_sidecar_tts import DoubaoStreamingHttpSidecarTtsRenderer
from asurada.voice_sidecar_protocol import TtsRenderRequest
from regression_support import emit_result


def scenario(mode):
    sockets = []; workers = []; closed = threading.Event(); ready = threading.Event()
    def connect(connection):
        client, peer = socket.socketpair(); sockets.extend((client, peer)); connection.sock = client
        def serve():
            try:
                peer.settimeout(2); raw = b''
                while b'\r\n\r\n' not in raw: raw += peer.recv(4096)
                head, body = raw.split(b'\r\n\r\n', 1)
                length = int(next(line.split(b':', 1)[1] for line in head.split(b'\r\n') if line.lower().startswith(b'content-length:')))
                while len(body) < length: body += peer.recv(length-len(body))
                event = b'data: ' + json.dumps({'event': 352, 'code': 0, 'data': base64.b64encode(b'\x01\x00'*20).decode()}).encode() + b'\n\n'
                ending = b'data: {"event":152,"code":20000000}\n\n'
                payload = event if mode == 'truncated' else event + ending
                peer.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(payload) if mode in {'complete', 'truncated'} else 100000).encode() + b'\r\n\r\n')
                if mode != 'blocked': peer.sendall(payload if mode in {'complete', 'truncated'} else event)
                ready.set()
                if peer.recv(1) == b'': closed.set()
            finally: peer.close()
        worker = threading.Thread(target=serve); workers.append(worker); worker.start()
    renderer = DoubaoStreamingHttpSidecarTtsRenderer('http://fixture.invalid/tts','fixture','fixture','fixture','fixture')
    request = TtsRenderRequest(text='test', persona_id='asurada_default', voice_profile_id='asurada_cn_ai_v1', audio_format='pcm_s16le')
    context = TaskContext.start('cloud-tts', 2000); chunks = []; errors = []
    with patch.object(http.client.HTTPConnection, 'connect', connect), patch('asurada.cancellable_http.getproxies', return_value={}):
        iterator = iter(renderer.stream_render(request, frame_size_bytes=16, context=context).iter_chunks())
        try:
            if mode in {'complete', 'truncated'}:
                try: chunks.extend(iterator)
                except Exception as exc: errors.append(exc)
            elif mode == 'early_close': chunks.append(next(iterator)); iterator.close()
            else:
                def read():
                    try: next(iterator)
                    except Exception as exc: errors.append(exc)
                consumer = threading.Thread(target=read); consumer.start(); assert ready.wait(1)
                context.cancel(); consumer.join(1)
                assert not consumer.is_alive()
        finally:
            iterator.close()
            for worker in workers: worker.join(2)
            for stream in sockets: stream.close()
    return chunks, errors, closed.is_set()


def run():
    chunks, errors, closed = scenario('complete')
    checks = {'sse_audio_decoded': b''.join(chunks) == b'\x01\x00'*20 and not errors and closed}
    chunks, errors, closed = scenario('truncated')
    checks['complete_http_body_without_terminal_is_rejected'] = bool(chunks) and len(errors) == 1 and str(errors[0]) == 'doubao_tts_stream_incomplete' and closed
    chunks, errors, closed = scenario('early_close')
    checks['early_close_releases_connection'] = bool(chunks) and not errors and closed
    chunks, errors, closed = scenario('blocked')
    checks['blocked_read_cancelled_and_closed'] = not chunks and isinstance(errors[0], TaskCancelled) and closed
    return {'passed': all(checks.values()), 'checks': checks, 'scope': 'real HTTP/SSE wire over socketpair; no listener, DNS, TLS or live provider'}


if __name__ == '__main__': emit_result(run())
