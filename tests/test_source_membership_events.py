"""Removing a reference photograph from a saved world and adding it back, against PostgreSQL.

Every HTTP call here goes through an application connected as the runtime role, so row-level
security and grants are part of what is tested rather than bypassed by the table owner. The
second workspace's token, two concurrent connections, direct statements as the runtime role and
the owner, retries after the world moved, and repeated detach and rebind cycles are each
exercised. Migration ``0090`` and its backfill are held by
``test_saved_world_membership_backfill.py``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.evidence.blob import BlobId
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.source_membership_events import current_memberships
from fastapi.testclient import TestClient
from psycopg import sql

from conftest import scratch_role_database
from test_saved_world_entries_api import (
    _attachment_body,
    _create_entry,
    _create_starter,
    _renew_reviewed_source,
    _reviewed_source,
)
from test_world_objects_api import CUBE, ObjectsApi
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

pytestmark = pytest.mark.postgres

_LOCK_SEED = 880_024

#: The two functions migration 0090 runs with the table owner's rights.
_DEFINERS = (
    "tg_saved_world_source_attachment_moves_membership",
    "tg_saved_world_source_detach_moves_membership",
)


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


@pytest.fixture
def api(objects_api, repository, spine_schema):
    """The same routes and tokens as ``objects_api``, served by a runtime-role connection."""
    provision_runtime_role(repository.connection)
    _psycopg, scratch = spine_schema
    database = scratch_role_database(scratch, RUNTIME_ROLE)
    services = Services(
        database=database,
        readonly_database=database,
        store=objects_api.store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    with TestClient(create_app(services, verify=False)) as client:
        yield ObjectsApi(
            client,
            objects_api.snapshot_id,
            objects_api.actor,
            objects_api.store,
            objects_api.world_id,
        )


@pytest.fixture
def runtime_session(api, repository, spine_schema):
    """Open a connection as the runtime role, scoped to a workspace (this test's by default)."""
    _psycopg, scratch = spine_schema

    def open_session(workspace=None):
        return scratch_role_database(scratch, RUNTIME_ROLE).session(
            workspace or repository.workspace_id
        )

    return open_session


# -- helpers --------------------------------------------------------------------------------------


def _path(entry, route):
    return f"/world-entries/{entry['entry_id']}/{route}"


def _cursor_body(entry, operation_id=None):
    return {
        "operation_id": str(operation_id or uuid.uuid4()),
        "base_revision": entry["revision"],
        "authored_version_id": entry["authored_version_id"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
        "style_version_id": entry["style_version_id"],
    }


def _detach_body(entry, *attachment_ids, operation_id=None):
    return {
        **_cursor_body(entry, operation_id),
        "selections": [{"attachment_id": str(value)} for value in attachment_ids],
    }


def _rebind_body(entry, *sources, operation_id=None):
    return {
        **_cursor_body(entry, operation_id),
        "sources": [
            {"capture_id": source["capture_id"], "evidence_span_id": source["evidence_span_id"]}
            for source in sources
        ],
    }


def _ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def _refused(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["code"] == code, response.text
    return response.json()


def _attached(api, repository, *, minute, valid_for_seconds=None):
    entry = _create_starter(api)
    source = _reviewed_source(repository, api, minute=minute, valid_for_seconds=valid_for_seconds)
    body = _ok(api.post(_path(entry, "source-attachments"), _attachment_body(entry, source)))
    return body, source, body["source_attachments"][0]


def _removed(api, entry, attachment_id):
    return _ok(api.post(_path(entry, "source-detachments"), _detach_body(entry, attachment_id)))


def _rows(repository, query, *params):
    return repository.connection.execute(query, params).fetchall()


def _history(repository, entry):
    return _rows(
        repository,
        "select a.attachment_id,a.operation_id,o.kind,a.capture_id,a.authorization_id,"
        "a.screening_id,a.attached_entry_revision from saved_world_source_attachment a "
        "join saved_world_source_attachment_operation o on o.workspace_id=a.workspace_id "
        "and o.operation_id=a.operation_id where a.workspace_id=%s and a.entry_id=%s "
        "order by a.attached_entry_revision,a.attachment_id",
        repository.workspace_id,
        uuid.UUID(entry["entry_id"]),
    )


def _detach_rows(repository, entry):
    return _rows(
        repository,
        "select operation_id,attachment_id,capture_id,detached_entry_revision,detached_at "
        "from saved_world_source_detach where workspace_id=%s and entry_id=%s "
        "order by detached_entry_revision",
        repository.workspace_id,
        uuid.UUID(entry["entry_id"]),
    )


def _pointer(repository, entry, capture_id):
    row = repository.connection.execute(
        "select attachment_id from saved_world_source_current_membership "
        "where workspace_id=%s and entry_id=%s and capture_id=%s",
        (repository.workspace_id, uuid.UUID(entry["entry_id"]), uuid.UUID(capture_id)),
    ).fetchone()
    return "absent" if row is None else row["attachment_id"]


def _assert_pointer_is_the_replay(repository, store, entry):
    """The stored pointer and a replay of the append-only events name the same attachments."""
    ledger = SavedWorldEntryRepository(
        repository.connection, repository.workspace_id, store
    ).membership_ledger(uuid.UUID(entry["entry_id"]))
    replayed = {member.attachment_id for member in current_memberships(ledger)}
    stored = {
        row["attachment_id"]
        for row in _rows(
            repository,
            "select attachment_id from saved_world_source_current_membership "
            "where workspace_id=%s and entry_id=%s and attachment_id is not null",
            repository.workspace_id,
            uuid.UUID(entry["entry_id"]),
        )
    }
    assert stored == replayed
    return ledger


def _wait_past(repository, instant: dt.datetime):
    repository.connection.execute(
        "select pg_sleep(greatest(0,extract(epoch from (%s-clock_timestamp())))+0.05)",
        (instant,),
    )


def _valid_until(repository, table, column, value):
    return repository.connection.execute(
        sql.SQL("select valid_until from {} where workspace_id=%s and {}=%s").format(
            sql.Identifier(table), sql.Identifier(column)
        ),
        (repository.workspace_id, uuid.UUID(value)),
    ).fetchone()["valid_until"]


def _bound_object_edit(api, entry, object_id="object:after-removal"):
    """Move the authored cursor and the entry revision together, as the object panel does."""
    version = api.get(
        f"/world/versions/{entry['authored_version_id']}?world_id={entry['world_id']}"
    ).json()
    added = api.post(
        f"/world/versions/{entry['authored_version_id']}/objects?world_id={entry['world_id']}",
        {
            "base_state_sha256": version["state_sha256"],
            "object_id": object_id,
            "asset_sha256": CUBE,
            "region_id": "region:starter",
            "transform": {
                "x_mm": 1_200,
                "y_mm": 0,
                "z_mm": -450,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            },
            "origin_role": "fictional",
            "saved_entry": {
                "entry_id": entry["entry_id"],
                "base_revision": entry["revision"],
                "authored_state_sha256": entry["authored_state_sha256"],
                "authored_edit_seq": entry["authored_edit_seq"],
            },
        },
    )
    assert added.status_code == 201, added.text
    return api.get(f"/world-entries/{entry['entry_id']}").json()


# -- the membership law -------------------------------------------------------------------------


def test_removing_a_reference_keeps_its_rows_and_media_and_lists_it_as_previous(api, repository):
    entry, source, member = _attached(api, repository, minute=11)
    before = _history(repository, entry)

    removed = _removed(api, entry, member["attachment_id"])

    assert removed["revision"] == entry["revision"] + 1
    for key in (
        "authored_version_id",
        "authored_state_sha256",
        "authored_edit_seq",
        "style_version_id",
        "source_snapshot_id",
        "availability",
    ):
        assert removed[key] == entry[key], key
    assert removed["source_attachments"] == []
    [previous] = removed["previous_source_attachments"]
    assert previous["attachment_id"] == member["attachment_id"]
    assert previous["authorization_id"] == source["authorization_id"]
    assert previous["screening_id"] == source["screening_id"]
    assert previous["detached_entry_revision"] == removed["revision"]
    assert previous["availability"] == "available"
    assert _history(repository, entry) == before
    assert api.store.exists(BlobId.from_hex(source["source_sha256"]))
    capture = _rows(
        repository,
        "select deleted_at from capture where workspace_id=%s and capture_id=%s",
        repository.workspace_id,
        uuid.UUID(source["capture_id"]),
    )[0]
    assert capture["deleted_at"] is None
    assert _pointer(repository, entry, source["capture_id"]) is None
    assert api.get(f"/world-entries/{entry['entry_id']}").json() == removed
    ledger = _assert_pointer_is_the_replay(repository, api.store, entry)
    assert [operation.kind for operation in ledger.operations] == ["attach", "detach"]


def test_attach_refuses_a_removed_photograph_and_says_rebind(api, repository):
    entry, source, member = _attached(api, repository, minute=12)
    removed = _removed(api, entry, member["attachment_id"])
    renewed = _renew_reviewed_source(repository, api, source)

    refused = _refused(
        api.post(_path(entry, "source-attachments"), _attachment_body(removed, renewed)),
        422,
        "rebind_required",
    )
    assert "add it back" in refused["detail"]
    assert len(_history(repository, entry)) == 1
    assert api.get(f"/world-entries/{entry['entry_id']}").json() == removed


def test_adding_back_needs_a_new_review_and_pins_it_as_a_new_row(api, repository):
    entry, source, member = _attached(api, repository, minute=13)
    removed = _removed(api, entry, member["attachment_id"])

    without_review = _refused(
        api.post(_path(entry, "source-rebinds"), _rebind_body(removed, source)),
        422,
        "review_required",
    )
    assert "new human review" in without_review["detail"]

    renewed = _renew_reviewed_source(repository, api, source)
    rebound = _ok(api.post(_path(entry, "source-rebinds"), _rebind_body(removed, source)))

    assert rebound["revision"] == removed["revision"] + 1
    assert rebound["previous_source_attachments"] == []
    [current] = rebound["source_attachments"]
    assert current["attachment_id"] != member["attachment_id"]
    # The table's default identity, a time-ordered UUID, rather than one minted in Python.
    assert uuid.UUID(current["attachment_id"]).version == 7
    assert current["authorization_id"] == renewed["authorization_id"]
    assert current["screening_id"] == renewed["screening_id"]
    assert current["availability"] == "available"
    first, second = _history(repository, entry)
    assert str(first["attachment_id"]) == member["attachment_id"]
    assert str(first["authorization_id"]) == source["authorization_id"]
    assert str(first["screening_id"]) == source["screening_id"]
    assert first["kind"] == "attach" and second["kind"] == "rebind"
    assert str(second["attachment_id"]) == current["attachment_id"]
    assert str(_pointer(repository, entry, source["capture_id"])) == current["attachment_id"]
    _assert_pointer_is_the_replay(repository, api.store, entry)


def test_a_second_removal_and_return_keeps_every_event(api, repository):
    entry, source, member = _attached(api, repository, minute=14)
    state = _removed(api, entry, member["attachment_id"])
    _renew_reviewed_source(repository, api, source)
    state = _ok(api.post(_path(entry, "source-rebinds"), _rebind_body(state, source)))
    second = state["source_attachments"][0]["attachment_id"]
    state = _removed(api, state, second)
    third_review = _renew_reviewed_source(repository, api, source)
    state = _ok(api.post(_path(entry, "source-rebinds"), _rebind_body(state, source)))

    history = _history(repository, entry)
    assert [row["kind"] for row in history] == ["attach", "rebind", "rebind"]
    assert len({row["screening_id"] for row in history}) == 3
    assert [str(row["attachment_id"]) for row in _detach_rows(repository, entry)] == [
        member["attachment_id"],
        second,
    ]
    assert state["source_attachments"][0]["screening_id"] == third_review["screening_id"]
    assert state["revision"] == entry["revision"] + 4
    ledger = _assert_pointer_is_the_replay(repository, api.store, entry)
    assert [operation.kind for operation in ledger.operations] == [
        "attach",
        "detach",
        "rebind",
        "detach",
        "rebind",
    ]


def test_a_return_never_pins_receipts_an_earlier_membership_used(api, repository):
    """The first membership's review is still current when the second one's expires.

    Comparing only the newest membership let the third membership pin the first one's
    receipts with no new review. Measured against the baseline before the fix.
    """
    entry, source, member = _attached(api, repository, minute=15)
    state = _removed(api, entry, member["attachment_id"])
    short = _renew_reviewed_source(repository, api, source, valid_for_seconds=3)
    state = _ok(api.post(_path(entry, "source-rebinds"), _rebind_body(state, source)))
    assert state["source_attachments"][0]["screening_id"] == short["screening_id"]
    state = _removed(api, state, state["source_attachments"][0]["attachment_id"])
    _wait_past(
        repository,
        _valid_until(
            repository, "reconstruction_privacy_screening", "screening_id", short["screening_id"]
        ),
    )

    _refused(
        api.post(_path(entry, "source-rebinds"), _rebind_body(state, source)),
        422,
        "review_required",
    )
    assert len(_history(repository, entry)) == 2
    assert api.get(f"/world-entries/{entry['entry_id']}").json() == state


def test_adding_back_needs_a_review_recorded_after_the_removal(api, repository):
    """A review made while the photograph was still in the world does not answer its removal.

    The drawer says adding a photograph back starts with a new review, and this is what makes
    that true. "A review this world never used" is not enough on its own: a renewal recorded
    while the photograph was still a reference satisfies it, and the photograph would return
    with no human decision taken after the person chose to remove it.
    """
    entry, source, member = _attached(api, repository, minute=34)
    before_removal = _renew_reviewed_source(repository, api, source)
    assert before_removal["screening_id"] != member["screening_id"]
    state = _removed(api, entry, member["attachment_id"])
    removed_at = _detach_rows(repository, entry)[0]["detached_at"]
    screened_at = _rows(
        repository,
        "select screened_at from reconstruction_privacy_screening "
        "where workspace_id=%s and screening_id=%s",
        repository.workspace_id,
        uuid.UUID(before_removal["screening_id"]),
    )[0]["screened_at"]
    assert screened_at < removed_at

    refused = _refused(
        api.post(_path(entry, "source-rebinds"), _rebind_body(state, source)),
        422,
        "review_required",
    )
    assert "recorded after it was removed" in refused["detail"]
    assert len(_history(repository, entry)) == 1
    assert api.get(f"/world-entries/{entry['entry_id']}").json() == state

    after_removal = _renew_reviewed_source(repository, api, source)
    rebound = _ok(api.post(_path(entry, "source-rebinds"), _rebind_body(state, source)))
    assert rebound["source_attachments"][0]["screening_id"] == after_removal["screening_id"]
    assert rebound["source_attachments"][0]["authorization_id"] == after_removal["authorization_id"]
    _assert_pointer_is_the_replay(repository, api.store, entry)


def test_the_database_refuses_a_rebind_row_pinning_a_review_older_than_the_removal(
    api, repository, runtime_session
):
    """The same rule as a trigger, so no writer of an attachment row can go round the route."""
    entry, source, member = _attached(api, repository, minute=35)
    stale_review = _renew_reviewed_source(repository, api, source)
    removed = _removed(api, entry, member["attachment_id"])

    with runtime_session() as app:
        forge = pytest.raises(
            psycopg.errors.IntegrityConstraintViolation, match="recorded after the photograph"
        )
        with forge, app.transaction():
            operation = _forged_operation(app, repository, removed, kind="rebind")
            _forged_attachment(app, repository, removed, operation, stale_review)
    assert len(_history(repository, entry)) == 1
    assert _pointer(repository, entry, source["capture_id"]) is None
    assert api.get(f"/world-entries/{entry['entry_id']}").json() == removed


def test_expired_and_deleted_references_can_be_removed(api, repository):
    entry, source, member = _attached(api, repository, minute=16, valid_for_seconds=3)
    _wait_past(
        repository,
        _valid_until(
            repository,
            "capture_reconstruction_authorization",
            "authorization_id",
            source["authorization_id"],
        ),
    )
    expired = api.get(f"/world-entries/{entry['entry_id']}").json()
    assert expired["source_attachments"][0]["unavailable_reason"] == "authorization_expired"
    removed = _removed(api, expired, member["attachment_id"])
    assert removed["source_attachments"] == []

    other = _reviewed_source(repository, api, minute=17)
    state = _ok(api.post(_path(entry, "source-attachments"), _attachment_body(removed, other)))
    other_member = state["source_attachments"][0]
    repository.insert_tombstone(
        scope="capture", capture_id=uuid.UUID(other["capture_id"]), requested_by=api.actor
    )
    deleted = api.get(f"/world-entries/{entry['entry_id']}").json()
    assert deleted["source_attachments"][0]["unavailable_reason"] == "source_unavailable"
    removed = _removed(api, deleted, other_member["attachment_id"])
    by_capture = {row["capture_id"]: row for row in removed["previous_source_attachments"]}
    assert by_capture[other["capture_id"]]["availability"] == "unavailable"
    assert by_capture[other["capture_id"]]["unavailable_reason"] == "source_unavailable"
    assert by_capture[source["capture_id"]]["availability"] == "available"

    _refused(
        api.post(_path(entry, "source-rebinds"), _rebind_body(removed, other)),
        422,
        "authority_unavailable",
    )


def test_refusals_name_the_membership_state(api, repository):
    entry, source, member = _attached(api, repository, minute=18)
    stranger_photo = _reviewed_source(repository, api, minute=19)

    _refused(
        api.post(_path(entry, "source-rebinds"), _rebind_body(entry, source)),
        422,
        "membership_current",
    )
    _refused(
        api.post(_path(entry, "source-rebinds"), _rebind_body(entry, stranger_photo)),
        422,
        "membership_unavailable",
    )
    _refused(
        api.post(_path(entry, "source-detachments"), _detach_body(entry, uuid.uuid4())),
        422,
        "membership_unavailable",
    )
    _refused(
        api.post(
            _path(entry, "source-detachments"),
            _detach_body(entry, member["attachment_id"], member["attachment_id"]),
        ),
        422,
        "invalid_detach",
    )
    stale = {**_detach_body(entry, member["attachment_id"]), "base_revision": entry["revision"] + 1}
    _refused(api.post(_path(entry, "source-detachments"), stale), 409, "stale_saved_world_entry")

    removed = _removed(api, entry, member["attachment_id"])
    _refused(
        api.post(
            _path(entry, "source-detachments"), _detach_body(removed, member["attachment_id"])
        ),
        422,
        "membership_unavailable",
    )
    _renew_reviewed_source(repository, api, source)
    _refused(
        api.post(_path(entry, "source-rebinds"), _rebind_body(entry, source)),
        409,
        "stale_saved_world_entry",
    )
    assert api.get(f"/world-entries/{entry['entry_id']}").json() == removed


def test_removal_ignores_authored_drift_and_adding_back_does_not(api, repository):
    """Detach reads and writes no scene, so a drifted branch cannot be adopted through it."""
    entry, source, member = _attached(api, repository, minute=20)
    version = api.get(
        f"/world/versions/{entry['authored_version_id']}?world_id={entry['world_id']}"
    ).json()
    drift = api.post(
        f"/world/versions/{entry['authored_version_id']}/objects?world_id={entry['world_id']}",
        {
            "base_state_sha256": version["state_sha256"],
            "object_id": "object:unbound-drift",
            "asset_sha256": CUBE,
            "region_id": "region:starter",
            "transform": {
                "x_mm": 0,
                "y_mm": 0,
                "z_mm": 0,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            },
            "origin_role": "fictional",
        },
    )
    assert drift.status_code == 201, drift.text
    drifted = api.get(f"/world-entries/{entry['entry_id']}").json()
    assert drifted["unavailable_reason"] == "authored_version_changed"

    removed = _removed(api, drifted, member["attachment_id"])
    assert removed["authored_state_sha256"] == entry["authored_state_sha256"]
    assert removed["unavailable_reason"] == "authored_version_changed"

    _renew_reviewed_source(repository, api, source)
    _refused(
        api.post(_path(entry, "source-rebinds"), _rebind_body(removed, source)),
        409,
        "stale_saved_world_entry",
    )


# -- retries and operation identity ---------------------------------------------------------


def test_an_exact_removal_retry_after_the_world_moved_returns_the_recorded_result(api, repository):
    entry, _source, member = _attached(api, repository, minute=21)
    body = _detach_body(entry, member["attachment_id"])
    removed = _ok(api.post(_path(entry, "source-detachments"), body))
    moved = _bound_object_edit(api, removed)
    assert moved["revision"] == removed["revision"] + 1
    assert moved["authored_edit_seq"] == removed["authored_edit_seq"] + 1

    retried = _ok(api.post(_path(entry, "source-detachments"), body))
    assert retried == moved
    assert len(_detach_rows(repository, entry)) == 1


def test_an_exact_return_retry_survives_a_cursor_move_a_newer_review_and_expiry(api, repository):
    entry, source, member = _attached(api, repository, minute=22)
    removed = _removed(api, entry, member["attachment_id"])
    short = _renew_reviewed_source(repository, api, source, valid_for_seconds=4)
    body = _rebind_body(removed, source)
    rebound = _ok(api.post(_path(entry, "source-rebinds"), body))
    pinned = rebound["source_attachments"][0]
    assert pinned["screening_id"] == short["screening_id"]

    moved = _bound_object_edit(api, rebound)
    assert _ok(api.post(_path(entry, "source-rebinds"), body)) == moved

    newer = _renew_reviewed_source(repository, api, source)
    assert newer["screening_id"] != short["screening_id"]
    assert _ok(api.post(_path(entry, "source-rebinds"), body)) == moved

    _wait_past(
        repository,
        _valid_until(
            repository, "reconstruction_privacy_screening", "screening_id", short["screening_id"]
        ),
    )
    expired = _ok(api.post(_path(entry, "source-rebinds"), body))
    assert expired["revision"] == moved["revision"]
    assert expired["source_attachments"][0]["attachment_id"] == pinned["attachment_id"]
    # The short review's authorization and screening end together; authorization is read first.
    assert expired["source_attachments"][0]["unavailable_reason"] == "authorization_expired"
    history = _history(repository, entry)
    assert [row["kind"] for row in history] == ["attach", "rebind"]
    assert str(history[1]["screening_id"]) == short["screening_id"]


def test_one_operation_identity_names_one_request_in_one_world(api, repository):
    entry, source, member = _attached(api, repository, minute=23)
    attach_operation = member["operation_id"]

    # A removal reusing the attach's identity is a conflict, not a server error.
    _refused(
        api.post(
            _path(entry, "source-detachments"),
            _detach_body(entry, member["attachment_id"], operation_id=attach_operation),
        ),
        409,
        "membership_event_operation_conflict",
    )
    detach_operation = uuid.uuid4()
    body = _detach_body(entry, member["attachment_id"], operation_id=detach_operation)
    removed = _ok(api.post(_path(entry, "source-detachments"), body))
    _refused(
        api.post(
            _path(entry, "source-detachments"),
            {**body, "selections": [{"attachment_id": str(uuid.uuid4())}]},
        ),
        409,
        "membership_event_operation_conflict",
    )
    _renew_reviewed_source(repository, api, source)
    _refused(
        api.post(
            _path(entry, "source-rebinds"),
            _rebind_body(removed, source, operation_id=detach_operation),
        ),
        409,
        "membership_event_operation_conflict",
    )
    other_photo = _reviewed_source(repository, api, minute=24)
    _refused(
        api.post(
            _path(entry, "source-attachments"),
            _attachment_body(removed, other_photo, operation_id=detach_operation),
        ),
        409,
        "source_attachment_operation_conflict",
    )
    rebind_operation = uuid.uuid4()
    rebound = _ok(
        api.post(
            _path(entry, "source-rebinds"),
            _rebind_body(removed, source, operation_id=rebind_operation),
        )
    )
    _refused(
        api.post(
            _path(entry, "source-rebinds"),
            {**_rebind_body(removed, source, operation_id=rebind_operation), "base_revision": 1},
        ),
        409,
        "membership_event_operation_conflict",
    )

    # Another saved world in the same workspace cannot reuse any of the three identities.
    personal, _version, _style = _create_entry(api, repository)
    personal_photo = _reviewed_source(repository, api, minute=25)
    for operation_id, route, request, code in (
        (
            detach_operation,
            "source-detachments",
            _detach_body(personal, uuid.uuid4(), operation_id=detach_operation),
            "membership_event_operation_conflict",
        ),
        (
            rebind_operation,
            "source-attachments",
            _attachment_body(personal, personal_photo, operation_id=rebind_operation),
            "source_attachment_operation_conflict",
        ),
        (
            uuid.UUID(attach_operation),
            "source-rebinds",
            _rebind_body(personal, personal_photo, operation_id=attach_operation),
            "membership_event_operation_conflict",
        ),
    ):
        _refused(api.post(_path(personal, route), request), 409, code)
        assert request["operation_id"] == str(operation_id)
    assert api.get(f"/world-entries/{entry['entry_id']}").json() == rebound
    assert api.get(f"/world-entries/{personal['entry_id']}").json() == personal


# -- concurrency ----------------------------------------------------------------------------------


def _released_together(ingest_spine, repository, calls):
    """Start every call while another connection holds the workspace lock, then release it.

    Waiting until each request is blocked on that lock proves they overlapped; a race where
    one request finished before the other started would test nothing.
    """
    _primary, open_another = ingest_spine
    holder = open_another().connection
    with ThreadPoolExecutor(max_workers=len(calls)) as executor:
        with holder.transaction():
            holder.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s::text,%s))",
                (repository.workspace_id, _LOCK_SEED),
            )
            futures = [executor.submit(call) for call in calls]
            deadline = monotonic() + 10
            while monotonic() < deadline:
                # Activity is sampled once per transaction; this one holds the lock, so it
                # clears its sample before each look.
                holder.execute("select pg_stat_clear_snapshot()")
                waiting = holder.execute(
                    "select count(*) as n from pg_stat_activity "
                    "where datname=current_database() and wait_event_type='Lock' "
                    "and wait_event='advisory' and pid<>pg_backend_pid()"
                ).fetchone()["n"]
                if waiting >= len(calls):
                    break
                sleep(0.01)
            else:
                raise AssertionError("the requests did not all wait on the workspace lock")
        return [future.result(timeout=10) for future in futures]


def test_two_removals_of_one_reference_race_and_one_records(api, repository, ingest_spine):
    entry, _source, member = _attached(api, repository, minute=26)
    responses = _released_together(
        ingest_spine,
        repository,
        [
            lambda: api.post(
                _path(entry, "source-detachments"), _detach_body(entry, member["attachment_id"])
            )
            for _ in range(2)
        ],
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    refused = next(response for response in responses if response.status_code == 409)
    assert refused.json()["code"] == "stale_saved_world_entry"
    assert len(_detach_rows(repository, entry)) == 1
    _assert_pointer_is_the_replay(repository, api.store, entry)


def test_concurrent_exact_retries_record_one_event(api, repository, ingest_spine):
    entry, _source, member = _attached(api, repository, minute=27)
    body = _detach_body(entry, member["attachment_id"])
    responses = _released_together(
        ingest_spine,
        repository,
        [lambda: api.post(_path(entry, "source-detachments"), body) for _ in range(2)],
    )
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert len(_detach_rows(repository, entry)) == 1


def test_a_removal_and_an_attachment_on_one_resume_point_serialize(api, repository, ingest_spine):
    entry, _source, member = _attached(api, repository, minute=28)
    other = _reviewed_source(repository, api, minute=29)
    responses = _released_together(
        ingest_spine,
        repository,
        [
            lambda: api.post(
                _path(entry, "source-detachments"), _detach_body(entry, member["attachment_id"])
            ),
            lambda: api.post(_path(entry, "source-attachments"), _attachment_body(entry, other)),
        ],
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    final = api.get(f"/world-entries/{entry['entry_id']}").json()
    assert final["revision"] == entry["revision"] + 1
    _assert_pointer_is_the_replay(repository, api.store, entry)


# -- isolation ----------------------------------------------------------------------------------


def test_another_workspace_can_neither_see_nor_move_this_worlds_references(
    api, repository, runtime_session
):
    entry, source, member = _attached(api, repository, minute=30)
    for response in (
        api.stranger_get(f"/world-entries/{entry['entry_id']}"),
        api.stranger_post(
            _path(entry, "source-detachments"), _detach_body(entry, member["attachment_id"])
        ),
        api.stranger_post(_path(entry, "source-rebinds"), _rebind_body(entry, source)),
    ):
        _refused(response, 404, "unknown_reference")
    assert api.get(f"/world-entries/{entry['entry_id']}").json() == entry

    removed = _removed(api, entry, member["attachment_id"])
    with runtime_session(uuid.uuid4()) as foreign:
        for table in (
            "saved_world_source_current_membership",
            "saved_world_source_detach",
            "saved_world_source_detach_operation",
            "saved_world_source_attachment",
        ):
            count = foreign.execute(
                sql.SQL("select count(*) as n from {}").format(sql.Identifier(table))
            ).fetchone()
            assert count["n"] == 0, table
    with runtime_session() as own:
        assert (
            own.execute("select count(*) as n from saved_world_source_detach").fetchone()["n"] == 1
        )
    assert removed["previous_source_attachments"][0]["attachment_id"] == member["attachment_id"]


# -- the database's own walls -----------------------------------------------------------------


def test_the_runtime_role_cannot_move_current_membership_without_an_event(
    api, repository, runtime_session
):
    entry, source, member = _attached(api, repository, minute=31)
    entry_id = uuid.UUID(entry["entry_id"])
    attachment_id = uuid.UUID(member["attachment_id"])
    with runtime_session() as app:
        for statement, params in (
            (
                "update saved_world_source_current_membership set attachment_id=null "
                "where entry_id=%s",
                (entry_id,),
            ),
            (
                "insert into saved_world_source_current_membership "
                "(workspace_id,entry_id,capture_id,attachment_id) values (%s,%s,%s,null)",
                (repository.workspace_id, entry_id, uuid.uuid4()),
            ),
            ("delete from saved_world_source_current_membership where entry_id=%s", (entry_id,)),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app.execute(statement, params)

    # A runtime role still holding a write grant, and the owner, meet the trigger instead.
    repository.connection.execute(
        sql.SQL("grant insert, update on saved_world_source_current_membership to {}").format(
            sql.Identifier(RUNTIME_ROLE)
        )
    )
    try:
        with (
            runtime_session() as app,
            pytest.raises(psycopg.errors.InsufficientPrivilege, match="moves only with"),
        ):
            app.execute(
                "update saved_world_source_current_membership set attachment_id=null "
                "where entry_id=%s",
                (entry_id,),
            )
    finally:
        provision_runtime_role(repository.connection)
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="moves only with"):
        repository.connection.execute(
            "update saved_world_source_current_membership set attachment_id=null "
            "where workspace_id=%s and entry_id=%s",
            (repository.workspace_id, entry_id),
        )
    assert _pointer(repository, entry, source["capture_id"]) == attachment_id
    assert api.get(f"/world-entries/{entry['entry_id']}").json() == entry


def _forged_operation(app, repository, entry, *, kind, operation_id=None, table="attachment"):
    operation_id = operation_id or uuid.uuid4()
    columns = (
        "(workspace_id,operation_id,entry_id,request_sha256,base_entry_revision,"
        "result_entry_revision,authored_version_id,authored_state_sha256,authored_edit_seq,"
        "style_version_id,created_by"
    )
    values = [
        repository.workspace_id,
        operation_id,
        uuid.UUID(entry["entry_id"]),
        b"\x01" * 32,
        entry["revision"],
        entry["revision"] + 1,
        uuid.UUID(entry["authored_version_id"]),
        entry["authored_state_sha256"],
        entry["authored_edit_seq"],
        uuid.UUID(entry["style_version_id"]),
        repository_actor(entry),
    ]
    if table == "attachment":
        app.execute(
            f"insert into saved_world_source_attachment_operation {columns},kind) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (*values, kind),
        )
    else:
        app.execute(
            f"insert into saved_world_source_detach_operation {columns}) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            tuple(values),
        )
    return operation_id


def repository_actor(entry):
    return uuid.UUID(entry["created_by"])


def _forged_attachment(app, repository, entry, operation_id, source):
    app.execute(
        "insert into saved_world_source_attachment (workspace_id,entry_id,operation_id,"
        "capture_id,evidence_span_id,source_sha256,authorization_id,screening_id,"
        "attached_entry_revision,attached_by) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            repository.workspace_id,
            uuid.UUID(entry["entry_id"]),
            operation_id,
            uuid.UUID(source["capture_id"]),
            uuid.UUID(source["evidence_span_id"]),
            bytes.fromhex(source["source_sha256"]),
            uuid.UUID(source["authorization_id"]),
            uuid.UUID(source["screening_id"]),
            entry["revision"] + 1,
            repository_actor(entry),
        ),
    )


def test_forged_events_cannot_move_membership_the_wrong_way(api, repository, runtime_session):
    entry, source, member = _attached(api, repository, minute=32)
    other = _reviewed_source(repository, api, minute=33)
    current = _ok(api.post(_path(entry, "source-attachments"), _attachment_body(entry, other)))
    removed = _removed(api, current, member["attachment_id"])
    renewed = _renew_reviewed_source(repository, api, source)
    other_renewed = _renew_reviewed_source(repository, api, other)
    before = api.get(f"/world-entries/{entry['entry_id']}").json()
    assert before == removed

    cases = (
        # Attach of a removed photograph.
        ("attach", renewed, psycopg.errors.IntegrityConstraintViolation, "no membership"),
        # Rebind with receipts the first membership pinned.
        ("rebind", source, psycopg.errors.IntegrityConstraintViolation, "new human review"),
        # Rebind of a photograph still in the world.
        ("rebind", other_renewed, psycopg.errors.IntegrityConstraintViolation, "removed from"),
    )
    with runtime_session() as app:
        for kind, receipts, error, message in cases:
            with pytest.raises(error, match=message), app.transaction():
                operation = _forged_operation(app, repository, removed, kind=kind)
                _forged_attachment(app, repository, removed, operation, receipts)

        # A second detach of a removed attachment.
        with pytest.raises(psycopg.errors.UniqueViolation), app.transaction():
            operation = _forged_operation(app, repository, removed, kind=None, table="detach")
            app.execute(
                "insert into saved_world_source_detach (workspace_id,entry_id,operation_id,"
                "attachment_id,capture_id,detached_entry_revision,detached_by) "
                "values (%s,%s,%s,%s,%s,%s,%s)",
                (
                    repository.workspace_id,
                    uuid.UUID(entry["entry_id"]),
                    operation,
                    uuid.UUID(member["attachment_id"]),
                    uuid.UUID(source["capture_id"]),
                    removed["revision"] + 1,
                    repository_actor(entry),
                ),
            )

        # A detach of the current attachment that does not advance the saved world is refused at
        # commit, and the pointer it moved comes back with the rollback.
        other_member = next(
            row for row in removed["source_attachments"] if row["capture_id"] == other["capture_id"]
        )
        with (
            pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="advance"),
            app.transaction(),
        ):
            operation = _forged_operation(app, repository, removed, kind=None, table="detach")
            app.execute(
                "insert into saved_world_source_detach (workspace_id,entry_id,operation_id,"
                "attachment_id,capture_id,detached_entry_revision,detached_by) "
                "values (%s,%s,%s,%s,%s,%s,%s)",
                (
                    repository.workspace_id,
                    uuid.UUID(entry["entry_id"]),
                    operation,
                    uuid.UUID(other_member["attachment_id"]),
                    uuid.UUID(other["capture_id"]),
                    removed["revision"] + 1,
                    repository_actor(entry),
                ),
            )

        # An identity already used by an attach cannot become a detach.
        with (
            pytest.raises(psycopg.errors.UniqueViolation, match="already names"),
            app.transaction(),
        ):
            _forged_operation(
                app,
                repository,
                removed,
                kind=None,
                table="detach",
                operation_id=uuid.UUID(member["operation_id"]),
            )

    assert api.get(f"/world-entries/{entry['entry_id']}").json() == before
    assert len(_history(repository, entry)) == 2
    assert len(_detach_rows(repository, entry)) == 1


# -- pairs and database facts adopted from the review B probes ----------------------------------


def test_a_removal_and_a_return_of_one_photograph_race(api, repository, ingest_spine):
    """Detach of photograph B against rebind of photograph A, from one resume point."""
    entry, first, member = _attached(api, repository, minute=61)
    other = _reviewed_source(repository, api, minute=62)
    state = _ok(api.post(_path(entry, "source-attachments"), _attachment_body(entry, other)))
    state = _removed(api, state, member["attachment_id"])
    _renew_reviewed_source(repository, api, first)
    kept = next(
        row for row in state["source_attachments"] if row["capture_id"] == other["capture_id"]
    )

    responses = _released_together(
        ingest_spine,
        repository,
        [
            lambda: api.post(
                _path(state, "source-detachments"), _detach_body(state, kept["attachment_id"])
            ),
            lambda: api.post(_path(state, "source-rebinds"), _rebind_body(state, first)),
        ],
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    refused = next(response for response in responses if response.status_code == 409)
    assert refused.json()["code"] == "stale_saved_world_entry", refused.text
    final = api.get(f"/world-entries/{entry['entry_id']}").json()
    assert final["revision"] == state["revision"] + 1
    _assert_pointer_is_the_replay(repository, api.store, entry)


def test_two_returns_of_one_photograph_race_and_one_records(api, repository, ingest_spine):
    entry, source, member = _attached(api, repository, minute=63)
    state = _removed(api, entry, member["attachment_id"])
    _renew_reviewed_source(repository, api, source)

    responses = _released_together(
        ingest_spine,
        repository,
        [
            lambda: api.post(_path(state, "source-rebinds"), _rebind_body(state, source))
            for _ in range(2)
        ],
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(_history(repository, entry)) == 2
    final = api.get(f"/world-entries/{entry['entry_id']}").json()
    assert len(final["source_attachments"]) == 1
    _assert_pointer_is_the_replay(repository, api.store, entry)


def test_an_attachment_and_a_return_on_one_resume_point_serialize(api, repository, ingest_spine):
    entry, source, member = _attached(api, repository, minute=64)
    state = _removed(api, entry, member["attachment_id"])
    _renew_reviewed_source(repository, api, source)
    fresh = _reviewed_source(repository, api, minute=65)

    responses = _released_together(
        ingest_spine,
        repository,
        [
            lambda: api.post(_path(state, "source-attachments"), _attachment_body(state, fresh)),
            lambda: api.post(_path(state, "source-rebinds"), _rebind_body(state, source)),
        ],
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    final = api.get(f"/world-entries/{entry['entry_id']}").json()
    assert final["revision"] == state["revision"] + 1
    assert len(final["source_attachments"]) == 1
    _assert_pointer_is_the_replay(repository, api.store, entry)


def test_a_removal_races_an_authored_edit_advancing_the_same_entry(api, repository, ingest_spine):
    """Exactly one of the two writers wins; the loser is a stable refusal, not a 500."""
    entry, source, member = _attached(api, repository, minute=66)
    outcome: dict[str, object] = {}

    def authored_edit():
        try:
            outcome["edit"] = _bound_object_edit(api, entry, object_id="object:membership-race")
        except AssertionError as failure:  # the object route refused; record how
            outcome["edit"] = failure
        return outcome["edit"]

    responses = _released_together(
        ingest_spine,
        repository,
        [
            lambda: api.post(
                _path(entry, "source-detachments"), _detach_body(entry, member["attachment_id"])
            ),
            authored_edit,
        ],
    )
    detach = responses[0]
    assert detach.status_code in (200, 409), detach.text
    if detach.status_code == 409:
        assert detach.json()["code"] == "stale_saved_world_entry", detach.text
        assert not isinstance(outcome["edit"], AssertionError)
    final = api.get(f"/world-entries/{entry['entry_id']}").json()
    assert final["revision"] == entry["revision"] + 1
    assert len(_detach_rows(repository, entry)) == (1 if detach.status_code == 200 else 0)
    assert source["capture_id"]
    _assert_pointer_is_the_replay(repository, api.store, entry)


def test_the_definer_functions_pin_a_search_path_and_no_role_may_call_them(api, repository):
    rows = _rows(
        repository,
        "select p.proname,p.prosecdef,p.proconfig,pg_get_userbyid(p.proowner) as owner,"
        "has_function_privilege(%s,p.oid,'EXECUTE') as runtime_may_execute "
        "from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
        "where n.nspname=current_schema() and p.proname like 'tg_saved_world_source%%' "
        "order by p.proname",
        RUNTIME_ROLE,
    )
    by_name = {row["proname"]: row for row in rows}
    for name in _DEFINERS:
        row = by_name[name]
        assert row["prosecdef"] is True
        assert any(str(item).startswith("search_path=") for item in row["proconfig"] or []), row
        assert row["runtime_may_execute"] is False, row
    # Every other trigger function on these tables runs as the role whose write fired it.
    for name, row in by_name.items():
        if name not in _DEFINERS:
            assert row["prosecdef"] is False, name


def test_the_runtime_role_cannot_reach_the_definer_functions_or_truncate_the_event_tables(
    api, repository, runtime_session
):
    entry, source, member = _attached(api, repository, minute=67)
    verbs = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "TRIGGER", "REFERENCES")
    held = {
        (table, verb): _rows(
            repository,
            "select has_table_privilege(%s,%s,%s) as held",
            RUNTIME_ROLE,
            table,
            verb,
        )[0]["held"]
        for table in (
            "saved_world_source_current_membership",
            "saved_world_source_detach",
            "saved_world_source_detach_operation",
            "saved_world_source_attachment",
        )
        for verb in verbs
    }
    assert {key for key, value in held.items() if value} == {
        ("saved_world_source_detach", "INSERT"),
        ("saved_world_source_detach_operation", "INSERT"),
        ("saved_world_source_attachment", "INSERT"),
    }
    assert (
        _rows(
            repository,
            "select has_schema_privilege(%s,current_schema(),'CREATE') as held",
            RUNTIME_ROLE,
        )[0]["held"]
        is False
    )
    with runtime_session() as app:
        for name in _DEFINERS:
            with pytest.raises(psycopg.errors.Error), app.transaction():
                app.execute(sql.SQL("select {}()").format(sql.Identifier(name)))
        for table in ("saved_world_source_current_membership", "saved_world_source_detach"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), app.transaction():
                app.execute(sql.SQL("truncate table {}").format(sql.Identifier(table)))
    assert (
        api.get(f"/world-entries/{entry['entry_id']}").json()["source_attachments"][0][
            "attachment_id"
        ]
        == member["attachment_id"]
    )
    assert source["capture_id"]


def test_removing_a_membership_that_is_not_current_is_refused(api, repository):
    """Through the route: a stale attachment id never clears a live pointer."""
    entry, source, member = _attached(api, repository, minute=68)
    state = _removed(api, entry, member["attachment_id"])
    _renew_reviewed_source(repository, api, source)
    rebound = _ok(api.post(_path(state, "source-rebinds"), _rebind_body(state, source)))
    assert rebound["source_attachments"][0]["attachment_id"] != member["attachment_id"]

    _refused(
        api.post(
            _path(rebound, "source-detachments"), _detach_body(rebound, member["attachment_id"])
        ),
        422,
        "membership_unavailable",
    )
    assert api.get(f"/world-entries/{entry['entry_id']}").json() == rebound
    _assert_pointer_is_the_replay(repository, api.store, entry)


def test_a_role_row_level_security_reaches_errors_rather_than_reading_nothing(
    api, repository, runtime_session
):
    """What ``row_security = off`` does to a role row-level security reaches.

    ``pg_dump`` sets it, so a backup taken by a role the policies apply to fails loudly instead
    of writing a dump with no rows in it. The retained upgrade plan names a superuser or
    BYPASSRLS role for the dump for this reason, and forbids ``--enable-row-security``, which
    would read the forced tables through the policies and dump nothing.
    """
    _attached(api, repository, minute=69)
    with runtime_session() as app, app.transaction():
        app.execute("set local row_security = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            app.execute("select count(*) from saved_world_source_attachment").fetchone()
