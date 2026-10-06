"""Thing kinds, their catalogs and their looks: what a kind of thing is, as data held to its checks.

What is shown here, with no database:

*   the four things catalogs read and hold to each other, and the humanoid plan is the VRM 1.0
    humanoid's 55 bones with its 15 required ones;
*   every kind and look this repository ships reads, is exactly what its script writes, and suggests
    looks of its own body plan alone;
*   a kind is refused by name for each thing its checks hold: a float, an unknown ability, an
    ability its body cannot serve, an object that acts, a routine that says something, an
    implausible offer, a look of another body, a bad origin;
*   a society reads a kind's semantics, never its looks, origin or ``ext``.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.documents import read_json
from exulanica.things.catalogs import thing_catalogs
from exulanica.things.kinds import (
    KINDS_DIRECTORY,
    THING_KIND_CODES,
    ThingKindRefused,
    read_thing_kind,
    shipped_thing_kinds,
)
from exulanica.things.looks import LookRefused, read_look

ROOT = Path(__file__).resolve().parents[1]
LOOKS_DIRECTORY = ROOT / "assets/catalogs/things/looks"
#: The VRM 1.0 humanoid's required bones, as its specification lists them (VRMC_vrm-1.0
#: humanoid.md, read 2026-10-06), written here rather than read from the catalog under test.
VRM_REQUIRED = {
    "hips",
    "spine",
    "head",
    "leftUpperLeg",
    "leftLowerLeg",
    "leftFoot",
    "rightUpperLeg",
    "rightLowerLeg",
    "rightFoot",
    "leftUpperArm",
    "leftLowerArm",
    "leftHand",
    "rightUpperArm",
    "rightLowerArm",
    "rightHand",
}


def _looks() -> dict[tuple[str, int, str], Any]:
    found = {}
    for path in sorted(LOOKS_DIRECTORY.glob("*.json")):
        look = read_look(read_json(path))
        found[(look.look, look.version, look.sha256)] = look
    return found


def _kind(key: str) -> dict[str, Any]:
    return read_json(KINDS_DIRECTORY / f"{key}.v1.json")


def test_the_humanoid_plan_is_the_vrm_humanoid():
    plan = thing_catalogs().plan("humanoid/v1")
    assert plan is not None
    assert len(plan.bones) == 55
    assert set(plan.required_bones) == VRM_REQUIRED
    assert {socket.key for socket in plan.sockets} == {"hand.right", "hand.left"}
    assert plan.socket("hand.right").bone == "rightHand"
    bodiless = thing_catalogs().plan("bodiless/v1")
    assert bodiless.bones == () and bodiless.socket("float").length_mm_maximum == 300


def test_every_shipped_kind_and_look_reads_and_suggests_looks_of_its_own_body():
    looks = _looks()
    kinds = shipped_thing_kinds()
    assert {
        "knight",
        "traveller",
        "lantern_spirit",
        "visitor",
        "villager",
        "sword",
        "lantern",
        "well",
        "gate",
        "bench",
    } <= {key for key, _version in kinds}
    for kind in kinds.values():
        for reference in kind.looks:
            look = looks[(reference["look"], reference["version"], reference["sha256"])]
            assert look.body_plan == kind.plan, (kind.kind, look.look)
        # Read again with every look resolved: the shipped kinds pass the full check.
        read_thing_kind(
            dict(kind.document),
            look_of=lambda ref: looks.get((ref["look"], ref["version"], ref["sha256"])),
        )


def test_the_shipped_kinds_and_looks_are_exactly_what_their_script_writes():
    checked = subprocess.run(
        [sys.executable, str(ROOT / "scripts/things/shipped_things.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_a_sword_is_held_in_a_hand_and_is_too_long_for_a_float_socket():
    kinds = shipped_thing_kinds()
    sword = kinds[("sword", 1)]
    longest = max(sword.document["body"]["box_mm"].values())
    hand = thing_catalogs().plan("humanoid/v1").socket("hand.right")
    floating = thing_catalogs().plan("bodiless/v1").socket("float")
    assert longest <= hand.length_mm_maximum
    assert longest > floating.length_mm_maximum
    lantern = kinds[("lantern", 1)]
    assert max(lantern.document["body"]["box_mm"].values()) <= floating.length_mm_maximum


def test_a_society_reads_a_kind_s_semantics_and_never_its_looks():
    knight = shipped_thing_kinds()[("knight", 1)]
    semantics = knight.semantics()
    assert not {"looks", "origin", "ext"} & set(semantics)
    assert semantics["reference"] == knight.reference()
    assert "look" not in json.dumps(semantics)


def _refused(document: Any, **kwargs: Any) -> ThingKindRefused:
    with pytest.raises(ThingKindRefused) as caught:
        read_thing_kind(document, **kwargs)
    assert caught.value.code in {code for code, _meaning in THING_KIND_CODES}
    return caught.value


@pytest.mark.parametrize(
    ("change", "code"),
    [
        pytest.param(lambda d: d.update(version=1.0), "thing_kind_invalid", id="a-float"),
        pytest.param(lambda d: d.update(colour="red"), "thing_kind_invalid", id="an-extra-key"),
        pytest.param(
            lambda d: d["abilities"].append({"key": "fly", "parameters": {}}),
            "thing_kind_reference_unknown",
            id="an-unknown-ability",
        ),
        pytest.param(
            lambda d: d["body"].update(height_mm={"from": 500, "to": 900}),
            "thing_kind_out_of_bounds",
            id="a-body-too-small",
        ),
        pytest.param(
            lambda d: d["routine"]["weights"].update(say=10),
            "thing_kind_body_unmet",
            id="a-routine-that-says-something",
        ),
        pytest.param(
            lambda d: d.update(moves=[]),
            "thing_kind_body_unmet",
            id="walking-abilities-with-no-way-to-move",
        ),
        pytest.param(
            lambda d: d["origin"].update({"class": "imported"}),
            "thing_kind_origin_invalid",
            id="imported-with-no-source",
        ),
    ],
)
def test_a_being_is_refused_by_name_for_each_thing_its_checks_hold(change, code):
    document = copy.deepcopy(_kind("knight"))
    read_thing_kind(copy.deepcopy(document))  # the positive control
    change(document)
    assert _refused(document).code == code


@pytest.mark.parametrize(
    ("change", "code"),
    [
        pytest.param(
            lambda d: d["abilities"].append({"key": "say", "parameters": {}}),
            "thing_kind_body_unmet",
            id="an-object-that-acts",
        ),
        pytest.param(
            lambda d: d["offers"][0]["parameters"]["grip"].update(z_mm=1200),
            "thing_kind_offer_implausible",
            id="a-grip-outside-the-box",
        ),
        pytest.param(
            lambda d: d["body"]["box_mm"].update(height=2000),
            "thing_kind_offer_implausible",
            id="holdable-and-longer-than-any-hand-holds",
        ),
        pytest.param(
            lambda d: d["offers"][0]["parameters"].update(axis="up"),
            "thing_kind_invalid",
            id="an-axis-that-is-not-one",
        ),
    ],
)
def test_an_object_is_refused_by_name_for_each_thing_its_checks_hold(change, code):
    document = copy.deepcopy(_kind("sword"))
    read_thing_kind(copy.deepcopy(document))  # the positive control
    change(document)
    assert _refused(document).code == code


def test_a_look_of_another_body_is_refused_for_a_kind():
    looks = _looks()
    document = copy.deepcopy(_kind("knight"))
    light = next(look for look in looks.values() if look.look == "spirit-light")
    document["looks"] = [light.reference()]
    refused = _refused(
        document, look_of=lambda ref: looks.get((ref["look"], ref["version"], ref["sha256"]))
    )
    assert refused.code == "thing_kind_look_unfit"


def test_a_look_is_refused_where_its_kind_does_not_draw_it():
    document = read_json(LOOKS_DIRECTORY / "spirit-light.v1.json")
    read_look(copy.deepcopy(document))  # the positive control
    for change in (
        {"body_plan": "humanoid/v1"},
        {"container": {"sha256": "a" * 64, "bytes": 10, "media_type": "model/gltf-binary"}},
        {"light": None},
        {"sampling": "cubic"},
    ):
        with pytest.raises(LookRefused):
            read_look({**copy.deepcopy(document), **change})
