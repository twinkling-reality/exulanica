"""A namespace registered only in the store registry is backed up, restored and purged.

Backup, verification, restore and the backup copy's purge take every namespace name from
``ContentStores.namespaces()`` and resolve it with ``ContentStores.namespace(name)``; a stored
kind's bytes are found through ``stored_target_store``. A child interpreter adds a shared and a
per-workspace namespace, and a stored kind kept in the second, before anything that reads them is
imported, which is what adding them to the source would do, and changes nothing else.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from exulanica.store.namespaces import SHARED_NAMESPACES, WORKSPACE_NAMESPACES

TESTS = Path(__file__).resolve().parent

_REGISTRY_ONLY = """
import json, sys, uuid
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, sys.argv[1])
import exulanica.store.namespaces as registry

registry.SHARED_NAMESPACES = (*registry.SHARED_NAMESPACES, "fixture-shared")
registry.WORKSPACE_NAMESPACES = (*registry.WORKSPACE_NAMESPACES, "fixture-workspaces")

import exulanica.deletion.queue as queue

queue.STORED_KIND_NAMESPACES = MappingProxyType(
    {**queue.STORED_KIND_NAMESPACES, "fixture_asset": "fixture-workspaces"}
)
queue.STORED_KINDS = tuple(queue.STORED_KIND_NAMESPACES)

from exulanica.orchestration.installation.backup_set import _copy
from exulanica.orchestration.installation.maintenance import MaintenanceStores
from exulanica.orchestration.installation.recovery import Target, restore_bytes
from exulanica.store.base import PurgeAuthorization, privileged_purger
from exulanica.store.configured import local_content_stores, object_content_stores
from exulanica.store.object import ObjectStoreCredentials, ObjectStoreLocation
from object_store_double import S3Double

data, live_kind, workspace = Path(sys.argv[2]), sys.argv[3], uuid.UUID(hex=sys.argv[4])
if live_kind == "object":
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    live = object_content_stores(
        ObjectStoreLocation(
            endpoint="http://127.0.0.1:19446", bucket="exulanica-test", region="us-east-1",
            prefix="exu",
        ),
        ObjectStoreCredentials("purge-key", "purge-secret"),
        spool_directory=data / "spool",
        transport=S3Double(clock=lambda: now).transport(),
        now=lambda: now,
        sleep=lambda _seconds: None,
        purging=True,
    )
else:
    live = local_content_stores(data / "live")
shared = live.shared("fixture-shared").put_bytes(b"in the shared fixture").blob_id
mine = live.per_workspace("fixture-workspaces").for_workspace(workspace)
held = mine.put_bytes(b"in a workspace").blob_id

pairs = MaintenanceStores(live=live, backup=local_content_stores(data / "backup"))
keys = [key for namespace in pairs.namespaces() for key in _copy(namespace)]
backup_set = data / "set"
backup_set.mkdir()
(backup_set / "keys.txt").write_text("".join(f"{key}\\n" for key in keys))
target = Target("unused", "unused", "unused", stores=local_content_stores(data / "target"))
copied, withheld = restore_bytes(backup_set, pairs.backup_for, target, erased=())
names = ("fixture-shared", f"fixture-workspaces/{workspace.hex}")
restored = [
    sorted(blob.hex for blob in target.stores.namespace(name).iter_blob_ids()) for name in names
]

authorization = PurgeAuthorization(tombstone_id="t", actor="a", reason="the fixture's purge")
privileged_purger(mine, authorization).purge(held)
purged = pairs.purge_backup_copy("fixture_asset", workspace, held, authorization)
print(json.dumps({
    "keys": sorted(keys),
    "copied": copied,
    "withheld": withheld,
    "restored": restored,
    "purged": purged,
    "backup_still_holds": pairs.backup_for(names[1]).exists(held),
    "shared": shared.hex,
    "held": held.hex,
}))
"""


@pytest.mark.parametrize("live_kind", ["local", "object"])
def test_a_namespace_added_only_to_the_registry_is_backed_up_restored_and_purged(
    tmp_path, live_kind
):
    assert "fixture-shared" not in SHARED_NAMESPACES, "the child's names must be its own"
    assert "fixture-workspaces" not in WORKSPACE_NAMESPACES
    workspace = uuid.UUID(int=7)
    completed = subprocess.run(
        [sys.executable, "-c", _REGISTRY_ONLY, str(TESTS), str(tmp_path), live_kind, workspace.hex],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    shared, held = result["shared"], result["held"]
    assert {f"fixture-shared/{shared}", f"fixture-workspaces/{workspace.hex}/{held}"} <= set(
        result["keys"]
    )
    assert result["copied"] == len(result["keys"]) == 2 and result["withheld"] == 0
    assert result["restored"] == [[shared], [held]]
    assert result["purged"] == 1 and result["backup_still_holds"] is False
