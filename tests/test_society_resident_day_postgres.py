"""A recorded resident day survives storage and reopening with composition opt-in disabled."""

from __future__ import annotations

import dataclasses

import pytest
from exulanica.abilities.registry import DAY
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.world.society_composition import reviewed_affordance_registry

from test_site_society_of_things_postgres import (  # noqa: F401
    CREATURE,
    V7,
    _input,
    _keep_creature,
    _made_alias,
    _place,
    _replayed,
    _site,
    _step,
    _the_same_site_on_every_run,
    imported_made,
)

pytestmark = pytest.mark.postgres


def _runtime(api, *, day):
    runtime = SocietyRuntime(
        store=api.store, reviewed_affordances=reviewed_affordance_registry(), resident_day=day
    )
    state = api.client.app.state
    state.services = dataclasses.replace(state.services, society_runtime=runtime)
    state.society_initial_input = runtime.initial_input
    state.society_input_authorizer = runtime.authorize
    state.society_authored_edit = runtime.authored_edit


def test_a_stored_day_reopens_and_replays_without_recomposing_its_context(made, tmp_path):
    api = made
    _runtime(api, day=True)
    entry, society, _ = _site(api, "farm", "fixture_farm", "small_farm")
    creature = _keep_creature(api, tmp_path)
    east, _height, south = entry["generated_site"]["arrival_mm"]
    _place(
        api, entry, CREATURE, {"source": "workspace", "sha256": creature.kind.sha256}, east, south
    )
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    body = created.json()
    first = _input(api, entry, 1)
    assert DAY in first["modules"]
    assert body["state"]["day_context"] == first["day"]
    assert all(p["location"]["indoors"] for p in body["state"]["inhabitants"] if "resident" in p)
    assert all("day" not in p for p in body["state"]["inhabitants"] if p["came_by"] == "placed")
    for _ in range(48):
        body = _step(api, entry, body)
    checkpoint = body["state_sha256"]
    _runtime(api, day=False)
    reopened = api.get(society)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["state_sha256"] == checkpoint
    body = _step(api, entry, body)
    assert body["state"]["day_context"] == first["day"]
    assert _input(api, entry, 1) == first
    assert _replayed(api, entry)
