"""Compare every model-required runtime column to a validated full export.

Replays raw packets and the production context builder, without model inference
or generating new labels. Record IDs must match the export in exact order.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from asurada.capture_ingest import CaptureJsonlSource
from asurada.context_window import CONTEXT_WINDOW_SECONDS
from asurada.decode import decode_snapshot
from asurada.model_runtime import StrategyActionModelRuntime,build_runtime_feature_row
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu_decoder import F125PacketDecoder,PacketDecodeError
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine
from asurada.training_export_validation import validate_export
from asurada.training_provenance import file_digest
from asurada.model_assets import read_model_asset
from export_phase2_training_data import training_record_id


def equivalent(exported,runtime):
    if runtime is None or runtime=='UNKNOWN':return exported in ('','UNKNOWN')
    if isinstance(runtime,(float,int)):
        try:return math.isfinite(float(exported)) and math.isfinite(runtime) and math.isclose(float(exported),runtime,rel_tol=1e-9,abs_tol=1e-9)
        except (TypeError,ValueError):return False
    return exported==str(runtime)


def run(dataset,retraining,output):
    output.mkdir(parents=True,exist_ok=True)
    validation=validate_export(dataset)
    manifest=json.loads((dataset/'manifest.json').read_text())
    samples=json.loads(Path(manifest['sample_metadata_path']).read_text())['samples']
    assets=json.loads((retraining/'retraining-report.json').read_text())['assets']
    columns={}
    for asset in assets:
        report,_=read_model_asset(Path(asset['report']),require_manifest=True)
        columns[asset['model']]=report['feature_columns']
    captures={s['file_path']:file_digest(Path(s['file_path'])) for s in samples}
    core=Path(__file__).resolve().parents[1]
    files=[*sorted((core/'src/asurada').rglob('*.py')),Path(__file__),core/'scripts/export_phase2_training_data.py']
    hashes={str(p):file_digest(p) for p in files}
    count=0;differences=Counter();comparisons=Counter();examples={};sessions={}
    report={'passed':False,'status':'running','required_columns':columns,'capture_sha256':captures,'source_sha256':hashes,
            'scope':'all required columns, raw packet/context replay versus saved export; no model inference, labels or driving-value acceptance'}
    def save():
        report.update(rows_checked=count,sessions=sessions,differences=dict(differences),comparisons=dict(comparisons),examples=examples)
        tmp=output/'report.tmp';tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2));tmp.replace(output/'report.json')
    save()
    context_builder=object.__new__(StrategyEngine)
    action_builder=object.__new__(StrategyActionModelRuntime)
    try:
        with (dataset/'features.csv').open(newline='') as source:
            rows=csv.DictReader(source)
            for sample in samples:
                decoder=F125PacketDecoder();assembler=CaptureSnapshotAssembler();store=UnifiedStateStore();accepted=0
                for packet in CaptureJsonlSource(Path(sample['file_path'])):
                    try:envelope=decoder.decode_raw(packet)
                    except PacketDecodeError:continue
                    normalized=assembler.push(envelope)
                    if normalized is None:continue
                    state=decode_snapshot(normalized)
                    if not store.update(state):continue
                    expected=next(rows,None)
                    if expected is None or expected['record_id']!=training_record_id(state):raise ValueError('export_record_order_mismatch')
                    if str(state.session_uid)!=str(sample['session_uid']):raise ValueError('sample_uid_mismatch')
                    context=context_builder._build_context(state,store.recent_seconds(CONTEXT_WINDOW_SECONDS))
                    common=build_runtime_feature_row(state=state,context=context)
                    action=action_builder._build_feature_row(state=state,context=context)
                    for model,names in columns.items():
                        actual=action if model=='strategy_action' else common
                        for name in names:
                            key=model+':'+name;comparisons[key]+=1
                            if name not in actual or name not in expected or not equivalent(expected.get(name),actual.get(name)):
                                differences[key]+=1
                                examples.setdefault(key,{'record_id':expected['record_id'],'exported':expected.get(name),'runtime':actual.get(name),'generated':name in actual})
                    count+=1;accepted+=1
                    if count%1000==0:save()
                sessions[sample['sample_name']]=accepted;save()
                print(json.dumps({'sample':sample['sample_name'],'rows':accepted,'differences':sum(differences.values())}),flush=True)
            if next(rows,None) is not None:raise ValueError('unvisited_export_rows')
        if count!=manifest['record_count']:raise ValueError('record_count_mismatch')
        if validate_export(dataset)!=validation:raise ValueError('export_changed_during_audit')
        if any(file_digest(Path(p))!=h for p,h in {**captures,**hashes}.items()):raise ValueError('audit_inputs_changed')
        report.update(status='completed',passed=not differences)
    except Exception as exc:
        report.update(status='failed',error=f'{type(exc).__name__}: {exc}')
    save()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--dataset',required=True,type=Path);parser.add_argument('--retraining',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();result=run(args.dataset,args.retraining,args.output)
    print(json.dumps({'passed':result['passed'],'rows_checked':result['rows_checked'],'status':result['status']}))
    raise SystemExit(0 if result['passed'] else 1)
