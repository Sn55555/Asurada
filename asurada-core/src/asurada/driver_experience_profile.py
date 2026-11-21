"""Inspect, derive, revoke and rebuild scoped radio and brake-habit evidence."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from .brake_habit import BrakePass, BrakeProbe, verified_reference
from .decode import decode_snapshot
from .driver_experience import PREFERENCE_KEY
from .training_memory import TrainingMemory


def _frames(paths, sessions):
    for path in paths:
        with path.open() as source:
            for line in source:
                if not line.strip():
                    continue
                row = json.loads(line)
                if sessions is None or str(row.get("session_uid")) in sessions:
                    yield row


def evaluate_sources(paths, sessions=None):
    """Use each race's latest branch only. Source files must be in capture order."""
    latest_epochs = {}
    for row in _frames(paths, sessions):
        uid, epoch = str(row["session_uid"]), row.get("session_epoch", 0)
        latest_epochs[uid] = max(epoch, latest_epochs.get(uid, -1))
    probes, passes = {}, []
    counts, observed_inputs, observed_flags = Counter(), Counter(), Counter()
    for row in _frames(paths, sessions):
        uid, epoch = str(row["session_uid"]), row.get("session_epoch", 0)
        if epoch != latest_epochs[uid]:
            continue
        counts[uid] += 1
        quality = ((row.get("raw") or {}).get("input_quality") or {}).get("brake", {})
        if quality.get("quality") == "observed":
            observed_inputs[uid] += 1
        if type((row.get("raw") or {}).get("marshal_zone_flag")) is int:
            observed_flags[uid] += 1
        else:
            if uid in probes:
                probes[uid].reset()
            continue
        if uid not in probes:
            probes[uid] = BrakeProbe()
        sample = probes[uid].observe(decode_snapshot(row))
        if sample is not None:
            passes.append(sample)
    coverage = Counter((item.track, item.corner, item.weather, item.tyre, str(item.session)) for item in passes)
    return {
        "inputs": [str(path) for path in paths],
        "frames_by_session": dict(counts),
        "observed_brake_by_session": dict(observed_inputs),
        "observed_marshal_flag_by_session": dict(observed_flags),
        "coverage": [{"track": k[0], "corner": k[1], "weather": k[2], "tyre": k[3], "session": k[4], "passes": count}
                     for k, count in sorted(coverage.items())],
        "reference": verified_reference(passes),
    }


def export_profile(memory, driver):
    return {
        "schema": "driver-experience-v1", "driver_id": driver,
        "preferences": memory.query(driver=driver, kind="user_preference"),
        "brake_habits": memory.brake_habits(driver=driver, include_revoked=True),
    }


def rebuild_profile(memory, driver, bundle):
    if bundle.get("schema") != "driver-experience-v1" or bundle.get("driver_id") != driver:
        raise ValueError("driver_experience_bundle_mismatch")
    # Recheck reference arithmetic from bundled evidence before restoring any record.
    for row in bundle["brake_habits"]:
        if row["revoked"] and not row["record"]:
            continue
        record = row["record"]
        passes = [BrakePass(**sample) for sample in record["training"] + record["holdout"]]
        if (verified_reference(passes) != record
                or (record["track"], record["corner"]) != (row["track"], row["corner"])):
            raise ValueError("brake_reference_does_not_match_evidence")
    for row in bundle["brake_habits"]:
        keys = {"driver": driver, "track": row["track"], "corner": row["corner"]}
        if row["record"]:
            memory.put_brake_habit(**keys, record=row["record"])
        if row["revoked"]:
            memory.revoke_brake_habit(**keys)
    for option in bundle["preferences"]:
        if option["driver"] != driver:
            raise ValueError("driver_experience_preference_mismatch")
        ttl_s = option["expires_at"] - memory.clock()
        if ttl_s <= 0:
            continue
        if option["key"] == PREFERENCE_KEY and option["value"] is True:
            memory.set_radio_straight(driver=driver, ttl_s=ttl_s)
        elif option["key"] == "review_detail":
            memory.set_review_detail(driver=driver, detail=option["value"], ttl_s=ttl_s)
    return export_profile(memory, driver)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--driver-id")
    commands = parser.add_subparsers(dest="command", required=True)
    learn = commands.add_parser("learn")
    learn.add_argument("--session", action="append")
    learn.add_argument("inputs", type=Path, nargs="+")
    commands.add_parser("show")
    commands.add_parser("export")
    revoke = commands.add_parser("revoke")
    revoke.add_argument("--track", required=True)
    revoke.add_argument("--corner", required=True)
    restore = commands.add_parser("rebuild")
    restore.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    if (args.command != "learn" or args.database) and not (args.database and args.driver_id and args.driver_id.strip()):
        parser.error("local profile commands require --database and --driver-id")
    memory = TrainingMemory(args.database) if args.database else None
    if args.command == "learn":
        result = evaluate_sources(args.inputs, args.session)
        record = result["reference"]
        result["stored"] = bool(memory and record and memory.put_brake_habit(
            driver=args.driver_id, track=record["track"], corner=record["corner"], record=record,
        ))
    elif args.command == "revoke":
        memory.revoke_brake_habit(driver=args.driver_id, track=args.track, corner=args.corner)
        result = export_profile(memory, args.driver_id)
    elif args.command == "rebuild":
        result = rebuild_profile(memory, args.driver_id, json.loads(args.bundle.read_text()))
    else:
        result = export_profile(memory, args.driver_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
