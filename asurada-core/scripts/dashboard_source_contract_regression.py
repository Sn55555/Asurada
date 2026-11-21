"""Dashboard binding and freshness follow the source, never transport heartbeat."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from dashboard_transport_regression import server
from asurada.live_dashboard_payload import build_dashboard_payload, dashboard_source_status
from asurada.runtime_context import RuntimeContextDetector
from asurada.snapshot_contract import snapshot_payload
from asurada.model_admission import ModelAdmissionPolicy, MODEL_NAMES
from asurada.config import AppConfig
from asurada.strategy import StrategyEngine
from phase1_rival_pit_window_support_regression import _build_state
from regression_support import emit_result


def run():
    state = _build_state()
    state.raw.update(timing_mode='race_like', timing_support_level='official_preferred', fuel_in_tank=1, fuel_capacity=100)
    # The dashboard contract binds the actual input state. A decision produced
    # by another fixture may contain different raw fields after fuel-policy fixes.
    engine = StrategyEngine(AppConfig().thresholds,
                            model_policy=ModelAdmissionPolicy(modes={name: 'disabled' for name in MODEL_NAMES}))
    decision = engine.evaluate(state, [state])
    payload = build_dashboard_payload(state, decision)
    record = snapshot_payload(state, decision)['decision_record']
    checks = {'same_decision_and_snapshot': payload['binding']['decision_id'] == record['decision_id']
              and payload['binding']['snapshot_id'] == record['snapshot_id'],
              'uid_preserves_integer_precision': payload['binding']['session_uid'] == str(state.session_uid)}
    for age in (0, 15000, 15001, -1):
        now = state.source_timestamp_ms + age
        status = dashboard_source_status(payload, now_ms=now)
        core = RuntimeContextDetector().detect(state=state, now_ms=now)
        checks[f'core_freshness_parity_{age}'] = (status['status'] != 'live') == core.stale_snapshot
    for value in (None, True, '123', float('nan'), float('inf'), 0, -1, 1.5):
        checks[f'invalid_time_{value}'] = dashboard_source_status({'source_timestamp_ms': value})['status'] == 'unavailable'
    state.player.speed_kph += 1
    try:
        build_dashboard_payload(state, decision)
        checks['mismatched_decision_rejected'] = False
    except ValueError:
        checks['mismatched_decision_rejected'] = True
    with TemporaryDirectory() as directory, patch.object(server, 'load_voice_meter_snapshot', return_value={}):
        path = Path(directory) / 'feed.json'
        source = server.DashboardStateSource(path, SimpleNamespace(latest_snapshot=lambda: {}))
        checks['missing_source_unavailable'] = source.latest_payload_dict()['source_status']['status'] == 'unavailable'
        path.write_text(json.dumps(payload))
        stamp = payload['source_timestamp_ms']
        with patch('asurada.live_dashboard_payload.time.time', return_value=(stamp+1)/1000):
            checks['fresh_file_live'] = source.latest_payload_dict()['source_status']['status'] == 'live'
        with patch('asurada.live_dashboard_payload.time.time', return_value=(stamp+15001)/1000):
            checks['unchanged_file_becomes_stale'] = source.latest_payload_dict()['source_status']['status'] == 'stale'
        for invalid in ('[]', '{', '{"payload_version":"future"}'):
            path.write_text(invalid)
            checks[f'invalid_file_{invalid}'] = source.latest_payload_dict()['source_status']['status'] == 'unavailable'
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())
