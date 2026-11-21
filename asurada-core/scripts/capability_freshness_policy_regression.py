"""Source-age boundaries affect reads and delivery, not historical analysis."""
import ast
from pathlib import Path
from asurada.capability_definitions import CAPABILITIES
from asurada.capability_executor import CapabilityExecutor
from asurada.task_runtime import TaskContext
from asurada.speech_applicability import validate_query_applicability
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    checks = {}
    limits = {'control': 2000, 'structured': 5000, 'explainer': 8000, 'analysis_tool': 15000}
    for name, spec in CAPABILITIES.items():
        checks[name + '_declared_budget'] = 0 < spec.deadline_ms < spec.freshness_ms <= limits[spec.lane]
    source = Path(__file__).parents[1] / 'src/asurada/capability_definitions.py'
    calls = [node for node in ast.walk(ast.parse(source.read_text())) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == 'CapabilitySpec']
    checks['all_policies_keyword_only'] = bool(calls) and all(not c.args for c in calls)
    state = make_state(); state.source_timestamp_ms = 1_000_000
    for name in ('front_gap', 'rear_gap', 'drs_status', 'fuel_status', 'tyre_status', 'race_control_status', 'overall_situation'):
        spec = CAPABILITIES[name]
        for age in (spec.freshness_ms - 1, spec.freshness_ms + 1, -1, float('nan')):
            clock = lambda age=age: (1_000_000 + age) / 1000
            should_pass = 0 <= age <= spec.freshness_ms
            executor = CapabilityExecutor(context=TaskContext.start('freshness', 5000),
                permissions=frozenset({'read_race_state'}), wall_clock=clock)
            try:
                executor.execute(name, state=state)
                checks[f'{name}_{age}_read'] = should_pass
            except ValueError as exc:
                checks[f'{name}_{age}_read'] = not should_pass and str(exc) == 'snapshot_not_current'
            try:
                validate_query_applicability('emit_query_response', {'query_kind': name}, state, state, wall_clock=clock)
                checks[f'{name}_{age}_delivery'] = should_pass
            except ValueError as exc:
                checks[f'{name}_{age}_delivery'] = not should_pass and str(exc) == 'speech_answer_snapshot_expired'
    executor = CapabilityExecutor(context=TaskContext.start('history', 5000), historical=True,
        permissions=frozenset({'read_session_history'}), wall_clock=lambda: 9999999)
    checks['historical_not_expired'] = executor.execute('fuel_status', state=state)['historical'] is True
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())
