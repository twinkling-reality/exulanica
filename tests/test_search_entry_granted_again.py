"""A photograph whose search right is granted again after a stop is ranked again.

Stopping the search right records each search entry made from the photograph as a vector target
of a ``caption_search`` tombstone, and the purge worker deletes it (migration 0104). The target rows
stay as the stop's record. A vector id is a digest of the capture, text and model, so granting the
right again and indexing again makes an entry under the same id. The search leaves an entry out
while a target names it and that target's purge has not destroyed it, and ranks the later entry,
decided by the purge job's own state rather than by deleting the tombstone's rows.

The search runs as the runtime role, which row-level security binds, as it does in the product.
"""

from __future__ import annotations

import pytest
from exulanica.epistemics.caption_embeddings import embed_capture
from exulanica.ingest.repository import IngestRepository
from exulanica.models.manifest import Role
from exulanica.selection.embeddings import READMITTED_SCOPE, QueryEmbedding, has_embeddings

from test_companion_matching import run, script, unchecked, vector
from test_purge import purged as purged
from test_search_entries_on_stop import UNDESCRIBED, _as_runtime, _entries, _grant, _stop
from test_search_entries_on_stop import indexed as indexed

pytestmark = pytest.mark.postgres


def _ranked(fixture, client) -> tuple[int, bool]:
    """How many photographs the vector path alone ranks, and whether search asks for a vector."""
    model = client.manifest[Role.EMBEDDING].primary.model_id
    # The stored entry's own vector, asked with words its description does not hold.
    query = QueryEmbedding(vector(), model, client.manifest.pipeline_version)
    with _as_runtime(fixture) as connection:
        repository = IngestRepository(connection, fixture.workspace_id)
        matched = run(repository, UNDESCRIBED, embedding=query).total_matched
        return matched, has_embeddings(connection, fixture.workspace_id, client)


def _stop_search(indexed) -> None:
    for right in indexed.rights[Role.EMBEDDING]:
        _stop(indexed.fixture, right.right_id)


def _grant_again(indexed, client):
    return _grant(
        indexed.fixture.repository,
        indexed.capture_id,
        indexed.authorization_id,
        Role.EMBEDDING,
        client.manifest,
        minutes=90,
    )


def _index_again(indexed, client, monkeypatch):
    fixture = indexed.fixture
    calls = script(client, monkeypatch, vector())
    embed_capture(
        fixture.repository.connection,
        fixture.workspace_id,
        indexed.capture_id,
        client,
        before_send=unchecked,
    )
    return calls


def _targets(fixture) -> int:
    return fixture.rows("select count(*) as n from tombstone_embedding_target")[0]["n"]


def test_an_entry_made_under_a_right_granted_after_the_stop_is_ranked(indexed, client, monkeypatch):
    fixture = indexed.fixture
    assert _ranked(fixture, client) == (1, True), "positive control: the entry ranks at first"
    _stop_search(indexed)
    assert fixture.worker().drain().destroyed == 1
    _grant_again(indexed, client)
    _index_again(indexed, client, monkeypatch)

    assert _entries(fixture) == [indexed.embedding_id], "the same id comes back"
    assert _targets(fixture) >= 1, "the stop's target rows are kept as its record"
    assert _ranked(fixture, client) == (1, True)


def test_a_stopped_entry_stays_out_until_its_purge_though_the_right_is_granted_again(
    indexed, client, monkeypatch
):
    fixture = indexed.fixture
    _stop_search(indexed)
    _grant_again(indexed, client)
    # The stopped entry is still stored, so indexing again sends nothing and adds nothing.
    assert _index_again(indexed, client, monkeypatch) == []
    assert _entries(fixture) == [indexed.embedding_id]
    assert _ranked(fixture, client) == (0, False)

    assert fixture.worker().drain().destroyed == 1
    assert _entries(fixture) == []
    assert _ranked(fixture, client) == (0, False)

    assert len(_index_again(indexed, client, monkeypatch)) == 1
    assert _ranked(fixture, client) == (1, True)


def test_a_second_stop_leaves_the_entry_made_again_out_before_its_own_purge(
    indexed, client, monkeypatch
):
    """The first stop's finished purge does not let the second stop's target rank."""
    fixture = indexed.fixture
    _stop_search(indexed)
    fixture.worker().drain()
    again = _grant_again(indexed, client)
    _index_again(indexed, client, monkeypatch)
    assert _ranked(fixture, client) == (1, True)

    for right in again:
        _stop(fixture, right.right_id)
    assert _entries(fixture) == [indexed.embedding_id], "the second purge has not run yet"
    assert _ranked(fixture, client) == (0, False)
    assert fixture.worker().drain().destroyed == 1
    assert _ranked(fixture, client) == (0, False)


def test_the_scope_search_admits_again_is_the_one_the_insert_guard_admits_again(purged):
    """Search's exception and 0104's guard are one decision: a scope admitted in one only is a bug.

    The guard refuses a vector id recorded as a target for every scope but this one, so only this
    scope's done purge can be followed by the same entry, and only it may rank again.
    """
    definition = purged.rows(
        "select pg_get_functiondef('tg_caption_vector_lifecycle_lock'::regproc) as body"
    )[0]["body"]
    assert f"t.scope::text <> '{READMITTED_SCOPE}'" in definition
    assert definition.count("t.scope::text <> ") == 1
