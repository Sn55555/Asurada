"""Read the core's atomic latest-state publication without scanning history."""
import json
import math
import os
import stat
import time
from pathlib import Path


class PublishedSessionProbe:
    def __init__(self, path, *, stale_after_ms=15000, wall_clock=time.time):
        self.path = Path(path)
        self.stale_after_ms = stale_after_ms
        self.wall_clock = wall_clock

    def __call__(self):
        row = self.read_snapshot()
        return row['session_uid'], row['session_epoch']

    def read_snapshot(self):
        # NONBLOCK plus fstat also rejects accidentally configured pipes/devices.
        fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4*1024*1024:
                raise ValueError('invalid_latest_snapshot_file')
            data = source.read(4*1024*1024+1)
        if len(data) > 4*1024*1024:
            raise ValueError('latest_snapshot_too_large')
        row = json.loads(data)
        uid, epoch, observed = row.get('session_uid'), row.get('session_epoch'), row.get('source_timestamp_ms')
        if row.get('contract_version') != 'telemetry-v1':
            raise ValueError('unsupported_latest_snapshot_contract')
        if not isinstance(uid, str) or not uid.strip() or isinstance(epoch,bool) or not isinstance(epoch,int) or epoch < 0:
            raise ValueError('invalid_latest_session_identity')
        if isinstance(observed,bool) or not isinstance(observed,(int,float)) or not math.isfinite(observed):
            raise ValueError('invalid_latest_snapshot_time')
        age = self.wall_clock()*1000-observed
        if age < 0 or age > self.stale_after_ms:
            raise ValueError('latest_snapshot_not_current')
        return row
