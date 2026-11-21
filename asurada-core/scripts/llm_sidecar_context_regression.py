"""Sidecar context wiring and server watcher behavior without a listener."""
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from asurada.llm_explainer import LlmExplainerRequest, LlmExplainerResult, VoiceSidecarLlmExplainerBackend
from asurada.voice_sidecar_protocol import build_explainer_result_envelope
from asurada.voice_sidecar_server import VoiceSidecarServer, VoiceSidecarServerConfig
from asurada.task_runtime import TaskContext, TaskCancelled
from regression_support import emit_result


def run():
    request=LlmExplainerRequest('s','t','r','overall_situation','query','test',5000,{})
    answer={'status':'unsupported'}
    result=LlmExplainerResult('completed','fake',True,answer,None,0)
    context=TaskContext.start('client',1000)
    with patch('asurada.cancellable_http.request_json',return_value=build_explainer_result_envelope(result).to_dict()) as transport:
        returned=VoiceSidecarLlmExplainerBackend(base_url='http://example.invalid').explain_with_context(request,context=context)
    checks={'client_context_reaches_transport':returned==answer and transport.call_args.kwargs['context'] is context}
    server=object.__new__(VoiceSidecarServer)
    server.config=VoiceSidecarServerConfig(llm_timeout_ms=500)
    server._shutdown_requested=threading.Event()
    seen=[]
    def quick(**kwargs):
        seen.append(kwargs['context'].remaining())
        return result
    server.llm_explainer=SimpleNamespace(run=quick)
    with patch('asurada.voice_sidecar_server.watch_stream'):
        server._explain_request(request,object(),'100')
        server._explain_request(request,object(),'5000')
    checks['transmitted_and_server_budgets_bound']=0<seen[0]<=.1 and .1<seen[1]<=.5
    for budget in ('0','-1','bad'):
        try:server._explain_request(request,object(),budget);checks['invalid_'+budget]=False
        except ValueError:checks['invalid_'+budget]=True
    class Connection:
        def __init__(self):self.stopped=False
        def recv(self,*args):return b''
        def shutdown(self,*args):self.stopped=True
    def waiting(**kwargs):
        task=kwargs['context']
        while True:task.remaining();time.sleep(.005)
    server.llm_explainer=SimpleNamespace(run=waiting)
    for reason in ('peer_eof','shutdown'):
        connection=Connection()
        server._shutdown_requested.clear()
        if reason=='shutdown':server._shutdown_requested.set()
        with patch('asurada.sidecar_execution.select.select',return_value=([connection],[],[])):
            try:server._explain_request(request,connection,'1000');checks[reason]=False
            except TaskCancelled:checks[reason]=connection.stopped
    return {'passed':all(checks.values()),'checks':checks,'scope':'mock transport and connection; no listener or live service acceptance'}


if __name__=='__main__':emit_result(run())
