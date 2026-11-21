"""Bounded diagnostics for datagrams rejected at the wire-decoder boundary."""
from collections import Counter

from .pdu_decoder import PacketDecodeError


class PacketDecodeDiagnostics:
    """Count known rejection reasons without retaining payloads or growing keys."""

    REASONS = frozenset({
        "short_header", "unsupported_format", "unsupported_version", "invalid_header",
        "size_mismatch", "invalid_car_index", "malformed_body",
    })

    def __init__(self) -> None:
        self.count = 0
        self.reasons: Counter[str] = Counter()
        self.last_error: str | None = None

    def record(self, error: PacketDecodeError) -> None:
        self.count += 1
        reason = error.reason if error.reason in self.REASONS else "malformed_body"
        self.reasons[reason] += 1
        self.last_error = str(error)[:512]

    def snapshot(self) -> dict:
        return {"count": self.count, "reasons": dict(self.reasons), "last_error": self.last_error}
