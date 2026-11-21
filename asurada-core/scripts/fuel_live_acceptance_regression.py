from unittest.mock import patch
from regression_support import emit_result, runtime_clock
from phase3_voice_regression import make_state, make_strategy_decision, FakeSpeechBackend
from asurada.assessment import assess_fuel
from asurada.output import ConsoleVoiceOutput


@runtime_clock(1_000_000)
def run():
    state = make_state()
    state.source_timestamp_ms = 1_000_000
    state.lap_number = 1
    state.total_laps = 3
    state.raw.update(fuel_in_tank=4.2, fuel_capacity=110, fuel_laps_remaining_source='derived_from_sample_consumption')
    checks = {'short_race_small_load_not_critical': assess_fuel(state).verdict == 'unavailable'}
    state.raw['fuel_in_tank'] = 0
    checks['empty_tank_still_critical'] = assess_fuel(state).verdict == 'critical'
    state.raw['fuel_in_tank'] = 4.2
    state.lap_number = 2
    state.player.fuel_laps_remaining = 3
    checks['reliable_sufficient_estimate'] = assess_fuel(state).verdict == 'stable'
    state.player.fuel_laps_remaining = 1
    checks['reliable_deficit_still_critical'] = assess_fuel(state).verdict == 'critical'
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    def emit(code='LOW_FUEL', detail='fuel'):
        d = make_strategy_decision(state=state, code=code, priority=95, title=code, detail=detail)
        output.emit(d, state=state, render=False)
    import time
    emit(); backend.complete_all(); output.tick()
    emit(detail='changed decimal'); checks['changing_detail_not_repeated'] = len(backend._handles) == 1
    output._last_fuel_broadcast_at = time.monotonic() - 59
    emit(); checks['interval_enforced'] = len(backend._handles) == 1
    output._last_fuel_broadcast_at = time.monotonic() - 60
    emit(); checks['persistent_deficit_can_remind'] = len(backend._handles) == 2
    backend.complete_all(); output.tick()
    state.session_epoch += 1
    emit(); checks['new_scope_can_warn_immediately'] = len(backend._handles) == 3
    backend.complete_all(); output.tick()
    emit('SAFETY_CAR'); checks['other_alert_not_suppressed'] = len(backend._handles) == 4
    output.shutdown(timeout_s=0)
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())
