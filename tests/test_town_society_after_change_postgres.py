"""A made town's society, made before its buildings change, keeps stepping after the changes are
kept through the parts routes.

Against PostgreSQL as the runtime role, on the small town made through the API under a fixed
identity, so it is the same town on every run. A society of things is made over the town as made
and stepped; a building its people live or work in is not removed from under them; then that
building, or another its people live or work in, is stood one storey taller through
``POST .../parts/{part_id}/storeys``. The society steps: the step is answered, its tick advances,
the input it consumed is the changed version's and is available, the people housed at genesis
keep their homes and jobs (where the society runs a resident day, each still at a node of the
changed town), and the head count stays the one genesis fixed. Nobody is rehomed and nobody is
added. What the town's people frame offers, as made and as changed, is printed for the run's log.
Expected figures are read from the town's own records and the society's own state, never retyped.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from typing import Any

import pytest
from exulanica.db.session import set_workspace
from exulanica.grammar.grammars.city.generation.massing import (
    BuildingChange,
    BuildingStoreysRefused,
)
from exulanica.world import saved_entries
from exulanica.world.composers.city_grammar_town import records_with
from exulanica.world.generated_worlds import town_records
from exulanica.world.society_authored_ground_area import ground_place_id
from exulanica.world.society_living import town_routine_of
from exulanica.world.society_walking_surfaces import walking_surfaces_place
from exulanica.world.town_parts import TownBuilding, town_buildings
from exulanica.world.town_people import people_frame
from exulanica.world.version_town import town_key, version_town_records

from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

TOWN = "world:generated:00000000-0000-4000-8000-000000000003"
THINGS = "exulanica-society/v7"


@pytest.fixture(name="made")
def _made_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _the_same_town_on_every_run(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: TOWN)


def _subject(premises: str) -> str:
    return f"city.premises:{premises}"


def _measured(document: dict[str, Any]) -> dict[str, Any]:
    """What an input states of its people: the population it records, and the homes and positions
    its people frame offers, which only a first input carries."""
    frame = document.get("people")
    return {
        "population": (document.get("population") or {}).get("size"),
        "homes": None if frame is None else sum(row["homes"] for row in frame["premises"]),
        "positions": (
            None if frame is None else sum(len(row["positions"]) for row in frame["premises"])
        ),
    }


@dataclasses.dataclass
class Town:
    """A town made through the API, its version and its society, read through the routes."""

    api: Any
    entry: dict[str, Any]
    snapshot_id: uuid.UUID

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.api.repository.workspace_id  # type: ignore[no-any-return]

    @property
    def version_id(self) -> uuid.UUID:
        return uuid.UUID(self.entry["authored_version_id"])

    def path(self, tail: str = "", query: str = "") -> str:
        return f"/world/versions/{self.version_id}{tail}?world_id={TOWN}{query}"

    def base(self) -> str:
        read = self.api.get(self.path())
        assert read.status_code == 200, read.text
        return str(read.json()["state_sha256"])

    def buildings(self) -> list[TownBuilding]:
        """The town's buildings as made."""
        with self.api.database.session(self.workspace_id) as connection:
            made = town_records(connection, self.workspace_id, TOWN, self.snapshot_id)
        return list(town_buildings(made.records))

    def receipt(self) -> Any:
        with self.api.database.session(self.workspace_id) as connection:
            return town_records(connection, self.workspace_id, TOWN, self.snapshot_id).receipt

    def change(self, part_id: str, tail: str, **body: Any) -> Any:
        return self.api.post(
            self.path(f"/parts/{part_id}/{tail}"), {"base_state_sha256": self.base(), **body}
        )

    def society(self) -> dict[str, Any]:
        read = self.api.get(self.path("/society", "&places=true"))
        assert read.status_code == 200, read.text
        return read.json()  # type: ignore[no-any-return]

    def step(self) -> dict[str, Any]:
        now = self.society()
        stepped = self.api.post(
            self.path("/society/steps"),
            {"base_tick": now["current_tick"], "base_state_sha256": now["state_sha256"]},
        )
        assert stepped.status_code == 200, stepped.text
        return self.society()

    def consumed(self) -> dict[str, Any]:
        """The stored input the society's current state consumed, read from its table: no route
        serves an input itself."""
        now = self.society()
        connection = self.api.repository.connection
        set_workspace(connection, self.workspace_id)
        row = connection.execute(
            "select document from world_society_input where society_id=%s and input_seq=%s",
            (now["society_id"], now["input_seq"]),
        ).fetchone()
        connection.commit()
        return row["document"]  # type: ignore[no-any-return]


def _residents(society: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Each housed person's resident entry, by ordinal: their home, their job or none."""
    return {
        person["ordinal"]: person["resident"]
        for person in society["state"]["inhabitants"]
        if person.get("resident")
    }


def _homes_and_jobs(society: dict[str, Any]) -> dict[int, tuple[str | None, str | None]]:
    """Each housed person's home and job premises, by ordinal, by record subject."""
    premises = society["state"]["people"]["premises"]

    def subject(held: dict[str, Any] | None) -> str | None:
        return None if not held else str(premises[held["premises"]]["subject_id"])

    return {
        ordinal: (subject(resident.get("home")), subject(resident.get("job")))
        for ordinal, resident in _residents(society).items()
    }


def _head_count(society: dict[str, Any]) -> tuple[int, int]:
    """Everybody in the society, and the people its ground's population brought."""
    people = society["state"]["inhabitants"]
    return len(people), sum(1 for person in people if person["came_by"] == "populated")


@dataclasses.dataclass
class Society:
    """A society of things made over a town as made and stepped once, and what genesis fixed."""

    town: Town
    genesis: dict[str, Any]
    first: dict[str, Any]
    housed: dict[int, tuple[str | None, str | None]]
    heads: tuple[int, int]

    @property
    def used(self) -> set[str]:
        """The record subject of every premises somebody lives or works in."""
        return {held for pair in self.housed.values() for held in pair if held is not None}

    def lived_or_worked_in(self, building: TownBuilding) -> bool:
        return any(_subject(premises) in self.used for premises in building.premises)

    def steps_on(self, kept: Any, before: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """After a kept change, the society steps over the town as the change leaves it, its
        people housed where genesis housed them, as many as genesis made."""
        assert kept.status_code == 200, kept.text
        after = self.town.step()
        assert after["current_tick"] == before["current_tick"] + 1
        assert after["input_seq"] > before["input_seq"]
        assert after["places"]["authored_state"]["edit_seq"] == kept.json()["edit_seq"]
        consumed = self.town.consumed()
        assert consumed["availability"] == "available", consumed.get("unavailable_reason")
        assert _homes_and_jobs(after) == self.housed
        assert _head_count(after) == self.heads
        # A later input carries no people frame (the first input's people are the society's for
        # its whole life). Where the society runs a resident day, somebody walks home and to work
        # by the destination genesis gave them: each still stands at a node the changed town's
        # navigation holds.
        unreached = _unreached(after, consumed)
        assert unreached == [], json.dumps(unreached[:6])
        return after, consumed


def _unreached(society: dict[str, Any], document: dict[str, Any]) -> list[dict[str, Any]]:
    """Each home or job a person of ``society`` holds whose destination's node the input's
    navigation does not hold: none where it runs no resident day, whose people's homes and jobs
    are who they are, not where they walk."""
    state = society["state"]
    if "day_context" not in state:
        return []
    destinations = {d["destination_id"]: d for d in state["day_context"]["destinations"]}
    nodes = {node["node_id"] for node in document["navigation"]["nodes"]}
    unreached = []
    for person in state["inhabitants"]:
        held = {
            "home": person.get("day_home"),
            "job": (person.get("day_work") or {}).get("destination_id"),
        }
        for what, destination in held.items():
            if destination is not None and destinations[destination]["node_id"] not in nodes:
                unreached.append(
                    {
                        "ordinal": person["ordinal"],
                        "what": what,
                        "destination_id": destination,
                        "node_id": destinations[destination]["node_id"],
                    }
                )
    return unreached


def _society(api: Any, recipe: str) -> Society:
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, societies_of_things=True
    )
    response = api.post("/worlds/generated", {"recipe": recipe, "title": "Changed"})
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["world_id"] == TOWN
    town = Town(api, entry, uuid.UUID(api.version(entry)["source_snapshot_id"]))
    created = api.post(
        town.path("/society"),
        {"region_id": entry["generated_ground"]["region_id"], "profile": THINGS},
    )
    assert created.status_code in (200, 201), created.text
    genesis = town.step()
    first = town.consumed()
    assert first["availability"] == "available", first.get("unavailable_reason")
    housed = _homes_and_jobs(genesis)
    assert housed, "the town's society houses nobody"
    return Society(town, genesis, first, housed, _head_count(genesis))


def _one_taller(society: Society, *, besides: str | None = None) -> TownBuilding:
    """A building the grammar lets stand one storey taller, one somebody lives or works in first:
    its people are the ones a taller building could take a home from."""
    receipt = society.town.receipt()
    allowed = []
    for building in society.town.buildings():
        if building.identity == besides:
            continue
        try:
            records_with(receipt, {building.identity: BuildingChange(storeys=building.storeys + 1)})
        except BuildingStoreysRefused:
            continue
        allowed.append(building)
    assert allowed, "no building of the town may stand one storey taller"
    housed = [building for building in allowed if society.lived_or_worked_in(building)]
    return (housed or allowed)[0]


def _homes_offered(town: Town, building: TownBuilding) -> dict[str, Any]:
    """The homes and positions the town's people frame would offer, as made and as the version's
    changes leave it: in all, in the premises whose homes differ, and in ``building``."""
    with town.api.database.session(town.workspace_id) as connection:
        made = town_records(connection, town.workspace_id, TOWN, town.snapshot_id)
        _key, changes = town_key(
            connection, town.workspace_id, TOWN, town.snapshot_id, town.version_id
        )
        changed = version_town_records(
            connection, town.workspace_id, TOWN, town.snapshot_id, changes
        )
    routine = town_routine_of(made.receipt)
    region = ground_place_id(town.entry["generated_ground"]["region_id"])
    frames = [
        {
            row["subject_id"]: (row["homes"], len(row["positions"]))
            for row in people_frame(
                walking_surfaces_place(region, generated.records, routine), routine
            )["premises"]
        }
        for generated in (made, changed)
    ]
    ours = {_subject(premises) for premises in building.premises}
    return {
        "homes": [sum(h for h, _p in frame.values()) for frame in frames],
        "positions": [sum(p for _h, p in frame.values()) for frame in frames],
        "premises": [len(frame) for frame in frames],
        "differ": sum(
            frames[0].get(subject) != frames[1].get(subject)
            for subject in set(frames[0]) | set(frames[1])
        ),
        "taller_building": [sorted(v for k, v in frame.items() if k in ours) for frame in frames],
    }


def _said(society: Society, **measured: Any) -> None:
    """The figures a run measured, printed for its log."""
    print("measured:", json.dumps({"head_count": society.heads, **measured}, sort_keys=True))


def test_a_town_s_society_steps_on_after_a_building_its_people_live_in_grows(made):
    society = _society(made, "small_town")
    town = society.town
    buildings = town.buildings()
    empty = [building for building in buildings if not society.lived_or_worked_in(building)]
    # A building somebody lives or works in is not removed from under them.
    lived_in = next(building for building in buildings if society.lived_or_worked_in(building))
    refused = town.change(lived_in.identity, "remove")
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "part_houses_people"

    taller = _one_taller(society)
    assert society.lived_or_worked_in(taller)
    _after, later = society.steps_on(
        town.change(taller.identity, "storeys", storeys=taller.storeys + 1), society.genesis
    )
    _said(
        society,
        buildings=len(buildings),
        empty=len(empty),
        runs_day="day_context" in society.genesis["state"],
        modules=society.genesis["state"].get("modules"),
        taller={"storeys": [taller.storeys, taller.storeys + 1]},
        inputs=[_measured(society.first), _measured(later)],
        frames=_homes_offered(town, taller),
    )
