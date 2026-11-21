from __future__ import annotations

from collections import deque

from .models import SessionState
from .session_lifecycle import SessionLifecycle, SessionTransition


class UnifiedStateStore:
    """Keeps the latest snapshot plus a short rolling history."""

    def __init__(self, maxlen: int = 120) -> None:
        self._history: deque[SessionState] = deque(maxlen=maxlen)
        self.lifecycle = SessionLifecycle()
        self.last_transition: SessionTransition | None = None
        self.latest: SessionState | None = None
        self._session_event: dict | None = None

    def update(self, state: SessionState) -> bool:
        self.last_transition = self.lifecycle.observe(state)
        if not self.last_transition.accepted:
            return False
        if self.last_transition.changed:
            self._history.clear()
            self._session_event = {
                'contract_version': 'session-event-v1',
                'type': 'telemetry_scope_changed',
                'reason': self.last_transition.reason,
                'session_uid': str(state.session_uid),
                'session_epoch': state.session_epoch,
                'source_timestamp_ms': state.source_timestamp_ms,
                'previous': None if self.latest is None else {
                    'session_uid': str(self.latest.session_uid),
                    'session_epoch': self.latest.session_epoch},
            }
        state.session_event = self._session_event
        self.latest = state
        self._history.append(state)
        return True

    def recent_seconds(self, seconds: float) -> list[SessionState]:
        """Window in source receive time, suitable for live and recorded replay."""
        if self.latest is None or seconds <= 0:
            return []
        cutoff = self.latest.source_timestamp_ms - seconds * 1000
        return [state for state in self._history if cutoff <= state.source_timestamp_ms <= self.latest.source_timestamp_ms]

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
