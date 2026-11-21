"""Audit current model integrity, runtime membership and recorded quality proof.

This is read-only unless --annotate-reports is explicitly selected. It never
creates model-admission-evidence-v1, trains weights or changes admission modes.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from asurada.model_admission import ModelAdmissionPolicy
from asurada.model_assets import read_model_asset, review_qualification
from retrain_current_models import expected_reports


def audit(reports_root: Path, *, annotate: bool = False) -> dict:
    reports_root = reports_root.resolve()
    runtime = expected_reports(reports_root)
    policy = ModelAdmissionPolicy()
    rows = []
    for path in sorted(reports_root.rglob('*report.json')):
        report = json.loads(path.read_text())
        qualification = report.get('review_qualification') or review_qualification(report)
        if annotate:
            report.setdefault('review_qualification', qualification)
            temporary = path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            temporary.replace(path)
        row = {
            'report': str(path.relative_to(reports_root)),
            'model': runtime.get(path),
            'mode': policy.mode(runtime[path]) if path in runtime else 'not_registered',
            'report_status': report.get('status'),
            'qualification': qualification,
        }
        if 'model_path' in report:
            try:
                sealed, _ = read_model_asset(path, require_manifest=True)
                row.update(asset_integrity='verified', asset_manifest=sealed['asset_manifest'])
            except (OSError, ValueError) as exc:
                row.update(asset_integrity='invalid', asset_error=str(exc))
        else:
            row['asset_integrity'] = 'no_model_in_report'
        historical = {}
        for key in ('dataset', 'features', 'labels'):
            value = report.get(key)
            if isinstance(value, str):
                reference = Path(value)
                resolved = reference if reference.is_absolute() else path.parent / reference
                historical[key] = {'reference': value, 'exists': resolved.is_file(), 'absolute': reference.is_absolute()}
        row['historical_data_references'] = historical
        provenance = report.get('training_provenance')
        row['training_provenance_status'] = provenance.get('validation_status', 'not_provided') if isinstance(provenance, dict) else 'not_recorded'
        rows.append(row)
    runtime_rows = [row for row in rows if row['model']]
    return {
        'version': 'model-asset-audit-v1',
        'passed': len(runtime_rows) == len(runtime) and all(row['asset_integrity'] == 'verified' for row in runtime_rows),
        'scope': 'asset integrity and report inventory; does not establish human quality or training-data reproducibility',
        'runtime_model_count': len(runtime_rows),
        'admission_modes': {mode: sum(row['mode'] == mode for row in runtime_rows) for mode in ('disabled', 'observe', 'active')},
        'reports': rows,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports-root', type=Path, default=ROOT / 'training/reports')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--annotate-reports', action='store_true')
    args = parser.parse_args()
    result = audit(args.reports_root, annotate=args.annotate_reports)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded)
    raise SystemExit(0 if result['passed'] else 1)
