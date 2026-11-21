from __future__ import annotations

import socket
import time
import threading
from collections.abc import Iterator

from .config import UdpConfig
from .pdu import RawPacket


class UdpPacketSource:
    """Low-level UDP source for future F1 25 packet ingest."""

    def __init__(self, config: UdpConfig) -> None:
        self.config = config
        self._stop = threading.Event()

    def __iter__(self) -> Iterator[RawPacket]:
        # 备注:
        # 这里保持最薄的一层 socket 包装，协议解析和业务容错都留给上游 runtime。
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.config.host, self.config.port))
            sock.settimeout(min(max(self.config.receive_timeout_s, .01), .2))
            while not self._stop.is_set():
                try:
                    payload, address = sock.recvfrom(self.config.buffer_size)
                except socket.timeout:
                    continue
                yield RawPacket(
                    received_at_ms=int(time.time() * 1000),
                    received_monotonic_ns=time.monotonic_ns(),
                    payload=payload,
                    source_host=address[0],
                    source_port=address[1],
                )
        finally:
            sock.close()

    def close(self) -> None:
        self._stop.set()
