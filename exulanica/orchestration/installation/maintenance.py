"""The unattended maintenance pass: withdrawal exports, purges, backups and the facts they feed.

One process runs :meth:`Maintenance.run_pass` in a loop, and each pass is bounded: a fixed number
of purge jobs, one backup set at most, one verification at most. Every step reports its outcome
as a stable code in the status file the API reads (``exulanica.maintenance-status/v1``); a step
that fails is a code in ``failures``, never a silent success, and the next pass tries again.

*   **Withdrawal export** when a tombstone or a catalogued withdrawal may have changed, detected
    by a cheap signal (the tombstone count and the catalog tables' write counters), and at least
    every export interval whatever the signal says, because statistics counters are advisory.
    Custody keeps the newest exports and every export a retained backup set names.
*   **Purge** of what committed tombstones ask for, bounded per pass, as the purge role.
*   **Backup set** when the newest is older than the backup interval.
*   **Backup copies purged**: bytes a completed purge destroyed are destroyed in the backup copy
    too, unless the live store holds them again, so erasure reaches backups within one pass.
*   **Verification** of the newest set when the last proof is older than its interval.
*   **Retention**: sets older than the retention bound are removed, the newest always kept.
*   **Queue observations**: the oldest queued item of each component, read across workspaces as
    the backup role, which the API's runtime role cannot do.
*   **The backup role itself**: a table it cannot read or could write, or a large object, is
    ``backup_role_incomplete``, reported each pass rather than found by the next backup.
*   **The door's sweep**: grants that ran out with a visitor still present or a traveller mind
    still current, found as the backup role and settled as the runtime role, a bounded number a
    pass (:mod:`exulanica.door.sweep`), so a visitor leaves within one pass of its grant's end.
    Not run, and said so, where no runtime role is configured.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from psycopg.rows import dict_row

from exulanica.api.installation import MAINTENANCE_STATUS_PROFILE, RecoveryPolicy
from exulanica.db.definer_role import DefinerRoleUnsafe, assert_definer_role, definer_role_installed
from exulanica.db.local.files import write_private
from exulanica.db.roles import backup_role_gaps
from exulanica.db.session import Database
from exulanica.deletion.queue import STORED_KINDS, stored_target_store
from exulanica.deletion.restore import export_withdrawals
from exulanica.deletion.withdrawals import CATALOG
from exulanica.deletion.worker import PurgeWorker
from exulanica.door.sweep import sweep
from exulanica.evidence.blob import BlobId
from exulanica.orchestration.installation.backup_set import (
    BackupSetRefused,
    Namespace,
    read_backup_set,
    take_backup_set,
    verify_backup_set,
)
from exulanica.orchestration.installation.custody import (
    DEFAULT_KEEP,
    UNLISTED_PREFIX,
    erased_targets,
    exports,
    prune_exports,
)
from exulanica.store.base import ContentAddressedStore, PurgeAuthorization, privileged_purger
from exulanica.store.configured import ContentStores

__all__ = ["PREPARER_QUEUE_QUERY", "QUEUE_QUERIES", "Maintenance", "MaintenanceStores"]

#: How old the oldest item each queued component is waiting on, read across workspaces. Items
#: that are waiting for a retry time are not late, so the derivative and tile queues count only
#: what is eligible now.
QUEUE_QUERIES: Final[Mapping[str, str]] = {
    "derivatives": (
        "select min(run_after) as oldest from job "
        "where kind = 'intake_derivatives' and state = 'queued' and run_after <= now()"
    ),
    "generated_tiles": (
        "select min(run_after) as oldest from job "
        "where kind = 'bake_generated_tile' and state = 'queued' and run_after <= now()"
    ),
    "pose_scene": "select min(created_at) as oldest from reconstruction_scene_job "
    "where status = 'queued'",
    "materials": "select min(requested_at) as oldest from material_bake where state = 'requested'",
    "preparation": "select min(requested_at) as oldest from workspace_preparation "
    "where state = 'requested'",
    # Each world's oldest unstarted comparison, then the oldest of those: an age across worlds. A
    # world is its workspace's: one identity can name a world in many (an arrival world).
    "comparison": "select min(oldest) as oldest from (select workspace_id, world_id, "
    "min(created_at) as oldest from society_comparison_start "
    "where finished_at is null and lease_token is null "
    "group by workspace_id, world_id) per_world",
}


#: The oldest requested preparation of each preparer, by its pin's parts.
PREPARER_QUEUE_QUERY: Final = (
    "select preparer_id, preparer_version, min(requested_at) as oldest from workspace_preparation "
    "where state = 'requested' group by preparer_id, preparer_version"
)


@dataclass(frozen=True, slots=True)
class MaintenanceStores:
    """The installation's purging stores and their backup copies, paired by namespace name.

    Every name comes from :meth:`ContentStores.namespaces`, so a namespace registered in
    :mod:`exulanica.store.namespaces` is backed up, verified, restored and purged with no edit
    here.
    """

    live: ContentStores
    backup: ContentStores

    def __post_init__(self) -> None:
        if self.live.overlaps(self.backup):
            raise BackupSetRefused(
                "backup_store_overlaps",
                "the backup copy lies inside the content store or holds it: a purge of one would "
                "reach the other",
            )

    def namespaces(self) -> list[Namespace]:
        found = []
        for name, store in self.live.namespaces():
            copy = self.backup.namespace(name)
            if copy is None:
                raise BackupSetRefused("backup_store_missing", f"no backup store for {name}")
            found.append(Namespace(name, store, copy))
        return found

    def purge_backup_copy(
        self,
        kind: str,
        workspace_id: uuid.UUID,
        blob_id: BlobId,
        authorization: PurgeAuthorization,
    ) -> int:
        """Destroy a completed purge's target in the backup copy, where its kind's namespace
        keeps it, unless the live store holds those bytes again. Returns how many were destroyed.
        """
        backup = stored_target_store(self.backup, kind, workspace_id)
        # The local copy first: once erased, a past purge costs no request to the live store, which
        # on the shared-store profile is a network round trip per target every pass.
        if not backup.exists(blob_id):
            return 0
        if stored_target_store(self.live, kind, workspace_id).exists(blob_id):
            return 0
        return int(privileged_purger(backup, authorization).purge(blob_id))

    def backup_for(self, name: str) -> ContentAddressedStore | None:
        """The backup copy a set's namespace name refers to, resolved from the name alone, which
        serves a restore target that holds nothing yet."""
        return self.backup.namespace(name)


@dataclass
class Maintenance:
    """One installation's maintenance, run a pass at a time."""

    backup_url: str
    purge_url: str | None
    custody: Path
    backup_directory: Path
    status_path: Path
    stores: MaintenanceStores
    policy: RecoveryPolicy
    identity: Mapping[str, Any]
    restore_state_path: Path | None
    backup_domains: tuple[Path, ...]
    backup_role: str = "exulanica_backup"
    #: The runtime role's connection, which the door's sweep settles grants as; none skips it.
    runtime_url: str | None = None
    purge_limit: int = 500
    keep_exports: int = DEFAULT_KEEP
    now: Callable[[], dt.datetime] = field(default=lambda: dt.datetime.now(dt.UTC))
    _signal: tuple[int, int] | None = field(default=None, init=False)
    _last_export: dt.datetime | None = field(default=None, init=False)
    _last_verified: dt.datetime | None = field(default=None, init=False)
    #: The door grants the last pass's sweep could not settle, or left as they were: the next
    #: pass takes them last.
    _sweep_stuck: tuple[uuid.UUID, ...] = field(default=(), init=False)

    @property
    def _database(self) -> Database:
        return Database(self.backup_url)

    def _change_signal(self) -> tuple[int, int]:
        tables = sorted({kind.table for kind in CATALOG})
        with self._database.unscoped() as raw:
            connection = raw.cursor(row_factory=dict_row)
            row = connection.execute(
                "select (select count(*) from tombstone) as tombstones, "
                "(select coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) "
                "from pg_stat_user_tables where schemaname = current_schema() "
                "and relname = any(%s)) as writes",
                (tables,),
            ).fetchone()
        assert row is not None
        return int(row["tombstones"]), int(row["writes"])

    def _referenced_exports(self) -> set[str]:
        referenced = set()
        for directory in self._sets():
            try:
                record = read_backup_set(directory).manifest["record"]
            except BackupSetRefused:
                continue
            referenced.add(record["withdrawal_export"]["sha256"])
        return referenced

    def _sets(self) -> list[Path]:
        if not self.backup_directory.exists():
            return []
        return sorted(
            path
            for path in self.backup_directory.iterdir()
            if path.is_dir() and (path / "backup-set.json").exists()
        )

    def _check_role(self, status: dict[str, Any]) -> None:
        """Every table readable, none writable, no large object: or a code, every pass. And a
        source set aside by a completed planned restore, which no deletion reaches, reported until
        it is discarded."""
        with self._database.unscoped() as connection:
            gaps = backup_role_gaps(connection, self.backup_role)
            kept = (
                connection.cursor(row_factory=dict_row)
                .execute(
                    "select count(*) as n from pg_database where datname ~ '_before_[0-9a-f]{8}$'"
                )
                .fetchone()
            )
        status["backup_role_gaps"] = len(gaps)
        if gaps:
            status["failures"].append("backup_role_incomplete")
        if kept is not None and kept["n"]:
            status["failures"].append("set_aside_database_present")

    def _check_definer(self, status: dict[str, Any]) -> None:
        """The SECURITY DEFINER functions' owner is still the narrow role with its grants, every
        pass: a role widened, a grant stripped or a definer handed back after the deployment's
        check is reported here rather than at the next deployment."""
        with self._database.unscoped() as connection:
            if not definer_role_installed(connection):
                return
            try:
                assert_definer_role(connection)
            except DefinerRoleUnsafe as unsafe:
                status["failures"].append("definer_role_unsafe")
                status.setdefault("detail", {})["definer_role_unsafe"] = str(unsafe)

    def _export(self, status: dict[str, Any]) -> None:
        now = self.now()
        signal = self._change_signal()
        due = (
            self._last_export is None
            or signal != self._signal
            or now - self._last_export >= dt.timedelta(seconds=self.policy.export_interval_seconds)
        )
        if due:
            path, _digest = export_withdrawals(
                self._database,
                self.custody,
                restore_state_path=self.restore_state_path,
                backup_domains=(*self.backup_domains, self.backup_directory),
            )
            self._signal, self._last_export = signal, now
            status["exports_removed"] = len(
                prune_exports(
                    self.custody,
                    source_identity=json.loads(path.read_bytes())["record"]["source_identity"],
                    keep=self.keep_exports,
                    referenced=self._referenced_exports(),
                )
            )
        newest = exports(self.custody)[:1]
        if newest:
            covered = dt.datetime.fromisoformat(newest[0].covered_through)
            status["withdrawal_export"] = {
                "sha256": newest[0].sha256,
                "covered_through": newest[0].covered_through,
                "lag_seconds": int((now - covered).total_seconds()),
            }

    def _purge(self, status: dict[str, Any]) -> None:
        if self.purge_url is None:
            status["failures"].append("purge_not_configured")
            return
        with self._database.unscoped() as raw:
            connection = raw.cursor(row_factory=dict_row)
            workspaces = frozenset(
                row["workspace_id"]
                for row in connection.execute(
                    "select distinct workspace_id from purge_job where state <> 'done'"
                ).fetchall()
            )
        if not workspaces:
            status["purge"] = {"destroyed": 0}
            return
        outcome = PurgeWorker.over(
            Database(self.purge_url),
            self.stores.live,
            workspaces,
            name="maintenance",
            limit_per_pass=self.purge_limit,
        ).drain()
        status["purge"] = {
            "destroyed": outcome.destroyed,
            "skipped": outcome.skipped,
            "failed": outcome.failed,
            "exhausted": outcome.exhausted,
        }
        if outcome.blocked or outcome.failed or outcome.exhausted:
            status["failures"].append("purge_incomplete")

    def _purge_backup_copies(self, status: dict[str, Any]) -> None:
        """Destroy in the backup copy what a completed purge destroyed, unless held again live.

        Only targets the newest export names: a target no export names yet stays in the backup
        copy until one does, so verification and a declared recovery accept the same gaps.
        """
        named = erased_targets(self.custody)
        with self._database.unscoped() as raw:
            connection = raw.cursor(row_factory=dict_row)
            rows = connection.execute(
                "select j.workspace_id, j.target_kind, j.target_ref, t.tombstone_id, "
                "t.requested_by from purge_job j join tombstone t "
                "on t.tombstone_id = j.tombstone_id "
                "where j.state = 'done' and j.target_kind = any(%s)",
                (list(STORED_KINDS),),
            ).fetchall()
        destroyed = 0
        for row in rows:
            if row["target_ref"] not in named:
                continue
            authorization = PurgeAuthorization(
                tombstone_id=str(row["tombstone_id"]),
                actor=str(row["requested_by"]),
                reason="a completed purge reaches the backup copy",
            )
            destroyed += self.stores.purge_backup_copy(
                row["target_kind"],
                row["workspace_id"],
                BlobId.from_hex(row["target_ref"]),
                authorization,
            )
        status["backup_copies_purged"] = destroyed

    def _backup(self, status: dict[str, Any]) -> None:
        now = self.now()
        sets = self._sets()
        newest = read_backup_set(sets[-1]).manifest["record"] if sets else None
        started = dt.datetime.fromisoformat(newest["started_at"]) if newest else None
        if started is not None and now - started < dt.timedelta(
            seconds=self.policy.backup_interval_seconds
        ):
            status["last_backup_at"] = newest["started_at"] if newest else None
            return
        taken = take_backup_set(
            backup_url=self.backup_url,
            directory=self.backup_directory,
            namespaces=self.stores.namespaces(),
            custody=self.custody,
            restore_state_path=self.restore_state_path,
            backup_domains=self.backup_domains,
            identity=self.identity,
            role=self.backup_role,
        )
        status["last_backup_at"] = taken.manifest["record"]["started_at"]

    def _verify(self, status: dict[str, Any]) -> None:
        sets = self._sets()
        if not sets:
            return
        now = self.now()
        if self._last_verified is not None and now - self._last_verified < dt.timedelta(
            seconds=self.policy.verification_interval_seconds
        ):
            status["last_verified_backup_at"] = self._last_verified.isoformat()
            return
        # The criterion a declared recovery applies: gaps the newest export names, and no other.
        verify_backup_set(sets[-1], self.stores.backup_for, erased=erased_targets(self.custody))
        self._last_verified = now
        status["last_verified_backup_at"] = now.isoformat()

    def _retain(self, status: dict[str, Any]) -> None:
        cutoff = self.now() - dt.timedelta(days=self.policy.backup_retention_days)
        removed = 0
        for directory in self._sets()[:-1]:
            record = read_backup_set(directory).manifest["record"]
            if dt.datetime.fromisoformat(record["started_at"]) < cutoff:
                shutil.rmtree(directory)
                removed += 1
        status["backup_sets_removed"] = removed

    def _queues(self, status: dict[str, Any]) -> None:
        now = self.now()
        queues: dict[str, dict[str, Any]] = {}
        with self._database.unscoped() as raw:
            connection = raw.cursor(row_factory=dict_row)
            for component, query in QUEUE_QUERIES.items():
                row = connection.execute(query).fetchone()
                oldest = row["oldest"] if row is not None else None
                queues[component] = {
                    "oldest_queued_seconds": 0
                    if oldest is None
                    else max(0, int((now - oldest).total_seconds()))
                }
            # Preparation per preparer as well: a profile may install some preparers and not
            # others, and a request for one it does not run waits by design.
            preparers = {
                f"{row['preparer_id']}@{row['preparer_version']}": max(
                    0, int((now - row["oldest"]).total_seconds())
                )
                for row in connection.execute(PREPARER_QUEUE_QUERY).fetchall()
            }
            queues["preparation"]["preparers"] = preparers
        status["queues"] = queues

    def run_pass(self) -> dict[str, Any]:
        """One bounded pass. Each step's failure is recorded by code and the rest still run."""
        status: dict[str, Any] = {"profile": MAINTENANCE_STATUS_PROFILE, "failures": []}
        steps: tuple[tuple[str, Callable[[dict[str, Any]], None]], ...] = (
            ("backup_role_check_failed", self._check_role),
            ("definer_role_check_failed", self._check_definer),
            # The sweep is short and runs before the backups, so a visitor leaves within a pass
            # of its grant's end whether or not a backup is due.
            ("door_sweep_failed", self._door_sweep),
            ("withdrawal_export_failed", self._export),
            ("purge_failed", self._purge),
            ("backup_copy_purge_failed", self._purge_backup_copies),
            ("backup_failed", self._backup),
            ("verification_failed", self._verify),
            ("retention_failed", self._retain),
            ("queue_observation_failed", self._queues),
            ("unlisted_objects_check_failed", self._unlisted),
        )
        for code, step in steps:
            if code in ("backup_copy_purge_failed", "backup_failed") and (
                "withdrawal_export_failed" in status["failures"]
            ):
                # Without a current export a backup set cannot be finished and no erasure is
                # named; skipping both keeps a failing pass from re-dumping the database each time.
                status.setdefault("skipped", []).append(code.removesuffix("_failed"))
                continue
            try:
                step(status)
            except Exception as failure:  # every failure is a code in the status, never a crash
                status["failures"].append(code)
                status.setdefault("detail", {})[code] = type(failure).__name__
        status["written_at"] = self.now().isoformat()
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        write_private(self.status_path, json.dumps(status, sort_keys=True, default=str) + "\n")
        return status

    def _door_sweep(self, status: dict[str, Any]) -> None:
        """Settle the door grants that ran out with nobody reading them: found as the backup role,
        settled as the runtime role. A grant a pass could not settle, or left as it was, is held
        back: later passes take it after every other, and while any is held back the status names
        them (``stuck``) and says ``door_sweep_incomplete``."""
        if self.runtime_url is None:
            status["door_sweep"] = {"configured": False}
            return
        swept = sweep(self._database, Database(self.runtime_url), deferred=self._sweep_stuck)
        self._sweep_stuck = tuple(swept["stuck"])
        status["door_sweep"] = {
            "configured": True,
            **swept,
            "stuck": [str(grant_id) for grant_id in swept["stuck"]],
        }
        if swept["failed"] or swept["stuck"]:
            status["failures"].append("door_sweep_incomplete")

    def _unlisted(self, status: dict[str, Any]) -> None:
        """How many keys restores listed as written after their backups, read from the listings
        beside the marker alone: no store request, so the pass stays bounded however many there are.

        A count, not a failure: a listed key is content-addressed and the restored installation may
        hold the same bytes again (an upload made again, a derivative made again), so whether one
        can be removed needs a reference check that does not exist; removal is open.
        """
        if self.restore_state_path is None:
            return
        status["objects_not_in_backup_listed"] = sum(
            len(listing.read_text().splitlines())
            for listing in self.restore_state_path.parent.glob(f"{UNLISTED_PREFIX}*.txt")
        )

    def run(self, *, pass_seconds: float, passes: int | None = None) -> None:
        """Run passes until stopped, or ``passes`` of them; each at least ``pass_seconds`` apart."""
        done = 0
        while passes is None or done < passes:
            started = time.monotonic()
            self.run_pass()
            done += 1
            time.sleep(max(0.0, pass_seconds - (time.monotonic() - started)))
