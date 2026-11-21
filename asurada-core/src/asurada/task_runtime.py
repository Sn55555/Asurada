"""Deadline and cancellation boundaries for blocking, untrusted-duration work.

Workers are bounded even after callers time out. Python cannot kill a running
thread: its capacity remains occupied until the backend actually exits.
"""
from __future__ import annotations

from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class TaskCancelled(Exception):
    pass


class TaskCapacityExceeded(Exception):
    pass


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    deadline: float
    cancellation: threading.Event = field(default_factory=threading.Event, repr=False)

    @classmethod
    def start(cls, task_id: str, timeout_ms: float) -> "TaskContext":
        return cls(task_id, time.monotonic() + max(timeout_ms, 0) / 1000)

    def cancel(self) -> None:
        self.cancellation.set()

    def remaining(self) -> float:
        if self.cancellation.is_set():
            raise TaskCancelled(self.task_id)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(self.task_id)
        return remaining

    def wait(self, future: Future[T]) -> T:
        while True:
            remaining = self.remaining()
            try:
                result = future.result(timeout=min(remaining, 0.01))
            except FutureTimeout:
                if future.done():
                    raise  # backend itself raised TimeoutError
                continue
            self.remaining()  # Never deliver a cancelled or late result.
            return result


class BoundedTaskExecutor:
    """No pending queue; overload fails immediately instead of growing threads."""

    def __init__(self, max_workers: int = 2) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._slots = threading.BoundedSemaphore(max_workers)

    def submit(self, context: TaskContext, function: Callable[[], T]) -> Future[T]:
        context.remaining()
        if not self._slots.acquire(blocking=False):
            raise TaskCapacityExceeded(context.task_id)
        future: Future[T] = Future()

        def execute() -> None:
            try:
                if future.set_running_or_notify_cancel():
                    context.remaining()
                    result = function()
                    context.remaining()
                    future.set_result(result)
            except BaseException as exc:
                future.set_exception(exc)
            finally:
                self._slots.release()

        try:
            threading.Thread(target=execute, name="asurada-task", daemon=True).start()
        except BaseException:
            self._slots.release()
            raise
        return future


# A process-wide limit also bounds concurrent requests from the sidecar server.
LLM_EXECUTOR = BoundedTaskExecutor(max_workers=2)
