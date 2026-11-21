"""Crash after a separate database commits but before workflow checkpointing."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from corner_review_regression import rows
from regression_support import emit_result
from asurada.session_review_workflow import run_session_review
from asurada.workflow_store import WorkflowStore

CHILD = r'''
import os,sys
from pathlib import Path
from asurada.training_memory import TrainingMemory
from asurada.training_plans import TrainingPlanStore
from asurada.workflow_store import WorkflowStore
from asurada.session_review_workflow import run_session_review
mode, root = sys.argv[1], Path(sys.argv[2])
if mode == 'memory':
    original = TrainingMemory.put
    def interrupted(self, **kwargs):
        original(self, **kwargs)
        os._exit(73)
    TrainingMemory.put = interrupted
else:
    original = TrainingPlanStore.process_review
    def interrupted(self, **kwargs):
        original(self, **kwargs)
        os._exit(73)
    TrainingPlanStore.process_review = interrupted
run_session_review(WorkflowStore(root/'review.db'), task_id='review', source=root/'source.jsonl', driver_id='driver')
'''


def read_rows(path, table):
    with sqlite3.connect(path) as db:
        return db.execute('SELECT * FROM ' + table + ' ORDER BY id').fetchall()


def run():
    checks = {}
    for mode in ('memory', 'plans'):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.jsonl'
            source.write_text('\n'.join(json.dumps(row) for row in rows()))
            child = subprocess.run([sys.executable, '-c', CHILD, mode, str(root)], capture_output=True, text=True, timeout=30)
            if child.returncode != 73:
                raise AssertionError({'mode': mode, 'code': child.returncode, 'stderr': child.stderr})
            store = WorkflowStore(root/'review.db')
            interrupted = store.get('review')
            checkpoint_names = [item['step'] for item in interrupted['results']]
            uncommitted = 'persist_session_facts' if mode == 'memory' else 'training_followup'
            checks[mode+'_crash_before_checkpoint'] = interrupted['status'] == 'running' and uncommitted not in checkpoint_names
            db_path = root / ('review.memory.sqlite3' if mode == 'memory' else 'review.training.sqlite3')
            table = 'memories' if mode == 'memory' else 'training_plans'
            before = read_rows(db_path, table)
            checks[mode+'_side_effect_committed'] = len(before) == 1
            result = run_session_review(store, task_id='review', source=source, driver_id='driver')
            after = read_rows(db_path, table)
            by_id = {row[0]: row for row in after}
            checks[mode+'_existing_row_and_expiry_unchanged'] = all(by_id.get(row[0]) == row for row in before)
            checks[mode+'_no_duplicate_side_effect'] = len(after) == (3 if mode == 'memory' else 1)
            checks[mode+'_workflow_completed'] = result['status'] == 'completed' and len(result['results']) == 6
            repeat = run_session_review(store, task_id='review', source=source, driver_id='driver')
            checks[mode+'_completed_read_does_not_repeat'] = repeat == result and read_rows(db_path, table) == after
    return {'passed': all(checks.values()), 'checks': checks,
            'scope': 'actual subprocess exit after committed SQLite side effect; memory insertion and draft creation only; no rollback or external-provider exactly-once claim'}


if __name__ == '__main__': emit_result(run())
