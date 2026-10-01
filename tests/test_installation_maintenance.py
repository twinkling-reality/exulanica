"""One maintenance pass exports withdrawals on change, purges into the backups, and reports.

Each property is one the installation facts depend on: the status file it writes is what the API
reads to say whether withdrawals are current, whether a backup has been proved, and how late each
queue is, so a pass that failed must say so in that file rather than leave the last good one.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import replace
from pathlib import Path

import psycopg
from exulanica.api.installation import (
    Installation,
    RecoveryPolicy,
    installation_facts,
    load_profile,
)
from exulanica.db.roles import provision_backup_role
from exulanica.orchestration.installation.custody import exports
from exulanica.orchestration.installation.maintenance import Maintenance, MaintenanceStores
from exulanica.store.configured import local_content_stores

from test_installation_facts import PROFILES, _services
from test_local_database_postgres import _require_server_binaries
from test_purge import _PURGE_PASSWORD, _PURGE_ROLE
from test_purge import purged as purged
from test_restore_replay import _capture

_ROLE = "exulanica_maintenance_test"
_PASSWORD = "maintenance-test-" + uuid.uuid4().hex
_POLICY = RecoveryPolicy(
    export_interval_seconds=300,
    max_export_lag_seconds=600,
    backup_interval_seconds=86400,
    backup_retention_days=30,
    verification_interval_seconds=604800,
)


def _backup_root(tmp_path):
    """Beside the fixture's data directory, not in it: a backup copy inside the content store is
    refused."""
    return tmp_path.with_name(f"{tmp_path.name}-backup-store")


def _maintenance(purged, tmp_path, **changes):
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        provision_backup_role(connection, role=_ROLE, password=_PASSWORD)
    maintenance = Maintenance(
        backup_url=purged.database(role=_ROLE, password=_PASSWORD).url,
        purge_url=purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD).url,
        custody=tmp_path / "custody",
        backup_directory=tmp_path / "backup-sets",
        status_path=tmp_path / "status" / "maintenance.json",
        stores=MaintenanceStores(
            live=local_content_stores(purged.store.root.parent),
            backup=local_content_stores(_backup_root(tmp_path)),
        ),
        policy=_POLICY,
        identity={"profile": "single-host"},
        restore_state_path=None,
        backup_domains=(purged.store.root, _backup_root(tmp_path)),
        backup_role=_ROLE,
    )
    return replace(maintenance, **changes)


def test_a_first_pass_exports_backs_up_verifies_and_reports(purged, tmp_path):
    _require_server_binaries()
    maintenance = _maintenance(purged, tmp_path)
    status = maintenance.run_pass()
    assert status["failures"] == []
    # One export on the first look, and one the backup set takes after its own dump.
    assert len(exports(tmp_path / "custody")) == 2
    assert status["withdrawal_export"]["lag_seconds"] >= 0
    assert status["last_backup_at"] and status["last_verified_backup_at"]
    assert set(status["queues"]) == {
        "derivatives",
        "generated_tiles",
        "pose_scene",
        "materials",
        "comparison",
    }
    written = json.loads((tmp_path / "status" / "maintenance.json").read_bytes())
    assert written["written_at"] == status["written_at"]
    # The API reads exactly this file.
    installation = Installation(
        profile=load_profile(PROFILES / "single-host.json"),
        code_revision=None,
        images={},
        maintenance_status_path=tmp_path / "status" / "maintenance.json",
    )
    facts = installation_facts(_services(purged, installation))
    components = {entry["component"]: entry for entry in facts["components"]}
    assert components["maintenance"]["state"] == "ready"
    assert components["derivatives"]["state"] == "configured"
    assert facts["recovery"]["withdrawal_authority"]["kind"] == "periodic_export"


def test_an_export_follows_a_withdrawal_and_not_an_idle_pass(purged, tmp_path):
    maintenance = _maintenance(purged, tmp_path)
    maintenance.run_pass()
    first = len(exports(tmp_path / "custody"))
    maintenance.run_pass()
    assert len(exports(tmp_path / "custody")) == first
    purged.tombstone_the_capture(_capture(purged))
    maintenance.run_pass()
    newest = exports(tmp_path / "custody")
    assert len(newest) == first + 1
    record = json.loads(newest[0].path.read_bytes())["record"]
    assert len(record["tombstones"]) == 1


def test_a_purge_reaches_the_backup_copy(purged, tmp_path):
    maintenance = _maintenance(purged, tmp_path)
    maintenance.run_pass()
    backup = maintenance.stores.backup.blobs
    objects = list(purged.store.iter_blob_ids())
    assert objects and all(backup.exists(blob) for blob in objects)
    purged.tombstone_the_capture(_capture(purged))
    status = maintenance.run_pass()
    assert status["purge"]["destroyed"] >= 3
    assert status["backup_copies_purged"] >= 3
    gone = [blob for blob in objects if not purged.store.exists(blob)]
    assert gone and not any(backup.exists(blob) for blob in gone)


def test_a_failed_step_is_a_code_and_the_rest_still_run(purged, tmp_path):
    _require_server_binaries()
    maintenance = _maintenance(purged, tmp_path, purge_url=None)
    status = maintenance.run_pass()
    assert status["failures"] == ["purge_not_configured"]
    assert status["last_backup_at"] and len(exports(tmp_path / "custody")) == 2
    installation = Installation(
        profile=load_profile(PROFILES / "single-host.json"),
        code_revision=None,
        images={},
        maintenance_status_path=tmp_path / "status" / "maintenance.json",
    )
    components = {
        entry["component"]: entry
        for entry in installation_facts(_services(purged, installation))["components"]
    }
    assert components["maintenance"] == {
        "component": "maintenance",
        "state": "degraded",
        "reason": "purge_not_configured",
    }


def test_retention_keeps_the_newest_set(purged, tmp_path):
    clock = [dt.datetime.now(dt.UTC)]
    maintenance = _maintenance(purged, tmp_path, now=lambda: clock[0])
    maintenance.run_pass()
    clock[0] += dt.timedelta(days=31)
    status = maintenance.run_pass()
    assert status["backup_sets_removed"] == 1
    assert len([p for p in (tmp_path / "backup-sets").iterdir() if p.is_dir()]) == 1


def test_the_command_names_a_missing_setting(monkeypatch, capsys):
    from exulanica.orchestration.installation.cli import main

    for name in ("BACKUP_DATABASE_URL", "BACKUP_STORE_DIRECTORY", "INSTALLATION_PROFILE"):
        monkeypatch.delenv(f"EXULANICA_{name}", raising=False)
    assert main(["maintenance", "--once"]) == 2
    assert "EXULANICA_BACKUP_STORE_DIRECTORY is not set" in capsys.readouterr().err


def test_a_gap_in_the_backup_role_is_reported_every_pass(purged, tmp_path):
    maintenance = _maintenance(purged, tmp_path)
    added = f'"{purged.scratch}".added_for_the_maintenance_check'
    with purged.database().unscoped() as connection:
        connection.execute(f"create table {added} (x int)")
        connection.execute(f'revoke select on {added} from "{_ROLE}"')
    try:
        status = maintenance.run_pass()
    finally:
        with purged.database().unscoped() as connection:
            connection.execute(f"drop table {added}")
    assert "backup_role_incomplete" in status["failures"]
    assert status["backup_role_gaps"] == 1


def test_a_set_whose_erased_objects_left_the_backup_copy_still_verifies(purged, tmp_path):
    _require_server_binaries()
    maintenance = _maintenance(purged, tmp_path)
    maintenance.run_pass()
    purged.tombstone_the_capture(_capture(purged))
    assert maintenance.run_pass()["backup_copies_purged"] >= 3
    # Verification is due again: the set now lacks objects a completed purge erased, by design.
    maintenance._last_verified = None
    status = maintenance.run_pass()
    assert "verification_failed" not in status["failures"], status.get("detail")
    assert status["last_verified_backup_at"]


def test_the_verify_command_accepts_the_gaps_maintenance_made(
    purged, tmp_path, monkeypatch, capsys
):
    _require_server_binaries()
    from exulanica.orchestration.installation.cli import main

    maintenance = _maintenance(purged, tmp_path)
    maintenance.run_pass()
    purged.tombstone_the_capture(_capture(purged))
    assert maintenance.run_pass()["backup_copies_purged"] >= 3
    older = sorted((tmp_path / "backup-sets").iterdir())[0]
    monkeypatch.setenv("EXULANICA_DATA_DIR", str(purged.store.root.parent))
    monkeypatch.setenv("EXULANICA_BACKUP_STORE_DIRECTORY", str(_backup_root(tmp_path)))
    monkeypatch.setenv("EXULANICA_CUSTODY_DIRECTORY", str(tmp_path / "custody"))
    assert main(["verify", "--backup-set", str(older)]) == 0, capsys.readouterr().err
    assert json.loads(capsys.readouterr().out)["erased_objects"] >= 3


def test_a_past_purge_costs_the_live_store_nothing_once_erased(purged, tmp_path, monkeypatch):
    from exulanica.store.local import LocalContentAddressedStore

    maintenance = _maintenance(purged, tmp_path)
    maintenance.run_pass()
    purged.tombstone_the_capture(_capture(purged))
    assert maintenance.run_pass()["backup_copies_purged"] >= 3
    live_root = purged.store.root
    asked = []
    original = LocalContentAddressedStore.exists

    def counting(self, blob_id):
        if Path(self.root) == live_root:
            asked.append(blob_id)
        return original(self, blob_id)

    monkeypatch.setattr(LocalContentAddressedStore, "exists", counting)
    status: dict = {"failures": []}
    maintenance._purge_backup_copies(status)
    assert status["backup_copies_purged"] == 0 and asked == []


def test_a_restore_writes_only_the_profiles_marker(monkeypatch, capsys, tmp_path):
    """The API reads the profile's marker at startup; a restore writing another could be served."""
    from exulanica.orchestration.installation.cli import main

    monkeypatch.setenv("EXULANICA_INSTALLATION_PROFILE", str(PROFILES / "single-host.json"))
    monkeypatch.delenv("EXULANICA_RESTORE_STATE_PATH", raising=False)
    for name in ("RESTORE_MAINTENANCE_URL", "RESTORE_DATABASE_URL", "PURGE_DATABASE_URL"):
        monkeypatch.setenv(f"EXULANICA_{name}", "postgresql://nobody@127.0.0.1:1/exulanica")
    monkeypatch.setenv("EXULANICA_DATA_DIR", str(tmp_path / "data"))
    code = main(
        [
            "restore",
            "declared",
            "--backup-set",
            str(tmp_path / "set"),
            "--export",
            str(tmp_path / "export.json"),
            "--declaration",
            str(tmp_path / "declaration.json"),
            "--marker",
            str(tmp_path / "elsewhere.json"),
        ]
    )
    assert code == 1
    assert "restore_state_path_conflict" in capsys.readouterr().err


def test_a_backup_copy_keeps_bytes_until_an_export_names_their_purge(purged, tmp_path):
    maintenance = _maintenance(purged, tmp_path)
    maintenance.run_pass()
    backup = maintenance.stores.backup.blobs
    purged.tombstone_the_capture(_capture(purged))
    purged.worker().drain()
    gone = [blob for blob in backup.iter_blob_ids() if not purged.store.exists(blob)]
    assert gone
    # No export names that purge yet: a declared recovery would refuse the gap, so none is made.
    status: dict = {"failures": []}
    maintenance._purge_backup_copies(status)
    assert status["backup_copies_purged"] == 0 and all(backup.exists(b) for b in gone)
    maintenance.run_pass()
    assert not any(backup.exists(b) for b in gone)


def test_a_pass_whose_export_fails_takes_no_backup_and_erases_nothing(purged, tmp_path):
    marker = tmp_path / "control" / "restore.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "profile": "exulanica.restore-state/v1",
                "state": "pending",
                "restore_id": str(uuid.uuid4()),
                "checkpoint_id": str(uuid.uuid4()),
                "checkpoint_sha256": "0" * 64,
            }
        )
    )
    maintenance = _maintenance(purged, tmp_path, restore_state_path=marker)
    status = maintenance.run_pass()
    assert "withdrawal_export_failed" in status["failures"]
    assert set(status["skipped"]) == {"backup", "backup_copy_purge"}
    assert not (tmp_path / "backup-sets").exists() or not any((tmp_path / "backup-sets").iterdir())


def test_init_writes_a_marker_only_on_a_first_install(purged, monkeypatch, tmp_path, capsys):
    """On an installed database a missing marker is lost custody, never "no restore declared"."""
    from exulanica.orchestration.installation.cli import main

    document = json.loads((PROFILES / "single-host.json").read_text())
    marker = tmp_path / "control" / "restore.json"
    document["recovery"]["restore_state_path"] = str(marker)
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(document))
    monkeypatch.setenv("EXULANICA_INSTALLATION_PROFILE", str(profile))
    monkeypatch.delenv("EXULANICA_RESTORE_STATE_PATH", raising=False)
    monkeypatch.setenv("EXULANICA_RESTORE_DATABASE_URL", purged.database().url)
    assert main(["init"]) == 1
    assert "missing on an installed database" in capsys.readouterr().err
    assert not marker.exists()


def test_listed_bytes_are_counted_without_asking_the_store(purged, tmp_path, monkeypatch):
    """A listed key may be held again by the restored installation (the same bytes uploaded or
    derived again), so it is never reported as removable, and counting the listings asks the live
    store nothing, however many there are."""
    from exulanica.store.local import LocalContentAddressedStore

    marker = tmp_path / "control" / "restore.json"
    marker.parent.mkdir()
    maintenance = _maintenance(purged, tmp_path, restore_state_path=marker)
    later = purged.store.put_bytes(b"written after the backup the restore replaced").blob_id
    (marker.parent / "objects-not-in-backup-00000000.txt").write_text(
        f"blobs/{later.hex}\nblobs/{'0' * 64}\n"
    )
    asked = []
    monkeypatch.setattr(
        LocalContentAddressedStore, "exists", lambda self, blob_id: asked.append(blob_id)
    )
    status: dict = {"failures": []}
    maintenance._unlisted(status)
    assert status == {"failures": [], "objects_not_in_backup_listed": 2}
    assert asked == []


def test_a_restore_refuses_a_marker_no_environment_declares(monkeypatch, capsys, tmp_path):
    """Without a profile or EXULANICA_RESTORE_STATE_PATH, a --marker protects nothing the API
    reads, so no restore mode takes one."""
    from exulanica.orchestration.installation.cli import main

    monkeypatch.delenv("EXULANICA_INSTALLATION_PROFILE", raising=False)
    monkeypatch.delenv("EXULANICA_RESTORE_STATE_PATH", raising=False)
    for name in ("RESTORE_MAINTENANCE_URL", "RESTORE_DATABASE_URL", "PURGE_DATABASE_URL"):
        monkeypatch.setenv(f"EXULANICA_{name}", "postgresql://nobody@127.0.0.1:1/exulanica")
    monkeypatch.setenv("EXULANICA_DATA_DIR", str(tmp_path / "data"))
    marker = tmp_path / "control" / "restore.json"
    for mode in ("planned", "return-to-source", "discard-set-aside"):
        code = main(
            ["restore", mode, "--checkpoint", str(tmp_path / "c.json"), "--marker", str(marker)]
        )
        assert code != 0 and "no restore marker is declared" in capsys.readouterr().err
    assert not marker.exists()


def test_a_set_aside_database_is_reported_until_discarded(purged, tmp_path):
    maintenance = _maintenance(purged, tmp_path)
    name = f"exulanica_before_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(purged.database().url, autocommit=True) as connection:
        connection.execute(f'create database "{name}"')
    try:
        status: dict = {"failures": []}
        maintenance._check_role(status)
        assert "set_aside_database_present" in status["failures"]
    finally:
        with psycopg.connect(purged.database().url, autocommit=True) as connection:
            connection.execute(f'drop database "{name}"')
    status = {"failures": []}
    maintenance._check_role(status)
    assert "set_aside_database_present" not in status["failures"]
