from copy import deepcopy
from asurada.analysis_answer import render_analysis_answer
from asurada.capabilities.history import ReviewScope
from regression_support import emit_result


def run():
    scope = ReviewScope('session', 0, 'Shanghai')
    evidence = [{'review_task_id': 'review', 'lap': n, 'source_sha256': 'fixture'} for n in [1, 2]]
    data = {'scope': {'session_uid': 'session', 'epoch': 0, 'track': 'Shanghai'},
            'unit': 'ms', 'interpretation': 'observed_segment_spread_not_causal_diagnosis',
            'status': 'compared', 'excluded': {'T2': 'conditions_or_distance_differ'},
            'comparisons': [{'segment': 'T1', 'lap_numbers': [1, 2], 'durations_ms': [5000, 4800],
                             'spread_ms': 200, 'delta_ms': -200, 'conditions': {'weather': 'Dry'}, 'evidence': evidence}]}
    result = {'tool': 'compare_review_segments', 'task_id': 'analysis', 'scope_id': scope.identity(),
              'historical': True, 'data': data}
    analysis = {'task_id': 'analysis', 'scope_id': scope.identity(), 'review_task_id': 'review',
                'observations': [{'status': 'completed', 'result': result}], 'selected_results': [result]}
    answer = render_analysis_answer(analysis)
    checks = {'segment_numbers_and_units': '相差 0.200 秒' in answer['text'] and '第 2 圈比第 1 圈快 0.200 秒' in answer['text'],
              'evidence_and_exclusions': answer['blocks'][0]['evidence'] == evidence and 'T2' in answer['blocks'][0]['excluded'],
              'no_causal_claim': '尚不能排除交通或燃油等影响' in answer['text']}
    for name, change in [
        ('wrong_unit', lambda a: a['selected_results'][0]['data'].update(unit='s')),
        ('wrong_scope', lambda a: a['selected_results'][0]['data']['scope'].update(epoch=1)),
        ('wrong_review', lambda a: a['selected_results'][0]['data']['comparisons'][0]['evidence'][0].update(review_task_id='other')),
        ('wrong_spread', lambda a: a['selected_results'][0]['data']['comparisons'][0].update(spread_ms=999)),
        ('nonfinite', lambda a: a['selected_results'][0]['data']['comparisons'][0].update(delta_ms=float('nan'))),
        ('failed_observation', lambda a: a['observations'][0].update(status='failed')),
    ]:
        bad = deepcopy(analysis); change(bad)
        try:
            render_analysis_answer(bad); checks[name] = False
        except ValueError:
            checks[name] = True
    empty = deepcopy(analysis)
    empty['selected_results'][0]['data'].update(status='insufficient_data', comparisons=[])
    checks['no_data_is_not_answered'] = render_analysis_answer(empty)['status'] == 'insufficient_data'
    answer['blocks'][0]['evidence'][0]['lap'] = 99
    checks['answer_does_not_mutate_evidence'] = evidence[0]['lap'] == 1
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())
