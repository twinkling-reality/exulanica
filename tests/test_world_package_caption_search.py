"""A world package carries a stopped search right as an audit record that blocks nothing.

Stopping a photograph's search right writes a ``caption_search`` tombstone (migration 0104). The
projector copies every tombstone the workspace holds into ``deletion/tombstones.json``, without its
reason or its requesting actor, and a package holds no search entry at all, so there the tombstone
records that the stop happened and erases nothing: the photograph and the graph are the same in the
package made after the stop as in the one made before it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exulanica.models.manifest import Role
from exulanica.world_package import diff_packages, verify_package
from exulanica.world_package.pseudonyms import urn

from test_purge import purged as purged
from test_search_entries_on_stop import _stop
from test_search_entries_on_stop import indexed as indexed
from test_world_package_postgres import _export
from world_support import registered_world

pytestmark = pytest.mark.postgres


def _graph(package: Path) -> dict:
    return json.loads((package / "memory/graph.json").read_text())


def test_a_stopped_search_right_is_an_audit_record_in_the_package_that_blocks_nothing(
    indexed, tmp_path: Path
):
    fixture = indexed.fixture
    repository = fixture.repository
    world_id = registered_world(repository.connection, repository.workspace_id)
    before = _export(repository, tmp_path / "before.wmp", world_id=world_id)
    assert _graph(before.output)["captures"], "the package holds the photograph"
    for right in indexed.rights[Role.EMBEDDING]:
        _stop(fixture, right.right_id)
    assert fixture.worker().drain().destroyed == 1, "the stop erased the search entry"

    after = _export(
        repository,
        tmp_path / "after.wmp",
        world_id=world_id,
        parent=before.merkle_root_sha256,
    )

    verify_package(after.output)
    difference = diff_packages(before.output, after.output)
    assert "deletion/tombstones.json" in difference.changed_files
    assert "memory/graph.json" not in difference.changed_files
    assert _graph(after.output) == _graph(before.output)
    [stop] = json.loads((after.output / "deletion/tombstones.json").read_text())["items"]
    assert stop["scope"] == "caption_search"
    assert stop["purge_state"] == "complete"
    assert stop["target"]["capture_id"] in {
        capture["capture_id"] for capture in _graph(after.output)["captures"]
    }
    assert stop["target"]["capture_id"] == urn("capture", indexed.capture_id)
    assert not {"reason", "requested_by"} & set(stop)
    # The entry the stop erased was never in any package, before the stop or after it.
    for package in (before.output, after.output):
        written = "".join(path.read_text() for path in sorted(package.rglob("*.json")))
        assert str(indexed.embedding_id) not in written
