"""One reader and one rule for the published texture manifest.

``exulanica.materials.manifest`` states the rule; the resolver in ``exulanica.world.texture_assets``
and the grammar's ``exulanica.grammar.textures`` both read through it. So every refusal below is
checked three ways and must carry the same words each way, and the published manifest must read to
the same pins through both modules. The comparisons a manifest and a container header are held to
are type-strict: ``true`` is not ``1``, which Python's ``==`` would otherwise let through.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.textures import (
    MANIFEST_PATH,
    TEXTURE_SET_ID,
    TextureSet,
    require_texture_set_id,
)
from exulanica.grammar.textures import read_texture_manifest as read_grammar_manifest
from exulanica.materials import (
    CONTAINER_LAYOUT,
    MaterialObjectError,
    freeze,
    identical,
    read_texture_manifest,
)
from exulanica.materials.manifest import SET_ID, SET_ID_PATTERN
from exulanica.world.texture_assets import (
    TEXTURE_DIRECTORY,
    TextureCatalogError,
    decode_texture_set,
    load_texture_catalog,
)

MANIFEST = TEXTURE_DIRECTORY / "manifest.json"
METAL = "cc0.storefront-metal"


def _document() -> dict:
    return json.loads(MANIFEST.read_bytes())


def _compact(document: object) -> bytes:
    """Canonical for these documents, and still writable when a case plants a float."""
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")


def test_the_published_manifest_reads_back_to_its_own_bytes():
    raw = MANIFEST.read_bytes()
    entries = read_texture_manifest(raw)
    assert len(entries) == 8
    rebuilt = {"profile": "exulanica.texture-manifest/v1", "sets": []}
    rebuilt["sets"] = [entry.as_entry() for entry in entries.values()]
    assert canonical_json(rebuilt) == raw


def test_grammar_and_the_resolver_pin_the_same_sets():
    assert MANIFEST_PATH == MANIFEST
    pinned = load_texture_catalog().sets
    assert read_grammar_manifest() == {
        set_id: TextureSet(pinned_set.set_id, pinned_set.version, pinned_set.content_sha256)
        for set_id, pinned_set in pinned.items()
    }


def _entry(document: dict) -> dict:
    return document["sets"][0]


CASES = [
    (lambda doc: doc["sets"].reverse(), "sorted by set_id"),
    (lambda doc: doc["sets"].insert(1, dict(doc["sets"][0])), "sorted by set_id"),
    (lambda doc: doc.update(sets=[]), "non-empty list"),
    (lambda doc: doc.update(sets={}), "non-empty list"),
    (lambda doc: doc.update(note=1), "exactly profile and sets"),
    (lambda doc: doc.update(profile="exulanica.texture-manifest/v2"), "profile is"),
    (lambda doc: _entry(doc).update(note=1), "keys other than exactly"),
    (lambda doc: _entry(doc).update(set_id="Cc0.Brick"), "is not a texture set id"),
    (lambda doc: _entry(doc).update(set_id="cc0.brick\n"), "a string the baker cannot write"),
    (lambda doc: _entry(doc).update(set_id="cc0.brick_bond"), "is not a texture set id"),
    (lambda doc: _entry(doc).update(version=0), "positive integers"),
    (lambda doc: _entry(doc).update(version=True), "positive integers"),
    (lambda doc: _entry(doc).update(byte_size=0), "positive integers"),
    (lambda doc: _entry(doc).update(content_sha256="A" * 64), "content_sha256 is 64"),
    (lambda doc: _entry(doc).update(licence_sha256="short"), "licence_sha256 is 64"),
    (lambda doc: _entry(doc).update(resolution={"width": 16}), "positive width and height"),
    (lambda doc: _entry(doc).update(resolution={"width": 0, "height": 8}), "positive width"),
    (lambda doc: _entry(doc).update(extent_mm={"u": 1800}), "whole-millimetre u and v"),
    (lambda doc: _entry(doc).update(extent_mm={"u": True, "v": 1}), "whole-millimetre u and v"),
    (lambda doc: _entry(doc).update(channels=4), "container layout"),
    (lambda doc: _entry(doc)["channels"].reverse(), "container layout"),
    (lambda doc: _entry(doc)["channels"][0].update(srgb=1), "container layout"),
    (lambda doc: _entry(doc)["channels"][3].update(components=True), "container layout"),
    (lambda doc: _entry(doc)["channels"][3].update(decode="linear"), "container layout"),
    (lambda doc: _entry(doc).update(licence_id="CC-BY-4.0"), "published sets only"),
    (
        lambda doc: _entry(doc).update(licence_id="LicenseRef-Exulanica-Workspace-Private"),
        "published sets only",
    ),
    (lambda doc: _entry(doc).update(version=0.5), "fraction or an exponent"),
]


@pytest.mark.parametrize(("change", "message"), CASES)
def test_every_reader_refuses_a_manifest_outside_the_rule_in_the_same_words(
    tmp_path, change, message
):
    document = _document()
    change(document)
    raw = _compact(document)
    with pytest.raises(MaterialObjectError, match=message) as refused:
        read_texture_manifest(raw)
    words = str(refused.value)

    path = tmp_path / "manifest.json"
    path.write_bytes(raw)
    with pytest.raises(CatalogError) as grammar:
        read_grammar_manifest(path)
    assert str(grammar.value) == words

    # The resolver reads the manifest before anything else, so the directory needs nothing more.
    directory = tmp_path / "textures"
    directory.mkdir()
    (directory / "manifest.json").write_bytes(raw)
    with pytest.raises(TextureCatalogError) as resolver:
        load_texture_catalog(directory)
    assert str(resolver.value) == words


@pytest.mark.parametrize(
    "raw",
    [
        lambda good: good + b"\n",
        lambda good: json.dumps(json.loads(good), sort_keys=True).encode("ascii"),
        lambda good: b"\xef\xbb\xbf" + good,
    ],
)
def test_a_manifest_in_any_other_byte_form_is_refused_by_both_modules(tmp_path, raw):
    path = tmp_path / "manifest.json"
    path.write_bytes(raw(MANIFEST.read_bytes()))
    with pytest.raises(MaterialObjectError) as refused:
        read_texture_manifest(path.read_bytes())
    with pytest.raises(CatalogError) as grammar:
        read_grammar_manifest(path)
    assert str(grammar.value) == str(refused.value)


@pytest.mark.parametrize("set_id", ["cc0.brick\n", "cc0.brick ", "Cc0.brick", "1cc0", "", "-x"])
def test_the_set_id_rule_is_one_rule_and_takes_no_trailing_newline(set_id):
    assert SET_ID.fullmatch(set_id) is None
    assert re.fullmatch(SET_ID_PATTERN, set_id) is None
    assert TEXTURE_SET_ID is SET_ID
    with pytest.raises(CatalogError):
        require_texture_set_id("set_id", set_id)


def test_a_missing_manifest_is_a_catalog_error_rather_than_an_empty_library(tmp_path):
    with pytest.raises(CatalogError, match="cannot read"):
        read_grammar_manifest(tmp_path / "manifest.json")


def test_the_layout_is_the_published_channels():
    assert [texture_map.as_channel() for texture_map in CONTAINER_LAYOUT] == _entry(_document())[
        "channels"
    ]


@pytest.mark.parametrize(
    ("left", "right", "same"),
    [
        ({"a": 1, "b": [True, None]}, {"b": [True, None], "a": 1}, True),
        (freeze({"a": [1, {"b": "c"}]}), {"a": [1, {"b": "c"}]}, True),
        (True, 1, False),
        (1, True, False),
        (0, False, False),
        ({"a": 1}, {"a": True}, False),
        ([1, 2], [1, 2, 3], False),
        ({"a": 1}, {"a": 1, "b": 2}, False),
        ("1", 1, False),
        (None, 0, False),
        ([], {}, False),
    ],
)
def test_documents_are_compared_as_json_rather_than_as_python(left, right, same):
    assert identical(left, right) is same


def test_python_equality_is_the_looser_rule_being_replaced():
    assert {"depth_mm": True} == {"depth_mm": 1}
    assert not identical({"depth_mm": True}, {"depth_mm": 1})


def _reencode(payload: bytes, change) -> bytes:
    """The container with its header changed, its padding and every map offset recomputed."""
    length = int.from_bytes(payload[4:8], "little")
    header = json.loads(payload[8 : 8 + length])
    old_start = -(-(8 + length) // 16) * 16
    body = payload[old_start:]
    change(header)
    while True:
        encoded = canonical_json(header)
        start = -(-(8 + len(encoded)) // 16) * 16
        cursor = start
        moved = False
        for entry in header["maps"]:
            if entry["byte_offset"] != cursor:
                entry["byte_offset"] = cursor
                moved = True
            cursor += entry["byte_length"]
        if not moved:
            break
    padding = b" " * (start - 8 - len(encoded))
    return b"LTX1" + len(encoded).to_bytes(4, "little") + encoded + padding + body


def _published_container() -> bytes:
    entry = _entry(_document())
    return (TEXTURE_DIRECTORY / "blobs" / f"{entry['content_sha256']}.ltex").read_bytes()


def test_the_reencoder_reproduces_an_unchanged_container():
    payload = _published_container()
    assert _reencode(payload, lambda header: None) == payload
    decode_texture_set(payload)


@pytest.mark.parametrize(
    "change",
    [
        lambda header: header["maps"][3].update(components=True),
        lambda header: header["maps"][0].update(srgb=1),
        lambda header: header["maps"][1].update(holds=["normal_x", "normal_y"]),
        lambda header: header["maps"][2].update(name="rma"),
    ],
)
def test_a_container_that_states_its_packing_any_other_way_is_refused(change):
    with pytest.raises(TextureCatalogError, match="is not packed as declared"):
        decode_texture_set(_reencode(_published_container(), change))


def test_a_container_may_describe_its_maps_beyond_their_packing():
    def describe(header: dict) -> None:
        header["maps"][3]["decode"] = "linear height, 0 is the lowest point"

    decode_texture_set(_reencode(_published_container(), describe))


def _linked_directory(tmp_path: Path) -> Path:
    """The published directory: blobs linked, everything a test may rewrite copied.

    A test writes only files it copied or files under new names, and checks before each write that
    it is not writing through a link into the repository.
    """
    directory = tmp_path / "textures"
    (directory / "blobs").mkdir(parents=True)
    for blob in (TEXTURE_DIRECTORY / "blobs").iterdir():
        (directory / "blobs" / blob.name).symlink_to(blob)
    shutil.copytree(TEXTURE_DIRECTORY / "objects", directory / "objects")
    for name in ("manifest.json", "catalog.json"):
        (directory / name).write_bytes((TEXTURE_DIRECTORY / name).read_bytes())
    return directory


def _write(path: Path, raw: bytes) -> None:
    assert not path.is_symlink(), f"{path} links into the repository"
    path.write_bytes(raw)


def _forge_container(directory: Path, set_id: str, change) -> str:
    """Replace one set's container with a changed header, every digest that names it kept true."""
    document = json.loads((directory / "manifest.json").read_bytes())
    (entry,) = [entry for entry in document["sets"] if entry["set_id"] == set_id]
    payload = (directory / "blobs" / f"{entry['content_sha256']}.ltex").read_bytes()
    forged = _reencode(payload, change)
    digest = hashlib.sha256(forged).hexdigest()
    _write(directory / "blobs" / f"{digest}.ltex", forged)
    entry.update(content_sha256=digest, byte_size=len(forged))
    manifest_raw = canonical_json(document)
    _write(directory / "manifest.json", manifest_raw)

    index = json.loads((directory / "catalog.json").read_bytes())
    (row,) = [row for row in index["sets"] if row["set_id"] == set_id]
    receipt_path = directory / "objects" / f"{row['receipt_sha256']}.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt.update(content_sha256=digest, byte_size=len(forged))
    receipt_raw = canonical_json(receipt)
    receipt_digest = hashlib.sha256(receipt_raw).hexdigest()
    _write(directory / "objects" / f"{receipt_digest}.json", receipt_raw)
    row.update(content_sha256=digest, receipt_sha256=receipt_digest)
    index["manifest_sha256"] = hashlib.sha256(manifest_raw).hexdigest()
    catalog_raw = canonical_json(index)
    _write(directory / "catalog.json", catalog_raw)
    return hashlib.sha256(catalog_raw).hexdigest()


def test_a_forged_container_that_changes_nothing_still_loads(tmp_path):
    """The forging below is sound: with no change, the rebound directory loads behind its pin."""
    directory = _linked_directory(tmp_path)

    def describe(header: dict) -> None:
        header["maps"][3]["decode"] = "linear height, 0 is the lowest point"

    own = _forge_container(directory, METAL, describe)
    loaded = load_texture_catalog(directory, catalog_sha256=own)
    assert loaded.sets[METAL].content_sha256 != load_texture_catalog().sets[METAL].content_sha256


def test_a_header_that_says_true_where_its_manifest_says_one_is_refused(tmp_path):
    directory = _linked_directory(tmp_path)
    document = _document()
    assert _entry(document)["version"] == 1, "the planted true stands for a version of 1"
    own = _forge_container(
        directory, _entry(document)["set_id"], lambda header: header.update(version=True)
    )
    with pytest.raises(TextureCatalogError, match="header version is True, not 1"):
        load_texture_catalog(directory, catalog_sha256=own)


def test_a_header_that_says_true_where_its_recipe_says_one_is_refused(tmp_path):
    """The metal's occlusion depth is 1 mm; a header stating true for it is not its recipe."""
    directory = _linked_directory(tmp_path)
    assert load_texture_catalog().sets[METAL].height_range_mm == 1

    def plant(header: dict) -> None:
        assert header["cavity"]["depth_mm"] == 1
        header["cavity"]["depth_mm"] = True

    own = _forge_container(directory, METAL, plant)
    with pytest.raises(TextureCatalogError, match=r"header cavity is .*, but its recipe says"):
        load_texture_catalog(directory, catalog_sha256=own)


def test_the_resolver_and_grammar_read_the_rule_rather_than_restate_it():
    """Neither module keeps an entry field list or a hex pattern of its own."""
    root = Path(__file__).resolve().parents[1]
    for relative in ("exulanica/world/texture_assets.py", "exulanica/grammar/textures.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert '"licence_sha256",' not in source, relative
        assert "[0-9a-f]{64}" not in source, relative
        assert "_entry_problems" not in source, relative
