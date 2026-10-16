"""Placed volumes stand apart: a new site world on a landscape is refused by name and path when two
placements' rock meets at a point of the grid laid over where their reaches (each volume's extent,
turned by its yaw and moved to its origin) meet; reaches that meet with their rock apart compose,
and a world made before is never held to it."""

from __future__ import annotations

import copy

import pytest
from exulanica.grammar.landscape import (
    LandscapeRefused,
    check_volumes_apart,
    placement_reach,
    read_landscape_document,
)
from exulanica.world.composers import site_plan
from exulanica.world.kinds.worker import compose_job
from exulanica.world.landscape_drawing import landscape_drawing

from test_landscape_document import BAY, ROCK
from test_landscape_world import WORLD, bay, compose
from test_landscape_world import on_land as imported_on_land  # noqa: F401
from test_site_land import kind

#: The stack's reach unturned at the bay's first origin, and how far it stands out east of it.
FIRST = read_landscape_document(BAY).placements[0]
REACH = placement_reach(FIRST)
HALF = REACH[1][0] - FIRST.at_mm[0]
WEST = ("west", ROCK, [30000, 40000, -3000], 0)
#: A long low wall, unweathered, 30 m east to west and 4 m thick.
WALL = {
    "profile": "exulanica.volume/v1",
    "id": "wall",
    "parts": [{"id": "body", "shape": "box", "size_mm": [30000, 4000, 8000]}],
}
SEED = "landscape spacing"


@pytest.fixture(name="on_land", scope="module")
def _on_land_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_on_land")


def _placed(*placements: tuple[str, dict, list[int], int]) -> dict:
    """The bay with volumes at the stated origins and turns."""
    raw = copy.deepcopy(BAY)
    raw["volumes"] = [
        {"id": name, "volume": volume, "at_mm": at_mm, "yaw_mdeg": yaw}
        for name, volume, at_mm, yaw in placements
    ]
    return raw


def _apart(*placements: tuple[str, dict, list[int], int]) -> None:
    check_volumes_apart(read_landscape_document(_placed(*placements)), SEED)


def _overlap(*placements: tuple[str, dict, list[int], int]) -> LandscapeRefused:
    with pytest.raises(LandscapeRefused) as caught:
        _apart(*placements)
    assert caught.value.code == "landscape_volumes_overlap"
    return caught.value


def _beside(on_land, east_mm: int, north_mm: int = 0) -> dict:  # type: ignore[no-untyped-def]
    """The farm's bay with a second stack ``east_mm`` east and ``north_mm`` north of the first."""
    raw = bay(on_land)
    first = raw["volumes"][0]
    x, y, z = first["at_mm"]
    raw["volumes"].append({**first, "id": "second", "at_mm": [x + east_mm, y + north_mm, z]})
    return raw


@pytest.fixture(scope="module")
def apart(on_land):  # type: ignore[no-untyped-def]
    return compose(landscape=_beside(on_land, 2 * HALF + 1000))


def test_placements_whose_reaches_stand_apart_compose(apart):
    receipt = apart.receipt
    assert [placed["id"] for placed in receipt["landscape"]["volumes"]] == ["stack", "second"]
    site_plan.check_receipt(receipt)


def test_reaches_that_meet_with_their_rock_apart_compose(on_land):
    # Corner to corner: the reaches share a corner 1.6 m square, where neither stack has rock.
    diagonal = _beside(on_land, 2 * HALF - 1600, 2 * HALF - 1600)
    first, second = read_landscape_document(diagonal).placements
    low, high = placement_reach(first)[1], placement_reach(second)[0]
    assert all(high[axis] < low[axis] for axis in range(2))
    assert compose(landscape=diagonal).receipt["landscape"]["volumes"][1]["id"] == "second"
    # The wall's end stands inside the stack's reach, beyond its rock: the wall is rock there and
    # the stack is not.
    _apart(("wall", WALL, [51000, 48000, -3000], 0), ("stack", ROCK, [30000, 40000, -3000], 0))


def test_rock_through_rock_is_refused_naming_both_and_the_point_by_the_later_path(on_land):
    with pytest.raises(LandscapeRefused) as caught:
        compose(landscape=_beside(on_land, 5000))
    refused = caught.value
    assert (refused.code, refused.path) == ("landscape_volumes_overlap", "landscape.volumes[1]")
    assert refused.detail.startswith("second and stack (volumes[0]) are both rock at (")
    # The later of the two is named, and the earlier one it meets, past one standing apart.
    refused = _overlap(
        WEST, ("east", ROCK, [90000, 40000, -3000], 0), ("near", ROCK, [36000, 40000, -3000], 0)
    )
    assert refused.path == "volumes[2]"
    assert refused.detail.startswith("near and west (volumes[0]) are both rock at")


def test_the_refusal_reaches_a_client_by_code_and_path_from_the_kind_worker(on_land):
    found = kind("farm")
    answer = compose_job(
        "workspace:spacing",
        dict(found.document),
        found.values(found.presets[0][0]),
        WORLD,
        None,
        None,
        _beside(on_land, 5000),
    )
    assert (answer["status"], answer["code"], answer["path"]) == (
        "landscape_refused",
        "landscape_volumes_overlap",
        "landscape.volumes[1]",
    )


def test_a_turn_moves_rock_into_rock():
    # North of the stack and running east to west, the wall's reach meets the stack's by 2 mm
    # with its rock 0.3 m clear; turned a quarter it runs north to south through the stack.
    _apart(WEST, ("wall", WALL, [30000, 49300, -3000], 0))
    assert _overlap(WEST, ("wall", WALL, [30000, 49300, -3000], 90000)).path == "volumes[1]"


def test_rock_over_rock_with_air_between_stands_apart():
    (_, _, low), (_, _, high) = REACH
    # Directly over the first stack, the floating one's reach starts 1 m above the first's top.
    lift = high - low + 1000
    _apart(WEST, ("above", ROCK, [30000, 40000, -3000 + lift], 0))
    # Reaches that touch, rock apart by the weathering's reach.
    _apart(WEST, ("above", ROCK, [30000, 40000, -3000 + lift - 1000], 0))
    # Lowered 3 m into the first stack's top, rock meets rock.
    sunk = ("sunk", ROCK, [30000, 40000, -3000 + 11000 - 3000], 0)
    assert _overlap(WEST, sunk).path == "volumes[1]"


def test_rock_is_judged_weathered_as_its_landscape_seed_realizes_it():
    # 11 m apart the stacks' trunks stand clear by less than their weathering: under one
    # landscape seed their rock meets at a grid point, under another it does not.
    raw = _placed(WEST, ("east", ROCK, [41000, 40000, -3000], 0))
    landscape = read_landscape_document(raw, volume_rules=2)
    check_volumes_apart(landscape, "weathering 0")
    with pytest.raises(LandscapeRefused):
        check_volumes_apart(landscape, "weathering 11")


def test_a_world_made_with_rock_through_rock_still_reads_and_draws(on_land, apart):
    """A receipt is never held to the rule: a world whose volumes meet reads and draws as made."""
    meeting = read_landscape_document({**_beside(on_land, 5000), "finest_cell_mm": 4000})
    with pytest.raises(LandscapeRefused):
        check_volumes_apart(meeting, SEED)
    receipt = copy.deepcopy(apart.receipt)
    receipt["landscape"] = meeting.canonical()
    receipt["landscape_sha256"] = meeting.sha256
    site_plan.check_receipt(receipt)
    drawn, bodies = landscape_drawing(WORLD, receipt, "0" * 64, "1" * 64)
    assert [placed["id"] for placed in drawn["volumes"]] == ["stack", "second"]
    for placed in drawn["volumes"]:
        assert placed["chunks"] and placed["tops"]
        assert {entry["sha256"] for entry in [*placed["chunks"], *placed["tops"]]} <= set(bodies)
