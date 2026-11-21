from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time

from regression_support import emit_result
from asurada.task_runtime import BoundedTaskExecutor, TaskCapacityExceeded
from asurada.workflow_store import WorkflowStore


def run():
    checks = {}
    with TemporaryDirectory() as temp:
        store = WorkflowStore(Path(temp)/'tasks.db', executor=BoundedTaskExecutor(1))
        entered, release, finished = Event(), Event(), Event()
        contexts = []
        def blocked(request, results, context):
            contexts.append(context)
            entered.set()
            release.wait(2)
            finished.set()
            return {'late':True}
        store.create('slow',{'steps':['one']},timeout_s=.08)
        started = time.monotonic()
        try:
            store.run('slow',(('one',blocked),))
            checks['deadline_returns_while_worker_blocked'] = False
        except TimeoutError:
            checks['deadline_returns_while_worker_blocked'] = time.monotonic()-started < .3 and not finished.is_set()
        checks['expiry_cancels_worker_context'] = contexts[0].cancellation.is_set()
        checks['expiry_persisted_without_result'] = store.get('slow')['status']=='expired' and not store.get('slow')['results']
        store.create('overload',{'steps':['one']})
        try:
            store.run('overload',(('one',lambda *a:1),))
            checks['timed_out_worker_keeps_capacity'] = False
        except TaskCapacityExceeded:
            checks['timed_out_worker_keeps_capacity'] = True
        release.set(); finished.wait(1)
        time.sleep(.01)
        checks['late_result_never_committed'] = not store.get('slow')['results']
        entered.clear(); release.clear(); finished.clear()
        store.create('cancel',{'steps':['one']})
        result = []
        worker = Thread(target=lambda:result.append(store.run('cancel',(('one',blocked),))))
        worker.start(); entered.wait(1)
        # A different store object represents cancellation by another coordinator.
        WorkflowStore(store.path).cancel('cancel')
        worker.join(.3)
        checks['persisted_cancel_interrupts_wait'] = not worker.is_alive() and result[0]['status']=='cancelled' and not finished.is_set()
        checks['cancel_reaches_inflight_context'] = contexts[-1].cancellation.is_set()
        release.set(); finished.wait(1); worker.join(1)
        checks['cancelled_result_never_committed'] = not store.get('cancel')['results']

        store = WorkflowStore(Path(temp)/'parallel.db', executor=BoundedTaskExecutor(2))
        entered.clear(); release.clear(); finished.clear()
        store.create('one',{'steps':['one']});store.create('two',{'steps':['one']})
        results = []
        worker = Thread(target=lambda:results.append(store.run('one',(('one',blocked),))))
        worker.start(); entered.wait(1)
        second = store.run('two',(('one',lambda *a:2),))
        checks['unrelated_tasks_do_not_share_execution_lock'] = second['status']=='completed' and not finished.is_set()
        try:
            store.run('one',(('one',lambda *a:3),))
            checks['same_task_coordinator_excluded'] = False
        except BlockingIOError:
            checks['same_task_coordinator_excluded'] = True
        release.set(); worker.join(1)
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())
