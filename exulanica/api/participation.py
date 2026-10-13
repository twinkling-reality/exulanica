"""Composition of browser invitation authority and the world's existing source authorization."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import psycopg

from exulanica.api.services import Services
from exulanica.api.society_making import SocietyHooks, society_repository
from exulanica.db.participant_role import assert_participant_role
from exulanica.epistemics.saved_names import recogniser, saved_names
from exulanica.evidence.blob import BlobId
from exulanica.participation import reads
from exulanica.participation.repository import (
    REFUSALS_PER_MINUTE,
    InvitationRepository,
    ParticipantScope,
    ParticipationRefused,
    RedemptionLimited,
    secret_sha256,
)
from exulanica.selection.validation import Session
from exulanica.world.baked_tiles import TILE_MEDIA_TYPE, BakedTileRepository
from exulanica.world.generated_worlds import generated_extent, generated_tiles
from exulanica.world.society import UnavailableSocietyInput, UnknownSociety
from exulanica.world.society_engines import society_engine
from exulanica.world.thing_looks import look_choices
from exulanica.world.thing_store import ThingStore
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.worlds import GENERATED, WorldIdentity, require_world


@dataclass(frozen=True)
class ParticipationRuntime:
    """Explicitly supplied to the app; its absence keeps visitor operations closed."""

    services: Services
    hooks: SocietyHooks

    def verify(self) -> None:
        with self.services.database.unscoped() as connection:
            assert_participant_role(connection)

    def host_open(self, workspace: uuid.UUID) -> None:
        accounts = self.services.accounts
        if accounts is None or not accounts.owned_workspace_active(workspace):
            raise ParticipationRefused()

    def eligible(
        self, connection: psycopg.Connection, workspace: uuid.UUID, world: str, version: uuid.UUID
    ) -> tuple[WorldIdentity, uuid.UUID, dict]:
        """Authorize sources and discard their private representation before any serving read."""
        identity = require_world(connection, workspace, world)
        if identity.kind not in ("authored-starter", GENERATED):
            raise ParticipationRefused()
        version_row = connection.execute(
            "select source_snapshot_id from world_alternate_version where workspace_id=%s "
            "and world_id=%s and version_id=%s",
            (workspace, world, version),
        ).fetchone()
        if version_row is None:
            raise ParticipationRefused()
        # Source-independent registration is not permission to share personal additions.
        for table in ("world_alternate_environment_instance", "world_alternate_point_map_instance"):
            if connection.execute(
                f"select 1 from {table} where workspace_id=%s and world_id=%s and version_id=%s "
                "and not removed limit 1",
                (workspace, world, version),
            ).fetchone():
                raise ParticipationRefused()
        for table in ("world_alternate_object", "world_alternate_thing"):
            if connection.execute(
                f"select 1 from {table} where workspace_id=%s and world_id=%s and version_id=%s "
                "and not removed and origin_role<>'fictional' limit 1",
                (workspace, world, version),
            ).fetchone():
                raise ParticipationRefused()
        if connection.execute(
            "select 1 from world_alternate_object where workspace_id=%s and world_id=%s "
            "and version_id=%s and not removed and workspace_preparation_id is not null limit 1",
            (workspace, world, version),
        ).fetchone():
            raise ParticipationRefused()
        session = Session(workspace, uuid.UUID(int=0))
        try:
            snapshot = society_repository(connection, session, self.hooks, world).snapshot(version)
        except (UnavailableSocietyInput, UnknownSociety) as error:
            # Source refusals can name private dependencies. A visitor receives the same closed
            # reference as an ended grant, without exposing that dependency or a server error.
            raise ParticipationRefused() from error
        if society_engine(snapshot["profile"]).state_family != "things":
            raise ParticipationRefused()
        return identity, version_row["source_snapshot_id"], snapshot

    def open(
        self, grant: uuid.UUID, actor: uuid.UUID, *, check_sources: bool = True
    ) -> ParticipantScope:
        with self.services.database.unscoped() as connection:
            row = connection.execute(
                "select workspace_id from world_grant_entry where grant_id=%s", (grant,)
            ).fetchone()
        if row is None:
            raise ParticipationRefused()
        workspace = row["workspace_id"]
        self.host_open(workspace)
        with self.services.database.session(workspace) as connection, connection.transaction():
            connection.execute("select participation_prune(1000)")
            lock_workspace(connection, workspace)
            repository = InvitationRepository(connection, workspace)
            scope = repository.scope(
                grant, actor, eligible=self.eligible if check_sources else lambda *_: None
            )
            if check_sources and recogniser(saved_names(connection, workspace))(
                repository.row(grant)["document"]["world_words"]
            ):
                raise ParticipationRefused()
            return scope

    def redeem(self, caller: Session, invitation: str, notice: str) -> dict:
        requester = secret_sha256(str(caller.actor))
        refusal = None
        result = None
        with (
            self.services.database.session(caller.workspace_id) as connection,
            connection.transaction(),
        ):
            # Serialize this browser's attempts without holding either workspace's world lock.
            connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("participation-redemption:" + str(caller.actor),),
            )
            connection.execute("select participation_prune(1000)")
            count = connection.execute(
                "select count(*) as n from participation_redemption_refusal where workspace_id=%s "
                "and requester_sha256=%s and refused_at>statement_timestamp()-interval '1 minute'",
                (caller.workspace_id, requester),
            ).fetchone()["n"]
            if count >= REFUSALS_PER_MINUTE:
                raise RedemptionLimited()
            try:
                result = self._redeem(caller, invitation, notice)
            except ParticipationRefused as error:
                refusal = error
                connection.execute(
                    "insert into participation_redemption_refusal(workspace_id,requester_sha256) "
                    "values(%s,%s)",
                    (caller.workspace_id, requester),
                )
        if refusal is not None:
            raise refusal
        assert result is not None
        return result

    def _redeem(self, caller: Session, invitation: str, notice: str) -> dict:
        if re.fullmatch(r"[A-Za-z0-9_-]{43}", invitation) is None:
            raise ParticipationRefused()
        with self.services.database.unscoped() as connection:
            entry = connection.execute(
                "select workspace_id,grant_id from world_grant_entry where secret_sha256=%s",
                (secret_sha256(invitation),),
            ).fetchone()
        if entry is None:
            raise ParticipationRefused()
        self.host_open(entry["workspace_id"])
        with self.services.database.session(entry["workspace_id"]) as connection:
            return InvitationRepository(connection, entry["workspace_id"]).redeem(
                entry["grant_id"], invitation, caller.actor, notice, eligible=self.eligible
            )

    def _standing(self, connection: psycopg.Connection, scope: ParticipantScope) -> dict:
        """Recheck authority after data read-ahead, serialized with revocation and erasure."""
        self.host_open(scope.workspace_id)
        lock_workspace(connection, scope.workspace_id)
        repository = InvitationRepository(connection, scope.workspace_id)
        row = repository.row(scope.grant_id)
        if (
            repository.state(row) != "bound"
            or row["used_at"] is None
            or row["principal_sha256"] != scope.principal_sha256
            or row["version_id"] != scope.version_id
            or row["world_id"] != scope.world_id
        ):
            raise ParticipationRefused()
        return row

    def grant(self, scope: ParticipantScope) -> dict:
        with (
            self.services.database.session(scope.workspace_id) as connection,
            connection.transaction(),
        ):
            return InvitationRepository.view(self._standing(connection, scope))

    def _drawing(
        self, connection: psycopg.Connection, scope: ParticipantScope
    ) -> tuple[dict, dict]:
        self._standing(connection, scope)
        identity, snapshot, society = self.eligible(
            connection, scope.workspace_id, scope.world_id, scope.version_id
        )
        geometry = {"tiles": [], "extent": None}
        if identity.kind == GENERATED:
            extent = generated_extent(connection, scope.workspace_id, scope.world_id, snapshot)
            geometry["extent"] = {
                "region_id": extent.region_id,
                "region_ids": list(extent.region_ids),
                "east_mm": list(extent.east_mm),
                "south_mm": list(extent.south_mm),
                "arrival_mm": list(extent.arrival_mm),
            }
            geometry["tiles"] = [
                {
                    "baked_tile_id": str(tile.baked_tile_id) if tile.baked_tile_id else None,
                    "tile_x": tile.tile_x,
                    "tile_y": tile.tile_y,
                    "state": tile.state,
                }
                for tile in generated_tiles(
                    connection, scope.workspace_id, scope.world_id, snapshot
                )
            ]
        return geometry, society

    def world(self, scope: ParticipantScope) -> dict:
        body = reads.world(self.services.database, scope)
        with (
            self.services.database.session(scope.workspace_id) as connection,
            connection.transaction(),
        ):
            geometry, _ = self._drawing(connection, scope)
            files = self._files(connection, scope)
        return body | geometry | {"files": list(files.values())}

    def society(self, scope: ParticipantScope) -> dict:
        body = reads.society(self.services.database, scope)
        with (
            self.services.database.session(scope.workspace_id) as connection,
            connection.transaction(),
        ):
            self._standing(connection, scope)
            self.eligible(connection, scope.workspace_id, scope.world_id, scope.version_id)
        return body

    def tile(self, scope: ParticipantScope, tile_id: uuid.UUID) -> tuple[bytes, str]:
        if self.services.tiles is None:
            raise ParticipationRefused()
        with self.services.database.session(scope.workspace_id) as connection:
            with connection.transaction():
                geometry, _ = self._drawing(connection, scope)
            if not any(
                t["baked_tile_id"] == str(tile_id) and t["state"] == "baked"
                for t in geometry["tiles"]
            ):
                raise ParticipationRefused()
            # Store I/O occurs on an idle connection, outside asset-read and workspace locks.
            served = BakedTileRepository(
                connection=connection, store=self.services.tiles
            ).serve_to_its_world(tile_id)
            self.host_open(scope.workspace_id)
            with connection.transaction():
                current, _ = self._drawing(connection, scope)
                if not any(
                    t["baked_tile_id"] == str(tile_id) and t["state"] == "baked"
                    for t in current["tiles"]
                ):
                    raise ParticipationRefused()
            return served.data, TILE_MEDIA_TYPE

    def file(self, scope: ParticipantScope, digest: str) -> tuple[bytes, str]:
        stores = self.services.content_stores
        if stores is None:
            raise ParticipationRefused()
        with self.services.database.session(scope.workspace_id) as connection:
            with connection.transaction():
                references = self._files(connection, scope)
            if digest not in references:
                raise ParticipationRefused()
            data = stores.looks.for_workspace(scope.workspace_id).get(BlobId.from_hex(digest))
            self.host_open(scope.workspace_id)
            with connection.transaction():
                current = self._files(connection, scope)
                if digest not in current or len(data) != current[digest]["bytes"]:
                    raise ParticipationRefused()
            return data, "model/gltf-binary"

    def _files(self, connection: psycopg.Connection, scope: ParticipantScope) -> dict:
        self._standing(connection, scope)
        _, _, snapshot = self.eligible(
            connection, scope.workspace_id, scope.world_id, scope.version_id
        )
        choices = look_choices(connection, scope.workspace_id, scope.world_id, scope.version_id)
        # Choice history outlives an inhabitant. Only a being still in the current authorized
        # snapshot makes its selected appearance a participant-readable reference.
        present = {person["id"] for person in snapshot["state"]["inhabitants"]}
        look_ids = {
            entry["look"]["sha256"]
            for entry in choices.get("workspace_looks", ())
            if entry["thing_id"] in present
        }
        store = ThingStore(connection, scope.workspace_id, None)
        for person in snapshot["state"]["inhabitants"]:
            reference = person.get("kind", {})
            if reference.get("source") == "workspace":
                kind = store.kind_by_digest(reference["sha256"])
                if kind is not None:
                    look_ids.update(look["sha256"] for look in kind.looks)
        result = {}
        for identity in sorted(look_ids):
            kept = store.look_by_digest(identity)
            if kept is not None and kept.container_sha256:
                result[kept.container_sha256] = {
                    "sha256": kept.container_sha256,
                    "bytes": kept.container_bytes,
                    "media_type": "model/gltf-binary",
                    "look_sha256": identity,
                }
        return result

    def leave(self, scope: ParticipantScope, actor: uuid.UUID) -> None:
        with self.services.database.session(scope.workspace_id) as connection:
            InvitationRepository(connection, scope.workspace_id).leave(
                scope.grant_id, actor, eligible=lambda *_: None
            )
