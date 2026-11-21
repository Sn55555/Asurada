from __future__ import annotations

import struct
from typing import Any


class CarDecoder:
    """Internal cars wire fields; layout constants come from F125PacketDecoder."""

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
            "drs_activation_distance": values[12],
            "actual_tyre_compound": values[13],
            "visual_tyre_compound": values[14],
            "tyres_age_laps": values[15],
            "ers_store_energy": values[19],
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
        car_index = payload[self.HEADER_SIZE]
        offset = self.HEADER_SIZE + 1
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
            "car_index": car_index,
            "sets": records,
            "fitted_idx": payload[tail_offset] if len(payload) > tail_offset else 255,
        }
