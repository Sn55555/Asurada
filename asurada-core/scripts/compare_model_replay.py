from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

CORE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE_ROOT / "src"))

from asurada.capture_ingest import CaptureJsonlSource
from asurada.config import AppConfig
from asurada.decode import decode_snapshot
from asurada.model_admission import MODEL_NAMES, ModelAdmissionPolicy
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu_decoder import F125PacketDecoder, PacketDecodeError
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine


def percentile(values, fraction):
    ordered = sorted(values)
    return round(ordered[min(int((len(ordered) - 1) * fraction), len(ordered) - 1)], 3) if ordered else None


def compare(sample):
    config = AppConfig()
    engines = {
        mode: StrategyEngine(config.thresholds, config.usage_hooks_path, model_policy=ModelAdmissionPolicy(
            modes={name: mode for name in MODEL_NAMES}, version=f"comparison-{mode}",
        )) for mode in ("disabled", "observe")
    }
    observed = engines["observe"]
    availability = {"strategy_action": observed.strategy_action_runtime.enabled, "defence_cost": observed.defence_cost_runtime.enabled}
    for attribute in ("resource_risk_runtime", "rival_pressure_runtime", "driving_quality_runtime", "tyre_degradation_trend_runtime"):
        availability.update({name: runtime.enabled for name, runtime in getattr(observed, attribute)._runtimes.items()})
    if not all(availability.values()):
        return {"passed": False, "sample": sample["sample_name"], "model_availability": availability, "error": "Missing model assets or dependencies"}
    decoder = F125PacketDecoder()
    assembler = CaptureSnapshotAssembler()
    store = UnifiedStateStore()
    durations = {mode: [] for mode in engines}
    actions = {mode: Counter() for mode in engines}
    switches = {mode: 0 for mode in engines}
    previous = {}
    differences = []
    difference_count = 0
    route_violations = 0
    decode_errors = 0
    frames = 0
    final_seen = False
    started = time.perf_counter()
    for packet in CaptureJsonlSource(Path(sample["file_path"])):
        try:
            envelope = decoder.decode_raw(packet)
        except PacketDecodeError:
            decode_errors += 1
            continue
        final_seen = final_seen or envelope.kind == "FinalClassification"
        snapshot = assembler.push(envelope)
        if snapshot is None:
            continue
        state = decode_snapshot(snapshot)
        store.update(state)
        decisions = {}
        for mode, engine in engines.items():
            tick = time.perf_counter()
            decision = engine.evaluate(state, store.recent(12))
            durations[mode].append((time.perf_counter() - tick) * 1000)
            decisions[mode] = decision
            primary = decision.messages[0].code if decision.messages else "NONE"
            actions[mode][primary] += 1
            switches[mode] += int(mode in previous and previous[mode] != primary)
            previous[mode] = primary
            allowed = set(decision.debug["arbiter_v2"]["input"]["session_route"]["allowed_action_codes"])
            route_violations += sum(message.code not in allowed for message in decision.messages)
        baseline, shadow = decisions["disabled"], decisions["observe"]
        if baseline.messages != shadow.messages or baseline.debug["long_horizon_strategy"] != shadow.debug["long_horizon_strategy"]:
            difference_count += 1
            if len(differences) < 10:
                differences.append({"frame": frames, "lap": state.lap_number, "disabled": [asdict(x) for x in baseline.messages], "observe": [asdict(x) for x in shadow.messages]})
        frames += 1
        if frames % 500 == 0:
            print(f"{sample['sample_name']} frames={frames} differences={difference_count} elapsed={time.perf_counter()-started:.1f}s", flush=True)
    return {
        "passed": frames > 0 and final_seen and decode_errors == 0 and difference_count == 0 and route_violations == 0,
        "sample": sample["sample_name"], "source": sample["file_path"], "frames": frames,
        "complete_capture": True, "final_classification_seen": final_seen,
        "decode_errors": decode_errors, "different_frames": difference_count,
        "route_violations": route_violations, "difference_examples": differences,
        "model_availability": availability,
        "primary_actions": {mode: dict(counts) for mode, counts in actions.items()},
        "primary_action_switches": switches,
        "strategy_latency_ms": {
            mode: {"p50": percentile(values, .5), "p95": percentile(values, .95), "max": round(max(values), 3) if values else None, "over_100ms": sum(value > 100 for value in values)}
            for mode, values in durations.items()
        },
        "seconds": round(time.perf_counter() - started, 3),
        "limits": ["Strategy-only timing excludes audio and logging", "Action switches are not ground-truth false-positive labels", "Observe mode does not validate model advice quality"],
    }


def main():
    parser = argparse.ArgumentParser(description="Compare full recorded sessions with all models disabled versus observed.")
    parser.add_argument("--metadata", type=Path, default=CORE_ROOT / "data/capture_samples/shanghai_race_weekend/metadata.json")
    parser.add_argument("--sample", required=True, help="Exact sample_name from metadata")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    samples = json.loads(args.metadata.read_text())["samples"]
    sample = next((item for item in samples if item["sample_name"] == args.sample), None)
    if sample is None:
        parser.error("Unknown sample name")
    report = compare(sample)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
