from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import SessionState, StrategyDecision


class ReplayLogger:
    """Append-only JSONL runtime log.

    备注:
    session_log.jsonl 是 dashboard、回放调试和后续分析的共同输入，
    所以这里保留 state + messages + debug 三层信息，不只写最终播报。
    """

    def __init__(self, directory: Path, *, max_bytes: int = 16 * 1024 * 1024) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "session_log.jsonl"
        self.max_bytes = max_bytes

    def reset(self) -> None:
        # 备注:
        # 每次运行前清空日志，避免把不同会话混在同一份 dashboard 数据里。
        self.path.write_text("", encoding="utf-8")

    def append(self, state: SessionState, decision: StrategyDecision) -> None:
        self._rotate_if_needed()
        payload = {
            "session_uid": state.session_uid,
            "lap_number": state.lap_number,
            "track": state.track,
            "total_laps": state.total_laps,
            "weather": state.weather,
            "safety_car": state.safety_car,
            "source_timestamp_ms": state.source_timestamp_ms,
            "player": asdict(state.player),
            "rivals": [asdict(item) for item in state.rivals],
            "raw": state.raw,
            "messages": [asdict(item) for item in decision.messages],
            "debug": decision.debug,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _rotate_if_needed(self) -> None:
        if self.max_bytes <= 0 or not self.path.exists():
            return
        if self.path.stat().st_size < self.max_bytes:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = self.directory / f"session_log.{timestamp}.jsonl"
        suffix = 1
        while archive_path.exists():
            archive_path = self.directory / f"session_log.{timestamp}_{suffix:02d}.jsonl"
            suffix += 1
        self.path.rename(archive_path)
        self.path.write_text("", encoding="utf-8")
