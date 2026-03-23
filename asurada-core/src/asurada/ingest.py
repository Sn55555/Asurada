from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path


class ReplaySource:
    """Reads normalized snapshots from a JSONL replay file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __iter__(self) -> Iterator[dict]:
        # 备注:
        # replay 输入已经是标准化快照，适合做快速回归和策略对比。
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)
