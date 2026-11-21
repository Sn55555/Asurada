"""Record the current scheduler against the archived Jeddah race using Piper PCM lengths."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import attack_forecast_archive_replay as runner
from asurada.output import ConsoleVoiceOutput
from asurada.track_model import load_track_profile

directory = Path(__file__).resolve().parent
lexicon_path = Path(os.environ.get(
    "ASURADA_AUDIT_LEXICON", "/tmp/asurada-battle-ab/defence-six-current/lex.json"))
lexicon = {text: Path(path) for text, path in json.loads(lexicon_path.read_text()).items()}
voice = subprocess.Popen([
    os.environ.get("ASURADA_AUDIT_PIPER_PYTHON", "/tmp/asurada-jarvis.bOjnjB/.venv/bin/python"),
    os.environ.get("ASURADA_AUDIT_PIPER_WORKER", str(directory / "piper_audit_worker.py")),
], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
events = []
jobs = []
base_event = ConsoleVoiceOutput._build_event_from_envelope
radio = None


class Recorder(runner.RadioClock):
    def __init__(self, durations):
        global radio
        super().__init__(durations)
        radio = self

    def start(self, job):
        line = job.speak_text
        if line not in lexicon or not lexicon[line].is_file():
            path = directory / ("pcm-" + hashlib.sha256(line.encode()).hexdigest()[:16] + ".pcm")
            if not path.is_file():
                print(json.dumps([line, str(path)], ensure_ascii=False), file=voice.stdin, flush=True)
                status = voice.stdout.readline().strip()
                if status != "ok":
                    raise SystemExit(f"Missing audit PCM for {line!r}: {status}")
            lexicon[line] = path
        self.durations[line] = lexicon[line].stat().st_size / 44100
        record = super().start(job)
        record.update(id=job.output_event_id, priority=job.priority,
                      is_combined=job.metadata.get("wing_compensation") == "combined")
        jobs.append(job)
        return record


def event(output, envelope, event_type, *args, **kwargs):
    result = base_event(output, envelope, event_type, *args, **kwargs)
    if envelope is not None:
        row = result.to_dict()
        if row["event_type"] != "suppress" or row["metadata"].get("reason"):
            events.append(dict(frame=radio.index, **row))
    return result


if __name__ == "__main__":
    archive = Path(sys.argv[1])
    assert load_track_profile("Jeddah") is not None, "Jeddah track resources are required"
    try:
        with patch.object(runner, "RadioClock", Recorder), patch.object(
            ConsoleVoiceOutput, "_build_event_from_envelope", event
        ):
            runner.replay(archive, "1476455955304844120", {}, directory / "race")
    finally:
        voice.stdin.close()
        voice.wait()
    for record, job in zip(radio.starts, jobs):
        record["cancel_reason"] = job.metadata.get("cancel_reason")
    for name, value in {"starts": radio.starts, "events": events,
                        "pcm-paths": {k: str(v) for k, v in lexicon.items()}}.items():
        (directory / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2))
