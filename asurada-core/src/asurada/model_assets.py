"""Portable model reports; integrity metadata never grants quality approval."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from .wheel_telemetry import WHEEL_ORDER_VERSION


def feature_schema_hash(columns: list[str], wheel_order_version: str | None = None) -> str:
    layout = columns if wheel_order_version is None else [wheel_order_version, columns]
    return hashlib.sha256(json.dumps(layout, separators=(',', ':')).encode()).hexdigest()


def _report_feature_schema_hash(report: dict[str, Any], columns: list[str]) -> str:
    version = (report.get('training_provenance') or {}).get('wheel_order_version')
    if version not in (None, WHEEL_ORDER_VERSION):
        raise ValueError('unsupported_wheel_feature_order')
    return feature_schema_hash(columns, version)


def read_model_asset(report_path: Path, *, require_manifest: bool = False) -> tuple[dict[str, Any], Path]:
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if not isinstance(report, dict) or not isinstance(report.get('model_path'), str) or not report['model_path']:
        raise ValueError('invalid_model_report')
    path = Path(report['model_path'])
    if require_manifest and path.is_absolute():
        raise ValueError('runtime_model_path_must_be_relative')
    if not path.is_absolute():
        path = report_path.parent / path
    if not path.is_file():
        raise ValueError('missing_model_asset')
    columns = report.get('feature_columns')
    if not isinstance(columns,list) or not columns or not all(isinstance(item,str) for item in columns) or len(set(columns)) != len(columns):
        raise ValueError('invalid_feature_schema')
    manifest = report.get('asset_manifest')
    if manifest is None:
        if require_manifest:
            raise ValueError('model_requires_asset_manifest')
    else:
        if not isinstance(manifest,dict) or manifest.get('version') != 'model-asset-v1':
            raise ValueError('unsupported_asset_manifest')
        if manifest.get('model_sha256') != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('model_hash_mismatch')
        if manifest.get('feature_schema_sha256') != _report_feature_schema_hash(report, columns):
            raise ValueError('feature_schema_hash_mismatch')
    return report, path


def review_qualification(report: dict[str, Any]) -> dict[str, Any]:
    """Describe recorded label evidence without upgrading it to human approval.

    Old reports often lack provenance. A nearby, newer dataset is not evidence
    for how those weights were trained, so their label tier remains unknown.
    Human metrics must be supplied independently; sealing only binds bytes.
    """
    provenance = report.get('label_provenance')
    if not isinstance(provenance, dict):
        training = report.get('training_provenance')
        provenance = training.get('label_provenance') if isinstance(training, dict) else None
    kind = provenance.get('kind') if isinstance(provenance, dict) else None
    known = {'rule_derived', 'proxy_derived_from_features', 'formula_proxy', 'telemetry_delta'}
    return {
        'version': 'model-review-qualification-v1',
        'label_quality_tier': kind if kind in known else 'unknown',
        'not_for_mainline': True,
        'human_holdout': {'status': 'not_provided', 'metrics': None},
        'scope': 'Asset integrity and pseudo-label metrics are not human quality approval; explicit admission evidence is still required.',
    }


def seal_report(report_path: Path) -> None:
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if not isinstance(report, dict) or not report.get('model_path'):
        raise ValueError('invalid_model_report')
    path = Path(report['model_path'])
    path = path if path.is_absolute() else report_path.parent / path
    if not path.is_file():
        raise ValueError('missing_model_asset')
    if path.parent.resolve() != report_path.parent.resolve():
        raise ValueError('model_must_be_colocated_for_packaging')
    import lightgbm as lgb
    columns = lgb.Booster(model_file=str(path)).feature_name()
    if report.get('feature_columns') and report['feature_columns'] != columns:
        raise ValueError('booster_feature_order_mismatch')
    report['feature_columns'] = columns
    report['model_path'] = path.name
    report['asset_manifest'] = {'version':'model-asset-v1',
                                'model_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                'feature_schema_sha256':_report_feature_schema_hash(report, columns)}
    # Preserve explicitly supplied review results. Packaging cannot manufacture
    # a holdout evaluation or replace a separately reviewed admission decision.
    report.setdefault('review_qualification', review_qualification(report))
    temporary = report_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(report_path)
