"""Load all current runtime assets after moving their report/model directory."""
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from asurada.model_assets import read_model_asset, review_qualification
from asurada.model_runtime import ResourceRiskModelRuntime, StrategyActionModelRuntime
from retrain_current_models import expected_reports, ROOT
from regression_support import emit_result


def run():
    checks = {}
    with TemporaryDirectory() as directory:
        destination = Path(directory)
        for source, name in expected_reports(ROOT / 'training/reports').items():
            report, model = read_model_asset(source, require_manifest=True)
            target = destination / name
            target.mkdir()
            shutil.copy2(model, target / model.name)
            path = target / source.name
            shutil.copy2(source, path)
            runtime = (StrategyActionModelRuntime(report_path=path) if name == 'strategy_action'
                       else ResourceRiskModelRuntime(name=name, report_path=path))
            checks[name + '_relocated_loads'] = runtime.enabled
            report.pop('asset_manifest')
            path.write_text(json.dumps(report))
            runtime = ResourceRiskModelRuntime(name=name, report_path=path)
            checks[name + '_observe_requires_manifest'] = not runtime.enabled and 'requires_asset_manifest' in runtime.disabled_reason
            report = json.loads(source.read_text())
            report['model_path'] = str(model.resolve())
            path.write_text(json.dumps(report))
            runtime = ResourceRiskModelRuntime(name=name, report_path=path)
            checks[name + '_absolute_runtime_path_rejected'] = not runtime.enabled and 'must_be_relative' in runtime.disabled_reason
        checks['missing_label_source_unknown'] = review_qualification({})['label_quality_tier'] == 'unknown'
        qualification = review_qualification({'label_provenance': {'kind': 'rule_derived', 'human_validated': False}})
        checks['pseudo_labels_not_quality_approval'] = qualification['not_for_mainline'] and qualification['human_holdout']['metrics'] is None
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())
