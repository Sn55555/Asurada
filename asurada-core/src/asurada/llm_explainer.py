from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from copy import deepcopy
import os
import shlex
import time
from typing import Any, Protocol
from .cancellable_http import request_json

from .task_runtime import BoundedTaskExecutor, LLM_EXECUTOR, TaskContext, TaskCancelled, TaskCapacityExceeded
from .capture_process import command_json_text
from .conversation_context import ConversationContext
from .llm_evidence import InvalidLlmEvidence, evidence_fields, validate_evidence
from .llm_response_schema import LlmResponse, coerce_llm_response
from .llm_claims import CLAIM_UNITS
from .answer_policy import render_racing_response
from .models import SessionState, StrategyMessage
from .persona_registry import build_llm_persona_instructions, get_default_persona, get_persona
from .state_summary_for_llm import LlmStateSummary, build_state_summary_for_llm
from .transcript_router import TranscriptRouteDecision


@dataclass(frozen=True)
class LlmExplainerRequest:
    interaction_session_id: str
    turn_id: str
    request_id: str
    query_kind: str
    normalized_query_text: str
    route_reason: str
    timeout_ms: int
    state_summary: dict[str, Any]
    interaction_mode: str = "racing_explainer"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LlmExplainerResult:
    status: str
    backend_name: str
    llm_used: bool
    response: dict[str, Any] | None
    fallback_reason: str | None
    duration_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LlmExplainerBackend(Protocol):
    name: str

    def explain(self, request: LlmExplainerRequest) -> dict[str, Any]:
        ...


class NullLlmExplainerBackend:
    name = "null_llm_explainer"

    def explain(self, request: LlmExplainerRequest) -> dict[str, Any]:
        return {
            "status": "unsupported",
            "answer_text": "",
            "confidence": 0.0,
            "reason_fields": [],
            "requires_confirmation": False,
            "metadata": {
                "reason": "llm_sidecar_disabled",
                "query_kind": request.query_kind,
            },
        }


class CommandLlmExplainerBackend:
    name = "command_llm_explainer"

    def __init__(self, *, command: tuple[str, ...], name: str | None = None) -> None:
        if not command:
            raise ValueError("command_llm_explainer_requires_command")
        self.command = tuple(command)
        self.name = name or self.name

    @classmethod
    def from_env(cls) -> "CommandLlmExplainerBackend":
        command_text = str(os.getenv("ASURADA_LLM_SIDECAR_COMMAND") or "").strip()
        if not command_text:
            raise ValueError("ASURADA_LLM_SIDECAR_COMMAND is required for command backend")
        return cls(command=tuple(shlex.split(command_text)))

    @classmethod
    def env_ready(cls) -> bool:
        return bool(str(os.getenv("ASURADA_LLM_SIDECAR_COMMAND") or "").strip())

    def explain(self, request: LlmExplainerRequest) -> dict[str, Any]:
        return self.explain_with_context(request, context=TaskContext.start(request.request_id, request.timeout_ms))

    def explain_with_context(self, request: LlmExplainerRequest, *, context: TaskContext) -> dict[str, Any]:
        payload = command_json_text(self.command, timeout_s=max(float(request.timeout_ms),1.)/1000.,
            context=context, input_bytes=json.dumps(request.to_dict(),ensure_ascii=False,allow_nan=False).encode('utf-8')).strip()
        if not payload:
            raise RuntimeError("llm_command_returned_empty_stdout")
        return json.loads(payload)


class OpenAiResponsesLlmExplainerBackend:
    name = "openai_responses_llm_explainer"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        organization: str | None = None,
        project: str | None = None,
        persona_id: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.organization = organization
        self.project = project
        self.persona_id = get_persona(persona_id).persona_id

    @classmethod
    def from_env(cls) -> "OpenAiResponsesLlmExplainerBackend":
        api_key = str(os.getenv("ASURADA_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for openai backend")
        model = str(os.getenv("ASURADA_OPENAI_MODEL") or "gpt-5.2-mini").strip()
        base_url = str(os.getenv("ASURADA_OPENAI_BASE_URL") or "https://api.openai.com/v1").strip()
        organization = str(os.getenv("OPENAI_ORGANIZATION") or "").strip() or None
        project = str(os.getenv("OPENAI_PROJECT") or "").strip() or None
        persona_id = str(os.getenv("ASURADA_LLM_PERSONA_ID") or "").strip() or None
        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            organization=organization,
            project=project,
            persona_id=persona_id,
        )

    @classmethod
    def env_ready(cls) -> bool:
        return bool(str(os.getenv("ASURADA_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip())

    def explain(self, request: LlmExplainerRequest) -> dict[str, Any]:
        return self.explain_with_context(request, context=TaskContext.start(request.request_id, request.timeout_ms))

    def explain_with_context(self, request: LlmExplainerRequest, *, context: TaskContext) -> dict[str, Any]:
        payload = self._post_responses(request=request, context=context)
        return self._extract_llm_payload(payload)

    def _post_responses(self, *, request: LlmExplainerRequest, context: TaskContext) -> dict[str, Any]:
        body = {
            "model": self.model,
            "instructions": self._instructions(request),
            "input": self._input_text(request),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "asurada_llm_sidecar_response",
                    "strict": True,
                    "schema": _LLM_RESPONSE_JSON_SCHEMA,
                }
            },
        }
        return request_json(f"{self.base_url}/responses", method="POST", body=body,
            context=context, timeout_ms=request.timeout_ms, headers=self._headers(),
            propagate_budget=False, trust_env=True, max_redirects=3)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        if self.project:
            headers["OpenAI-Project"] = self.project
        return headers

    def _instructions(self, request: LlmExplainerRequest) -> str:
        return build_llm_persona_instructions(
            self.persona_id,
            interaction_mode=request.interaction_mode,
        ) + "\n比赛解释的 reason_fields 必须从 available_evidence_refs 选择实际依据；没有依据时返回 unsupported 或 needs_clarification。数值使用 claims 声明，answer_text 用 {{id}} 占位，程序自动添加数值和单位。claims 每项包含 id、operation(value 或 difference)、refs、value、unit、precision(0至3)，difference 按 refs[0]-refs[1] 计算。metadata.request_id 回传输入 request_id。没有数值时 claims 为空。needs_clarification 的 claims 必须为空，metadata.clarification_field 可为 query_scope、lap_selection、segment_selection，程序根据该字段生成澄清问题；不得在澄清中输出比赛结论。"

    def _input_text(self, request: LlmExplainerRequest) -> str:
        return json.dumps(
            {
                "task": request.interaction_mode,
                "query_kind": request.query_kind,
                "interaction_mode": request.interaction_mode,
                "normalized_query_text": request.normalized_query_text,
                "route_reason": request.route_reason,
                "state_summary": request.state_summary,
                "available_evidence_refs": sorted(evidence_fields(request.state_summary)),
                "numeric_claim_units": CLAIM_UNITS,
                "request_id": request.request_id,
                "metadata": request.metadata,
            },
            ensure_ascii=False,
        )

    def _extract_llm_payload(self, response_payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(response_payload.get("output_text"), str) and response_payload["output_text"].strip():
            return _extract_json_or_text_payload(str(response_payload["output_text"]))

        for item in response_payload.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []) or []:
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return _extract_json_or_text_payload(text)

        raise RuntimeError("openai_response_missing_json_text")


class DoubaoArkResponsesLlmExplainerBackend(OpenAiResponsesLlmExplainerBackend):
    name = "doubao_ark_responses_llm_explainer"

    @classmethod
    def from_env(cls) -> "DoubaoArkResponsesLlmExplainerBackend":
        api_key = str(
            os.getenv("ASURADA_DOUBAO_API_KEY")
            or os.getenv("ARK_API_KEY")
            or ""
        ).strip()
        if not api_key:
            raise ValueError("ASURADA_DOUBAO_API_KEY or ARK_API_KEY is required for doubao backend")
        model = str(
            os.getenv("ASURADA_DOUBAO_MODEL")
            or os.getenv("ASURADA_DOUBAO_ENDPOINT_ID")
            or ""
        ).strip()
        if not model:
            raise ValueError(
                "ASURADA_DOUBAO_MODEL or ASURADA_DOUBAO_ENDPOINT_ID is required for doubao backend"
            )
        base_url = str(
            os.getenv("ASURADA_DOUBAO_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3"
        ).strip()
        persona_id = str(os.getenv("ASURADA_LLM_PERSONA_ID") or "").strip() or None
        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            organization=None,
            project=None,
            persona_id=persona_id,
        )

    @classmethod
    def env_ready(cls) -> bool:
        api_key = str(
            os.getenv("ASURADA_DOUBAO_API_KEY")
            or os.getenv("ARK_API_KEY")
            or ""
        ).strip()
        model = str(
            os.getenv("ASURADA_DOUBAO_MODEL")
            or os.getenv("ASURADA_DOUBAO_ENDPOINT_ID")
            or ""
        ).strip()
        return bool(api_key and model)


class DoubaoArkChatCompletionsLlmExplainerBackend(DoubaoArkResponsesLlmExplainerBackend):
    name = "doubao_ark_chat_completions_llm_explainer"

    def explain(self, request: LlmExplainerRequest) -> dict[str, Any]:
        return self.explain_with_context(request, context=TaskContext.start(request.request_id, request.timeout_ms))

    def explain_with_context(self, request: LlmExplainerRequest, *, context: TaskContext) -> dict[str, Any]:
        payload = self._post_chat_completions(request=request, context=context)
        return self._extract_chat_completions_payload(payload)

    def _post_chat_completions(self, *, request: LlmExplainerRequest, context: TaskContext) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._instructions(request)},
                {"role": "user", "content": self._input_text(request)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "asurada_llm_sidecar_response",
                    "strict": True,
                    "schema": _LLM_RESPONSE_JSON_SCHEMA,
                },
            },
        }
        return request_json(f"{self.base_url}/chat/completions", method="POST", body=body,
            context=context, timeout_ms=request.timeout_ms, headers=self._headers(),
            propagate_budget=False, trust_env=True, max_redirects=3)

    def _extract_chat_completions_payload(self, response_payload: dict[str, Any]) -> dict[str, Any]:
        for choice in response_payload.get("choices", []) or []:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return _extract_json_or_text_payload(content)
            if isinstance(content, list):
                fragments: list[str] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        fragments.append(text)
                if fragments:
                    return _extract_json_or_text_payload("".join(fragments))
        raise RuntimeError("doubao_chat_response_missing_json_text")


class DoubaoArkLlmExplainerBackend:
    name = "doubao_ark_llm_explainer"

    def __init__(
        self,
        *,
        primary: DoubaoArkResponsesLlmExplainerBackend | DoubaoArkChatCompletionsLlmExplainerBackend,
        fallback: DoubaoArkResponsesLlmExplainerBackend | DoubaoArkChatCompletionsLlmExplainerBackend | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    @classmethod
    def from_env(cls) -> "DoubaoArkLlmExplainerBackend":
        mode = str(os.getenv("ASURADA_DOUBAO_API_STYLE") or "auto").strip().lower()
        if mode == "responses":
            return cls(primary=DoubaoArkResponsesLlmExplainerBackend.from_env())
        if mode in {"chat", "chat_completions"}:
            return cls(primary=DoubaoArkChatCompletionsLlmExplainerBackend.from_env())
        return cls(
            primary=DoubaoArkResponsesLlmExplainerBackend.from_env(),
            fallback=DoubaoArkChatCompletionsLlmExplainerBackend.from_env(),
        )

    @classmethod
    def env_ready(cls) -> bool:
        return DoubaoArkResponsesLlmExplainerBackend.env_ready()

    def explain(self, request: LlmExplainerRequest) -> dict[str, Any]:
        return self.explain_with_context(request, context=TaskContext.start(request.request_id, request.timeout_ms))

    def explain_with_context(self, request: LlmExplainerRequest, *, context: TaskContext) -> dict[str, Any]:
        def invoke(backend):
            owned = replace(request, timeout_ms=max(1, int(context.remaining()*1000)))
            contextual = getattr(backend, 'explain_with_context', None)
            return contextual(owned, context=context) if contextual is not None else backend.explain(owned)
        try:
            return invoke(self.primary)
        except Exception as exc:
            if self.fallback is None:
                raise
            if not _should_fallback_from_responses(exc):
                raise
            context.remaining()
            return invoke(self.fallback)


class VoiceSidecarLlmExplainerBackend:
    name = "voice_sidecar_llm_explainer"

    def __init__(self, *, base_url: str, timeout_ms: int = 2500) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_ms = max(int(timeout_ms), 1)

    @classmethod
    def from_env(cls) -> "VoiceSidecarLlmExplainerBackend":
        base_url = str(os.getenv("ASURADA_VOICE_SIDECAR_BASE_URL") or "http://127.0.0.1:8788").strip()
        timeout_ms = int(os.getenv("ASURADA_VOICE_SIDECAR_TIMEOUT_MS") or "2500")
        return cls(base_url=base_url, timeout_ms=timeout_ms)

    @classmethod
    def env_ready(cls) -> bool:
        return bool(str(os.getenv("ASURADA_VOICE_SIDECAR_BASE_URL") or "http://127.0.0.1:8788").strip())

    def explain(self, request: LlmExplainerRequest) -> dict[str, Any]:
        return self.explain_with_context(request, context=TaskContext.start(request.request_id, request.timeout_ms or self.timeout_ms))

    def explain_with_context(self, request: LlmExplainerRequest, *, context: TaskContext) -> dict[str, Any]:
        from .audio_agent_client import VoiceSidecarClient, VoiceSidecarClientConfig

        client = VoiceSidecarClient(
            VoiceSidecarClientConfig(
                base_url=self.base_url,
                timeout_ms=max(request.timeout_ms or self.timeout_ms, 1),
            )
        )
        context.remaining()
        result = client.explain(request=request, timeout_ms=max(request.timeout_ms or self.timeout_ms, 1), context=context)
        context.remaining()
        if result.status == "completed" and result.response is not None:
            return dict(result.response)
        if result.fallback_reason == "llm_timeout":
            raise TimeoutError("voice_sidecar_timeout")
        raise RuntimeError(
            f"voice_sidecar_failed:{result.fallback_reason or result.status}:{result.backend_name}"
        )


class LlmExplainer:
    """Timeout-guarded LLM sidecar wrapper.

    This wrapper is intentionally narrow:
    - only receives explainer-lane requests
    - always returns a schema-coerced response or a structured fallback result
    - never raises backend exceptions to the caller
    """

    def __init__(
        self,
        *,
        backend: LlmExplainerBackend | None = None,
        default_timeout_ms: int = 1800,
        executor: BoundedTaskExecutor | None = None,
    ) -> None:
        self.backend = backend or NullLlmExplainerBackend()
        self.default_timeout_ms = default_timeout_ms
        self.executor = executor or LLM_EXECUTOR

    @classmethod
    def from_env(cls) -> "LlmExplainer":
        return cls(
            backend=resolve_default_llm_explainer_backend(),
            default_timeout_ms=llm_timeout_ms_from_env(),
        )

    def run(
        self,
        *,
        request: LlmExplainerRequest,
        context: TaskContext | None = None,
    ) -> LlmExplainerResult:
        started = time.monotonic()
        request = replace(request, state_summary=deepcopy(request.state_summary), metadata=deepcopy(request.metadata))
        context = context or TaskContext.start(
            request.request_id, request.timeout_ms or self.default_timeout_ms
        )
        try:
            def invoke():
                remaining_ms = max(1, int(context.remaining() * 1000))
                owned_request = replace(request, timeout_ms=remaining_ms, state_summary=deepcopy(request.state_summary))
                contextual = getattr(self.backend, 'explain_with_context', None)
                if contextual is not None:
                    return contextual(owned_request, context=context)
                return self.backend.explain(owned_request)

            payload = context.wait(self.executor.submit(context, invoke))
            response = coerce_llm_response(payload).to_dict()
            validate_evidence(response, summary=request.state_summary, mode=request.interaction_mode, request_id=request.request_id)
            if request.interaction_mode != 'companion_chat':
                template = response['metadata'].get('claim_template', response['answer_text'])
                response['answer_text'] = render_racing_response(response, summary=request.state_summary, request_id=request.request_id)
                if response['claims']:
                    response['metadata']['claim_template'] = template
                    response['metadata']['claims_version'] = 'numeric-claims-v1'
            context.remaining()
            return LlmExplainerResult(
                status="completed",
                backend_name=self.backend.name,
                llm_used=self.backend.name != "null_llm_explainer",
                response=response,
                fallback_reason=None,
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"query_kind": request.query_kind},
            )
        except InvalidLlmEvidence as exc:
            return LlmExplainerResult(
                status="fallback", backend_name=self.backend.name,
                llm_used=True, response=None, fallback_reason="llm_invalid_evidence",
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"query_kind": request.query_kind, "validation_reason": str(exc)},
            )
        except (TaskCancelled, TaskCapacityExceeded) as exc:
            return LlmExplainerResult(
                status="fallback", backend_name=self.backend.name,
                llm_used=False, response=None,
                fallback_reason="llm_cancelled" if isinstance(exc, TaskCancelled) else "llm_overloaded",
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"query_kind": request.query_kind},
            )
        except TimeoutError:
            return LlmExplainerResult(
                status="fallback",
                backend_name=self.backend.name,
                llm_used=self.backend.name != "null_llm_explainer",
                response=None,
                fallback_reason="llm_timeout",
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"query_kind": request.query_kind},
            )
        except Exception as exc:  # pragma: no cover - defensive catch for backend failures
            return LlmExplainerResult(
                status="fallback",
                backend_name=self.backend.name,
                llm_used=self.backend.name != "null_llm_explainer",
                response=None,
                fallback_reason="llm_error",
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={
                    "query_kind": request.query_kind,
                    "error_type": type(exc).__name__,
            },
            )


def _should_fallback_from_responses(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "404",
            "not found",
            "unsupported",
            "responses",
            "doubao_chat_http_error:400",
            "openai_http_error:400",
            "openai_http_error:404",
        )
    )


def _extract_json_or_text_payload(text: str) -> dict[str, Any]:
    normalized = str(text or "").strip()
    if not normalized:
        raise RuntimeError("llm_response_empty_text")

    fenced = normalized
    if fenced.startswith("```"):
        lines = fenced.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        fenced = "\n".join(lines).strip()
    for candidate in (normalized, fenced):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    start = fenced.find("{")
    end = fenced.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(fenced[start : end + 1])
        except json.JSONDecodeError:
            pass

    return {
        "status": "answerable",
        "answer_text": normalized,
        "confidence": 0.55,
        "reason_fields": [],
        "requires_confirmation": False,
        "metadata": {
            "payload_mode": "plain_text_fallback",
        },
    }


def resolve_default_llm_explainer_backend() -> LlmExplainerBackend:
    forced_backend = str(os.getenv("ASURADA_LLM_SIDECAR_BACKEND") or "").strip().lower()
    if forced_backend == "null":
        return NullLlmExplainerBackend()
    if forced_backend == "command":
        try:
            return CommandLlmExplainerBackend.from_env()
        except ValueError:
            return NullLlmExplainerBackend()
    if forced_backend == "openai":
        try:
            return OpenAiResponsesLlmExplainerBackend.from_env()
        except ValueError:
            return NullLlmExplainerBackend()
    if forced_backend in {"voice_sidecar", "http_sidecar"}:
        try:
            return VoiceSidecarLlmExplainerBackend.from_env()
        except ValueError:
            return NullLlmExplainerBackend()
    if forced_backend == "doubao":
        try:
            return DoubaoArkLlmExplainerBackend.from_env()
        except ValueError:
            return NullLlmExplainerBackend()
    if forced_backend in {"doubao_responses", "doubao_ark_responses"}:
        try:
            return DoubaoArkResponsesLlmExplainerBackend.from_env()
        except ValueError:
            return NullLlmExplainerBackend()
    if forced_backend in {"doubao_chat", "doubao_chat_completions"}:
        try:
            return DoubaoArkChatCompletionsLlmExplainerBackend.from_env()
        except ValueError:
            return NullLlmExplainerBackend()
    if CommandLlmExplainerBackend.env_ready():
        try:
            return CommandLlmExplainerBackend.from_env()
        except ValueError:
            return NullLlmExplainerBackend()
    if DoubaoArkResponsesLlmExplainerBackend.env_ready():
        try:
            return DoubaoArkLlmExplainerBackend.from_env()
        except ValueError:
            return NullLlmExplainerBackend()
    if forced_backend in {"voice_sidecar", "http_sidecar"}:
        try:
            return VoiceSidecarLlmExplainerBackend.from_env()
        except ValueError:
            return NullLlmExplainerBackend()
    if OpenAiResponsesLlmExplainerBackend.env_ready():
        try:
            return OpenAiResponsesLlmExplainerBackend.from_env()
        except ValueError:
            return NullLlmExplainerBackend()
    return NullLlmExplainerBackend()


def resolve_embedded_llm_explainer_backend() -> LlmExplainerBackend:
    provider_backend = str(
        os.getenv("ASURADA_VOICE_SIDECAR_PROVIDER_BACKEND")
        or os.getenv("ASURADA_LLM_SIDECAR_PROVIDER_BACKEND")
        or os.getenv("ASURADA_LLM_SIDECAR_BACKEND")
        or ""
    ).strip().lower()

    if provider_backend in {"", "voice_sidecar", "http_sidecar"}:
        if DoubaoArkResponsesLlmExplainerBackend.env_ready():
            return DoubaoArkLlmExplainerBackend.from_env()
        if OpenAiResponsesLlmExplainerBackend.env_ready():
            return OpenAiResponsesLlmExplainerBackend.from_env()
        if CommandLlmExplainerBackend.env_ready():
            return CommandLlmExplainerBackend.from_env()
        return NullLlmExplainerBackend()

    if provider_backend == "null":
        return NullLlmExplainerBackend()
    if provider_backend == "command":
        return CommandLlmExplainerBackend.from_env()
    if provider_backend == "openai":
        return OpenAiResponsesLlmExplainerBackend.from_env()
    if provider_backend == "doubao":
        return DoubaoArkLlmExplainerBackend.from_env()
    if provider_backend in {"doubao_responses", "doubao_ark_responses"}:
        return DoubaoArkResponsesLlmExplainerBackend.from_env()
    if provider_backend in {"doubao_chat", "doubao_chat_completions"}:
        return DoubaoArkChatCompletionsLlmExplainerBackend.from_env()
    raise ValueError(f"unsupported_embedded_llm_backend:{provider_backend}")


def llm_sidecar_enabled_from_env(default: bool = False) -> bool:
    raw = str(os.getenv("ASURADA_LLM_SIDECAR_ENABLED") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def llm_timeout_ms_from_env(default: int = 1800) -> int:
    try:
        return max(int(os.getenv("ASURADA_LLM_SIDECAR_TIMEOUT_MS", str(default))), 1)
    except ValueError:
        return default


_LLM_RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["answerable", "needs_clarification", "unsupported", "unsafe"],
        },
        "answer_text": {"type": "string"},
        "claims": {"type":"array", "items":{"type":"object", "additionalProperties":False,
            "properties":{"id":{"type":"string"}, "operation":{"type":"string","enum":["value","difference"]},
                "refs":{"type":"array","items":{"type":"string"}}, "value":{"type":"number"},
                "unit":{"type":"string","enum":["s","%","lap","km/h","position"]}, "precision":{"type":"integer"}},
            "required":["id","operation","refs","value","unit","precision"]}},
        "confidence": {"type": "number"},
        "reason_fields": {
            "type": "array",
            "items": {"type": "string"},
        },
        "requires_confirmation": {"type": "boolean"},
        "metadata": {
            "type": "object",
            "additionalProperties": True,
        },
    },
    "required": [
        "status",
        "answer_text",
        "claims",
        "confidence",
        "reason_fields",
        "requires_confirmation",
        "metadata",
    ],
}


def build_llm_explainer_request(
    *,
    interaction_session_id: str,
    turn_id: str,
    request_id: str,
    normalized_query_text: str,
    route_decision: TranscriptRouteDecision,
    state: SessionState,
    primary_message: StrategyMessage | None,
    conversation_context: ConversationContext,
    capability_snapshot: dict[str, Any] | None = None,
    timeout_ms: int = 1800,
) -> LlmExplainerRequest:
    if route_decision.lane not in {"explainer", "companion"} or route_decision.query_kind is None:
        raise ValueError("llm_explainer_request_requires_llm_eligible_lane")

    state_summary = build_state_summary_for_llm(
        state=state,
        primary_message=primary_message,
        conversation_context=conversation_context,
        capability_snapshot=capability_snapshot or route_decision.metadata.get("capability_check") or {},
    )
    return LlmExplainerRequest(
        interaction_session_id=interaction_session_id,
        turn_id=turn_id,
        request_id=request_id,
        query_kind=route_decision.query_kind,
        interaction_mode="companion_chat" if route_decision.lane == "companion" else "racing_explainer",
        normalized_query_text=normalized_query_text,
        route_reason=route_decision.reason,
        timeout_ms=timeout_ms,
        state_summary=state_summary.to_dict(),
        metadata={
            "route_decision": route_decision.to_dict(),
            "persona_id": get_default_persona().persona_id,
        },
    )
