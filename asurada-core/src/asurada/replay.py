from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import SessionState, StrategyDecision
from .snapshot_contract import snapshot_payload


class ReplayLogger:
    """Append-only JSONL runtime log.

    备注:
    session_log.jsonl 是 dashboard、回放调试和后续分析的共同输入，
    所以这里保留 state + messages + debug 三层信息，不只写最终播报。
    """

    def __init__(self, directory: Path, *, max_bytes: int = 16 * 1024 * 1024,
                 max_archives: int | None = None) -> None:
        if max_archives is not None and (type(max_archives) is not int or max_archives < 0):
            raise ValueError("max_archives must be a nonnegative integer or None")
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "session_log.jsonl"
        self.max_bytes = max_bytes
        self.max_archives = max_archives

    def reset(self) -> None:
        # 备注:
        # 每次运行前清空日志，避免把不同会话混在同一份 dashboard 数据里。
        self.path.write_text("", encoding="utf-8")
        (self.directory / "latest_snapshot.json").unlink(missing_ok=True)

    def append(self, state: SessionState, decision: StrategyDecision) -> None:
        self._rotate_if_needed()
        payload = snapshot_payload(state, decision)
        payload["debug"] = decision.debug
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
        if self.max_archives is not None:
            archives = [p for p in self.directory.iterdir()
                        if re.fullmatch(r"session_log\.\d{8}_\d{6}(?:_\d+)?\.jsonl", p.name)
                        and p.is_file() and not p.is_symlink()]
            archives.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
            for old in archives[self.max_archives:]:
                old.unlink()
