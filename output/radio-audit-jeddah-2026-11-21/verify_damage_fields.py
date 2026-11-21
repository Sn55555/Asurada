"""Join the race's audio start frames to the archived telemetry fields."""
from collections import Counter
from itertools import groupby
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
archive = Path(sys.argv[1])
frames = [json.loads(line) for line in (root / "race.jsonl").open()]
starts = json.loads((root / "starts.json").read_text())
by_frame = {e["i"]: e for e in starts if e["code"] in {"TYRE_DAMAGE", "FRONT_WING_DAMAGE"}}
counts = Counter()
details = []
for name, group in groupby(frames, key=lambda r: r["src"][0]):
    targets = {row["src"][1]: row for row in group}
    with (archive / name).open("rb") as source:
        for i, raw in enumerate(source, 1):
            row = targets.pop(i, None)
            if row is None:
                continue
            snapshot = json.loads(raw)
            telemetry = snapshot["raw"]
            wear = telemetry.get("tyres_wear_pct")
            damage = telemetry.get("tyres_damage_pct")
            wing = telemetry.get("wing_damage_pct")
            if isinstance(wear, list) and isinstance(damage, list) and len(wear) == len(damage) == 4:
                counts["four_wheel_samples"] += 1
                counts["exact_wear_damage_matches"] += wear == damage
                counts["integer_wear_damage_matches"] += [int(x) for x in wear] == damage
                counts["has_wear_or_damage"] += any(wear) or any(damage)
            event = by_frame.get(row["i"])
            if event:
                details.append(dict(source=row["src"], lap=row["lap"], t=row["t"],
                                    line=event["text"], code=event["code"], tyres_wear_pct=wear,
                                    tyres_damage_pct=damage, wing_damage_pct=wing,
                                    average_wear=snapshot["player"]["tyre"]["wear_pct"]))
            if not targets:
                break
summary = dict(frames=len(frames), counts=counts, speech_frames=details)
(root / "damage-fields.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
print(summary["counts"])
