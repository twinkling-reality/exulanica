"""The joint reconstruction that admits a scene to a place, driven end to end against a stub.

**Nothing here runs COLMAP.** The joint model comes from the same ``FakeColmap`` the scene
reconstruction tests use, extended with camera centres that a place alignment can actually be
fitted to; the reason it has to be extended is in :class:`JointColmap`. So what these tests
establish is the build: which rows are written, which are not, what is read to produce them, and
that a refusal arrives as a result rather than as a traceback. They establish nothing whatever
about two real captures of a real place. ``docs/place-identity.md`` says the exit for that stays
open, and it does.

The geometry is a fixture with a known ground truth, which is what makes the composition
assertable rather than merely non-crashing: each scene's cameras are placed in its own frame,
the joint frame is a chosen similarity away from the anchor's, and the candidate is a second
chosen similarity away from that. The transform the build must recover is therefore known before
the build runs, and the two-hop case's is the product of the two.

Each test is named for the failure it catches.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from pathlib import Path

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.evidence.scene import scene_id_for, scene_member_digest
from exulanica.ingest.place_alignment import (
    PlaceAlignmentUnavailable,
    build_place_alignment,
    establish_place,
)
from exulanica.ingest.stages import stage
from exulanica.reconstruction.pose import CommandResult
from exulanica.store.local import LocalContentAddressedStore

from test_scene_reconstruction_pipeline import FakeColmap

_CODE_REVISION = "c" * 40
_EXECUTION_IMAGE = "registry.example/exulanica-place@sha256:" + "d" * 64

#: Fifteen correspondences is the floor the policy sets once the held-out fold is reserved: with
#: a stride of five, sixteen cameras leave thirteen to fit on and three to judge on. A fixture
#: below that number would exercise only the refusal path, which is what one test here wants and
#: no other does.
_CAMERAS = 16


class JointColmap(FakeColmap):
    """The repository's COLMAP double, with the one thing a place alignment cannot do without.

    ``FakeColmap`` stands every recovered camera on the x axis at ``-index * spacing``. That is
    right for what it was written for and fatal here: collinear cameras make the cross-covariance
    singular, ``fit_place_alignment`` refuses a singular fit rather than returning an arbitrary
    rotation, and so no accepted join could ever be exercised through it. Everything else it
    does, the call log, the failure and crash shapes, the database file each stage leaves, is
    inherited unchanged.

    Cameras are looked up by the CONTENT of the staged file rather than by its name, so this
    double knows nothing about how the build names a frame inside a joint manifest. A test that
    encoded that naming rule would pass by agreeing with the code rather than with the world.
    """

    def __init__(
        self,
        centres: dict[str, tuple[float, float, float]],
        *,
        aside: dict[str, tuple[float, float, float]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.centres = centres
        # A second, smaller connected model. COLMAP writes one directory per component and
        # `pose.py` selects the largest, so this is how a run that recovered both capture sets
        # but not in ONE model is expressed.
        self.aside = aside or {}

    def __call__(self, command: tuple[str, ...], cwd: Path) -> CommandResult:
        if command[1] != "mapper":
            return super().__call__(command, cwd)
        self.calls.append("mapper")
        source = Path(command[command.index("--image_path") + 1])
        staged = {
            path.name: _sha256(path.read_bytes())
            for path in source.iterdir()
            if path.is_file() and not path.name.startswith(".")
        }
        for ordinal, placed in enumerate((self.centres, self.aside)):
            names = sorted(name for name, digest in staged.items() if digest in placed)
            if not names and ordinal:
                continue
            model = cwd / "sparse" / str(ordinal)
            model.mkdir(parents=True)
            lines: list[str] = []
            for index, name in enumerate(names, 1):
                x, y, z = placed[staged[name]]
                # Identity rotation, so COLMAP's translation is the negated camera centre and
                # `_quaternion_camera_centre` reads back exactly the point this fixture chose.
                lines.extend([f"{index} 1 0 0 0 {-x} {-y} {-z} 1 {name}", ""])
            (model / "images.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            # One sparse point, because the joint model is a build intermediate whose tracks
            # nothing reads. No `cameras.txt`: the retained-track path is for a scene's own
            # receipt, and this frame is deliberately never retained.
            (model / "points3D.txt").write_text(
                "1 0 0 0 255 255 255 0.4 1 0 2 0\n", encoding="utf-8"
            )
        return CommandResult(0, "ok", "", 1.0)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- the fixture geometry ---------------------------------------------------------------


def _rotation(yaw: float, pitch: float) -> list[list[float]]:
    """The same proper rotation ``tests/test_place_alignment.py`` builds, for the same reason."""
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    return [
        [cy * cp, -sy, cy * sp],
        [sy * cp, cy, sy * sp],
        [-sp, 0.0, cp],
    ]


def _similarity(
    *, scale: float, yaw: float, pitch: float, offset: tuple[float, float, float]
) -> tuple[float, ...]:
    rotation = _rotation(yaw, pitch)
    return (
        scale * rotation[0][0],
        scale * rotation[0][1],
        scale * rotation[0][2],
        offset[0],
        scale * rotation[1][0],
        scale * rotation[1][1],
        scale * rotation[1][2],
        offset[1],
        scale * rotation[2][0],
        scale * rotation[2][1],
        scale * rotation[2][2],
        offset[2],
        0.0,
        0.0,
        0.0,
        1.0,
    )


def _apply(matrix: tuple[float, ...], point: tuple[float, float, float]) -> tuple[float, ...]:
    return tuple(
        sum(matrix[row * 4 + column] * point[column] for column in range(3)) + matrix[row * 4 + 3]
        for row in range(3)
    )


def _compose(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(
        sum(left[row * 4 + k] * right[k * 4 + column] for k in range(4))
        for row in range(4)
        for column in range(4)
    )


def _ring(count: int, *, radius: float, phase: float) -> list[tuple[float, float, float]]:
    """Cameras circling one subject, with a vertical wobble so they are not coplanar."""
    return [
        (
            radius * math.cos(2 * math.pi * index / count + phase),
            0.45 * math.sin(3 * (2 * math.pi * index / count + phase)),
            radius * math.sin(2 * math.pi * index / count + phase),
        )
        for index in range(count)
    ]


#: The joint frame, one chosen similarity away from the anchor scene's own recovered frame. Its
#: particular numbers matter only in that they are not identity: a joint run that happened to
#: land on the anchor's frame would let a build that forgot to invert anything pass.
_JOINT_FROM_ANCHOR = _similarity(scale=1.7, yaw=0.5, pitch=-0.2, offset=(5.0, -3.0, 2.0))
#: The truth the build has to recover for the one-hop case: where the second capture's frame sits
#: in the first's.
_ANCHOR_FROM_SECOND = _similarity(scale=0.8, yaw=-0.9, pitch=0.35, offset=(-2.0, 1.5, 4.0))
#: And for the two-hop case, where the third capture's frame sits in the second's.
_SECOND_FROM_THIRD = _similarity(scale=1.25, yaw=0.4, pitch=0.15, offset=(1.0, 2.0, -3.5))
_JOINT_FROM_SECOND = _similarity(scale=0.6, yaw=1.1, pitch=0.25, offset=(-7.0, 4.0, 1.0))


# -- the world --------------------------------------------------------------------------


class Scene:
    """One retained scene: its captures, its own recovered camera centres, and its receipt."""

    def __init__(self, scene_id, captures, centres) -> None:
        self.scene_id = scene_id
        self.captures = captures
        self.centres = centres

    def joint(
        self, transform: tuple[float, ...], *, only: int | None = None, noise: float = 0.0
    ) -> dict[str, tuple[float, float, float]]:
        """This scene's cameras as the joint run would recover them, keyed by source bytes.

        ``only`` registers a prefix of them and ``noise`` displaces them, which is how the three
        refusals are reached: too few correspondences, and a frame the joint run contradicts.
        """
        selected = self.captures if only is None else self.captures[:only]
        placed: dict[str, tuple[float, float, float]] = {}
        for index, capture in enumerate(selected):
            moved = _apply(transform, self.centres[index])
            placed[capture.blob_id.hex] = tuple(  # type: ignore[assignment]
                moved[axis] + (noise if (index + axis) % 2 == 0 else -noise) for axis in range(3)
            )
        return placed


def _scene(repository, store, *, label: str, when: str, phase: float, radius: float) -> Scene:
    captures = []
    for index in range(_CAMERAS):
        stored = store.put_bytes(f"{label}-photograph-{index}".encode())
        repository.upsert_blob(
            stored.blob_id,
            byte_size=stored.byte_size,
            media_type="image/jpeg",
            storage_key=store.key_for(stored.blob_id),
        )
        captures.append(repository.insert_capture(stored.blob_id, device_id=None, started_at=when))
    capture_ids = [capture.capture_id for capture in captures]
    scene_id = scene_id_for(capture_ids)
    repository.insert_completed_reconstruction_scene(
        scene_id=scene_id,
        member_digest=scene_member_digest(capture_ids),
        scene_members=[(capture_id, True) for capture_id in capture_ids],
    )
    return Scene(scene_id, captures, _ring(_CAMERAS, radius=radius, phase=phase))


def _write_pose_receipt(repository, store, scene: Scene) -> uuid.UUID:
    """The retained receipt the build reads its scene-side correspondences out of.

    Written by hand rather than by running the pose stage, for the reason ``write_point_map``
    gives about a point map: the stage needs COLMAP, which is not installed here. What matters is
    that this is the shape the pose stage writes, ``exulanica.colmap-pose-receipt/v2`` carrying
    its own manifest and one ``camera_centre_xyz`` per registered photograph, because that pairing
    is the only route from an image name back to a capture.
    """
    frames = [
        {
            "capture_ref": str(capture.capture_id),
            "filename": f"{index:06d}.jpg",
            "sha256": capture.blob_id.hex,
            "capture_set": str(scene.scene_id),
        }
        for index, capture in enumerate(scene.captures)
    ]
    receipt = {
        "profile": "exulanica.colmap-pose-receipt/v2",
        "manifest_digest": "0" * 64,
        "manifest": {"scene_ref": str(scene.scene_id), "frames": frames},
        "quality_digest": "0" * 64,
        "quality": {
            "registered_images": [frame["filename"] for frame in frames],
            "cameras": [
                {"image_name": frame["filename"], "camera_centre_xyz": list(scene.centres[index])}
                for index, frame in enumerate(frames)
            ],
        },
    }
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    stored = store.put_bytes(payload)
    spec = stage("scene_pose")
    artifact_id = uuid.uuid5(uuid.NAMESPACE_URL, f"pose-receipt/{scene.scene_id}")
    repository.insert_scene_artifact(
        artifact_id=artifact_id,
        kind=spec.output_kind,
        scene_id=scene.scene_id,
        stage_key=spec.key,
        stage_version=spec.version,
        params_digest=spec.params_digest,
        input_digest=bytes(32),
        idempotency_key=f"pose-receipt/{scene.scene_id}",
        content_sha256=stored.blob_id.digest,
        storage_key=store.key_for(stored.blob_id),
        byte_size=stored.byte_size,
        produced_by_event=None,
    )
    return artifact_id


def _build(repository, store, tmp_path, *, place_id, candidate, against, executor):
    return build_place_alignment(
        repository,
        store,
        place_id=place_id,
        candidate_scene_id=candidate,
        against_scene_id=against,
        scratch_root=tmp_path / "scratch",
        code_revision=_CODE_REVISION,
        execution_image=_EXECUTION_IMAGE,
        colmap_version="pycolmap 4.2.0 (stubbed)",
        executor=executor,
    )


def _receipt(store, artifact: dict) -> dict:
    """The receipt bytes the artifact row names, read back through the content address."""
    return json.loads(store.get(BlobId(bytes(artifact["content_sha256"]))))


def _rows(repository, table: str, **where) -> list[dict]:
    clause = " and ".join(f"{column} = %s" for column in where)
    sql = f"select * from {table}"
    if clause:
        sql = f"{sql} where {clause}"
    return [dict(row) for row in repository.connection.execute(sql, tuple(where.values()))]


@pytest.fixture
def world(repository, tmp_path):
    """An anchored place, a second capture of it, and both scenes' retained pose receipts."""
    store = LocalContentAddressedStore(tmp_path / "store")
    anchor = _scene(
        repository, store, label="anchor", when="2026-08-01T10:00:00+00:00", phase=0.0, radius=3.0
    )
    second = _scene(
        repository, store, label="second", when="2026-09-01T10:00:00+00:00", phase=0.7, radius=2.4
    )
    _write_pose_receipt(repository, store, anchor)
    _write_pose_receipt(repository, store, second)
    place_id = uuid.uuid4()
    establish_place(repository, place_id=place_id, anchor_scene_id=anchor.scene_id)
    return store, place_id, anchor, second


def test_an_accepted_join_writes_one_version_at_one_hop_and_no_second_verdict(
    repository, tmp_path, world
):
    """The whole build, and the four rows it is allowed to leave behind.

    A second call is the part worth the assertion. 0038's unique key says one build over one
    union under one policy has one answer, and a caller that re-ran the joint reconstruction
    would spend forty-five minutes reaching a row the database would refuse, while its numbers
    differed from the first run's in the last digits and looked like a disagreement about the
    world rather than about a mapper's threading.
    """
    store, place_id, anchor, second = world
    centres = {
        **anchor.joint(_JOINT_FROM_ANCHOR),
        **second.joint(_compose(_JOINT_FROM_ANCHOR, _ANCHOR_FROM_SECOND)),
    }
    executor = JointColmap(centres)
    outcome = _build(
        repository,
        store,
        tmp_path,
        place_id=place_id,
        candidate=second.scene_id,
        against=anchor.scene_id,
        executor=executor,
    )

    assert outcome.accepted is True, outcome.reason
    assert outcome.reason is None
    assert outcome.frame_hops == 1
    assert outcome.reused is False

    alignments = _rows(repository, "place_alignment", place_id=place_id)
    assert len(alignments) == 1
    assert alignments[0]["accepted"] is True and alignments[0]["reason"] is None
    assert alignments[0]["receipt_artifact_id"] == outcome.receipt_artifact_id

    versions = {
        row["scene_id"]: row for row in _rows(repository, "place_version", place_id=place_id)
    }
    assert set(versions) == {anchor.scene_id, second.scene_id}
    assert versions[anchor.scene_id]["frame_hops"] == 0
    assert versions[anchor.scene_id]["admitted_by_alignment_id"] is None
    assert versions[second.scene_id]["frame_hops"] == 1
    assert versions[second.scene_id]["admitted_by_alignment_id"] == outcome.alignment_id
    assert versions[second.scene_id]["ordered_by_basis"] == "capture_exif"

    # The receipt's subject is the place. Attaching it to either scene would be a claim about one
    # capture set that was measured over two, and the claim would be invisible from that side.
    artifact = _rows(repository, "artifact", artifact_id=outcome.receipt_artifact_id)[0]
    assert artifact["place_id"] == place_id
    assert artifact["scene_id"] is None and artifact["source_blob_sha256"] is None
    assert artifact["kind"] == "place_alignment_receipt"

    receipt = _receipt(store, artifact)
    assert receipt["profile"] == "exulanica.place-alignment-receipt/v1"
    assert receipt["physically_validated"] is False
    assert receipt["frame_hops"] == 1
    assert receipt["joint_model_sha256"] is not None
    assert len(receipt["union"]["frames"]) == 2 * _CAMERAS
    assert {frame["capture_set"] for frame in receipt["union"]["frames"]} == {
        str(anchor.scene_id),
        str(second.scene_id),
    }
    # The transform is the one the fixture built the joint frame out of, recovered through an
    # inversion and a composition rather than read back from anywhere.
    for measured, expected in zip(
        receipt["place_from_candidate_row_major"], _ANCHOR_FROM_SECOND, strict=True
    ):
        assert measured == pytest.approx(expected, abs=1e-6)
    assert receipt["candidate_units_to_place_units"] == pytest.approx(0.8, rel=1e-6)

    calls = list(executor.calls)
    again = _build(
        repository,
        store,
        tmp_path,
        place_id=place_id,
        candidate=second.scene_id,
        against=anchor.scene_id,
        executor=executor,
    )
    assert again.reused is True
    assert again.alignment_id == outcome.alignment_id
    assert again.accepted is True and again.frame_hops == 1
    assert executor.calls == calls, "the second call re-ran the joint reconstruction"
    assert len(_rows(repository, "place_alignment", place_id=place_id)) == 1
    assert len(_rows(repository, "place_version", place_id=place_id)) == 2


@pytest.mark.parametrize(
    ("shape", "reason"),
    [
        ("disconnected", "place-alignment-not-connected"),
        ("too_few", "place-alignment-insufficient-correspondences"),
        ("contradicted", "place-alignment-inconsistent"),
    ],
)
def test_each_measured_refusal_is_a_row_with_its_reason_and_never_an_exception(
    repository, tmp_path, world, shape, reason
):
    """A refused pair stays two places, and the world has to be able to say so.

    It can say it from a row carrying a reason. It cannot say it from an exception: the scene
    processor catches every exception and files it as a job failure with ``failure_class`` set to
    the exception's class name, which is the right shape for a crash and says nothing about
    whether two captures are of one place. So all three refusals return, and each writes an
    alignment row and no version.
    """
    store, place_id, anchor, second = world
    joint_from_second = _compose(_JOINT_FROM_ANCHOR, _ANCHOR_FROM_SECOND)
    if shape == "disconnected":
        # The second capture set has no registered image in the model at all, so the two declared
        # sets did not land in one connected reconstruction.
        centres = anchor.joint(_JOINT_FROM_ANCHOR)
    elif shape == "too_few":
        centres = {
            **anchor.joint(_JOINT_FROM_ANCHOR, only=4),
            **second.joint(joint_from_second, only=4),
        }
    else:
        centres = {
            **anchor.joint(_JOINT_FROM_ANCHOR),
            **second.joint(joint_from_second, noise=2.5),
        }

    outcome = _build(
        repository,
        store,
        tmp_path,
        place_id=place_id,
        candidate=second.scene_id,
        against=anchor.scene_id,
        executor=JointColmap(centres),
    )

    assert outcome.accepted is False
    assert outcome.reason == reason
    assert outcome.frame_hops is None

    alignments = _rows(repository, "place_alignment", place_id=place_id)
    assert len(alignments) == 1
    assert alignments[0]["accepted"] is False
    assert alignments[0]["reason"] == reason

    versions = [row["scene_id"] for row in _rows(repository, "place_version", place_id=place_id)]
    assert versions == [anchor.scene_id], "a refused candidate was bound to the place anyway"

    receipt_id = alignments[0]["receipt_artifact_id"]
    artifact = _rows(repository, "artifact", artifact_id=receipt_id)[0]
    receipt = _receipt(store, artifact)
    assert receipt["accepted"] is False and receipt["reason"] == reason
    assert receipt["place_from_candidate_row_major"] is None
    assert receipt["candidate_units_to_place_units"] is None


def test_a_scene_with_no_retained_pose_receipt_refuses_before_inventing_correspondences(
    repository, tmp_path
):
    """The constraint the whole design rests on, checked from the side that would hide it.

    Every correspondence's scene half is a ``camera_centre_xyz`` a pose receipt already retained.
    A scene without one has no camera positions in its own frame at all, and there is nothing
    else to derive them from: no learned descriptors are persisted and COLMAP point ids mean
    nothing across two reconstructions. A build that produced a fit here would have invented the
    half of every correspondence it could not read, so it refuses, and it refuses before the
    joint reconstruction rather than after an hour of matching.
    """
    store = LocalContentAddressedStore(tmp_path / "store")
    anchor = _scene(
        repository, store, label="anchor", when="2026-08-01T10:00:00+00:00", phase=0.0, radius=3.0
    )
    second = _scene(
        repository, store, label="second", when="2026-09-01T10:00:00+00:00", phase=0.7, radius=2.4
    )
    _write_pose_receipt(repository, store, anchor)
    place_id = uuid.uuid4()
    establish_place(repository, place_id=place_id, anchor_scene_id=anchor.scene_id)
    executor = JointColmap({})

    with pytest.raises(PlaceAlignmentUnavailable, match="no retained pose receipt"):
        _build(
            repository,
            store,
            tmp_path,
            place_id=place_id,
            candidate=second.scene_id,
            against=anchor.scene_id,
            executor=executor,
        )

    assert executor.calls == [], "a scene with no receipt still reached the reconstruction"
    assert _rows(repository, "place_alignment", place_id=place_id) == []
    assert [row["scene_id"] for row in _rows(repository, "place_version", place_id=place_id)] == [
        anchor.scene_id
    ]


def test_capture_sets_that_do_not_land_in_one_model_refuse_rather_than_fitting_what_did(
    repository, tmp_path, world
):
    """The check that only means something once each frame carries its ORIGIN capture set.

    ``pose.py`` has always refused a run whose declared capture sets do not all appear in one
    connected model, and the ingest layer has always stamped one constant set on every frame, so
    the check has never had two sets to compare. Here the anchor's photographs and the
    candidate's carry different sets, and a model holding only one of them is disconnected even
    though every camera in it is internally consistent and would fit beautifully on its own.
    """
    store, place_id, anchor, second = world
    # Every photograph registers. They register in TWO models, which is the case a residual
    # cannot see: the chosen model holds the anchor's sixteen cameras and fits them perfectly,
    # while the candidate's ten sit in a second component with a frame of their own.
    outcome = _build(
        repository,
        store,
        tmp_path,
        place_id=place_id,
        candidate=second.scene_id,
        against=anchor.scene_id,
        executor=JointColmap(
            anchor.joint(_JOINT_FROM_ANCHOR),
            aside=second.joint(_JOINT_FROM_SECOND, only=10),
        ),
    )
    assert outcome.reason == "place-alignment-not-connected"
    receipt_id = _rows(repository, "place_alignment", place_id=place_id)[0]["receipt_artifact_id"]
    artifact = _rows(repository, "artifact", artifact_id=receipt_id)[0]
    receipt = _receipt(store, artifact)
    assert receipt["fits"]["candidate"]["reason"] == "place-alignment-not-connected"
    assert receipt["fits"]["against"]["reason"] == "place-alignment-not-connected"


def test_a_scene_admitted_against_a_non_anchor_version_records_two_hops(
    repository, tmp_path, world
):
    """``frame_hops`` is the honesty column, and this is the case it exists for.

    The third capture's frame was never jointly reconstructed with the anchor. Its transform is
    the product of two measurements, and without this column a reader would take that composition
    for a measurement. The product is also asserted, because a build that composed in the wrong
    order, or forgot to invert the against side, would still write a 2 here.
    """
    store, place_id, anchor, second = world
    first = _build(
        repository,
        store,
        tmp_path,
        place_id=place_id,
        candidate=second.scene_id,
        against=anchor.scene_id,
        executor=JointColmap(
            {
                **anchor.joint(_JOINT_FROM_ANCHOR),
                **second.joint(_compose(_JOINT_FROM_ANCHOR, _ANCHOR_FROM_SECOND)),
            }
        ),
    )
    assert first.accepted is True, first.reason

    third = _scene(
        repository, store, label="third", when="2026-09-20T10:00:00+00:00", phase=1.9, radius=3.3
    )
    _write_pose_receipt(repository, store, third)
    outcome = _build(
        repository,
        store,
        tmp_path,
        place_id=place_id,
        candidate=third.scene_id,
        against=second.scene_id,
        executor=JointColmap(
            {
                **second.joint(_JOINT_FROM_SECOND),
                **third.joint(_compose(_JOINT_FROM_SECOND, _SECOND_FROM_THIRD)),
            }
        ),
    )

    assert outcome.accepted is True, outcome.reason
    assert outcome.frame_hops == 2

    versions = {
        row["scene_id"]: row for row in _rows(repository, "place_version", place_id=place_id)
    }
    assert versions[third.scene_id]["frame_hops"] == 2
    assert versions[third.scene_id]["ordinal"] == 2

    artifact = _rows(repository, "artifact", artifact_id=outcome.receipt_artifact_id)[0]
    receipt = _receipt(store, artifact)
    expected = _compose(_ANCHOR_FROM_SECOND, _SECOND_FROM_THIRD)
    for measured, truth in zip(receipt["place_from_candidate_row_major"], expected, strict=True):
        assert measured == pytest.approx(truth, abs=1e-6)
    assert receipt["candidate_units_to_place_units"] == pytest.approx(0.8 * 1.25, rel=1e-6)
