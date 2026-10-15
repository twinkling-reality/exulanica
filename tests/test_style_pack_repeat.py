"""A piece that repeats its bays and storeys to meet its slot (``repeat_mm``).

The reader takes the optional field on a fill family's variant and refuses it elsewhere; catalog
version 3 makes the structure family a fill family, so a building's piece may repeat; and the
server holds every triangle of a repeating palette piece to one side of each zone edge, in the pack
check worker, so the copies the page bakes join without a crack. The browser's reader is held to
the same refusals by ``web/packages/atlas-core/test/style-pack.test.ts``.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import struct
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.world import style_packs
from exulanica.world.style_pack_checks import check_version, colour_table
from exulanica.world.style_pack_pieces import (
    PieceOutOfBounds,
    StylePieceRefused,
    check_repeat_zones,
    hold_pieces,
)
from exulanica.world.workspace_style_packs import PackFile, StylePackVersionRecord
from exulanica_pieces.budgets import read_budgets

from static_glb_builder import UNSIGNED_SHORT, Gltf, png

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = style_packs.load_context(ROOT)
BUDGETS = read_budgets(ROOT)
TABLE = colour_table(ROOT)
CASES: dict[str, Any] = json.loads(
    (ROOT / "assets/style-packs/manifest-cases.v1.json").read_text(encoding="utf-8")
)
V2 = {"version": 2, "sha256": CONTEXT.family_catalogs[2].sha256}
V3 = {"version": 3, "sha256": CONTEXT.family_catalogs[3].sha256}
#: The shared cases' complete pack: a contained car and a window that stretches on every axis.
BASE = CASES["cases"][0]
SWATCHES = [{"key": "stone", "srgb8": [226, 214, 192]}, {"key": "shade", "srgb8": [58, 52, 48]}]


def _cases_context() -> style_packs.StylePackContext:
    families = {
        key: style_packs.LookFamily(**value) for key, value in CASES["context"]["families"].items()
    }
    return style_packs.StylePackContext(
        families=families, texture_sets=frozenset(CASES["context"]["texture_sets"])
    )


def _window(stretch: list[Any], repeat: Any) -> dict[str, Any]:
    """The base pack with its window's stretch and repeat zones replaced."""
    manifest = copy.deepcopy(BASE["manifest"])
    variant = manifest["modules"]["window.default"]["variants"][0]
    variant["stretch_mm"] = stretch
    variant["repeat_mm"] = repeat
    return manifest


def test_a_fill_variant_may_repeat_a_zone_and_one_stating_none_reads_as_it_did():
    manifest = _window([None, [40, 80], None], [[60, 940], None, [60, 1540]])
    read = style_packs.read_manifest(manifest, _cases_context())
    variant = read["modules"]["window.default"]["variants"][0]
    assert variant["repeat_mm"] == [[60, 940], None, [60, 1540]]
    assert '"repeat_mm":[[60,940],null,[60,1540]]' in style_packs.canonical_json(read)
    # The field is added within the profile: a manifest without it keeps its bytes and digest.
    untouched = style_packs.read_manifest(BASE["manifest"], _cases_context())
    assert "repeat_mm" not in untouched["modules"]["window.default"]["variants"][0]
    assert style_packs.manifest_sha256(untouched) == BASE["expect"]["sha256"]


@pytest.mark.parametrize(
    ("edit", "reason", "path"),
    [
        (
            lambda m: m["modules"]["vehicle.car"]["variants"][0].update(
                repeat_mm=[[500, 3700], None, None]
            ),
            "reference",
            "modules.vehicle.car.variants[0].repeat_mm",
        ),
        (
            lambda m: m.update(_window([None, [40, 80], None], [[60, 1100], None, None])),
            "range",
            "modules.window.default.variants[0].repeat_mm[0]",
        ),
        (
            lambda m: m.update(_window([None, [40, 80], None], [[500, 500], None, None])),
            "range",
            "modules.window.default.variants[0].repeat_mm[0]",
        ),
        (
            lambda m: m.update(_window([None, [40, 80], None], [None, [40, 80], None])),
            "shape",
            "modules.window.default.variants[0].repeat_mm[1]",
        ),
        (
            lambda m: m.update(_window([None, [40, 80], None], [[60, 940]])),
            "shape",
            "modules.window.default.variants[0].repeat_mm",
        ),
    ],
    ids=["a contain family", "past the piece", "of no length", "an axis that stretches", "arity"],
)
def test_a_repeat_is_refused_by_reason_and_path(edit, reason, path):
    manifest = copy.deepcopy(BASE["manifest"])
    edit(manifest)
    with pytest.raises(style_packs.StylePackRefused) as refused:
        style_packs.read_manifest(manifest, _cases_context())
    assert (refused.value.reason, refused.value.path) == (reason, path)


def _with_hall(pin: dict[str, Any], stretch: bool = True) -> dict[str, Any]:
    """The base pack pinned to ``pin`` with a hall that repeats its bays along its width and its
    storeys up its height, and stretches its plain middle in depth when ``stretch``."""
    manifest = copy.deepcopy(BASE["manifest"])
    manifest["look_family_catalog"] = pin
    manifest["modules"]["structure.hall"] = {
        "variants": [
            {
                "file": "pieces/hall.glb",
                "lod1": None,
                "size_mm": [9000, 12000, 15000],
                "stretch_mm": [None, [3000, 9000] if stretch else None, None],
                "repeat_mm": [[1000, 8000], None, [6000, 12000]],
            }
        ]
    }
    listed = {file["path"]: file for file in manifest["files"]}
    listed["pieces/hall.glb"] = {
        "path": "pieces/hall.glb",
        "sha256": "a" * 64,
        "bytes": 1024,
        "media_type": "model/gltf-binary",
    }
    manifest["files"] = [listed[path] for path in sorted(listed)]
    return manifest


def test_catalog_v3_lets_a_building_repeat_its_bays_and_v2_does_not():
    assert CONTEXT.family_catalogs[2].families["structure"].fit == "contain"
    assert CONTEXT.family_catalogs[3].families["structure"].fit == "fill"
    read = style_packs.read_manifest(_with_hall(V3), CONTEXT)
    assert read["modules"]["structure.hall"]["variants"][0]["repeat_mm"][0] == [1000, 8000]
    with pytest.raises(style_packs.StylePackRefused) as refused:
        style_packs.read_manifest(_with_hall(V2, stretch=False), CONTEXT)
    assert (refused.value.reason, str(refused.value)) == (
        "reference",
        "modules.structure.hall.variants[0].repeat_mm: repeats only a piece of a fill family",
    )


def _palette() -> list[dict[str, Any]]:
    return [
        {
            **swatch,
            "roughness_permille": 800,
            "metalness_permille": 0,
            "emission_permille": 0,
        }
        for swatch in SWATCHES
    ]


Box = tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


def _block(boxes: list[Box]) -> bytes:
    """A palette piece of axis-aligned boxes, in stone: six faces each, two triangles a face."""
    points: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    for box in boxes:
        for axis in range(3):
            other = [k for k in range(3) if k != axis]
            for side in (0, 1):
                for a, b in ((0, 0), (1, 0), (1, 1), (0, 1)):
                    corner = [0.0, 0.0, 0.0]
                    corner[axis] = box[axis][side]
                    corner[other[0]], corner[other[1]] = box[other[0]][a], box[other[1]][b]
                    points.append((corner[0], corner[1], corner[2]))
                    normal = [0.0, 0.0, 0.0]
                    normal[axis] = 1.0 if side else -1.0
                    normals.append((normal[0], normal[1], normal[2]))
    stone = [TABLE[byte] for byte in SWATCHES[0]["srgb8"]]
    colours = struct.pack(f"<{len(points) * 4}H", *([*stone, 65535] * len(points)))
    gltf = Gltf()
    colour = gltf.accessor(
        gltf.view(colours, target=34962), UNSIGNED_SHORT, "VEC4", len(points), normalized=True
    )
    quads = range(len(points) // 4)
    primitive = {
        "attributes": {
            "POSITION": gltf.positions(points),
            "NORMAL": gltf.vectors(normals, "VEC3"),
            "COLOR_0": colour,
        },
        "indices": gltf.indices(4 * q + k for q in quads for k in (0, 1, 2, 0, 2, 3)),
    }
    gltf.scene(gltf.node(mesh=gltf.mesh(primitive)))
    return gltf.build()


#: A 3 m wide, 2 m deep, 3 m tall piece whose middle metre of width repeats: edges at x = -0.5, 0.5.
WIDE = {"size_mm": [3000, 2000, 3000], "repeat_mm": [[1000, 2000], None, None]}
TALL = {"size_mm": [3000, 2000, 3000], "repeat_mm": [None, None, [1000, 2000]]}
WHOLE = [((-1.5, 1.5), (0.0, 3.0), (-1.0, 1.0))]
SPLIT = [
    ((-1.5, -0.5), (0.0, 3.0), (-1.0, 1.0)),
    ((-0.5, 0.5), (0.0, 3.0), (-1.0, 1.0)),
    ((0.5, 1.5), (0.0, 3.0), (-1.0, 1.0)),
]


def test_a_triangle_across_a_repeat_edge_is_refused_and_one_at_an_edge_holds():
    with pytest.raises(StylePieceRefused) as across:
        check_repeat_zones(_block(WHOLE), WIDE)
    assert across.value.reason == "crosses_repeat_zone"
    assert "the width repeat zone's edge at 1000 mm" in str(across.value)
    check_repeat_zones(_block(SPLIT), WIDE)
    # A corner 0.3 mm past an edge is on the edge: the zone is stated in whole millimetres.
    check_repeat_zones(
        _block(
            [
                ((-1.5, -0.4997), (0.0, 3.0), (-1.0, 1.0)),
                ((-0.4997, 0.5), (0.0, 3.0), (-1.0, 1.0)),
                ((0.5, 1.5), (0.0, 3.0), (-1.0, 1.0)),
            ]
        ),
        WIDE,
    )
    # Height is measured up from the base: the split boxes all cross a storey zone at 1 m.
    with pytest.raises(StylePieceRefused) as storey:
        check_repeat_zones(_block(SPLIT), TALL)
    assert "the height repeat zone's edge at 1000 mm" in str(storey.value)
    # A variant that repeats nothing is not read at all.
    check_repeat_zones(b"", {"size_mm": [3000, 2000, 3000], "repeat_mm": [None, None, None]})
    check_repeat_zones(b"", {"size_mm": [3000, 2000, 3000]})


class _Store:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._by_sha = {hashlib.sha256(data).hexdigest(): data for data in files.values()}

    def get(self, blob: BlobId) -> bytes:
        return self._by_sha[blob.hex]


class _Repository:
    workspace_id = uuid.UUID(int=1)

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files
        self.store = _Store(files)

    def files(self, _manifest_sha256: str) -> list[PackFile]:
        return [
            PackFile(path, hashlib.sha256(data).hexdigest(), len(data), "model/gltf-binary")
            for path, data in sorted(self._files.items())
        ]


class _Stores:
    def __init__(self, store: _Store) -> None:
        self._store = store

    def for_workspace(self, _workspace: uuid.UUID) -> _Store:
        return self._store


def _check(piece: bytes, repeat: Any) -> tuple[str | None, str | None]:
    """The pack check worker over one hall piece whose variant states ``repeat``."""
    variant: dict[str, Any] = {
        "file": "pieces/hall.glb",
        "lod1": None,
        "size_mm": [3000, 2000, 3000],
        "stretch_mm": [None, None, None],
    }
    if repeat is not None:
        variant["repeat_mm"] = repeat
    manifest = {
        "palette": {"swatches": _palette()},
        "modules": {"structure.hall": {"variants": [variant]}},
        "base": None,
    }
    repository = _Repository({"pieces/hall.glb": piece})
    record = StylePackVersionRecord(
        manifest_sha256="0" * 64,
        pack_id="maker.hall",
        version=1,
        manifest_canonical=style_packs.canonical_json(manifest).encode(),
        manifest_byte_size=0,
        rights_basis="own_work",
        licence_id=style_packs.OWN_WORK,
        base=None,
        file_count=1,
        file_byte_size=0,
        preview_sha256=None,
        declaration_sha256="0" * 64,
        created_by=uuid.UUID(int=2),
        created_at=dt.datetime(2026, 10, 14, tzinfo=dt.UTC),
        erased=False,
        state="checking",
        failure_class=None,
        failure_message=None,
        attempts=0,
        withdrawn=False,
    )
    failure, message, _report = check_version(
        repository,  # type: ignore[arg-type]
        _Stores(repository.store),  # type: ignore[arg-type]
        record,
        table=TABLE,
        library=lambda _sha: None,
    )
    return failure, message


def test_the_check_holds_a_repeating_piece_to_its_zones_and_leaves_others_as_they_were():
    failure, message = _check(_block(WHOLE), WIDE["repeat_mm"])
    assert failure == "refused"
    assert message is not None and message.startswith("pieces/hall.glb: crosses_repeat_zone: ")
    assert _check(_block(SPLIT), WIDE["repeat_mm"]) == (None, None)
    # The same whole box, repeating nothing, passes as every palette piece did.
    assert _check(_block(WHOLE), None) == (None, None)


def _textured() -> bytes:
    """A 1 by 2 m quad drawn in a picture: a textured piece."""
    gltf = Gltf()
    quad = [(-0.5, 0.0, 0.0), (-0.5, 2.0, 0.0), (0.5, 2.0, 0.0), (0.5, 0.0, 0.0)]
    primitive = {
        "attributes": {
            "POSITION": gltf.positions(quad),
            "NORMAL": gltf.vectors([(0.0, 0.0, 1.0)] * 4, "VEC3"),
            "TEXCOORD_0": gltf.vectors([(0, 0), (0, 1), (1, 1), (1, 0)], "VEC2"),
        },
        "indices": gltf.indices([0, 1, 2, 0, 2, 3], UNSIGNED_SHORT),
        "material": 0,
        "mode": 4,
    }
    colour = gltf.texture(gltf.image(png(64, 64), "image/png"))
    gltf.material(pbrMetallicRoughness={"baseColorTexture": {"index": colour}})
    gltf.mesh(primitive)
    gltf.scene(gltf.node(mesh=0))
    return gltf.build()


def test_a_textured_piece_states_no_repeat_zone():
    variant = {
        "file": "pieces/hall.glb",
        "lod1": None,
        "size_mm": [1000, 400, 2000],
        "stretch_mm": [None, None, None],
        "repeat_mm": [None, None, [500, 1500]],
    }
    with pytest.raises(PieceOutOfBounds) as refused:
        hold_pieces(
            {"pieces/hall.glb": ("structure", variant, False)},
            {"pieces/hall.glb": _textured()}.__getitem__,
            BUDGETS.families,
            BUDGETS.lod1_share_permille,
        )
    assert (refused.value.code, str(refused.value)) == (
        "style_pack_piece_refused",
        "a textured piece states no repeat zone: it is drawn whole",
    )
