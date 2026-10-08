"""The namespace registry, and the stored kinds whose bytes live in its namespaces.

``exulanica.store.namespaces`` names every namespace once. What has to reach every namespace (the
stores a process builds, their listing for backup and restore, the sweep of unfinished writes, the
object store's check of which uploads are its own) reads the registry rather than a list of its
own, so a namespace added there needs no other change. The test that matters most here adds two
names to the registry in a fresh interpreter, edits nothing else, and watches both backends build,
list, resolve, sweep and recognise them.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from exulanica.db.session import Database
from exulanica.deletion import queue
from exulanica.deletion.queue import stored_target_store
from exulanica.deletion.worker import PurgeWorker
from exulanica.evidence.blob import BlobId
from exulanica.store.configured import local_content_stores
from exulanica.store.namespaces import SHARED_NAMESPACES, WORKSPACE_NAMESPACES

TESTS = Path(__file__).resolve().parent

#: Names an object key, a data directory and a backup set already carry, with their kind. Never
#: renamed and never moved between kinds; a new namespace is added beside them.
STABLE = {
    "blobs": "shared",
    "tiles": "shared",
    "materials": "per-workspace",
    "workspace-assets": "per-workspace",
    "looks": "per-workspace",
}


def test_the_registered_names_are_stable_single_segments():
    registered = {name: "shared" for name in SHARED_NAMESPACES} | {
        name: "per-workspace" for name in WORKSPACE_NAMESPACES
    }
    assert len(registered) == len(SHARED_NAMESPACES) + len(WORKSPACE_NAMESPACES), "a name twice"
    assert STABLE.items() <= registered.items()
    for name in registered:
        # One segment, so no namespace's directory or key prefix can lie inside another's.
        assert re.fullmatch(r"[a-z][a-z0-9-]*", name), name


# The child adds one name to each tuple of the registry before anything that reads it is
# imported, which is what adding them to the source would do, and changes nothing else.
_REGISTRY_ONLY = """
import json, os, sys, uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import exulanica.store.namespaces as registry

registry.SHARED_NAMESPACES = (*registry.SHARED_NAMESPACES, "fixture-shared")
registry.WORKSPACE_NAMESPACES = (*registry.WORKSPACE_NAMESPACES, "fixture-workspaces")

from exulanica.store.configured import (
    local_content_stores, object_content_stores, sweep_incomplete_writes,
)
from exulanica.store.object import ObjectRequests, ObjectStoreCredentials, ObjectStoreLocation
from object_store_double import S3Double

data, workspace = Path(sys.argv[2]), uuid.UUID(hex=sys.argv[3])
now = datetime(2026, 9, 30, 12, tzinfo=UTC)
double = S3Double(clock=lambda: now)
location = ObjectStoreLocation(
    endpoint="http://127.0.0.1:19446", bucket="exulanica-test", region="us-east-1", prefix="exu"
)
credentials = ObjectStoreCredentials("runtime-key", "runtime-secret")
remote = object_content_stores(
    location, credentials, spool_directory=data / "spool", transport=double.transport(),
    now=lambda: now, sleep=lambda _seconds: None,
)
local_root = data / "local"
local = local_content_stores(local_root)
for stores in (local, remote):
    stores.shared("fixture-shared").put_bytes(b"in the shared fixture")
    stores.per_workspace("fixture-workspaces").for_workspace(workspace).put_bytes(b"in a workspace")

requests = ObjectRequests(location, credentials, transport=double.transport(), now=lambda: now)
digest = "ab" * 32
for key in (
    f"exu/fixture-shared/sha-256/ab/ab/{digest}",
    f"exu/fixture-workspaces/{workspace.hex}/sha-256/ab/ab/{digest}",
    f"exu/unregistered/sha-256/ab/ab/{digest}",
):
    requests.create_upload(key)
for path in (
    local_root / "fixture-shared" / "sha-256" / "_incoming" / "put-a",
    local_root / "fixture-workspaces" / workspace.hex / "sha-256" / "_incoming" / "put-b",
):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"partial")
    os.utime(path, (0, 0))
later = now + timedelta(days=2)
remote_swept = sweep_incomplete_writes(remote, older_than=timedelta(days=1), now=later)
local_swept = sweep_incomplete_writes(local, older_than=timedelta(days=1), now=later)
print(json.dumps({
    "local": [name for name, _store in local.namespaces()],
    "object": [name for name, _store in remote.namespaces()],
    "resolved": [
        sorted(blob.hex for blob in stores.namespace(name).iter_blob_ids())
        for stores in (local, remote)
        for name in ("fixture-shared", f"fixture-workspaces/{workspace.hex}")
    ],
    "local_paths": sorted(
        p.relative_to(local_root).as_posix() for p in local_root.rglob("*") if p.is_file()
    ),
    "object_keys": [key.removeprefix("exu/") for key in double.stored_keys()],
    "uploads_aborted": remote_swept.uploads_aborted,
    "uploads_left": sorted(upload.key for upload in requests.iter_uploads("exu/")),
    "files_removed": local_swept.files_removed,
}))
"""


def test_a_namespace_added_only_to_the_registry_is_built_listed_swept_and_recognised(tmp_path):
    assert "fixture-shared" not in SHARED_NAMESPACES, "the child's names must be its own"
    workspace = uuid.uuid4()
    completed = subprocess.run(
        [sys.executable, "-c", _REGISTRY_ONLY, str(TESTS), str(tmp_path), workspace.hex],
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    facts = json.loads(completed.stdout)
    added = ["fixture-shared", f"fixture-workspaces/{workspace.hex}"]
    # Listed by both backends, by the names a backup set records, after the registered ones.
    assert facts["local"] == facts["object"] == [*SHARED_NAMESPACES, *added]
    # Resolved by name to the stores holding what was written there.
    shared, own = BlobId.of_bytes(b"in the shared fixture"), BlobId.of_bytes(b"in a workspace")
    assert facts["resolved"] == [[shared.hex], [own.hex]] * 2
    # One key on either backend, the local path under the data directory.
    assert facts["local_paths"] == facts["object_keys"]
    assert [key.split("/sha-256/")[0] for key in facts["object_keys"]] == added
    # Swept: a stale upload and a stale temporary file in each new namespace, while an upload
    # under a name nothing registers is somebody else's and stays.
    assert facts["uploads_aborted"] == 2
    assert facts["uploads_left"] == [f"exu/unregistered/sha-256/ab/ab/{'ab' * 32}"]
    assert facts["files_removed"] == 2


# -- stored kinds ----------------------------------------------------------------------------------


def test_every_stored_kind_names_a_registered_namespace():
    assert tuple(queue.STORED_KIND_NAMESPACES) == queue.STORED_KINDS
    registered = {*SHARED_NAMESPACES, *WORKSPACE_NAMESPACES}
    assert set(queue.STORED_KIND_NAMESPACES.values()) <= registered
    # Every destroyable kind but one names stored bytes; that one, embedding, is a database row.
    assert set(queue.STORED_KINDS) <= set(queue.DESTROYABLE_KINDS)
    assert set(queue.DESTROYABLE_KINDS) - set(queue.STORED_KINDS) == {"embedding"}


def test_a_stored_target_resolves_to_the_store_its_bytes_live_in(tmp_path):
    stores = local_content_stores(tmp_path)
    workspace = uuid.uuid4()
    assert stored_target_store(stores, "blob", workspace) is stores.blobs
    assert stored_target_store(stores, "artifact", workspace) is stores.blobs
    bake = stored_target_store(stores, "material_bake", workspace).put_bytes(b"a bake").blob_id
    assert stores.materials.for_workspace(workspace).exists(bake)
    assert not stores.blobs.exists(bake)
    assert not stores.materials.for_workspace(uuid.uuid4()).exists(bake)
    with pytest.raises(ValueError):
        stored_target_store(stores, "embedding", workspace)


def test_a_worker_built_over_the_stores_claims_every_kind_it_can_destroy(tmp_path):
    stores = local_content_stores(tmp_path)
    database = Database(url="postgresql://never-connected.invalid/none")
    assert PurgeWorker.over(database, stores, frozenset())._kinds == queue.DESTROYABLE_KINDS
    # A worker handed fewer namespaces claims fewer kinds, which is what this would catch.
    assert "material_bake" not in PurgeWorker(database, stores.blobs, frozenset())._kinds
