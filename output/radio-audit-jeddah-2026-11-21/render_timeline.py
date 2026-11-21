"""Render the replay's actual spoken prefix and produce a keyed audit timeline."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
rows = [json.loads(x) for x in (root / "race.jsonl").open()]
starts = json.loads((root / "starts.json").read_text())
events = json.loads((root / "events.json").read_text())
lex = json.loads((root / "pcm-paths.json").read_text())
sr = 22050
origin = rows[0]["wall"]
clock = 0
last = 0
compact = bytearray()
timeline = []
at_frame = defaultdict(list)
for start in starts:
    at_frame[start["i"]].append(start["code"])
for i, start in enumerate(starts, 1):
    row = rows[start["i"]]
    cut = rows[start["cut"]] if "cut" in start else None
    assert (cut is not None) == bool(start["cancel_reason"]), start
    pcm = Path(lex[start["text"]]).read_bytes()
    begin = round((row["wall"] - origin) * sr)
    end = round((cut["wall"] - origin) * sr) if cut else begin + len(pcm) // 2
    assert last <= begin < end <= begin + len(pcm) // 2
    compact.extend(bytes(2 * min(begin - last, round(.65 * sr))) if i > 1 else b"")
    offset = len(compact) / (2 * sr)
    compact.extend(pcm[:2 * (end - begin)])
    last = end
    timeline.append(dict(number=i, id=start["id"], epoch=row["epoch"], lap=row["lap"],
                         race_s=row["t"], audio_s=round(offset, 3), output_code=start["code"],
                         priority=start["priority"], text=start["text"], source=row["src"],
                         full_s=round(len(pcm) / (2 * sr), 3), actual_s=round((end - begin) / sr, 3),
                         cancel_reason=start["cancel_reason"] if cut else None,
                         cut_race_s=cut["t"] if cut else None,
                         other_start_same_frame=at_frame[cut["i"]] if cut else []))
kinds = Counter((line["output_code"], bool(line["cancel_reason"])) for line in timeline)
enqueues = {e["output_event_id"]: e for e in events if e["event_type"] in {"enqueue", "replace_pending"}}
expired = {e["output_event_id"] for e in events
           if e["metadata"].get("reason") == "expired_before_start"}
start_ids = {e["id"] for e in timeline}
summary = {
    "frames": len(rows),
    "counts": {code: {"full": kinds[code, False], "cut": kinds[code, True]} for code, _ in kinds},
    "starts": len(timeline),
    "cuts": sum(bool(line["cancel_reason"]) for line in timeline),
    "cuts_under_one_second": sum(bool(line["cancel_reason"]) and line["actual_s"] < 1 for line in timeline),
    "cancel_reasons": Counter(line["cancel_reason"] for line in timeline if line["cancel_reason"]),
    "spoken_seconds": round(sum(line["actual_s"] for line in timeline), 3),
    "spoken_seconds_by_code": {code: round(sum(line["actual_s"] for line in timeline
                                         if line["output_code"] == code), 3) for code, _ in kinds},
    "pending_jobs": len(enqueues),
    "expired_pending_jobs": len(expired),
    "expired_pending_started": sorted(expired & start_ids),
    "started_pending": [line for line in timeline if line["id"] in enqueues],
    "terminal_frame_s": rows[-1]["t"],
    "audio_duration_s": len(compact) / (2 * sr),
}
for filename, data in (("audit-summary.json", summary), ("timeline.json", timeline)):
    (root / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2))
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(sr), "-ac", "1",
     "-i", "pipe:0", "-c:a", "libmp3lame", "-b:a", "64k", str(root / "jeddah-radio-current.mp3")],
    input=compact, check=True,
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
