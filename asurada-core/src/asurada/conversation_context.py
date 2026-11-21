from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import SessionState, StrategyMessage


@dataclass(frozen=True)
class ConversationRecord:
    request_id: str
    transcript_text: str
    query_kind: str | None
    action_code: str | None
    speak_text: str | None
    timestamp_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConversationContext:
    """Short-horizon conversational memory for follow-up and explanation queries."""

    def __init__(self, *, max_history: int = 6) -> None:
        self._scope: tuple[str, int] | None = None
        self._last_strategy_message: dict[str, Any] | None = None
        self._last_user_query: ConversationRecord | None = None
        self._last_response: ConversationRecord | None = None
        self._strategy_history: deque[dict[str, Any]] = deque(maxlen=max_history)
        self._user_query_history: deque[ConversationRecord] = deque(maxlen=max_history)
        self._response_history: deque[ConversationRecord] = deque(maxlen=max_history)

    def bind(self, state: SessionState) -> None:
        scope = (state.session_uid, state.session_epoch)
        if self._scope is not None and self._scope != scope:
            self._last_strategy_message = None
            self._last_user_query = None
            self._last_response = None
            self._strategy_history.clear()
            self._user_query_history.clear()
            self._response_history.clear()
        self._scope = scope

    def expire_racing(self) -> None:
        """Discard race follow-ups while retaining explicitly scoped companion chat."""
        self._last_strategy_message = None
        self._strategy_history.clear()
        queries = [record for record in self._user_query_history if record.metadata.get("lane") == "companion"]
        responses = [record for record in self._response_history if record.action_code == "QUERY_COMPANION_CHAT"]
        self._user_query_history.clear()
        self._user_query_history.extend(queries)
        self._response_history.clear()
        self._response_history.extend(responses)
        self._last_user_query = queries[-1] if queries else None
        self._last_response = responses[-1] if responses else None

    def observe_strategy_message(self, primary_message: StrategyMessage | None, *, state: SessionState) -> None:
        self.bind(state)
        if primary_message is None:
            return
        self._last_strategy_message = {
            "code": primary_message.code,
            "title": primary_message.title,
            "detail": primary_message.detail,
            "priority": primary_message.priority,
            "track": state.track,
            "lap_number": state.lap_number,
            "session_uid": state.session_uid,
            "timestamp_ms": state.source_timestamp_ms,
        }
        self._strategy_history.append(self._last_strategy_message)

    def observe_user_query(
        self,
        *,
        request_id: str,
        transcript_text: str,
        query_kind: str | None,
        timestamp_ms: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._last_user_query = ConversationRecord(
            request_id=request_id,
            transcript_text=transcript_text,
            query_kind=query_kind,
            action_code=None,
            speak_text=None,
            timestamp_ms=timestamp_ms,
            metadata=metadata or {},
        )
        self._user_query_history.append(self._last_user_query)

    def observe_response(
        self,
        *,
        request_id: str,
        query_kind: str | None,
        action_code: str | None,
        speak_text: str | None,
        timestamp_ms: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record = ConversationRecord(
            request_id=request_id,
            transcript_text="",
            query_kind=query_kind,
            action_code=action_code,
            speak_text=speak_text,
            timestamp_ms=timestamp_ms,
            metadata=metadata or {},
        )
        for index, previous in enumerate(self._response_history):
            if previous.request_id == request_id:
                self._response_history[index] = record
                break
        else:
            self._response_history.append(record)
        self._last_response = self._response_history[-1] if self._response_history else None

    def snapshot(self, *, include_racing: bool = True) -> dict[str, Any]:
        if not include_racing:
            queries = [record.to_dict() for record in self._user_query_history if record.metadata.get("lane") == "companion"]
            responses = [record.to_dict() for record in self._response_history if record.action_code == "QUERY_COMPANION_CHAT"]
            return {"last_strategy_message": None, "recent_strategy_messages": [],
                    "last_user_query": queries[-1] if queries else None, "recent_user_queries": queries,
                    "last_response": responses[-1] if responses else None, "recent_responses": responses}
        return {
            "last_strategy_message": self._last_strategy_message,
            "last_user_query": self._last_user_query.to_dict() if self._last_user_query is not None else None,
            "last_response": self._last_response.to_dict() if self._last_response is not None else None,
            "recent_strategy_messages": [item for item in self._strategy_history],
            "recent_user_queries": [item.to_dict() for item in self._user_query_history],
            "recent_responses": [item.to_dict() for item in self._response_history],
        }

    def last_query_kind(self) -> str | None:
        return None if self._last_user_query is None else self._last_user_query.query_kind

    def last_non_control_query_kind(self) -> str | None:
        for record in reversed(self._user_query_history):
            if record.query_kind not in {None, "repeat_last", "stop", "cancel", "open_fallback"}:
                return record.query_kind
        return None

    def last_strategy_code(self) -> str | None:
        if self._last_strategy_message is None:
            return None
        return str(self._last_strategy_message.get("code") or "")

    def last_strategy_detail(self) -> str | None:
        if self._last_strategy_message is None:
            return None
        return str(self._last_strategy_message.get("detail") or "")
