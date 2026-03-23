from __future__ import annotations

import struct
from typing import Any

from .pdu import PacketEnvelope, RawPacket


class PacketDecodeError(Exception):
    pass


class F125PacketDecoder:
    """F1 25 UDP decoder for header + selected body fields.

    备注:
    当前实现采用“可靠字段优先”的保守策略。
    宁可少解几个字段，也不把未验证偏移的脏数据送进策略层。
    """

    HEADER_FORMAT = "<HBBBBBQfIIBB"
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    EVENT_PACKET_ID = 3

    MOTION_PACKET_ID = 0
    SESSION_PACKET_ID = 1
    LAP_DATA_PACKET_ID = 2
    PARTICIPANTS_PACKET_ID = 4
    CAR_SETUPS_PACKET_ID = 5
    CAR_TELEMETRY_PACKET_ID = 6
    CAR_STATUS_PACKET_ID = 7
    FINAL_CLASSIFICATION_PACKET_ID = 8
    LOBBY_INFO_PACKET_ID = 9
    CAR_DAMAGE_PACKET_ID = 10
    SESSION_HISTORY_PACKET_ID = 11
    TYRE_SETS_PACKET_ID = 12
    MOTION_EX_PACKET_ID = 13
    TIME_TRIAL_PACKET_ID = 14
    LAP_POSITIONS_PACKET_ID = 15

    PACKET_ID_NAMES = {
        0: "Motion",
        1: "Session",
        2: "LapData",
        3: "Event",
        4: "Participants",
        5: "CarSetups",
        6: "CarTelemetry",
        7: "CarStatus",
        8: "FinalClassification",
        9: "LobbyInfo",
        10: "CarDamage",
        11: "SessionHistory",
        12: "TyreSets",
        13: "MotionEx",
        14: "TimeTrial",
        15: "LapPositions",
    }

    MOTION_CAR_FORMAT = "<ffffffhhhhhhffffff"
    MOTION_CAR_SIZE = struct.calcsize(MOTION_CAR_FORMAT)  # 60
    LAP_DATA_CAR_SIZE = 57
    CAR_TELEMETRY_FORMAT = "<HfffBbHBBH4H4B4BH4f4B"
    CAR_TELEMETRY_SIZE = struct.calcsize(CAR_TELEMETRY_FORMAT)  # 60
    CAR_STATUS_FORMAT = "<BBBBBfffHHBBHBBBbfffBfffB"
    CAR_STATUS_SIZE = struct.calcsize(CAR_STATUS_FORMAT)  # 55
    CAR_SETUPS_FORMAT = "<BBBBffffBBBBBBBBB4fBf"
    CAR_SETUPS_SIZE = struct.calcsize(CAR_SETUPS_FORMAT)  # 50
    SESSION_PREFIX_FORMAT = "<BbbBHBBBHHBBBBBBBB"
    SESSION_PREFIX_SIZE = struct.calcsize(SESSION_PREFIX_FORMAT)  # 21
    SESSION_MARSHAL_ZONE_SIZE = 5
    SESSION_MAX_MARSHAL_ZONES = 21
    SESSION_FORECAST_SAMPLE_FORMAT = "<BBBbbbbB"
    SESSION_FORECAST_SAMPLE_SIZE = struct.calcsize(SESSION_FORECAST_SAMPLE_FORMAT)  # 8
    SESSION_MAX_FORECAST_SAMPLES = 64
    LOBBY_PLAYER_NAME_BYTES = 32
    LOBBY_INFO_RECORD_SIZE = 42

    def decode_raw(self, packet: RawPacket) -> PacketEnvelope:
        # 备注:
        # 所有 packet 先统一过 common header，再按 packet_id 分发正文解析。
        # 这样 assembler 和调试输出可以共享同一份 header 结构。
        if len(packet.payload) < self.HEADER_SIZE:
            raise PacketDecodeError(
                f"packet too small to contain valid F1 25 header: {len(packet.payload)} bytes"
            )

        (
            packet_format,
            game_year,
            game_major_version,
            game_minor_version,
            packet_version,
            packet_id,
            session_uid,
            session_time,
            frame_identifier,
            overall_frame_identifier,
            player_car_index,
            secondary_player_car_index,
        ) = struct.unpack_from(self.HEADER_FORMAT, packet.payload, 0)

        header = {
            "packet_format": packet_format,
            "game_year": game_year,
            "game_major_version": game_major_version,
            "game_minor_version": game_minor_version,
            "packet_version": packet_version,
            "packet_id": packet_id,
            "packet_name": self.PACKET_ID_NAMES.get(packet_id, f"Unknown({packet_id})"),
            "session_uid": session_uid,
            "session_time_s": round(session_time, 6),
            "frame_identifier": frame_identifier,
            "overall_frame_identifier": overall_frame_identifier,
            "player_car_index": player_car_index,
            "secondary_player_car_index": secondary_player_car_index,
            "byte_length": len(packet.payload),
            "preview_hex": packet.payload[:16].hex(),
            "received_at_ms": packet.received_at_ms,
        }

        body = self._decode_body(packet.payload, packet_id, player_car_index)

        return PacketEnvelope(
            kind=header["packet_name"],
            frame_identifier=frame_identifier,
            session_uid=str(session_uid),
            payload={"header": header, "body": body},
        )

    def _decode_motion(self, payload: bytes, player_car_index: int) -> dict[str, Any]:
        offset = self.HEADER_SIZE + player_car_index * self.MOTION_CAR_SIZE
        values = struct.unpack_from(self.MOTION_CAR_FORMAT, payload, offset)
        world_forward_dir = values[6:9]
        world_right_dir = values[9:12]
        return {
            "world_position": {"x": values[0], "y": values[1], "z": values[2]},
            "world_velocity": {"x": values[3], "y": values[4], "z": values[5]},
            "world_forward_dir": {
                "x_raw": world_forward_dir[0],
                "y_raw": world_forward_dir[1],
                "z_raw": world_forward_dir[2],
                "x": world_forward_dir[0] / 32767.0,
                "y": world_forward_dir[1] / 32767.0,
                "z": world_forward_dir[2] / 32767.0,
            },
            "world_right_dir": {
                "x_raw": world_right_dir[0],
                "y_raw": world_right_dir[1],
                "z_raw": world_right_dir[2],
                "x": world_right_dir[0] / 32767.0,
                "y": world_right_dir[1] / 32767.0,
                "z": world_right_dir[2] / 32767.0,
            },
            "g_force": {"lateral": values[12], "longitudinal": values[13], "vertical": values[14]},
            "orientation": {"yaw": values[15], "pitch": values[16], "roll": values[17]},
        }

    def _decode_session(self, payload: bytes) -> dict[str, Any]:
        """Decode the fixed-width session packet, including the tail settings block.

        备注:
        F1 24/25 的 Session packet 是定长结构。
        之前按“实际天气样本数”截断，导致未使用的 forecast 槽位被误判成 trailer。
        这里改成按固定 64 个 weather sample 后再解析尾部设置字段。
        """
        values = struct.unpack_from(self.SESSION_PREFIX_FORMAT, payload, self.HEADER_SIZE)
        marshal_zones_offset = self.HEADER_SIZE + self.SESSION_PREFIX_SIZE
        num_marshal_zones = int(values[15])
        marshal_zones = []
        for index in range(min(num_marshal_zones, self.SESSION_MAX_MARSHAL_ZONES)):
            base = marshal_zones_offset + index * self.SESSION_MARSHAL_ZONE_SIZE
            if len(payload) < base + self.SESSION_MARSHAL_ZONE_SIZE:
                break
            zone_start, zone_flag = struct.unpack_from("<fb", payload, base)
            marshal_zones.append(
                {
                    "zone_index": index,
                    "zone_start": zone_start,
                    "zone_flag": zone_flag,
                }
            )

        forecast_count_offset = (
            marshal_zones_offset + self.SESSION_MAX_MARSHAL_ZONES * self.SESSION_MARSHAL_ZONE_SIZE
        )
        num_weather_forecast_samples = payload[forecast_count_offset] if len(payload) > forecast_count_offset else 0
        forecast_samples = []
        forecast_base = forecast_count_offset + 1
        for index in range(min(num_weather_forecast_samples, self.SESSION_MAX_FORECAST_SAMPLES)):
            base = forecast_base + index * self.SESSION_FORECAST_SAMPLE_SIZE
            if len(payload) < base + self.SESSION_FORECAST_SAMPLE_SIZE:
                break
            (
                session_type,
                time_offset,
                weather,
                track_temperature,
                track_temperature_change,
                air_temperature,
                air_temperature_change,
                rain_percentage,
            ) = struct.unpack_from("<BBBbbbbB", payload, base)
            forecast_samples.append(
                {
                    "sample_index": index,
                    "session_type": session_type,
                    "time_offset_minutes": time_offset,
                    "weather": weather,
                    "track_temperature_c": track_temperature,
                    "track_temperature_change": track_temperature_change,
                    "air_temperature_c": air_temperature,
                    "air_temperature_change": air_temperature_change,
                    "rain_percentage": rain_percentage,
                }
            )

        session_tail_offset = (
            forecast_base + self.SESSION_MAX_FORECAST_SAMPLES * self.SESSION_FORECAST_SAMPLE_SIZE
        )
        cursor = session_tail_offset

        def read_u8() -> int:
            nonlocal cursor
            value = payload[cursor] if len(payload) > cursor else 0
            cursor += 1
            return value

        def read_u32() -> int:
            nonlocal cursor
            if len(payload) < cursor + 4:
                cursor += 4
                return 0
            value = struct.unpack_from("<I", payload, cursor)[0]
            cursor += 4
            return value

        def read_f32() -> float:
            nonlocal cursor
            if len(payload) < cursor + 4:
                cursor += 4
                return 0.0
            value = struct.unpack_from("<f", payload, cursor)[0]
            cursor += 4
            return value

        forecast_accuracy = read_u8()
        ai_difficulty = read_u8()
        season_link_identifier = read_u32()
        weekend_link_identifier = read_u32()
        session_link_identifier = read_u32()
        pit_stop_window_ideal_lap = read_u8()
        pit_stop_window_latest_lap = read_u8()
        pit_stop_rejoin_position = read_u8()
        steering_assist = read_u8()
        braking_assist = read_u8()
        gearbox_assist = read_u8()
        pit_assist = read_u8()
        pit_release_assist = read_u8()
        ers_assist = read_u8()
        drs_assist = read_u8()
        dynamic_racing_line = read_u8()
        dynamic_racing_line_type = read_u8()
        game_mode = read_u8()
        rule_set = read_u8()
        time_of_day_minutes = read_u32()
        session_length = read_u8()
        speed_units_lead_player = read_u8()
        temperature_units_lead_player = read_u8()
        speed_units_secondary_player = read_u8()
        temperature_units_secondary_player = read_u8()
        num_safety_car_periods = read_u8()
        num_virtual_safety_car_periods = read_u8()
        num_red_flag_periods = read_u8()
        equal_car_performance = read_u8()
        recovery_mode = read_u8()
        flashback_limit = read_u8()
        surface_type = read_u8()
        low_fuel_mode = read_u8()
        race_starts = read_u8()
        tyre_temperature = read_u8()
        pit_lane_tyre_sim = read_u8()
        car_damage = read_u8()
        car_damage_rate = read_u8()
        collisions = read_u8()
        collisions_off_for_first_lap_only = read_u8()
        mp_unsafe_pit_release = read_u8()
        mp_off_for_griefing = read_u8()
        corner_cutting_stringency = read_u8()
        parc_ferme_rules = read_u8()
        pit_stop_experience = read_u8()
        safety_car = read_u8()
        safety_car_experience = read_u8()
        formation_lap = read_u8()
        formation_lap_experience = read_u8()
        red_flags = read_u8()
        affects_licence_level_solo = read_u8()
        affects_licence_level_mp = read_u8()
        num_sessions_in_weekend = read_u8()
        weekend_structure = [read_u8() for _ in range(12)]
        sector2_lap_distance_start_m = read_f32()
        sector3_lap_distance_start_m = read_f32()

        return {
            "weather": values[0],
            "track_temperature_c": values[1],
            "air_temperature_c": values[2],
            "total_laps": values[3],
            "track_length_m": values[4],
            "session_type": values[5],
            "track_id": values[6],
            "formula": values[7],
            "session_time_left_s": values[8],
            "session_duration_s": values[9],
            "pit_speed_limit_kph": values[10],
            "game_paused": bool(values[11]),
            "is_spectating": bool(values[12]),
            "spectator_car_index": values[13],
            "sli_native_support": values[14],
            "num_marshal_zones": num_marshal_zones,
            "marshal_zones": marshal_zones,
            "safety_car_status": values[16],
            "network_game": values[17],
            "num_weather_forecast_samples": num_weather_forecast_samples,
            "weather_forecast_samples": forecast_samples,
            "forecast_accuracy": forecast_accuracy,
            "ai_difficulty": ai_difficulty,
            "season_link_identifier": season_link_identifier,
            "weekend_link_identifier": weekend_link_identifier,
            "session_link_identifier": session_link_identifier,
            "pit_stop_window_ideal_lap": pit_stop_window_ideal_lap,
            "pit_stop_window_latest_lap": pit_stop_window_latest_lap,
            "pit_stop_rejoin_position": pit_stop_rejoin_position,
            "steering_assist": steering_assist,
            "braking_assist": braking_assist,
            "gearbox_assist": gearbox_assist,
            "pit_assist": pit_assist,
            "pit_release_assist": pit_release_assist,
            "ers_assist": ers_assist,
            "drs_assist": drs_assist,
            "dynamic_racing_line": dynamic_racing_line,
            "dynamic_racing_line_type": dynamic_racing_line_type,
            "game_mode": game_mode,
            "rule_set": rule_set,
            "time_of_day_minutes": time_of_day_minutes,
            "session_length": session_length,
            "speed_units_lead_player": speed_units_lead_player,
            "temperature_units_lead_player": temperature_units_lead_player,
            "speed_units_secondary_player": speed_units_secondary_player,
            "temperature_units_secondary_player": temperature_units_secondary_player,
            "num_safety_car_periods": num_safety_car_periods,
            "num_virtual_safety_car_periods": num_virtual_safety_car_periods,
            "num_red_flag_periods": num_red_flag_periods,
            "equal_car_performance": equal_car_performance,
            "recovery_mode": recovery_mode,
            "flashback_limit": flashback_limit,
            "surface_type": surface_type,
            "low_fuel_mode": low_fuel_mode,
            "race_starts": race_starts,
            "tyre_temperature": tyre_temperature,
            "pit_lane_tyre_sim": pit_lane_tyre_sim,
            "car_damage": car_damage,
            "car_damage_rate": car_damage_rate,
            "collisions": collisions,
            "collisions_off_for_first_lap_only": collisions_off_for_first_lap_only,
            "mp_unsafe_pit_release": mp_unsafe_pit_release,
            "mp_off_for_griefing": mp_off_for_griefing,
            "corner_cutting_stringency": corner_cutting_stringency,
            "parc_ferme_rules": parc_ferme_rules,
            "pit_stop_experience": pit_stop_experience,
            "safety_car_setting": safety_car,
            "safety_car_experience": safety_car_experience,
            "formation_lap": formation_lap,
            "formation_lap_experience": formation_lap_experience,
            "red_flags_setting": red_flags,
            "affects_licence_level_solo": affects_licence_level_solo,
            "affects_licence_level_mp": affects_licence_level_mp,
            "num_sessions_in_weekend": num_sessions_in_weekend,
            "weekend_structure": weekend_structure[:num_sessions_in_weekend],
            "weekend_structure_raw": weekend_structure,
            "sector2_lap_distance_start_m": sector2_lap_distance_start_m,
            "sector3_lap_distance_start_m": sector3_lap_distance_start_m,
            "session_trailer_hex": payload[cursor:].hex(),
        }

    def _decode_lap_data(self, payload: bytes, player_car_index: int) -> dict[str, Any]:
        offset = self.HEADER_SIZE + player_car_index * self.LAP_DATA_CAR_SIZE
        tail_offset = self.HEADER_SIZE + 22 * self.LAP_DATA_CAR_SIZE
        sector1_time_ms_part = struct.unpack_from("<H", payload, offset + 8)[0]
        sector1_time_minutes = payload[offset + 10]
        sector2_time_ms_part = struct.unpack_from("<H", payload, offset + 11)[0]
        sector2_time_minutes = payload[offset + 13]
        delta_to_car_in_front_ms_part = struct.unpack_from("<H", payload, offset + 14)[0]
        delta_to_car_in_front_minutes = payload[offset + 16]
        delta_to_race_leader_ms_part = struct.unpack_from("<H", payload, offset + 17)[0]
        delta_to_race_leader_minutes = payload[offset + 19]
        player = {
            "last_lap_time_ms": struct.unpack_from("<I", payload, offset + 0)[0],
            "current_lap_time_ms": struct.unpack_from("<I", payload, offset + 4)[0],
            "sector1_time_ms_part": sector1_time_ms_part,
            "sector1_time_minutes": sector1_time_minutes,
            "sector1_time_ms": sector1_time_ms_part + sector1_time_minutes * 60_000,
            "sector2_time_ms_part": sector2_time_ms_part,
            "sector2_time_minutes": sector2_time_minutes,
            "sector2_time_ms": sector2_time_ms_part + sector2_time_minutes * 60_000,
            "delta_to_car_in_front_ms_part": delta_to_car_in_front_ms_part,
            "delta_to_car_in_front_minutes": delta_to_car_in_front_minutes,
            "delta_to_car_in_front_ms": delta_to_car_in_front_ms_part + delta_to_car_in_front_minutes * 60_000,
            "delta_to_race_leader_ms_part": delta_to_race_leader_ms_part,
            "delta_to_race_leader_minutes": delta_to_race_leader_minutes,
            "delta_to_race_leader_ms": delta_to_race_leader_ms_part + delta_to_race_leader_minutes * 60_000,
            "lap_distance_m": struct.unpack_from("<f", payload, offset + 20)[0],
            "total_distance_m": struct.unpack_from("<f", payload, offset + 24)[0],
            "safety_car_delta": struct.unpack_from("<f", payload, offset + 28)[0],
            "car_position": payload[offset + 32],
            "current_lap_num": payload[offset + 33],
            "pit_status": payload[offset + 34],
            "num_pit_stops": payload[offset + 35],
            "sector": payload[offset + 36],
            "current_lap_invalid": bool(payload[offset + 37]),
            "penalties": payload[offset + 38],
            "total_warnings": payload[offset + 39],
            "corner_cutting_warnings": payload[offset + 40],
            "num_unserved_drive_through_pens": payload[offset + 41],
            "num_unserved_stop_go_pens": payload[offset + 42],
            "grid_position": payload[offset + 43],
            "driver_status": payload[offset + 44],
            "result_status": payload[offset + 45],
            "pit_lane_timer_active": bool(payload[offset + 46]),
            "pit_lane_time_in_lane_ms": struct.unpack_from("<H", payload, offset + 47)[0],
            "pit_stop_timer_ms": struct.unpack_from("<H", payload, offset + 49)[0],
            "pit_stop_should_serve_pen": bool(payload[offset + 51]),
            "time_trial_personal_best_car_idx": payload[tail_offset] if len(payload) > tail_offset else 255,
            "time_trial_rival_car_idx": payload[tail_offset + 1] if len(payload) > tail_offset + 1 else 255,
        }
        all_cars = [self._decode_lap_data_car(payload, car_index) for car_index in range(22)]
        player["all_cars"] = all_cars
        return player

    def _decode_lap_data_car(self, payload: bytes, car_index: int) -> dict[str, Any]:
        offset = self.HEADER_SIZE + car_index * self.LAP_DATA_CAR_SIZE
        sector1_time_ms_part = struct.unpack_from("<H", payload, offset + 8)[0]
        sector1_time_minutes = payload[offset + 10]
        sector2_time_ms_part = struct.unpack_from("<H", payload, offset + 11)[0]
        sector2_time_minutes = payload[offset + 13]
        delta_to_car_in_front_ms_part = struct.unpack_from("<H", payload, offset + 14)[0]
        delta_to_car_in_front_minutes = payload[offset + 16]
        delta_to_race_leader_ms_part = struct.unpack_from("<H", payload, offset + 17)[0]
        delta_to_race_leader_minutes = payload[offset + 19]
        return {
            "car_index": car_index,
            "last_lap_time_ms": struct.unpack_from("<I", payload, offset + 0)[0],
            "current_lap_time_ms": struct.unpack_from("<I", payload, offset + 4)[0],
            "sector1_time_ms_part": sector1_time_ms_part,
            "sector1_time_minutes": sector1_time_minutes,
            "sector1_time_ms": sector1_time_ms_part + sector1_time_minutes * 60_000,
            "sector2_time_ms_part": sector2_time_ms_part,
            "sector2_time_minutes": sector2_time_minutes,
            "sector2_time_ms": sector2_time_ms_part + sector2_time_minutes * 60_000,
            "delta_to_car_in_front_ms_part": delta_to_car_in_front_ms_part,
            "delta_to_car_in_front_minutes": delta_to_car_in_front_minutes,
            "delta_to_car_in_front_ms": delta_to_car_in_front_ms_part + delta_to_car_in_front_minutes * 60_000,
            "delta_to_race_leader_ms_part": delta_to_race_leader_ms_part,
            "delta_to_race_leader_minutes": delta_to_race_leader_minutes,
            "delta_to_race_leader_ms": delta_to_race_leader_ms_part + delta_to_race_leader_minutes * 60_000,
            "lap_distance_m": struct.unpack_from("<f", payload, offset + 20)[0],
            "total_distance_m": struct.unpack_from("<f", payload, offset + 24)[0],
            "safety_car_delta": struct.unpack_from("<f", payload, offset + 28)[0],
            "car_position": payload[offset + 32],
            "current_lap_num": payload[offset + 33],
            "pit_status": payload[offset + 34],
            "num_pit_stops": payload[offset + 35],
            "sector": payload[offset + 36],
            "current_lap_invalid": bool(payload[offset + 37]),
            "penalties": payload[offset + 38],
            "total_warnings": payload[offset + 39],
            "corner_cutting_warnings": payload[offset + 40],
            "driver_status": payload[offset + 44],
            "result_status": payload[offset + 45],
        }

    def _decode_participants(self, payload: bytes, player_car_index: int) -> dict[str, Any]:
        offset = self.HEADER_SIZE
        if len(payload) <= offset:
            return {}

        num_active_cars = payload[offset]
        participant_size = 57
        participants = []
        for car_index in range(22):
            base = offset + 1 + car_index * participant_size
            block = payload[base : base + participant_size]
            if len(block) < participant_size:
                break
            name = self._decode_participant_name(block[7:55])
            participants.append(
                {
                    "car_index": car_index,
                    "ai_controlled": bool(block[0]),
                    "driver_id": block[1],
                    "network_id": block[2],
                    "team_id": block[3],
                    "my_team": bool(block[4]),
                    "race_number": block[5],
                    "nationality": block[6],
                    "name": name or f"Car {car_index}",
                    "telemetry_setting": block[55],
                    "show_online_names": bool(block[56]),
                }
            )

        player = participants[player_car_index] if 0 <= player_car_index < len(participants) else {}
        return {
            "num_active_cars": num_active_cars,
            "player": player,
            "all_cars": participants,
        }

    def _decode_lobby_info(self, payload: bytes, player_car_index: int) -> dict[str, Any]:
        """Decode multiplayer lobby participant metadata.

        备注:
        当前抓包样本不含 packet 9，这里按 F1 24 布局和 F1 25 官方
        “名称长度缩短到 32 字节、包长变为 954 bytes”的变更实现保守解析。
        结果先挂到 raw.lobby_info，等待后续样本验证，不进入策略主路径。
        """
        offset = self.HEADER_SIZE
        if len(payload) <= offset:
            return {}
        num_players = payload[offset]
        players = []
        for car_index in range(22):
            base = offset + 1 + car_index * self.LOBBY_INFO_RECORD_SIZE
            block = payload[base : base + self.LOBBY_INFO_RECORD_SIZE]
            if len(block) < self.LOBBY_INFO_RECORD_SIZE:
                break
            name_end = 4 + self.LOBBY_PLAYER_NAME_BYTES
            players.append(
                {
                    "car_index": car_index,
                    "ai_controlled": bool(block[0]),
                    "team_id": block[1],
                    "nationality": block[2],
                    "platform": block[3],
                    "name": self._decode_participant_name(block[4:name_end]) or f"LobbyCar {car_index}",
                    "car_number": block[name_end],
                    "telemetry_setting": block[name_end + 1],
                    "show_online_names": bool(block[name_end + 2]),
                    "tech_level": struct.unpack_from("<H", block, name_end + 3)[0],
                    "ready_status": block[name_end + 5],
                }
            )
        active_players = [
            entry
            for entry in players
            if any(
                (
                    entry["team_id"],
                    entry["nationality"],
                    entry["platform"],
                    entry["car_number"],
                    entry["telemetry_setting"],
                    entry["show_online_names"],
                    entry["tech_level"],
                    entry["ready_status"],
                    not entry["name"].startswith("LobbyCar "),
                )
            )
        ][: min(num_players, len(players))]
        player = players[player_car_index] if 0 <= player_car_index < len(players) else {}
        tail_offset = offset + 1 + 22 * self.LOBBY_INFO_RECORD_SIZE
        return {
            "num_players": num_players,
            "player": player,
            "active_players": active_players,
            "all_players": players,
            "tail_hex": payload[tail_offset:].hex(),
        }

    def _decode_participant_name(self, raw_name: bytes) -> str:
        trimmed = raw_name.split(b"\x00", 1)[0].replace(b"\xff", b"")
        return trimmed.decode("utf-8", errors="ignore").strip()

    def _decode_car_telemetry(self, payload: bytes, player_car_index: int) -> dict[str, Any]:
        offset = self.HEADER_SIZE + player_car_index * self.CAR_TELEMETRY_SIZE
        values = struct.unpack_from(self.CAR_TELEMETRY_FORMAT, payload, offset)
        tail_offset = self.HEADER_SIZE + 22 * self.CAR_TELEMETRY_SIZE
        player = {
            "speed_kph": values[0],
            "throttle": values[1],
            "steer": values[2],
            "brake": values[3],
            "clutch": values[4],
            "gear": values[5],
            "engine_rpm": values[6],
            "drs": bool(values[7]),
            "rev_lights_percent": values[8],
            "rev_lights_bit_value": values[9],
            "brakes_temperature": list(values[10:14]),
            "tyres_surface_temperature": list(values[14:18]),
            "tyres_inner_temperature": list(values[18:22]),
            "engine_temperature": values[22],
            "tyres_pressure": list(values[23:27]),
            "surface_type": list(values[27:31]),
            "mfd_panel_index": payload[tail_offset],
            "mfd_panel_index_secondary": payload[tail_offset + 1],
            "suggested_gear": struct.unpack_from("<b", payload, tail_offset + 2)[0],
        }
        player["all_cars"] = [self._decode_car_telemetry_car(payload, car_index) for car_index in range(22)]
        return player

    def _decode_car_setups(self, payload: bytes, player_car_index: int) -> dict[str, Any]:
        player = self._decode_car_setups_car(payload, player_car_index)
        player["all_cars"] = [self._decode_car_setups_car(payload, car_index) for car_index in range(22)]
        return player

    def _decode_car_setups_car(self, payload: bytes, car_index: int) -> dict[str, Any]:
        offset = self.HEADER_SIZE + car_index * self.CAR_SETUPS_SIZE
        values = struct.unpack_from(self.CAR_SETUPS_FORMAT, payload, offset)
        return {
            "car_index": car_index,
            "front_wing": values[0],
            "rear_wing": values[1],
            "on_throttle": values[2],
            "off_throttle": values[3],
            "front_camber": values[4],
            "rear_camber": values[5],
            "front_toe": values[6],
            "rear_toe": values[7],
            "front_suspension": values[8],
            "rear_suspension": values[9],
            "front_anti_roll_bar": values[10],
            "rear_anti_roll_bar": values[11],
            "front_suspension_height": values[12],
            "rear_suspension_height": values[13],
            "brake_pressure": values[14],
            "brake_bias": values[15],
            "engine_braking": values[16],
            "rear_left_tyre_pressure": values[17],
            "rear_right_tyre_pressure": values[18],
            "front_left_tyre_pressure": values[19],
            "front_right_tyre_pressure": values[20],
            "ballast": values[21],
            "fuel_load": values[22],
        }

    def _decode_car_telemetry_car(self, payload: bytes, car_index: int) -> dict[str, Any]:
        offset = self.HEADER_SIZE + car_index * self.CAR_TELEMETRY_SIZE
        values = struct.unpack_from(self.CAR_TELEMETRY_FORMAT, payload, offset)
        return {
            "car_index": car_index,
            "speed_kph": values[0],
            "throttle": values[1],
            "steer": values[2],
            "brake": values[3],
            "gear": values[5],
            "engine_rpm": values[6],
            "drs": bool(values[7]),
        }

    def _decode_car_status(self, payload: bytes, player_car_index: int) -> dict[str, Any]:
        offset = self.HEADER_SIZE + player_car_index * self.CAR_STATUS_SIZE
        values = struct.unpack_from(self.CAR_STATUS_FORMAT, payload, offset)
        player = {
            "traction_control": values[0],
            "anti_lock_brakes": bool(values[1]),
            "fuel_mix": values[2],
            "front_brake_bias": values[3],
            "pit_limiter_status": bool(values[4]),
            "fuel_in_tank": values[5],
            "fuel_capacity": values[6],
            "fuel_remaining_laps": values[7],
            "max_rpm": values[8],
            "idle_rpm": values[9],
            "max_gears": values[10],
            "drs_allowed": bool(values[11]),
            "drs_activation_distance": values[12],
            "actual_tyre_compound": values[13],
            "visual_tyre_compound": values[14],
            "tyres_age_laps": values[15],
            "vehicle_fia_flags": values[16],
            "engine_power_ice": values[17],
            "engine_power_mguk": values[18],
            "ers_store_energy": values[19],
            "ers_deploy_mode": values[20],
            "ers_harvested_this_lap_mguk": values[21],
            "ers_harvested_this_lap_mguh": values[22],
            "ers_deployed_this_lap": values[23],
            "network_paused": bool(values[24]),
        }
        player["all_cars"] = [self._decode_car_status_car(payload, car_index) for car_index in range(22)]
        return player

    def _decode_car_status_car(self, payload: bytes, car_index: int) -> dict[str, Any]:
        offset = self.HEADER_SIZE + car_index * self.CAR_STATUS_SIZE
        values = struct.unpack_from(self.CAR_STATUS_FORMAT, payload, offset)
        return {
            "car_index": car_index,
            "fuel_remaining_laps": values[7],
            "drs_allowed": bool(values[11]),
            "actual_tyre_compound": values[13],
            "visual_tyre_compound": values[14],
            "tyres_age_laps": values[15],
            "ers_store_energy": values[19],
        }

    def _decode_final_classification(self, payload: bytes, player_car_index: int) -> dict[str, Any]:
        offset = self.HEADER_SIZE
        num_cars = payload[offset] if len(payload) > offset else 0
        record_size = 46
        classifications = []
        for car_index in range(22):
            base = offset + 1 + car_index * record_size
            block = payload[base : base + record_size]
            if len(block) < record_size:
                break
            classifications.append(
                {
                    "car_index": car_index,
                    "position": block[0],
                    "num_laps": block[1],
                    "grid_position": block[2],
                    "points": block[3],
                    "num_pit_stops": block[4],
                    "result_status": block[5],
                    "best_lap_time_ms": struct.unpack_from("<I", block, 6)[0],
                    "total_race_time_s": struct.unpack_from("<d", block, 10)[0],
                    "penalties_time_s": block[18],
                    "num_penalties": block[19],
                    "num_tyre_stints": block[20],
                    "tyre_stints_actual": list(block[21:29]),
                    "tyre_stints_visual": list(block[29:37]),
                    "tyre_stints_end_laps": list(block[37:45]),
                }
            )
        player = classifications[player_car_index] if 0 <= player_car_index < len(classifications) else {}
        return {
            "num_cars": num_cars,
            "player": player,
            "all_cars": classifications,
        }

    def _decode_car_damage(self, payload: bytes, player_car_index: int) -> dict[str, Any]:
        car_size = 46
        offset = self.HEADER_SIZE + player_car_index * car_size
        player = self._decode_car_damage_car(payload, player_car_index)
        player["all_cars"] = [self._decode_car_damage_car(payload, car_index) for car_index in range(22)]
        return player

    def _decode_car_damage_car(self, payload: bytes, car_index: int) -> dict[str, Any]:
        car_size = 46
        offset = self.HEADER_SIZE + car_index * car_size
        tyre_wear = list(struct.unpack_from("<4f", payload, offset))
        tyre_damage = list(payload[offset + 16 : offset + 20])
        brakes_damage = list(payload[offset + 20 : offset + 24])
        return {
            "car_index": car_index,
            "tyres_wear_pct": tyre_wear,
            "tyres_damage_pct": tyre_damage,
            "brakes_damage_pct": brakes_damage,
            "tyre_blisters_pct": list(payload[offset + 24 : offset + 28]),
            "front_left_wing_damage_pct": payload[offset + 28],
            "front_right_wing_damage_pct": payload[offset + 29],
            "rear_wing_damage_pct": payload[offset + 30],
            "floor_damage_pct": payload[offset + 31],
            "diffuser_damage_pct": payload[offset + 32],
            "sidepod_damage_pct": payload[offset + 33],
            "drs_fault": bool(payload[offset + 34]),
            "ers_fault": bool(payload[offset + 35]),
            "gearbox_damage_pct": payload[offset + 36],
            "engine_damage_pct": payload[offset + 37],
            "engine_components_damage_pct": {
                "mguh": payload[offset + 38],
                "energy_store": payload[offset + 39],
                "control_electronics": payload[offset + 40],
                "ice": payload[offset + 41],
                "mguk": payload[offset + 42],
                "turbo_charger": payload[offset + 43],
            },
            "engine_blown": bool(payload[offset + 44]),
            "engine_seized": bool(payload[offset + 45]),
        }

    def _decode_tyre_sets(self, payload: bytes) -> dict[str, Any]:
        offset = self.HEADER_SIZE
        records = []
        record_size = 10
        for index in range(20):
            base = offset + index * record_size
            block = payload[base : base + record_size]
            if len(block) < record_size:
                break
            records.append(
                {
                    "set_index": index,
                    "raw_hex": block.hex(),
                    "actual_tyre_compound": block[0],
                    "visual_tyre_compound": block[1],
                    "wear_pct": block[2],
                    "available": bool(block[3]),
                    "recommended_session": block[4],
                    "life_span_laps": block[5],
                    "usable_life_laps": block[6],
                    "lap_delta_time_ms": int.from_bytes(block[7:9], "little", signed=True),
                    "fitted": bool(block[9]),
                }
            )
        tail_offset = offset + 20 * record_size
        return {
            "sets": records,
            "fitted_idx": payload[tail_offset] if len(payload) > tail_offset else 255,
            "requested_fitted_idx": payload[tail_offset + 1] if len(payload) > tail_offset + 1 else 255,
        }

    def _decode_session_history(self, payload: bytes) -> dict[str, Any]:
        offset = self.HEADER_SIZE
        if len(payload) < offset + 7:
            return {}
        lap_history_offset = offset + 7
        lap_record_size = 14
        lap_history = []
        for index in range(100):
            base = lap_history_offset + index * lap_record_size
            block = payload[base : base + lap_record_size]
            if len(block) < lap_record_size:
                break
            lap_history.append(
                {
                    "lap": index + 1,
                    "lap_time_ms": struct.unpack_from("<I", block, 0)[0],
                    "sector1_time_ms_part": struct.unpack_from("<H", block, 4)[0],
                    "sector1_time_minutes": block[6],
                    "sector2_time_ms_part": struct.unpack_from("<H", block, 7)[0],
                    "sector2_time_minutes": block[9],
                    "sector3_time_ms_part": struct.unpack_from("<H", block, 10)[0],
                    "sector3_time_minutes": block[12],
                    "lap_valid_bit_flags": block[13],
                }
            )
        stint_offset = lap_history_offset + 100 * lap_record_size
        tyre_stints = []
        for index in range(8):
            base = stint_offset + index * 3
            block = payload[base : base + 3]
            if len(block) < 3:
                break
            tyre_stints.append(
                {
                    "stint": index,
                    "end_lap": block[0],
                    "tyre_actual_compound": block[1],
                    "tyre_visual_compound": block[2],
                }
            )
        return {
            "car_index": payload[offset],
            "num_laps": payload[offset + 1],
            "num_tyre_stints": payload[offset + 2],
            "best_lap_time_lap_num": payload[offset + 3],
            "best_sector1_lap_num": payload[offset + 4],
            "best_sector2_lap_num": payload[offset + 5],
            "best_sector3_lap_num": payload[offset + 6],
            "lap_history_data": lap_history,
            "tyre_stints_history_data": tyre_stints,
        }

    def _decode_motion_ex(self, payload: bytes) -> dict[str, Any]:
        offset = self.HEADER_SIZE
        motion_ex_floats = struct.unpack_from("<61f", payload, offset)
        return {
            "suspension_position": list(motion_ex_floats[0:4]),
            "suspension_velocity": list(motion_ex_floats[4:8]),
            "suspension_acceleration": list(motion_ex_floats[8:12]),
            "wheel_speed": list(motion_ex_floats[12:16]),
            "wheel_slip_ratio": list(motion_ex_floats[16:20]),
            "wheel_slip_angle": list(motion_ex_floats[20:24]),
            "wheel_lat_force": list(motion_ex_floats[24:28]),
            "wheel_long_force": list(motion_ex_floats[28:32]),
            "height_of_cog_above_ground": motion_ex_floats[32],
            "local_velocity": {
                "x": motion_ex_floats[33],
                "y": motion_ex_floats[34],
                "z": motion_ex_floats[35],
            },
            "angular_velocity": {
                "x": motion_ex_floats[36],
                "y": motion_ex_floats[37],
                "z": motion_ex_floats[38],
            },
            "angular_acceleration": {
                "x": motion_ex_floats[39],
                "y": motion_ex_floats[40],
                "z": motion_ex_floats[41],
            },
            "front_wheels_angle": motion_ex_floats[42],
            "wheel_vert_force": list(motion_ex_floats[43:47]),
            "front_aero_height": motion_ex_floats[47],
            "rear_aero_height": motion_ex_floats[48],
            "front_roll_angle": motion_ex_floats[49],
            "rear_roll_angle": motion_ex_floats[50],
            "chassis_yaw": motion_ex_floats[51],
            "chassis_pitch": motion_ex_floats[52],
            "wheel_camber": list(motion_ex_floats[53:57]),
            "wheel_camber_gain": list(motion_ex_floats[57:61]),
        }

    def _decode_lap_positions(self, payload: bytes, player_car_index: int) -> dict[str, Any]:
        """Decode the lap-position history matrix packet.

        备注:
        这个 packet 在 F1 25 中是固定长度 1131 bytes：
        header + num_laps + lap_start + 50x22 的位置矩阵。
        每一行表示一圈，每一列表示 car_index，该值为该车该圈完赛位置。
        """
        offset = self.HEADER_SIZE
        num_laps = payload[offset] if len(payload) > offset else 0
        lap_start = payload[offset + 1] if len(payload) > offset + 1 else 0
        matrix_offset = offset + 2
        max_laps = 50
        car_count = 22
        lap_positions = []
        player_lap_positions = []
        for lap_index in range(max_laps):
            base = matrix_offset + lap_index * car_count
            block = payload[base : base + car_count]
            if len(block) < car_count:
                break
            row = list(block)
            lap_number = lap_start + lap_index
            if lap_index < num_laps:
                lap_positions.append(
                    {
                        "lap_index": lap_index,
                        "lap_number": lap_number,
                        "positions_by_car_index": row,
                    }
                )
                player_position = row[player_car_index] if 0 <= player_car_index < len(row) else 0
                player_lap_positions.append(
                    {
                        "lap_index": lap_index,
                        "lap_number": lap_number,
                        "position": player_position if player_position > 0 else None,
                    }
                )
        tail_offset = matrix_offset + max_laps * car_count
        return {
            "num_laps": num_laps,
            "lap_start": lap_start,
            "max_laps_supported": max_laps,
            "car_count": car_count,
            "player_car_index": player_car_index,
            "player_lap_positions": player_lap_positions,
            "lap_positions": lap_positions,
            "tail_hex": payload[tail_offset:].hex(),
        }

    def _decode_time_trial(self, payload: bytes) -> dict[str, Any]:
        dataset_size = 24
        offset = self.HEADER_SIZE
        labels = ("player_session_best", "personal_best", "rival_session_best")
        datasets = {}
        for index, label in enumerate(labels):
            base = offset + index * dataset_size
            block = payload[base : base + dataset_size]
            if len(block) < dataset_size:
                break
            datasets[label] = {
                "car_index": block[0],
                "team_id": block[1],
                "lap_time_ms": struct.unpack_from("<I", block, 2)[0],
                "sector1_time_ms": struct.unpack_from("<I", block, 6)[0],
                "sector2_time_ms": struct.unpack_from("<I", block, 10)[0],
                "sector3_time_ms": struct.unpack_from("<I", block, 14)[0],
                "traction_control": block[18],
                "gearbox_assist": block[19],
                "anti_lock_brakes": bool(block[20]),
                "equal_car_performance": bool(block[21]),
                "custom_setup": bool(block[22]),
                "valid": bool(block[23]),
            }
        return datasets

    def _decode_body(self, payload: bytes, packet_id: int, player_car_index: int) -> dict[str, Any]:
        # 备注:
        # 这里只分发当前主链路需要的 packet 类型，其他 packet 默认返回空 body。
        if packet_id == self.MOTION_PACKET_ID:
            return self._decode_motion(payload, player_car_index)
        if packet_id == self.SESSION_PACKET_ID:
            return self._decode_session(payload)
        if packet_id == self.LAP_DATA_PACKET_ID:
            return self._decode_lap_data(payload, player_car_index)
        if packet_id == self.PARTICIPANTS_PACKET_ID:
            return self._decode_participants(payload, player_car_index)
        if packet_id == self.CAR_SETUPS_PACKET_ID:
            return self._decode_car_setups(payload, player_car_index)
        if packet_id == self.CAR_TELEMETRY_PACKET_ID:
            return self._decode_car_telemetry(payload, player_car_index)
        if packet_id == self.CAR_STATUS_PACKET_ID:
            return self._decode_car_status(payload, player_car_index)
        if packet_id == self.FINAL_CLASSIFICATION_PACKET_ID:
            return self._decode_final_classification(payload, player_car_index)
        if packet_id == self.LOBBY_INFO_PACKET_ID:
            return self._decode_lobby_info(payload, player_car_index)
        if packet_id == self.CAR_DAMAGE_PACKET_ID:
            return self._decode_car_damage(payload, player_car_index)
        if packet_id == self.SESSION_HISTORY_PACKET_ID:
            return self._decode_session_history(payload)
        if packet_id == self.TYRE_SETS_PACKET_ID:
            return self._decode_tyre_sets(payload)
        if packet_id == self.MOTION_EX_PACKET_ID:
            return self._decode_motion_ex(payload)
        if packet_id == self.TIME_TRIAL_PACKET_ID:
            return self._decode_time_trial(payload)
        if packet_id == self.EVENT_PACKET_ID:
            return self._decode_event(payload)
        if packet_id == self.LAP_POSITIONS_PACKET_ID:
            return self._decode_lap_positions(payload, player_car_index)
        return {}

    def _decode_event(self, payload: bytes) -> dict[str, Any]:
        if len(payload) < self.HEADER_SIZE + 4:
            return {}
        event_code = payload[self.HEADER_SIZE : self.HEADER_SIZE + 4].decode("ascii", errors="replace")
        detail_payload = payload[self.HEADER_SIZE + 4 :]
        event = {
            "event_code": event_code,
            "event_detail": self._decode_event_detail(event_code, detail_payload),
        }
        if event_code == "BUTN" and len(detail_payload) >= 4:
            event["button_status"] = struct.unpack_from("<I", detail_payload, 0)[0]
        return event

    def _decode_event_detail(self, event_code: str, detail_payload: bytes) -> dict[str, Any]:
        """Decode event-specific payloads using the official union layout.

        备注:
        有些 event code 本身没有 detail 结构，样本里看到的后续字节只是
        union 残留，不应强行解释成有效字段。
        """
        if event_code == "FTLP" and len(detail_payload) >= 5:
            return {
                "vehicle_idx": detail_payload[0],
                "lap_time_s": round(struct.unpack_from("<f", detail_payload, 1)[0], 6),
            }
        if event_code in {"RTMT", "TMPT", "RCWN"} and len(detail_payload) >= 1:
            return {"vehicle_idx": detail_payload[0]}
        if event_code in {"SSTA", "SEND", "DRSE", "DRSD", "CHQF", "LGOT", "RDFL"}:
            return {}
        if event_code == "STLG" and len(detail_payload) >= 1:
            return {"num_lights": detail_payload[0]}
        if event_code in {"DTSV", "SGSV"} and len(detail_payload) >= 1:
            return {"vehicle_idx": detail_payload[0]}
        if event_code == "PENA" and len(detail_payload) >= 7:
            return {
                "penalty_type": detail_payload[0],
                "infringement_type": detail_payload[1],
                "vehicle_idx": detail_payload[2],
                "other_vehicle_idx": detail_payload[3],
                "time_s": detail_payload[4],
                "lap_num": detail_payload[5],
                "places_gained": detail_payload[6],
            }
        if event_code == "SPTP" and len(detail_payload) >= 13:
            return {
                "vehicle_idx": detail_payload[0],
                "speed_kph": round(struct.unpack_from("<f", detail_payload, 1)[0], 6),
                "is_overall_fastest_in_session": bool(detail_payload[5]),
                "is_driver_fastest_in_session": bool(detail_payload[6]),
                "fastest_vehicle_idx_in_session": detail_payload[7],
                "fastest_speed_in_session_kph": round(struct.unpack_from("<f", detail_payload, 8)[0], 6),
            }
        if event_code == "OVTK" and len(detail_payload) >= 2:
            return {
                "overtaking_vehicle_idx": detail_payload[0],
                "being_overtaken_vehicle_idx": detail_payload[1],
            }
        if event_code == "FLBK" and len(detail_payload) >= 8:
            return {
                "flashback_frame_identifier": struct.unpack_from("<I", detail_payload, 0)[0],
                "flashback_session_time_s": round(struct.unpack_from("<f", detail_payload, 4)[0], 6),
            }
        if event_code == "SCAR" and len(detail_payload) >= 2:
            return {
                "safety_car_type": detail_payload[0],
                "event_type": detail_payload[1],
            }
        if event_code == "COLL" and len(detail_payload) >= 2:
            return {
                "vehicle_1_idx": detail_payload[0],
                "vehicle_2_idx": detail_payload[1],
            }
        if event_code == "BUTN" and len(detail_payload) >= 4:
            return {"button_status": struct.unpack_from("<I", detail_payload, 0)[0]}
        return {}
