"""A site world's made parts, changed by a person: applied to its records and checked, pure.

The worlds are the hand-written fixture kinds in ``tests/fixtures/world-kinds`` (test fixtures,
not kinds a person or a model made). Positions and words are read from the records the fixture
makes, never retyped.
"""

from __future__ import annotations

import pytest
from exulanica.grammar.grammars.site import check_site_records
from exulanica.grammar.grammars.site.records import (
    SiteFixtureRecord,
    SiteRoomRecord,
    SiteStructureRecord,
    SiteWallRecord,
)
from exulanica.world.authored_delta import canonical_delta_document
from exulanica.world.composers.site_plan import society_place
from exulanica.world.kinds.catalogs import BOUNDS_VERSIONS, load_kind_catalogs
from exulanica.world.kinds.samples import first_unreached
from exulanica.world.objects import ElementOverride, Transform, override_document
from exulanica.world.site_parts import (
    LAND_WORDS,
    PART_CODES,
    QUARTER_TURNS,
    PartChange,
    PartChangeRefused,
    apply_changes,
    changeable_parts,
    changes_document,
    changes_from_document,
    changes_of,
    changes_sha256,
    check_change,
    check_storeys,
    part_override,
    people_of_part,
    receipt_storeys_bound,
    refused_people_words,
)
from exulanica.world.society_site_place import SiteSociety

from test_site_worlds import _composed


@pytest.fixture(scope="module", name="farm")
def _farm():  # type: ignore[no-untyped-def]
    _kind, composed = _composed("farm")
    return composed


def _uses(composed):  # type: ignore[no-untyped-def]
    return SiteSociety.read(composed.receipt["society"]).uses


def _part(composed, key: str):  # type: ignore[no-untyped-def]
    return next(p for p in changeable_parts(composed.records, _uses(composed)) if p.part_key == key)


def _record(records, identity: str):  # type: ignore[no-untyped-def]
    return next(r for r in records if getattr(r, "identity", None) == identity)


def _owned(records, structure: str) -> set[str]:  # type: ignore[no-untyped-def]
    rooms = {
        r.identity
        for r in records
        if isinstance(r, SiteRoomRecord) and r.structure_identity == structure
    }
    return (
        rooms
        | {
            r.identity
            for r in records
            if isinstance(r, SiteWallRecord) and r.owner_identity == structure
        }
        | {
            r.identity
            for r in records
            if isinstance(r, SiteFixtureRecord) and r.owner_identity in rooms
        }
    )


def _checked(composed, change: PartChange):  # type: ignore[no-untyped-def]
    changed = apply_changes(composed.records, [change])
    check_change(
        changed,
        change.identity,
        root_identity=composed.receipt["subject_identity"],
        uses=_uses(composed),
    )
    return changed


def test_the_parts_a_person_may_change_are_buildings_garden_fixtures_and_areas(farm):
    parts = changeable_parts(farm.records, _uses(farm))
    kinds = {part.identity: part.kind for part in parts}
    for record in farm.records:
        if isinstance(record, SiteStructureRecord):
            assert kinds[record.identity] == "building"
        if isinstance(record, SiteRoomRecord | SiteWallRecord):
            assert record.identity not in kinds
    room_fixtures = [
        r
        for r in farm.records
        if isinstance(r, SiteFixtureRecord)
        and any(
            isinstance(o, SiteRoomRecord) and o.identity == r.owner_identity for o in farm.records
        )
    ]
    assert all(fixture.identity not in kinds for fixture in room_fixtures)
    assert {"building", "fixture", "area"} <= set(kinds.values())


def test_a_moved_building_carries_its_walls_rooms_and_room_fixtures_and_keeps_every_identity(farm):
    barn = _part(farm, "barn")
    east, north = barn.centre_mm
    changed = _checked(farm, PartChange(barn.identity, False, (east - 3_000, north + 1_000)))
    assert [getattr(r, "identity", None) for r in changed] == [
        getattr(r, "identity", None) for r in farm.records
    ]
    for identity in _owned(farm.records, barn.identity) | {barn.identity}:
        before, after = _record(farm.records, identity), _record(changed, identity)
        if isinstance(before, SiteWallRecord):
            assert (after.start_x_mm, after.start_y_mm) == (
                before.start_x_mm - 3_000,
                before.start_y_mm + 1_000,
            )
        elif isinstance(before, SiteFixtureRecord):
            assert (after.x_mm, after.y_mm) == (before.x_mm - 3_000, before.y_mm + 1_000)
        else:
            assert (after.min_x_mm, after.max_y_mm) == (
                before.min_x_mm - 3_000,
                before.max_y_mm + 1_000,
            )
    for before, after in zip(farm.records, changed, strict=True):
        if getattr(before, "identity", None) not in _owned(farm.records, barn.identity) | {
            barn.identity
        }:
            assert before == after


def test_a_quarter_turn_turns_a_building_about_its_centre_with_its_door(farm):
    barn = _part(farm, "barn")
    made = _record(farm.records, barn.identity)
    changed = _checked(farm, PartChange(barn.identity, False, barn.centre_mm, 1))
    turned = _record(changed, barn.identity)
    assert turned.max_x_mm - turned.min_x_mm == made.max_y_mm - made.min_y_mm
    assert turned.max_y_mm - turned.min_y_mm == made.max_x_mm - made.min_x_mm
    facing = {"north": "west", "west": "south", "south": "east", "east": "north"}
    assert turned.door_facing == facing[made.door_facing]
    # Walls stay written from their lesser end, so the records' own rules hold.
    check_site_records(changed, root_identity=farm.receipt["subject_identity"])
    # A part left where it was made, unturned, is as it was made.
    again = apply_changes(farm.records, [PartChange(barn.identity, False, barn.centre_mm, 0)])
    assert again == farm.records


def test_a_fixture_turns_by_its_own_quarter_turns(farm):
    bench = _part(farm, "bench")
    made = _record(farm.records, bench.identity)
    changed = _checked(farm, PartChange(bench.identity, False, bench.centre_mm, 2))
    assert _record(changed, bench.identity).yaw_quarter_turns == (made.yaw_quarter_turns + 2) % 4


def test_a_removed_building_takes_what_it_owns_and_people_still_reach_every_place(farm):
    barn = _part(farm, "barn")
    changed = _checked(farm, PartChange(barn.identity, True))
    gone = _owned(farm.records, barn.identity) | {barn.identity}
    assert not gone & {getattr(r, "identity", None) for r in changed}
    place = society_place("place:test", farm.receipt, changed)
    assert first_unreached(place) is None
    assert f"structure:{barn.identity}" not in {d["destination_id"] for d in place["destinations"]}


def test_a_part_is_refused_by_name_out_of_its_area_and_onto_another_part(farm):
    pond, bench, house = _part(farm, "pond"), _part(farm, "bench"), _part(farm, "farmhouse")
    with pytest.raises(PartChangeRefused) as left:
        _checked(
            farm, PartChange(pond.identity, False, (pond.centre_mm[0] - 40_000, pond.centre_mm[1]))
        )
    assert left.value.code == "part_outside_zone"
    assert str(left.value) == f"Not here: it would leave the {pond.zone_label}."
    with pytest.raises(PartChangeRefused) as blocked:
        _checked(farm, PartChange(bench.identity, False, house.centre_mm))
    assert blocked.value.code == "part_blocked"
    assert str(blocked.value) == f"Not here: it would stand on the {house.label}."
    assert blocked.value.where["blocked_by"] == house.identity


def test_a_part_a_person_does_not_change_alone_is_refused(farm):
    wall = next(r for r in farm.records if isinstance(r, SiteWallRecord))
    with pytest.raises(PartChangeRefused) as refused:
        apply_changes(farm.records, [PartChange(wall.identity, True)])
    assert refused.value.code == "part_not_changeable"
    with pytest.raises(PartChangeRefused) as unknown:
        apply_changes(farm.records, [PartChange("00000000-0000-5000-8000-000000000000", True)])
    assert unknown.value.code == "part_unknown"


def test_a_change_is_stored_as_an_override_naming_the_part_and_read_back(farm):
    barn = _part(farm, "barn")
    moved = PartChange(barn.identity, False, (1_000, 2_000), 3)
    override = part_override(moved)
    assert override.element_id == f"part:{barn.identity}"
    assert override.transform == Transform(1_000, 0, -2_000, QUARTER_TURNS[3], 1_000)
    removed = part_override(PartChange(barn.identity, True))
    assert removed.suppressed and removed.transform is None
    snapshot = ElementOverride("element:site", True)
    assert changes_of([override, snapshot]) == (moved,)
    assert changes_from_document(changes_document([moved])) == (moved,)
    with pytest.raises(ValueError, match="no part can stand"):
        changes_of([ElementOverride(override.element_id, False, Transform(0, 0, 0, 1, 1_000))])


def test_the_digest_of_no_changes_is_empty_and_of_changes_their_own(farm):
    barn = _part(farm, "barn")
    assert changes_sha256(()) == ""
    one = changes_sha256([PartChange(barn.identity, True)])
    other = changes_sha256([PartChange(barn.identity, False, barn.centre_mm, 1)])
    assert len(one) == 64 and one != other
    assert one == changes_sha256([PartChange(barn.identity, True)])


def test_the_people_a_part_houses_are_named_from_either_engine():
    premises = {"subject_id": "site.structure:house", "use_class": "home", "label": "farmhouse"}
    state = {
        "people": {"premises": [premises, {"subject_id": "site.structure:barn"}]},
        "inhabitants": [
            {
                "display_name": "Ada Lane 1",
                "resident": {
                    "home": {"premises": 0, "household": 0},
                    "job": None,
                    "role": {"key": "r", "label": "r"},
                },
            },
            {
                "display_name": "Bo Cole 2",
                "resident": {
                    "home": {"premises": 1, "household": 0},
                    "job": {
                        "premises": 0,
                        "position": 0,
                        "shift": {"start_minute": 0, "minutes": 60},
                    },
                    "role": {"key": "r", "label": "r"},
                },
            },
            {
                "display_name": "Cy Moss 3",
                "home": {"destination_id": "structure:house"},
                "role": {"key": "r", "label": "r"},
            },
        ],
    }
    assert people_of_part(state, "house") == [
        ("Ada Lane 1", "lives"),
        ("Bo Cole 2", "works"),
        ("Cy Moss 3", "lives"),
    ]
    assert people_of_part(state, "pond") == []
    assert refused_people_words("farmhouse", people_of_part(state, "house")) == (
        "Not removed: Ada Lane 1 lives there, Bo Cole 2 works there and Cy Moss 3 lives there. "
        "The farmhouse can be moved instead."
    )


LAND = {
    "profile": "exulanica.landform/v1",
    "ground_mm": 8000,
    "features": [
        {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 30},
        {"id": "sea", "kind": "shore", "side": "south", "distance_mm": 60000},
    ],
}


@pytest.fixture(scope="module", name="land_farm")
def _land_farm():  # type: ignore[no-untyped-def]
    kind, _composed_level = _composed("farm")
    from exulanica.world.composers import composer_module

    return composer_module("site-plan", 1).compose_kind(
        kind, kind.values(kind.presets[0][0]), "world:generated:land-parts", land=LAND
    )


def _part_job(composed, change: PartChange):  # type: ignore[no-untyped-def]
    from exulanica.world.kinds.worker import part_job, site_ground_place_id

    return part_job(
        "workspace:test",
        dict(composed.receipt),
        composed.receipt_sha256,
        site_ground_place_id(),
        changes_document([change]),
        change.identity,
    )


def test_every_code_the_land_grader_refuses_with_has_its_own_words():
    import inspect
    import re

    from exulanica.grammar.landform import grading

    raised = set(re.findall(r'code="(landform_[a-z_]+)"', inspect.getsource(grading)))
    assert raised
    assert raised <= set(LAND_WORDS)
    assert set(LAND_WORDS) <= PART_CODES


def test_on_land_a_moved_pond_is_graded_again_and_its_place_made(land_farm):
    assert land_farm.receipt["composer"]["version"] == 5
    pond = _part(land_farm, "pond")
    east, north = pond.centre_mm
    answer = _part_job(land_farm, PartChange(pond.identity, False, (east - 2_000, north)))
    assert answer["status"] == "done", answer
    assert first_unreached(answer["place"]) is None


def test_on_land_a_change_the_land_refuses_is_answered_by_the_graders_code(land_farm, monkeypatch):
    from exulanica.grammar.landform import LandformRefused
    from exulanica.world import site_land

    def refused(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise LandformRefused("pond p would spill over its rim", code="landform_water_spills")

    monkeypatch.setattr(site_land, "site_land_of", refused)
    pond = _part(land_farm, "pond")
    answer = _part_job(land_farm, PartChange(pond.identity, False, pond.centre_mm))
    assert answer["status"] == "refused"
    assert answer["code"] == "landform_water_spills"
    assert answer["detail"] == LAND_WORDS["landform_water_spills"]
    assert answer["where"]["landform"] == "pond p would spill over its rim"


def test_a_change_the_layout_cannot_take_is_refused_in_plain_words(farm):
    pond = _part(farm, "pond")
    with pytest.raises(PartChangeRefused) as refused:
        _checked(farm, PartChange(pond.identity, False, pond.centre_mm, 1))
    assert refused.value.code == "part_records_refused"
    assert str(refused.value) == "Not here: the world's layout cannot take it there."
    assert "access_y_mm" in refused.value.where["detail"]


def test_a_building_stands_taller_with_its_own_walls_and_nothing_else_changes(farm):
    barn = _part(farm, "barn")
    made = _record(farm.records, barn.identity)
    taller = made.storeys + 1
    changed = apply_changes(farm.records, [PartChange(barn.identity, False, storeys=taller)])
    assert _record(changed, barn.identity).storeys == taller
    height = taller * made.storey_height_mm
    walls = [
        r for r in changed if isinstance(r, SiteWallRecord) and r.owner_identity == barn.identity
    ]
    assert walls and all(wall.height_mm == height for wall in walls)
    assert all(o.height_mm <= height for wall in walls for o in wall.openings)
    kept = {barn.identity} | {wall.identity for wall in walls}
    for before, after in zip(farm.records, changed, strict=True):
        if getattr(before, "identity", None) not in kept:
            assert before == after
    check_site_records(changed, root_identity=farm.receipt["subject_identity"])


def test_only_a_building_has_storeys(farm):
    bench = _part(farm, "bench")
    with pytest.raises(PartChangeRefused) as refused:
        apply_changes(farm.records, [PartChange(bench.identity, False, storeys=2)])
    assert refused.value.code == "part_storeys_refused"
    assert str(refused.value) == "Only a building has storeys."


def test_storeys_are_held_to_the_bounds_the_world_was_made_under(farm):
    fewest, most = receipt_storeys_bound(farm.receipt)
    assert 1 <= fewest <= most
    check_storeys(most, (fewest, most), "barn")
    with pytest.raises(PartChangeRefused) as taller:
        check_storeys(most + 1, (fewest, most), "barn")
    assert str(taller.value) == f"Not taller: buildings in this world have at most {most} storeys."
    unknown = {**farm.receipt, "catalogs": {**farm.receipt["catalogs"], "kind-bound": "0" * 64}}
    with pytest.raises(PartChangeRefused) as refused:
        receipt_storeys_bound(unknown)
    assert refused.value.code == "parts_not_served"


@pytest.mark.parametrize("bounds_version", BOUNDS_VERSIONS)
def test_a_world_reads_the_storeys_bound_of_the_bounds_version_its_receipt_names(
    farm, bounds_version
):
    catalogs = load_kind_catalogs(bounds_version=bounds_version)
    receipt = {
        **farm.receipt,
        "catalogs": {**farm.receipt["catalogs"], "kind-bound": catalogs.sha256["kind-bound"]},
    }
    assert receipt_storeys_bound(receipt) == catalogs.bound("storeys")


def test_a_storeys_change_is_stored_alone_or_with_a_move_and_read_back(farm):
    barn = _part(farm, "barn")
    alone = PartChange(barn.identity, False, storeys=3)
    stored = part_override(alone)
    assert stored.transform is None and stored.storeys == 3
    assert changes_of([stored]) == (alone,)
    moved = PartChange(barn.identity, False, barn.centre_mm, 2, storeys=4)
    assert changes_of([part_override(moved)]) == (moved,)
    assert changes_from_document(changes_document([alone, moved])) == (alone, moved)
    # A change stating no storeys keeps the document and the digest it always had.
    plain = PartChange(barn.identity, False, barn.centre_mm, 1)
    assert "storeys" not in changes_document([plain])[0]
    assert "storeys" not in override_document(part_override(plain))


def test_a_delta_holding_storeys_selects_its_own_schema_version_and_one_without_keeps_its_own(farm):
    barn = _part(farm, "barn")
    sections = {
        "objects": (),
        "environment_instances": (),
        "point_map_instances": (),
        "things": (),
    }
    plain = canonical_delta_document(
        element_overrides=(part_override(PartChange(barn.identity, True)),), **sections
    )
    storeyed = canonical_delta_document(
        element_overrides=(part_override(PartChange(barn.identity, False, storeys=3)),),
        **sections,
    )
    assert plain["schema_version"] == 1
    assert storeyed["schema_version"] == 6
    assert storeyed["element_overrides"][0]["storeys"] == 3
