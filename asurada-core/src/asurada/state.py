from __future__ import annotations

from collections import deque

from .models import SessionState


class UnifiedStateStore:
    """Keeps the latest snapshot plus a short rolling history."""

    def __init__(self, maxlen: int = 120) -> None:
        self._history: deque[SessionState] = deque(maxlen=maxlen)
        self.latest: SessionState | None = None

    def update(self, state: SessionState) -> None:
        # 备注:
        # 状态仓只维护短窗口历史，给趋势、上下文和回放调试使用，
        # 不承担长期存储职责。
        self.latest = state
        self._history.append(state)

    def history(self) -> list[SessionState]:
        """Return the full in-memory rolling history."""
        return list(self._history)

    def previous(self) -> SessionState | None:
        """Return the previous frame if available."""
        if len(self._history) < 2:
            return None
        return self._history[-2]

    def recent(self, count: int) -> list[SessionState]:
        """Return the latest N frames from the rolling window."""
        if count <= 0:
            return []
        return list(self._history)[-count:]
