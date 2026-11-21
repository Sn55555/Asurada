"""Build a wheel containing the explicitly selected runtime asset tree."""
import hashlib
import json
from pathlib import Path
import shutil
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithAssets(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        destination = Path(self.build_lib) / 'asurada' / '_assets'
        if destination.exists():
            shutil.rmtree(destination)
        files = {root / 'data' / 'sample_session.jsonl'}
        for pattern in ('data/tracks/*.json', 'data/strategy/*.json',
                        'training/reports/**/*.json', 'training/reports/**/*.txt',
                        'scripts/macos_*.swift'):
            files.update(root.glob(pattern))
        manifest = []
        for source in sorted(files):
            if not source.is_file():
                raise FileNotFoundError(source)
            relative = source.relative_to(root)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            manifest.append({'path':relative.as_posix(), 'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
        (destination/'manifest.json').write_text(json.dumps({'version':'runtime-assets-v1','files':manifest},indent=2))


setup(cmdclass={'build_py':BuildWithAssets})
