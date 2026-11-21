"""Packet-level rewind boundary; ordinary within-epoch reordering is allowed."""
from __future__ import annotations
from dataclasses import dataclass
from .frame_counter import newer, older


def counter(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0xffffffff else None


@dataclass
class PacketEpoch:
    epoch: int = 0
    overall: int | None = None
    frame: int | None = None
    floor: int | None = None

    def observe(self, header):
        overall = counter(header.get('overall_frame_identifier'))
        frame = counter(header.get('frame_identifier'))
        if overall is None or frame is None:
            return True, False
        if self.floor is not None and older(overall, self.floor):
            return False, False
        changed = False
        if self.overall is None or newer(overall, self.overall):
            if self.frame is not None and older(frame, self.frame):
                self.epoch += 1
                self.floor = overall
                changed = True
            self.overall, self.frame = overall, frame
        return True, changed
