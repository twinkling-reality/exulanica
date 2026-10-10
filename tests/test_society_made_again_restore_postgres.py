"""A society made again on a world version after its erasure survives a restore.

A society's identity derives from its world version alone, so the society a person brings into a
version after erasing the one before it has the erased society's id. A restore carries the
erasure and replays its society tombstone. A backup taken after the second society was made
holds the erasure itself, so the carried row is found present and deletes nothing, and the
society, its records and a Companion answer given about it after the erasure stay as the backup
holds them.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.db.session import set_workspace
from exulanica.deletion.restore import verify_restore
from exulanica.world.companion_memory import CompanionMemoryRepository, SimulationCitation
from exulanica.world.society_erasure import erase_society

from test_companion_memory import _answer
from test_purge import purged as purged
from test_restore_replay import _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _replay
from test_search_entries_on_stop import ACCOUNT
from test_society_authored_world_postgres import create_society, place_object
from test_society_authored_world_postgres import saved_world as saved_world

pytestmark = pytest.mark.postgres


def _cited(purged, binding, question: str):
    with purged.database().session(purged.workspace_id) as connection:
        return CompanionMemoryRepository(connection, purged.workspace_id, ACCOUNT).record_answer(
            _answer(
                question=question,
                answer_text="Nobody is resting.",
                world_id=binding.world_id,
                simulation_citations=(
                    SimulationCitation(
                        ordinal=0,
                        result_kind="synthetic_inhabitant",
                        version_id=binding.version_id,
                        inhabitant_id=uuid.uuid4(),
                        event_id=None,
                        tick=0,
                    ),
                ),
            )
        )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_society_made_again_after_its_erasure_and_an_answer_about_it_survive_a_restore(
    purged,
    saved_world,
    commands,
    tmp_path,
):
    world, binding = saved_world, saved_world["binding"]
    set_workspace(world["connection"], world["workspace"])
    place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    first, _document = create_society(world)
    world["connection"].commit()
    before = _cited(purged, binding, "Who was resting before?")
    with purged.database().session(purged.workspace_id) as connection:
        erase_society(
            connection, purged.workspace_id, binding.world_id, binding.version_id, erased_by=ACCOUNT
        )
    # Made again on the same version: the same identity as the society erased.
    set_workspace(world["connection"], world["workspace"])
    again, _document = create_society(world)
    world["connection"].commit()
    assert again["society_id"] == first["society_id"]
    after = _cited(purged, binding, "Who is resting now?")

    def held() -> dict[str, object]:
        [row] = purged.rows(
            "select (select count(*) from world_society where workspace_id = %s "
            "and society_id = %s) as societies, "
            "(select count(*) from world_society_input where society_id = %s) as inputs, "
            "(select count(*) from society_erasure) as erasures, "
            "(select status::text from companion_answer where answer_id = %s) as before, "
            "(select status::text from companion_answer where answer_id = %s) as after",
            purged.workspace_id,
            again["society_id"],
            again["society_id"],
            before.answer_id,
            after.answer_id,
        )
        return dict(row)

    at_the_source = held()
    # The positive control: the society made again is held, the first one's erasure is recorded,
    # the answer that cited the erased society is withdrawn and the one given after is not.
    assert at_the_source == {
        "societies": 1,
        "inputs": 1,
        "erasures": 1,
        "before": "withdrawn",
        "after": "active",
    }
    dump, blobs = _backup(purged, tmp_path)
    source, marker = _seal(tmp_path)
    _restore(purged, dump, blobs)
    assert held() == at_the_source, "the backup holds what the source held"
    _replay(source, marker)
    verify_restore(purged.database(), marker)
    assert held() == at_the_source
