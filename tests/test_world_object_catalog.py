"""The world object catalog: what it refuses, the digests it pins, and the containers it makes."""

from __future__ import annotations

import copy
import json
import math
import pathlib
import re
import struct
import zlib
from collections.abc import Callable
from typing import Any, Final

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.world.assets import (
    CC0_LICENCE_TEXT,
    CC0_TEXTURED_LICENCE_TEXT,
    reviewed_assets,
)
from exulanica.world.object_catalog import (
    CATALOG_DIRECTORY,
    CATALOG_VERSION,
    MarkerRecipe,
    PartsRecipe,
    load_world_object_catalog,
    world_object_catalog,
)
from exulanica.world.object_glb import stored_png
from exulanica.world.object_meshes import form_triangles
from exulanica.world.texture_assets import decode_texture_set, load_texture_catalog

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "exulanica" / "migrations"
_CATALOG_FILE = CATALOG_DIRECTORY / f"world-object.v{CATALOG_VERSION}.json"
_ROW = re.compile(
    r"\('(?P<key>[a-z][a-z0-9.-]*)','(?P<title>(?:[^']|'')*)',\s*"
    r"'(?P<summary>(?:[^']|'')*)',\s*'model/gltf-binary',\s*"
    r"'(?P<sha>[0-9a-f]{64})',(?P<size>[0-9]+),'CC0-1.0',\s*"
    r"'(?P<licence>[0-9a-f]{64})'(?:,'(?P<kind>[a-z]+)')?\)"
)


def _pinned_rows(migration: str) -> dict[str, dict[str, str]]:
    (path,) = _MIGRATIONS.glob(f"{migration}_*.sql")
    return {match["key"]: match.groupdict() for match in _ROW.finditer(path.read_text())}


def _markers() -> set[str]:
    return {
        kind.asset_key
        for kind in world_object_catalog().kinds
        if isinstance(kind.recipe, MarkerRecipe)
    }


# -- the pins ----------------------------------------------------------------------------------


def test_migration_0105_pins_every_kind_0042_does_not_and_nothing_else():
    """If this fails, a migration describes bytes this code no longer produces."""
    pinned = _pinned_rows("0105")
    generated = {asset.asset_key: asset for asset in reviewed_assets()}
    assert set(pinned) == set(generated) - _markers()
    assert set(_pinned_rows("0042")) == _markers()
    for key, row in pinned.items():
        asset = generated[key]
        assert (row["sha"], int(row["size"])) == (asset.content_sha256, asset.byte_size), key
        assert row["licence"] == asset.licence_sha256
        assert row["kind"] == "object"


def test_each_row_names_the_catalog_title_and_summary():
    rows = {**_pinned_rows("0042"), **_pinned_rows("0105")}
    for kind in world_object_catalog().kinds:
        row = rows[kind.asset_key]
        assert row["title"].replace("''", "'") == kind.title
        assert row["summary"].replace("''", "'") == kind.summary


def test_the_markers_keep_their_licence_and_every_other_kind_names_its_maps():
    for asset in reviewed_assets():
        expected = CC0_LICENCE_TEXT if asset.asset_key in _markers() else CC0_TEXTURED_LICENCE_TEXT
        assert asset.licence_bytes == expected.encode("utf-8")
    assert "texture maps" in CC0_TEXTURED_LICENCE_TEXT


def test_the_reviewed_catalog_is_the_object_catalog_in_its_order():
    assert [asset.asset_key for asset in reviewed_assets()] == [
        kind.asset_key for kind in world_object_catalog().kinds
    ]


# -- what the loader refuses -------------------------------------------------------------------


def _document() -> dict[str, Any]:
    return json.loads(_CATALOG_FILE.read_text())


def _entry(document: dict[str, Any], key: str) -> dict[str, Any]:
    return next(entry for entry in document["entries"] if entry["key"] == key)


def _load(tmp_path: pathlib.Path, document: dict[str, Any]):
    """Load ``document`` as the current version, beside a copy of every earlier published one."""
    for earlier in range(1, CATALOG_VERSION):
        name = f"world-object.v{earlier}.json"
        (tmp_path / name).write_bytes((CATALOG_DIRECTORY / name).read_bytes())
    (tmp_path / _CATALOG_FILE.name).write_text(json.dumps(document))
    return load_world_object_catalog(tmp_path)


def test_the_published_file_loads_through_the_same_path_the_refusals_take(tmp_path):
    """Positive control: an unchanged copy loads, so each refusal below is its own mutation's."""
    loaded = _load(tmp_path, _document())
    assert loaded.sha256 == world_object_catalog().sha256
    assert [kind.key for kind in loaded.kinds] == [
        kind.key for kind in world_object_catalog().kinds
    ]


def _set(path: list[Any], value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(document: dict[str, Any]) -> None:
        target: Any = _entry(document, path[0])
        for step in path[1:-1]:
            target = target[step]
        target[path[-1]] = value

    return mutate


def _grow_the_cafe_table_to(side_mm: int) -> Callable[[dict[str, Any]], None]:
    """A table top ``side_mm`` across, with the dimensions it then draws, and nothing else moved.

    A top that wide covers the chairs, so their seats would lie on it; the seats and the
    declaration they cite are taken away with it, and only the places are left to refuse.
    """

    def mutate(document: dict[str, Any]) -> None:
        entry = _entry(document, "cafe_table")
        top = entry["recipe"]["parts"][0]
        top["size_x_mm"] = top["size_y_mm"] = side_mm
        entry["dimensions_mm"]["width"] = entry["dimensions_mm"]["depth"] = side_mm
        for row in entry["use"]["places"]:
            row["seat"] = None
        del entry["declared"]["seat_point"]

    return mutate


def _standing_rows(key: str, rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], None]:
    """Rows with no seat, and no seat declaration left over, so only the rows are refused."""

    def mutate(document: dict[str, Any]) -> None:
        entry = _entry(document, key)
        entry["use"]["places"] = rows
        entry["declared"].pop("seat_point", None)

    return mutate


#: The bench's published seat, for rows a refusal restates, so only what the refusal names differs.
_BENCH_SEAT: Final = _entry(_document(), "bench")["use"]["places"][0]["seat"]

REFUSALS: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
    ("unknown recipe profile", _set(["bench", "recipe", "profile"], "parts-v9"), "profile"),
    (
        "a cited part that differs from the street furniture catalog",
        _set(["bench", "recipe", "parts", 0, "size_x_mm"], 1700),
        "differs from it",
    ),
    (
        "a citation of a part the street furniture catalog lacks",
        _set(["bench", "recipe", "parts", 0, "source"], "street-furniture.v2/bench/9"),
        "lacks",
    ),
    (
        "a declared citation with no declaration",
        _set(["cafe_table", "recipe", "parts", 0, "source"], "declared/nothing"),
        "does not declare",
    ),
    (
        "a declaration nothing cites",
        _set(["cafe_table", "declared", "unused"], "A measurement no part uses."),
        "no number cites",
    ),
    (
        "a role its materials do not dress",
        _set(["bench", "materials"], {"object_primary": "cc0.painted-timber"}),
        "every role a part takes is dressed",
    ),
    (
        "a cutout set on a role that admits only opaque sets",
        _set(["bench", "materials", "object_primary"], "cc0.broadleaf-foliage"),
        "admits",
    ),
    (
        "a texture set nobody published",
        _set(["bench", "materials", "object_primary"], "cc0.nothing"),
        "not published",
    ),
    (
        "maps embedded at a size that is not the set's side over a power of two",
        _set(["bench", "recipe", "texels"], 384),
        "power of two",
    ),
    (
        "dimensions the recipe does not draw",
        _set(["bench", "dimensions_mm", "width"], 1900),
        "draws",
    ),
    (
        "two rows on one side, whose places coincide",
        _set(
            ["bench", "use", "places"],
            [
                {"side": "+y", "count": 1, "seat": _BENCH_SEAT},
                {"side": "+y", "count": 1, "seat": _BENCH_SEAT},
            ],
        ),
        "closer than a standing spacing and the turning margin",
    ),
    (
        "a row longer than the side it stands along",
        _standing_rows("bench", [{"side": "+y", "count": 4, "seat": None}]),
        "do not fit along its",
    ),
    (
        "a side the part frame does not have",
        _set(["bench", "use", "places"], [{"side": "up", "count": 1, "seat": None}]),
        "side is one of",
    ),
    (
        "places around a kind that blocks nothing",
        _set(["bench", "use", "blocks_navigation"], False),
        "blocks nothing",
    ),
    (
        "a place farther from its centre than a registry row allows",
        _grow_the_cafe_table_to(20_000),
        "farther than",
    ),
    (
        "a kind with no part where a person walks",
        _set(["lamp_post", "recipe", "parts", 0, "offset_z_mm"], 2_000),
        "walker capsule",
    ),
    (
        "a marker that states places",
        _set(["marker_cube", "use", "places"], [{"side": "+y", "count": 1, "seat": None}]),
        "a marker states no places",
    ),
    (
        "a kind nobody uses that states places",
        _set(["lamp_post", "use", "places"], [{"side": "+y", "count": 1, "seat": None}]),
        "nobody uses",
    ),
    (
        "an activity the society does not have",
        _set(["bench", "use", "affordance"], "dance"),
        "affordance",
    ),
]


@pytest.mark.parametrize(
    ("mutate", "match"), [(m, s) for _, m, s in REFUSALS], ids=[name for name, _, _ in REFUSALS]
)
def test_the_loader_refuses_by_name(tmp_path, mutate, match):
    document = _document()
    mutate(document)
    with pytest.raises(CatalogError, match=match):
        _load(tmp_path, document)


def test_a_file_no_schema_claims_is_refused(tmp_path):
    (tmp_path / f"world-object.v{CATALOG_VERSION + 1}.json").write_text("{}")
    with pytest.raises(CatalogError, match="files with no schema"):
        _load(tmp_path, _document())


def test_two_kinds_naming_one_registry_key_are_refused(tmp_path):
    document = _document()
    _entry(document, "cafe_table")["asset_key"] = "cc0.bench"
    with pytest.raises(CatalogError, match="one registry key for two kinds"):
        _load(tmp_path, document)


# -- the containers ----------------------------------------------------------------------------


def _chunks(payload: bytes) -> tuple[dict[str, Any], bytes]:
    magic, version, total = struct.unpack_from("<III", payload, 0)
    assert (magic, version, total) == (0x46546C67, 2, len(payload))
    offset, chunks = 12, {}
    while offset < total:
        length, kind = struct.unpack_from("<II", payload, offset)
        assert length % 4 == 0
        chunks[kind] = payload[offset + 8 : offset + 8 + length]
        offset += 8 + length
    assert offset == total
    return json.loads(chunks[0x4E4F534A]), chunks[0x004E4942]


def _read(document: dict[str, Any], binary: bytes, accessor: int) -> list[tuple[float, ...]]:
    entry = document["accessors"][accessor]
    view = document["bufferViews"][entry["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[entry["type"]]
    code, size = {5126: ("f", 4), 5123: ("H", 2)}[entry["componentType"]]
    assert view["byteLength"] == entry["count"] * width * size
    return [
        struct.unpack_from(f"<{width}{code}", binary, view["byteOffset"] + index * width * size)
        for index in range(entry["count"])
    ]


def _textured() -> list[Any]:
    return [asset for asset in reviewed_assets() if asset.asset_key not in _markers()]


def _kind_of(asset):
    return world_object_catalog().by_asset_key()[asset.asset_key]


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b, strict=True))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


@pytest.mark.parametrize("asset", _textured(), ids=lambda a: a.asset_key)
def test_every_textured_container_is_what_the_renderer_accepts(asset):
    """The rules atlas-react's validateGlbContainer holds a container to, read here in Python."""
    document, binary = _chunks(asset.payload)
    assert asset.byte_size <= 32 * 1024 * 1024
    assert len(json.dumps(document)) <= 4 * 1024 * 1024
    assert document["asset"]["version"] == "2.0"
    assert "extensionsRequired" not in document and "extensionsUsed" not in document
    assert all("uri" not in item for item in document["buffers"] + document["images"])
    assert all(isinstance(image["bufferView"], int) for image in document["images"])
    assert document["buffers"] == [{"byteLength": len(binary)}]
    kind = _kind_of(asset)
    assert len(document["materials"]) == len(set(kind.materials.values()))


@pytest.mark.parametrize("asset", _textured(), ids=lambda a: a.asset_key)
def test_a_container_holds_its_kind_at_its_stated_size_on_the_ground(asset):
    document, binary = _chunks(asset.payload)
    kind = _kind_of(asset)
    points = [
        point
        for primitive in document["meshes"][0]["primitives"]
        for point in _read(document, binary, primitive["attributes"]["POSITION"])
    ]
    extent = [
        round((max(p[axis] for p in points) - min(p[axis] for p in points)) * 1000)
        for axis in range(3)
    ]
    width, depth, height = kind.dimensions_mm
    assert extent == [width, height, depth]
    assert min(p[1] for p in points) == 0.0


@pytest.mark.parametrize("asset", _textured(), ids=lambda a: a.asset_key)
def test_every_triangle_faces_out_and_its_bitangent_points_to_row_0(asset):
    """Winding, normals and the glTF handedness, checked against each triangle's own geometry."""
    document, binary = _chunks(asset.payload)
    checked = 0
    for primitive in document["meshes"][0]["primitives"]:
        attributes = primitive["attributes"]
        positions = _read(document, binary, attributes["POSITION"])
        normals = _read(document, binary, attributes["NORMAL"])
        tangents = _read(document, binary, attributes["TANGENT"])
        uvs = _read(document, binary, attributes["TEXCOORD_0"])
        indices = [value[0] for value in _read(document, binary, primitive["indices"])]
        for vertex in range(len(positions)):
            assert math.isclose(_dot(normals[vertex], normals[vertex]), 1, abs_tol=1e-5)
            assert abs(_dot(normals[vertex], tangents[vertex][:3])) < 1e-5
            assert tangents[vertex][3] in (-1.0, 1.0)
        for start in range(0, len(indices), 3):
            a, b, c = indices[start : start + 3]
            edge_one, edge_two = _sub(positions[b], positions[a]), _sub(positions[c], positions[a])
            face = _cross(edge_one, edge_two)
            if _dot(face, face) < 1e-12:
                continue
            for vertex in (a, b, c):
                assert _dot(face, normals[vertex]) > 0, (asset.asset_key, start)
            du1, dv1 = _sub(uvs[b], uvs[a])
            du2, dv2 = _sub(uvs[c], uvs[a])
            determinant = du1 * dv2 - du2 * dv1
            if abs(determinant) < 1e-9:
                continue
            # dP/dv, the direction v increases in; row 0 is the other way.
            dp_dv = tuple(
                (du1 * e2 - du2 * e1) / determinant
                for e1, e2 in zip(edge_one, edge_two, strict=True)
            )
            for vertex in (a, b, c):
                tangent = tangents[vertex]
                bitangent = tuple(x * tangent[3] for x in _cross(normals[vertex], tangent[:3]))
                assert _dot(bitangent, dp_dv) < 0, (asset.asset_key, start, vertex)
                checked += 1
    assert checked > 0


def _png_texels(png: bytes) -> tuple[int, int, int, bytes]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    offset, chunks = 8, []
    while offset < len(png):
        (length,) = struct.unpack_from(">I", png, offset)
        kind = png[offset + 4 : offset + 8]
        data = png[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack_from(">I", png, offset + 8 + length)
        assert crc == zlib.crc32(kind + data)
        chunks.append((kind, data))
        offset += 12 + length
    assert [kind for kind, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    width, height, depth, colour, *_ = struct.unpack(">IIBBBBB", chunks[0][1])
    components = {2: 3, 6: 4}[colour]
    assert depth == 8
    raw = zlib.decompress(chunks[1][1])
    row = width * components + 1
    assert len(raw) == row * height
    assert all(raw[start] == 0 for start in range(0, len(raw), row))
    texels = b"".join(raw[start + 1 : start + row] for start in range(0, len(raw), row))
    return width, height, components, texels


def _image(document: dict[str, Any], binary: bytes, texture: int) -> tuple[int, int, int, bytes]:
    """The texels of the image a texture index draws, decoded from its PNG."""
    source = document["images"][document["textures"][texture]["source"]]
    view = document["bufferViews"][source["bufferView"]]
    start = view["byteOffset"]
    return _png_texels(binary[start : start + view["byteLength"]])


def _averaged(texels: bytes, side: int, components: int, factor: int) -> bytes:
    """An independent box average: whole rows summed first, then columns, rounded half up."""
    if factor == 1:
        return texels
    out = bytearray()
    count = factor * factor
    for block_row in range(side // factor):
        stride = side * components
        rows = [
            texels[(block_row * factor + r) * stride : (block_row * factor + r + 1) * stride]
            for r in range(factor)
        ]
        for block_column in range(side // factor):
            for component in range(components):
                total = sum(
                    row[(block_column * factor + column) * components + component]
                    for row in rows
                    for column in range(factor)
                )
                out.append((total + count // 2) // count)
    return bytes(out)


def _z(x: int, y: int) -> int:
    nx, ny = 2 * x / 255 - 1, 2 * y / 255 - 1
    return math.floor((math.sqrt(max(0.0, 1 - nx * nx - ny * ny)) + 1) / 2 * 255 + 0.5)


@pytest.fixture(scope="module")
def library():
    return load_texture_catalog().sets


def test_every_embedded_image_is_its_set_s_own_map(library):
    """Provenance: each image decodes to the pinned set's map, at the recipe's texel size."""
    seen: set[tuple[str, int]] = set()
    for asset in _textured():
        document, binary = _chunks(asset.payload)
        kind = _kind_of(asset)
        assert isinstance(kind.recipe, PartsRecipe)
        for material in document["materials"]:
            pin = material["extras"]["texture_set"]
            pinned = library[pin["set_id"]]
            assert pin == {
                "content_sha256": pinned.content_sha256,
                "set_id": pinned.set_id,
                "version": pinned.version,
            }
            texels = material["extras"]["texels"]
            assert texels == kind.recipe.texels
            if (pinned.set_id, texels) in seen:
                continue
            seen.add((pinned.set_id, texels))
            decoded = decode_texture_set(pinned.read_bytes())
            factor = pinned.width // texels
            pbr = material["pbrMetallicRoughness"]
            cutout = pinned.material_class == "cutout"
            colour_name = "base_color_coverage" if cutout else "base_color"
            components = 4 if colour_name == "base_color_coverage" else 3
            assert _image(document, binary, pbr["baseColorTexture"]["index"]) == (
                texels,
                texels,
                components,
                _averaged(bytes(decoded.maps[colour_name]), pinned.width, components, factor),
            )
            assert _image(document, binary, pbr["metallicRoughnessTexture"]["index"]) == _image(
                document, binary, material["occlusionTexture"]["index"]
            )
            assert _image(document, binary, material["occlusionTexture"]["index"])[3] == _averaged(
                bytes(decoded.maps["orm"]), pinned.width, 3, factor
            )
            stored = bytes(decoded.maps["normal"])
            rebuilt = bytearray()
            for texel in range(len(stored) // 2):
                x, y = stored[2 * texel], stored[2 * texel + 1]
                rebuilt += bytes((x, y, _z(x, y)))
            assert _image(document, binary, material["normalTexture"]["index"])[3] == _averaged(
                bytes(rebuilt), pinned.width, 3, factor
            )
            if pinned.material_class == "cutout":
                assert material["alphaMode"] == "MASK"
                assert material["alphaCutoff"] == decoded.header["class"]["alpha_cutoff"] / 255
                assert material["doubleSided"] is True
            else:
                assert "alphaMode" not in material and "doubleSided" not in material
    assert seen


def test_a_stored_png_is_written_without_a_compressor_and_reads_back():
    # 240 by 320 RGB texels: more than one stored block's 65535 bytes.
    texels = bytes(range(256)) * 3 * 300
    png = stored_png(240, 320, 3, texels)
    assert _png_texels(png) == (240, 320, 3, texels)
    # Stored blocks only: the deflate stream holds every byte it encodes, uncompressed.
    assert len(png) > len(texels)


def test_a_cutout_set_dresses_only_what_admits_it():
    for kind in world_object_catalog().kinds:
        for role, set_id in kind.materials.items():
            if set_id == "cc0.broadleaf-foliage":
                assert role == "canopy", kind.key


def test_the_catalog_stated_dimensions_are_what_the_triangles_fill():
    for kind in world_object_catalog().kinds:
        if not isinstance(kind.recipe, PartsRecipe):
            continue
        triangles = form_triangles(tuple(part.form for part in kind.recipe.parts))
        xs = [v.x_mm for t in triangles for v in t.vertices]
        ys = [v.y_mm for t in triangles for v in t.vertices]
        zs = [v.z_mm for t in triangles for v in t.vertices]
        assert (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) == kind.dimensions_mm


def test_a_mutated_copy_is_not_the_published_catalog(tmp_path):
    """The catalog digest covers every nested value, so one changed number moves it."""
    document = _document()
    changed = copy.deepcopy(document)
    _entry(changed, "seating_planter")["use"]["places"][0]["count"] -= 1
    assert _load(tmp_path, changed).sha256 != world_object_catalog().sha256
