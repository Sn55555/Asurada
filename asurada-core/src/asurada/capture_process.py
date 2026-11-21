"""Cancellable, bounded-output local capture subprocesses (POSIX)."""
import os
import selectors
import signal
import subprocess
import time
from .task_runtime import TaskContext


def command_lines(command, *, timeout_s, context=None, input_bytes=None):
    parent = context or TaskContext.start('audio-capture', timeout_s*1000)
    task = TaskContext(parent.task_id, min(parent.deadline,time.monotonic()+timeout_s), parent.cancellation)
    task.remaining()
    if input_bytes is not None and (not isinstance(input_bytes, bytes) or len(input_bytes)>4*1024*1024):
        raise ValueError('command_input_invalid_or_too_large')
    process = subprocess.Popen(command, stdin=subprocess.PIPE if input_bytes is not None else None,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    selector = selectors.DefaultSelector()
    pending = bytearray()
    errors = bytearray()
    try:
        for stream in (process.stdout,process.stderr):
            os.set_blocking(stream.fileno(),False)
            selector.register(stream,selectors.EVENT_READ)
        remaining_input = memoryview(input_bytes or b'')
        if process.stdin is not None:
            os.set_blocking(process.stdin.fileno(),False)
            if remaining_input:
                selector.register(process.stdin,selectors.EVENT_WRITE)
            else:
                process.stdin.close()
        while selector.get_map():
            for key,_ in selector.select(timeout=min(.02,task.remaining())):
                if key.fileobj is process.stdin:
                    try:
                        written=os.write(process.stdin.fileno(),remaining_input[:65536])
                        remaining_input=remaining_input[written:]
                    except BrokenPipeError:
                        remaining_input=memoryview(b'')
                    if not remaining_input:
                        selector.unregister(process.stdin)
                        process.stdin.close()
                    continue
                data=os.read(key.fileobj.fileno(),65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                if key.fileobj is process.stderr:
                    errors.extend(data)
                    del errors[:-65536]
                    continue
                pending.extend(data)
                while b'\n' in pending:
                    line,_,rest=pending.partition(b'\n')
                    pending=bytearray(rest)
                    if len(line)>4*1024*1024:raise ValueError('capture_line_too_large')
                    task.remaining()
                    yield line.decode('utf-8')
                if len(pending)>4*1024*1024:raise ValueError('capture_line_too_large')
        process.wait(timeout=task.remaining())
        task.remaining()
        if process.returncode:
            raise RuntimeError(f'capture_process_failed:{process.returncode}: {errors.decode("utf-8",errors="replace")}')
        if pending:
            yield pending.decode('utf-8')
    finally:
        selector.close()
        # The command owns its own process group; descendants may hold pipe ends.
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(timeout=.2)
        except subprocess.TimeoutExpired:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait(timeout=1)
        finally:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.stdout.close()
            process.stderr.close()
            if process.stdin is not None:
                process.stdin.close()


def command_json_text(command, *, timeout_s, context, input_bytes=None):
    lines=[]
    size=0
    iterator=command_lines(command,timeout_s=timeout_s,context=context,input_bytes=input_bytes)
    try:
        for line in iterator:
            size+=len(line.encode('utf-8'))+1
            if size>4*1024*1024:raise ValueError('capture_output_too_large')
            lines.append(line)
        return '\n'.join(lines)
    finally:
        iterator.close()
