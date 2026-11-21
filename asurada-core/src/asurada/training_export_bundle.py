"""Copy a validated export into a relocatable, hash-checked training bundle."""
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from .training_export_paths import export_table_path
from .training_export_validation import TABLES, validate_export
from .training_provenance import file_digest


def package_training_export(source: Path, destination: Path) -> dict:
    """Publish only complete copies; preserve input artifacts and original proof.

    The bundle contains the six training tables, not raw telemetry. Moving it
    requires re-running validation to bind the new location; no model is trained
    or activated. Unversioned/invalid legacy exports must be regenerated first.
    """
    source, destination = source.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError('training_bundle_destination_exists')
    if destination.is_relative_to(source):
        raise ValueError('training_bundle_destination_inside_source')
    validation = validate_export(source)
    manifest_bytes = (source / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.training-bundle-', dir=destination.parent) as staging:
        root = Path(staging)
        bundled = dict(manifest)
        bundled['path_base'] = 'manifest_directory'
        for key, _ in TABLES:
            path = export_table_path(manifest, source / 'manifest.json', key)
            # Use fixed keys for unique names; never rely on unrelated basenames.
            stem = key.removesuffix('_path')
            filename = stem + ('.csv' if key in {'features_path', 'labels_path'} else '_v1.csv')
            shutil.copyfile(path, root / filename)
            if file_digest(root / filename) != validation['tables'][key]['sha256']:
                raise ValueError('training_bundle_copy_hash_mismatch:' + key)
            bundled[key] = filename
        provenance = root / 'provenance'
        provenance.mkdir()
        (provenance / 'source-manifest.json').write_bytes(manifest_bytes)
        (provenance / 'source-validation.json').write_text(json.dumps(validation, indent=2) + '\n')
        # Raw capture references remain historical provenance, not resolvable
        # bundle inputs. The source manifest is retained verbatim for auditing.
        bundled.pop('sample_metadata_path', None)
        bundled.pop('samples', None)
        bundled['source_export'] = {
            'manifest': 'provenance/source-manifest.json',
            'manifest_sha256': validation['manifest_sha256'],
            'validation': 'provenance/source-validation.json',
            'raw_capture_included': False,
        }
        (root / 'manifest.json').write_text(json.dumps(bundled, ensure_ascii=False, indent=2) + '\n')
        staged_validation = validate_export(root)
        if validate_export(source) != validation or (source / 'manifest.json').read_bytes() != manifest_bytes:
            raise ValueError('training_bundle_source_changed')
        # TemporaryDirectory cleanup removes only our staging path on failure.
        # The destination must not overwrite an existing collection.
        if destination.exists():
            raise ValueError('training_bundle_destination_exists')
        root.rename(destination)
    final_validation = validate_export(destination)
    (destination / 'validation.json').write_text(json.dumps(final_validation, indent=2) + '\n')
    return {
        'version': 'training-export-bundle-v1', 'passed': True,
        'table_count': len(staged_validation['tables']),
        'source_manifest_sha256': validation['manifest_sha256'],
        'manifest_sha256': final_validation['manifest_sha256'],
        'validation': final_validation,
        'scope': 'portable validated training tables; excludes raw capture and human quality approval',
    }
