"""Identity: naming a person, finding them again, and being allowed to change your mind.

This is the recurrence thesis at its smallest honest size. Two photographs, one person, one
account holder who says so. Everything here is rung one, user-asserted identity: nothing
computes an embedding, nothing proposes a match, and nothing needs the open biometric question
answered before it can run.

Four properties are what this file exists to pin, and each of them has a specific failure it
prevents:

*   **A name comes only from the account holder.** Not from a detector, not from a caption, not
    from a direct UPDATE. The last one is the interesting case: it is the route that bypasses
    every line of Python in this repository.
*   **A confirmed link is a human decision.** ``auto_provisional`` may drive layout; only
    ``user_confirm`` may support a claim.
*   **A rejection is durable, evidence-keyed, and revocable.** Keyed by ``occurrence_id`` it
    would evaporate on the next detector run; keyed without the basis it would gag a genuinely
    better proposal forever; deleted rather than revoked it would erase that the user ever said
    no.
*   **Every decision is an event, and the event is enough to undo it.** Not approximately.
"""

from __future__ import annotations

import ast
import copy
import inspect
import pathlib
import re
import uuid
from dataclasses import dataclass

import exulanica.identity
import exulanica.identity.repository
import psycopg
import pytest
from exulanica.db.session import set_workspace
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import (
    AlreadyIdentified,
    IdentityError,
    IdentityRepository,
    NeverSame,
    NotUndoable,
    UnknownSubject,
    basis_digest,
    confirm_link,
    merge_entities,
    name_occurrence,
    reject_link,
    revoke_link,
    split_entity,
    undo,
)
from exulanica.identity.decisions import OCCURRENCE_ENTITY
from exulanica.identity.keys import USER_STATEMENT_BASIS
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, write_photo

#: What the trigger guards raise. `raise exception ... using errcode =
#: 'integrity_constraint_violation'` is SQLSTATE 23000 exactly, and psycopg maps that to this
#: class. Note that CheckViolation (23514) is NOT a subclass of it in psycopg 3, so a CHECK
#: constraint has to be named separately rather than being caught by this.
REFUSED = psycopg.errors.IntegrityConstraintViolation
CHECK_REFUSED = psycopg.errors.CheckViolation

#: A person, located, so ingest produces a person occurrence rather than a bare assertion.
_PERSON_BOX = {"x": 0.55, "y": 0.1, "w": 0.2, "h": 0.6}


def _payload_with_a_located_person() -> dict:
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    person = next(entry for entry in payload["objects"] if entry["label"] == "person")
    person["box"] = dict(_PERSON_BOX)
    return payload


@pytest.fixture
def library(tmp_path, photo_dir, repository):
    """Two photographs, each with one located person, ingested.

    Two captures rather than one, because the whole claim is about recurrence: a person named in
    one photograph and recognised in another. One capture could not distinguish "identity works"
    from "the row is still where I left it".
    """
    store = LocalContentAddressedStore(tmp_path / "blobs")
    vision = CountingVisionModel(payload=_payload_with_a_located_person())
    pipeline = PhotoIngestPipeline(repository, store, vision=vision)
    captures = (("morning.jpg", "2026:08:27 10:00:00"), ("evening.jpg", "2026:08:27 19:30:00"))
    for name, when in captures:
        outcome = pipeline.ingest_file(write_photo(photo_dir, name, when=when))
        assert outcome.error is None, outcome.error

    identity = IdentityRepository(repository.connection, repository.workspace_id)
    assertions = AssertionWriter(repository.connection, repository.workspace_id)
    people = repository.connection.execute(
        "select occurrence_id from occurrence where class = 'person' order by occurrence_id"
    ).fetchall()
    assert len(people) == 2, people
    return Library(
        repository=repository,
        identity=identity,
        assertions=assertions,
        occurrences=[row["occurrence_id"] for row in people],
        actor=uuid.uuid4(),
    )


class Library:
    def __init__(self, *, repository, identity, assertions, occurrences, actor) -> None:
        self.repository = repository
        self.identity = identity
        self.assertions = assertions
        self.occurrences = occurrences
        self.actor = actor

    def name(self, index: int, display_name: str):
        return name_occurrence(
            self.identity,
            self.assertions,
            occurrence_id=self.occurrences[index],
            display_name=display_name,
            actor=self.actor,
        )

    def identity_key(self, index: int) -> bytes:
        occurrence = self.identity.occurrences.by_id(self.occurrences[index])
        assert occurrence is not None
        return occurrence.identity_key


# -- the thesis --------------------------------------------------------------------------


def test_a_person_named_once_is_confirmable_in_a_second_capture(library):
    """The whole recurrence claim, in the version that needs no biometrics.

    Named in one photograph, confirmed in another, and the link is queryable in both
    directions: which occurrences are this person, and which person is this occurrence.
    """
    named = library.name(0, "Julie")
    entity = library.identity.entities.by_id(named.entity_id)
    assert entity is not None
    assert entity.display_name == "Julie"
    assert entity.entity_class == "person"

    confirm_link(
        library.identity,
        occurrence_id=library.occurrences[1],
        entity_id=named.entity_id,
        actor=library.actor,
    )

    occurrences = library.identity.occurrences.of_entity(named.entity_id)
    assert {o.occurrence_id for o in occurrences} == set(library.occurrences)
    # Two captures, not one photograph counted twice. That is the claim.
    assert len({o.capture_id for o in occurrences}) == 2

    for occurrence_id in library.occurrences:
        link = library.identity.links.for_occurrence(occurrence_id)
        assert link is not None
        assert link.entity_id == named.entity_id
        assert link.state == "confirmed"
        assert link.method == "user_confirm"
        assert link.decided_by == library.actor


def test_the_name_is_a_cache_of_an_assertion_the_user_made(library):
    """Not a column somebody set. The assertion is the claim; the column repeats it."""
    named = library.name(0, "Julie")
    row = library.repository.connection.execute(
        "select a.kind, a.object_value, a.stated_by_user, a.produced_by_run, "
        "a.support_span_ids, p.key, p.writes_a_name from assertion a "
        "join predicate p on p.predicate_id = a.predicate_id "
        "where a.assertion_id = %s",
        (named.assertion_id,),
    ).fetchone()
    assert row["kind"] == "user"
    assert row["key"] == "name_is"
    assert row["writes_a_name"] is True
    assert row["object_value"] == "Julie"
    assert row["stated_by_user"] == library.actor
    # A claim the user made was not produced by a pipeline run. Migration 0002 refuses the row
    # outright if it were, which is what closed the laundering route.
    assert row["produced_by_run"] is None
    # It cites the photograph the user was looking at.
    occurrence = library.identity.occurrences.by_id(library.occurrences[0])
    assert list(row["support_span_ids"]) == [occurrence.primary_span_id]


def test_retracting_the_statement_takes_the_name_off_the_entity(library):
    """A name that outlives the statement supporting it is the failure to prevent.

    The user says "actually that is not Julie" and the label has to stop appearing. Enforced by
    trigger rather than by a cleanup pass, so there is no window in which the two disagree.
    """
    named = library.name(0, "Julie")
    assert library.identity.entities.by_id(named.entity_id).display_name == "Julie"

    library.assertions.retract(
        named.assertion_id, retracted_by=library.actor, reason="wrong person"
    )
    assert library.identity.entities.by_id(named.entity_id).display_name is None

    retraction = library.repository.connection.execute(
        "select status from assertion where assertion_id = %s", (named.assertion_id,)
    ).fetchone()
    assert retraction["status"] == "retracted", "the claim is withdrawn, not erased"


# -- invariant 4, on the route that bypasses this package entirely -----------------------


@pytest.mark.parametrize("kind", ["inference", "capture", "external"])
def test_no_model_can_name_an_entity_by_any_route(library, kind):
    """Three ways in, all refused, none of them going through Python.

    The first two are the vocabulary guard: name_is allows only 'user'. The third is the one
    that motivated migration 0002, because it needs no assertion at all: a direct UPDATE of
    entity.display_name was ACCEPTED by the committed schema with nothing supporting it.
    """
    named = library.name(0, "Julie")
    connection = library.repository.connection
    other = library.identity.entities.create(entity_class="person")

    with pytest.raises(REFUSED, match="name_is"), connection.transaction():
        connection.execute(
            "insert into assertion (workspace_id, kind, predicate_id, subject_ref, "
            "object_value, support_span_ids, produced_by_run, external_source, emit_key) "
            "select %s, %s, predicate_id, jsonb_build_object('type','entity','id',%s::text), "
            "to_jsonb('Aunt Marjorie'::text), array[]::uuid[], null, "
            "case when %s = 'external' then '{}'::jsonb else null end, %s "
            "from predicate where key = 'name_is'",
            (library.repository.workspace_id, kind, str(other), kind, f"attack:{kind}"),
        )

    with pytest.raises(REFUSED, match="no active user assertion says so"), connection.transaction():
        connection.execute(
            "update entity set display_name = 'Aunt Marjorie' where entity_id = %s", (other,)
        )

    with pytest.raises(REFUSED, match="no active user assertion says so"), connection.transaction():
        connection.execute(
            "insert into entity (workspace_id, class, display_name) values (%s, 'person', %s)",
            (library.repository.workspace_id, "Aunt Marjorie"),
        )

    # The one that is allowed still is, so the guard is not simply refusing everything.
    assert library.identity.entities.by_id(named.entity_id).display_name == "Julie"


def test_a_link_cannot_be_confirmed_without_a_human(library):
    """`confirmed_needs_a_human`: model confidence is never user confirmation."""
    named = library.name(0, "Julie")
    connection = library.repository.connection
    for method, decided_by in (("embedding_knn", uuid.uuid4()), ("user_confirm", None)):
        refusal = pytest.raises(CHECK_REFUSED, match="confirmed_needs_a_human")
        with refusal, connection.transaction():
            connection.execute(
                "insert into entity_link (workspace_id, occurrence_id, entity_id, state, "
                "method, basis_digest, decided_by) values (%s, %s, %s, 'confirmed', %s, %s, %s)",
                (
                    library.repository.workspace_id,
                    library.occurrences[1],
                    named.entity_id,
                    method,
                    USER_STATEMENT_BASIS,
                    decided_by,
                ),
            )


def test_one_occurrence_cannot_be_two_people(library):
    """Two answers to a question that has one."""
    first = library.name(0, "Julie")
    other = library.name(1, "Leo")
    with pytest.raises(AlreadyIdentified, match="already confirmed"):
        confirm_link(
            library.identity,
            occurrence_id=library.occurrences[0],
            entity_id=other.entity_id,
            actor=library.actor,
        )
    still = library.identity.links.for_occurrence(library.occurrences[0])
    assert still.entity_id == first.entity_id


# -- rejection memory --------------------------------------------------------------------


def test_a_rejection_is_durable_and_keyed_by_evidence_not_by_the_row(library):
    """The defect this design exists to avoid, reproduced as the scenario that would trigger it.

    A detector re-run mints a new ``occurrence_id`` for the same person in the same photograph.
    Keyed by that id, every rejection evaporates and the user re-answers the same question
    forever. Keyed by ``identity_key``, which is a function of the evidence address, the second
    row is recognised as the same thing.
    """
    named = library.name(0, "Julie")
    reject_link(
        library.identity,
        occurrence_id=library.occurrences[1],
        entity_id=named.entity_id,
        actor=library.actor,
    )
    key = library.identity_key(1)
    assert library.identity.rejections.is_rejected(
        scope=OCCURRENCE_ENTITY,
        key_a=key,
        key_b=named.entity_id.bytes,
        basis_digest=USER_STATEMENT_BASIS,
    )

    # A second detector version over the same photograph: a new row, the same evidence.
    original = library.identity.occurrences.by_id(library.occurrences[1])
    reborn = library.repository.insert_occurrence(
        capture_id=original.capture_id,
        occurrence_class="person",
        primary_span_id=original.primary_span_id,
        span_ids=list(original.span_ids),
        presence=[(0, 1)],
        produced_by_run=library.repository.connection.execute(
            "select run_id from pipeline_run limit 1"
        ).fetchone()["run_id"],
        detector_version="vision:99",
        identity_key=original.identity_key,
        emit_key="rerun:person:0",
    )
    assert reborn is not None and reborn != library.occurrences[1]
    assert library.identity.rejections.is_rejected(
        scope=OCCURRENCE_ENTITY,
        key_a=library.identity.occurrences.by_id(reborn).identity_key,
        key_b=named.entity_id.bytes,
        basis_digest=USER_STATEMENT_BASIS,
    ), "a re-detected occurrence must inherit the answer the user already gave"


def test_a_rejection_does_not_gag_a_proposal_built_from_different_signals(library):
    """The opposite failure, and it is just as bad.

    "Not on this evidence" is what a rejection means. A system that later has genuinely
    different signals is entitled to ask again; one that could never ask again would be unable
    to improve.
    """
    named = library.name(0, "Julie")
    reject_link(
        library.identity,
        occurrence_id=library.occurrences[1],
        entity_id=named.entity_id,
        actor=library.actor,
    )
    richer = basis_digest(["co_presence", "place"], {"scene_grouping": "2"})
    assert richer != USER_STATEMENT_BASIS
    assert not library.identity.rejections.is_rejected(
        scope=OCCURRENCE_ENTITY,
        key_a=library.identity_key(1),
        key_b=named.entity_id.bytes,
        basis_digest=richer,
    )


def test_confirming_after_a_rejection_overrules_it(library):
    """The user changing their mind is not a re-proposal, and memory must not argue back."""
    named = library.name(0, "Julie")
    reject_link(
        library.identity,
        occurrence_id=library.occurrences[1],
        entity_id=named.entity_id,
        actor=library.actor,
    )
    confirm_link(
        library.identity,
        occurrence_id=library.occurrences[1],
        entity_id=named.entity_id,
        actor=library.actor,
    )
    assert not library.identity.rejections.is_rejected(
        scope=OCCURRENCE_ENTITY,
        key_a=library.identity_key(1),
        key_b=named.entity_id.bytes,
        basis_digest=USER_STATEMENT_BASIS,
    )
    assert library.identity.links.for_occurrence(library.occurrences[1]).state == "confirmed"


def test_a_rejection_is_revoked_and_never_deleted(library):
    """A deleted rejection leaves no evidence that the user ever said no."""
    named = library.name(0, "Julie")
    reject_link(
        library.identity,
        occurrence_id=library.occurrences[1],
        entity_id=named.entity_id,
        actor=library.actor,
    )
    library.identity.rejections.revoke(
        scope=OCCURRENCE_ENTITY,
        key_a=library.identity_key(1),
        key_b=named.entity_id.bytes,
        basis_digest=USER_STATEMENT_BASIS,
    )
    row = library.repository.connection.execute(
        "select rejected_at, revoked_at from identity_rejection"
    ).fetchone()
    assert row is not None, "the row is still there"
    assert row["revoked_at"] is not None


# -- merge, split, undo ------------------------------------------------------------------


def test_merging_two_records_of_one_person_keeps_every_link_resolving(library):
    """A merge is an alias redirect, so nothing that was written before it has to be rewritten."""
    julie = library.name(0, "Julie")
    duplicate = library.name(1, "Julie (again)")

    merge_entities(
        library.identity,
        sources=[duplicate.entity_id],
        target=julie.entity_id,
        actor=library.actor,
    )
    assert library.identity.entities.resolve(duplicate.entity_id) == julie.entity_id
    # The link still names the entity it was written against, and still resolves.
    link = library.identity.links.for_occurrence(library.occurrences[1])
    assert link.entity_id == duplicate.entity_id
    assert library.identity.entities.resolve(link.entity_id) == julie.entity_id


def test_a_split_refuses_a_later_merge_of_the_two_it_separated(library):
    """`never_same` is the user's decision written down, so a merge cannot quietly reverse it."""
    julie = library.name(0, "Julie")
    confirm_link(
        library.identity,
        occurrence_id=library.occurrences[1],
        entity_id=julie.entity_id,
        actor=library.actor,
    )
    split_entity(
        library.identity,
        entity_id=julie.entity_id,
        occurrence_ids=[library.occurrences[1]],
        actor=library.actor,
    )
    moved = library.identity.links.for_occurrence(library.occurrences[1])
    assert moved.entity_id != julie.entity_id
    # The new entity is unnamed: the user said "not that person", not "this is somebody named X".
    assert library.identity.entities.by_id(moved.entity_id).display_name is None

    with pytest.raises(NeverSame, match="split apart"):
        merge_entities(
            library.identity,
            sources=[moved.entity_id],
            target=julie.entity_id,
            actor=library.actor,
        )


def test_a_split_that_moves_everything_is_refused_as_a_rename(library):
    julie = library.name(0, "Julie")
    with pytest.raises(Exception, match="rename, not a split"):
        split_entity(
            library.identity,
            entity_id=julie.entity_id,
            occurrence_ids=[library.occurrences[0]],
            actor=library.actor,
        )


@pytest.mark.parametrize("decision", ["confirm", "reject", "revoke", "merge", "split"])
def test_every_recorded_decision_can_be_undone_exactly(library, decision):
    """Undo reads the event payload rather than guessing, so it restores what was there."""
    julie = library.name(0, "Julie")
    second = library.occurrences[1]

    if decision == "confirm":
        confirm_link(
            library.identity, occurrence_id=second, entity_id=julie.entity_id, actor=library.actor
        )
        event = _latest(library, "link_confirmed")
        undo(library.identity, event_id=event, actor=library.actor)
        assert library.identity.links.for_occurrence(second) is None
    elif decision == "reject":
        reject_link(
            library.identity, occurrence_id=second, entity_id=julie.entity_id, actor=library.actor
        )
        event = _latest(library, "link_rejected")
        undo(library.identity, event_id=event, actor=library.actor)
        assert not library.identity.rejections.is_rejected(
            scope=OCCURRENCE_ENTITY,
            key_a=library.identity_key(1),
            key_b=julie.entity_id.bytes,
            basis_digest=USER_STATEMENT_BASIS,
        )
    elif decision == "revoke":
        confirm_link(
            library.identity, occurrence_id=second, entity_id=julie.entity_id, actor=library.actor
        )
        revoke_link(library.identity, occurrence_id=second, actor=library.actor)
        assert library.identity.links.for_occurrence(second) is None
        undo(library.identity, event_id=_latest(library, "link_revoked"), actor=library.actor)
        restored = library.identity.links.for_occurrence(second)
        assert restored is not None and restored.entity_id == julie.entity_id
    elif decision == "merge":
        other = library.name(1, "Leo")
        merge_entities(
            library.identity,
            sources=[other.entity_id],
            target=julie.entity_id,
            actor=library.actor,
        )
        undo(library.identity, event_id=_latest(library, "entities_merged"), actor=library.actor)
        assert library.identity.entities.resolve(other.entity_id) == other.entity_id
    else:
        confirm_link(
            library.identity, occurrence_id=second, entity_id=julie.entity_id, actor=library.actor
        )
        split_entity(
            library.identity,
            entity_id=julie.entity_id,
            occurrence_ids=[second],
            actor=library.actor,
        )
        moved = library.identity.links.for_occurrence(second).entity_id
        undo(library.identity, event_id=_latest(library, "entity_split"), actor=library.actor)
        assert library.identity.links.for_occurrence(second).entity_id == julie.entity_id
        assert not library.identity.never_same.holds(julie.entity_id, moved)


def test_an_event_cannot_be_undone_twice_and_an_undo_cannot_be_undone(library):
    """Both would look like an undo and be something else."""
    julie = library.name(0, "Julie")
    confirm_link(
        library.identity,
        occurrence_id=library.occurrences[1],
        entity_id=julie.entity_id,
        actor=library.actor,
    )
    confirmed = _latest(library, "link_confirmed")
    undo(library.identity, event_id=confirmed, actor=library.actor)

    with pytest.raises(NotUndoable, match="already been undone"):
        undo(library.identity, event_id=confirmed, actor=library.actor)
    with pytest.raises(NotUndoable, match="redo"):
        undo(library.identity, event_id=_latest(library, "event_undone"), actor=library.actor)


def test_creating_a_person_is_refused_by_undo_rather_than_half_done(library):
    """Undoing the creation of a person is a deletion, and deletion cascades and tombstones."""
    library.name(0, "Julie")
    with pytest.raises(NotUndoable, match="deletion"):
        undo(library.identity, event_id=_latest(library, "entity_created"), actor=library.actor)


# -- recomputation -----------------------------------------------------------------------


def test_a_decision_marks_everything_that_depended_on_it_stale(library):
    """Otherwise a generated caption naming somebody survives that person being merged away."""
    julie = library.name(0, "Julie")
    derived_id = uuid.uuid4()
    assert library.repository.upsert_derived_artifact(
        derived_id=derived_id,
        kind="episode_summary",
        depends_on=[{"kind": "entity", "id": str(julie.entity_id)}],
        dep_index=[f"entity:{julie.entity_id}"],
        source_ids=[],
        payload={"title": "A day with Julie"},
    )
    assert not _is_stale(library, derived_id)

    confirm_link(
        library.identity,
        occurrence_id=library.occurrences[1],
        entity_id=julie.entity_id,
        actor=library.actor,
    )
    assert _is_stale(library, derived_id)


def test_a_decision_about_someone_else_leaves_unrelated_artifacts_alone(library):
    """A stale flag on everything is the same as a stale flag on nothing."""
    julie = library.name(0, "Julie")
    leo = library.name(1, "Leo")
    derived_id = uuid.uuid4()
    library.repository.upsert_derived_artifact(
        derived_id=derived_id,
        kind="episode_summary",
        depends_on=[{"kind": "entity", "id": str(leo.entity_id)}],
        dep_index=[f"entity:{leo.entity_id}"],
        source_ids=[],
        payload={"title": "A day with Leo"},
    )
    revoke_link(library.identity, occurrence_id=library.occurrences[0], actor=library.actor)
    assert not _is_stale(library, derived_id)
    assert julie.entity_id != leo.entity_id


# -- workspace scoping -------------------------------------------------------------------


def test_another_workspace_is_indistinguishable_from_nothing(library):
    """Not a different error, the same one. Otherwise the surface is an existence oracle."""
    with pytest.raises(UnknownSubject):
        confirm_link(
            library.identity,
            occurrence_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
            actor=library.actor,
        )


def _latest(library, event_type: str) -> uuid.UUID:
    row = library.repository.connection.execute(
        "select event_id from identity_event where type = %s "
        "order by created_at desc, event_id desc limit 1",
        (event_type,),
    ).fetchone()
    assert row is not None, f"no {event_type} event was recorded"
    return row["event_id"]


def _is_stale(library, derived_id: uuid.UUID) -> bool:
    row = library.repository.connection.execute(
        "select stale from derived_artifact where derived_id = %s", (derived_id,)
    ).fetchone()
    assert row is not None
    return row["stale"]


def test_merging_a_named_record_into_an_unnamed_one_is_refused(library):
    """The surviving record keeps its name, so the merge has to go the other way round.

    Refused at the API as well as in the client draft, and the duplication is deliberate: the
    client refusal does not cover a caller that never went through ``draftMerge``. A merge that
    went the wrong way is undoable only if somebody notices, and nothing about an entity that
    quietly lost its name is loud.
    """
    julie = library.name(0, "Julie")
    unnamed = library.identity.entities.create(entity_class="person")

    with pytest.raises(IdentityError, match="the other way round"):
        merge_entities(
            library.identity,
            sources=[julie.entity_id],
            target=unnamed,
            actor=library.actor,
        )

    # The other direction is permitted, because the survivor keeps a name somebody chose.
    merge_entities(
        library.identity,
        sources=[unnamed],
        target=julie.entity_id,
        actor=library.actor,
    )
    assert library.identity.entities.resolve(unnamed) == julie.entity_id

# -- every query names its workspace ------------------------------------------------------
#
# This section exists because of what the identity repository was split into. Nine modules now
# hold the SQL that one class used to, and the thing a move like that loses silently is a
# `where workspace_id = %s` on the way past.
#
# It is checked HERE, as the database owner, rather than in `test_row_level_security.py`. The
# owner is a superuser and PostgreSQL says plainly that "superusers and roles with the BYPASSRLS
# attribute always bypass the row security system", so on this connection the predicate inside
# each statement is the ONLY thing scoping the read, and dropping one leaks. On a non-superuser
# connection the same drop is unobservable by construction: `ws_isolation` already filters to
# `current_workspace()`, so the query returns the same rows either way. The two facts need two
# different roles, and the other one is in `test_row_level_security.py`.


@dataclass(frozen=True, slots=True)
class Neighbour:
    """Somebody else's workspace, with a row in every identity table."""

    repository: IdentityRepository
    entity_id: uuid.UUID
    merged_id: uuid.UUID
    sibling_id: uuid.UUID
    occurrence_id: uuid.UUID
    spare_occurrence_id: uuid.UUID
    identity_key: bytes
    link_id: uuid.UUID
    event_id: uuid.UUID
    undone_id: uuid.UUID
    rejection_id: uuid.UUID
    derived_id: uuid.UUID


@pytest.fixture
def neighbour(library):
    """A second workspace on the same connection, seeded through the same code the library used.

    The seed ends by reading every row back from the workspace that owns it. Without that half,
    a seed that quietly wrote nothing would make every assertion in the two tests below pass
    for the wrong reason.
    """
    connection = library.repository.connection
    workspace = uuid.uuid4()
    theirs = IdentityRepository(connection, workspace)
    assertions = AssertionWriter(connection, workspace)
    actor = uuid.uuid4()

    digest = bytes([9]) * 32
    connection.execute(
        "insert into blob (blob_sha256, byte_size, media_type) "
        "values (%s, 3, 'image/jpeg') on conflict (blob_sha256) do nothing",
        (digest,),
    )
    capture_id = connection.execute(
        "insert into capture (workspace_id, blob_sha256) values (%s, %s) returning capture_id",
        (workspace, digest),
    ).fetchone()["capture_id"]
    run_id = connection.execute(
        "insert into pipeline_run (workspace_id, trigger) values (%s, 'manual') returning run_id",
        (workspace,),
    ).fetchone()["run_id"]

    occurrence_ids = []
    for index in range(2):
        span_id = connection.execute(
            "insert into evidence_span (workspace_id, blob_sha256, track_key, t_start_ns, "
            "t_end_ns, modality, span_digest) values (%s, %s, 'img', %s, %s, 'still_image', %s) "
            "returning span_id",
            (workspace, digest, index, index + 1, bytes([index]) * 32),
        ).fetchone()["span_id"]
        occurrence_ids.append(
            connection.execute(
                "insert into occurrence (workspace_id, capture_id, class, primary_span_id, "
                "span_ids, presence, produced_by_run, detector_version, identity_key, emit_key) "
                "values (%s, %s, 'person', %s, array[%s]::uuid[], '{[0,1)}'::int8multirange, "
                "%s, 'v1', %s, %s) returning occurrence_id",
                (
                    workspace,
                    capture_id,
                    span_id,
                    span_id,
                    run_id,
                    bytes([index + 40]) * 32,
                    f"neighbour:occurrence:{index}",
                ),
            ).fetchone()["occurrence_id"]
        )

    named = name_occurrence(
        theirs,
        assertions,
        occurrence_id=occurrence_ids[0],
        display_name="Somebody Else",
        actor=actor,
    )
    merged_id = theirs.entities.create(entity_class="person")
    theirs.entities.set_merged_into(merged_id, named.entity_id)
    sibling_id = theirs.entities.create(entity_class="person")
    theirs.never_same.record(named.entity_id, sibling_id)

    occurrence = theirs.occurrences.by_id(occurrence_ids[0])
    rejection_id = theirs.rejections.record(
        scope=OCCURRENCE_ENTITY,
        key_a=occurrence.identity_key,
        key_b=named.entity_id.bytes,
        basis_digest=USER_STATEMENT_BASIS,
        rejected_by=actor,
        basis_modalities=["context_place"],
    )
    assert theirs.proposals.record(
        occurrence_id=occurrence_ids[1],
        entity_id=named.entity_id,
        score=0.9,
        rank=1,
        basis_digest=USER_STATEMENT_BASIS,
        basis={"modalities": ["context_place"]},
        outcome="surfaced",
        produced_by_run=run_id,
        emit_key="neighbour:proposal:0",
    ) is not None
    undone_id = theirs.events.record(
        "event_undone",
        actor=actor,
        payload={"undid": str(named.event_ids[-1]), "type": "link_confirmed"},
        undoes=named.event_ids[-1],
    )
    derived_id = uuid.uuid4()
    connection.execute(
        "insert into derived_artifact (derived_id, workspace_id, kind, depends_on, dep_index, "
        "source_ids, payload, stale) values (%s, %s, 'episode_summary', '[]'::jsonb, "
        "%s::text[], '{}'::uuid[], '{}'::jsonb, false)",
        (derived_id, workspace, [f"entity:{named.entity_id}"]),
    )

    assert theirs.occurrences.by_id(occurrence_ids[0]) is not None
    assert len(theirs.occurrences.of_entity(named.entity_id)) == 1
    assert theirs.entities.by_id(named.entity_id).display_name == "Somebody Else"
    assert theirs.entities.resolve(merged_id) == named.entity_id
    assert theirs.links.for_occurrence(occurrence_ids[0]) is not None
    assert len(theirs.links.of_entity(named.entity_id)) == 1
    assert theirs.rejections.covering(
        scope=OCCURRENCE_ENTITY,
        key_a=occurrence.identity_key,
        key_b=named.entity_id.bytes,
        modalities=["context_place"],
    ) == (True, None)
    assert theirs.rejections.is_rejected(
        scope=OCCURRENCE_ENTITY,
        key_a=occurrence.identity_key,
        key_b=named.entity_id.bytes,
        basis_digest=USER_STATEMENT_BASIS,
    )
    assert theirs.never_same.holds(named.entity_id, sibling_id)
    assert (
        theirs.proposals.pending(occurrence_id=occurrence_ids[1], entity_id=named.entity_id)
        is not None
    )
    assert theirs.events.by_id(named.event_ids[-1]) is not None
    assert theirs.events.undo_of(named.event_ids[-1]) == undone_id
    assert named.event_ids[-1] in {row["event_id"] for row in theirs.events.recent(limit=200)}

    # Back to the workspace the library fixture left the session on, so the tests below run
    # scoped exactly as a request would be.
    set_workspace(connection, library.repository.workspace_id)
    return Neighbour(
        repository=theirs,
        entity_id=named.entity_id,
        merged_id=merged_id,
        sibling_id=sibling_id,
        occurrence_id=occurrence_ids[0],
        spare_occurrence_id=occurrence_ids[1],
        identity_key=occurrence.identity_key,
        link_id=named.link_id,
        event_id=named.event_ids[-1],
        undone_id=undone_id,
        rejection_id=rejection_id,
        derived_id=derived_id,
    )


def test_no_identity_read_crosses_a_workspace_boundary(library, neighbour):
    """Thirteen reads over six tables and one view, none of which may see the workspace next door.

    Drop the ``and workspace_id = %s`` from any one of the moved SELECTs and the matching line
    here fails, because this connection belongs to the owner and row-level security is filtering
    nothing for it.
    """
    mine = library.identity

    assert mine.occurrences.by_id(neighbour.occurrence_id) is None
    assert mine.occurrences.of_entity(neighbour.entity_id) == []
    assert mine.entities.by_id(neighbour.entity_id) is None
    # Not the merge target. An unreadable row has no `merged_into` to follow, so the walk stops
    # where it started rather than redirecting into somebody else's workspace.
    assert mine.entities.resolve(neighbour.merged_id) == neighbour.merged_id
    assert mine.links.for_occurrence(neighbour.occurrence_id) is None
    assert mine.links.of_entity(neighbour.entity_id) == []
    assert mine.rejections.covering(
        scope=OCCURRENCE_ENTITY,
        key_a=neighbour.identity_key,
        key_b=neighbour.entity_id.bytes,
        modalities=["context_place"],
    ) == (False, None)
    assert not mine.rejections.is_rejected(
        scope=OCCURRENCE_ENTITY,
        key_a=neighbour.identity_key,
        key_b=neighbour.entity_id.bytes,
        basis_digest=USER_STATEMENT_BASIS,
    )
    assert not mine.never_same.holds(neighbour.entity_id, neighbour.sibling_id)
    assert (
        mine.proposals.pending(
            occurrence_id=neighbour.spare_occurrence_id, entity_id=neighbour.entity_id
        )
        is None
    )
    assert mine.events.by_id(neighbour.event_id) is None
    assert mine.events.undo_of(neighbour.event_id) is None
    assert neighbour.event_id not in {row["event_id"] for row in mine.events.recent(limit=200)}


def test_no_identity_write_crosses_a_workspace_boundary(library, neighbour):
    """The eight UPDATE and DELETE predicates, which fail more quietly than the reads do.

    A read that leaks is at least visible to whoever reads it. An UPDATE that lost its workspace
    predicate rewrites another account's decisions and returns a row count nobody looks at, which
    is why the second half repeats every call from the side that owns the rows: each zero above
    has to mean "no rows of mine to change" rather than "nothing to change anywhere".
    """
    mine = library.identity
    theirs = neighbour.repository

    assert mine.recomputation.mark_stale(entity=neighbour.entity_id) == 0
    assert (
        mine.rejections.revoke(
            scope=OCCURRENCE_ENTITY,
            key_a=neighbour.identity_key,
            key_b=neighbour.entity_id.bytes,
            basis_digest=USER_STATEMENT_BASIS,
        )
        == 0
    )
    assert (
        mine.rejections.revoke_all(
            scope=OCCURRENCE_ENTITY,
            key_a=neighbour.identity_key,
            key_b=neighbour.entity_id.bytes,
        )
        == []
    )
    assert mine.rejections.revive([neighbour.rejection_id]) == 0
    assert mine.never_same.forget(neighbour.entity_id, neighbour.sibling_id) == 0
    mine.links.set_state(neighbour.link_id, "revoked")
    mine.entities.set_name_cache(neighbour.entity_id, None)
    mine.entities.set_merged_into(neighbour.merged_id, None)

    assert theirs.links.for_occurrence(neighbour.occurrence_id).state == "confirmed"
    assert theirs.entities.by_id(neighbour.entity_id).display_name == "Somebody Else"
    assert theirs.entities.resolve(neighbour.merged_id) == neighbour.entity_id

    assert theirs.recomputation.mark_stale(entity=neighbour.entity_id) == 1
    assert theirs.rejections.revoke_all(
        scope=OCCURRENCE_ENTITY,
        key_a=neighbour.identity_key,
        key_b=neighbour.entity_id.bytes,
    ) == [neighbour.rejection_id]
    assert theirs.rejections.revive([neighbour.rejection_id]) == 1
    assert theirs.never_same.forget(neighbour.entity_id, neighbour.sibling_id) == 1


def test_the_facade_holds_no_sql():
    """The repository is a workspace, a connection, a transaction and eight names.

    Scanned over the class's CODE, with docstrings removed first and comments dropped by the
    round trip through the syntax tree. A plain scan of ``inspect.getsource`` matches prose
    instead: this class used to carry a docstring saying a revocation is "never a delete", and
    that sentence alone would have turned the check red with no query anywhere near it.
    """
    tree = ast.parse(inspect.getsource(IdentityRepository))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef):
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            node.body = node.body[1:] or [ast.Pass()]
    code = ast.unparse(ast.fix_missing_locations(tree)).lower()

    for statement in ("select", "insert", "update", "delete"):
        assert statement not in code, f"the facade carries SQL again: {statement}"
    # The stripping is what makes the four above mean anything, so it is checked rather than
    # assumed: one phrase that is only in the class docstring, one name that is only in the code.
    assert "vocabularies over the identity tables" not in code
    assert "recomputation" in code


def test_the_package_docstring_accounts_for_every_module_in_the_package():
    """The three-way split at the top of ``exulanica.identity`` is a partition, not a gesture.

    A docstring that says six modules carry the argument, eight are the tables and five are the
    producer is a claim about all nineteen files, and the arithmetic is the point of writing it
    that way. The eight are named one rung down, in ``repository.py``'s index, so the two
    docstrings are read together. Add a module and name it in neither and this goes red, which
    is what stops a count nobody can reproduce from the code turning into decoration.
    """
    package = pathlib.Path(exulanica.identity.__file__).parent
    on_disk = {path.stem for path in package.glob("*.py")} - {"__init__"}
    prose = f"{exulanica.identity.__doc__}\n{exulanica.identity.repository.__doc__}"
    named = set(re.findall(r"exulanica\.identity\.(\w+)", prose))

    assert on_disk - named == set(), "modules that neither docstring accounts for"
    assert named - on_disk == set(), "a docstring naming a module that is gone"
    assert len(on_disk) == 19
    assert "Nineteen modules in three groups" in exulanica.identity.__doc__
