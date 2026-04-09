from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

from asurada.audio_agent_client import VoiceSidecarClient, VoiceSidecarClientError
from asurada.audio_io import AudioFormat
from asurada.decode import decode_snapshot
from asurada.macos_speech import MacOSSpeechRecognizer
from asurada.models import SessionState, StrategyMessage
from asurada.open_asr import OpenAsrRecognizer
from asurada.output import ConsoleVoiceOutput
from asurada.persona_registry import get_default_persona
from asurada.tts_backends import NullSpeechBackend
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_meter import load_voice_meter_snapshot
from asurada.voice_sidecar_asr import (
    DoubaoRealtimeAsrRecognizer,
    VoiceSidecarAsrRecognizer,
    VoiceSidecarRealtimeAsrRecognizer,
)
from asurada.voice_sidecar_protocol import TtsRenderRequest
from asurada.voice_turn import VoiceTurn
from asurada.wake_word import WakeWordGate


_DEFAULT_RECOGNIZER_BACKEND = (
    "voice_sidecar_realtime_asr"
    if VoiceSidecarRealtimeAsrRecognizer.env_ready()
    else "doubao_realtime_asr"
    if DoubaoRealtimeAsrRecognizer.env_ready()
    else "voice_sidecar_asr"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a macOS duplex voice-loop smoke test against one snapshot.")
    parser.add_argument(
        "--session-log",
        default="asurada-core/runtime_logs/session_log.jsonl",
        help="Session log jsonl used as the snapshot source.",
    )
    parser.add_argument(
        "--row",
        default="latest",
        help="Row selector: latest or zero-based row index.",
    )
    parser.add_argument(
        "--locale",
        default="zh-CN",
        help="Speech recognition locale identifier.",
    )
    parser.add_argument(
        "--recognizer-backend",
        choices=("voice_sidecar_realtime_asr", "voice_sidecar_asr", "doubao_realtime_asr", "open_asr", "macos_speech"),
        default=os.getenv("ASURADA_RECOGNIZER_BACKEND", _DEFAULT_RECOGNIZER_BACKEND),
        help="Recognizer backend used for microphone turns.",
    )
    parser.add_argument(
        "--no-auto-refresh",
        action="store_true",
        help="Do not reload the latest snapshot before each listen cycle.",
    )
    parser.add_argument(
        "--wait-for-live-seconds",
        type=float,
        default=30.0,
        help="How long to wait for the first live snapshot when the session log is still empty.",
    )
    parser.add_argument(
        "--wake-phrase",
        action="append",
        dest="wake_phrases",
        help="Wake phrase to require before processing a query. Repeatable.",
    )
    parser.add_argument(
        "--disable-wake-word",
        action="store_true",
        help="Disable the wake-word gate and accept every recognized turn directly.",
    )
    parser.add_argument(
        "--wake-window-ms",
        type=int,
        default=8000,
        help="How long follow-up turns remain active after a wake phrase.",
    )
    parser.add_argument(
        "--show-recognizer-json",
        action="store_true",
        help="Print the full recognizer result json.",
    )
    parser.add_argument(
        "--show-processing-json",
        action="store_true",
        help="Print the full voice processing result json.",
    )
    parser.add_argument(
        "--enable-llm-sidecar",
        action="store_true",
        help="Enable the explainer-sidecar path for explainer-lane questions.",
    )
    parser.add_argument(
        "--llm-timeout-ms",
        type=int,
        default=None,
        help="Override the LLM sidecar timeout in milliseconds.",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Use the old press-Enter-per-turn mode instead of continuous listening.",
    )
    parser.add_argument(
        "--loop-idle-ms",
        type=int,
        default=250,
        help="Idle delay between continuous listen cycles.",
    )
    parser.add_argument(
        "--use-sidecar-tts",
        action="store_true",
        help="Render speech through the voice sidecar and play locally instead of using the core TTS backend.",
    )
    args = parser.parse_args()

    wake_phrases = tuple(args.wake_phrases or ["阿斯拉达", "asurada"])
    wake_word_gate = WakeWordGate(
        enabled=not args.disable_wake_word,
        phrases=wake_phrases,
        activation_window_ms=args.wake_window_ms,
    )

    state, primary_message = wait_for_state_and_message(
        Path(args.session_log),
        args.row,
        wait_seconds=args.wait_for_live_seconds,
    )
    coordinator = VoiceInputCoordinator(
        wake_word_gate=wake_word_gate,
        enable_llm_sidecar=True if args.enable_llm_sidecar else None,
        llm_timeout_ms=args.llm_timeout_ms,
    )
    state_ref: dict[str, Any] = {
        "state": state,
        "primary_message": primary_message,
    }
    recognizer = _build_recognizer(
        args.recognizer_backend,
        wake_word_gate=wake_word_gate,
        route_preview_callback=_make_partial_route_preview_callback(
            coordinator=coordinator,
            state_ref=state_ref,
            wake_word_gate=wake_word_gate,
        ),
    )
    if recognizer is None:
        print(f"recognizer backend is not ready: {args.recognizer_backend}", file=sys.stderr)
        return 2
    voice_output = ConsoleVoiceOutput(
        backend=NullSpeechBackend() if args.use_sidecar_tts else None,
    )
    sidecar_client = VoiceSidecarClient.from_env() if args.use_sidecar_tts else None
    downlink_cooldown_ms = max(int(os.getenv("ASURADA_VOICE_DOWNLINK_COOLDOWN_MS") or "900"), 0)
    downlink_resume_after_ms = 0

    print("macOS duplex voice loop")
    print(f"track={state.track} lap={state.lap_number}/{state.total_laps} position=P{state.player.position}")
    print(f"weather={state.weather} safety_car={state.safety_car} source_ts={state.source_timestamp_ms}")
    if primary_message is not None:
        print(f"primary_message={primary_message.code} {primary_message.title}")
    if args.disable_wake_word:
        print("wake_word=disabled")
    else:
        print(f"wake_word=enabled phrases={list(wake_phrases)} window_ms={args.wake_window_ms}")
    print(
        f"llm_sidecar enabled={coordinator.enable_llm_sidecar} "
        f"backend={coordinator.llm_explainer.backend.name} "
        f"timeout_ms={coordinator.llm_timeout_ms}"
    )
    print(f"recognizer_backend={args.recognizer_backend}")
    print(f"sidecar_tts enabled={args.use_sidecar_tts}")
    if args.manual:
        print("mode=manual commands: press Enter to listen, r to reload snapshot, q to quit")
    else:
        print("mode=continuous controls: type r + Enter to reload snapshot, q + Enter to quit")
        print("continuous listening is active; say the wake phrase and query in one sentence.")

    control = _ControlChannel()
    if not args.manual:
        control.start()

    while True:
        if args.manual:
            command = input("> ").strip().lower()
            if command in {"q", "quit", "exit"}:
                return 0
            if command in {"r", "reload"}:
                state, primary_message = wait_for_state_and_message(
                    Path(args.session_log),
                    args.row,
                    wait_seconds=args.wait_for_live_seconds,
                )
                state_ref["state"] = state
                state_ref["primary_message"] = primary_message
                print(f"reloaded track={state.track} lap={state.lap_number}/{state.total_laps} P{state.player.position}")
                continue
        else:
            command = control.poll_command()
            if command in {"q", "quit", "exit"}:
                return 0
            if command in {"r", "reload"}:
                state, primary_message = wait_for_state_and_message(
                    Path(args.session_log),
                    args.row,
                    wait_seconds=args.wait_for_live_seconds,
                )
                state_ref["state"] = state
                state_ref["primary_message"] = primary_message
                print(f"reloaded track={state.track} lap={state.lap_number}/{state.total_laps} P{state.player.position}")
                continue

        if not args.no_auto_refresh:
            state, primary_message = wait_for_state_and_message(
                Path(args.session_log),
                args.row,
                wait_seconds=args.wait_for_live_seconds,
            )
            state_ref["state"] = state
            state_ref["primary_message"] = primary_message

        now_ms = int(time.time() * 1000)
        if _is_downlink_playback_active() or now_ms < downlink_resume_after_ms:
            if not args.manual:
                time.sleep(max(args.loop_idle_ms, 0) / 1000.0)
            continue

        print("listening...")
        try:
            result = recognizer.listen_once()
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            message = str(exc)
            print(f"recognizer_error={message}", file=sys.stderr)
            if _is_privacy_violation(message):
                print(
                    "macOS privacy denied microphone or speech recognition access for Terminal. "
                    "Enable both permissions, then restart the voice loop.",
                    file=sys.stderr,
                )
                return 3
            if args.manual:
                continue
            time.sleep(max(args.loop_idle_ms, 0) / 1000.0)
            continue
        print(f"recognizer status={result.status} transcript={result.transcript_text!r}")
        if args.show_recognizer_json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        if result.status not in {"recognized", "recognized_partial"} or not result.transcript_text.strip():
            if not args.manual:
                time.sleep(max(args.loop_idle_ms, 0) / 1000.0)
            continue

        turn = VoiceTurn(
            turn_id=f"voice-turn:macos:{int(time.time() * 1000)}",
            started_at_ms=result.started_at_ms,
            ended_at_ms=result.ended_at_ms,
            audio_format=AudioFormat(),
            pcm_s16le=b"",
            chunk_count=0,
            source=args.recognizer_backend,
            completion_reason=result.status,
            metadata={
                "transcript_text": result.transcript_text,
                "transcript_hint": str((result.metadata or {}).get("partial_transcript") or "").strip(),
                args.recognizer_backend: result.to_dict(),
            },
        )
        processing = coordinator.process_completed_turn(
            state=state,
            turn=turn,
            voice_output=voice_output,
            primary_message=primary_message,
            render=not args.use_sidecar_tts,
        )
        _print_processing_summary(processing.to_dict())
        if args.show_processing_json:
            print(json.dumps(processing.to_dict(), ensure_ascii=False, indent=2))
        if sidecar_client is not None:
            played = _play_sidecar_tts(processing=processing.to_dict(), client=sidecar_client)
            if played:
                downlink_resume_after_ms = int(time.time() * 1000) + downlink_cooldown_ms
        if processing.status == "wake_armed":
            print("wake word armed, waiting for follow-up query...")
        if processing.status == "ignored":
            print("ignored: wake word required")
        if not args.manual:
            time.sleep(max(args.loop_idle_ms, 0) / 1000.0)


def load_state_and_message(path: Path, row_selector: str) -> tuple[SessionState, StrategyMessage | None]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise RuntimeError(f"empty session log: {path}")
    if row_selector == "latest":
        row = rows[-1]
    else:
        row = rows[int(row_selector)]

    payload = {
        "session_uid": row["session_uid"],
        "track": row["track"],
        "lap_number": row["lap_number"],
        "total_laps": row["total_laps"],
        "weather": row.get("weather") or "Unknown",
        "safety_car": row.get("safety_car") or "NONE",
        "source_timestamp_ms": row.get("source_timestamp_ms") or 0,
        "player": row["player"],
        "rivals": row.get("rivals") or [],
        "raw": row.get("raw") or {},
    }
    state = decode_snapshot(payload)
    primary_message = None
    if row.get("messages"):
        top = row["messages"][0]
        primary_message = StrategyMessage(
            code=str(top["code"]),
            priority=int(top["priority"]),
            title=str(top["title"]),
            detail=str(top["detail"]),
        )
    return state, primary_message


def build_standby_state_and_message() -> tuple[SessionState, StrategyMessage | None]:
    now_ms = int(time.time() * 1000)
    payload = {
        "session_uid": f"standby-{now_ms}",
        "track": "Standby",
        "lap_number": 0,
        "total_laps": 0,
        "weather": "N/A",
        "safety_car": "NONE",
        "source_timestamp_ms": now_ms,
        "player": {
            "car_index": 0,
            "name": "Driver",
            "position": 0,
            "lap": 0,
            "gap_ahead_s": None,
            "gap_behind_s": None,
            "fuel_laps_remaining": 0.0,
            "ers_pct": 0.0,
            "drs_available": False,
            "tyre": {
                "compound": "Unknown",
                "wear_pct": 0.0,
                "age_laps": 0,
                "surface_temperature_c": [],
                "inner_temperature_c": [],
            },
            "speed_kph": 0.0,
            "status_tags": [],
        },
        "rivals": [],
        "raw": {
            "runtime_context_seed": "standby_bootstrap",
        },
    }
    return decode_snapshot(payload), None


def _build_recognizer(
    backend_name: str,
    *,
    wake_word_gate: WakeWordGate | None = None,
    route_preview_callback: Any | None = None,
):
    last_partial = {"text": "", "wake": None}

    def handle_partial(text: str) -> None:
        cleaned = str(text or "").strip()
        if not cleaned or cleaned == last_partial["text"]:
            return
        last_partial["text"] = cleaned
        print(f"recognizer partial={cleaned!r}")
        if wake_word_gate is None or not wake_word_gate.enabled:
            if route_preview_callback is not None:
                route_preview_callback(cleaned, None, cleaned)
            return
        matched_phrase, remainder = wake_word_gate.preview_match(cleaned)
        if matched_phrase is None:
            last_partial["wake"] = None
            return
        preview_key = f"{matched_phrase}|{remainder}"
        if last_partial["wake"] == preview_key:
            return
        last_partial["wake"] = preview_key
        activation_expires_at_ms = wake_word_gate.arm_from_preview(
            timestamp_ms=int(time.time() * 1000),
            matched_phrase=matched_phrase,
        )
        print(
            "wake_preview "
            f"matched={matched_phrase!r} "
            f"query={remainder!r} "
            f"activation_expires_at_ms={activation_expires_at_ms}"
        )
        if route_preview_callback is not None:
            route_preview_callback(cleaned, matched_phrase, remainder)

    if backend_name == "voice_sidecar_asr":
        if not VoiceSidecarAsrRecognizer.env_ready():
            return None
        return VoiceSidecarAsrRecognizer.from_env()
    if backend_name == "voice_sidecar_realtime_asr":
        if not VoiceSidecarRealtimeAsrRecognizer.env_ready():
            return None
        return VoiceSidecarRealtimeAsrRecognizer.from_env(
            partial_callback=handle_partial,
        )
    if backend_name == "doubao_realtime_asr":
        if not DoubaoRealtimeAsrRecognizer.env_ready():
            return None
        return DoubaoRealtimeAsrRecognizer.from_env(
            partial_callback=handle_partial,
        )
    if backend_name == "open_asr":
        if not OpenAsrRecognizer.env_ready():
            return None
        return OpenAsrRecognizer.from_env()
    if backend_name == "macos_speech":
        if not MacOSSpeechRecognizer.env_ready():
            return None
        return MacOSSpeechRecognizer.from_env()
    return None


def _make_partial_route_preview_callback(
    *,
    coordinator: VoiceInputCoordinator,
    state_ref: dict[str, Any],
    wake_word_gate: WakeWordGate,
):
    last_preview = {"key": None}

    def callback(partial_text: str, matched_phrase: str | None, remainder: str) -> None:
        if wake_word_gate.enabled:
            if matched_phrase is None:
                return
            effective_text = str(remainder or "").strip()
        else:
            effective_text = str(partial_text or "").strip()
        if not effective_text:
            return

        state = state_ref.get("state")
        if not isinstance(state, SessionState):
            return
        primary_message = state_ref.get("primary_message")
        if primary_message is not None and not isinstance(primary_message, StrategyMessage):
            primary_message = None

        preview_turn = VoiceTurn(
            turn_id=f"voice-turn:partial-preview:{int(time.time() * 1000)}",
            started_at_ms=0,
            ended_at_ms=int(time.time() * 1000),
            audio_format=AudioFormat(),
            pcm_s16le=b"",
            chunk_count=0,
            source="doubao_realtime_asr_partial",
            completion_reason="recognized_partial",
            metadata={"transcript_text": effective_text},
        )
        fast_intent = coordinator.fast_intent_asr.recognize_turn(preview_turn)
        semantic_intent = coordinator.semantic_normalizer.normalize(
            state=state,
            voice_turn=preview_turn,
            fast_intent=fast_intent,
            conversation_context=coordinator.conversation_context,
            primary_message=primary_message,
        )
        route_decision = coordinator.transcript_router.route(
            state=state,
            fast_intent=fast_intent,
            semantic_intent=semantic_intent,
        )
        if route_decision.status != "routed" or route_decision.query_kind is None:
            return

        preview_key = "|".join(
            (
                route_decision.lane,
                str(route_decision.query_kind),
                str(semantic_intent.normalized_query_text),
            )
        )
        if last_preview["key"] == preview_key:
            return
        last_preview["key"] = preview_key
        print(
            "route_preview "
            f"lane={route_decision.lane} "
            f"query_kind={route_decision.query_kind} "
            f"text={semantic_intent.normalized_query_text!r}"
        )

    return callback


def wait_for_state_and_message(path: Path, row_selector: str, *, wait_seconds: float) -> tuple[SessionState, StrategyMessage | None]:
    deadline = time.time() + max(wait_seconds, 0.0)
    while True:
        try:
            return load_state_and_message(path, row_selector)
        except FileNotFoundError:
            if time.time() >= deadline:
                print(f"session log not found: {path}; using standby snapshot", file=sys.stderr)
                return build_standby_state_and_message()
            time.sleep(0.25)
        except RuntimeError as exc:
            if "empty session log" not in str(exc):
                raise
            if time.time() >= deadline:
                print(f"session log empty: {path}; using standby snapshot", file=sys.stderr)
                return build_standby_state_and_message()
            time.sleep(0.25)


def _print_processing_summary(processing: dict[str, Any]) -> None:
    status = str(processing.get("status") or "")
    reason = str(processing.get("reason") or "")
    wake_word = dict(processing.get("wake_word") or {})
    route_decision = dict(processing.get("route_decision") or {})
    bundle = dict(processing.get("bundle") or {})
    output_debug = dict(processing.get("output_debug") or {})
    output_event = dict(((output_debug.get("output_lifecycle") or {}).get("event") or {}))
    llm_sidecar = dict(((output_debug.get("voice_pipeline_log") or {}).get("llm_sidecar") or {}))
    llm_result = dict((((bundle.get("llm_explainer") or {}).get("result")) or {}))

    print(f"processing status={status} reason={reason}")
    if wake_word:
        print(
            "wake_word "
            f"status={wake_word.get('status')} "
            f"reason={wake_word.get('reason')} "
            f"matched={wake_word.get('matched_phrase')!r}"
        )
    if route_decision:
        print(
            "route "
            f"lane={route_decision.get('lane')} "
            f"query_kind={route_decision.get('query_kind')} "
            f"reason={route_decision.get('reason')} "
            f"llm_eligible={route_decision.get('llm_sidecar_eligible')}"
        )
    if llm_sidecar or llm_result:
        print(
            "llm_sidecar "
            f"status={llm_sidecar.get('status') or llm_result.get('status')} "
            f"backend={llm_sidecar.get('backend_name') or llm_result.get('backend_name')} "
            f"fallback_reason={llm_sidecar.get('fallback_reason') or llm_result.get('fallback_reason')} "
            f"used={llm_sidecar.get('used')}"
        )
    if output_event:
        print(
            "output "
            f"event_type={output_event.get('event_type')} "
            f"action_code={output_event.get('action_code')} "
            f"text={output_event.get('speak_text')!r}"
        )


class _ControlChannel:
    def __init__(self) -> None:
        self._commands: "queue.Queue[str]" = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._reader_loop, name="voice-loop-control", daemon=True)
        self._thread.start()

    def poll_command(self) -> str | None:
        try:
            return self._commands.get_nowait()
        except queue.Empty:
            return None

    def _reader_loop(self) -> None:
        while True:
            try:
                command = input().strip().lower()
            except EOFError:
                return
            except KeyboardInterrupt:
                self._commands.put("q")
                return
            if command in {"q", "quit", "exit", "r", "reload"}:
                self._commands.put(command)


def _is_privacy_violation(message: str) -> bool:
    lowered = message.lower()
    return "privacy_violation" in lowered or "tcc" in lowered


def _is_downlink_playback_active() -> bool:
    snapshot = load_voice_meter_snapshot()
    if bool(snapshot.get("playback_active")):
        return True
    updated_at_ms = int(snapshot.get("updated_at_ms") or 0)
    if updated_at_ms <= 0:
        return False
    now_ms = int(time.time() * 1000)
    if now_ms - updated_at_ms > 350:
        return False
    level = float(snapshot.get("amplitude_level") or 0.0)
    peak = float(snapshot.get("amplitude_peak") or 0.0)
    beat = float(snapshot.get("beat_pulse") or 0.0)
    return level >= 0.03 or peak >= 0.06 or beat >= 0.06


def _play_sidecar_tts(*, processing: dict[str, Any], client: VoiceSidecarClient) -> bool:
    output_event = dict((((processing.get("output_debug") or {}).get("output_lifecycle") or {}).get("event") or {}))
    if not output_event:
        return False
    speak_text = str(output_event.get("speak_text") or "").strip()
    if not speak_text:
        return False
    metadata = dict(output_event.get("metadata") or {})
    default_persona = get_default_persona()
    try:
        result = client.play_tts(
            request=TtsRenderRequest(
                text=speak_text,
                persona_id=str(metadata.get("persona_id") or default_persona.persona_id),
                voice_profile_id=str(metadata.get("voice_profile_id") or default_persona.voice_profile_id),
                audio_format="pcm_s16le",
            )
        )
    except VoiceSidecarClientError as exc:
        print(f"sidecar_tts status=error reason={exc}")
        return False
    print(
        "sidecar_tts "
        f"status={result.status} "
        f"player={result.player_binary} "
        f"bytes={result.audio_bytes}"
    )
    return result.status == "played"


if __name__ == "__main__":
    raise SystemExit(main())
