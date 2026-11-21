"""Freeze at the first lights-out packet, with no access to post-start telemetry."""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from asurada.frame_counter import newer
from asurada.grid_feed import GridPlanFeed
from asurada.grid_strategy import grid_inputs, optimise, transition_capacity
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu_decoder import F125PacketDecoder
from replay_pit_shadow import ROOT, packets


def compare(row):
    n = row["inputs"]["laps"] or 0
    ideal, latest = row["game"]["ideal"], row["game"]["latest"]
    if not all(type(v) is int for v in (ideal, latest)) or not 1 <= ideal <= latest <= n:
        return None
    result = {}
    for count, route in row["plan"].get("fitted_start", {}).get("routes", {}).items():
        result[count] = [v for v in route["first_stops"] if ideal <= v <= latest]
    return result


def replay(job):
    path, labels = job
    decoder, assembler, feed = F125PacketDecoder(), CaptureSnapshotAssembler(), GridPlanFeed()
    waiting = {int(x) for x in labels}
    results = []
    game_history = {}
    for ordinal, packet in enumerate(packets(ROOT / path), 1):
        if int.from_bytes(packet.payload[7:15], "little") not in waiting:
            continue
        envelope = decoder.decode_raw(packet)
        assembler.push(envelope)
        feed.observe(envelope, assembler)
        if envelope.kind == "Session" and assembler.accepted_epoch is not None:
            uid = str(envelope.session_uid)
            session = assembler.latest_session_by_uid.get(uid, {})
            header = assembler.latest_session_header_by_uid.get(uid, {})
            if session and header == envelope.payload["header"] and session.get("session_type") in (15, 16, 17):
                values = [session.get("pit_stop_window_ideal_lap"), session.get("pit_stop_window_latest_lap")]
                log = game_history.setdefault(uid, [])
                if not log or log[-1]["window"] != values:
                    log.append(dict(ordinal=ordinal, frame=header["overall_frame_identifier"], window=values))
        if envelope.kind != "Event" or envelope.payload["body"].get("event_code") != "LGOT":
            continue
        uid = str(envelope.session_uid)
        row = feed.entries.get(uid)
        if not row or row["event"] != "LGOT":
            results.append(dict(uid=uid, source=path, missing="lights_out_not_accepted"))
        else:
            for key in ("session_frame", "inventory_frame"):
                assert row[key] is None or newer(row["frame"], row[key])
            grid = row["inputs"]
            session = assembler.latest_session_by_uid.get(uid, {}) if row["session_frame"] is not None else {}
            inventory = assembler.latest_tyre_sets_by_uid.get(uid, {}) if row["inventory_frame"] is not None else {}
            masked = dict(session, pit_stop_window_ideal_lap=255, pit_stop_window_latest_lap=255)
            blind = grid_inputs(masked, inventory, grid["player"])
            assert blind == grid and optimise(blind) == row["plan"]
            row.update(source=path, cutoff_ordinal=ordinal, game_window_overlap=compare(row),
                       observed_game_windows=[v for v in game_history.get(uid, ()) if newer(row["frame"], v["frame"])])
            if row["plan"]["status"] == "conditional":
                row["slope_sensitivity"] = {
                    str(slope): {mode: result["one_two_break_even_s"] for mode, result in
                                 optimise(grid, slope).items() if mode in ("free_start", "fitted_start")}
                    for slope in (50, 100, 200)}
                row["reserve_one_spare"] = {}
                for t in grid["sets"]:
                    if not t["available"] or t["fitted"] or t["actual_tyre_compound"] in (7, 8):
                        continue
                    restricted = dict(grid, sets=[dict(x, available=False) if x == t else x for x in grid["sets"]])
                    row["reserve_one_spare"][str(t["set_index"])] = {
                        mode: r["one_two_break_even_s"] for mode,r in optimise(restricted).items()
                        if mode in ("free_start", "fitted_start")}
                row["weather_switch_feasibility"] = {
                    mode: {lap: transition_capacity(grid, lap, fixed_start=fixed) for lap in range(2, grid["laps"] + 1)}
                    for mode, fixed in (("free_start", False), ("fitted_start", True))}
            results.append(row)
        waiting.remove(int(uid))
        if not waiting:
            break
    return results + [dict(uid=str(uid), source=path, missing="no_lights_out") for uid in sorted(waiting)]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    phase2 = ROOT / "output/race-costs-20261121"
    complete = set(json.loads((phase2 / "validation.json").read_text())["complete_uids"])
    inventory = json.loads((phase2 / "inventory.json").read_text())
    wanted = {r["uid"] for source in inventory for r in source["races"]}
    jobs = []
    for source in inventory:
        uids = wanted.intersection(r["uid"] for r in source["races"])
        if uids:
            jobs.append((source["source"], sorted(uids)))
            wanted -= uids
    assert not wanted
    with ProcessPoolExecutor(max_workers=4) as pool:
        rows = [row for group in pool.map(replay,jobs) for row in group]
    for row in rows:
        row["complete_recording"] = row["uid"] in complete
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "grid.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
