#!/usr/bin/env python3
"""
USB bridge relay for AsuradaRaceReplayPrototype.

Writes normalized telemetry packets into the iOS Simulator app container:
  <AppData>/Documents/usb_live_stream.ndjson

Input sources:
  - stdin
  - serial (USB CDC/COM-style stream)
  - tcp server

Accepted input line formats:
  1) JSON (any common telemetry keys)
  2) CSV: second,speed,throttle,brake[,delta]
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Relay USB telemetry to Simulator or mounted iPhone document stream.")
    parser.add_argument("--bundle-id", default="com.asurada.AsuradaRaceReplayPrototype")
    parser.add_argument("--sim-device", default="booted", help="simctl device id, default: booted")
    parser.add_argument(
        "--output-file",
        default="",
        help="Direct output file path. If set, simctl lookup is skipped. Use this for mounted iPhone Documents path.",
    )
    parser.add_argument("--source", choices=["stdin", "serial", "tcp"], default="stdin")
    parser.add_argument("--serial-port", default="/dev/tty.usbmodem1")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--tcp-host", default="0.0.0.0")
    parser.add_argument("--tcp-port", type=int, default=9077)
    parser.add_argument("--truncate", action="store_true", help="truncate bridge file before writing")
    parser.add_argument("--echo", action="store_true", help="echo normalized packets to stdout")
    return parser.parse_args()


def get_simulator_bridge_file(bundle_id: str, sim_device: str) -> Path:
    cmd = ["xcrun", "simctl", "get_app_container", sim_device, bundle_id, "data"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(
            "Failed to find simulator app container. "
            "Make sure the app is installed and simulator is booted.\n"
            f"Command: {' '.join(cmd)}\n"
            f"Error: {stderr}"
        )

    container = Path(result.stdout.strip())
    bridge_file = container / "Documents" / "usb_live_stream.ndjson"
    bridge_file.parent.mkdir(parents=True, exist_ok=True)
    if not bridge_file.exists():
        bridge_file.write_text("", encoding="utf-8")
    return bridge_file


def resolve_output_file(args: argparse.Namespace) -> Path:
    if args.output_file:
        target = Path(args.output_file).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("", encoding="utf-8")
        return target
    return get_simulator_bridge_file(args.bundle_id, args.sim_device)


def read_lines_from_stdin() -> Iterator[str]:
    for line in sys.stdin:
        yield line


def read_lines_from_tcp(host: str, port: int) -> Iterator[str]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(1)
        print(f"[usb-bridge] TCP listening on {host}:{port}", file=sys.stderr)
        conn, addr = server.accept()
        print(f"[usb-bridge] TCP connected: {addr}", file=sys.stderr)
        with conn, conn.makefile("r", encoding="utf-8", errors="ignore") as stream:
            for line in stream:
                yield line


def read_lines_from_serial(port: str, baud: int) -> Iterator[str]:
    try:
        import serial  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pyserial is required for --source serial. Install via: pip3 install pyserial"
        ) from exc

    print(f"[usb-bridge] Serial listening on {port} @ {baud}", file=sys.stderr)
    with serial.Serial(port, baudrate=baud, timeout=1) as ser:
        while True:
            data = ser.readline()
            if not data:
                continue
            yield data.decode("utf-8", errors="ignore")


def parse_number(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def pick_number(payload: Dict, keys: Iterable[str]) -> Optional[float]:
    for key in keys:
        if key in payload:
            value = parse_number(payload.get(key))
            if value is not None:
                return value
    return None


def to_percent(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    if value <= 1.0:
        value *= 100.0
    return max(0.0, min(100.0, value))


def normalize_json_line(line: str) -> Optional[Dict]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    second = pick_number(
        payload,
        ["second", "time", "t", "timestampSec", "timestamp_s", "timestampMs", "timestamp_ms", "timestamp", "ts"],
    )
    speed = pick_number(payload, ["speed", "speedKph", "speed_kph", "velocity", "v"])
    throttle = pick_number(payload, ["throttle", "throttlePct", "throttle_pct", "gas", "accel"])
    brake = pick_number(payload, ["brake", "brakePct", "brake_pct"])
    delta = pick_number(payload, ["delta", "lapDelta", "timeDelta", "dt"]) or 0.0

    if speed is None:
        return None

    if second is not None and second > 1_000_000:
        second = second / 1000.0

    packet = {
        "second": second if second is not None else 0.0,
        "speedKph": speed,
        "throttlePct": to_percent(throttle),
        "brakePct": to_percent(brake),
        "delta": delta,
    }

    passthrough_keys = [
        "steer",
        "gear",
        "engineRPM",
        "rpm",
        "drs",
        "revLightsPercent",
        "lapNumber",
        "currentLapNum",
        "currentLapTimeSec",
        "lastLapTimeSec",
        "carPosition",
        "sector",
        "trackId",
        "trackName",
        "trackLengthM",
        "trackLengthMeters",
        "totalLaps",
        "worldX",
        "worldY",
        "worldZ",
        "packetFormat",
        "gameYear",
        "tyresWearPct",
        "tyresDamagePct",
        "brakesDamagePct",
        "tyreBlistersPct",
        "frontLeftWingDamagePct",
        "frontRightWingDamagePct",
        "rearWingDamagePct",
        "floorDamagePct",
        "diffuserDamagePct",
        "sidepodDamagePct",
        "drsFault",
        "ersFault",
        "gearboxDamagePct",
        "engineDamagePct",
        "engineBlown",
        "engineSeized",
    ]
    for key in passthrough_keys:
        if key in payload:
            packet[key] = payload[key]

    return packet


def normalize_csv_line(line: str) -> Optional[Dict]:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 4:
        return None

    second = parse_number(parts[0])
    speed = parse_number(parts[1])
    throttle = parse_number(parts[2])
    brake = parse_number(parts[3])
    delta = parse_number(parts[4]) if len(parts) > 4 else 0.0

    if speed is None:
        return None

    return {
        "second": second if second is not None else 0.0,
        "speedKph": speed,
        "throttlePct": to_percent(throttle),
        "brakePct": to_percent(brake),
        "delta": delta or 0.0,
    }


def normalize_line(line: str) -> Optional[Dict]:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("{"):
        packet = normalize_json_line(stripped)
        if packet is not None:
            return packet
    return normalize_csv_line(stripped)


def line_source(args: argparse.Namespace) -> Iterator[str]:
    if args.source == "stdin":
        return read_lines_from_stdin()
    if args.source == "serial":
        return read_lines_from_serial(args.serial_port, args.baud)
    return read_lines_from_tcp(args.tcp_host, args.tcp_port)


def main() -> int:
    args = parse_args()
    bridge_file = resolve_output_file(args)
    print(f"[usb-bridge] Output: {bridge_file}", file=sys.stderr)

    if args.truncate:
        bridge_file.write_text("", encoding="utf-8")

    count = 0
    try:
        with bridge_file.open("a", encoding="utf-8") as out:
            for raw in line_source(args):
                packet = normalize_line(raw)
                if packet is None:
                    continue
                out.write(json.dumps(packet, separators=(",", ":")) + "\n")
                out.flush()
                count += 1
                if args.echo:
                    print(json.dumps(packet, ensure_ascii=False))
                if count % 100 == 0:
                    print(f"[usb-bridge] packets: {count}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n[usb-bridge] stopped by user", file=sys.stderr)
    except BrokenPipeError:
        print("\n[usb-bridge] upstream closed", file=sys.stderr)

    print(f"[usb-bridge] total packets: {count}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
