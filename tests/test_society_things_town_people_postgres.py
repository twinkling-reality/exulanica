"""A society of things made through the API over a town is the town's own people, as a
deployment stores it: its first stored input carries what they are made from, authorised by
composing it again; its villagers are residents with homes and jobs; the document its state
records is the one the world's own seed makes from that input; a later input states no people;
and the stored minutes replay.

A town made through the API takes a fresh identity, and its seed, its streets and how many
positions its premises offer follow from that identity: of 48 small towns made under fixed
identities on 2026-10-10, four offered fewer positions than the 76 people of 128 who seek work
(62, 62, 72 and 72 against 76 to 178 in the others). So each town here is made under a fixed
identity and is the same town on every run, one with positions to spare and one that runs out,
and what is held is the rule: as many work as seek work or as there are positions, whichever is
fewer, and each of the rest says that no position was open."""

from __future__ import annotations

import pytest
from exulanica.world import saved_entries
from exulanica.world.society import world_society_seed
from exulanica.world.town_people import people_from_frame

from test_society_made_world import made as imported_made  # noqa: F401
from test_walking_surfaces_v3_postgres import (  # noqa: F401
    V3,
    V7,
    _every_town_a_test_makes_is_made,
    _made_alias,
    _offering_things,
    _place,
    _step,
)

pytestmark = pytest.mark.postgres


def _input(api, entry: dict, seq: int) -> dict:
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select i.document from world_society_input i join world_society s using "
            "(workspace_id,society_id) where s.workspace_id=%s and s.world_id=%s "
            "and s.version_id=%s and i.input_seq=%s",
            (api.repository.workspace_id, entry["world_id"], entry["authored_version_id"], seq),
        ).fetchone()["document"]


#: Small towns by the identity each is made under, with what its own records offer: read on
#: 2026-10-10 from each town's place (the positions its premises state), 128 people living in
#: each. ``(identity, positions, at work, seeking with no position open)``.
SPARE = ("world:generated:00000000-0000-4000-8000-000000000003", 136, 76, 0)
SHORT = ("world:generated:00000000-0000-4000-8000-000000000020", 62, 62, 14)


@pytest.mark.parametrize(
    ("identity", "positions", "at_work", "none_open"),
    [SPARE, SHORT],
    ids=["positions-to-spare", "positions-run-out"],
)
def test_a_town_with_a_knight_in_it_keeps_its_bakers_as_a_deployment_stores_them(
    made, monkeypatch, identity, positions, at_work, none_open
):
    api = made
    _offering_things(api)
    # The same town on every run: the identity the world would have drawn is this one.
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: identity)
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": "A housed town"})
    assert made_town.status_code == 201, made_town.text
    entry = made_town.json()
    assert entry["world_id"] == identity
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    # Made at all: the unpersisted first input, frame and all, was composed again and compared.
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V7}
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    state = body["state"]
    first = _input(api, entry, 1)
    assert first["profile"] == V3
    frame = first["people"]
    assert frame["profile"] == "exulanica.town-people-frame/v1"
    villagers = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    [knight] = [p for p in state["inhabitants"] if p["came_by"] == "placed"]
    assert frame["population"] == first["population"]["size"] == len(villagers)
    assert "resident" not in knight
    # The people the world's own seed makes from the stored frame, worked here from the seed the
    # server derives for the world: the document the state records, and each villager's entry.
    seed = world_society_seed(api.repository.workspace_id, entry["world_id"])
    people = people_from_frame(seed, frame)
    assert state["people"]["document_sha256"] == people["document_sha256"]
    assert "seed" not in body and seed not in created.text
    premises = state["people"]["premises"]
    assert [row["subject_id"] for row in premises] == [
        row["subject_id"] for row in people["premises"]
    ]
    for villager, stated in zip(villagers, people["people"], strict=True):
        resident = villager["resident"]
        assert premises[resident["home"]["premises"]]["subject_id"] == stated["home"]["subject_id"]
        assert resident["role"] == stated["role"] and villager["role"] == stated["role"]["label"]
        assert (resident["job"] is None) == (stated["job"] is None)
    # The rule, from the town's own frame: the policy's share of its people seek work, and as
    # many work as seek or as the town has positions, whichever is fewer. Whoever sought and
    # found none says so, and nobody else does.
    working = [v for v in villagers if v["resident"]["job"] is not None]
    seeking = len(villagers) * frame["employment_share_milli"] // 1000
    offered = sum(len(row["positions"]) for row in frame["premises"])
    assert (len(villagers), seeking, offered) == (128, 76, positions)
    assert len(working) == min(seeking, offered) == at_work > 0
    reasons = [v["resident"]["reason"] for v in villagers if v["resident"]["job"] is None]
    assert reasons.count("no_open_position") == seeking - len(working) == none_open
    assert set(reasons) <= {"keeps_no_job", "no_open_position", "lives_at_premises"}
    assert all(premises[v["resident"]["job"]["premises"]]["label"] for v in working)
    # A thing placed after the society was made is a later input, which states no people.
    _place(api, entry, "well", "well", 2, east + 3_000, south)
    for _ in range(2):
        body = _step(api, entry, body)
    later = _input(api, entry, 2)
    assert "people" not in later and "modules" not in later
    assert {t["placed_id"] for t in body["state"]["things"]} == {"well"}
    assert body["state"]["people"] == state["people"]
    assert {p["id"]: p["resident"] for p in body["state"]["inhabitants"] if "resident" in p} == {
        p["id"]: p["resident"] for p in villagers
    }
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True
