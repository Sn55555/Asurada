"""Validate the bounded schema subset used by the capability registry.

This is intentionally not a general JSON Schema implementation. Unknown schema
keywords fail closed so extending a declaration requires extending validation.
"""

from .limits import TOOL_PAYLOAD_MAX_BYTES
import json
import math

KEYWORDS = frozenset({'type', 'properties', 'required', 'additionalProperties',
    'exclusiveMinimum', 'items', 'minItems', 'maxItems', 'uniqueItems', 'minimum', 'maximum',
    'minLength', 'maxLength', 'enum', 'const', 'default'})


def validate_tool_payload(value, schema, *, max_bytes=TOOL_PAYLOAD_MAX_BYTES):
    try:
        _validate_schema(schema, 0)
        _validate(value, schema, 0)
        size = 0
        for chunk in json.JSONEncoder(allow_nan=False, ensure_ascii=False).iterencode(value):
            size += len(chunk.encode('utf-8'))
            if size > max_bytes:
                raise ValueError('tool_payload_too_large')
    except (TypeError, OverflowError, RecursionError) as exc:
        raise ValueError('invalid_tool_payload') from exc


def _validate_schema(schema, depth):
    if depth > 32 or not isinstance(schema, dict) or set(schema) - KEYWORDS:
        raise ValueError('unsupported_tool_schema')
    if 'additionalProperties' in schema and type(schema['additionalProperties']) is not bool:
        raise ValueError('unsupported_tool_schema')
    properties = schema.get('properties', {})
    if not isinstance(properties, dict):
        raise ValueError('unsupported_tool_schema')
    for child in properties.values():
        _validate_schema(child, depth + 1)
    if 'items' in schema:
        _validate_schema(schema['items'], depth + 1)


def _validate(value, schema, depth):
    if depth > 32 or not isinstance(schema, dict) or set(schema) - KEYWORDS:
        raise ValueError('unsupported_tool_schema')
    if type(value) not in (dict, list, str, int, float, bool, type(None)):
        raise ValueError('tool_payload_not_json')
    if type(value) is float and not math.isfinite(value):
        raise ValueError('tool_payload_nonfinite')
    kind = schema.get('type')
    types = {'object': lambda: type(value) is dict, 'array': lambda: type(value) is list,
             'string': lambda: type(value) is str, 'integer': lambda: type(value) is int,
             'number': lambda: type(value) in (int, float) and math.isfinite(value),
             'boolean': lambda: type(value) is bool, 'null': lambda: value is None}
    if kind is not None and (kind not in types or not types[kind]()):
        raise ValueError('tool_payload_type')
    # JSON encodings keep booleans distinct from 0/1 when comparing enums.
    normalized = lambda x: json.dumps(x, sort_keys=True, allow_nan=False)
    if 'const' in schema and normalized(value) != normalized(schema['const']):
        raise ValueError('tool_payload_const')
    if 'enum' in schema and normalized(value) not in [normalized(v) for v in schema['enum']]:
        raise ValueError('tool_payload_enum')
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError('tool_payload_key')
        properties = schema.get('properties', {})
        if set(schema.get('required', [])) - value.keys():
            raise ValueError('tool_payload_required')
        if schema.get('additionalProperties') is False and value.keys() - properties.keys():
            raise ValueError('tool_payload_extra')
        for key, item in value.items():
            _validate(item, properties.get(key, {}), depth + 1)
    elif type(value) is list:
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', len(value)):
            raise ValueError('tool_payload_array_size')
        if schema.get('uniqueItems') and len({normalized(v) for v in value}) != len(value):
            raise ValueError('tool_payload_duplicates')
        for item in value:
            _validate(item, schema.get('items', {}), depth + 1)
    elif type(value) is str:
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', len(value)):
            raise ValueError('tool_payload_string_size')
    elif type(value) in (int, float):
        if 'exclusiveMinimum' in schema and value <= schema['exclusiveMinimum']:
            raise ValueError('tool_payload_number_range')
        if not schema.get('minimum', value) <= value <= schema.get('maximum', value):
            raise ValueError('tool_payload_number_range')
