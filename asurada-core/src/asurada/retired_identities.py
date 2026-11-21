"""Exact lifetime tombstones with bounded Python memory.

Evicting a UID permits an old packet to reopen a retired race. Keep the first
identities in memory and spill later identities to a private SQLite temporary
database instead. SQLite deletes that database on close; no replay archive or
user data is removed. Storage errors propagate rather than forgetting history.
"""
from __future__ import annotations

import sqlite3
import threading


class RetiredIdentities:
    def __init__(self, *, memory_capacity: int = 256) -> None:
        if type(memory_capacity) is not int or memory_capacity < 1:
            raise ValueError('invalid_tombstone_capacity')
        self.memory_capacity = memory_capacity
        self._memory: set[str] = set()
        self._database: sqlite3.Connection | None = None
        self._spilled = 0
        self._lock = threading.RLock()
        self._closed = False

    def __contains__(self, identity: str) -> bool:
        with self._lock:
            self._check_open()
            return identity in self._memory or (self._database is not None and
                self._database.execute('SELECT 1 FROM retired WHERE uid=?', (identity,)).fetchone() is not None)

    def add(self, identity: str) -> None:
        if not isinstance(identity, str):
            raise TypeError('tombstone_identity_must_be_string')
        with self._lock:
            self._check_open()
            if identity in self:
                return
            if len(self._memory) < self.memory_capacity:
                self._memory.add(identity)
                return
            if self._database is None:
                self._database = sqlite3.connect('', check_same_thread=False, isolation_level=None)
                # Bound SQLite's page cache too; don't merely move the unbounded
                # Python set into an in-memory database.
                self._database.execute('PRAGMA cache_size=-256')
                self._database.execute('CREATE TABLE retired (uid TEXT PRIMARY KEY) WITHOUT ROWID')
            self._database.execute('INSERT INTO retired VALUES (?)', (identity,))
            self._spilled += 1

    def __len__(self) -> int:
        with self._lock:
            return len(self._memory) + self._spilled

    def health(self) -> dict[str, int | str]:
        with self._lock:
            return {'mode': 'exact_memory_and_temporary_disk', 'memory_capacity': self.memory_capacity,
                    'memory_count': len(self._memory), 'spilled_count': self._spilled,
                    'total_count': len(self), 'forgotten_count': 0}

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError('tombstone_store_closed')

    def close(self) -> None:
        with self._lock:
            if self._database is not None:
                self._database.close()
                self._database = None
            self._closed = True

    def __del__(self) -> None:
        database = getattr(self, '_database', None)
        if database is not None:
            database.close()
