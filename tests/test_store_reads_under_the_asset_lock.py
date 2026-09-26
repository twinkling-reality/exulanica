"""Nothing is read from the object store while the global asset read lock is held.

The lock is exclusive and global: while one transaction holds it, every guarded write in every
workspace is refused and every final read check waits (``docs/asset-read-currency.md``). A writer
takes it for its last question (``lock_asset_reads_until_commit``) and holds it until its
transaction commits, so it reads and checks stored bytes before taking it, answers with what it
wrote without availability, and the caller reads availability after the commit.

Each path below is one a person reaches: adding photographs to a made world, branching a version,
placing and moving an environment piece and a depth estimate, and editing a world whose society
takes inputs, with the society's own authorization when its state is read. Every request runs
through the application as a deployment runs it, connected as a runtime role. The recorder is
shown to see a read under a held lock before an empty record is trusted, and each test shows that
the reads it makes happen, before the lock or after the commit.

What reading before the lock gives up is tested too: bytes lost with no row saying why, between
the read and the last question, no longer refuse a placement, which is written and reads
``unavailable_bytes``; and rows under the lock naming bytes nobody read refuse the request as a
race to be asked again, which neither records an input nor pauses playback.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.api.society_runtime import SocietyRuntime, _ReadFirst
from exulanica.db.read_check import lock_asset_reads_until_commit
from exulanica.deletion.queue import PurgeTarget, mark_purged
from exulanica.evidence.blob import BlobId
from exulanica.ingest.repository import IngestRepository
from exulanica.selection import execute, validate
from exulanica.world import UnavailableAsset, reviewed_assets
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world.society import SocietyBytesNotRead, UnavailableSocietyInput
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_repository import SocietyRepository
from fastapi.testclient import TestClient

import test_society_authored_world_postgres as helpers
import test_society_saved_world_api as saved_api
import test_society_social_postgres as social_helpers
import test_world_arrangements as arrangements
import test_world_environment_composition_postgres as composition
from asset_lock_support import recorded_store_reads
from personal_world_support import (
    CUBE,
    binding,
    group,
    make_world,
    personal_world_api,
    photograph,
    place_object,
    source_media,
)
from society_fixtures import SEED, society_input
from test_personal_world_addition import (
    _add_what_the_read_offers,
    _attach,
    _estimate,
    _place_estimate,
    _placed_environment,
)
from world_package_rich_world import _admit_environment

saved_world = helpers.saved_world
runtime_app = arrangements.runtime_app
objects_api = social_helpers.objects_api
social = social_helpers.social
composed = composition.composed
memory_place = composition.memory_place
pytestmark = pytest.mark.postgres
PILLAR = next(a for a in reviewed_assets() if a.asset_key == "cc0.marker-pillar").content_sha256


@pytest.fixture
def api(tmp_path, repository, spine_schema):
    yield from personal_world_api(tmp_path, repository, spine_schema)


def _made(api) -> tuple[dict, str, uuid.UUID]:
    capture = photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    [region] = {slot["region_id"] for slot in source_media(api, entry)}
    return entry, region, capture


def _reads(api, monkeypatch):
    return recorded_store_reads(
        api.repository.connection,
        api.database,
        api.repository.workspace_id,
        api.store,
        monkeypatch,
        planted=CUBE,
    )


def _asked(reads, function: str) -> bool:
    """Whether any read was asked for with this product function on the stack."""
    return any(function in where.split(" < ") for _, where in reads.every)


# -- a world made from photographs ----------------------------------------------------------------


def test_adding_photographs_checks_the_attached_photograph_only_after_it_commits(api, monkeypatch):
    entry, _, capture = _made(api)
    entry, _ = _attach(api, entry, capture)
    # Positive control: the attached photograph reads available with a viewer image, so reading
    # the entry back checks that image in the store.
    [attachment] = entry["source_attachments"]
    assert attachment["availability"] == "available" and attachment["viewer_sha256"]
    photograph(api, minute=3)
    group(api)
    reads = _reads(api, monkeypatch)
    added = _add_what_the_read_offers(api, entry)
    assert reads.under_the_lock == []
    assert added["parent_version_id"] == entry["authored_version_id"]
    # Reading the entry back after the commit checked the photograph's viewer image.
    assert _asked(reads, "world/saved_entries.py:_attachments")
    [again] = api.entry(entry["entry_id"])["source_attachments"]
    assert again["availability"] == "available"


def test_a_branch_inside_a_callers_transaction_reads_availability_only_after_it_commits(
    api, tmp_path, monkeypatch
):
    entry, region, _ = _made(api)
    entry, _ = _placed_environment(api, entry, region, tmp_path)
    reads = _reads(api, monkeypatch)
    workspace = api.repository.workspace_id
    with api.database.session(workspace) as connection:
        objects = WorldObjectRepository(
            connection, workspace, world_id=entry["world_id"], store=api.store
        )
        seen = len(reads.every)
        with connection.transaction():
            branched = objects.branch_version(
                parent_version_id=uuid.UUID(entry["authored_version_id"]),
                title="Branched inside another write",
                created_by=api.actor,
            )
        assert [i.availability for i in branched.version.environment_instances] == ["unknown"]
        assert reads.every[seen:] == [], "nothing was read from the store inside the branch"
        drawn = objects.with_availability(branched.version)
    assert [i.availability for i in drawn.environment_instances] == ["available"]
    assert drawn.state_sha256 == branched.version.state_sha256
    assert reads.under_the_lock == []
    assert _asked(reads, "world/environment_source_authority.py:_require_bytes")


def test_placing_and_moving_an_environment_piece_reads_nothing_under_the_lock(
    api, tmp_path, monkeypatch
):
    entry, region, _ = _made(api)
    reads = _reads(api, monkeypatch)
    entry, _ = _placed_environment(api, entry, region, tmp_path)
    version = api.version(entry)
    moved = api.post(
        f"/world/versions/{entry['authored_version_id']}/environment-instances/environment:yard"
        f"/move?world_id={entry['world_id']}",
        {
            "base_state_sha256": version["state_sha256"],
            "transform": {
                "x_mm": 250,
                "y_mm": 0,
                "z_mm": 0,
                "yaw_microradians": 0,
                "scale_milli": 1000,
            },
            "saved_entry": binding(api.entry(entry["entry_id"])),
        },
    )
    assert moved.status_code == 200, moved.text
    assert [i["availability"] for i in moved.json()["environment_instances"]] == ["available"]
    assert reads.under_the_lock == []
    # The placement's own checks read the pinned bytes, before the lock.
    assert _asked(reads, "world/environment_source_authority.py:_require_bytes")


def test_placing_and_moving_a_depth_estimate_reads_nothing_under_the_lock(api, monkeypatch):
    entry, region, capture = _made(api)
    entry, reviewed = _attach(api, entry, capture)
    _estimate(api, capture, reviewed)
    reads = _reads(api, monkeypatch)
    placed = _place_estimate(api, entry, region)
    assert placed.status_code == 201, placed.text
    assert [i["availability"] for i in placed.json()["point_map_instances"]] == ["available"]
    workspace = api.repository.workspace_id
    with api.database.session(workspace) as connection:
        objects = WorldObjectRepository(
            connection, workspace, world_id=entry["world_id"], store=api.store
        )
        version_id = uuid.UUID(entry["authored_version_id"])
        moved = objects.move_point_map(
            version_id,
            "point-map:courtyard",
            Transform(1500, 0, -450, 0, 1000),
            base_state_sha256=objects.version(version_id).state_sha256,
            actor=api.actor,
        )
    # What the move wrote, without availability: that is read after the commit.
    assert [i.availability for i in moved.point_map_instances] == ["unknown"]
    assert reads.under_the_lock == []
    assert _asked(reads, "world/point_map_source_authority.py:_read")


def test_an_edit_reads_nothing_after_its_society_hook_takes_the_lock(api, tmp_path, monkeypatch):
    """What an edit reads after its society's hook is read under the lock that hook took.

    ``on_edit`` runs inside the edit's transaction after its row is written, and a society's hook
    takes the asset read lock there. Here a hook that takes only the lock stands in for it, so what
    is recorded is the repository's own reading: a move's final question and what it returns.
    """
    entry, region, capture = _made(api)
    entry, _ = _placed_environment(api, entry, region, tmp_path)
    entry, reviewed = _attach(api, entry, capture)
    _estimate(api, capture, reviewed)
    assert _place_estimate(api, entry, region).status_code == 201
    reads = _reads(api, monkeypatch)
    workspace = api.repository.workspace_id
    version_id = uuid.UUID(entry["authored_version_id"])
    hooked: list[uuid.UUID] = []
    with api.database.session(workspace) as connection:

        def locking_hook(edited: uuid.UUID) -> None:
            hooked.append(edited)
            lock_asset_reads_until_commit(connection, outside="the hook runs inside an edit")

        objects = WorldObjectRepository(
            connection, workspace, world_id=entry["world_id"], store=api.store, on_edit=locking_hook
        )
        for move in (objects.move_environment, objects.move_point_map):
            instance = (
                "environment:yard" if move == objects.move_environment else "point-map:courtyard"
            )
            move(
                version_id,
                instance,
                Transform(900, 0, -300, 0, 1000),
                base_state_sha256=objects.version(version_id).state_sha256,
                actor=api.actor,
            )
    assert hooked == [version_id, version_id], "the hook ran inside both moves"
    assert reads.under_the_lock == []
    # Each move's own current checks read the pinned bytes, before the hook took the lock.
    assert _asked(reads, "world/environment_source_authority.py:_require_bytes")


def test_a_depth_estimate_purged_before_its_last_question_is_refused_by_its_rows(api, monkeypatch):
    """A rows check: a purge the rows record refuses the placement at its last question.

    The product erases a stored estimate only for a purge job, which a committed deletion
    creates, and it records the erasure as it goes (``mark_purged``: destroyed first, recorded
    second). Here both happen inside the placement's own transaction, after its bytes were read
    and before its last question. The artifact's row refuses the estimate before the bytes would
    be asked about at all, so this holds with or without a look at the store; what it shows is
    that the rows asked under the lock see the purge, nothing is written, and nothing is read from
    the store under the lock.
    """
    entry, region, capture = _made(api)
    entry, reviewed = _attach(api, entry, capture)
    _estimate(api, capture, reviewed)
    written = WorldObjectRepository._insert_point_map
    destroyed: list[bytes] = []

    def purged_as_it_is_written(self, version_id, instance, edit_ids):
        written(self, version_id, instance, edit_ids)
        digest = instance.source.point_map_sha256
        stored = api.store.root / api.store.key_for(BlobId.from_hex(digest))
        destroyed.append(stored.read_bytes())
        stored.unlink()
        mark_purged(
            self.connection,
            PurgeTarget(
                purge_id=uuid.uuid4(),
                tombstone_id=uuid.uuid4(),
                workspace_id=self.workspace_id,
                target_kind="artifact",
                target_ref=digest,
                attempts=1,
                requested_by=api.actor,
                reason=None,
                scope="capture",
            ),
        )

    before = api.version(entry)
    reads = _reads(api, monkeypatch)
    monkeypatch.setattr(WorldObjectRepository, "_insert_point_map", purged_as_it_is_written)
    refused = _place_estimate(api, entry, region)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "composition_blocked", refused.json()
    assert reads.under_the_lock == []
    assert refused.json()["detail"] == "depth_not_permitted"
    assert api.version(entry)["state_sha256"] == before["state_sha256"], "nothing was written"
    monkeypatch.undo()
    # Positive control: the purge's row went with the refused transaction; with its bytes put
    # back, the same placement is written.
    [data] = destroyed
    api.store.put_bytes(data)
    assert _place_estimate(api, entry, region).status_code == 201


def test_a_depth_estimate_whose_bytes_vanish_before_its_last_question_is_written_unavailable(
    api, monkeypatch
):
    """The trade reading before the lock makes: bytes lost with no row saying why are not refused.

    The estimate's bytes are read when the placement is resolved, before the lock. If they then
    vanish from the store while every row still allows them, the last question, asked of rows
    alone, lets the placement be written, and it reads ``unavailable_bytes`` from then on, as it
    would had they vanished a moment after the commit.
    """
    entry, region, capture = _made(api)
    entry, reviewed = _attach(api, entry, capture)
    _estimate(api, capture, reviewed)
    written = WorldObjectRepository._insert_point_map
    vanished: list[bytes] = []

    def vanishes_as_it_is_written(self, version_id, instance, edit_ids):
        written(self, version_id, instance, edit_ids)
        stored = api.store.root / api.store.key_for(
            BlobId.from_hex(instance.source.point_map_sha256)
        )
        vanished.append(stored.read_bytes())
        stored.unlink()

    reads = _reads(api, monkeypatch)
    with monkeypatch.context() as patch:
        patch.setattr(WorldObjectRepository, "_insert_point_map", vanishes_as_it_is_written)
        placed = _place_estimate(api, entry, region)
    assert placed.status_code == 201, placed.text
    assert [i["availability"] for i in placed.json()["point_map_instances"]] == [
        "unavailable_bytes"
    ]
    assert reads.under_the_lock == []
    read = api.version(api.entry(entry["entry_id"]))
    assert [i["availability"] for i in read["point_map_instances"]] == ["unavailable_bytes"]
    # Positive control: the bytes back, the same placement reads available.
    [data] = vanished
    api.store.put_bytes(data)
    read = api.version(api.entry(entry["entry_id"]))
    assert [i["availability"] for i in read["point_map_instances"]] == ["available"]


def test_additions_in_one_transaction_refuse_bytes_found_missing_before_the_first(api, monkeypatch):
    """Bytes looked for before a run of additions answer every addition in it, missing or not.

    The first addition's hook takes the asset read lock, as a society's does, and holds it to
    the commit; the second addition's asset was found missing before the first, and is refused
    from that finding without looking again.
    """
    entry, region, _ = _made(api)
    stored = api.store.root / api.store.key_for(BlobId.from_hex(PILLAR))
    kept = stored.read_bytes()
    stored.unlink()
    reads = _reads(api, monkeypatch)
    workspace = api.repository.workspace_id
    version_id = uuid.UUID(entry["authored_version_id"])
    hooked: list[uuid.UUID] = []

    def thing(object_id: str, digest: str) -> AuthoredObject:
        return AuthoredObject(
            object_id,
            digest,
            region,
            Transform(1_200, 0, -450, 0, 1_000),
            ObjectOrigin("authored", "fictional"),
        )

    with api.database.session(workspace) as connection:

        def locking_hook(edited: uuid.UUID) -> None:
            hooked.append(edited)
            lock_asset_reads_until_commit(connection, outside="the hook runs inside an edit")

        objects = WorldObjectRepository(
            connection, workspace, world_id=entry["world_id"], store=api.store, on_edit=locking_hook
        )
        base = objects.version(version_id).state_sha256
        seen = len(reads.every)
        with (
            pytest.raises(UnavailableAsset, match="its bytes do not"),
            connection.transaction(),
            objects.reviewed_bytes_read_first([CUBE, PILLAR]),
        ):
            first = objects.add_object(
                version_id, thing("object:cube", CUBE), base_state_sha256=base, actor=api.actor
            )
            objects.add_object(
                version_id,
                thing("object:pillar", PILLAR),
                base_state_sha256=first.state_sha256,
                actor=api.actor,
            )
        assert objects.version(version_id).state_sha256 == base, "nothing was written"
    api.store.put_bytes(kept)
    assert hooked == [version_id], "the first addition's hook took the lock"
    assert reads.under_the_lock == []
    # Both digests were looked for once, before the first addition, and never again.
    assert [method for method, _ in reads.every[seen:]] == ["exists", "exists"]


def test_an_edit_answers_a_placement_whose_stored_bytes_are_corrupt_as_unavailable(api, tmp_path):
    """Bytes that fail their digest are unavailable to a reader after the commit, not a failure.

    An edit answers with its version after its transaction has committed, so the edit is kept
    whatever reading the version then finds: a placement whose stored bytes no longer match their
    digest is answered ``unavailable_bytes`` rather than failing the answer to a kept edit.
    """
    entry, region, _ = _made(api)
    entry, environment = _placed_environment(api, entry, region, tmp_path)
    stored = api.store.root / api.store.key_for(BlobId.from_hex(environment.render.expected_sha256))
    stored.chmod(0o644)
    stored.write_bytes(b"not the pinned render")
    entry = place_object(api, entry, region)
    version = api.version(entry)
    assert [o["object_id"] for o in version["objects"]] == ["object:lantern"]
    assert [i["availability"] for i in version["environment_instances"]] == ["unavailable_bytes"]


# -- a world whose society takes inputs ------------------------------------------------------------


def _inhabited(runtime_app, client):
    world, _ = runtime_app
    saved_api.place(client, world, "object:cushion", 3_000, 5_000)
    brought = saved_api.bring_inhabitants(client, world)
    assert brought.status_code in (200, 201), brought.text
    return world


def _society_reads(world, client, monkeypatch):
    return recorded_store_reads(
        world["connection"],
        client.app.state.services.database,
        world["workspace"],
        world["store"],
        monkeypatch,
        planted=world["plate"].content_sha256,
    )


def _forgetting_licences(monkeypatch) -> None:
    """Leave each licence unread before the lock, as if its row named new bytes after the read."""
    read_first = SocietyRuntime._read_first

    def forgets(self, read, digest, size, *, keep=False):
        if size is not None or keep:
            read_first(self, read, digest, size, keep=keep)

    monkeypatch.setattr(SocietyRuntime, "_read_first", forgets)


def _inputs(world) -> list[dict]:
    rows = (
        world["connection"]
        .execute(
            "select input_seq, document from world_society_input where workspace_id=%s "
            "order by input_seq",
            (world["workspace"],),
        )
        .fetchall()
    )
    world["connection"].commit()
    return rows


def test_an_object_edit_in_a_world_whose_society_takes_inputs_reads_nothing_under_the_lock(
    runtime_app, monkeypatch
):
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        world = _inhabited(runtime_app, client)
        before = _inputs(world)
        reads = _society_reads(world, client, monkeypatch)
        saved_api.place(client, world, "object:second", -3_000, 5_000, asset="pillar")
    assert reads.under_the_lock == []
    # The society still took the edit as an input, and still checked each object's bytes, before
    # the lock: the input is available and names both objects' reviewed assets.
    after = _inputs(world)
    assert len(after) == len(before) + 1
    latest = after[-1]["document"]
    assert latest["availability"] == "available"
    assert {r["identity"] for r in latest["dependency_refs"] if r["kind"] == "reviewed_asset"} == {
        world["plate"].asset_key,
        world["pillar"].asset_key,
    }
    assert _asked(reads, "api/society_runtime.py:_read_first")


def test_an_environment_piece_in_a_world_whose_society_takes_inputs_reads_nothing_under_the_lock(
    runtime_app, tmp_path, monkeypatch
):
    world, make_app = runtime_app
    scope, version, _ = saved_api.routes(world)
    with TestClient(make_app()) as client:
        world = _inhabited(runtime_app, client)
        environment = _admit_environment(
            IngestRepository(world["connection"], world["workspace"]),
            world["store"],
            tmp_path,
            "yard",
        )
        world["connection"].commit()
        before = _inputs(world)
        reads = _society_reads(world, client, monkeypatch)
        transform = {"x_mm": 0, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0, "scale_milli": 1000}
        base = client.get(version, headers=saved_api.OWNER, params=scope).json()["state_sha256"]
        placed = client.post(
            version + "/environment-instances",
            headers=saved_api.OWNER,
            params=scope,
            json={
                "base_state_sha256": base,
                "instance_id": "environment:yard",
                "admission_id": str(environment.source.admission_id),
                "render_asset_id": str(environment.render.asset_id),
                "publication_id": None,
                "selection": {"kind": "whole_asset"},
                "source_anchor": {
                    "frame_name": "nyc-grid",
                    "coordinate_scale": 1000,
                    "coordinates": [10, 20, 0],
                },
                "region_id": world["binding"].region_id,
                "transform": transform,
                "origin_role": "fictional",
            },
        )
        assert placed.status_code == 201, placed.text
        moved = client.post(
            version + "/environment-instances/environment:yard/move",
            headers=saved_api.OWNER,
            params=scope,
            json={
                "base_state_sha256": placed.json()["state_sha256"],
                "transform": {**transform, "x_mm": 250},
            },
        )
    assert moved.status_code == 200, moved.text
    assert [i["availability"] for i in moved.json()["environment_instances"]] == ["available"]
    assert reads.under_the_lock == []
    # The society took both edits as inputs, each naming the piece as one it does not read.
    after = _inputs(world)
    assert len(after) == len(before) + 2
    assert after[-1]["document"]["availability"] == "available"
    assert [p["instance_id"] for p in after[-1]["document"]["unread_placements"]] == [
        "environment:yard"
    ]
    assert _asked(reads, "api/society_runtime.py:_read_first")


def test_reading_a_society_authorizes_its_input_without_reading_under_the_lock(
    runtime_app, monkeypatch
):
    world, make_app = runtime_app
    scope, _, society = saved_api.routes(world)
    with TestClient(make_app()) as client:
        world = _inhabited(runtime_app, client)
        reads = _society_reads(world, client, monkeypatch)
        read = client.get(society, headers=saved_api.OWNER, params=scope)
    assert read.status_code == 200, read.text
    assert reads.under_the_lock == []
    assert _asked(reads, "api/society_runtime.py:_read_first"), "the object's bytes were checked"


def test_the_small_square_looks_for_its_objects_bytes_before_the_first_addition(
    runtime_app, monkeypatch
):
    """Each addition's own byte check is made before the first addition takes the lock.

    The society's own reads for each input are its authorization's, measured on their own.
    """
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        world = _inhabited(runtime_app, client)
        reads = _society_reads(world, client, monkeypatch)
        scope, version, body = arrangements._body(client, world)
        applied = client.post(
            version + "/arrangements/apply", headers=saved_api.OWNER, params=scope, json=body
        )
    assert applied.status_code == 201, applied.text
    asked_by_an_addition = [
        (method, where)
        for method, where in reads.under_the_lock
        if where.split(" < ")[0].startswith("world/object_repository.py")
    ]
    assert asked_by_an_addition == []
    assert _asked(reads, "world/object_repository.py:reviewed_bytes_read_first")


def test_rows_naming_bytes_nobody_read_before_the_lock_refuse_the_edit_to_be_asked_again(
    runtime_app, monkeypatch
):
    world, make_app = runtime_app
    scope, version, _ = saved_api.routes(world)
    with TestClient(make_app()) as client:
        world = _inhabited(runtime_app, client)
        inputs = _inputs(world)
        base = client.get(version, headers=saved_api.OWNER, params=scope).json()["state_sha256"]
        reads = _society_reads(world, client, monkeypatch)
        with monkeypatch.context() as patch:
            _forgetting_licences(patch)
            refused = saved_api.place_request(
                client, world, "object:second", -3_000, 5_000, asset="pillar"
            )
        assert refused.status_code == 409, refused.text
        assert refused.json() == {
            "code": "busy",
            "detail": "a society input names stored bytes that were not read before the asset "
            "read lock was taken; ask again",
        }
        after = client.get(version, headers=saved_api.OWNER, params=scope).json()["state_sha256"]
        assert after == base, "the edit was not written"
        assert _inputs(world) == inputs, "no input was recorded"
        assert reads.under_the_lock == []
        # Positive control: asked again, the bytes are read first and the edit is taken.
        saved_api.place(client, world, "object:second", -3_000, 5_000, asset="pillar")
    assert len(_inputs(world)) == len(inputs) + 1


def test_playback_fails_a_round_that_names_unread_bytes_and_the_next_claim_retries(
    runtime_app, monkeypatch
):
    """A race fails the round without pausing: the lease is left to expire and is claimed again."""
    world, make_app = runtime_app
    scope, _, society = saved_api.routes(world)
    control_route = society + "/control"
    with TestClient(make_app()) as client:
        world = _inhabited(runtime_app, client)
        control = client.get(control_route, headers=saved_api.OWNER, params=scope).json()
        playing = client.put(
            control_route,
            headers=saved_api.OWNER,
            params=scope,
            json={"base_revision": control["revision"], "mode": "playing", "speed": 1},
        )
        assert playing.status_code == 200, playing.text

        def due(*, lease_expired: bool) -> None:
            expire = ",lease_expires_at=clock_timestamp()-interval '1 second'"
            world["connection"].execute(
                "update world_society_control set "
                "next_due_at=clock_timestamp()-interval '5 seconds'"
                + (expire if lease_expired else "")
                + " where workspace_id=%s",
                (world["workspace"],),
            )
            world["connection"].commit()

        due(lease_expired=False)
        before = client.get(society, headers=saved_api.OWNER, params=scope).json()
        services = client.app.state.services
        worker = SocietyControlWorker(
            services.database, runtime=services.society_runtime, workspaces=[world["workspace"]]
        )
        with monkeypatch.context() as patch:
            _forgetting_licences(patch)
            with pytest.raises(SocietyBytesNotRead):
                worker.run_once(world["workspace"])
        still = client.get(control_route, headers=saved_api.OWNER, params=scope).json()
        assert still["mode"] == "playing", still
        now = client.get(society, headers=saved_api.OWNER, params=scope).json()
        assert now["current_tick"] == before["current_tick"], "the failed round advanced nothing"
        # The lease the failed round claimed is left to expire; once it has, the round is retried.
        due(lease_expired=True)
        result = worker.run_once(world["workspace"])
    assert result is not None and result["receipt"]["kind"] == "advanced", result


def test_bytes_read_before_the_lock_answer_only_for_what_was_read():
    """The record read before the lock answers from what it holds and refuses anything else."""
    record = _ReadFirst(
        {
            ("a" * 64, 3): None,
            ("b" * 64, None): "required exact asset bytes are unavailable",
            ("c" * 64, None): b"{}",
        }
    )
    assert record.answer("a" * 64, 3) is None
    assert record.kept("c" * 64) == b"{}"
    with pytest.raises(UnavailableSocietyInput, match="required exact asset bytes are unavailable"):
        record.answer("b" * 64, None)
    # The same digest held to another size was not what was read, nor were bytes not kept.
    for unread in (lambda: record.answer("a" * 64, 4), lambda: record.kept("a" * 64)):
        with pytest.raises(SocietyBytesNotRead):
            unread()
    # A race is not an unavailable input: nothing that records one, or pauses for one, takes it.
    assert not issubclass(SocietyBytesNotRead, (UnavailableSocietyInput, ValueError))


def test_the_application_answers_the_race_as_a_retry_whatever_route_meets_it(
    runtime_app, monkeypatch
):
    """One handler answers the race for every route: a society read that meets it is a 409 busy."""
    world, make_app = runtime_app
    scope, _, society = saved_api.routes(world)
    with TestClient(make_app()) as client:
        world = _inhabited(runtime_app, client)
        assert SocietyBytesNotRead in client.app.exception_handlers
        reads = _society_reads(world, client, monkeypatch)
        with monkeypatch.context() as patch:
            _forgetting_licences(patch)
            raced = client.get(society, headers=saved_api.OWNER, params=scope)
        assert raced.status_code == 409, raced.text
        assert raced.json()["code"] == "busy"
        assert reads.under_the_lock == []
        # Positive control: asked again, the same read is answered.
        assert client.get(society, headers=saved_api.OWNER, params=scope).status_code == 200


def test_a_question_whose_society_meets_the_race_is_answered_without_the_society(memory_place):
    """The selection executor leaves a society out for this question when it meets the race.

    The question is still answered, from everything else it may read, exactly as it is when the
    society's input is unavailable; the next question asks the society again.
    """
    memory = memory_place
    composition._confirm_bridge(memory)
    world = memory.composed
    conn = world.worlds.connection
    version = world.version.version_id
    SocietyRepository(
        conn,
        world.worlds.workspace_id,
        world_id=world.worlds.world_id,
        input_authorizer=lambda _document: None,
    ).create(
        version,
        place_id=world.source.place_id,
        region_id="region-a",
        seed=SEED,
        actor=memory.actor,
        profile="exulanica-society/v2",
        initial_input=society_input(version),
    )
    conn.commit()

    def run(authorizer):
        return execute(
            conn,
            validate(conn, memory.plan(), memory.session),
            world_id=world.worlds.world_id,
            store=world.store,
            society_authorizer=authorizer,
        )

    def raced(_document):
        raise SocietyBytesNotRead("the rows named bytes nobody read")

    def unavailable(_document):
        raise UnavailableSocietyInput("the society's source was withdrawn")

    allowed, left_out, answered = run(lambda _document: None), run(unavailable), run(raced)
    # Positive control: allowed, the society's people are part of the answer.
    assert any(item.origin_kind == "simulated" for item in allowed.content)
    assert answered.content == left_out.content
    assert answered.total_matched == left_out.total_matched < allowed.total_matched


def test_a_decision_whose_finish_meets_the_race_is_finished_once_more_and_keeps_its_answer(
    social, client, transport, manifest, monkeypatch
):
    """Finishing is idempotent, so a race inside it is met by finishing once more.

    The model was already asked and paid for; losing its answer would leave the request in
    progress under its key for good.
    """
    api, _repo, _version, route, _changed, _rights, body = social
    api.client.app.state.society_decision_provider = social_helpers.provider_for(
        client, transport, manifest
    )
    authorize = api.client.app.state.society_input_authorizer
    finishing = {"now": False, "finishes": 0, "raced": 0}
    finish = SocietyDecisionRepository.finish

    def counted(self, *args, **kwargs):
        finishing["now"], finishing["finishes"] = True, finishing["finishes"] + 1
        try:
            return finish(self, *args, **kwargs)
        finally:
            finishing["now"] = False

    def racing(connection, session, document):
        if finishing["now"] and not finishing["raced"]:
            finishing["raced"] += 1
            raise SocietyBytesNotRead("the rows named bytes nobody read")
        return authorize(connection, session, document)

    monkeypatch.setattr(SocietyDecisionRepository, "finish", counted)
    api.client.app.state.society_input_authorizer = racing
    answered = api.post(api.in_world(route + "/decisions"), body)
    assert answered.status_code == 200, answered.text
    assert answered.json()["decision"]["status"] == "accepted"
    assert finishing == {"now": False, "finishes": 2, "raced": 1}
    assert len(transport.requests) == 1, "the model was asked once and its answer kept"
    # The same key reads the recorded decision, not a request stuck in progress.
    assert api.post(api.in_world(route + "/decisions"), body).json() == answered.json()
