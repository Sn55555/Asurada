"""Machine-readable command results that distinguish invocation and task state."""


def execute_review(callback, *, store, task_id):
    try:
        result = callback()
    except Exception as error:
        try:
            task = store.get(task_id)
        except Exception:
            task = None
        if isinstance(error, TimeoutError) and task is not None and task['status']=='expired':
            return task, 2
        # An input conflict can refer to an already completed task. Its old
        # status must never turn the new, failed invocation into a success.
        result = {'status': 'invocation_failed', 'task_id': task_id,
                  'error': {'type': type(error).__name__, 'message': str(error)},
                  'task_status': task['status'] if task else None}
        return result, 1
    completed = result.get('status') == 'completed'
    results = result.get('results') or []
    if completed and (not results or results[-1].get('step') != 'review_report'):
        return {'status': 'invocation_failed', 'task_id': task_id,
                'error': {'type': 'InvalidReviewResult', 'message': 'completed_review_report_missing'}}, 1
    return result, 0 if completed else 2


def review_summary(result):
    summary = {'status': result['status']}
    if result['status'] == 'completed':
        report = result['results'][-1]['result']
        summary.update(comparisons=len(report['segment_review']['comparisons']),
                       rejected=report['segment_review']['rejected'])
    elif result.get('error'):
        summary['error'] = result['error']
    return summary
