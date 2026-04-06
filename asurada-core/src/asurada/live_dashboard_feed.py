from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .live_dashboard_payload import build_dashboard_payload, placeholder_dashboard_payload
from .models import SessionState, StrategyDecision


class CompositeRuntimeLogger:
    """Fan out runtime append/reset events to multiple sinks."""

    def __init__(self, *sinks: Any) -> None:
        self.sinks = [sink for sink in sinks if sink is not None]

    def reset(self) -> None:
        for sink in self.sinks:
            sink.reset()

    def append(self, state: SessionState, decision: StrategyDecision) -> None:
        for sink in self.sinks:
            sink.append(state, decision)


class DashboardFeedWriter:
    """Write the latest live dashboard payload for external consumers."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "live_payload.json"

    def reset(self) -> None:
        self._write_payload(placeholder_dashboard_payload())

    def append(self, state: SessionState, decision: StrategyDecision) -> None:
        self._write_payload(build_dashboard_payload(state, decision))

    def _write_payload(self, payload: dict[str, Any]) -> None:
        temp_path = self.path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(self.path)
