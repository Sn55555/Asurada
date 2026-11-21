from regression_support import emit_result
from phase3_voice_regression import make_state
from asurada.capability_executor import CapabilityExecutor
from asurada.task_runtime import TaskContext
from asurada.assessment import snapshot_id


def run():
    state=make_state()
    def runner(**kwargs):
        return CapabilityExecutor(context=TaskContext.start('test',1000),permissions=frozenset({'read_race_state'}),wall_clock=lambda:state.source_timestamp_ms/1000,**kwargs)
    def denied(executor, name='fuel_status', arguments=None):
        try:executor.execute(name,state=state,arguments=arguments);return False
        except (ValueError,PermissionError):return True
    checks={'valid':runner().execute('fuel_status',state=state)['snapshot_id']==snapshot_id(state),
            'controls_denied':denied(runner(),'stop'), 'unknown_denied':denied(runner(),'shell'),
            'arguments_validated':denied(runner(),arguments={'command':'anything'}),
            'old_snapshot_denied':denied(CapabilityExecutor(context=TaskContext.start('old',1000),permissions=frozenset({'read_race_state'}),wall_clock=lambda:state.source_timestamp_ms/1000+20)),
            'historical_requires_permission':denied(runner(historical=True)),
            'superseded_denied':denied(runner(current_snapshot_id=lambda:'another'))}
    limit=runner(max_calls=1);limit.execute('fuel_status',state=state);checks['call_budget']=denied(limit)
    history=CapabilityExecutor(context=TaskContext.start('history',1000),permissions=frozenset({'read_session_history'}),historical=True)
    checks['explicit_historical_read']=history.execute('fuel_status',state=state)['historical']
    return {'passed':all(checks.values()),'checks':checks}

if __name__=='__main__':emit_result(run())
