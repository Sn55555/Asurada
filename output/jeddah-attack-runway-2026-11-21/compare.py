"""Score the three short calls and render their exact before/after audio."""
import json
from collections import Counter
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
paths = {"before": root.parent / "radio-fixes-jeddah-2026-11-21" / "candidate",
         "after": root / "candidate"}
read = lambda path: json.loads(path.read_text())
archives = {name: read(path / "race.json") for name, path in paths.items()}
assert archives["before"]["frames"] == archives["after"]["frames"] == 19116
assert archives["before"]["archive_sha256"] == archives["after"]["archive_sha256"]
frames = {name: [json.loads(line) for line in (path / "race.jsonl").open()]
          for name, path in paths.items()}
starts = {name: read(path / "starts.json") for name, path in paths.items()}
lexicons = {name: read(path / "pcm-paths.json") for name, path in paths.items()}
assert all(f["src"] == g["src"] for f, g in zip(frames["before"], frames["after"]))

def elapsed(name, item):
    rows = frames[name]
    return rows[item["cut"]]["wall"] - item["wall"] if "cut" in item else item["duration"]

def summarize(name, job):
    rows = frames[name]
    row = rows[job["i"]]
    forecast = row["forecast"]
    actual = elapsed(name, job)
    budget = (job.get("attack") or {}).get("speech_deadline")
    deadlines = {"estimated_runway": budget} if budget is not None else {}
    for later in rows[job["i"] + 1:]:
        if later["epoch"] != row["epoch"]:
            break
        f = later["forecast"]
        if "first_brake" not in deadlines and (later["brake"] or 0) > .18:
            deadlines["first_brake"] = later["t"]
        if "forecast_withdrawn" not in deadlines and f is not None and (
                f["id"] != forecast["id"] or not f["recommended"]):
            deadlines["forecast_withdrawn"] = later["t"]
        if "first_brake" in deadlines and "forecast_withdrawn" in deadlines:
            break
    if "cut" in job:
        deadlines["actual_cut"] = rows[job["cut"]]["t"]
    # The new phrase contains only the action. Including the last PCM sample
    # is a conservative bound that needs no alignment or ASR assumption.
    end = row["t"] + job["duration"] if "cut" not in job else None
    earliest = min(deadlines.values()) if deadlines else None
    return dict(code=job["code"], text=job["text"], start_s=row["t"], actual_s=round(actual, 4),
                duration_s=job["duration"], cut_s=rows[job["cut"]]["t"] if "cut" in job else None,
                last_useful_s=earliest, deadlines_s=deadlines, action_end_upper_s=end,
                remaining_after_action_s=earliest - end if end is not None and earliest is not None else None,
                source=row["src"])

short = [job for job in starts["before"] if job["code"] == "ATTACK_FORECAST"
         and "cut" in job and elapsed("before", job) < 1.]
assert len(short) == 3
sr = 22050
playlist = bytearray()
cases = []
for old in short:
    baseline = frames["before"][old["i"]]
    forecast = baseline["forecast"]
    new = next((job for job in starts["after"] if job["code"] == "ATTACK_FORECAST"
                and (job.get("attack") or {}).get("id") == forecast["id"]), None)
    first = old["wall"] - .45
    last = max(old["wall"] + 2., new["wall"] + elapsed("after", new) + .45 if new else 0.)
    n = round((last - first) * sr)
    case = dict(driver=forecast["name"], lap=baseline["lap"], gate=forecast["corner"],
                forecast_id=forecast["id"], before=summarize("before", old),
                after=summarize("after", new) if new else None)
    for name, job in (("before", old), ("after", new)):
        case[name + "_audio_s"] = round(len(playlist) / (2 * sr), 3)
        pcm = bytearray(2 * n)
        if job:
            data = Path(lexicons[name][job["text"]]).read_bytes()
            first_sample = round((job["wall"] - first) * sr)
            upto = min(len(data) // 2, round(elapsed(name, job) * sr))
            retained = max(0, min(upto, n - first_sample))
            pcm[first_sample * 2:(first_sample + retained) * 2] = data[:retained * 2]
        playlist.extend(pcm)
        playlist.extend(bytes(round(.65 * sr) * 2))
    playlist.extend(bytes(round(.35 * sr) * 2))
    cases.append(case)

counts = {}
for name, sequence in starts.items():
    forecasts = [item for item in sequence if item["code"] == "ATTACK_FORECAST"]
    counts[name] = dict(starts=len(forecasts), completed=sum("cut" not in a for a in forecasts),
                        cuts=sum("cut" in a for a in forecasts),
                        under_one_second=sum("cut" in a and elapsed(name, a) < 1 for a in forecasts),
                        all_codes=Counter(a["code"] for a in sequence))
result = dict(cases=cases, counts=counts)
(root / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i",
                "pipe:0", "-c:a", "libmp3lame", "-b:a", "64k",
                str(root / "jeddah-attack-before-after.mp3")], input=playlist, check=True)
print(json.dumps(result, ensure_ascii=False, indent=2))
assert all(case["after"] is None or (case["after"]["remaining_after_action_s"] or 0) > 0 for case in cases)
