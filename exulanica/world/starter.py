"""Source-independent authored starter-world authority.

The starter is a real structural snapshot with one explicitly authored region.  It contains no
capture, evidence span, reconstruction or inferred source slot.  The built-in ground module is a
versioned renderer contract, and the saved entry remains the exact resume authority.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg

from exulanica.canonical import sha256_of_canonical
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.models import StyleVersion
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.structure import SpatialCandidate
from exulanica.world.structure_repository import WorldStructureRepository
from exulanica.world.worlds import AUTHORED_STARTER, register_world

AUTHORED_STARTER_COMPOSER: Final = "authored-starter-world"
AUTHORED_STARTER_COMPOSER_VERSION: Final = 1
AUTHORED_GROUND_MODULE: Final = "region.authored-ground"
AUTHORED_GROUND_MODULE_VERSION: Final = 2
AUTHORED_GROUND_RECIPE: Final = "region.authored-starter"
AUTHORED_GROUND_STREAMING_KEY: Final = "builtin:region.authored-ground@2"
AUTHORED_STARTER_REGION_ID: Final = "region:starter"
AUTHORED_STARTER_ELEMENT_ID: Final = "element:starter-ground"
AUTHORED_STARTER_DESTINATION_ID: Final = "destination:region:starter"
AUTHORED_GROUND_ELEVATION_MM: Final = 0
AUTHORED_SPAWN_X_MM: Final = 0
AUTHORED_SPAWN_Y_MM: Final = 0
AUTHORED_SPAWN_Z_MM: Final = 4_000
AUTHORED_SPAWN_YAW_MICRORADIANS: Final = 0

# Version 1 stated a 24 metre by 24 metre rectangle. The constants stay because entries created
# against that module version keep it: a stored descriptor is read at the version it was written
# at, and nothing here migrates one.
AUTHORED_GROUND_V1_MODULE_VERSION: Final = 1
AUTHORED_GROUND_V1_STREAMING_KEY: Final = "builtin:region.authored-ground@1"
AUTHORED_GROUND_V1_HALF_WIDTH_MM: Final = 12_000
AUTHORED_GROUND_V1_HALF_DEPTH_MM: Final = 12_000

_EMPTY_GRAPH_SHA256: Final = sha256_of_canonical(
    {"schema_version": 1, "plane": "graph", "observations": []}
).hex()
_EMPTY_RECONSTRUCTION_SHA256: Final = sha256_of_canonical(
    {"schema_version": 1, "plane": "reconstruction", "artifacts": []}
).hex()


@dataclass(frozen=True, slots=True)
class BoundedAuthoredGround:
    """A ground whose horizontal extent is a real property of the place it describes."""

    kind: Literal["flat"]
    half_width_mm: int
    half_depth_mm: int
    elevation_mm: int


@dataclass(frozen=True, slots=True)
class EndlessAuthoredGround:
    """A flat plane that states it has no horizontal extent, so it carries none.

    A starter world is empty space to build in. It has no edge to describe, so a descriptor that
    named one would be authoring a wall rather than recording a fact. How far a renderer can
    actually carry a person across such a plane is a property of that renderer, not of the world,
    and it belongs where it is measured rather than in a stored descriptor that every world born
    today would keep for good.
    """

    kind: Literal["endless"]
    elevation_mm: int


AuthoredGround = BoundedAuthoredGround | EndlessAuthoredGround


@dataclass(frozen=True, slots=True)
class AuthoredSpawn:
    x_mm: int
    y_mm: int
    z_mm: int
    yaw_microradians: int


@dataclass(frozen=True, slots=True)
class AuthoredModule:
    key: str
    version: int


@dataclass(frozen=True, slots=True)
class AuthoredRegion:
    region_id: str
    origin: Literal["authored"]
    module: AuthoredModule
    ground: AuthoredGround
    spawn: AuthoredSpawn


@dataclass(frozen=True, slots=True)
class AuthoredStarterScene:
    schema_version: Literal[1]
    kind: Literal["authored-starter"]
    region: AuthoredRegion


def authored_starter_candidate(world_id: str) -> SpatialCandidate:
    """Return the canonical source-independent initial structural world."""

    return _authored_starter_candidate(
        world_id,
        module_version=AUTHORED_GROUND_MODULE_VERSION,
        streaming_key=AUTHORED_GROUND_STREAMING_KEY,
    )


def _authored_starter_candidate(
    world_id: str, *, module_version: int, streaming_key: str
) -> SpatialCandidate:
    """Build one ground module version's exact snapshot.

    Every supported version is built here, from one body, because the versions differ only in which
    module the element names. `tests/test_authored_starter_scene.py` pins the canonical digest of
    each one, so a change to this body that would move a version already written to a database
    fails rather than making existing entries unreadable.
    """

    topology = {
        "schema_version": 1,
        "world_id": world_id,
        "regions": [{"region_id": AUTHORED_STARTER_REGION_ID}],
        "elements": [
            {
                "element_id": AUTHORED_STARTER_ELEMENT_ID,
                "owner": {"kind": "region", "id": AUTHORED_STARTER_REGION_ID},
                "module": {
                    "key": AUTHORED_GROUND_MODULE,
                    "version": module_version,
                    "requested_key": AUTHORED_GROUND_MODULE,
                },
                "lineage": {
                    "recipe_key": AUTHORED_GROUND_RECIPE,
                    "recipe_version": 1,
                    "slot_key": "ground",
                },
                "collision": {"kind": "none"},
                "evidence": {"kind": "none"},
                "attachment": None,
                "streaming_key": streaming_key,
            }
        ],
        "navigation": {
            "agent_radius_mm": 300,
            "maximum_slope_millidegrees": 15_000,
            "destinations": [
                {
                    "destination_id": AUTHORED_STARTER_DESTINATION_ID,
                    "region_id": AUTHORED_STARTER_REGION_ID,
                    "required": True,
                }
            ],
            "edges": [],
        },
        "dependencies": [],
    }
    layout = {
        "schema_version": 1,
        "layout_version": 1,
        "regions": [{"region_id": AUTHORED_STARTER_REGION_ID, "creation_ordinal": 0}],
    }
    placement = {
        "schema_version": 1,
        "coordinate_unit": "millimetre",
        "elements": [
            {
                "element_id": AUTHORED_STARTER_ELEMENT_ID,
                "x_mm": 0,
                "y_mm": AUTHORED_GROUND_ELEVATION_MM,
                "z_mm": 0,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            }
        ],
        "destinations": [
            {
                "destination_id": AUTHORED_STARTER_DESTINATION_ID,
                "x_mm": AUTHORED_SPAWN_X_MM,
                "y_mm": AUTHORED_SPAWN_Y_MM,
                "z_mm": AUTHORED_SPAWN_Z_MM,
            }
        ],
    }
    neighborhood = {
        "schema_version": 1,
        "neighborhood_version": 1,
        "layout_version": 1,
        "neighborhoods": [
            {"neighborhood_id": "neighborhood:starter", "region_ids": [AUTHORED_STARTER_REGION_ID]}
        ],
    }
    return SpatialCandidate(
        _EMPTY_GRAPH_SHA256,
        _EMPTY_RECONSTRUCTION_SHA256,
        topology,
        layout,
        placement,
        neighborhood,
        composer_key=AUTHORED_STARTER_COMPOSER,
        composer_version=AUTHORED_STARTER_COMPOSER_VERSION,
    )


def authored_ground_for_module_version(module_version: int) -> AuthoredGround:
    """The ground one module version states. Version 1 has edges; version 2 states it has none."""

    if module_version == AUTHORED_GROUND_V1_MODULE_VERSION:
        return BoundedAuthoredGround(
            "flat",
            AUTHORED_GROUND_V1_HALF_WIDTH_MM,
            AUTHORED_GROUND_V1_HALF_DEPTH_MM,
            AUTHORED_GROUND_ELEVATION_MM,
        )
    if module_version == AUTHORED_GROUND_MODULE_VERSION:
        return EndlessAuthoredGround("endless", AUTHORED_GROUND_ELEVATION_MM)
    raise InvalidStructuralData("unknown authored ground module version")


def _supported_starter_candidates(world_id: str) -> tuple[tuple[int, SpatialCandidate], ...]:
    return (
        (
            AUTHORED_GROUND_V1_MODULE_VERSION,
            _authored_starter_candidate(
                world_id,
                module_version=AUTHORED_GROUND_V1_MODULE_VERSION,
                streaming_key=AUTHORED_GROUND_V1_STREAMING_KEY,
            ),
        ),
        (AUTHORED_GROUND_MODULE_VERSION, authored_starter_candidate(world_id)),
    )


def authored_starter_scene(
    *,
    composer_key: str,
    composer_version: int,
    topology: Mapping[str, Any],
    placement: Mapping[str, Any],
) -> AuthoredStarterScene:
    """Validate and project the exact built-in starter snapshot for a renderer.

    A snapshot is read at the ground module version it was written at. The stored snapshot is
    matched against every supported version rather than asked which version it claims, so a
    descriptor cannot select its own validation.
    """

    if (
        composer_key != AUTHORED_STARTER_COMPOSER
        or composer_version != AUTHORED_STARTER_COMPOSER_VERSION
    ):
        raise InvalidStructuralData("the authored entry does not name the starter composer")
    stored_topology = dict(topology)
    stored_placement = dict(placement)
    world_id = str(stored_topology.get("world_id", ""))
    for module_version, candidate in _supported_starter_candidates(world_id):
        expected_topology = dict(candidate.topology)
        expected_placement = dict(candidate.placement)
        if stored_topology == expected_topology and stored_placement == expected_placement:
            return AuthoredStarterScene(
                schema_version=1,
                kind="authored-starter",
                region=AuthoredRegion(
                    region_id=AUTHORED_STARTER_REGION_ID,
                    origin="authored",
                    module=AuthoredModule(AUTHORED_GROUND_MODULE, module_version),
                    ground=authored_ground_for_module_version(module_version),
                    spawn=AuthoredSpawn(
                        AUTHORED_SPAWN_X_MM,
                        AUTHORED_SPAWN_Y_MM,
                        AUTHORED_SPAWN_Z_MM,
                        AUTHORED_SPAWN_YAW_MICRORADIANS,
                    ),
                ),
            )
    raise InvalidStructuralData(
        "the authored starter snapshot does not match a supported ground module version"
    )


def create_starter_authorities(
    connection: psycopg.Connection,
    *,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    title: str,
    world_id: str,
) -> tuple[uuid.UUID, StyleVersion, uuid.UUID]:
    """Register the world, then create snapshot, style and authored version.

    All inside the caller's transaction. The registration comes first because every world table
    names a registered world.
    """

    register_world(
        connection,
        workspace_id,
        world_id=world_id,
        kind=AUTHORED_STARTER,
        created_by=actor,
        reason="authored starter for a workspace with no saved world",
    )
    structures = WorldStructureRepository(connection, workspace_id, world_id=world_id)
    candidate = authored_starter_candidate(world_id)
    preview = structures.preview(candidate, proposed_by=actor)
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=None,
        base_graph_sha256=None,
        base_reconstruction_sha256=None,
        committed_by=actor,
    )
    style = WorldStyleRepository(connection, workspace_id, world_id=world_id).current()
    version = WorldObjectRepository(connection, workspace_id, world_id=world_id).create_version(
        source_snapshot_id=snapshot.snapshot_id,
        title=title,
        style_version_id=style.version_id,
        created_by=actor,
    )
    return snapshot.snapshot_id, style, version.version_id
