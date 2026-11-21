"""Missing/invalid telemetry remains unknown in the dashboard projection."""
import json
from phase3_voice_regression import make_state
from asurada.models import StrategyDecision
from asurada.live_dashboard_payload import build_dashboard_payload, placeholder_dashboard_payload
from regression_support import emit_result


def run():
    checks = {}
    for label, value in [('missing', None), ('nan', float('nan')), ('inf', float('inf')), ('bool', True), ('text', '30')]:
        state = make_state(); state.raw = {}
        state.player.ers_pct = state.player.speed_kph = state.player.fuel_laps_remaining = value
        state.player.tyre.wear_pct = value
        state.player.tyre.surface_temperature_c = [value]*4
        state.raw['official_gap_ahead_s'] = value
        payload = build_dashboard_payload(state, StrategyDecision([]))
        checks[label+'_resources_unknown'] = all(payload['car'][k] is None for k in ('ers_pct','speed_kph','fuel_laps_remaining'))
        checks[label+'_tyres_unknown'] = payload['tyres']['wear_pct_avg'] is None and payload['tyres']['surface_temperature_c'] == [None]*4
        checks[label+'_damage_unknown'] = payload['damage']['body_damage_pct'] is None and payload['damage']['powertrain_damage_pct'] is None
        checks[label+'_gap_unknown'] = payload['gaps']['ahead_s'] is None and payload['gaps']['ahead_source'] == 'missing'
        json.dumps(payload, allow_nan=False)
        checks[label+'_strict_json'] = True
    state = make_state();state.raw = {'wing_damage_pct':{'front_left':0,'front_right':0,'rear':0},
        'floor_damage_pct':0,'diffuser_damage_pct':0,'sidepod_damage_pct':0,'gearbox_damage_pct':0,'engine_damage_pct':0}
    payload = build_dashboard_payload(state, StrategyDecision([]))
    checks['complete_real_zero_preserved'] = payload['damage']['body_damage_pct'] == payload['damage']['powertrain_damage_pct'] == 0
    state.raw['floor_damage_pct'] = None
    checks['partial_damage_not_false_zero'] = build_dashboard_payload(state,StrategyDecision([]))['damage']['body_damage_pct'] is None
    state.raw.update(official_gap_ahead_s=float('nan'),estimated_gap_ahead_s=1.2)
    payload = build_dashboard_payload(state,StrategyDecision([]))
    checks['valid_estimate_fallback'] = payload['gaps']['ahead_s']==1.2 and payload['gaps']['ahead_source']=='estimated'
    empty=placeholder_dashboard_payload()
    checks['standby_unknown_resources'] = empty['car']['ers_pct'] is None and empty['car']['speed_kph'] is None
    checks['standby_unknown_damage'] = empty['damage']['body_damage_pct'] is None
    return {'passed':all(checks.values()),'checks':checks}


if __name__ == '__main__':emit_result(run())
