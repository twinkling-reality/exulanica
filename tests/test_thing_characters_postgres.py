"""Who a placed being is, as the database, the route and a society of things hold it.

What is shown against PostgreSQL, through the routes a page writes with and the society runtime a
deployment builds:

*   the world's owner writes a character for a knight they placed; the version's society of
    things, made since the character module was built, carries it in its next input, and the
    knight keeps it from the society's next minute; the knight's card states it with its
    revision. A write over an older revision is refused (409 ``character_changed``), and so is one
    that says what the newest already says (409 ``no_change``); text out of bounds and an object
    are refused 422, an absent thing 404, and nothing is written for any of them. Clearing
    appends a record holding neither part, and the knight keeps none from the next minute;
*   migration 0213's table: a record is never changed, deleted only by the definers' owner, and
    only the newest may be replaced; the runtime role holds insert and select alone, and another
    workspace sees no row;
*   a world's erasure and a workspace's tombstone delete every record.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from test_saved_world_holding_things_postgres import (
    THINGS,
    _make,
    _offering,
    _place_knight,
    _query,
    _scope,
    _starter,
    _step,
)
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

CHARACTER = {"name": "Sir Pell", "about": "A tired knight who guards the seat and dislikes rain."}


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _write(api, entry, thing, base, character):
    return api.post(
        _scope(entry) + f"/things/{thing}/character" + _query(entry),
        {"base_revision": base, "character": character},
    )


def _records(api, entry) -> list[dict]:
    """Every record of the entry's world, oldest first, as its owner's connection reads them."""
    return [
        dict(row)
        for row in api.repository.connection.execute(
            "select placed_id,revision,name,about,base_revision from world_thing_character "
            "where workspace_id=%s and world_id=%s order by revision",
            (api.repository.workspace_id, entry["world_id"]),
        ).fetchall()
    ]


def _latest_input(api, society) -> dict:
    return api.repository.connection.execute(
        "select document from world_society_input where workspace_id=%s and society_id=%s "
        "order by input_seq desc limit 1",
        (api.repository.workspace_id, society["society_id"]),
    ).fetchone()["document"]


def _knight(society) -> dict:
    [knight] = [p for p in society["state"]["inhabitants"] if p["came_by"] == "placed"]
    return knight


def _a_society_with_a_knight(api):
    _offering(api, True)
    entry = _starter(api)
    _place_knight(api, entry)
    made = _make(api, entry, THINGS)
    assert made.status_code in (200, 201), made.text
    society = made.json()
    assert "exulanica-ability/character/v1" in society["state"]["modules"]
    return entry, society


def test_the_owner_writes_a_character_a_society_of_things_takes_in_and_clears(made):
    api = made
    entry, society = _a_society_with_a_knight(api)
    written = _write(api, entry, "knight", None, CHARACTER)
    assert written.status_code == 200, written.text
    record = written.json()
    assert record["profile"] == "exulanica.thing-character/v1"
    assert (record["placed_id"], record["character"], record["society"]) == (
        "knight",
        CHARACTER,
        "runs_characters",
    )
    assert record["written_at"].endswith("Z")
    revision = record["revision"]
    # The society's next input carries it, and the knight keeps it from its next minute.
    [entry_of_knight] = [
        t for t in _latest_input(api, society)["things"] if t["placed_id"] == "knight"
    ]
    assert entry_of_knight["character"] == CHARACTER
    society = _step(api, entry, society)
    assert _knight(society)["character"] == CHARACTER
    card = api.get(_scope(entry) + f"/society/things/{_knight(society)['id']}" + _query(entry))
    assert card.status_code == 200, card.text
    assert card.json()["character"]["character"] == CHARACTER
    assert (card.json()["character"]["revision"], card.json()["character"]["shown"]) == (
        revision,
        True,
    )

    # Refused by name, and nothing written for any of them.
    stale = _write(api, entry, "knight", None, {"name": "Sir Pell the Second"})
    assert stale.status_code == 409, stale.text
    assert stale.json() == {
        "code": "character_changed",
        "detail": "another character was written since this one was read",
        "revision": revision,
    }
    same = _write(api, entry, "knight", revision, dict(reversed(list(CHARACTER.items()))))
    assert (same.status_code, same.json()["code"]) == (409, "no_change")
    long = _write(api, entry, "knight", revision, {"name": "x" * 41})
    assert (long.status_code, long.json()["code"]) == (422, "character_out_of_bounds")
    absent = _write(api, entry, "nobody", None, CHARACTER)
    assert absent.status_code == 404, absent.text
    assert [r["revision"] for r in _records(api, entry)] == [revision]

    cleared = _write(api, entry, "knight", revision, None)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["character"] is None
    assert _records(api, entry)[-1] == {
        "placed_id": "knight",
        "revision": cleared.json()["revision"],
        "name": None,
        "about": None,
        "base_revision": revision,
    }
    society = _step(api, entry, society)
    assert "character" not in _knight(society)


def test_an_object_is_refused_a_character(made):
    api = made
    entry, _society = _a_society_with_a_knight(api)
    base = api.get(_scope(entry) + _query(entry)).json()["state_sha256"]
    placed = api.post(
        _scope(entry) + "/things" + _query(entry),
        {
            "base_state_sha256": base,
            "thing_id": "well",
            "kind": {"kind": "well", "version": 1},
            "region_id": _knight_region(api, entry),
            "pose": {"x_mm": 3_000, "y_mm": 0, "z_mm": -3_000, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text
    refused = _write(api, entry, "well", None, CHARACTER)
    assert (refused.status_code, refused.json()["code"]) == (422, "character_for_beings_only")
    assert _records(api, entry) == []


def _knight_region(api, entry) -> str:
    version = api.get(_scope(entry) + _query(entry)).json()
    [knight] = [t for t in version["things"] if t["thing_id"] == "knight"]
    return knight["region_id"]


def test_the_table_keeps_every_record_and_only_the_newest_is_replaced(made):
    api = made
    entry, _society = _a_society_with_a_knight(api)
    first = _write(api, entry, "knight", None, CHARACTER).json()["revision"]
    second = _write(api, entry, "knight", first, {"name": "Pell"}).json()["revision"]
    admin = api.repository.connection
    admin.commit()
    workspace = api.repository.workspace_id
    insert = (
        "insert into world_thing_character(workspace_id,world_id,version_id,placed_id,name,"
        "base_revision,actor) values (%s,%s,%s,'knight','Pell',%s,%s)"
    )
    where = (workspace, entry["world_id"], entry["authored_version_id"])
    for base in (None, first):
        with pytest.raises(psycopg.errors.CheckViolation, match="replaces the newest"):
            admin.execute(insert, (*where, base, uuid.uuid4()))
        admin.rollback()
    for change, guard in (
        ("update world_thing_character set name='Sir'", "appended and never changed"),
        ("delete from world_thing_character", "erased whole"),
    ):
        with pytest.raises(psycopg.errors.CheckViolation, match=guard):
            admin.execute(change)
        admin.rollback()
    assert [r["revision"] for r in _records(api, entry)] == [first, second]
    with api.database.session(workspace) as runtime:
        for privilege, held in (
            ("INSERT", True),
            ("SELECT", True),
            ("UPDATE", False),
            ("DELETE", False),
        ):
            allowed = runtime.execute(
                "select has_table_privilege(current_user,'world_thing_character',%s) as allowed",
                (privilege,),
            ).fetchone()["allowed"]
            assert allowed is held, privilege
        # The positive control for the stranger below: the owner's own session sees its rows.
        assert (
            runtime.execute("select count(*) as n from world_thing_character").fetchone()["n"] == 2
        )
    with api.database.session(uuid.uuid4()) as stranger:
        assert (
            stranger.execute("select count(*) as n from world_thing_character").fetchone()["n"] == 0
        )


def test_a_world_s_erasure_deletes_every_record(made):
    api = made
    entry, _society = _a_society_with_a_knight(api)
    first = _write(api, entry, "knight", None, CHARACTER).json()["revision"]
    _write(api, entry, "knight", first, None)
    assert len(_records(api, entry)) == 2
    admin = api.repository.connection
    admin.commit()
    workspace = api.repository.workspace_id
    with admin.transaction():
        admin.execute("set local role exulanica_definer")
        admin.execute("select set_config('exulanica.workspace_id', %s, true)", (str(workspace),))
        admin.execute("select participation_erase(%s, %s)", (workspace, entry["world_id"]))
        admin.execute("select world_erase_rows(%s, %s)", (workspace, entry["world_id"]))
    assert _records(api, entry) == []


def test_a_workspace_s_tombstone_deletes_every_record(made):
    api = made
    entry, _society = _a_society_with_a_knight(api)
    _write(api, entry, "knight", None, CHARACTER)
    assert len(_records(api, entry)) == 1
    api.repository.connection.commit()
    with api.database.session(api.repository.workspace_id) as runtime:
        runtime.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'the workspace is erased')",
            (api.repository.workspace_id, api.actor),
        )
    assert _records(api, entry) == []
