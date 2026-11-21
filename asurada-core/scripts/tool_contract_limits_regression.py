from regression_support import emit_result
from asurada.tool_contract import validate_tool_payload
from asurada.capability_definitions import CAPABILITIES


def run():
    def rejects(value, schema, **options):
        try:
            validate_tool_payload(value, schema, **options)
        except ValueError:
            return True
        return False
    schema = CAPABILITIES['compare_review_laps'].input_schema
    valid = {'review_task_id': 'review', 'lap_numbers': [1, 2]}
    validate_tool_payload(valid, schema)
    deep = 1
    for _ in range(34):
        deep = [deep]
    checks = {'valid_input': True,
        'extra_input': rejects(dict(valid, command='bad'), schema),
        'duplicate_laps': rejects(dict(valid, lap_numbers=[1, 1]), schema),
        'boolean_lap': rejects(dict(valid, lap_numbers=[True, 2]), schema),
        'oversized_text': rejects('x' * 100, {'type': 'string'}, max_bytes=50),
        'deep_tree': rejects(deep, {}),
        'unknown_schema_keyword': rejects({}, {'patternProperties': {}}),
        'unknown_keyword_in_absent_property': rejects({}, {'properties': {'absent': {'format': 'date'}}}),
        'nested_nan': rejects({'a': [float('nan')]}, {}),
        'tuple_is_not_json_array': rejects({'a': (1, 2)}, {}),
        'nonstring_key': rejects({1: 'x'}, {}),
        'boolean_is_not_numeric_enum': rejects(True, {'enum': [1]}),
        'minimum': rejects(0, {'type': 'integer', 'minimum': 1}),
        'maximum': rejects(21, {'type': 'integer', 'maximum': 20})}
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())
