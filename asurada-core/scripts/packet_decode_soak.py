"""Low-load, timed malformed-datagram injection through the live runtime.

This is an offline synthetic ingestion soak: no UDP socket, game, microphone,
voice playback or model activation. Progress is atomically published for review.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from asurada.capture_ingest import CaptureJsonlSource
from asurada.config import StrategyThresholds
from asurada.live_runtime import LiveRuntime
from asurada.model_admission import MODEL_NAMES, ModelAdmissionPolicy
from asurada.pdu import RawPacket
from asurada.pdu_decoder import F125PacketDecoder
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine


def run(duration_s: float, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    fixture = list(CaptureJsonlSource(ROOT / 'data/capture_samples/f1_25_udp_frame_fixture.jsonl'))
    clock_start = time.monotonic()
    progress = {'cycles': 0, 'generated_bad_packets': 0, 'generated_good_packets': 0, 'snapshots': 0}
    runtime = None

    def publish(status, error=None):
        elapsed = time.monotonic() - clock_start
        observed = runtime.decode_diagnostics.snapshot() if runtime else {}
        passed = status == 'complete' and elapsed >= duration_s and (
            observed.get('count') == progress['generated_bad_packets']
            and progress['snapshots'] > 0 and progress['cycles'] > 0)
        report = dict(status=status, passed=passed, duration_requested_s=duration_s, elapsed_s=round(elapsed, 3),
            progress=progress, decode_diagnostics=observed, error=error,
            scope='offline fault injection through LiveRuntime; no real UDP/audio',
            cadence_s=0.5)
        temporary = output / 'summary.json.tmp'
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        temporary.replace(output / 'summary.json')
        return passed

    def source():
        next_tick = clock_start
        while time.monotonic() - clock_start < duration_s:
            cycle = progress['cycles']
            now_ms = time.time_ns() // 1_000_000
            for packet_id, size in F125PacketDecoder.PACKET_SIZES.items():
                header = struct.pack(F125PacketDecoder.HEADER_FORMAT, 2025, 25, 1, 0, 1, packet_id, 100, 1., 1, 1, 0, 255)
                full = header + bytes(size - len(header))
                for length in (29, size // 2, size - 1):
                    progress['generated_bad_packets'] += 1
                    yield RawPacket(now_ms, full[:length], 'offline-soak', 1)
            for packet in fixture:
                data = bytearray(packet.payload)
                header = list(struct.unpack_from(F125PacketDecoder.HEADER_FORMAT, data))
                header[7] += cycle * .5
                header[8] += cycle
                header[9] += cycle
                struct.pack_into(F125PacketDecoder.HEADER_FORMAT, data, 0, *header)
                progress['generated_good_packets'] += 1
                yield RawPacket(now_ms, bytes(data), 'offline-soak', 1)
            progress['cycles'] += 1
            if progress['cycles'] % 20 == 0:
                publish('running')
            next_tick += .5
            time.sleep(max(0., min(next_tick - time.monotonic(), duration_s - (time.monotonic() - clock_start))))

    def recorded_snapshot(*args):
        progress['snapshots'] += 1

    runtime = LiveRuntime(source(), state_store=UnifiedStateStore(), strategy=StrategyEngine(
        StrategyThresholds(), model_policy=ModelAdmissionPolicy(modes={name: 'disabled' for name in MODEL_NAMES})),
        voice_output=SimpleNamespace(emit=lambda *a, **k: {}), logger=SimpleNamespace(append=recorded_snapshot))
    publish('running')
    try:
        runtime.run()
    except BaseException as exc:
        publish('interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', repr(exc))
        raise
    return 0 if publish('complete') else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration-s', type=float, default=1800.)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.duration_s <= 0:
        parser.error('--duration-s must be positive')
    raise SystemExit(run(args.duration_s, args.output.resolve()))
