from __future__ import annotations

from collections import Counter
from typing import Callable

from .decode import decode_snapshot
from .output import ConsoleVoiceOutput
from .packet_snapshot import CaptureSnapshotAssembler
from .pdu_decoder import F125PacketDecoder, PacketDecodeError
from .replay import ReplayLogger
from .state import UnifiedStateStore
from .strategy import StrategyEngine
from .udp_ingest import UdpPacketSource


class LiveRuntime:
    """Real-time runtime shell wired into the main decode -> strategy chain."""

    def __init__(
        self,
        packet_source: UdpPacketSource,
        *,
        state_store: UnifiedStateStore,
        strategy: StrategyEngine,
        voice_output: ConsoleVoiceOutput,
        logger: ReplayLogger,
        dashboard_refresh: Callable[[], None] | None = None,
    ) -> None:
        self.packet_source = packet_source
        self.decoder = F125PacketDecoder()
        self.assembler = CaptureSnapshotAssembler()
        self.state_store = state_store
        self.strategy = strategy
        self.voice_output = voice_output
        self.logger = logger
        self.dashboard_refresh = dashboard_refresh

    def run(self) -> None:
        counter: Counter[str] = Counter()
        packet_count = 0
        snapshot_count = 0
        emitted_count = 0
        print("[ASURADA] Live UDP runtime started. Waiting for packets...")
        for packet in self.packet_source:
            try:
                envelope = self.decoder.decode_raw(packet)
            except PacketDecodeError as exc:
                print(f"[ASURADA][UDP] decode failed: {exc}")
                continue

            packet_count += 1
            counter[envelope.kind] += 1
            if envelope.kind == "Session":
                session_header = dict(envelope.payload.get("header", {}))
                session_body = dict(envelope.payload.get("body", {}))
                session_valid = self.assembler._is_session_valid(session_body)
                print(
                    "[ASURADA][UDP][session] "
                    f"session_uid={envelope.session_uid} valid={session_valid} "
                    f"byte_length={session_header.get('byte_length')} "
                    f"packet_version={session_header.get('packet_version')} "
                    f"track_id={session_body.get('track_id')} "
                    f"track_length_m={session_body.get('track_length_m')} "
                    f"session_type={session_body.get('session_type')} "
                    f"safety_car_status={session_body.get('safety_car_status')}"
                )
                print(
                    "[ASURADA][UDP][session-preview] "
                    f"{session_header.get('preview_hex')}"
                )
            normalized_snapshot = self.assembler.push(envelope)
            if normalized_snapshot is None:
                if packet_count % 500 == 0:
                    header = dict(envelope.payload.get("header", {}))
                    session_uid = str(envelope.session_uid or "unknown")
                    frame_identifier = header.get("frame_identifier")
                    bundle = None
                    missing_packets: list[str] = []
                    lap_valid = None
                    session_cached = session_uid in self.assembler.latest_session_by_uid
                    if frame_identifier is not None:
                        bundle = self.assembler.frames.get((session_uid, int(frame_identifier)))
                    if bundle is not None:
                        missing_packets = sorted(
                            self.assembler.REQUIRED_FRAME_PACKETS.difference(bundle.packets.keys())
                        )
                        if session_cached and not missing_packets:
                            lap_valid = self.assembler._is_lap_valid(
                                bundle,
                                self.assembler.latest_session_by_uid[session_uid],
                            )
                    top_kinds = ", ".join(
                        f"{kind}:{count}" for kind, count in counter.most_common(6)
                    )
                    print(
                        "[ASURADA][UDP][diag] "
                        f"packets={packet_count} snapshots={snapshot_count} "
                        f"latest_kind={envelope.kind} session_uid={session_uid} "
                        f"frame={frame_identifier} session_cached={session_cached} "
                        f"missing={missing_packets or ['none']} lap_valid={lap_valid} "
                        f"top_kinds={top_kinds}"
                    )
                continue

            snapshot_count += 1
            state = decode_snapshot(normalized_snapshot)
            self.state_store.update(state)
            decision = self.strategy.evaluate(state, self.state_store.recent(12))
            render_output = bool(decision.messages and decision.messages[0].priority >= 70)
            lifecycle = self.voice_output.emit(decision, render=render_output)
            event = (lifecycle or {}).get("event", {})
            if event.get("event_type") in {"start", "interrupt"}:
                emitted_count += 1
            self.logger.append(state, decision)

            if self.dashboard_refresh is not None and (snapshot_count == 1 or snapshot_count % 50 == 0):
                self.dashboard_refresh()

            if snapshot_count % 100 == 0:
                print(
                    "[ASURADA][UDP] "
                    f"snapshots={snapshot_count} emitted={emitted_count} "
                    f"latest_kind={envelope.kind} lap={state.lap_number} pos={state.player.position} "
                    f"speed={state.player.speed_kph:.0f} track={state.track}"
                )
