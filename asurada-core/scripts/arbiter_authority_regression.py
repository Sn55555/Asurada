"""The arbiter decides actions; priority metadata never claims a cooldown."""
from dataclasses import asdict
from asurada.arbiter import OutputControl
from asurada.strategy import StrategyEngine
from phase1_regression import analyze_arbiter_contract
from regression_support import emit_result


def run():
    checks = {'priority_field_has_its_actual_name': asdict(OutputControl(72)) == {'voice_priority_floor': 72}}
    # This resolver needs no model loading or audio to verify authority.
    engine = StrategyEngine.__new__(StrategyEngine)
    checks['empty_is_authoritative'] = engine._resolve_final_messages({'output': {'ordered_actions': []}}) == []
    for value in ({}, {'output': {}}, {'output': {'ordered_actions': [None]}}):
        try:
            engine._resolve_final_messages(value)
            checks[str(value)] = False
        except ValueError:
            checks[str(value)] = True
    actions = [{'code': 'SAFETY_CAR', 'title': 'Safety car', 'priority': 100, 'detail': 'pace controlled'}]
    checks['valid_action_preserved'] = [asdict(x) for x in engine._resolve_final_messages({'output': {'ordered_actions': actions}})] == actions
    report = analyze_arbiter_contract()
    checks.update(report['checks'])
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())
