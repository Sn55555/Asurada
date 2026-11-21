"""Both voice query entry points consume declared capability freshness."""
from dataclasses import replace
from asurada.capability_definitions import CAPABILITIES
import asurada.speech_applicability as module
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    state=make_state();state.source_timestamp_ms=1000000
    checks={};previous=CAPABILITIES['fuel_status']
    try:
     for limit in (100,15000):
      CAPABILITIES['fuel_status']=replace(previous,freshness_ms=limit)
      for method,params in [('emit_query_response',{'query_kind':'fuel_status'}),('emit_interaction_bundle',{'bundle':{'structured_query':{'query_kind':'fuel_status'}}})]:
       for age in (50,200,16000):
        try:
         module.validate_query_applicability(method,params,state,state,wall_clock=lambda:(1000000+age)/1000)
         checks[f'{limit}_{method}_{age}']=age<=limit
        except ValueError as e:
         checks[f'{limit}_{method}_{age}']=age>limit and str(e)=='speech_answer_snapshot_expired'
    finally:CAPABILITIES['fuel_status']=previous
    return {'passed':all(checks.values()),'checks':checks}

if __name__ == '__main__':
    emit_result(run())
