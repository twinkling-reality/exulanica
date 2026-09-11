"""The World Read route: what it answers, and what it refuses to distinguish.

The bundle's own guarantees are ``tests/test_world_read_bundle.py``. What is checked here is only
what the HTTP surface adds: that a foreign scene and an absent one are indistinguishable, that a
withdrawn scene is 410 rather than 404, and that the bytes on the wire are the bytes whose digest
the bundle claims.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid

from exulanica.graph.world_read import WORLD_READ_PROFILE
from exulanica.ingest.scene_reconstruction import SceneReconstructionProcessor

from conftest import write_photo, write_point_map
from test_api import deployment as deployment
from test_place_read_bundle import FIRST, _bind, _second_scene
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


def test_two_requests_for_an_unchanged_scene_return_the_same_digest(
    deployment, repository, tmp_path
):
    """Determinism across requests, which is what makes the digest worth quoting to anybody.

    The first version of this test constructed a second store object and asserted its root, which
    is a fact about the constructor and not about the route. This asks the route twice.
    """
    scene_id = _scene_in(deployment, repository, tmp_path)
    first = deployment.as_owner("GET", f"/world-read/scenes/{scene_id}").json()
    second = deployment.as_owner("GET", f"/world-read/scenes/{scene_id}").json()
    assert first["bundle_sha256"] == second["bundle_sha256"]
    assert first == second


def test_a_scene_whose_geometry_bytes_vanish_returns_a_different_digest(
    deployment, repository, tmp_path
):
    """And the digest must move when the world does, or determinism is just a constant."""
    from exulanica.evidence.blob import BlobId

    scene_id = _scene_in(deployment, repository, tmp_path)
    before = deployment.as_owner("GET", f"/world-read/scenes/{scene_id}").json()
    entries = before["bundle"]["geometry"]
    assert entries, "the fixture publishes geometry; without it this test cannot fire"
    for entry in entries:
        path = deployment.store.root / deployment.store.key_for(
            BlobId.from_hex(entry["content_sha256"])
        )
        path.unlink(missing_ok=True)

    after = deployment.as_owner("GET", f"/world-read/scenes/{scene_id}").json()
    assert after["bundle_sha256"] != before["bundle_sha256"]
    assert after["bundle"]["scene"]["placement_state"] != "available"


def _place_in(deployment, repository, tmp_path):
    """One place over two published scenes, inside the deployment's own workspace and store."""
    first = _scene_in(deployment, repository, tmp_path)
    _captures, second = _second_scene(repository, deployment.store, tmp_path)
    return first, second, _bind(repository, deployment.store, first, second)


def test_a_place_addressed_between_two_captures_serves_the_earlier_one_over_the_wire(
    deployment, repository, tmp_path
):
    """The route's half of the resolution rule, checked on the bytes a caller actually receives.

    The bundle's own tests resolve in process. What this adds is that the resolved scene survives
    serialisation and that the digest still verifies over the wire, because a place address that
    produced an unverifiable bundle would be a new way to hand a model something it cannot check.
    """
    first, _second, place = _place_in(deployment, repository, tmp_path)
    between = (FIRST + dt.timedelta(days=10)).isoformat()
    response = deployment.as_owner(
        "GET", f"/world-read/places/{place.place_id}", params={"at": between}
    )
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["bundle"]["scene"]["scene_id"] == str(first)
    assert envelope["bundle"]["addressing"]["place"]["version_ordinal"] == 0
    assert hashlib.sha256(_canonical(envelope["bundle"])).hexdigest() == envelope["bundle_sha256"]


def test_a_place_addressed_before_its_first_capture_is_200_rather_than_404(
    deployment, repository, tmp_path
):
    """A place that exists must not be reported as missing because the caller asked too early.

    404 is the answer for an id that names nothing. Using it here would tell a caller holding a
    real place id that their id is wrong, and the correct fact, that this place has nothing
    recorded that early, would be unreachable from the surface.
    """
    _first, _second, place = _place_in(deployment, repository, tmp_path)
    early = (FIRST - dt.timedelta(days=30)).isoformat()
    response = deployment.as_owner(
        "GET", f"/world-read/places/{place.place_id}", params={"at": early}
    )
    assert response.status_code == 200, response.text
    bundle = response.json()["bundle"]
    assert bundle["addressing"]["place"]["state"] == "no_version_at_that_time"
    assert "scene" not in bundle
    assert bundle["place"]["version_count"] == 2


def test_a_place_with_no_anchor_is_neither_missing_nor_deleted(deployment, repository, tmp_path):
    """Three states share one guard, and collapsing them tells the caller the wrong thing.

    ``tombstone_blocks_place`` fails closed on a place with no anchor and on one whose anchor was
    withdrawn. Both make the bundle unreadable and they are different facts: nobody has aligned
    this place yet, versus somebody deleted the photographs its frame came from. 404 for either
    would deny a place the caller can see in their own library.
    """
    place_id = repository.connection.execute(
        "insert into place (workspace_id) values (%s) returning place_id",
        (repository.workspace_id,),
    ).fetchone()["place_id"]
    response = deployment.as_owner("GET", f"/world-read/places/{place_id}")
    assert response.status_code == 424, response.text
    assert response.json()["code"] == "place_without_anchor"


def test_a_withdrawn_anchor_answers_410_rather_than_pretending_the_place_never_existed(
    deployment, repository, tmp_path
):
    """A caller holding an earlier place bundle is entitled to learn that the user deleted it."""
    first, _second, place = _place_in(deployment, repository, tmp_path)
    assert deployment.as_owner("GET", f"/world-read/places/{place.place_id}").status_code == 200
    member = repository.connection.execute(
        "select capture_id from reconstruction_scene_member "
        "where workspace_id=%s and scene_id=%s order by ordinal limit 1",
        (repository.workspace_id, first),
    ).fetchone()
    repository.insert_tombstone(
        scope="capture",
        capture_id=member["capture_id"],
        requested_by=uuid.uuid4(),
        reason="place route withdrawal test",
    )
    response = deployment.as_owner("GET", f"/world-read/places/{place.place_id}")
    assert response.status_code == 410, response.text
    assert response.json()["code"] == "tombstoned"


def test_a_stranger_and_an_unknown_place_are_indistinguishable(deployment, repository, tmp_path):
    """M10 again, on the new address. A 403 here would confirm the place belongs to somebody."""
    _first, _second, place = _place_in(deployment, repository, tmp_path)
    real_to_a_stranger = deployment.as_stranger("GET", f"/world-read/places/{place.place_id}")
    invented = deployment.as_stranger("GET", f"/world-read/places/{uuid.uuid4()}")
    assert real_to_a_stranger.status_code == 404
    assert real_to_a_stranger.json() == invented.json()


def test_a_time_with_no_zone_is_refused_rather_than_read_as_utc(deployment, repository, tmp_path):
    """An assumed zone is an hour that goes missing without anybody being told.

    The column is UTC and the caller's naive string is not, so the two can differ by any offset
    on earth. Refusing costs the caller one character and removes a class of silently wrong
    answers where a place resolves to the version before the one they meant.
    """
    _first, _second, place = _place_in(deployment, repository, tmp_path)
    response = deployment.as_owner(
        "GET", f"/world-read/places/{place.place_id}", params={"at": "2026-09-20T12:00:00"}
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "unzoned_time"


def test_a_bounded_observation_request_says_it_was_bounded_and_what_it_left(
    deployment, repository, tmp_path
):
    """A page that reads as the whole graph is the failure; a client counting it undercounts.

    The unbounded answer is unchanged and still the default, so this asks for both and compares
    them: the page has to be smaller, say so, name the total it came from, and carry a cursor
    that reaches the rest.
    """
    scene_id = _scene_in(deployment, repository, tmp_path)
    whole = deployment.as_owner("GET", f"/world-read/scenes/{scene_id}/observations")
    assert whole.status_code == 200, whole.text
    complete = whole.json()
    assert complete["bounds"]["state"] == "complete"
    assert complete["bounds"]["point_count_not_returned"] == 0
    assert complete["bounds"]["next_point_id"] is None
    total = complete["bounds"]["point_count_total"]
    assert total > 1, "a one-point scene cannot demonstrate a page"

    first_page = deployment.as_owner(
        "GET", f"/world-read/scenes/{scene_id}/observations", params={"limit": 1}
    ).json()
    assert first_page["bounds"]["state"] == "page"
    assert first_page["point_count"] == 1
    assert first_page["bounds"]["point_count_total"] == total
    assert first_page["bounds"]["point_count_not_returned"] == total - 1
    assert f"1 of the {total} points" in first_page["bounds"]["note"]
    assert len(json.dumps(first_page)) < len(json.dumps(complete))

    # The cursor reaches the rest, and the walk returns every point exactly once. A cursor that
    # repeated or skipped a point would let a client assemble a graph the scene never observed.
    walked = list(first_page["points"])
    cursor = first_page["bounds"]["next_point_id"]
    while cursor is not None:
        page = deployment.as_owner(
            "GET",
            f"/world-read/scenes/{scene_id}/observations",
            params={"limit": 2, "after_point_id": cursor},
        ).json()
        walked.extend(page["points"])
        cursor = page["bounds"]["next_point_id"]
    assert [point["point_id"] for point in walked] == [
        point["point_id"] for point in complete["points"]
    ]


# -- the inspector's reads: a summary and one resolved click -----------------------------------

#: What one resolved click may weigh on the wire, as a header plus at most one observation per
#: scene photograph, each carrying that photograph's consent record. The answer holds one point,
#: so the point count is absent from the bound on purpose. MEASURED 2026-09-11 on the frozen
#: volcanic copy: a miss is 1,784 bytes and a hit adds 1,160 to 1,190 per observation it lists
#: (11,277 bytes for eight, 92,547 for seventy-eight).
_RESOLVE_HEADER_BUDGET = 2_560
_RESOLVE_PER_PHOTOGRAPH_BUDGET = 1_536
#: Counts and three sentences. MEASURED 2026-09-11 on the same copy: 781 bytes.
_SUMMARY_BUDGET = 1_024


def _members(repository, scene_id) -> list[uuid.UUID]:
    return [
        row["capture_id"]
        for row in repository.connection.execute(
            "select capture_id from reconstruction_scene_member "
            "where workspace_id=%s and scene_id=%s order by ordinal",
            (repository.workspace_id, scene_id),
        ).fetchall()
    ]


def test_what_the_inspector_reads_stays_within_budget_however_many_points_the_scene_holds(
    deployment, repository, tmp_path
):
    """The size budget, held on the wire, on a synthetic scene inflated until its graph is large.

    The fixture's receipt is rewritten so every photograph holds its full retained sample of 4096
    observations, and every added point is observed by every photograph, which is the heaviest a
    single point's answer can be. One of them sits straight ahead of the first camera, nearer than
    anything else, so a click on the principal point has exactly one right answer.

    The whole graph grows with the points and a resolved click does not. That is the property the
    inspector needed: on the volcanic scene the graph is 1,015,016,928 bytes, more than a browser
    can hold as one string, and the answer to one click is kilobytes.
    """
    from test_scene_observations import _pose_receipt_bytes, _replace_pose_receipt

    scene_id = _scene_in(deployment, repository, tmp_path)
    route = f"/world-read/scenes/{scene_id}/observations"
    before = deployment.as_owner("GET", route)
    assert before.status_code == 200, before.text

    receipt = json.loads(_pose_receipt_bytes(repository, scene_id, deployment.store))
    frames = {frame["filename"]: frame["capture_ref"] for frame in receipt["manifest"]["frames"]}
    cameras = receipt["quality"]["cameras"]
    first = cameras[0]
    # FakeColmap poses every camera with the identity rotation, which is what lets the probe be
    # placed by hand. Asserted, so a fixture that changes cannot silently move the probe.
    assert first["quaternion_wxyz"] == [1, 0, 0, 0]
    assert first["calibration"]["model"] == "PINHOLE"
    tx, ty, tz = first["translation_xyz"]
    _fx, _fy, cx, cy = first["calibration"]["parameters"]
    room = 4096 - max(len(camera["sparse_observations"]) for camera in cameras) - 1
    added = [(10_000_000 + k, (k * 0.01, 1.0, 400.0)) for k in range(room)]
    # COLMAP maps world to camera as x + t here, so this is ten units straight ahead of camera 1.
    probe = (9_999_999, (-tx, -ty, -tz + 10.0))
    for camera in cameras:
        camera["sparse_observations"].extend(
            [point_id, 1.0, 1.0, *world, 0.4, len(cameras)] for point_id, world in [probe, *added]
        )
    receipt["quality_digest"] = hashlib.sha256(
        json.dumps(
            receipt["quality"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    _replace_pose_receipt(repository, scene_id, deployment.store, receipt)

    members = len(frames)
    budget = _RESOLVE_HEADER_BUDGET + _RESOLVE_PER_PHOTOGRAPH_BUDGET * members
    whole = deployment.as_owner("GET", route)
    assert whole.status_code == 200, whole.text
    assert whole.json()["bounds"]["point_count_total"] >= room
    assert len(whole.content) > 10 * len(before.content)
    assert len(whole.content) > 100 * budget, (len(whole.content), budget)

    summary = deployment.as_owner("GET", f"{route}/summary")
    assert summary.status_code == 200, summary.text
    assert len(summary.content) <= _SUMMARY_BUDGET, len(summary.content)
    assert summary.json()["point_count_total"] == whole.json()["bounds"]["point_count_total"]
    assert summary.headers["cache-control"] == "private, no-store"

    capture = frames[first["image_name"]]
    hit = deployment.as_owner(
        "GET",
        f"{route}/resolve",
        params={
            "capture_id": capture,
            "u": cx,
            "v": cy,
            "tolerance_px": 0.5,
            "occlusion_band_px": 0,
        },
    )
    assert hit.status_code == 200, hit.text
    answer = hit.json()
    assert answer["state"] == "hit"
    assert answer["point"]["point_id"] == probe[0]
    assert answer["point"]["observations_retained"] == members
    assert len(hit.content) <= budget, (len(hit.content), budget)
    assert hit.headers["cache-control"] == "private, no-store"

    miss = deployment.as_owner(
        "GET", f"{route}/resolve", params={"capture_id": capture, "u": -5000, "v": -5000}
    )
    assert miss.status_code == 200, miss.text
    assert miss.json()["state"] == "miss"
    assert len(miss.content) <= _RESOLVE_HEADER_BUDGET, len(miss.content)


def test_a_stranger_learns_nothing_from_the_inspectors_reads(deployment, repository, tmp_path):
    """M10 on both new addresses: a real scene and an invented one answer the same 404."""
    scene_id = _scene_in(deployment, repository, tmp_path)
    capture = str(_members(repository, scene_id)[0])
    for suffix, params in (("summary", {}), ("resolve", {"capture_id": capture, "u": 80, "v": 50})):
        owner = deployment.as_owner(
            "GET", f"/world-read/scenes/{scene_id}/observations/{suffix}", params=params
        )
        assert owner.status_code == 200, owner.text
        real = deployment.as_stranger(
            "GET", f"/world-read/scenes/{scene_id}/observations/{suffix}", params=params
        )
        invented = deployment.as_stranger(
            "GET", f"/world-read/scenes/{uuid.uuid4()}/observations/{suffix}", params=params
        )
        assert real.status_code == invented.status_code == 404
        assert real.json() == invented.json()


def test_a_photograph_outside_the_scene_is_named_as_the_problem(deployment, repository, tmp_path):
    """The scene is the caller's and readable, so "no observation graph" would be the wrong 404."""
    scene_id = _scene_in(deployment, repository, tmp_path)
    response = deployment.as_owner(
        "GET",
        f"/world-read/scenes/{scene_id}/observations/resolve",
        params={"capture_id": str(uuid.uuid4()), "u": 80, "v": 50},
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "unknown_view"


def test_a_cursor_the_resolve_cannot_honestly_answer_is_refused(deployment, repository, tmp_path):
    scene_id = _scene_in(deployment, repository, tmp_path)
    capture = str(_members(repository, scene_id)[0])
    for params in (
        {"u": "nan", "v": 50},
        {"u": 80, "v": "inf"},
        {"u": 80, "v": 50, "tolerance_px": 0},
        {"u": 80, "v": 50, "tolerance_px": 5000},
        {"u": 80, "v": 50, "occlusion_band_px": -1},
    ):
        response = deployment.as_owner(
            "GET",
            f"/world-read/scenes/{scene_id}/observations/resolve",
            params={"capture_id": capture} | params,
        )
        assert response.status_code == 422, (params, response.text)


def test_a_withdrawn_scene_answers_410_to_the_inspectors_reads_too(
    deployment, repository, tmp_path
):
    scene_id = _scene_in(deployment, repository, tmp_path)
    members = _members(repository, scene_id)
    route = f"/world-read/scenes/{scene_id}/observations"
    params = {"capture_id": str(members[1]), "u": 80, "v": 50}
    assert deployment.as_owner("GET", f"{route}/resolve", params=params).status_code == 200
    repository.insert_tombstone(
        scope="capture",
        capture_id=members[0],
        requested_by=uuid.uuid4(),
        reason="inspector reads withdrawal test",
    )
    for response in (
        deployment.as_owner("GET", f"{route}/summary"),
        deployment.as_owner("GET", f"{route}/resolve", params=params),
    ):
        assert response.status_code == 410, response.text
        assert response.json()["code"] == "tombstoned"
