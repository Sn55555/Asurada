from __future__ import annotations

from .context_window import CONTEXT_WINDOW_SECONDS

import time
from dataclasses import asdict, dataclass
from typing import Any

from .decode import decode_snapshot
from .grid_feed import GridPlanFeed
from .output import ConsoleVoiceOutput
from .packet_snapshot import CaptureSnapshotAssembler
from .pdu import RawPacket
from .personality_runtime import PersonalityRuntime
from .pdu_decoder import F125PacketDecoder, PacketDecodeError, PacketEnvelope
from .state import UnifiedStateStore
from .strategy import StrategyEngine


@dataclass
class PipelineStepResult:
    envelope: PacketEnvelope
    normalized_snapshot: dict[str, Any] | None
    emitted: bool = False
    submitted: bool = False


class StrategyRuntimePipeline:
    """Shared live/capture packet -> state -> strategy pipeline."""

    def __init__(
        self,
        *,
        state_store: UnifiedStateStore,
        strategy: StrategyEngine,
        voice_output: ConsoleVoiceOutput,
        logger: Any,
        personality: PersonalityRuntime | None = None,
        replay: bool = False,
    ) -> None:
        self.decoder = F125PacketDecoder()
        self.assembler = CaptureSnapshotAssembler()
        self.grid_feed = GridPlanFeed()
        self.state_store = state_store
        self.strategy = strategy
        self.voice_output = voice_output
        self.logger = logger
        self.personality = personality
        self.replay = replay

    def ingest_packet(self, packet: RawPacket) -> PipelineStepResult:
        wall_started_ms = time.time_ns() // 1_000_000
        decode_started_ns = time.monotonic_ns()
        def wall_ms(value):
            return wall_started_ms + (value - decode_started_ns) // 1_000_000
        envelope = self.decoder.decode_raw(packet)
        decode_finished_ns = time.monotonic_ns()

        normalized_snapshot = self.assembler.push(envelope)
        self.grid_feed.observe(envelope, self.assembler)
        if (self.personality is not None and self.assembler.accepted_epoch is not None
                and (envelope.kind in {"Event", "FinalClassification"} or
                     (envelope.kind == "LapData" and envelope.payload["body"].get("result_status") == 3))):
            self.personality.observe_packet(envelope, self.assembler.accepted_epoch, replay=self.replay)
        if normalized_snapshot is None:
            return PipelineStepResult(envelope=envelope, normalized_snapshot=None, emitted=False)

        snapshot_ready_ns = time.monotonic_ns()
        state = decode_snapshot(normalized_snapshot)
        if not self.state_store.update(state):
            return PipelineStepResult(envelope=envelope, normalized_snapshot=None, emitted=False)

        strategy_started_ns = time.monotonic_ns()
        decision = self.strategy.evaluate(state, self.state_store.recent_seconds(CONTEXT_WINDOW_SECONDS))
        self.grid_feed.annotate(state, decision)
        strategy_finished_ns = time.monotonic_ns()

        if self.personality is not None:
            state.personality = self.personality.observe_snapshot(state, decision, replay=self.replay)
            if state.personality is not None:
                decision.debug["personality"] = asdict(state.personality)
        render_output = bool(decision.messages and decision.messages[0].priority >= 70)
        lifecycle = self.voice_output.emit(decision, state=state, render=render_output)
        output_finished_ns = time.monotonic_ns()

        decision.debug["runtime_timing"] = {
            "duration_clock": "monotonic",
            "ingress_queue_ms": packet.ingress_queue_ms,
            "ingress_health": packet.ingress_health,
            "receive_to_output_submission_ms": (self._delta_ms(packet.received_monotonic_ns, output_finished_ns)
                                                   if packet.received_monotonic_ns is not None else None),
            "source_received_at_ms": int(packet.received_at_ms),
            "state_source_timestamp_ms": int(state.source_timestamp_ms),
            "pipeline_started_at_ms": wall_ms(decode_started_ns),
            "decode_started_at_ms": wall_ms(decode_started_ns),
            "decode_finished_at_ms": wall_ms(decode_finished_ns),
            "snapshot_ready_at_ms": wall_ms(snapshot_ready_ns),
            "strategy_started_at_ms": wall_ms(strategy_started_ns),
            "strategy_finished_at_ms": wall_ms(strategy_finished_ns),
            "output_finished_at_ms": wall_ms(output_finished_ns),
            "decode_latency_ms": self._delta_ms(decode_started_ns, decode_finished_ns),
            "assemble_latency_ms": self._delta_ms(decode_finished_ns, snapshot_ready_ns),
            "strategy_latency_ms": self._delta_ms(strategy_started_ns, strategy_finished_ns),
            "output_latency_ms": self._delta_ms(strategy_finished_ns, output_finished_ns),
            "pipeline_latency_ms": self._delta_ms(decode_started_ns, output_finished_ns),
        }
        if hasattr(self.logger, "snapshot"):
            decision.debug["sink_health_before_append"] = self.logger.snapshot()
        self.logger.append(state, decision)

        event = (lifecycle or {}).get("event", {})
        emitted = event.get("event_type") == "start"
        return PipelineStepResult(
            envelope=envelope,
            normalized_snapshot=normalized_snapshot,
            emitted=bool(emitted),
            submitted=event.get("event_type") == "submission_accepted",
        )

    def _delta_ms(self, start_ns: int, end_ns: int) -> float:
        return round(max(end_ns - start_ns, 0) / 1_000_000.0, 3)

    def _ns_to_ms(self, value_ns: int) -> int:
        return int(value_ns // 1_000_000)
