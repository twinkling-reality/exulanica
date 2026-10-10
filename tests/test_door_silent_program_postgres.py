"""A silent outside program does not slow its world, against PostgreSQL.

Through the real routes, with a decision host asking the door for one of a society of things' own
beings, which a grant hands to a bridge's program and which is asked every minute: a program that
stays connected but lets its asks pass is asked again only now and then, and each turn between is
refused at once and decided by the routine (``docs/door-contract.md``, the decision host's asks).
What is shown:

*   after a run of unanswered asks for one thing, its turns between are refused at once as
    ``decider_disconnected``, with no ask written for the program to let pass, and the program is
    asked for it again once enough of the world's minutes have passed since its last ask for it;
    another thing of the same grant whose asks it answers is asked every minute all along;
*   a program that says hello again is asked at its thing's next turn;
*   a program that answers again is asked every minute again.

Whether the program answers an ask is the test's own choice, and the world's wait follows that
choice rather than the clock, so a loaded machine changes none of it. Where the routine walks the
knight is the seed's, so the society starts from a chosen one, and each turn read is held to be the
one its own minute recorded: a being with nothing to choose is not asked at all
(``docs/decision-roles-contract.md``), and a minute with no turn is never read as the one before.
"""

from __future__ import annotations

from typing import Any

import pytest
from exulanica.door import asker as asker_module

import test_society_authored_world_postgres as helpers
import test_society_person_decisions_postgres as decisions
from society_seed_support import choose_society_seed
from test_door_crossings_postgres import crossings as crossings
from test_door_lines_postgres import _Bridge, _host, _Knight, _minute, _person
from test_door_postgres import OWNER, _bridges, _credential, _hello
from test_door_postgres import door as door
from test_society_things_postgres import _make_society, _place

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres

#: The run of unanswered asks and the minutes between asks after it, small so the test is short.
AFTER = 2
EVERY = 3
#: The program's answer window: the longest the decision contract lets a world wait
#: (decision_deadline_ms), so an ask the program answers is never cut short by a loaded machine.
DEADLINE_MS = 20_000
#: The seed the society starts from (sha256 of "door-silent-program-0"). The one a saved world
#: derives from its workspace and world ids changes each run, and under some the routine walks the
#: knight out of everyone's hearing with something still under way, where it has nothing but going
#: on to choose and is not asked, so that minute records no turn for it. Under this one the knight
#: and the squire each have something to choose in every minute the test plays.
SEED = "efdb9fcce2332384424ef1265bbe00febf867ddb8094c6b48939a9f8b8e06a7d"


def _asks(door, grant_id: str, subject: str) -> int:
    """How many asks for ``subject`` were written for the grant's program."""
    world = door["world"]
    row = (
        world["connection"]
        .execute(
            "select count(*) as asks from door_ask k join world_society_decision_request r "
            "  on r.workspace_id = k.workspace_id and r.request_id = k.request_id "
            "where k.workspace_id = %s and k.grant_id = %s and r.subject_id = %s",
            (world["workspace"], grant_id, subject),
        )
        .fetchone()
    )
    return int(row["asks"])


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_silent_program_is_asked_now_and_then_and_its_world_does_not_wait(
    door, crossings, monkeypatch
):
    monkeypatch.setattr(asker_module, "SILENT_AFTER_UNANSWERED", AFTER)
    monkeypatch.setattr(asker_module, "SILENT_ASK_EVERY_MINUTES", EVERY)
    client, runtime = door["application"](
        _bridges(door["world"]["workspace"], deadline_ms=DEADLINE_MS)
    )
    door = {**door, "client": client, "runtime": runtime}
    # A society of things with two knights the grant hands to the program: it answers for one of
    # them all along and lets the other's asks pass.
    world = door["world"]
    choose_society_seed(client.app, SEED)
    _place(client, world, "well", "well", 2, -4_000, 2_000)
    _place(client, world, "knight", "knight", 1, 3_000, 3_000)
    _place(client, world, "squire", "knight", 1, -3_000, 3_000)
    society = _make_society(client, world)
    knight = _person(society, placed="knight")["id"]
    squire = _person(society, placed="squire")["id"]
    issued = client.post(
        "/door/grants",
        headers=OWNER,
        params={"world_id": world["binding"].world_id},
        json={
            "idempotency_key": "silent-program-knight",
            "bridge": "test-bridge",
            "things": [knight, squire],
            "version_id": str(world["binding"].version_id),
        },
    )
    assert issued.status_code == 201, issued.text
    grant_id = issued.json()["grant"]["grant_id"]
    channel = _credential(door, grant_id)
    hello = _hello(door, channel)
    assert hello.status_code == 200, hello.text
    host, _manifest, _model_id = _host(door, _Knight())
    services = client.app.state.services
    answering: list[bool] = [False]

    def lets_pass(subject_id: str) -> bool:
        return subject_id == knight and not answering[0]

    def choose(frame: dict[str, Any]) -> dict[str, Any] | None:
        return None if lets_pass(frame["subject_id"]) else {"label": frame["idle_label"]}

    # Whether the program answers an ask is this test's own choice, so the world's wait follows it
    # rather than the clock: an ask the program lets pass ends as soon as it is written, as one
    # whose window ran out does, and one it answers is waited for through the whole window.
    asked = asker_module.DoorAsker.answer

    def answer(self, workspace_id, world_id, request, ends_at):
        if lets_pass(request["subject_id"]):
            ends_at = self.monotonic()
        return asked(self, workspace_id, world_id, request, ends_at)

    monkeypatch.setattr(asker_module.DoorAsker, "answer", answer)

    def turns(count: int) -> list[tuple[str, int]]:
        """The knight's next ``count`` turns: each one's reason and the asks for it written by its
        end; the squire's turns are each asked and answered meanwhile. Each turn read is the one
        its own minute recorded."""
        nonlocal society
        seen = []
        for _ in range(count):
            minute = society["current_tick"]
            society = _minute(door, host, world, society)
            receipts = [
                d
                for d in decisions._decisions(services, world, society)
                if d["base_tick"] == minute
            ]
            mine = [d for d in receipts if d["subject_id"] == knight]
            theirs = [d for d in receipts if d["subject_id"] == squire]
            # A being with nothing to choose is not asked, and its minute records no turn.
            assert (len(mine), len(theirs)) == (1, 1), (
                f"minute {minute} recorded {len(mine)} turns of the knight and {len(theirs)} of "
                "the squire: under SEED each has something to choose in every minute"
            )
            assert theirs[0]["reason"] == "validated_choice", theirs[0]
            seen.append((mine[0]["reason"], _asks(door, grant_id, knight)))
        return seen

    with _Bridge(client, channel, hello.json()["cursor"], choose):
        # Two asks let pass, then refused at once until three minutes after the last ask, when the
        # program is asked again; one more let pass, and refused again.
        assert turns(8) == [
            ("no_answer_in_time", 1),
            ("no_answer_in_time", 2),
            ("decider_disconnected", 2),
            ("decider_disconnected", 2),
            ("no_answer_in_time", 3),
            ("decider_disconnected", 3),
            ("decider_disconnected", 3),
            ("no_answer_in_time", 4),
        ]
        # It says hello again: asked at once, though its last ask was a minute ago.
        assert _hello(door, channel).status_code == 200
        assert turns(1) == [("no_answer_in_time", 5)]
        # It answers again: asked every minute.
        answering[0] = True
        assert _hello(door, channel).status_code == 200
        assert turns(3) == [
            ("validated_choice", 6),
            ("validated_choice", 7),
            ("validated_choice", 8),
        ]
