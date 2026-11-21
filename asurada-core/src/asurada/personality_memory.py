"""Versioned evidence and race-boundary progression for a local driver."""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any

from .async_sink import AsyncRuntimeSink
from .pit_feedback import driver_profile_id, evidence_path, load_race_cooperation

APPLICATION_ID = 1095979596
SCHEMA_VERSION = 2
LEGACY_EXPORT_VERSION = "asurada-relationship-evidence-v1"
EVIDENCE_EXPORT_VERSION = "asurada-relationship-evidence-v2"
GROWTH_THRESHOLDS = ((3, 0), (8, 2), (16, 5))
H2_COOPERATION_RACES = 2


@dataclass(frozen=True)
class Relationship:
    races: int = 0
    positive_races: int = 0
    acknowledgements: int = 0
    stage: int = 0
    memory_kind: str | None = None
    cooperation_races: int = 0
    last_cooperation: dict | None = None


def relationship_path() -> Path:
    configured = os.getenv("ASURADA_RELATIONSHIP_DB")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".asurada" / "relationship.sqlite3"


class RelationshipStore:
    """One local driver per database. A committed snapshot is safe to read without IO."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.driver_id = driver_profile_id()
        self.pit_path = evidence_path()
        self.current = Relationship()
        self._worker = AsyncRuntimeSink(self, capacity=64)
        self._worker.append("load", None)

    def record_race(self, evidence: dict[str, Any]) -> bool:
        return self._worker.append("race", evidence)

    def refresh(self) -> None:
        self._worker.append("refresh", None)

    def reconcile(self) -> bool:
        return self._worker.append("load", None)

    def health(self) -> dict[str, Any]:
        return self._worker.snapshot()

    def close(self) -> bool:
        return self._worker.close()

    def append(self, operation: str, evidence: dict[str, Any] | str | None) -> None:
        # Called by the worker, never the packet or audio thread.
        for attempt in range(3):
            try:
                if operation == "refresh":
                    if self.path.exists():
                        with closing(_open_readonly(self.path, driver_id=self.driver_id)) as db:
                            self.current = _read_relationship(db)
                    else:
                        self.current = Relationship()
                else:
                    self.current = update_database(
                        self.path, operation, evidence, driver_id=self.driver_id, pit_path=self.pit_path)
                return
            except sqlite3.OperationalError as exc:
                retryable = (getattr(exc, "sqlite_errorname", "") in {"SQLITE_BUSY", "SQLITE_LOCKED"}
                             or str(exc).startswith(("database is locked", "database table is locked")))
                if attempt == 2 or not retryable:
                    raise
                time.sleep(.05 * (attempt + 1))


def _initialize_schema(db: sqlite3.Connection, driver_id: str) -> None:
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in {0, 1, SCHEMA_VERSION}:
        raise ValueError("unsupported_relationship_schema")
    application = db.execute("PRAGMA application_id").fetchone()[0]
    if application != APPLICATION_ID:
        if version != 0 or application != 0 or db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
            raise ValueError("not_an_asurada_relationship_database")
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
    db.execute("""CREATE TABLE IF NOT EXISTS evidence(
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, race_id TEXT NOT NULL,
                positive INTEGER NOT NULL, payload TEXT NOT NULL)""")
    db.execute("CREATE TABLE IF NOT EXISTS growth(id INTEGER PRIMARY KEY CHECK(id=1), stage INTEGER NOT NULL)")
    db.execute("INSERT OR IGNORE INTO growth VALUES (1, 0)")
    db.execute("CREATE TABLE IF NOT EXISTS profile(id INTEGER PRIMARY KEY CHECK(id=1), driver_id TEXT NOT NULL)")
    db.execute("INSERT OR IGNORE INTO profile VALUES (1, ?)", (driver_id,))
    if db.execute("SELECT driver_id FROM profile WHERE id=1").fetchone()[0] != driver_id:
        raise ValueError("relationship_profile_mismatch")
    db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def _read_relationship(db: sqlite3.Connection) -> Relationship:
    races, positives = db.execute(
        """SELECT COUNT(*), COALESCE(SUM(positive OR EXISTS(
               SELECT 1 FROM evidence a WHERE a.id = 'ack:' || f.race_id)), 0)
           FROM evidence f WHERE f.kind='finish'"""
    ).fetchone()
    stage = db.execute("SELECT stage FROM growth WHERE id=1").fetchone()[0]
    acknowledgements = db.execute(
        "SELECT COUNT(*) FROM evidence WHERE kind='acknowledgement'"
    ).fetchone()[0]
    memory = db.execute(
        "SELECT kind FROM evidence WHERE kind IN ('overtake', 'fastest_lap') ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    cooperation_races = db.execute("SELECT COUNT(DISTINCT race_id) FROM evidence WHERE kind='pit_cooperation'").fetchone()[0]
    cooperation = db.execute("""SELECT c.payload FROM evidence c JOIN evidence f ON f.id='race:' || c.race_id
                             WHERE c.kind='pit_cooperation' ORDER BY f.rowid DESC, c.rowid DESC LIMIT 1""").fetchone()
    return Relationship(races, positives, acknowledgements, stage, memory[0] if memory else None,
                        cooperation_races, json.loads(cooperation[0]) if cooperation else None)


def _add_cooperation(db: sqlite3.Connection, item: dict, driver_id: str) -> bool:
    if (not isinstance(item, dict) or item.get("driver_id") != driver_id
            or any(not isinstance(item.get(key), str) or not item[key] for key in
                   ("race_id", "recommendation_id", "recommendation_snapshot_id", "reply_snapshot_id",
                    "outcome_snapshot_id"))
            or type(item.get("epoch")) is not int
            or any(type(item.get(key)) not in {int, float} or not 0 <= item[key] <= 100
                   for key in ("wear_before_pct", "wear_after_pct"))
            or item["wear_before_pct"] <= item["wear_after_pct"]):
        raise ValueError("invalid_pit_cooperation")
    finish = db.execute("SELECT payload FROM evidence WHERE id=? AND kind='finish'",
                        (f'race:{item["race_id"]}',)).fetchone()
    if finish is None or json.loads(finish[0]).get("epoch") != item["epoch"]:
        raise ValueError("pit_cooperation_requires_verified_finish")
    return db.execute("INSERT OR IGNORE INTO evidence VALUES (?, 'pit_cooperation', ?, 1, ?)",
                      ("coop:" + item["recommendation_id"], item["race_id"], json.dumps(item))).rowcount == 1


def _import_cooperation(db: sqlite3.Connection, path: Path, driver_id: str) -> bool:
    if not path.exists():
        return False
    finishes = db.execute("""SELECT payload FROM
        (SELECT payload, rowid FROM evidence WHERE kind='finish' ORDER BY rowid DESC LIMIT 50)
        ORDER BY rowid""")
    races = []
    for payload, in finishes:
        finish = json.loads(payload)
        epoch = finish.get("epoch")
        if type(epoch) is int:
            races.append((finish["race_id"], epoch))
    imported = False
    for item in load_race_cooperation(path, driver_id=driver_id, races=races):
        imported |= _add_cooperation(db, item, driver_id)
    return imported


def _apply(db: sqlite3.Connection, operation: str, evidence, *, driver_id: str,
           pit_path: Path | None = None, legacy_growth: bool = False) -> Relationship:
    inserted = False
    if operation == "reset":
        db.execute("DELETE FROM evidence")
        db.execute("UPDATE growth SET stage=0")
    elif operation == "race":
        race_id = evidence["race_id"]
        positives = evidence["positive_events"]
        inserted = db.execute(
            "INSERT OR IGNORE INTO evidence VALUES (?, 'finish', ?, ?, ?)",
            (f"race:{race_id}", race_id, bool(positives), json.dumps(evidence)),
        ).rowcount == 1
        if inserted:
            db.executemany(
                "INSERT OR IGNORE INTO evidence VALUES (?, ?, ?, 1, ?)",
                ((event["id"], event["kind"], race_id, json.dumps(event)) for event in positives),
            )
    elif operation == "acknowledgement":
        row = db.execute("SELECT 1 FROM evidence WHERE id=? AND kind='finish'", (f"race:{evidence}",)).fetchone()
        if row is None:
            raise ValueError("unknown_verified_race")
        db.execute("INSERT OR IGNORE INTO evidence VALUES (?, 'acknowledgement', ?, 1, '{}')",
                   (f"ack:{evidence}", evidence))
    elif operation == "pit_cooperation":
        inserted = _add_cooperation(db, evidence, driver_id)
    elif operation == "revoke_pit_cooperation":
        if not isinstance(evidence, str) or not evidence:
            raise ValueError("invalid_pit_cooperation_reference")
        db.execute("""INSERT INTO evidence VALUES (?, 'pit_cooperation_revoked', '', 0, '{}')
            ON CONFLICT(id) DO UPDATE SET kind='pit_cooperation_revoked', race_id='', positive=0, payload='{}'""",
                   ("coop:" + evidence,))
    elif operation != "load":
        raise ValueError("unknown_relationship_operation")

    if pit_path is not None and operation in {"race", "load"}:
        inserted |= _import_cooperation(db, pit_path, driver_id)
    relation = _read_relationship(db)
    if inserted and relation.stage < len(GROWTH_THRESHOLDS):
        minimum_races, minimum_positive = GROWTH_THRESHOLDS[relation.stage]
        cooperation_ready = (legacy_growth or relation.stage != 1 or relation.cooperation_races >= H2_COOPERATION_RACES)
        if relation.races >= minimum_races and relation.positive_races >= minimum_positive and cooperation_ready:
            db.execute("UPDATE growth SET stage=? WHERE id=1", (relation.stage + 1,))
            return replace(relation, stage=relation.stage + 1)
    return relation


def update_database(path: Path, operation: str = "load", evidence=None, *,
                    driver_id: str | None = None, pit_path: Path | None = None) -> Relationship:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=0.5)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        owner = driver_profile_id() if driver_id is None else driver_id
        _initialize_schema(db, owner)
        return _apply(db, operation, evidence, driver_id=owner, pit_path=pit_path)


def _open_readonly(path: Path, *, driver_id: str | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=.5)
    try:
        db.execute("BEGIN")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if (db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                or version not in {1, SCHEMA_VERSION}):
            raise ValueError("unsupported_relationship_schema")
        if (version == SCHEMA_VERSION
                and db.execute("SELECT driver_id FROM profile WHERE id=1").fetchone()[0]
                != (driver_id or driver_profile_id())):
            raise ValueError("relationship_profile_mismatch")
    except (ValueError, sqlite3.Error):
        db.close()
        raise
    return db


def growth_progress(path: Path) -> dict[str, Any]:
    with closing(_open_readonly(path)) as db:
        relation = _read_relationship(db)
        by_kind = dict(db.execute("SELECT kind, COUNT(*) FROM evidence GROUP BY kind").fetchall())
    next_stage = None
    if relation.stage < len(GROWTH_THRESHOLDS):
        finishes, positives = GROWTH_THRESHOLDS[relation.stage]
        missing_finishes = max(0, finishes - relation.races)
        missing_positives = max(0, positives - relation.positive_races)
        next_stage = {
            "stage": f"H{relation.stage + 1}",
            "required": {"races": finishes, "positive_races": positives},
            "missing": {"races": missing_finishes, "positive_races": missing_positives},
            "promotion_on": "next_verified_finish",
            "waiting_only_for_finish": not (missing_finishes or missing_positives),
        }
        if relation.stage == 1:
            missing_cooperation = max(0, H2_COOPERATION_RACES - relation.cooperation_races)
            next_stage["required"]["cooperation_races"] = H2_COOPERATION_RACES
            next_stage["missing"]["cooperation_races"] = missing_cooperation
            next_stage["waiting_only_for_finish"] &= not missing_cooperation
    return {**asdict(relation), "stage_label": f"H{relation.stage}", "evidence_counts": by_kind,
            "next": next_stage}


def export_evidence(path: Path) -> dict[str, Any]:
    with closing(_open_readonly(path)) as db:
        relationship = asdict(_read_relationship(db))
        events = []
        for identity, kind, race_id, payload in db.execute(
                """SELECT id, kind, race_id, payload FROM evidence
                   WHERE kind IN ('finish','acknowledgement','pit_cooperation','pit_cooperation_revoked')
                   ORDER BY rowid"""):
            event = {"kind": kind, "race_id": race_id}
            if kind in {"finish", "pit_cooperation"}:
                event["payload"] = json.loads(payload)
            elif kind == "pit_cooperation_revoked":
                event["recommendation_id"] = identity.removeprefix("coop:")
            events.append(event)
    return {"version": EVIDENCE_EXPORT_VERSION, "driver_id": driver_profile_id(),
            "relationship": relationship, "events": events}


def rebuild_evidence(bundle: dict[str, Any], destination: Path) -> Relationship:
    """Replay recorded facts into a fresh DB and publish it only on exact agreement."""
    if not isinstance(bundle, dict) or bundle.get("version") not in {EVIDENCE_EXPORT_VERSION, LEGACY_EXPORT_VERSION}:
        raise ValueError("unsupported_relationship_export")
    if not isinstance(bundle.get("events"), list) or not isinstance(bundle.get("relationship"), dict):
        raise ValueError("invalid_relationship_export")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    legacy = bundle["version"] == LEGACY_EXPORT_VERSION
    driver_id = driver_profile_id()
    if not legacy and bundle.get("driver_id") != driver_id:
        raise ValueError("relationship_profile_mismatch")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".relationship-rebuild-", dir=destination.parent) as work:
        prepared = Path(work) / "relationship.sqlite3"
        with closing(sqlite3.connect(prepared)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            _initialize_schema(db, driver_id)
            seen = set()
            positive_ids = set()
            cooperation_ids = set()
            for event in bundle["events"]:
                if not isinstance(event, dict):
                    raise ValueError("invalid_relationship_event")
                kind, race_id = event.get("kind"), event.get("race_id")
                if not legacy and kind in {"pit_cooperation", "pit_cooperation_revoked"}:
                    payload = event.get("payload") if kind == "pit_cooperation" else {}
                    identity = payload.get("recommendation_id") if isinstance(payload, dict) else None
                    identity = identity or event.get("recommendation_id")
                    if (not isinstance(identity, str) or not identity or identity in cooperation_ids
                            or (kind == "pit_cooperation" and (
                                not isinstance(payload, dict) or payload.get("race_id") != race_id))):
                        raise ValueError("invalid_or_duplicate_pit_cooperation")
                    cooperation_ids.add(identity)
                    operation = "pit_cooperation" if kind == "pit_cooperation" else "revoke_pit_cooperation"
                    _apply(db, operation, payload if kind == "pit_cooperation" else identity, driver_id=driver_id)
                    continue
                if (kind not in ("finish", "acknowledgement") or not isinstance(race_id, str) or not race_id
                        or (kind, race_id) in seen):
                    raise ValueError("invalid_or_duplicate_relationship_event")
                seen.add((kind, race_id))
                if kind == "finish":
                    payload = event.get("payload")
                    if not isinstance(payload, dict) or payload.get("race_id") != race_id:
                        raise ValueError("invalid_relationship_finish_payload")
                    positives = payload.get("positive_events")
                    if not isinstance(positives, list) or any(
                            not isinstance(item, dict) or item.get("kind") not in ("overtake", "fastest_lap")
                            or not isinstance(item.get("id"), str) or not item["id"] for item in positives):
                        raise ValueError("invalid_relationship_positive_evidence")
                    for item in positives:
                        if item["id"] in positive_ids:
                            raise ValueError("duplicate_relationship_positive_evidence")
                        positive_ids.add(item["id"])
                    _apply(db, "race", payload, driver_id=driver_id, legacy_growth=legacy)
                else:
                    _apply(db, "acknowledgement", race_id, driver_id=driver_id)
            relationship = _read_relationship(db)
            expected = dict(bundle["relationship"])
            if legacy:
                expected.update(cooperation_races=0, last_cooperation=None)
            else:
                stage = expected.get("stage")
                # A migrated or later revoked history can have attained a higher
                # stage than currently replayable evidence. Existing stages are sticky.
                if type(stage) is not int or not 0 <= stage <= len(GROWTH_THRESHOLDS):
                    raise ValueError("invalid_exported_growth_stage")
                if stage and (relationship.races < GROWTH_THRESHOLDS[stage - 1][0]
                              or relationship.positive_races < GROWTH_THRESHOLDS[stage - 1][1]):
                    raise ValueError("invalid_exported_growth_stage")
                db.execute("UPDATE growth SET stage=? WHERE id=1", (stage,))
                relationship = replace(relationship, stage=stage)
            if asdict(relationship) != expected:
                raise ValueError("relationship_export_does_not_rebuild")
        prepared.chmod(0o600)
        os.link(prepared, destination)
    return relationship


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or manage the local Asurada relationship profile.")
    parser.add_argument("--db", type=Path, default=relationship_path())
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("status")
    actions.add_parser("reset")
    actions.add_parser("history")
    actions.add_parser("progress")
    export = actions.add_parser("export")
    export.add_argument("--output", type=Path, help="Write to a new file. Defaults to stdout.")
    rebuild = actions.add_parser("rebuild")
    rebuild.add_argument("source", type=Path, help="Evidence export. --db must name a new database.")
    acknowledge = actions.add_parser("acknowledge")
    acknowledge.add_argument("race_id", help="Verified F1 session UID shown by the history command.")
    revoke = actions.add_parser("revoke-pit-cooperation")
    revoke.add_argument("recommendation_id", help="Cooperation reference to stop using.")
    args = parser.parse_args()
    if args.action not in {"status", "rebuild"} and not args.db.exists():
        parser.error("relationship profile does not exist")
    try:
        if args.action == "history":
            with closing(_open_readonly(args.db)) as db:
                values = [json.loads(row[0]) for row in db.execute(
                    "SELECT payload FROM evidence WHERE kind='finish' ORDER BY rowid DESC LIMIT 50"
                )]
        elif args.action == "progress":
            values = growth_progress(args.db)
        elif args.action == "export":
            values = export_evidence(args.db)
            if args.output is not None:
                with tempfile.TemporaryDirectory(prefix=".relationship-export-", dir=args.output.parent) as work:
                    prepared = Path(work) / "evidence.json"
                    prepared.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    prepared.chmod(0o600)
                    os.link(prepared, args.output)
                return
        elif args.action == "rebuild":
            values = asdict(rebuild_evidence(json.loads(args.source.read_text(encoding="utf-8")), args.db))
        else:
            operation = {"status": "load", "reset": "reset", "acknowledge": "acknowledgement",
                         "revoke-pit-cooperation": "revoke_pit_cooperation"}[args.action]
            value = getattr(args, "race_id", None) or getattr(args, "recommendation_id", None)
            values = asdict(update_database(args.db, operation, value))
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(values, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
