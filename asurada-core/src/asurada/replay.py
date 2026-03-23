from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import SessionState, StrategyDecision


class ReplayLogger:
    """Append-only JSONL runtime log.

    备注:
    session_log.jsonl 是 dashboard、回放调试和后续分析的共同输入，
    所以这里保留 state + messages + debug 三层信息，不只写最终播报。
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "session_log.jsonl"

    def reset(self) -> None:
        # 备注:
        # 每次运行前清空日志，避免把不同会话混在同一份 dashboard 数据里。
        self.path.write_text("", encoding="utf-8")

    def append(self, state: SessionState, decision: StrategyDecision) -> None:
        payload = {
            "session_uid": state.session_uid,
            "lap_number": state.lap_number,
            "track": state.track,
            "player": asdict(state.player),
            "rivals": [asdict(item) for item in state.rivals],
            "raw": state.raw,
            "messages": [asdict(item) for item in decision.messages],
            "debug": decision.debug,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
