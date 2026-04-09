from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .llm_explainer import LlmExplainerRequest, LlmExplainerResult


VOICE_SIDECAR_PROTOCOL_VERSION = "v1"


@dataclass(frozen=True)
class VoiceSidecarEnvelope:
    protocol_version: str
    message_type: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VoiceSidecarHealth:
    status: str
    sidecar_name: str
    llm_backend_name: str
    tts_available: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AsrTranscribeRequest:
    audio_base64: str
    audio_format: str = "wav"
    locale: str = "zh-CN"
    prompt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AsrTranscribeResponse:
    status: str
    transcript_text: str
    confidence: float | None
    started_at_ms: int
    ended_at_ms: int
    locale: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AsrRealtimeStartRequest:
    locale: str = "zh-CN"
    audio_format: str = "pcm"
    prompt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AsrRealtimeChunk:
    sequence_id: int
    audio_base64: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AsrRealtimeEndRequest:
    started_at_ms: int
    ended_at_ms: int
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AsrRealtimeStarted:
    status: str
    request_id: str
    locale: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AsrRealtimePartial:
    transcript_text: str
    locale: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AsrRealtimeFinal:
    status: str
    transcript_text: str
    confidence: float | None
    started_at_ms: int
    ended_at_ms: int
    locale: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TtsRenderRequest:
    text: str
    persona_id: str
    voice_profile_id: str
    audio_format: str = "pcm_s16le"
    sample_rate_hz: int = 16_000
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TtsRenderResponse:
    status: str
    audio_base64: str | None
    audio_format: str
    sample_rate_hz: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TtsStreamStart:
    status: str
    audio_format: str
    sample_rate_hz: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TtsAudioFrame:
    sequence_id: int
    audio_base64: str
    audio_bytes: int
    is_final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TtsStreamEnd:
    status: str
    total_frames: int
    total_audio_bytes: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_explainer_request_envelope(request: LlmExplainerRequest) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="explainer_request",
        payload=request.to_dict(),
    )


def parse_explainer_request_envelope(payload: dict[str, Any]) -> LlmExplainerRequest:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "explainer_request")
    body = envelope.payload
    return LlmExplainerRequest(
        interaction_session_id=str(body.get("interaction_session_id") or ""),
        turn_id=str(body.get("turn_id") or ""),
        request_id=str(body.get("request_id") or ""),
        query_kind=str(body.get("query_kind") or ""),
        normalized_query_text=str(body.get("normalized_query_text") or ""),
        route_reason=str(body.get("route_reason") or ""),
        timeout_ms=int(body.get("timeout_ms") or 0),
        state_summary=dict(body.get("state_summary") or {}),
        interaction_mode=str(body.get("interaction_mode") or "racing_explainer"),
        metadata=dict(body.get("metadata") or {}),
    )


def build_explainer_result_envelope(result: LlmExplainerResult) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="explainer_result",
        payload=result.to_dict(),
    )


def parse_explainer_result_envelope(payload: dict[str, Any]) -> LlmExplainerResult:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "explainer_result")
    body = envelope.payload
    return LlmExplainerResult(
        status=str(body.get("status") or ""),
        backend_name=str(body.get("backend_name") or ""),
        llm_used=bool(body.get("llm_used")),
        response=dict(body.get("response") or {}) if body.get("response") is not None else None,
        fallback_reason=(None if body.get("fallback_reason") is None else str(body.get("fallback_reason"))),
        duration_ms=int(body.get("duration_ms") or 0),
        metadata=dict(body.get("metadata") or {}),
    )


def build_health_envelope(health: VoiceSidecarHealth) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="health",
        payload=health.to_dict(),
    )


def build_asr_transcribe_request_envelope(request: AsrTranscribeRequest) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="asr_transcribe_request",
        payload=request.to_dict(),
    )


def parse_asr_transcribe_request_envelope(payload: dict[str, Any]) -> AsrTranscribeRequest:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "asr_transcribe_request")
    body = envelope.payload
    prompt_value = body.get("prompt")
    return AsrTranscribeRequest(
        audio_base64=str(body.get("audio_base64") or ""),
        audio_format=str(body.get("audio_format") or "wav"),
        locale=str(body.get("locale") or "zh-CN"),
        prompt=(None if prompt_value is None else str(prompt_value)),
        metadata=dict(body.get("metadata") or {}),
    )


def build_asr_transcribe_response_envelope(response: AsrTranscribeResponse) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="asr_transcribe_response",
        payload=response.to_dict(),
    )


def parse_asr_transcribe_response_envelope(payload: dict[str, Any]) -> AsrTranscribeResponse:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "asr_transcribe_response")
    body = envelope.payload
    confidence_value = body.get("confidence")
    try:
        confidence = None if confidence_value is None else float(confidence_value)
    except (TypeError, ValueError):
        confidence = None
    return AsrTranscribeResponse(
        status=str(body.get("status") or ""),
        transcript_text=str(body.get("transcript_text") or ""),
        confidence=confidence,
        started_at_ms=int(body.get("started_at_ms") or 0),
        ended_at_ms=int(body.get("ended_at_ms") or 0),
        locale=str(body.get("locale") or "zh-CN"),
        metadata=dict(body.get("metadata") or {}),
    )


def build_asr_realtime_start_request_envelope(request: AsrRealtimeStartRequest) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="asr_realtime_start_request",
        payload=request.to_dict(),
    )


def parse_asr_realtime_start_request_envelope(payload: dict[str, Any]) -> AsrRealtimeStartRequest:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "asr_realtime_start_request")
    body = envelope.payload
    prompt_value = body.get("prompt")
    return AsrRealtimeStartRequest(
        locale=str(body.get("locale") or "zh-CN"),
        audio_format=str(body.get("audio_format") or "pcm"),
        prompt=(None if prompt_value is None else str(prompt_value)),
        metadata=dict(body.get("metadata") or {}),
    )


def build_asr_realtime_chunk_envelope(chunk: AsrRealtimeChunk) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="asr_realtime_chunk",
        payload=chunk.to_dict(),
    )


def parse_asr_realtime_chunk_envelope(payload: dict[str, Any]) -> AsrRealtimeChunk:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "asr_realtime_chunk")
    body = envelope.payload
    return AsrRealtimeChunk(
        sequence_id=int(body.get("sequence_id") or 0),
        audio_base64=str(body.get("audio_base64") or ""),
        metadata=dict(body.get("metadata") or {}),
    )


def build_asr_realtime_end_request_envelope(request: AsrRealtimeEndRequest) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="asr_realtime_end_request",
        payload=request.to_dict(),
    )


def parse_asr_realtime_end_request_envelope(payload: dict[str, Any]) -> AsrRealtimeEndRequest:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "asr_realtime_end_request")
    body = envelope.payload
    return AsrRealtimeEndRequest(
        started_at_ms=int(body.get("started_at_ms") or 0),
        ended_at_ms=int(body.get("ended_at_ms") or 0),
        status=str(body.get("status") or ""),
        metadata=dict(body.get("metadata") or {}),
    )


def build_asr_realtime_started_envelope(event: AsrRealtimeStarted) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="asr_realtime_started",
        payload=event.to_dict(),
    )


def parse_asr_realtime_started_envelope(payload: dict[str, Any]) -> AsrRealtimeStarted:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "asr_realtime_started")
    body = envelope.payload
    return AsrRealtimeStarted(
        status=str(body.get("status") or ""),
        request_id=str(body.get("request_id") or ""),
        locale=str(body.get("locale") or "zh-CN"),
        metadata=dict(body.get("metadata") or {}),
    )


def build_asr_realtime_partial_envelope(event: AsrRealtimePartial) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="asr_realtime_partial",
        payload=event.to_dict(),
    )


def parse_asr_realtime_partial_envelope(payload: dict[str, Any]) -> AsrRealtimePartial:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "asr_realtime_partial")
    body = envelope.payload
    return AsrRealtimePartial(
        transcript_text=str(body.get("transcript_text") or ""),
        locale=str(body.get("locale") or "zh-CN"),
        metadata=dict(body.get("metadata") or {}),
    )


def build_asr_realtime_final_envelope(event: AsrRealtimeFinal) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="asr_realtime_final",
        payload=event.to_dict(),
    )


def parse_asr_realtime_final_envelope(payload: dict[str, Any]) -> AsrRealtimeFinal:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "asr_realtime_final")
    body = envelope.payload
    confidence_value = body.get("confidence")
    try:
        confidence = None if confidence_value is None else float(confidence_value)
    except (TypeError, ValueError):
        confidence = None
    return AsrRealtimeFinal(
        status=str(body.get("status") or ""),
        transcript_text=str(body.get("transcript_text") or ""),
        confidence=confidence,
        started_at_ms=int(body.get("started_at_ms") or 0),
        ended_at_ms=int(body.get("ended_at_ms") or 0),
        locale=str(body.get("locale") or "zh-CN"),
        metadata=dict(body.get("metadata") or {}),
    )


def build_tts_render_request_envelope(request: TtsRenderRequest) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="tts_render_request",
        payload=request.to_dict(),
    )


def parse_tts_render_request_envelope(payload: dict[str, Any]) -> TtsRenderRequest:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "tts_render_request")
    body = envelope.payload
    return TtsRenderRequest(
        text=str(body.get("text") or ""),
        persona_id=str(body.get("persona_id") or ""),
        voice_profile_id=str(body.get("voice_profile_id") or ""),
        audio_format=str(body.get("audio_format") or "pcm_s16le"),
        sample_rate_hz=int(body.get("sample_rate_hz") or 16_000),
        metadata=dict(body.get("metadata") or {}),
    )


def build_tts_render_response_envelope(response: TtsRenderResponse) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="tts_render_response",
        payload=response.to_dict(),
    )


def build_tts_stream_start_envelope(event: TtsStreamStart) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="tts_stream_start",
        payload=event.to_dict(),
    )


def parse_tts_stream_start_envelope(payload: dict[str, Any]) -> TtsStreamStart:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "tts_stream_start")
    body = envelope.payload
    return TtsStreamStart(
        status=str(body.get("status") or ""),
        audio_format=str(body.get("audio_format") or "pcm_s16le"),
        sample_rate_hz=int(body.get("sample_rate_hz") or 16_000),
        metadata=dict(body.get("metadata") or {}),
    )


def build_tts_audio_frame_envelope(event: TtsAudioFrame) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="tts_audio_frame",
        payload=event.to_dict(),
    )


def parse_tts_audio_frame_envelope(payload: dict[str, Any]) -> TtsAudioFrame:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "tts_audio_frame")
    body = envelope.payload
    return TtsAudioFrame(
        sequence_id=int(body.get("sequence_id") or 0),
        audio_base64=str(body.get("audio_base64") or ""),
        audio_bytes=int(body.get("audio_bytes") or 0),
        is_final=bool(body.get("is_final")),
        metadata=dict(body.get("metadata") or {}),
    )


def build_tts_stream_end_envelope(event: TtsStreamEnd) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=VOICE_SIDECAR_PROTOCOL_VERSION,
        message_type="tts_stream_end",
        payload=event.to_dict(),
    )


def parse_tts_stream_end_envelope(payload: dict[str, Any]) -> TtsStreamEnd:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "tts_stream_end")
    body = envelope.payload
    return TtsStreamEnd(
        status=str(body.get("status") or ""),
        total_frames=int(body.get("total_frames") or 0),
        total_audio_bytes=int(body.get("total_audio_bytes") or 0),
        metadata=dict(body.get("metadata") or {}),
    )


def parse_tts_render_response_envelope(payload: dict[str, Any]) -> TtsRenderResponse:
    envelope = _coerce_envelope(payload)
    _ensure_message_type(envelope, "tts_render_response")
    body = envelope.payload
    return TtsRenderResponse(
        status=str(body.get("status") or ""),
        audio_base64=(None if body.get("audio_base64") is None else str(body.get("audio_base64"))),
        audio_format=str(body.get("audio_format") or "pcm_s16le"),
        sample_rate_hz=int(body.get("sample_rate_hz") or 16_000),
        metadata=dict(body.get("metadata") or {}),
    )


def _coerce_envelope(payload: dict[str, Any]) -> VoiceSidecarEnvelope:
    return VoiceSidecarEnvelope(
        protocol_version=str(payload.get("protocol_version") or ""),
        message_type=str(payload.get("message_type") or ""),
        payload=dict(payload.get("payload") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def _ensure_message_type(envelope: VoiceSidecarEnvelope, expected: str) -> None:
    if envelope.protocol_version != VOICE_SIDECAR_PROTOCOL_VERSION:
        raise ValueError(f"unsupported_voice_sidecar_protocol:{envelope.protocol_version}")
    if envelope.message_type != expected:
        raise ValueError(f"unexpected_voice_sidecar_message_type:{envelope.message_type}")
