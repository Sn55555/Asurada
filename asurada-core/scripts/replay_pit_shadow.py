"""Replay whole capture streams in receive order, using the live state pipeline."""
import argparse
import gzip
import json
import struct
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from asurada.capture_ingest import CaptureJsonlSource
from asurada.config import StrategyThresholds
from asurada.decode import decode_snapshot
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu import RawPacket
from asurada.pdu_decoder import F125PacketDecoder, PacketDecodeError
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine
from asurada.pit_shadow import PitShadow

ROOT = Path(__file__).resolve().parents[2]


def packets(path):
    if path.suffix == ".jsonl":
        yield from CaptureJsonlSource(path)
    elif path.suffix == ".gz":
        sys.path.insert(0, str(ROOT / "output/community-full-coverage-20260915"))
        from audit_recordings import packets as compressed
        for seconds, payload in compressed(path):
            yield RawPacket(round(seconds * 1000), payload, "capture", 0)
    elif path.suffix in (".bin", ".f1bin"):
        nano = path.suffix == ".f1bin"
        record = struct.Struct("<QH" if nano else "<IQ")
        with path.open("rb") as stream:
            while header := stream.read(record.size):
                a, b = record.unpack(header)
                size, ms = (b, a // 1_000_000) if nano else (a, b)
                payload = stream.read(size)
                if len(payload) != size:
                    raise ValueError("truncated capture")
                yield RawPacket(ms, payload, "capture", 0)
    else:
        raise ValueError(path)


def checkpoints(job):
    path, uids, destination = job
    decoder, assembler, store, shadow = F125PacketDecoder(), CaptureSnapshotAssembler(), UnifiedStateStore(), PitShadow()
    counts = dict(packets=0, frames=0, checkpoints=0, decode_errors=0)
    with gzip.open(destination, "wt") as output:
        for ordinal, packet in enumerate(packets(ROOT / path), 1):
            if int.from_bytes(packet.payload[7:15], "little") not in uids:
                continue
            counts["packets"] += 1
            try:
                envelope = decoder.decode_raw(packet)
            except PacketDecodeError:
                counts["decode_errors"] += 1
                continue
            snapshot = assembler.push(envelope)
            if snapshot is None:
                continue
            state = decode_snapshot(snapshot)
            if not store.update(state):
                continue
            counts["frames"] += 1
            if shadow.checkpoint(state):
                # The state store can detect a rewind between two assembled frames.
                snapshot["session_epoch"] = state.session_epoch
                output.write(json.dumps([ordinal, snapshot], separators=(",", ":")) + "\n")
                counts["checkpoints"] += 1
    return path, counts


def exit_positions(rows, stops):
    """Post-replay labels: first on-track LapData after a timed lane visit."""
    wanted = {(s["uid"], s["lap"]) for s in stops if s["pit"] is not None}
    positions = {}
    sources = {row["source"] for row in rows if (row["uid"], row["lap"]) in wanted}
    for path in sources:
        active = {}
        for packet in packets(ROOT / path):
            b = packet.payload
            if len(b) != F125PacketDecoder.PACKET_SIZES[2] or b[6] != 2 or b[27] >= 22:
                continue
            uid = str(int.from_bytes(b[7:15], "little"))
            i = 29 + b[27] * 57
            lap, in_lane = b[i+33], b[i+34]
            if in_lane and (uid, lap) in wanted:
                active.setdefault(uid, lap)
            elif not in_lane and uid in active:
                entry_lap = active.pop(uid)
                if lap in (entry_lap, entry_lap + 1) and 1 <= b[i+32] <= 22:
                    positions[uid, entry_lap] = b[i+32]
    return positions


def score(output, validation):
    # Only the scoring pass can read actual stops. The estimator has already finished.
    rows = [json.loads(line) for line in (output / "checkpoints.jsonl").read_text().splitlines()]
    first = {}
    for row in rows:
        first.setdefault((row["uid"], row["lap"]), row)
    samples = list(first.values())
    comparisons = Counter((r["game"]["action"] or "unavailable", r["nominal"] or "undetermined") for r in samples)
    stops = []
    exits = exit_positions(samples, validation["stops"])
    for stop in validation["stops"]:
        row = first.get((stop["uid"], stop["lap"]))
        if not row or stop["pit"] is None:
            continue
        winner = None
        for scenario in row.get("pit_price_sensitivity", ()):
            if stop["pit"] > scenario["above_pit_s"]:
                winner = scenario["action"]
        prior = row["prior"]["pit_s"]
        stops.append(dict(track=row["track"], lap=row["lap"], observed_net_s=round(stop["pit"], 3),
                          predicted_net_s=prior, predicted_minus_observed_s=round(prior-stop["pit"], 3) if prior is not None else None,
                          nominal=row["nominal"], repriced_action=winner, game=row["game"],
                          rejoin_estimate=row.get("rejoin_if_now"), observed_exit_position=exits.get((stop["uid"], stop["lap"]))))
    counts = Counter(r["nominal"] or "undetermined" for r in samples)
    stats = dict(races=len({r["uid"] for r in samples}), events=len(rows), unique_race_laps=len(first),
                 nominal=counts, verdict=Counter(r["verdict"] for r in samples),
                 game_comparisons={game:dict((action, n) for (g, action), n in comparisons.items() if g == game)
                                   for game in sorted({g for g, _ in comparisons})},
                 actual_stops=stops)
    (output / "comparison.json").write_text(json.dumps(stats, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--reuse", action="store_true", help="use previously extracted checkpoints")
    args = parser.parse_args()
    args.cache.mkdir(exist_ok=True, parents=True)
    args.output.mkdir(exist_ok=True, parents=True)
    phase2 = ROOT / "output/race-costs-20261121"
    wanted = set(json.loads((phase2 / "validation.json").read_text())["complete_uids"])
    jobs = []
    for source in json.loads((phase2 / "inventory.json").read_text()):
        uids = wanted.intersection(r["uid"] for r in source["races"])
        if uids:
            jobs.append((source["source"], {int(uid) for uid in uids}, args.cache / f"{len(jobs)}.gz"))
            wanted -= uids
    assert not wanted
    if not args.reuse:
        with ProcessPoolExecutor(max_workers=4) as pool:
            counts = dict(pool.map(checkpoints, jobs))
        (args.output / "coverage.json").write_text(json.dumps(counts, indent=2))
    with (args.output / "checkpoints.jsonl").open("w") as out:
        for path, _, cache in jobs:
            engine = StrategyEngine(StrategyThresholds())
            with gzip.open(cache, "rt") as stream:
                for line in stream:
                    ordinal, snapshot = json.loads(line)
                    state = decode_snapshot(snapshot)
                    decision = engine.evaluate(state)
                    row = decision.debug["pit_timing_shadow"]
                    if not row or not decision.debug["pit_broadcast_muted"]:
                        raise ValueError(f"checkpoint disagrees with live strategy at {path}:{ordinal}")
                    # Negative control: mutate only the comparison fields after the live decision.
                    masked = decode_snapshot(snapshot)
                    masked.raw["shadow_session"] = dict(masked.raw["shadow_session"], ideal=None, latest=None)
                    blind = PitShadow.assess(masked)
                    if any(blind[k] != v for k, v in row.items() if k != "game"):
                        raise ValueError(f"game window influenced strategy at {path}:{ordinal}")
                    row.update(source=path, ordinal=ordinal, uid=state.session_uid, epoch=state.session_epoch,
                               lap=state.lap_number, track=state.track, total=state.total_laps,
                               frame=state.raw["overall_frame_identifier"], position=state.player.position,
                               session_time_s=state.raw["session_time_s"], lap_distance_m=state.player.lap_distance_m)
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")

    score(args.output, json.loads((phase2 / "validation.json").read_text()))


if __name__ == "__main__":
    main()
