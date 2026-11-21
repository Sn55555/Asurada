from __future__ import annotations

import threading
import time
from dataclasses import replace
from regression_support import emit_result
from asurada.task_runtime import BoundedTaskExecutor, TaskContext
from asurada.llm_explainer import LlmExplainer, LlmExplainerRequest, DoubaoArkLlmExplainerBackend


def run():
    release = threading.Event()
    entered = threading.Event()
    calls = []
    class Blocking:
        name = 'blocking_fake'
        def explain(self, request):
            calls.append(request)
            entered.set()
            release.wait(2)
            return {'status': 'answerable', 'answer_text': 'late', 'confidence': .8,
                    'reason_fields': [], 'requires_confirmation': False}
    request = LlmExplainerRequest('s', 't', 'r', 'overall_situation', 'q', 'test', 40, {})
    executor = BoundedTaskExecutor(1)
    llm = LlmExplainer(backend=Blocking(), executor=executor)
    started = time.monotonic()
    timeout = llm.run(request=request)
    elapsed = time.monotonic() - started
    overloaded = llm.run(request=request)
    checks = {
        'deadline_returns_before_backend_finishes': timeout.fallback_reason == 'llm_timeout' and elapsed < .2 and not release.is_set(),
        'timed_out_worker_retains_capacity': overloaded.fallback_reason == 'llm_overloaded' and len(calls) == 1,
    }
    release.set()
    # A separate executor isolates cancellation from the worker releasing above.
    release.clear(); entered.clear()
    llm = LlmExplainer(backend=Blocking(), executor=BoundedTaskExecutor(1))
    context = TaskContext.start('cancel-test', 1000)
    result = []
    thread = threading.Thread(target=lambda: result.append(llm.run(request=request, context=context)))
    thread.start()
    entered.wait(.5)
    context.cancel()
    thread.join(.2)
    checks['cancel_returns_without_late_answer'] = not thread.is_alive() and result[0].fallback_reason == 'llm_cancelled' and result[0].response is None
    release.set()
    fallback_requests = []
    class Primary:
        def explain(self, request):
            time.sleep(.03)
            raise RuntimeError('responses unsupported')
    class Fallback:
        def explain(self, request):
            fallback_requests.append(request)
            return {}
    DoubaoArkLlmExplainerBackend(primary=Primary(), fallback=Fallback()).explain(replace(request, timeout_ms=100))
    checks['fallback_receives_remaining_budget'] = 0 < fallback_requests[0].timeout_ms <= 80
    expired = TaskContext.start('expired', 0)
    result = llm.run(request=request, context=expired)
    checks['expired_task_never_submits'] = result.fallback_reason == 'llm_timeout'
    return {'passed': all(checks.values()), 'checks': checks, 'analysis': {'timeout_elapsed_ms': round(elapsed*1000, 2)}}


if __name__ == '__main__':
    emit_result(run())
