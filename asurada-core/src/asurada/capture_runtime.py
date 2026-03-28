from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import time
from typing import Callable

from .decode import decode_snapshot
from .capture_ingest import CaptureJsonlSource
from .output import ConsoleVoiceOutput
from .packet_snapshot import CaptureSnapshotAssembler
from .pdu_decoder import F125PacketDecoder, PacketDecodeError
from .replay import ReplayLogger
from .state import UnifiedStateStore
from .strategy import StrategyEngine


class CaptureReplayRuntime:
    """Replays raw UDP captures through the real decode pipeline.

    备注:
    这里的职责不是“再做一套策略逻辑”，而是把抓包完整送进
    decoder + assembler + state + strategy，并输出验证信息。
    """

    def __init__(
        self,
        capture_path: Path,
        *,
        state_store: UnifiedStateStore,
        strategy: StrategyEngine,
        voice_output: ConsoleVoiceOutput,
        logger: ReplayLogger,
        dashboard_refresh: Callable[[], None] | None = None,
        session_paced: bool = False,
        pace_multiplier: float = 1.0,
    ) -> None:
        self.capture_path = capture_path
        self.source = CaptureJsonlSource(capture_path)
        self.decoder = F125PacketDecoder()
        self.assembler = CaptureSnapshotAssembler()
        self.state_store = state_store
        self.strategy = strategy
        self.voice_output = voice_output
        self.logger = logger
        self.dashboard_refresh = dashboard_refresh
        self.session_paced = session_paced
        self.pace_multiplier = max(pace_multiplier, 0.1)

    def run(self) -> None:
        # 备注:
        # 这里做三件事:
        # 1. 统计抓包内容和正文样本，方便排查协议问题
        # 2. 把原始 packet 组装为标准化快照
        # 3. 复用主策略链路并按节流规则刷新 dashboard
        counter: Counter[str] = Counter()
        session_uid = None
        first_packets = []
        body_samples: dict[str, dict] = {}
        snapshot_count = 0
        emitted_count = 0
        previous_session_time_s: float | None = None

        for index, packet in enumerate(self.source, start=1):
            try:
                envelope = self.decoder.decode_raw(packet)
            except PacketDecodeError as exc:
                print(f"[ASURADA][CAPTURE] decode failed at packet {index}: {exc}")
                continue

            counter[envelope.kind] += 1
            if envelope.session_uid not in (None, "0", 0):
                session_uid = session_uid or str(envelope.session_uid)
            body_samples.setdefault(envelope.kind, envelope.payload.get("body", {}))
            if len(first_packets) < 8:
                header = envelope.payload.get("header", {})
                first_packets.append(
                    f"{index}. {envelope.kind} frame={envelope.frame_identifier} bytes={header.get('byte_length')}"
                )

            normalized_snapshot = self.assembler.push(envelope)
            if normalized_snapshot is None:
                continue

            snapshot_count += 1
            if self.session_paced:
                current_session_time_s = float(normalized_snapshot.get("session_time_s", 0.0))
                if previous_session_time_s is not None:
                    delta_s = max(current_session_time_s - previous_session_time_s, 0.0)
                    if delta_s > 0:
                        time.sleep(delta_s / self.pace_multiplier)
                previous_session_time_s = current_session_time_s
            state = decode_snapshot(normalized_snapshot)
            self.state_store.update(state)
            decision = self.strategy.evaluate(state, self.state_store.recent(12))
            render_output = bool(decision.messages and decision.messages[0].priority >= 70)
            lifecycle = self.voice_output.emit(decision, render=render_output)
            event = (lifecycle or {}).get("event", {})
            if event.get("event_type") in {"start", "interrupt"}:
                emitted_count += 1
            self.logger.append(state, decision)
            if self.dashboard_refresh is not None and snapshot_count % 500 == 0:
                # 备注:
                # dashboard 重建频率控制在 500 帧一次，避免回放期间
                # 频繁写 HTML 导致 IO 开销过高。
                self.dashboard_refresh()
        if self.dashboard_refresh is not None:
            self.dashboard_refresh()

        print(f"[ASURADA][CAPTURE] source={self.capture_path}")
        if self.session_paced:
            print(f"[ASURADA][CAPTURE] replay pacing=session_time_s x{self.pace_multiplier:.2f}")
        if self.state_store.latest is not None:
            session_uid = self.state_store.latest.session_uid
        print(f"[ASURADA][CAPTURE] session_uid={session_uid}")
        print(f"[ASURADA][CAPTURE] normalized snapshots={snapshot_count}")
        print(f"[ASURADA][CAPTURE] emitted strategy events={emitted_count}")
        print("[ASURADA][CAPTURE] first packets")
        for line in first_packets:
            print(f"  - {line}")
        print("[ASURADA][CAPTURE] packet counts")
        for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
            print(f"  - {name}: {count}")
        print("[ASURADA][CAPTURE] parsed body samples")
        for name in ["Session", "LapData", "CarTelemetry", "CarStatus", "CarDamage", "TyreSets", "Motion", "MotionEx", "Event", "LapPositions"]:
            if name not in body_samples:
                continue
            print(f"  - {name}: {body_samples[name]}")
        if self.state_store.latest is not None:
            latest = self.state_store.latest
            print("[ASURADA][CAPTURE] latest normalized state")
            print(
                "  - "
                f"track={latest.track}, lap={latest.lap_number}, pos={latest.player.position}, "
                f"speed={latest.player.speed_kph:.0f}, fuel_laps={latest.player.fuel_laps_remaining:.1f}, "
                f"ers={latest.player.ers_pct:.0f}, tags={latest.player.status_tags}"
            )
        summary_path = self.logger.directory / "capture_summary.json"
        decoded_kinds = sorted(name for name, sample in body_samples.items() if sample)
        unknown_kinds = sorted(name for name in counter if name.startswith("Unknown"))
        summary = {
            "source": str(self.capture_path),
            "session_uid": session_uid,
            "normalized_snapshots": snapshot_count,
            "emitted_strategy_events": emitted_count,
            "packet_counts": dict(sorted(counter.items())),
            "decoded_kinds": decoded_kinds,
            "unknown_kinds": unknown_kinds,
            "coverage": {
                "present_packet_kinds": len(counter),
                "decoded_packet_kinds": len(decoded_kinds),
                "unknown_packet_kinds": len(unknown_kinds),
            },
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ASURADA][CAPTURE] summary={summary_path}")
