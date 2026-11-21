"""Deterministic review answers derived only from selected tool observations."""
import math
from copy import deepcopy

from .capabilities.history import ReviewScope


def _number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (positive and value <= 0):
        raise ValueError('invalid_answer_number')
    return value


def _measurements(numbers, durations, evidence, review_id):
    if (not isinstance(numbers, list) or not 2 <= len(numbers) <= 10
            or any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in numbers)
            or len(set(numbers)) != len(numbers) or len(durations) != len(numbers)
            or not isinstance(evidence, list) or len(evidence) != len(numbers)):
        raise ValueError('invalid_answer_measurements')
    for n, duration, ref in zip(numbers, durations, evidence):
        _number(duration, positive=True)
        if (not isinstance(ref, dict) or ref.get('lap') != n
                or ref.get('review_task_id') != review_id
                or not isinstance(ref.get('source_sha256'), str) or not ref['source_sha256']):
            raise ValueError('invalid_answer_evidence')


def _delta_text(first, last, delta):
    relation = '快' if delta < 0 else '慢' if delta > 0 else '相同'
    if delta == 0:
        return f'第 {last} 圈与第 {first} 圈用时相同。'
    return f'第 {last} 圈比第 {first} 圈{relation} {abs(delta) / 1000:.3f} 秒。'


def render_analysis_answer(analysis):
    """Not an authentication boundary; callers must load authorized tool results."""
    blocks = []
    successful = [o['result'] for o in analysis['observations'] if o['status'] == 'completed']
    for result in analysis['selected_results']:
        if (result not in successful or result.get('task_id') != analysis['task_id']
                or result.get('scope_id') != analysis['scope_id'] or result.get('historical') is not True):
            raise ValueError('answer_result_binding_mismatch')
        data = result['data']; scope = data['scope']
        identity = ReviewScope(scope['session_uid'], scope['epoch'], scope['track']).identity()
        if identity != analysis['scope_id'] or data.get('unit') != 'ms':
            raise ValueError('answer_scope_or_unit_mismatch')
        if result['tool'] == 'compare_review_laps':
            if data.get('interpretation') != 'observed_lap_time_difference_not_causal_effect':
                raise ValueError('invalid_answer_interpretation')
            laps = data['laps']; numbers = [lap['lap'] for lap in laps]
            durations = [lap['time_ms'] for lap in laps]
            _measurements(numbers, durations, data['evidence'], analysis['review_task_id'])
            if any(any(lap.get(key) != value for key, value in scope.items()) for lap in laps):
                raise ValueError('answer_lap_scope_mismatch')
            delta = _number(data['delta_ms'])
            if not math.isclose(delta, durations[-1] - durations[0], rel_tol=0, abs_tol=1e-6):
                raise ValueError('answer_delta_mismatch')
            text = '；'.join(f'第 {n} 圈 {t / 1000:.3f} 秒' for n, t in zip(numbers, durations)) + '。'
            text += _delta_text(numbers[0], numbers[-1], delta)
            text += '这是观测圈时差异，不能据此认定训练或某项操作产生了效果。'
            blocks.append({'tool': result['tool'], 'text': text, 'evidence': deepcopy(data['evidence'])})
        elif result['tool'] == 'compare_review_segments':
            if data.get('interpretation') != 'observed_segment_spread_not_causal_diagnosis':
                raise ValueError('invalid_answer_interpretation')
            comparisons = data['comparisons']
            if data['status'] == 'insufficient_data' and not comparisons:
                blocks.append({'tool': result['tool'], 'text': '这些圈没有足够的可比区段数据，暂时无法判断区段耗时波动。', 'evidence': [], 'excluded': deepcopy(data['excluded'])})
                continue
            if data['status'] != 'compared' or not comparisons:
                raise ValueError('invalid_answer_comparison_status')
            for row in comparisons:
                numbers, durations = row['lap_numbers'], row['durations_ms']
                _measurements(numbers, durations, row['evidence'], analysis['review_task_id'])
                spread = _number(row['spread_ms']); delta = _number(row['delta_ms'])
                if (not math.isclose(spread, round(max(durations) - min(durations), 3), rel_tol=0, abs_tol=1e-6)
                        or not math.isclose(delta, round(durations[-1] - durations[0], 3), rel_tol=0, abs_tol=1e-6)):
                    raise ValueError('answer_segment_derivation_mismatch')
                name = row['segment']
                if not isinstance(name, str) or not name.strip():
                    raise ValueError('invalid_answer_segment')
                text = f'区段 {name}，比较圈号 {"、".join(map(str, numbers))}，最长与最短用时相差 {spread / 1000:.3f} 秒。'
                text += _delta_text(numbers[0], numbers[-1], delta)
                text += '已按工具记录的条件和距离范围比较；耗时波动不等于驾驶原因诊断，尚不能排除交通或燃油等影响。'
                blocks.append({'tool': result['tool'], 'text': text, 'evidence': deepcopy(row['evidence']),
                               'conditions': deepcopy(row['conditions']), 'excluded': deepcopy(data['excluded'])})
        else:
            raise ValueError('unsupported_answer_tool')
    has_evidence = any(block['evidence'] for block in blocks)
    return {'version': 'review-answer-v1', 'status': 'answered' if has_evidence else 'insufficient_data',
            'scope_id': analysis['scope_id'], 'review_task_id': analysis['review_task_id'],
            'text': '\n'.join(block['text'] for block in blocks) or '没有可用于回答的成功工具证据。', 'blocks': blocks}
