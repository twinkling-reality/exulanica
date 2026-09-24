"""The standpoint stage and the graph's reading of it, over scenes pose placed nothing.

The photographs are renders of one procedural room (``standpoint_fixtures``) from one standpoint,
ingested through the pipeline as JPEGs, with the point maps the depth stage would make of them.
Pose is COLMAP's test double registering nothing, which is what a real pose run does with
photographs taken from one spot. The join runs COLMAP's real SIFT.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import uuid
from pathlib import Path

import pytest

#: numpy and scipy arrive with the `reconstruction` extra, which a plain `uv sync` does not install,
#: and the join and its fixtures import both; unguarded, one import stops the whole collection.
pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)
pytest.importorskip(
    "scipy", reason="scipy is absent; install it with `uv sync --extra reconstruction`"
)

import numpy as np
from exulanica.api.routes.graph import withhold_scene_geometry
from exulanica.evidence.blob import BlobId
from exulanica.graph import read_snapshot
from exulanica.graph.reconstruction_scenes import clear_placement_memo
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.scene_worker import SceneReconstructionWorker
from exulanica.ingest.scenes import run_scene_grouping
from exulanica.ingest.stages import stage
from exulanica.ingest.standpoint_scenes import publish_standpoint_scene, scenes_due_standpoint
from exulanica.reconstruction.standpoint import StandpointPolicy
from exulanica.reconstruction.standpoint_features import PycolmapSift
from exulanica.reconstruction.standpoint_record import parse_standpoint_record
from exulanica.store.local import LocalContentAddressedStore
from PIL import Image

from conftest import CountingVisionModel, write_point_map
from standpoint_fixtures import Camera, Room, focal_35mm, fov_y_for_focal_35mm, photograph
from test_scene_reconstruction_pipeline import (
    _CODE_REVISION,
    _EXECUTION_IMAGE,
    FakeColmap,
    _processor,
)

#: Three photographs turned on one spot, each overlapping both others.
#: A phone's 24 mm equivalent, which EXIF states exactly: rounding is measured by the evaluation,
#: not here, where what is under test is the pipeline around the join.
_FOV = fov_y_for_focal_35mm(24)
CAMERAS = (
    Camera(0, 0, fov_y_deg=_FOV),
    Camera(-22, 4, fov_y_deg=_FOV),
    Camera(-44, -2, fov_y_deg=_FOV),
)
#: Under half a pixel of the room's photographs; see test_standpoint_method.py.
ROTATION_TOLERANCE_DEG = 0.2

POLICY = StandpointPolicy.from_params(stage("scene_standpoint").params)


@pytest.fixture(scope="module")
def extractor() -> PycolmapSift:
    return PycolmapSift(
        max_features=POLICY.max_features,
        peak_threshold=POLICY.peak_threshold,
        threads=POLICY.feature_threads,
    )


def _jpeg(image: Image.Image, when: str, focal_35mm_film: int | None) -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 1
    exif[0x010F] = "TestCam"
    exif[0x0110] = "Standpoint"
    exif.get_ifd(0x8769)[0x9003] = when
    if focal_35mm_film is not None:
        # FocalLengthIn35mmFilm, a whole number of millimetres as a phone writes it.
        exif.get_ifd(0x8769)[0xA405] = focal_35mm_film
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=95, exif=exif)
    return out.getvalue()


def _unplaced_scene(
    repository, tmp_path: Path, *, registered: int = 0, unstated: frozenset[int] = frozenset()
):
    """Three photographs of the room from one spot, grouped, and built with nobody registered.

    Each states its lens's focal length, except the ones named in ``unstated``.
    """
    store = LocalContentAddressedStore(tmp_path / "store")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    captures: list[uuid.UUID] = []
    point_maps: list[uuid.UUID] = []
    for index, camera in enumerate(CAMERAS):
        image, point_map = photograph(Room(), camera)
        path = tmp_path / f"{index}.jpg"
        focal = None if index in unstated else round(focal_35mm(camera))
        path.write_bytes(_jpeg(image, f"2026:09:23 12:0{index}:00", focal))
        outcome = pipeline.ingest_file(path)
        assert outcome.error is None and outcome.capture_id is not None
        captures.append(outcome.capture_id)
        artifact, _ = write_point_map(
            repository, store, BlobId.of_bytes(path.read_bytes()), payload=point_map
        )
        point_maps.append(artifact)
    assert len(run_scene_grouping(repository).reconstruction_jobs) == 1
    claimed = repository.claim_reconstruction_scene(worker="test", lease_seconds=60)
    assert claimed is not None
    outcome = _processor(repository, store, tmp_path, FakeColmap(registered=registered)).process(
        claimed
    )
    assert outcome.status == "succeeded"
    return store, captures, point_maps, outcome.scene_id


def _scene(repository, store):
    clear_placement_memo()
    [scene] = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes
    return scene


def _standpoint_rows(repository, scene_id):
    return repository.connection.execute(
        "select artifact_id, content_sha256, stage_key from artifact "
        "where workspace_id=%s and scene_id=%s and kind='standpoint_scene' order by created_at",
        (repository.workspace_id, scene_id),
    ).fetchall()


def _angle_deg(rotation: np.ndarray) -> float:
    skew = np.array(
        [
            rotation[2, 1] - rotation[1, 2],
            rotation[0, 2] - rotation[2, 0],
            rotation[1, 0] - rotation[0, 1],
        ]
    )
    return math.degrees(math.atan2(np.linalg.norm(skew) / 2, (np.trace(rotation) - 1) / 2))


def test_an_unplaced_scene_is_joined_and_the_graph_serves_the_measured_arrangement(
    repository, tmp_path, extractor
):
    store, captures, _maps, scene_id = _unplaced_scene(repository, tmp_path)
    before = _scene(repository, store)
    assert before.standpoint is None
    assert all(member.standpoint_placement is None for member in before.members)
    [due] = scenes_due_standpoint(repository, store, extractor_identity=extractor.identity)
    assert due.scene_id == scene_id

    result = publish_standpoint_scene(repository, store, scene_id, extractor=extractor)

    assert result["action"] == "written", result
    assert result["joined"] == 3 and result["refusal"] is None
    [row] = _standpoint_rows(repository, scene_id)
    assert row["stage_key"] == "scene_standpoint"
    record = parse_standpoint_record(store.get(BlobId(bytes(row["content_sha256"]))))
    assert [member.member_ref for member in record.members] == [str(c) for c in captures]

    scene = _scene(repository, store)
    assert scene.standpoint is not None and scene.standpoint.state == "joined"
    assert scene.standpoint.joined_member_count == 3 and scene.standpoint.excluded == []
    assert scene.standpoint.reference_capture_id == captures[0]
    assert scene.rendering_substrate == "unposed_point_maps" and scene.displayed_rung == 3
    assert scene.recorded_rung == 4, "the recorded rung is the gate's and is not changed"
    assert any("joined where they were taken" in reason for reason in scene.display_reasons)
    assert not any("not measured" in reason for reason in scene.display_reasons)
    matrices = {}
    for member in scene.members:
        assert (
            member.unposed_point_map is not None and member.unposed_point_map.state == "available"
        )
        placement = member.standpoint_placement
        assert placement is not None and len(placement.scene_from_opm_row_major) == 16
        matrix = np.array(placement.scene_from_opm_row_major).reshape(4, 4)
        assert np.allclose(matrix[:3, 3], 0.0), "every camera stands at the standpoint"
        linear = matrix[:3, :3]
        rotation = linear / np.linalg.norm(linear, axis=0)
        matrices[member.ordinal] = rotation
    for a, b in ((0, 1), (1, 2), (0, 2)):
        estimated = matrices[a].T @ matrices[b]
        true = CAMERAS[a].rotation.T @ CAMERAS[b].rotation
        assert _angle_deg(estimated.T @ true) < ROTATION_TOLERANCE_DEG
    assert scenes_due_standpoint(repository, store, extractor_identity=extractor.identity) == []


def test_joining_the_same_scene_again_writes_nothing(repository, tmp_path, extractor):
    store, _captures, _maps, scene_id = _unplaced_scene(repository, tmp_path)
    first = publish_standpoint_scene(repository, store, scene_id, extractor=extractor)
    second = publish_standpoint_scene(repository, store, scene_id, extractor=extractor)
    assert first["action"] == "written"
    assert second["action"] == "already-present"
    assert second["artifact_id"] == first["artifact_id"]
    assert len(_standpoint_rows(repository, scene_id)) == 1


def test_a_member_that_may_no_longer_be_read_withdraws_the_arrangement_until_joined_again(
    repository, tmp_path, extractor
):
    store, captures, maps, scene_id = _unplaced_scene(repository, tmp_path)
    publish_standpoint_scene(repository, store, scene_id, extractor=extractor)
    # asset_point_allows is what a withdrawn depth right, an expired review, a withdrawn person
    # and a lost or repaired artifact all end in; this makes it answer no for one member.
    repository.mark_artifact_needs_repair(maps[1])

    scene = _scene(repository, store)
    assert scene.standpoint is not None and scene.standpoint.state == "withdrawn"
    assert all(member.standpoint_placement is None for member in scene.members)
    assert any("withheld until it is joined again" in r for r in scene.display_reasons)

    [due] = scenes_due_standpoint(repository, store, extractor_identity=extractor.identity)
    assert due.scene_id == scene_id
    again = publish_standpoint_scene(repository, store, scene_id, extractor=extractor)
    assert again["action"] == "written" and again["not_permitted"] == 1
    [_, newest] = _standpoint_rows(repository, scene_id)
    record = parse_standpoint_record(store.get(BlobId(bytes(newest["content_sha256"]))))
    assert record.members[1].outcome == "not_permitted"
    assert record.members[1].reading is None and record.members[1].point_map_artifact_ref is None

    rejoined = _scene(repository, store)
    assert rejoined.standpoint is not None and rejoined.standpoint.state == "joined"
    assert rejoined.standpoint.joined_member_count == 2
    assert [item.capture_id for item in rejoined.standpoint.excluded] == [captures[1]]
    assert rejoined.standpoint.excluded[0].reason == "not_permitted"
    assert rejoined.members[1].standpoint_placement is None


def test_a_scene_pose_placed_is_never_joined(repository, tmp_path, extractor):
    store, _captures, _maps, scene_id = _unplaced_scene(repository, tmp_path, registered=2)
    assert scenes_due_standpoint(repository, store, extractor_identity=extractor.identity) == []
    result = publish_standpoint_scene(repository, store, scene_id, extractor=extractor)
    assert result["action"] == "skipped" and "pose placed" in result["reason"]
    assert _standpoint_rows(repository, scene_id) == []


def test_a_permission_that_ends_during_the_join_refuses_the_write(
    repository, tmp_path, extractor, monkeypatch
):
    store, _captures, maps, scene_id = _unplaced_scene(repository, tmp_path)
    from exulanica.reconstruction import standpoint as method

    join = method.join_standpoint

    def withdrawn_while_joining(**kwargs):
        record = join(**kwargs)
        repository.mark_artifact_needs_repair(maps[2])
        return record

    # The stage imports the method when it runs, so the patch is what it calls.
    monkeypatch.setattr(method, "join_standpoint", withdrawn_while_joining)

    result = publish_standpoint_scene(repository, store, scene_id, extractor=extractor)

    assert result["action"] == "skipped"
    assert "permission ended while" in result["reason"]
    assert _standpoint_rows(repository, scene_id) == []


def test_deleting_a_member_takes_the_standpoint_with_the_scene(repository, tmp_path, extractor):
    store, captures, _maps, scene_id = _unplaced_scene(repository, tmp_path)
    publish_standpoint_scene(repository, store, scene_id, extractor=extractor)
    [row] = _standpoint_rows(repository, scene_id)

    tombstone = repository.insert_tombstone(
        scope="capture",
        capture_id=captures[0],
        requested_by=uuid.uuid4(),
        reason="the user deleted this photograph",
    )

    queued = repository.connection.execute(
        "select target_ref from purge_job where tombstone_id=%s and target_kind='artifact'",
        (tombstone,),
    ).fetchall()
    # Purge jobs name an artifact's bytes by their content digest, as every scene artifact's do.
    assert bytes(row["content_sha256"]).hex() in {item["target_ref"] for item in queued}
    clear_placement_memo()
    assert (
        read_snapshot(repository.connection, repository.workspace_id, store).reconstruction_scenes
        == []
    )
    result = publish_standpoint_scene(repository, store, scene_id, extractor=extractor)
    assert result["action"] == "skipped"


def test_a_withheld_scene_loses_its_standpoint_with_the_rest_of_its_geometry(
    repository, tmp_path, extractor
):
    store, _captures, _maps, scene_id = _unplaced_scene(repository, tmp_path)
    publish_standpoint_scene(repository, store, scene_id, extractor=extractor)
    scene = _scene(repository, store)
    assert scene.standpoint is not None and scene.standpoint.state == "joined"

    withheld = withhold_scene_geometry(scene)

    assert withheld.standpoint is None
    assert all(member.standpoint_placement is None for member in withheld.members)


class _WorkerDatabase:
    """The scene worker's `Database`, answering every session with this test's own connection."""

    def __init__(self, repository):
        self._repository = repository

    @contextlib.contextmanager
    def session(self, workspace_id):
        assert workspace_id == self._repository.workspace_id
        yield self._repository.connection


def test_the_scene_worker_joins_each_due_scene_once_per_state(repository, tmp_path):
    store, _captures, maps, scene_id = _unplaced_scene(repository, tmp_path)
    worker = SceneReconstructionWorker(
        _WorkerDatabase(repository),
        store,
        tmp_path / "scratch",
        frozenset({repository.workspace_id}),
        name="standpoint-sweep",
        code_revision=_CODE_REVISION,
        execution_image=_EXECUTION_IMAGE,
    )
    [result] = worker.refresh_standpoint_scenes()
    assert result["action"] == "written" and result["scene_id"] == str(scene_id)
    assert worker.refresh_standpoint_scenes() == [], "answered for, so no longer due"
    repository.mark_artifact_needs_repair(maps[0])
    [again] = worker.refresh_standpoint_scenes()
    assert again["action"] == "written" and again["not_permitted"] == 1
    assert json.loads(json.dumps(again))["due"]
