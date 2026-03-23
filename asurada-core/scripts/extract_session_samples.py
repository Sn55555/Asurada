from __future__ import annotations

import argparse
import base64
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from asurada.capture_ingest import CaptureJsonlSource
from asurada.pdu import RawPacket
from asurada.pdu_decoder import F125PacketDecoder, PacketDecodeError


SESSION_CLASSIFICATIONS = {
    "11681155589853237715": {
        "sample_name": "shanghai_qualifying_like_uid13",
        "session_type_code": 13,
        "session_label": "QualifyingLike(13)",
        "confidence": "medium",
        "reason": "Single-lap ranked competitive session with no points and final classification.",
    },
    "14150869158713609585": {
        "sample_name": "shanghai_short_result_like_uid8",
        "session_type_code": 8,
        "session_label": "ShortResultLike(8)",
        "confidence": "medium",
        "reason": "Short competitive result session with final classification and non-zero points, but official mode name remains unresolved.",
    },
    "18131203574741043245": {
        "sample_name": "shanghai_sprint_race_like_uid15",
        "session_type_code": 15,
        "session_label": "SprintRaceLike(15)",
        "confidence": "high",
        "reason": "Race-like session with 3 laps, start/end events, adjacent official gap data, and 7-point finish.",
    },
    "4014030831115520530": {
        "sample_name": "shanghai_feature_race_like_uid16",
        "session_type_code": 16,
        "session_label": "FeatureRaceLike(16)",
        "confidence": "high",
        "reason": "Race-like session with 5 laps, start/end events, adjacent official gap data, and 25-point win.",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract reusable per-session samples from one raw capture JSONL.")
    parser.add_argument(
        "--capture-jsonl",
        type=Path,
        default=Path("/Users/sn5/Asurada/tools/captures/f1_25_udp_capture_20260321_024707.jsonl"),
        help="Source raw packet capture JSONL.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/Users/sn5/Asurada/asurada-core/data/capture_samples/shanghai_race_weekend"),
        help="Directory where extracted per-session JSONL samples and metadata are written.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = _extract_samples(args.capture_jsonl, args.output_dir)
    metadata_path = args.output_dir / "metadata.json"
    metadata_path.write_text(json.dumps({"samples": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(metadata_path)
    print(json.dumps({"samples": records}, ensure_ascii=False, indent=2))
    return 0


def _extract_samples(capture_path: Path, output_dir: Path) -> list[dict]:
    """Split one raw capture into reusable per-session sample files.

    备注:
    阶段二更适合按 session_uid 管理样本，而不是反复从整份大抓包里筛选。
    这里保留原始 packet 行，只做 session 维度切片和 metadata 汇总。
    """
    decoder = F125PacketDecoder()
    target_uids = set(SESSION_CLASSIFICATIONS)
    handles: dict[str, object] = {}
    packet_counts = defaultdict(Counter)
    event_counts = defaultdict(Counter)
    session_meta: dict[str, dict] = {}
    final_meta: dict[str, dict] = {}
    first_ms: dict[str, int] = {}
    last_ms: dict[str, int] = {}

    try:
        with capture_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                try:
                    payload = base64.b64decode(record["payload_base64"])
                except Exception:
                    continue
                try:
                    envelope = decoder.decode_raw(
                        RawPacket(
                            payload=payload,
                            received_at_ms=int(record["received_at_ms"]),
                            source_host=str(record["source_host"]),
                            source_port=int(record["source_port"]),
                        )
                    )
                except PacketDecodeError:
                    continue

                uid = str(envelope.payload["header"]["session_uid"])
                if uid not in target_uids:
                    continue

                if uid not in handles:
                    sample_name = SESSION_CLASSIFICATIONS[uid]["sample_name"]
                    handles[uid] = (output_dir / f"{sample_name}.jsonl").open("w", encoding="utf-8")

                handles[uid].write(line)
                packet_counts[uid][envelope.kind] += 1
                ms = int(envelope.payload["header"]["received_at_ms"])
                first_ms[uid] = ms if uid not in first_ms else min(first_ms[uid], ms)
                last_ms[uid] = ms if uid not in last_ms else max(last_ms[uid], ms)

                if envelope.kind == "Session" and uid not in session_meta:
                    body = envelope.payload["body"]
                    session_meta[uid] = {
                        "track_id": body.get("track_id"),
                        "total_laps": body.get("total_laps"),
                        "game_mode": body.get("game_mode"),
                        "session_time_s_first": envelope.payload["header"].get("session_time_s"),
                    }
                if envelope.kind == "Event":
                    event_code = envelope.payload["body"].get("event_code")
                    event_counts[uid][event_code] += 1
                if envelope.kind == "FinalClassification" and uid not in final_meta:
                    body = envelope.payload["body"]
                    player = body.get("player") or {}
                    final_meta[uid] = {
                        "session_time_s": envelope.payload["header"].get("session_time_s"),
                        "player_position": player.get("position"),
                        "player_points": player.get("points"),
                        "player_num_laps": player.get("num_laps"),
                    }
    finally:
        for file_handle in handles.values():
            file_handle.close()

    results = []
    for uid, config in SESSION_CLASSIFICATIONS.items():
        sample_path = output_dir / f"{config['sample_name']}.jsonl"
        results.append(
            {
                "session_uid": uid,
                "sample_name": config["sample_name"],
                "file_path": str(sample_path),
                "session_type_code": config["session_type_code"],
                "session_label": config["session_label"],
                "confidence": config["confidence"],
                "reason": config["reason"],
                "wall_seconds": round((last_ms[uid] - first_ms[uid]) / 1000.0, 3) if uid in first_ms else 0.0,
                "session": session_meta.get(uid, {}),
                "final": final_meta.get(uid, {}),
                "packet_counts": dict(packet_counts[uid]),
                "event_counts": dict(event_counts[uid].most_common()),
            }
        )
    return results


if __name__ == "__main__":
    raise SystemExit(main())
