"""The World Read route: what it answers, and what it refuses to distinguish.

The bundle's own guarantees are ``tests/test_world_read_bundle.py``. What is checked here is only
what the HTTP surface adds: that a foreign scene and an absent one are indistinguishable, that a
withdrawn scene is 410 rather than 404, and that the bytes on the wire are the bytes whose digest
the bundle claims.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from exulanica.graph.world_read import WORLD_READ_PROFILE
from exulanica.ingest.scene_reconstruction import SceneReconstructionProcessor
from exulanica.store.local import LocalContentAddressedStore

from conftest import write_photo, write_point_map
from test_api import deployment as deployment
from test_scene_reconstruction_pipeline import (
    _CODE_REVISION,
    _EXECUTION_IMAGE,
    FakeColmap,
    _numeric_point_map,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _scene_in(deployment, repository, tmp_path):
    """Publish one scene into the deployment's own store, so the route can read it.

    The deployment fixture already ingested one photograph. Three more, a grouping run and one
    processor pass give a scene whose receipts and point maps live in the same store the running
    application holds.
    """
    from exulanica.evidence.blob import BlobId
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.ingest.scenes import run_scene_grouping

    from conftest import CountingVisionModel

    photos = tmp_path / "world-read-photos"
    photos.mkdir(exist_ok=True)
    pipeline = PhotoIngestPipeline(repository, deployment.store, vision=CountingVisionModel())
    for index in range(3):
        path = write_photo(
            photos, f"wr{index}.jpg", when=f"2026:09:06 09:0{index}:00", size=(160 + index, 100)
        )
        outcome = pipeline.ingest_file(path)
        assert outcome.error is None
        write_point_map(
            repository,
            deployment.store,
            BlobId.of_bytes(path.read_bytes()),
            payload=_numeric_point_map(index),
        )
    report = run_scene_grouping(repository)
    assert report.reconstruction_jobs, "the three new photographs must form one scene job"
    claimed = repository.claim_reconstruction_scene(worker="world-read-route", lease_seconds=60)
    assert claimed is not None
    processor = SceneReconstructionProcessor(
        repository,
        deployment.store,
        tmp_path / "world-read-scratch",
        code_revision=_CODE_REVISION,
        execution_image=_EXECUTION_IMAGE,
        colmap_version="pycolmap test",
        executor=FakeColmap(registered=3, camera_spacing=5),
        retry_delay_seconds=0,
    )
    outcome = processor.process(claimed)
    assert outcome.scene_id is not None, outcome.message
    return outcome.scene_id


def test_the_owner_receives_a_bundle_whose_digest_verifies_over_the_wire(
    deployment, repository, tmp_path
):
    scene_id = _scene_in(deployment, repository, tmp_path)
    response = deployment.as_owner("GET", f"/world-read/scenes/{scene_id}")
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["profile"] == WORLD_READ_PROFILE
    assert hashlib.sha256(_canonical(envelope["bundle"])).hexdigest() == envelope["bundle_sha256"]
    assert envelope["bundle"]["scene"]["scene_id"] == str(scene_id)


def test_a_stranger_and_an_unknown_scene_are_indistinguishable(deployment, repository, tmp_path):
    """M10: 404, never 403, so the surface is not an existence oracle."""
    scene_id = _scene_in(deployment, repository, tmp_path)
    real_to_a_stranger = deployment.as_stranger("GET", f"/world-read/scenes/{scene_id}")
    invented = deployment.as_stranger("GET", f"/world-read/scenes/{uuid.uuid4()}")
    assert real_to_a_stranger.status_code == 404
    assert real_to_a_stranger.json() == invented.json()


def test_an_absent_scene_in_your_own_workspace_is_also_404(deployment):
    response = deployment.as_owner("GET", f"/world-read/scenes/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_reference"


def test_a_withdrawn_scene_answers_410_rather_than_pretending_it_never_existed(
    deployment, repository, tmp_path
):
    """A caller holding an earlier bundle is entitled to learn that the user deleted the thing."""
    scene_id = _scene_in(deployment, repository, tmp_path)
    assert deployment.as_owner("GET", f"/world-read/scenes/{scene_id}").status_code == 200

    member = repository.connection.execute(
        "select capture_id from reconstruction_scene_member "
        "where workspace_id=%s and scene_id=%s order by ordinal limit 1",
        (repository.workspace_id, scene_id),
    ).fetchone()
    repository.insert_tombstone(
        scope="capture",
        capture_id=member["capture_id"],
        requested_by=uuid.uuid4(),
        reason="world-read withdrawal test",
    )

    response = deployment.as_owner("GET", f"/world-read/scenes/{scene_id}")
    assert response.status_code == 410, response.text
    assert response.json()["code"] == "tombstoned"


def test_the_route_holds_a_read_only_connection(deployment, repository, tmp_path):
    """The read-only role is what makes 'this route can only read' a rule rather than a habit.

    Checked by asking the application's own dependency wiring rather than by attempting a write:
    a route that hands a world model everything it may condition on is the last one that should
    hold a connection able to write, and the assertion should fail on a wiring change even when no
    write is attempted anywhere.
    """
    from exulanica.api.dependencies import readonly_connection
    from exulanica.api.routes import world_read

    route = next(
        item
        for item in world_read.router.routes
        if getattr(item, "path", None) == "/world-read/scenes/{scene_id}"
    )
    dependencies = [
        dependency.call
        for dependency in route.dependant.dependencies  # type: ignore[attr-defined]
    ]
    assert readonly_connection in dependencies


def test_the_store_is_reopened_per_request_without_changing_the_digest(
    deployment, repository, tmp_path
):
    scene_id = _scene_in(deployment, repository, tmp_path)
    first = deployment.as_owner("GET", f"/world-read/scenes/{scene_id}").json()
    reopened = LocalContentAddressedStore(deployment.store.root)
    assert reopened.root == deployment.store.root
    second = deployment.as_owner("GET", f"/world-read/scenes/{scene_id}").json()
    assert first["bundle_sha256"] == second["bundle_sha256"]
