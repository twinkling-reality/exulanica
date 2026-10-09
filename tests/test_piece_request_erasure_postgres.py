"""A workspace tombstone cancels every open piece request, whichever role writes the tombstone.

The trigger that does it runs as the tombstone's writer (it is not a SECURITY DEFINER function),
so a role that writes tombstones on a real path and lacked the grant to update ``piece_request``
would make the deletion itself fail. Each such role is exercised here with an open request
present: the runtime role (``IngestRepository.insert_tombstone``, the product's one tombstone
writer), the administrative role a restore replays carried tombstones as, and the real restore:
a ``pg_dump`` backup taken while the request was open, the tombstone written, the backup restored
with ``psql`` and the tombstones replayed by the restore command. A capture tombstone reaches no
request. The other writers of tombstones, the invoker triggers of migrations 0082 and 0104, write
scene_training and caption_search tombstones only, never a workspace's, so they never reach the
trigger's update.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import psycopg
import pytest
from exulanica.generation import store
from exulanica.generation.requests import (
    GPU_PROVIDER,
    LookReference,
    generation_catalogs,
    plan_requests,
)
from exulanica.ingest.repository import IngestRepository
from exulanica.world.style_pack_library import style_pack_library

from generated_piece_support import kept_output
from test_purge import _APP_PASSWORD, _APP_ROLE
from test_purge import purged as purged
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _through_a_restore
from world_support import FIXTURE_WORLD_ID, registered_world

pytestmark = pytest.mark.postgres


def _open_request(purged) -> uuid.UUID:
    connection, workspace_id = purged.repository.connection, purged.workspace_id
    registered_world(connection, workspace_id)
    library = style_pack_library()
    pack = library.default_pack
    look = LookReference(pack.pack_id, pack.version, pack.manifest_sha256)
    planned = plan_requests([("well", 1)], look, library=library)
    compute = generation_catalogs().compute.for_provider(GPU_PROVIDER)
    (made,), _ = store.create_piece_requests(
        connection,
        workspace_id,
        requested_by=uuid.uuid4(),
        world_id=FIXTURE_WORLD_ID,
        look=look,
        planned=planned,
        worst_cases=[compute.worst_case_usd(planned[0].variants)],
    )
    connection.commit()
    return made.piece_request_id


def _state(purged, piece_request_id: uuid.UUID) -> tuple[str, str | None]:
    [row] = purged.rows(
        "select state, failure from piece_request where piece_request_id = %s and world_id = %s",
        piece_request_id,
        FIXTURE_WORLD_ID,
    )
    return row["state"], row["failure"]


def _workspace_tombstone_as_runtime(purged) -> None:
    runtime = purged.database(role=_APP_ROLE, password=_APP_PASSWORD)
    with runtime.session(purged.workspace_id) as connection:
        IngestRepository(connection, purged.workspace_id).insert_tombstone(
            scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
        )


def test_the_runtime_role_s_workspace_tombstone_cancels_an_open_request(purged) -> None:
    made = _open_request(purged)
    _workspace_tombstone_as_runtime(purged)
    assert _state(purged, made) == ("cancelled", "workspace_deleted")


def test_the_administrative_role_s_workspace_tombstone_cancels_an_open_request(purged) -> None:
    made = _open_request(purged)
    with purged.database().session(purged.workspace_id) as connection:
        connection.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'an operator deleted the workspace')",
            (purged.workspace_id, uuid.uuid4()),
        )
    assert _state(purged, made) == ("cancelled", "workspace_deleted")


def test_a_capture_tombstone_reaches_no_piece_request(purged) -> None:
    made = _open_request(purged)
    [capture] = purged.rows("select capture_id from capture")
    purged.tombstone_the_capture(capture["capture_id"])
    assert _state(purged, made) == ("requested", None)


def test_a_restore_replays_the_tombstone_onto_the_request_the_backup_held_open(
    purged, commands, tmp_path
) -> None:
    made = _open_request(purged)

    def current() -> bool:
        return _state(purged, made)[0] == "requested"

    assert not _through_a_restore(
        purged, tmp_path, withdraw=lambda: _workspace_tombstone_as_runtime(purged), current=current
    )
    assert _state(purged, made) == ("cancelled", "workspace_deleted")


def _made_batch(purged) -> None:
    """A request queued into a batch that ended done with one output, as the worker records it."""
    from exulanica.generation import batches

    made = _open_request(purged)
    connection, workspace_id = purged.repository.connection, purged.workspace_id
    queued_at = dt.datetime.now(dt.UTC)
    batches.record_batch(
        connection,
        workspace_id,
        generation_session_id=uuid.uuid4(),
        job_raw=b'{"a job":"for the test"}',
        queued_at=queued_at,
        not_after=queued_at + dt.timedelta(hours=1),
        queued=[
            batches.QueuedReservation(
                piece_request_id=made,
                reservation_id=uuid.uuid4(),
                authority_id=uuid.uuid4(),
                holder="worker:test",
            )
        ],
    )
    [batch] = batches.batches_in_flight(connection, workspace_id)
    batches.end_batch(
        connection,
        workspace_id,
        batch,
        state="done",
        ended_at=dt.datetime.now(dt.UTC),
        settlements={made: ("reported", Decimal("0.01"))},
        outputs=[kept_output(batch.requests[0].request_sha256)],
    )
    connection.commit()


def _batch_rows(purged) -> int:
    [row] = purged.rows(
        "select (select count(*) from piece_batch) + (select count(*) from piece_output) as n"
    )
    return row["n"]


def test_no_output_is_written_for_a_deleted_workspace(purged) -> None:
    """After a workspace's tombstone, an output naming a piece the index keeps, with that row's own
    receipt and verdict (so every other check holds), is refused as the tombstone's."""
    from exulanica.generation import batches

    made = _open_request(purged)
    connection, workspace_id = purged.repository.connection, purged.workspace_id
    [request] = purged.rows(
        "select request_sha256 from piece_request where piece_request_id = %s", made
    )
    kept = kept_output(request["request_sha256"])
    with connection.cursor() as cursor:
        batches._record_generated(cursor, kept)
    connection.commit()
    _workspace_tombstone_as_runtime(purged)
    runtime = purged.database(role=_APP_ROLE, password=_APP_PASSWORD)
    with (
        runtime.session(workspace_id) as session,
        pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="piece_output"),
    ):
        session.execute(
            "insert into piece_output (workspace_id, piece_request_id, variant, cache_key, "
            "  receipt_canonical, receipt_sha256, piece_sha256, within, over_checks) "
            "values (%s, %s, 0, %s, %s, %s, %s, true, '{}')",
            (
                workspace_id,
                made,
                kept.cache_key,
                kept.output.receipt.decode("ascii"),
                kept.output.receipt_sha256,
                kept.output.piece_sha256,
            ),
        )


def test_a_workspace_tombstone_erases_the_workspace_s_batches_and_outputs(purged) -> None:
    _made_batch(purged)
    assert _batch_rows(purged) == 2
    [kept] = purged.rows("select cache_key, variant from generated_piece")
    _workspace_tombstone_as_runtime(purged)
    assert _batch_rows(purged) == 0
    # The installation's index of kept pieces holds nothing of the workspace's and stays.
    assert purged.rows("select cache_key, variant from generated_piece") == [kept]


def test_the_administrative_role_s_tombstone_erases_them_too(purged) -> None:
    _made_batch(purged)
    with purged.database().session(purged.workspace_id) as connection:
        connection.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'an operator deleted the workspace')",
            (purged.workspace_id, uuid.uuid4()),
        )
    assert _batch_rows(purged) == 0


def test_a_restore_erases_the_batches_the_backup_held(purged, commands, tmp_path) -> None:
    _made_batch(purged)
    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: _workspace_tombstone_as_runtime(purged),
        current=lambda: _batch_rows(purged) == 2,
    )
    assert _batch_rows(purged) == 0
