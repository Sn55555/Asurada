"""Capability and parent budgets must constrain the actual LLM request."""
from dataclasses import replace
from asurada.capability_definitions import CAPABILITIES, CONTROL_QUERY_KINDS
from asurada.llm_explainer import LlmExplainer
from asurada.task_runtime import TaskContext
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
import asurada.voice_input as module
from phase3_llm_sidecar_integration_regression import _make_state, _make_turn, SuccessBackend
from regression_support import runtime_clock, emit_result
@runtime_clock(1777200000000)
def run():
 checks={};observed=[];old=CAPABILITIES['overall_situation']
 try:
  CAPABILITIES['overall_situation']=replace(old,deadline_ms=100)
  for configured,parent,expected in [(900,None,100),(50,None,50),(900,30,30)]:
   calls=[]
   class Backend(SuccessBackend):
    def explain(self,request):calls.append(request.timeout_ms);return super().explain(request)
   c=module.VoiceInputCoordinator(llm_explainer=LlmExplainer(backend=Backend()),enable_llm_sidecar=True,llm_timeout_ms=configured)
   ctx=TaskContext.start('parent',parent) if parent else None
   result=c.process_completed_turn(state=_make_state(),turn=_make_turn('整体形势怎么样','policy-check'),voice_output=ConsoleVoiceOutput(backend=NullSpeechBackend()),render=False,context=ctx)
   checks[f'budget_{configured}_{parent}']=bool(calls) and 0<calls[0]<=expected
   observed.append({'configured':configured,'parent':parent,'backend':list(calls)})
  context=TaskContext.start('cancelled',100);context.cancel();calls.clear()
  result=c.process_completed_turn(state=_make_state(),turn=_make_turn('整体形势怎么样','cancelled'),voice_output=ConsoleVoiceOutput(backend=NullSpeechBackend()),render=False,context=context)
  checks['cancelled_parent_never_calls_backend']=result.status=='cancelled' and not calls
  checks['single_control_definition']=module.CONTROL_QUERY_KINDS is CONTROL_QUERY_KINDS
 finally:CAPABILITIES['overall_situation']=old
 return {'passed':all(checks.values()),'checks':checks,'observed':observed}

if __name__ == '__main__':
 emit_result(run())
