"""Relocate a real small export; keep identity, hashes and provenance checks."""
import csv
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from asurada.training_export_bundle import package_training_export
from asurada.training_export_validation import TABLES, validate_export
from asurada.training_provenance import training_provenance
from regression_support import emit_result


def run():
    checks = {}
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / 'source'
        source.mkdir()
        manifest = {
            'partition': {'assignments': {'s1': 'train', 's2': 'test'}},
            'context_window_version': 'source-time-weighted-v1',
            'context_window_seconds': 1.0,
            'record_identity_version': 'session-epoch-overall-frame-v1',
            'label_provenance': {'kind': 'rule_derived', 'human_validated': False},
        }
        for key, count in TABLES:
            path = source / (key + '.csv')
            with path.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=['record_id', 'session_uid', 'split', 'source_record_id'])
                writer.writeheader()
                writer.writerows([
                    {'record_id': 'a', 'session_uid': 's1', 'split': 'train', 'source_record_id': 'a'},
                    {'record_id': 'b', 'session_uid': 's2', 'split': 'test', 'source_record_id': 'b'},
                ])
            manifest[key] = str(path)
            manifest[count] = 2
        (source / 'manifest.json').write_text(json.dumps(manifest))
        original_manifest = (source / 'manifest.json').read_bytes()
        original_validation = validate_export(source)
        destination = root / 'bundle'
        packaged = package_training_export(source, destination)
        checks['six_tables_packaged'] = packaged['passed'] and packaged['table_count'] == 6
        checks['original_provenance_verbatim'] = (destination / 'provenance/source-manifest.json').read_bytes() == original_manifest
        checks['source_manifest_unchanged'] = (source / 'manifest.json').read_bytes() == original_manifest
        checks['training_entry_filenames_compatible'] = (destination / 'strategy_action_features_v1.csv').is_file()
        relocated = root / 'elsewhere'
        destination.rename(relocated)
        shutil.rmtree(source)
        current = validate_export(relocated)
        checks['relocates_without_source'] = all(current['tables'][key]['sha256'] == original_validation['tables'][key]['sha256'] for key, _ in TABLES)
        (relocated / 'validation.json').write_text(json.dumps(current))
        proof = training_provenance(relocated / 'features.csv', relocated / 'labels.csv')
        checks['relocated_provenance_validated'] = proof['validation_status'] == 'matched'
        checks['no_human_quality_invented'] = proof['label_provenance']['human_validated'] is False
        try:
            package_training_export(relocated, relocated)
            checks['occupied_destination_rejected'] = False
        except ValueError as exc:
            checks['occupied_destination_rejected'] = str(exc) == 'training_bundle_destination_exists'
        payload = json.loads((relocated / 'manifest.json').read_text())
        for invalid in ('../escape.csv', str(root / 'absolute.csv')):
            (relocated / 'manifest.json').write_text(json.dumps({**payload, 'features_path': invalid}))
            try:
                validate_export(relocated)
                checks['reject_' + invalid] = False
            except ValueError as exc:
                checks['reject_' + invalid] = str(exc).startswith('nonportable_export_path:')
        (relocated / 'manifest.json').write_text(json.dumps(payload))
        (relocated / 'features.csv').write_text('record_id,session_uid,split\na,s1,val\n')
        try:
            package_training_export(relocated, root / 'invalid_bundle')
            checks['invalid_partition_not_packaged'] = False
        except ValueError:
            checks['invalid_partition_not_packaged'] = not (root / 'invalid_bundle').exists()
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())
