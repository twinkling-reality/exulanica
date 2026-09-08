"""The World Read bundle: what it promises a recipient, checked from outside the builder.

Every test here is written from the position of the recipient the bundle exists for: a client in
another process, in another language, holding only the returned JSON. Where a test needs to know a
digest, it recomputes one rather than calling the production function, because a test that hashes
with the code under test proves that the code agrees with itself.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.graph.read_consent import SCREENING_BASIS, person_consent_state, release_state
from exulanica.graph.reconstruction_scenes import reconstruction_scene_rows
from exulanica.graph.world_read import (
    NUMBER_DECIMALS,
    WORLD_READ_PROFILE,
    world_read_bundle,
)
from exulanica.ingest.repository import IngestRepository
from exulanica.store.local import LocalContentAddressedStore

from test_scene_reconstruction_pipeline import FakeColmap, _processor, _queued_scene


def _canonical(value: object) -> bytes:
    """Canonical JSON, reimplemented here rather than imported.

    This is the recipient's half of the digest claim. If the production canonicaliser and this
    four-line one ever disagree, the bundle's promise that another implementation can reproduce
    its digest is false, and this is where that shows up.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _published_scene(repository, tmp_path: Path, *, registered: int, spacing: float):
    """One real scene through the ordinary pipeline: group, pose, place, gate, assert.

    ``registered`` and ``spacing`` decide whether the pose receipt is accepted. Cameras reach the
    payload only from an accepted receipt (``recovered_camera_records`` returns nothing otherwise),
    and the camera-translation floor refuses a set photographed from too close together, so a
    fixture that wants recovered cameras has to register every photograph and separate them.
    """
    store, captures, _point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="world-read", lease_seconds=60)
    assert claimed is not None and claimed.job_id == job_id
    executor = FakeColmap(registered=registered, camera_spacing=spacing)
    outcome = _processor(repository, store, tmp_path, executor).process(claimed)
    assert outcome.scene_id is not None
    return store, captures, outcome.scene_id


@pytest.fixture
def published(repository, tmp_path):
    """Every photograph registered, the pose receipt accepted, so recovered cameras exist."""
    return _published_scene(repository, tmp_path, registered=3, spacing=5)


@pytest.fixture
def partly_registered(repository, tmp_path):
    """Two photographs of three register, which is the ordinary honest-degradation case."""
    return _published_scene(repository, tmp_path, registered=2, spacing=1)


def test_a_recipient_reproduces_the_digest_from_the_returned_bytes_alone(published, repository):
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    assert envelope["profile"] == WORLD_READ_PROFILE
    assert envelope["bundle"]["profile"] == WORLD_READ_PROFILE

    # The recipient has the parsed JSON and nothing else. Round-tripping through json.dumps and
    # json.loads first is the point: it destroys every Python object identity the builder had, so
    # what is hashed here is genuinely the wire form.
    received = json.loads(json.dumps(envelope))
    recomputed = hashlib.sha256(_canonical(received["bundle"])).hexdigest()
    assert recomputed == envelope["bundle_sha256"]


def test_every_number_in_the_bundle_survives_canonical_json(published, repository):
    """No float reaches the digest input, at any depth, under any key."""
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None

    floats: list[str] = []

    def walk(value: object, path: str) -> None:
        if isinstance(value, bool) or value is None or isinstance(value, int | str):
            return
        if isinstance(value, float):
            floats.append(path)
            return
        if isinstance(value, dict):
            for key, sub in value.items():
                walk(sub, f"{path}.{key}")
            return
        if isinstance(value, list):
            for index, sub in enumerate(value):
                walk(sub, f"{path}[{index}]")
            return
        floats.append(f"{path} is a {type(value).__name__}")

    walk(envelope["bundle"], "$")
    assert floats == []


def test_measured_numbers_are_decimal_strings_at_the_declared_precision(published, repository):
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    bundle = envelope["bundle"]

    cameras = [view["camera"] for view in bundle["views"] if view["camera"] is not None]
    assert cameras, "the fixture registers cameras; a bundle with none proves nothing here"
    for camera in cameras:
        for number in camera["scene_from_camera_row_major"]:
            assert isinstance(number, str)
            assert len(number.split(".")[1]) == NUMBER_DECIMALS
        assert isinstance(camera["calibration"]["fx"], str)
        assert isinstance(camera["calibration"]["width"], int)

    assert str(NUMBER_DECIMALS) in bundle["number_encoding"]


def test_changing_one_referenced_digest_changes_the_bundle_digest(published, repository):
    """The bundle is bound to the artifacts it names, not merely accompanied by them."""
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None

    mutated = json.loads(json.dumps(envelope["bundle"]))
    entries = mutated["geometry"]
    assert entries, "the fixture publishes geometry; without it this test cannot fire"
    original = entries[0]["content_sha256"]
    entries[0]["content_sha256"] = f"{'0' * 63}1"
    assert entries[0]["content_sha256"] != original
    assert hashlib.sha256(_canonical(mutated)).hexdigest() != envelope["bundle_sha256"]


def test_no_geometry_entry_is_offered_as_evidence(published, repository):
    """Invariant 2, in the shape a machine can check.

    A consumer scanning the bundle for the bytes behind a claim must not find a point map or a
    trained asset presented as one. The check is over key names rather than values because the
    failure this guards against is a well-meaning addition of a ``support_span_ids`` field to a
    geometry entry, which would read as a citation to anything that consumes the graph's
    vocabulary.
    """
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None

    forbidden = {"support_span_ids", "span_id", "evidence", "evidence_span_id", "assertion_id"}
    for entry in envelope["bundle"]["geometry"]:
        assert forbidden.isdisjoint(entry), entry.keys() & forbidden
        assert entry["tier"] == "recorded"
    assert "Nothing in this bundle is evidence" in envelope["bundle"]["epistemics"]["evidence"]


def test_recorded_and_displayed_rungs_stay_separate(partly_registered, repository):
    """Collapsing the two is how a system claims a rung it did not earn, so they must differ.

    Asserting only that both keys exist proved nothing: they would still both exist if one were
    assigned from the other. The fixture here has receipts on disk but no accepted pose, so the
    scene has a durable recorded rung and cannot draw it, and the two numbers genuinely diverge.
    """
    store, _captures, scene_id = partly_registered
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    rungs = envelope["bundle"]["rungs"]
    assert set(rungs) == {"recorded", "recorded_reasons", "displayed", "display_reasons", "ladder"}

    # Now take the bytes away. The recorded claim is durable and must not move; the displayed rung
    # is what can actually be drawn and must fall to 4.
    for entry in envelope["bundle"]["geometry"]:
        digest = BlobId.from_hex(entry["content_sha256"])
        (store.root / store.key_for(digest)).unlink(missing_ok=True)
    degraded = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert degraded is not None
    assert degraded["bundle"]["rungs"]["recorded"] == rungs["recorded"]
    assert degraded["bundle"]["rungs"]["displayed"] == 4
    assert degraded["bundle"]["rungs"]["displayed"] != degraded["bundle"]["rungs"]["recorded"]
    assert degraded["bundle"]["geometry"] == []


def test_a_scene_bundle_says_which_address_reached_it_and_what_still_has_none(
    published, repository
):
    """The limitation this used to assert became false, and a false limitation is the worst kind.

    It said addressing by a place and a time was not implemented. It is, so the string is gone
    and what replaced it has to be checkable in both directions: what this bundle CAN be
    addressed by, and the one thing it still cannot, which is an entity. A test that only
    asserted the string was gone would pass on a bundle that says nothing at all.

    The membership half matters as much. This scene belongs to no place, and the block says so
    with a state rather than by omitting the key, because "no place" and "this reader did not
    look" are different facts and a missing key is indistinguishable between them.
    """
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    addressing = envelope["bundle"]["addressing"]
    assert addressing["by"] == "reconstruction_scene"
    assert addressing["scene_id"] == str(scene_id)
    assert addressing["at"] is None
    assert "limitation" not in addressing
    assert "a place by its id with a time" in addressing["addresses"]
    assert addressing["not_addressable"].startswith("an entity")
    assert addressing["place"]["state"] == "none"
    assert addressing["place"]["place_id"] is None
    assert "ordinary case" in addressing["place"]["reason"]


def test_every_member_appears_as_a_view_even_when_it_did_not_register(
    partly_registered, repository
):
    """Counting the views must give the number of photographs, not the number that worked."""
    store, _captures, scene_id = partly_registered
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    bundle = envelope["bundle"]
    assert len(bundle["views"]) == bundle["scene"]["member_count"]
    registered = [view for view in bundle["views"] if view["registered"]]
    assert len(registered) == bundle["scene"]["registered_member_count"]
    # Cameras are all-or-nothing per scene, and that is worth pinning rather than working
    # around: they come only from an accepted pose receipt, so a scene whose receipt the gate
    # refused shows every member without a camera even where the member registered and placed.
    # A reader that inferred "no camera means this photograph failed" would be wrong here.
    with_camera = [view for view in bundle["views"] if view["camera"] is not None]
    assert with_camera == [] or len(with_camera) == len(registered)


def test_a_scene_in_another_workspace_is_not_readable(published, repository, ingest_spine):
    """Workspace isolation, asked the way a cross-tenant probe would ask it.

    The probe holds a real scene id and a valid session for a different workspace, which is the
    only interesting case: an attacker who has to guess the id learns nothing either way.
    """
    store, _captures, scene_id = published
    _primary, open_another = ingest_spine
    elsewhere = uuid.uuid4()
    assert elsewhere != repository.workspace_id
    other = IngestRepository(open_another().connection, elsewhere)
    assert world_read_bundle(other.connection, elsewhere, scene_id, store) is None


def test_an_unknown_scene_is_not_readable(published, repository):
    store, _captures, _scene_id = published
    absent = uuid.uuid4()
    assert world_read_bundle(repository.connection, repository.workspace_id, absent, store) is None


def test_consent_reports_the_screening_basis_and_refuses_to_infer_people(published, repository):
    """An unscreened photograph says nobody looked, and never says nobody is there."""
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    consent = envelope["bundle"]["consent"]
    # This fixture writes no person regions, so every photograph in it is unscreened and the scene
    # rests on the screening receipt alone. The basis is per photograph now: it becomes the
    # per-person one only where regions exist, so a capture nobody screened is not credited with
    # receipts it does not have.
    assert consent["basis"] == SCREENING_BASIS
    assert consent["person_consent"] == "unscreened"
    assert len(consent["per_capture"]) == envelope["bundle"]["scene"]["member_count"]
    for record in consent["per_capture"].values():
        # Never an empty list of people, and never "nobody is here" either. The two answers this
        # field can give are "nobody looked" and "people are located"; absence is neither.
        assert record["person_consent"] == "unscreened"
        assert record["recorded_person_count"] == 0
        assert "not a statement that there is nobody in it" in record["person_consent_reason"]
        assert record["screening"]["state"] in {"screened", "unscreened"}


def test_the_scene_consent_answer_is_the_weakest_of_its_photographs(published, repository):
    """One unexamined photograph must not hide behind the examined ones beside it.

    The scene-level field and the per-capture records used to speak different vocabularies under
    one word: the scene said whether the *build* had a person layer while each capture said
    whether that *photograph* had a decision, so a merged tree produced a bundle reporting
    ``available`` over a list of captures every one of which said ``unavailable``. Both now
    describe photographs, and this asserts the fold is the restrictive one.
    """
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    consent = envelope["bundle"]["consent"]
    per_capture = consent["per_capture"]
    assert per_capture, "the fixture must publish at least one member for this to mean anything"
    recorded = {"person_consent": "recorded", "recorded_person_count": 1}
    unscreened = {"person_consent": "unscreened", "recorded_person_count": 0}
    assert consent["person_consent"] == person_consent_state(per_capture)
    # The discriminating case, and the only one that is: a scene with BOTH kinds of photograph.
    # An all-unscreened or all-recorded scene answers the same under a restrictive fold and a
    # permissive one, so a test built only from those proves nothing. MEASURED 2026-09-07: the
    # first version of this test asserted exactly those two and the negative control's `all` to
    # `any` mutant survived it.
    assert person_consent_state({"a": recorded, "b": unscreened}) == "unscreened"
    assert person_consent_state({"a": recorded, "b": recorded}) == "recorded"
    assert person_consent_state({"a": unscreened}) == "unscreened"
    # No members at all is the restrictive answer too, and not by accident: an empty fold over
    # `all` is vacuously true, so this is the one case the natural spelling gets backwards.
    assert person_consent_state({}) == "unscreened"


def test_the_release_state_is_internal_only_while_no_person_state_reaches_the_bundle(
    published, repository
):
    """This test is a tripwire, and it is armed for the thing that is missing NOW.

    Its predecessor was armed for the person-consent layer arriving, and it fired when that layer
    merged on 2026-09-07. The release rule was then decided rather than inherited, and the decision
    was that ``internal_only`` still holds, for a reason that is not the old one: the bundle
    carries no state for any individual person, so a recipient holding it cannot check a claim
    that the people in these photographs agreed. A permissive state nobody can check from the
    bytes they were handed is the failure Phase 10 capability 5 exists to prevent, and it does not
    become acceptable because the facts now exist somewhere else in the system.

    So this pins the ABSENCE, not the value. The day a per-person state is added to a view, this
    fails, and whoever added it has to decide the release gradient with the clock problem in front
    of them: a presentation consent expires against ``clock_timestamp()``, ``release`` is inside
    ``recorded_keys``, and a digest that moves when nobody wrote anything is a digest nobody can
    quote. Deleting this assertion instead of answering that is how the bundle starts lying.
    """
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    bundle = envelope["bundle"]
    release = bundle["release"]
    assert release["state"] == "internal_only"
    assert release["basis"] == SCREENING_BASIS
    assert any("third party" in claim for claim in release["does_not_establish"])
    assert any("train" in claim for claim in release["does_not_establish"])
    # The three consents stay apart, and none of them is established by anything in this bundle.
    assert set(release["scopes"]) == {"presence", "naming", "likeness"}
    assert not any(scope["established"] for scope in release["scopes"].values())
    # The tripwire itself: no view carries a per-person fact, so the claim above is the only one
    # this bundle can support.
    for view in bundle["views"]:
        assert "person_regions" not in view
        assert "person_review_state" not in view
        assert "state" not in view["consent"]
    assert "authenticate" in release["not_yet_earnable"]["releasable"]
    assert "recipient_evidence" in bundle


def test_the_release_counts_are_recomputable_from_the_bundles_own_per_capture_records(
    published, repository
):
    """A release claim a recipient cannot recompute is a release claim they have to trust.

    The counts in ``release.people`` are a fold over ``consent.per_capture``, which travels in the
    same bundle, so this reproduces them from the wire form alone. It is the same discipline as
    the recorded-digest recipe: the bundle states its arithmetic and a stranger checks it.
    """
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    received = json.loads(json.dumps(envelope))["bundle"]
    per_capture = received["consent"]["per_capture"]
    people = received["release"]["people"]
    assert people["photographs"] == len(per_capture)
    assert people["screened_for_people"] == sum(
        1 for record in per_capture.values() if record["person_consent"] == "recorded"
    )
    assert people["recorded_people"] == sum(
        record["recorded_person_count"] for record in per_capture.values()
    )


def test_the_release_state_does_not_move_when_a_consent_expires(published, repository):
    """The recorded digest may not depend on the clock, and this is the rule stated as a test.

    ``person_consent_is_granted`` (migration 0037) filters on ``clock_timestamp()`` against
    ``effective_at`` and ``valid_until``, so a temporary hide expiring changes a person's resolved
    state with no write in between. ``release`` is inside ``recorded_keys``, so a release answer
    that read a resolved state would move both digests on a timer. This asserts the release block
    is a function of facts with no time predicate behind them: given the same per-capture records,
    it returns the same answer, and it never consults a resolver to produce it.
    """
    unscreened = {"person_consent": "unscreened", "recorded_person_count": 0}
    recorded = {"person_consent": "recorded", "recorded_person_count": 3}
    assert release_state({"a": recorded}) == release_state({"a": dict(recorded)})
    # And the answer does vary with the facts, so the equality above is not the equality of a
    # constant. The state does not move; the reason and the counts do.
    mixed = release_state({"a": recorded, "b": unscreened})
    assert mixed["state"] == release_state({"a": recorded})["state"] == "internal_only"
    assert mixed["people"]["screened_for_people"] == 1
    assert (
        mixed["scopes"]["likeness"]["reason"]
        != (release_state({"a": recorded})["scopes"]["likeness"]["reason"])
    )
    assert "have not been screened" in mixed["scopes"]["likeness"]["reason"]


def test_the_region_graph_says_unavailable_rather_than_empty(published, repository):
    """No structural snapshot is committed by this fixture, and the bundle must say that.

    An empty ``regions`` list with an ``available`` state would read as "this scene belongs to no
    region", which is a claim about the world. "No snapshot exists" is the fact.
    """
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    region_graph = envelope["bundle"]["region_graph"]
    assert region_graph["state"] == "unavailable"
    assert region_graph["regions"] == []
    assert "no current structural snapshot" in region_graph["reason"]


def test_a_bundle_without_a_store_still_reports_honestly(published, repository):
    """With no store the receipts are unreadable, and the scene degrades rather than vanishing."""
    _store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, None)
    assert envelope is not None
    bundle = envelope["bundle"]
    assert bundle["scene"]["receipt_state"] == "missing"
    assert bundle["scene"]["placement_state"] == "unavailable"
    assert bundle["geometry"] == []
    assert bundle["views"], "the photographs are still members even when no geometry loads"


def test_two_reads_of_an_unchanged_scene_produce_the_same_digest(published, repository, tmp_path):
    """Determinism, which is what makes the digest worth quoting to anybody."""
    store, _captures, scene_id = published
    first = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    reopened = LocalContentAddressedStore(tmp_path / "store")
    second = world_read_bundle(repository.connection, repository.workspace_id, scene_id, reopened)
    assert first is not None and second is not None
    assert first["bundle_sha256"] == second["bundle_sha256"]


def test_a_recipient_reproduces_the_recorded_digest_from_the_keys_the_bundle_names(
    published, repository
):
    """The half the first version got wrong, found by a real scene rather than by this file.

    MEASURED 2026-09-06 against the retained bowl scene: a recipient recomputing the recorded
    digest by removing ``generated`` got a different answer, because the wire bundle also carries
    ``recorded_sha256`` itself, which was not an input to its own hash. The before-and-after test
    below could not see that, because it compared two of this code's own answers. This one follows
    the bundle's stated recipe from outside.
    """
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    received = json.loads(json.dumps(envelope))["bundle"]

    recorded = {key: received[key] for key in received["recorded_keys"]}
    assert hashlib.sha256(_canonical(recorded)).hexdigest() == received["recorded_sha256"]

    # The recipe must not name itself or the generated tier, or the digest becomes either
    # self-referential or sensitive to filing a generation. Both were real defects.
    assert "recorded_sha256" not in received["recorded_keys"]
    assert "generated" not in received["recorded_keys"]
    assert "recorded_keys" not in received["recorded_keys"]
    assert set(received["recorded_keys"]) | {
        "generated",
        "scene",
        "views",
        "geometry",
        "rungs",
        "recorded_keys",
        "recorded_sha256",
    } == set(received)


def test_the_scene_filter_is_applied_in_the_query(published, repository):
    """One scene per request must mean one scene's receipts, not the whole workspace's.

    A read API a world model calls per place cannot read and validate every pose, placement and
    gate receipt in the store to answer for one of them. What is asserted here is that the filter
    selects exactly the asked-for scene and refuses an absent one. That the OTHER scenes' bytes are
    never fetched follows from the filter being a `where` clause rather than a comprehension over
    the result, which is visible in `exulanica/graph/reconstruction_scenes.py` and is not something
    a test with one scene in the workspace can demonstrate.
    """
    store, _captures, scene_id = published

    narrowed = reconstruction_scene_rows(
        repository.connection, repository.workspace_id, store, scene_id=scene_id
    )
    assert [row.scene_id for row in narrowed] == [scene_id]

    absent = reconstruction_scene_rows(
        repository.connection, repository.workspace_id, store, scene_id=uuid.uuid4()
    )
    assert absent == []

    # And narrowing changes the answer for that scene not at all.
    whole = reconstruction_scene_rows(repository.connection, repository.workspace_id, store)
    assert narrowed[0] == next(row for row in whole if row.scene_id == scene_id)


_SUPERSEDED_POLICY = "exulanica.reconstruction-privacy/v1"


def _screen_again_under_the_superseded_policy(repository, capture_id: uuid.UUID) -> uuid.UUID:
    """Write a newer screening receipt for this photograph under the policy version 2 replaced.

    An insert rather than an update, and not for convenience: migration 0029 puts
    ``tg_reconstruction_privacy_screening_append_only`` on this table, so a receipt's
    ``policy_version`` cannot be edited after the fact. That is also the shape of the real case
    this stands in for, where the receipt was written under version 1 and the policy moved
    afterwards.

    The receipt is built the way ``exulanica.ingest.privacy._record_screening`` builds one, because
    the table checks that ``digest(receipt_canonical,'sha256')`` is ``receipt_digest`` and that the
    canonical bytes parse back to ``receipt_record``. It cannot be produced by calling that
    function, which hardcodes the current ``PRIVACY_POLICY_VERSION``.
    """
    authorization = repository.connection.execute(
        "select authorization_id from capture_reconstruction_authorization "
        "where workspace_id=%s and capture_id=%s",
        (repository.workspace_id, capture_id),
    ).fetchone()
    assert authorization is not None, "the fixture must authorize its captures"
    row = repository.reconstruction_authorization(authorization["authorization_id"])
    assert row is not None

    params_digest = hashlib.sha256(b"exulanica.reconstruction-privacy/v1 params").digest()
    # Later than the 2026-09-04 the fixture screens at, so `distinct on ... screened_at desc`
    # selects this one. A test whose superseding receipt lost the ordering would pass for the
    # wrong reason.
    screened_at = dt.datetime(2026, 9, 5, tzinfo=dt.UTC)
    record = {
        "profile": "exulanica.reconstruction-privacy-screening-receipt/v1",
        "authorization": {
            "authorization_id": str(row.authorization_id),
            "evidence_sha256": row.evidence_digest.hex(),
            "scope": row.authorization_scope,
        },
        "capture_id": str(capture_id),
        "source_sha256": row.source_sha256.hex(),
        "screening_method": "synthetic_exemption",
        "model": None,
        "human_review": {"required": False, "reviewed_by": None},
        "sensitive_regions": [],
        "mask_artifacts": [],
        "eligibility_state": "eligible",
        "blocking_reasons": [],
        "policy": {"version": _SUPERSEDED_POLICY, "params_sha256": params_digest.hex()},
        "screened_at": "2026-09-05T00:00:00+00:00",
        "valid_until": None,
    }
    canonical = _canonical(record)
    digest = hashlib.sha256(canonical).digest()
    screening_id = uuid.uuid4()
    repository.insert_privacy_screening(
        screening_id=screening_id,
        authorization_id=row.authorization_id,
        capture_id=capture_id,
        source_sha256=BlobId(row.source_sha256),
        screening_method="synthetic_exemption",
        human_review_required=False,
        reviewed_by=None,
        sensitive_regions=[],
        eligibility_state="eligible",
        blocking_reasons=[],
        policy_version=_SUPERSEDED_POLICY,
        policy_params_digest=params_digest,
        authorization_scope=row.authorization_scope,
        screened_at=screened_at,
        valid_until=None,
        receipt_record=record,
        receipt_canonical=canonical,
        receipt_digest=digest,
    )
    return screening_id


def test_a_receipt_the_database_refuses_is_not_reported_as_simply_eligible(published, repository):
    """A receipt written under a superseded policy must not be published as screened and eligible.

    This is the bundle contradicting its own database. ``privacy_screening_allows_capture``
    (migration 0037) requires ``s.policy_version = current_privacy_policy()``, and version 2
    replaced "is anybody visible?" with a region list carrying a consent state per person, so a
    version 1 receipt does not carry forward. The bundle applied no such check: it selected the
    newest receipt per capture and published its ``eligibility_state`` verbatim.

    MEASURED 2026-09-07 against the retained ``public`` schema: 281 of the 283 captures whose
    newest receipt is retained say ``eligible`` while the database refuses geometry for them on
    the policy version alone, and none is both eligible and current. So this is not a hypothetical
    shape, it is the whole of the retained corpus.

    What is asserted is the DISTINCTION, not a rewrite. The receipt still says ``eligible``,
    because that is what the named reviewer wrote and no read path gets to edit it. What is added
    is whether the policy in force still accepts it.
    """
    store, captures, scene_id = published
    refused_capture = captures[0]
    superseded_id = _screen_again_under_the_superseded_policy(repository, refused_capture)

    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    per_capture = envelope["bundle"]["consent"]["per_capture"]
    refused = per_capture[str(refused_capture)]

    # The receipt is untouched: it says screened, and it says eligible, because it does.
    assert refused["screening"]["state"] == "screened"
    assert refused["screening"]["eligibility"] == "eligible"
    assert refused["screening"]["policy_version"] == _SUPERSEDED_POLICY
    # And the new fact, which is the one the database actually gates on.
    assert refused["screening"]["policy_in_force"] == "exulanica.reconstruction-privacy/v2"
    assert refused["screening"]["under_current_policy"] is False
    assert "screened again" in refused["screening"]["policy_reason"]
    # The reason must not overstate what was checked. Being current is one term of the predicate.
    assert "not sufficient" in refused["screening"]["policy_reason"]

    # The database agrees, which is what makes this a test about the contradiction rather than
    # about a string the bundle builder chose.
    assert repository.privacy_screening_allows(refused_capture, superseded_id) is False

    # The discriminating control, in the same scene and the same bundle. An all-superseded fixture
    # would be passed by a hardcoded False. MEASURED 2026-09-07: the sibling fold test in this file
    # records a mutant that survived exactly that mistake.
    others = [str(capture) for capture in captures[1:]]
    assert others, "a mixed scene is the point; a one-member fixture proves nothing here"
    for key in others:
        current = per_capture[key]
        assert current["screening"]["under_current_policy"] is True
        assert current["screening"]["policy_version"] == "exulanica.reconstruction-privacy/v2"
        newest = repository.connection.execute(
            "select screening_id from reconstruction_privacy_screening "
            "where workspace_id=%s and capture_id=%s order by screened_at desc limit 1",
            (repository.workspace_id, uuid.UUID(key)),
        ).fetchone()
        assert newest is not None
        assert repository.privacy_screening_allows(uuid.UUID(key), newest["screening_id"]) is True


def test_the_policy_currency_field_cannot_move_the_recorded_digest_on_a_timer(
    published, repository
):
    """The policy half of the gate may go in the digest; the expiry half beside it may not.

    ``privacy_screening_allows_capture`` is a conjunction of terms that do not behave alike.
    ``s.policy_version = current_privacy_policy()`` compares against an ``immutable`` function
    returning a literal, so it moves only when a migration writes a new version. Its neighbours
    ``s.valid_until > clock_timestamp()`` and ``a.valid_until > clock_timestamp()`` move with no
    write at all, which is why the bundle reports the first and not the whole predicate.

    This is armed for the migration that redefines ``current_privacy_policy()`` as anything but a
    literal. That would put a timer inside ``recorded_keys`` and make the recorded digest of every
    bundle unquotable, and it would do it silently.
    """
    store, _captures, scene_id = published
    # Every visible definition, not the first one. MEASURED 2026-09-07: during a suite run two
    # rows come back, `public`'s and the throwaway schema's, and `public` sorts first, so an
    # unscoped fetchone() was reading the retained schema's function rather than the one this
    # test's own migration just created. A tripwire armed against the wrong schema is not armed:
    # a migration that made this function volatile would change it in the scratch schema while
    # `public` kept its 'i', and this would have passed.
    volatility = repository.connection.execute(
        "select n.nspname, p.provolatile from pg_proc p "
        "join pg_namespace n on n.oid = p.pronamespace "
        "where p.proname = 'current_privacy_policy'"
    ).fetchall()
    assert volatility, "the policy predicate must exist to be reported"
    assert all(row["provolatile"] == "i" for row in volatility), (
        "current_privacy_policy() stopped being immutable in "
        f"{[row['nspname'] for row in volatility if row['provolatile'] != 'i']}, so the policy "
        "currency this bundle reports can now change with no write, and it is inside recorded_keys"
    )

    first = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    second = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert first is not None and second is not None
    assert first["bundle"]["recorded_sha256"] == second["bundle"]["recorded_sha256"]
    assert first["bundle_sha256"] == second["bundle_sha256"]
    # The field is genuinely inside the recorded recipe, so the equality above is a claim about
    # this field and not about some unrelated subset of the bundle.
    recorded = {key: first["bundle"][key] for key in first["bundle"]["recorded_keys"]}
    assert "consent" in recorded
    assert all(
        "under_current_policy" in record["screening"]
        for record in recorded["consent"]["per_capture"].values()
    )
