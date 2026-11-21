"""Render and transcribe unprompted same-model wording samples."""
import json
from pathlib import Path
import subprocess
import sys
import wave

from faster_whisper import WhisperModel

directory = Path(__file__).resolve().parent
lexicon = json.loads(Path("/tmp/asurada-battle-ab/defence-six-current/lex.json").read_text())
worker = (directory / "piper_audit_worker.py").read_text()
anchor = "for request in sys.stdin:"
extra = "輪lun2 胎tai1 讀du2 读du2 数shu4 輪lun2 平ping2 均jun1 磨mo2 約yue1 约yue1"
worker = worker.replace(anchor, f"chars.update({{s[0]: s[1:] for s in {extra!r}.split()}})\n{anchor}")
phrases = [
    ("current_wing", "右前翼受损，损伤程度百分之三十一。前轮抓地可能下降。", True),
    ("current_tyre_damage", "注意。 右前轮损伤 35%", True),
    ("candidate_wing", "右前翼受损，损伤程度百分之三十一。", False),
    ("candidate_tyre_wear_same_frame", "右前轮胎磨损百分之三十五。", False),
    ("candidate_tyre_wear_spoken", "右前这条胎，磨损百分之三十五。", False),
    ("candidate_tyre_damage", "轮胎受损。右前轮，百分之三十五。", False),
    ("candidate_average_wear", "四条轮胎，平均磨损约百分之三十。", False),
]
parts = []
rows = []
with subprocess.Popen(
    ["/tmp/asurada-jarvis.bOjnjB/.venv/bin/python", "-c", worker],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
) as voice:
    for label, phrase, use_replay_pcm in phrases:
        if use_replay_pcm:
            pcm = Path(lexicon[phrase]).read_bytes()
        else:
            path = directory / f"{label}.pcm"
            print(json.dumps([phrase, str(path)], ensure_ascii=False), file=voice.stdin, flush=True)
            assert voice.stdout.readline().strip() == "ok", phrase
            pcm = path.read_bytes()
            path.unlink()
        path = directory / f"{label}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
            wav.writeframes(pcm)
        parts.append(pcm)
        rows.append({"sample": label, "expected": phrase, "seconds": len(pcm) / 44100})
    voice.stdin.close()
    assert voice.wait() == 0
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", "22050", "-ac", "1",
     "-i", "pipe:0", "-c:a", "libmp3lame", "-b:a", "64k", str(directory / "damage-wear-AB.mp3")],
    input=bytes(52920).join(parts), check=True,
)
model = WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
for item in rows:
    path = directory / (item["sample"] + ".wav")
    segments, _ = model.transcribe(str(path), language="zh", beam_size=5, condition_on_previous_text=False)
    item["asr"] = "".join(s.text for s in segments).strip()
    print(item, flush=True)
(directory / "damage-wear-ASR.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
