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
    received_monotonic_ns: int | None = None
    capture_submission_id: int | None = None
    ingress_queue_ms: float | None = None
    ingress_health: dict[str, Any] | None = None


@dataclass
class PacketEnvelope:
    """Decoded packet header/body wrapper used by the assembler."""

    kind: str
    frame_identifier: int | None
    session_uid: str | None
    payload: dict[str, Any]
