"""Bounded Ollama assistance for optional, non-tactical personality speech."""
from __future__ import annotations

from collections import Counter
from concurrent.futures import Future
from dataclasses import dataclass
from hashlib import sha256
import json
import os
import re
import time
from typing import Protocol
from urllib.parse import urlsplit

from .cancellable_http import request_json
from .task_runtime import BoundedTaskExecutor, TaskCancelled, TaskCapacityExceeded, TaskContext


MODES = frozenset({"disabled", "shadow", "enabled"})
SUPPORTED_OPPORTUNITIES = frozenset({"overtake", "fastest_lap", "finish"})
_TONES = frozenset({"", "calm", "firm", "concerned", "excited"})
_FRAGMENTS = (
    "(?:干得|做得|跑得)(?:漂亮|不错|很好|利落|扎实|干净)"
    "|(?:这下|刚才那下)(?:很|真|够)(?:漂亮|利落|干净)"
    "|(?:配合|节奏)(?:不错|很好|挺好)"
    "|漂亮|有默契|这配合，我喜欢|今天配合得不错|这下很有默契"
)
_FRAGMENT = re.compile(rf"(?:{_FRAGMENTS})[。！]?")
_FAMILIAR_FRAGMENTS = frozenset({"有默契", "这配合，我喜欢", "今天配合得不错", "这下很有默契"})


@dataclass(frozen=True)
class PersonalityLlmRequest:
    request_id: str
    decision_ref: str
    opportunity: str
    stage: int
    tone: str = ""


@dataclass(frozen=True)
class PersonalityLlmResult:
    request_id: str
    status: str
    fragment: str | None
    elapsed_ms: float
    decision_ref: str | None = None


class PersonalityLlmProvider(Protocol):
    def generate(self, request: PersonalityLlmRequest, context: TaskContext) -> dict:
        ...


class DisabledProvider:
    def generate(self, request: PersonalityLlmRequest, context: TaskContext) -> dict:
        return {}


class OllamaProvider:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "qwen3:8b",
                 *, seed: int | None = None):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or parsed.username is not None or parsed.password is not None):
            raise ValueError("invalid_personality_ollama_url")
        # Accessing .port validates the port as well as the URL syntax.
        if parsed.port == 0 or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./:-]{0,127}", model):
            raise ValueError("invalid_personality_ollama_configuration")
        self.url = base_url.rstrip("/") + "/api/generate"
        self.model = model
        self.seed = seed

    def request_body(self, request: PersonalityLlmRequest) -> dict:
        # Do not send snapshot IDs, driver text, or telemetry to the model.
        wire_ref = sha256(request.decision_ref.encode("utf-8")).hexdigest()[:16]
        opportunity = {"overtake": "超车", "fastest_lap": "最快圈", "finish": "完赛"}[request.opportunity]
        register = ("简洁客观", "简短肯定", "熟悉的队友", "默契的队友")[request.stage]
        tone = {"calm": "平静", "firm": "坚定", "concerned": "关怀", "excited": "兴奋"}.get(request.tone, register)
        familiar = "也可以说配合不错、有默契。" if request.stage >= 2 else "措辞保持客观。"
        prompt = (
            f"你是车队电台阿斯拉达。情境：{opportunity}。关系风格：{register}。语气：{tone}。"
            "只写一句短的中文肯定语，可接在已有电台播报后。可以选用："
            f"干得/做得/跑得 ＋ 漂亮/不错/很好/利落/扎实/干净。{familiar}"
            "不要复述事件，不说数字、人名、驾驶指令、比赛事实，不加引号和说明。"
            f"原样返回 decision_ref {wire_ref}，并在 fragment 里填短句。"
        )
        options = {"temperature": 0.3, "num_ctx": 1024, "num_predict": 64}
        if self.seed is not None:
            options["seed"] = self.seed
        return {
            "model": self.model, "prompt": prompt, "stream": False, "think": False,
            "format": {"type": "object", "properties": {
                "decision_ref": {"type": "string", "enum": [wire_ref]},
                "fragment": {"type": "string"},
            }, "required": ["decision_ref", "fragment"], "additionalProperties": False},
            "options": options,
        }

    def generate(self, request: PersonalityLlmRequest, context: TaskContext) -> dict:
        body = self.request_body(request)
        wire_ref = body["format"]["properties"]["decision_ref"]["enum"][0]
        result = request_json(
            self.url, method="POST", context=context, timeout_ms=context.remaining() * 1000,
            max_response_bytes=16_384, propagate_budget=False, body=body,
        )
        if isinstance(result, dict) and result.get("done") is True and isinstance(result.get("response"), str):
            try:
                payload = json.loads(result["response"])
                if isinstance(payload, dict) and payload.get("decision_ref") == wire_ref:
                    payload["decision_ref"] = request.decision_ref
                    return payload
            except ValueError:
                pass
        return {}


@dataclass(frozen=True)
class _Pending:
    request: PersonalityLlmRequest
    context: TaskContext
    future: Future
    created: float


class PersonalityLlm:
    """Called by one output owner; the worker communicates via its future only."""

    def __init__(self, mode="disabled", provider: PersonalityLlmProvider | None = None, timeout_ms=600):
        if mode not in MODES or type(timeout_ms) is not int or not 1 <= timeout_ms <= 600:
            raise ValueError("invalid_personality_llm_configuration")
        self.mode = mode
        self.provider = provider if provider is not None else DisabledProvider()
        if mode != "disabled" and isinstance(self.provider, DisabledProvider):
            self.mode = "disabled"
        self.timeout_ms = timeout_ms
        self._executor = BoundedTaskExecutor(max_workers=1)
        self._pending: _Pending | None = None
        self._closed = False
        self._counts: Counter = Counter()

    @classmethod
    def from_env(cls) -> PersonalityLlm:
        mode = os.getenv("ASURADA_PERSONALITY_LLM_MODE", "disabled").strip().lower()
        if mode == "disabled":
            return cls()
        try:
            if mode not in MODES:
                raise ValueError("invalid_personality_llm_mode")
            return cls(
                mode=mode,
                timeout_ms=int(os.getenv("ASURADA_PERSONALITY_LLM_TIMEOUT_MS", "600")),
                provider=OllamaProvider(
                    os.getenv("ASURADA_PERSONALITY_LLM_BASE_URL", "http://127.0.0.1:11434"),
                    os.getenv("ASURADA_PERSONALITY_LLM_MODEL", "qwen3:8b"),
                ),
            )
        except ValueError:
            disabled = cls()
            disabled._counts["invalid_config"] += 1
            return disabled

    @property
    def pending(self) -> bool:
        return self._pending is not None

    def start(self, request: PersonalityLlmRequest) -> bool:
        if self.mode == "disabled" or self._closed:
            return False
        if (not isinstance(request.request_id, str) or not 1 <= len(request.request_id) <= 256
                or not isinstance(request.opportunity, str) or request.opportunity not in SUPPORTED_OPPORTUNITIES
                or type(request.stage) is not int or not 0 <= request.stage <= 3
                or not isinstance(request.tone, str) or request.tone not in _TONES
                or not isinstance(request.decision_ref, str) or not 1 <= len(request.decision_ref) <= 256):
            self._counts["ineligible"] += 1
            return False
        if self._pending is not None:
            self._counts["busy"] += 1
            return False
        created = time.monotonic()
        context = TaskContext(request.request_id, created + self.timeout_ms / 1000)

        def generate():
            payload = self.provider.generate(request, context)
            return payload, time.monotonic()

        try:
            future = self._executor.submit(context, generate)
        except TaskCapacityExceeded:
            self._counts["busy"] += 1
            return False
        except (RuntimeError, TimeoutError):
            self._counts["error"] += 1
            return False
        self._pending = _Pending(request, context, future, created)
        self._counts["started"] += 1
        return True

    def poll(self) -> PersonalityLlmResult | None:
        pending = self._pending
        if pending is None:
            return None
        now = time.monotonic()
        if not pending.future.done() and now < pending.context.deadline:
            return None
        self._pending = None
        fragment = None
        try:
            if not pending.future.done():
                pending.context.cancel()
                raise TimeoutError
            payload, now = pending.future.result()
            if now >= pending.context.deadline:
                raise TimeoutError
            fragment = validate_fragment(payload, pending.request)
            status = "ok" if fragment else "invalid"
        except TimeoutError:
            status = "timeout"
        except TaskCancelled:
            status = "cancelled"
        except Exception:
            status = "error"
        self._counts[status] += 1
        return PersonalityLlmResult(pending.request.request_id, status, fragment,
                                    (now - pending.created) * 1000, pending.request.decision_ref)

    def cancel(self) -> None:
        if self._pending is not None:
            self._pending.context.cancel()
            self._pending = None
            self._counts["cancelled"] += 1

    def close(self) -> None:
        self._closed = True
        self.cancel()

    def snapshot(self) -> dict:
        return {"mode": self.mode, "pending": self.pending, "counts": dict(self._counts)}


def validate_fragment(payload: object, request: PersonalityLlmRequest) -> str | None:
    if (not isinstance(payload, dict) or payload.keys() != {"decision_ref", "fragment"}
            or payload["decision_ref"] != request.decision_ref or not isinstance(payload["fragment"], str)):
        return None
    fragment = payload["fragment"].strip()
    if len(fragment) > 16 or not _FRAGMENT.fullmatch(fragment):
        return None
    if request.stage < 2 and fragment.rstrip("。！") in _FAMILIAR_FRAGMENTS:
        return None
    return fragment if fragment.endswith(("。", "！")) else fragment + "。"
