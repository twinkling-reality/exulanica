"""A version of a made town whose buildings were changed is read with its changes by the society's
town read and by the landing for placed things, so people walk, and things land, in the changed
town (``exulanica/world/version_town.py``).

Against PostgreSQL as the runtime role, on a small town made through the API under a fixed
identity, so it is the same town on every run, its changes written as the parts routes write them:
an element override named ``part:<building>``, suppressed for a removal or stating ``storeys``.
"""

from __future__ import annotations

import dataclasses
import math
import uuid
from fractions import Fraction

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.city.generation.massing import (
    BuildingChange,
    BuildingStoreysRefused,
)
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.streets import CurbEdgeRecord
from exulanica.grammar.grammars.city.surface import city_surface_z_at
from exulanica.selection.validation import Session
from exulanica.world import saved_entries, thing_landing_source
from exulanica.world.composers import composer_module
from exulanica.world.generated_worlds import town_records
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import ElementOverride
from exulanica.world.society_authored_ground import read_authored_ground
from exulanica.world.society_authored_ground_area import ground_place_id
from exulanica.world.society_city_place import city_blocked_parts
from exulanica.world.society_living import town_routine_of
from exulanica.world.society_walking_surfaces import (
    surface_height_at,
    town_head_count,
    walking_surfaces_place,
)
from exulanica.world.thing_landing_source import prepare_landing_in_region
from exulanica.world.town_parts import town_buildings
from exulanica.world.town_people import people_frame
from exulanica.world.version_town import town_key, version_town_records

from test_society_made_world import made as imported_made  # noqa: F401
from test_walking_surfaces_v3_postgres import (  # noqa: F401
    V3,
    V7,
    _every_town_a_test_makes_is_made,
    _made_alias,
    _offering_things,
)

pytestmark = pytest.mark.postgres

#: The town every test here makes: the identity the world would have drawn is this one.
IDENTITY = "world:generated:00000000-0000-4000-8000-000000000003"


class _Town:
    """A small town made through the API, its version, and the parts routes' writes to it."""

    def __init__(self, api, entry: dict) -> None:
        self.api = api
        self.entry = entry
        self.workspace = api.repository.workspace_id
        self.world = entry["world_id"]
        self.version_id = uuid.UUID(entry["authored_version_id"])
        self.snapshot = uuid.UUID(api.version(entry)["source_snapshot_id"])
        self.region = entry["generated_ground"]["region_id"]
        with api.database.session(self.workspace) as connection:
            self.made = town_records(connection, self.workspace, self.world, self.snapshot)

    def state(self) -> str:
        return self.api.version(self.entry)["state_sha256"]

    def change(self, connection, override: ElementOverride, building: str, base: str) -> None:
        WorldObjectRepository(connection, self.workspace, world_id=self.world).set_part_change(
            self.version_id,
            override,
            base_state_sha256=base,
            actor=self.api.actor,
            part_ids=frozenset({building}),
        )

    def changed(self, override: ElementOverride, building: str) -> None:
        base = self.state()
        with self.api.database.session(self.workspace) as connection:
            self.change(connection, override, building, base)

    def records(self):
        with self.api.database.session(self.workspace) as connection:
            key, changes = town_key(
                connection, self.workspace, self.world, self.snapshot, self.version_id
            )
            generated = version_town_records(
                connection, self.workspace, self.world, self.snapshot, changes
            )
        return key, generated

    def frame(self, records, made=None) -> dict:
        """The people frame the town's living place under its own routine makes from ``records``,
        with ``made`` the town's records as made where a version changed its buildings."""
        routine = town_routine_of(self.made.receipt)
        place = walking_surfaces_place(ground_place_id(self.region), records, routine, made)
        return people_frame(place, routine, population=town_head_count(place, made, routine))


@pytest.fixture
def town(made, monkeypatch) -> _Town:
    api = made
    _offering_things(api)
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: IDENTITY)
    response = api.post("/worlds/generated", {"recipe": "small_town", "title": "Changed town"})
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["world_id"] == IDENTITY
    return _Town(api, entry)


def _housed(town: _Town, frame: dict) -> list[str]:
    """The buildings of the made town whose premises offer a home or a position in ``frame``."""
    offered = {row["subject_id"] for row in frame["premises"]}
    return [
        building.identity
        for building in town_buildings(town.made.records)
        if any(subject.endswith(premises) for premises in building.premises for subject in offered)
    ]


def _premises_in(frame: dict, premises: tuple[str, ...]) -> list[str]:
    return [
        row["subject_id"]
        for row in frame["premises"]
        if any(row["subject_id"].endswith(identity) for identity in premises)
    ]


def _first_input(town: _Town) -> dict:
    with town.api.database.session(town.workspace) as connection:
        return connection.execute(
            "select i.document from world_society_input i join world_society s using "
            "(workspace_id,society_id) where s.workspace_id=%s and s.world_id=%s "
            "and s.version_id=%s and i.input_seq=1",
            (town.workspace, town.world, town.version_id),
        ).fetchone()["document"]


def _society(town: _Town) -> dict:
    created = town.api.post(
        f"/world/versions/{town.version_id}/society?world_id={town.world}",
        {"region_id": town.region, "profile": V7},
    )
    assert created.status_code in (200, 201), created.text
    document = _first_input(town)
    assert document["profile"] == V3
    return document


def _region_rings(records) -> set[tuple]:
    """Every building's base ring in ``records``, in the region's frame (east and south)."""
    return {
        tuple((x, -y) for x, y in ring)
        for kind, _label, ring in city_blocked_parts(records)
        if kind == "building"
    }


def _landing(town: _Town):
    with town.api.database.session(town.workspace) as connection:
        repository = WorldObjectRepository(connection, town.workspace, world_id=town.world)
        landing = prepare_landing_in_region(repository, town.version_id, town.region)
    assert landing is not None
    return landing


def _place_well(town: _Town, east: int, south: int):
    return town.api.post(
        f"/world/versions/{town.version_id}/things?world_id={town.world}",
        {
            "base_state_sha256": town.state(),
            "thing_id": "well",
            "kind": {"kind": "well", "version": 2},
            "region_id": town.region,
            "pose": {"x_mm": east, "y_mm": 0, "z_mm": south, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )


def test_an_unchanged_version_reads_the_town_exactly_as_it_was_made(town):
    key, generated = town.records()
    assert key == (town.world, town.snapshot, None)
    assert generated.receipt_sha256 == town.made.receipt_sha256
    assert generated.records == town.made.records
    # The society's first input over the unchanged version is the town's own people.
    document = _society(town)
    assert document["people"] == town.frame(town.made.records)
    # The landing reads the town's own buildings.
    landing = _landing(town)
    assert {p.ring for p in landing.parts if p.kind == "building"} == _region_rings(
        town.made.records
    )


def test_a_removed_building_is_gone_from_the_society_s_town_and_from_the_landing(town):
    made_frame = town.frame(town.made.records)
    gone = _housed(town, made_frame)[0]
    [building] = [b for b in town_buildings(town.made.records) if b.identity == gone]
    assert _premises_in(made_frame, building.premises)
    town.changed(ElementOverride(f"part:{gone}", suppressed=True), gone)

    key, generated = town.records()
    assert key is not None and key[:2] == (town.world, town.snapshot) and key[2] is not None
    assert gone not in {b.identity for b in town_buildings(generated.records)}
    # The society made over the changed version offers nothing in the removed building.
    document = _society(town)
    assert document["people"] == town.frame(generated.records, town.made.records)
    assert not _premises_in(document["people"], building.premises)
    assert document["people"]["place"] != made_frame["place"]
    # The landing no longer holds a thing off the removed building's base ring, and holds every
    # other building's as it stands in the changed town.
    standing = {p.ring for p in _landing(town).parts if p.kind == "building"}
    assert standing == _region_rings(generated.records)
    assert len(_region_rings(town.made.records) - standing) == 1


def test_a_removed_building_s_ground_takes_a_placed_thing_it_refused(town):
    gone = _housed(town, town.frame(town.made.records))[0]
    composer = town.made.receipt["composer"]
    removed = composer_module(composer["key"], composer["version"]).records_with(
        town.made.receipt, {gone: BuildingChange(removed=True)}
    )
    [ring] = _region_rings(town.made.records) - _region_rings(removed)
    east = int(sum(Fraction(x) for x, _ in ring) / len(ring))
    south = int(sum(Fraction(z) for _, z in ring) / len(ring))
    refused = _place_well(town, east, south)
    assert refused.status_code == 422, refused.text
    town.changed(ElementOverride(f"part:{gone}", suppressed=True), gone)
    placed = _place_well(town, east, south)
    assert placed.status_code == 201, placed.text


def _taller(town: _Town):
    """The first building of the made town its lot lets stand one storey taller, with the records
    the change makes, chosen by the grammar's own refusal."""
    composer = town.made.receipt["composer"]
    module = composer_module(composer["key"], composer["version"])
    for building in town_buildings(town.made.records):
        change = {building.identity: BuildingChange(storeys=building.storeys + 1)}
        try:
            return building, module.records_with(town.made.receipt, change)
        except BuildingStoreysRefused:
            continue
    raise AssertionError("no building of the town stands one storey taller")


def test_a_taller_building_changes_the_society_s_town(town):
    tall, _ = _taller(town)
    storeys = tall.storeys + 1
    town.changed(
        ElementOverride(f"part:{tall.identity}", suppressed=False, storeys=storeys), tall.identity
    )
    key, generated = town.records()
    assert key is not None and key[2] is not None
    [massing] = [
        r for r in generated.records if isinstance(r, MassingRecord) and r.identity == tall.identity
    ]
    assert massing.storeys == storeys
    document = _society(town)
    assert document["people"] == town.frame(generated.records, town.made.records)
    made_frame = town.frame(town.made.records)
    assert document["people"]["place"] != made_frame["place"]
    # The taller building adds homes and takes none from its neighbours; the society is given the
    # made town's people, so the new homes stand empty.
    homes = {row["subject_id"]: row["homes"] for row in document["people"]["premises"]}
    made_homes = {row["subject_id"]: row["homes"] for row in made_frame["premises"]}
    grew = {s for s in homes if homes[s] != made_homes[s]}
    assert grew and all(homes[s] > made_homes[s] for s in grew)
    assert all(_premises_in({"premises": [{"subject_id": s}]}, tall.premises) for s in grew)
    assert document["people"]["population"] == made_frame["population"] < sum(homes.values())
    # Its base ring stands where it stood: a thing is held off the same ground.
    assert {p.ring for p in _landing(town).parts if p.kind == "building"} == _region_rings(
        generated.records
    )


def test_two_changes_of_a_version_in_one_transaction_never_share_a_town_read(town):
    """The society's read of a town is kept for its transaction by world, snapshot and the
    version's changes: a change written in the same transaction is read anew, not answered from
    the read before it, and the living place made after it is the changed town's."""
    runtime = town.api.client.app.state.services.society_runtime
    session = Session(workspace_id=town.workspace, actor=town.api.actor)
    gone = _housed(town, town.frame(town.made.records))[0]
    [building] = [b for b in town_buildings(town.made.records) if b.identity == gone]
    base = town.state()
    with town.api.database.session(town.workspace) as connection, connection.transaction():
        runtime._lock(connection, session)
        read = runtime._transaction_read(connection)
        binding, ground = runtime._authored_scope(connection, session, town.version_id, town.region)
        runtime._read_town_ahead(connection, binding, ground, read)
        town.change(connection, ElementOverride(f"part:{gone}", suppressed=True), gone, base)
        runtime._read_town_ahead(connection, binding, ground, read)
        unchanged = read.towns.pop((town.world, town.snapshot, None))
        [(key, changed)] = read.towns.items()
    assert key[:2] == (town.world, town.snapshot) and key[2] is not None
    assert unchanged.records == town.made.records
    assert gone not in {b.identity for b in town_buildings(changed.records)}
    assert canonical_json(unchanged.place) != canonical_json(changed.place)
    routine = town_routine_of(town.made.receipt)
    lived_in = runtime._living_place(ground, changed, routine)
    assert not _premises_in(people_frame(lived_in, routine), building.premises)


def _beside(curb: CurbEdgeRecord, out: int) -> tuple[int, int]:
    """The point ``out`` millimetres from the middle of the curb's first kerb piece, towards its
    footway (or into the road, below 0), in the region's frame (east and south)."""
    (ax, ay, _), (bx, by, _) = curb.kerb_line_mm[:2]
    dx, dy = bx - ax, by - ay
    side = 1 if curb.side == "left" else -1
    length = math.isqrt(dx * dx + dy * dy)
    x = (ax + bx) // 2 - side * dy * out // length
    y = (ay + by) // 2 + side * dx * out // length
    return x, -y


def _curb(town: _Town) -> CurbEdgeRecord:
    return min(
        (r for r in town.made.records if isinstance(r, CurbEdgeRecord)), key=lambda r: r.identity
    )


def test_a_thing_rests_on_the_town_s_own_surface_above_its_arrival(town):
    # The town hangs its region at its arrival's height, so a thing on its footway or its road
    # rests at the city's own surface there less that height, the kerb between them.
    curb = _curb(town)
    footway = _beside(curb, curb.kerb_width_mm + curb.footway_width_mm // 2)
    road = _beside(curb, -1_000)
    surface = city_surface_z_at(town.made.records)
    arrival = town.entry["generated_ground"]["arrival_mm"][1]
    landing = _landing(town)
    assert landing.rest_height is not None
    rests = [landing.rest_height(point) for point in (footway, road)]
    assert rests == [surface((east, -south)) - arrival for east, south in (footway, road)]
    assert rests[0] - rests[1] > curb.kerb_height_mm // 2
    # Where the city states no street surface (open land beyond the town), the walking line nearest.
    beyond = (-50_000, 50_000)
    assert surface((beyond[0], -beyond[1])) is None
    with town.api.database.session(town.workspace) as connection:
        ground = read_authored_ground(
            connection, town.workspace, town.world, town.snapshot, region_id=town.region
        )
    lines = surface_height_at(walking_surfaces_place(ground.place_id, town.made.records), ground)
    assert landing.rest_height(beyond) == lines(beyond) - arrival
    # The placing's preview answers the same height, whatever height it was asked about.
    east, south = footway
    answered = town.api.post(
        f"/world/versions/{town.version_id}/things/preview?world_id={town.world}",
        {
            "base_state_sha256": town.state(),
            "thing_id": "well",
            "kind": {"kind": "well", "version": 2},
            "region_id": town.region,
            "pose": {"x_mm": east, "y_mm": 0, "z_mm": south, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["landing"] == {"checked": True, "rest_y_mm": rests[0]}


def test_a_bench_resting_where_the_landing_rests_it_offers_itself_to_the_town_s_people(
    town, monkeypatch
):
    # However high a town's arrival stands (here 150 mm up), a bench placed on its road at the
    # height the landing rests it at is read by the town's society of things as resting there,
    # from the same surface, not as standing off the walking lines.
    stated = thing_landing_source.generated_extent

    def raised(*scope):
        extent = stated(*scope)
        east, _height, south = extent.arrival_mm
        return dataclasses.replace(extent, arrival_mm=(east, 150, south))

    monkeypatch.setattr(thing_landing_source, "generated_extent", raised)
    east, south = _beside(_curb(town), -1_000)
    rest = _landing(town).rest_height((east, south))
    placed = town.api.post(
        f"/world/versions/{town.version_id}/things?world_id={town.world}",
        {
            "base_state_sha256": town.state(),
            "thing_id": "bench",
            "kind": {"kind": "bench", "version": 1},
            "region_id": town.region,
            "pose": {"x_mm": east, "y_mm": rest, "z_mm": south, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text
    document = _society(town)
    assert [r for r in document["unavailable_affordances"] if r["object_id"] == "bench"] == []
    assert [t["affordance"] for t in document["targets"] if t["object_id"] == "bench"]
