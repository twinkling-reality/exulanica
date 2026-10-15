"""The preparers a preparation worker runs: fixed in code, keyed by their pins, and runnable here.

Pure: a worker is built and inspected, never started, so nothing connects to a database.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from exulanica.api.services import describe_configuration
from exulanica.store.namespaces import LocalWorkspaceStores
from exulanica.world import asset_import, asset_preparation
from exulanica.world.asset_preparation import (
    PREPARERS,
    AssetPreparationWorker,
    StaticGlbPreparer,
    preparer_source_sha256,
)
from exulanica.world.workspace_preparations import (
    DEFAULT_RETAINED_BYTES,
    RETAINED_BYTES_BOUNDS,
    WorkspaceAssetSettingRefused,
    retained_bytes_limit,
)


class _Absent(StaticGlbPreparer):
    """The static preparer on a host that cannot run it, for this test only."""

    def available(self) -> bool:
        return False


def _worker(tmp_path: Path, preparers) -> AssetPreparationWorker:
    return AssetPreparationWorker(
        object(),  # never connected: the worker is built, not started
        LocalWorkspaceStores(tmp_path / "workspace-assets"),
        frozenset({uuid.uuid4()}),
        preparers=preparers,
    )


def test_the_registry_is_keyed_by_each_preparers_own_pin():
    assert (StaticGlbPreparer.preparer_id, StaticGlbPreparer.preparer_version) in PREPARERS
    for (preparer_id, version), preparer in PREPARERS.items():
        assert (preparer.preparer_id, preparer.preparer_version) == (preparer_id, version)
        assert preparer.lease_seconds > preparer.timeout_seconds
    with pytest.raises(TypeError):
        PREPARERS[("anything", 1)] = StaticGlbPreparer()  # type: ignore[index]


def test_a_worker_runs_only_the_preparers_this_process_can_run(tmp_path):
    key = (StaticGlbPreparer.preparer_id, StaticGlbPreparer.preparer_version)
    assert _worker(tmp_path, PREPARERS).preparers == (f"{key[0]}@{key[1]}",)
    # A row of a preparer this host cannot run waits for one that can, so a worker that could
    # run nothing at all refuses to start rather than idle as if it were healthy.
    with pytest.raises(ValueError, match="no registered preparer can run in this process"):
        _worker(tmp_path, {key: _Absent()})


def test_a_preparer_registered_under_another_pin_or_a_short_lease_is_refused(tmp_path):
    with pytest.raises(ValueError, match="another preparer's pin"):
        _worker(tmp_path, {("someone.else", 1): StaticGlbPreparer()})

    class Hurried(StaticGlbPreparer):
        lease_seconds = 30.0

    key = (StaticGlbPreparer.preparer_id, StaticGlbPreparer.preparer_version)
    with pytest.raises(ValueError, match="a lease must outlast its timeout"):
        _worker(tmp_path, {key: Hurried()})


def test_the_retained_bytes_limit_is_a_declared_setting_with_bounds():
    name = "EXULANICA_WORKSPACE_ASSET_RETAINED_BYTES"
    assert retained_bytes_limit({}) == DEFAULT_RETAINED_BYTES == 2 * 1024**3
    low, high = RETAINED_BYTES_BOUNDS
    assert retained_bytes_limit({name: str(low)}) == low
    assert retained_bytes_limit({name: f" {high} "}) == high
    for refused in (str(low - 1), str(high + 1), "2GiB", "-1", "1e9"):
        with pytest.raises(WorkspaceAssetSettingRefused, match=name):
            retained_bytes_limit({name: refused})
    # The configuration report names it, and never its value.
    assert describe_configuration({name: "123"})[name] == "set"


def test_the_static_glb_preparer_s_source_digest_names_every_file_of_its_profile():
    """A file of the profile left out of the receipt's source digest could change what runs while
    every receipt still named the same source."""
    import importlib

    world = Path(asset_preparation.__file__).parent
    profile = [
        importlib.import_module(f"exulanica.world.{path.stem}")
        for path in sorted(world.glob("static_glb*.py"))
    ]
    assert [module.__name__.rsplit(".", 1)[1] for module in profile] == [
        "static_glb",
        "static_glb_checks",
        "static_glb_format",
    ]
    assert StaticGlbPreparer().source_sha256() == preparer_source_sha256(*profile, asset_import)
