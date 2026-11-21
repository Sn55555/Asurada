"""Private envelope/result contracts and the queue serialization guard."""
from __future__ import annotations
from dataclasses import dataclass, field
import time
from functools import wraps
from typing import Any, TYPE_CHECKING
from .interaction import OutputLifecycleEvent, SpeechJob

if TYPE_CHECKING:
    from .attack_opportunity import PlayingForecast


@dataclass
class _SpeechEnvelope:
    job: SpeechJob
    interaction_input_event: dict[str, Any]
    task_handle: dict[str, Any]
    created_monotonic: float = field(default_factory=time.monotonic)
    start_guard: Any = field(default=None, repr=False)
    repeat_target: SpeechJob | None = field(default=None, repr=False)
    playing_forecast: PlayingForecast | None = field(default=None, repr=False)

    rear_observation: tuple[float, float] | None = field(default=None, repr=False)

    @property
    def rank(self) -> tuple[int, int]:
        job = self.job
        if job.source_kind == "personality_optional" or job.action_code == "ATTACK_OUTCOME":
            band = 0
        elif job.source_kind == "query_response":
            band = 2
        elif job.source_kind == "strategy_broadcast":
            band = strategy_speech_band(job.action_code, job.metadata.get("interrupt"))
        else:
            band = 3
        return band, job.priority

    @property
    def dedup_key(self) -> tuple:
        job = self.job
        scope = job.metadata.get("session_scope")
        if job.source_kind in {"query_response", "personality_optional"}:
            return scope, job.source_kind, job.request_id
        subject = job.metadata.get("semantic_subject", job.metadata.get("target"))
        return scope, job.source_kind, job.action_code, subject


CAUTION_SPEECH_CODES = frozenset({"FRONT_LOAD", "TYRE_DAMAGE", "TYRE_WEAR_ALERT", "FRONT_WING_DAMAGE", "LOW_FUEL", "ERS_LOW"})
EPISODE_RECOVERY = {
    "DEFEND_WINDOW": ("defend_state", "clear"),
    "DYNAMICS_UNSTABLE": ("dynamics_state", "stable"),
}
EPISODE_CUES = frozenset((*EPISODE_RECOVERY, "TYRE_DAMAGE", "TYRE_WEAR_ALERT", "LOCAL_YELLOW"))


def strategy_speech_band(code: str, interrupt: bool = False) -> int:
    if code in {"LOCAL_YELLOW", "SAFETY_CAR", "DYNAMICS_UNSTABLE", "RED_FLAG"}:
        return 4
    if interrupt or code in {"BOX_WINDOW", "BOX_NOW", "PIT_NOW", "DEFEND_WINDOW", "ATTACK_WINDOW"}:
        return 3
    return 1


@dataclass
class _OutputProcessingResult:
    lifecycle_event: OutputLifecycleEvent
    event_envelope: _SpeechEnvelope | None
    completed_output_event: OutputLifecycleEvent | None = None
    completed_envelope: _SpeechEnvelope | None = None
    completed_event_published: bool = False
    cancelled_output_event: OutputLifecycleEvent | None = None
    cancelled_envelope: _SpeechEnvelope | None = None


def _serialized(function):
    @wraps(function)
    def call(self, *args, **kwargs):
        with self._output_lock:
            return function(self, *args, **kwargs)
    return call

