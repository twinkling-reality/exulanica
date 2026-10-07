"""Every shipped skinned look passes the skinned container profile's reader.

The reader is ``exulanica_pieces.skinned.read_skinned_glb``, the one creature looks are read by.
Each shipped look of kind ``skinned`` is read from the container its import receipt names, found by
content digest, with its rig's bones and its body plan's parents: a container that breaks the
profile, or a rig whose bones do not keep the plan's tree, is refused by name. At least one such
look ships. No database and no source archive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.things.catalogs import thing_catalogs
from exulanica_pieces.canonical import Refused
from exulanica_pieces.skinned import read_skinned_glb

ROOT = Path(__file__).resolve().parents[1]
LOOKS = ROOT / "assets/catalogs/things/looks"
IMPORTED = ROOT / "assets/things"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _skinned_looks() -> list[dict[str, Any]]:
    return [
        doc
        for doc in (_json(path) for path in sorted(LOOKS.glob("*.json")))
        if doc["look_kind"] == "skinned"
    ]


def _container(doc: dict[str, Any]) -> bytes:
    """The container the import receipt with the look's content digest names."""
    for receipt in sorted(IMPORTED.glob("*/*.import.json")):
        if _json(receipt)["content_sha256"] == doc["container"]["sha256"]:
            return receipt.with_name(
                receipt.name.removesuffix(".import.json") + ".glb"
            ).read_bytes()
    raise AssertionError(f"no import receipt names {doc['look']}'s container")


def _parents(doc: dict[str, Any]) -> dict[str, str | None]:
    plan = thing_catalogs().plan(doc["body_plan"])
    assert plan is not None, doc["body_plan"]
    return {bone.name: bone.parent for bone in plan.bones}


def test_a_skinned_look_ships():
    assert _skinned_looks()


@pytest.mark.parametrize("look", [f"{doc['look']}.v{doc['version']}" for doc in _skinned_looks()])
def test_every_shipped_skinned_look_passes_the_skinned_container_reader(look):
    doc = _json(LOOKS / f"{look}.json")
    container = read_skinned_glb(
        _container(doc), bones=doc["rig"]["bones"], plan_parents=_parents(doc)
    )
    assert set(container.clips) == set(doc["rig"]["clips"].values())
    assert container.bytes == doc["container"]["bytes"]


def test_a_rig_that_breaks_the_plan_s_tree_is_refused():
    doc = _skinned_looks()[0]
    payload, parents = _container(doc), _parents(doc)
    bones = dict(doc["rig"]["bones"])
    read_skinned_glb(payload, bones=bones, plan_parents=parents)  # the positive control
    bones["hips"], bones["head"] = bones["head"], bones["hips"]
    with pytest.raises(Refused, match="does not hang from its plan parent"):
        read_skinned_glb(payload, bones=bones, plan_parents=parents)
