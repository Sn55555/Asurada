"""Validate completed export tables before model training consumes them."""
import csv
import json
from pathlib import Path
from .training_provenance import file_digest
from .context_window import CONTEXT_WINDOW_SECONDS
from .training_export_paths import export_table_path


TABLES = (
    ('features_path', 'record_count'), ('labels_path', 'record_count'),
    ('tactical_features_path', 'tactical_record_count'), ('event_features_path', 'event_record_count'),
    ('attack_features_path', 'attack_record_count'), ('strategy_action_features_path', 'strategy_action_record_count'),
)


def validate_export(directory):
    manifest_path = Path(directory) / 'manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    assignments = manifest['partition']['assignments']
    if not assignments or not set(assignments.values()) <= {'train', 'val', 'test'}:
        raise ValueError('invalid_export_assignments')
    if (manifest.get('context_window_version') != 'source-time-weighted-v1'
            or isinstance(manifest.get('context_window_seconds'), bool)
            or manifest.get('context_window_seconds') != CONTEXT_WINDOW_SECONDS):
        raise ValueError('export_window_not_current')
    if manifest.get('record_identity_version') != 'session-epoch-overall-frame-v1':
        raise ValueError('unsupported_export_identity')
    tables, main_ids = {}, None
    for path_key, count_key in TABLES:
        path = export_table_path(manifest, manifest_path, path_key)
        before = path.stat()
        ids = {}
        sessions = {}
        with path.open(newline='', encoding='utf-8') as handle:
            reader = csv.DictReader(handle)
            if not {'record_id', 'session_uid', 'split'} <= set(reader.fieldnames or []):
                raise ValueError('missing_export_identity_columns:' + path_key)
            for row in reader:
                record_id, uid = row['record_id'], row['session_uid']
                if not record_id or record_id in ids:
                    raise ValueError('duplicate_or_missing_record_id:' + path_key)
                if uid not in assignments or row['split'] != assignments[uid]:
                    raise ValueError('export_row_partition_mismatch:' + path_key)
                if path_key not in {'features_path', 'labels_path'}:
                    source = row.get('source_record_id') or record_id
                    if source not in main_ids or main_ids[source] != uid:
                        raise ValueError('derived_export_source_missing:' + path_key)
                ids[record_id] = uid
                sessions[uid] = sessions.get(uid, 0) + 1
        expected = manifest[count_key]
        if isinstance(expected, bool) or not isinstance(expected, int) or len(ids) != expected:
            raise ValueError('export_row_count_mismatch:' + path_key)
        if path_key == 'features_path':
            main_ids = ids
            if not ids: raise ValueError('empty_main_export')
            if set(sessions) != set(assignments):
                raise ValueError('configured_export_session_missing')
        if path_key == 'labels_path' and ids != main_ids:
            raise ValueError('export_feature_label_identity_mismatch')
        digest = file_digest(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('export_changed_during_validation:' + path_key)
        tables[path_key] = {'path': str(path.resolve()), 'rows': len(ids), 'sessions': sessions,
                            'sha256': digest}
    if manifest_path.read_bytes() != manifest_bytes:
        raise ValueError('export_manifest_changed_during_validation')
    return {'version': 'training-export-validation-v1', 'passed': True,
            'manifest_sha256': file_digest(manifest_path), 'tables': tables,
            'scope': 'counts, unique IDs, configured partitions and feature-label identity; not model quality'}
