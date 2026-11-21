"""Extract scheduling examples from the same continuous comparison audio."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
timeline = json.loads((root / "timeline.json").read_text())
events = (
    next((e for e in timeline if e["lap"] == 16 and e["output_code"] == "FRONT_WING_DAMAGE"
          and "DYNAMICS_UNSTABLE" in e["other_start_same_frame"]), None),
    next((e for e in timeline if e["output_code"] == "ATTACK_FORECAST"
          and e["cancel_reason"] and e["actual_s"] < 1), None),
)
result = []
for index, event in enumerate(events):
    if event is None:
        continue
    filename = ("wing-to-instability.mp3", "attack-cut.mp3")[index]
    duration = event["actual_s"]
    if index == 0:
        following = timeline[event["number"]]
        duration = following["audio_s"] + following["actual_s"] - event["audio_s"]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", str(event["audio_s"]),
         "-i", str(root / "jeddah-radio-current.mp3"), "-t", str(duration), str(root / filename)],
        check=True,
    )
    result.append(dict(file=filename, **event))
(root / "highlights.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
