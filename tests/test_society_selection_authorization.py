"""Purposeful society authorization applies before related-result counts and pages."""

import pytest
from exulanica.selection import execute, validate
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_repository import SocietyRepository

import test_world_environment_composition_postgres as composition
from society_fixtures import SEED, edited, seal, society_input

composed = composition.composed
memory_place = composition.memory_place
pytestmark = pytest.mark.postgres


def test_society_rights_gate_counts_pagination_and_historical_events(memory_place):
    memory = memory_place
    composition._confirm_bridge(memory)
    world = memory.composed
    conn = world.worlds.connection
    version = world.version.version_id
    doc = society_input(version)
    society = SocietyRepository(conn, world.worlds.workspace_id, input_authorizer=lambda _: None)
    society.create(
        version,
        place_id=world.source.place_id,
        region_id="region-a",
        seed=SEED,
        actor=memory.actor,
        profile="exulanica-society/v2",
        initial_input=doc,
    )
    initial = society.snapshot(version)
    society.advance(
        version, base_tick=initial["current_tick"], base_state_sha256=initial["state_sha256"]
    )
    successor = seal(edited(doc))
    society.record_input(version, successor)
    conn.commit()

    def run(authorizer=None, *, limit=24, after=None):
        return execute(
            conn,
            validate(conn, memory.plan(limit=limit, after=after), memory.session),
            store=world.store,
            society_authorizer=authorizer,
        )

    # Without a runtime adapter, v2 is unavailable, not silently authorized by its stored bytes.
    absent = run()
    seen = []
    allowed = run(lambda value: seen.append(value["input_seq"]))
    assert seen == [1, 2]
    assert allowed.total_matched > absent.total_matched
    assert any(item.origin_kind == "simulated" for item in allowed.content)
    assert all(item.origin_kind != "simulated" for item in absent.content)

    def withdrawn_history(value):
        if value["input_seq"] == 1:
            raise UnavailableSocietyInput("old source withdrawn")

    denied = run(withdrawn_history)
    assert denied.total_matched == absent.total_matched
    assert denied.content == absent.content
    # Permission filtering precedes the look-ahead row too, so hidden people create no next page.
    page = run(withdrawn_history, limit=1)
    collected = list(page.content)
    while page.next_page is not None:
        page = run(withdrawn_history, limit=1, after=page.next_page)
        collected.extend(page.content)
    assert len(collected) == absent.total_matched
    assert all(item.origin_kind != "simulated" for item in collected)
