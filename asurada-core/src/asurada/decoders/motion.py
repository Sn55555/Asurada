from __future__ import annotations

import struct
from typing import Any


class MotionDecoder:
    """Internal motion wire fields; layout constants come from F125PacketDecoder."""

    def _decode_motion_car(self, payload: bytes, car_index: int) -> dict[str, Any]:
        offset = self.HEADER_SIZE + car_index * self.MOTION_CAR_SIZE
        values = struct.unpack_from(self.MOTION_CAR_FORMAT, payload, offset)
        world_forward_dir = values[6:9]
        world_right_dir = values[9:12]
        return {
            "car_index": car_index,
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


    def _decode_motion(self, payload: bytes, player_car_index: int) -> dict[str, Any]:
        player = self._decode_motion_car(payload, player_car_index)
        player["all_cars"] = [self._decode_motion_car(payload, car_index) for car_index in range(22)]
        return player


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
