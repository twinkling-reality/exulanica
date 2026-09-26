"""The command line, which is mostly a promise that running it twice is safe.

The second run must say what it skipped and why. A tool that silently does nothing looks
identical to a tool that silently did everything again and billed for it.

Unlike every other test of the ingest path, nothing here is handed a repository. The CLI
resolves its own database from ``EXULANICA_DATABASE_URL`` and opens its own connections, and that
resolution is part of what is being tested, so the ``cli_database`` fixture points that variable
at the throwaway schema instead of substituting a connection. The five model-wiring tests at the
bottom touch no database at all and ask for nothing.
"""

from __future__ import annotations

import io
import re
import uuid
from pathlib import Path

from exulanica.db import Database
from exulanica.ingest.cli import main

from conftest import write_photo

# No module-level postgres marker. tests/conftest.py marks each test by the fixtures it
# actually requests, so the handful here that need no server stay runnable without one.


def _run(argv: list[str]) -> tuple[int, str]:
    stream = io.StringIO()
    code = main(argv, stream=stream)
    return code, stream.getvalue()


def _first_capture_run_id(data_dir: Path) -> uuid.UUID:
    """The run id the CLI would print, read back the way anything else would have to read it.

    ``pipeline_run`` is under FORCE row-level security, so a connection that has not declared a
    workspace sees an empty table rather than an error. The workspace is the one the CLI wrote
    under ``--data-dir``, which is the only place it is recorded. ``run_id`` defaults to
    ``uuidv7()``, which is time ordered, so ordering by it is an insertion ordering rather than
    an arbitrary one and "the first run that reached a capture" means what it says.
    """
    workspace_id = uuid.UUID((data_dir / "workspace.txt").read_text(encoding="utf-8").strip())
    with Database.from_env().session(workspace_id) as connection:
        row = connection.execute(
            "select run_id from pipeline_run where capture_id is not null order by run_id limit 1"
        ).fetchone()
    assert row is not None
    return row["run_id"]


def test_ingesting_a_directory_twice_reports_the_second_run_as_unchanged(
    tmp_path, photo_dir, cli_database
):
    write_photo(photo_dir, "a.jpg", when="2026:08:27 10:00:00", gps=(64.3271, -20.1199))
    write_photo(photo_dir, "b.jpg", when="2026:08:27 10:04:00", gps=(64.3271, -20.1199))
    data_dir = str(tmp_path / "state")

    code, first = _run(["--data-dir", data_dir, "ingest", str(photo_dir), "--offline"])
    assert code == 0
    assert "ingested   2" in first
    assert "unchanged  0" in first

    code, second = _run(["--data-dir", data_dir, "ingest", str(photo_dir), "--offline"])
    assert code == 0
    assert "unchanged  2" in second
    assert "nothing recomputed, nothing billed" in second
    assert "model calls 0" in second
    # Offline, so the vision stage never ran. That is reported as incomplete, not as done.
    assert "incomplete 2" in second


def test_the_workspace_id_survives_between_runs(tmp_path, photo_dir, cli_database):
    """A regenerated workspace looks exactly like an ingest that quietly did nothing."""
    write_photo(photo_dir, "a.jpg")
    data_dir = str(tmp_path / "state")
    _, first = _run(["--data-dir", data_dir, "ingest", str(photo_dir), "--offline"])
    _, second = _run(["--data-dir", data_dir, "ingest", str(photo_dir), "--offline"])
    pattern = re.compile(r"workspace ([0-9a-f-]{36})")
    assert pattern.search(first).group(1) == pattern.search(second).group(1)


def test_the_summary_says_when_the_vision_stage_did_not_run(tmp_path, photo_dir, cli_database):
    write_photo(photo_dir, "a.jpg")
    _, output = _run(["--data-dir", str(tmp_path / "state"), "ingest", str(photo_dir), "--offline"])
    assert "vision: disabled" in output
    assert "complete for capture-supported facts and incomplete for inference" in output
    assert "not run: vision" in output


def test_an_unreadable_file_fails_alone_and_the_run_still_reports(
    tmp_path, photo_dir, cli_database
):
    write_photo(photo_dir, "good.jpg")
    (photo_dir / "broken.jpg").write_bytes(b"not an image at all")
    code, output = _run(
        ["--data-dir", str(tmp_path / "state"), "ingest", str(photo_dir), "--offline"]
    )
    assert code == 1
    assert "FAILED" in output and "broken.jpg" in output
    assert "ingested   1" in output


def test_scene_grouping_runs_and_is_reported(tmp_path, photo_dir, cli_database):
    write_photo(photo_dir, "a.jpg", when="2026:08:27 10:00:00", gps=(64.3271, -20.1199))
    write_photo(photo_dir, "b.jpg", when="2026:08:27 18:00:00", gps=(64.1466, -21.9426))
    _, output = _run(["--data-dir", str(tmp_path / "state"), "ingest", str(photo_dir), "--offline"])
    assert "scenes      2 groups" in output
    assert "awaiting confirmation" in output


def test_replay_prints_the_ledger_for_a_run(tmp_path, photo_dir, cli_database):
    write_photo(photo_dir, "a.jpg")
    data_dir = str(tmp_path / "state")
    _run(["--data-dir", data_dir, "ingest", str(photo_dir), "--offline"])

    run_id = _first_capture_run_id(Path(data_dir))

    code, output = _run(["--data-dir", data_dir, "replay", str(run_id)])
    assert code == 0
    assert "run_started" in output
    assert "stage_succeeded" in output
    assert "artifact_written" in output


# -- the model wiring --------------------------------------------------------------------
#
# Every test above runs --offline, so none of them touch the model client. These four cover the
# two places the CLI reaches into exulanica.models. None of them issues a request: constructing a
# client opens no connection, and the preflight is given a catalog rather than fetching one.
#
# None of them opens a database either, so none of them asks for cli_database.


def _catalog_snapshot(*, drop: str | None = None) -> list[dict]:
    """A catalog in which every manifest identifier resolves and still fits its role."""
    from exulanica.models.manifest import load_manifest

    manifest = load_manifest()
    entries = []
    for model_id in sorted(manifest.referenced_model_ids()):
        if model_id == drop:
            continue
        spec = manifest.spec(model_id)
        entries.append(
            {
                "name": "Display Name Code Must Never Read",
                "flavors": [
                    {
                        "model_id": model_id,
                        "use_cases": list(spec.catalog_use_cases),
                        "input_price_per_million_tokens": float(spec.input_usd_per_mtok),
                        "output_price_per_million_tokens": float(spec.output_usd_per_mtok),
                    }
                ],
            }
        )
    return entries


def test_the_preflight_passes_when_every_manifest_id_resolves(monkeypatch):
    import io

    from exulanica.ingest.cli import _preflight

    monkeypatch.setattr(
        "exulanica.models.preflight.fetch_catalog", lambda url, **kw: _catalog_snapshot()
    )
    stream = io.StringIO()
    assert _preflight(stream) is True
    assert "resolve against the live catalog" in stream.getvalue()


def test_the_preflight_fails_when_a_manifest_id_has_been_withdrawn(monkeypatch):
    """The December failure the whole mechanism exists to catch, seen from the CLI."""
    import io

    from exulanica.ingest.cli import _preflight
    from exulanica.models.manifest import Role, load_manifest

    withdrawn = load_manifest()[Role.VISION].primary.model_id
    monkeypatch.setattr(
        "exulanica.models.preflight.fetch_catalog",
        lambda url, **kw: _catalog_snapshot(drop=withdrawn),
    )
    stream = io.StringIO()
    assert _preflight(stream) is False
    assert "absent_from_catalog" in stream.getvalue()


def test_an_unreachable_catalog_is_not_a_passing_preflight(monkeypatch):
    """The check exists to be believed when it is green, so unreachable is not green."""
    import io

    from exulanica.ingest.cli import _preflight
    from exulanica.models.errors import TransportError

    def boom(url, **kwargs):
        raise TransportError("DNS is having a day")

    monkeypatch.setattr("exulanica.models.preflight.fetch_catalog", boom)
    stream = io.StringIO()
    assert _preflight(stream) is False
    assert "could not reach the catalog" in stream.getvalue()


def test_the_vision_stage_is_built_with_a_cache_under_the_data_dir(tmp_path, monkeypatch):
    """The cache holds model output over the user's photographs, so the cascade must reach it."""
    import argparse
    import io
    import json

    from exulanica.ingest.cli import _build_vision
    from exulanica.ingest.vision import NebiusVisionModel
    from exulanica.models.manifest import Role, load_manifest

    manifest = load_manifest()
    provider = manifest.provider(manifest[Role.VISION].provider)
    monkeypatch.setenv(provider.api_key_env, "test-key-not-real")
    # A real client is built here, and a real client refuses to exist without an egress
    # allowlist naming its endpoint. No request is made.
    monkeypatch.setenv("EXULANICA_EGRESS_ALLOWLIST", json.dumps([provider.origin]))
    data_dir = tmp_path / "state"
    args = argparse.Namespace(offline=False, skip_preflight=True, data_dir=str(data_dir))

    model = _build_vision(args, io.StringIO())
    assert isinstance(model, NebiusVisionModel)
    assert (data_dir / "model-cache").is_dir()


def test_offline_builds_no_model_client_at_all(tmp_path):
    import argparse
    import io

    from exulanica.ingest.cli import _build_vision

    args = argparse.Namespace(offline=True, skip_preflight=False, data_dir=str(tmp_path))
    assert _build_vision(args, io.StringIO()) is None
