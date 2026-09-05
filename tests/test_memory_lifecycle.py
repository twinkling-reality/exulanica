"""One occurrence, one entity and one derived artifact, walked creation to withdrawal.

The readiness audit's exit gate for this goal asks for "a recorded path from creation through
confirmation to withdrawal" for each of the three, and that "a withdrawal marks dependent
artifacts stale through ``dep_index`` rather than regenerating them".

Every piece of that machinery already existed. What did not exist was a test that walked it on
an artifact **the pipeline actually writes**, and the distinction is the whole reason this file
is here. The two existing staleness tests each insert their own row:

    tests/test_identity.py:      dep_index=[f"entity:{julie.entity_id}"]
    tests/test_geometry_delivery.py:  kind='entity_exemplars', dep_index=[f"entity:{...}"]

No shipping producer emits either shape. ``upsert_derived_artifact`` has exactly two production
call sites, both in :mod:`exulanica.ingest.scenes`, and both write ``capture:<uuid>``. So the
invalidation path was demonstrated only against rows a test had planted, which proves the
predicate compiles and nothing about the system.

Here the ``scene_group`` is the one ``run_scene_grouping`` produced, with the ``dep_index``
grouping gave it, and the person is named afterwards. That ordering is the production one and it
is the half that needed proving: the artifact is written at ingest and the person is identified
later, so the dependency has to be recorded on the **link** side. Migration 0030 reads
``dep_index`` in both directions, and only one of them fires here.

**Three ledgers, and they are not merged.** An occurrence's confirmation and an entity's creation
are ``identity_event`` rows; the artifact's confirmation is a ``person_derivative_dependency``
row carrying ``basis = 'confirmed_identity_link'``; the withdrawal is a
``person_withdrawal_receipt`` bound to its tombstone by digest. The record retained for this goal
says so rather than papering over it, because an entity's withdrawal genuinely is not in the
ledger its creation is in.
"""

from __future__ import annotations

import copy
import hashlib
import uuid

import pytest
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.scenes import SCENE_GROUP_KIND, run_scene_grouping
from exulanica.store.local import LocalContentAddressedStore

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, write_photo

#: Two photographs five minutes apart at one position, so grouping produces one scene rather
#: than two. The place label comes from the vision payload and is what makes the group's
#: place_proposal non-empty.
GULLFOSS = (64.3271, -20.1199)


def _payload_with_a_person():
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["objects"] = [
        {
            "label": "person",
            "salience": "primary",
            "confidence": "high",
            "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
        }
    ]
    return payload


class Lifecycle:
    """The corpus, the ids it produced, and the small queries this file asks repeatedly."""

    def __init__(self, repository, store, photo_dir) -> None:
        self.repository = repository
        self.store = store
        self.photo_dir = photo_dir
        self.connection = repository.connection
        self.workspace = repository.workspace_id

    def sql(self, statement: str, *args):
        return self.connection.execute(statement, args).fetchall()

    def artifact(self, derived_id: uuid.UUID):
        rows = self.sql(
            "select kind, dep_index, source_ids, payload, computed_at, stale "
            "from derived_artifact where workspace_id = %s and derived_id = %s",
            self.workspace,
            derived_id,
        )
        assert len(rows) == 1
        return rows[0]

    def event_types(self) -> list[str]:
        return [
            row["type"]
            for row in self.sql(
                "select type from identity_event where workspace_id = %s "
                "order by created_at, event_id",
                self.workspace,
            )
        ]


@pytest.fixture
def lifecycle(tmp_path, photo_dir, repository):
    """Two photographs of one place, ingested, grouped, with a person in the first."""
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(
        repository, store, vision=CountingVisionModel(payload=_payload_with_a_person())
    )
    for name, when in (("a.jpg", "2026:08:27 10:00:00"), ("b.jpg", "2026:08:27 10:05:00")):
        outcome = pipeline.ingest_file(
            write_photo(photo_dir, name, when=when, gps=GULLFOSS)
        )
        assert outcome.error is None, outcome.error
    return Lifecycle(repository, store, photo_dir)


def _scene_group(lifecycle: Lifecycle) -> uuid.UUID:
    """The one scene group grouping wrote, asserted to be the shape production emits."""
    report = run_scene_grouping(lifecycle.repository)
    assert len(report.groups) == 1, "the two photographs should be one scene"
    rows = lifecycle.sql(
        "select derived_id, dep_index from derived_artifact "
        "where workspace_id = %s and kind = %s",
        lifecycle.workspace,
        SCENE_GROUP_KIND,
    )
    assert len(rows) == 1
    dep_index = list(rows[0]["dep_index"])
    assert dep_index and all(entry.startswith("capture:") for entry in dep_index), (
        "the shipping producer writes capture: and nothing else; a test that plants entity: "
        "here would be proving the predicate compiles rather than that the system works"
    )
    return rows[0]["derived_id"]


def _name_the_person(lifecycle: Lifecycle, actor: uuid.UUID):
    occurrence = lifecycle.sql(
        "select occurrence_id, capture_id from occurrence where workspace_id = %s "
        "and class = 'person' order by occurrence_id limit 1",
        lifecycle.workspace,
    )[0]
    named = name_occurrence(
        IdentityRepository(lifecycle.connection, lifecycle.workspace),
        AssertionWriter(lifecycle.connection, lifecycle.workspace),
        occurrence_id=occurrence["occurrence_id"],
        display_name="Julie",
        actor=actor,
    )
    return occurrence, named


# -- creation ---------------------------------------------------------------------------------


def test_ingest_creates_the_occurrence_and_grouping_creates_the_derived_artifact(lifecycle):
    """Stage one for two of the three subjects, and neither is created by a person.

    A detection becomes an occurrence with an evidence span and no name, and a scene group
    becomes a derived artifact recording the captures it was computed from. Neither is a claim
    about anybody, which is why the entity does not exist yet: an entity is the thing a person
    creates by saying who somebody is.
    """
    occurrences = lifecycle.sql(
        "select occurrence_id, primary_span_id from occurrence where workspace_id = %s "
        "and class = 'person'",
        lifecycle.workspace,
    )
    assert len(occurrences) == 2, "one person in each photograph"
    assert all(row["primary_span_id"] is not None for row in occurrences)

    derived_id = _scene_group(lifecycle)
    row = lifecycle.artifact(derived_id)
    assert row["source_ids"], "a derived object must record what it was computed from"
    assert row["stale"] is False

    assert lifecycle.event_types() == [], "nothing has been decided by a person yet"
    assert lifecycle.sql(
        "select entity_id from entity where workspace_id = %s", lifecycle.workspace
    ) == []


# -- confirmation -----------------------------------------------------------------------------


def test_naming_a_person_records_the_entity_the_link_and_the_artifact_it_now_depends_on(
    lifecycle,
):
    """Stage two for all three, in the ordering production actually has.

    The artifact was written at ingest and the person is identified afterwards, so nothing about
    this dependency can be recorded when the artifact is inserted. It is recorded on the link
    side instead: ``record_person_dependencies_for_link`` reads ``dep_index`` for the
    ``capture:`` entries the group already carries, and files one row per dependent target with
    ``basis = 'confirmed_identity_link'``.

    That row is the derived artifact's confirmation step. It is the only one it has: the table
    carries ``stale`` and nothing else, and this is the record of the moment the artifact became
    something a person's withdrawal has to reach.
    """
    derived_id = _scene_group(lifecycle)
    actor = uuid.uuid4()
    occurrence, named = _name_the_person(lifecycle, actor)

    assert lifecycle.event_types() == ["entity_created", "link_confirmed"]
    link = lifecycle.sql(
        "select state, method, decided_by from entity_link where link_id = %s", named.link_id
    )[0]
    assert link["state"] == "confirmed"
    assert link["method"] == "user_confirm"
    assert link["decided_by"] == actor, "a confirmed link names the person who confirmed it"

    dependency = lifecycle.sql(
        "select basis, link_id, occurrence_id, capture_id from person_derivative_dependency "
        "where workspace_id = %s and entity_id = %s and target_kind = 'derived_artifact' "
        "and target_id = %s",
        lifecycle.workspace,
        named.entity_id,
        derived_id,
    )
    assert len(dependency) == 1, (
        "the scene group carries this capture in dep_index, so confirming a person in that "
        "capture must record the artifact as depending on them"
    )
    assert dependency[0]["basis"] == "confirmed_identity_link"
    assert dependency[0]["link_id"] == named.link_id
    assert dependency[0]["occurrence_id"] == occurrence["occurrence_id"]
    assert dependency[0]["capture_id"] == occurrence["capture_id"]


# -- withdrawal -------------------------------------------------------------------------------


def test_withdrawing_the_entity_marks_the_pipeline_written_artifact_stale(lifecycle):
    """Stage three, and the gate sentence: stale through ``dep_index``, not regenerated.

    The four assertions after the tombstone are one claim each and they are not
    interchangeable. ``stale`` is the invalidation. ``computed_at`` and ``payload`` unchanged is
    the "rather than regenerating" half, asserted rather than assumed. The unchanged row count
    is what rules out a replacement row beside the stale one, which would leave the name alive
    inside a fresh artifact and satisfy every other check here.
    """
    derived_id = _scene_group(lifecycle)
    before = lifecycle.artifact(derived_id)
    total_before = lifecycle.sql(
        "select count(*) as n from derived_artifact where workspace_id = %s", lifecycle.workspace
    )[0]["n"]
    actor = uuid.uuid4()
    _occurrence, named = _name_the_person(lifecycle, actor)
    assert lifecycle.artifact(derived_id)["stale"] is False, "naming is not withdrawal"

    tombstone = lifecycle.repository.insert_tombstone(
        scope="entity",
        entity_id=named.entity_id,
        requested_by=actor,
        reason="the person withdrew",
    )

    after = lifecycle.artifact(derived_id)
    assert after["stale"] is True
    assert after["computed_at"] == before["computed_at"], "it was recomputed, not invalidated"
    assert after["payload"] == before["payload"]
    assert (
        lifecycle.sql(
            "select count(*) as n from derived_artifact where workspace_id = %s",
            lifecycle.workspace,
        )[0]["n"]
        == total_before
    ), "a replacement artifact was written beside the stale one"

    entity = lifecycle.sql(
        "select display_name, deleted_at from entity where workspace_id = %s and entity_id = %s",
        lifecycle.workspace,
        named.entity_id,
    )[0]
    assert entity["display_name"] is None
    assert entity["deleted_at"] is not None
    assert (
        lifecycle.sql(
            "select status from assertion where assertion_id = %s", named.assertion_id
        )[0]["status"]
        == "retracted"
    )

    receipt = lifecycle.sql(
        "select record, canonical_bytes, record_digest from person_withdrawal_receipt "
        "where tombstone_id = %s",
        tombstone,
    )
    assert len(receipt) == 1, "a withdrawal that left no receipt is not a recorded withdrawal"
    assert hashlib.sha256(bytes(receipt[0]["canonical_bytes"])).digest() == bytes(
        receipt[0]["record_digest"]
    )
    assert receipt[0]["record"]["entity_id"] == str(named.entity_id)
    assert receipt[0]["record"]["dependency_count"] >= 1


def test_running_the_producer_again_does_not_clear_the_staleness_it_caused(lifecycle):
    """"Invalidated, never silently regenerated" is a property of the writer, not a convention.

    ``derived.upsert`` is ``on conflict (derived_id) do nothing`` and the id is a uuid5 over the
    stage version, the parameter digest and the group key, so a second grouping run over the
    same corpus addresses the same row and declines to touch it. Nothing anywhere sets ``stale``
    back to false. This asserts the consequence, because the day somebody makes that upsert an
    update, a withdrawn person's name comes back inside a regenerated payload and every other
    test in this file still passes.
    """
    derived_id = _scene_group(lifecycle)
    actor = uuid.uuid4()
    _occurrence, named = _name_the_person(lifecycle, actor)
    lifecycle.repository.insert_tombstone(
        scope="entity", entity_id=named.entity_id, requested_by=actor, reason="withdrew"
    )
    stale = lifecycle.artifact(derived_id)
    assert stale["stale"] is True

    run_scene_grouping(lifecycle.repository)

    again = lifecycle.artifact(derived_id)
    assert again["stale"] is True, "a re-run cleared an invalidation it must not be able to clear"
    assert again["computed_at"] == stale["computed_at"]
    assert again["payload"] == stale["payload"]


def test_the_occurrence_leaves_the_read_model_the_withdrawal_reached(lifecycle):
    """The occurrence's own withdrawal, which it has no column of its own for.

    ``occurrence`` has no ``deleted_at`` and ``tombstone_scope`` has no ``occurrence`` member, so
    an occurrence is withdrawn by the withdrawal of the person it was confirmed to be. This
    asserts the consequence a reader sees rather than a state the schema does not carry, and it
    is the honest form of the occurrence's third stage.
    """
    from exulanica.graph import read_snapshot

    _scene_group(lifecycle)
    actor = uuid.uuid4()
    occurrence, named = _name_the_person(lifecycle, actor)

    before = read_snapshot(lifecycle.connection, lifecycle.workspace)
    assert any(row.occurrence_id == occurrence["occurrence_id"] for row in before.occurrences)
    assert any(row.entity_id == named.entity_id for row in before.entities)

    lifecycle.repository.insert_tombstone(
        scope="entity", entity_id=named.entity_id, requested_by=actor, reason="withdrew"
    )

    after = read_snapshot(lifecycle.connection, lifecycle.workspace)
    assert not any(row.occurrence_id == occurrence["occurrence_id"] for row in after.occurrences)
    assert not any(row.entity_id == named.entity_id for row in after.entities)


def test_an_artifact_that_names_no_dependency_is_left_alone_by_the_withdrawal(lifecycle):
    """The control that makes ``dep_index`` load-bearing rather than incidental.

    Everything above would still pass if the cascade staled every artifact in the workspace, and
    a withdrawal that invalidates the whole library is not person-scoped deletion, it is a
    denial of service somebody triggers by exercising a right. So a second artifact is written
    beside the scene group with an empty ``dep_index``, and it must come through untouched.

    ``dep_index`` is read by ``record_person_dependencies_for_link`` when the link is confirmed,
    which is what files the ``person_derivative_dependency`` row the cascade later joins. An
    artifact naming nothing gets no dependency row and therefore no staleness.
    """
    derived_id = _scene_group(lifecycle)
    unrelated = uuid.uuid4()
    lifecycle.connection.execute(
        "insert into derived_artifact (derived_id, workspace_id, kind, depends_on, dep_index, "
        "payload) values (%s, %s, 'atlas_layout', '[]'::jsonb, '{}'::text[], '{}'::jsonb)",
        (unrelated, lifecycle.workspace),
    )
    actor = uuid.uuid4()
    _occurrence, named = _name_the_person(lifecycle, actor)
    lifecycle.repository.insert_tombstone(
        scope="entity", entity_id=named.entity_id, requested_by=actor, reason="withdrew"
    )

    assert lifecycle.artifact(derived_id)["stale"] is True, "the dependent one"
    assert lifecycle.artifact(unrelated)["stale"] is False, (
        "an artifact that named no dependency was invalidated anyway, so the cascade is not "
        "scoped by dep_index and a withdrawal empties the library"
    )
    assert (
        lifecycle.sql(
            "select count(*) as n from person_derivative_dependency where workspace_id = %s "
            "and target_kind = 'derived_artifact' and target_id = %s",
            lifecycle.workspace,
            unrelated,
        )[0]["n"]
        == 0
    )


def test_the_next_ingest_after_a_withdrawal_writes_nothing_live_about_that_person(lifecycle):
    """A withdrawal that only reaches backwards is defeated by the next photograph.

    Everything above is about derivatives that existed when the tombstone landed. This is the
    one that did not, and it is the case the production path actually reaches: one more
    photograph of the same scene changes the group key, so ``run_scene_grouping`` computes a new
    uuid5, the row is an INSERT rather than a conflict, and none of the machinery above applies
    to it.

    Measured before migration 0035 existed: the new scene_group came out with ``stale = false``
    and a ``person_derivative_dependency`` row naming the withdrawn entity with basis
    ``confirmed_identity_link``, because ``entity_link.state`` is still ``confirmed`` after a
    withdrawal and the recorder does not look at ``entity.deleted_at``. A live, unmarked
    derivative naming a withdrawn person's capture, written after they withdrew.

    That is docs/domain-and-evidence-model.md 6.4's failure with the recorded set present and
    correct: the name survives its own deletion because invalidation only ever looked backwards.
    """
    first = _scene_group(lifecycle)
    actor = uuid.uuid4()
    _occurrence, named = _name_the_person(lifecycle, actor)
    lifecycle.repository.insert_tombstone(
        scope="entity", entity_id=named.entity_id, requested_by=actor, reason="withdrew"
    )
    assert lifecycle.artifact(first)["stale"] is True

    store = LocalContentAddressedStore(lifecycle.store.root.parent / "after")
    PhotoIngestPipeline(
        lifecycle.repository, store, vision=CountingVisionModel(payload=_payload_with_a_person())
    ).ingest_file(
        write_photo(
            lifecycle.photo_dir, "c.jpg", when="2026:08:27 10:07:00", gps=GULLFOSS
        )
    )
    run_scene_grouping(lifecycle.repository)

    groups = lifecycle.sql(
        "select derived_id, stale, dep_index from derived_artifact where workspace_id = %s "
        "and kind = %s order by derived_id",
        lifecycle.workspace,
        SCENE_GROUP_KIND,
    )
    assert len(groups) == 2, "the third photograph should have produced a second group"
    live = [row for row in groups if not row["stale"]]
    assert live == [], (
        "a derivative written after the withdrawal names the withdrawn person's capture and is "
        f"live: {[row['derived_id'] for row in live]}"
    )


def test_an_ingest_that_touches_nobody_withdrawn_still_produces_live_artifacts(lifecycle):
    """The control on the one above, and it is the assertion that keeps it from being a hammer.

    Staling every artifact a workspace writes after any withdrawal would pass the previous test
    and would make one person's withdrawal invalidate the whole library. So: a second scene,
    holding a capture the withdrawn person was never confirmed in, comes out live.
    """
    _first = _scene_group(lifecycle)
    actor = uuid.uuid4()
    _occurrence, named = _name_the_person(lifecycle, actor)
    lifecycle.repository.insert_tombstone(
        scope="entity", entity_id=named.entity_id, requested_by=actor, reason="withdrew"
    )

    # Six hours later and somewhere else, with nobody in it, so no occurrence links it to
    # anyone: a different scene by both the time and the distance rule.
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["objects"] = []
    store = LocalContentAddressedStore(lifecycle.store.root.parent / "elsewhere")
    PhotoIngestPipeline(
        lifecycle.repository, store, vision=CountingVisionModel(payload=payload)
    ).ingest_file(
        write_photo(
            lifecycle.photo_dir, "d.jpg", when="2026:08:27 16:00:00", gps=(38.7223, -9.1393)
        )
    )
    run_scene_grouping(lifecycle.repository)

    groups = lifecycle.sql(
        "select derived_id, stale, dep_index from derived_artifact where workspace_id = %s "
        "and kind = %s",
        lifecycle.workspace,
        SCENE_GROUP_KIND,
    )
    assert len(groups) == 2
    live = [row for row in groups if not row["stale"]]
    assert len(live) == 1, "the scene the withdrawn person was never in must survive"
    assert len(live[0]["dep_index"]) == 1, "the new scene holds the one new photograph"
