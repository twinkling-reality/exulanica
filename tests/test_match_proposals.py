"""Automatic match proposals, from context and never from biometrics.

Before this, ``match_proposal`` was written by nothing and identity was rung one: the account
holder says who somebody is. These tests are the second rung, and the thing they are most
concerned with is the rule that stops it becoming a nag.

Decision id-4: a rejected match is never re-proposed identically, and a proposal built from
genuinely DIFFERENT signals is still permitted to ask again. That is a subset test over modality
sets, and until migration 0008 it could not be computed at all: ``identity_rejection`` stored a
digest and no modality list, and a digest is opaque. What existed was digest equality, which
under-suppresses in the dangerous direction, because ``basis_digest`` covers extractor versions
and a version bump would therefore revive every rejection the user had already answered.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, confirm_link, name_occurrence, reject_link
from exulanica.identity.proposer import PROPOSER_PARAMS, propose_matches
from exulanica.identity.signals import (
    SCENE_GROUP_KIND,
    CaptureContext,
    ContextSignals,
    corroborating_modalities,
)

pytestmark = pytest.mark.postgres


def test_the_scene_group_kind_is_the_one_ingest_writes():
    """A literal duplicated across a boundary nothing checks is a literal that drifts.

    ``exulanica.identity`` may not import ``exulanica.ingest``: the layer contract makes them
    siblings. So the ``derived_artifact.kind`` string is written in one and read in the other,
    and this test is the only thing that can see both. It needs no database, which is why it
    would still catch the drift on a machine with no server.
    """
    from exulanica.ingest.scenes import SCENE_GROUP_KIND as ingest_kind

    assert ingest_kind == SCENE_GROUP_KIND


def _context(
    *,
    capture: uuid.UUID | None = None,
    lat: float | None = None,
    lon: float | None = None,
    groups: frozenset[uuid.UUID] = frozenset(),
    labels: frozenset[str] = frozenset(),
) -> CaptureContext:
    return CaptureContext(
        capture_id=capture or uuid.uuid4(),
        started_at=None,
        lat=lat,
        lon=lon,
        scene_group_ids=groups,
        object_labels=labels,
    )


# -- the signals, which need no database ---------------------------------------------------


def test_two_captures_at_the_same_place_corroborate_on_place():
    near = _context(lat=51.5007, lon=-0.1246)
    also_near = _context(lat=51.5009, lon=-0.1244)
    assert corroborating_modalities(
        near, also_near, join_label="red cube", max_place_distance_m=250, min_shared_labels=2
    ) == ("context_place",)


def test_a_capture_with_no_position_corroborates_nothing_on_place():
    """"We do not know where this was taken" is not "these were taken far apart".

    The corpus has an indoor trip with no GPS at all, so this is the normal case rather than an
    edge one, and a sentinel distance would quietly let the first behave like the second.
    """
    positioned = _context(lat=51.5007, lon=-0.1246)
    unknown = _context()
    assert (
        corroborating_modalities(
            positioned, unknown, join_label=None, max_place_distance_m=250, min_shared_labels=2
        )
        == ()
    )


def test_captures_far_apart_corroborate_nothing():
    london = _context(lat=51.5007, lon=-0.1246)
    edinburgh = _context(lat=55.9533, lon=-3.1883)
    assert (
        corroborating_modalities(
            london, edinburgh, join_label=None, max_place_distance_m=250, min_shared_labels=2
        )
        == ()
    )


def test_the_join_label_is_not_counted_as_its_own_evidence():
    """Twenty-seven captures containing a red cube do not contain the same red cube.

    The label is the hard constraint that decides which pairs are worth comparing. Counting it in
    the shared-label set would make the constraint corroborate itself, and every red cube in the
    library would be proposed as the same cube with a straight face.
    """
    group = uuid.uuid4()
    a = _context(labels=frozenset({"red cube"}))
    b = _context(labels=frozenset({"red cube"}))
    assert (
        corroborating_modalities(
            a, b, join_label="red cube", max_place_distance_m=250, min_shared_labels=1
        )
        == ()
    )
    # The same pair, sharing something that is NOT the join key, does corroborate.
    c = _context(labels=frozenset({"red cube", "a bench"}))
    d = _context(labels=frozenset({"red cube", "a bench"}))
    assert corroborating_modalities(
        c, d, join_label="red cube", max_place_distance_m=250, min_shared_labels=1
    ) == ("context_cooccurrence",)
    # And a shared scene group corroborates on its own.
    e = _context(groups=frozenset({group}))
    f = _context(groups=frozenset({group}))
    assert corroborating_modalities(
        e, f, join_label="red cube", max_place_distance_m=250, min_shared_labels=99
    ) == ("context_cooccurrence",)


# -- the producer, against a real database -------------------------------------------------


@pytest.fixture
def corpus(repository):
    """Two captures, each with one 'person' occurrence, at the same place and in one group.

    Built by hand rather than by ingest, because what is under test is the proposer and a vision
    model in the loop would make the fixture about the detector instead.
    """
    from exulanica.evidence import EvidenceAddress
    from exulanica.evidence.blob import BlobId
    from exulanica.identity.keys import occurrence_identity_key
    from exulanica.ingest.ledger import Ledger

    run = Ledger.start_run(repository, trigger="ingest")
    captures: list[uuid.UUID] = []
    occurrences: list[uuid.UUID] = []
    for index in range(2):
        blob = BlobId.of_bytes(f"photo-{index}".encode())
        repository.upsert_blob(blob, byte_size=8, media_type="image/jpeg", storage_key=f"k{index}")
        capture = repository.insert_capture(blob, device_id="probe", started_at=None)
        address = EvidenceAddress.photograph(blob)
        span = repository.upsert_span(address)
        occurrence = repository.insert_occurrence(
            capture_id=capture.capture_id,
            occurrence_class="person",
            primary_span_id=span,
            span_ids=[span],
            presence=[(0, 1)],
            produced_by_run=run.run_id,
            detector_version="probe:1",
            identity_key=occurrence_identity_key(address, "person"),
            emit_key=f"probe:o:{index}",
            quality={"label": "person", "confidence_band": "high"},
        )
        # A position, so the pair corroborates on place as well as on co-occurrence. One signal
        # is deliberately not enough to earn a question; see the drop test below.
        repository.insert_assertion(
            kind="capture",
            predicate_key="gps_position_is",
            subject_ref={"type": "capture", "id": str(capture.capture_id)},
            object_value={"lat": 51.5007 + index * 0.0002, "lon": -0.1246},
            emit_key=f"probe:gps:{index}",
            support_span_ids=[span],
        )
        captures.append(capture.capture_id)
        occurrences.append(occurrence)

    # One scene group holding both, which is what makes them corroborate on co-occurrence.
    repository.upsert_derived_artifact(
        derived_id=uuid.uuid4(),
        kind=SCENE_GROUP_KIND,
        depends_on=[{"kind": "capture", "id": str(c)} for c in captures],
        dep_index=[f"capture:{c}" for c in captures],
        source_ids=list(captures),
        payload={"capture_ids": [str(c) for c in captures], "ordinal": 0},
    )
    return repository, run.run_id, captures, occurrences


def _name_first(repository, occurrence_id: uuid.UUID, actor: uuid.UUID) -> uuid.UUID:
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    named = name_occurrence(
        identity,
        AssertionWriter(repository.connection, repository.workspace_id),
        occurrence_id=occurrence_id,
        display_name="Julie",
        actor=actor,
    )
    return named.entity_id


def _propose(repository, run_id: uuid.UUID):
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    signals = ContextSignals.read(repository.connection, repository.workspace_id)
    return identity, propose_matches(identity, signals, run_id=run_id)


def test_naming_one_person_produces_a_question_about_the_other_capture(corpus):
    """The whole point. Before this, nothing wrote a match proposal at all."""
    repository, run_id, _captures, occurrences = corpus
    actor = uuid.uuid4()
    _name_first(repository, occurrences[0], actor)

    identity, report = _propose(repository, run_id)
    assert report.anchors == 1
    assert report.candidates == 1
    assert len(report.surfaced) == 1, report

    pending = identity.proposals.pending(
        occurrence_id=occurrences[1],
        entity_id=_entity_of(identity, occurrences[0]),
    )
    assert pending is not None
    assert pending["basis"]["modalities"] == ["context_cooccurrence", "context_place"]


def _entity_of(identity: IdentityRepository, occurrence_id: uuid.UUID) -> uuid.UUID:
    link = identity.links.for_occurrence(occurrence_id)
    assert link is not None
    return link.entity_id


def test_a_second_pass_asks_no_second_question(corpus):
    """Idempotent by the emit key, which is keyed on the question and not on the answer."""
    repository, run_id, _captures, occurrences = corpus
    _name_first(repository, occurrences[0], uuid.uuid4())
    _identity, first = _propose(repository, run_id)
    _identity, second = _propose(repository, run_id)
    assert len(first.surfaced) == 1
    assert second.written == 0, "a re-run wrote a proposal that was already there"


def test_rejecting_a_proposal_suppresses_the_same_basis_and_not_a_different_one(corpus):
    """Decision id-4, which is the reason migration 0008 stores a modality list.

    Rejecting on ``{context_cooccurrence}`` must suppress a later proposal built from exactly
    that, and must NOT suppress one that carries a modality the user was never shown. Under
    digest equality alone the first half fails the moment a version bumps.
    """
    repository, run_id, _captures, occurrences = corpus
    actor = uuid.uuid4()
    _name_first(repository, occurrences[0], actor)
    identity, _ = _propose(repository, run_id)
    entity_id = _entity_of(identity, occurrences[0])

    pending = identity.proposals.pending(occurrence_id=occurrences[1], entity_id=entity_id)
    assert pending is not None
    reject_link(
        identity,
        occurrence_id=occurrences[1],
        entity_id=entity_id,
        actor=actor,
        basis_digest=bytes(pending["basis_digest"]),
        basis_modalities=pending["basis"]["modalities"],
    )

    occurrence = identity.occurrences.by_id(occurrences[1])
    assert occurrence is not None
    suppressed, new_modality = identity.rejections.covering(
        scope="occurrence_entity",
        key_a=occurrence.identity_key,
        key_b=entity_id.bytes,
        modalities=("context_cooccurrence", "context_place"),
    )
    assert suppressed is True
    assert new_modality is None

    # A genuinely different signal set is still permitted to ask, and says what is new.
    permitted, fresh = identity.rejections.covering(
        scope="occurrence_entity",
        key_a=occurrence.identity_key,
        key_b=entity_id.bytes,
        modalities=("context_cooccurrence", "context_place", "user_text"),
    )
    assert permitted is False
    assert fresh == "user_text"


def test_a_user_who_was_shown_nothing_suppresses_everything(corpus):
    """An unprompted no carries NULL modalities, not an empty list, and the two are opposite.

    An empty array is a subset of nothing, so it would suppress no future proposal at all and a
    GPS coincidence could overrule a person about their own life. NULL, read through the guard,
    suppresses every basis. A zero must say which zero it is.
    """
    repository, _run_id, _captures, occurrences = corpus
    actor = uuid.uuid4()
    entity_id = _name_first(repository, occurrences[0], actor)
    identity = IdentityRepository(repository.connection, repository.workspace_id)

    reject_link(identity, occurrence_id=occurrences[1], entity_id=entity_id, actor=actor)
    occurrence = identity.occurrences.by_id(occurrences[1])
    assert occurrence is not None
    for modalities in (("context_place",), ("context_cooccurrence", "context_place", "user_text")):
        suppressed, _ = identity.rejections.covering(
            scope="occurrence_entity",
            key_a=occurrence.identity_key,
            key_b=entity_id.bytes,
            modalities=modalities,
        )
        assert suppressed is True, modalities


def test_a_suppressed_proposal_is_recorded_rather_than_silently_skipped(corpus):
    """"Why is it not asking me about this" has to be answerable."""
    repository, run_id, _captures, occurrences = corpus
    actor = uuid.uuid4()
    entity_id = _name_first(repository, occurrences[0], actor)
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    reject_link(identity, occurrence_id=occurrences[1], entity_id=entity_id, actor=actor)

    _identity, report = _propose(repository, run_id)
    assert len(report.suppressed) == 1, report
    assert report.surfaced == []
    outcome = repository.connection.execute(
        "select outcome from match_proposal where workspace_id = %s",
        (repository.workspace_id,),
    ).fetchone()
    assert outcome["outcome"] == "suppressed_by_rejection"


def test_confirming_withdraws_every_live_rejection_for_the_pair(corpus):
    """Otherwise a machine rejection outlives the confirmation that contradicted it.

    The user rejected on one basis and then said yes. Leaving that no live would suppress future
    proposals about a pair they have now confirmed.
    """
    repository, run_id, _captures, occurrences = corpus
    actor = uuid.uuid4()
    entity_id = _name_first(repository, occurrences[0], actor)
    identity, _ = _propose(repository, run_id)
    pending = identity.proposals.pending(occurrence_id=occurrences[1], entity_id=entity_id)
    assert pending is not None
    reject_link(
        identity,
        occurrence_id=occurrences[1],
        entity_id=entity_id,
        actor=actor,
        basis_digest=bytes(pending["basis_digest"]),
        basis_modalities=pending["basis"]["modalities"],
    )
    confirm_link(identity, occurrence_id=occurrences[1], entity_id=entity_id, actor=actor)

    live = repository.connection.execute(
        "select count(*) as n from identity_rejection where workspace_id = %s "
        "and revoked_at is null",
        (repository.workspace_id,),
    ).fetchone()
    assert live["n"] == 0, "a rejection survived the confirmation that contradicted it"


def test_the_open_question_count_falls_when_the_question_is_answered(corpus):
    """``open_question_count`` had to stop meaning "was ever surfaced".

    Counting ``outcome = 'surfaced'`` counts answered proposals forever, and the ambient counter
    the interface shows would read the same number for the rest of time.
    """
    from exulanica.graph import read_snapshot

    repository, run_id, _captures, occurrences = corpus
    actor = uuid.uuid4()
    entity_id = _name_first(repository, occurrences[0], actor)
    identity, _ = _propose(repository, run_id)

    before = read_snapshot(repository.connection, repository.workspace_id)
    assert [e.open_question_count for e in before.entities] == [1]

    confirm_link(identity, occurrence_id=occurrences[1], entity_id=entity_id, actor=actor)
    after = read_snapshot(repository.connection, repository.workspace_id)
    assert [e.open_question_count for e in after.entities] == [0]


def test_no_proposal_is_written_when_nothing_corroborates(repository):
    """A label match with no context signal is not a weak question. It is not a question."""
    from exulanica.evidence import EvidenceAddress
    from exulanica.evidence.blob import BlobId
    from exulanica.identity.keys import occurrence_identity_key
    from exulanica.ingest.ledger import Ledger

    run = Ledger.start_run(repository, trigger="ingest")
    occurrences = []
    for index in range(2):
        blob = BlobId.of_bytes(f"lonely-{index}".encode())
        repository.upsert_blob(blob, byte_size=8, media_type="image/jpeg", storage_key=f"l{index}")
        capture = repository.insert_capture(blob, device_id="probe", started_at=None)
        address = EvidenceAddress.photograph(blob)
        span = repository.upsert_span(address)
        occurrences.append(
            repository.insert_occurrence(
                capture_id=capture.capture_id,
                occurrence_class="person",
                primary_span_id=span,
                span_ids=[span],
                presence=[(0, 1)],
                produced_by_run=run.run_id,
                detector_version="probe:1",
                identity_key=occurrence_identity_key(address, "person"),
                emit_key=f"lonely:o:{index}",
                quality={"label": "person"},
            )
        )
    # No scene group, no GPS, no shared labels: nothing corroborates.
    _name_first(repository, occurrences[0], uuid.uuid4())
    _identity, report = _propose(repository, run.run_id)
    assert report.written == 0
    assert report.uncorroborated == 1, report


def test_the_producer_widens_selection_without_making_a_citable_claim(corpus):
    from exulanica.selection import (
        Abstention,
        EntitySelector,
        EpistemicScope,
        Intent,
        SelectionPlan,
        Session,
        abstain,
        build_packet,
        execute,
        validate,
    )

    repository, run_id, _captures, occurrences = corpus
    actor = uuid.uuid4()
    entity_id = _name_first(repository, occurrences[0], actor)
    identity, report = _propose(repository, run_id)
    assert len(report.auto_provisional) == 1
    link = identity.links.for_occurrence(occurrences[1], states=("auto_provisional",))
    assert link is not None and link.decided_by is None
    pending = identity.proposals.pending(occurrence_id=occurrences[1], entity_id=entity_id)
    assert pending["basis"]["weights_milli"] == {
        "context_place": 400, "context_cooccurrence": 400,
    }
    assert pending["basis"]["thresholds_milli"]["auto_provisional"] == 800
    assert "calibration" in pending["basis"]
    assert "user_text" not in pending["basis"]["modalities"]
    counts = []
    for scope in (EpistemicScope.CONFIRMED, EpistemicScope.INCLUDE_PROPOSALS):
        plan = SelectionPlan(intent=Intent.CAPTURES,
                             entities=EntitySelector(ids=[entity_id]), epistemic=scope)
        result = execute(repository.connection, validate(
            repository.connection, plan, Session(workspace_id=repository.workspace_id, actor=actor)
        ))
        counts.append(result.total_matched)
        packet = build_packet(repository.connection, result, workspace_id=repository.workspace_id)
        if scope is EpistemicScope.INCLUDE_PROPOSALS:
            assert not packet.citable
            assert abstain(packet)[1] is Abstention.AMBIGUOUS
    assert counts == [1, 2]


@pytest.mark.parametrize("decision", ["confirm", "reject"])
def test_real_proposal_decisions_and_undo_invalidate_the_consumed_index(corpus, decision):
    from exulanica.identity.match_context import MATCH_CONTEXT_KIND, refresh_match_context
    from exulanica.identity.undo import undo

    repository, run_id, _captures, occurrences = corpus
    actor = uuid.uuid4()
    entity_id = _name_first(repository, occurrences[0], actor)
    identity, report = _propose(repository, run_id)
    proposal_link = report.auto_provisional[0]
    index = repository.connection.execute(
        "select derived_id, dep_index, payload from derived_artifact "
        "where workspace_id = %s and kind = %s and not stale",
        (repository.workspace_id, MATCH_CONTEXT_KIND),
    ).fetchone()
    assert f"entity:{entity_id}" in index["dep_index"]
    assert f"occurrence:{occurrences[0]}" in index["dep_index"]
    assert index["payload"]["anchors"][0]["occurrence_id"] == str(occurrences[0])
    operation = confirm_link if decision == "confirm" else reject_link
    operation(identity, occurrence_id=occurrences[1], entity_id=entity_id, actor=actor)
    event = identity.events.recent(limit=1)[0]
    state = repository.connection.execute(
        "select state from entity_link where link_id = %s", (proposal_link,),
    ).fetchone()["state"]
    assert state == ("revoked" if decision == "confirm" else "rejected")
    if decision == "confirm":
        assert event["payload"]["superseded_proposal"] == str(proposal_link)
    assert repository.connection.execute(
        "select stale from derived_artifact where derived_id = %s", (index["derived_id"],),
    ).fetchone()["stale"] is True
    rebuilt = refresh_match_context(identity)
    assert len(rebuilt["anchors"]) == (2 if decision == "confirm" else 1)
    undo(identity, event_id=event["event_id"], actor=actor)
    assert repository.connection.execute(
        "select state from entity_link where link_id = %s", (proposal_link,),
    ).fetchone()["state"] == "proposed"
    assert repository.connection.execute(
        "select count(*) as n from derived_artifact where workspace_id = %s "
        "and kind = %s and not stale", (repository.workspace_id, MATCH_CONTEXT_KIND),
    ).fetchone()["n"] == 0



def test_the_surface_threshold_is_a_parameter_and_not_a_constant():
    """The weights are unvalidated, and an edit has to move the digest that records them.

    Same discipline as the depth stage: parameters rather than constants, so a later tuning pass
    is recorded on the rows it produced rather than applied retroactively.
    """
    from exulanica.identity.proposer import params_digest

    original = params_digest()
    PROPOSER_PARAMS["surface_threshold_milli"] = 999
    try:
        assert params_digest() != original
    finally:
        PROPOSER_PARAMS["surface_threshold_milli"] = 500
    assert params_digest() == original


def test_one_signal_alone_is_recorded_and_not_asked_about(repository):
    """A single GPS coincidence is not a question. It is a coincidence.

    The threshold sits above the weight of one context signal and below two, so a pair that
    corroborates on one is written as ``dropped`` and never surfaced. The row exists because
    "we considered this and did not ask" is the part of the record that explains why the user is
    not being asked, and because the threshold was measured by nobody and may move.
    """
    from exulanica.evidence import EvidenceAddress
    from exulanica.evidence.blob import BlobId
    from exulanica.identity.keys import occurrence_identity_key
    from exulanica.ingest.ledger import Ledger

    run = Ledger.start_run(repository, trigger="ingest")
    occurrences = []
    for index in range(2):
        blob = BlobId.of_bytes(f"one-signal-{index}".encode())
        repository.upsert_blob(blob, byte_size=8, media_type="image/jpeg", storage_key=f"s{index}")
        capture = repository.insert_capture(blob, device_id="probe", started_at=None)
        address = EvidenceAddress.photograph(blob)
        span = repository.upsert_span(address)
        occurrences.append(
            repository.insert_occurrence(
                capture_id=capture.capture_id,
                occurrence_class="person",
                primary_span_id=span,
                span_ids=[span],
                presence=[(0, 1)],
                produced_by_run=run.run_id,
                detector_version="probe:1",
                identity_key=occurrence_identity_key(address, "person"),
                emit_key=f"one-signal:o:{index}",
                quality={"label": "person"},
            )
        )
        # Position only. No scene group and no shared object labels, so place is the only signal.
        repository.insert_assertion(
            kind="capture",
            predicate_key="gps_position_is",
            subject_ref={"type": "capture", "id": str(capture.capture_id)},
            object_value={"lat": 51.5007, "lon": -0.1246},
            emit_key=f"one-signal:gps:{index}",
            support_span_ids=[span],
        )
    _name_first(repository, occurrences[0], uuid.uuid4())
    _identity, report = _propose(repository, run.run_id)
    assert report.surfaced == []
    assert len(report.dropped) == 1, report


def test_a_rejected_proposal_reads_as_suppressed_even_though_its_row_still_says_surfaced(corpus):
    """``outcome`` is what the producer decided and it goes stale the moment the user answers.

    The emit key is keyed on the question rather than on the answer, deliberately, so the next
    pass recomputes the same key and ``on conflict do nothing`` declines to rewrite the row. A
    read that trusted the column would show a proposal the user has refused as a live one, which
    is the interface asking again with no record of having been told no.
    """
    from exulanica.graph import read_snapshot

    repository, run_id, _captures, occurrences = corpus
    actor = uuid.uuid4()
    entity_id = _name_first(repository, occurrences[0], actor)
    identity, _ = _propose(repository, run_id)
    pending = identity.proposals.pending(occurrence_id=occurrences[1], entity_id=entity_id)
    assert pending is not None
    reject_link(
        identity,
        occurrence_id=occurrences[1],
        entity_id=entity_id,
        actor=actor,
        basis_digest=bytes(pending["basis_digest"]),
        basis_modalities=pending["basis"]["modalities"],
    )

    stored = repository.connection.execute(
        "select outcome from match_proposal where workspace_id = %s", (repository.workspace_id,)
    ).fetchone()["outcome"]
    assert stored == "surfaced", "the stored outcome is the producer's decision and does not move"

    snapshot = read_snapshot(repository.connection, repository.workspace_id)
    assert [p.suppressed_by_rejection for p in snapshot.proposals] == [True]
    assert [e.open_question_count for e in snapshot.entities] == [0]


def test_a_surfaceable_question_below_the_auto_threshold_remains_unlinked(corpus, monkeypatch):
    repository, run_id, _captures, occurrences = corpus
    _name_first(repository, occurrences[0], uuid.uuid4())
    monkeypatch.setitem(PROPOSER_PARAMS, "auto_provisional_threshold_milli", 801)
    identity, report = _propose(repository, run_id)
    assert len(report.surfaced) == 1
    assert report.auto_provisional == []
    assert identity.links.for_occurrence(
        occurrences[1], states=("auto_provisional", "confirmed"),
    ) is None


def test_duplicate_exemplars_do_not_break_a_tie_between_entities(repository):
    """Three object anchors mean two tied entities, not three votes or an automatic winner."""
    from exulanica.evidence import EvidenceAddress
    from exulanica.evidence.blob import BlobId
    from exulanica.identity.keys import occurrence_identity_key
    from exulanica.ingest.ledger import Ledger

    run = Ledger.start_run(repository, trigger="ingest")
    captures, occurrences = [], []
    for index in range(4):
        payload = f"synthetic-tied-object-{index}".encode()
        blob = BlobId.of_bytes(payload)
        repository.upsert_blob(
            blob, byte_size=len(payload), media_type="image/jpeg", storage_key=f"tie-{index}",
        )
        capture = repository.insert_capture(blob, device_id="synthetic-probe", started_at=None)
        address = EvidenceAddress.photograph(blob)
        span = repository.upsert_span(address)
        occurrences.append(repository.insert_occurrence(
            capture_id=capture.capture_id, occurrence_class="object", primary_span_id=span,
            span_ids=[span], presence=[(0, 1)], produced_by_run=run.run_id,
            detector_version="synthetic-context:1",
            identity_key=occurrence_identity_key(address, "object"),
            emit_key=f"tie:object:{index}", quality={"label": "red cube"},
        ))
        repository.insert_assertion(
            kind="capture", predicate_key="gps_position_is",
            subject_ref={"type": "capture", "id": str(capture.capture_id)},
            object_value={"lat": 51.5007, "lon": -0.1246},
            emit_key=f"tie:gps:{index}", support_span_ids=[span],
        )
        captures.append(capture.capture_id)
    repository.upsert_derived_artifact(
        derived_id=uuid.uuid4(), kind=SCENE_GROUP_KIND,
        depends_on=[{"kind": "capture", "id": str(c)} for c in captures],
        dep_index=[f"capture:{c}" for c in captures], source_ids=captures,
        payload={"capture_ids": [str(c) for c in captures], "ordinal": 0},
    )
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    actor = uuid.uuid4()
    entities = sorted((
        name_occurrence(
            identity, AssertionWriter(repository.connection, repository.workspace_id),
            occurrence_id=occurrences[index], display_name=f"Synthetic box {index}", actor=actor,
        ).entity_id for index in range(2)
    ), key=str)
    # Duplicate the entity that sorts first. If anchors are ranked without deduplication,
    # idempotent proposal writes hide its second row but leave the other entity at rank 2.
    confirm_link(identity, occurrence_id=occurrences[2], entity_id=entities[0], actor=actor)

    identity, report = _propose(repository, run.run_id)
    assert report.anchors == 3 and report.candidates == 1
    rows = repository.connection.execute(
        "select entity_id, rank, score, outcome from match_proposal "
        "where workspace_id=%s and occurrence_id=%s order by rank",
        (repository.workspace_id, occurrences[3]),
    ).fetchall()
    assert [row["entity_id"] for row in rows] == entities
    assert [row["rank"] for row in rows] == [0, 1]
    assert [(row["score"], row["outcome"]) for row in rows] == [
        (0.8, "surfaced"), (0.8, "surfaced"),
    ]
    assert len(report.surfaced) == 2
    assert report.auto_provisional == []
    assert identity.links.for_occurrence(
        occurrences[3], states=("auto_provisional", "confirmed", "proposed"),
    ) is None
