"""Replay a capture in source order; emit compact decisions and wire audit counts."""
import argparse
import csv
import json
import struct
from collections import Counter
from pathlib import Path

from asurada.capture_ingest import CaptureJsonlSource
from asurada.config import AppConfig
from asurada.context_window import CONTEXT_WINDOW_SECONDS
from asurada.decode import decode_snapshot
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu_decoder import F125PacketDecoder, PacketDecodeError
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine


def replay(source, destination):
    config = AppConfig()
    engine = StrategyEngine(config.thresholds, config.usage_hooks_path)
    decoder, assembler, store = F125PacketDecoder(), CaptureSnapshotAssembler(), UnifiedStateStore()
    counts = Counter()
    with destination.open("w") as output:
        rows = csv.writer(output)
        rows.writerow("ordinal uid epoch frame track lap session result enabled pit_lap compound tyre_set rule stops box primary".split())
        for ordinal, packet in enumerate(CaptureJsonlSource(source), 1):
            counts["packets"] += 1
            try:
                envelope = decoder.decode_raw(packet)
            except PacketDecodeError:
                counts["decode_errors"] += 1
                continue
            b = packet.payload
            if envelope.kind == "TyreSets" and b[29] == b[27]:
                counts["player_packets"] += 1
                body = envelope.payload["body"]
                counts["owner_or_index_errors"] += int((body.get("car_index"), body["fitted_idx"]) != (b[29], b[230]))
                for i, row in enumerate(body["sets"]):
                    fields = ("actual_tyre_compound", "visual_tyre_compound", "wear_pct", "available",
                              "recommended_session", "life_span_laps", "usable_life_laps", "lap_delta_time_ms", "fitted")
                    counts["set_errors"] += int(tuple(row[k] for k in fields) != struct.unpack_from("<7BhB", b, 30+10*i))
            snapshot = assembler.push(envelope)
            if snapshot is None:
                continue
            state = decode_snapshot(snapshot)
            if not store.update(state):
                continue
            counts["frames"] += 1
            inventory = state.raw.get("tyre_sets") or {}
            if inventory:
                counts["inventory_frames"] += 1
                counts["foreign_or_unknown_inventory_frames"] += int(inventory.get("car_index") != state.player.car_index)
            decision = engine.evaluate(state, store.recent_seconds(CONTEXT_WINDOW_SECONDS))
            plan = decision.debug["long_horizon_strategy"]
            codes = [message.code for message in decision.messages]
            advised = plan.get("recommended_set_index")
            if advised is not None:
                counts["set_recommendations"] += 1
                sets = inventory.get("sets", [])
                if not 0 <= advised < len(sets) or not sets[advised]["available"] or sets[advised]["fitted"]:
                    counts["unusable_set_recommendations"] += 1
            rows.writerow([ordinal, state.session_uid, state.session_epoch, envelope.frame_identifier,
                           state.track, state.lap_number, state.raw["session_type"], state.raw.get("result_status"), int(bool(plan.get("enabled"))), plan.get("recommended_pit_lap"),
                           plan.get("recommended_compound"), plan.get("recommended_set_index"), plan.get("compound_rule_state"),
                           plan.get("remaining_required_stops"), int("BOX_WINDOW" in codes), next(iter(codes), "")])
    print(json.dumps(counts))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    replay(args.source, args.destination)
