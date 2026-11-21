import os
import time
from phase3_macos_voice_loop import _ControlChannel, _bind_current_voice_session
from regression_support import emit_result


def run():
    checks = {}
    read_fd, write_fd = os.pipe()
    channel = _ControlChannel(input_fd=read_fd, manual=True)
    try:
        channel.start(); start = time.monotonic(); channel.close()
        checks['idle_reader_closes_without_stdin_input'] = not channel._thread.is_alive() and time.monotonic() - start < .5
    finally:
        os.close(read_fd); os.close(write_fd)
    read_fd, write_fd = os.pipe()
    stops=[]; channel=_ControlChannel(input_fd=read_fd,manual=True,on_stop=lambda:stops.append(True))
    try:
        channel.start(); os.write(write_fd,b'\ns\nq\n'); channel._thread.join(1)
        checks['stop_and_quit_remain_responsive'] = len(stops)==2 and channel.wait_command()=='q' and not channel._thread.is_alive()
    finally:
        channel.close(); os.close(read_fd); os.close(write_fd)
    class Service:
        current=False
        def bind_session(self,state):
            if not self.current:raise RuntimeError('ValueError: latest_snapshot_not_current')
    service=Service()
    checks['stale_does_not_crash_or_bind'] = not _bind_current_voice_session(service,None)
    service.current=True
    checks['same_service_can_recover'] = _bind_current_voice_session(service,None)
    class Broken:
        def bind_session(self,state):raise RuntimeError('different_service_error')
    try:
        _bind_current_voice_session(Broken(),None); checks['other_failure_not_hidden']=False
    except RuntimeError:checks['other_failure_not_hidden']=True
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())
