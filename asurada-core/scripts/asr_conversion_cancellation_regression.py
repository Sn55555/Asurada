from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from regression_support import emit_result
from asurada.task_runtime import TaskContext, TaskCancelled
from asurada.voice_sidecar_asr import VoiceSidecarAsrRecognizer


def run():
    checks={}
    with TemporaryDirectory() as directory:
        root=Path(directory);source=root/'capture.caf';source.write_bytes(b'fake')
        marker=root/'entered';converter=root/'afconvert'
        converter.write_text('#!'+sys.executable+'\nimport pathlib,sys,time\npathlib.Path(sys.argv[-1]).write_bytes(b"partial")\npathlib.Path('+repr(str(marker))+').write_text("started")\ntime.sleep(20)\n')
        converter.chmod(0o700)
        class Capture:
            def capture_once(self,context=None):
                return SimpleNamespace(status='recorded',audio_file_path=str(source),started_at_ms=1,ended_at_ms=2,to_dict=lambda:{})
        calls=[]
        class Client:
            def transcribe_asr(self,**kwargs):calls.append(kwargs);raise AssertionError('cancelled audio must not be uploaded')
        recognizer=VoiceSidecarAsrRecognizer(audio_capture=Capture(),client=Client())
        context=TaskContext.start('conversion',3000);errors=[]
        def work():
            try:recognizer.listen_once(context=context)
            except Exception as exc:errors.append(exc)
        with patch('asurada.voice_sidecar_asr.shutil.which',return_value=str(converter)),patch('asurada.voice_sidecar_asr.tempfile.gettempdir',return_value=str(root)):
            worker=threading.Thread(target=work);worker.start()
            try:
                deadline=time.monotonic()+1
                while not marker.exists() and time.monotonic()<deadline:time.sleep(.005)
                assert marker.exists()
                context.cancel();worker.join(.5)
                checks['recognizer_cancels_actual_conversion_process']=not worker.is_alive() and isinstance(errors[0],TaskCancelled)
                checks['source_and_partial_conversion_removed']=not source.exists() and not list(root.glob('*_sidecar_asr.wav'))
                checks['cancelled_conversion_never_uploaded']=not calls
            finally:context.cancel();worker.join(1)
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())
