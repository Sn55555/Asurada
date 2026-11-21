"""Journal read-only analysis calls in the existing task store.

Recovery replays committed observations. Uncommitted reads may run again;
model attempts are reserved before I/O, including attempts with unknown outcome.
"""
from copy import deepcopy
import hashlib
import json
import threading
import time

from .analysis_agent import ReviewAnalysisAgent
from .analysis_answer import render_analysis_answer
from .capabilities.history import completed_review
from .task_runtime import TaskContext, TaskCancelled


def read_analysis_result(*, store, task_id, executor):
    """Read a terminal answer with a new read budget, never a new execution budget."""
    executor.context.remaining()
    if not executor.historical or 'read_session_history' not in executor.permissions:
        raise PermissionError('read_session_history')
    saved = store.get(task_id); request = saved['request']
    if request.get('kind') != 'review-analysis-journal-v1':
        raise ValueError('not_an_analysis_task')
    if request.get('driver_id') != executor.driver_id:
        raise PermissionError('analysis_owner_mismatch')
    review = completed_review(executor.review_store, executor.driver_id, request['review_task_id'], executor.context)
    if _digest(review) != request['review_sha256']:
        raise ValueError('analysis_review_changed')
    if saved['status'] not in {'completed', 'insufficient_data'}:
        raise ValueError('analysis_result_not_available')
    finals = [entry for entry in saved['results'] if entry['kind'] == 'final']
    if len(finals) != 1 or finals[0]['status'] != 'completed':
        raise ValueError('analysis_final_checkpoint_missing')
    result = deepcopy(finals[0]['result'])
    if (result['task_id'] != task_id or result['scope_id'] != request['scope_id']
            or result['review_task_id'] != request['review_task_id'] or result['status'] != saved['status']):
        raise ValueError('analysis_final_binding_mismatch')
    result['answer'] = render_analysis_answer(result)
    executor.context.remaining()
    return result


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _usage_summary(entries, attempts):
    records = [record for entry in entries if entry['kind'] == 'planner'
               for record in entry.get('provider_attempts', [])]
    known_input = known_output = complete = 0
    for record in records:
        usage = record.get('usage') or {}
        incoming = usage.get('input_tokens', usage.get('prompt_tokens'))
        outgoing = usage.get('output_tokens', usage.get('completion_tokens'))
        valid = lambda n: isinstance(n, int) and not isinstance(n, bool) and n >= 0
        if valid(incoming): known_input += incoming
        if valid(outgoing): known_output += outgoing
        if valid(incoming) and valid(outgoing): complete += 1
    return {'model_attempts': attempts, 'attempts_with_complete_usage': complete,
            'attempts_with_unknown_or_partial_usage': attempts - complete,
            'known_input_tokens': known_input, 'known_output_tokens': known_output,
            'coverage': 'complete' if attempts == complete else 'partial_or_unknown',
            'cost': None, 'cost_status': 'not_calculated', 'attempts': deepcopy(records)}


class _Journal:
    def __init__(self, store, task_id, context, max_model_calls, max_tool_calls):
        self.store, self.task_id, self.context = store, task_id, context
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self.position = 0

    def call(self, kind, arguments, invoke, audit=None):
        self.context.remaining()
        task = self.store.get(self.task_id)
        if task['status'] == 'cancelled':
            self.context.cancel(); raise TaskCancelled(self.task_id)
        entries = task['results']; index = self.position
        self.position += 1
        signature = _digest(arguments)
        if index < len(entries):
            entry = entries[index]
            if entry['kind'] != kind or entry['input_sha256'] != signature:
                raise ValueError('analysis_journal_input_mismatch')
            if entry['status'] == 'completed':
                return deepcopy(entry['result'])
        else:
            entries.append({'kind': kind, 'input_sha256': signature, 'status': 'pending'})
        with self.store._connect() as db:
            if kind == 'planner' and task['attempts'] >= self.max_model_calls:
                raise ValueError('analysis_persistent_model_budget_exhausted')
            if kind == 'planner':
                entries[index].setdefault('provider_attempts', []).append({'status': 'outcome_unknown', 'usage': None})
            if kind == 'tool':
                if sum(e.get('attempts', 0) for e in entries if e['kind'] == 'tool') >= self.max_tool_calls:
                    raise ValueError('analysis_persistent_tool_budget_exhausted')
                entries[index]['attempts'] = entries[index].get('attempts', 0) + 1
            changed = db.execute("UPDATE tasks SET results=?, attempts=attempts+?, status='running' WHERE id=? AND status!='cancelled'",
                (json.dumps(entries, allow_nan=False), int(kind == 'planner'), self.task_id)).rowcount
            if not changed:
                self.context.cancel(); raise TaskCancelled(self.task_id)
        try:
            value = invoke()
        except Exception:
            # A cancelled/expired worker must not write late state. Its reserved
            # attempt remains outcome_unknown, rather than appearing free.
            if audit is not None:
                try:
                    self.context.remaining()
                except (TaskCancelled, TimeoutError):
                    raise
                entries[index]['provider_attempts'][-1] = deepcopy(audit)
                with self.store._connect() as db:
                    db.execute("UPDATE tasks SET results=? WHERE id=? AND status!='cancelled'",
                        (json.dumps(entries, ensure_ascii=False, allow_nan=False), self.task_id))
            raise
        self.context.remaining()
        if audit is not None:
            entries[index]['provider_attempts'][-1] = deepcopy(audit)
        entries[index].update(status='completed', result=deepcopy(value))
        with self.store._connect() as db:
            changed = db.execute("UPDATE tasks SET results=? WHERE id=? AND status!='cancelled'",
                (json.dumps(entries, ensure_ascii=False, allow_nan=False), self.task_id)).rowcount
            if not changed:
                self.context.cancel(); raise TaskCancelled(self.task_id)
        return value


class _Planner:
    def __init__(self, journal, planner):
        self.journal, self.planner = journal, planner

    def next_step(self, payload, *, context):
        audit = {'status': 'outcome_unknown', 'usage': None}
        def invoke():
            calls = getattr(self.planner, 'calls', None)
            count = len(calls) if isinstance(calls, list) else None
            try:
                value = self.planner.next_step(payload, context=context)
                audit['status'] = 'completed'
                return value
            except Exception:
                audit['status'] = 'failed'
                raise
            finally:
                if count is not None and len(calls) == count + 1:
                    # Store only provider accounting metadata, never credentials.
                    audit.update({key: deepcopy(calls[-1][key]) for key in
                        ('status', 'model', 'style', 'requested_max_output_tokens', 'usage') if key in calls[-1]})
        return self.journal.call('planner', payload, invoke, audit=audit)


class _Tools:
    def __init__(self, journal, executor, review_id, review_digest):
        self.journal, self.executor, self.review_id = journal, executor, review_id
        self.review_digest = review_digest
        self.context, self.permissions = executor.context, executor.permissions

    def execute(self, name, *, state, arguments):
        # Authorization is checked even when the tool result is already cached.
        current = completed_review(self.executor.review_store, self.executor.driver_id, self.review_id, self.context)
        if _digest(current) != self.review_digest:
            raise ValueError('analysis_review_changed')
        return self.journal.call('tool', {'name': name, 'scope': state.identity(), 'arguments': arguments},
                                 lambda: self.executor.execute(name, state=state, arguments=arguments))


def run_durable_analysis(*, store, task_id, planner, planner_identity, executor, question,
                         scope, review_task_id, max_model_calls=6, max_tool_calls=4):
    if not task_id.startswith('analysis:'):
        raise ValueError('analysis_task_namespace_required')
    review = completed_review(executor.review_store, executor.driver_id, review_task_id, executor.context)
    request = {'kind': 'review-analysis-journal-v1', 'question': question, 'scope_id': scope.identity(),
               'review_task_id': review_task_id, 'driver_id': executor.driver_id,
               'permissions': sorted(executor.permissions), 'planner_identity': planner_identity,
               'max_model_calls': max_model_calls, 'max_tool_calls': max_tool_calls, 'review_sha256': _digest(review)}
    if 'read_session_history' not in executor.permissions or not executor.historical:
        raise PermissionError('read_session_history')
    with store.task_lock(task_id):
        store.create(task_id, request, timeout_s=executor.context.remaining())
        saved = store.get(task_id)
        if saved['status'] in {'completed', 'insufficient_data'}:
            return read_analysis_result(store=store, task_id=task_id, executor=executor)
        if saved['status'] in {'cancelled', 'expired'}:
            raise ValueError('analysis_task_' + saved['status'])
        # Restarts cannot reset the original elapsed-time budget.
        executor.context = TaskContext(task_id, min(executor.context.deadline,
            time.monotonic() + max(0, saved['expires'] - time.time())), executor.context.cancellation)
        context = executor.context
        finished = threading.Event()
        def watch_cancel():
            while not finished.wait(.025):
                try:
                    if store.get(task_id)['status'] == 'cancelled':
                        context.cancel(); return
                except Exception:
                    context.cancel(); return
        watcher = threading.Thread(target=watch_cancel, daemon=True, name='analysis-cancellation')
        watcher.start()
        try:
            journal = _Journal(store, task_id, context, max_model_calls, max_tool_calls)
            agent = ReviewAnalysisAgent(planner=_Planner(journal, planner),
                executor=_Tools(journal, executor, review_task_id, request['review_sha256']), max_model_calls=max_model_calls,
                max_tool_calls=max_tool_calls)
            result = agent.run(question=question, scope=scope, review_task_id=review_task_id)
            current = store.get(task_id)
            result['journal'] = {'task_id': task_id, 'model_attempts': current['attempts'],
                                 'recovery': 'committed_calls_replayed_uncommitted_reads_may_repeat'}
            entries = current['results']
            result['provider_usage'] = _usage_summary(entries, current['attempts'])
            if result['status'] in {'completed', 'insufficient_data'}:
                context.remaining()
                entries.append({'kind': 'final', 'status': 'completed', 'result': deepcopy(result)})
            with store._connect() as db:
                changed = db.execute("UPDATE tasks SET status=?,error=?,results=? WHERE id=? AND status!='cancelled'",
                    (result['status'], json.dumps(result.get('error')) if result.get('error') else None,
                     json.dumps(entries, ensure_ascii=False, allow_nan=False), task_id)).rowcount
            if not changed:
                result.pop('answer', None); result['status'] = 'cancelled'
            if result['status'] in {'completed', 'insufficient_data'}:
                context.remaining()
            return result
        finally:
            finished.set(); watcher.join(timeout=1.1)
