"""Scoped, expiring training records with immutable provenance and idempotency."""
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

KINDS = frozenset({'session_fact', 'verified_performance', 'user_preference'})


class TrainingMemory:
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, driver TEXT NOT NULL, kind TEXT NOT NULL, scope TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS memory_scope ON memories(driver, kind, scope, expires)')
            db.execute('''CREATE TABLE IF NOT EXISTS brake_habits
                (driver TEXT NOT NULL, track TEXT NOT NULL, corner TEXT NOT NULL,
                 payload TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                 PRIMARY KEY(driver, track, corner))''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, *, driver, kind, key, value, evidence, ttl_s, session_uid=None,
            epoch=None, verification=None, context=None):
        if not isinstance(driver,str) or not driver or not isinstance(key,str) or not key or kind not in KINDS or not math.isfinite(ttl_s) or ttl_s <= 0:
            raise ValueError('invalid_memory_record')
        if kind == 'session_fact' and (session_uid is None or not isinstance(epoch, int) or epoch < 0):
            raise ValueError('session_memory_requires_scope')
        if not isinstance(evidence, list) or not evidence or any(not isinstance(item, dict) or not item for item in evidence):
            raise ValueError('memory_requires_provenance')
        if kind == 'verified_performance' and (not isinstance(verification, dict) or not verification.get('method') or not verification.get('evidence_ids')):
            raise ValueError('performance_requires_verification')
        if kind == 'user_preference' and any(item.get('origin') != 'explicit_user_input' for item in evidence):
            raise ValueError('preference_requires_user_source')
        if kind == 'verified_performance':
            verification = self._verify_performance(driver, value, verification)
        scope = json.dumps([str(session_uid), epoch]) if kind == 'session_fact' else 'driver'
        payload = json.dumps(dict(key=key,value=value,evidence=evidence,verification=verification),
                             sort_keys=True,ensure_ascii=False,allow_nan=False)
        identity = json.dumps([driver,kind,scope,key],ensure_ascii=False)
        memory_id = hashlib.sha256(identity.encode()).hexdigest()
        now = self.clock()
        with self._connect() as db:
            existing = db.execute('SELECT payload FROM memories WHERE id=?',(memory_id,)).fetchone()
            if existing is not None and existing[0] != payload:
                raise ValueError('memory_identity_conflict')
            if context is not None:
                context.remaining()
            db.execute('INSERT OR IGNORE INTO memories VALUES (?,?,?,?,?,?,?)',
                       (memory_id,driver,kind,scope,payload,now,now+ttl_s))
        return memory_id

    def query(self, *, driver, kind, session_uid=None, epoch=None):
        if kind not in KINDS:
            raise ValueError('unknown_memory_kind')
        if kind == 'session_fact' and (session_uid is None or epoch is None):
            raise ValueError('session_memory_query_requires_scope')
        scope = json.dumps([str(session_uid),epoch]) if kind == 'session_fact' else 'driver'
        with self._connect() as db:
            rows = db.execute('SELECT id,payload,created,expires FROM memories WHERE driver=? AND kind=? AND scope=? AND expires>? ORDER BY created,id',
                              (driver,kind,scope,self.clock())).fetchall()
        return [dict(id=row[0],kind=kind,driver=driver,created_at=row[2],expires_at=row[3],**json.loads(row[1])) for row in rows]

    def purge_expired(self):
        with self._connect() as db:
            return db.execute('DELETE FROM memories WHERE expires<=?',(self.clock(),)).rowcount

    def set_review_detail(self, *, driver, detail, ttl_s=30*86400):
        """Explicit local user preference; changing it never edits racing facts."""
        if not isinstance(driver, str) or not driver.strip():
            raise ValueError('driver_required')
        if detail not in ('brief', 'detailed'):
            raise ValueError('unsupported_review_detail')
        return self._set_preference(driver, 'review_detail', detail, ttl_s, 'review_profile')

    def set_radio_straight(self, *, driver, ttl_s=30*86400):
        return self._set_preference(driver, 'radio_long_reason_straight', True, ttl_s, 'speech_control')

    def _set_preference(self, driver, key, value, ttl_s, entrypoint):
        if not isinstance(driver, str) or not driver.strip():
            raise ValueError('driver_required')
        if type(ttl_s) not in (int, float) or not math.isfinite(ttl_s) or ttl_s <= 0:
            raise ValueError('invalid_preference_ttl')
        identity = json.dumps([driver, 'user_preference', 'driver', key], ensure_ascii=False)
        memory_id = hashlib.sha256(identity.encode()).hexdigest()
        payload = json.dumps(dict(key=key, value=value,
            evidence=[{'origin':'explicit_user_input', 'entrypoint':entrypoint}], verification=None),
            sort_keys=True, ensure_ascii=False, allow_nan=False)
        now = self.clock()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT payload,expires FROM memories WHERE id=?', (memory_id,)).fetchone()
            # Retrying an unchanged live preference must not extend its lifetime.
            if existing is None or existing[0] != payload or existing[1] <= now:
                db.execute('INSERT INTO memories VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,created=excluded.created,expires=excluded.expires',
                           (memory_id, driver, 'user_preference', 'driver', payload, now, now+ttl_s))
        return memory_id

    def revoke_review_detail(self, *, driver):
        return self._revoke_preference(driver, 'review_detail')

    def revoke_radio_straight(self, *, driver):
        return self._revoke_preference(driver, 'radio_long_reason_straight')

    def _revoke_preference(self, driver, key):
        if not isinstance(driver, str) or not driver.strip():
            raise ValueError('driver_required')
        identity = json.dumps([driver, 'user_preference', 'driver', key], ensure_ascii=False)
        memory_id = hashlib.sha256(identity.encode()).hexdigest()
        with self._connect() as db:
            return db.execute("DELETE FROM memories WHERE id=? AND driver=? AND kind='user_preference'", (memory_id,driver)).rowcount

    def put_brake_habit(self, *, driver, track, corner, record):
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
        with self._connect() as db:
            result = db.execute('''INSERT INTO brake_habits(driver,track,corner,payload,revoked)
                VALUES (?,?,?,?,0) ON CONFLICT(driver,track,corner) DO UPDATE SET payload=excluded.payload
                WHERE brake_habits.revoked=0''', (driver, track, corner, payload))
            return result.rowcount == 1

    def revoke_brake_habit(self, *, driver, track, corner):
        with self._connect() as db:
            db.execute('''INSERT INTO brake_habits(driver,track,corner,payload,revoked)
                VALUES (?,?,?,'{}',1) ON CONFLICT(driver,track,corner) DO UPDATE SET revoked=1''',
                       (driver, track, corner))

    def brake_habits(self, *, driver, include_revoked=False):
        with self._connect() as db:
            rows = db.execute('''SELECT track,corner,payload,revoked FROM brake_habits
                WHERE driver=? AND (? OR revoked=0) ORDER BY track,corner''', (driver, include_revoked)).fetchall()
        return [dict(track=track, corner=corner, record=json.loads(payload), revoked=bool(revoked))
                for track, corner, payload, revoked in rows]

    def _verify_performance(self, driver, value, verification):
        ids = verification['evidence_ids']
        if verification['method'] != 'official_lap_delta_v1' or len(ids) != 2 or len(set(ids)) != 2:
            raise ValueError('unsupported_performance_verification')
        facts = []
        evidence_snapshots = []
        with self._connect() as db:
            for memory_id in ids:
                row = db.execute("SELECT payload FROM memories WHERE id=? AND driver=? AND kind='session_fact' AND expires>?",(memory_id,driver,self.clock())).fetchone()
                if row is None:
                    raise ValueError('performance_evidence_unavailable')
                original = json.loads(row[0])
                facts.append(original['value'])
                evidence_snapshots.append(dict(memory_id=memory_id,value=original['value'],evidence=original['evidence']))
        first, last = facts
        if first.get('track') != last.get('track'):
            raise ValueError('performance_track_mismatch')
        expected = dict(track=first['track'], baseline_time_ms=first['time_ms'],
                        observed_time_ms=last['time_ms'], delta_ms=last['time_ms']-first['time_ms'])
        if value != expected:
            raise ValueError('performance_value_not_verified')
        return dict(verification,evidence_snapshots=evidence_snapshots)
