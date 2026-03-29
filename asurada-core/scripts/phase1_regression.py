from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from asurada.capture_ingest import CaptureJsonlSource
from asurada.arbiter import (
    ArbiterInput,
    ConfidenceContext,
    FallbackContext,
    ModelCandidate,
    OutputControl,
    RuleCandidate,
    StrategyArbiterV2,
    TacticalContext,
)
from asurada.config import AppConfig
from asurada.dashboard import DebugDashboardBuilder
from asurada.decode import decode_snapshot
from asurada.models import ContextProfile, DriverState, SessionState, StateAssessment, TyreState
from asurada.output import ConsoleVoiceOutput
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu_decoder import F125PacketDecoder, PacketDecodeError
from asurada.replay import ReplayLogger
from asurada.state import UnifiedStateStore
from asurada.state_machine import TacticalStateMachine, TacticalStateResolution
from asurada.strategy import StrategyEngine

DEFAULT_CAPTURE = Path("/Users/sn5/Asurada/tools/captures/f1_25_udp_capture_20260321_024707.jsonl")
DEFAULT_SAMPLE_METADATA = Path(
    "/Users/sn5/Asurada/asurada-core/data/capture_samples/shanghai_race_weekend/metadata.json"
)
DEFAULT_REPORT = Path("/Users/sn5/Asurada/asurada-core/runtime_logs/regression/latest_phase1_regression.json")


class SilentVoiceOutput(ConsoleVoiceOutput):
    """Mute console strategy output during regression runs.

    备注:
    回归脚本只关心断言结果，不需要把策略播报刷到终端。
    """

    def emit(self, decision) -> None:  # noqa: D401
        return None


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the phase-one regression runner.

    备注:
    总抓包和分 session 样本的回归口径不同，所以分别保留 limit 参数。
    """

    parser = argparse.ArgumentParser(description="Run phase-one offline regression checks.")
    parser.add_argument(
        "--capture-jsonl",
        type=Path,
        default=DEFAULT_CAPTURE,
        help="Path to the full captured UDP JSONL sample.",
    )
    parser.add_argument(
        "--snapshot-limit",
        type=int,
        default=1200,
        help="Stop the full-capture health check after this many normalized snapshots.",
    )
    parser.add_argument(
        "--sample-metadata",
        type=Path,
        default=DEFAULT_SAMPLE_METADATA,
        help="Path to extracted per-session sample metadata JSON.",
    )
    parser.add_argument(
        "--sample-snapshot-limit",
        type=int,
        default=0,
        help="Optional per-sample snapshot limit. Use 0 to process each sample fully.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT,
        help="Where to write the regression summary JSON.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the regression suite and emit a machine-readable report."""

    args = parse_args()
    report = run_regression(
        capture_path=args.capture_jsonl,
        snapshot_limit=args.snapshot_limit,
        sample_metadata_path=args.sample_metadata,
        sample_snapshot_limit=args.sample_snapshot_limit,
    )
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ASURADA][REGRESSION] report={args.report_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def run_regression(
    capture_path: Path,
    snapshot_limit: int,
    sample_metadata_path: Path,
    sample_snapshot_limit: int,
) -> dict[str, Any]:
    """Run the full-capture health check plus per-session semantic assertions.

    备注:
    阶段一封板看两层结果：
    1. 总抓包主链是否健康。
    2. 已切出的比赛样本是否满足 session/timing 语义断言。
    """

    sample_metadata = load_sample_metadata(sample_metadata_path)
    full_capture = analyze_capture(capture_path, snapshot_limit if snapshot_limit > 0 else None)
    session_samples = [
        analyze_sample_session(sample, sample_snapshot_limit if sample_snapshot_limit > 0 else None)
        for sample in sample_metadata.get("samples", [])
    ]
    arbiter_contract = analyze_arbiter_contract()
    tactical_state_machine_contract = analyze_tactical_state_machine_contract()

    checks = {
        "full_capture_passed": full_capture["passed"],
        "sample_metadata_exists": sample_metadata_path.exists(),
        "session_samples_present": bool(session_samples),
        "all_session_samples_passed": all(item["passed"] for item in session_samples),
        "arbiter_contract_passed": arbiter_contract["passed"],
        "tactical_state_machine_contract_passed": tactical_state_machine_contract["passed"],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "full_capture": full_capture,
        "session_samples": session_samples,
        "arbiter_contract": arbiter_contract,
        "tactical_state_machine_contract": tactical_state_machine_contract,
    }


def load_sample_metadata(metadata_path: Path) -> dict[str, Any]:
    """Load per-session sample metadata.

    备注:
    这里直接复用阶段一切出来的周末样本清单，避免回归脚本再硬编码多份路径。
    """

    if not metadata_path.exists():
        return {"samples": []}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def analyze_sample_session(sample: dict[str, Any], snapshot_limit: int | None) -> dict[str, Any]:
    """Run semantic assertions against one extracted session sample.

    备注:
    每个 session 样本都有不同的 timing 预期；这里只验证阶段一已经确认过的语义。
    """

    sample_path = Path(sample["file_path"])
    summary = analyze_capture(sample_path, snapshot_limit)
    expected = expected_sample_profile(sample)
    assertions = build_sample_assertions(summary, sample, expected)
    return {
        "sample_name": sample.get("sample_name"),
        "session_uid": sample.get("session_uid"),
        "session_type_code": sample.get("session_type_code"),
        "session_label": sample.get("session_label"),
        "confidence": sample.get("confidence"),
        "passed": summary["passed"] and all(item["passed"] for item in assertions),
        "expected_profile": json_safe(expected),
        "analysis": summary,
        "assertions": assertions,
    }


def expected_sample_profile(sample: dict[str, Any]) -> dict[str, Any]:
    """Return the expected timing/session profile for a known sample."""

    label = sample.get("session_label", "")
    if label == "QualifyingLike(13)":
        return {
            "timing_mode": "qualifying_like",
            "timing_support_level": "official_preferred",
            "session_type": "QualifyingLike(13)",
            "dominant_gap_source_behind": "official_lapdata_adjacent",
        }
    if label == "ShortResultLike(8)":
        return {
            "timing_mode": "session_type_estimated",
            "timing_support_level": "estimated_only",
            "session_type": "ShortResultLike(8)",
            "forbidden_dominant_gap_sources": {"official_lapdata_adjacent"},
        }
    if label == "SprintRaceLike(15)":
        return {
            "timing_mode": "race_like",
            "timing_support_level": "official_preferred",
            "session_type": "SprintRaceLike(15)",
            "requires_official_gap": True,
        }
    if label == "FeatureRaceLike(16)":
        return {
            "timing_mode": "race_like",
            "timing_support_level": "official_preferred",
            "session_type": "FeatureRaceLike(16)",
            "requires_official_gap": True,
        }
    return {}


def build_sample_assertions(
    summary: dict[str, Any],
    sample: dict[str, Any],
    expected: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build per-sample semantic assertions from capture analysis."""

    analysis = summary["analysis"]
    timing_mode_counts = analysis["timing_mode_counts"]
    timing_support_counts = analysis["timing_support_counts"]
    session_type_counts = analysis["session_type_counts"]
    gap_source_ahead_counts = analysis["gap_source_ahead_counts"]
    gap_source_behind_counts = analysis["gap_source_behind_counts"]
    dominant_ahead = dominant_key(gap_source_ahead_counts)
    dominant_behind = dominant_key(gap_source_behind_counts)

    assertions = [
        {
            "name": "base_capture_health",
            "passed": summary["passed"],
            "detail": "Underlying sample replay must satisfy the generic phase-one health checks.",
        }
    ]

    if "session_type" in expected:
        actual = dominant_key(session_type_counts)
        assertions.append(
            {
                "name": "session_type_label",
                "passed": actual == expected["session_type"],
                "expected": expected["session_type"],
                "actual": actual,
            }
        )

    if "timing_mode" in expected:
        actual = dominant_key(timing_mode_counts)
        assertions.append(
            {
                "name": "timing_mode",
                "passed": actual == expected["timing_mode"],
                "expected": expected["timing_mode"],
                "actual": actual,
            }
        )

    if "timing_support_level" in expected:
        actual = dominant_key(timing_support_counts)
        assertions.append(
            {
                "name": "timing_support_level",
                "passed": actual == expected["timing_support_level"],
                "expected": expected["timing_support_level"],
                "actual": actual,
            }
        )

    if "dominant_gap_source_behind" in expected:
        assertions.append(
            {
                "name": "dominant_gap_source_behind",
                "passed": dominant_behind == expected["dominant_gap_source_behind"],
                "expected": expected["dominant_gap_source_behind"],
                "actual": dominant_behind,
            }
        )

    forbidden_gap_sources = expected.get("forbidden_dominant_gap_sources")
    if forbidden_gap_sources:
        forbidden_list = sorted(forbidden_gap_sources)
        assertions.append(
            {
                "name": "dominant_gap_source_ahead_not_forbidden",
                "passed": dominant_ahead not in forbidden_gap_sources,
                "forbidden": forbidden_list,
                "actual": dominant_ahead,
            }
        )
        assertions.append(
            {
                "name": "dominant_gap_source_behind_not_forbidden",
                "passed": dominant_behind not in forbidden_gap_sources,
                "forbidden": forbidden_list,
                "actual": dominant_behind,
            }
        )

    if expected.get("requires_official_gap"):
        official_ahead = gap_source_ahead_counts.get("official_lapdata_adjacent", 0)
        official_behind = gap_source_behind_counts.get("official_lapdata_adjacent", 0)
        assertions.append(
            {
                "name": "official_gap_present",
                "passed": (official_ahead + official_behind) > 0,
                "actual": {
                    "ahead": official_ahead,
                    "behind": official_behind,
                },
            }
        )

    final_summary = sample.get("final") or {}
    if final_summary:
        assertions.append(
            {
                "name": "final_classification_present",
                "passed": bool(summary["analysis"]["final_classification_seen"]),
                "expected": {
                    "position": final_summary.get("player_position"),
                    "points": final_summary.get("player_points"),
                },
                "actual": summary["analysis"]["latest_final_classification"],
            }
        )

    return assertions


def analyze_capture(capture_path: Path, snapshot_limit: int | None) -> dict[str, Any]:
    """Analyze one capture file and return health + semantic counters."""

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
    timing_mode_counts: Counter[str] = Counter()
    timing_support_counts: Counter[str] = Counter()
    session_type_counts: Counter[str] = Counter()
    gap_source_ahead_counts: Counter[str] = Counter()
    gap_source_behind_counts: Counter[str] = Counter()
    gap_confidence_ahead_counts: Counter[str] = Counter()
    gap_confidence_behind_counts: Counter[str] = Counter()
    event_code_counts: Counter[str] = Counter()
    arbiter_primary_counts: Counter[str] = Counter()
    snapshot_count = 0
    last_debug: dict[str, Any] = {}
    latest_state = None
    latest_raw: dict[str, Any] = {}
    latest_final_classification: dict[str, Any] = {}
    arbiter_sidecar_seen = False
    arbiter_contract_seen = False
    arbiter_model_candidate_frames = 0

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
            if envelope.kind == "Event":
                event_code = envelope.payload.get("body", {}).get("event_code")
                if event_code:
                    event_code_counts[str(event_code)] += 1
            if envelope.kind == "FinalClassification":
                latest_final_classification = dict(envelope.payload.get("body", {}))
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
            latest_raw = dict(state.raw)

            arbiter_sidecar = decision.debug.get("arbiter_v2") or {}
            if arbiter_sidecar:
                arbiter_sidecar_seen = True
                if "input" in arbiter_sidecar and "output" in arbiter_sidecar:
                    arbiter_contract_seen = True
                model_candidates = arbiter_sidecar.get("input", {}).get("model_candidates", [])
                if model_candidates:
                    arbiter_model_candidate_frames += 1
                primary = arbiter_sidecar.get("output", {}).get("final_strategy_stack", {}).get("primary")
                if primary:
                    arbiter_primary_counts[str(primary)] += 1

            timing_mode_counts[str(latest_raw.get("timing_mode"))] += 1
            timing_support_counts[str(latest_raw.get("timing_support_level"))] += 1
            session_type_counts[str(latest_raw.get("session_type"))] += 1
            gap_source_ahead_counts[str(latest_raw.get("gap_source_ahead"))] += 1
            gap_source_behind_counts[str(latest_raw.get("gap_source_behind"))] += 1
            gap_confidence_ahead_counts[str(latest_raw.get("gap_confidence_ahead"))] += 1
            gap_confidence_behind_counts[str(latest_raw.get("gap_confidence_behind"))] += 1

            if snapshot_limit is not None and snapshot_count >= snapshot_limit:
                break

        dashboard_path = dashboard_builder.build_from_session_log(logger.path)
        dashboard_text = dashboard_path.read_text(encoding="utf-8")

    seen_packet_kinds = set(counter.keys())
    missing_required = sorted(required_packet_kinds - seen_packet_kinds)
    has_risk_explain = bool(last_debug.get("risk_explain"))
    has_usage_bias = bool(last_debug.get("usage_bias"))
    session_route = last_debug.get("session_route") or {}
    has_chain_ui = all(
        token in dashboard_text
        for token in (
            "World Trajectory",
            "Current Strategy Output",
            "Front / Rear Rival",
            "Frame Browser",
            "trajectory-canvas",
            "frame-slider",
        )
    )
    interaction_input_event = last_debug.get("interaction_input_event") or {}
    snapshot_binding = interaction_input_event.get("snapshot_binding") or {}
    output_lifecycle = last_debug.get("output_lifecycle") or {}
    output_lifecycle_event = output_lifecycle.get("event") or {}
    structured_query = last_debug.get("structured_query") or {}
    query_route = last_debug.get("query_route") or {}
    confirmation_policy = last_debug.get("confirmation_policy") or {}
    task_handle = last_debug.get("task_handle") or {}
    task_lifecycle = last_debug.get("task_lifecycle") or {}
    task_lifecycle_event = task_lifecycle.get("event") or {}
    voice_pipeline_log = last_debug.get("voice_pipeline_log") or {}
    asr_stage = voice_pipeline_log.get("asr") or {}
    query_stage = voice_pipeline_log.get("query_normalization") or {}
    strategy_stage = voice_pipeline_log.get("strategy") or {}
    tts_stage = voice_pipeline_log.get("tts") or {}
    checks = {
        "capture_exists": capture_path.exists(),
        "required_packets_seen": not missing_required,
        "min_snapshots": snapshot_count >= min(200, snapshot_limit or 200),
        "latest_state_present": latest_state is not None,
        "risk_explain_present": has_risk_explain,
        "usage_bias_present": has_usage_bias,
        "session_route_present": bool(session_route),
        "arbiter_v2_present": arbiter_sidecar_seen,
        "arbiter_v2_contract_present": arbiter_contract_seen,
        "arbiter_model_candidates_present": arbiter_model_candidate_frames > 0,
        "interaction_input_event_present": bool(interaction_input_event),
        "interaction_snapshot_binding_present": bool(snapshot_binding.get("snapshot_binding_id")),
        "output_lifecycle_present": bool(output_lifecycle),
        "output_lifecycle_contract_present": bool(output_lifecycle_event.get("output_event_id"))
        and bool(output_lifecycle_event.get("event_type")),
        "structured_query_present": bool(structured_query),
        "structured_query_contract_present": bool(structured_query.get("schema_version"))
        and bool(structured_query.get("query_kind"))
        and bool(query_route.get("handler")),
        "confirmation_policy_present": bool(confirmation_policy),
        "confirmation_policy_contract_present": bool(confirmation_policy.get("policy_version"))
        and bool(confirmation_policy.get("decision"))
        and isinstance(confirmation_policy.get("requires_confirmation"), bool),
        "task_handle_present": bool(task_handle),
        "task_handle_contract_present": bool(task_handle.get("task_id"))
        and bool(task_handle.get("handler"))
        and bool(task_handle.get("task_type")),
        "task_lifecycle_present": bool(task_lifecycle),
        "task_lifecycle_contract_present": bool(task_lifecycle_event.get("task_id"))
        and bool(task_lifecycle_event.get("event_type"))
        and bool(task_lifecycle_event.get("status")),
        "voice_pipeline_log_present": bool(voice_pipeline_log),
        "voice_pipeline_contract_present": bool(query_stage.get("normalized_query_text"))
        and bool(strategy_stage.get("primary_action_code"))
        and bool(tts_stage.get("event_type"))
        and bool(asr_stage.get("stage_status")),
        "dashboard_chain_ui_present": has_chain_ui,
        "time_trial_route_filters_race_actions": latest_raw.get("timing_mode") != "time_trial_disabled"
        or (
            "LOW_FUEL" not in set(session_route.get("allowed_action_codes") or [])
            and "DEFEND_WINDOW" not in set(session_route.get("allowed_action_codes") or [])
            and session_route.get("allow_timing_actions") is False
        ),
    }
    analysis = {
        "timing_mode_counts": dict(sorted(timing_mode_counts.items())),
        "timing_support_counts": dict(sorted(timing_support_counts.items())),
        "session_type_counts": dict(sorted(session_type_counts.items())),
        "gap_source_ahead_counts": dict(sorted(gap_source_ahead_counts.items())),
        "gap_source_behind_counts": dict(sorted(gap_source_behind_counts.items())),
        "gap_confidence_ahead_counts": dict(sorted(gap_confidence_ahead_counts.items())),
        "gap_confidence_behind_counts": dict(sorted(gap_confidence_behind_counts.items())),
        "event_code_counts": dict(sorted(event_code_counts.items())),
        "arbiter_primary_counts": dict(sorted(arbiter_primary_counts.items())),
        "arbiter_model_candidate_frames": arbiter_model_candidate_frames,
        "latest_session_route": session_route,
        "latest_interaction_input_event": interaction_input_event,
        "latest_output_lifecycle": output_lifecycle,
        "latest_structured_query": structured_query,
        "latest_query_route": query_route,
        "latest_confirmation_policy": confirmation_policy,
        "latest_task_handle": task_handle,
        "latest_task_lifecycle": task_lifecycle,
        "latest_voice_pipeline_log": voice_pipeline_log,
        "latest_raw": {
            "session_type": latest_raw.get("session_type"),
            "timing_mode": latest_raw.get("timing_mode"),
            "timing_support_level": latest_raw.get("timing_support_level"),
            "gap_source_ahead": latest_raw.get("gap_source_ahead"),
            "gap_source_behind": latest_raw.get("gap_source_behind"),
            "gap_confidence_ahead": latest_raw.get("gap_confidence_ahead"),
            "gap_confidence_behind": latest_raw.get("gap_confidence_behind"),
        },
        "latest_final_classification": summarize_final_classification(latest_final_classification),
        "final_classification_seen": bool(latest_final_classification),
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
        "analysis": analysis,
    }


def analyze_arbiter_contract() -> dict[str, Any]:
    """Run synthetic regression checks against StrategyArbiterV2 behavior."""

    arbiter = StrategyArbiterV2()

    priority_payload = ArbiterInput(
        rule_candidates=[],
        model_candidates=[
            ModelCandidate(
                code="LOW_FUEL",
                score=0.616,
                rank=1,
                source_model="strategy_action_model",
                title="燃油紧张",
                detail="LOW_FUEL 候选分数 0.616",
            ),
            ModelCandidate(
                code="NONE",
                score=0.347,
                rank=2,
                source_model="strategy_action_model",
                title="保持当前策略",
                detail="NONE 候选分数 0.347",
            ),
        ],
        tactical_context=TacticalContext(tactical_state="neutral"),
        confidence_context=ConfidenceContext(confidence_score=0.9, confidence_level="high", mainline_allowed=True),
        fallback_context=FallbackContext(fallback_mode="none", voice_allowed=True, hud_only=False),
        output_control=OutputControl(cooldown_hint=0, last_emitted_action=None, suppression_window=0),
    )
    priority_result = arbiter.arbitrate(priority_payload)

    cooldown_payload = ArbiterInput(
        rule_candidates=[],
        model_candidates=[
            ModelCandidate(
                code="LOW_FUEL",
                score=0.616,
                rank=1,
                source_model="strategy_action_model",
                title="燃油紧张",
                detail="LOW_FUEL 候选分数 0.616",
            ),
            ModelCandidate(
                code="NONE",
                score=0.347,
                rank=2,
                source_model="strategy_action_model",
                title="保持当前策略",
                detail="NONE 候选分数 0.347",
            ),
        ],
        tactical_context=TacticalContext(tactical_state="neutral"),
        confidence_context=ConfidenceContext(confidence_score=0.9, confidence_level="high", mainline_allowed=True),
        fallback_context=FallbackContext(fallback_mode="none", voice_allowed=True, hud_only=False),
        output_control=OutputControl(cooldown_hint=0, last_emitted_action="LOW_FUEL", suppression_window=1),
    )
    cooldown_result = arbiter.arbitrate(cooldown_payload)

    dedupe_payload = ArbiterInput(
        rule_candidates=[
            RuleCandidate(
                code="DEFEND_WINDOW",
                priority=74,
                title="防守窗口",
                detail="规则链防守候选。",
            )
        ],
        model_candidates=[
            ModelCandidate(
                code="DEFEND_WINDOW",
                score=0.71,
                rank=1,
                source_model="strategy_action_model",
                title="防守窗口",
                detail="模型链防守候选。",
            ),
            ModelCandidate(
                code="NONE",
                score=0.18,
                rank=2,
                source_model="strategy_action_model",
                title="保持当前策略",
                detail="NONE 候选分数 0.180",
            ),
        ],
        tactical_context=TacticalContext(tactical_state="defence_active", state_priority_hint="DEFEND_WINDOW", state_lock=True),
        confidence_context=ConfidenceContext(confidence_score=0.95, confidence_level="high", mainline_allowed=True),
        fallback_context=FallbackContext(fallback_mode="none", voice_allowed=True, hud_only=False),
        output_control=OutputControl(cooldown_hint=0, last_emitted_action=None, suppression_window=0),
    )
    dedupe_result = arbiter.arbitrate(dedupe_payload)
    deduped_codes = [item.code for item in dedupe_result.ordered_actions]

    fallback_payload = ArbiterInput(
        rule_candidates=[
            RuleCandidate(
                code="DEFEND_WINDOW",
                priority=74,
                title="防守窗口",
                detail="规则链防守候选。",
            )
        ],
        model_candidates=[
            ModelCandidate(
                code="DEFEND_WINDOW",
                score=0.82,
                rank=1,
                source_model="strategy_action_model",
                title="防守窗口",
                detail="模型链防守候选。",
            )
        ],
        tactical_context=TacticalContext(tactical_state="defence_active", state_priority_hint="DEFEND_WINDOW", state_lock=True),
        confidence_context=ConfidenceContext(confidence_score=0.32, confidence_level="low", mainline_allowed=False),
        fallback_context=FallbackContext(fallback_mode="rule_only", voice_allowed=False, hud_only=True),
        output_control=OutputControl(cooldown_hint=0, last_emitted_action=None, suppression_window=0),
    )
    fallback_result = arbiter.arbitrate(fallback_payload)

    checks = {
        "priority_floor_calibrated": priority_result.final_strategy_stack.primary == "LOW_FUEL"
        and priority_result.ordered_actions
        and priority_result.ordered_actions[0].priority >= 70,
        "cooldown_suppresses_last_action": cooldown_result.final_strategy_stack.primary == "NONE"
        and any(item.suppression_reason == "cooldown_window" for item in cooldown_result.suppressed_actions),
        "duplicate_codes_deduped": deduped_codes.count("DEFEND_WINDOW") == 1,
        "low_confidence_falls_back_to_rules": fallback_result.final_strategy_stack.primary == "DEFEND_WINDOW"
        and any(item.suppression_reason == "fallback_rule_only" for item in fallback_result.suppressed_actions)
        and fallback_result.final_voice_action is None,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "priority_result": {
                "primary": priority_result.final_strategy_stack.primary,
                "ordered_actions": [item.__dict__ for item in priority_result.ordered_actions],
            },
            "cooldown_result": {
                "primary": cooldown_result.final_strategy_stack.primary,
                "suppressed_actions": [item.__dict__ for item in cooldown_result.suppressed_actions],
                "ordered_actions": [item.__dict__ for item in cooldown_result.ordered_actions],
            },
            "dedupe_result": {
                "primary": dedupe_result.final_strategy_stack.primary,
                "ordered_actions": [item.__dict__ for item in dedupe_result.ordered_actions],
            },
            "fallback_result": {
                "primary": fallback_result.final_strategy_stack.primary,
                "suppressed_actions": [item.__dict__ for item in fallback_result.suppressed_actions],
                "ordered_actions": [item.__dict__ for item in fallback_result.ordered_actions],
                "voice_action": fallback_result.final_voice_action.__dict__ if fallback_result.final_voice_action else None,
            },
        },
    }


def analyze_tactical_state_machine_contract() -> dict[str, Any]:
    """Run synthetic regression checks against TacticalStateMachine behavior."""

    state_machine = TacticalStateMachine()
    context = ContextProfile(
        recent_unstable_ratio=0.1,
        recent_front_overload_ratio=0.0,
        driving_mode="push_exit",
        track_zone="deployment_straight",
        track_segment="T14 Exit",
        track_usage="attack",
        tyre_age_factor=2,
        brake_phase_factor=0,
        throttle_phase_factor=8,
        steering_phase_factor=2,
    )

    defend_previous = _make_session_state(position=2, gap_ahead_s=0.8, gap_behind_s=0.4, drs_available=False)
    defend_current = _make_session_state(position=2, gap_ahead_s=0.9, gap_behind_s=0.3, drs_available=False)
    defend_assessment = StateAssessment(
        fuel_state="stable",
        tyre_state="stable",
        ers_state="stable",
        race_state="green",
        attack_state="closed",
        defend_state="urgent",
        dynamics_state="stable",
    )
    defend_result = state_machine.resolve(
        state=defend_current,
        previous_state=defend_previous,
        previous_resolution=None,
        last_output_action=None,
        assessment=defend_assessment,
        context=context,
    )

    counter_previous = _make_session_state(position=1, gap_ahead_s=None, gap_behind_s=0.4, drs_available=False)
    counter_current = _make_session_state(position=2, gap_ahead_s=0.45, gap_behind_s=0.6, drs_available=True)
    counter_assessment = StateAssessment(
        fuel_state="stable",
        tyre_state="stable",
        ers_state="stable",
        race_state="green",
        attack_state="available",
        defend_state="clear",
        dynamics_state="stable",
    )
    counter_result = state_machine.resolve(
        state=counter_current,
        previous_state=counter_previous,
        previous_resolution=None,
        last_output_action=None,
        assessment=counter_assessment,
        context=context,
    )

    history_previous = _make_session_state(position=2, gap_ahead_s=0.8, gap_behind_s=0.9, drs_available=False)
    history_current = _make_session_state(position=2, gap_ahead_s=1.0, gap_behind_s=1.35, drs_available=False)
    history_previous_resolution = TacticalStateResolution(
        previous_tactical_state="neutral",
        tactical_state="defence_prepare",
        state_transition="neutral->defence_prepare",
        state_priority_hint="DEFEND_WINDOW",
        state_lock=False,
        recommended_action="DEFEND_WINDOW",
        position_lost_recently=False,
        position_gain_recently=False,
        history_hold_applied=False,
        history_anchor_action=None,
    )
    history_assessment = StateAssessment(
        fuel_state="stable",
        tyre_state="stable",
        ers_state="stable",
        race_state="green",
        attack_state="closed",
        defend_state="clear",
        dynamics_state="stable",
    )
    history_result = state_machine.resolve(
        state=history_current,
        previous_state=history_previous,
        previous_resolution=history_previous_resolution,
        last_output_action="DEFEND_WINDOW",
        assessment=history_assessment,
        context=context,
    )

    checks = {
        "defence_window_locks_state": defend_result.tactical_state == "defence_active"
        and defend_result.state_lock
        and defend_result.state_priority_hint == "DEFEND_WINDOW",
        "position_loss_arms_counterattack": counter_result.position_lost_recently
        and counter_result.tactical_state in {"counterattack_prepare", "counterattack_active"}
        and counter_result.state_priority_hint == "ATTACK_WINDOW",
        "output_history_holds_tactical_state": history_result.history_hold_applied
        and history_result.tactical_state == "defence_prepare"
        and history_result.history_anchor_action == "DEFEND_WINDOW",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "defence_result": defend_result.__dict__,
            "counterattack_result": counter_result.__dict__,
            "history_hold_result": history_result.__dict__,
        },
    }


def _make_session_state(
    *,
    position: int,
    gap_ahead_s: float | None,
    gap_behind_s: float | None,
    drs_available: bool,
) -> SessionState:
    player = DriverState(
        car_index=0,
        name="player",
        position=position,
        lap=3,
        gap_ahead_s=gap_ahead_s,
        gap_behind_s=gap_behind_s,
        fuel_laps_remaining=4.0,
        ers_pct=45.0,
        drs_available=drs_available,
        tyre=TyreState(compound="C3", wear_pct=22.0, age_laps=3),
        speed_kph=245.0,
        status_tags=[],
    )
    return SessionState(
        session_uid="synthetic-session",
        track="Shanghai",
        lap_number=3,
        total_laps=5,
        weather="Clear",
        safety_car="NONE",
        player=player,
        rivals=[],
        source_timestamp_ms=0,
        raw={},
    )


def summarize_final_classification(final_classification: dict[str, Any]) -> dict[str, Any]:
    """Extract a compact summary for regression output."""

    if not final_classification:
        return {}
    player = final_classification.get("player") or {}
    return {
        "position": player.get("position"),
        "points": player.get("points"),
        "num_laps": player.get("num_laps"),
        "result_status": player.get("result_status"),
    }


def dominant_key(counts: dict[str, int]) -> str | None:
    """Return the dominant key from a frequency mapping."""

    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def json_safe(value: Any) -> Any:
    """Convert nested regression payloads into JSON-safe values."""

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, set):
        return [json_safe(item) for item in sorted(value)]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
