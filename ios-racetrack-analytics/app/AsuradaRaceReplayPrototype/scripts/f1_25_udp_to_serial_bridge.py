#!/usr/bin/env python3
"""
F1 25 UDP -> JSON telemetry bridge.

Reads Codemasters F1 UDP telemetry packets and writes normalized JSON lines to
either a serial port or a TCP telemetry receiver. Serial output can be consumed
on the Mac side by:
  scripts/usb_bridge_relay.py --source serial ...

TCP output can be sent directly to the iPhone app's Wi-Fi listener:
  scripts/f1_25_udp_to_serial_bridge.py --listen-ip 0.0.0.0 --output tcp --tcp-target-host iPhoneA.local
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import time
from typing import Optional


PACKET_ID_MOTION = 0
PACKET_ID_SESSION = 1
PACKET_ID_LAP_DATA = 2
PACKET_ID_CAR_TELEMETRY = 6
PACKET_ID_CAR_DAMAGE = 10

# uint16 packetFormat
# uint8 gameYear
# uint8 gameMajorVersion
# uint8 gameMinorVersion
# uint8 packetVersion
# uint8 packetId
# uint64 sessionUID
# float sessionTime
# uint32 frameIdentifier
# uint32 overallFrameIdentifier
# uint8 playerCarIndex
# uint8 secondaryPlayerCarIndex
HEADER_FORMAT = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 29

# CarTelemetryData (first fields we need)
# uint16 speed
# float throttle
# float steer
# float brake
# uint8 clutch
# int8 gear
# uint16 engineRPM
# uint8 drs
# uint8 revLightsPercent
# uint16 revLightsBitValue
CAR_TELEMETRY_PREFIX_FORMAT = "<HfffBbHBBH"
CAR_TELEMETRY_PREFIX_SIZE = struct.calcsize(CAR_TELEMETRY_PREFIX_FORMAT)  # 22
CAR_TELEMETRY_SIZE = 59
CAR_MOTION_SIZE = 60
LAP_DATA_SIZE = 57
CAR_DAMAGE_SIZE = 46
SESSION_TRACK_LENGTH_OFFSET = 4  # uint16
SESSION_TRACK_ID_OFFSET = 7  # int8

TRACK_NAMES = {
    0: "Melbourne Grand Prix Circuit",
    2: "Shanghai International Circuit",
    3: "Bahrain International Circuit",
    4: "Circuit de Barcelona-Catalunya",
    5: "Circuit de Monaco",
    6: "Circuit Gilles Villeneuve",
    7: "Silverstone Circuit",
    10: "Circuit de Spa-Francorchamps",
    11: "Autodromo Nazionale Monza",
    12: "Marina Bay Street Circuit",
    13: "Suzuka International Racing Course",
    14: "Yas Marina Circuit",
    15: "Circuit of the Americas",
    16: "Autodromo Jose Carlos Pace (Interlagos)",
    17: "Red Bull Ring",
    26: "Circuit Zandvoort",
    27: "Autodromo Enzo e Dino Ferrari (Imola)",
    29: "Jeddah Corniche Circuit",
    30: "Miami International Autodrome",
    31: "Las Vegas Strip Circuit",
    32: "Lusail International Circuit",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bridge F1 25 UDP telemetry to JSON stream.")
    parser.add_argument("--listen-ip", default="127.0.0.1", help="UDP listen IP, use 127.0.0.1 for same PC.")
    parser.add_argument("--listen-port", type=int, default=20777, help="F1 25 UDP port.")
    parser.add_argument("--output", choices=["serial", "tcp", "stdout"], default="serial")
    parser.add_argument("--serial-port", default="", help="Serial output port, e.g. COM5.")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--tcp-target-host", default="iPhoneA.local")
    parser.add_argument("--tcp-target-port", type=int, default=9077)
    parser.add_argument("--echo", action="store_true", help="Echo JSON packets to stdout.")
    parser.add_argument("--max-hz", type=float, default=60.0, help="Output cap rate.")
    return parser.parse_args()


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def parse_header(data: bytes) -> Optional[dict]:
    if len(data) < HEADER_SIZE:
        return None

    (
        packet_format,
        game_year,
        _major,
        _minor,
        _packet_version,
        packet_id,
        _session_uid,
        session_time,
        _frame_id,
        _overall_frame_id,
        player_car_index,
        _secondary_player_car_index,
    ) = struct.unpack_from(HEADER_FORMAT, data, 0)
    return {
        "packet_format": packet_format,
        "game_year": game_year,
        "packet_id": packet_id,
        "session_time": session_time,
        "player_car_index": player_car_index,
    }


def parse_session_packet(data: bytes) -> Optional[dict]:
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


def parse_lap_data_packet(data: bytes, player_car_index: int) -> Optional[dict]:
    offset = HEADER_SIZE + player_car_index * LAP_DATA_SIZE
    if len(data) < offset + LAP_DATA_SIZE:
        return None

    last_lap_ms, current_lap_ms = struct.unpack_from("<II", data, offset)
    return {
        "lastLapTimeSec": float(last_lap_ms) / 1000.0,
        "currentLapTimeSec": float(current_lap_ms) / 1000.0,
        "carPosition": int(data[offset + 32]),
        "lapNumber": int(data[offset + 33]),
        "sector": int(data[offset + 36]),
    }


def parse_motion_packet(data: bytes, player_car_index: int) -> Optional[dict]:
    offset = HEADER_SIZE + player_car_index * CAR_MOTION_SIZE
    if len(data) < offset + 12:
        return None

    world_x, _world_y, world_z = struct.unpack_from("<fff", data, offset)
    return {
        "worldX": float(world_x),
        "worldY": float(world_z),
    }


def parse_car_telemetry_packet(data: bytes, header: dict, live_state: dict) -> Optional[dict]:
    if header["packet_id"] != PACKET_ID_CAR_TELEMETRY:
        return None

    player_car_index = int(header["player_car_index"])
    player_offset = HEADER_SIZE + player_car_index * CAR_TELEMETRY_SIZE
    if len(data) < player_offset + CAR_TELEMETRY_PREFIX_SIZE:
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
    ) = struct.unpack_from(CAR_TELEMETRY_PREFIX_FORMAT, data, player_offset)

    packet = {
        "second": float(header["session_time"]),
        "speedKph": float(speed_kph),
        "throttlePct": clamp(float(throttle), 0.0, 1.0) * 100.0,
        "brakePct": clamp(float(brake), 0.0, 1.0) * 100.0,
        "steer": clamp(float(steer), -1.0, 1.0),
        "gear": int(gear),
        "engineRPM": int(rpm),
        "drs": bool(drs),
        "revLightsPercent": int(rev_lights_percent),
        "delta": 0.0,
        "packetFormat": int(header["packet_format"]),
        "gameYear": int(header["game_year"]),
    }
    packet.update(live_state)
    return packet


def parse_car_damage_packet(data: bytes, player_car_index: int) -> Optional[dict]:
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


class LineWriter:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.serial = None
        self.tcp: Optional[socket.socket] = None

    def __enter__(self):
        if self.args.output == "serial":
            if not self.args.serial_port:
                raise RuntimeError("--serial-port is required when --output serial")
            try:
                import serial  # type: ignore
            except ImportError as exc:
                raise RuntimeError("pyserial is required. Install via: pip install pyserial") from exc
            self.serial = serial.Serial(self.args.serial_port, baudrate=self.args.baud, timeout=1)
        elif self.args.output == "tcp":
            self._connect_tcp()
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        if self.serial is not None:
            self.serial.close()
        if self.tcp is not None:
            self.tcp.close()

    def write(self, line: str) -> None:
        data = line.encode("utf-8")
        if self.args.output == "stdout":
            sys.stdout.write(line)
            sys.stdout.flush()
            return
        if self.args.output == "serial":
            assert self.serial is not None
            self.serial.write(data)
            return
        self._write_tcp(data)

    def _connect_tcp(self) -> None:
        if self.tcp is not None:
            self.tcp.close()
            self.tcp = None
        self.tcp = socket.create_connection(
            (self.args.tcp_target_host, self.args.tcp_target_port),
            timeout=5.0,
        )
        self.tcp.settimeout(5.0)

    def _write_tcp(self, data: bytes) -> None:
        if self.tcp is None:
            self._connect_tcp()
        try:
            assert self.tcp is not None
            self.tcp.sendall(data)
        except OSError:
            self._connect_tcp()
            assert self.tcp is not None
            self.tcp.sendall(data)


def main() -> int:
    args = parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.listen_ip, args.listen_port))
    sock.settimeout(1.0)

    print(f"[f1-bridge] UDP listen: {args.listen_ip}:{args.listen_port}", file=sys.stderr)
    if args.output == "serial":
        print(f"[f1-bridge] Serial out: {args.serial_port} @ {args.baud}", file=sys.stderr)
    elif args.output == "tcp":
        print(f"[f1-bridge] TCP out: {args.tcp_target_host}:{args.tcp_target_port}", file=sys.stderr)
    else:
        print("[f1-bridge] stdout out", file=sys.stderr)

    try:
        writer_context = LineWriter(args)
        writer = writer_context.__enter__()
    except RuntimeError as exc:
        print(f"[f1-bridge] {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"[f1-bridge] output connection failed: {exc}", file=sys.stderr)
        return 2

    try:
        packet_count = 0
        last_sent_at = 0.0
        min_interval = 1.0 / max(1.0, args.max_hz)
        live_state: dict = {}

        while True:
            try:
                data, _addr = sock.recvfrom(4096)
            except socket.timeout:
                continue

            header = parse_header(data)
            if header is None:
                continue

            packet_id = int(header["packet_id"])
            player_car_index = int(header["player_car_index"])

            if packet_id == PACKET_ID_SESSION:
                parsed_session = parse_session_packet(data)
                if parsed_session:
                    live_state.update(parsed_session)
                continue

            if packet_id == PACKET_ID_LAP_DATA:
                parsed_lap = parse_lap_data_packet(data, player_car_index)
                if parsed_lap:
                    live_state.update(parsed_lap)
                continue

            if packet_id == PACKET_ID_MOTION:
                parsed_motion = parse_motion_packet(data, player_car_index)
                if parsed_motion:
                    live_state.update(parsed_motion)
                continue

            if packet_id == PACKET_ID_CAR_DAMAGE:
                parsed_damage = parse_car_damage_packet(data, player_car_index)
                if parsed_damage:
                    live_state.update(parsed_damage)
                continue

            parsed = parse_car_telemetry_packet(data, header, live_state)
            if parsed is None:
                continue

            now = time.monotonic()
            if now - last_sent_at < min_interval:
                continue

            line = json.dumps(parsed, separators=(",", ":")) + "\n"
            try:
                writer.write(line)
            except OSError as exc:
                print(f"[f1-bridge] output write failed: {exc}", file=sys.stderr)
                continue

            packet_count += 1
            last_sent_at = now

            if args.echo:
                print(line.rstrip("\n"))

            if packet_count % 120 == 0:
                print(f"[f1-bridge] forwarded packets: {packet_count}", file=sys.stderr)
    finally:
        writer_context.__exit__(None, None, None)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[f1-bridge] stopped", file=sys.stderr)
        raise SystemExit(0)
