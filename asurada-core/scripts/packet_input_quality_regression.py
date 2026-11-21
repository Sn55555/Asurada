import json
from regression_support import emit_result
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu import PacketEnvelope
from asurada.decode import decode_snapshot
from asurada.strategy import StrategyEngine
from asurada.assessment import assess_domain
from asurada.config import StrategyThresholds
from asurada.model_admission import ModelAdmissionPolicy, MODEL_NAMES


def assemble(controls, *, drs_permission=None):
    assembler = CaptureSnapshotAssembler()
    bodies = {'Session': dict(track_id=0, track_length_m=5000, session_type=10, total_laps=20),
              'LapData': dict(current_lap_num=2, sector=0, car_position=1, lap_distance_m=100),
              'CarTelemetry': dict(speed_kph=180, **controls),
              'CarStatus': {} if drs_permission is None else {'drs_allowed': drs_permission}}
    result = None
    for kind in ['Session', *sorted(assembler.REQUIRED_FRAME_PACKETS)]:
        header = dict(session_uid='input-quality', received_at_ms=1000, frame_identifier=1)
        result = assembler.push(PacketEnvelope(kind, 1, 'input-quality',
            {'header': header, 'body': bodies.get(kind, {})}))
    assert result is not None
    return result


def run():
    checks = {}
    engine = object.__new__(StrategyEngine)
    for name in ('throttle', 'brake', 'steer'):
        for label, value in [('missing', None), ('bool', True), ('text', '0'),
                             ('nan', float('nan')), ('infinite', float('inf')), ('range', 2)]:
            controls = dict(throttle=0., brake=0., steer=0.)
            if label == 'missing': controls.pop(name)
            else: controls[name] = value
            payload = assemble(controls)
            # Same JSON round trip used by snapshot persistence, without NaN.
            state = decode_snapshot(json.loads(json.dumps(payload, allow_nan=False)))
            context = engine._build_context(state, [state])
            key = name + '_' + label
            checks[key] = (state.raw[name] is None and context.driving_mode == 'unknown'
                and context.input_quality[name]['quality'] == 'unavailable'
                and assess_domain(state).labels.dynamics_state == 'unavailable')
            quality = state.raw['input_quality'][name]
            checks[key + '_source'] = quality == dict(source='CarTelemetry', observed_at_ms=1000,
                unit='normalized', quality='missing' if label == 'missing' else 'invalid')
    payload = assemble(dict(throttle=0., brake=0., steer=0.))
    state = decode_snapshot(payload)
    checks['zero_observed'] = all(q['quality'] == 'observed' for q in state.raw['input_quality'].values())
    checks['zero_is_stable'] = assess_domain(state).labels.dynamics_state == 'stable'
    checks['zero_driving_mode'] = engine._build_context(state, [state]).driving_mode == 'straightline'
    closed = decode_snapshot(assemble({'drs': False}, drs_permission=True))
    opened = decode_snapshot(assemble({'drs': True}, drs_permission=False))
    checks['drs_permission_and_wing_position_stay_independent'] = (
        closed.raw['forecast_drs_allowed'] is True and closed.raw['drs_open'] is False
        and opened.raw['forecast_drs_allowed'] is False and opened.raw['drs_open'] is True
        and state.raw['forecast_drs_allowed'] is None and state.raw['drs_open'] is None)
    # A missing throttle does not invalidate an independently supported braking tag.
    assembler = CaptureSnapshotAssembler()
    tags = assembler._build_status_tags(speed_kph=180, throttle=None, brake=.9, steer=0.,
        g_force_lateral=0, g_force_longitudinal=-4, wheel_slip_ratio=[])
    rear_slip = assembler._build_status_tags(180, 0., .9, 0., 0, -4, [.18, 0., 0., 0.])
    front_slip = assembler._build_status_tags(180, 0., .9, 0., 0, -4, [0., 0., .18, 0.])
    severe_rear_slip = assembler._build_status_tags(180, 0., .9, 0., 0, -4, [.25, 0., 0., 0.])
    checks["front_load_uses_front_axle_only"] = (
        "front_tyre_overload" in front_slip and "front_tyre_overload" not in rear_slip)
    checks["urgent_rear_slip_remains_eligible"] = "unstable" in severe_rear_slip
    checks['independent_braking_evidence_retained'] = 'heavy_braking' in tags and 'unavailable' in tags and 'stable' not in tags
    runtime = StrategyEngine(StrategyThresholds(), model_policy=ModelAdmissionPolicy(
        modes={name: 'disabled' for name in MODEL_NAMES}))
    missing = decode_snapshot(assemble({}))
    decision = runtime.evaluate(missing, [missing])
    checks['assembled_unknown_survives_strategy'] = (decision.record.assessment.labels.dynamics_state == 'unavailable'
        and decision.debug['context']['driving_mode'] == 'unknown')
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__': emit_result(run())
