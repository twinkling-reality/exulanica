"""What a workspace's store reads of a look made elsewhere, before any database is asked.

:func:`exulanica.world.thing_store.read_admission` makes every check the store makes of a look and
its container that needs no database, and the operator's dry run asks the same. Shown here:

*   a look a deployment built is read by its container profile's reader, static or skinned, and a
    rig that breaks its plan's tree is refused;
*   a look the reader refuses, a shipped key, a look that draws no file and a container that is not
    the one the look names are each refused by name;
*   the look's label and every word of its origin are held to the line rule: a zero-width space, a
    direction override or isolate, or an accent written apart from its letter, each of which the
    look's and the origin's readers take, is refused with the field it is in;
*   a share-alike look is read only with the credit its licence asks: its attribution, its authors
    and its licence's address.

The documents built here are the store's and the command's fixtures as well.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.things.authored import container_of
from exulanica.world.thing_store import ThingStoreRefused, read_admission

from test_creature_bodies import BY

ROOT = Path(__file__).resolve().parents[1]
LOOKS = ROOT / "assets/catalogs/things/looks"


def _shipped_look(name: str) -> dict[str, Any]:
    return json.loads((LOOKS / f"{name}.v1.json").read_text(encoding="utf-8"))


def _skinned_container(document: dict[str, Any]) -> bytes:
    """The container the import receipt with the look's content digest names."""
    for receipt in sorted((ROOT / "assets/things").glob("*/*.import.json")):
        held = json.loads(receipt.read_text(encoding="utf-8"))
        if held["content_sha256"] == document["container"]["sha256"]:
            return receipt.with_name(
                receipt.name.removesuffix(".import.json") + ".glb"
            ).read_bytes()
    raise AssertionError(f"no import receipt names {document['look']}'s container")


def _imported(**licence: Any) -> dict[str, Any]:
    """An imported humanoid look, built for these tests from a shipped look's container: the
    origin a deployment's intake gives a traveller's own look, share-alike with its credit."""
    document = copy.deepcopy(_shipped_look("blocky-traveller"))
    document["look"] = "fixture-traveller-own"
    document["label"] = "a traveller's own look"
    document["origin"] = {
        "profile": "exulanica.origin/v1",
        "class": "imported",
        "by": {"kind": "project"},
        "sources": [
            {
                "reference": "a fixture figure from an outside game",
                "retrieved_on": None,
                "revision": None,
                "licence_page_sha256": None,
            }
        ],
        "licence": {
            "spdx": "CC-BY-SA-4.0",
            "verdict": "SHIP-ATTRIB",
            "attribution": "a fixture figure by its maker (CC BY-SA 4.0); changed: none",
            "share_alike": True,
            "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "licence_text_sha256": None,
            **licence,
        },
        "authors": ["its maker"],
        "lineage": {
            "ingredients": ["c" * 64],
            "receipts": [],
            "translation_manifest_sha256": None,
        },
        "distribution": "public",
    }
    return document


def _sculpted() -> tuple[dict[str, Any], bytes]:
    """A generated skinned look on a shipped plan: a shipped skinned look's container under a key
    of its own, made by a model."""
    document = copy.deepcopy(_shipped_look("kaykit-mannequin"))
    container = _skinned_container(document)
    document["look"] = "fixture-sculpted-figure"
    document["origin"] = {
        "profile": "exulanica.origin/v1",
        "class": "generated",
        "by": dict(BY),
        "sources": [],
        "licence": {
            "spdx": "CC0-1.0",
            "verdict": "SHIP",
            "attribution": None,
            "share_alike": False,
            "licence_url": None,
            "licence_text_sha256": None,
        },
        "authors": [],
        "lineage": {"ingredients": [], "receipts": ["f" * 64], "translation_manifest_sha256": None},
        "distribution": "private",
    }
    return document, container


def _crossed() -> dict[str, Any]:
    """A look that came across a bridge, made by the program the bridge is."""
    document = _imported()
    document["look"] = "fixture-crossed-figure"
    origin = document["origin"]
    origin["class"] = "crossed"
    origin["by"] = {
        "kind": "program",
        "bridge": "test-bridge",
        "adapter_version": "0.1.0",
        "mapping_sha256": "a" * 64,
        "grant_id": "00000000-0000-4000-8000-0000000000b1",
    }
    origin["lineage"]["translation_manifest_sha256"] = "b" * 64
    return document


def _refused(document: dict[str, Any], container: bytes) -> ThingStoreRefused:
    with pytest.raises(ThingStoreRefused) as refused:
        read_admission(document, container)
    return refused.value


def test_a_built_look_is_read_by_its_container_s_reader():
    static = read_admission(_imported(), container_of("blocky-traveller"))
    assert static.look.look == "fixture-traveller-own"
    assert static.container_profile == "exulanica.static-glb/v1"
    assert static.report["reader"] == "exulanica.world.static_glb.inspect_static_glb"
    document, container = _sculpted()
    skinned = read_admission(document, container)
    assert skinned.container_profile == "exulanica.skinned-glb/v1"
    assert skinned.report["joints"] > 0
    # A rig whose bones break the plan's own tree.
    broken = copy.deepcopy(document)
    bones = broken["rig"]["bones"]
    bones["hips"], bones["head"] = bones["head"], bones["hips"]
    assert _refused(broken, container).code == "look_container_refused"


def test_a_look_is_refused_by_name():
    static = container_of("blocky-traveller")
    unread = _imported()
    unread["label"] = "Not Lowercase"
    shipped = _imported()
    shipped["look"] = "blocky-traveller"
    light = copy.deepcopy(_shipped_look("spirit-light"))
    light["look"] = "fixture-light-own"
    assert _refused(unread, static).code == "look_refused"
    assert _refused(shipped, static).code == "thing_key_shipped"
    assert _refused(light, static).code == "look_without_container"
    assert _refused(_imported(), container_of("blocky-knight")).code == "look_container_mismatch"


#: Each free text a look states, by where the refusal names it.
_UNPLAIN = {
    "label": "label",
    "attribution": "origin.licence.attribution",
    "attribution-nfc": "origin.licence.attribution",
    "licence_url": "origin.licence.licence_url",
    "author": "origin.authors[0]",
    "reference": "origin.sources[0].reference",
    "revision": "origin.sources[0].revision",
    "provider": "origin.by.provider",
    "model_id": "origin.by.model_id",
    "prompt_version": "origin.by.prompt_version",
    "bridge": "origin.by.bridge",
}


def _unplain(field: str) -> tuple[dict[str, Any], bytes]:
    """A look whose one ``field`` holds what no line holds and its readers take: a zero-width
    space or joiner, a direction override or isolate, or an accent apart from its letter."""
    if field in ("provider", "model_id", "prompt_version"):
        document, container = _sculpted()
        by = document["origin"]["by"]
        document["origin"]["by"] = {**by, field: f"x​{by[field]}"}
        return document, container
    document = _crossed() if field == "bridge" else _imported()
    origin = document["origin"]
    if field == "label":
        document["label"] = "a traveller​s own look"
    elif field == "attribution":
        origin["licence"]["attribution"] = "a fixture figure by its maker‮ (CC BY-SA 4.0)"
    elif field == "attribution-nfc":
        origin["licence"]["attribution"] = "a fixture figure by its makér (CC BY-SA 4.0)"
    elif field == "licence_url":
        origin["licence"]["licence_url"] = "https://creativecommons.org/licenses/by-sa/4.0/\u200b"
    elif field == "author":
        origin["authors"] = ["its⁦ maker"]
    elif field == "reference":
        origin["sources"][0]["reference"] = "a fixture figure‍ from an outside game"
    elif field == "revision":
        origin["sources"][0]["revision"] = "r​1"
    else:
        origin["by"]["bridge"] = "test​bridge"
    return document, container_of("blocky-traveller")


@pytest.mark.parametrize("field", sorted(_UNPLAIN))
def test_a_look_s_words_are_held_to_the_line_rule(field):
    refused = _refused(*_unplain(field))
    assert refused.code == "look_text_refused"
    assert refused.detail.startswith(f"{_UNPLAIN[field]}: ")


@pytest.mark.parametrize("missing", ["attribution", "authors", "licence_url"])
def test_a_share_alike_look_is_read_only_with_its_credit(missing):
    document = _imported()
    origin = document["origin"]
    if missing == "authors":
        origin["authors"] = []
    else:
        origin["licence"][missing] = None
    if missing == "attribution":
        # A verdict that asks no attribution, so the origin's reader takes the look.
        origin["licence"]["verdict"] = "SHIP"
    assert _refused(document, container_of("blocky-traveller")).code == "look_credit_missing"
