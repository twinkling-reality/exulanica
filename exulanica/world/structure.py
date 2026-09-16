"""Canonical structural world candidates and the checks required before persistence.

This module is deliberately pure.  It validates the reviewed composer's fixed-point boundary,
derives each section digest and the enclosing snapshot digest, and computes the protected diff.
PostgreSQL owns concurrency, evidence liveness, and the current pointer in
``structure_repository``; renderers own none of those decisions.
"""

from __future__ import annotations

import re
import uuid
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isqrt
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.world.errors import InvalidStructuralData

__all__ = [
    "PlacementMigration",
    "SpatialCandidate",
    "SpatialDigests",
    "SpatialPreview",
    "SpatialSnapshot",
    "candidate_from_document",
    "canonical_candidate_document",
    "protected_diff",
    "validate_candidate",
]

_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
_KEY: Final = re.compile(r"^[a-z][a-z0-9.-]*$")
#: Optional placement lists for identities that have no authored or measured position. Absent
#: means none, and a present list is never empty, so one placement has exactly one encoding.
_UNPLACED: Final = {"unplaced_elements": "element_id", "unplaced_destinations": "destination_id"}


@dataclass(frozen=True, slots=True)
class PlacementMigration:
    migration_id: uuid.UUID
    region_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class SpatialCandidate:
    graph_sha256: str
    reconstruction_sha256: str
    topology: Mapping[str, Any]
    layout: Mapping[str, Any]
    placement: Mapping[str, Any]
    neighborhood: Mapping[str, Any]
    composer_key: str = "atlas-world-composer"
    composer_version: int = 1
    placement_migrations: tuple[PlacementMigration, ...] = ()


@dataclass(frozen=True, slots=True)
class SpatialDigests:
    topology_sha256: str
    layout_sha256: str
    placement_sha256: str
    neighborhood_sha256: str
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class SpatialSnapshot:
    snapshot_id: uuid.UUID
    revision: int
    parent_snapshot_id: uuid.UUID | None
    candidate: SpatialCandidate
    digests: SpatialDigests
    package_projection: Mapping[str, Any]
    committed_by: uuid.UUID
    invalidated: bool


@dataclass(frozen=True, slots=True)
class SpatialPreview:
    preview_id: uuid.UUID
    base_snapshot_id: uuid.UUID | None
    base_graph_sha256: str | None
    base_reconstruction_sha256: str | None
    candidate: SpatialCandidate
    digests: SpatialDigests
    protected_diff: Mapping[str, Any]
    validation_checks: Mapping[str, Any]


def _plain(value: Any) -> Any:
    """Return only JSON-domain containers, preserving integers and refusing everything else."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise InvalidStructuralData("canonical structural objects require string keys")
        return {key: _plain(sub) for key, sub in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_plain(sub) for sub in value]
    return value


def _digest(value: Any) -> str:
    return sha256_of_canonical(_plain(value)).hex()


def canonical_candidate_document(candidate: SpatialCandidate) -> dict[str, Any]:
    """The exact JSON document persisted in a preview and independently revalidated on apply."""
    validate_candidate(candidate)
    sections = {
        "topology": _plain(candidate.topology),
        "layout": _plain(candidate.layout),
        "placement": _plain(candidate.placement),
        "neighborhood": _plain(candidate.neighborhood),
    }
    digests = _digests(candidate, sections)
    return {
        "schema_version": 1,
        "graph_sha256": candidate.graph_sha256,
        "reconstruction_sha256": candidate.reconstruction_sha256,
        "composer": {"key": candidate.composer_key, "version": candidate.composer_version},
        "sections": sections,
        "digests": {
            "topology_sha256": digests.topology_sha256,
            "layout_sha256": digests.layout_sha256,
            "placement_sha256": digests.placement_sha256,
            "neighborhood_sha256": digests.neighborhood_sha256,
            "snapshot_sha256": digests.snapshot_sha256,
        },
        "placement_migrations": [
            {
                "migration_id": str(value.migration_id),
                "region_id": value.region_id,
                "reason": value.reason,
            }
            for value in candidate.placement_migrations
        ],
    }


def candidate_from_document(value: Mapping[str, Any]) -> SpatialCandidate:
    """Decode a persisted preview document and verify every embedded digest."""
    _exact_keys(
        value,
        {
            "schema_version",
            "graph_sha256",
            "reconstruction_sha256",
            "composer",
            "sections",
            "digests",
            "placement_migrations",
        },
        "candidate",
    )
    if value["schema_version"] != 1:
        raise InvalidStructuralData("candidate.schema_version must be 1")
    composer = _object(value["composer"], "candidate.composer")
    _exact_keys(composer, {"key", "version"}, "candidate.composer")
    sections = _object(value["sections"], "candidate.sections")
    _exact_keys(
        sections,
        {"topology", "layout", "placement", "neighborhood"},
        "candidate.sections",
    )
    migrations: list[PlacementMigration] = []
    for index, raw in enumerate(
        _array(value["placement_migrations"], "candidate.placement_migrations")
    ):
        item = _object(raw, f"candidate.placement_migrations[{index}]")
        _exact_keys(
            item,
            {"migration_id", "region_id", "reason"},
            f"candidate.placement_migrations[{index}]",
        )
        try:
            migration_id = uuid.UUID(
                _string(
                    item["migration_id"],
                    f"candidate.placement_migrations[{index}].migration_id",
                )
            )
        except ValueError as exc:
            raise InvalidStructuralData("placement migration id must be a UUID") from exc
        migrations.append(
            PlacementMigration(
                migration_id,
                _string(item["region_id"], f"candidate.placement_migrations[{index}].region_id"),
                _string(item["reason"], f"candidate.placement_migrations[{index}].reason"),
            )
        )
    candidate = SpatialCandidate(
        graph_sha256=_string(value["graph_sha256"], "candidate.graph_sha256"),
        reconstruction_sha256=_string(
            value["reconstruction_sha256"], "candidate.reconstruction_sha256"
        ),
        topology=_object(sections["topology"], "candidate.sections.topology"),
        layout=_object(sections["layout"], "candidate.sections.layout"),
        placement=_object(sections["placement"], "candidate.sections.placement"),
        neighborhood=_object(sections["neighborhood"], "candidate.sections.neighborhood"),
        composer_key=_string(composer["key"], "candidate.composer.key"),
        composer_version=_integer(composer["version"], "candidate.composer.version", minimum=1),
        placement_migrations=tuple(migrations),
    )
    actual = validate_candidate(candidate)
    digests = _object(value["digests"], "candidate.digests")
    expected = {
        "topology_sha256": actual.topology_sha256,
        "layout_sha256": actual.layout_sha256,
        "placement_sha256": actual.placement_sha256,
        "neighborhood_sha256": actual.neighborhood_sha256,
        "snapshot_sha256": actual.snapshot_sha256,
    }
    if dict(digests) != expected:
        raise InvalidStructuralData("candidate embedded digests do not match canonical payload")
    return candidate


def validate_candidate(candidate: SpatialCandidate) -> SpatialDigests:
    """Validate all structural sections and return their canonical SHA-256 identities."""
    for label, value in (
        ("graph_sha256", candidate.graph_sha256),
        ("reconstruction_sha256", candidate.reconstruction_sha256),
    ):
        if _SHA256.fullmatch(value) is None:
            raise InvalidStructuralData(f"{label} must be a lowercase SHA-256 digest")
    if _KEY.fullmatch(candidate.composer_key) is None:
        raise InvalidStructuralData("composer_key is not a reviewed registry key")
    if (
        isinstance(candidate.composer_version, bool)
        or not isinstance(candidate.composer_version, int)
        or candidate.composer_version < 1
    ):
        raise InvalidStructuralData("composer_version must be a positive integer")

    sections = {
        "topology": _object(candidate.topology, "topology"),
        "layout": _object(candidate.layout, "layout"),
        "placement": _object(candidate.placement, "placement"),
        "neighborhood": _object(candidate.neighborhood, "neighborhood"),
    }
    # This is both a type/refusal check and the cryptographic serialization contract.  In
    # particular it rejects a float at any depth before semantic validation can overlook it.
    for label, value in sections.items():
        try:
            canonical_json(_plain(value))
        except Exception as exc:
            raise InvalidStructuralData(
                f"{label} is not canonical fixed-point JSON: {exc}"
            ) from exc

    topology = sections["topology"]
    layout = sections["layout"]
    placement = sections["placement"]
    neighborhood = sections["neighborhood"]
    _schema(topology, "topology")
    _schema(layout, "layout")
    _schema(placement, "placement")
    _schema(neighborhood, "neighborhood")

    region_ids = _topology_regions(topology)
    element_ids, region_elements = _topology_elements(topology, region_ids)
    unplaced_destinations = _unplaced(placement, "unplaced_destinations")
    destination_ids = _navigation(topology, region_ids, unplaced_destinations)
    _layout(layout, region_ids)
    _placement(placement, element_ids, destination_ids)
    _collision_issues(topology, placement, region_elements)
    _neighborhood(neighborhood, layout, region_ids)
    _migrations(candidate.placement_migrations, region_ids)
    return _digests(candidate, sections)


def _digests(
    candidate: SpatialCandidate, sections: Mapping[str, Mapping[str, Any]]
) -> SpatialDigests:
    topology = _digest(sections["topology"])
    layout = _digest(sections["layout"])
    placement = _digest(sections["placement"])
    neighborhood = _digest(sections["neighborhood"])
    envelope = {
        "schema_version": 1,
        "graph_sha256": candidate.graph_sha256,
        "reconstruction_sha256": candidate.reconstruction_sha256,
        "composer": {"key": candidate.composer_key, "version": candidate.composer_version},
        "sections": {
            "topology_sha256": topology,
            "layout_sha256": layout,
            "placement_sha256": placement,
            "neighborhood_sha256": neighborhood,
        },
    }
    return SpatialDigests(topology, layout, placement, neighborhood, _digest(envelope))


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidStructuralData(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise InvalidStructuralData(f"{label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidStructuralData(f"{label} must be a non-empty string")
    return value


def _integer(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidStructuralData(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise InvalidStructuralData(f"{label} must be >= {minimum}")
    return value


def _exact_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted(allowed - set(value))
    if unknown or missing:
        detail = []
        if missing:
            detail.append(f"missing {', '.join(missing)}")
        if unknown:
            detail.append(f"unknown {', '.join(unknown)}")
        raise InvalidStructuralData(f"{label} has {'; '.join(detail)}")


def _schema(value: Mapping[str, Any], label: str) -> None:
    if value.get("schema_version") != 1:
        raise InvalidStructuralData(f"{label}.schema_version must be 1")


def _topology_regions(topology: Mapping[str, Any]) -> set[str]:
    _exact_keys(
        topology,
        {"schema_version", "world_id", "regions", "elements", "navigation", "dependencies"},
        "topology",
    )
    _string(topology["world_id"], "topology.world_id")
    region_ids: set[str] = set()
    ordered_regions: list[str] = []
    for index, raw in enumerate(_array(topology["regions"], "topology.regions")):
        region = _object(raw, f"topology.regions[{index}]")
        _exact_keys(region, {"region_id"}, f"topology.regions[{index}]")
        region_id = _string(region["region_id"], f"topology.regions[{index}].region_id")
        if region_id in region_ids:
            raise InvalidStructuralData(f"duplicate topology region {region_id}")
        region_ids.add(region_id)
        ordered_regions.append(region_id)
    if not region_ids:
        raise InvalidStructuralData("topology must contain at least one region")
    if ordered_regions != sorted(ordered_regions):
        raise InvalidStructuralData("topology regions must be sorted by region_id")
    _dependencies(topology["dependencies"])
    return region_ids


def _dependencies(raw_dependencies: Any) -> None:
    seen: set[tuple[str, str, str | None]] = set()
    ordered: list[tuple[str, str, str]] = []
    for index, raw in enumerate(_array(raw_dependencies, "topology.dependencies")):
        value = _object(raw, f"topology.dependencies[{index}]")
        _exact_keys(
            value,
            {"kind", "ref", "element_id"},
            f"topology.dependencies[{index}]",
        )
        kind = _string(value["kind"], f"topology.dependencies[{index}].kind")
        if kind not in {"evidence_span", "capture", "entity", "assertion"}:
            raise InvalidStructuralData(f"unknown structural dependency kind {kind}")
        try:
            uuid.UUID(_string(value["ref"], f"topology.dependencies[{index}].ref"))
        except ValueError as exc:
            raise InvalidStructuralData(
                f"topology.dependencies[{index}].ref must be a UUID"
            ) from exc
        element_id = value["element_id"]
        if element_id is not None:
            element_id = _string(element_id, f"topology.dependencies[{index}].element_id")
        identity = (kind, value["ref"], element_id)
        if identity in seen:
            raise InvalidStructuralData(f"duplicate structural dependency {identity}")
        seen.add(identity)
        ordered.append((kind, value["ref"], element_id or ""))
    if ordered != sorted(ordered):
        raise InvalidStructuralData("topology dependencies must be canonically sorted")


def _topology_elements(
    topology: Mapping[str, Any], region_ids: set[str]
) -> tuple[set[str], dict[str, str]]:
    element_ids: set[str] = set()
    region_elements: dict[str, str] = {}
    ordered_elements: list[str] = []
    for index, raw in enumerate(_array(topology["elements"], "topology.elements")):
        label = f"topology.elements[{index}]"
        value = _object(raw, label)
        _exact_keys(
            value,
            {
                "element_id",
                "owner",
                "module",
                "lineage",
                "collision",
                "evidence",
                "attachment",
                "streaming_key",
            },
            label,
        )
        element_id = _string(value["element_id"], f"{label}.element_id")
        if element_id in element_ids:
            raise InvalidStructuralData(f"duplicate structural element {element_id}")
        element_ids.add(element_id)
        ordered_elements.append(element_id)
        owner = _object(value["owner"], f"{label}.owner")
        _exact_keys(owner, {"kind", "id"}, f"{label}.owner")
        owner_kind = _string(owner["kind"], f"{label}.owner.kind")
        owner_id = _string(owner["id"], f"{label}.owner.id")
        if owner_kind not in {"world", "region", "relationship"}:
            raise InvalidStructuralData(f"{label}.owner.kind is invalid")
        if owner_kind == "region":
            if owner_id not in region_ids:
                raise InvalidStructuralData(f"{element_id} belongs to unknown region {owner_id}")
            region_elements[element_id] = owner_id
        module = _object(value["module"], f"{label}.module")
        _exact_keys(module, {"key", "version", "requested_key"}, f"{label}.module")
        _string(module["key"], f"{label}.module.key")
        _string(module["requested_key"], f"{label}.module.requested_key")
        _integer(module["version"], f"{label}.module.version", minimum=1)
        lineage = _object(value["lineage"], f"{label}.lineage")
        _exact_keys(
            lineage,
            {"recipe_key", "recipe_version", "slot_key"},
            f"{label}.lineage",
        )
        _string(lineage["recipe_key"], f"{label}.lineage.recipe_key")
        _integer(lineage["recipe_version"], f"{label}.lineage.recipe_version", minimum=1)
        _string(lineage["slot_key"], f"{label}.lineage.slot_key")
        _collision(value["collision"], label)
        _evidence(value["evidence"], label)
        _string(value["streaming_key"], f"{label}.streaming_key")
        if value["attachment"] is not None:
            attachment = _object(value["attachment"], f"{label}.attachment")
            _exact_keys(attachment, {"parent_element_id", "socket_key"}, f"{label}.attachment")
            _string(attachment["parent_element_id"], f"{label}.attachment.parent_element_id")
            _string(attachment["socket_key"], f"{label}.attachment.socket_key")

    for raw in _array(topology["elements"], "topology.elements"):
        attachment = _object(raw, "topology element")["attachment"]
        if attachment is not None and attachment["parent_element_id"] not in element_ids:
            raise InvalidStructuralData(
                f"element attachment names unknown parent {attachment['parent_element_id']}"
            )
    for index, raw in enumerate(_array(topology["dependencies"], "topology.dependencies")):
        element_id = _object(raw, "dependency")["element_id"]
        if element_id is not None and element_id not in element_ids:
            raise InvalidStructuralData(
                f"topology.dependencies[{index}] names unknown element {element_id}"
            )
    if ordered_elements != sorted(ordered_elements):
        raise InvalidStructuralData("topology elements must be sorted by element_id")
    return element_ids, region_elements


def _collision(raw: Any, element_label: str) -> None:
    value = _object(raw, f"{element_label}.collision")
    kind = value.get("kind")
    if kind == "none":
        _exact_keys(value, {"kind"}, f"{element_label}.collision")
    elif kind == "circle":
        _exact_keys(value, {"kind", "radius_mm"}, f"{element_label}.collision")
        _integer(value["radius_mm"], f"{element_label}.collision.radius_mm", minimum=0)
    elif kind == "box":
        _exact_keys(
            value,
            {"kind", "half_width_mm", "half_depth_mm"},
            f"{element_label}.collision",
        )
        _integer(value["half_width_mm"], f"{element_label}.collision.half_width_mm", minimum=0)
        _integer(value["half_depth_mm"], f"{element_label}.collision.half_depth_mm", minimum=0)
    else:
        raise InvalidStructuralData(f"{element_label}.collision.kind is invalid")


def _evidence(raw: Any, element_label: str) -> None:
    value = _object(raw, f"{element_label}.evidence")
    kind = value.get("kind")
    if kind == "none":
        _exact_keys(value, {"kind"}, f"{element_label}.evidence")
    elif kind == "span":
        _exact_keys(value, {"kind", "span_id"}, f"{element_label}.evidence")
        try:
            uuid.UUID(_string(value["span_id"], f"{element_label}.evidence.span_id"))
        except ValueError as exc:
            raise InvalidStructuralData(f"{element_label}.evidence.span_id must be a UUID") from exc
    elif kind == "missing":
        _exact_keys(value, {"kind", "reason"}, f"{element_label}.evidence")
        _string(value["reason"], f"{element_label}.evidence.reason")
    else:
        raise InvalidStructuralData(f"{element_label}.evidence.kind is invalid")


def _navigation(topology: Mapping[str, Any], region_ids: set[str], unplaced: set[str]) -> set[str]:
    """Validate destinations and edges; ``unplaced`` destinations take no edge and no route.

    A destination with no position cannot be reached and cannot be adjacent to anything, so it is
    exempt from the reachability rule rather than being given an edge nobody measured.
    """
    nav = _object(topology["navigation"], "topology.navigation")
    _exact_keys(
        nav,
        {"agent_radius_mm", "maximum_slope_millidegrees", "destinations", "edges"},
        "topology.navigation",
    )
    _integer(nav["agent_radius_mm"], "topology.navigation.agent_radius_mm", minimum=1)
    maximum_slope = _integer(
        nav["maximum_slope_millidegrees"],
        "topology.navigation.maximum_slope_millidegrees",
        minimum=0,
    )
    destination_ids: set[str] = set()
    required: set[str] = set()
    ordered_destinations: list[str] = []
    for index, raw in enumerate(_array(nav["destinations"], "topology.navigation.destinations")):
        label = f"topology.navigation.destinations[{index}]"
        value = _object(raw, label)
        _exact_keys(value, {"destination_id", "region_id", "required"}, label)
        destination_id = _string(value["destination_id"], f"{label}.destination_id")
        if destination_id in destination_ids:
            raise InvalidStructuralData(f"duplicate navigation destination {destination_id}")
        destination_ids.add(destination_id)
        ordered_destinations.append(destination_id)
        if value["region_id"] not in region_ids:
            raise InvalidStructuralData(f"{destination_id} names an unknown region")
        if not isinstance(value["required"], bool):
            raise InvalidStructuralData(f"{label}.required must be boolean")
        if value["required"]:
            required.add(destination_id)
    if not required:
        raise InvalidStructuralData("navigation must have at least one required destination")
    adjacency = {value: set() for value in destination_ids}
    ordered_edges: list[tuple[str, str, str]] = []
    for index, raw in enumerate(_array(nav["edges"], "topology.navigation.edges")):
        label = f"topology.navigation.edges[{index}]"
        value = _object(raw, label)
        _exact_keys(value, {"from", "to", "kind", "max_slope_millidegrees"}, label)
        start = _string(value["from"], f"{label}.from")
        end = _string(value["to"], f"{label}.to")
        if start == end or start not in adjacency or end not in adjacency:
            raise InvalidStructuralData(f"{label} does not connect two known distinct destinations")
        if start in unplaced or end in unplaced:
            raise InvalidStructuralData(f"{label} connects a destination that has no position")
        slope = _integer(
            value["max_slope_millidegrees"], f"{label}.max_slope_millidegrees", minimum=0
        )
        if slope > maximum_slope:
            raise InvalidStructuralData(f"{label} exceeds the navigation slope contract")
        if value["kind"] not in {"field", "confirmed-relationship"}:
            raise InvalidStructuralData(f"{label}.kind is invalid")
        ordered_edges.append((start, end, value["kind"]))
        adjacency[start].add(end)
        adjacency[end].add(start)
    reachable = required - unplaced
    visited: set[str] = set()
    queue = deque([min(reachable)] if reachable else [])
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        queue.extend(sorted(adjacency[current] - visited))
    missing = sorted(reachable - visited)
    if missing:
        raise InvalidStructuralData(f"required destinations are unreachable: {', '.join(missing)}")
    if ordered_destinations != sorted(ordered_destinations):
        raise InvalidStructuralData("navigation destinations must be sorted by destination_id")
    if ordered_edges != sorted(ordered_edges):
        raise InvalidStructuralData("navigation edges must be canonically sorted")
    return destination_ids


def _layout(layout: Mapping[str, Any], region_ids: set[str]) -> None:
    _exact_keys(layout, {"schema_version", "layout_version", "regions"}, "layout")
    _integer(layout["layout_version"], "layout.layout_version", minimum=1)
    found: set[str] = set()
    ordinals: set[int] = set()
    ordered: list[tuple[int, str]] = []
    for index, raw in enumerate(_array(layout["regions"], "layout.regions")):
        label = f"layout.regions[{index}]"
        value = _object(raw, label)
        _exact_keys(value, {"region_id", "creation_ordinal"}, label)
        region_id = _string(value["region_id"], f"{label}.region_id")
        ordinal = _integer(value["creation_ordinal"], f"{label}.creation_ordinal", minimum=0)
        if region_id in found or ordinal in ordinals:
            raise InvalidStructuralData("layout region ids and creation ordinals must be unique")
        found.add(region_id)
        ordinals.add(ordinal)
        ordered.append((ordinal, region_id))
    if found != region_ids:
        raise InvalidStructuralData("layout regions must exactly equal topology regions")
    if ordered != sorted(ordered):
        raise InvalidStructuralData("layout regions must be sorted by creation_ordinal and id")


def _unplaced(placement: Mapping[str, Any], key: str) -> set[str]:
    """Identities listed under an optional ``unplaced_*`` key, each with its stated reason."""
    if not isinstance(placement, Mapping) or key not in placement:
        return set()
    identity_key = _UNPLACED[key]
    values = _array(placement[key], f"placement.{key}")
    if not values:
        raise InvalidStructuralData(f"placement.{key} is omitted when nothing is unplaced")
    ordered: list[str] = []
    for index, raw in enumerate(values):
        label = f"placement.{key}[{index}]"
        value = _object(raw, label)
        _exact_keys(value, {identity_key, "reason"}, label)
        ordered.append(_string(value[identity_key], f"{label}.{identity_key}"))
        _string(value["reason"], f"{label}.reason")
    if len(set(ordered)) != len(ordered):
        raise InvalidStructuralData(f"placement.{key} names an identity twice")
    if ordered != sorted(ordered):
        raise InvalidStructuralData(f"placement.{key} must be sorted by {identity_key}")
    return set(ordered)


def _placement(
    placement: Mapping[str, Any], element_ids: set[str], expected_destinations: set[str]
) -> None:
    _exact_keys(
        placement,
        {"schema_version", "coordinate_unit", "elements", "destinations"}
        | (set(placement) & set(_UNPLACED)),
        "placement",
    )
    unplaced_elements = _unplaced(placement, "unplaced_elements")
    unplaced_destinations = _unplaced(placement, "unplaced_destinations")
    if placement["coordinate_unit"] != "millimetre":
        raise InvalidStructuralData("placement.coordinate_unit must be millimetre")
    by_id: dict[str, Mapping[str, Any]] = {}
    ordered_elements: list[str] = []
    for index, raw in enumerate(_array(placement["elements"], "placement.elements")):
        label = f"placement.elements[{index}]"
        value = _object(raw, label)
        _exact_keys(
            value,
            {"element_id", "x_mm", "y_mm", "z_mm", "yaw_microradians", "scale_milli"},
            label,
        )
        element_id = _string(value["element_id"], f"{label}.element_id")
        if element_id in by_id:
            raise InvalidStructuralData(f"duplicate placement for {element_id}")
        for key in ("x_mm", "y_mm", "z_mm", "yaw_microradians"):
            _integer(value[key], f"{label}.{key}")
        _integer(value["scale_milli"], f"{label}.scale_milli", minimum=1)
        by_id[element_id] = value
        ordered_elements.append(element_id)
    if set(by_id) & unplaced_elements or set(by_id) | unplaced_elements != element_ids:
        raise InvalidStructuralData(
            "placed and unplaced elements must partition the topology elements exactly"
        )

    destination_ids: set[str] = set()
    ordered_destinations: list[str] = []
    for index, raw in enumerate(_array(placement["destinations"], "placement.destinations")):
        label = f"placement.destinations[{index}]"
        value = _object(raw, label)
        _exact_keys(value, {"destination_id", "x_mm", "y_mm", "z_mm"}, label)
        destination_id = _string(value["destination_id"], f"{label}.destination_id")
        if destination_id in destination_ids:
            raise InvalidStructuralData(f"duplicate destination placement {destination_id}")
        destination_ids.add(destination_id)
        ordered_destinations.append(destination_id)
        for key in ("x_mm", "y_mm", "z_mm"):
            _integer(value[key], f"{label}.{key}")
    if (
        destination_ids & unplaced_destinations
        or destination_ids | unplaced_destinations != expected_destinations
    ):
        raise InvalidStructuralData(
            "placed and unplaced destinations must partition the navigation destinations exactly"
        )
    if ordered_elements != sorted(ordered_elements):
        raise InvalidStructuralData("placement elements must be sorted by element_id")
    if ordered_destinations != sorted(ordered_destinations):
        raise InvalidStructuralData("destination placements must be sorted by destination_id")


def _collision_issues(
    topology: Mapping[str, Any],
    placement: Mapping[str, Any],
    region_elements: Mapping[str, str],
) -> None:
    """Reject overlapping peer-region collision bodies using integer-only conservative radii."""
    if not region_elements:
        raise InvalidStructuralData("topology must contain at least one region-owned element")
    placed = {value["element_id"]: value for value in placement["elements"]}
    bodies: list[tuple[str, str, int, int, int]] = []
    for element in topology["elements"]:
        element_id = element["element_id"]
        if element_id not in region_elements or element["attachment"] is not None:
            continue
        collision = element["collision"]
        if collision["kind"] == "none":
            continue
        if element_id not in placed:
            # Overlap cannot be ruled out for a body that has no position.
            raise InvalidStructuralData(f"{element_id} has a collision body but no position")
        if collision["kind"] == "circle":
            radius = collision["radius_mm"]
        else:
            # Integer ceiling of the circumscribed radius.  Conservative is intentional: the
            # preview may refuse a close authored layout; it may never approve an overlap.
            squared = collision["half_width_mm"] ** 2 + collision["half_depth_mm"] ** 2
            radius = isqrt(squared)
            if radius * radius < squared:
                radius += 1
        transform = placed[element_id]
        scaled_radius = (radius * transform["scale_milli"] + 999) // 1000
        bodies.append(
            (
                element_id,
                region_elements[element_id],
                transform["x_mm"],
                transform["z_mm"],
                scaled_radius,
            )
        )
    for index, first in enumerate(bodies):
        for second in bodies[index + 1 :]:
            if first[1] == second[1]:
                continue
            minimum = first[4] + second[4]
            distance_squared = (first[2] - second[2]) ** 2 + (first[3] - second[3]) ** 2
            if distance_squared < minimum * minimum:
                raise InvalidStructuralData(
                    f"collision bodies overlap across regions: {first[0]} and {second[0]}"
                )


def _neighborhood(
    neighborhood: Mapping[str, Any], layout: Mapping[str, Any], region_ids: set[str]
) -> None:
    _exact_keys(
        neighborhood,
        {"schema_version", "neighborhood_version", "layout_version", "neighborhoods"},
        "neighborhood",
    )
    _integer(neighborhood["neighborhood_version"], "neighborhood.neighborhood_version", minimum=1)
    if neighborhood["layout_version"] != layout["layout_version"]:
        raise InvalidStructuralData("neighborhood.layout_version must equal layout.layout_version")
    assigned: set[str] = set()
    neighborhood_ids: set[str] = set()
    ordered_neighborhoods: list[str] = []
    for index, raw in enumerate(
        _array(neighborhood["neighborhoods"], "neighborhood.neighborhoods")
    ):
        label = f"neighborhood.neighborhoods[{index}]"
        value = _object(raw, label)
        _exact_keys(value, {"neighborhood_id", "region_ids"}, label)
        identity = _string(value["neighborhood_id"], f"{label}.neighborhood_id")
        if identity in neighborhood_ids:
            raise InvalidStructuralData(f"duplicate neighborhood {identity}")
        neighborhood_ids.add(identity)
        ordered_neighborhoods.append(identity)
        members = _array(value["region_ids"], f"{label}.region_ids")
        if not members:
            raise InvalidStructuralData(f"{label}.region_ids must not be empty")
        member_values: list[str] = []
        for member in members:
            region_id = _string(member, f"{label}.region_ids")
            if region_id not in region_ids or region_id in assigned:
                raise InvalidStructuralData(
                    f"region {region_id} has invalid neighborhood membership"
                )
            assigned.add(region_id)
            member_values.append(region_id)
        if member_values != sorted(member_values):
            raise InvalidStructuralData(f"{label}.region_ids must be sorted")
    if assigned != region_ids:
        raise InvalidStructuralData("neighborhood membership must exactly cover topology regions")
    if ordered_neighborhoods != sorted(ordered_neighborhoods):
        raise InvalidStructuralData("neighborhoods must be sorted by neighborhood_id")


def _migrations(values: tuple[PlacementMigration, ...], region_ids: set[str]) -> None:
    migrations: set[uuid.UUID] = set()
    regions: set[str] = set()
    for value in values:
        if value.migration_id in migrations or value.region_id in regions:
            raise InvalidStructuralData("placement migrations must have unique ids and regions")
        if value.region_id not in region_ids:
            raise InvalidStructuralData(
                f"placement migration names unknown region {value.region_id}"
            )
        if not value.reason.strip():
            raise InvalidStructuralData("placement migration reason must not be empty")
        migrations.add(value.migration_id)
        regions.add(value.region_id)


def protected_diff(
    previous: SpatialCandidate | None, candidate: SpatialCandidate
) -> dict[str, Any]:
    """Digest-level diff plus stable identity additions/removals and placement changes."""
    current = validate_candidate(candidate)
    if previous is None:
        previous_digests = None
        old_elements: set[str] = set()
        old_regions: set[str] = set()
        old_placements: dict[str, str] = {}
    else:
        previous_digests = validate_candidate(previous)
        old_elements = _element_ids(previous.topology)
        old_regions = _region_ids(previous.topology)
        old_placements = _placement_digests(previous.placement)
    new_elements = _element_ids(candidate.topology)
    new_regions = _region_ids(candidate.topology)
    new_placements = _placement_digests(candidate.placement)
    changed = sorted(
        identity
        for identity in old_placements.keys() & new_placements.keys()
        if old_placements[identity] != new_placements[identity]
    )
    return {
        "schema_version": 1,
        "sections": {
            "topology": previous_digests is None
            or previous_digests.topology_sha256 != current.topology_sha256,
            "layout": previous_digests is None
            or previous_digests.layout_sha256 != current.layout_sha256,
            "placement": previous_digests is None
            or previous_digests.placement_sha256 != current.placement_sha256,
            "neighborhood": previous_digests is None
            or previous_digests.neighborhood_sha256 != current.neighborhood_sha256,
        },
        "regions": {
            "added": sorted(new_regions - old_regions),
            "removed": sorted(old_regions - new_regions),
        },
        "elements": {
            "added": sorted(new_elements - old_elements),
            "removed": sorted(old_elements - new_elements),
            "placement_changed": changed,
        },
    }


def _element_ids(topology: Mapping[str, Any]) -> set[str]:
    return {value["element_id"] for value in topology["elements"]}


def _region_ids(topology: Mapping[str, Any]) -> set[str]:
    return {value["region_id"] for value in topology["regions"]}


def _placement_digests(placement: Mapping[str, Any]) -> dict[str, str]:
    return {
        value["element_id"]: _digest(value)
        for value in (*placement["elements"], *placement.get("unplaced_elements", ()))
    }
