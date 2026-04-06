from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .decode import decode_snapshot
from .output import ConsoleVoiceOutput
from .packet_snapshot import CaptureSnapshotAssembler
from .pdu import RawPacket
from .pdu_decoder import F125PacketDecoder, PacketDecodeError, PacketEnvelope
from .state import UnifiedStateStore
from .strategy import StrategyEngine


@dataclass
class PipelineStepResult:
    envelope: PacketEnvelope
    normalized_snapshot: dict[str, Any] | None
    emitted: bool = False


class StrategyRuntimePipeline:
    """Shared live/capture packet -> state -> strategy pipeline."""

    def __init__(
        self,
        *,
        state_store: UnifiedStateStore,
        strategy: StrategyEngine,
        voice_output: ConsoleVoiceOutput,
        logger: Any,
    ) -> None:
        self.decoder = F125PacketDecoder()
        self.assembler = CaptureSnapshotAssembler()
        self.state_store = state_store
        self.strategy = strategy
        self.voice_output = voice_output
        self.logger = logger

    def ingest_packet(self, packet: RawPacket) -> PipelineStepResult:
        decode_started_ns = time.time_ns()
        envelope = self.decoder.decode_raw(packet)
        decode_finished_ns = time.time_ns()

        normalized_snapshot = self.assembler.push(envelope)
        if normalized_snapshot is None:
            return PipelineStepResult(envelope=envelope, normalized_snapshot=None, emitted=False)

        snapshot_ready_ns = time.time_ns()
        state = decode_snapshot(normalized_snapshot)
        self.state_store.update(state)

        strategy_started_ns = time.time_ns()
        decision = self.strategy.evaluate(state, self.state_store.recent(12))
        strategy_finished_ns = time.time_ns()

        render_output = bool(decision.messages and decision.messages[0].priority >= 70)
        lifecycle = self.voice_output.emit(decision, render=render_output)
        output_finished_ns = time.time_ns()

        decision.debug["runtime_timing"] = {
            "source_received_at_ms": int(packet.received_at_ms),
            "state_source_timestamp_ms": int(state.source_timestamp_ms),
            "pipeline_started_at_ms": self._ns_to_ms(decode_started_ns),
            "decode_started_at_ms": self._ns_to_ms(decode_started_ns),
            "decode_finished_at_ms": self._ns_to_ms(decode_finished_ns),
            "snapshot_ready_at_ms": self._ns_to_ms(snapshot_ready_ns),
            "strategy_started_at_ms": self._ns_to_ms(strategy_started_ns),
            "strategy_finished_at_ms": self._ns_to_ms(strategy_finished_ns),
            "output_finished_at_ms": self._ns_to_ms(output_finished_ns),
            "decode_latency_ms": self._delta_ms(decode_started_ns, decode_finished_ns),
            "assemble_latency_ms": self._delta_ms(decode_finished_ns, snapshot_ready_ns),
            "strategy_latency_ms": self._delta_ms(strategy_started_ns, strategy_finished_ns),
            "output_latency_ms": self._delta_ms(strategy_finished_ns, output_finished_ns),
            "pipeline_latency_ms": self._delta_ms(decode_started_ns, output_finished_ns),
        }
        self.logger.append(state, decision)

        event = (lifecycle or {}).get("event", {})
        emitted = event.get("event_type") == "start"
        return PipelineStepResult(
            envelope=envelope,
            normalized_snapshot=normalized_snapshot,
            emitted=bool(emitted),
        )

    def _delta_ms(self, start_ns: int, end_ns: int) -> float:
        return round(max(end_ns - start_ns, 0) / 1_000_000.0, 3)

    def _ns_to_ms(self, value_ns: int) -> int:
        return int(value_ns // 1_000_000)
