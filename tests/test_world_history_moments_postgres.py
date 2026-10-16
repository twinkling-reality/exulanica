"""A world's moments, written with the minute that made them, read for its History, back-filled
through the replay, and erased with their society (private PostgreSQL).

A knight played by a person says a line beside another: the minute that records the line records
its moment in the same transaction, and the History read joins the line from its event, names who
decided and keeps no words of its own. The replay's back-fill finds the moment written and adds
nothing; the society's erasure leaves none. Played before moments were written, the same line is
back-filled from the replay, each minute formed from the moments before it alone, however many later
minutes have moments already. A version's History reads its own society alone, beside another
version's.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.world import society_repository
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.society_moments import MOMENTS_PROFILE, RULES_PROFILE, _Stored, backfill
from exulanica.world.society_repository import SocietyRepository

import test_society_erasure_postgres as erasure
import test_society_stay_requests_api as stays
from test_society_person_decisions_postgres import _services
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres


def _moment_rows(connection, society_id) -> list[dict]:
    rows = connection.execute(
        "select moment_id, kind, subjects, document from world_society_moment "
        "where society_id = %s order by tick, moment_id",
        (society_id,),
    ).fetchall()
    connection.commit()
    return rows


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_line_said_is_a_moment_read_with_its_line_back_filled_once_and_erased(app):
    world, client = app
    services = _services(client)
    _, knight = erasure._played_line(world, client, services)
    connection = world["connection"]
    society_id = erasure._society_id(world)

    # Written with the minute: the line's moment is there once the minute is, with no words.
    rows = _moment_rows(connection, society_id)
    [said] = [row for row in rows if row["subjects"][0] == uuid.UUID(knight)]
    assert said["kind"] in {"met", "spoke_to_all"}
    assert erasure.LINE not in str(said["document"]), "a moment keeps no one's words"
    assert said["document"]["decider"] == {"kind": "person", "model": None}

    # Read for History: the line joined from its event, who decided, the rule it was formed by.
    scope, version, _ = routes(world)
    answer = client.get(version + "/history/moments", headers=OWNER, params=scope)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["profile"], body["rule_version"], body["more"]) == (
        MOMENTS_PROFILE,
        RULES_PROFILE,
        False,
    )
    [moment] = [m for m in body["moments"] if m["moment_id"] == str(said["moment_id"])]
    assert moment["said"][0]["line"] == erasure.LINE
    assert moment["said"][0]["by"] == knight
    assert moment["decider"] == {"kind": "person", "model": None}
    assert moment["said"][0]["decider"] == {"kind": "person", "model": None}, "each line's own"
    assert moment["at"] is not None, "a person's time, to order moments among edits"
    assert moment["picture"] is None and moment["branches"] == []
    assert moment["scene"]["people"][0]["id"] == knight
    assert body["now"]["tick"] >= moment["tick"]
    # Paging: nothing before the first minute.
    earlier = client.get(
        version + "/history/moments", headers=OWNER, params={**scope, "before": 0}
    ).json()
    assert (earlier["moments"], earlier["more"]) == ([], False)

    # The back-fill replays every minute played and finds the moment written: it adds nothing.
    repository = SocietyRepository(
        connection,
        world["workspace"],
        world_id=world["binding"].world_id,
        input_authorizer=lambda _document: None,
    )
    row = repository._row(world["binding"].version_id)
    with connection.transaction():
        seen = backfill(repository.replay, connection, world["workspace"], row, row["version_id"])
    assert seen == row["current_tick"]
    assert _moment_rows(connection, society_id) == rows

    # Erased with its society, as every record of it is.
    erased = client.delete(version + "/society", headers=OWNER, params=scope)
    assert erased.status_code == 204, erased.text
    assert _moment_rows(connection, society_id) == []


def _replayed(world) -> tuple[SocietyRepository, dict]:
    repository = SocietyRepository(
        world["connection"],
        world["workspace"],
        world_id=world["binding"].world_id,
        input_authorizer=lambda _document: None,
    )
    return repository, repository._row(world["binding"].version_id)


def _later(connection, world, society_id, anchor, tick, kind, subjects) -> None:
    """A moment of a later minute, as the hook writes one for a minute played after these."""
    connection.execute(
        "insert into world_society_moment(workspace_id,moment_id,society_id,version_id,tick,kind,"
        "rule_version,anchor_event_id,event_ids,request_id,subjects,document,document_sha256) "
        "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,null,%s,'{}'::jsonb,repeat('0',64))",
        (
            world["workspace"],
            uuid.uuid4(),
            society_id,
            world["binding"].version_id,
            tick,
            kind,
            RULES_PROFILE,
            anchor,
            [anchor],
            subjects,
        ),
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_back_fill_forms_each_minute_from_the_moments_before_it_alone(app, monkeypatch):
    world, client = app
    services = _services(client)
    with monkeypatch.context() as quiet:
        # As a world played before moments were written: its minutes write none.
        quiet.setattr(society_repository, "record_moments", lambda *_args, **_keywords: [])
        _, knight = erasure._played_line(world, client, services)
    connection = world["connection"]
    society_id = erasure._society_id(world)
    assert _moment_rows(connection, society_id) == [], "the positive control: played without them"
    knight_id = uuid.UUID(knight)
    said = connection.execute(
        "select event_id, tick, document->'thing'->>'to' as listener from world_society_event "
        "where society_id=%s and subject_id=%s and event_kind='said'",
        (society_id, knight_id),
    ).fetchone()
    connection.commit()
    listener = None if said["listener"] is None else uuid.UUID(said["listener"])
    early, late = int(said["tick"]), int(said["tick"]) + 100
    # Minutes played under the hook after these, before the back-fill ran: a going of the knight's,
    # and a meeting of the knight's with its listener (or with someone, for a line to everyone).
    other = listener or uuid.uuid4()
    _later(connection, world, society_id, said["event_id"], late, "went", [knight_id])
    _later(connection, world, society_id, said["event_id"], late, "met", [knight_id, other])
    connection.commit()
    workspace = world["workspace"]
    before, after = (_Stored(connection, workspace, society_id, at) for at in (early, late + 1))
    assert (before.met(knight_id, other), before.last_went(knight_id)) == (False, None)
    assert (after.met(knight_id, other), after.last_went(knight_id)) == (True, late)

    repository, row = _replayed(world)
    with connection.transaction():
        seen = backfill(repository.replay, connection, world["workspace"], row, row["version_id"])
    assert seen == row["current_tick"]
    [formed] = [
        one
        for one in _moment_rows(connection, society_id)
        if one["subjects"][0] == knight_id and one["document"]
    ]
    # The knight's first line to its listener is the meeting it was, not speech after a later one.
    assert formed["kind"] == ("met" if listener else "spoke_to_all")
    assert formed["document"]["decider"] == {"kind": "person", "model": None}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_version_s_history_reads_its_own_society_s_moments_and_lines_alone(app, monkeypatch):
    world, client = app
    services = _services(client)
    erasure._played_line(world, client, services)
    connection = world["connection"]
    # Another version of the same world, in the same workspace, whose knight says another line.
    with connection.transaction():
        style = WorldStyleRepository(connection, world["workspace"], world_id=world["world_id"])
        other_version = world["objects"].create_version(
            source_snapshot_id=world["binding"].source_snapshot_id,
            title="Another version",
            style_version_id=style.current().version_id,
            created_by=world["session"].actor,
        )
    versioned = {
        **world,
        "binding": world["binding"].model_copy(update={"version_id": other_version.version_id}),
    }
    elsewhere = "The tide turns at the third bell."
    with monkeypatch.context() as other_line:
        other_line.setattr(erasure, "LINE", elsewhere)
        erasure._played_line(versioned, client, services)
    societies = {erasure._society_id(world), erasure._society_id(versioned)}
    assert len(societies) == 2, "the positive control: two societies in one workspace"
    for held, line in ((world, erasure.LINE), (versioned, elsewhere)):
        scope, version, _ = routes(held)
        body = client.get(version + "/history/moments", headers=OWNER, params=scope).json()
        own = {row["moment_id"] for row in _moment_rows(connection, erasure._society_id(held))}
        read = {moment["moment_id"] for moment in body["moments"]}
        assert read and read <= {str(moment_id) for moment_id in own}
        said = {one["line"] for moment in body["moments"] for one in moment["said"]}
        assert said == {line}, said
