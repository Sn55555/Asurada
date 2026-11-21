"""Check emotion delivery, bounded cache validation, and the fast emergency route."""
from pathlib import Path
import hashlib
import math
import struct
import wave
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asurada.interaction import SpeechJob
from asurada.personality_voice import AsuradaPersonalityVoice, voice_cache_path
from asurada.personality_voice_worker import (
    DELIVERIES, cache_filename, detect_pauses, max_voice_seconds, render_blocks, shape_delivery, synthesis_text,
    valid_voice_file, write_wave,
)
from asurada.tts_backends import SpeechBackend
from regression_support import emit_result


def job(code, text, tone, **extra):
    return SpeechJob("out:1", "session", "turn", "request", "snapshot", "strategy_broadcast",
                     code, 80, text, True, metadata={"personality": {"tone": tone}, **extra})


class Fallback(SpeechBackend):
    def start(self, value):
        return value.action_code


def run():
    text = "隼人，保持这个节奏。"
    with TemporaryDirectory(prefix="asurada-voice-test-") as directory:
        root = Path(directory).resolve()
        player = root / "afplay"
        player.touch()
        player.chmod(0o700)
        (root / ".venv/bin").mkdir(parents=True)
        (root / ".venv/bin/python").touch()
        (root / "model").mkdir()
        (root / "model/config.json").touch()
        (root / "reference.wav").touch()
        (root / "cache").mkdir()
        line = voice_cache_path(root, text)
        write_wave(line, b"\0" * 44100, 44100)
        emergency_line = voice_cache_path(root, "动态不稳定")
        write_wave(emergency_line, b"\0" * 44100, 44100)
        backend = AsuradaPersonalityVoice(root, Fallback(), player=str(player))
        legacy_key = hashlib.sha256(text.encode("utf-8")).hexdigest() + ".wav"
        spliced_key = hashlib.sha256(f"mandarin-name-v3\0{text}".encode("utf-8")).hexdigest() + ".wav"
        checks = {
            "pronunciation_uses_same_sound_without_changing_cue_text": synthesis_text(text) == "笋人，保持这个节奏。"
                and cache_filename(text) not in {legacy_key, spliced_key}
                and synthesis_text("动态不稳定") == "动态不稳定",
            "callsign_is_rendered_in_context_at_either_position": (
                render_blocks("隼人，稳住。我们还有机会。", phrase_breaks=True)
                == ["笋人，稳住。", "我们还有机会。"]
                and render_blocks("进站，隼人。", phrase_breaks=False) == ["进站，笋人。"]),
        }
        rate = 24000
        signal = b"".join(struct.pack("<h", round(12000 * math.sin(2 * math.pi * 300 * i / rate)))
                          for i in range(rate))
        two_phrases = root / "two-phrases.wav"
        write_wave(two_phrases, signal + b"\0" * (rate // 2) + signal, rate)
        variants = {}
        for name in ("firm", "concerned", "excited"):
            rendered = root / f"{name}.wav"
            shape_delivery(two_phrases, rendered, name)
            with wave.open(str(rendered), "rb") as take:
                duration = take.getnframes() / take.getframerate()
            gaps = detect_pauses(rendered, threshold_db=-39, minimum_s=.07)
            variants[name] = (duration, max((end-start for start, end in gaps), default=0))
        checks["emotion_varies_emphasis_and_short_pauses_without_changing_phrase_rate"] = (
            all(profile.lead_rate == profile.follow_rate == 1. for profile in DELIVERIES.values())
            and len({(profile.lead_db, profile.follow_db, profile.presence_db)
                     for profile in DELIVERIES.values()}) == 3
            and variants["excited"][1] < variants["firm"][1] < variants["concerned"][1] < .32
            and variants["concerned"][0] - variants["excited"][0] < .24)

        with patch.object(backend, "_run", return_value="started") as spawn:
            def command(code, words, tone, **metadata):
                request = job(code, words, tone, **metadata)
                backend.start(request)
                return spawn.call_args, request.metadata

            concerned, audible = command("QUERY_TIRE_STATUS", text, "concerned")
            checks["concerned_shapes_cached_pcm_as_two_phrases"] = (
                concerned.args[0][-4:] == ["--delivery", "concerned", "--source-wave", str(line)]
                and audible["render_rate"] == audible["render_follow_rate"] == 1.)
            excited, audible = command("PERSONALITY_OVERTAKE", text, "excited")
            checks["excited_shapes_cached_pcm_without_accelerating_phrases"] = (
                excited.args[0][-4:] == ["--delivery", "excited", "--source-wave", str(line)]
                and audible["render_rate"] == 1. and audible["render_delivery"] == "excited")
            incumbent, audible = command("PERSONALITY_PIT_INSIST", text, "firm", pit_follow_up="insist")
            checks["approved_pit_lines_keep_their_rate"] = incumbent.args[0] == [str(player), str(line)] and audible["render_rate"] == 1
            emergency, audible = command("DYNAMICS_UNSTABLE", "动态不稳定", "excited")
            checks["urgent_plays_precached_at_baseline_without_synthesis"] = (
                emergency.args[0] == [str(player), str(emergency_line)] and audible["render_delivery"] == "urgent")
            calls = spawn.call_count
            fallback = backend.start(job("SAFETY_CAR", "未缓存的赛道管制短句", "concerned"))
            checks["uncached_emergency_uses_fast_fallback"] = fallback.process == "SAFETY_CAR" and spawn.call_count == calls
            write_wave(line, b"\0" * (2 * 44100 * 60), 44100)
            retry, _ = command("PERSONALITY_OVERTAKE", text, "excited")
            checks["runaway_cache_is_not_playable"] = (
                not valid_voice_file(line, text) and max_voice_seconds(text) < 15
                and retry.args[0][-2:] == ["--delivery", "excited"] and retry.kwargs["text"] == text)
    return {"passed": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    emit_result(run())
