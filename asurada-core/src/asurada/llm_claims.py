"""Versioned numeric claims, computed from whitelisted canonical evidence."""
from decimal import Decimal, ROUND_HALF_UP
import math
import re
from .llm_evidence import InvalidLlmEvidence, evidence_fields

CLAIM_UNITS = {
    'state_snapshot.gap_ahead_s': 's', 'state_snapshot.gap_behind_s': 's',
    'state_snapshot.ers_pct': '%', 'state_snapshot.fuel_laps_remaining': 'lap',
    'state_snapshot.speed_kph': 'km/h', 'state_snapshot.lap_number': 'lap',
    'state_snapshot.total_laps': 'lap', 'state_snapshot.player_position': 'position',
    'state_snapshot.tyre.wear_pct': '%', 'state_snapshot.tyre.age_laps': 'lap',
}
UNIT_TEXT = {'s':'秒', '%':'%', 'lap':'圈', 'km/h':'公里/小时', 'position':'名'}
TOKEN = re.compile(r'\{\{([a-z][a-z0-9_]{0,31})\}\}')
QUANTITY = re.compile(r'\d|百分之|(?<![上下每这那前后])[零〇一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟]+(?:点[零〇一二三四五六七八九]+)?\s*(?:秒|毫秒|圈|米|公里|档|挡|度|名|成|倍|%)')


def render_claims(response, *, summary, request_id):
    claims = response.get('claims') or []
    text = (response.get('metadata') or {}).get('claim_template', response['answer_text'])
    if not isinstance(text,str):
        raise InvalidLlmEvidence('invalid_claim_template')
    if not claims:
        if '{{' in text or '}}' in text:
            raise InvalidLlmEvidence('claim_placeholder_without_claim')
        if text != response['answer_text'] or QUANTITY.search(text):
            raise InvalidLlmEvidence('numeric_answer_requires_claims')
        return text
    if not isinstance(request_id,str) or not request_id or (response.get('metadata') or {}).get('request_id') != request_id:
        raise InvalidLlmEvidence('claims_require_request_binding')
    if len(claims) > 8:
        raise InvalidLlmEvidence('claim_count_limit')
    available = evidence_fields(summary)
    rendered = {}
    refs_used = set()
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) != {'id','operation','refs','value','unit','precision'}:
            raise InvalidLlmEvidence('invalid_claim_schema')
        name, refs, operation = claim['id'], claim['refs'], claim['operation']
        if not isinstance(name,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}',name) or name in rendered:
            raise InvalidLlmEvidence('invalid_claim_id')
        arity = {'value':1,'difference':2}.get(operation) if isinstance(operation,str) else None
        if not isinstance(refs,list) or arity is None or len(refs)!=arity or not all(isinstance(r,str) for r in refs):
            raise InvalidLlmEvidence('invalid_claim_operation')
        unit = claim['unit']
        if any(ref not in CLAIM_UNITS or ref not in available or CLAIM_UNITS[ref]!=unit for ref in refs):
            raise InvalidLlmEvidence('claim_unit_or_source_mismatch')
        numbers = [available[ref] for ref in refs] + [claim['value']]
        if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) for n in numbers):
            raise InvalidLlmEvidence('claim_requires_finite_numbers')
        precision = claim['precision']
        if isinstance(precision,bool) or not isinstance(precision,int) or not 0<=precision<=3:
            raise InvalidLlmEvidence('invalid_claim_precision')
        values = [Decimal(str(n)) for n in numbers]
        computed = values[0] if operation=='value' else values[0]-values[1]
        quantum = Decimal(1).scaleb(-precision)
        rounded = computed.quantize(quantum, rounding=ROUND_HALF_UP)
        if values[-1] != rounded:
            raise InvalidLlmEvidence('claim_value_mismatch')
        rendered[name] = format(rounded, f'.{precision}f') + UNIT_TEXT[unit]
        refs_used.update(refs)
    if not refs_used.issubset(set(response.get('reason_fields') or [])):
        raise InvalidLlmEvidence('claim_sources_not_declared')
    tokens = TOKEN.findall(text)
    if set(tokens)!=set(rendered):
        raise InvalidLlmEvidence('claim_placeholder_mismatch')
    remaining = TOKEN.sub('', text)
    if '{{' in remaining or '}}' in remaining or QUANTITY.search(remaining):
        raise InvalidLlmEvidence('unbound_numeric_text')
    result = TOKEN.sub(lambda match: rendered[match.group(1)],text)
    if response['answer_text'] not in (text, result):
        raise InvalidLlmEvidence('claim_rendered_text_mismatch')
    return result
