"""Render the S5 pit replay and a fixed H2 voice-delivery blind comparison."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import wave

from asurada.personality_voice import voice_cache_path
from asurada.personality_voice_worker import shape_delivery, valid_voice_file, write_wave
from personality_pit_advice_regression import run


VOICE_PROBE = "隼人，情况确认。我们还有机会。"
BLIND_ORDER = ("concerned", "excited", "calm", "firm")
SAMPLE_RATE = 44100


def prepare_voice(source, isolated, texts):
    for name in ("model", "reference.wav"):
        path = source / name
        if path.exists():
            (isolated / name).symlink_to(path)
    (isolated / "cache").mkdir()
    for text in texts:
        cached = voice_cache_path(source, text)
        if valid_voice_file(cached, text):
            voice_cache_path(isolated, text).symlink_to(cached)
    worker = Path(__file__).resolve().parents[1] / "src/asurada/personality_voice_worker.py"
    subprocess.run([str(source / ".venv/bin/python"), str(worker), str(isolated), "--prepare"],
                   input=json.dumps(texts, ensure_ascii=False), text=True, check=True)


def prepare_delivery_probe(source, isolated, target):
    # Match uncached production delivery. Both samples and the control share
    # one underlying render with clause breaks so that pace stays comparable.
    script = (
        "from pathlib import Path\n"
        "import sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from asurada.personality_voice_worker import Renderer\n"
        "Renderer(Path(sys.argv[2])).render(sys.stdin.read(), Path(sys.argv[3]), phrase_breaks=True)\n"
    )
    asurada_src = Path(__file__).resolve().parents[1] / "src"
    subprocess.run([str(source / ".venv/bin/python"), "-c", script, str(asurada_src), str(isolated), str(target)],
                   input=VOICE_PROBE, text=True, check=True)


def concatenate(clips, output, work):
    frames = bytearray()
    manifest = []
    for clip, row, pause in clips:
        start = len(frames) / (2 * SAMPLE_RATE)
        with wave.open(str(clip), "rb") as voice:
            if (voice.getframerate(), voice.getsampwidth(), voice.getnchannels()) != (SAMPLE_RATE, 2, 1):
                raise ValueError(f"Unexpected preview audio format in {clip}")
            frames.extend(voice.readframes(voice.getnframes()))
        manifest.append({**row, "start_s": round(start, 3), "end_s": round(len(frames) / (2 * SAMPLE_RATE), 3)})
        frames.extend(b"\0" * (int(SAMPLE_RATE * pause) * 2))
    joined = work / f"{output.stem}.wav"
    write_wave(joined, frames, SAMPLE_RATE)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(joined),
                    "-c:a", "libmp3lame", "-b:a", "128k", str(output)], check=True)
    return manifest


def preview(source, output):
    replay = run()
    if not replay["passed"]:
        raise RuntimeError("Pit replay failed before voice rendering")
    stages = {stage: [item for item in items if item["code"] == "BOX_WINDOW"
                      or item["code"].startswith("PERSONALITY_PIT_")]
              for stage, items in replay["examples"].items()}
    texts = list(dict.fromkeys(item["text"] for items in stages.values() for item in items))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="asurada-personality-preview-") as directory:
        workspace = Path(directory)
        voice_root = workspace / "voice"
        voice_root.mkdir()
        prepare_voice(source, voice_root, texts)
        stage_clips = [(voice_cache_path(voice_root, item["text"]), {"stage": stage, **item},
                        1.5 if index == len(items) - 1 else .55)
                       for stage, items in stages.items() for index, item in enumerate(items)]
        stage_index = concatenate(stage_clips, output / "H0-H3-pit-radio.mp3", workspace)
        blind_clips = []
        base = workspace / "delivery-probe.wav"
        prepare_delivery_probe(source, voice_root, base)
        for letter, style in zip("ABCD", BLIND_ORDER):
            clip = base
            if style != "calm":
                styled = workspace / f"H2-{letter}.wav"
                shape_delivery(clip, styled, style)
                clip = styled
            blind_clips.append((clip, {"sample": letter, "text": VOICE_PROBE}, 1.4))
        blind_index = concatenate(blind_clips, output / "H2-delivery-blind.mp3", workspace)
    notes = {"voice": "asurada_zh_reference_v1", "stage_timeline": stage_index,
             "blind_timeline": blind_index, "scheduler_interruptions": replay["interruptions"]}
    (output / "preview-index.json").write_text(json.dumps(notes, ensure_ascii=False, indent=2) + "\n")
    (output / "blind-answer-key.json").write_text(json.dumps(dict(zip("ABCD", BLIND_ORDER)), indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice-dir", type=Path, default=Path.home() / ".asurada/voice/asurada-zh-v1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    preview(args.voice_dir.expanduser().resolve(), args.output.resolve())
