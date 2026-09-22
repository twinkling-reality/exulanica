"""Migration 0090 over saved worlds that already hold reference photographs.

A schema is migrated to 0089 and filled the way that release filled it: starter worlds through
the saved-world repository, photographs through the ingest pipeline and the personal privacy
receipts, and attachments through the statements the pre-0090 repository ran, under 0086's own
validating triggers. The current repository cannot write them because it needs 0090's tables.

Before 0090 the read path treated every attachment row as current. Two stand-in views state
exactly that so the current route can answer ``GET /world-entries/{entry_id}`` over the 0089
schema; they are removed before the migration runs. The same route after the migration must
return the same bodies, and the row counts must hold.

The upgrade runs twice: as the bootstrap superuser the test servers use, and with the
attachment tables owned by a role that is neither superuser nor BYPASSRLS. Under that owner the
0090 first written read nothing through FORCE row-level security and committed an empty
collection; measured, that is why the backfill now lifts FORCE for its read.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from types import SimpleNamespace

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.canonical import sha256_of_canonical
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.db.session import Database
from exulanica.env import env_get
from exulanica.ingest.privacy import record_human_screening
from exulanica.ingest.repository import IngestRepository
from exulanica.migrations import migrations
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.saved_entries import SavedWorldEntryRepository, SourceAttachmentSelection
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

import pg_harness
from test_saved_world_entries_api import _renew_reviewed_source, _reviewed_source
from tests_support_api import EVERY_PERMISSION

pytestmark = pytest.mark.postgres

_OWNER = "exulanica_membership_backfill_owner"

#: What the 0089 read path meant: every attachment row is current and nothing was detached.
_STAND_INS = (
    "create view saved_world_source_current_membership as "
    "select workspace_id,entry_id,capture_id,attachment_id from saved_world_source_attachment",
    "create view saved_world_source_detach as select null::uuid as detach_id,"
    "null::uuid as workspace_id,null::uuid as entry_id,null::uuid as operation_id,"
    "null::uuid as attachment_id,null::uuid as capture_id,null::bigint as detached_entry_revision,"
    "null::uuid as detached_by,null::timestamptz as detached_at where false",
)


def _database(scratch: str, *, role: str | None = None) -> Database:
    base = env_get("TEST_DATABASE_URL")
    assert base is not None
    options = f"-csearch_path={scratch},public" + (f" -crole={role}" if role else "")
    return Database(url=make_conninfo(base, options=options))


def _attach_as_released_before_0090(connection, workspace_id, entry, sources, actor, store):
    """The pre-0090 repository's attach: its digest, its three writes, one transaction.

    Receipts come from the repository's resolver, which 0090 does not change.
    """
    repository = SavedWorldEntryRepository(connection, workspace_id, store)
    selections = [
        SourceAttachmentSelection(uuid.UUID(s["capture_id"]), uuid.UUID(s["evidence_span_id"]))
        for s in sources
    ]
    operation_id = uuid.uuid4()
    body = {
        "entry_id": str(entry.entry_id),
        "operation_id": str(operation_id),
        "base_revision": entry.revision,
        "authored_version_id": str(entry.authored_version_id),
        "authored_state_sha256": entry.authored_state_sha256,
        "authored_edit_seq": entry.authored_edit_seq,
        "style_version_id": str(entry.style_version_id),
        "sources": [
            {"capture_id": str(s.capture_id), "evidence_span_id": str(s.evidence_span_id)}
            for s in selections
        ],
        "attached_by": str(actor),
    }
    with connection.transaction():
        repository._lock_workspace()
        connection.execute(
            "insert into saved_world_source_attachment_operation "
            "(workspace_id,operation_id,entry_id,request_sha256,base_entry_revision,"
            "result_entry_revision,authored_version_id,authored_state_sha256,"
            "authored_edit_seq,style_version_id,created_by) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                workspace_id,
                operation_id,
                entry.entry_id,
                sha256_of_canonical(body),
                entry.revision,
                entry.revision + 1,
                entry.authored_version_id,
                entry.authored_state_sha256,
                entry.authored_edit_seq,
                entry.style_version_id,
                actor,
            ),
        )
        for selection in selections:
            authority = repository._resolve_attachment(selection, actor)
            connection.execute(
                "insert into saved_world_source_attachment "
                "(workspace_id,entry_id,operation_id,capture_id,evidence_span_id,"
                "source_sha256,authorization_id,screening_id,attached_entry_revision,"
                "attached_by) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    workspace_id,
                    entry.entry_id,
                    operation_id,
                    selection.capture_id,
                    selection.evidence_span_id,
                    authority["source_sha256"],
                    authority["authorization_id"],
                    authority["screening_id"],
                    entry.revision + 1,
                    actor,
                ),
            )
        connection.execute(
            "update saved_world_entry set revision=revision+1,updated_at=now() "
            "where workspace_id=%s and entry_id=%s and revision=%s",
            (workspace_id, entry.entry_id, entry.revision),
        )
    return {
        "operation_id": str(operation_id),
        "base_revision": entry.revision,
        "authored_version_id": str(entry.authored_version_id),
        "authored_state_sha256": entry.authored_state_sha256,
        "authored_edit_seq": entry.authored_edit_seq,
        "style_version_id": str(entry.style_version_id),
        "sources": body["sources"],
    }


def _short_review(repository, photographer, *, minute: int) -> dict:
    """A photograph whose authority stays current and whose newest human review expires.

    The resolver pins the newest allowed screening, so the attachment ends up on this one and
    the reference reads `screening_expired` rather than `authorization_expired`.
    """
    source = _reviewed_source(repository, photographer, minute=minute)
    now = repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    screening = record_human_screening(
        repository,
        authorization_id=uuid.UUID(source["authorization_id"]),
        reviewed_by=photographer.actor,
        sensitive_regions=[],
        screened_at=now,
        valid_until=now + dt.timedelta(seconds=2),
    )
    return {**source, "screening_id": str(screening.screening_id)}


def _counts(admin) -> dict[str, int]:
    return {
        table: admin.execute(
            sql.SQL("select count(*) from {}").format(sql.Identifier(table))
        ).fetchone()[0]
        for table in ("saved_world_source_attachment", "saved_world_source_attachment_operation")
    }


def _as_owner(admin, owned: bool):
    if owned:
        admin.execute(sql.SQL("set role {}").format(sql.Identifier(_OWNER)))


@pytest.mark.parametrize("owner", ["bootstrap superuser", "non-superuser owner"])
def test_0090_keeps_every_reference_a_populated_0089_database_held(
    owner, spine_schema, monkeypatch, tmp_path
):
    owned = owner == "non-superuser owner"
    everything = list(migrations())
    by_version = {migration.version: migration for migration in everything}
    first = "0086" if owned else "0090"
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness, "migrations", lambda: iter(m for m in everything if m.version < first)
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            scratch = admin.execute("select current_schema()").fetchone()[0]
            if owned:
                if not admin.execute(
                    "select 1 from pg_roles where rolname=%s", (_OWNER,)
                ).fetchone():
                    admin.execute(
                        sql.SQL("create role {} nologin nosuperuser nobypassrls").format(
                            sql.Identifier(_OWNER)
                        )
                    )
                for statement in (
                    "grant usage, create on schema {} to {}",
                    "grant all on all tables in schema {} to {}",
                ):
                    admin.execute(
                        sql.SQL(statement).format(sql.Identifier(scratch), sql.Identifier(_OWNER))
                    )
                admin.commit()
                # The attachment tables belong to a role row-level security binds.
                _as_owner(admin, owned)
                admin.execute(by_version["0086"].sql)
                admin.execute("reset role")
                for version in ("0087", "0088", "0089"):
                    admin.execute(by_version[version].sql)
            for statement in _STAND_INS:
                admin.execute(statement)
            admin.commit()
            provision_runtime_role(admin)
            admin.commit()

            store = LocalContentAddressedStore(tmp_path / "blobs")
            actor = uuid.uuid4()
            workspaces = [uuid.uuid4() for _ in range(3)]
            tokens = {
                f"membership-backfill-token-{index}-long-enough-for-tests": w
                for index, w in enumerate(workspaces)
            }
            monkeypatch.setenv(
                "EXULANICA_API_TOKENS",
                json.dumps(
                    {
                        token: {
                            "workspace_id": str(workspace),
                            "actor": str(actor),
                            "permissions": EVERY_PERMISSION,
                        }
                        for token, workspace in tokens.items()
                    }
                ),
            )
            owner_database = _database(scratch)
            photographer = SimpleNamespace(store=store, actor=actor)
            entries, retries, sources_by_workspace, expiring = {}, {}, {}, {}
            for index, workspace in enumerate(workspaces):
                with owner_database.session(workspace) as connection:
                    repository = IngestRepository(connection, workspace)
                    saved = SavedWorldEntryRepository(connection, workspace, store)
                    entry = saved.create_starter(title=f"World {index}", created_by=actor)
                    photos = [
                        _reviewed_source(repository, photographer, minute=10 * index + n)
                        for n in range(3 - index)
                    ]
                    sources_by_workspace[workspace] = photos
                    if index == 0:
                        # Two operations, the first with two photographs, and a third holding
                        # the three ways a reference is unavailable: the authority expired, the
                        # review expired, the original photograph was deleted. An upgrade that
                        # carried only readable references would look correct here without them.
                        retries[workspace] = _attach_as_released_before_0090(
                            connection, workspace, entry, photos[:2], actor, store
                        )
                        entry = saved.entry(entry.entry_id)
                        _attach_as_released_before_0090(
                            connection, workspace, entry, photos[2:], actor, store
                        )
                        entry = saved.entry(entry.entry_id)
                        unavailable = [
                            _reviewed_source(
                                repository, photographer, minute=7, valid_for_seconds=2
                            ),
                            _short_review(repository, photographer, minute=8),
                            _reviewed_source(repository, photographer, minute=9),
                        ]
                        _attach_as_released_before_0090(
                            connection, workspace, entry, unavailable, actor, store
                        )
                        repository.insert_tombstone(
                            scope="capture",
                            capture_id=uuid.UUID(unavailable[2]["capture_id"]),
                            requested_by=actor,
                        )
                        connection.execute("select pg_sleep(2.2)")
                        expiring[workspace] = unavailable
                    elif index == 1:
                        retries[workspace] = _attach_as_released_before_0090(
                            connection, workspace, entry, photos[:1], actor, store
                        )
                    entries[workspace] = saved.entry(entry.entry_id)

            runtime = _database(scratch, role=RUNTIME_ROLE)
            services = Services(
                database=runtime,
                readonly_database=runtime,
                store=store,
                tokens=load_token_directory(),
                executor_shares_the_write_role=True,
                model_client=None,
            )

            def read_all(client):
                return {
                    workspace: client.get(
                        f"/world-entries/{entries[workspace].entry_id}",
                        headers={"Authorization": f"Bearer {token}"},
                    ).json()
                    for token, workspace in tokens.items()
                }

            with TestClient(create_app(services, verify=False)) as client:
                before = read_all(client)
            assert [len(before[w]["source_attachments"]) for w in workspaces] == [6, 1, 0]
            reasons = {
                member["capture_id"]: member["unavailable_reason"]
                for member in before[workspaces[0]]["source_attachments"]
            }
            expired_authority, expired_review, deleted = expiring[workspaces[0]]
            assert reasons[expired_authority["capture_id"]] == "authorization_expired"
            assert reasons[expired_review["capture_id"]] == "screening_expired"
            assert reasons[deleted["capture_id"]] == "source_unavailable"
            assert sum(1 for value in reasons.values() if value is None) == 3
            counts = _counts(admin)
            assert counts == {
                "saved_world_source_attachment": 7,
                "saved_world_source_attachment_operation": 4,
            }

            admin.execute("drop view saved_world_source_detach")
            admin.execute("drop view saved_world_source_current_membership")
            admin.commit()
            _as_owner(admin, owned)
            admin.execute(by_version["0090"].sql)
            admin.execute("reset role")
            # Migrations first, then roles, as the provisioning command runs them.
            provision_runtime_role(admin)
            admin.commit()

            assert _counts(admin) == counts
            pointers = admin.execute(
                "select c.workspace_id,c.entry_id,c.capture_id,c.attachment_id "
                "from saved_world_source_current_membership c order by c.attachment_id"
            ).fetchall()
            history = admin.execute(
                "select workspace_id,entry_id,capture_id,attachment_id "
                "from saved_world_source_attachment order by attachment_id"
            ).fetchall()
            assert pointers == history
            assert admin.execute(
                "select array_agg(distinct kind) from saved_world_source_attachment_operation"
            ).fetchone()[0] == ["attach"]
            forced = admin.execute(
                "select relname, relforcerowsecurity from pg_class "
                "where relnamespace=%s::regnamespace and relname = any(%s) order by relname",
                (
                    scratch,
                    [
                        "saved_world_source_attachment",
                        "saved_world_source_current_membership",
                        "saved_world_source_detach",
                        "saved_world_source_detach_operation",
                    ],
                ),
            ).fetchall()
            assert all(flag for _name, flag in forced) and len(forced) == 4

            with TestClient(create_app(services, verify=False)) as client:
                after = read_all(client)
                assert after == before
                assert all(body["previous_source_attachments"] == [] for body in after.values())

                # A retry of an attachment recorded before the upgrade is still that request.
                token = next(t for t, w in tokens.items() if w == workspaces[0])
                headers = {"Authorization": f"Bearer {token}"}
                path = f"/world-entries/{entries[workspaces[0]].entry_id}"
                retried = client.post(
                    f"{path}/source-attachments", headers=headers, json=retries[workspaces[0]]
                )
                assert retried.status_code == 200, retried.text
                assert retried.json() == after[workspaces[0]]

                # The lifecycle works on migrated references, through the runtime role.
                member = next(
                    row
                    for row in after[workspaces[0]]["source_attachments"]
                    if row["availability"] == "available"
                )
                cursor = {
                    key: after[workspaces[0]][key]
                    for key in (
                        "authored_version_id",
                        "authored_state_sha256",
                        "authored_edit_seq",
                        "style_version_id",
                    )
                }
                removed = client.post(
                    f"{path}/source-detachments",
                    headers=headers,
                    json={
                        "operation_id": str(uuid.uuid4()),
                        "base_revision": after[workspaces[0]]["revision"],
                        **cursor,
                        "selections": [{"attachment_id": member["attachment_id"]}],
                    },
                )
                assert removed.status_code == 200, removed.text
                assert len(removed.json()["source_attachments"]) == 5
                photo = next(
                    s
                    for s in sources_by_workspace[workspaces[0]]
                    if s["capture_id"] == member["capture_id"]
                )
                with owner_database.session(workspaces[0]) as connection:
                    _renew_reviewed_source(
                        IngestRepository(connection, workspaces[0]), photographer, photo
                    )
                rebound = client.post(
                    f"{path}/source-rebinds",
                    headers=headers,
                    json={
                        "operation_id": str(uuid.uuid4()),
                        "base_revision": removed.json()["revision"],
                        **cursor,
                        "sources": [
                            {
                                "capture_id": photo["capture_id"],
                                "evidence_span_id": photo["evidence_span_id"],
                            }
                        ],
                    },
                )
                assert rebound.status_code == 200, rebound.text
                assert len(rebound.json()["source_attachments"]) == 6
                assert rebound.json()["previous_source_attachments"] == []
            admin.commit()


def test_a_failing_0090_restores_force_row_level_security(monkeypatch):
    """The lift and the restore are in one transaction, so a failure cannot publish the lift."""
    everything = list(migrations())
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness, "migrations", lambda: iter(m for m in everything if m.version < "0090")
        )
        with pg_harness.migrated_schema() as (_module, admin):
            forced = (
                "select relforcerowsecurity from pg_class "
                "where oid='saved_world_source_attachment'::regclass"
            )
            assert admin.execute(forced).fetchone()[0] is True
            text = next(m for m in everything if m.version == "0090").sql
            marker = "alter table saved_world_source_attachment no force row level security;"
            broken = text.replace(
                marker,
                marker + "\ndo $$ begin raise exception 'injected upgrade failure'; end $$;",
            )
            assert broken != text
            with pytest.raises(psycopg.errors.RaiseException, match="injected upgrade failure"):
                admin.execute(broken)
            admin.rollback()
            assert admin.execute(forced).fetchone()[0] is True
            assert (
                admin.execute(
                    "select count(*) from information_schema.tables "
                    "where table_schema=current_schema() "
                    "and table_name='saved_world_source_current_membership'"
                ).fetchone()[0]
                == 0
            )


def test_the_backfill_reads_with_row_security_off_and_asserts_its_count():
    """The text holds the two guards the measured failure needs; the test above runs them."""
    text = next(m for m in migrations() if m.version == "0090").sql
    backfill = text.index("insert into saved_world_source_current_membership (")
    assert text.index("set local row_security = off;") < backfill
    assert (
        text.index("alter table saved_world_source_attachment no force row level security;")
        < backfill
    )
    assert backfill < text.index("current membership backfill wrote % pointers")
    assert backfill < text.index(
        "alter table saved_world_source_attachment force row level security;"
    )
    # No write trigger exists on the pointer while the backfill fills it.
    assert backfill < text.index("create trigger tg_saved_world_source_current_membership_guard")
