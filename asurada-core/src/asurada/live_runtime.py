from __future__ import annotations

from .pdu_decoder import F125PacketDecoder, PacketDecodeError
from .udp_ingest import UdpPacketSource


class LiveRuntime:
    """Real-time runtime shell for future packet-driven operation."""

    def __init__(self, packet_source: UdpPacketSource) -> None:
        self.packet_source = packet_source
        self.decoder = F125PacketDecoder()

    def run(self) -> None:
        # 备注:
        # 这里当前只做“收包 + 基础解码预览”，还没有接入完整状态仓与策略链。
        # 真正实时闭环会沿用 capture replay 那套标准化路径。
        print("[ASURADA] Live UDP runtime started. Waiting for packets...")
        for packet in self.packet_source:
            try:
                envelope = self.decoder.decode_raw(packet)
            except PacketDecodeError as exc:
                print(f"[ASURADA][UDP] decode failed: {exc}")
                continue

            print(
                "[ASURADA][UDP] "
                f"kind={envelope.kind} bytes={envelope.payload.get('byte_length')} "
                f"preview={envelope.payload.get('preview_hex')}"
            )
