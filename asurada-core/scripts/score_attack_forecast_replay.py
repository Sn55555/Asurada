"""Score a frozen forward replay after inference. Never imported by the strategy."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path


def blend(before, after, field, threshold):
    offset = (threshold - before[field]) / (after[field] - before[field])
    return before["t"] + offset * (after["t"] - before["t"])


def assess(rows, indexes, starts, events):
    first = rows[indexes[0]]
    f = first["forecast"]
    key, target = f["id"], f["target"]
    proposed = [rows[i] for i in indexes if rows[i]["forecast"]["recommended"]]
    start = next((s for s in starts if s.get("forecast") and s["forecast"]["id"] == key), None)
    anchor = rows[start["i"]] if start else proposed[0] if proposed else first
    samples = []
    reached = gate_time = brake_time = alongside = None
    side_since = braking_since = None
    limit = (f["gate_lap"] - 1) * f["length_m"] + f["gate_m"]
    for r in rows[anchor["i"] : anchor["i"] + 800]:
        if r["epoch"] != anchor["epoch"] or (samples and not 0 <= r["t"] - samples[-1]["t"] <= 0.65):
            break
        absolute = (r["lap"] - 1) * f["length_m"] + r["dist"]
        prev = samples[-1] if samples else None
        if prev and not -4 <= absolute - prev["absolute"] <= 125 * (r["t"] - prev["t"]) + 4:
            break
        if prev and prev["absolute"] < limit <= absolute:
            gate_time = blend(prev, dict(r, absolute=absolute), "absolute", limit)
        other = next((v for v in r["rivals"] if v[0] == target), None)
        geo = other[4] if other else None
        side = geo and abs(geo[0]) <= 4 and 1.7 <= abs(geo[1]) <= 5
        side_since = (r["t"] if side_since is None else side_since) if side else None
        if side_since is not None and r["t"] - side_since >= 0.25 and alongside is None:
            alongside = side_since
        braking = limit - 180 <= absolute <= limit + 80 and r["brake"] is not None and r["brake"] > 0.18
        braking_since = (r["t"] if braking_since is None else braking_since) if braking else None
        if braking_since is not None and r["t"] - braking_since >= 0.20 and brake_time is None:
            brake_time = braking_since
        samples.append(dict(r, absolute=absolute, other=other))
        if absolute >= limit + 80:
            reached = True
            break
    matches = [
        e
        for e in events
        if anchor["i"] <= e["i"] <= samples[-1]["i"]
        and e["pair"] == [anchor["player"], target]
        and e["ms"] >= anchor["wall"] * 1000 - 1
        and e["verified"]
    ]
    finish = hypothetical = None
    if start:
        end_wall = start["wall"] + start["duration"]
        # Wall-time pauses and cuts cannot be counted as driving preparation.
        for i in range(anchor["i"] + 1, min(anchor["i"] + 200, len(rows))):
            r, p = rows[i], rows[i - 1]
            if (
                r["epoch"] != anchor["epoch"]
                or not 0 <= r["t"] - p["t"] <= 0.65
                or not 0 <= r["wall"] - p["wall"] <= 0.8
            ):
                break
            if p["wall"] < end_wall <= r["wall"]:
                hypothetical = blend(p, r, "wall", end_wall)
                if "cut" not in start:
                    finish = hypothetical
                break
    final = [r for r in samples if gate_time is not None and gate_time - 1 <= r["t"] <= gate_time]
    negative = (
        reached
        and len(final) >= 3
        and all(
            r["other"]
            and r["other"][2] == r["pos"] - 1
            and r["other"][3] == "NONE"
            and r["gap"] is not None
            and r["gap"] >= 0.6
            for r in final
        )
    )
    if matches:
        verdict = "同目标超车"
    elif alongside is not None:
        verdict = "观察到并排"
    elif negative:
        verdict = "到点未接近"
    else:
        verdict = "不确定"
    available = [x for x in [gate_time, brake_time, alongside, *[e["t"] for e in matches]] if x is not None]
    decision_at = min(available) if available else None
    cut = None
    if start and "cut" in start:
        r = rows[start["cut"]]
        cut = dict(
            t=r["t"],
            wall=r["wall"],
            code=r["code"],
            block=r["block"],
            source=r["src"],
            gap=r["gap"],
            target_present=any(v[0] == target and v[2] == r["pos"] - 1 for v in r["rivals"]),
            still_recommended=bool(
                r["forecast"] and r["forecast"]["recommended"] and r["forecast"]["id"] == key
            ),
        )
    return dict(
        id=key,
        lap=anchor["lap"],
        epoch=anchor["epoch"],
        first_eval=first["t"],
        t=anchor["t"],
        last_eval=rows[indexes[-1]]["t"],
        source=anchor["src"],
        evidence=anchor["forecast"],
        first_proposed=proposed[0]["t"] if proposed else None,
        first_input=proposed[0]["forecast"] if proposed else None,
        before_play_blocks=dict(Counter(r["block"] or r["code"] for r in proposed if start and r["i"] < start["i"])),
        proposed_frames=len(proposed),
        vetoes=dict(Counter(r["block"] or (r["code"] if r["code"] != "NONE" else "clear") for r in proposed)),
        closest_projected=min(rows[i]["forecast"]["predicted_gap_s"] for i in indexes),
        start=start,
        cut=cut,
        finished_s=finish,
        hypothetical_end=hypothetical,
        gate_s=gate_time,
        brake_s=brake_time,
        alongside_s=alongside,
        pass_events=matches,
        prep_s=decision_at - finish if finish is not None and decision_at is not None else None,
        gate_margin_s=gate_time - finish if finish is not None and gate_time is not None else None,
        verdict=verdict,
        last_observed=samples[-1]["t"],
        coverage_end=bool(reached),
    )


def score(prefix):
    rows = list(map(json.loads, prefix.with_suffix(".jsonl").open()))
    meta = json.loads(prefix.with_suffix(".json").read_text())
    assert len(rows) == meta["frames"]
    groups = defaultdict(list)
    events = []
    seen = set()
    for r in rows:
        if r["forecast"]:
            groups[r["forecast"]["id"]].append(r["i"])
        event, ms = r["event"], r["event_ms"]
        if not event or ms is None or not 0 <= 1000 * r["wall"] - ms <= 1500:
            continue
        pair = [event["overtaking_vehicle_idx"], event["being_overtaken_vehicle_idx"]]
        key = (r["epoch"], ms, *pair)
        if pair[0] != r["player"] or key in seen:
            continue
        seen.add(key)
        after = []
        for later in rows[r["i"] : r["i"] + 25]:
            if later["epoch"] != r["epoch"] or not 0 <= later["t"] - r["t"] <= 1.1:
                break
            rival = next((v for v in later["rivals"] if v[0] == pair[1]), None)
            if not rival or rival[2] <= later["pos"] or rival[3] != "NONE":
                break
            after.append(later)
        events.append(
            dict(
                i=r["i"],
                t=r["t"],
                epoch=r["epoch"],
                lap=r["lap"],
                ms=ms,
                pair=pair,
                dist=r["dist"],
                source=r["src"],
                verified=bool(after and after[-1]["t"] - r["t"] >= 0.4),
            )
        )
    windows = [assess(rows, idx, meta["starts"], events) for idx in groups.values()]
    return dict(
        frames=len(rows),
        sources=meta["archive_sha256"],
        windows=windows,
        events=events,
        terminal=[
            dict(
                t=r["t"],
                lap=r["lap"],
                pos=r["pos"],
                source=r["src"],
                forecast=r["forecast"],
                front=next((v[:3] for v in r["rivals"] if v[2] == r["pos"] - 1), None),
            )
            for r in rows
            if r["code"] == "ATTACK_WINDOW"
        ],
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suzuka", type=Path)
    p.add_argument("jeddah", type=Path)
    p.add_argument("result", type=Path)
    args = p.parse_args()
    result = {name: score(prefix) for name, prefix in (("铃鹿", args.suzuka), ("吉达", args.jeddah))}
    args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
