"""Opening a world with inhabitants reads the inputs it shows, not the whole history behind them.

Every stored input was validated against its predecessor when it was recorded, the table takes no
update or delete, and replay re-verifies the whole chain. So a read of the society, its events or
its playback, and a step, load and validate only the inputs they materialize or consume: the one
the state consumed, any queued after it, and those the events name. Replay still reads everything.
A read that validated every stored input would cost milliseconds for each edit the world had ever
had, on every open and every simulated minute.
"""

from __future__ import annotations

import pytest
from exulanica.world import society_repository as repository_module
from exulanica.world.objects import Transform

from test_society_authored_world_postgres import (  # noqa: F401
    create_society,
    place_object,
    saved_world,
    society_repository,
)

pytestmark = pytest.mark.postgres
EDITS = 12


def _counting(monkeypatch):
    seen: list[int] = []
    validate = repository_module.validate_society_input

    def counted(document):
        seen.append(document["input_seq"])
        validate(document)

    monkeypatch.setattr(repository_module, "validate_society_input", counted)
    return seen


def _edited(world):
    """A saved world whose society has consumed EDITS + 1 inputs, then one more queued."""
    placed = place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    society, _ = create_society(world)
    objects, version_id = world["objects"], world["binding"].version_id
    for index in range(EDITS):
        version = objects.version(version_id)
        objects.move_object(
            version_id,
            "object:cushion",
            Transform(3_000 + 100 * (index % 2 == 0), 0, 5_000, 3_141_593, 1000),
            base_state_sha256=version.state_sha256,
            actor=world["session"].actor,
        )
    society = society_repository(world).advance(
        version_id, base_tick=society["current_tick"], base_state_sha256=society["state_sha256"]
    )
    version = objects.version(version_id)
    objects.move_object(
        version_id,
        "object:cushion",
        Transform(3_000, 0, 5_200, 3_141_593, 1000),
        base_state_sha256=version.state_sha256,
        actor=world["session"].actor,
    )
    assert placed is not None
    return society


def test_a_read_validates_what_it_shows_and_replay_validates_everything(
    saved_world,  # noqa: F811
    monkeypatch,
):
    world = saved_world
    society = _edited(world)
    version_id = world["binding"].version_id
    consumed = society["input_seq"]
    assert consumed == EDITS + 1
    seen = _counting(monkeypatch)
    snapshot = society_repository(world).snapshot(version_id, places=True)
    # The state consumed input 13; input 14 is queued and authorised too; nothing older is read.
    assert sorted(set(seen)) == [consumed, consumed + 1]
    assert snapshot["places"]["input_seq"] == consumed
    seen.clear()
    events = society_repository(world).events(version_id, limit=256)
    assert {event["document"]["input_seq"] for event in events} <= set(seen)
    assert len(set(seen)) <= 3
    seen.clear()
    stepped = society_repository(world).advance(
        version_id, base_tick=snapshot["current_tick"], base_state_sha256=snapshot["state_sha256"]
    )
    assert stepped["input_seq"] == consumed + 1
    assert set(seen) <= {consumed, consumed + 1}
    # Replay is the whole verification: it reads every input from the first.
    seen.clear()
    assert society_repository(world).replay(version_id)["replay_verified"]
    assert set(seen) == set(range(1, consumed + 2))
