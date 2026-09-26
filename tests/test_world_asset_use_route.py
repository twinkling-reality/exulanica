"""What the registry reads say inhabitants do with each placeable kind, and where.

``GET /world/assets`` and ``GET /world/assets/{asset_key}`` carry each kind's use: its places, the
way a person standing at each faces, and the seat a resting person is drawn on. The page draws
people from this, so it must say what the catalog file states and what the society's registry rows
fill. The expected values here are worked out from those two, not read from the fields the route
reads: the places from the society's own registry row (its ``[x, -y]`` places), the facing from
each row's side, and each seat from the row's stated point, the place's offset along the row and
the top of the box part the file puts under it.

Each row also carries what inhabitants do there and how long they stay, which the page says under
the chosen kind. That is worked out here from the purposeful routine's own file, the version a new
society input records, read as JSON rather than through the routine loader the route calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.api.world_version_document import object_activity_view, object_use_view
from exulanica.world.object_catalog import CATALOG_DIRECTORY, CATALOG_VERSION
from exulanica.world.society_catalogs import (
    PURPOSEFUL_CATALOG,
    PURPOSEFUL_ROUTINE_VERSIONS,
    ROUTINE_DIRECTORY,
)
from exulanica.world.society_composition import (
    PLACES_FIELD,
    REVIEWED_REACH_MM,
    reviewed_affordance_registry,
)

import test_world_objects_api as helpers

objects_api = helpers.objects_api
pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = json.loads((CATALOG_DIRECTORY / f"world-object.v{CATALOG_VERSION}.json").read_text())
ENTRIES = {entry["asset_key"]: entry for entry in DOCUMENT["entries"]}
#: A person standing along a side faces across it, toward the kind.
ACROSS = {"+y": "-y", "-y": "+y", "+x": "-x", "-x": "+x"}
#: The purposeful routine a new society input records, as its file states it.
ROUTINE = json.loads(
    (
        ROUTINE_DIRECTORY
        / f"{PURPOSEFUL_CATALOG}.v{PURPOSEFUL_ROUTINE_VERSIONS[PURPOSEFUL_CATALOG]}.json"
    ).read_text()
)


def _society_places(asset_key: str) -> list[list[int]] | None:
    """The places the society's registry row holds for a kind, back in the kind's part frame."""
    rows = {
        row["asset_key"]: row for row in reviewed_affordance_registry(REVIEWED_REACH_MM).values()
    }
    places = rows[asset_key].get(PLACES_FIELD)
    return None if places is None else [[x, -z] for x, z in places]


def _top_under(entry: dict[str, Any], x: int, y: int) -> int:
    """The top of the highest box the file places under a plan point of the kind."""
    tops = [
        part["offset_z_mm"] + part["size_z_mm"]
        for part in entry["recipe"]["parts"]
        if part["shape"] == "box"
        and 2 * abs(x - part["offset_x_mm"]) <= part["size_x_mm"]
        and 2 * abs(y - part["offset_y_mm"]) <= part["size_y_mm"]
    ]
    assert tops, (entry["key"], x, y)
    return max(tops)


def _expected(asset_key: str) -> dict[str, Any]:
    entry = ENTRIES[asset_key]
    use = entry["use"]
    places = (
        _society_places(asset_key) if "affordance" in use and use["affordance"] != "none" else []
    )
    if use["places"] is None:
        return {"affordance": use["affordance"], "places": None}
    rows = [row for row in use["places"] for _ in range(row["count"])]
    assert places is not None and len(places) == len(rows), asset_key
    served = []
    for (px, py), row in zip(places, rows, strict=True):
        seat = row["seat"]
        drawn = None
        if seat is not None:
            along_x = row["side"] in ("+y", "-y")
            x = seat["x_mm"] + (px if along_x else 0)
            y = seat["y_mm"] + (0 if along_x else py)
            drawn = {"position_mm": [x, y, _top_under(entry, x, y)], "faces": seat["faces"]}
        served.append({"position_mm": [px, py], "faces": ACROSS[row["side"]], "seat": drawn})
    return {"affordance": use["affordance"], "places": served}


def test_every_listed_kind_serves_what_the_file_and_the_society_rows_state(objects_api):
    listed = objects_api.get("/world/assets")
    assert listed.status_code == 200, listed.text
    rows = {row["asset_key"]: row for row in listed.json()}
    # Positive control: every kind the file states is listed, so the loop compares all of them.
    assert set(rows) == set(ENTRIES)
    seated = 0
    for key, row in rows.items():
        assert row["use"] == _expected(key), key
        seated += sum(place["seat"] is not None for place in row["use"]["places"] or ())
        one = objects_api.get(f"/world/assets/{key}")
        assert one.status_code == 200, one.text
        assert one.json()["use"] == row["use"], key
    assert seated == 9


def _expected_activity(asset_key: str) -> tuple[str, dict[str, Any] | None]:
    """What the routine file says people do at a kind, and which of its entries says it.

    The kind's own entry at an object, else the entry its affordance states for every kind; a kind
    whose affordance has no entry at an object is one nobody uses there.
    """
    entry = ENTRIES[asset_key]
    at_objects = [
        each
        for each in ROUTINE["entries"]
        if each["setting"] == "object" and each["affordance"] == entry["use"]["affordance"]
    ]
    own = [each for each in at_objects if each["object_kind"] == entry["key"]]
    shared = [each for each in at_objects if each["object_kind"] == "any"]
    if not at_objects:
        return "nobody", None
    [chosen] = own or shared
    return ("own" if own else "shared"), {
        "key": chosen["key"],
        "label": chosen["label"],
        "duration_minimum_ticks": chosen["duration_minimum_ticks"],
        "duration_maximum_ticks": chosen["duration_maximum_ticks"],
    }


def test_every_listed_kind_serves_what_inhabitants_do_there_as_the_routine_file_states(
    objects_api,
):
    listed = objects_api.get("/world/assets")
    assert listed.status_code == 200, listed.text
    rows = {row["asset_key"]: row for row in listed.json()}
    assert set(rows) == set(ENTRIES)
    sources = []
    for key, row in rows.items():
        source, expected = _expected_activity(key)
        sources.append(source)
        assert row["activity"] == expected, key
        one = objects_api.get(f"/world/assets/{key}")
        assert one.status_code == 200, one.text
        assert one.json()["activity"] == row["activity"], key
    # Positive control: the loop compared a kind served from its own entry, one served from the
    # entry its affordance states for every kind, and one nobody uses, so each rule was exercised.
    assert set(sources) == {"own", "shared", "nobody"}


def test_an_asset_the_catalog_does_not_state_has_no_use():
    characters = json.loads((ROOT / "assets/characters/catalog.json").read_text())
    component = characters["families"][0]["bases"][0]["asset"]["assetKey"]
    # Positive control: a kind the catalog states has one, so the null below is the key's.
    assert object_use_view(next(iter(ENTRIES))) is not None
    assert object_activity_view(next(iter(ENTRIES))) is not None
    assert object_use_view(component) is None
    assert object_activity_view(component) is None
