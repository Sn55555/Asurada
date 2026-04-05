from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .asr_fast import FastIntentASR, FastIntentResult, KeywordFastIntentASR
from .models import SessionState, StrategyMessage
from .output import ConsoleVoiceOutput
from .voice_nlu import VoiceQueryBundle, build_voice_query_bundle
from .voice_turn import VoiceTurn


CONTROL_QUERY_KINDS = {"repeat_last", "stop", "cancel"}


@dataclass(frozen=True)
class VoiceInputProcessingResult:
    """End-to-end result of one completed voice turn."""

    status: str
    reason: str
    fast_intent: dict[str, Any]
    voice_turn: dict[str, Any]
    bundle: dict[str, Any] | None = None
    output_debug: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VoiceInputCoordinator:
    """Bridge completed voice turns into the existing interaction/output path."""

    def __init__(self, *, fast_intent_asr: FastIntentASR | None = None) -> None:
        self.fast_intent_asr = fast_intent_asr or KeywordFastIntentASR()

    def process_completed_turn(
        self,
        *,
        state: SessionState,
        turn: VoiceTurn,
        voice_output: ConsoleVoiceOutput,
        primary_message: StrategyMessage | None = None,
        render: bool = True,
    ) -> VoiceInputProcessingResult:
        fast_intent = self.fast_intent_asr.recognize_turn(turn)
        if fast_intent.status != "matched" or fast_intent.query_kind is None:
            return VoiceInputProcessingResult(
                status="fallback",
                reason="fast_intent_unmatched",
                fast_intent=fast_intent.to_dict(),
                voice_turn=turn.to_dict(),
            )

        bundle = build_voice_query_bundle(
            state=state,
            voice_turn=turn,
            fast_intent=fast_intent,
        )
        if fast_intent.query_kind in CONTROL_QUERY_KINDS:
            return VoiceInputProcessingResult(
                status="control_unwired",
                reason="control_query_execution_not_wired",
                fast_intent=fast_intent.to_dict(),
                voice_turn=turn.to_dict(),
                bundle=bundle.to_dict(),
            )

        output_debug = voice_output.emit_voice_query_bundle(
            state=state,
            bundle=bundle,
            primary_message=primary_message,
            render=render,
        )
        return VoiceInputProcessingResult(
            status="spoken",
            reason="query_response_emitted",
            fast_intent=fast_intent.to_dict(),
            voice_turn=turn.to_dict(),
            bundle=bundle.to_dict(),
            output_debug=output_debug,
        )
