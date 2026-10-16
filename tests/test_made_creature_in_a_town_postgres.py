"""A creature its workspace keeps, placed in a generated town, lives there and walks on its own,
as a deployment stores it.

What is shown, as the world's owner through the real routes, on the small town every test here
makes under one fixed identity:

*   placed before anybody lives there, the creature makes the town's society one of things: it is
    taken in as a being by its kind's digest and, minute by minute, walks the town's streets by its
    own routine, away from where it was placed;
*   placed in a town whose living society is already under way, it is taken in when the town's
    people take in what was placed, and walks there too.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.selection.creature_drafting import assembled_form
from exulanica.store.local import LocalContentAddressedStore
from exulanica.things.bodies import body_grammar
from exulanica.things.creatures import assemble_creature
from exulanica.world import saved_entries
from exulanica.world.thing_store import ThingStore

from creature_support import form_of
from test_society_made_kinds import BY
from test_society_made_world import made as imported_made  # noqa: F401
from test_walking_surfaces_v3_postgres import (  # noqa: F401
    V7,
    _every_town_a_test_makes_is_made,
    _made_alias,
    _offering_things,
    _step,
)

pytestmark = pytest.mark.postgres

V5 = "exulanica-society/v5"
TOWN = "world:generated:00000000-0000-4000-8000-000000000005"
#: A placed creature's id, opaque as the page makes it.
CREATURE = "creature:7a40c2e1"
#: Minutes played before the creature is asked to have moved.
MINUTES = 12


@pytest.fixture(autouse=True)
def _the_same_town_on_every_run(monkeypatch):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: TOWN)


def _kept(api, tmp_path) -> str:
    """A creature that walks about by its routine, kept in the town's workspace: its digest."""
    form = form_of("crocodile", label="quorzle wibbet")
    for ability, weight in (("stand", 600), ("visit", 200), ("rest", 100)):
        form[f"can_{ability}"] = True
        form[f"weight_{ability}"] = weight
    creature = assemble_creature(assembled_form(form, body_grammar()), by=BY)
    workspace = api.repository.workspace_id
    with api.database.session(workspace) as session:
        ThingStore(
            session, workspace, LocalContentAddressedStore(tmp_path / "looks")
        ).keep_creature(creature, created_by=uuid.uuid4())
    return creature.kind.sha256


def _town(api, title: str) -> dict:
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": title})
    assert made_town.status_code == 201, made_town.text
    return made_town.json()


def _place_creature(api, entry: dict, sha256: str) -> None:
    root = f"/world/versions/{entry['authored_version_id']}?world_id={entry['world_id']}"
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    placed = api.post(
        f"/world/versions/{entry['authored_version_id']}/things?world_id={entry['world_id']}",
        {
            "base_state_sha256": api.get(root).json()["state_sha256"],
            "thing_id": CREATURE,
            "kind": {"source": "workspace", "sha256": sha256},
            "region_id": entry["generated_ground"]["region_id"],
            "pose": {"x_mm": east - 2_000, "y_mm": 0, "z_mm": south, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text


def _creature(body: dict, sha256: str) -> dict:
    [being] = [p for p in body["state"]["inhabitants"] if p["came_by"] == "placed"]
    assert being["placed_id"] == CREATURE
    assert being["kind"] == {"source": "workspace", "sha256": sha256}
    return being


def _walks(api, entry: dict, body: dict, sha256: str) -> None:
    """Over the minutes played, the creature leaves where it was taken in, walking a path."""
    start = _creature(body, sha256)["position_mm"]
    positions, walked = [start], False
    for _ in range(MINUTES):
        body = _step(api, entry, body)
        being = _creature(body, sha256)
        positions.append(being["position_mm"])
        walked = walked or len(being["motion_path_mm"]) > 1
    assert walked and any(position != start for position in positions), positions
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200 and replayed.json()["replay_verified"] is True


def test_a_made_creature_placed_in_a_town_walks_its_streets(made, tmp_path):
    api = made
    _offering_things(api)
    sha256 = _kept(api, tmp_path)
    entry = _town(api, "A town a creature walks")
    _place_creature(api, entry, sha256)
    created = api.post(
        f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}",
        {"region_id": entry["generated_ground"]["region_id"], "profile": V7},
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    assert body["profile"] == V7
    _walks(api, entry, body, sha256)


def test_a_living_town_takes_a_made_creature_in_and_it_walks_there(made, tmp_path):
    api = made
    _offering_things(api)
    sha256 = _kept(api, tmp_path)
    entry = _town(api, "A living town a creature joins")
    root = f"/world/versions/{entry['authored_version_id']}/society"
    scope = f"?world_id={entry['world_id']}"
    created = api.post(
        root + scope, {"region_id": entry["generated_ground"]["region_id"], "profile": V5}
    )
    assert created.status_code in (200, 201), created.text
    assert created.json()["profile"] == V5
    _place_creature(api, entry, sha256)
    taken = api.post(f"{root}/take-in{scope}", {})
    assert taken.status_code in (200, 201), taken.text
    body = taken.json()
    assert body["profile"] == V7
    _walks(api, entry, body, sha256)
