"""A society of things on a farm with a pond, as a deployment stores it: its inputs carry the water.

The fixture farm is made from its world kind through the routes, under a fixed identity, and a
body with legs and a pair of fins (``tests/water_society_support.py``) is kept and placed on the
walking line south of the farm's pond. The society the runtime creates over it records swimming in
its first input, and that input carries the pond's water, laid by the kind worker's statement of
it; an edit's next input carries it too, and the stored minutes replay. A society created while
swimming was not yet recorded, as every one made before it was built, is handed no water by any
input it reads.
"""

from __future__ import annotations

from typing import Any

import pytest
from exulanica.movement import registry
from exulanica.movement.registry import SWIMMING, WALKING_V2
from exulanica.world import saved_entries
from exulanica.world.society_water import WATER_FIELD
from exulanica.world.thing_store import ThingStore

import test_site_society_of_things_postgres as farm_site
from test_society_made_world import made as imported_made  # noqa: F401
from water_society_support import finned_walker_creature

pytestmark = pytest.mark.postgres

V7 = farm_site.V7
SWIMMER = "creature:5e1f1a21"


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _the_same_site_on_every_run(monkeypatch):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: farm_site.FARM)


def _farm_with_a_swimmer(api) -> tuple[dict[str, Any], str]:
    entry, society, _records = farm_site._site(api, "farm", "fixture_farm", "small_farm")
    creature = finned_walker_creature()
    with api.database.session(api.repository.workspace_id) as session:
        ThingStore(session, api.repository.workspace_id, api.store).keep_creature(
            creature, created_by=api.actor
        )
    kind = {"source": "workspace", "sha256": creature.kind.sha256}
    # On the walking line along the pond's south side, in the region's frame (east, and south as
    # the negative of the site's north).
    farm_site._place(api, entry, SWIMMER, kind, 74_181, -1_500)
    return entry, society


def _an_edit(api, entry: dict[str, Any]) -> None:
    east, _height, south = entry["generated_site"]["arrival_mm"]
    farm_site._place(
        api, entry, "well-by-the-gate", {"kind": "well", "version": 2}, east + 3_000, south
    )


def test_a_farm_with_a_pond_hands_its_water_to_every_input_of_its_swimming_society(made):
    api = made
    entry, society = _farm_with_a_swimmer(api)
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    body = created.json()
    first = farm_site._input(api, entry, 1)
    assert first["movement_modules"] == [SWIMMING, WALKING_V2]
    water = first[WATER_FIELD]
    [pond] = water["bodies"]
    assert (pond["kind"], pond["level_mm"]) == ("pond", 0)
    assert len(water["nodes"]) == 18 * 16
    assert any(edge["kind"] == "shore" for edge in water["edges"])
    assert body["state"]["movement_modules"] == [SWIMMING, WALKING_V2]
    for _ in range(3):
        body = farm_site._step(api, entry, body)
    _an_edit(api, entry)
    second = farm_site._input(api, entry, 2)
    assert "movement_modules" not in second
    assert second[WATER_FIELD] == water
    for _ in range(3):
        body = farm_site._step(api, entry, body)
    assert farm_site._replayed(api, entry) is True


def test_a_society_made_before_swimming_is_handed_no_water(made, monkeypatch):
    api = made
    entry, society = _farm_with_a_swimmer(api)
    with monkeypatch.context() as before:
        before.setattr(registry, "current_engine_modules", lambda engine: (WALKING_V2,))
        created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    body = created.json()
    first = farm_site._input(api, entry, 1)
    assert first["movement_modules"] == [WALKING_V2]
    assert WATER_FIELD not in first
    _an_edit(api, entry)
    assert WATER_FIELD not in farm_site._input(api, entry, 2)
    for _ in range(3):
        body = farm_site._step(api, entry, body)
    assert farm_site._replayed(api, entry) is True
