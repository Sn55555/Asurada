"""Actual batch adapter with controlled sockets; no cloud or microphone."""
import sys
import io
import wave
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from regression_support import emit_result
from asurada.task_runtime import TaskContext, TaskCancelled
from asurada.voice_sidecar_asr import DoubaoBigmodelStreamingWsSidecarAsrBackend, _iter_streaming_audio_chunks
from phase3_doubao_streaming_asr_backend_regression import _build_ws_success_frame


class Closed(Exception): pass
class Timeout(Exception): pass


def run():
    checks = {}
    for phase in ('send', 'receive', 'deadline', 'late_connect', 'pacing', 'positive', 'provider_error'):
        entered, aborted, release = threading.Event(), threading.Event(), threading.Event()
        errors, results, budgets = [], [], []
        context = TaskContext.start(phase, 120 if phase == 'deadline' else 2000)

        class WS:
            headers = {'X-Tt-Logid': 'batch-test-log'}
            closed = False
            sent = 0
            reads = 0

            def settimeout(self, value): pass

            def send_binary(self, payload):
                self.sent += 1
                if phase == 'send':
                    entered.set()
                    aborted.wait(3)
                    raise Closed()

            def recv(self):
                self.reads += 1
                entered.set()
                if phase in ('positive', 'provider_error'):
                    return _build_ws_success_frame(-1, {'code': 9999 if phase == 'provider_error' else 1000,
                        'result': {'text': '后车差距', 'utterances': [{'confidence': .9}]}})
                if phase == 'pacing':
                    raise Timeout()
                aborted.wait(3)
                raise Closed()

            def abort(self): aborted.set()
            def shutdown(self): self.closed = True

        ws = WS()

        def connect(*args, **kwargs):
            budgets.append(kwargs['timeout'])
            if phase == 'late_connect':
                entered.set()
                release.wait(3)
            return ws

        module = SimpleNamespace(create_connection=connect, WebSocketTimeoutException=Timeout,
                                 WebSocketConnectionClosedException=Closed)
        backend = DoubaoBigmodelStreamingWsSidecarAsrBackend(url='wss://unused.invalid',
            resource_id='test-resource', app_key=None, access_key=None, api_key='test-key', user_id='test-user',
            audio_chunk_ms=1000, connect_timeout_s=5, recv_timeout_s=2)

        def work():
            try:
                results.append(backend.transcribe_audio(audio_bytes=b'\0' * 64000,
                    audio_format='pcm', locale='zh-CN', metadata={'test': phase}, context=context))
            except Exception as exc:
                errors.append(exc)

        with patch.dict(sys.modules, websocket=module):
            worker = threading.Thread(target=work)
            worker.start()
            try:
                assert entered.wait(1)
                if phase not in ('positive', 'provider_error', 'deadline'):
                    context.cancel()
                release.set()
                worker.join(1)
                checks[phase + '_clean_exit'] = (not worker.is_alive() and ws.closed and
                    not any(t.name == 'doubao-batch-asr-cancel' for t in threading.enumerate()))
                checks[phase + '_connect_budget'] = 0 < budgets[0] <= 2
                if phase == 'positive':
                    checks['normal_result_and_metadata'] = (not errors and len(results) == 1 and
                        results[0].transcript_text == '后车差距' and
                        results[0].metadata['provider_request_id'] == 'batch-test-log' and
                        results[0].metadata['request_metadata'] == {'test': phase})
                elif phase == 'provider_error':
                    checks['provider_error_preserved'] = not results and len(errors) == 1 and '9999' in str(errors[0])
                else:
                    checks[phase + '_no_result'] = (not results and len(errors) == 1 and
                        isinstance(errors[0], TimeoutError if phase == 'deadline' else TaskCancelled))
                if phase == 'late_connect': checks['late_connect_no_send'] = ws.sent == 0
                if phase == 'pacing': checks['pacing_no_next_chunk'] = ws.sent == 2
            finally:
                context.cancel()
                aborted.set()
                release.set()
                worker.join(1)
    checks['dispatcher_opt_in'] = backend.supports_task_context is True
    pcm = bytes(range(256)) * 250
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)
    for fmt, data in (('wav', buffer.getvalue()), ('pcm', pcm)):
        chunks = _iter_streaming_audio_chunks(data, audio_format=fmt, chunk_ms=200)
        checks[fmt + '_chunks_and_exact_samples'] = len(chunks) == 10 and all(len(c) == 6400 for c in chunks) and b''.join(chunks) == pcm
    bad = io.BytesIO()
    with wave.open(bad, 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(pcm)
    try:
        _iter_streaming_audio_chunks(bad.getvalue(), audio_format='wav', chunk_ms=200)
        checks['wrong_format_rejected'] = False
    except ValueError:
        checks['wrong_format_rejected'] = True
    # Exercise the real dispatcher without starting a network listener.
    from asurada.voice_sidecar_server import VoiceSidecarServer
    server = object.__new__(VoiceSidecarServer)
    server.asr_backend = backend
    forwarded = []
    request = SimpleNamespace(audio_base64='', audio_format='pcm', locale='zh-CN', prompt=None, metadata={})
    def transcribe(self, **kwargs):
        forwarded.append(kwargs.get('context'))
        return 'dispatched'
    with patch.object(DoubaoBigmodelStreamingWsSidecarAsrBackend, 'transcribe_audio', transcribe):
        response = server._transcribe_asr(request, context=context)
    checks['real_dispatcher_forwards_context'] = response == 'dispatched' and forwarded == [context]
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__': emit_result(run())
