from __future__ import annotations

import struct
from typing import Any


class RaceDecoder:
    """Internal race wire fields; layout constants come from F125PacketDecoder."""

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
            "speed_trap_fastest_speed_kph": struct.unpack_from("<f", payload, offset + 52)[0],
            "speed_trap_fastest_lap": payload[offset + 56],
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
            "speed_trap_fastest_speed_kph": struct.unpack_from("<f", payload, offset + 52)[0],
            "speed_trap_fastest_lap": payload[offset + 56],
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
            name = self._decode_participant_name(block[7:39])
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
                    "telemetry_setting": block[39],
                    "show_online_names": bool(block[40]),
                    "tech_level": struct.unpack_from("<H", block, 41)[0],
                    "platform": block[43],
                    "num_colours": block[44],
                    "livery_colours": [
                        {"red": block[45 + i * 3], "green": block[46 + i * 3], "blue": block[47 + i * 3]}
                        for i in range(min(block[44], 4))
                    ],
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
