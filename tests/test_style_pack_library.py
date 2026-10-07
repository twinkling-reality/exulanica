"""The committed style pack library: read once, held to its digests, refused whole when broken.

Expected values come from the committed files themselves (each manifest file is its canonical JSON
and one newline, so its digest is the SHA-256 of the file without that newline), never from the
loader under test. Each refusal is a copy of the committed library with one thing broken, and the
unbroken copy loads, so every refusal is the broken thing's.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from exulanica.world.committed_content import (
    CommittedContent,
    CommittedContentRefused,
    ServedItem,
)
from exulanica.world.style_pack_library import (
    LIBRARY_DIRECTORY,
    LIST_PROFILE,
    StylePackLibraryRefused,
    load_style_pack_library,
)
from exulanica.world.style_packs import load_context

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "assets" / "style-packs" / "packs"
CONTEXT = load_context(ROOT)


def _committed() -> dict[str, tuple[dict, bytes]]:
    """Each committed pack's manifest and its canonical bytes, read from the files."""
    found = {}
    for folder in sorted(PACKS.iterdir()):
        text = (folder / "manifest.json").read_bytes()
        assert text.endswith(b"\n")
        found[folder.name] = (json.loads(text), text[:-1])
    return found


def _copy(tmp_path: Path) -> Path:
    library = tmp_path / "packs"
    shutil.copytree(PACKS, library)
    return library


def _load(library: Path):
    return load_style_pack_library(library, CONTEXT)


def test_the_library_is_the_committed_folders_each_listed_with_its_licence() -> None:
    library = load_style_pack_library()
    assert LIBRARY_DIRECTORY == PACKS
    committed = _committed()
    listing = library.listing()
    assert listing["profile"] == LIST_PROFILE
    assert [pack["pack_id"] for pack in listing["packs"]] == sorted(committed)
    for entry in listing["packs"]:
        manifest, canonical = committed[entry["pack_id"]]
        assert entry["manifest_sha256"] == hashlib.sha256(canonical).hexdigest()
        assert entry["version"] == manifest["version"]
        assert entry["licence"] == manifest["licence"]
        assert entry["authors"] == manifest["authors"]
        assert entry["origin"] == manifest["origin"]
        assert entry["files"] == len(manifest["files"])
        assert entry["total_bytes"] == len(canonical) + sum(f["bytes"] for f in manifest["files"])
        picture = (PACKS / entry["pack_id"] / manifest["preview"]).read_bytes()
        assert entry["preview_sha256"] == hashlib.sha256(picture).hexdigest()
        assert entry["preview_media_type"] == "image/jpeg"
        assert library.content.get(entry["preview_sha256"]).data == picture


def test_it_serves_each_manifest_and_listed_file_by_digest_and_nothing_else() -> None:
    library = load_style_pack_library()
    expected: dict[str, tuple[str, bytes]] = {}
    for folder, (manifest, canonical) in _committed().items():
        expected[hashlib.sha256(canonical).hexdigest()] = ("application/json", canonical)
        for file in manifest["files"]:
            data = (PACKS / folder / file["path"]).read_bytes()
            expected[hashlib.sha256(data).hexdigest()] = (file["media_type"], data)
    assert len(library.content) == len(expected)
    for digest, (media_type, data) in expected.items():
        item = library.content.get(digest)
        assert item is not None, digest
        assert (item.media_type, item.data) == (media_type, data)
    assert library.content.get("0" * 64) is None


def test_an_unbroken_copy_loads_and_folder_notes_are_passed_over(tmp_path: Path) -> None:
    library = _copy(tmp_path)
    (library / ".DS_Store").write_bytes(b"notes")
    (library / "exulanica.cozy-town" / ".DS_Store").write_bytes(b"notes")
    loaded = _load(library)
    assert [pack.pack_id for pack in loaded.packs] == sorted(_committed())
    assert hashlib.sha256(b"notes").hexdigest() not in loaded.content


@pytest.mark.parametrize(
    ("breakage", "named"),
    [
        ("piece_bytes", "pieces/tree.glb is not the bytes its manifest states"),
        ("piece_missing", "lists pieces/tree.glb, which is not a file in its folder"),
        ("piece_unlisted", "holds pieces/extra.glb, which its manifest does not list"),
        ("piece_symlink", "lists pieces/tree.glb, which is not a file in its folder"),
        ("folder_name", "its folder is not named by its pack id exulanica.cozy-town"),
        ("manifest_layout", "not written as its canonical JSON and one newline"),
        ("manifest_rule", "its manifest is refused"),
        ("stray_file", "is not a pack folder"),
    ],
)
def test_one_broken_pack_refuses_the_library_naming_it(
    tmp_path: Path, breakage: str, named: str
) -> None:
    library = _copy(tmp_path)
    cozy = library / "exulanica.cozy-town"
    manifest = json.loads((cozy / "manifest.json").read_text())
    if breakage == "piece_bytes":
        data = bytearray((cozy / "pieces/tree.glb").read_bytes())
        data[-1] ^= 1
        (cozy / "pieces/tree.glb").write_bytes(bytes(data))
    elif breakage == "piece_missing":
        (cozy / "pieces/tree.glb").unlink()
    elif breakage == "piece_unlisted":
        (cozy / "pieces/extra.glb").write_bytes((cozy / "pieces/tree.glb").read_bytes())
    elif breakage == "piece_symlink":
        moved = tmp_path / "tree.glb"
        (cozy / "pieces/tree.glb").rename(moved)
        (cozy / "pieces/tree.glb").symlink_to(moved)
    elif breakage == "folder_name":
        cozy.rename(library / "exulanica.cosy-town")
    elif breakage == "manifest_layout":
        (cozy / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=1) + "\n")
    elif breakage == "manifest_rule":
        manifest["licence"] = {"id": "CC-BY-4.0", "attribution": None}
        (cozy / "manifest.json").write_text(_canonical(manifest) + "\n")
    elif breakage == "stray_file":
        (library / "notes.txt").write_text("not a pack")
    with pytest.raises(StylePackLibraryRefused) as refused:
        _load(library)
    assert named in str(refused.value)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _derived(library: Path, base: dict) -> None:
    """A pack ``exulanica.derived-town`` over ``base``: the cozy pack's own content renamed."""
    source = library / "exulanica.cozy-town"
    derived = library / "exulanica.derived-town"
    shutil.copytree(source, derived)
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["pack_id"] = "exulanica.derived-town"
    manifest["base"] = base
    (derived / "manifest.json").write_text(_canonical(manifest) + "\n")


def test_a_base_must_be_a_pack_of_the_library_at_its_version_and_digest(tmp_path: Path) -> None:
    manifest, canonical = _committed()["exulanica.cozy-town"]
    stated = {
        "pack_id": "exulanica.cozy-town",
        "version": manifest["version"],
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    library = _copy(tmp_path / "named")
    _derived(library, stated)
    assert _load(library).pack("exulanica.derived-town") is not None
    for wrong in (
        {**stated, "pack_id": "exulanica.nowhere-town"},
        {**stated, "version": manifest["version"] + 1},
        {**stated, "manifest_sha256": "0" * 64},
    ):
        library = _copy(
            tmp_path / wrong["pack_id"] / str(wrong["version"]) / wrong["manifest_sha256"]
        )
        _derived(library, wrong)
        with pytest.raises(StylePackLibraryRefused, match="is not a pack of the library"):
            _load(library)


def test_the_default_is_the_pack_the_library_file_names_and_only_it_is_listed_so() -> None:
    named = json.loads((ROOT / "assets" / "style-packs" / "library.v1.json").read_text("utf-8"))
    assert named["profile"] == "exulanica.style-pack-library/v1"
    library = load_style_pack_library()
    assert library.default == named["default"] == library.default_pack.pack_id
    listed = {pack["pack_id"]: pack["default"] for pack in library.listing()["packs"]}
    assert listed == {pack_id: pack_id == named["default"] for pack_id in _committed()}


COMMITTED_DEFAULT = {"profile": "exulanica.style-pack-library/v1", "default": "exulanica.cozy-town"}


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"default": "exulanica.nowhere-town"}, "not a pack of the library"),
        ({"profile": "exulanica.style-pack-library/v2"}, "a profile and a default, nothing else"),
        ({"fallback": "exulanica.toon-town"}, "a profile and a default, nothing else"),
    ],
)
def test_a_default_that_is_not_a_pack_or_a_file_of_another_shape_refuses_the_library(
    tmp_path: Path, change: dict, named: str
) -> None:
    library_file = tmp_path / "library.v1.json"
    # The positive control: the committed default, written here, loads.
    library_file.write_text(json.dumps(COMMITTED_DEFAULT))
    assert load_style_pack_library(PACKS, CONTEXT, library_file).default == "exulanica.cozy-town"
    library_file.write_text(json.dumps({**COMMITTED_DEFAULT, **change}))
    with pytest.raises(StylePackLibraryRefused, match=named):
        load_style_pack_library(PACKS, CONTEXT, library_file)


def test_committed_content_holds_bytes_to_their_digest_and_one_media_type() -> None:
    data = b"piece"
    digest = hashlib.sha256(data).hexdigest()
    item = ServedItem(digest, "model/gltf-binary", data)
    held = CommittedContent([item, item])
    assert len(held) == 1
    assert held.get(digest) == item
    with pytest.raises(CommittedContentRefused, match="hash to another digest"):
        CommittedContent([ServedItem(digest, "model/gltf-binary", b"other")])
    with pytest.raises(CommittedContentRefused, match="stated as model/gltf-binary and as"):
        CommittedContent([item, ServedItem(digest, "application/json", data)])
    with pytest.raises(CommittedContentRefused, match="not a SHA-256"):
        CommittedContent([ServedItem(digest.upper(), "model/gltf-binary", data)])
