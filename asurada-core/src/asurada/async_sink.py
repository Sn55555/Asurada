"""Bounded asynchronous sink with explicit loss/error accounting."""
from __future__ import annotations
from collections import deque
from copy import deepcopy
import threading
import time
from typing import Any


class AsyncRuntimeSink:
    def __init__(self, sink: Any, *, capacity: int = 128, latest_only: bool = False) -> None:
        if capacity < 1:
            raise ValueError('capacity must be positive')
        self.sink = sink
        self.capacity = 1 if latest_only else capacity
        self.latest_only = latest_only
        self._queue: deque[tuple[Any, Any]] = deque()
        self._condition = threading.Condition()
        self._closed = False
        self._inflight = False
        self._counts = dict(accepted=0, written=0, dropped=0, coalesced=0, failures=0)
        self._last_error: str | None = None
        self._write_ms = 0.0
        self._thread = threading.Thread(target=self._consume, name='asurada-sink', daemon=True)
        self._thread.start()

    def append(self, state: Any, decision: Any) -> bool:
        # Capture an owned snapshot before the producer mutates/reuses objects.
        item = deepcopy((state, decision))
        with self._condition:
            if self._closed:
                raise RuntimeError('sink_closed')
            if len(self._queue) >= self.capacity:
                if not self.latest_only:
                    self._counts['dropped'] += 1
                    return False
                self._queue.popleft()
                self._counts['coalesced'] += 1
            self._queue.append(item)
            self._counts['accepted'] += 1
            self._condition.notify()
            return True

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {**self._counts, 'queued':len(self._queue), 'inflight':self._inflight,
                    'capacity':self.capacity, 'closed':self._closed, 'worker_alive':self._thread.is_alive(),
                    'last_error':self._last_error, 'last_write_ms':self._write_ms}

    def close(self, timeout_s: float = 5.0) -> bool:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._thread.join(max(timeout_s, 0))
        return not self._thread.is_alive()

    def _consume(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if not self._queue:
                    return
                item = self._queue.popleft()
                self._inflight = True
            started = time.monotonic()
            error = None
            try:
                self.sink.append(*item)
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
            with self._condition:
                self._inflight = False
                self._write_ms = round((time.monotonic() - started)*1000, 3)
                if error is None:
                    self._counts['written'] += 1
                else:
                    self._counts['failures'] += 1
                    self._last_error = error
                self._condition.notify_all()
