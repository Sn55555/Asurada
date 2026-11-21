#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture raw F1 25 UDP packets into a JSONL file."
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Local host/interface to bind to. Use 0.0.0.0 for all interfaces.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=20777,
        help="UDP port configured in the game telemetry settings.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSONL path. Defaults to captures/f1_25_udp_capture_<timestamp>.jsonl",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        help="Stop after this many seconds.",
    )
    parser.add_argument(
        "--max-packets",
        type=int,
        help="Stop after capturing this many packets.",
    )
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=65535,
        help="Socket receive buffer size.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.5,
        help="Socket timeout in seconds.",
    )
    parser.add_argument(
        "--preview-bytes",
        type=int,
        default=16,
        help="How many leading bytes to include as preview_hex.",
    )
    return parser


def ensure_positive(name: str, value: int | float | None) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be greater than 0")


def default_output_path() -> Path:
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    return Path("captures") / f"f1_25_udp_capture_{timestamp}.jsonl"


def iso_timestamp_from_ms(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        ensure_positive("port", args.port)
        ensure_positive("seconds", args.seconds)
        ensure_positive("max-packets", args.max_packets)
        ensure_positive("buffer-size", args.buffer_size)
        ensure_positive("timeout", args.timeout)
        ensure_positive("preview-bytes", args.preview_bytes)
    except ValueError as exc:
        print(f"Argument error: {exc}", file=sys.stderr)
        return 2

    output_path = args.output or default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    start_monotonic = time.monotonic()
    deadline = start_monotonic + args.seconds if args.seconds is not None else None
    packet_count = 0

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(args.timeout)

    print(f"Listening on udp://{args.host}:{args.port}")
    print(f"Writing capture to {output_path.resolve()}")
    print("Press Ctrl+C to stop.")

    try:
        with output_path.open("w", encoding="utf-8") as handle:
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    break

                try:
                    payload, address = sock.recvfrom(args.buffer_size)
                except socket.timeout:
                    continue

                packet_count += 1
                received_at_ms = int(time.time() * 1000)
                record = {
                    "sequence_id": packet_count,
                    "received_at_ms": received_at_ms,
                    "received_at_utc": iso_timestamp_from_ms(received_at_ms),
                    "source_host": address[0],
                    "source_port": address[1],
                    "byte_length": len(payload),
                    "preview_hex": payload[: args.preview_bytes].hex(),
                    "payload_base64": base64.b64encode(payload).decode("ascii"),
                }
                handle.write(json.dumps(record, ensure_ascii=True))
                handle.write("\n")
                handle.flush()

                if packet_count == 1 or packet_count % 25 == 0:
                    print(
                        f"Captured {packet_count} packets. "
                        f"Last packet: {len(payload)} bytes from {address[0]}:{address[1]}"
                    )

                if args.max_packets is not None and packet_count >= args.max_packets:
                    break
    except KeyboardInterrupt:
        print("\nCapture stopped by user.")
    finally:
        sock.close()

    elapsed_s = time.monotonic() - start_monotonic
    print(
        f"Finished. packets={packet_count} elapsed={elapsed_s:.2f}s "
        f"output={output_path.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
