"""Bounded receive queue; decoding and strategy never run on its producer."""

from .limits import INGRESS_QUEUE_CAPACITY
from collections import deque
from dataclasses import replace
import threading
import time


class BufferedPacketSource:
    def __init__(self, source, *, capacity=INGRESS_QUEUE_CAPACITY):
        if capacity < 1:
            raise ValueError('receive_capacity_must_be_positive')
        self.source, self.capacity = source, capacity
        self._queue = deque()
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread = None
        self._done = False
        self._error = None
        self._received = self._dropped = self._delivered = 0
        self._max_depth = 0

    def _receive(self):
        try:
            for packet in self.source:
                if self._stop.is_set():
                    break
                with self._condition:
                    self._received += 1
                    if len(self._queue) >= self.capacity:
                        self._queue.popleft()
                        self._dropped += 1
                    self._queue.append((packet, time.monotonic_ns()))
                    self._max_depth = max(self._max_depth, len(self._queue))
                    self._condition.notify()
        except Exception as exc:
            self._error = exc
        finally:
            with self._condition:
                self._done = True
                self._condition.notify_all()

    def __iter__(self):
        if self._thread is not None:
            raise RuntimeError('receive_source_is_single_use')
        self._thread = threading.Thread(target=self._receive, name='asurada-udp-receiver', daemon=True)
        self._thread.start()
        try:
            while True:
                with self._condition:
                    while not self._queue and not self._done and not self._stop.is_set():
                        self._condition.wait(.1)
                    if self._stop.is_set():
                        break
                    if not self._queue:
                        if self._error is not None:
                            raise self._error
                        break
                    packet, queued_at = self._queue.popleft()
                    self._delivered += 1
                    health = self._snapshot()
                yield replace(packet, received_monotonic_ns=packet.received_monotonic_ns or queued_at,
                              ingress_queue_ms=(time.monotonic_ns()-queued_at)/1_000_000,
                              ingress_health=health)
        finally:
            self.close()

    def _snapshot(self):
        return dict(received=self._received, delivered=self._delivered, dropped_oldest=self._dropped,
                    queued=len(self._queue), capacity=self.capacity, max_depth=self._max_depth,
                    done=self._done, error=str(self._error) if self._error else None)

    def snapshot(self):
        with self._condition:
            return self._snapshot()

    def close(self):
        self._stop.set()
        if hasattr(self.source, 'close'):
            self.source.close()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=1)
        return self._thread is None or not self._thread.is_alive()
