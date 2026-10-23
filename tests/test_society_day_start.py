"""A society's day starts at the hour its world's setting is lit for: the clock and the sky agree.

*   the catalog gives a minute to every sky part the setting rules list, and to the look's own day
    sun by where it stands; it refuses a sky part entry that is no sky part and day sun entries that
    leave an azimuth unread (with a positive control: the catalog as committed loads);
*   a setting's sky part gives its minute; with none, the look's day sun gives the morning's minute
    east of south and the afternoon's due south and west of it; with neither, none (the policy's);
*   a pack the library holds is read for its own day's sun, and an unknown one for none;
*   a town's people frame states the minute it is given, and the policy's without one;
*   through the API, a town dressed at dusk as a world made from words is, before its people come,
    records the catalog's dusk minute in its society's first input, serves its clock from it, and
    replays; a town with no setting records the minute its look's day sun gives.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.world.creation_look import name_creation_look
from exulanica.world.models import StylePackBinding
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.society import served_clock
from exulanica.world.society_day_start import (
    CATALOG_PATH,
    DayStartRefused,
    day_starts,
    day_sun_azimuth,
    start_minute_for,
)
from exulanica.world.society_living import town_routine
from exulanica.world.style_pack_library import style_pack_context, style_pack_library
from exulanica.world.town_people import people_frame
from exulanica.world.world_settings import bound_setting, setting_rules

from test_society_made_world import made as imported_made  # noqa: F401
from test_society_things_town_people_postgres import _input
from test_town_people import _six
from test_walking_surfaces_v3_postgres import (  # noqa: F401
    V7,
    _every_town_a_test_makes_is_made,
    _made_alias,
    _offering_things,
    _place,
)

#: Suns the catalog's two sides are tried on, in millidegrees of azimuth.
SOUTH_EAST, DUE_SOUTH, SOUTH_WEST = 142_000, 180_000, 235_000


def _entries() -> list[dict]:
    """The catalog's entries, read from the file itself."""
    return json.loads(CATALOG_PATH.read_text())["entries"]


def _sky() -> dict[str, int]:
    return {e["key"]: e["start_minute_of_day"] for e in _entries() if e["from"] == "sky_part"}


def _sun(key: str) -> int:
    return next(e["start_minute_of_day"] for e in _entries() if e["key"] == key)


def test_the_catalog_gives_a_minute_to_every_sky_part_and_to_the_look_s_day_sun():
    starts = day_starts()
    assert dict(starts.by_sky) == _sky()
    assert set(_sky()) == set(setting_rules().part_names["sky"])
    assert starts.by_sun == tuple(
        sorted(
            (e["sun_azimuth_below_mdeg"], e["start_minute_of_day"])
            for e in _entries()
            if e["from"] == "day_sun"
        )
    )


def _refused(tmp_path, change) -> None:
    document = json.loads(CATALOG_PATH.read_text())
    path = tmp_path / CATALOG_PATH.name
    path.write_text(json.dumps(document))
    assert day_starts.__wrapped__(path).by_sky == day_starts().by_sky
    change(document["entries"])
    path.write_text(json.dumps(document))
    with pytest.raises(DayStartRefused):
        day_starts.__wrapped__(path)


def test_a_sky_part_entry_that_is_no_sky_part_is_refused(tmp_path):
    def sea(entries: list[dict]) -> None:
        next(e for e in entries if e["from"] == "sky_part")["key"] = "sea"

    _refused(tmp_path, sea)


def test_day_sun_entries_that_leave_an_azimuth_unread_are_refused(tmp_path):
    def short(entries: list[dict]) -> None:
        last = max(
            (e for e in entries if e["from"] == "day_sun"),
            key=lambda e: e["sun_azimuth_below_mdeg"],
        )
        last["sun_azimuth_below_mdeg"] -= 1

    _refused(tmp_path, short)


def test_a_setting_s_sky_part_gives_its_minute_else_the_look_s_day_sun_by_where_it_stands():
    sky = _sky()
    dusk = {"parts": [{"axis": "ground", "key": "sea"}, {"axis": "sky", "key": "dusk"}]}
    assert start_minute_for(dusk, SOUTH_WEST) == start_minute_for(dusk, None) == sky["dusk"]
    assert (
        start_minute_for({"parts": [{"axis": "sky", "key": "overcast"}]}, None) == sky["overcast"]
    )
    # No sky of its own: the look's day. Morning east of south; due south and west, afternoon.
    morning, afternoon = _sun("sun_east_of_south"), _sun("sun_west_of_south")
    assert morning != afternoon
    assert start_minute_for(None, SOUTH_EAST) == morning
    assert start_minute_for(None, DUE_SOUTH) == afternoon
    assert start_minute_for(None, SOUTH_WEST) == afternoon
    sea = {"parts": [{"axis": "ground", "key": "sea"}]}
    assert start_minute_for(sea, SOUTH_EAST) == morning
    assert start_minute_for({"parts": []}, SOUTH_WEST) == afternoon
    # Neither a sky nor a sun: the policy's own minute.
    assert start_minute_for(None, None) is None and start_minute_for(sea, None) is None


def test_a_pack_the_library_holds_is_read_for_its_own_day_s_sun():
    pack = style_pack_library().default_pack
    manifest = json.loads(
        (
            CATALOG_PATH.parents[2] / "style-packs" / "packs" / pack.pack_id / "manifest.json"
        ).read_text()
    )
    light = manifest["light"]
    assert (
        day_sun_azimuth(pack.manifest_sha256)
        == light["presets"][light["default_preset"]]["sun"]["azimuth_mdeg"]
    )
    assert day_sun_azimuth("0" * 64) is None and day_sun_azimuth(None) is None


def test_a_town_s_people_frame_states_the_minute_it_is_given_and_else_the_policy_s():
    routine = town_routine()
    policy = routine.policy["start_minute_of_day"]
    assert people_frame(_six(), routine)["day"] == {"start_minute_of_day": policy}
    given = people_frame(_six(), routine, start_minute=_sky()["dusk"])
    assert given["day"] == {"start_minute_of_day": _sky()["dusk"]}


@pytest.mark.postgres
def test_a_town_dressed_at_dusk_starts_its_society_s_clock_at_its_dusk(made):
    api = made
    _offering_things(api)
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": "A town at dusk"})
    assert made_town.status_code == 201, made_town.text
    entry = made_town.json()
    # Dressed as a world made from words "at dusk" is, as it is made: the library's look with the
    # dusk sky part.
    library = style_pack_library()
    pack = library.default_pack
    chain = library.chain(pack.manifest_sha256)
    assert chain is not None
    setting = bound_setting(chain, style_pack_context(), chosen={"sky": "dusk"})
    look = StylePackBinding(pack.pack_id, pack.version, pack.manifest_sha256, setting=setting)
    with api.database.session(api.repository.workspace_id) as connection:
        entries = SavedWorldEntryRepository(connection, api.repository.workspace_id, api.store)
        name_creation_look(entries, entries.entry(uuid.UUID(entry["entry_id"])), look, api.actor)
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V7}
    )
    assert created.status_code in (200, 201), created.text
    dusk = _sky()["dusk"]
    assert _input(api, entry, 1)["people"]["day"] == {"start_minute_of_day": dusk}
    # The clock its read serves beside the state, from that minute.
    read = api.get(society)
    assert read.status_code == 200, read.text
    assert read.json()["clock"] == served_clock(dusk, read.json()["current_tick"])
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True


@pytest.mark.postgres
def test_a_town_with_no_setting_starts_at_the_minute_its_look_s_day_sun_gives(made):
    api = made
    _offering_things(api)
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": "A plain town"})
    assert made_town.status_code == 201, made_town.text
    entry = made_town.json()
    with api.database.session(api.repository.workspace_id) as connection:
        worn = connection.execute(
            "select v.style_pack_setting, v.style_pack_manifest_sha256 from world_style_state s "
            "join world_style_version v on v.workspace_id=s.workspace_id and v.world_id=s.world_id "
            "and v.version_id=s.current_style_version_id where s.workspace_id=%s and s.world_id=%s",
            (api.repository.workspace_id, entry["world_id"]),
        ).fetchone()
    assert worn["style_pack_setting"] is None
    sun = day_sun_azimuth(worn["style_pack_manifest_sha256"])
    assert sun is not None
    expected = _sun("sun_east_of_south" if sun < DUE_SOUTH else "sun_west_of_south")
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V7}
    )
    assert created.status_code in (200, 201), created.text
    assert _input(api, entry, 1)["people"]["day"] == {"start_minute_of_day": expected}
