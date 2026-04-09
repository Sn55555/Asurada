from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
from typing import Any

from .models import SessionState


_STANDBY_TRACKS = frozenset({"", "standby", "unknown", "n/a"})


@dataclass(frozen=True)
class RuntimeContext:
    mode: str
    racing_active: bool
    stale_snapshot: bool
    snapshot_age_ms: int | None
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeContextDetector:
    def __init__(self, *, stale_after_ms: int = 15_000) -> None:
        self.stale_after_ms = max(int(stale_after_ms), 1)

    def detect(self, *, state: SessionState, now_ms: int | None = None) -> RuntimeContext:
        current_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        source_timestamp_ms = _coerce_int(state.source_timestamp_ms)
        snapshot_age_ms = None
        if source_timestamp_ms is not None and source_timestamp_ms > 0:
            snapshot_age_ms = max(current_ms - source_timestamp_ms, 0)

        track = str(state.track or "").strip()
        track_key = track.lower()
        has_live_laps = int(state.total_laps or 0) > 0 and int(state.lap_number or 0) > 0
        has_player_position = int(getattr(state.player, "position", 0) or 0) > 0
        stale_snapshot = snapshot_age_ms is None or snapshot_age_ms > self.stale_after_ms

        if track_key in _STANDBY_TRACKS:
            return RuntimeContext(
                mode="companion",
                racing_active=False,
                stale_snapshot=stale_snapshot,
                snapshot_age_ms=snapshot_age_ms,
                reason="standby_track",
                metadata=self._metadata(
                    state=state,
                    source_timestamp_ms=source_timestamp_ms,
                ),
            )
        if not has_live_laps:
            return RuntimeContext(
                mode="companion",
                racing_active=False,
                stale_snapshot=stale_snapshot,
                snapshot_age_ms=snapshot_age_ms,
                reason="missing_live_lap_context",
                metadata=self._metadata(
                    state=state,
                    source_timestamp_ms=source_timestamp_ms,
                ),
            )
        if not has_player_position:
            return RuntimeContext(
                mode="companion",
                racing_active=False,
                stale_snapshot=stale_snapshot,
                snapshot_age_ms=snapshot_age_ms,
                reason="missing_player_position",
                metadata=self._metadata(
                    state=state,
                    source_timestamp_ms=source_timestamp_ms,
                ),
            )
        if stale_snapshot:
            return RuntimeContext(
                mode="companion",
                racing_active=False,
                stale_snapshot=True,
                snapshot_age_ms=snapshot_age_ms,
                reason="stale_snapshot",
                metadata=self._metadata(
                    state=state,
                    source_timestamp_ms=source_timestamp_ms,
                ),
            )
        return RuntimeContext(
            mode="racing",
            racing_active=True,
            stale_snapshot=False,
            snapshot_age_ms=snapshot_age_ms,
            reason="fresh_race_snapshot",
            metadata=self._metadata(
                state=state,
                source_timestamp_ms=source_timestamp_ms,
            ),
        )

    def _metadata(
        self,
        *,
        state: SessionState,
        source_timestamp_ms: int | None,
    ) -> dict[str, Any]:
        return {
            "track": state.track,
            "lap_number": state.lap_number,
            "total_laps": state.total_laps,
            "player_position": getattr(state.player, "position", None),
            "source_timestamp_ms": source_timestamp_ms,
            "stale_after_ms": self.stale_after_ms,
        }


def _coerce_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None
