import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
from asurada.capture_process import command_lines
from asurada.macos_audio_capture import MacOSAudioCapture, MacOSAudioCaptureConfig
from asurada.macos_audio_stream import MacOSAudioStreamCapture, MacOSAudioStreamConfig
from asurada.task_runtime import TaskContext, TaskCancelled, TaskCapacityExceeded
from asurada.recognition_runtime import listen_with_context
from regression_support import emit_result


def run():
    checks={}
    with TemporaryDirectory() as temp:
        pidfile=Path(temp)/'pid'
        command=[sys.executable,'-c',"import os,time,pathlib; pathlib.Path(__import__('sys').argv[1]).write_text(str(os.getpid())); time.sleep(20)",str(pidfile)]
        capture=MacOSAudioCapture(MacOSAudioCaptureConfig(sys.executable,'unused'))
        capture._command=lambda:command
        context=TaskContext.start('capture-cancel',5000)
        errors=[]
        def work():
            try:capture.capture_once(context=context)
            except BaseException as exc:errors.append(exc)
        worker=threading.Thread(target=work);worker.start()
        deadline=time.monotonic()+2
        while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.005)
        assert pidfile.exists()
        pid=int(pidfile.read_text());started=time.monotonic();context.cancel();worker.join(1)
        checks['batch_capture_cancel_returns']=not worker.is_alive() and isinstance(errors[0],TaskCancelled) and time.monotonic()-started<.5
        try:os.kill(pid,0);gone=False
        except ProcessLookupError:gone=True
        checks['actual_capture_process_reaped']=gone
        stream=MacOSAudioStreamCapture(MacOSAudioStreamConfig(sys.executable,'unused',command_timeout_s=.05))
        stream._command=lambda:[sys.executable,'-c','import time;time.sleep(20)']
        started=time.monotonic()
        try:list(stream.iter_events());timed_out=False
        except TimeoutError:timed_out=True
        checks['silent_stream_honors_deadline']=timed_out and time.monotonic()-started<.5
        lines=command_lines([sys.executable,'-c',"import sys;sys.stderr.write('x'*200000);print('ok')"],timeout_s=2)
        checks['stderr_drained_without_deadlock']=list(lines)==['ok']
        lines=command_lines([sys.executable,'-c',"import time;print('first',flush=True);time.sleep(20)"],timeout_s=20)
        checks['stream_delivers_before_process_exit']=next(lines)=='first'
        started=time.monotonic();lines.close()
        checks['generator_close_cleans_process']=time.monotonic()-started<.5
    entered=threading.Event();release=threading.Event();results=[]
    class Blocking:
        def listen_once(self):entered.set();release.wait(3);return 'late'
    context=TaskContext.start('noncooperative',2000)
    def caller():
        try:results.append(listen_with_context(Blocking(),context))
        except TaskCancelled:results.append('cancelled')
    worker=threading.Thread(target=caller);worker.start();assert entered.wait(1)
    context.cancel();worker.join(.2)
    checks['recognition_wait_cancelled_without_waiting_for_backend']=not worker.is_alive() and results==['cancelled']
    class Next:
        supports_task_context=True
        def listen_once(self,context=None):context.remaining();return 'fresh'
    try:listen_with_context(Next(),TaskContext.start('busy',100));busy=False
    except TaskCapacityExceeded:busy=True
    checks['cancelled_backend_keeps_only_worker_slot']=busy
    release.set()
    deadline=time.monotonic()+1;fresh=None
    while time.monotonic()<deadline:
        try:fresh=listen_with_context(Next(),TaskContext.start('new',100));break
        except TaskCapacityExceeded:time.sleep(.002)
    checks['context_passed_and_slot_recovered']=fresh=='fresh'
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())
