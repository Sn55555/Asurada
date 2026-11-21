"""Bounded live strategy submissions; playback stays owned by the output service.

One worker and one replaceable pending decision. A receipt acknowledges submission,
not playback. Failed calls are not retried because delivery may already have occurred.
"""
from collections import Counter, deque
from copy import deepcopy
import math
import threading
import time
from .speech_clock import speech_time
import uuid


class LiveSpeechSubmission:
    def __init__(self, output, *, max_age_s=.5):
        if not math.isfinite(max_age_s) or max_age_s <= 0:
            raise ValueError('invalid_speech_submission_age')
        self.output = output
        self.max_age_s = max_age_s
        self._condition = threading.Condition()
        self._pending = None
        self._active = None
        self._closed = False
        self._counts = Counter()
        self._receipts = deque(maxlen=128)
        self._thread = threading.Thread(target=self._run, name='live-speech-submit', daemon=True)
        self._thread.start()

    def _record(self, item, status, **details):
        self._counts[status] += 1
        if len(self._receipts) == self._receipts.maxlen:
            self._counts['receipt_evicted'] += 1
        self._receipts.append(dict(submission_id=item['id'], status=status,
                                   session_uid=item['scope'][0], session_epoch=item['scope'][1],
                                   decision_id=item['decision_id'], **details))

    def emit(self, decision, *, state, render=True):
        # Freeze before another frame can mutate state or the logger adds fields.
        started = time.monotonic()
        produced = speech_time()
        frozen_state, frozen_decision = deepcopy((state, decision))
        record = decision.record
        item = dict(id=uuid.uuid4().hex, created=started, produced=produced, state=frozen_state,
                    decision=frozen_decision, render=render,
                    scope=(state.session_uid, state.session_epoch),
                    decision_id=record.decision_id if record else None)
        with self._condition:
            if self._closed:
                self._record(item, 'closed')
                event = 'submission_rejected'
            else:
                if self._pending is not None:
                    self._record(self._pending, 'superseded')
                self._pending = item
                self._counts['submitted'] += 1
                self._condition.notify()
                event = 'submission_accepted'
            receipts = list(self._receipts)
            self._receipts.clear()
            result = dict(event=dict(event_type=event, submission_id=item['id']),
                          receipts=receipts, health=self._health())
        # Never copy a worker's late debug mutation into the caller's decision.
        decision.debug['speech_submission'] = result
        return result

    def _health(self):
        return dict(counts=dict(self._counts), pending=int(self._pending is not None),
                    in_flight=int(self._active is not None), closed=self._closed,
                    worker_alive=self._thread.is_alive(), max_age_s=self.max_age_s)

    def snapshot(self):
        with self._condition:
            return dict(**self._health(), receipts=deepcopy(list(self._receipts)))

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed:
                    return
                item, self._pending = self._pending, None
                if time.monotonic() - item['created'] > self.max_age_s:
                    self._record(item, 'expired')
                    continue
                self._active = item['id']
            try:
                output = self.output.bind_delivery(item['produced']) if hasattr(self.output, 'bind_delivery') else self.output
                lifecycle = output.emit(item['decision'], state=item['state'], render=item['render'])
                with self._condition:
                    self._record(item, 'acknowledged', lifecycle=deepcopy(lifecycle))
            except Exception as exc:
                with self._condition:
                    self._record(item, 'delivery_unknown', error=f'{type(exc).__name__}: {exc}')
            finally:
                with self._condition:
                    self._active = None

    def close(self, *, timeout_s=1.2):
        with self._condition:
            self._closed = True
            if self._pending is not None:
                self._record(self._pending, 'closed')
                self._pending = None
            self._condition.notify_all()
        self._thread.join(timeout=max(0, timeout_s))
        # Does not stop the shared service or claim to cancel an in-flight call.
        return not self._thread.is_alive()
