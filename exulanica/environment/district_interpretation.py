"""Optional, source-bound district recipes. These do not establish real street access."""

from __future__ import annotations

import hashlib
import heapq
import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from exulanica.canonical import canonical_json
from exulanica.environment.district_geometry import DistrictGeometry, length_mm

PROFILE = "exulanica.district-interpretation/v1"
PRODUCER = "flatiron-interpretation/1"
Integer = Annotated[StrictInt, Field(ge=-1_000_000_000, le=1_000_000_000)]
Positive = Annotated[StrictInt, Field(gt=0, le=1_000_000)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identity = Annotated[str, Field(min_length=1, max_length=256)]
Point = tuple[Integer, Integer]
Bounds = tuple[Integer, Integer, Integer, Integer]
Use = Literal["render", "select", "collide", "navigate", "simulate", "modify"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Frame(Record):
    name: Literal["flatiron-local-mm"] = "flatiron-local-mm"
    origin_crs84_e7: tuple[Integer, Integer]
    axis_order: tuple[Literal["east"], Literal["south"]] = ("east", "south")
    horizontal_unit: Literal["millimetre"] = "millimetre"
    altitude_reference: Literal["authored-flat-ground"] = "authored-flat-ground"


class SourceDependency(Record):
    dataset_id: Identity
    provider_revision: Identity
    sha256: Digest
    source_url: str
    attribution: str
    operation_rights: dict[str, bool]


class SourceRef(Record):
    dataset_id: Identity
    sha256: Digest
    feature_id: Identity


class Footprint(Record):
    kind: Literal["source-footprint"]
    feature_id: Identity


class Facade(Record):
    kind: Literal["facade-grid"]
    feature_id: Identity
    height_mm: Positive
    bay_width_mm: Positive
    floor_height_mm: Positive
    window_width_mm: Positive
    window_height_mm: Positive
    sill_height_mm: Positive
    recess_mm: Positive
    material_index: Annotated[StrictInt, Field(ge=0, le=6)]


class Roof(Record):
    kind: Literal["roof-parapet"]
    feature_id: Identity
    height_mm: Positive
    parapet_height_mm: Positive


class Ground(Record):
    kind: Literal["flat-ground"]
    height_mm: Literal[0]


class Residual(Record):
    kind: Literal["residual-ground"]
    excluded_subject_ids: tuple[Identity, ...]


class Envelope(Record):
    kind: Literal["walk-envelope"]
    bounds_mm: Bounds
    grid_spacing_mm: Positive


class Entrance(Record):
    kind: Literal["entrance-marker"]
    building_subject_id: Identity
    position_mm: Point
    polygon_index: Annotated[StrictInt, Field(ge=0)]
    facade_edge_index: Annotated[StrictInt, Field(ge=0)]
    width_mm: Positive
    height_mm: Positive


class RestPad(Record):
    kind: Literal["rest-pad"]
    position_mm: Point
    radius_mm: Positive
    height_mm: Literal[0]


Recipe = Annotated[
    Footprint | Facade | Roof | Ground | Residual | Envelope | Entrance | RestPad,
    Field(discriminator="kind"),
]


class Subject(Record):
    subject_id: Identity
    kind: Literal[
        "building",
        "sidewalk",
        "facade",
        "roof",
        "ground",
        "road-completion",
        "walk-envelope",
        "entrance",
        "civic-object",
    ]
    epistemic_status: Literal["observation", "interpretation", "generated", "authored"]
    source_refs: tuple[SourceRef, ...]
    uncertainty: str
    permitted_uses: tuple[Use, ...]
    recipe: Recipe


class Node(Record):
    node_id: Identity
    subject_id: Identity
    position_mm: Point


class Edge(Record):
    edge_id: Identity
    from_node_id: Identity
    to_node_id: Identity
    length_mm: Positive
    subject_id: Identity


class Destination(Record):
    destination_id: Identity
    subject_id: Identity
    node_id: Identity
    affordance: Literal["visit", "rest"]
    duration_ticks: Positive


class Navigation(Record):
    profile: Literal["bounded-sidewalk-graph/v1"] = "bounded-sidewalk-graph/v1"
    clearance_mm: Literal[450] = 450
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    destinations: tuple[Destination, ...]
    unavailable_reason: Literal["no-supported-connected-sidewalk"] | None


class DistrictInterpretation(Record):
    profile: Literal["exulanica.district-interpretation/v1"] = PROFILE
    district_id: Identity
    base_artifact_sha256: Digest
    producer: Literal["flatiron-interpretation/1"] = PRODUCER
    seed: Integer
    frame: Frame
    bounds_mm: Bounds
    source_dependencies: tuple[SourceDependency, ...]
    subjects: tuple[Subject, ...]
    navigation: Navigation
    unsupported: tuple[str, ...]
    document_sha256: Digest

    @model_validator(mode="after")
    def integrity(self) -> Self:
        doc = self.model_dump(mode="json", exclude={"document_sha256"})
        if hashlib.sha256(canonical_json(doc)).hexdigest() != self.document_sha256:
            raise ValueError("interpretation digest mismatch")
        for values, field in (
            (self.subjects, "subject_id"),
            (self.navigation.nodes, "node_id"),
            (self.navigation.edges, "edge_id"),
            (self.navigation.destinations, "destination_id"),
        ):
            ids = [getattr(v, field) for v in values]
            if ids != sorted(set(ids)):
                raise ValueError(f"{field} must be unique and sorted")
        return self


def _base(data: bytes) -> dict[str, Any]:
    base = json.loads(data)
    if base.get("profile") != "exulanica.owned-district/v1":
        raise ValueError("unsupported base district profile")
    frame = base.get("frame", {})
    if (
        frame.get("axis_order") != ["east", "south"]
        or frame.get("coordinate_scale") != 100
        or frame.get("horizontal_unit") != "centimetre"
        or frame.get("altitude_reference") != "authored-flat-ground"
    ):
        raise ValueError("unsupported base coordinate frame")
    # Base schema predates this extension. Reject malformed geometry without changing old bytes.
    canonical_json(base)
    for key in ("bounds_cm",):
        if len(base[key]) != 4 or any(type(v) is not int for v in base[key]):
            raise ValueError("invalid base bounds")
    if base["bounds_cm"][0] >= base["bounds_cm"][2] or base["bounds_cm"][1] >= base["bounds_cm"][3]:
        raise ValueError("invalid base bounds")
    for layer in ("buildings", "sidewalks"):
        ids = [f["id"] for f in base[layer]]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate base feature")
        for feature in base[layer]:
            if not feature["polygons"]:
                raise ValueError("empty polygon")
            points = []
            for polygon in feature["polygons"]:
                if not polygon:
                    raise ValueError("empty polygon")
                for ring in polygon:
                    if len(ring) < 4 or ring[0] != ring[-1]:
                        raise ValueError("unclosed polygon")
                    for p in ring:
                        if len(p) != 2 or any(
                            type(v) is not int or abs(v) > 100_000_000 for v in p
                        ):
                            raise ValueError("invalid polygon coordinate")
                    points.extend(ring)
            expected = [
                min(p[0] for p in points),
                min(p[1] for p in points),
                max(p[0] for p in points),
                max(p[1] for p in points),
            ]
            if feature["bbox_cm"] != expected:
                raise ValueError("base geometry bounding box mismatch")
    return base


def _dependencies(base: dict) -> list[dict]:
    fields = tuple(SourceDependency.model_fields)
    result = [{k: s[k] for k in fields} for s in base["source_records"]]
    if {s["dataset_id"] for s in result} != {"5zhs-2jue", "52n9-sdep"} or len(result) != 2:
        raise ValueError("missing district source dependencies")
    if any(
        any(s["operation_rights"].get(k) is not True for k in ("display", "persist", "modify"))
        for s in result
    ):
        raise ValueError("source is not admitted for interpretation")
    return sorted(result, key=lambda s: s["dataset_id"])


def compile_interpretation(base_bytes: bytes) -> bytes:
    """Compile a bounded Flatiron sidewalk component and compact declared completions."""
    base = _base(base_bytes)
    deps = _dependencies(base)
    by_dataset = {s["dataset_id"]: s for s in deps}
    geometry = DistrictGeometry(base)
    prefix = base["district_id"]
    subjects: list[dict] = []

    def ref(feature: dict, layer: str) -> dict:
        source = by_dataset["5zhs-2jue" if layer == "building" else "52n9-sdep"]
        return {
            "dataset_id": source["dataset_id"],
            "sha256": source["sha256"],
            "feature_id": feature["id"],
        }

    def add(
        identity: str,
        kind: str,
        status: str,
        refs: list[dict],
        uncertainty: str,
        recipe: dict,
        uses: tuple[str, ...] = ("render", "select"),
    ) -> None:
        subjects.append(
            dict(
                subject_id=identity,
                kind=kind,
                epistemic_status=status,
                source_refs=refs,
                uncertainty=uncertainty,
                permitted_uses=list(uses),
                recipe=recipe,
            )
        )

    for building in sorted(base["buildings"], key=lambda b: b["id"]):
        identity = building["id"]
        refs = [ref(building, "building")]
        add(
            identity,
            "building",
            "observation",
            refs,
            "Footprint only; source accuracy and present-day state unvalidated. Courtyard"
            " holes retained but collision blocks exteriors.",
            dict(kind="source-footprint", feature_id=identity),
            ("render", "select", "collide"),
        )
        add(
            f"{prefix}/facade/{identity}",
            "facade",
            "generated",
            refs,
            "Procedural mass and facade, not observed windows/material. Legacy height may"
            " be roof-derived, clamped or fallback; original v1 does not distinguish.",
            dict(
                kind="facade-grid",
                feature_id=identity,
                height_mm=building["height_cm"] * 10,
                bay_width_mm=4000 + (base["seed"] + building["material"]) % 3 * 500,
                floor_height_mm=4200,
                window_width_mm=1240,
                window_height_mm=1450,
                sill_height_mm=2700,
                recess_mm=55,
                material_index=building["material"],
            ),
        )
        add(
            f"{prefix}/roof/{identity}",
            "roof",
            "generated",
            refs,
            "Flat roof/parapet completion, no roof survey or roof access. Preserve every "
            "ring; no center-fan fill across holes.",
            dict(
                kind="roof-parapet",
                feature_id=identity,
                height_mm=building["height_cm"] * 10,
                parapet_height_mm=600,
            ),
        )
    for sidewalk in sorted(base["sidewalks"], key=lambda s: s["id"]):
        add(
            sidewalk["id"],
            "sidewalk",
            "observation",
            [ref(sidewalk, "sidewalk")],
            "Source polygon, not current accessible pedestrian clearance; holes remain "
            "unsupported.",
            dict(kind="source-footprint", feature_id=sidewalk["id"]),
        )
    add(
        f"{prefix}/ground",
        "ground",
        "authored",
        [],
        "Flat authored datum, not surveyed terrain.",
        dict(kind="flat-ground", height_mm=0),
        ("render", "select", "collide"),
    )
    add(
        f"{prefix}/road-completion",
        "road-completion",
        "generated",
        [],
        "Residual visible ground, not observed road geometry, lanes or crossings; "
        "excluded from route support.",
        dict(
            kind="residual-ground",
            excluded_subject_ids=sorted(b["id"] for b in base["buildings"] + base["sidewalks"]),
        ),
    )

    # Bounded demonstration near Flatiron; do not infer connectivity outside this envelope.
    w, n, e, s = geometry.bounds
    bounds = [max(w, -60_000), max(n, 30_000), min(e, 110_000), min(s, 200_000)]
    envelope_id = f"{prefix}/walk-envelope"
    nodes = {}
    step = 4000
    if bounds[0] < bounds[2] and bounds[1] < bounds[3]:
        for x in range(-(-bounds[0] // step) * step, bounds[2] + 1, step):
            for z in range(-(-bounds[1] // step) * step, bounds[3] + 1, step):
                point = (x, z)
                if geometry.supports(point, point):
                    nodes[point] = f"{prefix}/walk:{x}:{z}"
    edges = []
    adjacency = {p: set() for p in nodes}
    for a in sorted(nodes):
        for dx, dz in ((step, 0), (0, step)):
            b = (a[0] + dx, a[1] + dz)
            if b in nodes and geometry.supports(a, b):
                adjacency[a].add(b)
                adjacency[b].add(a)
                start, end = sorted((nodes[a], nodes[b]))
                edges.append(
                    dict(
                        edge_id=f"{start}|{end}",
                        from_node_id=start,
                        to_node_id=end,
                        length_mm=length_mm(a, b),
                        subject_id=envelope_id,
                    )
                )
    components = []
    remaining = set(nodes)
    while remaining:
        pending = [min(remaining)]
        component = set()
        while pending:
            point = pending.pop()
            if point in component:
                continue
            component.add(point)
            pending.extend(adjacency[point] - component)
        remaining -= component
        if len(component) >= 2:
            components.append(component)
    selected = min(components, key=lambda c: (-len(c), min(c))) if components else set()
    nodes = {p: identity for p, identity in nodes.items() if p in selected}
    node_ids = set(nodes.values())
    edges = [
        edge
        for edge in edges
        if edge["from_node_id"] in node_ids and edge["to_node_id"] in node_ids
    ]
    add(
        envelope_id,
        "walk-envelope",
        "interpretation",
        [],
        "Conservative simulated envelope only. All source layers are withdrawal "
        "dependencies, including negative-space collision exclusions. Disconnected "
        "components omitted.",
        dict(
            kind="walk-envelope",
            bounds_mm=bounds if nodes else geometry.bounds,
            grid_spacing_mm=step,
        ),
        ("render", "select", "navigate", "simulate"),
    )
    destinations = []
    # Generate visible exterior markers only when a node lies close to a source facade.
    used = set()
    for building in sorted(base["buildings"], key=lambda b: (not bool(b.get("name")), b["id"])):
        if not nodes or len(destinations) >= 8:
            break
        candidates = []
        for pi, polygon in enumerate(building["polygons"]):
            for ei, (ac, bc) in enumerate(zip(polygon[0], polygon[0][1:], strict=False)):
                a, b = (ac[0] * 10, ac[1] * 10), (bc[0] * 10, bc[1] * 10)
                for point in nodes:
                    if point in used:
                        continue
                    dx, dz = b[0] - a[0], b[1] - a[1]
                    den = dx * dx + dz * dz
                    if not den:
                        continue
                    dot = max(0, min(den, (point[0] - a[0]) * dx + (point[1] - a[1]) * dz))
                    projection = (a[0] + dx * dot // den, a[1] + dz * dot // den)
                    distance = length_mm(point, projection)
                    if 450 < distance <= 5000:
                        candidates.append((distance, point, pi, ei))
        if not candidates:
            continue
        _, point, pi, ei = min(candidates)
        used.add(point)
        identity = f"{prefix}/entrance/{building['id']}"
        add(
            identity,
            "entrance",
            "generated",
            [ref(building, "building")],
            "Generated exterior arrival marker near a facade, not an actual door. No "
            "entry or indoor route.",
            dict(
                kind="entrance-marker",
                building_subject_id=building["id"],
                position_mm=point,
                polygon_index=pi,
                facade_edge_index=ei,
                width_mm=1000,
                height_mm=2200,
            ),
            ("render", "select", "simulate"),
        )
        destinations.append(
            dict(
                destination_id=identity,
                subject_id=identity,
                node_id=nodes[point],
                affordance="visit",
                duration_ticks=1,
            )
        )
    # Flush rest pads are explicit generated civic objects, not invented benches obstructing routes.
    for point in sorted(nodes):
        if len([d for d in destinations if d["affordance"] == "rest"]) >= 3:
            break
        if any(length_mm(point, p) < 12000 for p in used):
            continue
        used.add(point)
        identity = f"{prefix}/rest:{point[0]}:{point[1]}"
        add(
            identity,
            "civic-object",
            "generated",
            [],
            "Generated flush civic rest pad, not observed furniture, seating or vegetation.",
            dict(kind="rest-pad", position_mm=point, radius_mm=600, height_mm=0),
            ("render", "select", "simulate"),
        )
        destinations.append(
            dict(
                destination_id=identity,
                subject_id=identity,
                node_id=nodes[point],
                affordance="rest",
                duration_ticks=3,
            )
        )
    doc = dict(
        profile=PROFILE,
        district_id=prefix,
        base_artifact_sha256=hashlib.sha256(base_bytes).hexdigest(),
        producer=PRODUCER,
        seed=base["seed"],
        frame=Frame(origin_crs84_e7=base["frame"]["origin_crs84_e7"]).model_dump(mode="json"),
        bounds_mm=geometry.bounds,
        source_dependencies=deps,
        subjects=sorted(subjects, key=lambda r: r["subject_id"]),
        navigation=dict(
            profile="bounded-sidewalk-graph/v1",
            clearance_mm=450,
            nodes=sorted(
                (dict(node_id=i, subject_id=envelope_id, position_mm=p) for p, i in nodes.items()),
                key=lambda r: r["node_id"],
            ),
            edges=sorted(edges, key=lambda r: r["edge_id"]),
            destinations=sorted(destinations, key=lambda r: r["destination_id"]),
            unavailable_reason=None if nodes else "no-supported-connected-sidewalk",
        ),
        unsupported=[
            "actual doors and interiors",
            "surveyed roads and crossings",
            "real-world accessibility",
            "terrain elevation",
            "individual windows as objects",
            "unregistered authored frames",
            "training and package export",
            "routes outside the published component",
        ],
    )
    doc["document_sha256"] = hashlib.sha256(canonical_json(doc)).hexdigest()
    parsed = DistrictInterpretation.model_validate(doc)
    return canonical_json(parsed.model_dump(mode="json")) + b"\n"


def validate_interpretation(data: bytes | dict, base_bytes: bytes) -> DistrictInterpretation:
    document = DistrictInterpretation.model_validate(
        json.loads(data) if isinstance(data, bytes) else data
    )
    base = _base(base_bytes)
    if document.base_artifact_sha256 != hashlib.sha256(base_bytes).hexdigest():
        raise ValueError("base artifact digest mismatch")
    if document.district_id != base["district_id"] or document.seed != base["seed"]:
        raise ValueError("base identity mismatch")
    if document.frame.origin_crs84_e7 != tuple(
        base["frame"]["origin_crs84_e7"]
    ) or document.bounds_mm != tuple(v * 10 for v in base["bounds_cm"]):
        raise ValueError("coordinate agreement failure")
    if [s.model_dump(mode="json") for s in document.source_dependencies] != _dependencies(base):
        raise ValueError("source dependency drift")
    features = {f["id"]: f for f in base["buildings"] + base["sidewalks"]}
    subjects = {s.subject_id: s for s in document.subjects}
    deps = {s.dataset_id: s.sha256 for s in document.source_dependencies}
    feature_datasets = {
        f["id"]: dataset
        for layer, dataset in (("buildings", "5zhs-2jue"), ("sidewalks", "52n9-sdep"))
        for f in base[layer]
    }
    building_ids = {b["id"] for b in base["buildings"]}
    if not set(features).issubset(subjects):
        raise ValueError("missing source subjects")
    semantics = {
        "facade-grid": ("facade", "generated", ("render", "select")),
        "roof-parapet": ("roof", "generated", ("render", "select")),
        "flat-ground": ("ground", "authored", ("render", "select", "collide")),
        "residual-ground": ("road-completion", "generated", ("render", "select")),
        "walk-envelope": (
            "walk-envelope",
            "interpretation",
            ("render", "select", "navigate", "simulate"),
        ),
        "entrance-marker": ("entrance", "generated", ("render", "select", "simulate")),
        "rest-pad": ("civic-object", "generated", ("render", "select", "simulate")),
    }
    for subject in document.subjects:
        for ref in subject.source_refs:
            if (
                deps.get(ref.dataset_id) != ref.sha256
                or feature_datasets.get(ref.feature_id) != ref.dataset_id
            ):
                raise ValueError("unresolved subject dependency")
        recipe = subject.recipe
        if isinstance(recipe, Footprint):
            is_building = recipe.feature_id in building_ids
            expected = (
                "building" if is_building else "sidewalk",
                "observation",
                ("render", "select", "collide") if is_building else ("render", "select"),
            )
            if subject.subject_id != recipe.feature_id:
                raise ValueError("footprint subject identity mismatch")
        else:
            expected = semantics[recipe.kind]
        if (subject.kind, subject.epistemic_status, subject.permitted_uses) != expected:
            raise ValueError("recipe kind, observation status or permitted uses mismatch")
        feature_id = getattr(recipe, "feature_id", None)
        if feature_id and (
            feature_id not in features
            or feature_id not in [r.feature_id for r in subject.source_refs]
        ):
            raise ValueError("unresolved recipe feature")
        if isinstance(recipe, (Facade, Roof)) and feature_id not in building_ids:
            raise ValueError("building recipe references nonbuilding")
        expected_refs = (
            [feature_id]
            if feature_id
            else ([recipe.building_subject_id] if isinstance(recipe, Entrance) else [])
        )
        if [r.feature_id for r in subject.source_refs] != expected_refs:
            raise ValueError("recipe source references mismatch")
        if isinstance(recipe, Residual) and set(recipe.excluded_subject_ids) != set(features):
            raise ValueError("road exclusion mismatch")
        if isinstance(recipe, Entrance):
            building = features.get(recipe.building_subject_id)
            if (
                not building
                or recipe.building_subject_id not in building_ids
                or recipe.polygon_index >= len(building["polygons"])
                or recipe.facade_edge_index
                >= len(building["polygons"][recipe.polygon_index][0]) - 1
            ):
                raise ValueError("unresolved entrance facade")
        if isinstance(recipe, Envelope):
            w, n, e, s = recipe.bounds_mm
            bw, bn, be, bs = document.bounds_mm
            if not (bw <= w < e <= be and bn <= n < s <= bs):
                raise ValueError("invalid navigation envelope bounds")
        if subject.epistemic_status == "observation" and not isinstance(recipe, Footprint):
            raise ValueError("completion cannot claim observation")
    nav = document.navigation
    geometry = DistrictGeometry(base)
    nodes = {n.node_id: n for n in nav.nodes}
    for node in nav.nodes:
        if (
            node.subject_id not in subjects
            or "navigate" not in subjects[node.subject_id].permitted_uses
        ):
            raise ValueError("unresolved navigation subject")
        envelope = subjects[node.subject_id].recipe
        if not isinstance(envelope, Envelope):
            raise ValueError("invalid navigation envelope")
        x, z = node.position_mm
        w, n, e, s = envelope.bounds_mm
        if not (w <= x <= e and n <= z <= s):
            raise ValueError("node outside navigation envelope")
        if not geometry.supports(node.position_mm, node.position_mm, nav.clearance_mm):
            raise ValueError("unsupported navigation node")
    for edge in nav.edges:
        if (
            edge.subject_id not in subjects
            or edge.from_node_id not in nodes
            or edge.to_node_id not in nodes
            or edge.from_node_id == edge.to_node_id
        ):
            raise ValueError("unresolved edge dependency")
        if not (
            edge.subject_id
            == nodes[edge.from_node_id].subject_id
            == nodes[edge.to_node_id].subject_id
        ):
            raise ValueError("edge subject disagreement")
        a, b = nodes[edge.from_node_id].position_mm, nodes[edge.to_node_id].position_mm
        if edge.length_mm != length_mm(a, b) or not geometry.supports(a, b, nav.clearance_mm):
            raise ValueError("route collision or length mismatch")
    for target in nav.destinations:
        if target.subject_id not in subjects or target.node_id not in nodes:
            raise ValueError("unresolved destination dependency")
        subject = subjects[target.subject_id]
        if (
            "simulate" not in subject.permitted_uses
            or getattr(subject.recipe, "position_mm", None) != nodes[target.node_id].position_mm
        ):
            raise ValueError("destination coordinate disagreement")
        if (target.affordance == "rest") != isinstance(
            subject.recipe, RestPad
        ) or target.duration_ticks != (3 if target.affordance == "rest" else 1):
            raise ValueError("unsupported affordance timing or recipe")
    if bool(nav.nodes) != (nav.unavailable_reason is None) or (
        not nav.nodes and (nav.edges or nav.destinations)
    ):
        raise ValueError("navigation availability disagreement")
    return document


def unavailable_dependencies(
    document: DistrictInterpretation, current: Mapping[str, str]
) -> tuple[str, ...]:
    """Current authorization is separate from immutable bytes; missing resolution fails closed."""
    return tuple(
        f"{source.sha256}:{current.get(source.sha256, 'unresolved')}"
        for source in document.source_dependencies
        if current.get(source.sha256) != "available"
    )


def shortest_route(
    document: DistrictInterpretation, start: str, end: str, current: Mapping[str, str]
) -> tuple[str, ...] | None:
    if unavailable_dependencies(document, current) or document.navigation.unavailable_reason:
        return None
    graph: dict[str, list[tuple[str, int]]] = {n.node_id: [] for n in document.navigation.nodes}
    if start not in graph or end not in graph:
        return None
    for edge in document.navigation.edges:
        graph[edge.from_node_id].append((edge.to_node_id, edge.length_mm))
        graph[edge.to_node_id].append((edge.from_node_id, edge.length_mm))
    pending = [(0, (start,), start)]
    best = {}
    while pending:
        distance, path, node = heapq.heappop(pending)
        if node in best:
            continue
        best[node] = distance
        if node == end:
            return path
        for neighbor, cost in sorted(graph[node]):
            if neighbor not in best:
                heapq.heappush(pending, (distance + cost, (*path, neighbor), neighbor))
    return None
