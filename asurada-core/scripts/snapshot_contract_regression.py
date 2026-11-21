from dataclasses import asdict
from tempfile import TemporaryDirectory
from pathlib import Path
import json
from regression_support import emit_result
from model_admission_regression import evaluate
from asurada.model_admission import ModelAdmissionPolicy, MODEL_NAMES
from asurada.snapshot_contract import snapshot_payload
from asurada.decode import decode_snapshot
from asurada.models import SessionState, DriverState, TyreState
from asurada.assessment import snapshot_id
from phase1_rival_pit_window_support_regression import _build_state
from asurada.live_dashboard_feed import LatestSnapshotWriter
from phase3_macos_voice_loop import load_state_and_message


def run():
    # Use the same source fixture as the actual engine path in evaluate().
    state=_build_state()
    state.raw.update(timing_mode='race_like',timing_support_level='official_preferred',fuel_in_tank=1,fuel_capacity=100,fuel_laps_remaining_source="derived_from_sample_consumption")
    decision=evaluate(ModelAdmissionPolicy(modes={name:'disabled' for name in MODEL_NAMES}),0)
    payload=json.loads(json.dumps(snapshot_payload(state,decision)))
    restored=decode_snapshot(payload)
    checks={'roundtrip_record':restored.decision_record==decision.record,'roundtrip_binding':snapshot_id(restored)==decision.record.snapshot_id}
    integer_state=decode_snapshot({**payload, 'decision_record':None})
    integer_state.player.speed_kph=int(integer_state.player.speed_kph)
    number_payload=json.loads(json.dumps(snapshot_payload(integer_state, type(decision)([]))))
    checks['integer_float_same_binding']=snapshot_id(integer_state)==snapshot_id(decode_snapshot(number_payload))
    integer_state.raw['large_counter']=18446744073709551614
    first=snapshot_id(integer_state)
    integer_state.raw['large_counter']=18446744073709551615
    checks['large_integer_precision_preserved']=snapshot_id(integer_state)!=first
    tampered=json.loads(json.dumps(payload));tampered['session_epoch']=99
    try: decode_snapshot(tampered); checks['mismatched_record_rejected']=False
    except ValueError: checks['mismatched_record_rejected']=True
    for key in ('model_admission', 'arbitration'):
        changed=json.loads(json.dumps(payload))
        changed['decision_record'][key]['tampered']=True
        try: decode_snapshot(changed); checks[key+'_tamper_rejected']=False
        except ValueError as exc: checks[key+'_tamper_rejected']=str(exc)=='decision_content_mismatch'
    from dataclasses import replace
    from asurada.decision_identity import decision_content_id
    different=replace(decision.record,model_admission={'version':'different-policy'})
    checks['same_actions_different_policy_different_id']=decision_content_id(different)!=decision.record.decision_id
    with TemporaryDirectory() as directory:
        path=Path(directory)
        LatestSnapshotWriter(path).append(state,decision)
        (path/'session_log.jsonl').write_text('invalid history must not be parsed')
        read,primary=load_state_and_message(path/'session_log.jsonl','latest')
        checks['voice_reads_latest_bound_record']=read.decision_record==decision.record and primary==decision.record.actions[0]
    return {'passed':all(checks.values()),'checks':checks}

if __name__=='__main__':emit_result(run())
