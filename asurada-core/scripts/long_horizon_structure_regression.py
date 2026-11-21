"""Snapshot compatibility and race-boundary invariants across pit-window scenarios."""
from dataclasses import replace
import hashlib
from itertools import product
import json

from asurada import long_horizon
from asurada.models import ContextProfile
from asurada.session_router import SessionRoute
from phase1_long_horizon_forecast_history_regression import _build_state
from regression_support import emit_result


# Updated for player-owned tyre evidence and 2025 race-distance rules.
# Input combinations are independent of the implementation's private methods.
EXPECTED_SHA256 = 'fb6ded7a939494df379e83f70c795d740dccde8392295fe4d845214869da525e'


def serialized_outputs(module):
    results = []
    for index, (track, weather, compound, lap, allowed) in enumerate(product(
        ('Shanghai', 'Suzuka'), ('Clear', 'LightRain', 'HeavyRain', 'Overcast'),
        ('C1', 'C3', 'C5', 'Intermediate', 'Wet'), (0, 1, 20, 53), (False, True),
    )):
        state = _build_state(forecast_samples=[{'weather': 3, 'rain_percentage': 80, 'time_offset': 5}])
        state.track, state.weather, state.lap_number = track, weather, lap
        state.total_laps = 0 if lap == 0 else 53
        state.player.tyre.compound = compound
        state.player.tyre.wear_pct = (index % 4) * 30.0
        state.safety_car = ('NONE', 'VSC', 'FULL')[index % 3]
        state.raw['num_pit_stops'] = index % 3
        if index % 5 == 0:
            state.raw.pop('session_history', None)
            state.raw.pop('tyre_sets', None)
        route = SessionRoute(session_mode='race', allowed_action_codes={'NONE', 'BOX_WINDOW'},
                             allow_timing_actions=allowed, allow_race_resource_actions=allowed,
                             route_reason='structure_regression')
        context = ContextProfile(0.0, 0.0, 'push', 'S2', 'mid', 'attack', 12, 1, 2, 1)
        resource = {'fuel_risk': {'score': float((index % 3) * 50)}}
        rival = {'rear_pressure': {'score': float((index % 2) * 100)}}
        support = module.PitWindowSupport().evaluate(state=state, session_route=route, context=context,
            resource_models=resource, rival_pressure_models=rival,
            tyre_degradation_trend_models={'future_grip_drop_score': {'score': 30.0}})
        plan = module.LongHorizonStrategyBaseline().plan(state=state, session_route=route,
            support=support, resource_models=resource, rival_pressure_models=rival)
        results.append({'support': support.to_dict(), 'plan': plan.to_dict()})
    return json.dumps(results, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


def run():
    encoded = serialized_outputs(long_horizon)
    digest = hashlib.sha256(encoded).hexdigest()
    checks = {
        'serialized_contract': digest == EXPECTED_SHA256,
        'no_pit_target_after_finish': all(
            row['plan']['recommended_pit_lap'] is None or row['plan']['recommended_pit_lap'] < 53
            for row in json.loads(encoded)),
        'unknown_rules_never_claim_a_stop_count': all(
            row['plan']['remaining_required_stops'] is None
            for row in json.loads(encoded) if row['plan']['compound_rule_state'] == 'unknown'),
        'legacy_public_types_available': all(hasattr(long_horizon, name) for name in (
            'PitWindowSupport', 'PitWindowSupportState', 'LongHorizonStrategyBaseline',
            'LongHorizonStrategyState', 'LongHorizonCandidate')),
    }
    return {'passed': all(checks.values()), 'checks': checks, 'cases': 320,
            'serialized_sha256': digest, 'serialized_bytes': len(encoded)}


if __name__ == '__main__':
    emit_result(run())
