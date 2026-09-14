from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.environment.district_geometry import (
    DistrictGeometry,
    segment_blocked,
    segment_inside,
)
from exulanica.environment.district_interpretation import (
    compile_interpretation,
    shortest_route,
    unavailable_dependencies,
    validate_interpretation,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets/owned-world/flatiron/flatiron-owned-district.json"
ARTIFACT = ROOT / "assets/owned-world/flatiron-interpretation-v1/district-interpretation.json"


def resign(doc):
    doc.pop("document_sha256", None)
    doc["document_sha256"] = hashlib.sha256(canonical_json(doc)).hexdigest()
    return doc


@pytest.fixture(scope="module")
def district():
    return validate_interpretation(ARTIFACT.read_bytes(), BASE.read_bytes())


def test_retained_artifact_reproduces_without_changing_old_input(district):
    before = BASE.read_bytes()
    assert compile_interpretation(before) == ARTIFACT.read_bytes()
    assert compile_interpretation(before) == compile_interpretation(before)
    assert BASE.read_bytes() == before
    assert district.navigation.nodes and district.navigation.edges
    assert {d.affordance for d in district.navigation.destinations} == {"visit", "rest"}
    assert any(d.subject_id.endswith("doitt_id:507159") for d in district.navigation.destinations)


def test_all_routes_destinations_share_collision_safe_coordinates(district):
    geometry = DistrictGeometry(json.loads(BASE.read_bytes()))
    nodes = {n.node_id: n for n in district.navigation.nodes}
    current = {s.sha256: "available" for s in district.source_dependencies}
    for edge in district.navigation.edges:
        assert geometry.supports(
            nodes[edge.from_node_id].position_mm, nodes[edge.to_node_id].position_mm
        )
    start = district.navigation.destinations[0].node_id
    for target in district.navigation.destinations:
        path = shortest_route(district, start, target.node_id, current)
        assert path and path[0] == start and path[-1] == target.node_id
    assert shortest_route(district, "unresolved", start, current) is None


def test_withdrawn_and_unresolved_dependencies_do_not_restore_routes(district):
    start, end = district.navigation.nodes[0].node_id, district.navigation.nodes[-1].node_id
    current = {s.sha256: "available" for s in district.source_dependencies}
    assert shortest_route(district, start, end, current)
    for reason in ["withdrawn", "unavailable", "binding_drift", "unrecognized"]:
        changed = {**current, district.source_dependencies[0].sha256: reason}
        assert unavailable_dependencies(district, changed)
        assert shortest_route(district, start, end, changed) is None
    assert shortest_route(district, start, end, {}) is None
    # Re-reading an old valid document cannot renew current rights.
    restored = validate_interpretation(ARTIFACT.read_bytes(), BASE.read_bytes())
    assert shortest_route(restored, start, end, changed) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(profile="unknown"),
        lambda d: d.update(extra="unrecognized"),
        lambda d: d.update(seed=True),
        lambda d: d["frame"].update(horizontal_unit="metre"),
        lambda d: d["frame"].update(origin_crs84_e7=[0, 0]),
        lambda d: d["navigation"]["nodes"][0].update(position_mm=[0, 0]),
        lambda d: d["navigation"]["nodes"][0].update(subject_id="absent"),
        lambda d: d["navigation"]["edges"][0].update(to_node_id="absent"),
        lambda d: d["navigation"]["edges"][0].update(length_mm=1),
        lambda d: d["navigation"]["destinations"][0].update(duration_ticks=2),
        lambda d: d["navigation"]["destinations"][0].update(node_id="absent"),
        lambda d: d["navigation"]["destinations"][0].update(affordance="enter"),
        lambda d: d["source_dependencies"][0].update(sha256="a" * 64),
        lambda d: d["subjects"].append(d["subjects"][0]),
    ],
)
def test_rejects_even_resigned_malformed_schema_and_bindings(mutation):
    doc = json.loads(ARTIFACT.read_bytes())
    mutation(doc)
    with pytest.raises(ValueError):
        validate_interpretation(resign(doc), BASE.read_bytes())


def test_digest_binds_exact_old_bytes_and_generated_status():
    doc = json.loads(ARTIFACT.read_bytes())
    doc["subjects"][0]["uncertainty"] = "tampered"
    with pytest.raises(ValueError, match="digest"):
        validate_interpretation(doc, BASE.read_bytes())
    with pytest.raises(ValueError, match="base artifact digest"):
        validate_interpretation(ARTIFACT.read_bytes(), BASE.read_bytes() + b" ")
    doc = json.loads(ARTIFACT.read_bytes())
    next(s for s in doc["subjects"] if s["kind"] == "facade")["epistemic_status"] = "observation"
    with pytest.raises(ValueError, match="observation"):
        validate_interpretation(resign(doc), BASE.read_bytes())


def test_seed_changes_recipe_digest_not_source_subject_identity(district):
    base = json.loads(BASE.read_bytes())
    base["seed"] += 1
    changed = validate_interpretation(
        compile_interpretation(canonical_json(base)), canonical_json(base)
    )
    assert changed.document_sha256 != district.document_sha256
    assert [s.subject_id for s in changed.subjects] == [s.subject_id for s in district.subjects]


def test_no_coverage_is_explicit_and_no_generated_ground_routes():
    base = json.loads(BASE.read_bytes())
    base["sidewalks"] = []
    data = canonical_json(base)
    result = validate_interpretation(compile_interpretation(data), data)
    assert result.navigation.unavailable_reason == "no-supported-connected-sidewalk"
    assert not result.navigation.nodes and not result.navigation.destinations


def test_exact_segment_guards_holes_thin_barriers_touching_and_concavity():
    outer = [(0, 0), (20000, 0), (20000, 20000), (0, 20000), (0, 0)]
    hole = [(9000, 9000), (10000, 9000), (10000, 10000), (9000, 10000), (9000, 9000)]
    assert segment_inside((1000, 1000), (19000, 1000), [outer, hole], 450)
    assert not segment_inside((1000, 9500), (19000, 9500), [outer, hole], 450)
    assert not segment_inside((1000, 450), (19000, 450), [outer], 450)
    thin = [(9900, 0), (9901, 0), (9901, 20000), (9900, 20000), (9900, 0)]
    assert segment_blocked((1000, 10000), (19000, 10000), thin, 450)
    # Both endpoints safe, but the segment crosses the concave notch.
    concave = [
        (0, 0),
        (20000, 0),
        (20000, 20000),
        (11000, 20000),
        (11000, 5000),
        (9000, 5000),
        (9000, 20000),
        (0, 20000),
        (0, 0),
    ]
    assert not segment_inside((2000, 10000), (18000, 10000), [concave], 450)


def test_route_rejects_safe_endpoints_whose_connector_crosses_building(district):
    doc = district.model_dump(mode="json")
    geometry = DistrictGeometry(json.loads(BASE.read_bytes()))
    pair = next(
        (a, b)
        for a in district.navigation.nodes
        for b in district.navigation.nodes
        if a.node_id < b.node_id and not geometry.supports(a.position_mm, b.position_mm)
    )
    a, b = pair
    from exulanica.environment.district_geometry import length_mm

    edge = copy.deepcopy(doc["navigation"]["edges"][0])
    edge.update(
        from_node_id=a.node_id,
        to_node_id=b.node_id,
        length_mm=length_mm(a.position_mm, b.position_mm),
    )
    doc["navigation"]["edges"][0] = edge
    with pytest.raises(ValueError, match="collision"):
        validate_interpretation(resign(doc), BASE.read_bytes())


@pytest.mark.parametrize(
    "case",
    [
        "wrong-layer",
        "wrong-kind",
        "missing-source",
        "wrong-use",
        "wrong-edge-subject",
        "wrong-footprint",
        "outside-envelope",
    ],
)
def test_rejects_semantic_cross_binding(case):
    doc = json.loads(ARTIFACT.read_bytes())
    building = next(s for s in doc["subjects"] if s["kind"] == "building")
    if case == "wrong-layer":
        source = next(s for s in doc["source_dependencies"] if s["dataset_id"] == "52n9-sdep")
        building["source_refs"][0].update(dataset_id=source["dataset_id"], sha256=source["sha256"])
    elif case == "wrong-kind":
        building["kind"] = "sidewalk"
    elif case == "missing-source":
        doc["subjects"].remove(building)
    elif case == "wrong-use":
        next(s for s in doc["subjects"] if s["kind"] == "facade")["permitted_uses"].append(
            "collide"
        )
    elif case == "wrong-edge-subject":
        doc["navigation"]["edges"][0]["subject_id"] = building["subject_id"]
    elif case == "wrong-footprint":
        building["recipe"]["feature_id"] = next(
            s for s in doc["subjects"] if s["kind"] == "sidewalk"
        )["subject_id"]
    else:
        next(s for s in doc["subjects"] if s["kind"] == "walk-envelope")["recipe"]["bounds_mm"] = [
            0,
            0,
            100,
            100,
        ]
    with pytest.raises(ValueError):
        validate_interpretation(resign(doc), BASE.read_bytes())


def test_python_types_remain_compatible_with_frozen_recipe_schema():
    from exulanica.environment.district_interpretation import DistrictInterpretation

    # Schema is intentionally generated from strict tagged models; validation does not mutate it.
    schema = DistrictInterpretation.model_json_schema()
    assert schema["additionalProperties"] is False
    assert (
        schema["$defs"]["Subject"]["properties"]["recipe"]["discriminator"]["propertyName"]
        == "kind"
    )


def test_old_source_compiler_bytes_match_the_retained_bundle():
    from exulanica.environment.owned_district import DownloadedLayer, compile_district

    base = json.loads(BASE.read_bytes())
    records = {s["dataset_id"]: s for s in base["source_records"]}
    layers = []
    for dataset, file in [("5zhs-2jue", "buildings.geojson"), ("52n9-sdep", "sidewalks.geojson")]:
        record = records[dataset]
        data = (BASE.parent / "source" / file).read_bytes()
        assert hashlib.sha256(data).hexdigest() == record["sha256"]
        layers.append(
            DownloadedLayer(dataset, data, record["source_url"], record["provider_revision"])
        )
    assert compile_district(*layers, seed=base["seed"]).data == BASE.read_bytes()


def test_source_iteration_order_does_not_change_semantic_recipes_or_routes(district):
    base = json.loads(BASE.read_bytes())
    base["buildings"].reverse()
    base["sidewalks"].reverse()
    data = canonical_json(base)
    result = validate_interpretation(compile_interpretation(data), data)
    assert result.subjects == district.subjects
    assert result.navigation == district.navigation
    assert result.base_artifact_sha256 != district.base_artifact_sha256


@pytest.mark.parametrize("case", ["unclosed", "noninteger", "bad-bbox", "empty", "duplicate"])
def test_extension_rejects_malformed_base_geometry(case):
    base = json.loads(BASE.read_bytes())
    building = base["buildings"][0]
    if case == "unclosed":
        building["polygons"][0][0].pop()
    elif case == "noninteger":
        building["polygons"][0][0][0][0] = True
    elif case == "bad-bbox":
        building["bbox_cm"][0] -= 1000
    elif case == "empty":
        building["polygons"] = []
    else:
        base["buildings"].append(building)
    with pytest.raises(ValueError):
        compile_interpretation(canonical_json(base))
