"""A submission receipt describes observed scheduling, not completed speech."""


def delivery_receipt(debug, request_id):
    event = ((debug.get('output_lifecycle') or {}).get('event') or {})
    kind = event.get('event_type')
    matches = event.get('request_id') == request_id
    status = {'start': 'started', 'enqueue': 'queued', 'replace_pending': 'queued',
              'suppress': 'suppressed', 'cancel': 'cancelled', 'complete': 'completed',
              'failed': 'failed', 'idle': 'idle', 'silent': 'silent'}.get(kind, 'unknown') if matches else 'unknown'
    control = debug.get('control_result')
    if not isinstance(control, dict) or control.get('request_id') != request_id:
        control = None
    return dict(version='delivery-receipt-v1', request_id=request_id, status=status,
                output_event_id=event.get('output_event_id') if matches else None,
                reason=(event.get('metadata') or {}).get('reason') if matches else 'no_matching_output_event',
                control_result=control)
