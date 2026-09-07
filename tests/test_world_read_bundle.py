"""The World Read bundle: what it promises a recipient, checked from outside the builder.

Every test here is written from the position of the recipient the bundle exists for: a client in
another process, in another language, holding only the returned JSON. Where a test needs to know a
digest, it recomputes one rather than calling the production function, because a test that hashes
with the code under test proves that the code agrees with itself.
"""

from __future__ import annotations

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


def test_the_bundle_names_the_scene_addressing_limitation(published, repository):
    """The roadmap promises addressing by entity, place and time. v1 addresses a scene."""
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    addressing = envelope["bundle"]["addressing"]
    assert addressing["by"] == "reconstruction_scene"
    assert "capability 3" in addressing["limitation"]


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
    assert release["not_yet_earnable"]["releasable"].startswith("no per-person state")


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
