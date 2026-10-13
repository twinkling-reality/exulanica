"""Authored routine preferences survive ordinary saved-world admission and replay."""

from __future__ import annotations

from dataclasses import replace

import pytest
from exulanica.abilities import registry
from exulanica.selection.creature_drafting import assembled_form
from exulanica.things.bodies import body_grammar
from exulanica.things.creatures import assemble_creature
from exulanica.world import saved_entries
from exulanica.world.society_planner import open_ground
from exulanica.world.thing_store import ThingStore

from creature_support import form_of
from test_site_society_of_things_postgres import FARM, V7, _input, _place, _site, _step
from test_society_made_kinds import BY
from test_society_made_world import made as made

pytestmark = pytest.mark.postgres


def _being(snapshot, placed):
    return next(p for p in snapshot["state"]["inhabitants"] if p.get("placed_id") == placed)


@pytest.mark.parametrize("recorded_version", [2, 3])
def test_authored_routine_preferences_are_recorded_and_replay(made, monkeypatch, recorded_version):
    api = made
    monkeypatch.setattr(saved_entries, "new_world_id", lambda _kind: FARM)
    workspace = api.repository.workspace_id
    api.client.app.state.services = replace(
        api.client.app.state.services,
        society_seed=lambda _workspace, _world: "7" * 64,
        model_client=None,
    )
    current_modules = registry.current_modules
    # Only genesis composition chooses the historical module. Restore today's composer before
    # edits and ordinary minutes, so retained version selection must come from saved history.
    with monkeypatch.context() as genesis:
        if recorded_version == 2:
            genesis.setattr(
                registry,
                "current_modules",
                lambda *, day=False: tuple(
                    "exulanica-ability/purposeful/v2"
                    if name.startswith("exulanica-ability/purposeful/")
                    else name
                    for name in current_modules(day=day)
                ),
            )
        entry, society, _records = _site(api, "farm", "fixture_farm", "small_farm")
        created = api.post(society, {"region_id": "region:generated", "profile": V7})
        assert created.status_code in (200, 201), created.text
    snapshot = created.json()
    expected_module = f"exulanica-ability/purposeful/v{recorded_version}"
    assert expected_module in snapshot["state"]["modules"]
    document = _input(api, entry, 1)
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    free = sorted(
        open_ground(document, snapshot["state"]["inhabitants"])[0],
        key=lambda node: (nodes[node], node),
    )
    chosen = []
    for node in free:
        if all(
            sum((a - b) ** 2 for a, b in zip(nodes[node], nodes[other], strict=True)) > 16000**2
            for other in chosen
        ):
            chosen.append(node)
        if len(chosen) == 2:
            break
    assert len(chosen) == 2
    references = {}
    for placed, preferred, node in zip(
        ("waiter", "walker"), ("wait", "stand"), chosen, strict=True
    ):
        form = form_of("ten_legs", label=placed, moves=["walking"])
        form["can_stand"] = True
        form["weight_wait"] = 1000 if preferred == "wait" else 0
        form["weight_stand"] = 1000 if preferred == "stand" else 0
        creature = assemble_creature(assembled_form(form, body_grammar()), by=BY)
        references[placed] = creature.kind.sha256
        with api.database.session(workspace) as connection:
            ThingStore(connection, workspace, api.store).keep_creature(
                creature, created_by=api.actor
            )
        _place(
            api,
            entry,
            placed,
            {"source": "workspace", "sha256": creature.kind.sha256},
            *nodes[node],
        )
    snapshot = _step(api, entry, snapshot)
    for placed, preferred in (("waiter", "wait"), ("walker", "stand")):
        assert snapshot["state"]["kinds"][references[placed]]["routine"]["weights"] == {
            preferred: 1000
        }
    positions = {placed: {tuple(_being(snapshot, placed)["position_mm"])} for placed in references}
    for _ in range(18):
        snapshot = _step(api, entry, snapshot)
        assert expected_module in snapshot["state"]["modules"]
        for placed, digest in references.items():
            person = _being(snapshot, placed)
            assert person["kind"] == {"source": "workspace", "sha256": digest}
            positions[placed].add(tuple(person["position_mm"]))
    assert len(positions["walker"]) > 1
    if recorded_version == 3:
        assert len(positions["waiter"]) == 1
    else:
        # Version 2 keeps the world's weights even for a wait-only authored preference.
        assert len(positions["waiter"]) > 1
    cold = api.get(society)
    assert cold.status_code == 200, cold.text
    assert cold.json()["state_sha256"] == snapshot["state_sha256"]
    root = f"/world/versions/{entry['authored_version_id']}/society"
    replay = api.get(root + f"/replay?world_id={entry['world_id']}")
    assert replay.status_code == 200, replay.text
    assert replay.json()["replay_verified"]
    assert replay.json()["state_sha256"] == snapshot["state_sha256"]
