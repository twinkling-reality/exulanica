"""The installation acceptance driver, ``scripts/acceptance/installation.py``, without Docker.

These hold what the driver's evidence depends on and a run would not show by itself: that Docker and
Compose read only the driver's own settings (not the caller's ``EXULANICA_`` values, which Compose
would prefer to the environment file, and no credential store); that its secrets file is private;
that the default photographs share their intake probe, which is the state row L2b's finding names
and the test of its fix, while ``--distinct-probes`` keeps them apart; and that the declaration it
writes is the one the restore reads, key for key.
"""

from __future__ import annotations

import importlib.util
import io
import json
import stat
import sys
import uuid
from pathlib import Path
from types import ModuleType

from exulanica.deletion.restore import _DECLARATION_KEYS, DECLARATION_PROFILE
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "acceptance" / "installation.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_acceptance_installation", DRIVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _size(photo: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(photo)).size


def test_docker_reads_only_the_drivers_own_settings(tmp_path, monkeypatch):
    driver = _load()
    monkeypatch.setenv("EXULANICA_API_TOKENS", "the caller's")
    monkeypatch.setenv("POSTGRES_PASSWORD", "the caller's")
    monkeypatch.setattr(driver.LAUNCH, "state_dir", lambda worktree: tmp_path / "state")
    installation = driver.Installation(tmp_path, 0, 19430)
    installation.prepare()
    environment = installation.environment()
    assert not [name for name in environment if name.startswith(("EXULANICA_", "POSTGRES_"))]
    assert environment["DOCKER_CONFIG"] == str(installation.docker_config)
    config = json.loads((installation.docker_config / "config.json").read_text())
    assert "credsStore" not in config and "auths" not in config


def test_the_secrets_file_is_private(tmp_path, monkeypatch):
    driver = _load()
    monkeypatch.setattr(driver.LAUNCH, "state_dir", lambda worktree: tmp_path / "state")
    installation = driver.Installation(tmp_path, 0, 19430)
    installation.prepare()
    values = driver.secrets_environment(installation, "0" * 40)
    driver.write_environment(installation, values)
    for path in (installation.env_file, installation.operator_file):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert values["EXULANICA_PORT"].startswith("127.0.0.1:")


def test_default_photographs_share_a_size_and_distinct_ones_do_not():
    driver = _load()
    same = {_size(driver.photograph(seed)) for seed in (1, 2, 3)}
    apart = {_size(driver.photograph(seed, distinct_probes=True)) for seed in (1, 2, 3)}
    assert len(same) == 1
    assert len(apart) == 3
    assert len({driver.photograph(seed) for seed in (1, 2, 3)}) == 3


def test_the_declaration_is_the_one_the_restore_reads():
    driver = _load()
    export = {"record_sha256": "a" * 64}
    stated = json.loads(driver.declaration(export, driver.dt.datetime.now(driver.dt.UTC)))
    assert set(stated) == _DECLARATION_KEYS
    assert stated["profile"] == DECLARATION_PROFILE
    assert stated["export_sha256"] == "a" * 64
    uuid.UUID(stated["declaration_id"])
