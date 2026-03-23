from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RawPacket:
    """Raw UDP datagram plus receive metadata."""

    received_at_ms: int
    payload: bytes
    source_host: str
    source_port: int


@dataclass
class PacketEnvelope:
    """Decoded packet header/body wrapper used by the assembler."""

    kind: str
    frame_identifier: int | None
    session_uid: str | None
    payload: dict[str, Any]
