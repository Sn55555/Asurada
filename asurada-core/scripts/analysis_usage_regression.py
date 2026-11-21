import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from asurada.analysis_planner import HttpAnalysisPlanner
from asurada.capabilities.history import ReviewScope
from asurada.capability_executor import CapabilityExecutor
from asurada.durable_analysis import run_durable_analysis, read_analysis_result
from asurada.task_runtime import TaskContext
from asurada.workflow_store import WorkflowStore
from regression_support import emit_result


def run():
    checks = {}
    with tempfile.TemporaryDirectory() as tmp:
        store = WorkflowStore(Path(tmp) / 'review.db'); scope = ReviewScope('session', 0, 'Shanghai')
        store.create('review', {'driver_id': 'driver', 'steps': ['index_official_laps']})
        laps = [{'session_uid': 'session', 'epoch': 0, 'track': 'Shanghai', 'lap': n, 'time_ms': t,
                 'evidence': {'source_sha256': 'fixture'}} for n, t in [(1, 100000), (2, 99000)]]
        store.run('review', (('index_official_laps', lambda r, s, c: laps),))
        def executor():
            return CapabilityExecutor(context=TaskContext.start('analysis:usage', 5000), historical=True,
                permissions=frozenset({'read_session_history'}), review_store=store, driver_id='driver')
        provider = SimpleNamespace(model='fixture', base_url='https://example.invalid/v1', _headers=lambda: {'Authorization': 'secret-fixture'})
        def execute():
            return run_durable_analysis(store=store, task_id='analysis:usage', planner=HttpAnalysisPlanner(provider),
                planner_identity='fixture', executor=executor(), question='compare', scope=scope, review_task_id='review')
        call = {'action': 'call', 'tool': 'compare_review_laps', 'arguments_json': '{"review_task_id":"review","lap_numbers":[1,2]}', 'result_ids': []}
        finish = {'action': 'finish', 'tool': '', 'arguments_json': '{}', 'result_ids': ['result-1']}
        responses = [{'status': 'completed', 'output_text': json.dumps(call), 'usage': {'input_tokens': 10, 'output_tokens': 20}},
                     {'status': 'incomplete', 'output_text': '', 'usage': {'input_tokens': 30, 'output_tokens': 40}}]
        with patch('asurada.analysis_planner.request_json', side_effect=responses):
            first = execute()
        checks['failed_response_usage_persisted'] = first['status'] == 'failed' and first['provider_usage']['known_input_tokens'] == 40 and first['provider_usage']['known_output_tokens'] == 60
        with patch('asurada.analysis_planner.request_json', return_value={'status': 'completed', 'output_text': json.dumps(finish)}) as http:
            second = execute()
        usage = second['provider_usage']
        checks['resume_counts_only_new_request'] = http.call_count == 1 and usage['model_attempts'] == 3
        checks['missing_usage_not_free'] = usage['coverage'] == 'partial_or_unknown' and usage['attempts_with_unknown_or_partial_usage'] == 1 and usage['cost'] is None
        with patch('asurada.analysis_planner.request_json', side_effect=AssertionError('read must not call provider')):
            saved = read_analysis_result(store=store, task_id='analysis:usage', executor=executor())
        checks['read_preserves_cumulative_usage'] = saved['provider_usage'] == usage
        checks['credentials_not_stored'] = 'secret-fixture' not in json.dumps(store.get('analysis:usage'))
    return {'passed': all(checks.values()), 'checks': checks, 'scope': 'mock provider usage and real SQLite recovery; no billing acceptance'}


if __name__ == '__main__':
    emit_result(run())
