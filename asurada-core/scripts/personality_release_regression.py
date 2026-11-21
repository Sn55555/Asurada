"""Rehearse the upgrade, export/rebuild and rollback on temporary profiles."""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asurada.personality_memory import export_evidence, rebuild_evidence, update_database
from asurada.training_memory import TrainingMemory
from regression_support import emit_result


def backup(source, destination):
    with closing(sqlite3.connect(source)) as old, closing(sqlite3.connect(destination)) as new:
        old.backup(new)


def old_reader(path):
    with closing(sqlite3.connect(path)) as database:
        if database.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("old_release_requires_v1")
        return (database.execute("SELECT stage FROM growth WHERE id=1").fetchone()[0],
                database.execute("SELECT COUNT(*) FROM evidence WHERE kind='finish'").fetchone()[0])


def run(root):
    candidate = root / "relationship.sqlite3"
    stable = root / "stable-relationship.sqlite3"
    rollback = root / "rollback-relationship.sqlite3"
    training = root / "training.sqlite3"
    preference = TrainingMemory(training)
    preference.set_review_detail(driver="release-fixture", detail="brief")
    preference.set_radio_straight(driver="release-fixture")
    for index in range(3):
        update_database(candidate, "race", {"race_id": f"fixture-{index}", "epoch": 0, "positive_events": []})
    with closing(sqlite3.connect(candidate)) as database, database:
        database.execute("DROP TABLE profile")
        database.execute("PRAGMA user_version=1")
    backup(candidate, stable)
    stable_hash = hashlib.sha256(stable.read_bytes()).hexdigest()
    old = old_reader(stable)

    upgraded = update_database(candidate)
    preference.revoke_radio_straight(driver="release-fixture")
    update_database(candidate, "race", {"race_id": "candidate-race", "epoch": 0, "positive_events": []})
    exported = export_evidence(candidate)
    recreated = root / "recreated.sqlite3"
    rebuild_evidence(exported, recreated)
    backup(stable, rollback)
    reopened = old_reader(rollback)

    return {
        "profile_migration_preserves_stage_and_history": old == (upgraded.stage, upgraded.races) == (1, 3),
        "evidence_export_rebuild_preserves_new_race": export_evidence(recreated) == exported
        and exported["relationship"]["races"] == 4,
        "rollback_uses_old_compatible_copy": reopened == old
        and hashlib.sha256(stable.read_bytes()).hexdigest() == stable_hash,
        "review_preference_and_radio_revocation_independent_of_rollback": {
            record["key"]: record["value"] for record in TrainingMemory(training).query(
                driver="release-fixture", kind="user_preference")
        } == {"review_detail": "brief"},
        "upgraded_database_ready_to_resume": update_database(candidate).races == 4,
    }


if __name__ == "__main__":
    with TemporaryDirectory(dir="/tmp") as temp, patch.dict(os.environ, {"ASURADA_DRIVER_ID": "release-fixture"}):
        emit_result(run(Path(temp)))
