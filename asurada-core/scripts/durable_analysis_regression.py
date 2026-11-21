import json
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from asurada.capabilities.history import ReviewScope
from asurada.capability_executor import CapabilityExecutor
from asurada.durable_analysis import run_durable_analysis
from asurada.task_runtime import TaskContext
from asurada.workflow_store import WorkflowStore
from regression_support import emit_result


def run():
    checks = {}
    with tempfile.TemporaryDirectory() as tmp:
        store = WorkflowStore(Path(tmp) / 'review.db')
        scope = ReviewScope('session', 0, 'Shanghai')
        laps = [{'session_uid': 'session', 'epoch': 0, 'track': 'Shanghai', 'lap': n,
                 'time_ms': t, 'evidence': {'source_sha256': 'fixture'}} for n, t in [(1, 100000), (2, 99000)]]
        store.create('review', {'driver_id': 'driver', 'steps': ['index_official_laps']})
        store.run('review', (('index_official_laps', lambda r, s, c: laps),))
        call = {'action': 'call', 'tool': 'compare_review_laps', 'arguments': {'review_task_id': 'review', 'lap_numbers': [1, 2]}}
        finish = {'action': 'finish', 'result_ids': ['result-1']}
        def execute(task_id, function, **options):
            executor = CapabilityExecutor(context=TaskContext.start(task_id, 5000),
                permissions=frozenset({'read_session_history'}), historical=True, review_store=store, driver_id='driver')
            return run_durable_analysis(store=store, task_id=task_id, planner=SimpleNamespace(next_step=function),
                planner_identity='fixture', executor=executor, question='compare', scope=scope, review_task_id='review', **options)
        def interrupted(payload, *, context):
            if payload['observations']:
                raise RuntimeError('simulated_transport_failure')
            return call
        first = execute('analysis:resume', interrupted)
        before = store.get('analysis:resume')
        checks['completed_tool_checkpointed'] = first['status'] == 'failed' and before['attempts'] == 2 and before['results'][1]['status'] == 'completed'
        planner_calls = []
        def recovered(payload, *, context):
            planner_calls.append(payload)
            return finish
        with patch.object(CapabilityExecutor, 'execute', side_effect=AssertionError('cached tool repeated')):
            second = execute('analysis:resume', recovered)
        checks['resume_reuses_committed_calls'] = second['status'] == 'completed' and len(planner_calls) == 1 and len(planner_calls[0]['observations']) == 1
        checks['attempts_and_expiry_preserved'] = store.get('analysis:resume')['attempts'] == 3 and store.get('analysis:resume')['expires'] == before['expires']
        checks['answer_after_recovery'] = '快 1.000 秒' in second['answer']['text']
        execute('analysis:budget', interrupted, max_model_calls=2)
        budget = execute('analysis:budget', recovered, max_model_calls=2)
        checks['restart_does_not_reset_model_budget'] = budget['status'] == 'failed' and store.get('analysis:budget')['attempts'] == 2
        with patch.object(CapabilityExecutor, 'execute', side_effect=RuntimeError('interrupted read')) as tool:
            execute('analysis:tool-budget', interrupted, max_tool_calls=1)
            execute('analysis:tool-budget', interrupted, max_tool_calls=1)
            checks['restart_does_not_reset_tool_budget'] = tool.call_count == 1
        with store.task_lock('analysis:locked'):
            try:
                execute('analysis:locked', recovered); checks['exclusive_coordinator'] = False
            except BlockingIOError:
                checks['exclusive_coordinator'] = True
        with store._connect() as db:
            db.execute('UPDATE tasks SET expires=? WHERE id=?', (time.time() - 1, 'analysis:resume'))
        recovered_count = len(planner_calls)
        completed_read = execute('analysis:resume', recovered)
        checks['completed_answer_survives_deadline'] = completed_read['status'] == 'completed' and len(planner_calls) == recovered_count
        with store._connect() as db:
            db.execute('UPDATE tasks SET expires=? WHERE id=?', (time.time() - 1, 'analysis:budget'))
        expired = execute('analysis:budget', recovered, max_model_calls=2)
        checks['original_deadline_enforced'] = expired['status'] == 'expired' and 'answer' not in expired
        started = threading.Event(); outputs = []
        def waiting(payload, *, context):
            started.set()
            while True:
                context.remaining(); time.sleep(.005)
        worker = threading.Thread(target=lambda: outputs.append(execute('analysis:cancel', waiting)))
        worker.start(); assert started.wait(2)
        store.cancel('analysis:cancel'); worker.join(2)
        checks['persistent_cancel_reaches_planner'] = not worker.is_alive() and outputs[0]['status'] == 'cancelled' and 'answer' not in outputs[0]
        root = Path(tmp); script = root / 'planner.py'; marker = root / 'interrupted'
        script.write_text('import json,sys\nfrom pathlib import Path\np=json.load(sys.stdin)\nm=Path(' + repr(str(marker)) + ')\n'
            'if p["observations"] and not m.exists():\n m.write_text("failed once")\n sys.exit(1)\n'
            'print(json.dumps(' + repr(call) + ' if not p["observations"] else ' + repr(finish) + '))\n')
        scope_file = root / 'scope.json'
        scope_file.write_text(json.dumps({'session_uid': 'session', 'session_epoch': 0, 'track': 'Shanghai'}))
        output = root / 'answer.json'
        command = [sys.executable, str(Path(__file__).with_name('run_review_analysis.py')),
                   '--analysis-id', 'cli-recovery', '--question', 'compare', '--review-task-id', 'review',
                   '--driver-id', 'driver', '--review-store', str(store.path), '--scope', str(scope_file),
                   '--output', str(output), '--planner-command', shlex.join([sys.executable, str(script)])]
        one = subprocess.run(command, capture_output=True, text=True, timeout=5)
        two = subprocess.run(command, capture_output=True, text=True, timeout=5)
        checks['actual_cli_process_restart'] = one.returncode == 2 and two.returncode == 0 and json.loads(output.read_text())['journal']['model_attempts'] == 3
        with store._connect() as db:
            db.execute('UPDATE tasks SET expires=? WHERE id=?', (time.time() - 1, 'analysis:cli-recovery'))
        read_command = [sys.executable, str(Path(__file__).with_name('read_review_analysis.py')),
                        '--task-id', 'analysis:cli-recovery', '--driver-id', 'driver',
                        '--review-store', str(store.path), '--output', str(output)]
        read_process = subprocess.run(read_command, capture_output=True, text=True, timeout=5)
        checks['actual_read_cli_after_expiry'] = read_process.returncode == 0 and '快 1.000 秒' in json.loads(output.read_text())['answer']['text']
        # A completed review changing ownership must invalidate cached access.
        with store._connect() as db:
            req = store.get('review')['request']; req['driver_id'] = 'other'
            db.execute('UPDATE tasks SET request=? WHERE id=?', (json.dumps(req), 'review'))
        try:
            execute('analysis:budget', recovered, max_model_calls=2); checks['restore_rechecks_owner'] = False
        except PermissionError:
            checks['restore_rechecks_owner'] = True
        revoked = subprocess.run(read_command, capture_output=True, text=True, timeout=5)
        checks['read_cli_rechecks_revoked_owner'] = revoked.returncode != 0 and 'review_owner_mismatch' in revoked.stderr
    return {'passed': all(checks.values()), 'checks': checks,
            'scope': 'SQLite recovery and fault-injected planner; no live provider or voice'}


if __name__ == '__main__':
    emit_result(run())
