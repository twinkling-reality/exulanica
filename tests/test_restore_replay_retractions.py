"""A restore keeps a person's retractions, and what each retraction ended with it.

A person who withdraws a claim they made writes a retraction row and retracts the claim
(``AssertionWriter.retract``). A retracted name leaves its place (migration 0002), and a place-name
right rests on an active naming claim (0097), so a backup taken before the retraction holds the
name and the right as current. The withdrawal catalog carries the retraction
(``exulanica/deletion/withdrawals.v2.json``, kind ``retraction``) and replay writes it again with
the product's retract, given to it by ``exulanica.orchestration.restore``.

The real restore below backs up with ``pg_dump``, retracts the product's way, seals, restores with
``psql`` and replays with the command, on the private test server's scratch schema. The branches
of one write, the census that keeps a tombstone's retractions out, the seal and the writers a
replay must be given are held beside it.
"""

from __future__ import annotations

import re
import uuid

import psycopg
import pytest
from exulanica.deletion import restore as deletion_restore
from exulanica.deletion.restore import RestoreRefused, replay, verify_restore
from exulanica.deletion.withdrawals import (
    Carried,
    CarryRefused,
    read_withdrawals,
    reapply,
    stale_withdrawals,
)
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import rename_entity, undo
from exulanica.orchestration.restore import WRITERS

from test_place_name_rights import PLACE, PLANNER, _released
from test_place_name_rights import _grant as _grant_place_name
from test_place_name_rights import _state as _place_name_state
from test_place_name_rights import named as named
from test_purge import purged as purged
from test_restore_replay import _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _replay
from test_search_entries_on_stop import _as_runtime

pytestmark = pytest.mark.postgres

ROLE = "structured_extraction"


def _naming(named) -> uuid.UUID:
    """The active naming claim the place's name is the cache of."""
    _, _, assertions, _, entities = named
    found = assertions.active_naming_assertion(entities["place"], PLACE)
    assert found is not None, "the place is named"
    return found


def _retract(purged, assertion_id: uuid.UUID, actor: uuid.UUID, reason: str) -> uuid.UUID:
    """Retract the claim the product's way, as the runtime role."""
    with _as_runtime(purged) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
        return AssertionWriter(connection, purged.workspace_id).retract(
            assertion_id, retracted_by=actor, reason=reason
        )


def _display_name(named) -> str | None:
    repository, _, _, _, entities = named
    return repository.connection.execute(
        "select display_name from entity where entity_id=%s", (entities["place"],)
    ).fetchone()["display_name"]


def _retraction_row(purged, retraction_id: uuid.UUID) -> dict | None:
    rows = purged.rows(
        "select to_jsonb(r) as row from retraction r where retraction_id=%s", retraction_id
    )
    return rows[0]["row"] if rows else None


# -- through a real restore ----------------------------------------------------------------------


def test_a_name_retracted_after_the_backup_stays_retracted_and_its_right_stays_ended(
    named, purged, commands, tmp_path
):
    _, _, _, actor, entities = named
    _grant_place_name(named, ROLE)
    assert _released(named, PLANNER) == {entities["place"]}, "the positive control"
    claim = _naming(named)
    dump, blobs = _backup(purged, tmp_path)

    retraction = _retract(purged, claim, actor, "not what this place is called")
    assert _display_name(named) is None, "the retraction took the name off the place"
    assert _released(named, PLANNER) == frozenset(), "and ended the right resting on it"
    after = _place_name_state(named, ROLE)
    written = _retraction_row(purged, retraction)
    source, marker = _seal(tmp_path)

    _restore(purged, dump, blobs)
    assert _display_name(named) == PLACE, "the backup holds the name"
    assert _released(named, PLANNER) == {entities["place"]}, "and the right"
    assert _retraction_row(purged, retraction) is None

    _replay(source, marker)
    verify_restore(purged.database(), marker)

    assert _retraction_row(purged, retraction) == written, "the person's retraction, as made"
    assert purged.rows("select status::text from assertion where assertion_id=%s", claim) == [
        {"status": "retracted"}
    ]
    assert _display_name(named) is None
    assert _released(named, PLANNER) == frozenset()
    assert _place_name_state(named, ROLE) == after


# -- one write's branches ------------------------------------------------------------------------


def test_a_retraction_write_finds_it_present_differing_absent_or_writes_it(named, purged):
    _, _, _, actor, _ = named
    claim = _naming(named)
    connection = purged.repository.connection
    with connection.transaction(force_rollback=True):
        made = AssertionWriter(connection, purged.workspace_id).retract(
            claim, retracted_by=actor, reason="the name was wrong"
        )
        [row] = purged.rows(
            "select to_jsonb(r) as row from retraction r where retraction_id=%s", made
        )
    carried = Carried("retraction", row["row"])
    assert _display_name(named) == PLACE, "the positive control: rolled back, still named"

    assert reapply(connection, carried, WRITERS) == "carried"
    assert _retraction_row(purged, made) == carried.row
    assert _display_name(named) is None, "the product's retract ran, and its trigger with it"
    assert reapply(connection, carried, WRITERS) == "present"
    with pytest.raises(CarryRefused, match="differs from the withdrawal the checkpoint records"):
        reapply(connection, Carried("retraction", {**carried.row, "reason": "another"}), WRITERS)
    nobody = {**carried.row, "retraction_id": str(uuid.uuid4()), "assertion_id": str(uuid.uuid4())}
    assert reapply(connection, Carried("retraction", nobody), WRITERS) == "absent"


def test_a_writer_that_writes_another_row_than_the_checkpoints_is_refused(named, purged):
    """The writer is given the retraction's identity and time; one that drops them is caught."""
    _, _, _, actor, _ = named
    claim = _naming(named)
    connection = purged.repository.connection
    with connection.transaction(force_rollback=True):
        made = AssertionWriter(connection, purged.workspace_id).retract(
            claim, retracted_by=actor, reason="the name was wrong"
        )
        [row] = purged.rows(
            "select to_jsonb(r) as row from retraction r where retraction_id=%s", made
        )

    def forgetful(connection, carried) -> None:
        AssertionWriter(connection, uuid.UUID(carried["workspace_id"])).retract(
            uuid.UUID(carried["assertion_id"]),
            retracted_by=uuid.UUID(carried["retracted_by"]),
            reason=carried["reason"],
        )

    with (
        connection.transaction(force_rollback=True),
        pytest.raises(CarryRefused, match="did not write the retraction row"),
    ):
        reapply(connection, Carried("retraction", row["row"]), {**WRITERS, "retract": forgetful})


def test_a_retraction_the_checkpoint_lacks_is_stale(named, purged):
    _, _, _, actor, _ = named
    retraction = _retract(purged, _naming(named), actor, "the name was wrong")
    carried = read_withdrawals(purged.repository.connection)
    assert [item.row["retraction_id"] for item in carried if item.kind == "retraction"] == [
        str(retraction)
    ]
    stale = stale_withdrawals(purged.repository.connection, [])
    assert [(kind, row["retraction_id"]) for kind, row in stale if kind == "retraction"] == [
        ("retraction", str(retraction))
    ]
    assert stale_withdrawals(purged.repository.connection, carried) == []


# -- what is not carried ---------------------------------------------------------------------------


def test_only_a_retraction_of_a_claim_a_person_stated_is_carried(named, purged):
    """A claim of another kind, retracted, is not a person's withdrawal of their own statement."""
    _, _, _, actor, _ = named
    [inferred] = purged.rows(
        "select assertion_id from assertion where kind <> 'user' and status = 'active' "
        "order by assertion_id limit 1"
    )
    other = _retract(purged, inferred["assertion_id"], actor, "a model's claim, taken back")
    theirs = _retract(purged, _naming(named), actor, "the name was wrong")
    carried = {
        item.row["retraction_id"]
        for item in read_withdrawals(purged.repository.connection)
        if item.kind == "retraction"
    }
    assert carried == {str(theirs)}, "the positive control is the person's own"
    assert str(other) not in carried


def test_every_retraction_a_trigger_writes_retracts_a_claim_no_person_can_state(repository):
    """A tombstone's cascade writes the only other retractions, and the replayed tombstone again.

    Asked of the migrated schema: every function that inserts a retraction, and every predicate
    it retracts, which must not allow a user's claim; otherwise the catalog's kind 'user' would
    carry a row the replayed cascade also writes.
    """
    connection = repository.connection
    writers = connection.execute(
        "select p.proname as name, p.prosrc as body from pg_proc p "
        "where p.pronamespace = current_schema()::regnamespace "
        "and p.prosrc ~* 'insert\\s+into\\s+retraction'"
    ).fetchall()
    assert [row["name"] for row in writers] == ["retract_scene_rungs_for_tombstone"]
    for row in writers:
        predicates = set(re.findall(r"p\.key\s*=\s*'([a-z_]+)'", row["body"]))
        assert predicates, "the positive control: the cascade names what it retracts"
        allowed = connection.execute(
            "select key, allows_kind::text[] as kinds from predicate where key = any(%s)",
            (sorted(predicates),),
        ).fetchall()
        assert {item["key"] for item in allowed} == predicates
        for item in allowed:
            assert "user" not in item["kinds"], item


# -- the seal and the writers a replay is given ----------------------------------------------------


def test_a_sealed_checkpoint_refuses_a_retraction(named, purged, commands, tmp_path):
    _, _, _, actor, _ = named
    claim = _naming(named)
    _seal(tmp_path)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"):
        _retract(purged, claim, actor, "the name was wrong")
    assert _display_name(named) == PLACE


@pytest.mark.parametrize(
    ("writers", "refusal"),
    [
        ({}, "was not given the writers the withdrawal catalog names"),
        (
            {key: value for key, value in WRITERS.items() if key != "retract"},
            r"was not given the writers the withdrawal catalog names: \['retract'\]",
        ),
        ({**WRITERS, "rumour": WRITERS["retract"]}, r"does not name: \['rumour'\]"),
    ],
    ids=["none", "one-missing", "one-unnamed"],
)
def test_replay_without_exactly_the_catalogs_writers_refuses_before_anything(
    purged, commands, tmp_path, writers, refusal
):
    source, marker = _seal(tmp_path)
    with pytest.raises(RestoreRefused, match=refusal):
        replay(purged.database(), purged.database(), purged.store, source, marker, writers=writers)
    assert purged.rows("select state from restore_control") == [{"state": "sealed"}]


def test_the_old_restore_command_names_where_the_command_is():
    with pytest.raises(SystemExit, match=r"python -m exulanica\.orchestration\.restore"):
        deletion_restore.main(["checkpoint", "--checkpoint", "unused"])


# -- the product's own caller is unchanged ---------------------------------------------------------


class _Recording:
    """A connection that records each statement it is given and runs it."""

    def __init__(self, connection) -> None:
        object.__setattr__(self, "_connection", connection)
        object.__setattr__(self, "statements", [])

    def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        return self._connection.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __setattr__(self, name, value) -> None:
        setattr(self._connection, name, value)


def test_undoing_a_first_naming_retracts_exactly_as_before(named, purged):
    """Identity undo, the product's caller, writes the statement and the defaults it always did."""
    repository, identity, assertions, actor, entities = named
    assertions.retract(_naming(named), retracted_by=actor, reason="unnamed again")
    rename_entity(
        identity, assertions, entity_id=entities["place"], display_name="The Old Mill", actor=actor
    )
    [renamed] = purged.rows(
        "select event_id, payload from identity_event where type = 'entity_renamed' "
        "order by created_at desc, event_id desc limit 1"
    )
    assert renamed["payload"]["superseded"] is None, "undo will retract, not restore"
    before = repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    with _as_runtime(purged) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
        recording = _Recording(connection)
        undo(
            type(identity)(recording, repository.workspace_id),
            event_id=renamed["event_id"],
            actor=actor,
        )
    inserts = [s for s in recording.statements if "into retraction" in str(s)]
    assert inserts == [
        "insert into retraction (workspace_id, assertion_id, retracted_by, reason) "
        "values (%s, %s, %s, %s) returning retraction_id"
    ]
    [row] = purged.rows(
        "select retraction_id, retracted_at, reason from retraction "
        "where reason = 'the rename that made this claim was undone'"
    )
    assert row["retraction_id"].version == 7, "the table's own uuidv7 default"
    assert row["retracted_at"] >= before, "the table's own now() default"
    assert _display_name(named) is None
