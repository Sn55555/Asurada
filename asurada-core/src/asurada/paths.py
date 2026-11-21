"""Separate read-only packaged assets from writable runtime state."""
import os
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]
IS_SOURCE_CHECKOUT = (SOURCE_ROOT / 'pyproject.toml').is_file() and (SOURCE_ROOT / 'data').is_dir()
ASSET_ROOT = Path(os.environ['ASURADA_ASSET_ROOT']).expanduser().resolve() if os.getenv('ASURADA_ASSET_ROOT') else (
    SOURCE_ROOT if IS_SOURCE_CHECKOUT else Path(__file__).resolve().parent / '_assets')
RUNTIME_ROOT = Path(os.environ['ASURADA_RUNTIME_DIR']).expanduser().resolve() if os.getenv('ASURADA_RUNTIME_DIR') else (
    SOURCE_ROOT / 'runtime_logs' if IS_SOURCE_CHECKOUT else Path.home() / '.local' / 'state' / 'asurada')
