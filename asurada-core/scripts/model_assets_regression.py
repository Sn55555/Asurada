from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import hashlib
from regression_support import emit_result
from asurada.model_assets import read_model_asset, seal_report
from asurada.model_runtime import ResourceRiskModelRuntime
from asurada.model_admission import ModelAdmissionPolicy
from asurada.strategy import StrategyEngine
from asurada.config import StrategyThresholds
from phase3_voice_regression import make_state
from asurada.snapshot_contract import snapshot_payload, restore_decision


def run():
    source=Path('asurada-core/training/reports/resource_risk_baselines/ers_risk/ers_risk_baseline_report.json')
    checks={}
    with TemporaryDirectory() as tmp:
        dest=Path(tmp)
        report=json.loads(source.read_text()); model=source.parent/report['model_path']
        shutil.copy2(model,dest/model.name); shutil.copy2(source,dest/source.name)
        path=dest/source.name
        runtime=ResourceRiskModelRuntime(name='ers_risk',report_path=path,mode='active')
        checks['relocated_model_loads']=runtime.enabled
        evidence_path=dest/'approval.json'
        policy=ModelAdmissionPolicy(modes={'ers_risk':'active'}, evidence={'ers_risk':'approval.json'}, context_window_version='source-time-weighted-v1')
        evidence={'version':'model-admission-evidence-v1', 'model':'ers_risk', 'approved':True,
                  'context_window_version':'source-time-weighted-v1', 'evaluation_summary':'Synthetic fixture, not production approval',
                  'model_sha256':report['asset_manifest']['model_sha256'],
                  'feature_schema_sha256':report['asset_manifest']['feature_schema_sha256']}
        evidence_path.write_text(json.dumps(evidence))
        policy.validate_assets({'ers_risk':runtime})
        checks['evidence_binds_relocated_asset']=True
        engine_policy=ModelAdmissionPolicy(modes={'ers_risk':'active'}, evidence={'ers_risk':str(evidence_path)}, context_window_version='source-time-weighted-v1')
        engine=StrategyEngine(StrategyThresholds(),model_policy=engine_policy)
        checks['engine_validates_bound_evidence']=engine.resource_risk_runtime._runtimes['ers_risk'].enabled
        verified_hash=hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        state=make_state()
        decision=engine.evaluate(state)
        payload=json.loads(json.dumps(snapshot_payload(state,decision),allow_nan=False))
        restore_decision(state,payload)
        checks['verified_evidence_survives_snapshot']=state.decision_record.model_admission['verified_evidence']['ers_risk']['evidence_sha256']==verified_hash
        payload['decision_record'].pop('model_admission')
        payload['decision_record'].pop('identity_version')
        restore_decision(state,payload)
        checks['legacy_decision_without_admission_readable']=state.decision_record.model_admission=={}
        for field, value in [('approved',False),('model','wrong'),('model_sha256','wrong'),
                             ('feature_schema_sha256','wrong'),('context_window_version','old'),('evaluation_summary','')]:
            evidence_path.write_text(json.dumps({**evidence,field:value}))
            try:
                policy.validate_assets({'ers_risk':runtime})
                checks['reject_'+field]=False
            except ValueError:
                checks['reject_'+field]=True
        evidence_path.unlink()
        after=engine.evaluate(state)
        checks['running_engine_retains_original_evidence_hash']=after.record.model_admission['verified_evidence']['ers_risk']['evidence_sha256']==verified_hash
        try:
            policy.validate_assets({'ers_risk':runtime})
            checks['reject_missing_evidence']=False
        except FileNotFoundError:
            checks['reject_missing_evidence']=True
        try:
            StrategyEngine(StrategyThresholds(),model_policy=engine_policy)
            checks['engine_rejects_missing_evidence']=False
        except FileNotFoundError:
            checks['engine_rejects_missing_evidence']=True
        (dest/model.name).write_text('corrupted model')
        runtime=ResourceRiskModelRuntime(name='ers_risk',report_path=path,mode='active')
        checks['corruption_disables']=not runtime.enabled and 'model_hash_mismatch' in runtime.disabled_reason
        shutil.copy2(model,dest/model.name)
        report['feature_columns'].reverse(); path.write_text(json.dumps(report))
        runtime=ResourceRiskModelRuntime(name='ers_risk',report_path=path,mode='observe')
        checks['schema_tamper_disables']=not runtime.enabled and 'feature_schema_hash_mismatch' in runtime.disabled_reason
        path.write_text('{broken')
        runtime=ResourceRiskModelRuntime(name='ers_risk',report_path=path,mode='observe')
        checks['malformed_report_degrades']=not runtime.enabled and 'JSONDecodeError' in runtime.disabled_reason
        report=json.loads(source.read_text());report.pop('asset_manifest');path.write_text(json.dumps(report))
        runtime=ResourceRiskModelRuntime(name='ers_risk',report_path=path,mode='active')
        checks['active_requires_manifest']=not runtime.enabled and 'requires_asset_manifest' in runtime.disabled_reason
        report.pop('feature_columns');path.write_text(json.dumps(report))
        seal_report(path)
        sealed, _ = read_model_asset(path, require_manifest=True)
        checks['packager_derives_actual_feature_order']=bool(sealed['feature_columns']) and sealed['model_path']==model.name
    return {'passed':all(checks.values()),'checks':checks}

if __name__=='__main__':emit_result(run())
