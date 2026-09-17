"""The tile bake: a deterministic stage whose output is the Node tessellator's bytes.

What this file holds the ``baked_tile`` stage to.

*   The stage declares itself deterministic, names no model role, refuses any run-time binding,
    and refuses a float in its parameters.
*   Its key is ``scene_group``'s shape with the tile's own key last, the tile key covers the
    ordered edit subsequence from the first bake, the empty subsequence has one encoding, and a
    nonempty one moves the key.
*   The parameters the registry states are the parameters the tessellator states, byte for byte,
    and the record shapes the tessellator reads are the grammar's own, field by field.
*   Two Node bakes of the conformance fixture under one key write byte-identical containers, and
    a second, independent reading of the triangle digest specification in Python agrees with the
    tessellator's.
*   A material record with its texture set stripped is refused, not defaulted.

**What is not here, and why.** The brief's fifth assertion, that a perturbed rebake under a fixed
key emits ``nondeterminism_detected`` and keeps the stored artifact, needs a row to keep. There is
none a tile can honestly have: ``artifact`` requires a source blob, a tile has none, and filing
tile bytes in ``derived_artifact`` would mix planes. The orchestrator decided on 2026-09-16 that
the baked-tile table and its fault path arrive with the corridor lane's migration 0072, keyed by
``baked_tile_id``. Until then that assertion is unbuilt, and this file does not pretend otherwise.

**The fixture.** ``web/packages/loom-tess/test/fixtures/tile-conformance.json`` is written by
:func:`build_fixture_document` below, from the grammar's own record classes, and the test holds
the committed bytes to it. Regenerate with::

    uv run python tests/test_bake_determinism.py --write-fixture

Its grammar is a TEST-ONLY descriptor beside it, ``cityrenderfixture.v1.json``, which admits
``render_batch`` and ``nav_envelope`` over the real city record classes; city version 1 admits no
projection, so a city version 1 tile draws nothing at all. Every key field the empty catalogs
cannot source carries an ``unresolved_`` value, and a test below proves none of them resolves.
Everything else is either read from the grammar and the pinned texture sets, or is a chosen
fixture input, listed in the fixture's README.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.errors import CanonicalisationError
from exulanica.evidence.blob import BlobId
from exulanica.grammar import Grammar, generate
from exulanica.grammar.catalogs import catalog_digest
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city import CITY_STAGES
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
from exulanica.grammar.grammars.city.facade import FacadeRecord
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.material import (
    MAXIMUM_ROTATION_URAD,
    MILLIONTHS,
    SurfaceMaterialRecord,
    require_texture_set,
)
from exulanica.grammar.grammars.city.parcels import LOT_CLASSES, ParcelRecord
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord
from exulanica.grammar.grammars.city.streets import (
    CURB_SIDES,
    KERB_HEIGHT_MAXIMUM_MM,
    KERB_HEIGHT_MINIMUM_MM,
    CurbEdgeRecord,
    StreetNodeRecord,
    StreetSegmentRecord,
)
from exulanica.grammar.grammars.city.terrain import TerrainRecord
from exulanica.grammar.grammars.city.tile import (
    HALO_RADIUS_MM,
    TILE_SIZE_MM,
    TileRecord,
    tile_inputs_digest,
)
from exulanica.grammar.grammars.city.vitrine import (
    VITRINE_DEPTH_MAXIMUM_MM,
    VITRINE_DEPTH_MINIMUM_MM,
    VitrineRecord,
)
from exulanica.grammar.records import KEY_PATTERN, canonical_record, record_payload
from exulanica.grammar.textures import TEXTURE_SET_ID, read_texture_manifest
from exulanica.ingest.stages import (
    ARTIFACT_NAMESPACE,
    STAGES,
    StageSpec,
    baked_tile_id,
    baked_tile_record_shapes,
    edit_delta_digest_of,
    idempotency_key,
    input_digest_of,
    stage,
)

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT.joinpath("web")
PACKAGE = WEB.joinpath("packages", "loom-tess")
FIXTURES = PACKAGE.joinpath("test", "fixtures")
DOCUMENT = FIXTURES.joinpath("tile-conformance.json")
DESCRIPTOR = FIXTURES.joinpath("cityrenderfixture.v1.json")
CLI = PACKAGE.joinpath("src", "node", "cli.ts")
TSX = WEB.joinpath("node_modules", ".bin", "tsx")
LIBRARY = WEB.joinpath("packages", "loom-texture", "library", "cc0.brick-running-bond.json")

TILE_DOCUMENT_PROFILE = "exulanica.tile-document/v1"
UNRESOLVED = "unresolved_"

#: The fixture's seed, chosen by naming it: SHA-256 of a label that says what it is for.
FIXTURE_SEED = hashlib.sha256(b"exulanica loom-tess conformance fixture").hexdigest()
#: The fixture's one building, identified the way an admitting party would: uuid5 over a stable
#: tuple. The tessellator never mints an identity; this test is the party that admitted it.
FIXTURE_BUILDING = str(
    uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.local/fixtures/loom-tess/building/0")
)


def fixture_grammar() -> Grammar:
    """The test-only descriptor, over the real city stages and their validators."""
    return Grammar.from_descriptor(DESCRIPTOR, stages=CITY_STAGES)


def _brick_modules() -> tuple[int, int]:
    """Course and mortar modules read from the pinned brick set's own recipe.

    A course is one unit height plus one bed joint; the mortar module is the bed joint. Both come
    from ``web/packages/loom-texture/library/cc0.brick-running-bond.json``.
    """
    recipe = json.loads(LIBRARY.read_text(encoding="utf-8"))["recipe"]["parameters"]
    return recipe["unit_height_mm"] + recipe["bed_joint_mm"], recipe["bed_joint_mm"]


def build_fixture_records() -> tuple[TileRecord, list[object]]:
    """The conformance tile, written by hand in the grammar's record classes.

    Small enough to read, and shaped to exercise the failure modes: a terrain grid that draws, a
    lot whose ring has a chamfered corner edge under 1.2 m (edge 2, 800 mm on each axis), a facade
    record on that short edge, ground-floor glazing represented by a vitrine record, one surface
    material bound to a pinned texture set, and a street with its kerb and a tree position.
    """
    grammar = fixture_grammar()
    sets = read_texture_manifest()
    receipt = generate(grammar, seed=FIXTURE_SEED, subject_identity=FIXTURE_BUILDING).receipt
    tile = TileRecord(
        city_seed=FIXTURE_SEED,
        grammar_versions=((grammar.key.grammar_id, grammar.key.grammar_version),),
        catalog_digest=catalog_digest(load_city_catalogs(texture_sets=sets)),
        tile_x=0,
        tile_y=0,
        lod=0,
        tile_size_mm=TILE_SIZE_MM,
        halo_radius_mm=HALO_RADIUS_MM,
        edit_delta_digest=edit_delta_digest_of([]),
    )
    # A plane rising 120 mm per cell in x and 160 mm in y over 4 m cells: a 3-4-5 slope, so the
    # stated slope magnitude is exactly 200 / 4000 = 50,000 millionths at every sample.
    columns, rows, cell = 4, 4, 4000
    heights = tuple(
        -200 + 120 * column + 160 * row for row in range(rows) for column in range(columns)
    )
    terrain = TerrainRecord(
        origin_x_mm=-4000,
        origin_y_mm=-4000,
        cell_mm=cell,
        columns=columns,
        rows=rows,
        height_mm=heights,
        slope_millionths=(50_000,) * (columns * rows),
    )
    ring = ((1000, 1000), (7000, 1000), (7000, 6200), (6200, 7000), (1000, 7000))
    parcel = ParcelRecord(
        parcel_ordinal=0,
        block_ordinal=0,
        lot_class=LOT_CLASSES[0],
        boundary_mm=ring,
        frontage_segment_ordinal=0,
        frontage_mm=6000,
        address_number=1,
        threshold_offset_mm=3000,
    )
    massing = MassingRecord(
        building_identity=FIXTURE_BUILDING,
        parcel_ordinal=0,
        typology=f"{UNRESOLVED}typology",
        era=f"{UNRESOLVED}era",
        storeys=4,
        ground_storey_height_mm=4500,
        upper_storey_height_mm=3200,
        setbacks=((3, 1500),),
        party_wall_edges=(4,),
        light_well_count=0,
        roof_family=f"{UNRESOLVED}roof_family",
        parapet_height_mm=900,
        rooftop_plant_count=1,
        rooftop_tank_count=1,
    )
    facades = [
        FacadeRecord(
            building_identity=FIXTURE_BUILDING,
            grammar_version=receipt.grammar_version,
            parameters=receipt.parameters.values,
            seed=receipt.seed,
            output_digest=receipt.output_digest,
            declared_semantics=receipt.declared_semantics,
            edge_ordinal=edge,
        )
        for edge in (0, 1, 2, 3)
    ]
    course, mortar = _brick_modules()
    material = SurfaceMaterialRecord(
        building_identity=FIXTURE_BUILDING,
        edge_ordinal=0,
        material=f"{UNRESOLVED}material",
        texture_set_id="cc0.brick-running-bond",
        # The identity transform and no weathering: neutral values, not chosen looks.
        uv_scale_millionths=MILLIONTHS,
        uv_rotation_urad=0,
        course_module_mm=course,
        mortar_module_mm=mortar,
        soiling_gradient_millionths=0,
        base_weathering_millionths=0,
        reveal_darkening_millionths=0,
    )
    require_texture_set(material, sets)
    vitrine = VitrineRecord(
        building_identity=FIXTURE_BUILDING,
        edge_ordinal=0,
        bay_ordinal=0,
        depth_mm=VITRINE_DEPTH_MINIMUM_MM,
        fitout=f"{UNRESOLVED}fitout",
    )
    premises = PremisesRecord(
        building_identity=FIXTURE_BUILDING,
        unit_ordinal=0,
        use_class=f"{UNRESOLVED}use_class",
        sign=f"{UNRESOLVED}sign",
    )
    nodes = [
        StreetNodeRecord(node_ordinal=0, x_mm=-4000, y_mm=-3000),
        StreetNodeRecord(node_ordinal=1, x_mm=8000, y_mm=-3000),
    ]
    segment = StreetSegmentRecord(
        segment_ordinal=0,
        start_node=0,
        end_node=1,
        centreline_mm=((-4000, -3000), (8000, -3000)),
        hierarchy=f"{UNRESOLVED}street_hierarchy",
        carriageway_width_mm=5000,
        kerb_height_mm=(KERB_HEIGHT_MINIMUM_MM + KERB_HEIGHT_MAXIMUM_MM) // 2,
        gutter_width_mm=300,
        footway_width_mm=1500,
        corner_radius_mm=3000,
        crossing_offsets_mm=(2000, 9000),
    )
    curbs = [
        CurbEdgeRecord(curb_ordinal=0, segment_ordinal=0, side=CURB_SIDES[0], next_curb_ordinal=1),
        CurbEdgeRecord(curb_ordinal=1, segment_ordinal=0, side=CURB_SIDES[1], next_curb_ordinal=0),
    ]
    tree = StreetFurnitureRecord(
        item_ordinal=0,
        item_class=f"{UNRESOLVED}tree_species",
        segment_ordinal=0,
        side=CURB_SIDES[0],
        along_mm=3000,
        kerb_offset_mm=600,
        x_mm=-1000,
        y_mm=100,
    )
    records: list[object] = [
        terrain,
        *nodes,
        segment,
        *curbs,
        parcel,
        massing,
        *facades,
        material,
        tree,
        vitrine,
        premises,
    ]
    return tile, records


def descriptor_sha256() -> str:
    return hashlib.sha256(DESCRIPTOR.read_bytes()).hexdigest()


def build_fixture_document() -> bytes:
    tile, records = build_fixture_records()
    grammar = fixture_grammar()
    semantics = grammar.semantics
    document = {
        "profile": TILE_DOCUMENT_PROFILE,
        "tile": record_payload(tile),
        "grammars": [
            {
                "grammar_id": grammar.key.grammar_id,
                "grammar_version": grammar.key.grammar_version,
                "descriptor_sha256": descriptor_sha256(),
                "declared_semantics": {
                    "subject_kind": semantics.subject_kind,
                    "admissible_uses": list(semantics.admissible_uses),
                    "plane": semantics.plane,
                },
                "records": [record_payload(record) for record in records],
            }
        ],
    }
    return canonical_json(document)


# -- the registry ---------------------------------------------------------------------------------


def test_the_bake_stage_is_registered_deterministic_with_no_model_role():
    spec = stage("baked_tile")
    assert spec.key == "baked_tile"
    assert spec.output_kind == "owd_tile"
    assert spec.deterministic is True
    assert spec.model_role is None
    assert spec.params["container"] == "owd/1"
    assert spec.params["tile_size_mm"] == TILE_SIZE_MM
    assert spec.params["halo_radius_mm"] == HALO_RADIUS_MM
    assert spec.params["record_shapes"] == baked_tile_record_shapes()


def test_the_bake_stage_refuses_any_binding():
    spec = stage("baked_tile")
    with pytest.raises(ValueError, match="declares no model_role"):
        idempotency_key(
            BlobId.of_bytes(b"anything"), spec, input_digest_of([]), binding={"model_id": "x/y"}
        )


def _floated(value: Any) -> list[Any]:
    """Every copy of ``value`` with exactly one integer replaced by a float."""
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [float(value)]
    if isinstance(value, dict):
        return [
            {**value, key: variant} for key, item in value.items() for variant in _floated(item)
        ]
    if isinstance(value, list):
        return [
            [*value[:index], variant, *value[index + 1 :]]
            for index, item in enumerate(value)
            for variant in _floated(item)
        ]
    return []


def test_no_float_reaches_the_bake_parameters():
    """Gate 6, for this stage by name, so a later parameter edit cannot slip a float in."""
    spec = stage("baked_tile")
    variants = _floated(spec.params)
    assert len(variants) >= 5, "the float probe found too few integers to prove anything"
    for variant in variants:
        with pytest.raises(CanonicalisationError):
            canonical_json(variant)
        with pytest.raises(CanonicalisationError):
            dataclasses.replace(spec, params=variant)


def test_no_float_reaches_the_tile_record_set():
    """Gate 6 over every integer of every record the fixture carries, the tile record included."""
    tile, records = build_fixture_records()
    probed = 0
    for record in [tile, *records]:
        for variant in _floated(record_payload(record)):
            probed += 1
            with pytest.raises(CanonicalisationError):
                canonical_json(variant)
        for field in dataclasses.fields(record):
            value = getattr(record, field.name)
            if type(value) is int:
                floated = dataclasses.replace(record, **{field.name: float(value)})
                with pytest.raises(CanonicalisationError):
                    canonical_record(floated)
    assert probed > 50


# -- the key --------------------------------------------------------------------------------------


def test_the_empty_edit_subsequence_has_one_encoding():
    assert edit_delta_digest_of([]) == hashlib.sha256(b"[]").hexdigest()
    tile, _ = build_fixture_records()
    assert tile.edit_delta_digest == edit_delta_digest_of([])


def test_a_nonempty_edit_subsequence_moves_the_key():
    """Gate 14, before any cache exists: an edit that targets the tile changes its key."""
    spec = stage("baked_tile")
    tile, _ = build_fixture_records()
    first = hashlib.sha256(b"an edit").digest()
    second = hashlib.sha256(b"another edit").digest()
    empty_key = baked_tile_id(spec, tile)
    keys = {
        empty_key,
        baked_tile_id(
            spec, dataclasses.replace(tile, edit_delta_digest=edit_delta_digest_of([first]))
        ),
        baked_tile_id(
            spec, dataclasses.replace(tile, edit_delta_digest=edit_delta_digest_of([first, second]))
        ),
        baked_tile_id(
            spec, dataclasses.replace(tile, edit_delta_digest=edit_delta_digest_of([second, first]))
        ),
    }
    assert len(keys) == 4, "a nonempty or reordered edit subsequence left the key unmoved"


def test_the_key_is_the_scene_group_shape_with_the_tile_key_last():
    spec = stage("baked_tile")
    tile, _ = build_fixture_records()
    inputs = tile_inputs_digest(tile)
    assert baked_tile_id(spec, tile) == uuid.uuid5(
        ARTIFACT_NAMESPACE, f"baked_tile:{spec.version}:{spec.params_digest.hex()}:{inputs}"
    )
    moved = dataclasses.replace(spec, params={**spec.params, "lod": 1})
    assert baked_tile_id(moved, tile) != baked_tile_id(spec, tile)
    with pytest.raises(ValueError, match="not the tile bake"):
        baked_tile_id(STAGES["scene_group"], tile)
    with pytest.raises(ValueError):
        edit_delta_digest_of([b"short"])


# -- the fixture ----------------------------------------------------------------------------------


def test_the_committed_fixture_is_what_the_record_classes_write():
    assert DOCUMENT.read_bytes() == build_fixture_document(), (
        "the committed fixture is stale; run: uv run python tests/test_bake_determinism.py "
        "--write-fixture, then update the golden digest in "
        "web/packages/loom-tess/test/triangle-digest-conformance.test.ts"
    )


def test_every_fixture_record_passes_its_own_grammar_validator():
    grammar = fixture_grammar()
    tile, records = build_fixture_records()
    stages = {stage_.stage_id: stage_ for stage_ in grammar.stages}
    stages["tile"].validate(tile)
    validated = 0
    for record in records:
        for candidate in grammar.stages:
            try:
                candidate.validate(record)
            except InvalidRecordError:  # every other stage refuses the record by design
                continue
            validated += 1
            break
    assert validated == len(records)
    assert grammar.semantics.admissible_uses == ("render_batch", "nav_envelope")
    document = json.loads(DOCUMENT.read_bytes())
    entry = document["grammars"][0]
    assert entry["descriptor_sha256"] == descriptor_sha256()
    assert entry["grammar_id"] == "cityrenderfixture"


def test_the_unresolved_fixture_keys_resolve_to_no_catalog_entry():
    """Every key the empty catalogs cannot source is labelled, and none of them resolves."""
    catalogs = load_city_catalogs(texture_sets=read_texture_manifest())
    known = {entry["key"] for catalog in catalogs for entry in catalog.payload()["entries"]}
    every_catalog = canonical_json([catalog.payload() for catalog in catalogs]).decode("utf-8")
    _, records = build_fixture_records()
    labelled = sorted(
        getattr(record, field.name)
        for record in records
        for field in dataclasses.fields(record)
        if isinstance(getattr(record, field.name), str)
        and getattr(record, field.name).startswith(UNRESOLVED)
    )
    assert labelled == sorted(
        f"{UNRESOLVED}{name}"
        for name in (
            "era",
            "fitout",
            "material",
            "roof_family",
            "sign",
            "street_hierarchy",
            "tree_species",
            "typology",
            "use_class",
        )
    )
    for value in labelled:
        assert value not in known
        assert value not in every_catalog


def test_the_fixture_keeps_every_value_inside_its_grammar_bound():
    _, records = build_fixture_records()
    material = next(r for r in records if isinstance(r, SurfaceMaterialRecord))
    assert TEXTURE_SET_ID.fullmatch(material.texture_set_id)
    assert 0 <= material.uv_rotation_urad <= MAXIMUM_ROTATION_URAD
    vitrine = next(r for r in records if isinstance(r, VitrineRecord))
    assert VITRINE_DEPTH_MINIMUM_MM <= vitrine.depth_mm <= VITRINE_DEPTH_MAXIMUM_MM
    parcel = next(r for r in records if isinstance(r, ParcelRecord))
    (x0, y0), (x1, y1) = parcel.boundary_mm[2], parcel.boundary_mm[3]
    assert (x1 - x0) ** 2 + (y1 - y0) ** 2 < 1200**2, "the short corner edge is not under 1.2 m"


# -- the tessellator, through its own CLI ---------------------------------------------------------


def _tess(*arguments: str | Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    if not TSX.exists():
        pytest.skip(
            f"the web toolchain is not installed ({TSX} is missing); run pnpm install in web/"
        )
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    return subprocess.run(
        [str(TSX), str(CLI), *map(str, arguments)],
        cwd=WEB,
        capture_output=True,
        text=True,
        check=check,
        timeout=300,
    )


def test_the_tessellator_states_the_registry_parameters():
    printed = _tess("params").stdout
    assert printed.encode("ascii") == canonical_json(stage("baked_tile").params) + b"\n"


_PATTERNS = {
    "key": r"^[a-z][a-z0-9_]*$",
    "identity": r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    "hex64": r"^[0-9a-f]{64}$",
    "texture_set_id": r"^" + TEXTURE_SET_ID.pattern + r"$",
}


def test_the_tessellator_reads_the_grammars_own_record_shapes():
    """Field names and order-free field sets, bounds and closed values, against the grammar."""
    from exulanica.grammar import ADMISSIBLE_USES, PLANE
    from exulanica.grammar.records import _HEX64, _IDENTITY

    shapes = json.loads(_tess("shapes").stdout)
    assert shapes["plane"] == PLANE
    assert shapes["projections"] == list(ADMISSIBLE_USES)
    assert shapes["patterns"]["key"] == "^" + KEY_PATTERN.pattern + "$"
    assert shapes["patterns"]["identity"] == "^" + _IDENTITY.pattern + "$"
    assert shapes["patterns"]["hex64"] == "^" + _HEX64.pattern + "$"
    assert shapes["patterns"] == _PATTERNS
    assert shapes["material_record_kind"] == SurfaceMaterialRecord.RECORD_KIND

    by_kind = {shape["kind"]: shape for shape in [shapes["tile"], *shapes["records"]]}
    grammar_types = {
        record_type.RECORD_KIND: record_type
        for city_stage in CITY_STAGES
        for record_type, _ in city_stage.validators
    }
    assert set(by_kind) == set(grammar_types)
    for kind, record_type in grammar_types.items():
        shape = by_kind[kind]
        assert shape["version"] == record_type.RECORD_VERSION
        assert set(shape["fields"]) == {field.name for field in dataclasses.fields(record_type)}

    expected_bounds = {
        ("city.tile", "tile_size_mm"): {"type": "int", "min": TILE_SIZE_MM, "max": TILE_SIZE_MM},
        ("city.tile", "halo_radius_mm"): {
            "type": "int",
            "min": HALO_RADIUS_MM,
            "max": HALO_RADIUS_MM,
        },
        ("city.street_segment", "kerb_height_mm"): {
            "type": "int",
            "min": KERB_HEIGHT_MINIMUM_MM,
            "max": KERB_HEIGHT_MAXIMUM_MM,
        },
        ("city.vitrine", "depth_mm"): {
            "type": "int",
            "min": VITRINE_DEPTH_MINIMUM_MM,
            "max": VITRINE_DEPTH_MAXIMUM_MM,
        },
        ("city.surface_material", "uv_rotation_urad"): {
            "type": "int",
            "min": 0,
            "max": MAXIMUM_ROTATION_URAD,
        },
        ("city.parcel", "lot_class"): {"type": "enum", "values": list(LOT_CLASSES)},
        ("city.curb_edge", "side"): {"type": "enum", "values": list(CURB_SIDES)},
        ("city.street_furniture", "side"): {"type": "enum", "values": list(CURB_SIDES)},
    }
    for name in (
        "soiling_gradient_millionths",
        "base_weathering_millionths",
        "reveal_darkening_millionths",
    ):
        expected_bounds[("city.surface_material", name)] = {
            "type": "int",
            "min": 0,
            "max": MILLIONTHS,
        }
    for (kind, field), expected in expected_bounds.items():
        assert by_kind[kind]["fields"][field] == expected, (kind, field)

    identity_kinds = {
        kind
        for kind, record_type in grammar_types.items()
        if "building_identity" in {field.name for field in dataclasses.fields(record_type)}
    }
    assert {kind for kind, shape in by_kind.items() if "identity_field" in shape} == identity_kinds


def _bake(tmp_path: Path, name: str, document: Path = DOCUMENT) -> tuple[dict[str, Any], bytes]:
    output = tmp_path.joinpath(name)
    report = json.loads(_tess("bake", document, output).stdout)
    return report, output.read_bytes()


def _independent_triangle_digests(container: bytes) -> dict[str, str]:
    """The triangle digest, read from the specification in `triangle-digest.ts`, not its code."""
    assert container[:4] == b"OWD1"
    (length,) = struct.unpack_from("<I", container, 4)
    header = json.loads(container[8 : 8 + length])
    assert canonical_json(header) == container[8 : 8 + length]
    records = header["records"]
    sections = {(s["projection"], s["name"]): s for s in header["sections"]}

    def field(data: bytes) -> bytes:
        return struct.pack(">Q", len(data)) + data

    def ints(section: dict[str, int], code: str) -> tuple[int, ...]:
        count = section["byte_length"] // 4
        return struct.unpack_from(f"<{count}{code}", container, section["byte_offset"])

    digests = {}
    for projection in header["projections"]:
        name = projection["name"]
        origin = projection["origin_mm"]
        offsets = ints(sections[(name, "position_mm")], "i")
        corners = ints(sections[(name, "index")], "I")
        carries_surfaces = (name, "surface_mm") in sections
        surface_offsets = ints(sections[(name, "surface_mm")], "i") if carries_surfaces else ()
        surface_origin = projection.get("surface_origin_mm", [])
        stream = [
            field(b"exulanica/owd-triangle-digest"),
            field(b"1"),
            field(name.encode("ascii")),
            field(struct.pack(">q", len(projection["entries"]))),
        ]
        for entry in projection["entries"]:
            record = records[entry["record"]]
            recomputed = sha256_of_canonical(
                {"kind": record["kind"], "version": record["version"], "fields": record["fields"]}
            ).hex()
            assert recomputed == record["sha256"]
            stream += [
                field(record["kind"].encode("ascii")),
                field(record["sha256"].encode("ascii")),
                field(record["identity"].encode("ascii")),
                field(entry["state"].encode("ascii")),
            ]
            if entry["state"] == "drawn":
                values = []
                surface = []
                first = entry["first_triangle"] * 3
                for corner in corners[first : first + entry["triangle_count"] * 3]:
                    for axis in range(3):
                        values.append(offsets[corner * 3 + axis] + origin[axis])
                    if carries_surfaces:
                        for axis in range(2):
                            surface.append(
                                surface_offsets[corner * 2 + axis] + surface_origin[axis]
                            )
                triangles = field(struct.pack(f">{len(values)}q", *values))
                if not carries_surfaces:
                    stream += [field(b""), field(b""), triangles, field(b"")]
                    continue
                material = entry["material"]
                reference = (
                    material["state"]
                    if material["state"] == "not-carried"
                    else records[material["record"]]["sha256"]
                )
                stream += [
                    field(reference.encode("ascii")),
                    field(entry["surface"].encode("ascii")),
                    triangles,
                    field(struct.pack(f">{len(surface)}q", *surface)),
                ]
            elif entry["state"] == "unavailable":
                stream += [
                    field(b""),
                    field(b""),
                    field(canonical_json(entry["needs"])),
                    field(b""),
                ]
            else:
                stream += [field(b""), field(b""), field(b""), field(b"")]
        digests[name] = hashlib.sha256(b"".join(stream)).hexdigest()
    return digests


def test_two_node_bakes_under_one_key_write_identical_bytes(tmp_path):
    """Gate 4: same key, same bytes, same digests, and a second reading of the digest agrees."""
    spec = stage("baked_tile")
    tile, _ = build_fixture_records()
    key = baked_tile_id(spec, tile)
    first_report, first = _bake(tmp_path, "first.owd")
    second_report, second = _bake(tmp_path, "second.owd")
    assert first == second
    assert first_report == second_report
    assert first_report["container_sha256"] == hashlib.sha256(first).hexdigest()
    assert first_report["byte_size"] == len(first)
    # The key both runs share is the one the registry derives from the tile record they read.
    assert first_report["tile_inputs_digest"] == tile_inputs_digest(tile)
    assert baked_tile_id(spec, tile) == key
    assert _independent_triangle_digests(first) == first_report["triangle_digests"]
    header_length = struct.unpack_from("<I", first, 4)[0]
    header = json.loads(first[8 : 8 + header_length])
    assert header["tile_inputs_digest"] == tile_inputs_digest(tile)
    assert header["truth"] == "invented"
    for projection in header["projections"]:
        entries = projection["entries"]
        drawn = [header["records"][e["record"]]["kind"] for e in entries if e["state"] == "drawn"]
        assert drawn == ["city.terrain"], projection["name"]
    assert [p["name"] for p in header["projections"]] == ["render_batch", "nav_envelope"]
    assert json.loads(_tess("verify", tmp_path.joinpath("first.owd")).stdout) == {
        "tile_inputs_digest": first_report["tile_inputs_digest"],
        "triangle_digests": first_report["triangle_digests"],
    }


def test_a_material_with_its_texture_set_stripped_is_refused(tmp_path):
    """Gate 7: no default texture, and no drawn surface in place of the refusal."""
    document = json.loads(DOCUMENT.read_bytes())
    for record in document["grammars"][0]["records"]:
        if record["kind"] == "city.surface_material":
            del record["fields"]["texture_set_id"]
    stripped = tmp_path.joinpath("stripped.json")
    stripped.write_bytes(canonical_json(document))
    result = _tess("bake", stripped, tmp_path.joinpath("stripped.owd"), check=False)
    assert result.returncode == 1
    assert "missing keys" in result.stderr
    assert "texture_set_id" in result.stderr
    assert not tmp_path.joinpath("stripped.owd").exists()
    with pytest.raises(TypeError):
        SurfaceMaterialRecord(  # type: ignore[call-arg]
            building_identity=FIXTURE_BUILDING,
            edge_ordinal=0,
            material=f"{UNRESOLVED}material",
            uv_scale_millionths=MILLIONTHS,
            uv_rotation_urad=0,
            course_module_mm=0,
            mortar_module_mm=0,
            soiling_gradient_millionths=0,
            base_weathering_millionths=0,
            reveal_darkening_millionths=0,
        )


def test_a_perturbed_record_under_the_same_key_writes_different_bytes(tmp_path):
    """The half of gate 5 that needs no row: the key stays, the bytes move.

    Keeping the stored artifact and emitting the event is unbuilt; see the module docstring.
    """
    document = json.loads(DOCUMENT.read_bytes())
    for record in document["grammars"][0]["records"]:
        if record["kind"] == "city.terrain":
            record["fields"]["height_mm"][5] += 1
    perturbed = tmp_path.joinpath("perturbed.json")
    perturbed.write_bytes(canonical_json(document))
    tile, _ = build_fixture_records()
    report, _ = _bake(tmp_path, "perturbed.owd", perturbed)
    original, _ = _bake(tmp_path, "original.owd")
    assert (
        report["tile_inputs_digest"] == original["tile_inputs_digest"] == tile_inputs_digest(tile)
    )
    assert report["container_sha256"] != original["container_sha256"]
    assert report["triangle_digests"] != original["triangle_digests"]


def test_the_stage_spec_refuses_a_float_parameter_at_construction():
    with pytest.raises(CanonicalisationError):
        StageSpec(
            key="baked_tile",
            version=1,
            output_kind="owd_tile",
            deterministic=True,
            params={"lod": 0.0},
        )


if __name__ == "__main__":
    if sys.argv[1:] != ["--write-fixture"]:
        raise SystemExit("usage: python tests/test_bake_determinism.py --write-fixture")
    DOCUMENT.write_bytes(build_fixture_document())
    print(f"wrote {DOCUMENT.relative_to(ROOT)}")
