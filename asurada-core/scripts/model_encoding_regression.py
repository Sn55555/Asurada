from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import time

from asurada.capture_ingest import CaptureJsonlSource
from asurada.config import AppConfig
from asurada.context_window import CONTEXT_WINDOW_SECONDS
from asurada.decode import decode_snapshot
from asurada.model_admission import MODEL_NAMES, ModelAdmissionPolicy
from asurada.model_runtime import RuntimeFeatureEncoder
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu_decoder import F125PacketDecoder
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine
from regression_support import emit_result


def runtimes(engine):
    return [engine.strategy_action_runtime, engine.defence_cost_runtime] + [
        runtime
        for attribute in ("resource_risk_runtime", "rival_pressure_runtime", "driving_quality_runtime", "tyre_degradation_trend_runtime")
        for runtime in getattr(engine, attribute)._runtimes.values()
    ]


def select_replay_samples(samples, core_root: Path):
    """Keep external replay coverage when available; CI uses declared fixture evidence."""
    if samples and all(Path(sample["file_path"]).is_file() for sample in samples):
        return samples, 128, "external_recorded_capture_samples"
    fixture = core_root / "data/capture_samples/f1_25_udp_frame_fixture.jsonl"
    if not fixture.is_file():
        raise FileNotFoundError(f"Model encoding regression fixture missing: {fixture}")
    return [{"sample_name": "checked_in_frame_fixture", "file_path": str(fixture)}], 1, "checked_in_frame_fixture"


def run_regression():
    if importlib.util.find_spec("lightgbm") is None:
        return {"passed": True, "checks": {"skipped": True}, "reason": "lightgbm unavailable"}
    import numpy as np

    config = AppConfig()
    policy = ModelAdmissionPolicy(modes={name: "observe" for name in MODEL_NAMES})
    fast = StrategyEngine(config.thresholds, model_policy=policy)
    legacy = StrategyEngine(config.thresholds, model_policy=policy)
    models = runtimes(fast)
    if not all(model.enabled for model in models):
        return {"passed": False, "error": "All 14 real model assets are required"}
    for model in runtimes(legacy):
        model._encoder.fast = False

    mismatches = 0
    boundary_cases = 0
    for model in models:
        encoder = model._encoder
        rows = [
            {},
            {name: "UNKNOWN" if name in encoder.categorical else "not-a-number" for name in encoder.columns},
            {name: "unseen-category" if name in encoder.categorical else "12.375" for name in encoder.columns},
            {name: float("nan") for name in encoder.columns},
            {name: next(iter(encoder.codes[name]), "UNKNOWN") if name in encoder.categorical else -1.0 for name in encoder.columns},
        ]
        for row in rows:
            expected = model._booster.predict(encoder.legacy_frame(row), num_iteration=model._best_iteration(), num_threads=1)
            actual = model._booster.predict(encoder.encode(row), num_iteration=model._best_iteration(), num_threads=1)
            mismatches += int(not np.allclose(expected, actual, rtol=0, atol=1e-12, equal_nan=True))
            boundary_cases += 1

    core_root = Path(__file__).resolve().parents[1]
    samples = json.loads((core_root / "data/capture_samples/shanghai_race_weekend/metadata.json").read_text())["samples"]
    samples, sample_stride, replay_evidence = select_replay_samples(samples, core_root)
    times = {"legacy": [], "optimized": []}
    states = 0
    differences = 0
    sample_counts = {}
    for sample in samples:
        decoder, assembler, store = F125PacketDecoder(), CaptureSnapshotAssembler(), UnifiedStateStore()
        frame_index = 0
        sample_counts[sample["sample_name"]] = 0
        for packet in CaptureJsonlSource(Path(sample["file_path"])):
            snapshot = assembler.push(decoder.decode_raw(packet))
            if snapshot is None:
                continue
            state = decode_snapshot(snapshot)
            store.update(state)
            frame_index += 1
            if frame_index % sample_stride:
                continue
            decisions = {}
            # Alternate order to reduce systematic warm-cache timing bias.
            pairs = [("legacy", legacy), ("optimized", fast)]
            for name, engine in pairs if states % 2 else reversed(pairs):
                started = time.perf_counter()
                decisions[name] = engine.evaluate(state, store.recent_seconds(CONTEXT_WINDOW_SECONDS))
                times[name].append((time.perf_counter() - started) * 1000)
            differences += int(decisions["legacy"].messages != decisions["optimized"].messages or decisions["legacy"].debug != decisions["optimized"].debug)
            states += 1
            sample_counts[sample["sample_name"]] += 1
    latency = {
        name: {"p50": round(float(np.percentile(values, 50)), 3), "p95": round(float(np.percentile(values, 95)), 3)}
        for name, values in times.items()
    }
    checks = {
        "all_14_models_fast_path": len(models) == 14 and all(model._encoder.fast for model in models),
        "boundary_prediction_parity": mismatches == 0,
        "sampled_replay_exact_parity": differences == 0 and states > 0 and all(sample_counts.values()),
    }
    pd = models[0]._pd
    no_metadata = RuntimeFeatureEncoder(pd, SimpleNamespace(pandas_categorical=None), ["speed"], ["speed"], [])
    unknown_type = RuntimeFeatureEncoder(pd, SimpleNamespace(pandas_categorical=[]), ["speed"], [], [])
    checks["missing_metadata_falls_back"] = not no_metadata.fast and isinstance(no_metadata.encode({"speed": "12"}), pd.DataFrame)
    checks["unknown_feature_type_falls_back"] = not unknown_type.fast and isinstance(unknown_type.encode({"speed": 12}), pd.DataFrame)
    return {"passed": all(checks.values()), "checks": checks, "boundary_cases": boundary_cases,
            "prediction_mismatches": mismatches, "sampled_frames": states, "different_frames": differences,
            "sample_counts": sample_counts, "strategy_latency_ms": latency, "inference_threads": 1,
            "replay_evidence": replay_evidence,
            "limits": ["Sampled states, not complete sequential replay", "Strategy only; no UDP, logging, or audio", "Latency is informational, not a timing-sensitive assertion"]}


if __name__ == "__main__":
    emit_result(run_regression())
