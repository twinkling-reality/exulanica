"""A made town's building is not lowered from under the people who live in it: a lowering whose
kept premises would hold fewer homes than the people living there is refused, naming how many
would lose a home, since nobody moves house (``POST .../parts/{part_id}/storeys`` and its preview,
``part_homes_lived_in``).

Against PostgreSQL as the runtime role, on the small town of
``tests/test_town_parts_routes_postgres.py`` under its fixed identity, with a society of things or
a living town. Expected figures are read from the town's own records and the society's state: the
homes each premises would hold from the place the society reads, made from the changed records
(``walking_surfaces_place``), and who lives where from the state's residents, never retyped.

*   with no society, the preview of such a lowering is ready: the refusal is the residents', not the
    change's;
*   with a society of things made, the lowering is refused 422 with the count, in words, and its
    preview is blocked alike; nothing is kept;
*   a lowering that leaves every resident a home is kept;
*   a living town, whose people name a home by its place's destination, refuses it alike;
*   a lowering checked before a society is made, and written while it is being made, waits for the
    workspace's lock that making holds and is refused as stale, nothing kept; asked again, it is
    refused for that society's people.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from typing import Any

import pytest
from exulanica.api.routes import world_parts
from exulanica.grammar.grammars.city.generation.massing import (
    BuildingChange,
    BuildingStoreysRefused,
)
from exulanica.world.composers.city_grammar_town import records_with
from exulanica.world.generated_worlds import town_records
from exulanica.world.society_grounds import CREATES
from exulanica.world.society_living import town_routine_of
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.society_walking_surfaces import walking_surfaces_place
from exulanica.world.town_parts import premises_of, premises_taken
from exulanica.world.workspace_lock import WORKSPACE_LOCK_SEED
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from test_society_made_world import made as imported_made  # noqa: F401
from test_town_parts_routes_postgres import (
    THINGS,
    TOWN,
    Town,
    _the_same_town_on_every_run,  # noqa: F401
    _town,
)

pytestmark = pytest.mark.postgres

PLACE = "place:lowering-homes"


@pytest.fixture(name="made")
def _made_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_made")


def _made_records(town: Town) -> tuple[object, ...]:
    with town.api.database.session(town.workspace_id) as connection:
        return tuple(town_records(connection, town.workspace_id, TOWN, town.snapshot_id).records)


def _residents(state: dict[str, Any]) -> dict[str, int]:
    """How many people of a society of things live in each premises, by record identity, named or
    not: its residents name a home by the town's record subject (``city.premises:<identity>``)."""
    premises = state["people"]["premises"]
    found: dict[str, int] = {}
    for person in state["inhabitants"]:
        resident = person.get("resident")
        if resident and resident.get("home"):
            subject = premises[resident["home"]["premises"]]["subject_id"]
            identity = subject.removeprefix("city.premises:")
            found[identity] = found.get(identity, 0) + 1
    return found


def _living_residents(state: dict[str, Any]) -> dict[str, int]:
    """How many people of a living town live in each premises, by record identity: its people name
    a home by the place's destination (``premises:<identity>``)."""
    found: dict[str, int] = {}
    for person in state["inhabitants"]:
        home = person.get("home")
        named = home.get("destination_id") if isinstance(home, dict) else None
        if isinstance(named, str) and named.startswith("premises:"):
            identity = named.removeprefix("premises:")
            found[identity] = found.get(identity, 0) + 1
    return found


def _full(town: Town) -> dict[str, int]:
    """Every home of the town as made full, as a society made over it fills them."""
    made_place = walking_surfaces_place(PLACE, _made_records(town), town_routine_of(town.receipt()))
    return {
        d["subject_id"].removeprefix("city.premises:"): d["resident_capacity"]
        for d in made_place["destinations"]
        if d["destination_id"].startswith("premises:") and d["resident_capacity"]
    }


def _lowerings(town: Town, residents: dict[str, int]) -> list[tuple[str, int, int]]:
    """Each building lowered by one storey where its lot allows it and no premises is taken, with
    the storeys and how many of its residents would have no home, read from the society's place
    made from the changed records."""
    made = _made_records(town)
    routine = town_routine_of(town.receipt())
    found = []
    for building in town.buildings():
        lowered = building.storeys - 1
        change = {building.identity: BuildingChange(storeys=lowered)}
        try:
            after = records_with(town.receipt(), change)
        except BuildingStoreysRefused:
            continue
        if premises_taken(made, after, building.identity):
            continue
        place = walking_surfaces_place(PLACE, after, routine, made_records=made)
        homes = {
            d["subject_id"].removeprefix("city.premises:"): d["resident_capacity"]
            for d in place["destinations"]
            if d["destination_id"].startswith("premises:")
        }
        lost = sum(
            max(0, residents.get(p, 0) - homes.get(p, 0))
            for p in premises_of(after, building.identity)
        )
        found.append((building.identity, lowered, lost))
    return found


def _society(town: Town, profile: str) -> dict[str, Any]:
    created = town.api.post(
        town.path("/society"),
        {"region_id": town.entry["generated_ground"]["region_id"], "profile": profile},
    )
    assert created.status_code in (200, 201), created.text
    return created.json()["state"]  # type: ignore[no-any-return]


def _refused(answer: Any, building: str, lowered: int, lost: int) -> str:
    """The lowering's write refused by how many would lose a home; its words."""
    assert answer.status_code == 422, answer.text
    body = answer.json()
    who = "1 person lives" if lost == 1 else f"{lost} people live"
    assert body["code"] == "part_homes_lived_in"
    assert body["detail"] == f"Not lowered: {who} in the homes it would lose."
    assert body["where"] == {"part_id": building, "storeys": lowered, "homes_lost": lost}
    return str(body["detail"])


def _refused_alike(town: Town, building: str, lowered: int, lost: int) -> None:
    """The lowering and its preview refused by how many would lose a home, and nothing kept."""
    base = town.base()
    detail = _refused(town.post(building, "storeys", storeys=lowered), building, lowered, lost)
    verdict = town.post(building, "storeys", preview=True, storeys=lowered).json()
    assert verdict["availability"] == "blocked"
    assert verdict["blocked_reason"] == "part_homes_lived_in"
    assert verdict["blocked_detail"] == detail
    assert town.base() == base and town.overrides() == {}


def test_a_lowering_that_would_leave_residents_without_a_home_is_refused_by_how_many(made):
    town = _town(made)
    made.client.app.state.services = dataclasses.replace(
        made.client.app.state.services, societies_of_things=True
    )
    lowerings = _lowerings(town, _residents(_society(town, THINGS)))
    refused_at = next((one for one in lowerings if one[2] > 0), None)
    kept_at = next((one for one in lowerings if one[2] == 0), None)
    assert refused_at is not None, "no lowering of the town leaves a resident without a home"
    assert kept_at is not None, "no lowering of the town leaves every resident a home"
    _refused_alike(town, *refused_at)

    building, lowered, _none = kept_at
    kept = town.post(building, "storeys", storeys=lowered)
    assert kept.status_code == 200, kept.text
    assert town.overrides()[building].storeys == lowered


def test_a_living_town_s_lowering_is_refused_by_how_many_live_there(made):
    """A host that offers no society of things makes a living town over a made town."""
    town = _town(made)
    state = _society(town, CREATES["town"])
    assert not any(person.get("resident") for person in state["inhabitants"])
    residents = _living_residents(state)
    assert residents, "the living town's people name no home"
    refused_at = next((one for one in _lowerings(town, residents) if one[2] > 0), None)
    assert refused_at is not None, "no lowering of the town leaves a resident without a home"
    _refused_alike(town, *refused_at)


def _waits_for_the_workspace_lock(town: Town) -> bool:
    """Whether a session waits for the town's workspace lock now."""
    connection = town.api.repository.connection
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select count(*) as waiting from pg_locks l, "
            "(select hashtextextended(%s::text, %s) as k) lock "
            "where l.locktype = 'advisory' and not l.granted and l.objsubid = 1 "
            "and l.classid = ((lock.k >> 32) & 4294967295)::oid "
            "and l.objid = (lock.k & 4294967295)::oid",
            (town.workspace_id, WORKSPACE_LOCK_SEED),
        ).fetchone()
    connection.commit()
    return bool(row and row["waiting"])


def test_a_society_made_after_a_lowering_is_checked_refuses_it(made, monkeypatch):
    """The write asks again under the workspace's lock, which a society is made under: a lowering
    checked before a society is made, and written while it is being made, is not kept."""
    town = _town(made)
    made.client.app.state.services = dataclasses.replace(
        made.client.app.state.services, societies_of_things=True
    )
    building, lowered, _most = max(_lowerings(town, _full(town)), key=lambda one: one[2])
    base = town.base()
    # The lowering is checked with no society, then waits to be written until the society's making
    # holds the workspace's lock; the making holds it until the write waits for it.
    checked, making_locks, write_waits = threading.Event(), threading.Event(), threading.Event()
    commit = world_parts.commit_edit
    lock = SocietyRepository._lock

    def commit_once_the_making_locks(*arguments: Any) -> Any:
        checked.set()
        assert making_locks.wait(120), "the society's making never took the lock"
        return commit(*arguments)

    def lock_until_the_write_waits(self: SocietyRepository) -> None:
        lock(self)
        in_transaction = self.connection.info.transaction_status == TransactionStatus.INTRANS
        if checked.is_set() and in_transaction and not making_locks.is_set():
            making_locks.set()
            assert write_waits.wait(120), "the lowering's write never waited for the lock"

    monkeypatch.setattr(world_parts, "commit_edit", commit_once_the_making_locks)
    monkeypatch.setattr(SocietyRepository, "_lock", lock_until_the_write_waits)
    states: list[dict[str, Any]] = []
    answered: list[Any] = []
    path = town.path(f"/parts/{building}/storeys")
    lowering = threading.Thread(
        target=lambda: answered.append(
            made.post(path, {"base_state_sha256": base, "storeys": lowered})
        )
    )
    making = threading.Thread(target=lambda: states.append(_society(town, THINGS)))
    lowering.start()
    try:
        assert checked.wait(120), "the lowering was never checked"
        making.start()
        assert making_locks.wait(120), "the society's making never took the lock"
        for _ in range(2400):
            if _waits_for_the_workspace_lock(town) or not lowering.is_alive():
                break
            time.sleep(0.05)
    finally:
        checked.set()
        making_locks.set()
        write_waits.set()
        lowering.join(120)
        if making.ident is not None:
            making.join(120)
    assert not making.is_alive() and not lowering.is_alive()
    assert len(states) == 1 and len(answered) == 1
    lost = next(one[2] for one in _lowerings(town, _residents(states[0])) if one[0] == building)
    assert lost > 0, "the society made leaves every resident of the building a home"
    # Checked before the society was made, the lowering is refused as stale under the lock, its
    # people unnamed; asked again, it is refused for them.
    stale = answered[0]
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_object_base"
    assert town.base() == base and town.overrides() == {}
    _refused_alike(town, building, lowered, lost)


def test_with_no_society_the_same_lowering_is_ready(made):
    town = _town(made)
    building, lowered, lost = next(one for one in _lowerings(town, _full(town)) if one[2] > 0)
    assert lost > 0
    verdict = town.post(building, "storeys", preview=True, storeys=lowered).json()
    assert verdict["availability"] == "ready", verdict
