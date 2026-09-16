"""Canonical Exulanica names after the pre-release cutover. See ADR-0011."""

from __future__ import annotations

import tomllib
from pathlib import Path

from exulanica.api.routes.evidence import _clock_headers, _evidence_headers
from exulanica.api.routes.geometry import POINT_MAP_MEDIA_TYPE
from exulanica.db.roles import EXECUTOR_ROLE, PURGE_ROLE, RUNTIME_ROLE
from exulanica.env import (
    env_get,
    resolve_briefs_path,
    resolve_corpus_dir,
    resolve_data_dir,
)
from exulanica.errors import ExulanicaError
from exulanica.evidence.address import URI_SCHEME, parse_uri
from exulanica.evidence.blob import BlobId
from exulanica.world_package.package import PROFILE_VERSION

ROOT = Path(__file__).resolve().parents[1]
PHOTO_BYTES = b"\xff\xd8\xff\xe0 pretend this is a jpeg"
BLOB = BlobId.of_bytes(PHOTO_BYTES)


def test_error_base_is_exulanica_error() -> None:
    assert issubclass(ExulanicaError, Exception)


def test_env_get_reads_only_the_exulanica_name() -> None:
    environ = {"EXULANICA_DATA_DIR": "/new", "ORIMERA_DATA_DIR": "/old"}
    assert env_get("DATA_DIR", environ) == "/new"
    assert env_get("DATA_DIR", {"ORIMERA_DATA_DIR": "/old"}) is None


def test_data_dir_default_is_exulanica(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".orimera" / "local").mkdir(parents=True)
    resolved = resolve_data_dir({})
    assert resolved == Path(".exulanica/local")


def test_corpus_dir_default_is_exulanica() -> None:
    assert resolve_corpus_dir() == Path(".exulanica/media/intake/synthetic")


def test_briefs_prefer_exulanica_and_fall_back_to_legacy(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_briefs_path("note.md") == Path(".exulanica/briefs/note.md")
    (tmp_path / ".orimera" / "briefs").mkdir(parents=True)
    (tmp_path / ".orimera" / "briefs" / "note.md").write_text("old", encoding="utf-8")
    assert resolve_briefs_path("note.md") == Path(".orimera/briefs/note.md")
    (tmp_path / ".exulanica" / "briefs").mkdir(parents=True)
    (tmp_path / ".exulanica" / "briefs" / "note.md").write_text("new", encoding="utf-8")
    assert resolve_briefs_path("note.md") == Path(".exulanica/briefs/note.md")
    assert resolve_briefs_path("note.md", explicit="/tmp/explicit") == Path("/tmp/explicit")


def test_cli_scripts_are_exulanica_only() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]
    assert all(name.startswith("exulanica-") for name in scripts)
    assert not any(name.startswith("orimera-") for name in scripts)


def test_evidence_headers_are_exulanica_only() -> None:
    headers = _evidence_headers("still_image")
    assert headers == {"X-Exulanica-Modality": "still_image"}
    clock = _clock_headers(
        {
            "modality": "still_image",
            "utc_instant": None,
            "uncertainty_ms": None,
            "source": None,
        }
    )
    assert "X-Orimera-Modality" not in clock


def test_permalinks_and_wmp_profile_are_exulanica() -> None:
    emitted = f"{URI_SCHEME}://blob/{BLOB.ni_uri}/img#t=0,0.000000001&m=still_image&v=1"
    parsed = parse_uri(emitted)
    assert parsed.to_uri().startswith("exulanica://")
    assert URI_SCHEME == "exulanica"
    assert PROFILE_VERSION == "exulanica-wmp-1.0"
    assert POINT_MAP_MEDIA_TYPE == "application/vnd.exulanica.point-map"


def test_canonical_role_names() -> None:
    assert RUNTIME_ROLE == "exulanica_app"
    assert EXECUTOR_ROLE == "exulanica_ro"
    assert PURGE_ROLE == "exulanica_purge"
