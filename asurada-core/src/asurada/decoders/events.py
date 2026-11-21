from __future__ import annotations

import struct
from typing import Any


class EventDecoder:
    """Internal events wire fields; layout constants come from F125PacketDecoder."""

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
