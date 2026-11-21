"""Incremental debt gate: only files absent before this repair get an 800-line cap."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from regression_support import emit_result


EXTENSIONS = {'.py', '.js', '.mjs', '.ts', '.tsx', '.css', '.html', '.swift', '.sh'}
IGNORED_PARTS = {'node_modules', '__pycache__', '.venv', 'vendor', 'build'}


def inspect_sources(root: Path, baseline: dict):
    existing = set(baseline['existing_files'])
    limit = baseline['new_file_limit']
    violations = []
    inherited = []
    checked = 0
    for folder in baseline['roots']:
        for path in sorted((root / folder).rglob('*')):
            if not path.is_file() or path.suffix not in EXTENSIONS or IGNORED_PARTS.intersection(path.parts):
                continue
            relative = path.relative_to(root).as_posix()
            lines = len(path.read_text(encoding='utf-8').splitlines())
            checked += 1
            if lines > limit:
                row = {'path': relative, 'lines': lines}
                (inherited if relative in existing else violations).append(row)
    return {'checked_sources': checked, 'new_file_violations': violations, 'existing_large_files': inherited}


def run():
    path = Path(__file__).with_name('source_size_baseline.json')
    baseline = json.loads(path.read_text())
    result = inspect_sources(Path(__file__).resolve().parents[2], baseline)
    checks = {'new_source_files_under_800_lines': not result['new_file_violations']}
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'old.py').write_text('\n' * 900)
        (root / 'new.py').write_text('\n' * 801)
        (root / 'exact.py').write_text('\n' * 800)
        sample = inspect_sources(root, {'existing_files': ['old.py'], 'new_file_limit': 800, 'roots': ['.']})
        checks['existing_dirty_sources_are_grandfathered'] = sample['existing_large_files'] == [{'path': 'old.py', 'lines': 900}]
        checks['new_801_line_source_rejected'] = sample['new_file_violations'] == [{'path': 'new.py', 'lines': 801}]
        checks['exact_800_line_source_accepted'] = not any(row['path'] == 'exact.py' for row in sample['new_file_violations'])
    return {'passed': all(checks.values()), 'checks': checks, 'size_report': result}


if __name__ == '__main__':
    emit_result(run())
