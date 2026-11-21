import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
from asurada.task_runtime import TaskContext, TaskCancelled
from asurada.voice_sidecar_tts import MacOSSaySidecarTtsRenderer
from asurada.voice_sidecar_protocol import TtsRenderRequest
from tts_audio_validity_regression import wav
from regression_support import emit_result


def run():
    timings = {}; checks = {}; request = TtsRenderRequest(text='test', persona_id='asurada_default', voice_profile_id='asurada_cn_ai_v1', audio_format='pcm_s16le')
    context = TaskContext.start('tts', 1000); budgets = []
    def execute(command, *, timeout_s, context):
        budgets.append((timeout_s, context))
        if command[0] == 'converter': Path(command[-1]).write_bytes(wav(20))
        else: time.sleep(.02)
    renderer = MacOSSaySidecarTtsRenderer(say_binary='say-fixture', afconvert_binary='converter')
    with patch('asurada.voice_sidecar_tts.command_json_text', side_effect=execute):
        response = renderer.render(request, context=context)
    checks['stages_share_remaining_budget'] = response.status == 'completed' and budgets[0][1] is context and budgets[1][1] is context and budgets[1][0] < budgets[0][0]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); pidfile = root / 'pid'; say = root / 'say'; convert = root / 'convert'
        say.write_text('#!' + sys.executable + '\nimport sys\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index("-o")+1]).write_bytes(b"fixture")\n')
        convert.write_text('#!' + sys.executable + '\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(pidfile)) + ').write_text(str(os.getpid()))\ntime.sleep(20)\n')
        say.chmod(0o755); convert.chmod(0o755)
        renderer = MacOSSaySidecarTtsRenderer(say_binary=str(say), afconvert_binary=str(convert))
        # Startup readiness is separate from the bounded post-cancel assertion.
        context = TaskContext.start('cancel-tts', 10000); errors = []
        def work():
            try: renderer.stream_render(request, frame_size_bytes=2048, context=context)
            except Exception as exc: errors.append(exc)
        started = time.monotonic()
        thread = threading.Thread(target=work); thread.start()
        until = started + 8
        try:
            while not pidfile.exists() and thread.is_alive() and time.monotonic() < until: time.sleep(.01)
            if not pidfile.exists():
                raise AssertionError({'phase': 'converter_startup', 'worker_alive': thread.is_alive(),
                                      'errors': [repr(error) for error in errors]})
            pid = int(pidfile.read_text())
            timings['fixture_startup_ms'] = round((time.monotonic() - started) * 1000, 3)
            cancelled = time.monotonic(); context.cancel(); thread.join(2)
            timings['cancellation_ms'] = round((time.monotonic() - cancelled) * 1000, 3)
            checks['cancelled_conversion_returns'] = not thread.is_alive() and bool(errors) and isinstance(errors[0], TaskCancelled)
            try: os.kill(pid, 0); checks['conversion_process_reaped'] = False
            except ProcessLookupError: checks['conversion_process_reaped'] = True
        finally:
            context.cancel()
            thread.join(2)
    return {'passed': all(checks.values()), 'checks': checks, 'timings': timings, 'scope': 'actual fixture subprocess cancellation, no native audio or listener'}


if __name__ == '__main__': emit_result(run())
