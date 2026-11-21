"""Local durable execution of fixed, read-only workflow steps.

A nonblocking per-task OS lock prevents duplicate coordinators for one task.
Only committed step results are resumed. Interrupted read-only steps may replay.
"""
from __future__ import annotations
import fcntl
from contextlib import contextmanager
from copy import deepcopy
from concurrent.futures import TimeoutError as FutureTimeout
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Callable, Any
from .task_runtime import TaskContext, TaskCancelled, BoundedTaskExecutor

_WORKFLOW_EXECUTOR = BoundedTaskExecutor(2)


class WorkflowStore:
    def __init__(self, path: Path, *, executor=None) -> None:
        self.path = path
        self.executor = executor or _WORKFLOW_EXECUTOR
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL, expires REAL NOT NULL, results TEXT NOT NULL, attempts INTEGER NOT NULL, error TEXT)')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=1)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, task_id: str, request: dict[str, Any], *, timeout_s: float = 300) -> None:
        encoded=json.dumps(request,sort_keys=True,separators=(',',':'))
        with self._connect() as db:
            existing=db.execute('SELECT request FROM tasks WHERE id=?',(task_id,)).fetchone()
            if existing:
                if existing[0]!=encoded:raise ValueError('task_id_input_conflict')
                return
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)',(task_id,encoded,'queued',time.time()+max(0,timeout_s),'[]',0,None))

    def get(self, task_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row=db.execute('SELECT request,status,expires,results,attempts,error FROM tasks WHERE id=?',(task_id,)).fetchone()
        if row is None:raise KeyError(task_id)
        return dict(request=json.loads(row[0]),status=row[1],expires=row[2],results=json.loads(row[3]),attempts=row[4],error=row[5])

    def cancel(self, task_id: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE tasks SET status='cancelled' WHERE id=? AND status NOT IN ('completed','expired')",(task_id,))

    @contextmanager
    def task_lock(self, task_id: str):
        lock_id = hashlib.sha256(task_id.encode()).hexdigest()
        with (self.path.parent / f'{self.path.name}.{lock_id}.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def run(self, task_id: str, steps: tuple[tuple[str, Callable], ...], *, max_attempts: int = 12) -> dict[str, Any]:
        lock_id = hashlib.sha256(task_id.encode()).hexdigest()
        lock_path = self.path.parent / f'{self.path.name}.{lock_id}.lock'
        with lock_path.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            task=self.get(task_id)
            if task['status'] in {'completed','cancelled','expired'}:return task
            names=[name for name,_ in steps]
            if task['request'].get('steps') != names:raise ValueError('workflow_definition_mismatch')
            results=task['results']
            if [item['step'] for item in results] != names[:len(results)]:raise ValueError('workflow_checkpoint_mismatch')
            context=TaskContext.start(task_id,max(0,(task['expires']-time.time())*1000))
            try:
                for name,step in steps[len(results):]:
                    context.remaining()
                    current=self.get(task_id)
                    if current['status']=='cancelled':return current
                    if current['attempts']>=max_attempts:raise ValueError('workflow_attempt_budget')
                    with self._connect() as db:
                        db.execute("UPDATE tasks SET status='running',attempts=attempts+1,error=NULL WHERE id=? AND status!='cancelled'",(task_id,))
                    value=self._execute_step(task_id, step, task['request'], results, context)
                    context.remaining()
                    results.append({'step':name,'result':value})
                    with self._connect() as db:
                        db.execute("UPDATE tasks SET results=? WHERE id=? AND status!='cancelled'",(json.dumps(results,ensure_ascii=False),task_id))
                with self._connect() as db:
                    db.execute("UPDATE tasks SET status='completed' WHERE id=? AND status!='cancelled'",(task_id,))
            except TaskCancelled:
                context.cancel()
                with self._connect() as db:
                    db.execute("UPDATE tasks SET status='cancelled',error='task_cancelled' WHERE id=? AND status NOT IN ('completed','expired')", (task_id,))
                return self.get(task_id)
            except Exception as exc:
                context.cancel()
                with self._connect() as db:
                    db.execute("UPDATE tasks SET status=?,error=? WHERE id=? AND status!='cancelled'",('expired' if isinstance(exc,TimeoutError) else 'failed',f'{type(exc).__name__}: {exc}',task_id))
                raise
            return self.get(task_id)

    def _execute_step(self, task_id, step, request, results, context):
        # The worker receives private inputs; only this coordinator can commit.
        owned_request, owned_results = deepcopy((request, results))
        if self.get(task_id)['status'] == 'cancelled':
            context.cancel()
            raise TaskCancelled(task_id)
        future = self.executor.submit(context, lambda: step(owned_request, owned_results, context))
        while True:
            context.remaining()
            if self.get(task_id)['status'] == 'cancelled':
                context.cancel()
                raise TaskCancelled(task_id)
            try:
                value = future.result(timeout=min(.025, context.remaining()))
            except FutureTimeout:
                if future.done():
                    raise
                continue
            context.remaining()
            if self.get(task_id)['status'] == 'cancelled':
                context.cancel()
                raise TaskCancelled(task_id)
            owned_value = deepcopy(value)
            context.remaining()
            return owned_value
