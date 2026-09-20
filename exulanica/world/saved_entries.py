"""Workspace authority for reopening a personal world at a saved authored state and style."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Final, Literal

import psycopg

from exulanica.world.errors import UnknownWorldResource

__all__ = [
    "SavedWorldCandidate",
    "SavedWorldEntry",
    "SavedWorldEntryRepository",
    "StaleSavedWorldEntry",
]

_WORKSPACE_LOCK_SEED: Final = 880_024


class StaleSavedWorldEntry(Exception):
    """The caller tried to replace an entry revision it did not read."""


@dataclass(frozen=True, slots=True)
class SavedWorldStyleCandidate:
    version_id: uuid.UUID
    revision: int


@dataclass(frozen=True, slots=True)
class SavedWorldCandidate:
    world_id: str
    authored_version_id: uuid.UUID
    title: str
    source_invalidated: bool
    styles: tuple[SavedWorldStyleCandidate, ...]


@dataclass(frozen=True, slots=True)
class SavedWorldEntry:
    entry_id: uuid.UUID
    world_id: str
    title: str
    source_kind: Literal["personal", "authored"]
    source_snapshot_id: uuid.UUID
    source_snapshot_sha256: str
    authored_scene: object | None
    authored_version_id: uuid.UUID
    authored_state_sha256: str
    authored_edit_seq: int
    current_authored_state_sha256: str
    current_authored_edit_seq: int
    style_version_id: uuid.UUID
    revision: int
    availability: Literal["available", "unavailable"]
    unavailable_reason: str | None
    created_by: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime


class SavedWorldEntryRepository:
    """Read and update saved entries through one workspace-scoped connection."""

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self.connection = connection
        self.workspace_id = workspace_id

    def entries(self) -> tuple[SavedWorldEntry, ...]:
        rows = self.connection.execute(
            self._select() + " order by e.updated_at desc, e.entry_id",
            (self.workspace_id,),
        ).fetchall()
        return tuple(self._entry(row) for row in rows)

    def candidates(self) -> tuple[SavedWorldCandidate, ...]:
        rows = self.connection.execute(
            "select v.world_id,v.version_id,v.title,"
            "exists(select 1 from world_structure_invalidation i "
            "where i.workspace_id=v.workspace_id and i.world_id=v.world_id "
            "and i.snapshot_id=v.source_snapshot_id) as source_invalidated "
            "from world_alternate_version v "
            "left join saved_world_entry e on e.workspace_id=v.workspace_id "
            "and e.world_id=v.world_id "
            "where v.workspace_id=%s and e.entry_id is null "
            "order by v.world_id,v.created_at,v.version_id",
            (self.workspace_id,),
        ).fetchall()
        styles_by_world: dict[str, tuple[SavedWorldStyleCandidate, ...]] = {}
        for world_id in {row["world_id"] for row in rows}:
            styles = self.connection.execute(
                "select version_id,revision from world_style_version "
                "where workspace_id=%s and world_id=%s order by revision,version_id",
                (self.workspace_id, world_id),
            ).fetchall()
            styles_by_world[world_id] = tuple(
                SavedWorldStyleCandidate(row["version_id"], row["revision"]) for row in styles
            )
        return tuple(
            SavedWorldCandidate(
                world_id=row["world_id"],
                authored_version_id=row["version_id"],
                title=row["title"],
                source_invalidated=row["source_invalidated"],
                styles=styles_by_world[row["world_id"]],
            )
            for row in rows
        )

    def entry(self, entry_id: uuid.UUID) -> SavedWorldEntry:
        row = self.connection.execute(
            self._select() + " and e.entry_id=%s",
            (self.workspace_id, entry_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such saved world entry")
        return self._entry(row)

    def create(
        self,
        *,
        world_id: str,
        title: str,
        authored_version_id: uuid.UUID,
        style_version_id: uuid.UUID,
        created_by: uuid.UUID,
        source_kind: Literal["personal", "authored"] = "personal",
    ) -> SavedWorldEntry:
        clean_world_id = world_id.strip()
        clean_title = title.strip()
        if not 1 <= len(clean_world_id) <= 200:
            raise ValueError("world_id must contain between 1 and 200 characters")
        if not 1 <= len(clean_title) <= 200:
            raise ValueError("title must contain between 1 and 200 characters")
        try:
            with self.connection.transaction():
                self._lock_workspace()
                authored = self._require_versions(
                    clean_world_id,
                    authored_version_id,
                    style_version_id,
                    lock_authored=True,
                )
                self._require_entry_origin(source_kind, authored)
                row = self.connection.execute(
                    "insert into saved_world_entry "
                    "(workspace_id,world_id,title,source_kind,authored_version_id,"
                    "authored_state_sha256,authored_edit_seq,style_version_id,created_by) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning entry_id",
                    (
                        self.workspace_id,
                        clean_world_id,
                        clean_title,
                        source_kind,
                        authored_version_id,
                        authored["state_sha256"],
                        authored["edit_seq"],
                        style_version_id,
                        created_by,
                    ),
                ).fetchone()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("this world already has a saved entry") from exc
        assert row is not None
        return self.entry(row["entry_id"])

    def create_starter(self, *, title: str, created_by: uuid.UUID) -> SavedWorldEntry:
        """Atomically create or return this workspace's one controlled authored starter."""

        clean_title = title.strip()
        if not 1 <= len(clean_title) <= 200:
            raise ValueError("title must contain between 1 and 200 characters")
        with self.connection.transaction():
            self._lock_workspace()
            existing = self.entries()
            if existing:
                if (
                    len(existing) == 1
                    and existing[0].source_kind == "authored"
                    and existing[0].availability == "available"
                ):
                    if existing[0].title == clean_title:
                        # A retry never renames or adopts a newer cursor. Explicit PUT remains the
                        # only rename/update authority.
                        return existing[0]
                    raise ValueError(
                        "the authored starter already exists under a different title"
                    )
                raise ValueError("the workspace already has a different saved world entry")

            from exulanica.world.starter import create_starter_authorities

            world_id = f"world:authored:{uuid.uuid4()}"
            _, style, authored_version_id = create_starter_authorities(
                self.connection,
                workspace_id=self.workspace_id,
                actor=created_by,
                title=clean_title,
                world_id=world_id,
            )
            return self.create(
                world_id=world_id,
                title=clean_title,
                authored_version_id=authored_version_id,
                style_version_id=style.version_id,
                created_by=created_by,
                source_kind="authored",
            )

    def update(
        self,
        entry_id: uuid.UUID,
        *,
        base_revision: int,
        authored_version_id: uuid.UUID,
        expected_authored_state_sha256: str,
        expected_authored_edit_seq: int,
        style_version_id: uuid.UUID,
        title: str | None = None,
    ) -> SavedWorldEntry:
        with self.connection.transaction():
            self._lock_workspace()
            row = self.connection.execute(
                "select world_id,revision,title,source_kind from saved_world_entry "
                "where workspace_id=%s and entry_id=%s for update",
                (self.workspace_id, entry_id),
            ).fetchone()
            if row is None:
                raise UnknownWorldResource("no such saved world entry")
            if row["revision"] != base_revision:
                raise StaleSavedWorldEntry(
                    f"entry targets revision {base_revision}; current revision is {row['revision']}"
                )
            clean_title = row["title"] if title is None else title.strip()
            if not 1 <= len(clean_title) <= 200:
                raise ValueError("title must contain between 1 and 200 characters")
            authored = self._require_versions(
                row["world_id"],
                authored_version_id,
                style_version_id,
                expected_authored_state_sha256=expected_authored_state_sha256,
                expected_authored_edit_seq=expected_authored_edit_seq,
                lock_authored=True,
            )
            self._require_entry_origin(str(row["source_kind"]), authored)
            self.connection.execute(
                "update saved_world_entry set title=%s,authored_version_id=%s,"
                "authored_state_sha256=%s,authored_edit_seq=%s,style_version_id=%s,"
                "revision=revision+1,updated_at=now() "
                "where workspace_id=%s and entry_id=%s",
                (
                    clean_title,
                    authored_version_id,
                    expected_authored_state_sha256,
                    expected_authored_edit_seq,
                    style_version_id,
                    self.workspace_id,
                    entry_id,
                ),
            )
        return self.entry(entry_id)

    def lock_authored_advance_base(
        self,
        entry_id: uuid.UUID,
        *,
        base_revision: int,
        world_id: str,
        authored_version_id: uuid.UUID,
        authored_state_sha256: str,
        authored_edit_seq: int,
        mutation_base_state_sha256: str,
    ) -> None:
        """Lock and validate the saved cursor before an authored mutation takes its branch lock."""

        self._lock_workspace()
        row = self.connection.execute(
            "select world_id,authored_version_id,authored_state_sha256,authored_edit_seq,revision "
            "from saved_world_entry where workspace_id=%s and entry_id=%s for update",
            (self.workspace_id, entry_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such saved world entry")
        expected = (
            world_id,
            authored_version_id,
            authored_state_sha256,
            authored_edit_seq,
            base_revision,
        )
        actual = (
            row["world_id"],
            row["authored_version_id"],
            row["authored_state_sha256"],
            row["authored_edit_seq"],
            row["revision"],
        )
        if actual != expected:
            raise StaleSavedWorldEntry(
                "the saved world resume point changed before the authored edit was recorded"
            )
        if mutation_base_state_sha256 != authored_state_sha256:
            raise StaleSavedWorldEntry(
                "the authored edit does not start from the saved world resume point"
            )
        authored = self.connection.execute(
            "select state_sha256,edit_seq from world_alternate_version "
            "where workspace_id=%s and world_id=%s and version_id=%s for update",
            (self.workspace_id, world_id, authored_version_id),
        ).fetchone()
        if authored is None:
            raise UnknownWorldResource("no such authored world version")
        if (
            authored["state_sha256"] != authored_state_sha256
            or authored["edit_seq"] != authored_edit_seq
        ):
            raise StaleSavedWorldEntry(
                "the authored world changed after the saved resume point was recorded"
            )

    def advance_authored_locked(
        self,
        entry_id: uuid.UUID,
        *,
        base_revision: int,
        world_id: str,
        authored_version_id: uuid.UUID,
        result_state_sha256: str,
        result_edit_seq: int,
    ) -> None:
        """Advance a locked entry to one exact mutation result in the same transaction."""

        current = self.connection.execute(
            "select state_sha256,edit_seq from world_alternate_version "
            "where workspace_id=%s and world_id=%s and version_id=%s for update",
            (self.workspace_id, world_id, authored_version_id),
        ).fetchone()
        if current is None:
            raise UnknownWorldResource("no such authored world version")
        if current["state_sha256"] != result_state_sha256 or current["edit_seq"] != result_edit_seq:
            raise StaleSavedWorldEntry(
                "the authored branch moved before its saved resume point could advance"
            )
        updated = self.connection.execute(
            "update saved_world_entry set authored_state_sha256=%s,authored_edit_seq=%s,"
            "revision=revision+1,updated_at=now() where workspace_id=%s and entry_id=%s "
            "and revision=%s returning entry_id",
            (
                result_state_sha256,
                result_edit_seq,
                self.workspace_id,
                entry_id,
                base_revision,
            ),
        ).fetchone()
        if updated is None:
            raise StaleSavedWorldEntry(
                "the saved world resume point changed before the authored edit was recorded"
            )

    def lock_style_advance_base(
        self,
        entry_id: uuid.UUID,
        *,
        base_revision: int,
        world_id: str,
        authored_state_sha256: str,
        authored_edit_seq: int,
        style_version_id: uuid.UUID,
    ) -> None:
        """Lock an entry and prove a style-only write will not adopt unseen authored state."""

        self._lock_workspace()
        row = self.connection.execute(
            "select world_id,authored_version_id,authored_state_sha256,authored_edit_seq,"
            "style_version_id,revision from saved_world_entry "
            "where workspace_id=%s and entry_id=%s for update",
            (self.workspace_id, entry_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such saved world entry")
        if (
            row["world_id"] != world_id
            or row["authored_state_sha256"] != authored_state_sha256
            or row["authored_edit_seq"] != authored_edit_seq
            or row["style_version_id"] != style_version_id
            or row["revision"] != base_revision
        ):
            raise StaleSavedWorldEntry(
                "the saved world resume point changed before the appearance was recorded"
            )
        authored = self.connection.execute(
            "select state_sha256,edit_seq from world_alternate_version "
            "where workspace_id=%s and world_id=%s and version_id=%s for update",
            (self.workspace_id, world_id, row["authored_version_id"]),
        ).fetchone()
        if authored is None:
            raise UnknownWorldResource("no such authored world version")
        if (
            authored["state_sha256"] != authored_state_sha256
            or authored["edit_seq"] != authored_edit_seq
        ):
            raise StaleSavedWorldEntry(
                "the authored world changed before the appearance could be saved"
            )

    def advance_style_locked(
        self,
        entry_id: uuid.UUID,
        *,
        base_revision: int,
        world_id: str,
        style_version_id: uuid.UUID,
    ) -> None:
        """Advance a previously locked entry to one exact committed style version."""

        style = self.connection.execute(
            "select 1 from world_style_version where workspace_id=%s and world_id=%s "
            "and version_id=%s for update",
            (self.workspace_id, world_id, style_version_id),
        ).fetchone()
        if style is None:
            raise UnknownWorldResource("no such world style version")
        updated = self.connection.execute(
            "update saved_world_entry set style_version_id=%s,revision=revision+1,"
            "updated_at=now() where workspace_id=%s and entry_id=%s and revision=%s "
            "returning entry_id",
            (style_version_id, self.workspace_id, entry_id, base_revision),
        ).fetchone()
        if updated is None:
            raise StaleSavedWorldEntry(
                "the saved world resume point changed before the appearance was recorded"
            )

    def _require_versions(
        self,
        world_id: str,
        authored_version_id: uuid.UUID,
        style_version_id: uuid.UUID,
        *,
        expected_authored_state_sha256: str | None = None,
        expected_authored_edit_seq: int | None = None,
        lock_authored: bool = False,
    ) -> dict[str, object]:
        authored = self.connection.execute(
            "select v.state_sha256,v.edit_seq,s.composer_key,s.composer_version,"
            "s.topology,s.placement from world_alternate_version v "
            "join world_structure_snapshot s on s.workspace_id=v.workspace_id "
            "and s.world_id=v.world_id and s.snapshot_id=v.source_snapshot_id "
            "where v.workspace_id=%s and v.world_id=%s and v.version_id=%s"
            + (" for update" if lock_authored else ""),
            (self.workspace_id, world_id, authored_version_id),
        ).fetchone()
        if authored is None:
            raise UnknownWorldResource("no such authored world version")
        if expected_authored_state_sha256 is not None and (
            authored["state_sha256"] != expected_authored_state_sha256
            or authored["edit_seq"] != expected_authored_edit_seq
        ):
            raise StaleSavedWorldEntry(
                "the authored world changed after this exact resume point was read"
            )
        style = self.connection.execute(
            "select 1 from world_style_version "
            "where workspace_id=%s and world_id=%s and version_id=%s",
            (self.workspace_id, world_id, style_version_id),
        ).fetchone()
        if style is None:
            raise UnknownWorldResource("no such world style version")
        return authored

    @staticmethod
    def _require_entry_origin(source_kind: str, snapshot: dict[str, object]) -> None:
        from exulanica.world.starter import (
            AUTHORED_STARTER_COMPOSER,
            authored_starter_scene,
        )

        composer_key = str(snapshot["composer_key"])

        if source_kind == "authored":
            if composer_key != AUTHORED_STARTER_COMPOSER:
                raise ValueError("an authored entry must name the controlled starter snapshot")
            authored_starter_scene(
                composer_key=composer_key,
                composer_version=int(snapshot["composer_version"]),
                topology=snapshot["topology"],
                placement=snapshot["placement"],
            )
            return
        if source_kind == "personal":
            if composer_key == AUTHORED_STARTER_COMPOSER:
                raise ValueError("an authored starter cannot be recorded as a personal source")
            return
        raise ValueError("unknown saved world source kind")

    def _lock_workspace(self) -> None:
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s::text,%s))",
            (self.workspace_id, _WORKSPACE_LOCK_SEED),
        )

    def _select(self) -> str:
        return (
            "select e.entry_id,e.world_id,e.title,e.source_kind,e.authored_version_id,"
            "e.authored_state_sha256,e.authored_edit_seq,e.style_version_id,e.revision,"
            "e.created_by,e.created_at,e.updated_at,v.state_sha256 as current_state_sha256,"
            "v.edit_seq as current_edit_seq,v.source_snapshot_id,s.snapshot_sha256,"
            "s.composer_key,s.composer_version,s.topology,s.placement,"
            "exists(select 1 from world_structure_invalidation i "
            "where i.workspace_id=e.workspace_id and i.world_id=e.world_id "
            "and i.snapshot_id=v.source_snapshot_id) as source_invalidated "
            "from saved_world_entry e join world_alternate_version v "
            "on v.workspace_id=e.workspace_id and v.world_id=e.world_id "
            "and v.version_id=e.authored_version_id join world_structure_snapshot s "
            "on s.workspace_id=v.workspace_id and s.world_id=v.world_id "
            "and s.snapshot_id=v.source_snapshot_id where e.workspace_id=%s"
        )

    @staticmethod
    def _entry(row: dict[str, object]) -> SavedWorldEntry:
        from exulanica.world.starter import authored_starter_scene

        source_invalidated = bool(row["source_invalidated"])
        authored_changed = (
            row["authored_state_sha256"] != row["current_state_sha256"]
            or row["authored_edit_seq"] != row["current_edit_seq"]
        )
        unavailable = source_invalidated or authored_changed
        source_kind = row["source_kind"]
        if source_kind not in {"personal", "authored"}:
            raise ValueError("unknown saved world source kind")
        scene = (
            authored_starter_scene(
                composer_key=str(row["composer_key"]),
                composer_version=int(row["composer_version"]),
                topology=row["topology"],
                placement=row["placement"],
            )
            if source_kind == "authored"
            else None
        )
        return SavedWorldEntry(
            entry_id=row["entry_id"],
            world_id=row["world_id"],
            title=row["title"],
            source_kind=source_kind,
            source_snapshot_id=row["source_snapshot_id"],
            source_snapshot_sha256=row["snapshot_sha256"],
            authored_scene=scene,
            authored_version_id=row["authored_version_id"],
            authored_state_sha256=row["authored_state_sha256"],
            authored_edit_seq=row["authored_edit_seq"],
            current_authored_state_sha256=row["current_state_sha256"],
            current_authored_edit_seq=row["current_edit_seq"],
            style_version_id=row["style_version_id"],
            revision=row["revision"],
            availability="unavailable" if unavailable else "available",
            unavailable_reason=(
                "source_deleted"
                if source_invalidated
                else "authored_version_changed"
                if authored_changed
                else None
            ),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
