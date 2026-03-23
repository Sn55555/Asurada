from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from asurada.capture_ingest import CaptureJsonlSource
from asurada.config import AppConfig
from asurada.dashboard import DebugDashboardBuilder
from asurada.decode import decode_snapshot
from asurada.output import ConsoleVoiceOutput
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu_decoder import F125PacketDecoder, PacketDecodeError
from asurada.replay import ReplayLogger
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine


class SilentVoiceOutput(ConsoleVoiceOutput):
    """Mute console strategy output during regression runs.

    备注:
    回归脚本只关心结果是否满足断言，不需要把策略播报刷满终端。
    """

    def emit(self, decision) -> None:  # noqa: D401
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run phase-one offline regression checks.")
    parser.add_argument(
        "--capture-jsonl",
        type=Path,
        default=Path("/Users/sn5/Asurada/tools/captures/f1_25_udp_capture_20260321_024707.jsonl"),
        help="Path to the captured UDP JSONL sample.",
    )
    parser.add_argument(
        "--snapshot-limit",
        type=int,
        default=1200,
        help="Stop after this many normalized snapshots have been produced.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("/Users/sn5/Asurada/asurada-core/runtime_logs/regression/latest_phase1_regression.json"),
        help="Where to write the regression summary JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_regression(args.capture_jsonl, args.snapshot_limit)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ASURADA][REGRESSION] report={args.report_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def run_regression(capture_path: Path, snapshot_limit: int) -> dict:
    required_packet_kinds = {
        "Session",
        "LapData",
        "CarTelemetry",
        "CarStatus",
        "CarDamage",
        "Motion",
        "MotionEx",
        "Participants",
        "TyreSets",
        "Event",
    }
    counter: Counter[str] = Counter()
    snapshot_count = 0
    last_debug: dict = {}
    latest_state = None

    with tempfile.TemporaryDirectory(prefix="asurada-phase1-regression-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        runtime_dir = tmp_root / "runtime_logs"
        config = AppConfig(replay_log_dir=runtime_dir)
        state_store = UnifiedStateStore()
        strategy = StrategyEngine(config.thresholds, config.usage_hooks_path)
        logger = ReplayLogger(runtime_dir)
        logger.reset()
        dashboard_builder = DebugDashboardBuilder(runtime_dir / "dashboard")
        decoder = F125PacketDecoder()
        assembler = CaptureSnapshotAssembler()

        for packet in CaptureJsonlSource(capture_path):
            try:
                envelope = decoder.decode_raw(packet)
            except PacketDecodeError:
                continue
            counter[envelope.kind] += 1
            snapshot = assembler.push(envelope)
            if snapshot is None:
                continue

            snapshot_count += 1
            state = decode_snapshot(snapshot)
            state_store.update(state)
            decision = strategy.evaluate(state, state_store.recent(12))
            logger.append(state, decision)
            latest_state = state
            last_debug = decision.debug

            if snapshot_count >= snapshot_limit:
                break

        dashboard_path = dashboard_builder.build_from_session_log(logger.path)
        dashboard_text = dashboard_path.read_text(encoding="utf-8")

    seen_packet_kinds = set(counter.keys())
    missing_required = sorted(required_packet_kinds - seen_packet_kinds)
    has_risk_explain = bool(last_debug.get("risk_explain"))
    has_usage_bias = bool(last_debug.get("usage_bias"))
    has_chain_ui = all(
        token in dashboard_text
        for token in (
            "Parse To Model Chain",
            "packet-filter",
            "Trigger Highlights",
            "Frame Change Diff",
        )
    )
    checks = {
        "capture_exists": capture_path.exists(),
        "required_packets_seen": not missing_required,
        "min_snapshots": snapshot_count >= min(200, snapshot_limit),
        "latest_state_present": latest_state is not None,
        "risk_explain_present": has_risk_explain,
        "usage_bias_present": has_usage_bias,
        "dashboard_chain_ui_present": has_chain_ui,
    }
    return {
        "passed": all(checks.values()),
        "source": str(capture_path),
        "snapshot_limit": snapshot_limit,
        "normalized_snapshots": snapshot_count,
        "packet_counts": dict(sorted(counter.items())),
        "missing_required_packet_kinds": missing_required,
        "latest_track": latest_state.track if latest_state is not None else None,
        "latest_lap": latest_state.lap_number if latest_state is not None else None,
        "checks": checks,
    }


if __name__ == "__main__":
    raise SystemExit(main())
