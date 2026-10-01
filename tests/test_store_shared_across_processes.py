"""Separate processes share one S3-compatible store, and nothing on a local disk.

The API runs in this test's process. The derivative worker, the material bake worker and the purge
command each run as a process of their own, with a data directory of their own, so what they share
is the database and the bucket that ``tests/object_store_double.py`` serves on a loopback socket.
What the API writes a worker reads, what a worker writes the API serves, and the purge command
erases with an identity no other process holds. None of the processes creates a local store.

``EXULANICA_TEST_OBJECT_STORE`` may name a JSON file describing a real endpoint (``endpoint``,
``bucket``, ``region``, and ``runtime`` and ``purge`` identities each with ``access_key_id`` and
``secret_access_key``); the same flows then run against it under a fresh prefix, without the
double's request log and fault injection, which only the double has.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import urllib.parse
import uuid
from pathlib import Path

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.roles import (
    PURGE_ROLE,
    RUNTIME_ROLE,
    provision_purge_role,
    provision_runtime_role,
)
from exulanica.env import env_get
from exulanica.evidence.blob import BlobId
from exulanica.migrations import migrations
from exulanica.store.configured import content_stores
from exulanica.store.object import ObjectRequests, ObjectStoreCredentials, ObjectStoreLocation
from exulanica.world.material_recipes import MaterialRuntime
from exulanica.world.texture_assets import load_material_catalog
from fastapi.testclient import TestClient

from conftest import photo_bytes
from object_store_double import S3Double, serve
from test_material_recipes import METAL, _real_runtime, _small
from tests_support_api import EVERY_PERMISSION, scratch_database

pytestmark = pytest.mark.postgres

_TOKEN = "shared-store-owner-token-long-enough-to-accept"
_APP = f"{RUNTIME_ROLE}_shared_store"
_PURGER = f"{PURGE_ROLE}_shared_store"
#: Generated for the run, never committed, as tests/test_purge.py does for its roles.
_APP_PASSWORD = secrets.token_urlsafe(24)
_PURGER_PASSWORD = secrets.token_urlsafe(24)


class Shared:
    def __init__(
        self, client, double, repository, scratch, tmp_path, environment, peek, purge
    ) -> None:
        self.client = client
        #: The in-repo double, or None against a real endpoint.
        self.double = double
        self.repository = repository
        self.scratch = scratch
        self.tmp_path = tmp_path
        self.environment = environment
        self.peek = peek
        self.purge = purge

    def call(self, method: str, path: str, **kwargs):
        headers = {"Authorization": f"Bearer {_TOKEN}"}
        return self.client.request(method, path, headers=headers, **kwargs)

    def rows(self, sql: str, *params):
        return self.repository.connection.execute(sql, params).fetchall()

    def url(self, role: str, password: str) -> str:
        base = env_get("TEST_DATABASE_URL")
        assert base is not None
        options = urllib.parse.quote(f"-csearch_path={self.scratch},public", safe="")
        parsed = urllib.parse.urlsplit(f"{base}{'&' if '?' in base else '?'}options={options}")
        netloc = f"{role}:{password}@{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")
        return urllib.parse.urlunsplit(parsed._replace(netloc=netloc))

    def run(self, command: str, *arguments: str, name: str, expect: int = 0, **extra: str) -> dict:
        """Run a console script as its own process, with a data directory nothing else uses.

        The console scripts are what an installation runs (``[project.scripts]``), so the test
        starts the same entry points rather than ``python -m``."""
        directory = self.tmp_path / name
        directory.mkdir()
        environment = {
            "PATH": os.environ["PATH"],
            "HOME": str(directory),
            "EXULANICA_DATA_DIR": str(directory),
            **self.environment,
            **extra,
        }
        completed = subprocess.run(
            [str(Path(sys.executable).parent / command), *arguments],
            cwd=directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert completed.returncode == expect, completed.stdout + completed.stderr
        local = sorted(
            p.name for p in directory.iterdir() if p.name in ("blobs", "materials", "tiles")
        )
        assert local == [], f"{name} built a local store: {local}"
        return {"stdout": completed.stdout, "stderr": completed.stderr}


@pytest.fixture
def shared(tmp_path, repository, spine_schema, monkeypatch):
    _psycopg, scratch = spine_schema
    owner = scratch_database(scratch)
    with owner.unscoped() as connection:
        connection.execute(f"set search_path to {scratch}, public")
        provision_runtime_role(connection, role=_APP, password=_APP_PASSWORD)
        provision_purge_role(connection, role=_PURGER, password=_PURGER_PASSWORD)
        # The harness applies migration files directly; a command verifies the bookkeeping too.
        for migration in migrations():
            connection.execute(
                "insert into schema_migrations (version, checksum) values (%s, %s) "
                "on conflict (version) do nothing",
                (migration.version, migration.checksum),
            )
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                _TOKEN: {
                    "workspace_id": str(repository.workspace_id),
                    "actor": str(uuid.uuid4()),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    named = os.environ.get("EXULANICA_TEST_OBJECT_STORE")
    if named:
        settings = json.loads(Path(named).read_text(encoding="utf-8"))
        yield from _serving(
            None,
            settings["endpoint"],
            settings,
            prefix=f"installation-{uuid.uuid4().hex[:12]}",
            owner=owner,
            repository=repository,
            scratch=scratch,
            tmp_path=tmp_path,
        )
        return
    double = S3Double()
    with serve(double) as endpoint:
        identities = {
            "bucket": double.bucket,
            "region": double.region,
            "runtime": {"access_key_id": "runtime-key", "secret_access_key": "runtime-secret"},
            "purge": {"access_key_id": "purge-key", "secret_access_key": "purge-secret"},
        }
        yield from _serving(
            double,
            endpoint,
            identities,
            prefix="installation",
            owner=owner,
            repository=repository,
            scratch=scratch,
            tmp_path=tmp_path,
        )


def _serving(double, endpoint, settings, *, prefix, owner, repository, scratch, tmp_path):
    runtime, purge = settings["runtime"], settings["purge"]
    environment = {
        "EXULANICA_STORE_KIND": "object",
        "EXULANICA_OBJECT_STORE_ENDPOINT": endpoint,
        "EXULANICA_OBJECT_STORE_BUCKET": settings["bucket"],
        "EXULANICA_OBJECT_STORE_REGION": settings["region"],
        "EXULANICA_OBJECT_STORE_PREFIX": prefix,
        "EXULANICA_OBJECT_STORE_ACCESS_KEY_ID": runtime["access_key_id"],
        "EXULANICA_OBJECT_STORE_SECRET_ACCESS_KEY": runtime["secret_access_key"],
    }
    api_directory = tmp_path / "api"
    stores = content_stores({**environment, "EXULANICA_DATA_DIR": str(api_directory)})
    reader = ObjectRequests(
        ObjectStoreLocation(
            endpoint=endpoint, bucket=settings["bucket"], region=settings["region"], prefix=prefix
        ),
        ObjectStoreCredentials(runtime["access_key_id"], runtime["secret_access_key"]),
    )

    def peek(key: str) -> bytes | None:
        response = reader.get(f"{prefix}/{key}")
        if response is None:
            return None
        try:
            return response.read()
        finally:
            response.close()

    services = Services(
        database=owner,
        readonly_database=owner,
        store=stores.blobs,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
        materials=MaterialRuntime(catalog=load_material_catalog(), stores=stores.materials),
        tiles=stores.tiles,
    )
    purge_environment = {
        "EXULANICA_OBJECT_STORE_PURGE_ACCESS_KEY_ID": purge["access_key_id"],
        "EXULANICA_OBJECT_STORE_PURGE_SECRET_ACCESS_KEY": purge["secret_access_key"],
    }
    with TestClient(create_app(services, verify=False)) as client:
        yield Shared(
            client, double, repository, scratch, tmp_path, environment, peek, purge_environment
        )
    assert not (api_directory / "blobs").exists() and not (api_directory / "tiles").exists()


def _screen(shared: Shared) -> None:
    """A synthetic exemption for every live capture, as tests/test_intake_upload.py records it."""
    from exulanica.ingest.privacy import authorize_synthetic_capture, record_synthetic_exemption

    for row in shared.rows("select capture_id from capture where deleted_at is null"):
        authorization = authorize_synthetic_capture(
            shared.repository,
            capture_id=row["capture_id"],
            actor=uuid.UUID("a244f9d0-9bd9-5f55-a133-2712cd05d720"),
            generator_manifest={
                "profile": "exulanica.synthetic-test-corpus/v1",
                "notice": "SYNTHETIC TEST FIXTURE",
            },
            authorization_scope={"purpose": "shared store test"},
        )
        record_synthetic_exemption(
            shared.repository, authorization_id=authorization.authorization_id
        )


def _object(shared: Shared, namespace: str, storage_key: str) -> bytes | None:
    return shared.peek(f"{namespace}/{storage_key}")


def test_a_worker_process_reads_the_api_s_original_and_the_purger_erases_both(shared):
    photograph = photo_bytes()
    accepted = shared.call(
        "POST", "/intake", files=[("files", ("a.jpg", photograph, "image/jpeg"))]
    )
    assert accepted.status_code == 202, accepted.text
    original = BlobId.of_bytes(photograph)
    [blob] = shared.rows("select storage_key from blob where blob_sha256 = %s", original.digest)
    assert _object(shared, "blobs", blob["storage_key"]) == photograph

    _screen(shared)
    workspace = str(shared.repository.workspace_id)
    shared.run(
        "exulanica-derivative-worker",
        "--workspace",
        workspace,
        "--once",
        name="derivative-worker",
        EXULANICA_DATABASE_URL=shared.url(_APP, _APP_PASSWORD),
    )
    renditions = shared.rows(
        "select content_sha256, storage_key from artifact where kind = 'rendition'"
    )
    assert renditions, "the worker process wrote no rendition"
    for rendition in renditions:
        stored = _object(shared, "blobs", rendition["storage_key"])
        assert stored is not None
        assert hashlib.sha256(stored).digest() == bytes(rendition["content_sha256"])

    # Erasure, in a third process holding the one identity that may delete.
    [capture] = shared.rows("select capture_id from capture")
    shared.repository.insert_tombstone(
        scope="capture",
        capture_id=capture["capture_id"],
        requested_by=uuid.uuid4(),
        reason="the user deleted this photograph",
    )
    outcome = shared.run(
        "exulanica-purge",
        "--workspace",
        workspace,
        name="purge",
        EXULANICA_PURGE_DATABASE_URL=shared.url(_PURGER, _PURGER_PASSWORD),
        **shared.purge,
    )
    assert "failed           0" in outcome["stdout"], outcome["stdout"]
    assert _object(shared, "blobs", blob["storage_key"]) is None
    for rendition in renditions:
        assert _object(shared, "blobs", rendition["storage_key"]) is None
    if shared.double is not None:
        deletions = [
            entry
            for entry in shared.double.log
            if entry[0] == "DELETE" and "uploadId" not in entry[3]
        ]
        assert deletions and {entry[2] for entry in deletions} == {"purge-key"}


def test_the_api_serves_a_texture_a_worker_process_baked(shared):
    # The worker process bakes with the real baker, which needs web/node_modules; without it the
    # test skips under the reason tests/expected_skips.toml accepts only where that is missing.
    _real_runtime()
    created = shared.call(
        "POST",
        "/materials/recipes",
        json={"recipe": _small(METAL), "based_on": {"set_id": METAL, "version": 1}},
    )
    assert created.status_code == 201, created.text
    recipe_id = created.json()["recipe_id"]
    requested = shared.call("POST", f"/materials/recipes/{recipe_id}/bake")
    assert requested.status_code in (200, 202), requested.text

    worker = shared.run(
        "exulanica-material-bake",
        "--workspace",
        str(shared.repository.workspace_id),
        "--once",
        name="material-bake-worker",
        EXULANICA_DATABASE_URL=shared.url(_APP, _APP_PASSWORD),
    )
    events = [json.loads(line) for line in worker["stdout"].splitlines() if line.startswith("{")]
    stopped = [event for event in events if event.get("event") == "stopped"]
    assert stopped and stopped[-1]["baked"] == 1, worker["stdout"] + worker["stderr"]
    bake = shared.call("GET", f"/materials/recipes/{recipe_id}/bake")
    assert bake.status_code == 200 and bake.json()["state"] == "baked", bake.text
    served = shared.call("GET", f"/materials/recipes/{recipe_id}/bake/bytes")
    assert served.status_code == 200, served.text
    digest = hashlib.sha256(served.content).hexdigest()
    workspace = shared.repository.workspace_id.hex
    namespaced = f"materials/{workspace}/sha-256/{digest[:2]}/{digest[2:4]}/{digest}"
    assert shared.peek(namespaced) == served.content
    if shared.double is None:
        return  # the double alone can make the endpoint unreachable on request

    # The same read with the endpoint unreachable is the store's refusal, not an unhandled 500.
    import httpx

    shared.double.inject(
        lambda method, key, params: method == "GET" and key is not None,
        httpx.ConnectError("the endpoint is down"),
        times=8,
    )
    unavailable = shared.call("GET", f"/materials/recipes/{recipe_id}/bake/bytes")
    assert unavailable.status_code == 503, unavailable.text
    assert unavailable.json() == {"code": "store_unavailable", "detail": "object_store_unreachable"}
    assert unavailable.headers["retry-after"] == "30"

    # A bucket the store refuses to trust answers the same code with its reason, and no
    # Retry-After: waiting does not help until its operator changes the bucket. The guard's own
    # schedule is a five-minute one, so the test asks it to look again now.
    shared.double.faults.clear()
    shared.double.public_list = True
    services = shared.client.app.state.services
    services.materials.stores._guard._until = 0.0
    refused = shared.call("GET", f"/materials/recipes/{recipe_id}/bake/bytes")
    assert refused.status_code == 503, refused.text
    assert refused.json() == {
        "code": "store_unavailable",
        "detail": "object_store_publicly_listable",
    }
    assert "retry-after" not in refused.headers


def test_a_worker_process_handed_the_purge_identity_refuses_to_start(shared):
    before = len(shared.double.log) if shared.double is not None else 0
    outcome = shared.run(
        "exulanica-derivative-worker",
        "--workspace",
        str(shared.repository.workspace_id),
        "--once",
        name="misconfigured-worker",
        expect=1,
        EXULANICA_DATABASE_URL=shared.url(_APP, _APP_PASSWORD),
        EXULANICA_OBJECT_STORE_PURGE_SECRET_ACCESS_KEY="purge-secret",
    )
    assert "EXULANICA_OBJECT_STORE_PURGE_SECRET_ACCESS_KEY" in outcome["stdout"]
    assert "purge-secret" not in outcome["stdout"] + outcome["stderr"]
    if shared.double is not None:
        assert len(shared.double.log) == before, "it refused before reaching the store"
