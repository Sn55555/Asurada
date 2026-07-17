#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from f1_25_track_catalog import F1_25_TRACK_CATALOG


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from asurada.capture_ingest import CaptureJsonlSource  # noqa: E402
from asurada.decode import decode_snapshot  # noqa: E402
from asurada.packet_snapshot import CaptureSnapshotAssembler  # noqa: E402
from asurada.pdu import RawPacket  # noqa: E402
from asurada.pdu_decoder import F125PacketDecoder  # noqa: E402
from asurada.track_model import load_track_profile  # noqa: E402


FULL_CAPTURE = ROOT.parent / "tools" / "captures" / "f1_25_udp_capture_20260321_024707.jsonl"
COMPACT_FIXTURE = ROOT / "data" / "capture_samples" / "f1_25_udp_frame_fixture.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay one F1 25 UDP frame across all track IDs.")
    parser.add_argument("--template-capture", type=Path)
    parser.add_argument("--write-fixture", type=Path)
    return parser.parse_args()


def resolve_template_capture(explicit_path: Path | None) -> Path:
    if explicit_path is not None:
        return explicit_path
    return FULL_CAPTURE if FULL_CAPTURE.exists() else COMPACT_FIXTURE


def load_real_udp_frame(capture_path: Path) -> tuple[RawPacket, dict[str, RawPacket]]:
    decoder = F125PacketDecoder()
    assembler = CaptureSnapshotAssembler()
    sessions: dict[str, RawPacket] = {}
    frames: dict[tuple[str, int | None], dict[str, RawPacket]] = defaultdict(dict)
    for packet in CaptureJsonlSource(capture_path):
        envelope = decoder.decode_raw(packet)
        session_uid = str(envelope.session_uid)
        if envelope.kind == "Session":
            sessions[session_uid] = packet
        if envelope.kind in assembler.REQUIRED_FRAME_PACKETS:
            frames[(session_uid, envelope.frame_identifier)][envelope.kind] = packet
        if assembler.push(envelope) is None:
            continue
        frame_packets = frames[(session_uid, envelope.frame_identifier)]
        if session_uid in sessions and assembler.REQUIRED_FRAME_PACKETS.issubset(frame_packets):
            return sessions[session_uid], frame_packets
    raise RuntimeError(f"no complete real UDP frame found in {capture_path}")


def write_compact_fixture(path: Path, session_packet: RawPacket, frame_packets: dict[str, RawPacket]) -> None:
    packets = [session_packet, *(frame_packets[kind] for kind in sorted(frame_packets))]
    records = [
        {
            "sequence_id": index,
            "received_at_ms": packet.received_at_ms,
            "source_host": packet.source_host,
            "source_port": packet.source_port,
            "byte_length": len(packet.payload),
            "payload_base64": base64.b64encode(packet.payload).decode("ascii"),
        }
        for index, packet in enumerate(packets, start=1)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def patch_session_packet(
    packet: RawPacket, *, decoder: F125PacketDecoder, track_id: int, lap_length_m: float
) -> RawPacket:
    payload = bytearray(packet.payload)
    struct.pack_into("<H", payload, decoder.HEADER_SIZE + 4, int(round(lap_length_m)))
    struct.pack_into("<b", payload, decoder.HEADER_SIZE + 7, int(track_id))
    return RawPacket(
        received_at_ms=packet.received_at_ms,
        payload=bytes(payload),
        source_host=packet.source_host,
        source_port=packet.source_port,
    )


def main() -> int:
    args = parse_args()
    template_capture = resolve_template_capture(args.template_capture)
    decoder = F125PacketDecoder()
    session_packet, frame_packets = load_real_udp_frame(template_capture)
    if args.write_fixture is not None:
        write_compact_fixture(args.write_fixture, session_packet, frame_packets)
    tracks: list[dict[str, Any]] = []

    for entry in F1_25_TRACK_CATALOG:
        profile = load_track_profile(entry.track_name)
        if profile is None:
            tracks.append({"track": entry.track_name, "passed": False, "reason": "profile_missing"})
            continue
        assembler = CaptureSnapshotAssembler()
        patched_session = patch_session_packet(
            session_packet,
            decoder=decoder,
            track_id=entry.track_id,
            lap_length_m=profile.lap_length_m,
        )
        session_envelope = decoder.decode_raw(patched_session)
        decoded_track_id = int(session_envelope.payload["body"].get("track_id", -1))
        assembler.push(session_envelope)

        snapshot = None
        target_segment = profile.semantic_segments[0]
        target_distance_m = (target_segment.start_m + target_segment.end_m) / 2.0
        for packet_kind in sorted(frame_packets):
            envelope = decoder.decode_raw(frame_packets[packet_kind])
            if packet_kind == "LapData":
                envelope.payload["body"]["lap_distance_m"] = target_distance_m
                envelope.payload["body"]["current_lap_num"] = 1
                envelope.payload["body"]["sector"] = 0
                envelope.payload["body"]["car_position"] = 1
            candidate = assembler.push(envelope)
            if candidate is not None:
                snapshot = candidate

        state = decode_snapshot(snapshot) if snapshot is not None else None
        classified = profile.classify(target_distance_m)
        passed = (
            decoded_track_id == entry.track_id
            and state is not None
            and state.track == entry.track_name
            and classified.zone_name == target_segment.name
        )
        tracks.append(
            {
                "track_id": entry.track_id,
                "track": entry.track_name,
                "evidence": "real_f1_25_udp_frame_with_synthetic_track_metadata",
                "decoded_track_id": decoded_track_id,
                "snapshot_track": state.track if state is not None else None,
                "classified_segment": classified.zone_name,
                "passed": passed,
            }
        )

    report = {
        "passed": all(bool(item["passed"]) for item in tracks),
        "template_capture": str(template_capture),
        "summary": {
            "track_layouts": len(tracks),
            "passed_tracks": sum(bool(item["passed"]) for item in tracks),
        },
        "tracks": tracks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
