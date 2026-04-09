from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .macos_audio_capture import MacOSAudioCapture, MacOSAudioCaptureResult


_DEFAULT_INITIAL_PROMPT = (
    "阿斯拉达 后车差距 前车差距 整体形势 为什么现在不进攻 DRS ERS "
    "轮胎 进站 车损 安全车 陪我聊天"
)


@dataclass(frozen=True)
class OpenAsrConfig:
    model_size_or_path: str = "tiny"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "zh"
    beam_size: int = 5
    vad_filter: bool = False
    initial_prompt: str = _DEFAULT_INITIAL_PROMPT
    keep_audio_files: bool = False


@dataclass(frozen=True)
class OpenAsrResult:
    status: str
    transcript_text: str
    confidence: float | None
    started_at_ms: int
    ended_at_ms: int
    locale: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OpenAsrBackend:
    def transcribe_file(self, *, audio_file_path: str) -> OpenAsrResult:
        raise NotImplementedError


class FasterWhisperOpenAsrBackend(OpenAsrBackend):
    def __init__(self, config: OpenAsrConfig | None = None) -> None:
        self.config = config or self.from_env().config
        self._model = None

    @classmethod
    def from_env(cls) -> "FasterWhisperOpenAsrBackend":
        return cls(
            OpenAsrConfig(
                model_size_or_path=os.getenv("ASURADA_OPEN_ASR_MODEL_SIZE", "tiny"),
                device=os.getenv("ASURADA_OPEN_ASR_DEVICE", "cpu"),
                compute_type=os.getenv("ASURADA_OPEN_ASR_COMPUTE_TYPE", "int8"),
                language=os.getenv("ASURADA_OPEN_ASR_LANGUAGE", "zh"),
                beam_size=int(os.getenv("ASURADA_OPEN_ASR_BEAM_SIZE", "5")),
                vad_filter=os.getenv("ASURADA_OPEN_ASR_VAD_FILTER", "0").lower() in {"1", "true", "yes", "on"},
                initial_prompt=os.getenv("ASURADA_OPEN_ASR_INITIAL_PROMPT", _DEFAULT_INITIAL_PROMPT),
                keep_audio_files=os.getenv("ASURADA_OPEN_ASR_KEEP_AUDIO", "0").lower() in {"1", "true", "yes", "on"},
            )
        )

    @classmethod
    def env_ready(cls) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def transcribe_file(self, *, audio_file_path: str) -> OpenAsrResult:
        model = self._load_model()
        start_ms = int(time.time() * 1000)
        segments, info = model.transcribe(
            audio=audio_file_path,
            language=self.config.language,
            beam_size=max(self.config.beam_size, 1),
            vad_filter=self.config.vad_filter,
            condition_on_previous_text=False,
            initial_prompt=self.config.initial_prompt or None,
            temperature=0.0,
        )
        segment_list = list(segments)
        transcript_text = " ".join((segment.text or "").strip() for segment in segment_list).strip()
        end_ms = int(time.time() * 1000)
        return OpenAsrResult(
            status="recognized" if transcript_text else "no_speech",
            transcript_text=transcript_text,
            confidence=float(getattr(info, "language_probability", 0.0) or 0.0),
            started_at_ms=start_ms,
            ended_at_ms=end_ms,
            locale=self.config.language,
            metadata={
                "backend": "faster_whisper",
                "model_size_or_path": self.config.model_size_or_path,
                "device": self.config.device,
                "compute_type": self.config.compute_type,
                "language": getattr(info, "language", self.config.language),
                "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
                "segment_count": len(segment_list),
                "duration_s": getattr(info, "duration", None),
                "audio_file_path": audio_file_path,
            },
        )

    def _load_model(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self.config.model_size_or_path,
            device=self.config.device,
            compute_type=self.config.compute_type,
        )
        return self._model


class OpenAsrRecognizer:
    """One-shot microphone capture + local ASR transcription."""

    def __init__(
        self,
        *,
        audio_capture: MacOSAudioCapture | None = None,
        backend: OpenAsrBackend | None = None,
    ) -> None:
        self.audio_capture = audio_capture or MacOSAudioCapture.from_env()
        self.backend = backend or FasterWhisperOpenAsrBackend.from_env()

    @classmethod
    def from_env(cls) -> "OpenAsrRecognizer":
        return cls()

    @classmethod
    def env_ready(cls) -> bool:
        return MacOSAudioCapture.env_ready() and FasterWhisperOpenAsrBackend.env_ready()

    def listen_once(self) -> OpenAsrResult:
        capture = self.audio_capture.capture_once()
        if capture.status not in {"recorded", "recorded_timeout"}:
            return OpenAsrResult(
                status=capture.status,
                transcript_text="",
                confidence=None,
                started_at_ms=capture.started_at_ms,
                ended_at_ms=capture.ended_at_ms,
                locale="zh",
                metadata={
                    "backend": "open_asr_capture_passthrough",
                    "capture": capture.to_dict(),
                },
            )

        audio_path = capture.audio_file_path
        try:
            result = self.backend.transcribe_file(audio_file_path=audio_path)
            return OpenAsrResult(
                status=result.status,
                transcript_text=result.transcript_text,
                confidence=result.confidence,
                started_at_ms=capture.started_at_ms,
                ended_at_ms=max(capture.ended_at_ms, result.ended_at_ms),
                locale=result.locale,
                metadata={
                    **result.metadata,
                    "capture": capture.to_dict(),
                },
            )
        finally:
            keep_audio = bool(getattr(getattr(self.backend, "config", None), "keep_audio_files", False))
            if audio_path and not keep_audio:
                try:
                    Path(audio_path).unlink(missing_ok=True)
                except OSError:
                    pass
