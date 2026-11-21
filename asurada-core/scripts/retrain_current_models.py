"""Rebuild the 14 runtime assets in isolation after complete export validation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from asurada.training_export_validation import validate_export
from asurada.model_assets import seal_report, read_model_asset
from asurada.model_runtime import (DEFAULT_STRATEGY_ACTION_REPORT, DEFAULT_DEFENCE_COST_REPORT,
    DEFAULT_RESOURCE_RISK_REPORTS, DEFAULT_RIVAL_PRESSURE_REPORTS,
    DEFAULT_DRIVING_QUALITY_REPORTS, DEFAULT_TYRE_DEGRADATION_TREND_REPORTS)


def expected_reports(destination):
    paths = {'strategy_action': DEFAULT_STRATEGY_ACTION_REPORT, 'defence_cost': DEFAULT_DEFENCE_COST_REPORT,
             **DEFAULT_RESOURCE_RISK_REPORTS, **DEFAULT_RIVAL_PRESSURE_REPORTS,
             **DEFAULT_DRIVING_QUALITY_REPORTS, **DEFAULT_TYRE_DEGRADATION_TREND_REPORTS}
    return {destination / path.relative_to(ROOT / 'training' / 'reports'): name for name, path in paths.items()}


def commands(dataset, destination):
    shared = ['--features', str(dataset / 'features.csv'), '--labels', str(dataset / 'labels.csv')]
    return [
        ('resource_risk_baselines', shared),
        ('driving_quality_baselines', ['--features', str(dataset / 'features.csv')]),
        ('rival_pressure_baseline', shared),
        ('strategy_action_baseline', ['--features', str(dataset / 'strategy_action_features_v1.csv')]),
        ('tyre_degradation_trend_baseline', ['--dataset', str(dataset / 'features.csv')]),
        ('defence_cost_baseline', shared),
    ]


def run(dataset, destination):
    dataset, destination = dataset.resolve(), destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('training_output_must_be_empty')
    validation = validate_export(dataset)
    (dataset / 'validation.json').write_text(json.dumps(validation, indent=2), encoding='utf-8')
    destination.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'dataset': str(dataset), 'validation': validation, 'stages': [], 'assets': []}
    def save():
        (destination / 'retraining-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    for name, arguments in commands(dataset, destination):
        command = [sys.executable, str(ROOT / 'scripts' / ('train_' + name + '.py')),
                   *arguments, '--output-dir', str(destination / name)]
        with (destination / (name + '.stdout.txt')).open('w') as stdout, (destination / (name + '.stderr.txt')).open('w') as stderr:
            completed = subprocess.run(command, stdout=stdout, stderr=stderr,
                env={**os.environ, 'OMP_NUM_THREADS': '1'})
        report['stages'].append({'name': name, 'command': command, 'exit_code': completed.returncode})
        save()
        if completed.returncode:
            return report
    try:
        expected = expected_reports(destination)
        produced = {path for path in destination.rglob('*report.json')
                    if 'model_path' in json.loads(path.read_text())}
        if produced != set(expected):
            raise ValueError('runtime_asset_reports_mismatch:' + json.dumps({
                'missing': sorted(str(p.relative_to(destination)) for p in set(expected) - produced),
                'unexpected': sorted(str(p.relative_to(destination)) for p in produced - set(expected))}))
        for path in sorted(produced):
            payload = json.loads(path.read_text())
            if 'model_path' not in payload:
                continue
            if payload.get('training_provenance', {}).get('validation_status') != 'matched':
                raise ValueError('trained_model_missing_validated_provenance:' + str(path))
            seal_report(path)
            sealed, _ = read_model_asset(path, require_manifest=True)
            report['assets'].append({'model': expected[path], 'report': str(path), 'manifest': sealed['asset_manifest']})
        if len(report['assets']) != 14:
            raise ValueError('expected_fourteen_runtime_assets')
        # Recheck that data still matches the validated inputs after training.
        if validate_export(dataset) != validation:
            raise ValueError('training_inputs_changed')
        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    result = run(args.dataset, args.output_dir)
    print(json.dumps({'passed': result['passed'], 'stages': len(result['stages']), 'assets': len(result['assets'])}))
    raise SystemExit(0 if result['passed'] else 1)
