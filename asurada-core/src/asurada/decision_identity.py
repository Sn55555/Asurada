"""Content identity for reproducible decision records, not an authenticity signature."""
import hashlib
import json
from dataclasses import asdict

VERSION = 'decision-content-v1'


def decision_content_id(record):
    payload = asdict(record)
    payload.pop('decision_id')
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()
