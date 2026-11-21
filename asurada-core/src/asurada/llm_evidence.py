"""Machine-checkable evidence boundary; does not claim to verify all prose."""
from __future__ import annotations
import math
from typing import Any


class InvalidLlmEvidence(ValueError):
    pass


def evidence_fields(summary: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    aliases: dict[str, list[str]] = {}
    def visit(value: Any, path: str) -> None:
        if value is None or value == '' or (isinstance(value, float) and not math.isfinite(value)):
            return
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, f'{path}.{key}' if path else key)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f'{path}.{index}')
            return
        result[path] = value
        aliases.setdefault(path.rsplit('.', 1)[-1], []).append(path)
    for section in ('state_snapshot', 'strategy_snapshot'):
        visit(summary.get(section, {}), section)
    for alias, paths in aliases.items():
        if len(paths) == 1:
            result[alias] = result[paths[0]]
    primary = summary.get('strategy_snapshot', {}).get('primary_message')
    if isinstance(primary, dict) and primary.get('code'):
        result['primary_message'] = primary
        result['strategy_snapshot.primary_message'] = primary
    return result


def validate_evidence(response: dict[str, Any], *, summary: dict[str, Any], mode: str, request_id: str) -> None:
    metadata = response.get('metadata') or {}
    if metadata.get('request_id') not in (None, request_id):
        raise InvalidLlmEvidence('request_binding_mismatch')
    if mode == 'companion_chat':
        return
    if metadata.get('payload_mode') == 'plain_text_fallback':
        raise InvalidLlmEvidence('racing_requires_structured_response')
    refs = response.get('reason_fields') or []
    if response['status'] == 'answerable' and not refs:
        raise InvalidLlmEvidence('missing_evidence')
    available = evidence_fields(summary)
    if any(ref not in available for ref in refs):
        raise InvalidLlmEvidence('unavailable_evidence')
