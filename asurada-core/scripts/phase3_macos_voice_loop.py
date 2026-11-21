from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
import queue
import select
import sys
import threading
import time
from pathlib import Path
from typing import Any

from asurada.live_speech import live_speech_client
from asurada.speech_driver import SpeechOutputDriver
from asurada.audio_io import AudioFormat
from asurada.decode import decode_snapshot
from asurada.macos_speech import MacOSSpeechRecognizer
from asurada.models import SessionState, StrategyMessage
from asurada.open_asr import OpenAsrRecognizer
from asurada.persona_registry import get_default_persona
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_meter import load_voice_meter_snapshot
from asurada.voice_sidecar_asr import (
    DoubaoRealtimeAsrRecognizer,
    VoiceSidecarAsrRecognizer,
    VoiceSidecarRealtimeAsrRecognizer,
)
from asurada.voice_turn import VoiceTurn
from asurada.voice_interrupt import VoiceTurnInterruption
from asurada.published_session import PublishedSessionProbe
from asurada.recognition_runtime import listen_with_context
from asurada.recognition_pump import RecognitionPump
from asurada.task_runtime import TaskCancelled, TaskCapacityExceeded
from asurada.radio_understanding import RaceRadio
from asurada.wake_word import WakeWordGate


_DEFAULT_SESSION_LOG = Path(__file__).resolve().parents[1] / "runtime_logs" / "session_log.jsonl"
_DEFAULT_RECOGNIZER_BACKEND = (
    "voice_sidecar_realtime_asr"
    if VoiceSidecarRealtimeAsrRecognizer.env_ready()
    else "doubao_realtime_asr"
    if DoubaoRealtimeAsrRecognizer.env_ready()
    else "voice_sidecar_asr"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a macOS voice-loop smoke test against one snapshot.")
    parser.add_argument(
        "--session-log",
        default=str(_DEFAULT_SESSION_LOG),
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
        "--spoken-interrupt",
        action="store_true",
        help="Keep recognition active during answers; use headphones or echo-isolated input. Requires a wake phrase before stop/cancel.",
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
        help="Require the shared speech service to use the sidecar TTS backend.",
    )
    parser.add_argument("--race-dialogue", action="store_true", help="Use local Ollama for contextual racing turns.")
    args = parser.parse_args()

    try:
        voice_output = live_speech_client()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"共享语音服务不可用，请先启动 --live-udp 或独立 speech_service：{exc}", file=sys.stderr)
        return 2
    if args.use_sidecar_tts and voice_output.health()["backend"] != "VoiceSidecarSpeechBackend":
        print("共享语音服务未配置 sidecar TTS；请在服务启动时使用 --sidecar-tts。", file=sys.stderr)
        return 2

    wake_phrases = tuple(args.wake_phrases or ["阿斯拉达", "asurada"])
    wake_word_gate = WakeWordGate(
        enabled=not args.disable_wake_word,
        phrases=wake_phrases,
        activation_window_ms=args.wake_window_ms,
    )

    session_log_path = Path(args.session_log).expanduser().resolve()
    state, primary_message = wait_for_state_and_message(
        session_log_path,
        args.row,
        wait_seconds=args.wait_for_live_seconds,
    )
    coordinator = VoiceInputCoordinator(
        wake_word_gate=wake_word_gate,
        race_radio=RaceRadio(latest=lambda: wait_for_state_and_message(session_log_path, args.row, wait_seconds=0))
            if args.race_dialogue else None,
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
    scope_probe = (PublishedSessionProbe(session_log_path.parent / 'latest_snapshot.json')
                   if args.row == 'latest' and session_log_path.name == 'session_log.jsonl' else None)
    with SpeechOutputDriver(voice_output), VoiceTurnInterruption(voice_output, scope_probe=scope_probe) as interruption, ExitStack() as listeners:
        downlink_cooldown_ms = max(int(os.getenv("ASURADA_VOICE_DOWNLINK_COOLDOWN_MS") or "900"), 0)
        downlink_resume_after_ms = 0
        downlink_was_active = False

        print("macOS voice loop")
        if args.race_dialogue:
            print("race_dialogue=enabled model=qwen3:4b (local Ollama)")
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
        if getattr(voice_output,"externally_driven",False):
            print(f"shared_speech backend={voice_output.health()['backend']}")
        else:
            print(f"sidecar_tts enabled={args.use_sidecar_tts}")
        if args.manual:
            print("mode=manual commands: Enter to listen, s + Enter to stop, r to reload, q to quit")
        else:
            print("mode=continuous controls: s + Enter to stop, r + Enter to reload, q + Enter to quit")
            print("continuous listening is active; say the wake phrase and query in one sentence.")

        pump = None

        def stop_turn():
            if pump is not None:
                pump.invalidate()
            result = interruption.stop(state_ref['state'])
            event = (result.get('output_lifecycle') or {}).get('event') or {}
            print(f"stop_requested event={event.get('event_type')} metadata={event.get('metadata')}")
        if args.spoken_interrupt:
            probe = scope_probe or (lambda: (state_ref['state'].session_uid, state_ref['state'].session_epoch))
            pump = RecognitionPump(recognizer, wake_phrases=wake_phrases, on_stop=stop_turn, scope_probe=probe).start()
            listeners.callback(pump.close)
            print("spoken_interrupt=enabled; exact wake phrase + stop/cancel; echo cancellation is not provided by this mode")
        control = _ControlChannel(on_stop=stop_turn, manual=args.manual)
        control.start()
        listeners.callback(control.close)

        while True:
            if args.manual:
                command = control.wait_command()
                if command in {"q", "quit", "exit"}:
                    return 0
                if command in {"r", "reload"}:
                    state, primary_message = wait_for_state_and_message(
                        session_log_path,
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
                        session_log_path,
                        args.row,
                        wait_seconds=args.wait_for_live_seconds,
                    )
                    state_ref["state"] = state
                    state_ref["primary_message"] = primary_message
                    print(f"reloaded track={state.track} lap={state.lap_number}/{state.total_laps} P{state.player.position}")
                    continue

            if not args.no_auto_refresh:
                previous_state = state
                state, primary_message = wait_for_state_and_message(
                    session_log_path,
                    args.row,
                    wait_seconds=args.wait_for_live_seconds,
                )
                state_ref["state"] = state
                state_ref["primary_message"] = primary_message
                _print_state_transition(previous_state, state)

            if not _bind_current_voice_session(voice_output, state):
                print("telemetry_not_current: 等待新遥测，请恢复驾驶后再次开始聆听。")
                if not args.manual:
                    time.sleep(max(args.loop_idle_ms, 250) / 1000.0)
                continue
            now_ms = int(time.time() * 1000)
            downlink_active = voice_output.is_playing() or _is_downlink_playback_active()
            if downlink_was_active and not downlink_active:
                downlink_resume_after_ms = now_ms + downlink_cooldown_ms
            downlink_was_active = downlink_active
            if pump is None and (downlink_active or now_ms < downlink_resume_after_ms):
                if not args.manual:
                    time.sleep(max(args.loop_idle_ms, 0) / 1000.0)
                continue

            print("listening...")
            turn_context = interruption.begin(state=state)
            _publish_microphone(voice_output, "listening", 30)
            try:
                result = pump.next_result(turn_context) if pump is not None else listen_with_context(recognizer, turn_context)
            except KeyboardInterrupt:
                return 0
            except (TaskCancelled, TaskCapacityExceeded) as exc:
                print(f"recognizer_cancel_or_busy={type(exc).__name__} reason={interruption.cancel_reason or 'user_stop_or_previous_capture_exiting'}")
                time.sleep(max(args.loop_idle_ms, 0) / 1000.0)
                continue
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
            finally:
                _publish_microphone(voice_output, "idle", 30)
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
            if args.row == "latest":
                state, primary_message = wait_for_state_and_message(session_log_path, args.row, wait_seconds=0)
                state_ref.update(state=state, primary_message=primary_message)
            processing = coordinator.process_completed_turn(
                state=state,
                turn=turn,
                voice_output=interruption.output_for(turn_context),
                primary_message=primary_message,
                render=not args.use_sidecar_tts,
                context=turn_context,
            )
            _print_processing_summary(processing.to_dict())
            if processing.status == 'cancelled':
                print(f"voice_turn_cancel_reason={interruption.cancel_reason or 'user_stop_or_turn_replaced'}")
            if args.show_processing_json:
                print(json.dumps(processing.to_dict(), ensure_ascii=False, indent=2))
            if processing.status == "wake_armed":
                print("wake word armed, waiting for follow-up query...")
            if processing.status == "ignored":
                print("ignored: wake word required")
            if not args.manual:
                time.sleep(max(args.loop_idle_ms, 0) / 1000.0)


def load_state_and_message(path: Path, row_selector: str) -> tuple[SessionState, StrategyMessage | None]:
    latest_path = path.parent / "latest_snapshot.json"
    if row_selector == "latest" and path.name == "session_log.jsonl" and latest_path.exists():
        row = json.loads(latest_path.read_text(encoding="utf-8"))
    else:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            raise RuntimeError(f"empty session log: {path}")
        row = rows[-1] if row_selector == "latest" else rows[int(row_selector)]
    state = decode_snapshot(row)
    if state.decision_record is not None:
        actions = state.decision_record.actions
        return state, actions[0] if actions else None
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


def _print_state_transition(previous: SessionState, current: SessionState) -> None:
    previous_key = (previous.track, previous.lap_number, previous.total_laps, previous.player.position)
    current_key = (current.track, current.lap_number, current.total_laps, current.player.position)
    if previous_key == current_key:
        return
    print(
        "snapshot "
        f"track={current.track} "
        f"lap={current.lap_number}/{current.total_laps} "
        f"position=P{current.player.position} "
        f"speed={round(current.player.speed_kph, 1)}"
    )


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


def _publish_microphone(voice_output, state, ttl_s):
    try:
        voice_output.call("report_microphone", {"state": state, "ttl_s": ttl_s})
    except (AttributeError, OSError, RuntimeError, TimeoutError):
        pass


def _bind_current_voice_session(voice_output, state):
    try:
        voice_output.bind_session(state)
        return True
    except (RuntimeError, ValueError) as exc:
        if 'latest_snapshot_not_current' not in str(exc):
            raise
        return False


class _ControlChannel:
    def __init__(self, *, on_stop=None, manual=False, input_fd=None) -> None:
        self._commands: "queue.Queue[str]" = queue.Queue(maxsize=8)
        self.on_stop = on_stop
        self.manual = manual
        self._input_fd = input_fd
        self._closed = threading.Event()
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

    def wait_command(self):
        return self._commands.get()

    def accept(self, command):
        if command in {'s', 'stop', 'q', 'quit', 'exit'} and self.on_stop is not None:
            try:
                self.on_stop()
            except Exception as exc:
                print(f'stop_unconfirmed={type(exc).__name__}: {exc}', file=sys.stderr)
        if command in {'s', 'stop'}:
            return
        if command in {'q', 'quit', 'exit'}:
            while self.poll_command() is not None:
                pass
        if command in {'q', 'quit', 'exit', 'r', 'reload'} or self.manual:
            try:
                self._commands.put_nowait(command)
            except queue.Full:
                pass

    def close(self):
        self._closed.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(1.5)

    def _reader_loop(self) -> None:
        # Never leave a daemon blocked inside Python's buffered stdin at shutdown.
        fd = self._input_fd if self._input_fd is not None else sys.stdin.fileno()
        pending = b""
        while not self._closed.is_set():
            try:
                readable, _, _ = select.select([fd], [], [], .1)
                if not readable:
                    continue
                chunk = os.read(fd, 1024)
            except (OSError, ValueError):
                self.accept('q')
                return
            if not chunk:
                self.accept('q')
                return
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                command = line.decode('utf-8', errors='replace').strip().lower()
                self.accept(command)
                if command in {'q', 'quit', 'exit'}:
                    return
            if len(pending) > 4096:
                pending = b""


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


if __name__ == "__main__":
    raise SystemExit(main())
