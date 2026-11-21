"""Provider request wiring and shared cancellation; HTTP transport is mocked."""
import json
import threading
import time
from unittest.mock import patch
from asurada.llm_explainer import (LlmExplainer, LlmExplainerRequest,
    OpenAiResponsesLlmExplainerBackend, DoubaoArkResponsesLlmExplainerBackend,
    DoubaoArkChatCompletionsLlmExplainerBackend, DoubaoArkLlmExplainerBackend)
from asurada.task_runtime import TaskContext, TaskCancelled
from regression_support import emit_result


def run():
    request=LlmExplainerRequest('session','turn','request','overall_situation','query','test',5000,{})
    answer={'status':'unsupported','answer_text':'','confidence':0.,'reason_fields':[], 'requires_confirmation':False}
    calls=[]
    def transport(url,**kwargs):
        calls.append((url,kwargs))
        text=json.dumps(answer)
        return {'choices':[{'message':{'content':text}}]} if url.endswith('/chat/completions') else {'output':[{'content':[{'type':'output_text','text':text}]}]}
    checks={}
    for cls in (OpenAiResponsesLlmExplainerBackend,DoubaoArkResponsesLlmExplainerBackend,DoubaoArkChatCompletionsLlmExplainerBackend):
        backend=cls(api_key='test',model='test',base_url='https://example.invalid/v1')
        context=TaskContext.start('parent',1000)
        with patch('asurada.llm_explainer.request_json',side_effect=transport):
            result=backend.explain_with_context(request,context=context)
        kwargs=calls[-1][1]
        checks[cls.__name__]=result==answer and kwargs['context'] is context and kwargs['propagate_budget'] is False and kwargs['headers']['Authorization']=='Bearer test'
    primary=DoubaoArkResponsesLlmExplainerBackend(api_key='test',model='test')
    fallback=DoubaoArkChatCompletionsLlmExplainerBackend(api_key='test',model='test')
    backend=DoubaoArkLlmExplainerBackend(primary=primary,fallback=fallback)
    context=TaskContext.start('fallback',1000)
    def fallback_transport(url,**kwargs):
        if url.endswith('/responses'):
            calls.append((url,kwargs));time.sleep(.03);raise RuntimeError('404 unsupported')
        return transport(url,**kwargs)
    with patch('asurada.llm_explainer.request_json',side_effect=fallback_transport):
        backend.explain_with_context(request,context=context)
    checks['fallback_same_cancellation_and_reduced_budget']=all(c[1]['context'] is context for c in calls[-2:]) and calls[-1][1]['timeout_ms']<calls[-2][1]['timeout_ms']
    calls.clear()
    def cancel_primary(url,**kwargs):
        calls.append(url);context.cancel();raise RuntimeError('404 unsupported')
    with patch('asurada.llm_explainer.request_json',side_effect=cancel_primary):
        try:backend.explain_with_context(request,context=context);checks['no_fallback_after_cancel']=False
        except TaskCancelled:checks['no_fallback_after_cancel']=len(calls)==1
    context=TaskContext.start('outer',1000)
    entered=threading.Event();released=threading.Event();seen=[]
    def waiting(url,**kwargs):
        seen.append(kwargs['context']);entered.set()
        try:
            while True:kwargs['context'].remaining();time.sleep(.005)
        finally:released.set()
    def cancel():
        if entered.wait(1):context.cancel()
    thread=threading.Thread(target=cancel);thread.start()
    with patch('asurada.llm_explainer.request_json',side_effect=waiting):
        result=LlmExplainer(backend=backend).run(request=request,context=context)
        released.wait(1)
    thread.join()
    checks['outer_context_reaches_provider']=seen==[context] and released.is_set() and result.fallback_reason=='llm_cancelled'
    return {'passed':all(checks.values()),'checks':checks,'scope':'mocked transport; not socket, proxy or live provider acceptance'}


if __name__=='__main__':emit_result(run())
