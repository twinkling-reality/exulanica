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

#: The record kinds whose stated extent does not cover the ground: a terrain patch is the ground,
#: and a district is a region. Every other kind with an extent covers the ground under it.
NOT_GROUND_COVER = frozenset({"city.terrain", "city.district"})


def fixture_document() -> TileDocument:
    return read_tile_document(DOCUMENT.read_bytes())


def fixture_records() -> list[object]:
    document = fixture_document()
    return [record for grammar in document.grammars for record in grammar.records()]


# -- the registry ---------------------------------------------------------------------------------


def test_the_bake_stage_is_registered_deterministic_with_no_model_role():
    spec = stage("baked_tile")
    assert spec.key == "baked_tile"
    assert spec.version == 2
    assert spec.output_kind == "owd_tile"
    assert spec.deterministic is True
    assert spec.model_role is None
    assert spec.params["container"] == "owd/2"
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
    """The table is ``describe_shapes`` over the city's shapes and the descriptor's frame."""
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
            "shapes": described,
        }
    ]
    assert json.loads(SHAPE_TABLE.read_bytes()) == described


def _bake(tmp_path: Path, name: str, document: Path = DOCUMENT) -> tuple[dict[str, Any], bytes]:
    output = tmp_path.joinpath(name)
    report = json.loads(_tess("bake", document, output).stdout)
    return report, output.read_bytes()


def _header(container: bytes) -> dict[str, Any]:
    assert container[:4] == b"OWD2"
    (length,) = struct.unpack_from("<I", container, 4)
    header = json.loads(container[8 : 8 + length])
    assert canonical_json(header) == container[8 : 8 + length]
    return header


def _ints(container: bytes, section: dict[str, int], code: str) -> tuple[int, ...]:
    count = section["byte_length"] // 4
    return struct.unpack_from(f"<{count}{code}", container, section["byte_offset"])


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
        stream = [
            field(b"exulanica/owd-triangle-digest"),
            field(b"2"),
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
                material = records[entry["material"]["record"]]
                assert material["kind"] == SurfaceMaterialRecord.RECORD_KIND
                stream += [
                    field(material["sha256"].encode("ascii")),
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

    stated = {record.identity: "owned" for record in grammar.owned}  # type: ignore[attr-defined]
    stated |= {record.identity: "halo" for record in grammar.halo}  # type: ignore[attr-defined]
    assert {r["identity"]: r["membership"] for r in header["records"]} == stated

    assert [p["name"] for p in header["projections"]] == ["render_batch", "nav_envelope"]
    for projection in header["projections"]:
        for entry in projection["entries"]:
            record = header["records"][entry["record"]]
            assert (entry["state"] == "halo") == (record["membership"] == "halo")
    render, nav = header["projections"]
    assert [e for e in render["entries"] if e["state"] == "drawn"] == []
    terrain = next(i for i, r in enumerate(header["records"]) if r["kind"] == "city.terrain")
    assert render["entries"][terrain] == {
        "needs": ["surface_material"],
        "record": terrain,
        "state": "unavailable",
    }
    drawn = [
        header["records"][e["record"]]["kind"] for e in nav["entries"] if e["state"] == "drawn"
    ]
    assert drawn == ["city.terrain"]


def test_the_tessellator_leaves_out_exactly_the_covered_terrain_cells(tmp_path):
    """A second reading of the one tessellation rule this version adds, from the records."""
    _, container = _bake(tmp_path, "fixture.owd")
    header = _header(container)
    records = fixture_records()
    cover = []
    for record in records:
        shape = CITY_SHAPES_BY_TYPE[type(record)]
        if shape.extent_field and shape.kind not in NOT_GROUND_COVER:
            extent = getattr(record, shape.extent_field)
            cover.append((extent.min_x_mm, extent.min_y_mm, extent.max_x_mm, extent.max_y_mm))
    terrain = next(r for r in records if CITY_SHAPES_BY_TYPE[type(r)].kind == "city.terrain")
    cell = terrain.cell_mm  # type: ignore[attr-defined]
    side = terrain.samples_per_side  # type: ignore[attr-defined]
    origin_x = terrain.tile_x * TILE_SIZE_MM  # type: ignore[attr-defined]
    origin_y = terrain.tile_y * TILE_SIZE_MM  # type: ignore[attr-defined]

    def covered(west: int, south: int) -> bool:
        return any(
            west <= max_x and min_x <= west + cell and south <= max_y and min_y <= south + cell
            for min_x, min_y, max_x, max_y in cover
        )

    expected = {
        (origin_x + column * cell, origin_y + row * cell)
        for row in range(side - 1)
        for column in range(side - 1)
        if not covered(origin_x + column * cell, origin_y + row * cell)
    }
    assert 0 < len(expected) < (side - 1) ** 2

    nav = header["projections"][1]
    sections = {(s["projection"], s["name"]): s for s in header["sections"]}
    offsets = _ints(container, sections[("nav_envelope", "position_mm")], "i")
    corners = _ints(container, sections[("nav_envelope", "index")], "I")
    drawn = set()
    for triangle in range(nav["triangle_count"]):
        points = [
            [offsets[corners[triangle * 3 + c] * 3 + a] + nav["origin_mm"][a] for a in range(3)]
            for c in range(3)
        ]
        drawn.add((min(p[0] for p in points), min(p[1] for p in points)))
        for x, y, z in points:
            sample = ((y - origin_y) // cell) * side + (x - origin_x) // cell
            assert z == terrain.height_mm[sample]  # type: ignore[attr-defined]
    assert drawn == expected
    assert nav["triangle_count"] == 2 * len(expected)


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
