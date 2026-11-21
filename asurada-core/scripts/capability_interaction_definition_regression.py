"""A newly registered capability reaches interaction and ASR without parallel tables."""
from dataclasses import replace
from regression_support import emit_result
from asurada.asr_fast import KeywordFastIntentASR
from asurada.audio_io import AudioFormat
from asurada.capability_definitions import CAPABILITIES
from asurada.capability_registry import CapabilityRegistry
from asurada.interaction import (
    StructuredQuerySchema, route_structured_query, _query_prompt,
    _requested_fields_for_query_kind,
)
from asurada.voice_turn import VoiceTurn


def run():
    name = 'registry_extension_regression'
    assert name not in CAPABILITIES
    CAPABILITIES[name] = replace(
        CAPABILITIES['fuel_status'], name=name,
        requested_fields=('new.fact',), route_handler='new_domain_handler',
        default_query_text='新增能力问句', fast_aliases=('注册扩展专用词',),
    )
    try:
        fields = _requested_fields_for_query_kind(name)
        schema = StructuredQuerySchema('v1', name, 'state', fields, None, 'voice', False)
        route = route_structured_query(schema)
        turn = VoiceTurn('extension', 0, 1, AudioFormat(), b'', 0, 'test', 'test',
                         {'transcript_text': '注册扩展专用词'})
        intent = KeywordFastIntentASR().recognize_turn(turn)
        registry = CapabilityRegistry()
        catalog = next(item for item in registry.tool_catalog() if item['name'] == name)
        checks = {
            'registry_drives_route': route.handler == 'new_domain_handler',
            'registry_drives_fields': fields == ['new.fact'],
            'registry_drives_prompt': _query_prompt(name) == '新增能力问句',
            'registry_drives_asr': intent.query_kind == name,
            'recognized_capability_allowed': registry.evaluate(query_kind=intent.query_kind, normalized_text=intent.normalized_text).allowed,
            'catalog_uses_same_metadata': catalog['policy']['requested_fields'] == ('new.fact',),
        }
        from asurada.capability_executor import CapabilityExecutor
        from asurada.task_runtime import TaskContext
        from phase3_voice_regression import make_state
        state = make_state()
        executor = CapabilityExecutor(context=TaskContext.start('extension', 1000),
            permissions=frozenset({'read_race_state'}),
            wall_clock=lambda: state.source_timestamp_ms / 1000)
        result = executor.execute(name, state=state)
        checks['new_registration_executes_handler'] = (
            result['tool'] == name and result['action_code'] == 'QUERY_FUEL_STATUS'
            and bool(result['speak_text']) and result['session_uid'] == state.session_uid)
        denied = CapabilityExecutor(context=TaskContext.start('denied-extension', 1000),
            permissions=frozenset(), wall_clock=lambda: state.source_timestamp_ms / 1000)
        try:
            denied.execute(name, state=state)
            checks['new_registration_enforces_permission'] = False
        except PermissionError:
            checks['new_registration_enforces_permission'] = True
        fields.append('caller_mutation')
        checks['projection_is_owned'] = _requested_fields_for_query_kind(name) == ['new.fact']
        custom = KeywordFastIntentASR(aliases={'stop': ('专用停止',)})
        checks['explicit_alias_override_preserved'] = list(custom.aliases) == ['stop']
        recognizer = KeywordFastIntentASR()
        # Broad front/rear and resource phrases must not hide specific exact aliases.
        checks['specific_alias_priority'] = all(
            recognizer._best_match_for_text(text)[0] == expected
            for text, expected in [('前车有没有drs', 'front_rival_drs_status'),
                                   ('燃油怎么样', 'fuel_status'), ('停止', 'stop')]
        )
        return {'passed': all(checks.values()), 'checks': checks}
    finally:
        del CAPABILITIES[name]


if __name__ == '__main__':
    emit_result(run())
