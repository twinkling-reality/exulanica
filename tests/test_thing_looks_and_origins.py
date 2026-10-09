"""The looks this repository authors, the one origin record, and translation manifests.

What is shown here, with no database:

*   every authored look's container passes the product's own static-glTF admission, is written to
    the same bytes twice, and is the container its look document pins; a blocky figure stands its
    15 required joints at the scene root, named by the VRM humanoid bones, unrotated and unscaled;
    and a static look lies inside its kind's box;
*   the origin record refuses by name what its rules forbid, and each origin vocabulary that
    already exists reads into it;
*   a translation manifest accounts for every field of its source exactly once, and one of the
    second profile says in words, held to the line rule, what each field became; a look's import
    names its look by key and version, the look naming the manifest by digest;
*   a rigged look may state where each of its plan's sockets is and how fast its moving clips go.
"""

from __future__ import annotations

import copy
import hashlib
import json
import struct
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.documents import read_json
from exulanica.things.authored import AUTHORED_LOOKS, container_of, nodes_of
from exulanica.things.catalogs import thing_catalogs
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.things.lines import LineRefused, check_line
from exulanica.things.looks import LookRefused, read_look
from exulanica.things.manifests import ManifestRefused, check_accounting, read_manifest
from exulanica.things.origin import ADAPTER_VERSION as ORIGIN_ADAPTER_VERSION
from exulanica.things.origin import OriginRefused, read_origin
from exulanica.things.pieces import write_container
from exulanica.things.vocabularies import (
    OWN_WORK,
    origin_of_catalog_entry,
    origin_of_character_family,
    origin_of_generated_piece,
    origin_of_reviewed_import,
    origin_of_style_pack,
    origin_of_workspace_asset,
    origin_of_world_kind,
)
from exulanica.world.deciders import ADAPTER_VERSION as DECIDER_ADAPTER_VERSION
from exulanica.world.static_glb import inspect_static_glb

ROOT = Path(__file__).resolve().parents[1]
LOOKS = ROOT / "assets/catalogs/things/looks"


def _document(data: bytes) -> dict[str, Any]:
    """The JSON chunk of a binary glTF, read here apart from the writer under test."""
    length, kind = struct.unpack("<II", data[12:20])
    assert kind == 0x4E4F534A
    return json.loads(data[20 : 20 + length])


@pytest.mark.parametrize("look", sorted(AUTHORED_LOOKS))
def test_an_authored_look_s_container_is_admitted_reproducible_and_pinned(look):
    data = container_of(look)
    inspect_static_glb(data)  # refuses with StaticGlbRefused anything the profile does not admit
    assert write_container(nodes_of(look)) == data
    pinned = read_json(LOOKS / f"{look}.v1.json")["container"]
    assert pinned == {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "media_type": "model/gltf-binary",
    }


@pytest.mark.parametrize("look", ["blocky-traveller", "blocky-knight", "blocky-hoplite"])
def test_a_blocky_figure_stands_every_required_joint_at_the_root_by_its_bone_name(look):
    document = _document(container_of(look))
    roots = [document["nodes"][index] for index in document["scenes"][0]["nodes"]]
    joints = {node["name"].removeprefix("bone:"): node for node in roots}
    assert all(node["name"].startswith("bone:") for node in roots)
    plan = thing_catalogs().plan("humanoid/v1")
    assert set(plan.required_bones) <= set(joints)
    assert set(joints) <= plan.bone_names
    for node in roots:
        assert "rotation" not in node and "scale" not in node and "matrix" not in node
    # In glTF's frame: +Y up, the character facing +Z with its left at +X.
    assert joints["head"]["translation"][1] > joints["hips"]["translation"][1] > 0
    assert joints["leftHand"]["translation"][0] > 0 > joints["rightHand"]["translation"][0]


@pytest.mark.parametrize(
    ("look", "kind"),
    [
        ("primitive-sword", "sword"),
        ("primitive-lantern", "lantern"),
        ("primitive-well", "well"),
        ("primitive-gate", "gate"),
    ],
)
def test_a_static_look_lies_inside_its_kind_s_box(look, kind):
    document = _document(container_of(look))
    box = shipped_thing_kinds()[(kind, 1)].document["body"]["box_mm"]
    for accessor in document["accessors"]:
        if "min" not in accessor:
            continue
        # glTF X = -x, Y = z, Z = y, in metres.
        low, high = accessor["min"], accessor["max"]
        assert max(abs(low[0]), abs(high[0])) * 1000 <= box["width"] / 2 + 1
        assert max(abs(low[2]), abs(high[2])) * 1000 <= box["depth"] / 2 + 1
        assert low[1] * 1000 >= -1 and high[1] * 1000 <= box["height"] + 1


def _origin(**changes: Any) -> dict[str, Any]:
    record = {
        "profile": "exulanica.origin/v1",
        "class": "imported",
        "by": {"kind": "project"},
        "sources": [
            {
                "reference": "https://example.org/pack",
                "retrieved_on": "2026-10-06",
                "revision": None,
                "licence_page_sha256": None,
            }
        ],
        "licence": {
            "spdx": "CC0-1.0",
            "verdict": "SHIP",
            "attribution": None,
            "share_alike": False,
            "licence_url": None,
            "licence_text_sha256": None,
        },
        "authors": ["A Maker"],
        "lineage": {"ingredients": [], "receipts": [], "translation_manifest_sha256": None},
        "distribution": "public",
    }
    for path, value in changes.items():
        target = record
        *parents, last = path.split("__")
        for parent in parents:
            target = target[parent]
        target[last] = value
    return record


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"sources": []}, id="imported-from-nowhere"),
        pytest.param({"class": "crossed", "by": {"kind": "project"}}, id="crossed-by-a-project"),
        pytest.param(
            {
                "class": "crossed",
                "by": {
                    "kind": "program",
                    "bridge": "luanti",
                    "adapter_version": "alex.smith",
                    "mapping_sha256": "b" * 64,
                    "grant_id": str(uuid.UUID(int=3)),
                },
                "lineage__translation_manifest_sha256": "c" * 64,
            },
            id="a-name-as-an-adapter-version",
        ),
        pytest.param(
            {
                "class": "crossed",
                "by": {
                    "kind": "program",
                    "bridge": "luanti",
                    "adapter_version": "0.1.0",
                    "mapping_sha256": "b" * 64,
                    "grant_id": str(uuid.UUID(int=3)),
                },
            },
            id="crossed-with-no-manifest",
        ),
        pytest.param({"class": "generated"}, id="generated-by-a-project"),
        pytest.param({"licence__attribution": "A Maker"}, id="cc0-with-attribution"),
        pytest.param({"licence__share_alike": True}, id="share-alike-on-cc0"),
        pytest.param(
            {
                "licence__spdx": "CC-BY-SA-3.0",
                "licence__verdict": "SHIP-ATTRIB",
                "licence__attribution": "A Maker",
            },
            id="share-alike-licence-unmarked",
        ),
        pytest.param(
            {"class": "uploaded", "by": {"kind": "account", "account_id": str(uuid.UUID(int=4))}},
            id="an-upload-made-public",
        ),
        pytest.param({"distribution": "everywhere"}, id="no-such-distribution"),
        pytest.param(
            {"class": "authored", "licence__spdx": OWN_WORK, "licence__verdict": "USE-ONLY"},
            id="a-person-s-own-work-made-public",
        ),
        pytest.param(
            {
                "class": "authored",
                "licence__spdx": "LicenseRef-Exulanica-Workspace-Private",
                "licence__verdict": "USE-ONLY",
            },
            id="bytes-baked-for-one-workspace-made-public",
        ),
        pytest.param({"licence__verdict": "BLOCKED"}, id="a-blocked-licence"),
    ],
)
def test_the_origin_record_refuses_what_its_rules_forbid(changes):
    read_origin(_origin())  # the positive control
    with pytest.raises(OriginRefused):
        read_origin(_origin(**copy.deepcopy(changes)))


def test_a_crossing_s_maker_is_the_program_it_came_through_at_a_numbered_adapter_version():
    crossed = _origin(
        **{
            "class": "crossed",
            "sources": [],
            "by": {
                "kind": "program",
                "bridge": "luanti",
                "adapter_version": "0.1.0",
                "mapping_sha256": "b" * 64,
                "grant_id": str(uuid.UUID(int=3)),
            },
            "lineage__translation_manifest_sha256": "c" * 64,
        }
    )
    assert read_origin(crossed).klass == "crossed"
    # One grammar for an adapter's version wherever it is recorded: the origin's and a receipt's.
    assert ORIGIN_ADAPTER_VERSION.pattern == DECIDER_ADAPTER_VERSION.pattern


def test_a_share_alike_look_carries_its_attribution_and_is_marked():
    record = _origin(
        licence__spdx="CC-BY-SA-3.0",
        licence__verdict="SHIP-ATTRIB",
        licence__attribution="Minetest Game contributors, CC BY-SA 3.0",
        licence__share_alike=True,
    )
    assert read_origin(record).share_alike


def test_each_origin_vocabulary_that_exists_reads_into_the_one_record():
    farm = read_json(ROOT / "tests/fixtures/world-kinds/fixture-farm.json")
    assert origin_of_world_kind(farm).klass == farm["origin"]
    # The cases file holds refused manifests too, a float among them, so it is read as plain JSON.
    cases = json.loads((ROOT / "assets/style-packs/manifest-cases.v1.json").read_text("utf-8"))[
        "cases"
    ]
    packs = [case["manifest"] for case in cases if case["name"].startswith("a complete pack")]
    drafted = [case["manifest"] for case in cases if case["name"].startswith("a pack drafted")]
    assert origin_of_style_pack(packs[0]).klass == "authored"
    drafted_origin = origin_of_style_pack(drafted[0])
    assert drafted_origin.klass == "drafted"
    assert drafted_origin.document["by"]["model_id"] == drafted[0]["provenance"]["model_id"]
    hoodie = read_json(ROOT / "assets/characters/quaternius-modular-v2/hoodie.import.json")
    imported = origin_of_reviewed_import(hoodie)
    assert imported.klass == "imported" and imported.spdx == "CC0-1.0"
    assert imported.document["sources"][0]["reference"] == hoodie["source_url"]
    bench = next(
        entry
        for entry in read_json(ROOT / "assets/catalogs/world-objects/world-object.v3.json")[
            "entries"
        ]
        if entry["key"] == "bench"
    )
    assert origin_of_catalog_entry(bench["licence"]).klass == "authored"
    # The people a routine person is drawn as: imported, under the licence text the catalog pins.
    characters = ROOT / "assets/characters"
    family = json.loads((characters / "catalog.json").read_text("utf-8"))["families"][0]
    definition = json.loads(
        (characters / family["licence"]["file"]).with_name("definition.json").read_text("utf-8")
    )
    people = origin_of_character_family(family, definition)
    assert people.klass == "imported" and people.spdx == family["licence"]["id"]
    assert people.document["licence"]["licence_text_sha256"] == family["licence"]["sha256"]
    assert read_json(LOOKS / "people-catalog.v1.json")["origin"] == dict(people.document)
    receipt = {
        "origin": "generated",
        "truth": "invented",
        "licence": "CC0-1.0",
        "request_sha256": "c" * 64,
    }
    generated = origin_of_generated_piece(receipt, distribution="private")
    assert generated.klass == "generated" and generated.document["lineage"]["receipts"]
    own = origin_of_workspace_asset(
        {"basis": "own_work", "licence_id": None, "attribution": None, "source_reference": None},
        account_id=uuid.UUID(int=5),
    )
    assert own.spdx == OWN_WORK and own.document["distribution"] == "private"
    licensed = origin_of_workspace_asset(
        {
            "basis": "licensed",
            "licence_id": "CC-BY-4.0",
            "attribution": "Somebody, CC BY 4.0",
            "source_reference": "a page they named",
        },
        account_id=uuid.UUID(int=5),
    )
    assert licensed.document["licence"]["verdict"] == "SHIP-ATTRIB"


def _manifest(fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "profile": "exulanica.translation-manifest/v1",
        "translator": {"key": "luanti-player", "version": 1, "sha256": "d" * 64},
        "source": {"format": "luanti", "type": "player", "sha256": "e" * 64},
        "target": {"kind": {"kind": "visitor", "version": 1, "sha256": "f" * 64}, "look": None},
        "fields": fields,
    }


_SOURCE = {"name": "a player", "hp": 20, "skin": {"texture": "player.png"}, "inventory": ["sword"]}
_ACCOUNTED = [
    {
        "path": "/name",
        "disposition": "dropped",
        "to": None,
        "reason": "a person's name never crosses",
    },
    {"path": "/hp", "disposition": "dropped", "to": None, "reason": "this world has no health"},
    {
        "path": "/skin",
        "disposition": "approximated",
        "to": "/look",
        "reason": "a 64 by 32 skin drawn as rigid parts on named bones; elbows do not bend",
    },
    {"path": "/inventory/0", "disposition": "exact", "to": "/holds/hand.right", "reason": None},
]


def test_a_manifest_accounts_for_every_source_field_exactly_once():
    manifest = read_manifest(_manifest(_ACCOUNTED))
    check_accounting(manifest, _SOURCE)  # the positive control
    assert manifest.paths("dropped") == ("/name", "/hp")
    for broken in (
        _ACCOUNTED[1:],  # a field left out
        [
            *_ACCOUNTED,
            {
                "path": "/skin/texture",
                "disposition": "opaque",
                "to": None,
                "reason": "kept by the game",
            },
        ],  # one accounted twice
        [
            *_ACCOUNTED,
            {"path": "/mana", "disposition": "dropped", "to": None, "reason": "no mana here"},
        ],  # one the source lacks
    ):
        with pytest.raises(ManifestRefused):
            check_accounting(read_manifest(_manifest(broken)), _SOURCE)


@pytest.mark.parametrize(
    "field",
    [
        pytest.param(
            {"path": "/hp", "disposition": "exact", "to": "/hp", "reason": "why"},
            id="exact-with-a-reason",
        ),
        pytest.param(
            {"path": "/hp", "disposition": "dropped", "to": None, "reason": None},
            id="dropped-with-no-reason",
        ),
        pytest.param(
            {"path": "/hp", "disposition": "approximated", "to": None, "reason": "x"},
            id="carried-nowhere",
        ),
        pytest.param(
            {"path": "hp", "disposition": "dropped", "to": None, "reason": "x"}, id="not-a-pointer"
        ),
    ],
)
def test_a_manifest_field_is_refused_by_name_where_its_shape_is_wrong(field):
    with pytest.raises(ManifestRefused):
        read_manifest(_manifest([field]))


def test_a_line_is_one_plain_line_within_its_bound():
    assert check_line("Take it, traveller. It is yours.") == "Take it, traveller. It is yours."
    assert check_line("x" * 200) == "x" * 200
    for refused in (
        "",
        "x" * 201,
        "two\nlines",
        " padded",
        "padded ",
        "Cafe\u0301",  # not in normal form C
        "hidden\u200btext",  # a format character
        "private\ue000use",
        "tab\there",
        42,
    ):
        with pytest.raises(LineRefused):
            check_line(refused)


def _worded(fields: list[dict[str, Any]], words: dict[str, str]) -> dict[str, Any]:
    return {
        **_manifest([{**field, "words": words[field["path"]]} for field in fields]),
        "profile": "exulanica.translation-manifest/v2",
    }


_WORDS = {
    "/name": "A player's name, which stays at home",
    "/hp": "Health, which this world does not keep",
    "/skin": "A skin, which arrives as rigid parts on a figure",
    "/inventory/0": "A sword, which arrives held in the right hand",
}


def test_a_second_profile_manifest_says_in_words_what_each_field_became():
    manifest = read_manifest(_worded(_ACCOUNTED, _WORDS))
    check_accounting(manifest, _SOURCE)  # the positive control
    assert manifest.document["fields"][2]["words"] == _WORDS["/skin"]
    # A manifest of the first profile states no words and is read as it was written.
    read_manifest(_manifest(_ACCOUNTED))
    for broken in (
        {**_WORDS, "/hp": "two\nlines"},
        {**_WORDS, "/hp": "x" * 201},
        {**_WORDS, "/hp": "Cafe\u0301"},
    ):
        with pytest.raises(ManifestRefused):
            read_manifest(_worded(_ACCOUNTED, broken))
    unworded = _worded(_ACCOUNTED, _WORDS)
    del unworded["fields"][0]["words"]
    with pytest.raises(ManifestRefused):
        read_manifest(unworded)


def test_a_look_s_import_names_its_look_by_key_and_version_alone():
    imported = {
        **_worded(_ACCOUNTED, _WORDS),
        "target": {"kind": None, "look": {"look": "kaykit-knight", "version": 1}},
    }
    read_manifest(imported)  # the positive control
    for target in (
        {"kind": None, "look": None},
        {"kind": None, "look": {"look": "kaykit-knight", "version": 1, "sha256": "a" * 64}},
        {"kind": None, "look": {"look": "Kaykit", "version": 1}},
    ):
        with pytest.raises(ManifestRefused):
            read_manifest({**imported, "target": target})
    # The first profile always names its kind.
    with pytest.raises(ManifestRefused):
        read_manifest({**_manifest(_ACCOUNTED), "target": imported["target"]})


def _skinned(**rig: Any) -> dict[str, Any]:
    plan = thing_catalogs().plan("humanoid/v1")
    assert plan is not None
    origin = read_json(LOOKS / "blocky-knight.v1.json")["origin"]
    return {
        "profile": "exulanica.look/v1",
        "look": "test-skinned",
        "version": 1,
        "label": "test figure",
        "body_plan": "humanoid/v1",
        "look_kind": "skinned",
        "container": {"sha256": "a" * 64, "bytes": 1024, "media_type": "model/gltf-binary"},
        "rig": {
            "bones": {bone: f"joint_{bone}" for bone in plan.required_bones},
            "clips": {"idle": "Idle_A", "walk": "Walking_A", "run": "Running_A"},
            **rig,
        },
        "height_mm": 1800,
        "sampling": "linear",
        "light": None,
        "role": None,
        "origin": origin,
    }


def test_a_rigged_look_states_its_sockets_and_the_ground_speed_of_its_moving_clips():
    sockets = {"hand.right": "handslot.r", "hand.left": "handslot.l"}
    speeds = {"walk": 500, "run": 2380}
    read_look(_skinned())  # neither is required
    read_look(_skinned(sockets=sockets, ground_speed_mm_per_s=speeds))  # the positive control
    for rig in (
        {"sockets": {"hand.middle": "handslot.m"}},  # not one of the plan's sockets
        {"sockets": {"hand.right": "handslot", "hand.left": "handslot"}},  # one joint twice
        {"sockets": {}},
        {"ground_speed_mm_per_s": {"idle": 10}},  # idle carries nobody anywhere
        {"ground_speed_mm_per_s": {"walk": 0}},
        {"ground_speed_mm_per_s": {"walk": 10_001}},
        {"ground_speed_mm_per_s": {"walk": 500.5}},
        {"tails": {}},  # a key a rig does not state
    ):
        with pytest.raises(LookRefused):
            read_look(_skinned(**rig))
    # A speed is stated only for a moving clip the rig has.
    walker = _skinned(ground_speed_mm_per_s={"run": 2380})
    del walker["rig"]["clips"]["run"]
    with pytest.raises(LookRefused):
        read_look(walker)
