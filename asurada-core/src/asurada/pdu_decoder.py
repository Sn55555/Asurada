from __future__ import annotations

import struct
import math
from typing import Any

from .pdu import PacketEnvelope, RawPacket
from .decoders.errors import PacketDecodeError
from .decoders.session import SessionDecoder
from .decoders.motion import MotionDecoder
from .decoders.cars import CarDecoder
from .decoders.race import RaceDecoder
from .decoders.events import EventDecoder


class F125PacketDecoder(SessionDecoder, MotionDecoder, CarDecoder, RaceDecoder, EventDecoder):
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
    SESSION_PREFIX_FORMAT = "<BbbBHBbBHHBBBBBB"
    SESSION_PREFIX_SIZE = struct.calcsize(SESSION_PREFIX_FORMAT)  # 19
    SESSION_MARSHAL_ZONE_SIZE = 5
    SESSION_MAX_MARSHAL_ZONES = 21
    SESSION_FORECAST_SAMPLE_FORMAT = "<BBBbbbbB"
    SESSION_FORECAST_SAMPLE_SIZE = struct.calcsize(SESSION_FORECAST_SAMPLE_FORMAT)  # 8
    SESSION_MAX_FORECAST_SAMPLES = 64
    LOBBY_PLAYER_NAME_BYTES = 32
    LOBBY_INFO_RECORD_SIZE = 42

    # EA's bundled F1 25 wire structures and recorded live packets agree on these
    # fixed sizes. An unknown version or extra bytes are not evidence that offsets
    # remain compatible: reject the packet before any body reaches the assembler.
    PACKET_SIZES = {
        0: 1349, 1: 753, 2: 1285, 3: 45, 4: 1284, 5: 1133,
        6: 1352, 7: 1239, 8: 1042, 9: 954, 10: 1041, 11: 1460,
        12: 231, 13: 273, 14: 101, 15: 1131,
    }
    PLAYER_ARRAY_PACKET_IDS = frozenset({0, 2, 4, 5, 6, 7, 8, 9, 10, 15})

    def decode_raw(self, packet: RawPacket) -> PacketEnvelope:
        # 备注:
        # 所有 packet 先统一过 common header，再按 packet_id 分发正文解析。
        # 这样 assembler 和调试输出可以共享同一份 header 结构。
        if len(packet.payload) < self.HEADER_SIZE:
            raise PacketDecodeError(
                f"packet too small to contain valid F1 25 header: {len(packet.payload)} bytes",
                reason="short_header"
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

        detail = (f"packet_id={packet_id} kind={header['packet_name']} "
                  f"format={packet_format} year={game_year} version={packet_version} "
                  f"bytes={len(packet.payload)}")
        if packet_format != 2025 or game_year != 25:
            raise PacketDecodeError(f"unsupported F1 25 header: {detail}", reason="unsupported_format")
        if not math.isfinite(session_time):
            raise PacketDecodeError(f"non-finite session time: {detail}", reason="invalid_header")
        if packet_id in self.PACKET_SIZES:
            if packet_version != 1:
                raise PacketDecodeError(f"unsupported packet version: {detail}; expected 1", reason="unsupported_version")
            expected_size = self.PACKET_SIZES[packet_id]
            if len(packet.payload) != expected_size:
                raise PacketDecodeError(f"packet size mismatch: {detail}; expected {expected_size}", reason="size_mismatch")
        if packet_id in self.PLAYER_ARRAY_PACKET_IDS and player_car_index >= 22:
            raise PacketDecodeError(f"invalid player car index {player_car_index}: {detail}", reason="invalid_car_index")
        try:
            body = self._decode_body(packet.payload, packet_id, player_car_index)
        except (struct.error, IndexError, UnicodeDecodeError) as exc:
            # Catch only wire-reading failures at the decoder boundary. Never
            # publish a partially decoded body or swallow a strategy/sink error.
            raise PacketDecodeError(f"malformed body: {detail}: {exc}") from exc

        return PacketEnvelope(
            kind=header["packet_name"],
            frame_identifier=frame_identifier,
            session_uid=str(session_uid),
            payload={"header": header, "body": body},
        )


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
