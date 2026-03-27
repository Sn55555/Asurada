from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from asurada.capture_ingest import CaptureJsonlSource
from asurada.config import AppConfig
from asurada.decode import decode_snapshot
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu_decoder import F125PacketDecoder, PacketDecodeError
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine
from asurada.track_model import load_track_profile


DEFAULT_CONFIG = PROJECT_ROOT / "training" / "configs" / "phase2_dataset_v1.json"

FEATURE_COLUMNS = [
    "record_id",
    "split",
    "sample_name",
    "session_uid",
    "frame_identifier",
    "overall_frame_identifier",
    "source_timestamp_ms",
    "session_time_s",
    "track",
    "session_type",
    "timing_mode",
    "timing_support_level",
    "lap_number",
    "total_laps",
    "weather",
    "safety_car",
    "player_name",
    "player_position",
    "position_lost_recently",
    "position_gain_recently",
    "lap_distance_m",
    "total_distance_m",
    "current_lap_time_ms",
    "last_lap_time_ms",
    "sector1_time_ms",
    "sector2_time_ms",
    "official_gap_ahead_s",
    "official_gap_behind_s",
    "official_gap_confidence_ahead",
    "official_gap_confidence_behind",
    "official_gap_source_ahead",
    "official_gap_source_behind",
    "estimated_gap_ahead_s",
    "estimated_gap_behind_s",
    "gap_closing_rate_ahead",
    "gap_closing_rate_behind",
    "speed_kph",
    "throttle",
    "brake",
    "steer",
    "gear",
    "rpm",
    "fuel_in_tank",
    "fuel_capacity",
    "fuel_laps_remaining",
    "ers_store_energy",
    "ers_pct",
    "ers_deploy_mode",
    "drs_available",
    "tyre_compound",
    "tyre_wear_pct",
    "tyre_age_laps",
    "status_tags",
    "g_force_lateral",
    "g_force_longitudinal",
    "g_force_vertical",
    "yaw",
    "pitch",
    "roll",
    "wheel_slip_ratio_fl",
    "wheel_slip_ratio_fr",
    "wheel_slip_ratio_rl",
    "wheel_slip_ratio_rr",
    "track_zone",
    "track_segment",
    "track_usage",
    "next_track_segment",
    "next_track_usage",
    "next_two_segments",
    "driving_mode",
    "recent_unstable_ratio",
    "recent_front_overload_ratio",
    "tyre_age_factor",
    "brake_phase_factor",
    "throttle_phase_factor",
    "steering_phase_factor",
    "front_rival_name",
    "front_rival_position",
    "front_rival_speed_kph",
    "front_rival_ers_pct",
    "front_rival_speed_delta",
    "rear_rival_name",
    "rear_rival_position",
    "rear_rival_speed_kph",
    "rear_rival_ers_pct",
    "rear_rival_drs_available",
    "rear_rival_speed_delta",
    "event_code",
]

LABEL_COLUMNS = [
    "record_id",
    "split",
    "sample_name",
    "session_uid",
    "frame_identifier",
    "session_type",
    "timing_support_level",
    "fuel_state_label",
    "tyre_state_label",
    "ers_state_label",
    "race_state_label",
    "attack_state_label",
    "defend_state_label",
    "dynamics_state_label",
    "fuel_risk_label",
    "tyre_risk_label",
    "ers_risk_label",
    "race_control_risk_label",
    "dynamics_risk_label",
    "attack_opportunity_label",
    "defend_risk_label",
    "primary_action_label",
    "action_codes",
    "position_lost_event_label",
    "position_gain_event_label",
    "official_gap_available_ahead_label",
    "official_gap_available_behind_label",
    "event_code_label",
]

TACTICAL_FEATURE_COLUMNS = [
    "record_id",
    "split",
    "sample_name",
    "session_uid",
    "frame_identifier",
    "session_time_s",
    "session_type",
    "timing_mode",
    "timing_support_level",
    "player_position",
    "position_lost_recently",
    "position_gain_recently",
    "official_gap_ahead_s",
    "official_gap_behind_s",
    "official_gap_confidence_ahead",
    "official_gap_confidence_behind",
    "gap_closing_rate_ahead",
    "gap_closing_rate_behind",
    "rear_rival_position",
    "rear_rival_speed_kph",
    "rear_rival_ers_pct",
    "rear_rival_drs_available",
    "rear_rival_speed_delta",
    "front_rival_position",
    "front_rival_speed_kph",
    "front_rival_ers_pct",
    "front_rival_speed_delta",
    "speed_kph",
    "throttle",
    "brake",
    "steer",
    "fuel_laps_remaining",
    "ers_pct",
    "tyre_wear_pct",
    "tyre_age_laps",
    "recent_unstable_ratio",
    "recent_front_overload_ratio",
    "g_force_lateral",
    "g_force_longitudinal",
    "wheel_slip_ratio_rl",
    "wheel_slip_ratio_rr",
    "track_zone",
    "track_segment",
    "track_usage",
    "rear_threat_zone_flag",
    "counterattack_zone_flag",
    "next_track_segment",
    "next_track_usage",
    "next_two_segments",
    "driving_mode",
    "drs_recovery_window",
    "defence_cost_proxy",
    "rear_rival_pressure_proxy",
    "event_code",
    "rear_threat_binary_label",
    "rear_threat_level_label",
    "yield_vs_fight_proxy_label",
    "counterattack_candidate_label",
    "primary_action_label",
]

EVENT_FEATURE_COLUMNS = [
    "record_id",
    "split",
    "sample_name",
    "session_uid",
    "frame_identifier",
    "session_time_s",
    "session_type",
    "timing_mode",
    "timing_support_level",
    "lap_number",
    "player_position",
    "position_lost_recently",
    "position_gain_recently",
    "official_gap_ahead_s",
    "official_gap_behind_s",
    "speed_kph",
    "fuel_laps_remaining",
    "ers_pct",
    "tyre_wear_pct",
    "recent_unstable_ratio",
    "recent_front_overload_ratio",
    "track_segment",
    "track_usage",
    "next_track_segment",
    "next_track_usage",
    "driving_mode",
    "event_code",
    "event_detail_kind",
    "event_code_started",
    "primary_action_label",
    "attack_opportunity_label",
    "defend_risk_label",
    "dynamics_risk_label",
    "event_impact_binary_label",
    "event_strategy_shift_label",
]

ATTACK_FEATURE_COLUMNS = [
    "record_id",
    "split",
    "sample_name",
    "session_uid",
    "frame_identifier",
    "actor_view",
    "session_time_s",
    "session_type",
    "timing_mode",
    "timing_support_level",
    "lap_number",
    "actor_position",
    "position_gain_recently",
    "official_gap_ahead_s",
    "official_gap_confidence_ahead",
    "gap_closing_rate_ahead",
    "front_rival_position",
    "front_rival_speed_kph",
    "front_rival_ers_pct",
    "front_rival_speed_delta",
    "speed_kph",
    "drs_available",
    "throttle",
    "brake",
    "steer",
    "fuel_laps_remaining",
    "ers_pct",
    "tyre_wear_pct",
    "tyre_age_laps",
    "recent_unstable_ratio",
    "recent_front_overload_ratio",
    "g_force_lateral",
    "g_force_longitudinal",
    "track_segment",
    "track_usage",
    "next_track_segment",
    "next_track_usage",
    "next_two_segments",
    "driving_mode",
    "attack_zone_flag",
    "attack_opportunity_proxy_label",
    "attack_opportunity_level_label",
    "attack_commit_proxy_label",
    "attack_followthrough_label",
    "primary_action_label",
    "attack_opportunity_label",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export phase-two feature and label tables from capture samples.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Dataset export config JSON.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override output directory. Defaults to training/exports/<dataset_name>.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=0,
        help="Optional limit of normalized frames per sample. Use 0 for full export.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    output_dir = args.output_dir or (PROJECT_ROOT / "training" / "exports" / config["dataset_name"])
    output_dir.mkdir(parents=True, exist_ok=True)

    report = export_dataset(
        sample_metadata_path=Path(config["sample_metadata_path"]),
        output_dir=output_dir,
        sample_splits=dict(config.get("sample_splits", {})),
        next_segment_offsets=[float(item) for item in config.get("next_segment_offsets_m", [120.0, 280.0])],
        max_history_frames=int(config.get("max_history_frames", 12)),
        sample_limit=args.sample_limit if args.sample_limit > 0 else None,
    )
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def export_dataset(
    *,
    sample_metadata_path: Path,
    output_dir: Path,
    sample_splits: dict[str, str],
    next_segment_offsets: list[float],
    max_history_frames: int,
    sample_limit: int | None,
) -> dict[str, Any]:
    """Export flat phase-two datasets from extracted per-session capture samples.

    备注:
    导出三类产物：
    1. 全量 `features.csv`
    2. 全量 `labels.csv`
    3. 聚焦攻防主线的 `tactical_features_v1.csv`
    """

    metadata = json.loads(sample_metadata_path.read_text(encoding="utf-8"))
    samples = list(metadata.get("samples", []))

    features_path = output_dir / "features.csv"
    labels_path = output_dir / "labels.csv"
    tactical_features_path = output_dir / "tactical_features_v1.csv"
    event_features_path = output_dir / "event_features_v1.csv"
    attack_features_path = output_dir / "attack_features_v1.csv"
    features_path.parent.mkdir(parents=True, exist_ok=True)

    sample_summaries: list[dict[str, Any]] = []
    split_counts: Counter[str] = Counter()
    tactical_split_counts: Counter[str] = Counter()
    event_split_counts: Counter[str] = Counter()
    attack_split_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    rear_threat_level_counts: Counter[str] = Counter()
    yield_vs_fight_counts: Counter[str] = Counter()
    event_impact_counts: Counter[str] = Counter()
    attack_commit_counts: Counter[str] = Counter()

    record_count = 0
    tactical_record_count = 0
    event_record_count = 0
    attack_record_count = 0

    with features_path.open("w", encoding="utf-8", newline="") as features_handle, labels_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as labels_handle, tactical_features_path.open("w", encoding="utf-8", newline="") as tactical_handle, event_features_path.open("w", encoding="utf-8", newline="") as event_handle, attack_features_path.open("w", encoding="utf-8", newline="") as attack_handle:
        feature_writer = csv.DictWriter(features_handle, fieldnames=FEATURE_COLUMNS)
        label_writer = csv.DictWriter(labels_handle, fieldnames=LABEL_COLUMNS)
        tactical_writer = csv.DictWriter(tactical_handle, fieldnames=TACTICAL_FEATURE_COLUMNS)
        event_writer = csv.DictWriter(event_handle, fieldnames=EVENT_FEATURE_COLUMNS)
        attack_writer = csv.DictWriter(attack_handle, fieldnames=ATTACK_FEATURE_COLUMNS)
        feature_writer.writeheader()
        label_writer.writeheader()
        tactical_writer.writeheader()
        event_writer.writeheader()
        attack_writer.writeheader()

        for sample in samples:
            sample_name = sample["sample_name"]
            split = sample_splits.get(sample_name, "train")
            summary = export_sample(
                sample=sample,
                split=split,
                feature_writer=feature_writer,
                label_writer=label_writer,
                tactical_writer=tactical_writer,
                event_writer=event_writer,
                attack_writer=attack_writer,
                next_segment_offsets=next_segment_offsets,
                max_history_frames=max_history_frames,
                sample_limit=sample_limit,
            )
            sample_summaries.append(summary)
            split_counts[split] += summary["records"]
            tactical_split_counts[split] += summary["tactical_records"]
            event_split_counts[split] += summary["event_records"]
            attack_split_counts.update(summary["attack_split_counts"])
            action_counts.update(summary["primary_action_counts"])
            rear_threat_level_counts.update(summary["rear_threat_level_counts"])
            yield_vs_fight_counts.update(summary["yield_vs_fight_counts"])
            event_impact_counts.update(summary["event_impact_counts"])
            attack_commit_counts.update(summary["attack_commit_counts"])
            record_count += summary["records"]
            tactical_record_count += summary["tactical_records"]
            event_record_count += summary["event_records"]
            attack_record_count += summary["attack_records"]

    return {
        "dataset_name": output_dir.name,
        "sample_metadata_path": str(sample_metadata_path),
        "features_path": str(features_path),
        "labels_path": str(labels_path),
        "tactical_features_path": str(tactical_features_path),
        "event_features_path": str(event_features_path),
        "attack_features_path": str(attack_features_path),
        "record_count": record_count,
        "tactical_record_count": tactical_record_count,
        "event_record_count": event_record_count,
        "attack_record_count": attack_record_count,
        "split_counts": dict(split_counts),
        "tactical_split_counts": dict(tactical_split_counts),
        "event_split_counts": dict(event_split_counts),
        "attack_split_counts": dict(attack_split_counts),
        "primary_action_counts": dict(action_counts.most_common()),
        "rear_threat_level_counts": dict(rear_threat_level_counts.most_common()),
        "yield_vs_fight_counts": dict(yield_vs_fight_counts.most_common()),
        "event_impact_counts": dict(event_impact_counts.most_common()),
        "attack_commit_counts": dict(attack_commit_counts.most_common()),
        "samples": sample_summaries,
        "notes": {
            "timing_policy": "official_only_in_main_features",
            "estimated_fields": "debug_only",
            "labels": "first_pass_pseudo_labels_from_strategy_and_transition_events",
            "tactical_rows": "official timing only, filtered for rear-threat/defence/counterattack work",
            "event_rows": "event transition only, excluding debug-only button events",
            "attack_rows": "official front-gap rows in race-like sessions, filtered for attack-opportunity and attack-commit work",
            "attack_split_policy": "uid15 lap 2 reserved as exported val for attack-chain models; uid15 lap 1/3 remain train; uid16 remains test",
        },
    }


def export_sample(
    *,
    sample: dict[str, Any],
    split: str,
    feature_writer: csv.DictWriter,
    label_writer: csv.DictWriter,
    tactical_writer: csv.DictWriter,
    event_writer: csv.DictWriter,
    attack_writer: csv.DictWriter,
    next_segment_offsets: list[float],
    max_history_frames: int,
    sample_limit: int | None,
) -> dict[str, Any]:
    """Export one session sample into full and tactical tables."""

    config = AppConfig()
    strategy = StrategyEngine(config.thresholds, config.usage_hooks_path)
    state_store = UnifiedStateStore(maxlen=max_history_frames)
    source = CaptureJsonlSource(Path(sample["file_path"]))
    decoder = F125PacketDecoder()
    assembler = CaptureSnapshotAssembler()
    track_profile = None

    records = 0
    tactical_records = 0
    event_records = 0
    attack_records = 0
    primary_action_counts: Counter[str] = Counter()
    rear_threat_level_counts: Counter[str] = Counter()
    yield_vs_fight_counts: Counter[str] = Counter()
    event_impact_counts: Counter[str] = Counter()
    attack_commit_counts: Counter[str] = Counter()
    attack_split_counts: Counter[str] = Counter()
    tactical_filter_reasons: Counter[str] = Counter()
    event_filter_reasons: Counter[str] = Counter()
    attack_filter_reasons: Counter[str] = Counter()
    sample_rows: list[dict[str, dict[str, Any]]] = []
    tactical_indices: list[int] = []
    event_indices: list[int] = []
    attack_indices: list[int] = []

    for packet in source:
        try:
            envelope = decoder.decode_raw(packet)
        except PacketDecodeError:
            continue

        normalized = assembler.push(envelope)
        if normalized is None:
            continue

        state = decode_snapshot(normalized)
        state_store.update(state)
        recent_states = state_store.recent(max_history_frames)
        decision = strategy.evaluate(state, recent_states)
        previous_state = state_store.previous()
        if track_profile is None:
            track_profile = load_track_profile(state.track)

        feature_row = build_feature_row(
            state=state,
            decision=decision,
            previous_state=previous_state,
            recent_states=recent_states,
            sample=sample,
            split=split,
            next_segment_offsets=next_segment_offsets,
            track_profile=track_profile,
        )
        label_row = build_label_row(
            state=state,
            decision=decision,
            previous_state=previous_state,
            sample=sample,
            split=split,
        )

        feature_writer.writerow({column: feature_row.get(column) for column in FEATURE_COLUMNS})
        label_writer.writerow({column: label_row.get(column) for column in LABEL_COLUMNS})
        sample_rows.append({"feature": feature_row, "label": label_row})
        records += 1
        primary_action_counts[label_row["primary_action_label"]] += 1

        include_tactical, reason = should_include_tactical_row(feature_row=feature_row, label_row=label_row)
        tactical_filter_reasons[reason] += 1
        if include_tactical:
            tactical_indices.append(len(sample_rows) - 1)
        include_event, event_reason = should_include_event_row(feature_row=feature_row)
        event_filter_reasons[event_reason] += 1
        if include_event:
            event_indices.append(len(sample_rows) - 1)
        include_attack, attack_reason = should_include_attack_row(feature_row=feature_row, label_row=label_row)
        attack_filter_reasons[attack_reason] += 1
        if include_attack:
            attack_indices.append(len(sample_rows) - 1)

        if sample_limit is not None and records >= sample_limit:
            break

    for row_index in tactical_indices:
        row_bundle = sample_rows[row_index]
        tactical_row = build_tactical_feature_row(
            feature_row=row_bundle["feature"],
            label_row=row_bundle["label"],
            sample_rows=sample_rows,
            row_index=row_index,
        )
        tactical_writer.writerow(tactical_row)
        tactical_records += 1
        rear_threat_level_counts[tactical_row["rear_threat_level_label"]] += 1
        yield_vs_fight_counts[tactical_row["yield_vs_fight_proxy_label"]] += 1

    for row_index in event_indices:
        row_bundle = sample_rows[row_index]
        event_row = build_event_feature_row(
            feature_row=row_bundle["feature"],
            label_row=row_bundle["label"],
            sample_rows=sample_rows,
            row_index=row_index,
        )
        event_writer.writerow(event_row)
        event_records += 1
        event_impact_counts[event_row["event_strategy_shift_label"]] += 1

    for row_index in attack_indices:
        row_bundle = sample_rows[row_index]
        attack_rows = build_attack_feature_rows(
            feature_row=row_bundle["feature"],
            label_row=row_bundle["label"],
            sample_rows=sample_rows,
            row_index=row_index,
        )
        for attack_row in attack_rows:
            attack_writer.writerow(attack_row)
            attack_records += 1
            attack_commit_counts[attack_row["attack_followthrough_label"]] += 1
            attack_split_counts[attack_row["split"]] += 1

    return {
        "sample_name": sample["sample_name"],
        "split": split,
        "records": records,
        "tactical_records": tactical_records,
        "event_records": event_records,
        "attack_records": attack_records,
        "session_label": sample["session_label"],
        "session_type_code": sample["session_type_code"],
        "primary_action_counts": dict(primary_action_counts.most_common()),
        "rear_threat_level_counts": dict(rear_threat_level_counts.most_common()),
        "yield_vs_fight_counts": dict(yield_vs_fight_counts.most_common()),
        "event_impact_counts": dict(event_impact_counts.most_common()),
        "attack_commit_counts": dict(attack_commit_counts.most_common()),
        "attack_split_counts": dict(attack_split_counts.most_common()),
        "tactical_filter_reasons": dict(tactical_filter_reasons.most_common()),
        "event_filter_reasons": dict(event_filter_reasons.most_common()),
        "attack_filter_reasons": dict(attack_filter_reasons.most_common()),
    }


def build_feature_row(
    *,
    state,
    decision,
    previous_state,
    recent_states,
    sample: dict[str, Any],
    split: str,
    next_segment_offsets: list[float],
    track_profile,
) -> dict[str, Any]:
    """Build one flat feature row from the normalized state plus context."""

    raw = state.raw
    context = decision.debug.get("context", {})
    front_rival = closest_rival(state, offset=-1)
    rear_rival = closest_rival(state, offset=1)

    session_time_s = optional_float(raw.get("session_time_s"))
    gap_closing_rate_ahead = closing_rate_from_recent_history(
        recent_states=recent_states,
        current_gap=state.player.gap_ahead_s,
        current_session_time_s=session_time_s,
        gap_side="ahead",
    )
    gap_closing_rate_behind = closing_rate_from_recent_history(
        recent_states=recent_states,
        current_gap=state.player.gap_behind_s,
        current_session_time_s=session_time_s,
        gap_side="behind",
    )

    next_segment, next_usage, next_two_segments = preview_segments(
        track_profile=track_profile,
        lap_distance_m=optional_float(raw.get("lap_distance_m")) or 0.0,
        offsets=next_segment_offsets,
    )

    wheel_slip = list(raw.get("wheel_slip_ratio", []))
    rear_threat_zone_flag = int((context.get("track_zone") or "") == "braking_entry")
    attack_zone_flag = int((context.get("track_usage") or "") in {"primary_overtake_deploy", "overtake_setup", "primary_ers_deploy"})
    counterattack_zone_flag = int(next_usage in {"primary_overtake_deploy", "overtake_setup", "ers_prepare"})
    drs_recovery_window = int(
        optional_float(raw.get("official_gap_ahead_s")) is not None
        and (optional_float(raw.get("official_gap_ahead_s")) or 0.0) <= 1.2
    )
    defence_cost_proxy = compute_defence_cost_proxy(
        ers_pct=state.player.ers_pct,
        tyre_wear_pct=state.player.tyre.wear_pct,
        recent_front_overload_ratio=optional_float(context.get("recent_front_overload_ratio")) or 0.0,
        track_usage=context.get("track_usage") or "",
        speed_kph=state.player.speed_kph,
    )
    rear_rival_pressure_proxy = compute_rear_rival_pressure_proxy(
        official_gap_behind_s=optional_float(raw.get("official_gap_behind_s")),
        gap_closing_rate_behind=gap_closing_rate_behind,
        rear_rival_speed_delta=speed_delta(rear_rival.get("speed_kph"), state.player.speed_kph),
        rear_rival_ers_pct=optional_float(rear_rival.get("ers_pct")),
        rear_rival_drs_available=bool(rear_rival.get("drs_available")),
    )
    event_code = raw.get("event_code")
    previous_event_code = previous_state.raw.get("event_code") if previous_state is not None else None
    event_code_started = int(bool(event_code) and event_code != "NONE" and event_code != previous_event_code)
    record_id = f"{state.session_uid}:{raw.get('frame_identifier', 0)}"

    return {
        "record_id": record_id,
        "split": split,
        "sample_name": sample["sample_name"],
        "session_uid": state.session_uid,
        "frame_identifier": raw.get("frame_identifier"),
        "overall_frame_identifier": raw.get("overall_frame_identifier"),
        "source_timestamp_ms": state.source_timestamp_ms,
        "session_time_s": session_time_s,
        "track": state.track,
        "session_type": raw.get("session_type"),
        "timing_mode": raw.get("timing_mode"),
        "timing_support_level": raw.get("timing_support_level"),
        "lap_number": state.lap_number,
        "total_laps": state.total_laps,
        "weather": state.weather,
        "safety_car": state.safety_car,
        "player_name": state.player.name,
        "player_position": state.player.position,
        "position_lost_recently": int(previous_state is not None and state.player.position > previous_state.player.position),
        "position_gain_recently": int(previous_state is not None and state.player.position < previous_state.player.position),
        "lap_distance_m": raw.get("lap_distance_m"),
        "total_distance_m": raw.get("total_distance_m"),
        "current_lap_time_ms": raw.get("current_lap_time_ms"),
        "last_lap_time_ms": raw.get("last_lap_time_ms"),
        "sector1_time_ms": raw.get("sector1_time_ms"),
        "sector2_time_ms": raw.get("sector2_time_ms"),
        "official_gap_ahead_s": raw.get("official_gap_ahead_s"),
        "official_gap_behind_s": raw.get("official_gap_behind_s"),
        "official_gap_confidence_ahead": raw.get("official_gap_confidence_ahead"),
        "official_gap_confidence_behind": raw.get("official_gap_confidence_behind"),
        "official_gap_source_ahead": raw.get("official_gap_source_ahead"),
        "official_gap_source_behind": raw.get("official_gap_source_behind"),
        "estimated_gap_ahead_s": raw.get("estimated_gap_ahead_s"),
        "estimated_gap_behind_s": raw.get("estimated_gap_behind_s"),
        "gap_closing_rate_ahead": gap_closing_rate_ahead,
        "gap_closing_rate_behind": gap_closing_rate_behind,
        "speed_kph": state.player.speed_kph,
        "throttle": raw.get("throttle"),
        "brake": raw.get("brake"),
        "steer": raw.get("steer"),
        "gear": raw.get("gear"),
        "rpm": raw.get("rpm"),
        "fuel_in_tank": raw.get("fuel_in_tank"),
        "fuel_capacity": raw.get("fuel_capacity"),
        "fuel_laps_remaining": state.player.fuel_laps_remaining,
        "ers_store_energy": raw.get("ers_store_energy"),
        "ers_pct": state.player.ers_pct,
        "ers_deploy_mode": raw.get("ers_deploy_mode"),
        "drs_available": int(state.player.drs_available),
        "tyre_compound": state.player.tyre.compound,
        "tyre_wear_pct": state.player.tyre.wear_pct,
        "tyre_age_laps": state.player.tyre.age_laps,
        "status_tags": "|".join(state.player.status_tags),
        "g_force_lateral": raw.get("g_force_lateral"),
        "g_force_longitudinal": raw.get("g_force_longitudinal"),
        "g_force_vertical": raw.get("g_force_vertical"),
        "yaw": raw.get("yaw"),
        "pitch": raw.get("pitch"),
        "roll": raw.get("roll"),
        "wheel_slip_ratio_fl": array_item(wheel_slip, 0),
        "wheel_slip_ratio_fr": array_item(wheel_slip, 1),
        "wheel_slip_ratio_rl": array_item(wheel_slip, 2),
        "wheel_slip_ratio_rr": array_item(wheel_slip, 3),
        "track_zone": context.get("track_zone"),
        "track_segment": context.get("track_segment"),
        "track_usage": context.get("track_usage"),
        "next_track_segment": next_segment,
        "next_track_usage": next_usage,
        "next_two_segments": next_two_segments,
        "driving_mode": context.get("driving_mode"),
        "recent_unstable_ratio": context.get("recent_unstable_ratio"),
        "recent_front_overload_ratio": context.get("recent_front_overload_ratio"),
        "tyre_age_factor": context.get("tyre_age_factor"),
        "brake_phase_factor": context.get("brake_phase_factor"),
        "throttle_phase_factor": context.get("throttle_phase_factor"),
        "steering_phase_factor": context.get("steering_phase_factor"),
        "front_rival_name": front_rival.get("name"),
        "front_rival_position": front_rival.get("position"),
        "front_rival_speed_kph": front_rival.get("speed_kph"),
        "front_rival_ers_pct": front_rival.get("ers_pct"),
        "front_rival_speed_delta": speed_delta(state.player.speed_kph, front_rival.get("speed_kph")),
        "rear_rival_name": rear_rival.get("name"),
        "rear_rival_position": rear_rival.get("position"),
        "rear_rival_speed_kph": rear_rival.get("speed_kph"),
        "rear_rival_ers_pct": rear_rival.get("ers_pct"),
        "rear_rival_drs_available": int(bool(rear_rival.get("drs_available"))) if rear_rival else None,
        "rear_rival_speed_delta": speed_delta(rear_rival.get("speed_kph"), state.player.speed_kph),
        "rear_rival_fuel_laps_remaining": rear_rival.get("fuel_laps_remaining"),
        "rear_rival_tyre_wear_pct": (rear_rival.get("tyre") or {}).get("wear_pct") if rear_rival else None,
        "rear_rival_tyre_age_laps": (rear_rival.get("tyre") or {}).get("age_laps") if rear_rival else None,
        "rear_threat_zone_flag": rear_threat_zone_flag,
        "attack_zone_flag": attack_zone_flag,
        "counterattack_zone_flag": counterattack_zone_flag,
        "drs_recovery_window": drs_recovery_window,
        "defence_cost_proxy": defence_cost_proxy,
        "rear_rival_pressure_proxy": rear_rival_pressure_proxy,
        "event_code": event_code,
        "event_code_started": event_code_started,
        "event_detail_kind": summarize_event_detail_kind(event_code=event_code, event_detail=raw.get("event_detail") or {}),
    }


def build_label_row(
    *,
    state,
    decision,
    previous_state,
    sample: dict[str, Any],
    split: str,
) -> dict[str, Any]:
    """Build one first-pass pseudo-label row from strategy debug output."""

    assessment = decision.debug.get("assessment", {})
    risk_profile = decision.debug.get("risk_profile", {})
    messages = decision.messages
    action_codes = [item.code if hasattr(item, "code") else item.get("code") for item in messages]
    primary_action = action_codes[0] if action_codes else "NONE"
    raw = state.raw
    record_id = f"{state.session_uid}:{raw.get('frame_identifier', 0)}"

    return {
        "record_id": record_id,
        "split": split,
        "sample_name": sample["sample_name"],
        "session_uid": state.session_uid,
        "frame_identifier": raw.get("frame_identifier"),
        "session_type": raw.get("session_type"),
        "timing_support_level": raw.get("timing_support_level"),
        "fuel_state_label": assessment.get("fuel_state"),
        "tyre_state_label": assessment.get("tyre_state"),
        "ers_state_label": assessment.get("ers_state"),
        "race_state_label": assessment.get("race_state"),
        "attack_state_label": assessment.get("attack_state"),
        "defend_state_label": assessment.get("defend_state"),
        "dynamics_state_label": assessment.get("dynamics_state"),
        "fuel_risk_label": risk_profile.get("fuel_risk"),
        "tyre_risk_label": risk_profile.get("tyre_risk"),
        "ers_risk_label": risk_profile.get("ers_risk"),
        "race_control_risk_label": risk_profile.get("race_control_risk"),
        "dynamics_risk_label": risk_profile.get("dynamics_risk"),
        "attack_opportunity_label": risk_profile.get("attack_opportunity"),
        "defend_risk_label": risk_profile.get("defend_risk"),
        "primary_action_label": primary_action,
        "action_codes": "|".join(action_codes),
        "position_lost_event_label": int(previous_state is not None and state.player.position > previous_state.player.position),
        "position_gain_event_label": int(previous_state is not None and state.player.position < previous_state.player.position),
        "official_gap_available_ahead_label": int(raw.get("official_gap_ahead_s") is not None),
        "official_gap_available_behind_label": int(raw.get("official_gap_behind_s") is not None),
        "event_code_label": raw.get("event_code") or "NONE",
    }


def build_tactical_feature_row(
    *,
    feature_row: dict[str, Any],
    label_row: dict[str, Any],
    sample_rows: list[dict[str, dict[str, Any]]],
    row_index: int,
) -> dict[str, Any]:
    """Build a focused tactical row for rear-threat / defend / counterattack work."""

    rear_threat_binary_label, rear_threat_level_label = derive_rear_threat_labels(feature_row)
    row = {column: feature_row.get(column) for column in TACTICAL_FEATURE_COLUMNS if column in feature_row}
    row.update(
        {
            "rear_threat_binary_label": rear_threat_binary_label,
            "rear_threat_level_label": rear_threat_level_label,
            "yield_vs_fight_proxy_label": derive_yield_vs_fight_proxy_label(
                feature_row=feature_row,
                label_row=label_row,
                sample_rows=sample_rows,
                row_index=row_index,
            ),
            "counterattack_candidate_label": derive_counterattack_candidate_label(feature_row, label_row),
            "primary_action_label": label_row["primary_action_label"],
        }
    )
    return row


def build_event_feature_row(
    *,
    feature_row: dict[str, Any],
    label_row: dict[str, Any],
    sample_rows: list[dict[str, dict[str, Any]]],
    row_index: int,
) -> dict[str, Any]:
    """Build a focused event row for event-impact modeling."""

    event_impact_binary_label, event_strategy_shift_label = derive_event_impact_labels(
        feature_row=feature_row,
        label_row=label_row,
        sample_rows=sample_rows,
        row_index=row_index,
    )
    row = {column: feature_row.get(column) for column in EVENT_FEATURE_COLUMNS if column in feature_row}
    row.update(
        {
            "primary_action_label": label_row.get("primary_action_label"),
            "attack_opportunity_label": label_row.get("attack_opportunity_label"),
            "defend_risk_label": label_row.get("defend_risk_label"),
            "dynamics_risk_label": label_row.get("dynamics_risk_label"),
            "event_impact_binary_label": event_impact_binary_label,
            "event_strategy_shift_label": event_strategy_shift_label,
        }
    )
    return row


def build_attack_feature_rows(
    *,
    feature_row: dict[str, Any],
    label_row: dict[str, Any],
    sample_rows: list[dict[str, dict[str, Any]]],
    row_index: int,
) -> list[dict[str, Any]]:
    """Build focused attack rows from player and immediate-rear-rival perspectives."""

    rows: list[dict[str, Any]] = []

    player_row = build_single_attack_feature_row(
        actor_view="player",
        feature_row=feature_row,
        label_row=label_row,
        sample_rows=sample_rows,
        row_index=row_index,
    )
    if player_row is not None:
        rows.append(player_row)

    rival_row = build_single_attack_feature_row(
        actor_view="rear_rival",
        feature_row=feature_row,
        label_row=label_row,
        sample_rows=sample_rows,
        row_index=row_index,
    )
    if rival_row is not None:
        rows.append(rival_row)

    return rows


def build_single_attack_feature_row(
    *,
    actor_view: str,
    feature_row: dict[str, Any],
    label_row: dict[str, Any],
    sample_rows: list[dict[str, dict[str, Any]]],
    row_index: int,
) -> dict[str, Any] | None:
    """Build one attack row for a specific actor perspective."""

    actor_feature = attack_actor_projection(actor_view=actor_view, feature_row=feature_row)
    if actor_feature is None:
        return None

    attack_opportunity_binary_label, attack_opportunity_level_label = derive_attack_opportunity_labels(
        feature_row=actor_feature,
        label_row=label_row,
        sample_rows=sample_rows,
        row_index=row_index,
        actor_view=actor_view,
    )
    attack_commit_binary_label, attack_followthrough_label = derive_front_attack_commit_labels(
        feature_row=actor_feature,
        label_row=label_row,
        sample_rows=sample_rows,
        row_index=row_index,
        actor_view=actor_view,
    )
    row = {column: actor_feature.get(column) for column in ATTACK_FEATURE_COLUMNS if column in actor_feature}
    row["split"] = derive_attack_split(actor_feature)
    row.update(
        {
            "actor_view": actor_view,
            "attack_opportunity_proxy_label": attack_opportunity_binary_label,
            "attack_opportunity_level_label": attack_opportunity_level_label,
            "attack_commit_proxy_label": attack_commit_binary_label,
            "attack_followthrough_label": attack_followthrough_label,
            "primary_action_label": label_row.get("primary_action_label"),
            "attack_opportunity_label": label_row.get("attack_opportunity_label"),
        }
    )
    return row


def derive_attack_split(feature_row: dict[str, Any]) -> str:
    """Assign a deterministic exported split for attack-chain models.

    备注:
    当前攻击链只有 `uid15` 和 `uid16` 两段 race-like 样本。
    为避免训练脚本继续依赖随机 holdout，这里把 `uid15` 的第 2 圈固定切成 exported val，
    第 1/3 圈保留为 train，`uid16` 保持 test。
    """

    base_split = str(feature_row.get("split") or "train")
    if base_split != "train":
        return base_split

    session_type = str(feature_row.get("session_type") or "")
    lap_number = int(feature_row.get("lap_number") or 0)
    if "SprintRaceLike" in session_type and lap_number == 2:
        return "val"
    return "train"


def should_include_tactical_row(*, feature_row: dict[str, Any], label_row: dict[str, Any]) -> tuple[bool, str]:
    """Filter rows so tactical exports focus on real tactical situations."""

    if feature_row["timing_support_level"] != "official_preferred":
        return False, "non_official_timing"
    session_type = str(feature_row.get("session_type") or "")
    if "RaceLike" not in session_type:
        return False, "non_race_like_session"
    if feature_row["official_gap_behind_s"] is not None:
        return True, "official_gap_behind"
    if feature_row["position_lost_recently"] or feature_row["position_gain_recently"]:
        return True, "position_change_event"
    if label_row["primary_action_label"] in {"DEFEND_WINDOW", "ATTACK_WINDOW"}:
        return True, "strategy_action"
    return False, "background_frame"


def should_include_event_row(*, feature_row: dict[str, Any]) -> tuple[bool, str]:
    """Keep only actual event transition rows, not cached latest-event carry-over."""

    event_code = feature_row.get("event_code")
    if not feature_row.get("event_code_started"):
        return False, "no_new_event"
    if event_code in {None, "", "NONE"}:
        return False, "missing_event_code"
    if event_code == "BUTN":
        return False, "button_event"
    return True, "event_transition"


def should_include_attack_row(*, feature_row: dict[str, Any], label_row: dict[str, Any]) -> tuple[bool, str]:
    """Keep official front-gap rows that are plausible attack setup situations."""

    if feature_row["timing_support_level"] != "official_preferred":
        return False, "non_official_timing"
    session_type = str(feature_row.get("session_type") or "")
    if "RaceLike" not in session_type:
        return False, "non_race_like_session"
    if feature_row.get("official_gap_behind_s") not in ("", None) and feature_row.get("official_gap_confidence_behind") == "high":
        return True, "rear_rival_official_gap_ahead"
    gap_ahead = optional_float(feature_row.get("official_gap_ahead_s"))
    if gap_ahead is None:
        return False, "missing_official_gap_ahead"
    if feature_row.get("official_gap_confidence_ahead") != "high":
        return False, "low_gap_confidence"
    if gap_ahead <= 2.0:
        return True, "official_gap_ahead"
    if label_row["primary_action_label"] == "ATTACK_WINDOW":
        return True, "strategy_attack_action"
    return False, "background_frame"


def derive_rear_threat_labels(feature_row: dict[str, Any]) -> tuple[int, str]:
    """Create first-pass rear-threat labels from official timing and pace context."""

    gap = optional_float(feature_row.get("official_gap_behind_s"))
    confidence = feature_row.get("official_gap_confidence_behind")
    closing = optional_float(feature_row.get("gap_closing_rate_behind")) or 0.0
    speed_delta_value = optional_float(feature_row.get("rear_rival_speed_delta")) or 0.0
    drs_available = bool(feature_row.get("rear_rival_drs_available"))
    zone_flag = int(feature_row.get("rear_threat_zone_flag") or 0)

    if gap is None or confidence != "high":
        return 0, "none"
    if gap <= 0.65 and (closing >= 0.02 or speed_delta_value >= 4.0 or drs_available):
        return 1, "immediate"
    if gap <= 0.95 and ((closing >= 0.01 and speed_delta_value >= 1.0) or (zone_flag and speed_delta_value >= 8.0)):
        return 1, "building"
    return 0, "none"


def derive_yield_vs_fight_proxy_label(
    *,
    feature_row: dict[str, Any],
    label_row: dict[str, Any],
    sample_rows: list[dict[str, dict[str, Any]]],
    row_index: int,
) -> str:
    """Create a defend-vs-yield label from near-future race outcome instead of pure cost proxy.

    备注:
    这里不再主要靠 `defence_cost_proxy` 直接给标签。
    当前标签更关注：
    1. 当前是否处于防守窗口
    2. 当前区段是否适合硬防
    3. 未来 1.5 秒内是否失位
    4. 失位后是否仍保有反击恢复条件
    """

    if label_row["primary_action_label"] != "DEFEND_WINDOW":
        if feature_row.get("position_lost_recently"):
            return "yield_and_counter"
        return "neutral"

    outcome = inspect_future_position_outcome(sample_rows=sample_rows, row_index=row_index, lookahead_s=1.5)
    official_gap_behind_s = optional_float(feature_row.get("official_gap_behind_s")) or 99.0
    rear_rival_speed_delta = optional_float(feature_row.get("rear_rival_speed_delta")) or 0.0
    rear_threat_zone_flag = int(feature_row.get("rear_threat_zone_flag") or 0)
    strong_yield_layout = official_gap_behind_s >= 0.55 and rear_rival_speed_delta >= 4.0 and rear_threat_zone_flag == 0

    if outcome["lost_position_soon"]:
        return "yield_and_counter"

    if strong_yield_layout:
        return "yield_and_counter"

    if outcome["held_position_window"]:
        return "defend"
    return "defend"


def derive_counterattack_candidate_label(feature_row: dict[str, Any], label_row: dict[str, Any]) -> int:
    """Create a cheap proxy label for counterattack-window work."""

    if not feature_row.get("position_lost_recently"):
        return 0
    if int(feature_row.get("counterattack_zone_flag") or 0) and int(feature_row.get("drs_recovery_window") or 0):
        return 1
    if label_row["primary_action_label"] == "ATTACK_WINDOW":
        return 1
    return 0


def derive_front_attack_commit_labels(
    *,
    feature_row: dict[str, Any],
    label_row: dict[str, Any],
    sample_rows: list[dict[str, dict[str, Any]]],
    row_index: int,
    actor_view: str,
) -> tuple[int, str]:
    """Create first-pass labels for front-attack commitment using short-horizon gain or strong setup."""

    outcome = inspect_future_attack_outcome(
        sample_rows=sample_rows,
        row_index=row_index,
        lookahead_s=2.0,
        actor_view=actor_view,
    )
    gap_ahead = optional_float(feature_row.get("official_gap_ahead_s")) or 99.0
    speed_delta = optional_float(feature_row.get("front_rival_speed_delta")) or 0.0
    ers_pct = optional_float(feature_row.get("ers_pct")) or 0.0
    drs_available = int(feature_row.get("drs_available") or 0)
    tyre_wear_pct = optional_float(feature_row.get("tyre_wear_pct")) or 0.0
    unstable_ratio = optional_float(feature_row.get("recent_unstable_ratio")) or 0.0
    next_usage = feature_row.get("next_track_usage") or ""
    next_usage_commit = next_usage in {"primary_overtake_deploy", "overtake_setup", "primary_ers_deploy"}

    hard_commit_setup = (
        gap_ahead <= 0.7
        and speed_delta >= 2.8
        and ers_pct >= 32.0
        and tyre_wear_pct <= 58.0
        and unstable_ratio <= 0.32
        and (drs_available == 1 or next_usage_commit)
    )
    if outcome["gained_position_soon"] and hard_commit_setup:
        return 1, "commit"

    commit_followthrough_setup = (
        gap_ahead <= 0.78
        and speed_delta >= 2.5
        and ers_pct >= 28.0
        and tyre_wear_pct <= 62.0
        and unstable_ratio <= 0.35
        and (drs_available == 1 or next_usage_commit)
    )
    if (
        commit_followthrough_setup
        and outcome["closed_gap_strongly"]
        and outcome["sustained_attack_pressure"]
        and outcome["held_attack_gap_window"]
    ):
        return 1, "commit"
    return 0, "hold"


def derive_attack_opportunity_labels(
    *,
    feature_row: dict[str, Any],
    label_row: dict[str, Any],
    sample_rows: list[dict[str, dict[str, Any]]],
    row_index: int,
    actor_view: str,
) -> tuple[int, str]:
    """Create first-pass front-attack opportunity labels from future gain and current setup."""

    outcome = inspect_future_attack_outcome(
        sample_rows=sample_rows,
        row_index=row_index,
        lookahead_s=2.0,
        actor_view=actor_view,
    )
    gap_ahead = optional_float(feature_row.get("official_gap_ahead_s")) or 99.0
    speed_delta = optional_float(feature_row.get("front_rival_speed_delta")) or 0.0
    ers_pct = optional_float(feature_row.get("ers_pct")) or 0.0
    unstable_ratio = optional_float(feature_row.get("recent_unstable_ratio")) or 0.0
    attack_zone_flag = int(feature_row.get("attack_zone_flag") or 0)
    drs_available = int(feature_row.get("drs_available") or 0)
    next_usage = feature_row.get("next_track_usage") or ""

    if outcome["gained_position_soon"]:
        return 1, "immediate"

    strong_setup = (
        gap_ahead <= 0.9
        and speed_delta >= 2.0
        and ers_pct >= 25.0
        and unstable_ratio <= 0.4
        and (attack_zone_flag == 1 or drs_available == 1 or next_usage in {"primary_overtake_deploy", "overtake_setup", "primary_ers_deploy"})
    )
    if outcome["closed_gap_strongly"] and strong_setup:
        return 1, "building"
    if strong_setup and gap_ahead <= 0.65:
        return 1, "building"
    return 0, "none"


def derive_event_impact_labels(
    *,
    feature_row: dict[str, Any],
    label_row: dict[str, Any],
    sample_rows: list[dict[str, dict[str, Any]]],
    row_index: int,
) -> tuple[int, str]:
    """Create a first-pass event-impact label from short-horizon state and action changes."""

    outcome = inspect_future_event_impact(sample_rows=sample_rows, row_index=row_index, lookahead_s=2.0)
    if outcome["position_changed"]:
        return 1, "position_change"
    if outcome["strategy_shift_label"] != "neutral":
        return 1, outcome["strategy_shift_label"]
    if outcome["risk_spike"]:
        return 1, "risk_shift"
    return 0, "neutral"


def inspect_future_event_impact(
    *,
    sample_rows: list[dict[str, dict[str, Any]]],
    row_index: int,
    lookahead_s: float,
) -> dict[str, Any]:
    """Inspect short-horizon future rows to derive event impact labels."""

    current_feature = sample_rows[row_index]["feature"]
    current_label = sample_rows[row_index]["label"]
    current_time = optional_float(current_feature.get("session_time_s"))
    current_position = int(current_feature.get("player_position") or 0)
    current_primary_action = current_label.get("primary_action_label") or "NONE"
    current_attack_opportunity = optional_float(current_label.get("attack_opportunity_label")) or 0.0
    current_defend_risk = optional_float(current_label.get("defend_risk_label")) or 0.0
    current_dynamics_risk = optional_float(current_label.get("dynamics_risk_label")) or 0.0
    if current_time is None:
        return {
            "position_changed": False,
            "strategy_shift_label": "neutral",
            "risk_spike": False,
        }

    future_rows: list[dict[str, dict[str, Any]]] = []
    for later in sample_rows[row_index + 1 :]:
        later_feature = later["feature"]
        later_time = optional_float(later_feature.get("session_time_s"))
        if later_time is None:
            continue
        if later_time - current_time > lookahead_s:
            break
        future_rows.append(later)

    if not future_rows:
        return {
            "position_changed": False,
            "strategy_shift_label": "neutral",
            "risk_spike": False,
        }

    position_changed = any(int(row["feature"].get("player_position") or 0) != current_position for row in future_rows)
    strategy_shift_label = "neutral"
    risk_spike = False
    for row in future_rows:
        later_label = row["label"]
        later_primary_action = later_label.get("primary_action_label") or "NONE"
        if later_primary_action != current_primary_action and later_primary_action != "NONE":
            strategy_shift_label = classify_strategy_shift(later_primary_action)
            break

        later_attack = optional_float(later_label.get("attack_opportunity_label")) or 0.0
        later_defend = optional_float(later_label.get("defend_risk_label")) or 0.0
        later_dynamics = optional_float(later_label.get("dynamics_risk_label")) or 0.0
        if (
            abs(later_attack - current_attack_opportunity) >= 12.0
            or abs(later_defend - current_defend_risk) >= 12.0
            or abs(later_dynamics - current_dynamics_risk) >= 15.0
        ):
            risk_spike = True

    return {
        "position_changed": position_changed,
        "strategy_shift_label": strategy_shift_label,
        "risk_spike": risk_spike,
    }


def classify_strategy_shift(primary_action_label: str) -> str:
    """Map a future action code into a compact strategy-shift family."""

    if primary_action_label in {"DEFEND_WINDOW"}:
        return "defend"
    if primary_action_label in {"ATTACK_WINDOW"}:
        return "attack"
    if primary_action_label in {"TYRE_MANAGE", "ERS_LOW", "DYNAMICS_UNSTABLE", "LOW_FUEL", "BOX_WINDOW"}:
        return "stabilize"
    if primary_action_label in {"SAFETY_CAR"}:
        return "control"
    return "neutral"


def summarize_event_detail_kind(*, event_code: str | None, event_detail: dict[str, Any]) -> str:
    """Summarize event detail into a stable categorical feature."""

    if not event_code or event_code == "NONE":
        return "none"
    if event_code == "OVTK":
        return "overtake"
    if event_code == "COLL":
        return "collision"
    if event_code == "PENA":
        return "penalty"
    if event_code == "SPTP":
        return "speed_trap"
    if event_code in {"STLG", "LGOT", "SSTA"}:
        return "start_sequence"
    if event_code in {"DTSV", "SGSV"}:
        return "penalty_served"
    if event_code in {"FTLP"}:
        return "fastest_lap"
    if event_code in {"SCAR"}:
        return "safety_car"
    if event_detail:
        return "|".join(sorted(event_detail.keys()))
    return event_code.lower()


def inspect_future_position_outcome(
    *,
    sample_rows: list[dict[str, dict[str, Any]]],
    row_index: int,
    lookahead_s: float,
) -> dict[str, bool]:
    """Inspect short-horizon future frames to derive defend-vs-yield outcome hints."""

    current_feature = sample_rows[row_index]["feature"]
    current_time = optional_float(current_feature.get("session_time_s"))
    current_position = int(current_feature.get("player_position") or 0)
    if current_time is None or current_position <= 0:
        return {
            "lost_position_soon": False,
            "held_position_window": False,
            "recovery_window_after_loss": False,
        }

    future_rows = []
    for later in sample_rows[row_index + 1 :]:
        later_feature = later["feature"]
        later_time = optional_float(later_feature.get("session_time_s"))
        if later_time is None:
            continue
        if later_time - current_time > lookahead_s:
            break
        future_rows.append(later_feature)

    if not future_rows:
        return {
            "lost_position_soon": False,
            "held_position_window": False,
            "recovery_window_after_loss": False,
        }

    lost_position_soon = any(int(row.get("player_position") or 0) > current_position for row in future_rows)
    held_position_window = not lost_position_soon
    recovery_window_after_loss = False
    if lost_position_soon:
        for row in future_rows:
            if int(row.get("player_position") or 0) <= current_position:
                recovery_window_after_loss = True
                break
            official_gap_ahead_s = optional_float(row.get("official_gap_ahead_s"))
            if official_gap_ahead_s is not None and official_gap_ahead_s <= 1.2:
                recovery_window_after_loss = True
                break

    return {
        "lost_position_soon": lost_position_soon,
        "held_position_window": held_position_window,
        "recovery_window_after_loss": recovery_window_after_loss,
    }


def inspect_future_attack_outcome(
    *,
    sample_rows: list[dict[str, dict[str, Any]]],
    row_index: int,
    lookahead_s: float,
    actor_view: str,
) -> dict[str, bool]:
    """Inspect short-horizon future rows for front-attack payoff."""

    current_feature = sample_rows[row_index]["feature"]
    current_time = optional_float(current_feature.get("session_time_s"))
    if actor_view == "player":
        current_position = int(current_feature.get("player_position") or 0)
        current_gap_ahead = optional_float(current_feature.get("official_gap_ahead_s"))
    else:
        current_position = int(current_feature.get("rear_rival_position") or 0)
        current_gap_ahead = optional_float(current_feature.get("official_gap_behind_s"))
    if current_time is None or current_position <= 0:
        return {
            "gained_position_soon": False,
            "closed_gap_strongly": False,
            "sustained_attack_pressure": False,
            "held_attack_gap_window": False,
        }

    future_rows = []
    for later in sample_rows[row_index + 1 :]:
        later_feature = later["feature"]
        later_time = optional_float(later_feature.get("session_time_s"))
        if later_time is None:
            continue
        if later_time - current_time > lookahead_s:
            break
        future_rows.append(later_feature)

    if not future_rows:
        return {
            "gained_position_soon": False,
            "closed_gap_strongly": False,
            "sustained_attack_pressure": False,
            "held_attack_gap_window": False,
        }

    if actor_view == "player":
        gained_position_soon = any(int(row.get("player_position") or 0) < current_position for row in future_rows)
    else:
        gained_position_soon = any(int(row.get("player_position") or 0) > int(current_feature.get("player_position") or 0) for row in future_rows)
    closed_gap_strongly = False
    sustained_attack_pressure = False
    held_attack_gap_window = False
    if current_gap_ahead is not None:
        if actor_view == "player":
            future_gaps = [optional_float(row.get("official_gap_ahead_s")) for row in future_rows]
        else:
            future_gaps = [optional_float(row.get("official_gap_behind_s")) for row in future_rows]
        future_gaps = [gap for gap in future_gaps if gap is not None]
        if future_gaps:
            min_gap = min(future_gaps)
            closed_gap_strongly = (current_gap_ahead - min_gap) >= 0.35 or min_gap <= 0.45
            attack_window_gaps = [gap for gap in future_gaps if gap <= 0.65]
            held_attack_gap_window = len(attack_window_gaps) >= 2
            sustained_attack_pressure = (
                held_attack_gap_window
                or ((current_gap_ahead - min_gap) >= 0.25 and len([gap for gap in future_gaps if gap <= 0.8]) >= 3)
            )

    return {
        "gained_position_soon": gained_position_soon,
        "closed_gap_strongly": closed_gap_strongly,
        "sustained_attack_pressure": sustained_attack_pressure,
        "held_attack_gap_window": held_attack_gap_window,
    }


def attack_actor_projection(*, actor_view: str, feature_row: dict[str, Any]) -> dict[str, Any] | None:
    """Project one frame into player or immediate rear-rival attack perspective."""

    base = dict(feature_row)
    if actor_view == "player":
        base["actor_view"] = "player"
        base["actor_position"] = feature_row.get("player_position")
        return base

    rear_position = feature_row.get("rear_rival_position")
    rear_gap = feature_row.get("official_gap_behind_s")
    rear_conf = feature_row.get("official_gap_confidence_behind")
    if rear_position in ("", None) or rear_gap in ("", None) or rear_conf != "high":
        return None

    rival = dict(feature_row)
    rival["actor_view"] = "rear_rival"
    rival["actor_position"] = rear_position
    rival["position_gain_recently"] = feature_row.get("position_lost_recently")
    rival["official_gap_ahead_s"] = rear_gap
    rival["official_gap_confidence_ahead"] = rear_conf
    rival["gap_closing_rate_ahead"] = feature_row.get("gap_closing_rate_behind")
    rival["front_rival_position"] = feature_row.get("player_position")
    rival["front_rival_speed_kph"] = feature_row.get("speed_kph")
    rival["front_rival_ers_pct"] = feature_row.get("ers_pct")
    rival["front_rival_speed_delta"] = feature_row.get("rear_rival_speed_delta")
    rival["speed_kph"] = feature_row.get("rear_rival_speed_kph")
    rival["drs_available"] = feature_row.get("rear_rival_drs_available")
    rival["fuel_laps_remaining"] = feature_row.get("rear_rival_fuel_laps_remaining")
    rival["ers_pct"] = feature_row.get("rear_rival_ers_pct")
    rival["tyre_wear_pct"] = feature_row.get("rear_rival_tyre_wear_pct")
    rival["tyre_age_laps"] = feature_row.get("rear_rival_tyre_age_laps")
    return rival


def closest_rival(state, *, offset: int) -> dict[str, Any]:
    """Return the nearest front or rear rival by current race position."""

    target_position = state.player.position + offset
    for rival in state.rivals:
        if rival.position == target_position:
            return {
                "name": rival.name,
                "position": rival.position,
                "speed_kph": rival.speed_kph,
                "ers_pct": rival.ers_pct,
                "drs_available": rival.drs_available,
            }
    return {}


def preview_segments(*, track_profile, lap_distance_m: float, offsets: list[float]) -> tuple[str | None, str | None, str]:
    """Preview the next one or two semantic segments from the current lap distance."""

    if track_profile is None:
        return None, None, ""
    classifications = [track_profile.classify(lap_distance_m + offset) for offset in offsets]
    first = classifications[0] if classifications else None
    combined = " > ".join(item.zone_name for item in classifications if item.zone_name)
    return (
        first.zone_name if first is not None else None,
        first.usage if first is not None else None,
        combined,
    )


def closing_rate(previous_gap: float | None, current_gap: float | None, delta_t: float | None) -> float | None:
    """Return positive values when the gap is shrinking."""

    if previous_gap is None or current_gap is None or delta_t is None or delta_t <= 0:
        return None
    return (previous_gap - current_gap) / delta_t


def closing_rate_from_recent_history(
    *,
    recent_states: list[Any],
    current_gap: float | None,
    current_session_time_s: float | None,
    gap_side: str,
) -> float | None:
    """Estimate closing rate from a short official-gap window instead of a single-frame delta.

    备注:
    官方 gap 在逐帧上会出现长段重复值，单帧差分几乎全是 0。
    这里回看最近几帧，找最早的有效官方 gap 作为参考点，计算短窗口斜率。
    """

    if current_gap is None or current_session_time_s is None or len(recent_states) < 2:
        return None

    for candidate in reversed(recent_states[:-1]):
        candidate_session_time_s = optional_float(candidate.raw.get("session_time_s"))
        if candidate_session_time_s is None or candidate_session_time_s >= current_session_time_s:
            continue
        candidate_gap = candidate.player.gap_ahead_s if gap_side == "ahead" else candidate.player.gap_behind_s
        if candidate_gap is None:
            continue
        delta_t = current_session_time_s - candidate_session_time_s
        if delta_t <= 0:
            continue
        return (float(candidate_gap) - float(current_gap)) / delta_t
    return None


def speed_delta(primary: float | None, secondary: float | None) -> float | None:
    if primary is None or secondary is None:
        return None
    return float(primary) - float(secondary)


def compute_defence_cost_proxy(
    *,
    ers_pct: float,
    tyre_wear_pct: float,
    recent_front_overload_ratio: float,
    track_usage: str,
    speed_kph: float,
) -> float:
    """Approximate defence cost before a dedicated defence-cost model exists."""

    score = 0.0
    score += max(0.0, 35.0 - ers_pct) * 0.6
    score += max(0.0, tyre_wear_pct - 45.0) * 0.8
    score += recent_front_overload_ratio * 25.0
    if track_usage in {"front_tyre_protection", "maximum_brake_pressure", "lateral_load_management"}:
        score += 12.0
    if speed_kph >= 260.0:
        score += 8.0
    return round(min(score, 100.0), 2)


def compute_rear_rival_pressure_proxy(
    *,
    official_gap_behind_s: float | None,
    gap_closing_rate_behind: float | None,
    rear_rival_speed_delta: float | None,
    rear_rival_ers_pct: float | None,
    rear_rival_drs_available: bool,
) -> float:
    """Approximate rear-rival pressure before a dedicated model exists."""

    if official_gap_behind_s is None:
        return 0.0
    score = max(0.0, 2.0 - official_gap_behind_s) * 24.0
    score += max(0.0, gap_closing_rate_behind or 0.0) * 60.0
    score += max(0.0, rear_rival_speed_delta or 0.0) * 1.8
    score += max(0.0, (rear_rival_ers_pct or 0.0) - 40.0) * 0.2
    if rear_rival_drs_available:
        score += 12.0
    return round(min(score, 100.0), 2)


def optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def array_item(values: list[Any], index: int) -> float | None:
    if index >= len(values):
        return None
    return optional_float(values[index])


if __name__ == "__main__":
    raise SystemExit(main())
