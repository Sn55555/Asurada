"""Capture input provenance without inventing missing export metadata."""
import hashlib
import json
from pathlib import Path
from .training_export_paths import export_table_path


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def training_provenance(features, labels=None, *, feature_key='features_path'):
    features = Path(features)
    labels = Path(labels) if labels is not None else None
    result = {'version': 'training-provenance-v1',
              'features_path': str(features.resolve()), 'labels_path': str(labels.resolve()) if labels else None,
              'features_sha256': file_digest(features), 'labels_sha256': file_digest(labels) if labels else None,
              'export_metadata_status': 'missing', 'validation_status': 'not_provided'}
    manifest_path = features.parent / 'manifest.json'
    if not manifest_path.exists():
        if (features.parent / 'validation.json').exists():
            raise ValueError('training_validation_without_manifest')
        return result
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    inputs = [(feature_key, features)] + ([('labels_path', labels)] if labels else [])
    for key, path in inputs:
        if export_table_path(manifest, manifest_path, key).resolve() != path.resolve():
            raise ValueError('training_manifest_input_mismatch:' + key)
    result.update(export_metadata_status='recorded', manifest_sha256=hashlib.sha256(raw).hexdigest())
    for key in ('context_window_version', 'context_window_seconds', 'label_provenance', 'label_quality_tier', 'not_for_mainline', 'record_identity_version', 'partition'):
        result[key] = manifest.get(key)
    if 'wheel_order_version' in manifest:
        result['wheel_order_version'] = manifest['wheel_order_version']
    validation_path = features.parent / 'validation.json'
    if validation_path.exists():
        validation_bytes = validation_path.read_bytes()
        validation = json.loads(validation_bytes)
        if (validation.get('version') != 'training-export-validation-v1' or validation.get('passed') is not True
                or validation.get('manifest_sha256') != result['manifest_sha256']):
            raise ValueError('training_validation_manifest_mismatch')
        for key, path in inputs:
            table = validation.get('tables', {}).get(key, {})
            expected_hash = result['features_sha256'] if key == feature_key else result['labels_sha256']
            if table.get('sha256') != expected_hash or table.get('path') != str(path.resolve()):
                raise ValueError('training_validation_input_mismatch:' + key)
        result.update(validation_status='matched', validation_sha256=hashlib.sha256(validation_bytes).hexdigest())
    return result
