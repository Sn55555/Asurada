"""Actual command cancellation, blocked stdin, output bounds and recovery."""
import subprocess
import sys
import threading
import time
from dataclasses import replace
from unittest.mock import patch
from asurada.llm_explainer import CommandLlmExplainerBackend, LlmExplainer, LlmExplainerRequest
from asurada.task_runtime import BoundedTaskExecutor, TaskContext
from regression_support import emit_result


def run():
    request=LlmExplainerRequest('session','turn','request','overall_situation','query','test',5000,{})
    processes=[]
    original=subprocess.Popen
    def spawn(*args,**kwargs):
        child=original(*args,**kwargs)
        processes.append(child)
        return child
    checks={}
    executor=BoundedTaskExecutor(1)
    for label,code,req in (
        ('waiting_output',"import sys,time;sys.stdin.read();time.sleep(30)",request),
        ('blocked_stdin',"import time;time.sleep(30)",replace(request,normalized_query_text='x'*1000000)),
    ):
        backend=CommandLlmExplainerBackend(command=(sys.executable,'-c',code))
        context=TaskContext.start(label,5000)
        timer=threading.Timer(.15,context.cancel)
        started=time.monotonic()
        with patch('asurada.capture_process.subprocess.Popen',side_effect=spawn):
            timer.start()
            result=LlmExplainer(backend=backend,executor=executor).run(request=req,context=context)
            timer.join()
        checks[label+'_cancelled']=result.fallback_reason=='llm_cancelled' and time.monotonic()-started<1
        deadline=time.monotonic()+2
        while processes[-1].poll() is None and time.monotonic()<deadline:
            time.sleep(.01)
        checks[label+'_reaped']=processes[-1].poll() is not None
        # Wait for the worker's cleanup, then verify its only slot is reusable.
        recovered=False
        while time.monotonic()<deadline:
            try:
                probe=TaskContext.start('probe',1000)
                recovered=probe.wait(executor.submit(probe,lambda:True))
                break
            except Exception:
                time.sleep(.01)
        checks[label+'_capacity_recovered']=recovered
    backend=CommandLlmExplainerBackend(command=(sys.executable,'-c',"import sys;sys.stdin.read();print('x'*5000000)"))
    try:
        backend.explain(request)
        checks['oversized_output_rejected']=False
    except ValueError as exc:
        checks['oversized_output_rejected']='too_large' in str(exc)
    backend=CommandLlmExplainerBackend(command=(sys.executable,'-c',"import sys,json;r=json.load(sys.stdin);print(json.dumps({'query':r['normalized_query_text']}))"))
    checks['unicode_input_roundtrip']=backend.explain(replace(request,normalized_query_text='最近三圈'))=={'query':'最近三圈'}
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':
    emit_result(run())
