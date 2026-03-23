from __future__ import annotations

import json
from pathlib import Path


class ReportWriter:
    """Writes structured analysis artifacts to disk."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, payload: dict) -> Path:
        path = self.directory / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
