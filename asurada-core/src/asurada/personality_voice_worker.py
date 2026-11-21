"""Render or prewarm the local Asurada voice using an isolated MLX interpreter."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import wave

# Usable as a standalone worker outside the strategy runtime's Python environment.
ARTICULATION_REFERENCE = "reference.wav"


@dataclass(frozen=True)
class Delivery:
    lead_rate: float
    follow_rate: float
    pause_s: float
    lead_db: float
    follow_db: float
    presence_db: float = 0.


DELIVERIES = {
    "firm": Delivery(1., 1., .14, 2.8, 0., .5),
    "concerned": Delivery(1., 1., .25, -1.8, -.2, -1.5),
    "excited": Delivery(1., 1., .08, 3., 1., 2.5),
}


def synthesis_text(text: str) -> str:
    # Common homophone helps the Mandarin tokenizer pronounce 隼 (sǔn).
    return text.replace("隼", "笋")


def render_blocks(text: str, *, phrase_breaks: bool) -> list[str]:
    # Let the model read the callsign within its sentence, including any commas.
    spoken = synthesis_text(text).lstrip(" ，、；：。！？,.!?")
    if phrase_breaks:
        return [segment for segment in re.split(r"(?<=[。！？])\s*", spoken) if segment]
    return [spoken] if spoken else []


def cache_filename(text: str) -> str:
    # Invalidate old name splices without regenerating unrelated alerts.
    key = f"mandarin-name-v4\0{text}" if synthesis_text(text) != text else text
    return hashlib.sha256(key.encode("utf-8")).hexdigest() + ".wav"


def max_voice_seconds(text: str) -> float:
    letters = sum(character.isalnum() for character in text)
    return min(90.0, max(5.5, 2.5 + .42 * letters))


def valid_voice_file(path: Path, text: str) -> bool:
    try:
        with wave.open(str(path), "rb") as wav:
            rate, frames = wav.getframerate(), wav.getnframes()
            return (rate > 0 and wav.getnchannels() == 1 and wav.getsampwidth() == 2
                    and .2 <= frames / rate <= max_voice_seconds(text)
                    and path.stat().st_size >= 2 * frames)
    except (OSError, EOFError, wave.Error):
        return False


def write_wave(path: Path, frames: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)


def detect_pauses(path: Path, *, threshold_db: int, minimum_s: float) -> list[tuple[float, float]]:
    report = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"silencedetect=noise={threshold_db}dB:d={minimum_s}", "-f", "null", "-"],
        capture_output=True, text=True, check=True).stderr
    starts = re.findall(r"silence_start: ([0-9.]+)", report)
    ends = re.findall(r"silence_end: ([0-9.]+)", report)
    return list(zip(map(float, starts), map(float, ends)))


def shorten_pauses(raw: Path, target: Path, rate: int, frames: bytes) -> None:
    pauses = detect_pauses(raw, threshold_db=-37, minimum_s=.22)
    total_s = len(frames) / (2 * rate)
    previous = 0
    pieces = []
    for start, end in pauses:
        if end - start < .46:
            continue
        keep = .24 if end >= total_s - .05 else .36
        keep_start = round((start + keep / 2) * rate) * 2
        keep_end = round((end - keep / 2) * rate) * 2
        pieces.append(frames[previous:keep_start])
        previous = keep_end
    pieces.append(frames[previous:])
    write_wave(target, b"".join(pieces), rate)


def shape_delivery(source: Path, target: Path, style: str) -> None:
    delivery = DELIVERIES[style]
    with wave.open(str(source), "rb") as original:
        duration = original.getnframes() / original.getframerate()
        rate = original.getframerate()
    # Pick an existing internal break. Never manufacture a pause inside a word.
    pauses = [gap for gap in detect_pauses(source, threshold_db=-39, minimum_s=.12)
              if duration * .12 < gap[0] and gap[1] < duration * .88]
    pause = max(pauses, key=lambda pair: pair[1] - pair[0], default=None)
    eq = f"equalizer=f=2450:t=q:w=0.9:g={delivery.presence_db},"
    limiter = "alimiter=limit=0.86:level=false:latency=1"
    if pause is None:
        # A one-phrase cue still gets a gentle emphasis contour.
        fade_position = min(.8, duration * .4 / delivery.lead_rate)
        span = max(.15, duration * .35 / delivery.lead_rate)
        begin, change = 10 ** (delivery.lead_db / 20), 10 ** (delivery.follow_db / 20) - 10 ** (delivery.lead_db / 20)
        gain = f"volume='{begin}+({change})*clip((t-{fade_position})/{span},0,1)':eval=frame"
        graph = f"[0:a]atempo={delivery.lead_rate},{gain},{eq}{limiter}[out]"
    else:
        start, end = pause
        graph = (
            f"[0:a]atrim=end={start + .025},asetpts=PTS-STARTPTS,atempo={delivery.lead_rate},volume={delivery.lead_db}dB[lead];"
            f"anullsrc=r={rate}:cl=mono:d={delivery.pause_s}[gap];"
            f"[0:a]atrim=start={end - .025},asetpts=PTS-STARTPTS,atempo={delivery.follow_rate},volume={delivery.follow_db}dB[follow];"
            f"[lead][gap][follow]concat=n=3:v=0:a=1,{eq}{limiter}[out]"
        )
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                    "-filter_complex", graph, "-map", "[out]", "-ac", "1", "-c:a", "pcm_s16le", str(target)],
                   check=True)


class Renderer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.model = None

    def render(self, text: str, target: Path, *, phrase_breaks: bool = False) -> None:
        import mlx.core as mx
        import numpy as np
        from mlx_audio.tts.utils import load_model

        if self.model is None:
            self.model = load_model(str(self.root / "model"))
        # Allow room for the usual final pause, but never publish a short line
        # which hit the model's token cap or ran on well beyond its text.
        token_limit = min(1200, math.ceil((max_voice_seconds(text) * 1.12 + 1) * 12.5))
        rate = self.model.sample_rate
        blocks = render_blocks(text, phrase_breaks=phrase_breaks)
        with tempfile.TemporaryDirectory(prefix=".voice-", dir=target.parent) as temp:
            directory = Path(temp)
            raw, paced, result = [directory / name for name in ("raw.wav", "paced.wav", "voice.wav")]
            for seed in (42, 137, 192):
                mx.random.seed(seed)
                chunks = []
                for block in blocks:
                    items = list(self.model.generate(text=block, lang_code="chinese",
                        ref_audio=str(self.root / ARTICULATION_REFERENCE), temperature=.5, max_tokens=token_limit))
                    if not items or any(item.token_count >= token_limit for item in items):
                        break
                    for item in items:
                        mx.eval(item.audio)
                    chunk = np.concatenate([np.asarray(item.audio, dtype=np.float32).ravel() for item in items])
                    chunks.append(chunk)
                if not chunks or len(chunks) != len(blocks):
                    continue
                timed = []
                for index, chunk in enumerate(chunks):
                    if index:
                        timed.append(np.zeros(int(rate * .20), dtype=np.float32))
                    timed.append(chunk)
                audio = np.concatenate(timed)
                if (audio.size < rate / 5 or not np.isfinite(audio).all() or np.max(np.abs(audio)) <= .025):
                    continue
                frames = (np.clip(audio, -.999, .999) * 32767).astype("<i2").tobytes()
                write_wave(raw, frames, rate)
                shorten_pauses(raw, paced, rate, frames)
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(paced),
                    "-af", "highpass=f=75,atempo=1.12,loudnorm=I=-16:LRA=7:TP=-1.5",
                    "-ar", "44100", "-ac", "1", "-codec:a", "pcm_s16le", str(result)], check=True)
                if valid_voice_file(result, text):
                    os.replace(result, target)
                    return
        raise ValueError("asurada_voice_unusable_audio")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true", help="Pre-render a JSON array of fixed lines from stdin.")
    group.add_argument("--play", metavar="PLAYER")
    parser.add_argument("--delivery", choices=tuple(DELIVERIES))
    parser.add_argument("--source-wave", type=Path)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    renderer = Renderer(args.root)
    if args.prepare:
        cache = args.root / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        for text in dict.fromkeys(json.load(sys.stdin)):
            path = cache / cache_filename(text)
            if not valid_voice_file(path, text):
                renderer.render(text, path)
    else:
        with tempfile.TemporaryDirectory(prefix="asurada-local-voice-") as temp:
            text = sys.stdin.read()
            path = args.source_wave
            if path is None or not valid_voice_file(path, text):
                path = Path(temp) / "speech.wav"
                renderer.render(text, path, phrase_breaks=bool(args.delivery))
            if args.delivery:
                styled = Path(temp) / "styled.wav"
                shape_delivery(path, styled, args.delivery)
                path = styled
            subprocess.run([args.play, str(path)], check=True)


if __name__ == "__main__":
    main()
