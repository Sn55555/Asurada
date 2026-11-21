from regression_support import emit_result
from phase3_voice_regression import make_state
from asurada.capability_definitions import CAPABILITIES
from asurada.capability_registry import CapabilityRegistry
from asurada.response_composer import compose_structured_query_response


def run():
    state=make_state();registry=CapabilityRegistry();checks={}
    for name,spec in CAPABILITIES.items():
        check=registry.evaluate(query_kind=name,normalized_text='')
        checks[name+'_route']=(not check.allowed and check.reason=='requires_tool_execution') if spec.lane=='analysis_tool' else check.allowed and check.lane==spec.lane
        if spec.handler_name is not None and spec.lane!='analysis_tool':
            text,code=compose_structured_query_response(state=state,query_kind=name)
            checks[name+'_handler']=isinstance(text,str) and bool(text) and isinstance(code,str) and code.startswith('QUERY_')
    tools=registry.tool_catalog()
    checks['controls_not_model_tools']=all(item['policy']['permission'] in {'read_race_state','read_session_history'} and item['policy']['lane']!='control' for item in tools)
    checks['catalog_complete']=len(tools)==sum(spec.handler_name is not None for spec in CAPABILITIES.values())
    return {'passed':all(checks.values()),'checks':checks,'analysis':{'capabilities':len(CAPABILITIES),'tools':len(tools)}}

if __name__=='__main__':emit_result(run())
