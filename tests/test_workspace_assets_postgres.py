"""Migration 0126 over HTTP and the worker: admission, isolation, preparation, withdrawal, delivery.

Every test runs the real application as a provisioned runtime role (neither owner nor
BYPASSRLS), with two workspaces, against a private PostgreSQL. Containers are built in code.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import IO

import psycopg
import pytest
from exulanica.db.session import Database
from exulanica.evidence.blob import BlobId
from exulanica.orchestration.judge_seed import (
    SeedRefused,
    _refuse_private_workspace_assets,
    export_seed,
)
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import workspace_asset_lock_key
from exulanica.world import asset_preparation_command
from exulanica.world.asset_preparation import PreparationOutcome, decode_texture
from exulanica.world.static_glb import inspect_static_glb, prepare_static_glb
from exulanica.world.workspace_assets import WorkspaceAssetRepository, WorkspaceAssetRuntime
from exulanica.world.workspace_preparations import AuthorizedOutput

from static_glb_builder import CUBE_CORNERS, Gltf, cube, png
from workspace_asset_support import AssetsApi, assets_api, declaration, without

pytestmark = pytest.mark.postgres
QUOTA = "workspace_asset_quota_exceeded"


@pytest.fixture
def api(repository, spine_schema, tmp_path):
    yield from assets_api(repository, spine_schema, tmp_path)


def _asset_id(response) -> str:
    return response.json()["asset_id"]


# -- admission ----------------------------------------------------------------------------------


def test_a_permitted_static_asset_is_admitted_prepared_and_delivered(api: AssetsApi) -> None:
    payload = cube(offset=(0.0, 0.0, 0.0), texture=png(4, 4)).build()
    admitted = api.admit(payload)
    assert admitted.status_code == 201, admitted.text
    view = admitted.json()
    assert view["availability"] == {"state": "not_placeable", "code": "preparing"}
    assert view["input"] == {
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "byte_size": len(payload),
        "media_type": "model/gltf-binary",
    }
    assert view["use"]["policy"] == "exulanica.workspace-asset-use/v1"
    assert view["preparation"]["state"] == "requested"

    outcome = api.drain()
    assert (outcome.prepared, outcome.failed, outcome.errors) == (1, 0, [])
    prepared = api.get(f"/workspace-assets/{view['asset_id']}").json()
    assert prepared["availability"] == {"state": "placeable", "code": None}
    assert prepared["preparation"]["dimensions_mm"] == {
        "width": 1000,
        "height": 1000,
        "depth": 1000,
    }
    output = prepared["preparation"]["output"]
    receipt = prepared["preparation"]["receipt"]
    assert receipt["input"]["content_sha256"] == view["input"]["content_sha256"]
    assert receipt["output"]["content_sha256"] == output["content_sha256"]
    assert [step["kind"] for step in receipt["steps"]].count("transform") == 1

    delivered = api.get(f"/workspace-assets/{view['asset_id']}/prepared/bytes")
    assert delivered.status_code == 200
    assert delivered.headers["cache-control"] == "private, no-store"
    assert delivered.headers["etag"] == f'"{output["content_sha256"]}"'
    assert hashlib.sha256(delivered.content).hexdigest() == output["content_sha256"]
    inspect_static_glb(delivered.content)

    listed = api.get("/workspace-assets").json()
    assert [item["asset_id"] for item in listed["assets"]] == [view["asset_id"]]
    assert listed["admission"]["bounds"]["content_bytes"] == 32 * 1024 * 1024
    assert listed["admission"]["bounds"]["workspace_assets"] == 64


def test_an_identical_upload_returns_the_first_asset_and_a_changed_one_is_new(
    api: AssetsApi,
) -> None:
    payload = cube().build()
    first = api.admit(payload)
    again = api.admit(payload)
    assert (first.status_code, again.status_code) == (201, 200)
    assert _asset_id(first) == _asset_id(again)
    renamed = api.admit(payload, declaration(payload, title="Oak bench, second"))
    assert renamed.status_code == 201
    assert _asset_id(renamed) != _asset_id(first)
    # One stored copy of the bytes, whatever number of admissions name them.
    assert len(api.namespace_files()) == 1


@pytest.mark.parametrize(
    ("build", "code", "detail"),
    [
        (lambda: b"glTF" + b"\x00" * 60, "asset_content_refused", "malformed_container"),
        (
            lambda: _changed(lambda d: d.update(extensionsUsed=["KHR_draco_mesh_compression"])),
            "asset_content_refused",
            "compressed_content",
        ),
        (
            lambda: _changed(lambda d: d.update(extensionsRequired=["KHR_materials_variants"])),
            "asset_content_refused",
            "required_extension",
        ),
        (
            lambda: _changed(lambda d: d.update(extensionsUsed=["KHR_texture_transform"])),
            "asset_content_refused",
            "extension_not_admitted",
        ),
        (
            lambda: _changed(lambda d: d["buffers"][0].update(uri="https://example.invalid/x")),
            "asset_content_refused",
            "external_reference",
        ),
        (
            lambda: _changed(lambda d: d.update(animations=[{"channels": [], "samplers": []}])),
            "asset_content_refused",
            "not_static",
        ),
    ],
)
def test_a_refused_container_writes_no_row_and_no_byte(api: AssetsApi, build, code, detail) -> None:
    before = api.counts()
    response = api.admit(build())
    assert response.status_code == 422, response.text
    assert (response.json()["code"], response.json()["detail"]) == (code, detail)
    assert api.counts() == before
    assert api.namespace_files() == []


def _changed(change) -> bytes:
    gltf = cube(texture=png(2, 2))
    gltf.document.setdefault("buffers", [{"byteLength": len(gltf.binary)}])
    change(gltf.document)
    return gltf.build()


def test_a_declaration_that_disagrees_or_is_not_admitted_writes_nothing(api: AssetsApi) -> None:
    payload = cube().build()
    before = api.counts()
    cases = [
        (declaration(payload, content_sha256="0" * 64), 422, "content_digest_mismatch"),
        (declaration(payload, byte_size=len(payload) + 4), 422, "content_digest_mismatch"),
        (
            declaration(payload, rights={"basis": "licensed", "licence_id": "CC-BY-NC-4.0"}),
            422,
            "licence_not_admitted",
        ),
        (
            declaration(payload, rights={"basis": "licensed", "licence_id": "CC-BY-4.0"}),
            422,
            "attribution_required",
        ),
        (declaration(payload, unit="furlong"), 422, "invalid_declaration"),
        (without(declaration(payload), "rights", "statement"), 422, "invalid_declaration"),
        (declaration(payload, surprise=True), 422, "invalid_declaration"),
    ]
    for document, status, code in cases:
        response = api.admit(payload, document)
        assert (response.status_code, response.json()["code"]) == (status, code), response.text
    response = api.admit(payload, raw_declaration="{not json")
    assert (response.status_code, response.json()["code"]) == (422, "invalid_declaration")
    assert api.counts() == before
    assert api.namespace_files() == []


def test_content_over_the_byte_ceiling_is_refused_before_a_row(api: AssetsApi) -> None:
    payload = b"\x00" * (32 * 1024 * 1024 + 4)
    before = api.counts()
    response = api.admit(payload, declaration(b"x" * 20))
    assert (response.status_code, response.json()["code"]) == (413, "asset_too_large")
    assert api.counts() == before


def test_licensed_assets_carry_their_licence_and_attribution(api: AssetsApi) -> None:
    payload = cube().build()
    view = api.admitted(
        payload,
        rights={"basis": "licensed", "licence_id": "CC-BY-4.0", "attribution": "Bench by A. Maker"},
    )
    assert view["rights"]["licence_id"] == "CC-BY-4.0"
    assert view["rights"]["attribution"] == "Bench by A. Maker"
    delivered = api.get(f"/workspace-assets/{view['asset_id']}/prepared/bytes")
    assert delivered.headers["x-exulanica-licence"] == "CC-BY-4.0"


# -- isolation ----------------------------------------------------------------------------------


def test_another_workspace_cannot_see_use_or_detect_an_asset(api: AssetsApi) -> None:
    payload = cube(texture=png(2, 2)).build()
    view = api.admitted(payload)
    asset = view["asset_id"]
    invented = str(uuid.uuid4())
    for path in ("/workspace-assets/{}", "/workspace-assets/{}/prepared/bytes"):
        foreign = api.get(path.format(asset), who="stranger")
        unknown = api.get(path.format(invented), who="stranger")
        assert foreign.status_code == unknown.status_code == 404
        assert (
            foreign.json()
            == unknown.json()
            == {
                "code": "unknown_reference",
                "detail": "no such workspace asset",
            }
        )
    for path in ("/workspace-assets/{}/withdraw", "/workspace-assets/{}/preparation"):
        foreign = api.post(path.format(asset), who="stranger")
        unknown = api.post(path.format(invented), who="stranger")
        assert (foreign.status_code, foreign.json()) == (unknown.status_code, unknown.json())
    assert api.get("/workspace-assets", who="stranger").json()["assets"] == []

    # The stranger uploading the very same bytes learns nothing and gets a copy of its own.
    theirs = api.admit(payload, who="stranger")
    assert theirs.status_code == 201
    assert theirs.json()["asset_id"] != asset
    assert len(api.namespace_files(api.stranger)) == 1
    api.drain(api.stranger)
    # Withdrawing the owner's leaves the stranger's alone.
    assert api.post(f"/workspace-assets/{asset}/withdraw").status_code == 200
    stranger_view = api.get(f"/workspace-assets/{theirs.json()['asset_id']}", who="stranger")
    assert stranger_view.json()["availability"]["state"] == "placeable"


def test_admission_leaves_the_global_catalog_untouched(api: AssetsApi) -> None:
    catalog = api.get("/world/assets").json()
    rows = api.sql("select asset_key, content_sha256 from world_reviewed_asset order by asset_key")
    view = api.admitted(cube().build())
    assert api.get("/world/assets").json() == catalog
    assert (
        api.sql("select asset_key, content_sha256 from world_reviewed_asset order by asset_key")
        == rows
    )
    digest = view["preparation"]["output"]["content_sha256"]
    assert api.get(f"/world/assets/{digest}").status_code == 404


# -- preparation --------------------------------------------------------------------------------


def _claimed(api: AssetsApi, connection, **options):
    """A worker holding one claim on ``connection``, as a running worker would."""
    worker = api.worker(**options)
    claim = worker._claim(connection, api.owner)
    assert claim is not None
    return worker, claim


def _expire_running(api: AssetsApi) -> None:
    """What time does to a dead worker's lease, without waiting for it."""
    api.sql(
        "update workspace_preparation set lease_expires_at = clock_timestamp() "
        "- interval '1 second' where state = 'running'"
    )


def test_an_interrupted_preparation_is_retaken_and_makes_one_output(api: AssetsApi) -> None:
    asset = _asset_id(api.admit(cube().build()))
    with api.database.session(api.owner) as connection:
        _claimed(api, connection)  # and the worker dies holding its lease
    _expire_running(api)
    outcome = api.drain()
    assert outcome.prepared == 1
    row = api.sql(
        "select state, attempts, output_sha256 from workspace_preparation where asset_id = %s",
        uuid.UUID(asset),
    )[0]
    assert (row["state"], row["attempts"]) == ("prepared", 2)
    blobs = api.sql(
        "select count(*) as n from workspace_asset_blob where content_sha256 = %s",
        row["output_sha256"],
    )
    assert blobs[0]["n"] == 1


def test_a_preparation_whose_every_attempt_dies_is_failed_exhausted(api: AssetsApi) -> None:
    asset = _asset_id(api.admit(cube().build()))
    for _ in range(3):
        with api.database.session(api.owner) as connection:
            _claimed(api, connection)
        _expire_running(api)
    outcome = api.drain()
    assert outcome.exhausted == 1
    view = api.get(f"/workspace-assets/{asset}").json()
    assert view["preparation"]["failure"]["class"] == "exhausted"
    assert view["availability"] == {"state": "not_placeable", "code": "preparation_failed"}
    retried = api.post(f"/workspace-assets/{asset}/preparation")
    assert retried.status_code == 202
    assert api.drain().prepared == 1


def test_cancelling_a_running_preparation_publishes_nothing(api: AssetsApi) -> None:
    asset = _asset_id(api.admit(cube().build()))
    outcome = PreparationOutcome()
    with api.database.session(api.owner) as connection:
        worker, claim = _claimed(api, connection)
        cancelled = api.post(f"/workspace-assets/{asset}/preparation/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["preparation"]["state"] == "cancelled"
        worker._prepare_one(connection, api.owner, claim, outcome)
    assert (outcome.prepared, outcome.lost) == (0, 1)
    input_sha256 = api.sql(
        "select input_sha256 from workspace_asset where asset_id = %s", uuid.UUID(asset)
    )[0]["input_sha256"]
    assert [
        row["content_sha256"] for row in api.sql("select content_sha256 from workspace_asset_blob")
    ] == [input_sha256]
    assert len(api.namespace_files()) == 1  # the input only
    again = api.post(f"/workspace-assets/{asset}/preparation")
    assert again.status_code == 202
    assert api.drain().prepared == 1


def test_a_withdrawal_during_preparation_prevents_publication(api: AssetsApi) -> None:
    asset = _asset_id(api.admit(cube().build()))
    outcome = PreparationOutcome()
    with api.database.session(api.owner) as connection:
        worker, claim = _claimed(api, connection)
        assert api.post(f"/workspace-assets/{asset}/withdraw").status_code == 200
        worker._prepare_one(connection, api.owner, claim, outcome)
    assert (outcome.prepared, outcome.lost) == (0, 1)
    state = api.sql(
        "select state, failure_class from workspace_preparation where asset_id = %s",
        uuid.UUID(asset),
    )[0]
    assert (state["state"], state["failure_class"]) == ("cancelled", "withdrawn")
    assert len(api.namespace_files()) == 1
    assert api.get(f"/workspace-assets/{asset}").status_code == 410
    assert api.post(f"/workspace-assets/{asset}/preparation").status_code == 410


def test_content_that_fails_preparation_is_failed_by_name_and_retry_is_deterministic(
    api: AssetsApi,
) -> None:
    gltf = Gltf()
    positions = gltf.positions(CUBE_CORNERS)
    mesh = gltf.mesh({"attributes": {"POSITION": positions}, "indices": gltf.indices([0, 1, 99])})
    gltf.scene(gltf.node(mesh=mesh))
    asset = _asset_id(api.admit(gltf.build()))
    assert api.drain().failed == 1
    view = api.get(f"/workspace-assets/{asset}").json()
    assert view["preparation"]["failure"]["class"] == "invalid_content"
    assert view["preparation"]["failure"]["code"] == "invalid_geometry"
    # A failure a second run of the same preparation cannot change is answered, not re-run.
    answered = api.post(f"/workspace-assets/{asset}/preparation")
    assert answered.status_code == 200
    assert answered.json()["preparation"]["state"] == "failed"
    assert api.drain().handled == 0


def test_an_admission_too_small_to_place_is_prepared_and_incompatible(api: AssetsApi) -> None:
    view = api.admitted(cube().build(), unit="millimetre")
    assert view["preparation"]["state"] == "prepared"
    assert view["availability"] == {"state": "not_placeable", "code": "incompatible"}
    assert view["compatibility"] == [
        {
            "profile": "exulanica.placeable-object/v1",
            "state": "incompatible",
            "code": "dimensions_out_of_bounds",
        }
    ]


def test_a_prepared_output_is_write_once_and_reproduced_after_loss(api: AssetsApi) -> None:
    view = api.admitted(cube().build())
    asset, digest = view["asset_id"], view["preparation"]["output"]["content_sha256"]
    with pytest.raises(psycopg.errors.CheckViolation):
        api.sql(
            "update workspace_preparation set output_sha256 = %s where asset_id = %s",
            "f" * 64,
            uuid.UUID(asset),
        )
    # Lose the prepared bytes: the asset says so, a request re-prepares, and the digest is the same.
    for path in api.namespace_files():
        if path.name == digest:
            path.chmod(0o644)
            path.unlink()
    lost = api.get(f"/workspace-assets/{asset}").json()
    assert lost["availability"] == {"state": "not_placeable", "code": "prepared_bytes_missing"}
    assert api.get(f"/workspace-assets/{asset}/prepared/bytes").json()["code"] == (
        "prepared_bytes_missing"
    )
    assert api.post(f"/workspace-assets/{asset}/preparation").status_code == 202
    assert api.drain().prepared == 1
    again = api.get(f"/workspace-assets/{asset}").json()
    assert again["preparation"]["output"]["content_sha256"] == digest
    assert again["availability"]["state"] == "placeable"


def test_a_workspace_has_at_most_eight_preparations_waiting(api: AssetsApi) -> None:
    for number in range(8):
        response = api.admit(cube(scale=1.0 + number).build())
        assert response.status_code == 201, response.text
    before = api.counts()
    refused = api.admit(cube(scale=20.0).build())
    assert (refused.status_code, refused.json()["code"]) == (
        429,
        "workspace_asset_quota_exceeded",
    )
    assert api.counts() == before


# -- withdrawal and delivery --------------------------------------------------------------------


def test_withdrawal_is_final_hides_everything_and_destroys_nothing(api: AssetsApi) -> None:
    view = api.admitted(cube().build())
    asset = view["asset_id"]
    files = api.namespace_files()
    assert api.post(f"/workspace-assets/{asset}/withdraw").json() == {
        "asset_id": asset,
        "withdrawn": True,
    }
    assert api.post(f"/workspace-assets/{asset}/withdraw").status_code == 200
    assert api.get(f"/workspace-assets/{asset}").json()["code"] == "withdrawn"
    assert api.get(f"/workspace-assets/{asset}/prepared/bytes").status_code == 410
    assert api.post(f"/workspace-assets/{asset}/preparation/cancel").status_code == 410
    assert api.get("/workspace-assets").json()["assets"] == []
    assert api.namespace_files() == files  # hidden, not erased
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        api.sql("delete from workspace_asset_withdrawal")


def _sessions_opened(monkeypatch: pytest.MonkeyPatch) -> list[psycopg.Connection]:
    """Every connection the application opens through ``Database.session``, as it opens them."""
    opened: list[psycopg.Connection] = []
    session = Database.session

    @contextmanager
    def recording(self: Database, workspace_id: uuid.UUID) -> Iterator[psycopg.Connection]:
        with session(self, workspace_id) as connection:
            opened.append(connection)
            yield connection

    monkeypatch.setattr(Database, "session", recording)
    return opened


def test_prepared_bytes_stream_from_their_checked_copy_with_no_connection_held(
    api: AssetsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bytes checked before the final check are sent a chunk at a time, the connection the
    route authorized on is closed before the first chunk, and the store's whole-object read, which
    held every prepared output in memory, is not used."""
    view = api.admitted(cube(offset=(0.0, 0.0, 0.0), texture=png(64, 64)).build())
    asset, output = view["asset_id"], view["preparation"]["output"]
    opened = _sessions_opened(monkeypatch)
    closed_at_first_chunk: list[bool] = []
    chunks = AuthorizedOutput.chunks

    def watched(self: AuthorizedOutput) -> Iterator[bytes]:
        closed_at_first_chunk.append(all(connection.closed for connection in opened))
        yield from chunks(self)

    def whole(*_args: object) -> bytes:
        raise AssertionError("a delivery never reads a whole prepared output into memory")

    monkeypatch.setattr(AuthorizedOutput, "chunks", watched)
    monkeypatch.setattr(LocalContentAddressedStore, "get", whole)
    delivered = api.get(f"/workspace-assets/{asset}/prepared/bytes")
    assert delivered.status_code == 200, delivered.text
    assert hashlib.sha256(delivered.content).hexdigest() == output["content_sha256"]
    assert delivered.headers["content-length"] == str(len(delivered.content))
    assert delivered.headers["content-type"] == "model/gltf-binary"
    assert delivered.headers["cache-control"] == "private, no-store"
    assert delivered.headers["etag"] == f'"{output["content_sha256"]}"'
    assert delivered.headers["x-exulanica-licence"] == "own-work"
    assert opened and closed_at_first_chunk == [True]


def test_the_checked_copy_is_closed_once_sent_and_when_a_late_withdrawal_refuses_it(
    api: AssetsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = api.admitted(cube().build())
    asset = view["asset_id"]
    copies: list[IO[bytes]] = []
    open_verified = LocalContentAddressedStore.open_verified

    def kept(self: LocalContentAddressedStore, blob_id: BlobId) -> IO[bytes]:
        copies.append(open_verified(self, blob_id))
        return copies[-1]

    monkeypatch.setattr(LocalContentAddressedStore, "open_verified", kept)
    assert api.get(f"/workspace-assets/{asset}/prepared/bytes").status_code == 200
    assert len(copies) == 1 and copies[0].closed

    def withdrawn_once_read(self: LocalContentAddressedStore, blob_id: BlobId) -> IO[bytes]:
        copy = kept(self, blob_id)
        with api.database.session(api.owner) as other:
            WorkspaceAssetRepository(other, api.owner, api.actor, stores=api.stores).withdraw(
                uuid.UUID(asset)
            )
        return copy

    # A withdrawal committed between the read and the final check: refused, and nothing sent.
    monkeypatch.setattr(LocalContentAddressedStore, "open_verified", withdrawn_once_read)
    refused = api.get(f"/workspace-assets/{asset}/prepared/bytes")
    assert (refused.status_code, refused.json()["code"]) == (410, "withdrawn")
    assert len(copies) == 2 and copies[1].closed


def test_prepared_bytes_that_changed_on_disk_are_refused_and_not_sent(api: AssetsApi) -> None:
    view = api.admitted(cube().build())
    digest = view["preparation"]["output"]["content_sha256"]
    (stored,) = [path for path in api.namespace_files() if path.name == digest]
    original = stored.read_bytes()
    stored.chmod(0o644)  # the store writes read-only files; this test plays a damaged disk
    stored.write_bytes(original[:-4] + b"\0\0\0\0")
    refused = api.get(f"/workspace-assets/{view['asset_id']}/prepared/bytes")
    assert (refused.status_code, refused.json()["code"]) == (500, "integrity_failure")


def test_a_prepared_asset_cannot_be_cancelled(api: AssetsApi) -> None:
    view = api.admitted(cube().build())
    response = api.post(f"/workspace-assets/{view['asset_id']}/preparation/cancel")
    assert (response.status_code, response.json()["code"]) == (409, "preparation_finished")


def test_the_declaration_is_stored_exactly_and_digested(api: AssetsApi) -> None:
    payload = cube().build()
    document = declaration(payload, rights={"source_reference": "made in a workshop"})
    view = api.admit(payload, document).json()
    assert view["declaration"] == document
    stored = api.sql(
        "select declaration_canonical from workspace_asset where asset_id = %s",
        uuid.UUID(view["asset_id"]),
    )[0]["declaration_canonical"]
    assert json.loads(bytes(stored)) == document
    assert hashlib.sha256(bytes(stored)).hexdigest() == view["declaration_sha256"]


def test_a_workspace_holding_its_own_assets_cannot_be_seeded(api: AssetsApi) -> None:
    """The judge seed copies a workspace for somebody else, and an admission never leaves it."""
    with api.owner_database.session(api.owner) as connection:
        # The control: nothing admitted, nothing refused.
        _refuse_private_workspace_assets(connection, api.owner)
    assert api.admit(cube().build()).status_code == 201
    with (
        api.owner_database.session(api.owner) as connection,
        pytest.raises(SeedRefused, match="holds 1 workspace asset object"),
    ):
        export_seed(
            connection,
            api.store,
            workspace_id=api.owner,
            destination=api.tmp_path / "seed",
            created_at="2026-09-30T00:00:00Z",
        )
    assert not (api.tmp_path / "seed").exists()


# -- the preparation process ---------------------------------------------------------------------


def _events(output: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]


def test_the_preparation_process_refuses_to_start_without_its_role_or_a_workspace(
    api: AssetsApi,
) -> None:
    output = io.StringIO()
    assert asset_preparation_command.main(["--once"], environ={}, stream=output) == 1
    [event] = _events(output)
    assert (event["event"], event["failure_class"]) == ("startup_failed", "DatabaseNotConfigured")

    # The schema owner is refused: the process runs as the runtime role or not at all.
    output = io.StringIO()
    owner = {"EXULANICA_DATABASE_URL": api.owner_database.url}
    assert (
        asset_preparation_command.main(
            ["--once", "--workspace", str(api.owner)], environ=owner, stream=output
        )
        == 1
    )
    assert _events(output)[0]["event"] == "startup_failed"

    output = io.StringIO()
    runtime = {"EXULANICA_DATABASE_URL": api.database.url}
    assert asset_preparation_command.main(["--once"], environ=runtime, stream=output) == 1
    [event] = _events(output)
    assert event["event"] == "startup_failed" and "silently prepares nothing" in event["message"]


def test_the_preparation_process_prepares_what_waits_once_and_exits(api: AssetsApi) -> None:
    admitted = api.admit(cube().build())
    assert admitted.status_code == 201, admitted.text
    output = io.StringIO()
    environ = {
        "EXULANICA_DATABASE_URL": api.database.url,
        "EXULANICA_DATA_DIR": str(api.stores.root.parent),
    }
    assert api.stores.root == api.stores.root.parent / "workspace-assets"
    code = asset_preparation_command.main(
        ["--once", "--workspace", str(api.owner), "--name", "test-preparation"],
        environ=environ,
        stream=output,
    )
    started, stopped = _events(output)
    assert code == 0, stopped
    assert (started["event"], started["worker"], started["mode"]) == (
        "startup",
        "test-preparation",
        "once",
    )
    assert (stopped["event"], stopped["prepared"], stopped["errors"]) == ("stopped", 1, [])
    view = api.get(f"/workspace-assets/{admitted.json()['asset_id']}").json()
    assert view["availability"] == {"state": "placeable", "code": None}


# -- capabilities --------------------------------------------------------------------------------


def _capabilities(view: dict) -> dict[str, dict]:
    return {descriptor["operation"]: descriptor for descriptor in view["capabilities"]}


def _admission(api: AssetsApi) -> tuple[str, str | None]:
    admit = _capabilities(api.get("/workspace-assets").json())["POST /workspace-assets"]
    return admit["state"], admit["code"]


def test_the_admission_descriptor_turns_unavailable_exactly_when_admission_is_refused(
    api: AssetsApi,
) -> None:
    assert _admission(api) == ("available", None)
    for number in range(8):
        assert api.admit(cube(scale=1.0 + number).build()).status_code == 201
        expected = ("available", None) if number < 7 else ("unavailable", QUOTA)
        assert _admission(api) == expected, number
    refused = api.admit(cube(scale=20.0).build())
    assert (refused.status_code, refused.json()["code"]) == (429, QUOTA)
    # Each waiting asset's own request answers as it is, so a spent bound does not stop it.
    listed = api.get("/workspace-assets").json()["assets"]
    for view in listed:
        asked = _capabilities(view)["POST /workspace-assets/{asset_id}/preparation"]
        assert (asked["state"], asked["code"]) == ("available", None)
    assert not api.drain().errors
    assert _admission(api) == ("available", None)


def test_an_assets_descriptors_follow_its_preparation(api: AssetsApi) -> None:
    admitted = api.admit(cube().build()).json()
    waiting = _capabilities(api.get(f"/workspace-assets/{admitted['asset_id']}").json())
    cancel = "POST /workspace-assets/{asset_id}/preparation/cancel"
    assert (waiting[cancel]["state"], waiting[cancel]["code"]) == ("available", None)
    assert not api.drain().errors
    prepared = _capabilities(api.get(f"/workspace-assets/{admitted['asset_id']}").json())
    assert (prepared[cancel]["state"], prepared[cancel]["code"]) == (
        "unavailable",
        "preparation_finished",
    )
    # The descriptor says what the route answers.
    stopped = api.post(f"/workspace-assets/{admitted['asset_id']}/preparation/cancel")
    assert (stopped.status_code, stopped.json()["code"]) == (409, "preparation_finished")
    withdraw = prepared["POST /workspace-assets/{asset_id}/withdraw"]
    assert (withdraw["state"], withdraw["bind"]) == (
        "available",
        {"asset_id": admitted["asset_id"]},
    )


# -- the independent review's cases (deliveries/A2/delivery-2/schema-review-0126.txt) --------------


def _lose_prepared_bytes(api: AssetsApi, digest: str) -> None:
    for path in api.namespace_files():
        if path.name == digest:
            path.chmod(0o644)
            path.unlink()


def _requested_while_held(api: AssetsApi, asset: str, key: str) -> int:
    """Ask for the asset's preparation while another session holds the advisory lock ``key``."""
    with api.owner_database.session(api.stranger) as other:
        other.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (key,))
        try:
            return api.post(f"/workspace-assets/{asset}/preparation").status_code
        finally:
            other.execute("select pg_advisory_unlock(hashtextextended(%s, 0))", (key,))


def test_a_lock_on_identical_bytes_in_another_workspace_neither_delays_nor_shows(
    api: AssetsApi,
) -> None:
    view = api.admitted(cube().build())
    asset, digest = view["asset_id"], view["preparation"]["output"]["content_sha256"]
    _lose_prepared_bytes(api, digest)
    # The control: a write of this workspace's object in progress counts as present, so the
    # request answers with the prepared preparation rather than queueing another run.
    assert _requested_while_held(api, asset, workspace_asset_lock_key(api.owner, digest)) == 200
    # Another workspace writing the same bytes holds its own object's lock, which this one never
    # asks for: the missing bytes are prepared again.
    assert _requested_while_held(api, asset, workspace_asset_lock_key(api.stranger, digest)) == 202


def test_a_withdrawal_written_again_keeps_its_own_time(api: AssetsApi) -> None:
    """A restore writes a carried withdrawal again by the catalog's insert, with its own time."""
    asset = uuid.UUID(api.admit(cube().build()).json()["asset_id"])
    api.sql(
        "insert into workspace_asset_withdrawal (workspace_id, asset_id, withdrawn_by, "
        "withdrawn_at) values (%s, %s, %s, '2026-09-01T00:00:00Z')",
        api.owner,
        asset,
        uuid.uuid4(),
    )
    [row] = api.sql(
        "select withdrawn_at from workspace_asset_withdrawal where asset_id = %s", asset
    )
    assert row["withdrawn_at"] == datetime(2026, 9, 1, tzinfo=UTC)


# -- the retained-bytes limit ---------------------------------------------------------------------


def _retain_at_most(api: AssetsApi, limit: int) -> None:
    """Serve the same application with this workspace asset retained-bytes limit."""
    services = api.client.app.state.services
    api.client.app.state.services = dataclasses.replace(
        services,
        workspace_assets=WorkspaceAssetRuntime(stores=api.stores, retained_bytes_limit=limit),
    )


EDGE = pytest.mark.parametrize(
    ("slack", "fits"), [(1, True), (0, True), (-1, False)], ids=["under", "at", "over"]
)


@EDGE
def test_an_admission_crossing_the_retained_bytes_limit_is_refused_at_the_byte(
    api: AssetsApi, slack: int, fits: bool
) -> None:
    first, second = cube().build(), cube(scale=2.0).build()
    assert api.admit(first).status_code == 201
    limit = len(first) + len(second) + slack
    _retain_at_most(api, limit)
    admitted = api.admit(second)
    if fits:
        assert admitted.status_code == 201, admitted.text
        return
    assert (admitted.status_code, admitted.json()["code"]) == (429, QUOTA)
    assert f"retained-bytes limit of {limit} bytes" in admitted.json()["detail"]
    assert api.counts()["workspace_asset"] == 1
    assert api.counts()["workspace_asset_blob"] == 1


@EDGE
def test_a_preparation_whose_output_would_cross_the_limit_fails_by_name(
    api: AssetsApi, slack: int, fits: bool
) -> None:
    payload = cube().build()
    asset = api.admit(payload).json()["asset_id"]
    output = prepare_static_glb(
        payload, unit="metre", expected_dimensions_mm=None, decode_image=decode_texture
    ).output
    limit = len(payload) + len(output) + slack
    outcome = api.worker(retained_bytes_limit=limit).drain()
    assert not outcome.errors, outcome.errors
    preparation = api.get(f"/workspace-assets/{asset}").json()["preparation"]
    if fits:
        assert preparation["state"] == "prepared"
        return
    assert preparation["state"] == "failed"
    assert (preparation["failure"]["class"], preparation["failure"]["code"]) == (
        "quota_exceeded",
        QUOTA,
    )
    assert f"retained-bytes limit of {limit} bytes" in preparation["failure"]["message"]
    assert api.counts()["workspace_asset_blob"] == 1  # nothing recorded beyond the input
    assert hashlib.sha256(output).hexdigest() not in {path.name for path in api.namespace_files()}


def test_withdrawn_bytes_count_until_the_workspace_is_erased_and_identical_bytes_add_none(
    api: AssetsApi,
) -> None:
    first, second = cube().build(), cube(scale=2.0).build()
    withdrawn = api.admit(first).json()["asset_id"]
    assert api.post(f"/workspace-assets/{withdrawn}/withdraw").status_code == 200
    _retain_at_most(api, len(first) + len(second) - 1)
    assert api.admit(second).status_code == 429
    # The same bytes again are already held: a new admission of them adds nothing.
    _retain_at_most(api, len(first))
    again = api.admit(first, declaration(first, title="Oak bench, again"))
    assert again.status_code == 201, again.text


def test_readiness_states_the_retained_bytes_limit_and_no_count(api: AssetsApi) -> None:
    _retain_at_most(api, 123_456_789)
    assert api.admit(cube().build()).status_code == 201
    capacity = api.client.get("/readyz").json()["capacity"]
    assert capacity["workspace_assets"] == {"retained_bytes_per_workspace": 123_456_789}
