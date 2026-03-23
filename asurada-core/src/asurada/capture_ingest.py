from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from pathlib import Path

from .pdu import RawPacket


class CaptureJsonlSource:
    """Reads raw UDP packets from the PC capture JSONL format."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __iter__(self) -> Iterator[RawPacket]:
        # 备注:
        # capture 文件保持最原始的 packet 粒度，这里只负责 base64 解包，
        # 不做任何协议层解释。
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                yield RawPacket(
                    received_at_ms=int(record["received_at_ms"]),
                    payload=base64.b64decode(record["payload_base64"]),
                    source_host=str(record["source_host"]),
                    source_port=int(record["source_port"]),
                )
