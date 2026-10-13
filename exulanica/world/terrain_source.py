"""Current terrain contact authority for versions with no authored occupancy delta."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Literal

from psycopg import sql

from exulanica.db.read_check import final_read_check
from exulanica.world.authored_delta import DELTA_SECTIONS, AlternateVersion
from exulanica.world.composers.site_plan import receipt_terrain
from exulanica.world.errors import InvalidStructuralData, StaleObjectBase
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.kinds.worker import TerrainDressingWorkerCompiler
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.reviewed_catalog import ReviewedCatalog
from exulanica.world.terrain_authoring import TERRAIN_COMPOSER_VERSIONS
from exulanica.world.terrain_dressing_authority import (
    require_terrain_dressing_current,
    resolve_terrain_dressing,
)
from exulanica.world.worlds import require_world

# The read model omits undone additions. Those retained rows also keep this conservative gate
# closed, so returning to an empty visible delta does not imply reconciled occupancy.
_DELTA_TABLES = {
    "objects": "world_alternate_object",
    "element_overrides": "world_alternate_element_override",
    "environment_instances": "world_alternate_environment_instance",
    "point_map_instances": "world_alternate_point_map_instance",
    "things": "world_alternate_thing",
}


@dataclass(frozen=True, slots=True)
class TerrainSourceProof:
    """A read-time source proof pinned to one exact authorized version state."""

    world_id: str
    version_id: str
    source_snapshot_id: str
    receipt_sha256: str
    geometry_sha256: str
    contact_sha256: str
    authored_state_sha256: str
    status: Literal["verified", "unavailable"]
    reason: Literal["authored_occupancy_unreconciled"] | None
    profile: Literal["exulanica.terrain-source-proof/v1", "exulanica.terrain-source-proof/v2"] = (
        "exulanica.terrain-source-proof/v1"
    )
    dressing_sha256: str | None = None

    def document(self) -> dict:
        document = asdict(self)
        if self.dressing_sha256 is None:
            del document["dressing_sha256"]
        return document


def _has_authored_delta(version: AlternateVersion) -> bool:
    return any(getattr(version, section.key) for section in DELTA_SECTIONS)


def _has_retained_delta(repository: WorldObjectRepository, version_id: uuid.UUID) -> bool:
    # Fail closed if a new authored section has not acquired a retained-row authority check.
    if set(_DELTA_TABLES) != {section.key for section in DELTA_SECTIONS}:
        raise InvalidStructuralData("terrain occupancy section coverage is incomplete")
    queries = [
        sql.SQL("select 1 from {} where workspace_id=%s and world_id=%s and version_id=%s").format(
            sql.Identifier(_DELTA_TABLES[section.key])
        )
        for section in DELTA_SECTIONS
    ]
    row = repository.connection.execute(
        sql.SQL("select exists({}) as occupied").format(sql.SQL(" union all ").join(queries)),
        (repository.workspace_id, repository.world_id, version_id) * len(queries),
    ).fetchone()
    return bool(row["occupied"])


def read_terrain_source(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    *,
    expected_state_sha256: str | None = None,
) -> TerrainSourceProof:
    """Read exact source pins and refuse any unreconciled authored occupancy.

    This does not grant future authority. Consumers bind the result to the returned version and
    state and re-read after changes. Dressed sources verify current bytes before the final
    read barrier.
    Existing scope errors conceal foreign versions; invalidation and stale reads retain their
    normal named exceptions. A final authority check follows source validation and occupancy I/O.
    """
    scope = (repository.connection, repository.workspace_id, repository.world_id)
    require_world(*scope)
    initial = repository.edit_base_row(version_id)
    repository.require_edit_base(
        initial, initial["state_sha256"] if expected_state_sha256 is None else expected_state_sha256
    )
    version = repository.version(version_id, with_availability=False)
    snapshot = repository.connection.execute(
        "select composer_key,composer_version from world_structure_snapshot "
        "where workspace_id=%s and world_id=%s and snapshot_id=%s",
        (repository.workspace_id, repository.world_id, version.source_snapshot_id),
    ).fetchone()
    if (
        snapshot is None
        or snapshot["composer_key"] != "site-plan"
        or snapshot["composer_version"] not in TERRAIN_COMPOSER_VERSIONS
    ):
        raise InvalidStructuralData("terrain_contact_source_unavailable")
    receipt_sha, receipt = generation_receipt(*scope, version.source_snapshot_id)
    source = receipt_terrain(receipt)
    resolved = resolve_terrain_dressing(
        ReviewedCatalog(repository.connection),
        repository.store,
        source,
        compile_coverage=TerrainDressingWorkerCompiler(repository.workspace_id),
    )
    occupied = _has_authored_delta(version) or _has_retained_delta(repository, version_id)
    with final_read_check(repository.connection, not_idle="terrain proof requires an idle read"):
        require_world(*scope)
        final = repository.edit_base_row(version_id)
        repository.require_edit_base(final, version.state_sha256)
        if (
            final["source_snapshot_id"] != version.source_snapshot_id
            or initial["source_snapshot_id"] != version.source_snapshot_id
            or initial["state_sha256"] != version.state_sha256
            or initial["edit_seq"] != version.edit_seq
            or final["edit_seq"] != version.edit_seq
        ):
            raise StaleObjectBase("terrain contact source changed while it was read")
        final_digest, _ = generation_receipt(*scope, version.source_snapshot_id)
        if final_digest != receipt_sha:
            raise StaleObjectBase("terrain receipt changed while it was read")
        if resolved is not None:
            require_terrain_dressing_current(ReviewedCatalog(repository.connection), resolved)
    return TerrainSourceProof(
        world_id=repository.world_id,
        version_id=str(version_id),
        source_snapshot_id=str(version.source_snapshot_id),
        receipt_sha256=receipt_sha,
        geometry_sha256=source.contact.geometry.sha256,
        contact_sha256=source.contact.sha256,
        authored_state_sha256=version.state_sha256,
        status="unavailable" if occupied else "verified",
        reason="authored_occupancy_unreconciled" if occupied else None,
        profile="exulanica.terrain-source-proof/v2"
        if resolved is not None
        else "exulanica.terrain-source-proof/v1",
        dressing_sha256=resolved.dressing.sha256 if resolved is not None else None,
    )
