"""Render matched race-time windows in before/after pairs without moving speech."""
from collections import Counter
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
source = root.parent / "radio-audit-jeddah-2026-11-21"
folders = {"before": source, "after": root / "candidate"}
read_json = lambda path: json.loads(path.read_text(encoding="utf-8"))
archives = {name: read_json(folder / "race.json") for name, folder in folders.items()}
assert archives["before"]["frames"] == archives["after"]["frames"] == 19116
assert archives["before"]["archive_sha256"] == archives["after"]["archive_sha256"]
frames = {
    name: [json.loads(line) for line in (folder / "race.jsonl").open()]
    for name, folder in folders.items()
}
starts = {name: read_json(folder / "starts.json") for name, folder in folders.items()}
lexicons = {name: read_json(folder / "pcm-paths.json") for name, folder in folders.items()}
stats = {}
for name, sequence in starts.items():
    by_frame = {job["i"]: job for job in sequence}
    kinds = Counter(job["code"] for job in sequence)
    wings = {job["i"]: by_frame.get(job.get("cut")) for job in sequence
             if job["code"] == "FRONT_WING_DAMAGE" and "cut" in job}
    stats[name] = dict(
        starts=len(sequence), cuts=sum("cut" in job for job in sequence), codes=kinds,
        wing_by_wing=sum(bool(other and other["code"] == "FRONT_WING_DAMAGE")
                         for other in wings.values()),
        wing_by_instability=sum(bool(other and other["code"] == "DYNAMICS_UNSTABLE")
                                for other in wings.values()),
    )
assert stats["before"]["wing_by_wing"] >= 1
assert stats["after"]["wing_by_wing"] == 0
assert stats["after"]["wing_by_instability"] == stats["before"]["wing_by_instability"] >= 1
assert stats["before"]["codes"]["TYRE_DAMAGE"] == stats["after"]["codes"]["TYRE_WEAR_ALERT"] > 0
assert stats["after"]["codes"]["TYRE_DAMAGE"] == 0
for needle in ("百分之三十五", "百分之四十八"):
    assert any(needle in job["text"] for job in starts["after"] if job["code"] == "TYRE_WEAR_ALERT")

sr = 22050
windows = (
    ("lap4_wing", 0, 317.3, 341.0),
    ("lap12_wear", 0, 1218.4, 1223.0),
    ("lap15_wear", 1, 1532.4, 1537.0),
    ("lap16_instability", 1, 1556.3, 1560.4),
)
comparison = []
playlist = bytearray()
for scene, epoch, scene_start, scene_end in windows:
    for name in ("before", "after"):
        rows = frames[name]
        anchor = next(row for row in rows if row["epoch"] == epoch and row["t"] >= scene_start)
        epoch_origin = anchor["wall"] - (anchor["t"] - scene_start)
        length = round((scene_end - scene_start) * sr)
        pcm = bytearray(length * 2)
        heard = []
        for job in starts[name]:
            row = rows[job["i"]]
            offset = round((row["wall"] - epoch_origin) * sr)
            if row["epoch"] != epoch or offset >= length:
                continue
            path = Path(lexicons[name][job["text"]])
            wave = path.read_bytes()
            duration = len(wave) // 2
            if "cut" in job:
                stop_at = rows[job["cut"]]["wall"]
                duration = min(duration, round((stop_at - row["wall"]) * sr))
            first, last = max(0, offset), min(length, offset + duration)
            if last <= first:
                continue
            pcm[2 * first:2 * last] = wave[2 * (first - offset):2 * (last - offset)]
            heard.append(dict(lap=row["lap"], race_s=row["t"], text=job["text"], code=job["code"],
                              cut="cut" in job, actual_s=round((last - first) / sr, 3)))
        comparison.append(dict(scene=scene, version=name, audio_s=round(len(playlist) / (2 * sr), 3),
                               duration_s=length / sr, heard=heard))
        playlist.extend(pcm)
        playlist.extend(bytes(round(sr * .6) * 2))
    playlist.extend(bytes(round(sr * .5) * 2))
path = root / "jeddah-before-after.mp3"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i",
                "pipe:0", "-c:a", "libmp3lame", "-b:a", "64k", str(path)], input=playlist, check=True)
(root / "comparison.json").write_text(json.dumps(dict(stats=stats, comparison=comparison),
                                                  ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(stats, ensure_ascii=False, indent=2))
