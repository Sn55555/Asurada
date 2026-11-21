"""The registry's output contract must be enforced at the tool boundary."""
from copy import deepcopy
from unittest.mock import patch
from regression_support import emit_result
from asurada.capability_definitions import CapabilitySpec
from asurada.capability_executor import CapabilityExecutor
from asurada.capabilities.history import ReviewScope
from asurada.task_runtime import TaskContext


def run():
    scope = ReviewScope('test-session', 0, 'Shanghai')
    valid = {'scope': {'session_uid': scope.session_uid, 'epoch': 0, 'track': scope.track},
             'laps': [{'session_uid': scope.session_uid, 'epoch': 0, 'track': scope.track,
                       'lap': n, 'time_ms': 1000 + n * 10, 'evidence': {'source_sha256': 'fixture'}} for n in (1, 2)],
             'delta_ms': 10, 'unit': 'ms',
             'evidence': [{'review_task_id': 'review', 'lap': n, 'source_sha256': 'fixture'} for n in (1, 2)],
             'interpretation': 'observed_lap_time_difference_not_causal_effect'}
    cases = {'missing_required_fields': {}, 'non_object_output': [],
             'wrong_unit': dict(valid, unit='seconds'),
             'nonfinite_number': dict(valid, delta_ms=float('nan')),
             'boolean_number': dict(valid, delta_ms=True),
             'wrong_collection_type': dict(valid, evidence='not an array')}
    cases['wrong_scope'] = dict(valid, scope={**valid['scope'], 'session_uid': 'other'})
    cases['missing_lap_duration'] = deepcopy(valid)
    del cases['missing_lap_duration']['laps'][0]['time_ms']
    cases['empty_source_reference'] = deepcopy(valid)
    cases['empty_source_reference']['evidence'][0]['source_sha256'] = ''
    cases['negative_lap_duration'] = deepcopy(valid)
    cases['negative_lap_duration']['laps'][0]['time_ms'] = -1
    checks = {}
    good_executor = CapabilityExecutor(context=TaskContext.start('valid', 1000),
        permissions=frozenset({'read_session_history'}), historical=True)
    with patch.object(CapabilitySpec, 'invoke', return_value=deepcopy(valid)):
        checks['valid_result_passes'] = good_executor.execute('compare_review_laps', state=scope,
            arguments={'review_task_id': 'review', 'lap_numbers': [1, 2]})['data'] == valid
    for name, output in cases.items():
        executor = CapabilityExecutor(context=TaskContext.start(name, 1000),
            permissions=frozenset({'read_session_history'}), historical=True)
        with patch.object(CapabilitySpec, 'invoke', return_value=deepcopy(output)):
            try:
                executor.execute('compare_review_laps', state=scope,
                                 arguments={'review_task_id': 'review', 'lap_numbers': [1, 2]})
            except ValueError:
                checks[name] = True
            else:
                checks[name] = False
    return {'passed': all(checks.values()), 'checks': checks,
            'scope': 'fault injection at registered handler return; verifies executor rejects malformed tool outputs'}


if __name__ == '__main__':
    emit_result(run())
