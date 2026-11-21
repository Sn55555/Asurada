"""Resolve versioned export paths without changing legacy working-dir semantics."""
from pathlib import Path


def export_table_path(manifest: dict, manifest_path: Path, key: str) -> Path:
    value = manifest.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError('invalid_export_path:' + key)
    path = Path(value)
    base = manifest.get('path_base')
    if base is None:
        return path  # Existing manifests used absolute paths or process cwd.
    if base != 'manifest_directory':
        raise ValueError('unsupported_export_path_base')
    root = manifest_path.parent.resolve()
    if path.is_absolute() or not (root / path).resolve().is_relative_to(root):
        raise ValueError('nonportable_export_path:' + key)
    return root / path
