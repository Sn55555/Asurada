"""Unknown race control is never interpreted as either green or controlled."""
from regression_support import emit_result
from phase3_voice_regression import make_state
from asurada.assessment import assess_domain
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.response_composer import compose_structured_query_response
from asurada.race_control import decode_race_control, race_control_active
from asurada.config import AppConfig
from asurada.strategy import StrategyEngine
from asurada.snapshot_contract import snapshot_payload
from asurada.models import StrategyDecision
from asurada.decode import decode_snapshot
from asurada.state_summary_for_llm import build_state_summary_for_llm
from asurada.conversation_context import ConversationContext
from asurada.csv_ingest import LapCsvSource
from asurada.live_dashboard_payload import placeholder_dashboard_payload
from pathlib import Path


def run():
    checks={}
    assembler=CaptureSnapshotAssembler()
    state=make_state()
    engine=StrategyEngine(AppConfig().thresholds)
    for index, value in enumerate((None,'UNKNOWN',True,99,{},[])):
        state.safety_car=value
        domain=assess_domain(state)
        answer,_=compose_structured_query_response(state=state,query_kind='race_control_status',primary_message=None)
        weather,_=compose_structured_query_response(state=state,query_kind='weather_status',primary_message=None)
        context=engine._build_context(state,[state])
        risks,_=engine._score_risks(state,domain.labels,context)
        candidates=engine._build_candidates(state,domain.labels,risks,context)
        checks[f'unknown_{index}']=domain.labels.race_state=='unavailable' and '数据不可用' in answer and '数据不可用' in weather and all(c.code!='SAFETY_CAR' for c in candidates)
    checks['invalid_packet_values_unavailable']=all(assembler._normalize_safety_car_name(value) is None for value in (None,99,'bad',True,'1',1.0))
    for code,name in enumerate(('NONE','FULL','VSC','FORMATION')):
        state.safety_car=name
        checks['valid_'+name]=decode_race_control(code)==name and assess_domain(state).labels.race_state==('green' if code==0 else 'controlled')
    state.safety_car=None
    payload=snapshot_payload(state,StrategyDecision([]))
    restored=decode_snapshot(payload)
    checks['unknown_roundtrip']=restored.safety_car is None and assess_domain(restored).labels.race_state=='unavailable'
    checks['unknown_not_active']=not race_control_active(None) and not race_control_active('UNKNOWN')
    row={key:'0' for key in ('speed_kmh','throttle','brake','steer','g_force_lateral',
        'g_force_longitudinal','ers_store_energy','lap_distance_m','session_time_s',
        'fuel_remaining_laps','drs','tyres_age_laps','frame_identifier','overall_frame_identifier',
        'lap_time_s','sector','gear','rpm','fuel_in_tank','ers_deploy_mode','g_force_vertical',
        'yaw','pitch','roll','world_position_x','world_position_y','world_position_z','current_lap_invalid')}
    row.update(track_name='Suzuka',lap_number='1')
    source=LapCsvSource(Path('fixture.csv'))
    checks['csv_missing_stays_unknown']=source._normalize_row(row,1000,1)['safety_car'] is None
    row['safety_car']='VSC'
    checks['csv_explicit_value_preserved']=source._normalize_row(row,1000,1)['safety_car']=='VSC'
    checks['standby_not_green_fact']=placeholder_dashboard_payload()['session']['safety_car'] is None
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':
    emit_result(run())
