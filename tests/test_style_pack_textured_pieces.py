"""Textured pieces on the server: the profile, the reader, the family budget and the picture count.

A piece whose container holds images is a textured piece (``docs/style-pack-contract.md``,
section 4). Each test builds one here from typed arrays and Pillow pictures, apart from the tree
maker's writer, and holds it to the rules both readers share: what it may hold, its family's
texture side, no stretch zone, a textured second level, and the pack's one count of pictures.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import struct
import uuid
from typing import Any

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.world import style_packs
from exulanica.world.style_pack_admission import StylePackAdmissionRefused, admit
from exulanica.world.style_pack_checks import check_version, colour_table
from exulanica.world.style_pack_pieces import (
    PieceOutOfBounds,
    StylePieceRefused,
    check_piece_profile,
    hold_pieces,
    is_textured_piece,
    read_textured_piece,
)
from exulanica.world.workspace_style_packs import PackFile, StylePackVersionRecord
from exulanica_pieces.budgets import read_budgets

from static_glb_builder import UNSIGNED_SHORT, Gltf
from style_pack_upload_support import COZY, ROOT, Upload, jpeg, png, upload

BUDGETS = read_budgets(ROOT)


def textured_piece(*, side: int = 64, edit: Any = None) -> bytes:
    """A trunk quad in bark (with a normal map) and a leaf card cut out by alpha, 3 m tall."""
    gltf = Gltf()
    primitives = []
    for material, quad in enumerate(
        [
            [(-0.1, 0.0, 0.0), (-0.1, 1.2, 0.0), (0.1, 1.2, 0.0), (0.1, 0.0, 0.0)],
            [(-0.5, 3.0, 0.2), (-0.5, 1.0, 0.2), (0.5, 1.0, 0.2), (0.5, 3.0, 0.2)],
        ]
    ):
        primitives.append(
            {
                "attributes": {
                    "POSITION": gltf.positions(quad),
                    "NORMAL": gltf.vectors([(0.0, 0.0, 1.0)] * 4, "VEC3"),
                    "TEXCOORD_0": gltf.vectors([(0, 0), (0, 1), (1, 1), (1, 0)], "VEC2"),
                },
                "indices": gltf.indices([0, 1, 2, 0, 2, 3], UNSIGNED_SHORT),
                "material": material,
                "mode": 4,
            }
        )
    colour = gltf.texture(gltf.image(png(side, side), "image/png"))
    normal = gltf.texture(gltf.image(jpeg(side, side), "image/jpeg"))
    gltf.material(
        pbrMetallicRoughness={
            "baseColorTexture": {"index": colour},
            "metallicFactor": 0,
            "roughnessFactor": 0.9,
        },
        normalTexture={"index": normal},
    )
    gltf.material(
        pbrMetallicRoughness={"baseColorTexture": {"index": colour}},
        alphaMode="MASK",
        alphaCutoff=0.5,
        doubleSided=True,
    )
    gltf.mesh(*primitives)
    gltf.scene(gltf.node(mesh=0))
    if edit is not None:
        edit(gltf.document)
    return gltf.build()


def test_a_textured_piece_passes_the_profile_and_reads_as_the_browser_reads_it():
    data = textured_piece()
    profile = check_piece_profile(data)
    assert (profile.textured, profile.triangles, profile.materials) == (True, 4, 2)
    assert profile.image_sizes == ((64, 64), (64, 64))
    assert is_textured_piece(data)
    piece = read_textured_piece(data)
    assert (piece.triangles, piece.images) == (4, 2)
    # A palette piece is not one, and keeps its profile.
    bus = (COZY / "pieces/bus.glb").read_bytes()
    assert not is_textured_piece(bus)
    assert not check_piece_profile(bus).textured


@pytest.mark.parametrize(
    ("edit", "reason", "message"),
    [
        (
            lambda d: d["nodes"][0].update(translation=[0, 1, 0]),
            "not_a_textured_piece",
            "a textured piece's node draws its mesh with no transform",
        ),
        (
            lambda d: d["meshes"][0]["primitives"][0]["attributes"].update(COLOR_0=1),
            "not_a_textured_piece",
            "meshes[0].primitives[0] states POSITION, NORMAL and TEXCOORD_0 and nothing else",
        ),
        (
            lambda d: d["materials"][1].update(alphaMode="BLEND"),
            "not_a_textured_piece",
            "materials[1] is opaque or cut out, never blended",
        ),
        (
            lambda d: d["materials"][0].update(emissiveFactor=[1, 0, 0]),
            "not_a_textured_piece",
            "materials[0] holds base colour, normal and factors only, not emissiveFactor",
        ),
        (
            lambda d: d["materials"][0]["pbrMetallicRoughness"].update(
                metallicRoughnessTexture={"index": 0}
            ),
            "not_a_textured_piece",
            "materials[0] holds base colour, normal and factors only, not metallicRoughnessTexture",
        ),
        (
            lambda d: d["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"].update(
                texCoord=1
            ),
            "not_a_textured_piece",
            "materials[0].baseColorTexture reads the first texture coordinates",
        ),
    ],
    ids=["node transform", "colour attribute", "blended", "emission", "metal map", "texCoord 1"],
)
def test_a_textured_piece_holding_more_is_refused_by_name(edit: Any, reason: str, message: str):
    with pytest.raises(StylePieceRefused) as refused:
        check_piece_profile(textured_piece(edit=edit))
    assert (refused.value.reason, str(refused.value)) == (reason, message)


def test_an_embedded_picture_that_hides_anything_is_refused_by_the_shared_probe():
    gltf_jpeg = jpeg(64, 64)
    commented = gltf_jpeg[:2] + b"\xff\xfe\x00\x07hello" + gltf_jpeg[2:]

    def swap(document: dict[str, Any]) -> None:
        document["images"][1]["_swap"] = True

    data = textured_piece(edit=swap)
    # Rebuild with the commented JPEG in the normal map's place, its view grown to hold it.
    json_length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + json_length])
    del document["images"][1]["_swap"]
    binary = bytearray(data[28 + json_length :])
    view = document["bufferViews"][document["images"][1]["bufferView"]]
    start = view["byteOffset"]
    binary[start : start + view["byteLength"]] = commented
    growth = len(commented) - view["byteLength"]
    view["byteLength"] = len(commented)
    for other in document["bufferViews"]:
        if other["byteOffset"] > start:
            other["byteOffset"] += growth
    binary.extend(b"\x00" * (-len(binary) % 4))
    document["buffers"][0]["byteLength"] = len(binary)
    from static_glb_builder import pack

    with pytest.raises(StylePieceRefused) as refused:
        check_piece_profile(pack(document, bytes(binary)))
    assert refused.value.reason == "image_hidden_data"


def _pieces(variant: dict[str, Any], family: str = "plant") -> dict[str, Any]:
    pieces = {variant["file"]: (family, variant, False)}
    if variant["lod1"] is not None:
        pieces[variant["lod1"]] = (family, variant, True)
    return pieces


def _variant(**fields: Any) -> dict[str, Any]:
    return {
        "file": "pieces/tree.glb",
        "lod1": None,
        "size_mm": [1000, 400, 3000],
        "stretch_mm": [None, None, None],
        **fields,
    }


def test_a_textured_piece_is_held_to_its_familys_texture_side_and_drawn_whole():
    def hold(files: dict[str, bytes], variant: dict[str, Any], textures: int = 0) -> dict[str, int]:
        return hold_pieces(
            _pieces(variant),
            files.__getitem__,
            BUDGETS.families,
            BUDGETS.lod1_share_permille,
            textures,
        )

    side = BUDGETS.families["plant"].texture_side_px
    assert hold({"pieces/tree.glb": textured_piece(side=side)}, _variant()) == {
        "pieces/tree.glb": 4
    }
    with pytest.raises(PieceOutOfBounds) as over:
        hold({"pieces/tree.glb": textured_piece(side=side * 2)}, _variant())
    assert (over.value.code, str(over.value)) == (
        "over_budget",
        f"an image {side * 2} px a side, over its family's {side}",
    )
    with pytest.raises(PieceOutOfBounds) as stretched:
        hold(
            {"pieces/tree.glb": textured_piece()},
            _variant(stretch_mm=[[100, 900], None, None]),
        )
    assert str(stretched.value) == "a textured piece states no stretch zone: it is drawn whole"
    bus = (COZY / "pieces/bus.glb").read_bytes()
    with pytest.raises(PieceOutOfBounds) as palette_far:
        hold(
            {"pieces/tree.glb": textured_piece(), "pieces/tree-far.glb": bus},
            _variant(lod1="pieces/tree-far.glb"),
        )
    assert str(palette_far.value) == "a textured piece's second level is textured too"
    # The pack's pictures, its textures' and its pieces', against the one shared count.
    with pytest.raises(PieceOutOfBounds) as many:
        hold({"pieces/tree.glb": textured_piece()}, _variant(), style_packs.PACK_IMAGES_MAX - 1)
    assert (many.value.code, many.value.path) == ("over_budget", "files")
    assert "draws with 65 pictures; at most 64" in str(many.value)


def _with_textured_tree(made: Upload) -> Upload:
    made.files["pieces/tree.glb"] = textured_piece()
    return made.relist()


def _no_base(_base: Any) -> str:
    raise StylePackAdmissionRefused("style_pack_base_unavailable", "no base here", path="base")


def _admit(made: Upload) -> Any:
    return admit(
        made.declaration_bytes(),
        made.manifest_bytes,
        made.files,
        context=style_packs.load_context(ROOT),
        budgets=BUDGETS.families,
        lod1_share_permille=BUDGETS.lod1_share_permille,
        resolve_base=_no_base,
    )


def test_an_upload_carrying_a_textured_piece_is_admitted_and_its_pictures_counted(monkeypatch):
    made = _with_textured_tree(upload())
    admitted = _admit(made)
    tree = next(file for file in admitted.files if file.path == "pieces/tree.glb")
    assert admitted.contents[tree.content_sha256] == made.files["pieces/tree.glb"]
    # One picture allowed: the tree's two are over the count, at admission, by the files.
    monkeypatch.setattr(style_packs, "PACK_IMAGES_MAX", 1)
    with pytest.raises(StylePackAdmissionRefused) as refused:
        _admit(made)
    assert (refused.value.code, refused.value.path) == ("over_budget", "files")


def test_a_cover_piece_is_admitted_textured_and_refused_by_name_as_a_palette_piece():
    def covered(made: Upload) -> Upload:
        made.manifest["cover"] = {
            "ground.default": {
                "pieces": ["plant.default"],
                "density_per_100m2": 300,
                "scale_permille": [800, 1200],
                "seed": 1,
            }
        }
        return made

    textured = covered(_with_textured_tree(upload()))
    assert _admit(textured).manifest_canonical == textured.manifest_bytes
    with pytest.raises(StylePackAdmissionRefused) as refused:
        _admit(covered(upload()))
    assert (refused.value.code, refused.value.path, str(refused.value)) == (
        "style_pack_piece_refused",
        "pieces/tree.glb",
        "pieces/tree.glb: a cover piece is a textured piece: cover is drawn instanced",
    )


def test_a_land_cover_piece_is_admitted_textured_and_refused_by_name_as_a_palette_piece():
    def grown(made: Upload) -> Upload:
        made.manifest["land_cover"] = {
            "woods": {
                "role": "land",
                "pieces": ["plant.default"],
                "density_per_ha": 40,
                "scale_permille": [800, 1200],
                "seed": 1,
            }
        }
        return made

    textured = grown(_with_textured_tree(upload()))
    assert _admit(textured).manifest_canonical == textured.manifest_bytes
    with pytest.raises(StylePackAdmissionRefused) as refused:
        _admit(grown(upload()))
    assert (refused.value.code, refused.value.path, str(refused.value)) == (
        "style_pack_piece_refused",
        "pieces/tree.glb",
        "pieces/tree.glb: a land cover piece is a textured piece: land_cover is drawn instanced",
    )


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


def test_the_check_reads_a_textured_piece_by_its_images_and_a_palette_piece_by_its_colours():
    manifest = json.loads((COZY / "manifest.json").read_text("utf-8"))
    files = {
        "pieces/tree.glb": textured_piece(),
        "pieces/bus.glb": (COZY / "pieces/bus.glb").read_bytes(),
    }
    repository = _Repository(files)
    record = StylePackVersionRecord(
        manifest_sha256="0" * 64,
        pack_id="maker.cozy-barn",
        version=1,
        manifest_canonical=style_packs.canonical_json(manifest).encode(),
        manifest_byte_size=0,
        rights_basis="own_work",
        licence_id=style_packs.OWN_WORK,
        base=None,
        file_count=len(files),
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
    failure, message, report = check_version(
        repository,  # type: ignore[arg-type]
        _Stores(repository.store),  # type: ignore[arg-type]
        record,
        table=colour_table(ROOT),
        library=lambda _sha: None,
    )
    assert (failure, message) == (None, None)
    assert report["pieces"]["pieces/tree.glb"] == {"triangles": 4, "images": 2}
    assert report["pieces"]["pieces/bus.glb"]["colours"] > 0
