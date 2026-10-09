"""A creator's style pack upload, admitted or refused by name, before anything is written.

The upload is the committed cozy pack re-labelled as a creator's own
(``style_pack_upload_support``), so a positive control admits real product pieces; each refusal
below changes one thing and states the code and path it must answer, written by hand. The
pieces' profile, their colours and the preview walk are held to the committed pieces and to
pictures Pillow encodes.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import pytest
from exulanica.world import style_packs
from exulanica.world.style_pack_admission import StylePackAdmissionRefused, admit
from exulanica.world.style_pack_checks import colour_table
from exulanica.world.style_pack_pieces import (
    StylePieceRefused,
    check_piece_profile,
    read_palette_piece,
)
from exulanica.world.style_pack_preview import PreviewRefused, walk_preview
from exulanica_pieces.budgets import read_budgets

from style_pack_upload_support import COZY, Upload, jpeg, png, upload

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = style_packs.load_context(ROOT)
BUDGETS = read_budgets(ROOT)
TABLE = colour_table(ROOT)
PIECES = sorted(Path(ROOT / "assets/style-packs/packs").rglob("*.glb"))


def _no_base(_base: Any) -> str:
    raise StylePackAdmissionRefused("style_pack_base_unavailable", "no base here", path="base")


def _admit(made: Upload, declaration: bytes | None = None) -> Any:
    return admit(
        made.declaration_bytes() if declaration is None else declaration,
        made.manifest_bytes,
        made.files,
        context=CONTEXT,
        budgets=BUDGETS.families,
        lod1_share_permille=BUDGETS.lod1_share_permille,
        resolve_base=_no_base,
    )


def _refused(made: Upload, declaration: bytes | None = None) -> tuple[str, str | None]:
    with pytest.raises(StylePackAdmissionRefused) as refused:
        _admit(made, declaration)
    return refused.value.code, refused.value.path


# -- admission ------------------------------------------------------------------------------------


def test_a_creators_own_pack_is_admitted_with_every_file_and_its_receipt():
    made = upload()
    admitted = _admit(made)
    assert (admitted.pack_id, admitted.version, admitted.licence_id) == (
        "maker.cozy-barn",
        1,
        "LicenseRef-Exulanica-Own-Work",
    )
    assert admitted.manifest_canonical == made.manifest_bytes
    assert [file.path for file in admitted.files] == [f["path"] for f in made.manifest["files"]]
    assert set(admitted.contents) == {f["sha256"] for f in made.manifest["files"]}
    assert admitted.receipt["preview_px"] == [64, 40]
    assert all(count > 0 for count in admitted.receipt["piece_triangles"].values())


def test_the_declaration_is_refused_by_name():
    made = upload()
    assert _refused(made, b"{not json") == ("invalid_declaration", None)
    assert _refused(made, made.declaration_bytes(surprise=True)) == ("invalid_declaration", None)
    licensed = upload()
    licensed.rights.update(basis="licensed", licence_id="CC-BY-NC-4.0")
    assert _refused(licensed) == ("licence_not_admitted", None)
    licensed.rights.update(licence_id="CC-BY-4.0")
    assert _refused(licensed) == ("attribution_required", None)
    own = upload()
    own.rights.update(attribution="Someone")
    assert _refused(own) == ("invalid_declaration", None)
    bidi = upload()
    bidi.rights.update(source_reference="made by ‮me")
    assert _refused(bidi) == ("invalid_declaration", None)


def test_the_manifest_bytes_are_the_declared_canonical_bytes():
    made = upload()
    assert _refused(made, made.declaration_bytes(manifest_sha256="0" * 64)) == (
        "content_digest_mismatch",
        None,
    )
    pretty = json.dumps(made.manifest, indent=1).encode()
    declaration = made.declaration_bytes(
        manifest_sha256=hashlib.sha256(pretty).hexdigest(), byte_size=len(pretty)
    )
    with pytest.raises(StylePackAdmissionRefused) as refused:
        admit(
            declaration,
            pretty,
            made.files,
            context=CONTEXT,
            budgets=BUDGETS.families,
            lod1_share_permille=BUDGETS.lod1_share_permille,
            resolve_base=_no_base,
        )
    assert refused.value.code == "invalid_style_data"
    for raw in (b'{"a":NaN}', b'{"a":1,"a":2}', b"[" * 40 + b"]" * 40, b"\xff\xfe"):
        sized = made.declaration_bytes(
            manifest_sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw)
        )
        with pytest.raises(StylePackAdmissionRefused) as refused:
            admit(
                sized,
                raw,
                made.files,
                context=CONTEXT,
                budgets=BUDGETS.families,
                lod1_share_permille=BUDGETS.lod1_share_permille,
                resolve_base=_no_base,
            )
        assert refused.value.code == "invalid_style_data", raw


def test_an_uploaded_pack_is_the_creators_own_and_states_the_declared_licence():
    authored = upload()
    authored.manifest.update(origin="authored", provenance={"kind": "authored"})
    authored.manifest["licence"] = {"id": "CC0-1.0", "attribution": None}
    authored.rights.update(basis="licensed", licence_id="CC0-1.0")
    assert _refused(authored) == ("invalid_style_data", "origin")
    ours = upload(pack_id="exulanica.cozy-barn")
    assert _refused(ours) == ("invalid_style_data", "pack_id")
    # The ids a workspace's erasure gives its erased versions are never an upload's.
    erased = upload(pack_id="erased.x" + "0" * 24)
    assert _refused(erased) == ("invalid_style_data", "pack_id")
    # Nor the ids of looks made of generated pieces.
    generated = upload(pack_id="generated.cozy-town")
    assert _refused(generated) == ("invalid_style_data", "pack_id")
    mismatched = upload()
    mismatched.rights.update(basis="licensed", licence_id="CC0-1.0")
    assert _refused(mismatched) == ("licence_mismatch", "licence")
    based = upload()
    based.manifest["base"] = {
        "pack_id": "exulanica.cozy-town",
        "version": 1,
        "manifest_sha256": "0" * 64,
    }
    assert _refused(based) == ("style_pack_base_unavailable", "base")


def test_the_parts_are_exactly_the_manifests_files_at_their_listed_bytes():
    missing = upload()
    del missing.files["pieces/bus.glb"]
    assert _refused(missing) == ("invalid_style_pack_body", None)
    extra = upload()
    extra.files["pieces/stowaway.glb"] = b"x"
    assert _refused(extra) == ("invalid_style_pack_body", None)
    changed = upload()
    changed.files["pieces/bus.glb"] = changed.files["pieces/bus.glb"][:-4] + b"\x00\x00\x00\x00"
    assert _refused(changed) == ("content_digest_mismatch", "pieces/bus.glb")


def test_a_piece_over_its_familys_triangles_is_refused_before_its_colours_are_read():
    budget = BUDGETS.families["vehicle"]
    assert budget.triangles_per_metre == 0, "a fixed family: its limit is the size's own"
    tight = upload()
    families = dict(BUDGETS.families)
    families["vehicle"] = type(budget)(
        triangles=1,
        triangles_per_metre=0,
        materials=budget.materials,
        texture_side_px=budget.texture_side_px,
        glb_bytes=budget.glb_bytes,
    )
    with pytest.raises(StylePackAdmissionRefused) as refused:
        admit(
            tight.declaration_bytes(),
            tight.manifest_bytes,
            tight.files,
            context=CONTEXT,
            budgets=families,
            lod1_share_permille=BUDGETS.lod1_share_permille,
            resolve_base=_no_base,
        )
    assert (refused.value.code, refused.value.path) == ("over_budget", "pieces/bus.glb")


def test_a_preview_that_hides_anything_is_refused():
    made = upload()
    preview = made.manifest["preview"]
    made.files[preview] = made.files[preview] + b"after the end"
    made.relist()
    assert _refused(made) == ("style_pack_preview_refused", preview)


# -- the piece profile and colours ---------------------------------------------------------------


def _drop_a_triangle(document: dict[str, Any]) -> None:
    """The index accessor reads one triangle fewer, leaving its last bytes read by nobody."""
    indices = document["meshes"][0]["primitives"][0]["indices"]
    document["accessors"][indices]["count"] -= 3


def _with_json(data: bytes, edit: Any) -> bytes:
    """A piece whose JSON chunk ``edit`` changed, padded with spaces, its binary chunk unchanged."""
    json_length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + json_length])
    edit(document)
    text = json.dumps(document, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    rest = data[20 + json_length :]
    body = struct.pack("<I", len(text)) + b"JSON" + text + rest
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def test_every_committed_piece_passes_the_profile_and_reads_as_palette_colours():
    assert PIECES, "the positive control needs the committed pieces"
    for path in PIECES:
        data = path.read_bytes()
        assert check_piece_profile(data).triangles > 0, path
        assert read_palette_piece(data, TABLE).colours, path


@pytest.mark.parametrize(
    ("edit", "reason"),
    [
        (lambda d: d["meshes"][0].update(extras={"note": "hidden"}), "hidden_data"),
        (lambda d: d["meshes"][0].update(name="x" * 65), "hidden_data"),
        (lambda d: d["asset"].update(copyright="someone"), "hidden_data"),
        (lambda d: _drop_a_triangle(d), "hidden_data"),
    ],
    ids=["extras", "a long name", "asset copyright", "a view byte nobody reads"],
)
def test_a_piece_carrying_anything_but_its_geometry_is_refused(edit: Any, reason: str):
    data = (COZY / "pieces/bus.glb").read_bytes()
    with pytest.raises(StylePieceRefused) as refused:
        check_piece_profile(_with_json(data, edit))
    assert refused.value.reason == reason


def test_trailing_bytes_in_the_binary_chunk_are_refused():
    data = bytearray((COZY / "pieces/bus.glb").read_bytes())
    json_length = struct.unpack_from("<I", data, 12)[0]
    bin_at = 20 + json_length
    bin_length = struct.unpack_from("<I", data, bin_at)[0]
    extended = bytes(data[: bin_at + 8 + bin_length]) + b"SECRET!!"
    head = bytearray(extended)
    struct.pack_into("<I", head, bin_at, bin_length + 8)
    struct.pack_into("<I", head, 8, len(head))
    with pytest.raises(StylePieceRefused) as refused:
        check_piece_profile(bytes(head))
    assert refused.value.reason in ("hidden_data", "malformed_container")


def test_a_colour_that_is_no_value_of_the_table_is_refused():
    data = (COZY / "pieces/bus.glb").read_bytes()
    table = list(TABLE)
    table[0], table[255] = table[255], table[0]
    shifted = [value + 1 if 0 < value < 65535 else value for value in TABLE]
    with pytest.raises(StylePieceRefused):
        read_palette_piece(data, shifted)
    assert read_palette_piece(data, table).colours  # a permuted table still names every byte


# -- the preview walk -----------------------------------------------------------------------------


def _png_chunk(kind: bytes, body: bytes) -> bytes:
    import zlib

    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def test_pictures_pillow_encodes_pass_the_walk():
    assert walk_preview(jpeg(), "image/jpeg").width_px == 64
    assert walk_preview(png(), "image/png").height_px == 40


@pytest.mark.parametrize(
    ("make", "media_type"),
    [
        (lambda: jpeg() + b"x", "image/jpeg"),
        (lambda: jpeg()[:2] + b"\xff\xe1\x00\x08Exif\x00\x00" + jpeg()[2:], "image/jpeg"),
        (lambda: jpeg()[:2] + b"\xff\xfe\x00\x07hello" + jpeg()[2:], "image/jpeg"),
        (lambda: png()[:33] + _png_chunk(b"tEXt", b"where\x00home") + png()[33:], "image/png"),
        (lambda: png()[:33] + _png_chunk(b"iCCP", b"p\x00\x00x") + png()[33:], "image/png"),
        (lambda: png()[:33] + _png_chunk(b"acTL", b"\x00" * 8) + png()[33:], "image/png"),
        (lambda: png() + b"x", "image/png"),
        (lambda: png(2049, 1), "image/png"),
    ],
    ids=[
        "JPEG trailing byte",
        "JPEG Exif",
        "JPEG comment",
        "PNG text",
        "PNG ICC profile",
        "PNG animation",
        "PNG trailing byte",
        "PNG too wide",
    ],
)
def test_a_picture_hiding_anything_is_refused(make: Any, media_type: str):
    with pytest.raises(PreviewRefused):
        walk_preview(make(), media_type)


def test_a_jfif_thumbnail_is_refused():
    data = bytearray(jpeg())
    assert data[2:4] == b"\xff\xe0" and data[4:6] == b"\x00\x10"
    data[18:20] = b"\x01\x01"  # a 1x1 thumbnail declared in the 16-byte APP0
    with pytest.raises(PreviewRefused):
        walk_preview(bytes(data), "image/jpeg")


def test_archives_are_bounded_per_process_and_one_per_workspace():
    import uuid

    from exulanica.api.routes.workspace_style_packs import ArchiveSlots

    slots = ArchiveSlots(limit=2)
    first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert slots.take(first) is None
    assert slots.take(first) == "workspace_capacity_exhausted"
    assert slots.take(second) is None
    assert slots.take(third) == "capacity_exhausted"
    slots.give_back(first)
    assert slots.take(third) is None
