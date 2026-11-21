import csv
import json
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from regression_support import emit_result
from asurada.training_partition import export_session_assignments
from asurada.capture_ingest import CaptureJsonlSource
from asurada.pdu_decoder import F125PacketDecoder
from asurada.state import UnifiedStateStore
from asurada.context_window import CONTEXT_WINDOW_SECONDS
from asurada.training_export_validation import validate_export
from asurada.training_provenance import training_provenance
from export_phase2_training_data import derive_tactical_split, derive_attack_split, derive_strategy_action_split, export_dataset, training_record_id, build_attack_feature_rows


def run():
    checks={}
    state=SimpleNamespace(session_uid='s',session_epoch=0,source_timestamp_ms=1,raw={'frame_identifier':10,'overall_frame_identifier':100})
    original=training_record_id(state)
    state.session_epoch=1
    checks['rewind_epoch_has_distinct_record_id']=training_record_id(state)!=original
    state.session_epoch=0;state.raw['overall_frame_identifier']=200
    checks['overall_frame_has_distinct_record_id']=training_record_id(state)!=original
    actor_feature=dict(record_id=original,split='train',session_uid='s',session_epoch=0,player_position=1,rear_rival_position=2,official_gap_behind_s=.5,official_gap_confidence_behind='high')
    with patch('export_phase2_training_data.derive_attack_opportunity_labels',return_value=(0,'none')),patch('export_phase2_training_data.derive_front_attack_commit_labels',return_value=(0,'none')):
        actors=build_attack_feature_rows(feature_row=actor_feature,label_row={},sample_rows=[],row_index=0)
    checks['actor_rows_have_distinct_ids_and_shared_source']=len(actors)==2 and len({r['record_id'] for r in actors})==2 and {r['source_record_id'] for r in actors}=={original}

    rows=[]
    for split in ('train','val','test'):
        for session in ('SprintRaceLike','FeatureRaceLike','ShortResultLike','QualifyingLike'):
            for lap in (1,2,3):
                for frame in (0,1,11,13,29,73):
                    row=dict(split=split,session_uid='s',session_type=session,lap_number=lap,frame_identifier=frame,attack_zone_flag=1)
                    rows.append((row,split))
    checks['all_domains_preserve_session_assignment']=all(
        derive_tactical_split(row)==split and derive_attack_split(feature_row=row,attack_opportunity_binary_label=label)==split and derive_strategy_action_split(row,{'primary_action_label':'LOW_FUEL'})==split
        for row,split in rows for label in (0,1))
    checks['short_result_eligibility_retained']=derive_strategy_action_split({'split':'train','session_type':'ShortResultLike'},{'primary_action_label':'NONE'})=='skip'
    samples=[dict(sample_name='one',session_uid='18446744073709551614'),dict(sample_name='same',session_uid='18446744073709551614')]
    checks['full_uint64_identity_preserved']=export_session_assignments(samples,{'one':'test','same':'test'})=={'18446744073709551614':'test'}
    try:export_session_assignments(samples,{'one':'test','same':'train'});checks['overlapping_capture_assignment_rejected']=False
    except ValueError:checks['overlapping_capture_assignment_rejected']=True
    fixture=Path(__file__).resolve().parents[1]/'data/capture_samples/f1_25_udp_frame_fixture.jsonl'
    first=next(iter(CaptureJsonlSource(fixture)));uid=str(F125PacketDecoder().decode_raw(first).session_uid)
    with TemporaryDirectory() as temp:
        root=Path(temp);metadata=root/'metadata.json'
        metadata.write_text(json.dumps({'samples':[dict(sample_name='fixture',session_label='Fixture',session_type_code=15,session_uid=uid,file_path=str(fixture))]}))
        observed_windows=[]
        original_window=UnifiedStateStore.recent_seconds
        def window(store, seconds):
            observed_windows.append(seconds)
            return original_window(store, seconds)
        with patch.object(UnifiedStateStore,'recent_seconds',window), patch.object(UnifiedStateStore,'recent',side_effect=AssertionError('legacy frame window used')):
            report=export_dataset(sample_metadata_path=metadata,output_dir=root/'export',sample_splits={'fixture':'test'},next_segment_offsets=[120.,280.],max_history_frames=12,sample_limit=None)
        checks['export_uses_runtime_time_window']=bool(observed_windows) and all(value==CONTEXT_WINDOW_SECONDS for value in observed_windows)
        checks['manifest_records_window_and_label_origin']=(report['context_window_version']=='source-time-weighted-v1'
            and report['label_provenance']=={'kind':'rule_derived','human_validated':False})
        tables=list((root/'export').glob('*.csv'))
        counts={}
        for table in tables:
            with table.open() as handle:data=list(csv.DictReader(handle))
            counts[table.name]=len(data)
            checks['table_scope_'+table.name]=all(row['split']=='test' and row['session_uid']==uid for row in data)
        checks['epoch_exported_on_main_and_label_tables']=all('session_epoch' in next(csv.DictReader((root/'export'/name).open())) for name in ('features.csv','labels.csv'))
        checks['real_export_produced_main_rows']=counts['features.csv']>0 and counts['labels.csv']>0
        checks['manifest_records_label_independent_policy']=report['partition']['assignments']=={uid:'test'} and report['partition']['label_independent']
        (root/'export/manifest.json').write_text(json.dumps(report))
        checks['completed_export_validation']=validate_export(root/'export')['passed']
        validation=validate_export(root/'export')
        validation_path=root/'export/validation.json'
        validation_path.write_text(json.dumps(validation))
        checks['training_matches_validated_export']=training_provenance(root/'export/features.csv',root/'export/labels.csv')['validation_status']=='matched'
        validation['tables']['features_path']['sha256']='stale'
        validation_path.write_text(json.dumps(validation))
        try:training_provenance(root/'export/features.csv');checks['stale_validation_rejected']=False
        except ValueError as exc:checks['stale_validation_rejected']='training_validation_input_mismatch' in str(exc)
        validation_path.unlink()
        report['partition']['assignments']['missing-session']='train'
        (root/'export/manifest.json').write_text(json.dumps(report))
        try:validate_export(root/'export');checks['configured_missing_session_rejected']=False
        except ValueError as exc:checks['configured_missing_session_rejected']=str(exc)=='configured_export_session_missing'
        del report['partition']['assignments']['missing-session']
        report['context_window_seconds']=.5
        (root/'export/manifest.json').write_text(json.dumps(report))
        try:validate_export(root/'export');checks['wrong_window_duration_rejected']=False
        except ValueError as exc:checks['wrong_window_duration_rejected']=str(exc)=='export_window_not_current'
        report['context_window_seconds']=CONTEXT_WINDOW_SECONDS
        report['record_count'] += 1
        (root/'export/manifest.json').write_text(json.dumps(report))
        try:validate_export(root/'export');checks['incomplete_export_rejected']=False
        except ValueError as exc:checks['incomplete_export_rejected']='export_row_count_mismatch' in str(exc)
        report['record_count'] -= 1
        (root/'export/manifest.json').write_text(json.dumps(report))
        label_path=root/'export/labels.csv'
        original_labels=label_path.read_text()
        for field,value,reason in [('split','train','export_row_partition_mismatch'),('record_id','foreign-record','export_feature_label_identity_mismatch')]:
            with label_path.open() as handle:
                reader=csv.DictReader(handle);columns=reader.fieldnames;label_rows=list(reader)
            label_rows[0][field]=value
            with label_path.open('w',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=columns);writer.writeheader();writer.writerows(label_rows)
            try:validate_export(root/'export');checks['tampered_'+field+'_rejected']=False
            except ValueError as exc:checks['tampered_'+field+'_rejected']=reason in str(exc)
            label_path.write_text(original_labels)
        metadata.write_text(json.dumps({'samples':[dict(sample_name='fixture',session_label='Fixture',session_type_code=15,session_uid='wrong',file_path=str(fixture))]}))
        try:export_dataset(sample_metadata_path=metadata,output_dir=root/'wrong',sample_splits={'fixture':'test'},next_segment_offsets=[],max_history_frames=12,sample_limit=1);checks['capture_metadata_mismatch_rejected']=False
        except ValueError as e:checks['capture_metadata_mismatch_rejected']=str(e)=='capture_session_does_not_match_metadata'
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())
