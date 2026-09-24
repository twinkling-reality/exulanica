"""A place's saved name reaches a model only while its account holder allows it, place by place.

The account holder's rules: a person's name never goes to a hosted model, with or without a right,
and a confirmed place's name goes only where they allowed it, asked for each place. Migration 0097
keeps each allow and each withdrawal as an appended, chained decision, and
:func:`released_place_names` is the resolver that answers, at the moment a name would be sent,
which places' names may go to one hand-over.

These tests name a real person and a real place through the product's own naming path and hold
the right to its terms against PostgreSQL through the real migrations. Every refusal is paired with
its positive control: the same place, with the right intact, released to the same hand-over, so an
empty answer means the rule and not a broken fixture.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.canonical import canonical_json, sha256_digest
from exulanica.consent import place_name_rights as rights
from exulanica.consent.place_name_rights import (
    PlaceNameRightRefused,
    UnknownPlace,
    grant_place_name,
    name_digest,
    place_name_released,
    read_place_name_rights,
    released_place_names,
    withdraw_place_name,
)
from exulanica.consent.place_names import (
    DECISION_PROFILE,
    load_place_name_uses,
    parse_place_name_uses,
)
from exulanica.db.roles import provision_runtime_role
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import (
    IdentityRepository,
    merge_entities,
    name_occurrence,
    rename_entity,
    undo,
)
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.models.handoff import ModelHandoff, ModelIdentity
from exulanica.models.manifest import Role, load_manifest
from exulanica.store.local import LocalContentAddressedStore
from psycopg.types.json import Jsonb

from conftest import (
    DEFAULT_PAYLOAD,
    CountingVisionModel,
    ingest_observed,
    scratch_role_database,
    write_photo,
)

PERSON = "Maria Estrada"
PLACE = "Lantern House"
MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "exulanica/migrations/0097_a_place_name_reaches_a_model_only_under_its_own_right.sql"
)

USES = load_place_name_uses()
MANIFEST = load_manifest()
#: Every offered role's whole chain at its destination, as the product would hand it over.
HANDOFFS = {use.role.value: USES.handoff(use, MANIFEST) for use in USES.uses}
SEARCH = HANDOFFS["embedding"]
#: An offered role with a fallback: how a two-model chain is held to the rule, which is the same
#: for every role.
PLANNER = HANDOFFS["structured_extraction"]
#: Another offered role, never granted in the test that grants the embedding use.
COMPOSER = HANDOFFS["reasoning_cheap"]


@pytest.fixture
def named(tmp_path, photo_dir, repository):
    """One photograph of a person and a place, both named by the same account holder."""
    store = LocalContentAddressedStore(tmp_path / "blobs")
    payload = json.loads(json.dumps(DEFAULT_PAYLOAD))
    payload["objects"] = [
        {
            "label": "person",
            "salience": "primary",
            "confidence": "high",
            "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
        }
    ]
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel(payload=payload))
    outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, "house.jpg"))
    assert outcome.error is None, outcome.error

    identity = IdentityRepository(repository.connection, repository.workspace_id)
    assertions = AssertionWriter(repository.connection, repository.workspace_id)
    actor = uuid.uuid4()
    entities = {}
    for occurrence_class, name in (("person", PERSON), ("place", PLACE)):
        occurrence = repository.connection.execute(
            "select occurrence_id from occurrence where class = %s order by occurrence_id limit 1",
            (occurrence_class,),
        ).fetchone()
        assert occurrence is not None, f"the fixture photograph has no {occurrence_class} to name"
        entities[occurrence_class] = name_occurrence(
            identity,
            assertions,
            occurrence_id=occurrence["occurrence_id"],
            display_name=name,
            actor=actor,
        ).entity_id
    return repository, identity, assertions, actor, entities


def _notice(role: str, uses=USES) -> str:
    use = uses.use(role)
    return uses.notice(use, uses.handoff(use, MANIFEST))


def _grant(named, role: str, *, entity=None, by=None, notice=None, uses=USES) -> None:
    repository, _, _, actor, entities = named
    grant_place_name(
        repository.connection,
        repository.workspace_id,
        entity_id=entity or entities["place"],
        role=role,
        notice=_notice(role, uses) if notice is None else notice,
        actor=by or actor,
        uses=uses,
        manifest=MANIFEST,
    )


def _withdraw(named, role: str, *, entity=None, by=None) -> None:
    repository, _, _, actor, entities = named
    withdraw_place_name(
        repository.connection,
        repository.workspace_id,
        entity_id=entity or entities["place"],
        role=role,
        actor=by or actor,
    )


def _released(named, handoff, uses=USES) -> frozenset[uuid.UUID]:
    repository = named[0]
    return released_place_names(
        repository.connection, repository.workspace_id, handoff, uses=uses, manifest=MANIFEST
    )


def _events(named) -> list[dict]:
    return (
        named[0]
        .connection.execute(
            "select * from place_name_right_event order by model_role,model_id,sequence"
        )
        .fetchall()
    )


def _state(named, role: str, uses=USES) -> str:
    repository, _, _, _, entities = named
    read = read_place_name_rights(
        repository.connection,
        repository.workspace_id,
        entities["place"],
        uses=uses,
        manifest=MANIFEST,
    )
    return next(reading.state for reading in read.uses if reading.use.role.value == role)


# -- what the migration does and does not do -------------------------------------------------------


def test_the_migration_grants_nobody_anything():
    """Places named before 0097 have no decision, and the migration invents none."""
    text = MIGRATION.read_text(encoding="utf-8").lower()
    assert "insert into" not in text
    assert "update place_name_right_event" not in text


def test_without_a_decision_no_place_name_is_released(named):
    for handoff in HANDOFFS.values():
        assert _released(named, handoff) == frozenset()
    assert _state(named, "embedding") == "not_allowed"


# -- the positive control, and exactly what it releases --------------------------------------------


def test_allowing_one_use_releases_the_place_name_to_exactly_that_role(named):
    place = named[4]["place"]
    _grant(named, "embedding")

    assert _released(named, SEARCH) == {place}
    assert _released(named, PLANNER) == frozenset()
    assert _released(named, COMPOSER) == frozenset()
    assert _state(named, "embedding") == "allowed"
    repository = named[0]
    assert place_name_released(repository.connection, repository.workspace_id, place, SEARCH)
    assert not place_name_released(repository.connection, repository.workspace_id, place, PLANNER)


def test_a_grant_covers_every_model_of_the_chain_and_no_model_beyond_it(named):
    """A request that can reach a model nobody allowed releases nothing, beside allowed ones too."""
    place = named[4]["place"]
    _grant(named, "structured_extraction")
    assert len(PLANNER.identities) > 1, "the planner's role has no fallback to cover"
    events = _events(named)
    assert {(e["model_id"], e["event"]) for e in events} == {
        (identity.model_id, "granted") for identity in PLANNER.identities
    }
    assert _released(named, PLANNER) == {place}, "the positive control"

    unasked = ModelIdentity(
        provider=PLANNER.identities[0].provider,
        role=PLANNER.identities[0].role,
        model_id="unasked/model-nobody-allowed",
        revision=None,
    )
    wider = ModelHandoff(identities=(*PLANNER.identities, unasked), destination=PLANNER.destination)
    assert _released(named, wider) == frozenset()
    elsewhere = ModelHandoff(identities=PLANNER.identities, destination="https://elsewhere.example")
    assert _released(named, elsewhere) == frozenset()


def test_a_hand_over_that_is_not_one_releases_nothing(named):
    _grant(named, "embedding")
    assert _released(named, SEARCH) == {named[4]["place"]}, "the positive control"
    assert _released(named, object()) == frozenset()
    mixed = ModelHandoff(
        identities=(*SEARCH.identities, *COMPOSER.identities), destination=SEARCH.destination
    )
    assert _released(named, mixed) == frozenset()


# -- a withdrawal ends it from the next read, and nothing is rewritten -----------------------------


def test_a_withdrawal_stops_the_name_from_the_next_read_and_keeps_the_grant(named):
    place = named[4]["place"]
    _grant(named, "structured_extraction")
    assert _released(named, PLANNER) == {place}, "the positive control"
    granted = {(e["model_id"], e["sequence"]): bytes(e["receipt_sha256"]) for e in _events(named)}

    _withdraw(named, "structured_extraction")

    assert _released(named, PLANNER) == frozenset()
    assert _state(named, "structured_extraction") == "withdrawn"
    events = _events(named)
    assert [(e["event"], e["sequence"]) for e in events] == [
        ("granted", 0),
        ("withdrawn", 1),
    ] * len(PLANNER.identities)
    for event in events:
        if event["event"] == "granted":
            assert bytes(event["receipt_sha256"]) == granted[(event["model_id"], 0)]
        else:
            assert bytes(event["previous_sha256"]) == granted[(event["model_id"], 0)]


def test_allowing_again_after_a_withdrawal_is_a_third_decision(named):
    place = named[4]["place"]
    _grant(named, "embedding")
    _withdraw(named, "embedding")
    assert _released(named, SEARCH) == frozenset()

    _grant(named, "embedding")

    assert _released(named, SEARCH) == {place}
    assert [(e["event"], e["sequence"]) for e in _events(named)] == [
        ("granted", 0),
        ("withdrawn", 1),
        ("granted", 2),
    ]


def test_asking_twice_records_once_and_stopping_nothing_records_nothing(named):
    _withdraw(named, "embedding")
    assert _events(named) == []
    _grant(named, "embedding")
    _grant(named, "embedding")
    assert len(_events(named)) == len(SEARCH.identities)


# -- no person's name, whatever is recorded --------------------------------------------------------


def test_a_person_cannot_hold_the_right_in_code_or_in_the_database(named):
    repository, _, _, actor, entities = named
    with pytest.raises(UnknownPlace):
        _grant(named, "embedding", entity=entities["person"])

    # A receipt shaped exactly as the code would write one, for the person, straight into the table.
    assertion = repository.connection.execute(
        "select a.assertion_id from assertion a where a.kind='user' and a.status='active' "
        "and a.subject_ref=jsonb_build_object('type','entity','id',%s::text)",
        (str(entities["person"]),),
    ).fetchone()["assertion_id"]
    at = repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    (identity,) = SEARCH.identities
    record = {
        "profile": DECISION_PROFILE,
        "event": "granted",
        "entity_id": str(entities["person"]),
        "model": identity.as_record(),
        "destination": SEARCH.destination,
        "sequence": 0,
        "previous_sha256": None,
        "decided_by": str(actor),
        "decided_at": at.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "naming_assertion_id": str(assertion),
        "name_sha256": name_digest(PERSON).hex(),
        "notice": _notice("embedding"),
        "valid_until": (at + dt.timedelta(days=1))
        .astimezone(dt.UTC)
        .strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
    canonical = canonical_json(record)
    with pytest.raises(psycopg.errors.CheckViolation, match="live place that is not merged"):
        repository.connection.execute(
            "insert into place_name_right_event (workspace_id,event_id,entity_id,model_provider,"
            "model_role,model_id,model_revision,destination,sequence,previous_sha256,event,"
            "naming_assertion_id,name_sha256,notice,valid_until,decided_by,decided_at,"
            "receipt_record,receipt_canonical,receipt_sha256) values "
            "(%s,%s,%s,%s,%s,%s,%s,%s,0,null,'granted',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                repository.workspace_id,
                uuid.uuid4(),
                entities["person"],
                identity.provider,
                identity.role,
                identity.model_id,
                identity.revision,
                SEARCH.destination,
                assertion,
                name_digest(PERSON),
                record["notice"],
                at + dt.timedelta(days=1),
                actor,
                at,
                Jsonb(record),
                canonical,
                sha256_digest(canonical),
            ),
        )


def test_a_place_with_a_right_merged_into_a_person_releases_no_name(named):
    """The right exists, the place stops being a place of its own, and no name goes anywhere."""
    _, identity, _, actor, entities = named
    for role in HANDOFFS:
        _grant(named, role)
    assert _released(named, SEARCH) == {entities["place"]}, "the positive control"

    merge_entities(identity, sources=[entities["place"]], target=entities["person"], actor=actor)

    for handoff in HANDOFFS.values():
        released = _released(named, handoff)
        assert released == frozenset()
        assert entities["person"] not in released
    assert _state(named, "embedding") == "name_changed"


def test_a_person_merged_into_a_place_with_a_right_leaves_the_place_released_alone(named):
    _, identity, _, actor, entities = named
    _grant(named, "embedding")

    merge_entities(identity, sources=[entities["person"]], target=entities["place"], actor=actor)

    assert _released(named, SEARCH) == {entities["place"]}


# -- anything that changes the naming ends the right -----------------------------------------------


def test_a_rename_ends_the_right_even_back_to_the_same_words(named):
    _, identity, assertions, actor, entities = named
    _grant(named, "embedding")
    assert _released(named, SEARCH) == {entities["place"]}, "the positive control"

    rename_entity(
        identity, assertions, entity_id=entities["place"], display_name="The Old Mill", actor=actor
    )
    assert _released(named, SEARCH) == frozenset()
    assert _state(named, "embedding") == "name_changed"

    rename_entity(
        identity, assertions, entity_id=entities["place"], display_name=PLACE, actor=actor
    )
    assert _released(named, SEARCH) == frozenset(), "a new naming is not the one that was allowed"

    _grant(named, "embedding")
    assert _released(named, SEARCH) == {entities["place"]}


def test_undoing_a_merge_restores_a_grant_and_never_one_that_was_withdrawn(named):
    """A merge suspends a grant; only a withdrawal ends it whatever happens to the place next."""
    _, identity, _, actor, entities = named
    place = entities["place"]
    _grant(named, "embedding")

    merged = merge_entities(identity, sources=[place], target=entities["person"], actor=actor)
    assert _released(named, SEARCH) == frozenset()
    undo(identity, event_id=merged, actor=actor)
    assert _released(named, SEARCH) == {place}, "the positive control: undo restores the place"

    merged = merge_entities(identity, sources=[place], target=entities["person"], actor=actor)
    _withdraw(named, "embedding")
    undo(identity, event_id=merged, actor=actor)
    assert _released(named, SEARCH) == frozenset()
    assert [e["event"] for e in _events(named)] == ["granted", "withdrawn"]


def test_a_deleted_place_releases_nothing(named):
    repository, _, _, actor, entities = named
    _grant(named, "embedding")
    assert _released(named, SEARCH) == {entities["place"]}, "the positive control"
    repository.insert_tombstone(
        scope="entity", entity_id=entities["place"], requested_by=actor, reason="withdrew"
    )
    assert _released(named, SEARCH) == frozenset()


def test_an_ended_term_releases_nothing(named, monkeypatch):
    repository = named[0]
    now = repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    past = now - USES.term - dt.timedelta(days=1)
    monkeypatch.setattr(rights, "_now", lambda _connection: past)
    _grant(named, "embedding")
    monkeypatch.undo()

    assert _released(named, SEARCH) == frozenset()
    assert _state(named, "embedding") == "ended"
    _grant(named, "embedding")
    assert _released(named, SEARCH) == {named[4]["place"]}, "allowing again renews it"


def test_a_changed_notice_stops_every_grant_made_against_the_old_words(named):
    """Rule P6: a grant is of exactly what was said, so new words need a new yes."""
    _grant(named, "embedding")
    assert _released(named, SEARCH) == {named[4]["place"]}, "the positive control"
    raw = json.loads(
        (Path(rights.__file__).with_name("place-name-uses.v1.json")).read_text(encoding="utf-8")
    )
    for use in raw["uses"]:
        if use["role"] == "embedding":
            use["purpose"] = "search your photographs"
    reworded = parse_place_name_uses(raw)

    assert _released(named, SEARCH, uses=reworded) == frozenset()
    assert _state(named, "embedding", uses=reworded) == "notice_changed"


# -- who may decide, and what a grant must match ---------------------------------------------------


def test_a_grant_against_words_the_product_does_not_state_is_refused(named):
    with pytest.raises(PlaceNameRightRefused) as refused:
        _grant(named, "embedding", notice=_notice("embedding") + " ")
    assert refused.value.reason == "notice_changed"
    assert _events(named) == []


def test_only_the_account_holder_who_named_the_place_can_allow_it(named):
    with pytest.raises(PlaceNameRightRefused) as refused:
        _grant(named, "embedding", by=uuid.uuid4())
    assert refused.value.reason == "not_yours"
    assert _released(named, SEARCH) == frozenset()

    _grant(named, "embedding")
    _withdraw(named, "embedding", by=uuid.uuid4())
    assert _released(named, SEARCH) == frozenset(), "anyone who may decide here may stop it"


def test_an_unnamed_place_and_an_unoffered_role_cannot_be_allowed(named):
    repository = named[0]
    unnamed = repository.connection.execute(
        "insert into entity (workspace_id,class) values (%s,'place') returning entity_id",
        (repository.workspace_id,),
    ).fetchone()["entity_id"]
    with pytest.raises(PlaceNameRightRefused) as refused:
        _grant(named, "embedding", entity=unnamed)
    assert refused.value.reason == "unnamed"
    unoffered = [role.value for role in Role if USES.use(role.value) is None]
    assert "vision" in unoffered, "the positive control: the vision stage is never offered"
    for role in unoffered:
        with pytest.raises(PlaceNameRightRefused) as refused:
            _grant(named, role, notice="anything")
        assert refused.value.reason == "not_offered"
    assert _events(named) == []


# -- the record itself -----------------------------------------------------------------------------


def test_a_decision_is_never_changed_or_deleted(named):
    repository = named[0]
    _grant(named, "embedding")
    (event,) = _events(named)
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        repository.connection.execute(
            "update place_name_right_event set valid_until=valid_until+interval '1 day' "
            "where event_id=%s",
            (event["event_id"],),
        )
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        repository.connection.execute(
            "delete from place_name_right_event where event_id=%s", (event["event_id"],)
        )


def test_a_decision_out_of_its_place_in_the_chain_is_refused(named, monkeypatch):
    """Two writers that both read the same last decision cannot both append after it."""
    repository = named[0]
    _grant(named, "embedding")
    (first,) = _events(named)
    stale = rights._Stored(
        decision=rights.LastDecision(
            identity=SEARCH.identities[0],
            destination=SEARCH.destination,
            event="granted",
            decided_at=first["decided_at"],
            valid_until=first["valid_until"],
            notice=first["notice"],
            naming_holds=True,
        ),
        sequence=first["sequence"],
        receipt_sha256=bytes(first["receipt_sha256"]),
    )
    _withdraw(named, "embedding")
    with (
        pytest.raises(psycopg.errors.SerializationFailure, match="follows the last one"),
        repository.connection.transaction(),
    ):
        rights._append(
            repository.connection,
            repository.workspace_id,
            entity_id=named[4]["place"],
            identity=SEARCH.identities[0],
            destination=SEARCH.destination,
            previous=stale,
            event="withdrawn",
            actor=named[3],
            at=repository.connection.execute("select clock_timestamp() as at").fetchone()["at"],
        )


def test_the_database_refuses_a_withdrawal_with_no_grant_before_it(named):
    repository = named[0]
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="only after it was granted"),
        repository.connection.transaction(),
    ):
        rights._append(
            repository.connection,
            repository.workspace_id,
            entity_id=named[4]["place"],
            identity=SEARCH.identities[0],
            destination=SEARCH.destination,
            previous=None,
            event="withdrawn",
            actor=named[3],
            at=repository.connection.execute("select clock_timestamp() as at").fetchone()["at"],
        )


def test_a_receipt_keeps_the_notice_and_the_digest_and_never_the_name(named):
    _grant(named, "embedding")
    (event,) = _events(named)
    receipt = event["receipt_record"]
    assert receipt["notice"] == _notice("embedding")
    assert receipt["name_sha256"] == name_digest(PLACE).hex()
    assert PLACE.lower() not in json.dumps(receipt).lower()
    assert bytes(event["receipt_sha256"]) == sha256_digest(canonical_json(receipt))


def test_a_withdrawal_cannot_commit_while_a_final_read_check_holds_the_lock(named, ingest_spine):
    _grant(named, "embedding")
    _, open_another = ingest_spine
    reader = open_another().connection
    with reader.transaction():
        reader.execute("select asset_read_lock()")
        with pytest.raises(psycopg.errors.SerializationFailure, match="asset delivery"):
            _withdraw(named, "embedding")
    _withdraw(named, "embedding")
    assert _released(named, SEARCH) == frozenset()


def test_the_resolver_waits_for_a_decision_still_being_recorded(named, ingest_spine):
    """It reads under the asset read lock: a withdrawal in flight is waited for, not read past."""
    repository, _, _, actor, entities = named
    _grant(named, "embedding")
    _, open_another = ingest_spine
    other = open_another()
    with other.connection.transaction():
        withdraw_place_name(
            other.connection,
            other.workspace_id,
            entity_id=entities["place"],
            role="embedding",
            actor=actor,
        )
        repository.connection.execute("set lock_timeout = '200ms'")
        try:
            with pytest.raises(psycopg.errors.LockNotAvailable):
                _released(named, SEARCH)
        finally:
            repository.connection.execute("reset lock_timeout")
    assert _released(named, SEARCH) == frozenset()


def test_the_resolver_refuses_a_connection_inside_a_transaction(named):
    """The lock it takes must be released before anything is sent, so it will not inherit one."""
    repository = named[0]
    with repository.connection.transaction(), pytest.raises(ValueError, match="idle connection"):
        _released(named, SEARCH)


def test_the_release_runs_on_the_executors_read_only_role_and_in_no_other_workspace(
    named, spine_schema
):
    """The question route reads on the read-only executor connection, so the release runs there.

    It takes the asset read lock inside a read-only transaction; if that role could not, every
    request would crash rather than decide. A session declaring another workspace sees neither
    this workspace's places nor their decisions, so it releases nothing of this one's.
    """
    repository = named[0]
    _, schema = spine_schema
    provision_runtime_role(repository.connection, role="exulanica_ro", read_only=True)
    readonly = scratch_role_database(schema, "exulanica_ro")
    workspace = repository.workspace_id
    _grant(named, "embedding")

    with readonly.session(workspace) as connection:
        assert connection.execute("select current_user as who").fetchone()["who"] == "exulanica_ro"
        assert released_place_names(connection, workspace, SEARCH) == {named[4]["place"]}

    with readonly.session(uuid.uuid4()) as connection:
        assert released_place_names(connection, workspace, SEARCH) == frozenset()
