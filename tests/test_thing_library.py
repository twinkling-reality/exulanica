"""The shipped thing library: read once, every container held to the digest its look pins.

Expected values come from the committed files (a kind or look is served as the canonical JSON of
its file's document, the body plans catalog as its file) and from the sources a container is made
by (the authored looks' writer, the reviewed assets), never from the library under test. Each
refusal is a copy of the committed looks with one thing broken, and the unbroken copy loads, so
every refusal is the broken thing's.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.documents import read_json
from exulanica.things.authored import AUTHORED_LOOKS, container_of
from exulanica.world.assets import reviewed_assets
from exulanica.world.thing_library import (
    BODY_PLANS,
    LIBRARY_PROFILE,
    LOOKS_DIRECTORY,
    ThingLibraryRefused,
    load_thing_library,
)

ROOT = Path(__file__).resolve().parents[1]
KINDS = ROOT / "assets/catalogs/things/kinds"
LOOKS = ROOT / "assets/catalogs/things/looks"


def _documents(directory: Path) -> dict[str, dict]:
    return {path.name: read_json(path) for path in sorted(directory.glob("*.v*.json"))}


def _digest(document: dict) -> str:
    return hashlib.sha256(canonical_json(document)).hexdigest()


def test_the_listing_names_every_shipped_kind_and_look_with_its_container() -> None:
    library = load_thing_library()
    assert LOOKS_DIRECTORY == LOOKS
    listing = library.listing()
    assert listing["profile"] == LIBRARY_PROFILE
    kinds = _documents(KINDS)
    assert [f"{k['kind']}.v{k['version']}.json" for k in listing["kinds"]] == sorted(kinds)
    for entry in listing["kinds"]:
        document = kinds[f"{entry['kind']}.v{entry['version']}.json"]
        assert entry == {
            "kind": document["kind"],
            "version": document["version"],
            "sha256": _digest(document),
            "label": document["label"],
            "class": document["class"],
            "body_plan": document["body"]["plan"],
            "looks": document["looks"],
        }
    looks = _documents(LOOKS)
    assert [f"{k['look']}.v{k['version']}.json" for k in listing["looks"]] == sorted(looks)
    for entry in listing["looks"]:
        document = looks[f"{entry['look']}.v{entry['version']}.json"]
        assert entry == {
            "look": document["look"],
            "version": document["version"],
            "sha256": _digest(document),
            "label": document["label"],
            "body_plan": document["body_plan"],
            "look_kind": document["look_kind"],
            "container": document["container"],
        }
    assert listing["body_plans"] == {"sha256": hashlib.sha256(BODY_PLANS.read_bytes()).hexdigest()}


def test_it_serves_each_document_and_container_by_digest_and_nothing_else() -> None:
    library = load_thing_library()
    served = {item.sha256 for item in library.content}
    expected = set()
    for document in [*_documents(KINDS).values(), *_documents(LOOKS).values()]:
        item = library.content.get(_digest(document))
        assert item is not None and item.media_type == "application/json"
        assert json.loads(item.data) == document
        expected.add(item.sha256)
    plans = library.content.get(hashlib.sha256(BODY_PLANS.read_bytes()).hexdigest())
    assert plans is not None and plans.data == BODY_PLANS.read_bytes()
    expected.add(plans.sha256)
    furniture = {asset.content_sha256: asset.payload for asset in reviewed_assets()}
    made = 0
    for document in _documents(LOOKS).values():
        container = document["container"]
        if container is None:
            continue
        item = library.content.get(container["sha256"])
        assert item is not None and item.media_type == container["media_type"]
        assert len(item.data) == container["bytes"]
        if document["look"] in AUTHORED_LOOKS:
            assert item.data == container_of(document["look"])
            made += 1
        else:
            assert item.data == furniture[container["sha256"]]
        expected.add(item.sha256)
    # The positive control: authored and furniture containers both reach the library.
    assert 0 < made < len(expected)
    assert served == expected


def _copy(tmp_path: Path) -> Path:
    looks = tmp_path / "looks"
    shutil.copytree(LOOKS, looks)
    return looks


def _write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def test_an_imported_container_is_read_by_the_digest_its_look_pins(tmp_path: Path) -> None:
    looks = _copy(tmp_path)
    gate = read_json(looks / "primitive-gate.v1.json")
    data = container_of("primitive-gate") + b"\0\0\0\0"
    imported = {
        **gate,
        "look": "imported-gate",
        "label": "imported gate",
        "container": {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "media_type": "model/gltf-binary",
        },
    }
    _write(looks / "imported-gate.v1.json", imported)
    packs = tmp_path / "things"
    (packs / "a-pack").mkdir(parents=True)
    with pytest.raises(ThingLibraryRefused, match="no source gives the container look imported"):
        load_thing_library(looks_directory=looks, imported_directory=packs)
    (packs / "a-pack" / "gate.glb").write_bytes(data)
    library = load_thing_library(looks_directory=looks, imported_directory=packs)
    item = library.content.get(imported["container"]["sha256"])
    assert item is not None and item.data == data


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (
            lambda looks: _repin(looks / "primitive-well.v1.json", "e" * 64),
            "look primitive-well's container is not the one it pins",
        ),
        (
            lambda looks: _repin(looks / "bench.v1.json", "e" * 64),
            "no source gives the container look bench pins",
        ),
        (
            lambda looks: (looks / "primitive-well.v1.json").rename(
                looks / "primitive-well.v2.json"
            ),
            "primitive-well.v2.json does not name the look and version it states",
        ),
        (
            lambda looks: (looks / "primitive-well.v1.json").unlink(),
            "kind well version 1 suggests look primitive-well version 1",
        ),
    ],
    ids=["an-authored-pin", "a-furniture-pin", "a-misnamed-file", "a-suggested-look-missing"],
)
def test_a_broken_look_refuses_the_library_naming_it(tmp_path: Path, break_it, message) -> None:
    looks = _copy(tmp_path)
    load_thing_library(looks_directory=looks)  # the positive control: the unbroken copy loads
    break_it(looks)
    with pytest.raises(ThingLibraryRefused, match=message):
        load_thing_library(looks_directory=looks)


def _repin(path: Path, sha256: str) -> None:
    document = read_json(path)
    document["container"] = {**document["container"], "sha256": sha256}
    _write(path, document)
