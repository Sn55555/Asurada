from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .csv_ingest import build_dynamic_tags
from .pdu import PacketEnvelope

WEATHER_NAMES = {
    0: "Clear",
    1: "LightCloud",
    2: "Overcast",
    3: "LightRain",
    4: "HeavyRain",
    5: "Storm",
}

SAFETY_CAR_NAMES = {
    0: "NONE",
    1: "FULL",
    2: "VSC",
    3: "FORMATION",
}

SESSION_TYPE_NAMES = {
    0: "Unknown",
    1: "Time Trial",
    5: "Qualifying",
    10: "Race",
    8: "ShortResultLike(8)",
    13: "QualifyingLike(13)",
    15: "SprintRaceLike(15)",
    16: "FeatureRaceLike(16)",
}

TRACK_NAMES = {
    2: "Shanghai",
    13: "Suzuka",
    17: "Austria",
}

TYRE_COMPOUND_NAMES = {
    16: "C5",
    17: "C4",
    18: "C3",
    19: "C2",
    20: "C1",
    7: "Intermediate",
    8: "Wet",
}

PIT_STATUS_NAMES = {
    0: "NONE",
    1: "PITTING",
    2: "IN_PIT_AREA",
}


@dataclass
class FrameBundle:
    """Packets that belong to the same session_uid + frame_identifier."""

    session_uid: str
    frame_identifier: int
    packets: dict[str, dict[str, Any]] = field(default_factory=dict)


class CaptureSnapshotAssembler:
    """Assembles multi-packet F1 frames into one normalized snapshot.

    备注:
    这是 raw capture 和策略主链之间最关键的桥接层。
    上游处理协议包，下游只看标准化快照。
    """

    REQUIRED_FRAME_PACKETS = {"LapData", "CarTelemetry", "CarStatus", "Motion", "MotionEx", "CarDamage"}

    def __init__(self) -> None:
        self.latest_session_by_uid: dict[str, dict[str, Any]] = {}
        self.latest_session_header_by_uid: dict[str, dict[str, Any]] = {}
        self.latest_event_by_uid: dict[str, dict[str, Any]] = {}
        self.latest_participants_by_uid: dict[str, dict[str, Any]] = {}
        self.latest_lobby_info_by_uid: dict[str, dict[str, Any]] = {}
        self.latest_car_setups_by_uid: dict[str, dict[str, Any]] = {}
        self.latest_session_history_by_uid: dict[str, dict[str, Any]] = {}
        self.latest_final_classification_by_uid: dict[str, dict[str, Any]] = {}
        self.latest_lap_positions_by_uid: dict[str, dict[str, Any]] = {}
        self.session_start_fuel_by_uid: dict[str, float] = {}
        self.frames: dict[tuple[str, int], FrameBundle] = {}

    def push(self, envelope: PacketEnvelope) -> dict[str, Any] | None:
        # 备注:
        # Session / Participants / Event 作为跨帧上下文缓存；
        # 只有必需主包齐全时，才产出一个可消费快照。
        header = dict(envelope.payload.get("header", {}))
        body = dict(envelope.payload.get("body", {}))
        session_uid = str(envelope.session_uid or "unknown")

        if envelope.kind == "Session":
            if self._is_session_valid(body):
                self.latest_session_by_uid[session_uid] = body
                self.latest_session_header_by_uid[session_uid] = header
            return None
        if envelope.kind == "Participants":
            if body.get("all_cars"):
                self.latest_participants_by_uid[session_uid] = body
            return None
        if envelope.kind == "LobbyInfo":
            if body.get("all_players"):
                self.latest_lobby_info_by_uid[session_uid] = body
            return None
        if envelope.kind == "CarSetups":
            self.latest_car_setups_by_uid[session_uid] = body
            return None
        if envelope.kind == "SessionHistory":
            self.latest_session_history_by_uid[session_uid] = body
            return None
        if envelope.kind == "FinalClassification":
            self.latest_final_classification_by_uid[session_uid] = body
            return None
        if envelope.kind in {"LapPositions", "Unknown(15)"}:
            self.latest_lap_positions_by_uid[session_uid] = body
            return None
        if envelope.kind == "Event":
            self.latest_event_by_uid[session_uid] = body

        frame_identifier = header.get("frame_identifier")
        if frame_identifier is None:
            return None

        bundle_key = (session_uid, int(frame_identifier))
        bundle = self.frames.setdefault(
            bundle_key,
            FrameBundle(session_uid=session_uid, frame_identifier=int(frame_identifier)),
        )
        bundle.packets[envelope.kind] = {"header": header, "body": body}

        if session_uid not in self.latest_session_by_uid or not self.REQUIRED_FRAME_PACKETS.issubset(bundle.packets):
            self._prune_old_frames(session_uid=session_uid, newest_frame_identifier=int(frame_identifier))
            return None
        if not self._is_lap_valid(bundle, self.latest_session_by_uid[session_uid]):
            self._prune_old_frames(session_uid=session_uid, newest_frame_identifier=int(frame_identifier))
            return None

        snapshot = self._normalize_snapshot(bundle)
        del self.frames[bundle_key]
        self._prune_old_frames(session_uid=session_uid, newest_frame_identifier=int(frame_identifier))
        return snapshot

    def _normalize_snapshot(self, bundle: FrameBundle) -> dict[str, Any]:
        # 备注:
        # 这里把真实 PDU 字段压平为项目统一快照结构。
        # 后续 decode_snapshot() 与策略层都依赖这个 shape 保持稳定。
        session = self.latest_session_by_uid.get(bundle.session_uid, {})
        session_header = self.latest_session_header_by_uid.get(bundle.session_uid, {})
        lap = bundle.packets["LapData"]["body"]
        telemetry = bundle.packets["CarTelemetry"]["body"]
        status = bundle.packets["CarStatus"]["body"]
        damage = bundle.packets["CarDamage"]["body"]
        motion = bundle.packets["Motion"]["body"]
        motion_ex = bundle.packets["MotionEx"]["body"]
        base_header = bundle.packets["LapData"]["header"]
        tyre_sets = bundle.packets.get("TyreSets", {}).get("body", {})
        participants = self.latest_participants_by_uid.get(bundle.session_uid, {})
        lobby_info = self.latest_lobby_info_by_uid.get(bundle.session_uid, {})
        car_setup = self.latest_car_setups_by_uid.get(bundle.session_uid, {})
        session_history = self.latest_session_history_by_uid.get(bundle.session_uid, {})
        final_classification = self.latest_final_classification_by_uid.get(bundle.session_uid, {})
        lap_positions = self.latest_lap_positions_by_uid.get(bundle.session_uid, {})

        track_length_m = float(session.get("track_length_m", 0.0))
        lap_distance_m = self._normalize_lap_distance(float(lap.get("lap_distance_m", 0.0)), track_length_m)
        session_type_code = int(session.get("session_type", 0))
        session_type = SESSION_TYPE_NAMES.get(session_type_code, f"SessionType({session_type_code})")
        position = self._normalize_position(int(lap.get("car_position", 0)), session_type_code)
        pit_status_code = int(lap.get("pit_status", 0))
        pit_status_name = self._pit_status_name(pit_status_code, session_type_code)
        throttle = float(telemetry.get("throttle", 0.0))
        brake = float(telemetry.get("brake", 0.0))
        steer = float(telemetry.get("steer", 0.0))
        speed_kph = float(telemetry.get("speed_kph", 0.0))
        g_force = motion.get("g_force", {})
        g_lat = float(g_force.get("lateral", 0.0))
        g_lon = float(g_force.get("longitudinal", 0.0))
        ers_store_energy = float(status.get("ers_store_energy", 0.0))
        ers_pct = min(max(ers_store_energy / 4_000_000.0 * 100.0, 0.0), 100.0)
        tyres_age_laps = int(status.get("tyres_age_laps", 0))
        tyre_wear_pct = round(sum(float(item) for item in damage.get("tyres_wear_pct", [0.0] * 4)) / 4.0, 2)
        fuel_in_tank = float(status.get("fuel_in_tank", 0.0))
        raw_fuel_laps_remaining = float(status.get("fuel_remaining_laps", 0.0))
        derived_fuel_laps_remaining, fuel_laps_remaining_source = self._derive_fuel_laps_remaining(
            session_uid=bundle.session_uid,
            lap_number=int(lap.get("current_lap_num", 0)),
            total_distance_m=float(lap.get("total_distance_m", 0.0)),
            lap_distance_m=lap_distance_m,
            track_length_m=track_length_m,
            fuel_in_tank=fuel_in_tank,
            raw_fuel_laps_remaining=raw_fuel_laps_remaining,
        )
        damage_cars = damage.get("all_cars", [])
        tags = self._build_status_tags(
            speed_kph=speed_kph,
            throttle=throttle,
            brake=brake,
            steer=steer,
            g_force_lateral=g_lat,
            g_force_longitudinal=g_lon,
            wheel_slip_ratio=motion_ex.get("wheel_slip_ratio", []),
            tyre_damage_pct=damage.get("tyres_damage_pct", []),
        )
        rivals, player_gap_meta = self._build_rivals(
            player_lap=lap,
            lap_cars=lap.get("all_cars", []),
            motion_cars=motion.get("all_cars", []),
            telemetry_cars=telemetry.get("all_cars", []),
            status_cars=status.get("all_cars", []),
            damage_cars=damage_cars,
            participant_cars=participants.get("all_cars", []),
            player_car_index=int(base_header.get("player_car_index", 0)),
            player_position=position,
            player_speed_kph=speed_kph,
            track_length_m=track_length_m,
            player_lap_distance_m=lap_distance_m,
            player_total_distance_m=float(lap.get("total_distance_m", 0.0)),
            session_type_code=session_type_code,
        )
        front_rival = next((item for item in rivals if int(item.get("position", 0)) == position - 1), None)
        rear_rival = next((item for item in rivals if int(item.get("position", 0)) == position + 1), None)
        front_rival_car_gap_ahead_s, front_rival_car_gap_behind_s = self._car_relative_gap_pair(
            lap_cars=lap.get("all_cars", []),
            target_position=position - 1,
        )
        rear_rival_car_gap_ahead_s, rear_rival_car_gap_behind_s = self._car_relative_gap_pair(
            lap_cars=lap.get("all_cars", []),
            target_position=position + 1,
        )
        gap_ahead_s = player_gap_meta.get("official_gap_ahead_s")
        gap_behind_s = player_gap_meta.get("official_gap_behind_s")

        return {
            "session_uid": str(base_header.get("session_uid", session_header.get("session_uid", "unknown"))),
            "track": TRACK_NAMES.get(int(session.get("track_id", -1)), f"track_{session.get('track_id', 'unknown')}"),
            "lap_number": int(lap.get("current_lap_num", 0)),
            "total_laps": int(session.get("total_laps", 0)),
            "weather": WEATHER_NAMES.get(int(session.get("weather", -1)), f"Weather({session.get('weather', 'unknown')})"),
            "safety_car": self._normalize_safety_car_name(session.get("safety_car_status", 0)),
            "source_timestamp_ms": int(base_header.get("received_at_ms", 0)),
            "player": {
                "car_index": int(base_header.get("player_car_index", 0)),
                "name": participants.get("player", {}).get("name") or "Player",
                "position": position,
                "lap": int(lap.get("current_lap_num", 0)),
                "gap_ahead_s": gap_ahead_s,
                "gap_behind_s": gap_behind_s,
                "fuel_laps_remaining": derived_fuel_laps_remaining,
                "ers_pct": ers_pct,
                "drs_available": bool(status.get("drs_allowed", False)),
                "speed_kph": speed_kph,
                "tyre": {
                    "compound": TYRE_COMPOUND_NAMES.get(
                        int(status.get("visual_tyre_compound", 0)),
                        f"Compound({status.get('visual_tyre_compound', 0)})",
                    ),
                    "wear_pct": tyre_wear_pct,
                    "age_laps": tyres_age_laps,
                },
                "status_tags": tags,
            },
            "rivals": rivals,
            "raw": {
                "frame_identifier": int(base_header.get("frame_identifier", 0)),
                "overall_frame_identifier": int(base_header.get("overall_frame_identifier", 0)),
                "session_time_s": float(base_header.get("session_time_s", 0.0)),
                "session_type": session_type,
                "timing_mode": self._timing_mode_name(session_type_code),
                "timing_support_level": self._timing_support_level(session_type_code),
                "lap_distance_m": lap_distance_m,
                "total_distance_m": float(lap.get("total_distance_m", 0.0)),
                "current_lap_time_ms": int(lap.get("current_lap_time_ms", 0)),
                "last_lap_time_ms": int(lap.get("last_lap_time_ms", 0)),
                "sector1_time_ms": int(lap.get("sector1_time_ms", 0)),
                "sector2_time_ms": int(lap.get("sector2_time_ms", 0)),
                "delta_to_car_in_front_minutes": int(lap.get("delta_to_car_in_front_minutes", 0)),
                "delta_to_car_in_front_ms": int(lap.get("delta_to_car_in_front_ms", 0)),
                "delta_to_race_leader_minutes": int(lap.get("delta_to_race_leader_minutes", 0)),
                "delta_to_race_leader_ms": int(lap.get("delta_to_race_leader_ms", 0)),
                "delta_to_car_in_front_s": player_gap_meta.get("official_delta_to_car_in_front_s"),
                "delta_to_race_leader_s": player_gap_meta.get("official_delta_to_race_leader_s"),
                "gap_source_ahead": player_gap_meta.get("official_gap_source_ahead"),
                "gap_source_behind": player_gap_meta.get("official_gap_source_behind"),
                "gap_confidence_ahead": player_gap_meta.get("official_gap_confidence_ahead"),
                "gap_confidence_behind": player_gap_meta.get("official_gap_confidence_behind"),
                "official_delta_to_car_in_front_s": player_gap_meta.get("official_delta_to_car_in_front_s"),
                "official_delta_to_race_leader_s": player_gap_meta.get("official_delta_to_race_leader_s"),
                "official_gap_ahead_s": player_gap_meta.get("official_gap_ahead_s"),
                "official_gap_behind_s": player_gap_meta.get("official_gap_behind_s"),
                "official_gap_source_ahead": player_gap_meta.get("official_gap_source_ahead"),
                "official_gap_source_behind": player_gap_meta.get("official_gap_source_behind"),
                "official_gap_confidence_ahead": player_gap_meta.get("official_gap_confidence_ahead"),
                "official_gap_confidence_behind": player_gap_meta.get("official_gap_confidence_behind"),
                "estimated_gap_ahead_s": player_gap_meta.get("estimated_gap_ahead_s"),
                "estimated_gap_behind_s": player_gap_meta.get("estimated_gap_behind_s"),
                "estimated_gap_source_ahead": player_gap_meta.get("estimated_gap_source_ahead"),
                "estimated_gap_source_behind": player_gap_meta.get("estimated_gap_source_behind"),
                "estimated_gap_confidence_ahead": player_gap_meta.get("estimated_gap_confidence_ahead"),
                "estimated_gap_confidence_behind": player_gap_meta.get("estimated_gap_confidence_behind"),
                "rival_gap_sources": [
                    {
                        "name": item.get("name"),
                        "position": item.get("position"),
                        "gap_source": item.get("gap_source"),
                        "gap_confidence": item.get("gap_confidence"),
                        "estimated_gap_source": item.get("estimated_gap_source"),
                        "estimated_gap_confidence": item.get("estimated_gap_confidence"),
                    }
                    for item in rivals
                ],
                "sector": int(lap.get("sector", 0)),
                "pit_status_code": pit_status_code,
                "pit_status": pit_status_name,
                "num_pit_stops": int(lap.get("num_pit_stops", 0)),
                "total_warnings": int(lap.get("total_warnings", 0)),
                "corner_cutting_warnings": int(lap.get("corner_cutting_warnings", 0)),
                "num_unserved_drive_through_pens": int(lap.get("num_unserved_drive_through_pens", 0)),
                "num_unserved_stop_go_pens": int(lap.get("num_unserved_stop_go_pens", 0)),
                "grid_position": int(lap.get("grid_position", 0)),
                "driver_status": int(lap.get("driver_status", 0)),
                "result_status": int(lap.get("result_status", 0)),
                "pit_lane_timer_active": bool(lap.get("pit_lane_timer_active", False)),
                "pit_lane_time_in_lane_ms": int(lap.get("pit_lane_time_in_lane_ms", 0)),
                "pit_stop_timer_ms": int(lap.get("pit_stop_timer_ms", 0)),
                "pit_stop_should_serve_pen": bool(lap.get("pit_stop_should_serve_pen", False)),
                "throttle": throttle,
                "brake": brake,
                "steer": steer,
                "gear": int(telemetry.get("gear", 0)),
                "rpm": int(telemetry.get("engine_rpm", 0)),
                "fuel_in_tank": fuel_in_tank,
                "fuel_capacity": float(status.get("fuel_capacity", 0.0)),
                "raw_fuel_laps_remaining": raw_fuel_laps_remaining,
                "derived_fuel_laps_remaining": derived_fuel_laps_remaining,
                "fuel_laps_remaining_source": fuel_laps_remaining_source,
                "ers_store_energy": ers_store_energy,
                "ers_deploy_mode": int(status.get("ers_deploy_mode", 0)),
                "tyres_wear_pct": list(damage.get("tyres_wear_pct", [])),
                "tyres_damage_pct": list(damage.get("tyres_damage_pct", [])),
                "tyre_blisters_pct": list(damage.get("tyre_blisters_pct", [])),
                "brakes_damage_pct": list(damage.get("brakes_damage_pct", [])),
                "wing_damage_pct": {
                    "front_left": int(damage.get("front_left_wing_damage_pct", 0)),
                    "front_right": int(damage.get("front_right_wing_damage_pct", 0)),
                    "rear": int(damage.get("rear_wing_damage_pct", 0)),
                },
                "floor_damage_pct": int(damage.get("floor_damage_pct", 0)),
                "diffuser_damage_pct": int(damage.get("diffuser_damage_pct", 0)),
                "sidepod_damage_pct": int(damage.get("sidepod_damage_pct", 0)),
                "gearbox_damage_pct": int(damage.get("gearbox_damage_pct", 0)),
                "engine_damage_pct": int(damage.get("engine_damage_pct", 0)),
                "engine_components_damage_pct": dict(damage.get("engine_components_damage_pct", {})),
                "engine_blown": bool(damage.get("engine_blown", False)),
                "engine_seized": bool(damage.get("engine_seized", False)),
                "g_force_lateral": g_lat,
                "g_force_longitudinal": g_lon,
                "g_force_vertical": float(g_force.get("vertical", 0.0)),
                "yaw": float(motion.get("orientation", {}).get("yaw", 0.0)),
                "pitch": float(motion.get("orientation", {}).get("pitch", 0.0)),
                "roll": float(motion.get("orientation", {}).get("roll", 0.0)),
                "world_position_x": float(motion.get("world_position", {}).get("x", 0.0)),
                "world_position_y": float(motion.get("world_position", {}).get("y", 0.0)),
                "world_position_z": float(motion.get("world_position", {}).get("z", 0.0)),
                "front_rival_world_position_x": front_rival.get("world_position_x") if front_rival else None,
                "front_rival_world_position_z": front_rival.get("world_position_z") if front_rival else None,
                "front_rival_name": front_rival.get("name") if front_rival else None,
                "front_rival_position": front_rival.get("position") if front_rival else None,
                "front_rival_car_gap_ahead_s": front_rival_car_gap_ahead_s,
                "front_rival_car_gap_behind_s": front_rival_car_gap_behind_s,
                "rear_rival_world_position_x": rear_rival.get("world_position_x") if rear_rival else None,
                "rear_rival_world_position_z": rear_rival.get("world_position_z") if rear_rival else None,
                "rear_rival_name": rear_rival.get("name") if rear_rival else None,
                "rear_rival_position": rear_rival.get("position") if rear_rival else None,
                "rear_rival_car_gap_ahead_s": rear_rival_car_gap_ahead_s,
                "rear_rival_car_gap_behind_s": rear_rival_car_gap_behind_s,
                "front_rival_lap_distance_m": front_rival.get("lap_distance_m") if front_rival else None,
                "rear_rival_lap_distance_m": rear_rival.get("lap_distance_m") if rear_rival else None,
                "world_forward_dir": dict(motion.get("world_forward_dir", {})),
                "world_right_dir": dict(motion.get("world_right_dir", {})),
                "wheel_slip_ratio": list(motion_ex.get("wheel_slip_ratio", [])),
                "wheel_slip_angle": list(motion_ex.get("wheel_slip_angle", [])),
                "wheel_lat_force": list(motion_ex.get("wheel_lat_force", [])),
                "wheel_long_force": list(motion_ex.get("wheel_long_force", [])),
                "wheel_vert_force": list(motion_ex.get("wheel_vert_force", [])),
                "local_velocity": dict(motion_ex.get("local_velocity", {})),
                "angular_velocity": dict(motion_ex.get("angular_velocity", {})),
                "angular_acceleration": dict(motion_ex.get("angular_acceleration", {})),
                "front_wheels_angle": float(motion_ex.get("front_wheels_angle", 0.0)),
                "front_aero_height": float(motion_ex.get("front_aero_height", 0.0)),
                "rear_aero_height": float(motion_ex.get("rear_aero_height", 0.0)),
                "front_roll_angle": float(motion_ex.get("front_roll_angle", 0.0)),
                "rear_roll_angle": float(motion_ex.get("rear_roll_angle", 0.0)),
                "chassis_yaw": float(motion_ex.get("chassis_yaw", 0.0)),
                "chassis_pitch": float(motion_ex.get("chassis_pitch", 0.0)),
                "wheel_camber": list(motion_ex.get("wheel_camber", [])),
                "wheel_camber_gain": list(motion_ex.get("wheel_camber_gain", [])),
                "height_of_cog_above_ground": float(motion_ex.get("height_of_cog_above_ground", 0.0)),
                "current_lap_invalid": bool(lap.get("current_lap_invalid", False)),
                "time_trial_personal_best_car_idx": int(lap.get("time_trial_personal_best_car_idx", 255)),
                "time_trial_rival_car_idx": int(lap.get("time_trial_rival_car_idx", 255)),
                "event_code": self.latest_event_by_uid.get(bundle.session_uid, {}).get("event_code"),
                "event_detail": dict(self.latest_event_by_uid.get(bundle.session_uid, {}).get("event_detail", {})),
                "tyre_wear_source": "car_damage_packet",
                "session_packet": session,
                "tyre_sets": tyre_sets,
                "participants": participants,
                "lobby_info": lobby_info,
                "car_setup": car_setup,
                "session_history_summary": {
                    "car_index": int(session_history.get("car_index", 0)),
                    "num_laps": int(session_history.get("num_laps", 0)),
                    "num_tyre_stints": int(session_history.get("num_tyre_stints", 0)),
                    "best_lap_time_lap_num": int(session_history.get("best_lap_time_lap_num", 0)),
                    "best_sector1_lap_num": int(session_history.get("best_sector1_lap_num", 0)),
                    "best_sector2_lap_num": int(session_history.get("best_sector2_lap_num", 0)),
                    "best_sector3_lap_num": int(session_history.get("best_sector3_lap_num", 0)),
                },
                "session_history": session_history,
                "final_classification": final_classification,
                "lap_positions": lap_positions,
                "auxiliary_packet_15": lap_positions,
            },
        }

    def _derive_fuel_laps_remaining(
        self,
        session_uid: str,
        lap_number: int,
        total_distance_m: float,
        lap_distance_m: float,
        track_length_m: float,
        fuel_in_tank: float,
        raw_fuel_laps_remaining: float,
    ) -> tuple[float, str]:
        start_fuel = self.session_start_fuel_by_uid.get(session_uid)
        if start_fuel is None or fuel_in_tank > start_fuel:
            start_fuel = fuel_in_tank
            self.session_start_fuel_by_uid[session_uid] = start_fuel

        if track_length_m > 0.0 and total_distance_m > 0.0:
            equivalent_laps = max(total_distance_m / track_length_m, 0.0)
        elif track_length_m > 0.0:
            equivalent_laps = max(float(max(lap_number - 1, 0)) + max(lap_distance_m, 0.0) / track_length_m, 0.0)
        else:
            equivalent_laps = 0.0

        fuel_used = max(start_fuel - fuel_in_tank, 0.0)
        if equivalent_laps < 0.05 or fuel_used < 0.05:
            return raw_fuel_laps_remaining, "raw_protocol_fallback"

        per_lap_consumption = fuel_used / equivalent_laps
        if per_lap_consumption <= 0.0:
            return raw_fuel_laps_remaining, "raw_protocol_fallback"

        return fuel_in_tank / per_lap_consumption, "derived_from_sample_consumption"

    def _normalize_lap_distance(self, lap_distance_m: float, track_length_m: float) -> float:
        if track_length_m <= 0:
            return lap_distance_m
        if lap_distance_m < 0:
            return max(track_length_m + lap_distance_m, 0.0)
        return lap_distance_m

    def _normalize_position(self, position: int, session_type_code: int) -> int:
        if session_type_code == 1:
            return 1
        if position <= 0:
            return 1
        return min(position, 22)

    def _pit_status_name(self, pit_status_code: int, session_type_code: int) -> str:
        if session_type_code == 1:
            return "TIME_TRIAL"
        return {
            0: "NONE",
            1: "PITTING",
            2: "IN_PIT_AREA",
        }.get(pit_status_code, f"PitStatus({pit_status_code})")

    def _build_status_tags(
        self,
        speed_kph: float,
        throttle: float,
        brake: float,
        steer: float,
        g_force_lateral: float,
        g_force_longitudinal: float,
        wheel_slip_ratio: list[Any],
        tyre_damage_pct: list[Any],
    ) -> list[str]:
        tags = build_dynamic_tags(
            speed_kmh=speed_kph,
            throttle=throttle,
            brake=brake,
            steer=steer,
            g_force_lateral=g_force_lateral,
            g_force_longitudinal=g_force_longitudinal,
        )

        slip_values = [abs(float(item)) for item in wheel_slip_ratio if isinstance(item, (float, int))]
        max_slip = max(slip_values) if slip_values else 0.0
        if max_slip > 0.22 and "unstable" not in tags:
            tags = [tag for tag in tags if tag != "stable"]
            tags.append("unstable")
        if brake > 0.65 and max_slip > 0.12 and "front_tyre_overload" not in tags:
            tags.append("front_tyre_overload")
        if tyre_damage_pct:
            front_damage = max(float(tyre_damage_pct[0]), float(tyre_damage_pct[1]))
            if front_damage >= 35 and "front_tyre_overload" not in tags:
                tags.append("front_tyre_overload")
        if not tags:
            tags.append("stable")
        return tags

    def _build_rivals(
        self,
        player_lap: dict[str, Any],
        lap_cars: list[dict[str, Any]],
        motion_cars: list[dict[str, Any]],
        telemetry_cars: list[dict[str, Any]],
        status_cars: list[dict[str, Any]],
        damage_cars: list[dict[str, Any]],
        participant_cars: list[dict[str, Any]],
        player_car_index: int,
        player_position: int,
        player_speed_kph: float,
        track_length_m: float,
        player_lap_distance_m: float,
        player_total_distance_m: float,
        session_type_code: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        timing_mainline_allowed = self._timing_support_level(session_type_code) == "official_preferred"
        if session_type_code == 1:
            return [], {
                "gap_ahead_s": None,
                "gap_behind_s": None,
                "gap_source_ahead": "session_type_time_trial_disabled",
                "gap_source_behind": "session_type_time_trial_disabled",
                "gap_confidence_ahead": "none",
                "gap_confidence_behind": "none",
                "official_gap_ahead_s": None,
                "official_gap_behind_s": None,
                "official_gap_source_ahead": "session_type_time_trial_disabled",
                "official_gap_source_behind": "session_type_time_trial_disabled",
                "official_gap_confidence_ahead": "none",
                "official_gap_confidence_behind": "none",
                "official_delta_to_car_in_front_s": None,
                "official_delta_to_race_leader_s": None,
                "estimated_gap_ahead_s": None,
                "estimated_gap_behind_s": None,
                "estimated_gap_source_ahead": None,
                "estimated_gap_source_behind": None,
                "estimated_gap_confidence_ahead": "none",
                "estimated_gap_confidence_behind": "none",
                "delta_to_car_in_front_s": None,
                "delta_to_race_leader_s": None,
            }

        motion_by_index = {item["car_index"]: item for item in motion_cars}
        telemetry_by_index = {item["car_index"]: item for item in telemetry_cars}
        status_by_index = {item["car_index"]: item for item in status_cars}
        damage_by_index = {item["car_index"]: item for item in damage_cars}
        participants_by_index = {item["car_index"]: item for item in participant_cars}
        position_to_lap = {
            int(item.get("car_position", 0)): item
            for item in lap_cars
            if 1 <= int(item.get("car_position", 0)) <= 22 and int(item.get("result_status", 0)) != 0
        }
        ahead_delta_s = self._lap_delta_seconds(player_lap.get("delta_to_car_in_front_ms"))
        leader_delta_s = self._cumulative_delta_to_leader_seconds(position_to_lap, player_position)
        official_ahead_delta_s = ahead_delta_s if timing_mainline_allowed else None
        official_leader_delta_s = leader_delta_s if timing_mainline_allowed else None
        player_gap_meta = {
            "gap_ahead_s": official_ahead_delta_s,
            "gap_behind_s": None,
            "gap_source_ahead": "official_lapdata_adjacent" if official_ahead_delta_s is not None else "unavailable",
            "gap_source_behind": "unavailable",
            "gap_confidence_ahead": self._official_gap_confidence_from_source(
                "official_lapdata_adjacent" if official_ahead_delta_s is not None else "unavailable"
            ),
            "gap_confidence_behind": "none",
            "delta_to_car_in_front_s": official_ahead_delta_s,
            "delta_to_race_leader_s": official_leader_delta_s,
            "official_gap_ahead_s": official_ahead_delta_s,
            "official_gap_behind_s": None,
            "official_gap_source_ahead": "official_lapdata_adjacent" if official_ahead_delta_s is not None else "unavailable",
            "official_gap_source_behind": "unavailable",
            "official_gap_confidence_ahead": self._official_gap_confidence_from_source(
                "official_lapdata_adjacent" if official_ahead_delta_s is not None else "unavailable"
            ),
            "official_gap_confidence_behind": "none",
            "official_delta_to_car_in_front_s": official_ahead_delta_s,
            "official_delta_to_race_leader_s": official_leader_delta_s,
            "estimated_gap_ahead_s": None,
            "estimated_gap_behind_s": None,
            "estimated_gap_source_ahead": None,
            "estimated_gap_source_behind": None,
            "estimated_gap_confidence_ahead": "none",
            "estimated_gap_confidence_behind": "none",
        }
        candidates = []
        for item in lap_cars:
            car_index = int(item.get("car_index", -1))
            if car_index == player_car_index:
                continue
            position = int(item.get("car_position", 0))
            if position <= 0 or position > 22:
                continue
            result_status = int(item.get("result_status", 0))
            if result_status == 0:
                continue
            lap_distance_m = self._normalize_lap_distance(float(item.get("lap_distance_m", 0.0)), track_length_m)
            total_distance_m = float(item.get("total_distance_m", 0.0))
            speed_kph = float(telemetry_by_index.get(car_index, {}).get("speed_kph", 0.0))
            compound_code = int(status_by_index.get(car_index, {}).get("visual_tyre_compound", 0))
            age_laps = int(status_by_index.get(car_index, {}).get("tyres_age_laps", 0))
            rival_damage = damage_by_index.get(car_index, {})
            rival_motion = motion_by_index.get(car_index, {})
            rival_wear_values = [float(value) for value in rival_damage.get("tyres_wear_pct", [])]
            rival_tyre_wear = round(sum(rival_wear_values) / len(rival_wear_values), 2) if rival_wear_values else 0.0
            estimated_gap_seconds, estimated_gap_source = self._estimate_gap_seconds(
                player_speed_kph=player_speed_kph,
                player_lap_distance_m=player_lap_distance_m,
                player_total_distance_m=player_total_distance_m,
                rival_lap_distance_m=lap_distance_m,
                rival_total_distance_m=total_distance_m,
                track_length_m=track_length_m,
                player_lap_number=int(player_lap.get("current_lap_num", 0)),
                rival_lap_number=int(item.get("current_lap_num", 0)),
            )
            official_gap_ahead_s = None
            official_gap_behind_s = None
            official_gap_source = "unavailable"
            official_gap_confidence = "none"
            estimated_gap_ahead_s = None
            estimated_gap_behind_s = None
            estimated_gap_source = estimated_gap_source
            estimated_gap_confidence = self._estimated_gap_confidence_from_source(estimated_gap_source)
            rival_delta_to_front_s = self._lap_delta_seconds(item.get("delta_to_car_in_front_ms"))
            rival_delta_to_leader_s = self._cumulative_delta_to_leader_seconds(position_to_lap, position)
            rival_gap_ahead_s = rival_delta_to_front_s if timing_mainline_allowed else None
            rival_gap_behind_s = None
            rival_gap_source_ahead = "official_lapdata_adjacent" if rival_gap_ahead_s is not None else "unavailable"
            rival_gap_confidence_ahead = self._official_gap_confidence_from_source(rival_gap_source_ahead)
            rival_gap_source_behind = "unavailable"
            rival_gap_confidence_behind = "none"
            behind_car = position_to_lap.get(position + 1)
            if timing_mainline_allowed and behind_car is not None:
                behind_delta_to_front_s = self._lap_delta_seconds(behind_car.get("delta_to_car_in_front_ms"))
                if behind_delta_to_front_s is not None:
                    rival_gap_behind_s = behind_delta_to_front_s
                    rival_gap_source_behind = "official_lapdata_adjacent"
                    rival_gap_confidence_behind = self._official_gap_confidence_from_source(
                        rival_gap_source_behind
                    )
            if timing_mainline_allowed and position == player_position - 1 and official_ahead_delta_s is not None:
                official_gap_ahead_s = official_ahead_delta_s
                official_gap_source = "official_lapdata_adjacent"
                official_gap_confidence = self._official_gap_confidence_from_source(official_gap_source)
            elif position == player_position + 1:
                behind_delta_s = self._lap_delta_seconds(item.get("delta_to_car_in_front_ms"))
                if timing_mainline_allowed and behind_delta_s is not None:
                    official_gap_behind_s = behind_delta_s
                    official_gap_source = "official_lapdata_adjacent"
                    player_gap_meta["official_gap_behind_s"] = behind_delta_s
                    player_gap_meta["official_gap_source_behind"] = "official_lapdata_adjacent"
                    player_gap_meta["official_gap_confidence_behind"] = self._official_gap_confidence_from_source(
                        "official_lapdata_adjacent"
                    )
                    player_gap_meta["gap_behind_s"] = behind_delta_s
                    player_gap_meta["gap_source_behind"] = "official_lapdata_adjacent"
                    player_gap_meta["gap_confidence_behind"] = self._official_gap_confidence_from_source(
                        "official_lapdata_adjacent"
                    )
            if official_gap_source == "unavailable":
                if rival_gap_ahead_s is not None or rival_gap_behind_s is not None:
                    official_gap_source = "official_lapdata_adjacent"
                    official_gap_confidence = self._official_gap_confidence_from_source(official_gap_source)
            if position < player_position:
                estimated_gap_ahead_s = estimated_gap_seconds
                if player_gap_meta["estimated_gap_ahead_s"] is None and position == player_position - 1:
                    player_gap_meta["estimated_gap_ahead_s"] = estimated_gap_seconds
                    player_gap_meta["estimated_gap_source_ahead"] = estimated_gap_source
                    player_gap_meta["estimated_gap_confidence_ahead"] = self._estimated_gap_confidence_from_source(
                        estimated_gap_source
                    )
            if position > player_position:
                estimated_gap_behind_s = estimated_gap_seconds
                if player_gap_meta["estimated_gap_behind_s"] is None and position == player_position + 1:
                    player_gap_meta["estimated_gap_behind_s"] = estimated_gap_seconds
                    player_gap_meta["estimated_gap_source_behind"] = estimated_gap_source
                    player_gap_meta["estimated_gap_confidence_behind"] = self._estimated_gap_confidence_from_source(
                        estimated_gap_source
                    )
            candidates.append(
                {
                    "car_index": car_index,
                    "name": participants_by_index.get(car_index, {}).get("name", f"Car {car_index}"),
                    "team_id": participants_by_index.get(car_index, {}).get("team_id"),
                    "race_number": participants_by_index.get(car_index, {}).get("race_number"),
                    "position": position,
                    "lap": int(item.get("current_lap_num", 0)),
                    "lap_distance_m": lap_distance_m,
                    "gap_ahead_s": rival_gap_ahead_s,
                    "gap_behind_s": rival_gap_behind_s,
                    "official_gap_ahead_s": rival_gap_ahead_s,
                    "official_gap_behind_s": rival_gap_behind_s,
                    "official_delta_to_car_in_front_s": rival_delta_to_front_s if timing_mainline_allowed else None,
                    "official_delta_to_race_leader_s": rival_delta_to_leader_s if timing_mainline_allowed else None,
                    "estimated_gap_ahead_s": estimated_gap_ahead_s,
                    "estimated_gap_behind_s": estimated_gap_behind_s,
                    "fuel_laps_remaining": float(status_by_index.get(car_index, {}).get("fuel_remaining_laps", 0.0)),
                    "ers_pct": self._ers_pct(status_by_index.get(car_index, {}).get("ers_store_energy", 0.0)),
                    "drs_available": bool(telemetry_by_index.get(car_index, {}).get("drs", False)),
                    "speed_kph": speed_kph,
                    "gap_source": official_gap_source,
                    "gap_confidence": official_gap_confidence,
                    "gap_source_ahead": rival_gap_source_ahead,
                    "gap_source_behind": rival_gap_source_behind,
                    "gap_confidence_ahead": rival_gap_confidence_ahead,
                    "gap_confidence_behind": rival_gap_confidence_behind,
                    "official_gap_source_ahead": rival_gap_source_ahead,
                    "official_gap_source_behind": rival_gap_source_behind,
                    "official_gap_confidence_ahead": rival_gap_confidence_ahead,
                    "official_gap_confidence_behind": rival_gap_confidence_behind,
                    "estimated_gap_source": estimated_gap_source,
                    "estimated_gap_confidence": estimated_gap_confidence,
                    "tyre": {
                        "compound": TYRE_COMPOUND_NAMES.get(compound_code, f"Compound({compound_code})"),
                        "wear_pct": rival_tyre_wear,
                        "age_laps": age_laps,
                    },
                    "world_position_x": float(rival_motion.get("world_position", {}).get("x", 0.0)),
                    "world_position_y": float(rival_motion.get("world_position", {}).get("y", 0.0)),
                    "world_position_z": float(rival_motion.get("world_position", {}).get("z", 0.0)),
                    "status_tags": [],
                }
            )
        candidates.sort(key=lambda item: abs((item["position"] or 99) - player_position))
        return candidates[:4], player_gap_meta

    def _estimate_gap_seconds(
        self,
        player_speed_kph: float,
        player_lap_distance_m: float,
        player_total_distance_m: float,
        rival_lap_distance_m: float,
        rival_total_distance_m: float,
        track_length_m: float,
        player_lap_number: int,
        rival_lap_number: int,
    ) -> tuple[float, str]:
        speed_mps = max(player_speed_kph / 3.6, 25.0)
        if player_total_distance_m > 0 and rival_total_distance_m > 0:
            delta_m = abs(rival_total_distance_m - player_total_distance_m)
            if player_lap_number == rival_lap_number:
                return round(delta_m / speed_mps, 3), "estimated_total_distance_same_lap"
            return round(delta_m / speed_mps, 3), "estimated_total_distance_cross_lap"
        delta_m = abs(rival_lap_distance_m - player_lap_distance_m)
        if track_length_m > 0:
            delta_m = min(delta_m, abs(track_length_m - delta_m))
        return round(delta_m / speed_mps, 3), "estimated_lap_distance_wrap"

    def _lap_delta_seconds(self, delta_ms: Any) -> float | None:
        try:
            value = int(delta_ms)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return round(value / 1000.0, 3)

    def _cumulative_delta_to_leader_seconds(
        self,
        position_to_lap: dict[int, dict[str, Any]],
        position: int,
    ) -> float | None:
        if position <= 1:
            return None
        total_s = 0.0
        for current_position in range(position, 1, -1):
            lap_item = position_to_lap.get(current_position)
            if lap_item is None:
                return None
            delta_s = self._lap_delta_seconds(lap_item.get("delta_to_car_in_front_ms"))
            if delta_s is None:
                return None
            total_s += delta_s
        return round(total_s, 3)

    def _car_relative_gap_pair(self, lap_cars: list[dict[str, Any]], target_position: int) -> tuple[float | None, float | None]:
        if target_position <= 0:
            return None, None
        position_to_car = {
            int(item.get("car_position", 0)): item
            for item in lap_cars
            if 1 <= int(item.get("car_position", 0)) <= 22 and int(item.get("result_status", 0)) != 0
        }
        target = position_to_car.get(target_position)
        behind = position_to_car.get(target_position + 1)
        gap_ahead_s = self._lap_delta_seconds(target.get("delta_to_car_in_front_ms")) if target is not None else None
        gap_behind_s = self._lap_delta_seconds(behind.get("delta_to_car_in_front_ms")) if behind is not None else None
        return gap_ahead_s, gap_behind_s

    def _timing_mode_name(self, session_type_code: int) -> str:
        if session_type_code == 1:
            return "time_trial_disabled"
        if session_type_code in {10, 15, 16}:
            return "race_like"
        if session_type_code in {5, 13}:
            return "qualifying_like"
        return "session_type_estimated"

    def _timing_support_level(self, session_type_code: int) -> str:
        """Describe whether timing deltas are fit for direct strategy/model use.

        备注:
        这里不回答“值是多少”，只回答“这一类 session 下能不能当正式 timing 用”。
        后续阶段二做特征筛选时，优先看这个字段而不是只看 gap 是否非空。
        """
        if session_type_code == 1:
            return "disabled"
        if session_type_code in {5, 10, 13, 15, 16}:
            return "official_preferred"
        return "estimated_only"

    def _gap_confidence_from_source(self, gap_source: str | None) -> str:
        """Backward-compatible alias for estimated/debug provenance confidence.

        备注:
        正式主链不再使用估算 gap 置信度；该函数保留给 debug/兼容路径。
        """
        return self._estimated_gap_confidence_from_source(gap_source)

    def _official_gap_confidence_from_source(self, gap_source: str | None) -> str:
        """Map official gap provenance to mainline confidence.

        备注:
        正式主链只接受官方相邻 timing；其它来源一律视为不可用于正式决策。
        """
        if gap_source == "official_lapdata_adjacent":
            return "high"
        return "none"

    def _estimated_gap_confidence_from_source(self, gap_source: str | None) -> str:
        """Convert estimated/debug gap provenance into a diagnostic confidence tier."""
        if gap_source in {None, "unavailable", "session_type_time_trial_disabled"}:
            return "none"
        if gap_source == "official_lapdata_adjacent":
            return "high"
        if gap_source == "estimated_total_distance_same_lap":
            return "medium"
        if gap_source in {"estimated_total_distance_cross_lap", "estimated_lap_distance_wrap"}:
            return "low"
        return "low"

    def _ers_pct(self, energy: Any) -> float:
        value = float(energy or 0.0)
        return min(max(value / 4_000_000.0 * 100.0, 0.0), 100.0)

    def _is_session_valid(self, session: dict[str, Any]) -> bool:
        track_length_m = int(session.get("track_length_m", 0))
        track_id = int(session.get("track_id", -1))
        return track_length_m > 1000 and track_id >= 0

    def _normalize_safety_car_name(self, raw_status: Any) -> str:
        try:
            status = int(raw_status)
        except (TypeError, ValueError):
            return "NONE"
        if status not in SAFETY_CAR_NAMES:
            return "NONE"
        return SAFETY_CAR_NAMES[status]

    def _is_lap_valid(self, bundle: FrameBundle, session: dict[str, Any]) -> bool:
        lap = bundle.packets["LapData"]["body"]
        session_type_code = int(session.get("session_type", 0))
        track_length_m = float(session.get("track_length_m", 0.0))
        lap_number = int(lap.get("current_lap_num", 0))
        sector = int(lap.get("sector", -1))
        lap_distance_m = float(lap.get("lap_distance_m", 0.0))
        car_position = int(lap.get("car_position", 0))

        if lap_number <= 0 or sector not in (0, 1, 2):
            return False
        if track_length_m > 0 and not (-track_length_m <= lap_distance_m <= track_length_m * 1.2):
            return False
        if session_type_code != 1 and not (1 <= car_position <= 22):
            return False
        return True

    def _prune_old_frames(self, session_uid: str, newest_frame_identifier: int) -> None:
        stale_keys = [
            key
            for key, bundle in self.frames.items()
            if bundle.session_uid == session_uid and bundle.frame_identifier < newest_frame_identifier - 4
        ]
        for key in stale_keys:
            del self.frames[key]
