"""Reconcile owned query events into short conversational memory."""
from collections import OrderedDict


class DeliveryContext:
    def __init__(self):
        self.cursor = None
        self.radio = OrderedDict()
        self.radio_scope = None
        self.requests = OrderedDict()
        self.health = 'uninitialized'

    def track(self, bundle, scope, started):
        event = bundle.input_event
        self.requests[event['request_id']] = dict(scope=scope,
            query_kind=bundle.structured_query.get('query_kind'),
            timestamp_ms=event.get('created_at_ms', 0), started=started)
        while len(self.requests) > 128:
            self.requests.popitem(last=False)

    def refresh(self, output, conversation, scope, *, timeout_s=.1):
        if self.radio_scope != scope:
            self.radio.clear()
            self.radio_scope = scope
        if not hasattr(output, 'read_events'):
            self.health = 'unsupported'
            return
        try:
            page = output.read_events(cursor=self.cursor, timeout_s=timeout_s)
        except Exception as exc:
            self.health = 'read_failed:' + type(exc).__name__
            return
        if page['reset'] or page['gap']:
            self.requests.clear()
            self.radio.clear()
            self.health = 'stream_reset' if page['reset'] else 'events_lost'
        else:
            self.health = 'current' if not page['has_more'] else 'catching_up'
            for row in page['events']:
                event = row['event']
                meta = event.get("metadata") or {}
                event_id = event["output_event_id"]
                if tuple(meta.get("session_scope") or ()) == scope:
                    kind = event["event_type"]
                    if kind == "start" and isinstance(meta.get("radio_event_ms"), int) and isinstance(meta.get("radio_source_ms"), int):
                        self.radio[event_id] = dict(ref=row["sequence"], text=event["speak_text"][:180],
                            code=event["action_code"], status=kind, source_ms=meta["radio_source_ms"],
                            started_ms=meta["radio_event_ms"], rival=(meta.get("attack_opportunity") or {}).get("front_car_index"),
                            pit_id=meta.get("pit_recommendation_id"), fuel_id=meta.get("fuel_recommendation_id"))
                        while len(self.radio) > 12:
                            self.radio.popitem(last=False)
                    elif event_id in self.radio and kind in {"complete", "cancel", "failed"}:
                        self.radio[event_id]["status"] = kind
                request = self.requests.get(event['request_id'])
                if request is None or request['scope'] != scope:
                    continue
                kind = event['event_type']
                if kind in {'start', 'complete'} or kind in {'cancel', 'failed'} and request['started']:
                    request['started'] = True
                    conversation.observe_response(request_id=event['request_id'], query_kind=request['query_kind'],
                        action_code=event['action_code'], speak_text=event['speak_text'], timestamp_ms=request['timestamp_ms'],
                        metadata={'event_type': kind, 'delivery_status': {'start':'started', 'complete':'completed', 'cancel':'cancelled', 'failed':'failed'}[kind],
                                  'output_event_id': event['output_event_id']})
                if kind in {'complete', 'cancel', 'suppress', 'failed'}:
                    self.requests.pop(event['request_id'], None)
        self.cursor = page['cursor']
        self.requests = OrderedDict((key, value) for key, value in self.requests.items() if value['scope'] == scope)
