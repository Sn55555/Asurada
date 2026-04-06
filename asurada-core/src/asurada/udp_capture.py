from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

from .pdu import RawPacket


class RawPacketCaptureRecorder:
    """Append raw UDP packets to a JSONL capture file compatible with CaptureJsonlSource."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sequence_id = 0

    @classmethod
    def default_path(cls, directory: Path) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return directory / f"live_udp_capture_{timestamp}.jsonl"

    def reset(self) -> None:
        self.path.write_text("", encoding="utf-8")
        self._sequence_id = 0

    def append(self, packet: RawPacket) -> None:
        self._sequence_id += 1
        received_at_ms = int(packet.received_at_ms)
        payload = packet.payload
        record = {
            "sequence_id": self._sequence_id,
            "received_at_ms": received_at_ms,
            "received_at_utc": datetime.fromtimestamp(received_at_ms / 1000.0, tz=timezone.utc).isoformat(),
            "source_host": packet.source_host,
            "source_port": packet.source_port,
            "byte_length": len(payload),
            "preview_hex": payload[:16].hex(),
            "payload_base64": base64.b64encode(payload).decode("ascii"),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
