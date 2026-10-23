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
from exulanica.world.society import society_state_sha256
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_moments import (
    MOMENTS_PROFILE,
    RULES_PROFILE,
    _Stored,
    backfill,
    touched_spans,
)
from exulanica.world.society_repository import SocietyRepository
from psycopg.types.json import Jsonb

import test_society_erasure_postgres as erasure
import test_society_stay_requests_api as stays
from test_society_person_decisions_postgres import _services
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres


def _moment_rows(connection, society_id) -> list[dict]:
    rows = connection.execute(
        "select moment_id, kind, subjects, request_id, document from world_society_moment "
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
    # Each moment and each line names the decision that made it, so a page can open it.
    request = str(said["request_id"])
    assert said["request_id"] is not None, "the positive control: a person's line answers a request"
    assert moment["request_id"] == request
    assert moment["said"][0]["request_id"] == request
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
def test_the_story_keeps_what_was_decided_and_who_was_touched_and_not_strangers_meetings(app):
    """H18: History's line holds what a model, a person playing or a program decided, and the
    moments of a being the person touched; a routine meeting of two nobody touched stays in the
    record (the read without story) but not on the line."""
    world, client = app
    services = _services(client)
    _, knight = erasure._played_line(world, client, services)
    knight = uuid.UUID(str(knight))
    connection = world["connection"]
    society_id = erasure._society_id(world)
    said = connection.execute(
        "select event_id, tick from world_society_event "
        "where society_id=%s and event_kind='said' order by tick limit 1",
        (society_id,),
    ).fetchone()
    tick = int(said["tick"])
    strangers = [uuid.uuid4(), uuid.uuid4()]
    with connection.transaction():
        _later(connection, world, society_id, said["event_id"], tick + 1, "met", strangers)
        _later(
            connection, world, society_id, said["event_id"], tick + 2, "met", [strangers[0], knight]
        )
        _later(connection, world, society_id, said["event_id"], tick + 3, "met", strangers[::-1])
    scope, version, _ = routes(world)

    def read(**more):
        return client.get(
            version + "/history/moments", headers=OWNER, params={**scope, **more}
        ).json()

    every = read()["moments"]
    story = read(story="true")["moments"]
    # The positive control: the record holds the strangers' two meetings.
    stranger_ticks = {tick + 1, tick + 3}
    assert stranger_ticks <= {moment["tick"] for moment in every}
    assert not stranger_ticks & {moment["tick"] for moment in story}
    assert tick + 2 in {moment["tick"] for moment in story}, "a meeting with the placed knight"
    lines = [one["line"] for moment in story for one in moment["said"]]
    assert erasure.LINE in lines, "the person playing's line, with its words"
    # What the line leaves out is routine and names nobody the person touched.
    kept = {moment["moment_id"] for moment in story}
    left = [moment for moment in every if moment["moment_id"] not in kept]
    assert stranger_ticks <= {moment["tick"] for moment in left}
    assert all(m["decider"]["kind"] == "routine" and str(knight) not in m["subjects"] for m in left)
    assert kept <= {moment["moment_id"] for moment in every}
    # Paging counts within the story: one at a time, the strangers' meetings never fill a page.
    newest = read(story="true", limit=1)
    assert [moment["tick"] for moment in newest["moments"]] == [tick + 2]
    assert newest["more"] is True
    older = read(story="true", limit=1, before=tick + 2)["moments"]
    assert older and older[0]["tick"] <= tick


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


def _choice(
    connection, world, row, subjects, model, recorded_at=None, *, decider=None, ended=None
) -> None:
    """A person's model choice for ``subjects``: in the first choice's shape, ``model`` a model or
    None, the routine; with ``decider``, that decider, and ``ended`` where it ends a person's play;
    recorded at ``recorded_at`` where given, else now."""
    role = person_role()
    sequence = connection.execute(
        "select coalesce(max(choice_seq), 0) + 1 as next from world_society_model_choice "
        "where workspace_id=%s and world_id=%s and society_id=%s",
        (world["workspace"], row["world_id"], row["society_id"]),
    ).fetchone()["next"]
    document = {
        "profile": role.choice_profile,
        "choice_seq": sequence,
        "request_id": str(uuid.uuid4()),
        "society_id": str(row["society_id"]),
        role.choice_subjects: [str(one) for one in subjects],
        **({"model": model} if decider is None else {"decider": decider}),
        **({"ended": ended} if ended else {}),
        "contract": {},
        "chosen_by": str(world["session"].actor),
    }
    document["document_sha256"] = society_state_sha256(document)
    connection.execute(
        "insert into world_society_model_choice(workspace_id,world_id,society_id,choice_seq,"
        "request_id,document,document_sha256,chosen_by,recorded_at) "
        "values(%s,%s,%s,%s,%s,%s,%s,%s,coalesce(%s,statement_timestamp()))",
        (
            world["workspace"],
            row["world_id"],
            row["society_id"],
            sequence,
            uuid.UUID(document["request_id"]),
            Jsonb(document),
            document["document_sha256"],
            world["session"].actor,
            recorded_at,
        ),
    )


MODEL = {"provider": "test", "model_id": "test"}
PLAYED = {"kind": "person", "account_id": str(uuid.UUID(int=0xA1))}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_each_source_of_a_touched_being_counts_alone(app):
    """A being counts as touched by any one source alone: a decision request for them, their
    coming by being placed, or a model choice giving them a model (H18's three sources, each
    apart); a choice that leaves them to their routine touches nobody."""
    world, client = app
    _, knight = erasure._played_line(world, client, _services(client))
    knight = uuid.UUID(str(knight))
    connection = world["connection"]
    _, row = _replayed(world)

    def touched(inhabitants: list[dict], **where) -> set[uuid.UUID]:
        state = {"inhabitants": inhabitants}
        spans = touched_spans(connection, world["workspace"], {**row, **where, "state": state})
        return {being for being, _opened, _closed in spans}

    # A decision request alone: read as of a world with no model choices (the choices' half names
    # its world; a request has no world column) and with nobody placed, the knight the person
    # played is touched by the requests made for them.
    assert knight in touched([], world_id=f"world:generated:{uuid.uuid4()}")
    asked = touched([])
    # A placement alone: a being placed counts with no request or choice; one that came otherwise
    # does not.
    placed, populated = uuid.uuid4(), uuid.uuid4()
    people = [
        {"id": str(placed), "came_by": "placed"},
        {"id": str(populated), "came_by": "populated"},
    ]
    assert touched(people) - asked == {placed}
    # A model choice alone: a being given a model counts with no request or placement; one a
    # choice leaves to its routine does not.
    chosen, routine = uuid.uuid4(), uuid.uuid4()
    with connection.transaction():
        _choice(connection, world, row, [chosen], MODEL)
        _choice(connection, world, row, [routine], None)
    assert touched([]) - asked == {chosen}


def _four_meetings(world, client, choices):
    """A resident's routine meetings in four minutes recorded one after another, each anchored to
    one, with ``choices(between)`` made for the resident in the same transaction; answers the four
    ticks, the ticks the record holds and the ticks the story holds."""
    erasure._played_line(world, client, _services(client))
    connection = world["connection"]
    society_id = erasure._society_id(world)
    _, row = _replayed(world)
    times = connection.execute(
        "select distinct on (recorded_at) event_id, recorded_at from world_society_event "
        "where society_id=%s order by recorded_at, event_id",
        (society_id,),
    ).fetchall()
    assert len(times) >= 4, "the played world records minutes at four times"
    anchors = times[-4:]
    top = connection.execute(
        "select max(tick) as tick from world_society_moment where society_id=%s", (society_id,)
    ).fetchone()["tick"]
    ticks = [int(top or 0) + index for index in range(1, 5)]

    def between(first, second):
        earlier, later = anchors[first]["recorded_at"], anchors[second]["recorded_at"]
        return earlier + (later - earlier) / 2

    resident, other = uuid.uuid4(), uuid.uuid4()
    with connection.transaction():
        for anchor, tick in zip(anchors, ticks, strict=True):
            _later(
                connection, world, society_id, anchor["event_id"], tick, "met", [resident, other]
            )
        for model, at, more in choices(between):
            _choice(connection, world, row, [resident], model, at, **more)
    scope, version, _ = routes(world)

    def read(**more):
        return client.get(
            version + "/history/moments", headers=OWNER, params={**scope, **more}
        ).json()["moments"]

    every = {moment["tick"] for moment in read()}
    story = {moment["tick"] for moment in read(story="true")}
    return ticks, every & set(ticks), story & set(ticks)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_resident_is_in_the_story_only_while_the_person_s_hand_is_on_them(app):
    """H18 as amended: a resident given a model is in the person's story from that choice until a
    choice sets them back to routine; their routine meetings recorded after it leave the line, and
    given a model again they come back (creature-town's Dev and Ada were given a model on 18 October
    and set back, and their meetings of today filled History's line)."""
    world, client = app
    # Given a model after the first meeting, set back to routine after the second and given a model
    # again before the fourth.
    ticks, every, story = _four_meetings(
        world,
        client,
        lambda between: [
            (MODEL, between(0, 1), {}),
            (None, between(1, 2), {}),
            (MODEL, between(2, 3), {}),
        ],
    )
    # The positive control: the record holds all four meetings.
    assert every == set(ticks)
    assert story == {ticks[1], ticks[3]}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_play_ending_inside_a_span_gives_back_the_model_and_the_span_runs_on(app):
    """A person plays the resident while their model decides, then gives them back: the model
    decides again, as every reader of who decides reads it (choice_steps), so the span runs on and
    the meeting after the play stays on the line."""
    world, client = app
    ticks, every, story = _four_meetings(
        world,
        client,
        lambda between: [
            (MODEL, between(0, 1), {}),
            (None, between(1, 2), {"decider": PLAYED}),
            (None, between(2, 3), {"decider": PLAYED, "ended": "given_back"}),
        ],
    )
    assert every == set(ticks)
    assert story == {ticks[1], ticks[2], ticks[3]}
