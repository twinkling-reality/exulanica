"""A restore keeps every search entry a person deleted deleted, measured through a real restore.

A search entry is a vector the caption pass made from a photograph's descriptions (``embedding``).
Two things delete one: deleting the photograph, whose ``capture`` tombstone records the entries as
vector targets (migration 0044), and stopping the photograph's search right, whose
``caption_search`` tombstone records the entries no other current search right covers (0104). The
purge role destroys a vector only when a tombstone recorded it as a target, and only a trigger
records one.

Each case takes an actual ``pg_dump`` backup at a named moment, seals the checkpoint and writes the
marker with the restore command, restores the dump with ``psql`` and replays with the command, then
asks what a person would: did the restore complete and may it serve, is any entry they deleted
left, does search still rank it, and does the database refuse it when it is written again.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid

import psycopg
import pytest
from exulanica.canonical import canonical_json
from exulanica.deletion.restore import RestoreRefused, verify_restore
from exulanica.deletion.restore import main as restore_command
from exulanica.env import resolve_data_dir
from exulanica.epistemics.caption_embeddings import embed_capture
from exulanica.models.manifest import Role
from exulanica.selection.embeddings import QueryEmbedding
from exulanica.store.namespaces import BLOB_NAMESPACE

from test_companion_matching import run, script, unchecked, vector
from test_purge import purged as purged
from test_restore_replay import _backup, _purge_database, _restore
from test_search_entries_on_stop import (
    DESCRIBED,
    UNDESCRIBED,
    _as_runtime,
    _entries,
    _grant,
    _stop,
)
from test_search_entries_on_stop import indexed as indexed

pytestmark = pytest.mark.postgres

_ENTRY_COLUMNS = (
    "workspace_id",
    "embedding_id",
    "family",
    "ref_type",
    "ref_id",
    "model_ref",
    "pipeline_version",
    "dims",
    "v",
)


@dataclasses.dataclass(frozen=True)
class Restored:
    """What a restore left, in the four questions the module docstring names."""

    #: Why replay refused, or None when it completed.
    refusal: str | None
    #: Whether the restore's startup check lets the API serve.
    serves: bool
    #: The search entries left in the workspace.
    entries: tuple[uuid.UUID, ...]
    #: How many photographs the entry's own vector still ranks.
    ranked: int
    #: Whether the database refuses the entry, written again as the runtime role writes one.
    refused_again: bool


#: A restore that kept every deletion: it completed, serves, and the entry is gone and refused.
ERASED = Restored(refusal=None, serves=True, entries=(), ranked=0, refused_again=True)

#: The refusal of a replay that finds an entry the checkpoint deleted, made before its deletion.
ENTRY_LEFT = "a search entry the checkpoint deleted is still in this database"


@pytest.fixture
def commands(purged, monkeypatch, tmp_path):
    """The restore command's own environment, pointed at this test's scratch schema and store.

    The command reads the administrative URL, the purge role's URL and the data directory from
    the environment, as an operator's shell gives them. The data directory is asserted before any
    command runs, so a missing variable can never let the command reach a default store.
    """
    monkeypatch.setenv("EXULANICA_DATABASE_URL", purged.database().url)
    monkeypatch.setenv("EXULANICA_PURGE_DATABASE_URL", _purge_database(purged).url)
    monkeypatch.setenv("EXULANICA_DATA_DIR", str(tmp_path))
    assert resolve_data_dir() == tmp_path
    assert purged.store.root == (tmp_path / BLOB_NAMESPACE).resolve()
    return purged


def _entry(fixture) -> dict:
    [row] = fixture.rows("select * from embedding")
    return dict(row)


def _seal(tmp_path):
    """Checkpoint the source and write the pending marker, before anything is restored."""
    source = tmp_path / "independent-journal" / "checkpoint.json"
    marker = tmp_path / "independent-control" / "restore.json"
    assert restore_command(["checkpoint", "--checkpoint", str(source)]) == 0
    assert restore_command(["prepare", "--checkpoint", str(source), "--marker", str(marker)]) == 0
    return source, marker


def _ranked(fixture, client) -> int:
    model = client.manifest[Role.EMBEDDING].primary.model_id
    query = QueryEmbedding(vector(), model, client.manifest.pipeline_version)
    return run(fixture.repository, UNDESCRIBED, embedding=query).total_matched


def _refused_again(fixture, entry: dict) -> bool:
    """Write the deleted entry back as the runtime role, and roll back whatever is accepted."""
    columns = ",".join(_ENTRY_COLUMNS)
    values = ",".join(["%s"] * len(_ENTRY_COLUMNS))
    with _as_runtime(fixture) as connection:
        try:
            with connection.transaction(force_rollback=True):
                connection.execute(
                    f"insert into embedding ({columns}) values ({values})",
                    [entry[column] for column in _ENTRY_COLUMNS],
                )
        except psycopg.errors.IntegrityConstraintViolation as refused:
            return "tombstoned" in str(refused)
        except psycopg.errors.UniqueViolation:
            return False
    return False


def _replay(fixture, client, source, marker, entry: dict) -> Restored:
    try:
        restore_command(["replay", "--checkpoint", str(source), "--marker", str(marker)])
    except RestoreRefused as refused:
        refusal = str(refused)
    else:
        refusal = None
    try:
        verify_restore(fixture.database(), marker)
    except RestoreRefused:
        serves = False
    else:
        serves = True
    return Restored(
        refusal=refusal,
        serves=serves,
        entries=tuple(_entries(fixture)),
        ranked=_ranked(fixture, client),
        refused_again=_refused_again(fixture, entry),
    )


def _as_version_1(source) -> None:
    """The checkpoint as profile v1 wrote it: its tombstones, and no withdrawal or catalog."""
    envelope = json.loads(source.read_bytes())
    record = {
        key: value
        for key, value in envelope["record"].items()
        if key not in ("withdrawals", "withdrawal_catalog")
    }
    record["profile"] = "exulanica.restore-tombstone-checkpoint/v1"
    envelope["record"] = record
    envelope["record_sha256"] = hashlib.sha256(canonical_json(record)).hexdigest()
    source.write_bytes(canonical_json(envelope))


def _search_right_current(fixture) -> bool:
    [row] = fixture.rows(
        "select bool_or(personal_model_right_allows(workspace_id,right_id,capture_id,"
        "model_provider,model_role,model_id,model_revision,destination,clock_timestamp())) "
        "as current from personal_model_right where model_role=%s",
        Role.EMBEDDING.value,
    )
    return bool(row["current"])


def _stop_search(indexed) -> None:
    for right in indexed.rights[Role.EMBEDDING]:
        _stop(indexed.fixture, right.right_id)
    outcome = indexed.fixture.worker().drain()
    assert outcome.failed == 0, outcome.errors
    assert _entries(indexed.fixture) == []


# -- deleting the photograph ------------------------------------------------------------------


def test_a_photograph_deleted_after_the_backup_has_its_search_entries_erased_again(
    indexed, client, commands, tmp_path
):
    fixture = indexed.fixture
    entry = _entry(fixture)
    dump, blobs = _backup(fixture, tmp_path)
    fixture.tombstone_the_capture(indexed.capture_id)
    assert fixture.worker().drain().failed == 0
    assert _entries(fixture) == []
    source, marker = _seal(tmp_path)
    _restore(fixture, dump, blobs)
    assert _entries(fixture) == [indexed.embedding_id], "the backup holds the entry"

    assert _replay(fixture, client, source, marker, entry) == ERASED


def test_a_photograph_deleted_and_purged_before_the_backup_replays_to_completion(
    indexed, client, commands, tmp_path
):
    fixture = indexed.fixture
    entry = _entry(fixture)
    fixture.tombstone_the_capture(indexed.capture_id)
    assert fixture.worker().drain().failed == 0
    assert _entries(fixture) == []
    dump, blobs = _backup(fixture, tmp_path)
    source, marker = _seal(tmp_path)
    _restore(fixture, dump, blobs)

    assert _replay(fixture, client, source, marker, entry) == ERASED


# -- stopping the search right ----------------------------------------------------------------


def test_a_search_right_stopped_and_purged_before_the_backup_replays_to_completion(
    indexed, client, commands, tmp_path
):
    fixture = indexed.fixture
    entry = _entry(fixture)
    _stop_search(indexed)
    dump, blobs = _backup(fixture, tmp_path)
    source, marker = _seal(tmp_path)
    _restore(fixture, dump, blobs)

    assert _replay(fixture, client, source, marker, entry) == ERASED
    assert not _search_right_current(fixture)
    assert run(fixture.repository, DESCRIBED).total_matched == 1, "the photograph survives"


def test_a_search_right_stopped_after_the_backup_stays_stopped(indexed, client, commands, tmp_path):
    """The checkpoint carries the stop, and replay writes it again before any tombstone.

    So the replayed ``caption_search`` tombstone's cascade finds no current right covering the
    entry, records it, and the purge erases it (migration 0104), as the stop itself did.
    """
    fixture = indexed.fixture
    entry = _entry(fixture)
    dump, blobs = _backup(fixture, tmp_path)
    _stop_search(indexed)
    source, marker = _seal(tmp_path)
    _restore(fixture, dump, blobs)
    assert _entries(fixture) == [indexed.embedding_id], "the backup holds the entry"
    assert _search_right_current(fixture), "the backup holds the right as current"

    assert _replay(fixture, client, source, marker, entry) == ERASED
    assert not _search_right_current(fixture)
    assert run(fixture.repository, DESCRIBED).total_matched == 1, "the photograph survives"


def test_a_version_1_checkpoint_of_that_stop_is_never_served(indexed, client, commands, tmp_path):
    """A checkpoint of profile v1 holds tombstones only, so the restored right keeps the entry.

    The replayed ``caption_search`` tombstone's cascade erases only what no current right covers,
    so it keeps the entry the stop deleted. Replay then finds that entry, made before the stop took
    effect, and refuses to complete rather than serve it.
    """
    fixture = indexed.fixture
    entry = _entry(fixture)
    dump, blobs = _backup(fixture, tmp_path)
    _stop_search(indexed)
    source = tmp_path / "independent-journal" / "checkpoint.json"
    marker = tmp_path / "independent-control" / "restore.json"
    assert restore_command(["checkpoint", "--checkpoint", str(source)]) == 0
    _as_version_1(source)
    assert restore_command(["prepare", "--checkpoint", str(source), "--marker", str(marker)]) == 0
    _restore(fixture, dump, blobs)

    restored = _replay(fixture, client, source, marker, entry)
    assert (restored.refusal, restored.serves) == (ENTRY_LEFT, False)
    assert _search_right_current(fixture), "a v1 checkpoint carries no withdrawal"


def test_an_entry_indexed_again_under_a_later_right_survives_the_replay(
    indexed, client, commands, monkeypatch, tmp_path
):
    """A right granted after the stop lets the photograph be indexed again, and replay keeps it.

    The later right is the person's current choice. Replaying the stop must not erase what that
    right covers, as the stop itself does not (0104).
    """
    fixture = indexed.fixture
    entry = _entry(fixture)
    _stop_search(indexed)
    _grant(
        fixture.repository,
        indexed.capture_id,
        indexed.authorization_id,
        Role.EMBEDDING,
        client.manifest,
        minutes=90,
    )
    script(client, monkeypatch, vector())
    embed_capture(
        fixture.repository.connection,
        fixture.workspace_id,
        indexed.capture_id,
        client,
        before_send=unchecked,
    )
    assert _entries(fixture) == [indexed.embedding_id]
    dump, blobs = _backup(fixture, tmp_path)
    source, marker = _seal(tmp_path)
    _restore(fixture, dump, blobs)

    restored = _replay(fixture, client, source, marker, entry)
    assert (restored.refusal, restored.serves, restored.entries) == (
        None,
        True,
        (indexed.embedding_id,),
    )
    assert _search_right_current(fixture)


# -- what a checkpoint may name -----------------------------------------------------------------


def test_a_checkpoint_naming_a_target_no_worker_destroys_is_refused_before_anything_restores(
    purged, commands, tmp_path
):
    """Replay queues stored bytes again and checks search entries, and nothing else exists.

    ``purge_job`` accepts a kind no worker destroys (``text_chunk``, which nothing writes), and a
    checkpoint naming one would leave its job queued for ever or pass it over unread. Both are
    refused where the checkpoint is read, before a marker exists.
    """
    purged.tombstone_the_capture(purged.rows("select capture_id from capture")[0]["capture_id"])
    source = tmp_path / "independent-journal" / "checkpoint.json"
    assert restore_command(["checkpoint", "--checkpoint", str(source)]) == 0
    envelope = json.loads(source.read_bytes())
    envelope["record"]["tombstones"][0]["targets"].append(
        {"target_kind": "text_chunk", "target_ref": str(uuid.uuid4())}
    )
    envelope["record_sha256"] = hashlib.sha256(canonical_json(envelope["record"])).hexdigest()
    source.write_bytes(canonical_json(envelope))
    marker = tmp_path / "independent-control" / "restore.json"

    with pytest.raises(RestoreRefused, match=r"no worker destroys: \['text_chunk'\]"):
        restore_command(["prepare", "--checkpoint", str(source), "--marker", str(marker)])
    assert not marker.exists()
