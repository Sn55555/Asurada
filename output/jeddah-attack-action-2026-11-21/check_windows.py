"""Check the original Jeddah windows and render matched radio-only clips."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
archive = Path(sys.argv[1])
runs = {
    "before": root.parent / "jeddah-attack-runway-2026-11-21" / "candidate",
    "after": root / "candidate",
}
def load(path):
    return json.loads(path.read_text())

metadata = [load(path / "race.json") for path in runs.values()]
assert metadata[0]["archive_sha256"] == metadata[1]["archive_sha256"]
assert metadata[0]["frames"] == metadata[1]["frames"] == 19116
rows = {version: [json.loads(line) for line in (path / "race.jsonl").open()] for version, path in runs.items()}
assert all(x["src"] == y["src"] for x, y in zip(rows["before"], rows["after"]))
jobs = {version: load(path / "starts.json") for version, path in runs.items()}
lex = {version: load(path / "pcm-paths.json") for version, path in runs.items()}
windows = (
    dict(driver="加斯利", target=10, lap=8, anchor=819.06665, start=818.2, end=824.0,
         scan_start=818.15, brake=828.369385),
    dict(driver="比尔曼", target=13, lap=9, anchor=920.361511, start=919.5, end=925.3,
         scan_start=919.45, brake=929.45697),
)
sr = 22050
playlist = bytearray()
results = []
for case in windows:
    start_frame = next(row for row in rows["before"]
                       if row["epoch"] == 0 and row["lap"] == case["lap"] and row["t"] >= case["start"])
    origin = start_frame["wall"] - (start_frame["t"] - case["start"])
    size = round((case["end"] - case["start"]) * sr)
    played = {}
    for version in ("before", "after"):
        audio = bytearray(2 * size)
        heard = []
        for job in jobs[version]:
            row = rows[version][job["i"]]
            start = round((job["wall"] - origin) * sr)
            if row["epoch"] != 0 or start >= size or start + job["duration"] * sr <= 0:
                continue
            pcm = Path(lex[version][job["text"]]).read_bytes()
            length = len(pcm) // 2
            if "cut" in job:
                stop = rows[version][job["cut"]]["wall"]
                length = min(length, round((stop - job["wall"]) * sr))
            a, b = max(0, start), min(size, start + length)
            if a < b:
                audio[2*a:2*b] = pcm[2*(a-start):2*(b-start)]
                heard.append(dict(text=job["text"], code=job["code"], start_s=row["t"],
                                  actual_s=(b-a)/sr))
        played[version] = dict(audio_start_s=len(playlist)/(2*sr), length_s=size/sr, heard=heard)
        playlist.extend(audio)
        playlist.extend(bytes(round(.7*sr)*2))
    playlist.extend(bytes(round(.5*sr)*2))
    assert [x["text"] for x in played["before"]["heard"]] == ["跟住前车。"]
    assert not any(x["code"].startswith("ATTACK") for x in played["after"]["heard"])

    sources = defaultdict(dict)
    for row in rows["before"]:
        if row["epoch"] == 0 and row["lap"] == case["lap"] and case["scan_start"] <= row["t"] < case["brake"]:
            name, line = row["src"]
            sources[name][line] = row
    facts = []
    for name, lines in sources.items():
        with (archive / name).open() as source:
            for number, line in enumerate(source, 1):
                row = lines.get(number)
                if row is None:
                    continue
                original = json.loads(line)
                raw, player = original["raw"], original["player"]
                target = next((entry for entry in original["rivals"]
                               if entry["car_index"] == case["target"] and entry["position"] == player["position"]-1), None)
                if target is None:
                    continue
                facts.append(dict(race_s=row["t"], source=row["src"], distance_m=row["dist"],
                    gap_s=row["gap"], player_kph=player["speed_kph"], front_kph=target["speed_kph"],
                    throttle=raw.get("throttle"), drs_allowed=raw.get("forecast_drs_allowed"),
                    normalized_drs_available=player.get("drs_available"), drs_open=raw.get("drs_open")))
    assert facts
    at_old = min(facts, key=lambda x: abs(x["race_s"] - case["anchor"]))
    assert not any(frame["drs_allowed"] is True for frame in facts)
    results.append({**case, "played": played, "at_old_opening": at_old,
                    "target_frames_before_brake": len(facts),
                    "front_faster_frames": sum(x["front_kph"] > x["player_kph"] for x in facts),
                    "latest_same_target": facts[-1]})

subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(sr), "-ac", "1",
    "-i", "pipe:0", "-c:a", "libmp3lame", "-b:a", "64k",
    str(root / "jeddah-action-before-after.mp3")], input=playlist, check=True)
counts = {version: Counter(job["code"] for job in trace) for version, trace in jobs.items()}
summary = dict(frames=19116, windows=results, start_counts=counts)
(root / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
