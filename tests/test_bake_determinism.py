"""The tile bake: a deterministic stage whose output is the Node tessellator's bytes.

What this file holds the ``baked_tile`` stage to.

*   The stage declares itself deterministic, names no model role, refuses any run-time binding,
    and refuses a float in its parameters.
*   Its key is ``scene_group``'s shape with the tile's own key last, the tile key covers the
    ordered edit subsequence from the first bake, the empty subsequence has one encoding, and a
    nonempty one moves the key.
*   The parameters the registry states are the parameters the tessellator states, byte for byte,
    and the grammar table the tessellator reads is the grammar's own ``describe_shapes`` and the
    descriptor's frame.
*   Two Node bakes of the conformance fixture under one key write byte-identical containers, and
    a second, independent reading of the triangle digest specification in Python agrees with the
    tessellator's, as does a second reading of which terrain cells the tessellator leaves out.
*   A material record with its texture set stripped is refused, not defaulted.

**What is not here, and why.** The brief's fifth assertion, that a perturbed rebake under a fixed
key emits ``nondeterminism_detected`` and keeps the stored artifact, needs a row to keep. There is
none a tile can honestly have: ``artifact`` requires a source blob, a tile has none, and filing
tile bytes in ``derived_artifact`` would mix planes. The orchestrator decided on 2026-09-16 that
the baked-tile table and its fault path arrive with the corridor lane's migration 0072, keyed by
``baked_tile_id``. Until then that assertion is unbuilt, and this file does not pretend otherwise.

**The fixture.** ``web/packages/loom-tess/test/fixtures/tile-conformance.json`` is a byte copy of
the city grammar's hand-written version 2 tile, ``tests/fixtures/city-v2/tile-document.json``, and
the test holds the copy to its source. The grammar's own document validator admits it. When the
source moves, copy it again and update the golden digests in the same commit.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import shutil
import struct
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.errors import CanonicalisationError
from exulanica.evidence.blob import BlobId
from exulanica.grammar.contract import ADMISSIBLE_USES, PLANE
from exulanica.grammar.grammars.city import CITY_SHAPES, CITY_SHAPES_BY_TYPE
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
from exulanica.grammar.grammars.city.descriptor import CITY_DESCRIPTOR_PATH
from exulanica.grammar.grammars.city.document import (
    TILE_DOCUMENT_PROFILE,
    TileDocument,
    read_tile_document,
    validate_city_document,
)
from exulanica.grammar.grammars.city.material import SurfaceMaterialRecord
from exulanica.grammar.grammars.city.tile import (
    EMPTY_EDIT_DELTA_DIGEST,
    HALO_RADIUS_MM,
    TILE_SIZE_MM,
    tile_inputs_digest,
)
from exulanica.grammar.records import KEY_PATTERN, canonical_record, record_payload
from exulanica.grammar.shapes import describe_shapes
from exulanica.grammar.textures import TEXTURE_SET_ID
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
DOCUMENT = PACKAGE.joinpath("test", "fixtures", "tile-conformance.json")
SOURCE_DOCUMENT = ROOT.joinpath("tests", "fixtures", "city-v2", "tile-document.json")
SHAPE_TABLE = ROOT.joinpath("tests", "fixtures", "city-v2", "record-shapes.json")
CLI = PACKAGE.joinpath("src", "node", "cli.ts")
TSX = WEB.joinpath("node_modules", ".bin", "tsx")

#: The record kinds the city's navigation table says obstruct a capsule with their low parts.
LOW_PART_KINDS = frozenset({"city.street_furniture", "city.street_tree"})


def _low_part_rings(record: Any, height_mm: int) -> list[list[tuple[float, float]]]:
    """Each part of a record that stands below the capsule height, as a plan ring inside it.

    A millimetre inside what the record states, and read from the record rather than from the
    tessellator. A ``box`` spans its sizes, so its ring is that rectangle; a ``prism`` and an
    ``ellipsoid`` are inscribed in the size ellipse, and every count the grammar allows holds at
    least the rectangle of half those sizes, since at the smallest, four segments, that rectangle's
    corners lie on the diamond itself. So the ring is inside the part either way, and a point within
    the capsule radius of the ring is within it of the part.
    """
    facing_x = getattr(record, "facing_dx_mm", None)
    facing_y = getattr(record, "facing_dy_mm", None)
    if facing_x is None:
        facing_x, facing_y = 1, 0
    length = math.hypot(facing_x, facing_y)
    along = (facing_x / length, facing_y / length)
    left = (-along[1], along[0])
    rings = []
    for part in record.parts:
        if part.offset_z_mm >= height_mm:
            continue
        span = 2 if part.shape == "box" else 4
        half_x = max(part.size_x_mm / span - 1, 0)
        half_y = max(part.size_y_mm / span - 1, 0)
        rings.append(
            [
                (
                    record.x_mm
                    + (part.offset_x_mm + sx * half_x) * along[0]
                    + (part.offset_y_mm + sy * half_y) * left[0],
                    record.y_mm
                    + (part.offset_x_mm + sx * half_x) * along[1]
                    + (part.offset_y_mm + sy * half_y) * left[1],
                )
                for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
            ]
        )
    return rings


def _ring_gap_squared(ring: list[tuple[float, float]], x: int, y: int) -> float:
    """The squared distance from a plan point to a closed ring, zero inside it."""
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside
    if inside:
        return 0
    best = None
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1], strict=True):
        dx, dy = bx - ax, by - ay
        along = ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)
        along = min(max(along, 0), 1)
        gap = (x - ax - along * dx) ** 2 + (y - ay - along * dy) ** 2
        best = gap if best is None else min(best, gap)
    return best


def fixture_document() -> TileDocument:
    return read_tile_document(DOCUMENT.read_bytes())


def fixture_records() -> list[object]:
    document = fixture_document()
    return [record for grammar in document.grammars for record in grammar.records()]


def fixture_terrain() -> Any:
    return next(r for r in fixture_records() if CITY_SHAPES_BY_TYPE[type(r)].kind == "city.terrain")


# -- the registry ---------------------------------------------------------------------------------


def test_the_bake_stage_is_registered_deterministic_with_no_model_role():
    spec = stage("baked_tile")
    assert spec.key == "baked_tile"
    assert spec.version == 3
    assert spec.output_kind == "owd_tile"
    assert spec.deterministic is True
    assert spec.model_role is None
    assert spec.params["container"] == "owd/3"
    assert spec.params["tile_document"] == TILE_DOCUMENT_PROFILE
    assert spec.params["tile_size_mm"] == TILE_SIZE_MM
    assert spec.params["halo_radius_mm"] == HALO_RADIUS_MM
    assert spec.params["record_shapes"] == baked_tile_record_shapes()
    assert spec.params["record_shapes"] == {shape.kind: shape.version for shape in CITY_SHAPES}


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
    document = fixture_document()
    probed = 0
    for record in [document.tile, *fixture_records()]:
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
    assert probed > 1000


# -- the key --------------------------------------------------------------------------------------


def test_the_empty_edit_subsequence_has_one_encoding():
    assert edit_delta_digest_of([]) == hashlib.sha256(b"[]").hexdigest() == EMPTY_EDIT_DELTA_DIGEST
    assert fixture_document().tile.edit_delta_digest == edit_delta_digest_of([])


def test_a_nonempty_edit_subsequence_moves_the_key():
    """Gate 14, before any cache exists: an edit that targets the tile changes its key."""
    spec = stage("baked_tile")
    tile = fixture_document().tile
    first = hashlib.sha256(b"an edit").digest()
    second = hashlib.sha256(b"another edit").digest()
    keys = {
        baked_tile_id(spec, tile),
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
    tile = fixture_document().tile
    inputs = tile_inputs_digest(tile)
    assert baked_tile_id(spec, tile) == uuid.uuid5(
        ARTIFACT_NAMESPACE, f"baked_tile:{spec.version}:{spec.params_digest.hex()}:{inputs}"
    )
    moved = dataclasses.replace(spec, params={**spec.params, "lod": 1})
    assert baked_tile_id(moved, tile) != baked_tile_id(spec, tile)
    pin = tile.grammar_versions[0]
    repinned = dataclasses.replace(
        tile,
        grammar_versions=(dataclasses.replace(pin, descriptor_sha256="0" * 64),),
    )
    assert baked_tile_id(spec, repinned) != baked_tile_id(spec, tile), (
        "a descriptor pin reuses keys"
    )
    with pytest.raises(ValueError, match="not the tile bake"):
        baked_tile_id(STAGES["scene_group"], tile)
    with pytest.raises(ValueError):
        edit_delta_digest_of([b"short"])


# -- the fixture ----------------------------------------------------------------------------------


def test_the_committed_fixture_is_the_city_grammars_own_tile():
    assert DOCUMENT.read_bytes() == SOURCE_DOCUMENT.read_bytes(), (
        "the conformance fixture is not the city v2 fixture tile; copy "
        "tests/fixtures/city-v2/tile-document.json over it, then update the golden digests in "
        "web/packages/loom-tess/test/triangle-digest-conformance.test.ts"
    )


def test_the_fixture_passes_the_grammars_own_document_validator():
    document = fixture_document()
    report = validate_city_document(document, catalogs=load_city_catalogs())
    assert report.materials == report.materials_with_texture_set > 0
    materials = [r for r in fixture_records() if isinstance(r, SurfaceMaterialRecord)]
    assert materials and all(TEXTURE_SET_ID.fullmatch(m.texture_set_id) for m in materials)


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


def test_the_tessellator_reads_the_grammars_own_table():
    """The table is ``describe_shapes`` over the city's shapes and the descriptor's frame, contract
    measures, per-projection resolutions and navigation table, each row without its prose reason."""
    from exulanica.grammar.records import _HEX64, _IDENTITY

    printed = json.loads(_tess("shapes").stdout)
    assert printed["plane"] == PLANE
    assert printed["projections"] == list(ADMISSIBLE_USES)
    assert printed["patterns"] == {
        "key": "^" + KEY_PATTERN.pattern + "$",
        "identity": "^" + _IDENTITY.pattern + "$",
        "hex64": "^" + _HEX64.pattern + "$",
        "texture_set_id": "^" + TEXTURE_SET_ID.pattern + "$",
    }
    assert printed["material_record_kind"] == SurfaceMaterialRecord.RECORD_KIND
    assert printed["tile_record_kind"] == "city.tile"
    descriptor = json.loads(CITY_DESCRIPTOR_PATH.read_bytes())
    described = json.loads(json.dumps(describe_shapes(CITY_SHAPES)))
    assert printed["grammars"] == [
        {
            "grammar_id": descriptor["grammar_id"],
            "grammar_version": descriptor["grammar_version"],
            "frame": descriptor["frame"],
            "measures": descriptor_measures(),
            # Every projection states a resolution, which a rule that cuts an arc into chords reads
            # rather than choosing a segment count of its own.
            "resolutions": {
                projection["projection"]: projection["resolution_mm"]
                for projection in descriptor["projections"]
            },
            "navigation": [
                {key: row[key] for key in ("kind", "ground", "cover", "obstruction")}
                for row in descriptor["navigation"]
            ],
            "shapes": described,
        }
    ]
    assert json.loads(SHAPE_TABLE.read_bytes()) == described


def _bake(tmp_path: Path, name: str, document: Path = DOCUMENT) -> tuple[dict[str, Any], bytes]:
    output = tmp_path.joinpath(name)
    report = json.loads(_tess("bake", document, output).stdout)
    return report, output.read_bytes()


def _header(container: bytes) -> dict[str, Any]:
    assert container[:4] == b"OWD3"
    (length,) = struct.unpack_from("<I", container, 4)
    header = json.loads(container[8 : 8 + length])
    assert canonical_json(header) == container[8 : 8 + length]
    return header


def _ints(container: bytes, section: dict[str, int], code: str) -> tuple[int, ...]:
    count = section["byte_length"] // 4
    return struct.unpack_from(f"<{count}{code}", container, section["byte_offset"])


def _deindexed(
    mesh: dict[str, Any], first_triangle: int, triangle_count: int, carries_surfaces: bool
) -> tuple[list[int], list[int]]:
    """A range's triangles de-indexed to absolute millimetres, and its surface coordinates."""
    values: list[int] = []
    surface: list[int] = []
    first = first_triangle * 3
    for corner in mesh["corners"][first : first + triangle_count * 3]:
        for axis in range(3):
            values.append(mesh["offsets"][corner * 3 + axis] + mesh["origin"][axis])
        if carries_surfaces:
            for axis in range(2):
                surface.append(
                    mesh["surface_offsets"][corner * 2 + axis] + mesh["surface_origin"][axis]
                )
    return values, surface


def _framed_range(
    mesh: dict[str, Any], carries_surfaces: bool, first_triangle: int, triangle_count: int
) -> tuple[bytes, bytes]:
    """A range's triangles and surface coordinates, each framed as the digest frames a field."""
    values, surface = _deindexed(mesh, first_triangle, triangle_count, carries_surfaces)
    return (
        struct.pack(">Q", len(values) * 8) + struct.pack(f">{len(values)}q", *values),
        struct.pack(">Q", len(surface) * 8) + struct.pack(f">{len(surface)}q", *surface),
    )


def _independent_triangle_digests(container: bytes) -> dict[str, str]:
    """The triangle digest, read from the specification in `triangle-digest.ts`, not its code."""
    header = _header(container)
    records = header["records"]
    sections = {(s["projection"], s["name"]): s for s in header["sections"]}

    def field(data: bytes) -> bytes:
        return struct.pack(">Q", len(data)) + data

    digests = {}
    for projection in header["projections"]:
        name = projection["name"]
        origin = projection["origin_mm"]
        offsets = _ints(container, sections[(name, "position_mm")], "i")
        corners = _ints(container, sections[(name, "index")], "I")
        carries_surfaces = (name, "surface_mm") in sections
        surface_offsets = (
            _ints(container, sections[(name, "surface_mm")], "i") if carries_surfaces else ()
        )
        surface_origin = projection.get("surface_origin_mm", [])
        mesh = {
            "corners": corners,
            "offsets": offsets,
            "origin": origin,
            "surface_offsets": surface_offsets,
            "surface_origin": surface_origin,
        }
        stream = [
            field(b"exulanica/owd-triangle-digest"),
            field(b"3"),
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
                if not carries_surfaces:
                    triangles, _ = _framed_range(
                        mesh, carries_surfaces, entry["first_triangle"], entry["triangle_count"]
                    )
                    stream += [field(b""), field(b""), triangles, field(b"")]
                    continue
                stream.append(field(struct.pack(">q", len(entry["surfaces"]))))
                for surface in entry["surfaces"]:
                    if surface["material"] == {"state": "none-exists"}:
                        reference = "none-exists"
                    else:
                        material = records[surface["material"]["record"]]
                        assert material["kind"] == SurfaceMaterialRecord.RECORD_KIND
                        assert material["fields"]["surface_identity"] == record["identity"]
                        assert material["fields"]["role"] == surface["role"]
                        reference = material["sha256"]
                    triangles, coordinates = _framed_range(
                        mesh, carries_surfaces, surface["first_triangle"], surface["triangle_count"]
                    )
                    stream += [
                        field(surface["role"].encode("ascii")),
                        field(reference.encode("ascii")),
                        field(surface["orientation"].encode("ascii")),
                        triangles,
                        coordinates,
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
    document = fixture_document()
    key = baked_tile_id(spec, document.tile)
    first_report, first = _bake(tmp_path, "first.owd")
    second_report, second = _bake(tmp_path, "second.owd")
    assert first == second
    assert first_report == second_report
    assert first_report["container_sha256"] == hashlib.sha256(first).hexdigest()
    assert first_report["byte_size"] == len(first)
    # The key both runs share is the one the registry derives from the tile record they read.
    assert first_report["tile_inputs_digest"] == tile_inputs_digest(document.tile)
    assert baked_tile_id(spec, document.tile) == key
    assert _independent_triangle_digests(first) == first_report["triangle_digests"]
    assert json.loads(_tess("verify", tmp_path.joinpath("first.owd")).stdout) == {
        "tile_inputs_digest": first_report["tile_inputs_digest"],
        "triangle_digests": first_report["triangle_digests"],
    }


def test_the_container_states_membership_frame_identity_and_what_is_drawn(tmp_path):
    _, container = _bake(tmp_path, "fixture.owd")
    header = _header(container)
    document = fixture_document()
    grammar = document.grammars[0]
    descriptor = json.loads(CITY_DESCRIPTOR_PATH.read_bytes())
    assert header["truth"] == "invented"
    assert header["tile_inputs_digest"] == tile_inputs_digest(document.tile)
    assert [g["frame"] for g in header["grammars"]] == [descriptor["frame"]]
    assert [g["subject_identity"] for g in header["grammars"]] == [grammar.subject_identity]
    assert [g["external"] for g in header["grammars"]] == [
        [{"identity": identity, "kind": kind} for identity, kind in grammar.external]
    ]

    stated = {record.identity: "owned" for record in grammar.owned}  # type: ignore[attr-defined]
    stated |= {record.identity: "halo" for record in grammar.halo}  # type: ignore[attr-defined]
    assert {r["identity"]: r["membership"] for r in header["records"]} == stated

    assert [p["name"] for p in header["projections"]] == ["render_batch", "nav_envelope"]
    for projection in header["projections"]:
        for entry in projection["entries"]:
            record = header["records"][entry["record"]]
            assert (entry["state"] == "halo") == (record["membership"] == "halo")
    render, nav = header["projections"]
    terrain = next(i for i, r in enumerate(header["records"]) if r["kind"] == "city.terrain")
    # Terrain is undressed but exact, and says that no material record dresses it. It is drawn less
    # the carriageways and gutters the segments draw and less the ground the building stands on, so
    # it has more triangles than the grid's cells; the drawn entries are the building, the three
    # segments and the terrain.
    segments = [i for i, r in enumerate(header["records"]) if r["kind"] == "city.street_segment"]
    massings = [i for i, r in enumerate(header["records"]) if r["kind"] == "city.massing"]
    facades = [i for i, r in enumerate(header["records"]) if r["kind"] == "city.facade"]
    # Every kind whose parts this version turns into solids draws too, each its own object, and
    # every kind that states a ring of ground draws that ground.
    objects = [
        i
        for i, r in enumerate(header["records"])
        if r["kind"] in ("city.rooftop_object", "city.street_furniture", "city.vitrine")
    ]
    lots = [
        i
        for i, r in enumerate(header["records"])
        if r["kind"] in ("city.block", "city.parcel", "city.street_tree")
    ]
    curbs = [i for i, r in enumerate(header["records"]) if r["kind"] == "city.curb_edge"]
    junctions = [i for i, r in enumerate(header["records"]) if r["kind"] == "city.junction"]
    assert [e["record"] for e in render["entries"] if e["state"] == "drawn"] == sorted(
        [*curbs, *facades, *junctions, *lots, *massings, *objects, *segments, terrain]
    )
    # A curb is its kerb face, its kerb top and the footway behind it.
    for entry in (render["entries"][i] for i in curbs):
        assert [(s["role"], s["orientation"]) for s in entry["surfaces"]] == [
            ("kerb", "vertical"),
            ("kerb", "horizontal"),
            ("footway", "horizontal"),
        ]
    for entry in (render["entries"][i] for i in objects):
        assert {s["role"] for s in entry["surfaces"]} <= {
            "object_primary",
            "object_secondary",
            "object_tertiary",
        }
    # A block gives up the ground its parcels take, so what it draws is what they leave.
    for index in lots:
        roles = {s["role"] for s in render["entries"][index]["surfaces"]}
        if header["records"][index]["kind"] == "city.street_tree":
            assert roles == {"tree_pit", "trunk", "canopy"}
            continue
        assert roles == {"lot"}
    # A face draws the wall of its run and the ground band below it, and the panels of every bay
    # that names it, so a ground bay draws nothing of its own.
    for entry in (render["entries"][i] for i in facades):
        roles = {s["role"] for s in entry["surfaces"]}
        assert roles <= {
            "wall",
            "ground_band",
            "party_wall_scar",
            "stall_riser",
            "glazing",
            "fascia",
            "door",
            "shopfront_frame",
        }
    for index, record in enumerate(header["records"]):
        if record["kind"] == "city.ground_bay":
            assert render["entries"][index]["state"] == "not_in_projection"
    for entry in (render["entries"][i] for i in massings):
        assert [(s["role"], s["orientation"]) for s in entry["surfaces"]] == [
            ("wall", "vertical"),
            ("roof", "horizontal"),
            ("parapet", "vertical"),
        ]
    [surface] = render["entries"][terrain]["surfaces"]
    assert (surface["role"], surface["orientation"]) == ("terrain", "horizontal")
    assert surface["material"] == {"state": "none-exists"}
    assert (
        render["entries"][terrain]["triangle_count"]
        > 2 * (fixture_terrain().samples_per_side - 1) ** 2
    )
    for entry in (render["entries"][i] for i in segments):
        roles = [(s["role"], s["orientation"], s["material"]["state"]) for s in entry["surfaces"]]
        assert roles == [
            ("carriageway", "horizontal", "record"),
            ("gutter", "horizontal", "record"),
        ]
    # Navigation draws what a person stands on: the same ground, the kerb tops and footways of the
    # curbs and the segments' own surfaces, each carved clear of what the grammar's navigation table
    # says obstructs a walking capsule.
    drawn = [
        header["records"][e["record"]]["kind"] for e in nav["entries"] if e["state"] == "drawn"
    ]
    assert drawn == (
        ["city.curb_edge"] * len(curbs)
        + ["city.junction"] * len(junctions)
        + ["city.street_segment"] * len(segments)
        + ["city.terrain"]
    )


def descriptor_measures() -> dict[str, dict[str, dict[str, int]]]:
    """Every integer measure the city descriptor's projection contracts state, by projection."""
    descriptor = json.loads(CITY_DESCRIPTOR_PATH.read_bytes())
    measures: dict[str, dict[str, dict[str, int]]] = {}
    for projection in descriptor["projections"]:
        for row in projection["preserved"]:
            if "measures" in row:
                measures.setdefault(projection["projection"], {})[row["property"]] = row["measures"]
    return measures


def capsule_radius_mm() -> int:
    return descriptor_measures()["nav_envelope"]["capsule_clearance"]["radius_mm"]


def capsule_height_mm() -> int:
    return descriptor_measures()["nav_envelope"]["capsule_clearance"]["height_mm"]


def test_the_tessellator_carves_support_clear_of_everything_that_obstructs(tmp_path):
    """A second reading of the support rule this version carves, from the records themselves."""
    _, container = _bake(tmp_path, "fixture.owd")
    header = _header(container)
    radius = capsule_radius_mm()
    height = capsule_height_mm()
    assert radius > 0
    assert height > 0
    obstructions = []
    for record in fixture_records():
        kind = CITY_SHAPES_BY_TYPE[type(record)].kind
        if kind == "city.massing":
            obstructions.append([tuple(point) for point in record.tiers[0].ring_mm])
            continue
        if kind not in LOW_PART_KINDS:
            continue
        obstructions.extend(_low_part_rings(record, height))
    # One building and the fifteen parts of eight objects that stand below head height. What stands
    # above it takes no ground: the tree's six metre canopy is not here, and nothing is wider than
    # the two metre bench, which is the whole of the difference from reading a stated extent.
    assert len(obstructions) == 16
    assert max(max(p[0] for p in ring) - min(p[0] for p in ring) for ring in obstructions[1:]) < 2000

    terrain = fixture_terrain()
    cell = terrain.cell_mm
    side = terrain.samples_per_side
    origin_x = terrain.tile_x * TILE_SIZE_MM
    origin_y = terrain.tile_y * TILE_SIZE_MM
    nav = header["projections"][1]
    sections = {(s["projection"], s["name"]): s for s in header["sections"]}
    offsets = _ints(container, sections[("nav_envelope", "position_mm")], "i")
    corners = _ints(container, sections[("nav_envelope", "index")], "I")
    triangles = [
        [
            [offsets[corners[triangle * 3 + c] * 3 + a] + nav["origin_mm"][a] for a in range(3)]
            for c in range(3)
        ]
        for triangle in range(nav["triangle_count"])
    ]

    # Every corner is on the surface it was carved from: a sample where it is one, and between its
    # cell's four samples otherwise, since the height is that cell's own plane, floored.
    terrain_entry = next(
        e
        for e in nav["entries"]
        if e["state"] == "drawn" and header["records"][e["record"]]["kind"] == "city.terrain"
    )
    low = terrain_entry["first_vertex"]
    at_samples = 0
    for vertex in range(low, low + terrain_entry["vertex_count"]):
        x, y, z = (offsets[vertex * 3 + a] + nav["origin_mm"][a] for a in range(3))
        column, row = (x - origin_x) // cell, (y - origin_y) // cell
        if (x - origin_x) % cell == 0 and (y - origin_y) % cell == 0:
            assert z == terrain.height_mm[row * side + column]
            at_samples += 1
            continue
        column = min(max(column, 0), side - 2)
        row = min(max(row, 0), side - 2)
        heights = [
            terrain.height_mm[(row + up) * side + column + east] for up in (0, 1) for east in (0, 1)
        ]
        assert min(heights) - 1 <= z <= max(heights) + 1
    assert at_samples > 0

    # Nothing within the capsule radius of an obstruction is supported, over a lattice of the tile,
    # and what is beyond that radius mostly is: the carve takes the clearance and not the ground.
    buckets: dict[tuple[int, int], list[int]] = {}
    for index, points in enumerate(triangles):
        for bx in range(min(p[0] for p in points) // cell, max(p[0] for p in points) // cell + 1):
            for by in range(
                min(p[1] for p in points) // cell, max(p[1] for p in points) // cell + 1
            ):
                buckets.setdefault((bx, by), []).append(index)

    def supported(x: int, y: int) -> bool:
        for index in buckets.get((x // cell, y // cell), ()):
            a, b, c = triangles[index]
            sides = [
                (q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0])
                for p, q in ((a, b), (b, c), (c, a))
            ]
            if all(side >= 0 for side in sides) or all(side <= 0 for side in sides):
                return True
        return False

    within, beyond, kept = 0, 0, 0
    step = 1000
    for y in range(origin_y, origin_y + TILE_SIZE_MM + 1, step):
        for x in range(origin_x, origin_x + TILE_SIZE_MM + 1, step):
            gaps = [_ring_gap_squared(ring, x, y) for ring in obstructions]
            if min(gaps) < radius**2:
                within += 1
                assert not supported(x, y), f"({x}, {y}) is within the radius of an obstruction"
                continue
            if min(gaps) > (radius + 10) ** 2:
                beyond += 1
                kept += 1 if supported(x, y) else 0
    assert within > 0
    assert kept > beyond // 2


def test_a_material_with_its_texture_set_stripped_is_refused(tmp_path):
    """Gate 7: no default texture, and no drawn surface in place of the refusal."""
    document = json.loads(DOCUMENT.read_bytes())
    stripped_any = False
    for record in document["grammars"][0]["owned"]:
        if record["kind"] == "city.surface_material":
            del record["fields"]["texture_set_id"]
            stripped_any = True
    assert stripped_any
    stripped = tmp_path.joinpath("stripped.json")
    stripped.write_bytes(canonical_json(document))
    result = _tess("bake", stripped, tmp_path.joinpath("stripped.owd"), check=False)
    assert result.returncode == 1
    assert "missing keys" in result.stderr
    assert "texture_set_id" in result.stderr
    assert not tmp_path.joinpath("stripped.owd").exists()
    material = next(r for r in fixture_records() if isinstance(r, SurfaceMaterialRecord))
    fields = {f.name: getattr(material, f.name) for f in dataclasses.fields(material)}
    del fields["texture_set_id"]
    with pytest.raises(TypeError):
        SurfaceMaterialRecord(**fields)


def test_a_perturbed_record_under_the_same_key_writes_different_bytes(tmp_path):
    """The half of gate 5 that needs no row: the key stays, the bytes move.

    Keeping the stored artifact and emitting the event is unbuilt; see the module docstring.
    """
    document = json.loads(DOCUMENT.read_bytes())
    parcel = next(r for r in document["grammars"][0]["owned"] if r["kind"] == "city.parcel")
    parcel["fields"]["address_number"] += 1
    perturbed = tmp_path.joinpath("perturbed.json")
    perturbed.write_bytes(canonical_json(document))
    tile = fixture_document().tile
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
            version=2,
            output_kind="owd_tile",
            deterministic=True,
            params={"lod": 0.0},
        )


# -- building blocks not yet wired into the bake ---------------------------------------------------


def test_the_fillet_centre_is_the_grammars_corner_rule(tmp_path):
    """Tess's `cornerCentre` gives exactly what `document._corner_centre` gives, which the
    `[corner_radius]` check holds every corner to, so the check and the geometry are one rule.

    The cases are both tangent points of every carried fixture corner with a radius, walked round
    the face as the grammar walks it (a right curb last to first), and generated corners whose
    products outgrow a double.
    """
    import random

    from exulanica.grammar.grammars.city.document import _corner_centre, _walk_round_face
    from exulanica.grammar.grammars.city.streets import CurbEdgeRecord

    if not TSX.exists():
        pytest.skip(
            f"the web toolchain is not installed ({TSX} is missing); run pnpm install in web/"
        )
    records = {record.identity: record for record in fixture_records()}  # type: ignore[attr-defined]
    cases = []
    for curb in records.values():
        if not isinstance(curb, CurbEdgeRecord) or curb.corner_radius_mm == 0:
            continue
        for identity in curb.next_curb_identity:
            follower = records.get(identity)
            if follower is None:
                continue
            before, after = _walk_round_face(curb), _walk_round_face(follower)
            p, q = before[-1], after[0]
            leaving = (p[0] - before[-2][0], p[1] - before[-2][1])
            joining = (after[1][0] - q[0], after[1][1] - q[1])
            cross = leaving[0] * joining[1] - leaving[1] * joining[0]
            turn = 1 if cross > 0 else -1
            cases += [
                (p, leaving, curb.corner_radius_mm, turn),
                (q, joining, curb.corner_radius_mm, turn),
            ]
    assert len(cases) >= 4, "the fixture carries no corner with a radius to compare"
    assert {record.side for record in records.values() if isinstance(record, CurbEdgeRecord)} == {
        "left",
        "right",
    }
    generator = random.Random(20260917)
    for _ in range(200):
        direction = (
            generator.randint(-2_000_000, 2_000_000),
            generator.randint(-2_000_000, 2_000_000),
        )
        if direction == (0, 0):
            continue
        point = (generator.randint(-(10**9), 10**9), generator.randint(-(10**9), 10**9))
        cases.append((point, direction, generator.randint(1, 50_000), generator.choice((1, -1))))
    expected = [
        list(_corner_centre(point, direction, radius, turn))
        for point, direction, radius, turn in cases
    ]

    inputs = tmp_path.joinpath("corners.json")
    inputs.write_text(json.dumps([[list(p), list(d), r, t] for p, d, r, t in cases]))
    script = tmp_path.joinpath("corners.ts")
    module = PACKAGE.joinpath("src", "core", "fillet-arc.ts")
    script.write_text(
        f"import {{ readFileSync }} from 'node:fs';\n"
        f"import {{ cornerCentre }} from {json.dumps(str(module))};\n"
        f"const cases = JSON.parse(readFileSync({json.dumps(str(inputs))}, 'utf8'));\n"
        "const centres = cases.map(([p, d, r, t]) => cornerCentre(p, d, r, t, 'parity'));\n"
        "process.stdout.write(JSON.stringify(centres));\n"
    )
    result = subprocess.run(
        [str(TSX), str(script)], cwd=WEB, capture_output=True, text=True, check=True, timeout=300
    )
    assert json.loads(result.stdout) == expected
