"""Choosing a process's content store from its settings, in the one place every process uses.

The local default must stay exactly what processes built before the choice existed: the same
classes over the same directories, built only when used. The object store must refuse every
malformed setting by name without printing its value, and a runtime process must refuse to start
holding the purge identity's credentials.
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from exulanica.errors import ObjectStoreConfigurationError
from exulanica.store import LocalContentAddressedStore, LocalWorkspaceStores
from exulanica.store import configured as configured_module
from exulanica.store.configured import (
    OBJECT_STORE_SETTINGS,
    PURGE_CREDENTIAL_SETTINGS,
    content_stores,
    local_content_stores,
    purging_content_stores,
)
from exulanica.store.object import (
    ObjectContentAddressedStore,
    ObjectWorkspaceStores,
    PurgingObjectContentAddressedStore,
)

ROOT = Path(__file__).resolve().parents[1]


def _object_environment(tmp_path: Path, **overrides: str) -> dict[str, str]:
    return {
        "EXULANICA_DATA_DIR": str(tmp_path / "data"),
        "EXULANICA_STORE_KIND": "object",
        "EXULANICA_OBJECT_STORE_ENDPOINT": "https://store.example",
        "EXULANICA_OBJECT_STORE_BUCKET": "exulanica-test",
        "EXULANICA_OBJECT_STORE_REGION": "eu-north1",
        "EXULANICA_OBJECT_STORE_PREFIX": "exu",
        "EXULANICA_OBJECT_STORE_ACCESS_KEY_ID": "runtime-key",
        "EXULANICA_OBJECT_STORE_SECRET_ACCESS_KEY": "runtime-secret-value",
        **overrides,
    }


# -- the local default -----------------------------------------------------------------------------


def test_the_default_is_the_local_store_the_data_directory_always_held(tmp_path):
    stores = content_stores({"EXULANICA_DATA_DIR": str(tmp_path)})
    assert stores.kind == "local"
    assert isinstance(stores.blobs, LocalContentAddressedStore)
    assert stores.blobs.root == (tmp_path / "blobs").resolve()
    assert isinstance(stores.materials, LocalWorkspaceStores)
    assert stores.materials.root == (tmp_path / "materials").resolve()
    assert stores.tiles.root == (tmp_path / "tiles").resolve()  # type: ignore[attr-defined]
    assert content_stores(
        {"EXULANICA_DATA_DIR": str(tmp_path), "EXULANICA_STORE_KIND": ""}
    ).kind == ("local")


def test_a_local_store_is_built_only_when_it_is_used(tmp_path):
    stores = content_stores({"EXULANICA_DATA_DIR": str(tmp_path)})
    assert list(tmp_path.iterdir()) == []
    stores.tiles  # noqa: B018 - using it is what builds it
    assert [path.name for path in tmp_path.iterdir()] == ["tiles"]


def test_an_explicit_directory_wins_over_the_environment(tmp_path):
    stores = content_stores(
        {"EXULANICA_DATA_DIR": str(tmp_path / "ignored")}, data_dir=tmp_path / "chosen"
    )
    assert stores.blobs.root == (tmp_path / "chosen" / "blobs").resolve()  # type: ignore[attr-defined]


def test_the_local_default_loads_no_http_client_for_its_store(tmp_path):
    program = (
        "import sys\n"
        "from exulanica.store.configured import content_stores\n"
        f"stores = content_stores({{'EXULANICA_DATA_DIR': {str(tmp_path)!r}}})\n"
        "stores.blobs.put_bytes(b'x')\n"
        "print('httpx' in sys.modules)\n"
    )
    run = subprocess.run(
        [sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert run.stdout.strip() == "False"


def test_an_unknown_kind_is_refused_by_name(tmp_path):
    with pytest.raises(ObjectStoreConfigurationError, match="EXULANICA_STORE_KIND"):
        content_stores({"EXULANICA_DATA_DIR": str(tmp_path), "EXULANICA_STORE_KIND": "s3"})


# -- the object store ------------------------------------------------------------------------------


def test_object_settings_build_runtime_stores_that_cannot_erase(tmp_path):
    stores = content_stores(_object_environment(tmp_path))
    assert stores.kind == "object"
    assert type(stores.blobs) is ObjectContentAddressedStore
    assert stores.blobs.namespace == "exu/blobs"  # type: ignore[attr-defined]
    assert stores.tiles.namespace == "exu/tiles"  # type: ignore[attr-defined]
    assert isinstance(stores.materials, ObjectWorkspaceStores)
    workspace = uuid.uuid4()
    assert stores.materials.for_workspace(workspace).namespace == f"exu/materials/{workspace.hex}"
    assert type(stores.materials.for_workspace(workspace)) is ObjectContentAddressedStore
    described = stores.describe()
    assert described["kind"] == "object" and described["purge_capable"] is False
    assert described["transport"] == "https"
    assert described["bucket_check"] == {"state": "unchecked", "code": None}


def test_purging_stores_use_only_the_purge_identity(tmp_path):
    environment = _object_environment(
        tmp_path,
        EXULANICA_OBJECT_STORE_PURGE_ACCESS_KEY_ID="purge-key",
        EXULANICA_OBJECT_STORE_PURGE_SECRET_ACCESS_KEY="purge-secret-value",
    )
    del environment["EXULANICA_OBJECT_STORE_ACCESS_KEY_ID"]
    del environment["EXULANICA_OBJECT_STORE_SECRET_ACCESS_KEY"]
    stores = purging_content_stores(environment)
    assert type(stores.blobs) is PurgingObjectContentAddressedStore
    assert type(stores.materials.for_workspace(uuid.uuid4())) is PurgingObjectContentAddressedStore
    assert stores.describe()["purge_capable"] is True
    without = _object_environment(tmp_path)
    with pytest.raises(ObjectStoreConfigurationError, match="PURGE_ACCESS_KEY_ID"):
        purging_content_stores(without)


def test_purging_stores_on_the_local_default_are_the_local_stores(tmp_path):
    stores = purging_content_stores({"EXULANICA_DATA_DIR": str(tmp_path)})
    assert isinstance(stores.blobs, LocalContentAddressedStore)


@pytest.mark.parametrize("setting", PURGE_CREDENTIAL_SETTINGS)
@pytest.mark.parametrize("kind", ["local", "object"])
def test_a_runtime_process_refuses_to_hold_the_purge_identity(tmp_path, setting, kind):
    environment = _object_environment(tmp_path, EXULANICA_STORE_KIND=kind, **{setting: "x"})
    with pytest.raises(ObjectStoreConfigurationError) as refused:
        content_stores(environment)
    assert refused.value.code == "object_store_purge_credentials_in_runtime"
    assert setting in str(refused.value)


@pytest.mark.parametrize(
    ("missing", "named"),
    [
        ("EXULANICA_OBJECT_STORE_ENDPOINT", "EXULANICA_OBJECT_STORE_ENDPOINT"),
        ("EXULANICA_OBJECT_STORE_BUCKET", "EXULANICA_OBJECT_STORE_BUCKET"),
        ("EXULANICA_OBJECT_STORE_REGION", "EXULANICA_OBJECT_STORE_REGION"),
        ("EXULANICA_OBJECT_STORE_ACCESS_KEY_ID", "EXULANICA_OBJECT_STORE_ACCESS_KEY_ID"),
        ("EXULANICA_OBJECT_STORE_SECRET_ACCESS_KEY", "EXULANICA_OBJECT_STORE_SECRET_ACCESS_KEY"),
    ],
)
def test_a_missing_object_setting_is_named(tmp_path, missing, named):
    environment = _object_environment(tmp_path)
    del environment[missing]
    with pytest.raises(ObjectStoreConfigurationError, match=named):
        content_stores(environment)


def test_a_secret_can_come_from_a_file_and_never_from_both(tmp_path):
    secret_file = tmp_path / "secret"
    secret_file.write_text("runtime-secret-from-file\n", encoding="utf-8")
    environment = _object_environment(
        tmp_path, EXULANICA_OBJECT_STORE_SECRET_ACCESS_KEY_FILE=str(secret_file)
    )
    with pytest.raises(ObjectStoreConfigurationError, match="not both") as refused:
        content_stores(environment)
    assert "runtime-secret" not in str(refused.value)
    del environment["EXULANICA_OBJECT_STORE_SECRET_ACCESS_KEY"]
    assert content_stores(environment).kind == "object"
    secret_file.write_text("  \n", encoding="utf-8")
    with pytest.raises(ObjectStoreConfigurationError, match="empty file"):
        content_stores(environment)
    environment["EXULANICA_OBJECT_STORE_SECRET_ACCESS_KEY_FILE"] = str(tmp_path / "absent")
    with pytest.raises(ObjectStoreConfigurationError, match="cannot be read"):
        content_stores(environment)


@pytest.mark.parametrize(
    "overrides",
    [
        {"EXULANICA_OBJECT_STORE_ENDPOINT": "http://store.example"},
        {"EXULANICA_OBJECT_STORE_PLAINTEXT": "yes"},
        {"EXULANICA_OBJECT_STORE_ADDRESSING": "sideways"},
        {"EXULANICA_OBJECT_STORE_PREFIX": "/exu"},
        {"EXULANICA_OBJECT_STORE_BUCKET": "Bad_Bucket"},
        {"EXULANICA_OBJECT_STORE_SECRET_ACCESS_KEY": "has space"},
    ],
)
def test_a_malformed_object_setting_is_refused_without_its_value(tmp_path, overrides):
    with pytest.raises(ObjectStoreConfigurationError) as refused:
        content_stores(_object_environment(tmp_path, **overrides))
    assert refused.value.code == "object_store_misconfigured"
    for value in overrides.values():
        if value not in ("yes", "sideways"):
            assert value not in str(refused.value)


def test_plain_http_to_a_private_network_needs_the_acknowledgement(tmp_path):
    environment = _object_environment(
        tmp_path,
        EXULANICA_OBJECT_STORE_ENDPOINT="http://seaweedfs:8333",
        EXULANICA_OBJECT_STORE_PLAINTEXT="private-network",
    )
    assert content_stores(environment).describe()["transport"] == "http_private_network"


class _Recording(dict):
    """An environment that remembers every name the code looked up."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.read: set[str] = set()

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def __contains__(self, key) -> bool:
        self.read.add(key)
        return super().__contains__(key)


def test_the_settings_list_names_every_setting_the_module_reads(tmp_path):
    """Observed from what the code reads, not retyped, so a new setting cannot miss the list."""
    runtime = _Recording(_object_environment(tmp_path))
    content_stores(runtime)
    purge = _Recording(
        _object_environment(
            tmp_path,
            EXULANICA_OBJECT_STORE_PURGE_ACCESS_KEY_ID="purge-key",
            EXULANICA_OBJECT_STORE_PURGE_SECRET_ACCESS_KEY="purge-secret-value",
        )
    )
    purging_content_stores(purge)
    read = {name for name in runtime.read | purge.read if name != "EXULANICA_DATA_DIR"}
    assert read <= set(OBJECT_STORE_SETTINGS), read - set(OBJECT_STORE_SETTINGS)
    assert set(OBJECT_STORE_SETTINGS) <= read, set(OBJECT_STORE_SETTINGS) - read


# -- locations -------------------------------------------------------------------------------------


def test_a_location_identifier_names_a_store_without_naming_it(tmp_path):
    first = content_stores(_object_environment(tmp_path))
    same = content_stores(
        _object_environment(tmp_path, EXULANICA_OBJECT_STORE_ENDPOINT="https://STORE.example:443/")
    )
    elsewhere = content_stores(
        _object_environment(tmp_path, EXULANICA_OBJECT_STORE_PREFIX="backup")
    )
    assert first.location_sha256 == same.location_sha256 != elsewhere.location_sha256
    described = str(first.describe())
    for value in ("store.example", "exulanica-test", "runtime-key", "runtime-secret-value"):
        assert value not in described
    assert re.fullmatch(r"[0-9a-f]{64}", first.describe()["location_sha256"])
    local = local_content_stores(tmp_path / "a")
    assert local.location_sha256 != local_content_stores(tmp_path / "b").location_sha256


@pytest.mark.parametrize(
    ("live", "other", "overlapping"),
    [
        ("exu", "exu", True),
        ("exu", "exu/backup", True),
        ("exu/backup", "exu", True),
        ("", "backup", True),
        ("exu", "exu-backup", False),
        ("exu", "backup", False),
    ],
)
def test_overlapping_object_locations_are_recognised(tmp_path, live, other, overlapping):
    one = content_stores(_object_environment(tmp_path, EXULANICA_OBJECT_STORE_PREFIX=live))
    two = content_stores(_object_environment(tmp_path, EXULANICA_OBJECT_STORE_PREFIX=other))
    assert one.overlaps(two) is overlapping and two.overlaps(one) is overlapping


def test_overlapping_local_locations_are_recognised(tmp_path):
    live = local_content_stores(tmp_path / "data")
    assert live.overlaps(local_content_stores(tmp_path / "data" / "custody"))
    assert not live.overlaps(local_content_stores(tmp_path / "custody"))
    assert not live.overlaps(content_stores(_object_environment(tmp_path)))


def test_the_module_reads_no_ambient_cloud_configuration():
    source = (ROOT / "exulanica" / "store" / "object.py").read_text(encoding="utf-8")
    source += (ROOT / "exulanica" / "store" / "configured.py").read_text(encoding="utf-8")
    assert "AWS_" not in source and ".aws" not in source
    assert "trust_env=False" in source
    assert configured_module.STORE_KIND_ENV == "EXULANICA_STORE_KIND"
