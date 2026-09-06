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
from exulanica.graph.read_consent import CONSENT_BASIS, PERSON_CONSENT_AVAILABLE
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


def test_recorded_and_displayed_rungs_stay_separate(published, repository):
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    rungs = envelope["bundle"]["rungs"]
    assert set(rungs) == {"recorded", "recorded_reasons", "displayed", "display_reasons", "ladder"}
    assert rungs["displayed"] in (1, 2, 3, 4)


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
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    consent = envelope["bundle"]["consent"]
    assert consent["basis"] == CONSENT_BASIS
    assert consent["person_consent"] == "unavailable"
    assert len(consent["per_capture"]) == envelope["bundle"]["scene"]["member_count"]
    for record in consent["per_capture"].values():
        # Never an empty list of people. Absence of a person layer is not absence of people.
        assert record["person_consent"] == "unavailable"
        assert record["screening"]["state"] in {"screened", "unscreened"}


def test_the_release_state_is_internal_only_until_person_consent_lands(published, repository):
    """This test is a tripwire, and it is meant to fail when the privacy branch merges.

    ``PERSON_CONSENT_AVAILABLE`` flips on that branch. When it does, this assertion fails and the
    release rule has to be decided from the per-person receipts rather than quietly inherited from
    the coarse screening receipt. A release state that upgraded itself silently would be the exact
    failure Phase 10 capability 5 exists to prevent.
    """
    assert PERSON_CONSENT_AVAILABLE is False
    store, _captures, scene_id = published
    envelope = world_read_bundle(repository.connection, repository.workspace_id, scene_id, store)
    assert envelope is not None
    release = envelope["bundle"]["release"]
    assert release["state"] == "internal_only"
    assert release["basis"] == CONSENT_BASIS
    assert any("third party" in claim for claim in release["does_not_establish"])
    assert any("train" in claim for claim in release["does_not_establish"])


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
