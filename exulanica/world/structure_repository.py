"""PostgreSQL compare-and-swap authority for immutable spatial world snapshots."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import sha256_of_canonical
from exulanica.world.composed import composed_candidate
from exulanica.world.errors import (
    InvalidStructuralData,
    InvalidStructuralPreviewState,
    StaleStructuralBase,
    UnknownWorldResource,
)
from exulanica.world.models import DEFAULT_WORLD_ID, TopologyContract, TopologySourceSlot
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.structure import (
    SpatialCandidate,
    SpatialDigests,
    SpatialPreview,
    SpatialSnapshot,
    candidate_from_document,
    canonical_candidate_document,
    protected_diff,
    validate_candidate,
)

__all__ = ["WorldStructureRepository"]

_WORKSPACE_LOCK_SEED: Final = 880_024


class WorldStructureRepository:
    """One workspace/world's reviewed structural preview and current-snapshot lifecycle."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str = DEFAULT_WORLD_ID,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id

    def preview(self, candidate: SpatialCandidate, *, proposed_by: uuid.UUID) -> SpatialPreview:
        """Validate a candidate against every current protected base without moving authority."""
        digests = validate_candidate(candidate)
        self._assert_world(candidate)
        document = canonical_candidate_document(candidate)
        with self.connection.transaction():
            self._lock_workspace()
            state = self._state(for_update=True)
            previous = (
                None
                if state is None
                else self._candidate_for_snapshot(state["current_snapshot_id"])
            )
            self._validate_database_dependencies(candidate)
            self._validate_stable_owners(candidate)
            self._validate_region_migrations(previous, candidate)
            difference = protected_diff(previous, candidate)
            checks = {
                "schema_version": 1,
                "canonical_sha256": "pass",
                "stable_identity": "pass",
                "reachability": "pass",
                "collision": "pass",
                "evidence_liveness": "pass",
                "placement_migrations": "pass",
            }
            preview_id = uuid.uuid4()
            base_snapshot_id = None if state is None else state["current_snapshot_id"]
            base_graph = None if state is None else state["current_graph_sha256"]
            base_reconstruction = None if state is None else state["current_reconstruction_sha256"]
            self.connection.execute(
                "insert into world_structure_preview "
                "(preview_id,workspace_id,world_id,base_snapshot_id,base_graph_sha256,"
                "base_reconstruction_sha256,candidate,protected_diff,validation_checks,"
                "proposed_by) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    preview_id,
                    self.workspace_id,
                    self.world_id,
                    base_snapshot_id,
                    base_graph,
                    base_reconstruction,
                    Jsonb(document),
                    Jsonb(difference),
                    Jsonb(checks),
                    proposed_by,
                ),
            )
            self._audit(
                "preview_created",
                actor=proposed_by,
                preview_id=preview_id,
                details={"candidate_snapshot_sha256": digests.snapshot_sha256},
            )
        return SpatialPreview(
            preview_id,
            base_snapshot_id,
            base_graph,
            base_reconstruction,
            candidate,
            digests,
            difference,
            checks,
        )

    def apply(
        self,
        preview_id: uuid.UUID,
        *,
        base_snapshot_id: uuid.UUID | None,
        base_graph_sha256: str | None,
        base_reconstruction_sha256: str | None,
        committed_by: uuid.UUID,
        base_composed_topology_digest: str | None = None,
    ) -> SpatialSnapshot:
        """Atomically revalidate, append, and CAS every protected current base."""
        failure: Exception | None = None
        result: SpatialSnapshot | None = None
        with self.connection.transaction():
            self._lock_workspace()
            state = self._state(for_update=True)
            preview = self._preview_row(preview_id, for_update=True)
            if preview["status"] != "open":
                raise InvalidStructuralPreviewState(
                    f"structural preview {preview_id} is {preview['status']}, not open"
                )
            actual = self._base_tuple(state)
            supplied = (base_snapshot_id, base_graph_sha256, base_reconstruction_sha256)
            proposed = (
                preview["base_snapshot_id"],
                preview["base_graph_sha256"],
                preview["base_reconstruction_sha256"],
            )
            if supplied != actual or proposed != actual:
                failure = StaleStructuralBase(
                    "the structural preview no longer names the current world, graph, and "
                    "reconstruction bases"
                )
                self._close_stale(preview_id, committed_by, actual)
            else:
                candidate = candidate_from_document(preview["candidate"])
                digests = validate_candidate(candidate)
                self._assert_world(candidate)
                previous = (
                    None
                    if state is None
                    else self._candidate_for_snapshot(state["current_snapshot_id"])
                )
                self._validate_database_dependencies(candidate)
                self._validate_stable_owners(candidate)
                region_changes = self._validate_region_migrations(previous, candidate)
                preserved = None
                if base_composed_topology_digest is not None:
                    preserved = WorldStyleRepository(
                        self.connection, self.workspace_id, world_id=self.world_id
                    ).current_topology_contract()
                    if (
                        state is not None
                        or preserved.topology_digest != base_composed_topology_digest
                    ):
                        raise StaleStructuralBase(
                            "bootstrap no longer names the initial composed base"
                        )
                    expected = composed_candidate(
                        preserved, candidate.graph_sha256, candidate.reconstruction_sha256
                    )
                    if canonical_candidate_document(candidate) != canonical_candidate_document(
                        expected
                    ):
                        raise InvalidStructuralData(
                            "bootstrap must preserve the exact composed sources"
                        )
                result = self._commit_snapshot(
                    preview_id,
                    candidate,
                    digests,
                    state,
                    region_changes,
                    committed_by,
                    preserved,
                )
        if failure is not None:
            raise failure
        assert result is not None
        return result

    def discard(self, preview_id: uuid.UUID, *, discarded_by: uuid.UUID) -> None:
        with self.connection.transaction():
            preview = self._preview_row(preview_id, for_update=True)
            if preview["status"] == "discarded":
                return
            if preview["status"] != "open":
                raise InvalidStructuralPreviewState(
                    f"structural preview {preview_id} is {preview['status']}, not open"
                )
            self.connection.execute(
                "update world_structure_preview set status='discarded',closed_at=now() "
                "where workspace_id=%s and world_id=%s and preview_id=%s",
                (self.workspace_id, self.world_id, preview_id),
            )
            self._audit("preview_discarded", actor=discarded_by, preview_id=preview_id, details={})

    def current(self) -> SpatialSnapshot | None:
        """The literal current pointer, including its invalidated state."""
        state = self._state(for_update=False)
        return None if state is None else self._snapshot(state["current_snapshot_id"])

    def effective_current(self) -> SpatialSnapshot | None:
        """Nearest non-invalid ancestor, or no world when deletion invalidated the lineage."""
        state = self._state(for_update=False)
        if state is None:
            return None
        row = self.connection.execute(
            "with recursive lineage as ("
            " select s.snapshot_id,s.parent_snapshot_id,0 as depth"
            " from world_structure_snapshot s"
            " where s.workspace_id=%s and s.world_id=%s and s.snapshot_id=%s"
            " union all"
            " select p.snapshot_id,p.parent_snapshot_id,l.depth+1"
            " from lineage l join world_structure_snapshot p"
            " on p.workspace_id=%s and p.world_id=%s and p.snapshot_id=l.parent_snapshot_id"
            ") select l.snapshot_id from lineage l"
            " where not exists (select 1 from world_structure_invalidation i"
            " where i.workspace_id=%s and i.world_id=%s and i.snapshot_id=l.snapshot_id)"
            " order by l.depth limit 1",
            (
                self.workspace_id,
                self.world_id,
                state["current_snapshot_id"],
                self.workspace_id,
                self.world_id,
                self.workspace_id,
                self.world_id,
            ),
        ).fetchone()
        return None if row is None else self._snapshot(row["snapshot_id"])

    def versions(self) -> tuple[SpatialSnapshot, ...]:
        rows = self.connection.execute(
            "select snapshot_id from world_structure_snapshot "
            "where workspace_id=%s and world_id=%s order by revision",
            (self.workspace_id, self.world_id),
        ).fetchall()
        return tuple(self._snapshot(row["snapshot_id"]) for row in rows)

    # -- commit internals -----------------------------------------------------------------

    def _commit_snapshot(
        self,
        preview_id: uuid.UUID,
        candidate: SpatialCandidate,
        digests: SpatialDigests,
        state: Mapping[str, Any] | None,
        region_changes: Mapping[str, tuple[str, str]],
        committed_by: uuid.UUID,
        preserved_topology: TopologyContract | None = None,
    ) -> SpatialSnapshot:
        revision = (
            0
            if state is None
            else int(self._snapshot_row(state["current_snapshot_id"])["revision"]) + 1
        )
        parent_id = None if state is None else state["current_snapshot_id"]
        snapshot_id = uuid.uuid4()
        topology_contract = (
            replace(preserved_topology, topology_digest=digests.topology_sha256)
            if preserved_topology is not None
            else self._topology_contract(candidate, digests)
        )
        styles = WorldStyleRepository(self.connection, self.workspace_id, world_id=self.world_id)
        if preserved_topology is None:
            styles.register_topology(topology_contract)
        else:
            # Satisfy the snapshot FK without moving the composed source pointer or style.
            styles.register_topology_history(topology_contract)
        projection = self._package_projection(snapshot_id, revision, parent_id, candidate, digests)
        self.connection.execute(
            "insert into world_structure_snapshot "
            "(snapshot_id,workspace_id,world_id,revision,parent_snapshot_id,graph_sha256,"
            "reconstruction_sha256,topology_sha256,layout_sha256,placement_sha256,"
            "neighborhood_sha256,snapshot_sha256,composer_key,composer_version,topology,layout,"
            "placement,neighborhood,package_projection,committed_by) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                snapshot_id,
                self.workspace_id,
                self.world_id,
                revision,
                parent_id,
                candidate.graph_sha256,
                candidate.reconstruction_sha256,
                digests.topology_sha256,
                digests.layout_sha256,
                digests.placement_sha256,
                digests.neighborhood_sha256,
                digests.snapshot_sha256,
                candidate.composer_key,
                candidate.composer_version,
                Jsonb(dict(candidate.topology)),
                Jsonb(dict(candidate.layout)),
                Jsonb(dict(candidate.placement)),
                Jsonb(dict(candidate.neighborhood)),
                Jsonb(projection),
                committed_by,
            ),
        )
        region_digests = self._region_placement_digests(candidate)
        for region_id, placement_sha256 in sorted(region_digests.items()):
            self.connection.execute(
                "insert into world_structure_snapshot_region "
                "(workspace_id,world_id,snapshot_id,region_id,placement_sha256) "
                "values (%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    self.world_id,
                    snapshot_id,
                    region_id,
                    placement_sha256,
                ),
            )
        placement_by_id = {
            value["element_id"]: sha256_of_canonical(value).hex()
            for value in candidate.placement["elements"]
        }
        for element in sorted(
            candidate.topology["elements"], key=lambda value: value["element_id"]
        ):
            element_id = element["element_id"]
            owner = element["owner"]
            inserted = self.connection.execute(
                "insert into world_structure_element_identity "
                "(workspace_id,world_id,element_id,owner_kind,owner_id,first_snapshot_id) "
                "values (%s,%s,%s,%s,%s,%s) on conflict do nothing returning element_id",
                (
                    self.workspace_id,
                    self.world_id,
                    element_id,
                    owner["kind"],
                    owner["id"],
                    snapshot_id,
                ),
            ).fetchone()
            if inserted is None:
                self._assert_owner(element_id, owner["kind"], owner["id"])
            region_id = owner["id"] if owner["kind"] == "region" else None
            self.connection.execute(
                "insert into world_structure_snapshot_element "
                "(workspace_id,world_id,snapshot_id,element_id,region_id,placement_sha256) "
                "values (%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    self.world_id,
                    snapshot_id,
                    element_id,
                    region_id,
                    placement_by_id[element_id],
                ),
            )
        for dependency in self._dependencies(candidate):
            self.connection.execute(
                "insert into world_structure_dependency "
                "(workspace_id,world_id,snapshot_id,dependency_kind,dependency_ref,element_id) "
                "values (%s,%s,%s,%s,%s,%s) on conflict do nothing",
                (
                    self.workspace_id,
                    self.world_id,
                    snapshot_id,
                    dependency["kind"],
                    dependency["ref"],
                    dependency["element_id"],
                ),
            )
        migrations = {value.region_id: value for value in candidate.placement_migrations}
        for region_id, (old_digest, new_digest) in sorted(region_changes.items()):
            migration = migrations[region_id]
            self.connection.execute(
                "insert into world_structure_placement_migration "
                "(migration_id,workspace_id,world_id,snapshot_id,region_id,"
                "from_placement_sha256,to_placement_sha256,reason,approved_by) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    migration.migration_id,
                    self.workspace_id,
                    self.world_id,
                    snapshot_id,
                    region_id,
                    old_digest,
                    new_digest,
                    migration.reason,
                    committed_by,
                ),
            )
        if state is None:
            self.connection.execute(
                "insert into world_structure_state "
                "(workspace_id,world_id,current_snapshot_id,current_graph_sha256,"
                "current_reconstruction_sha256) values (%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    self.world_id,
                    snapshot_id,
                    candidate.graph_sha256,
                    candidate.reconstruction_sha256,
                ),
            )
        else:
            updated = self.connection.execute(
                "update world_structure_state set current_snapshot_id=%s,current_graph_sha256=%s,"
                "current_reconstruction_sha256=%s,updated_at=now() "
                "where workspace_id=%s and world_id=%s and current_snapshot_id=%s "
                "returning current_snapshot_id",
                (
                    snapshot_id,
                    candidate.graph_sha256,
                    candidate.reconstruction_sha256,
                    self.workspace_id,
                    self.world_id,
                    state["current_snapshot_id"],
                ),
            ).fetchone()
            if updated is None:
                raise StaleStructuralBase("the structural pointer changed during commit")
        self.connection.execute(
            "update world_structure_preview set status='applied',closed_at=now() "
            "where workspace_id=%s and world_id=%s and preview_id=%s",
            (self.workspace_id, self.world_id, preview_id),
        )
        self._audit(
            "preview_applied",
            actor=committed_by,
            preview_id=preview_id,
            snapshot_id=snapshot_id,
            details={"snapshot_sha256": digests.snapshot_sha256},
        )
        return SpatialSnapshot(
            snapshot_id,
            revision,
            parent_id,
            candidate,
            digests,
            projection,
            committed_by,
            False,
        )

    # -- validation against durable state -------------------------------------------------

    def _validate_database_dependencies(self, candidate: SpatialCandidate) -> None:
        for dependency in self._dependencies(candidate):
            kind = dependency["kind"]
            reference = uuid.UUID(dependency["ref"])
            if kind == "evidence_span":
                row = self.connection.execute(
                    "select span_id,tombstone_blocks_any_span(%s,array[span_id]) as blocked "
                    "from evidence_span where workspace_id=%s and span_id=%s",
                    (self.workspace_id, self.workspace_id, reference),
                ).fetchone()
            elif kind == "capture":
                row = self.connection.execute(
                    "select capture_id,(deleted_at is not null or "
                    "tombstone_blocks_capture(%s,capture_id)) as blocked "
                    "from capture where workspace_id=%s and capture_id=%s",
                    (self.workspace_id, self.workspace_id, reference),
                ).fetchone()
            elif kind == "entity":
                row = self.connection.execute(
                    "select entity_id,(deleted_at is not null or "
                    "tombstone_blocks_entity(%s,entity_id)) as blocked "
                    "from entity where workspace_id=%s and entity_id=%s",
                    (self.workspace_id, self.workspace_id, reference),
                ).fetchone()
            else:
                row = self.connection.execute(
                    "select assertion_id,(status<>'active' or exists ("
                    "select 1 from tombstone t where t.workspace_id=%s "
                    "and t.effective_at<=clock_timestamp() and "
                    "(t.scope='workspace' or (t.scope='assertion' and "
                    "t.assertion_id=assertion.assertion_id)))) as blocked "
                    "from assertion where workspace_id=%s and assertion_id=%s",
                    (self.workspace_id, self.workspace_id, reference),
                ).fetchone()
            if row is None:
                raise InvalidStructuralData(
                    f"{kind} dependency {reference} is absent from the authorised workspace"
                )
            if row["blocked"]:
                raise InvalidStructuralData(
                    f"{kind} dependency {reference} is deleted, retracted, or tombstoned"
                )

    def _validate_stable_owners(self, candidate: SpatialCandidate) -> None:
        for element in candidate.topology["elements"]:
            row = self.connection.execute(
                "select owner_kind,owner_id from world_structure_element_identity "
                "where workspace_id=%s and world_id=%s and element_id=%s",
                (self.workspace_id, self.world_id, element["element_id"]),
            ).fetchone()
            if row is not None and (
                row["owner_kind"] != element["owner"]["kind"]
                or row["owner_id"] != element["owner"]["id"]
            ):
                raise InvalidStructuralData(
                    f"stable element {element['element_id']} cannot change semantic owner"
                )

    def _validate_region_migrations(
        self, previous: SpatialCandidate | None, candidate: SpatialCandidate
    ) -> dict[str, tuple[str, str]]:
        if previous is None:
            if candidate.placement_migrations:
                raise InvalidStructuralData(
                    "an initial snapshot cannot declare placement migrations"
                )
            return {}
        before = self._region_placement_digests(previous)
        after = self._region_placement_digests(candidate)
        changes = {
            region_id: (before[region_id], after[region_id])
            for region_id in before.keys() & after.keys()
            if before[region_id] != after[region_id]
        }
        declared = {value.region_id for value in candidate.placement_migrations}
        missing = sorted(set(changes) - declared)
        surplus = sorted(declared - set(changes))
        if missing:
            raise InvalidStructuralData(
                "existing region placement changed without a recorded migration: "
                + ", ".join(missing)
            )
        if surplus:
            raise InvalidStructuralData(
                "placement migrations must correspond to an actual protected change: "
                + ", ".join(surplus)
            )
        return changes

    # -- document and row adapters --------------------------------------------------------

    def _topology_contract(
        self, candidate: SpatialCandidate, digests: SpatialDigests
    ) -> TopologyContract:
        slots: list[TopologySourceSlot] = []
        for element in candidate.topology["elements"]:
            evidence = element["evidence"]
            if evidence["kind"] == "none":
                continue
            element_id = element["element_id"]
            owner = element["owner"]
            slots.append(
                TopologySourceSlot(
                    source_id=uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"exulanica:{self.workspace_id}:{self.world_id}:{element_id}:source",
                    ),
                    slot_key=f"source.{sha256_of_canonical(element_id).hex()[:20]}",
                    region_id=owner["id"] if owner["kind"] == "region" else None,
                    evidence_span_id=(
                        uuid.UUID(evidence["span_id"]) if evidence["kind"] == "span" else None
                    ),
                    missing_reason=(evidence["reason"] if evidence["kind"] == "missing" else None),
                )
            )
        return TopologyContract(
            digests.topology_sha256,
            tuple(sorted(value["region_id"] for value in candidate.topology["regions"])),
            tuple(slots),
            world_id=self.world_id,
        )

    def _dependencies(self, candidate: SpatialCandidate) -> list[dict[str, Any]]:
        values = [dict(value) for value in candidate.topology["dependencies"]]
        known = {(value["kind"], value["ref"], value["element_id"]) for value in values}
        for element in candidate.topology["elements"]:
            evidence = element["evidence"]
            if evidence["kind"] != "span":
                continue
            value = ("evidence_span", evidence["span_id"], element["element_id"])
            if value not in known:
                values.append({"kind": value[0], "ref": value[1], "element_id": value[2]})
                known.add(value)
        return sorted(
            values, key=lambda value: (value["kind"], value["ref"], value["element_id"] or "")
        )

    def _region_placement_digests(self, candidate: SpatialCandidate) -> dict[str, str]:
        owner_by_element = {
            element["element_id"]: element["owner"] for element in candidate.topology["elements"]
        }
        grouped: dict[str, list[Mapping[str, Any]]] = {
            value["region_id"]: [] for value in candidate.topology["regions"]
        }
        for placement in candidate.placement["elements"]:
            owner = owner_by_element[placement["element_id"]]
            if owner["kind"] == "region":
                grouped[owner["id"]].append(placement)
        return {
            region_id: sha256_of_canonical(
                sorted(values, key=lambda value: value["element_id"])
            ).hex()
            for region_id, values in grouped.items()
        }

    def _package_projection(
        self,
        snapshot_id: uuid.UUID,
        revision: int,
        parent_id: uuid.UUID | None,
        candidate: SpatialCandidate,
        digests: SpatialDigests,
    ) -> dict[str, Any]:
        return {
            "profile": "https://exulanica.local/profiles/spatial-authority/1",
            "snapshot_id": str(snapshot_id),
            "revision": revision,
            "parent_snapshot_id": None if parent_id is None else str(parent_id),
            "snapshot_sha256": digests.snapshot_sha256,
            "input_snapshots": {
                "graph_sha256": candidate.graph_sha256,
                "reconstruction_sha256": candidate.reconstruction_sha256,
            },
            "sections": [
                {"path": "world/topology.json", "sha256": digests.topology_sha256},
                {"path": "world/layout.json", "sha256": digests.layout_sha256},
                {"path": "world/placement.json", "sha256": digests.placement_sha256},
                {"path": "world/neighborhood.json", "sha256": digests.neighborhood_sha256},
            ],
            "compatibility": {
                "composer_key": candidate.composer_key,
                "composer_version": candidate.composer_version,
                "fixed_point_coordinate_unit": "millimetre",
            },
        }

    def _candidate_for_snapshot(self, snapshot_id: uuid.UUID) -> SpatialCandidate:
        row = self._snapshot_row(snapshot_id)
        return SpatialCandidate(
            graph_sha256=row["graph_sha256"],
            reconstruction_sha256=row["reconstruction_sha256"],
            topology=row["topology"],
            layout=row["layout"],
            placement=row["placement"],
            neighborhood=row["neighborhood"],
            composer_key=row["composer_key"],
            composer_version=row["composer_version"],
            placement_migrations=(),
        )

    def _snapshot(self, snapshot_id: uuid.UUID) -> SpatialSnapshot:
        row = self._snapshot_row(snapshot_id)
        candidate = self._candidate_for_snapshot(snapshot_id)
        invalidated = (
            self.connection.execute(
                "select 1 from world_structure_invalidation "
                "where workspace_id=%s and world_id=%s and snapshot_id=%s limit 1",
                (self.workspace_id, self.world_id, snapshot_id),
            ).fetchone()
            is not None
        )
        return SpatialSnapshot(
            snapshot_id=row["snapshot_id"],
            revision=row["revision"],
            parent_snapshot_id=row["parent_snapshot_id"],
            candidate=candidate,
            digests=SpatialDigests(
                row["topology_sha256"],
                row["layout_sha256"],
                row["placement_sha256"],
                row["neighborhood_sha256"],
                row["snapshot_sha256"],
            ),
            package_projection=row["package_projection"],
            committed_by=row["committed_by"],
            invalidated=invalidated,
        )

    def _snapshot_row(self, snapshot_id: uuid.UUID) -> Mapping[str, Any]:
        row = self.connection.execute(
            "select * from world_structure_snapshot where workspace_id=%s and world_id=%s "
            "and snapshot_id=%s",
            (self.workspace_id, self.world_id, snapshot_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such structural world snapshot")
        return row

    def _state(self, *, for_update: bool) -> Mapping[str, Any] | None:
        return self.connection.execute(
            "select * from world_structure_state where workspace_id=%s and world_id=%s"
            + (" for update" if for_update else ""),
            (self.workspace_id, self.world_id),
        ).fetchone()

    def _preview_row(self, preview_id: uuid.UUID, *, for_update: bool) -> Mapping[str, Any]:
        row = self.connection.execute(
            "select * from world_structure_preview where workspace_id=%s and world_id=%s "
            "and preview_id=%s" + (" for update" if for_update else ""),
            (self.workspace_id, self.world_id, preview_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such structural world preview")
        return row

    def _assert_world(self, candidate: SpatialCandidate) -> None:
        if candidate.topology["world_id"] != self.world_id:
            raise InvalidStructuralData("candidate topology belongs to another world")

    def _assert_owner(self, element_id: str, owner_kind: str, owner_id: str) -> None:
        row = self.connection.execute(
            "select owner_kind,owner_id from world_structure_element_identity "
            "where workspace_id=%s and world_id=%s and element_id=%s",
            (self.workspace_id, self.world_id, element_id),
        ).fetchone()
        if row is None or row["owner_kind"] != owner_kind or row["owner_id"] != owner_id:
            raise InvalidStructuralData(f"stable element {element_id} changed owner")

    def _lock_workspace(self) -> None:
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s::text,%s))",
            (self.workspace_id, _WORKSPACE_LOCK_SEED),
        )

    @staticmethod
    def _base_tuple(
        state: Mapping[str, Any] | None,
    ) -> tuple[uuid.UUID | None, str | None, str | None]:
        if state is None:
            return (None, None, None)
        return (
            state["current_snapshot_id"],
            state["current_graph_sha256"],
            state["current_reconstruction_sha256"],
        )

    def _close_stale(
        self,
        preview_id: uuid.UUID,
        actor: uuid.UUID,
        actual: tuple[uuid.UUID | None, str | None, str | None],
    ) -> None:
        self.connection.execute(
            "update world_structure_preview set status='stale',closed_at=now() "
            "where workspace_id=%s and world_id=%s and preview_id=%s",
            (self.workspace_id, self.world_id, preview_id),
        )
        self._audit(
            "preview_stale",
            actor=actor,
            preview_id=preview_id,
            details={
                "current_snapshot_id": None if actual[0] is None else str(actual[0]),
                "current_graph_sha256": actual[1],
                "current_reconstruction_sha256": actual[2],
            },
        )

    def _audit(
        self,
        event_type: str,
        *,
        actor: uuid.UUID | None,
        details: Mapping[str, Any],
        preview_id: uuid.UUID | None = None,
        snapshot_id: uuid.UUID | None = None,
    ) -> None:
        self.connection.execute(
            "insert into world_structure_audit_event "
            "(workspace_id,world_id,event_type,actor,preview_id,snapshot_id,details) "
            "values (%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                self.world_id,
                event_type,
                actor,
                preview_id,
                snapshot_id,
                Jsonb(dict(details)),
            ),
        )
