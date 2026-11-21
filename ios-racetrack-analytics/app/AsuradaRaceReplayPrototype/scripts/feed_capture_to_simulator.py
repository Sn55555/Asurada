#!/usr/bin/env python3
"""
Feed F1 25 UDP capture jsonl directly into iOS Simulator bridge file.

Input format:
  jsonl lines containing payload_base64 from UDP capture.
Output format:
  normalized NDJSON packets:
    {second, speedKph, throttlePct, brakePct, delta, worldX, worldY, trackName, ...}
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
import subprocess
import sys
import time
from pathlib import Path


HEADER_FORMAT = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 29
PACKET_ID_MOTION = 0
PACKET_ID_SESSION = 1
PACKET_ID_LAP_DATA = 2
PACKET_ID_CAR_TELEMETRY = 6
PACKET_ID_CAR_DAMAGE = 10

CAR_MOTION_SIZE = 60
LAP_DATA_SIZE = 57
CAR_DAMAGE_SIZE = 46

# Session packet offsets after header for Codemasters F1 UDP format (2025-compatible).
SESSION_TRACK_LENGTH_OFFSET = 4  # uint16
SESSION_TRACK_ID_OFFSET = 7  # int8

CAR_TELEMETRY_PREFIX_FORMAT = "<HfffBbHBBH"
CAR_TELEMETRY_PREFIX_SIZE = struct.calcsize(CAR_TELEMETRY_PREFIX_FORMAT)  # 22
CAR_TELEMETRY_SIZE = 59

TRACK_NAMES = {
    0: "Melbourne Grand Prix Circuit",
    1: "Paul Ricard",
    2: "Shanghai International Circuit",
    3: "Bahrain International Circuit",
    4: "Circuit de Barcelona-Catalunya",
    5: "Circuit de Monaco",
    6: "Circuit Gilles Villeneuve",
    7: "Silverstone Circuit",
    8: "Hockenheimring",
    9: "Hungaroring",
    10: "Circuit de Spa-Francorchamps",
    11: "Autodromo Nazionale Monza",
    12: "Marina Bay Street Circuit",
    13: "Suzuka International Racing Course",
    14: "Yas Marina Circuit",
    15: "Circuit of the Americas",
    16: "Autodromo Jose Carlos Pace (Interlagos)",
    17: "Red Bull Ring",
    18: "Sochi Autodrom",
    19: "Autodromo Hermanos Rodriguez",
    20: "Baku City Circuit",
    21: "Bahrain Short",
    22: "Silverstone Short",
    23: "COTA Short",
    24: "Suzuka Short",
    25: "Hanoi Circuit",
    26: "Circuit Zandvoort",
    27: "Autodromo Enzo e Dino Ferrari (Imola)",
    28: "Algarve International Circuit (Portimao)",
    29: "Jeddah Corniche Circuit",
    30: "Miami International Autodrome",
    31: "Las Vegas Strip Circuit",
    32: "Lusail International Circuit",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Feed capture jsonl into simulator telemetry stream file.")
    parser.add_argument("--input", required=True, help="Capture file path (.jsonl)")
    parser.add_argument("--bundle-id", default="com.asurada.AsuradaRaceReplayPrototype")
    parser.add_argument("--sim-device", default="booted")
    parser.add_argument("--max-packets", type=int, default=3000)
    parser.add_argument("--sleep-ms", type=float, default=0.0, help="Delay per packet for visual realtime effect.")
    parser.add_argument("--truncate", action="store_true")
    parser.add_argument("--skip-zero-speed", action="store_true", help="Ignore packets until speed > 0.")
    parser.add_argument("--echo-every", type=int, default=500, help="Progress print interval.")
    return parser.parse_args()


def get_bridge_file(bundle_id: str, sim_device: str) -> Path:
    cmd = ["xcrun", "simctl", "get_app_container", sim_device, bundle_id, "data"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to find simulator app container.\n"
            f"Command: {' '.join(cmd)}\n"
            f"Error: {result.stderr.strip()}"
        )
    container = Path(result.stdout.strip())
    bridge_file = container / "Documents" / "usb_live_stream.ndjson"
    bridge_file.parent.mkdir(parents=True, exist_ok=True)
    if not bridge_file.exists():
        bridge_file.write_text("", encoding="utf-8")
    return bridge_file


def decode_capture_payload(line: str):
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    payload_base64 = record.get("payload_base64")
    if not isinstance(payload_base64, str):
        return None
    try:
        data = base64.b64decode(payload_base64)
    except Exception:
        return None

    if len(data) < HEADER_SIZE:
        return None

    header = struct.unpack_from(HEADER_FORMAT, data, 0)
    packet_id = int(header[5])
    session_time = float(header[7])
    player_car_index = int(header[10])
    return {
        "payload": data,
        "packet_id": packet_id,
        "session_time": session_time,
        "player_car_index": player_car_index,
    }


def parse_session_packet(data: bytes):
    if len(data) < HEADER_SIZE + SESSION_TRACK_ID_OFFSET + 1:
        return None

    track_id = int(struct.unpack_from("<b", data, HEADER_SIZE + SESSION_TRACK_ID_OFFSET)[0])
    track_length = int(struct.unpack_from("<H", data, HEADER_SIZE + SESSION_TRACK_LENGTH_OFFSET)[0])

    packet = {
        "trackId": track_id,
        "trackLengthM": track_length,
    }
    track_name = TRACK_NAMES.get(track_id)
    if track_name:
        packet["trackName"] = track_name
    return packet


def parse_lap_data_packet(data: bytes, player_car_index: int):
    offset = HEADER_SIZE + player_car_index * LAP_DATA_SIZE
    if len(data) < offset + LAP_DATA_SIZE:
        return None

    last_lap_ms, current_lap_ms = struct.unpack_from("<II", data, offset)
    lap_number = int(struct.unpack_from("<B", data, offset + 44)[0])
    return {
        "lapNumber": lap_number,
        "currentLapTimeSec": float(current_lap_ms) / 1000.0,
        "lastLapTimeSec": float(last_lap_ms) / 1000.0,
    }


def parse_motion_packet(data: bytes, player_car_index: int):
    offset = HEADER_SIZE + player_car_index * CAR_MOTION_SIZE
    if len(data) < offset + 12:
        return None

    world_x, _world_y, world_z = struct.unpack_from("<fff", data, offset)
    return {
        "worldX": float(world_x),
        "worldY": float(world_z),
    }


def parse_car_telemetry_packet(data: bytes, session_time: float, player_car_index: int):
    offset = HEADER_SIZE + player_car_index * CAR_TELEMETRY_SIZE
    if len(data) < offset + CAR_TELEMETRY_PREFIX_SIZE:
        return None

    (
        speed_kph,
        throttle,
        steer,
        brake,
        _clutch,
        gear,
        rpm,
        drs,
        rev_lights_percent,
        _rev_lights_bit_value,
    ) = struct.unpack_from(
        CAR_TELEMETRY_PREFIX_FORMAT,
        data,
        offset,
    )
    return {
        "second": float(session_time),
        "speedKph": float(speed_kph),
        "throttlePct": max(0.0, min(100.0, float(throttle) * 100.0)),
        "brakePct": max(0.0, min(100.0, float(brake) * 100.0)),
        "steer": max(-1.0, min(1.0, float(steer))),
        "gear": int(gear),
        "engineRPM": int(rpm),
        "drs": bool(drs),
        "revLightsPercent": int(rev_lights_percent),
        "delta": 0.0,
    }


def parse_car_damage_packet(data: bytes, player_car_index: int):
    offset = HEADER_SIZE + player_car_index * CAR_DAMAGE_SIZE
    if len(data) < offset + CAR_DAMAGE_SIZE:
        return None

    tyre_wear = list(struct.unpack_from("<4f", data, offset))
    return {
        "tyresWearPct": [round(float(value), 2) for value in tyre_wear],
        "tyresDamagePct": list(data[offset + 16 : offset + 20]),
        "brakesDamagePct": list(data[offset + 20 : offset + 24]),
        "tyreBlistersPct": list(data[offset + 24 : offset + 28]),
        "frontLeftWingDamagePct": int(data[offset + 28]),
        "frontRightWingDamagePct": int(data[offset + 29]),
        "rearWingDamagePct": int(data[offset + 30]),
        "floorDamagePct": int(data[offset + 31]),
        "diffuserDamagePct": int(data[offset + 32]),
        "sidepodDamagePct": int(data[offset + 33]),
        "drsFault": bool(data[offset + 34]),
        "ersFault": bool(data[offset + 35]),
        "gearboxDamagePct": int(data[offset + 36]),
        "engineDamagePct": int(data[offset + 37]),
        "engineBlown": bool(data[offset + 44]),
        "engineSeized": bool(data[offset + 45]),
    }


def main() -> int:
    args = parse_args()

    capture_file = Path(args.input).expanduser().resolve()
    if not capture_file.exists():
        print(f"[feed-capture] input not found: {capture_file}", file=sys.stderr)
        return 2

    bridge_file = get_bridge_file(args.bundle_id, args.sim_device)
    print(f"[feed-capture] output: {bridge_file}", file=sys.stderr)
    print(f"[feed-capture] input:  {capture_file}", file=sys.stderr)

    if args.truncate:
        bridge_file.write_text("", encoding="utf-8")

    sent = 0
    started = not args.skip_zero_speed
    live_state = {}
    with capture_file.open("r", encoding="utf-8", errors="ignore") as source, bridge_file.open(
        "a", encoding="utf-8"
    ) as out:
        for raw in source:
            decoded = decode_capture_payload(raw)
            if decoded is None:
                continue

            packet_id = decoded["packet_id"]
            payload = decoded["payload"]
            player_car_index = decoded["player_car_index"]

            if packet_id == PACKET_ID_SESSION:
                session_packet = parse_session_packet(payload)
                if session_packet:
                    live_state.update(session_packet)
                continue

            if packet_id == PACKET_ID_LAP_DATA:
                lap_packet = parse_lap_data_packet(payload, player_car_index)
                if lap_packet:
                    live_state.update(lap_packet)
                continue

            if packet_id == PACKET_ID_MOTION:
                motion_packet = parse_motion_packet(payload, player_car_index)
                if motion_packet:
                    live_state.update(motion_packet)
                continue

            if packet_id == PACKET_ID_CAR_DAMAGE:
                damage_packet = parse_car_damage_packet(payload, player_car_index)
                if damage_packet:
                    live_state.update(damage_packet)
                continue

            if packet_id != PACKET_ID_CAR_TELEMETRY:
                continue

            telemetry_packet = parse_car_telemetry_packet(payload, decoded["session_time"], player_car_index)
            if telemetry_packet is None:
                continue
            if not started and telemetry_packet["speedKph"] <= 0:
                continue

            started = True
            packet = dict(telemetry_packet)
            packet.update(live_state)

            out.write(json.dumps(packet, separators=(",", ":")) + "\n")
            out.flush()
            sent += 1

            if args.sleep_ms > 0:
                time.sleep(args.sleep_ms / 1000.0)
            if args.echo_every > 0 and sent % args.echo_every == 0:
                print(f"[feed-capture] packets: {sent}", file=sys.stderr)
            if sent >= args.max_packets:
                break

    print(f"[feed-capture] total packets: {sent}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
