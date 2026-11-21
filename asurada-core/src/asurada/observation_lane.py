"""Sampled observation work with bounded ownership across live restarts."""
from __future__ import annotations

from concurrent.futures import Future
from copy import deepcopy
import time
from typing import Any, Callable

from .task_runtime import BoundedTaskExecutor, TaskContext, TaskCancelled


class ObservationLane:
    def __init__(self, *, interval_s: float = .2, result_ttl_s: float = 2,
                 timeout_ms: float = 5000) -> None:
        self.interval_s = max(interval_s, 0)
        self.result_ttl_s = max(result_ttl_s, 0)
        self.timeout_ms = timeout_ms
        self._executor = BoundedTaskExecutor(1)
        self._future: Future | None = None
        self._context: TaskContext | None = None
        self._submitted_at = float('-inf')
        self._latest = None
        self._scope = None
        self._counts = dict(submitted=0, busy_skipped=0, sample_skipped=0,
                            failed=0, cancelled=0)
        self._last_error = None
        self._closed = False

    def reopen(self) -> None:
        # Keep the same worker slot: an uncooperative old model must finish
        # before a new live run can submit another inference on that runtime.
        self._closed = False
        self._latest = None
        self._scope = None
        self._submitted_at = float('-inf')

    def _collect(self) -> None:
        if self._future is None or not self._future.done():
            return
        try:
            self._latest = self._future.result()
        except TaskCancelled:
            self._counts['cancelled'] += 1
        except Exception as exc:
            self._counts['failed'] += 1
            self._last_error = f'{type(exc).__name__}: {exc}'
        self._future = None
        self._context = None

    def offer(self, *, binding: dict[str, Any],
              build_work: Callable[[TaskContext], Callable]) -> dict[str, Any]:
        scope = (binding['session_uid'], binding['epoch'])
        if scope != self._scope:
            if self._context is not None:
                self._context.cancel()
            self._latest = None
            self._scope = scope
        self._collect()
        now = time.monotonic()
        if not self._closed:
            if self._future is not None:
                self._counts['busy_skipped'] += 1
            elif now - self._submitted_at < self.interval_s:
                self._counts['sample_skipped'] += 1
            else:
                context = TaskContext.start(f"observe:{binding['snapshot_id']}", self.timeout_ms)
                try:
                    owned_binding = deepcopy(binding)
                    work = build_work(context)
                    def run():
                        return {'binding': owned_binding, 'results': work(),
                                'submitted_monotonic': now}
                    self._future = self._executor.submit(context, run)
                    self._context = context
                    self._submitted_at = now
                    self._counts['submitted'] += 1
                except Exception as exc:
                    self._counts['failed'] += 1
                    self._last_error = f'{type(exc).__name__}: {exc}'
        latest = self._latest
        if latest is not None:
            if ((latest['binding']['session_uid'], latest['binding']['epoch']) != scope
                    or now - latest['submitted_monotonic'] > self.result_ttl_s):
                latest = None
        return {'counts': dict(self._counts), 'inflight': self._future is not None,
                'latest': deepcopy(latest), 'last_error': self._last_error,
                'closed': self._closed}

    def close(self) -> bool:
        self._closed = True
        self._latest = None
        if self._context is not None:
            self._context.cancel()
        self._collect()
        return self._future is None
