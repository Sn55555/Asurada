"""Bounded replayable event stream. Restart and retention loss are explicit."""
from collections import deque
import json
import uuid


class SpeechEventStream:
    def __init__(self, *, max_bytes=2*1024*1024, capacity=512):
        if max_bytes < 1 or capacity < 1:
            raise ValueError('invalid_event_retention')
        self.stream_id = uuid.uuid4().hex
        self.sequence = self.dropped_through = self.size = 0
        self.max_bytes, self.capacity = max_bytes, capacity
        self.rows = deque()

    def append(self, event):
        if event.get('event_type') == 'idle':
            return
        self.sequence += 1
        try:
            encoded = json.dumps(event, ensure_ascii=False, allow_nan=False).encode()
        except (TypeError, ValueError):
            self.rows.clear()
            self.size = 0
            self.dropped_through = self.sequence
            return
        while self.rows and (len(self.rows) >= self.capacity or self.size + len(encoded) > self.max_bytes):
            sequence, previous = self.rows.popleft()
            self.size -= len(previous)
            self.dropped_through = sequence
        if len(encoded) > self.max_bytes:
            self.dropped_through = self.sequence
            return
        self.rows.append((self.sequence, encoded))
        self.size += len(encoded)

    def read(self, *, cursor=None, limit=64):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 128:
            raise ValueError('invalid_event_limit')
        reset = False
        after = 0
        if cursor is not None:
            if not isinstance(cursor, dict) or set(cursor) != {'stream_id', 'sequence'}:
                raise ValueError('invalid_event_cursor')
            after = cursor['sequence']
            if isinstance(after, bool) or not isinstance(after, int) or after < 0 or not isinstance(cursor['stream_id'], str):
                raise ValueError('invalid_event_cursor')
            reset = cursor['stream_id'] != self.stream_id
            if reset:
                after = 0
            elif after > self.sequence:
                raise ValueError('event_cursor_in_future')
        selected = [(seq, data) for seq, data in self.rows if seq > after][:limit]
        next_sequence = selected[-1][0] if selected else max(after, self.dropped_through)
        return dict(version='speech-events-v1', reset=reset, gap=after < self.dropped_through,
            cursor=dict(stream_id=self.stream_id, sequence=next_sequence),
            events=[dict(sequence=seq, event=json.loads(data)) for seq, data in selected],
            has_more=bool(self.rows and self.rows[-1][0] > next_sequence))
