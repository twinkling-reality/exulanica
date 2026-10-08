"""The Luanti adapter (``bridges/luanti``) against the door and the thing catalogs, with no game.

CI has no Luanti, so what can be held without it is held here, each against a source other than the
adapter's own code:

*   each mapping file meets the door's own checks (``exulanica.door.mapping``), with every game
    field the adapter declares it reads accounted for, and every published profile of it (v1
    naming looks by digest, v2 by the library's reference) means the same looks through the door's
    own reader;
*   every thing kind it names exists in the catalogs at that version and the item kinds can be held;
    a CC0 look is one the library ships, with the licence the catalog records; the share-alike look
    (a player's own picture, built at a deployment and never committed) states its credit and the
    picture's digest the builder pins, and the builder makes a look the thing contract reads from
    any 64 by 32 picture, putting the picture's left on the character's right;
*   at most one game item per kind travels out, so a departing thing's game item is never a guess;
*   the mod decides nothing for a character that crossed: in a recorded run it posted only its
    hello, its arrivals and its delivery reports, each valid against the door's own request models,
    and every frame it received has the fields the door's frame builders write;
*   nothing kept with the adapter looks like a channel credential or an invite code.

Each guard is shown to refuse a mutant first.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import re
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

import pytest
from exulanica.api.routes.door import ArrivalBody, DeliveryBody, HelloBody
from exulanica.canonical import sha256_of_canonical
from exulanica.door.crossings import _look_reference
from exulanica.door.mapping import MappingRefused, check_mapping, check_reads
from exulanica.door.protocol import (
    arrival_refused_frame,
    arrived_frame,
    asked_frame,
    departed_frame,
    grant_ended_frame,
    grant_frame,
    outcome_frame,
)
from exulanica.things.lines import check_line
from exulanica.things.looks import read_look
from exulanica.things.origin import read_origin
from exulanica.world.deciders import ADAPTER_VERSION
from exulanica.world.placed_things import named_kind
from exulanica.world.thing_looks import LookReference, ThingLookRefused, check_crossing_look

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "bridges" / "luanti"
MOD = ADAPTER / "mod" / "exulanica_gate"
MAPPINGS = sorted((MOD / "mapping").glob("*.json"))
KINDS = ROOT / "assets" / "catalogs" / "things" / "kinds"
LOOKS = ROOT / "assets" / "catalogs" / "things" / "looks"
FIXTURES = sorted((ADAPTER / "fixtures").glob("*.jsonl"))


def _adapter() -> dict[str, Any]:
    return json.loads((MOD / "adapter.json").read_text())


def _reads(adapter: dict[str, Any], mapping: dict[str, Any]) -> list[str]:
    """What the mod sends as its reads: the declared fields and every item its mapping lists."""
    return list(adapter["reads"]) + [item["game_item"] for item in mapping["items"]]


def _document(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text())
    return loaded.get("document", loaded)


def test_there_is_a_mapping_for_the_game_the_demo_runs():
    """Each published version stays beside the next: a deployment pinning either keeps working."""
    assert [path.name for path in MAPPINGS] == [
        "luanti-minetest-game.v1.json",
        "luanti-minetest-game.v2.json",
    ]


def _look_digest(named: str | dict[str, Any]) -> str:
    """A mapping's look as a digest: ``sha256:<digest>`` in v1, ``{look, version, sha256}``
    in v2."""
    return named["sha256"] if isinstance(named, dict) else named.removeprefix("sha256:")


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda path: path.name)
def test_the_mapping_meets_the_doors_own_checks(path):
    mapping = json.loads(path.read_text())
    check_mapping(mapping)
    reads = _reads(_adapter(), mapping)
    assert check_reads(mapping, reads) == frozenset(reads)


def test_the_doors_checks_refuse_a_mapping_that_loses_a_field_silently():
    """The guard on the guard: dropping the player's name from never_crosses, or reading a field
    the mapping does not account for, is refused by the door's checks."""
    mapping = json.loads(MAPPINGS[0].read_text())
    nameless = {
        **mapping,
        "never_crosses": [
            entry for entry in mapping["never_crosses"] if entry["field"] != "player name"
        ],
    }
    with pytest.raises(MappingRefused):
        check_mapping(nameless)
    with pytest.raises(MappingRefused):
        check_reads(mapping, [*_reads(_adapter(), mapping), "player health bar"])


def _kind(key: str, version: int) -> dict[str, Any]:
    path = KINDS / f"{key}.v{version}.json"
    assert path.exists(), f"the mapping names kind {key} v{version}, which the catalog lacks"
    return _document(path)


def _looks_by_digest() -> dict[str, dict[str, Any]]:
    looks = {}
    for path in LOOKS.glob("*.json"):
        document = _document(path)
        looks[sha256_of_canonical(document).hex()] = document
    return looks


@functools.cache
def _builder() -> Any:
    """``bridges/luanti/tools/build_look.py``, the only maker of the share-alike look, loaded once
    under a name of its own (its dataclasses resolve their annotations through ``sys.modules``)."""
    spec = importlib.util.spec_from_file_location(
        "luanti_build_look", ADAPTER / "tools" / "build_look.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda path: path.name)
def test_every_kind_and_look_the_mapping_names_is_in_the_catalogs(path):
    mapping = json.loads(path.read_text())
    looks = _looks_by_digest()
    builder = _builder()
    for visitor in mapping["visitors"]:
        kind = _kind(visitor["kind"]["key"], visitor["kind"]["version"])
        assert kind["class"] == "being"
        for look in visitor["looks"]:
            digest = _look_digest(look["look"])
            licence = look["licence"]
            if licence["spdx"] == "CC0-1.0":
                assert digest in looks, f"no look in the catalog has digest {digest}"
                catalogued = looks[digest]
                assert catalogued["body_plan"] == kind["body"]["plan"]
                assert catalogued["origin"]["licence"]["spdx"] == "CC0-1.0"
                continue
            # A player's own picture: built at a deployment, never in the library, credited.
            assert digest not in looks
            assert licence["spdx"] == "CC-BY-SA-3.0" and licence["share_alike"] is True
            assert "Jordach" in licence["attribution"]
            assert licence["licence_url"] == "https://creativecommons.org/licenses/by-sa/3.0/"
            assert look["source_sha256"] == builder.PICTURE_SHA256
    for item in mapping["items"]:
        kind = _kind(item["kind"]["key"], item["kind"]["version"])
        assert "holdable" in {offer["key"] for offer in kind["offers"]}, item["game_item"]


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda path: path.name)
def test_the_adapter_names_looks_its_mapping_lists(path):
    adapter = _adapter()
    mapping = json.loads(path.read_text())
    listed = {look["look_key"]: look for look in mapping["visitors"][0]["looks"]}
    assert set(adapter["looks"]["by_texture"].values()) <= set(listed)
    # Any picture the adapter does not name arrives in a look free of any obligation.
    assert listed[adapter["looks"]["otherwise"]]["licence"]["spdx"] == "CC0-1.0"


def _worn(kind: Any, named: str | dict[str, Any]) -> LookReference | str:
    """What the door makes of a mapping's look for a visitor of ``kind``: the look it wears, or
    the code it refuses the arrival with."""
    reference = {"kind": kind.kind, "version": kind.version, "sha256": kind.sha256}
    try:
        return check_crossing_look(reference, _look_reference(named))
    except ThingLookRefused as refused:
        return refused.code


def test_every_mapping_profile_means_the_same_looks_through_the_doors_reader():
    """v1 names a look by its digest and v2 by the library's reference: through the door's own
    reader each look key comes to the same look in both, the CC0 look the library ships and the
    player's own look refused until a world's store holds it (the traveller then arrives in the
    CC0 look)."""
    worn: dict[str, dict[str, LookReference | str]] = {}
    for path in MAPPINGS:
        mapping = json.loads(path.read_text())
        for visitor in mapping["visitors"]:
            kind = named_kind(visitor["kind"]["key"], visitor["kind"]["version"])
            for look in visitor["looks"]:
                worn.setdefault(look["look_key"], {})[path.name] = _worn(kind, look["look"])
    blocky = _document(LOOKS / "blocky-traveller.v1.json")
    assert worn == {
        "cc0-traveller": dict.fromkeys(
            [path.name for path in MAPPINGS],
            LookReference("blocky-traveller", 1, sha256_of_canonical(blocky).hex()),
        ),
        "default-skin": dict.fromkeys([path.name for path in MAPPINGS], "look_not_shipped"),
    }


def _png(width: int, height: int, pixel: Any) -> bytes:
    """An 8-bit RGBA PNG, unfiltered, from ``pixel(u, v)``."""
    rows = b"".join(
        b"\x00" + b"".join(bytes(pixel(u, v)) for u in range(width)) for v in range(height)
    )

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


#: A marked pixel: the top left of the head's front in the legacy layout (u 8, v 8).
MARK = (250, 10, 10, 255)


def _synthetic_picture(builder: Any) -> Any:
    def pixel(u: int, v: int) -> tuple[int, int, int, int]:
        if (u, v) == (8, 8):
            return MARK
        return (40 + u * 3, 60 + v * 5, 90, 255)

    width, height, pixels = builder.read_png(_png(64, 32, pixel))
    return builder.Picture(width, height, pixels)


def test_the_builder_makes_a_look_the_thing_contract_reads():
    builder = _builder()
    nodes = builder.figure(_synthetic_picture(builder))
    assert [node.name for node in nodes] == [f"bone:{bone}" for bone in builder.JOINTS]
    container = builder.write_container(nodes)
    assert container == builder.write_container(builder.figure(_synthetic_picture(builder)))
    document = builder.look_document(container, 1722)
    read_look(document)
    origin = read_origin(document["origin"])
    assert origin.share_alike and origin.spdx == "CC-BY-SA-3.0"
    for text in (
        document["origin"]["licence"]["attribution"],
        document["origin"]["sources"][0]["reference"],
        *document["origin"]["authors"],
    ):
        assert check_line(text, maximum=200) == text


def test_the_pictures_left_is_the_characters_right():
    """The legacy layout is drawn as seen facing the character: the head front's top left pixel
    lies on the character's right (+x here, the character facing +y with its left at -x), at the
    top of its face."""
    builder = _builder()
    marked = "#{:02x}{:02x}{:02x}".format(*MARK[:3])
    nodes = builder.figure(_synthetic_picture(builder))
    [head] = [node for node in nodes if node.name == "bone:head"]
    [part] = [part for part in head.parts if part.colour == marked]
    xs = [head.at_mm[0] + vertex[0] for vertex in part.vertices_mm]
    zs = [head.at_mm[2] + vertex[2] for vertex in part.vertices_mm]
    ys = {head.at_mm[1] + vertex[1] for vertex in part.vertices_mm}
    assert min(xs) >= 3 * builder.P and max(xs) == 4 * builder.P
    assert max(zs) == 32 * builder.P and min(zs) >= 31 * builder.P
    assert ys == {4 * builder.P}


def test_the_builder_refuses_any_other_picture(tmp_path):
    """The guard on the guard: a game folder whose picture is not the pinned one builds nothing."""
    builder = _builder()
    folder = tmp_path / "minetest_game"
    (folder / builder.PICTURE).parent.mkdir(parents=True)
    (folder / builder.PICTURE).write_bytes(_png(64, 32, lambda u, v: (1, 2, 3, 255)))
    (folder / builder.LICENCE_FILE).write_text("a licence file")
    with pytest.raises(SystemExit, match="no other skin is used"):
        builder.build(folder)


def test_the_catalog_check_refuses_a_look_it_does_not_hold():
    """The guard on the guard: a digest no catalogued look has is not found."""
    assert ("0" * 64) not in _looks_by_digest()


def _outbound_kinds(mapping: dict[str, Any]) -> list[str]:
    return [
        f"{item['kind']['key']}.v{item['kind']['version']}"
        for item in mapping["items"]
        if item["ways"] in ("out", "both")
    ]


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda path: path.name)
def test_at_most_one_game_item_per_kind_travels_out(path):
    outbound = _outbound_kinds(json.loads(path.read_text()))
    assert len(outbound) == len(set(outbound))


def test_two_outbound_items_of_one_kind_are_seen():
    """The guard on the guard."""
    mapping = json.loads(MAPPINGS[0].read_text())
    doubled = {
        **mapping,
        "items": [*mapping["items"], {**mapping["items"][0], "game_item": "default:sword_twin"}],
    }
    outbound = _outbound_kinds(doubled)
    assert len(outbound) != len(set(outbound))


def test_the_adapter_version_meets_the_decider_rule():
    assert ADAPTER_VERSION.fullmatch(_adapter()["adapter_version"])


def _exchanges() -> list[dict[str, Any]]:
    found = []
    for path in FIXTURES:
        for line in path.read_text().splitlines():
            entry = json.loads(line)
            if entry.get("exchange"):
                found.append(entry)
    return found


def test_fixtures_were_recorded_from_a_real_run():
    exchanges = _exchanges()
    paths = {entry["path"].split("?")[0] for entry in exchanges}
    assert {"/door/channel/hello", "/door/channel/frames", "/door/channel/arrivals"} <= paths


#: Everything the mod posts, with the door's request model for it (a departure's path names it).
#: It never answers an ask or says its player is gone: the world decides for a character that
#: crossed, and the character lives on when its player leaves the game.
REQUEST_MODELS = {
    "/door/channel/hello": HelloBody,
    "/door/channel/arrivals": ArrivalBody,
    "/door/channel/departures/*/delivered": DeliveryBody,
}


def _route(path: str) -> str:
    parts = path.split("/")
    if parts[1:4] == ["door", "channel", "departures"] and len(parts) == 6:
        parts[4] = "*"
    return "/".join(parts)


def test_every_request_the_mod_sent_meets_the_doors_request_models():
    checked = set()
    for entry in _exchanges():
        if entry["method"] != "POST":
            continue
        route = _route(entry["path"])
        assert route in REQUEST_MODELS, f"the mod posted to {route}"
        REQUEST_MODELS[route].model_validate(json.loads(entry["request_text"]))
        checked.add(route)
    assert checked == set(REQUEST_MODELS)


#: The fields each frame kind carries, as the door's own builders write them.
FRAME_FIELDS = {
    "asked": set(
        asked_frame(
            ask_seq=1,
            request={
                "request_id": "r",
                "document_sha256": "d",
                "subject_id": "s",
                "base_tick": 1,
                "context": {},
                "provider_config": {},
            },
            instruction="i",
            choice_description="c",
            deadline_ms=1,
            messages=[],
            act={},
            idle_label=None,
        )
    ),
    "outcome": set(outcome_frame(ask_seq=1, request_id="r", status="s", reason="r")),
    "arrived": set(arrived_frame(arrival_id="a", thing_id="t", carried=[])),
    "arrival_refused": set(arrival_refused_frame(arrival_id="a", reason="r")),
    "departed": set(departed_frame(departure_id="d", thing_id="t", why="w", carried=[])),
    "grant": set(grant_frame(grant_seq=1, scope={})),
    "grant_ended": set(grant_ended_frame(grant_id="g", grant_seq=1, reason="r")),
}
#: Fields the door added to a frame kind after these fixtures were recorded. A frame grows only by
#: optional fields, so a recorded frame may lack one, and the mod reads none of them as required.
ADDED_SINCE_RECORDED: dict[str, set[str]] = {"asked": {"idle_label"}}


def test_every_frame_the_mod_read_has_the_fields_the_door_writes():
    kinds = set()
    for entry in _exchanges():
        if not entry["path"].startswith("/door/channel/frames") or entry["status"] != 200:
            continue
        for frame in json.loads(entry["response_text"])["frames"]:
            written = FRAME_FIELDS[frame["kind"]]
            assert set(frame) <= written, frame["kind"]
            assert written - set(frame) <= ADDED_SINCE_RECORDED.get(frame["kind"], set()), frame[
                "kind"
            ]
            kinds.add(frame["kind"])
    assert {"grant", "arrived", "departed", "grant_ended"} <= kinds


#: A channel credential is 32 random bytes as URL-safe base64 (43 characters); an invite is 16
#: characters of Crockford base32 in four groups.
CREDENTIAL = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])")
INVITE = re.compile(r"(?<![0-9A-Z])[0-9A-HJKMNP-TV-Z]{4}(-[0-9A-HJKMNP-TV-Z]{4}){3}(?![0-9A-Z])")


def _secret_shaped(text: str) -> list[str]:
    return [match.group(0) for match in CREDENTIAL.finditer(text)] + [
        match.group(0) for match in INVITE.finditer(text)
    ]


def test_the_secret_search_finds_one_where_one_is_written():
    """The guard on the guard."""
    assert _secret_shaped("Bearer " + "A" * 21 + "_" + "b" * 21)
    assert _secret_shaped("code 7KQ2-M9TX-4HZP-R1WD")
    assert not _secret_shaped("sha256 " + "0" * 64)


def test_nothing_kept_with_the_adapter_looks_like_a_credential_or_an_invite():
    offenders = {
        str(path.relative_to(ROOT)): found
        for path in ADAPTER.rglob("*")
        if path.is_file() and (found := _secret_shaped(path.read_text(errors="replace")))
    }
    assert offenders == {}
