from __future__ import annotations

import struct
from typing import Any

from .errors import PacketDecodeError


class SessionDecoder:
    """Internal session wire fields; layout constants come from F125PacketDecoder."""

    def _decode_session(self, payload: bytes) -> dict[str, Any]:
        """Decode the fixed-width session packet, including the tail settings block.

        备注:
        F1 24/25 的 Session packet 是定长结构。
        之前按“实际天气样本数”截断，导致未使用的 forecast 槽位被误判成 trailer。
        这里改成按固定 64 个 weather sample 后再解析尾部设置字段。
        """
        if len(payload) != 753:
            raise PacketDecodeError(f"invalid F1 25 Session packet size: {len(payload)}; expected 753")
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

        safety_car_offset = (
            marshal_zones_offset + self.SESSION_MAX_MARSHAL_ZONES * self.SESSION_MARSHAL_ZONE_SIZE
        )
        forecast_count_offset = safety_car_offset + 2
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
            "safety_car_status": payload[safety_car_offset],
            "network_game": payload[safety_car_offset + 1],
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
