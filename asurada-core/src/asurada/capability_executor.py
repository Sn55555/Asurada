"""Bounded read-only tool execution with explicit task and snapshot scope."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
import threading
import time
import math
from typing import Any, Callable
from .tool_contract import validate_tool_payload
from .assessment import assess_domain, snapshot_id
from .capability_definitions import CAPABILITIES
from .capabilities.history import ReviewScope
from .models import SessionState
from .task_runtime import BoundedTaskExecutor, TaskContext

_TOOL_WORKERS = BoundedTaskExecutor(2)


class CapabilityExecutor:
    def __init__(self, *, context: TaskContext, permissions: frozenset[str], max_calls: int = 8,
                 historical: bool = False, wall_clock: Callable[[], float] = time.time,
                 current_snapshot_id: Callable[[], str] | None = None, review_store=None, driver_id=None) -> None:
        if max_calls < 1:
            raise ValueError('max_calls must be positive')
        self.context, self.permissions, self.max_calls = context, permissions, max_calls
        self.historical, self.wall_clock = historical, wall_clock
        self.current_snapshot_id = current_snapshot_id
        self.review_store, self.driver_id = review_store, driver_id
        self._calls = 0
        self._lock = threading.Lock()

    def execute(self, name: str, *, state: SessionState | ReviewScope, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self.context.remaining()
        with self._lock:
            if self._calls >= self.max_calls:
                raise ValueError('tool_call_limit')
            self._calls += 1
        spec = CAPABILITIES.get(name)
        if spec is None or spec.handler_name is None:
            raise ValueError('not_a_read_tool')
        permission = 'read_session_history' if self.historical else spec.permission
        if permission not in self.permissions:
            raise PermissionError(permission)
        if spec.lane != 'analysis_tool' and arguments is not None and (not isinstance(arguments, dict) or arguments):
            raise ValueError('unexpected_tool_arguments')
        snapshot = deepcopy(state)
        if isinstance(snapshot,ReviewScope) and (not self.historical or spec.lane!='analysis_tool'):
            raise ValueError('review_scope_requires_historical_analysis_tool')
        binding = snapshot.identity() if isinstance(snapshot,ReviewScope) else snapshot_id(snapshot)
        self._validate_snapshot(snapshot, binding, spec.freshness_ms)
        child = TaskContext(self.context.task_id, min(self.context.deadline, time.monotonic()+spec.deadline_ms/1000), self.context.cancellation)
        declared = spec.tool_schema()
        validate_tool_payload({} if arguments is None else arguments, declared['input_schema'])
        owned_arguments = deepcopy(arguments)
        def invoke():
            if spec.lane == 'analysis_tool':
                value = spec.invoke(state=snapshot,arguments=owned_arguments,review_store=self.review_store,
                                    driver_id=self.driver_id,context=child)
                validate_tool_payload(value, declared['output_schema'])
                expected_scope = {'session_uid': snapshot.session_uid, 'epoch': snapshot.session_epoch, 'track': snapshot.track}
                if value['scope'] != expected_scope:
                    raise ValueError('tool_output_scope_mismatch')
                child.remaining()
                return value
            primary = snapshot.decision_record.actions[0] if snapshot.decision_record is not None and snapshot.decision_record.snapshot_id == binding and snapshot.decision_record.actions else None
            value = spec.invoke(state=snapshot, primary_message=primary, schema_metadata={})
            if not isinstance(value, (tuple, list)) or len(value) != 2:
                raise ValueError('invalid_tool_result')
            validate_tool_payload({'speak_text': value[0], 'action_code': value[1]}, declared['output_schema'])
            child.remaining()
            return value
        result = child.wait(_TOOL_WORKERS.submit(child, invoke))
        self._validate_snapshot(snapshot, binding, spec.freshness_ms)
        if spec.lane == 'analysis_tool':
            return {'tool':name,'capability_version':spec.version,'task_id':self.context.task_id,
                    'snapshot_id':None if isinstance(snapshot,ReviewScope) else binding,
                    'scope_id':binding if isinstance(snapshot,ReviewScope) else None,
                    'session_uid':snapshot.session_uid,'session_epoch':snapshot.session_epoch,
                    'historical':True,'data':result}
        text, code = result
        if not isinstance(text,str) or not isinstance(code,str):
            raise ValueError('invalid_tool_result')
        return {'tool':name, 'capability_version':spec.version, 'task_id':self.context.task_id,
                'snapshot_id':binding,'session_uid':snapshot.session_uid,'session_epoch':snapshot.session_epoch,
                'historical':self.historical,'speak_text':text,'action_code':code,
                'assessment':asdict(assess_domain(snapshot))}

    def _validate_snapshot(self, state: SessionState, binding: str, freshness_ms: int) -> None:
        self.context.remaining()
        if not self.historical:
            age = self.wall_clock()*1000-state.source_timestamp_ms
            if not math.isfinite(age) or age < 0 or age > freshness_ms:
                raise ValueError('snapshot_not_current')
            if self.current_snapshot_id is not None and self.current_snapshot_id() != binding:
                raise ValueError('snapshot_superseded')
