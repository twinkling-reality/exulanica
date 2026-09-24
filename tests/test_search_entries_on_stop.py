"""Stopping a photograph's search right deletes the search entries made from its descriptions.

The search right is a personal model right for the embedding role ("Search index" in the photo
drawer). Stopping it writes a ``caption_search`` tombstone over the photograph (migration 0104),
whose cascade records every search entry made from the photograph's descriptions as a vector
target and queues its purge, the way deleting the photograph does; the purge role destroys them.
A search entry whose model another current right still covers for that photograph is kept, and is
deleted when the last such right stops. A vector whose result reaches the database after the stop
is refused there, so a call in flight cannot put it back. The photograph itself, its descriptions
and its other rights are untouched, so it is still found by the words of its description.

Every withdrawal here connects as the runtime role and every purge as the purge role: the
fixture's own connection is the schema owner, which row-level security does not bind.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import threading
import uuid

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.deletion import queue
from exulanica.epistemics.caption_embeddings import embed_capture
from exulanica.ingest.model_rights import grant_model_right, withdraw_model_right
from exulanica.ingest.personal_admission import MODEL_RIGHT_USES, role_handoff
from exulanica.ingest.personal_requests import admission_status
from exulanica.ingest.privacy import authorize_personal_capture
from exulanica.ingest.repository import IngestRepository
from exulanica.models.manifest import Role
from exulanica.selection.embeddings import QueryEmbedding, has_embeddings
from fastapi.testclient import TestClient

from test_companion_matching import run, script, unchecked, vector
from test_purge import _APP_PASSWORD, _APP_ROLE, _PURGE_ROLE
from test_purge import purged as purged
from tests_support_api import EVERY_PERMISSION

pytestmark = pytest.mark.postgres

ACCOUNT = uuid.UUID("0190a000-0000-7000-8000-0000000000aa")
PURPOSE = "Find my own photographs by what they show."
#: A word of the fixture photograph's own description, which the lexical search matches locally.
DESCRIBED = "red"
#: Words the fixture photograph's description does not hold, which the lexical search never matches.
UNDESCRIBED = "zebra quartz"


@dataclasses.dataclass
class Indexed:
    fixture: object
    capture_id: uuid.UUID
    authorization_id: uuid.UUID
    embedding_id: uuid.UUID
    rights: dict[Role, list]


def _now(repository) -> dt.datetime:
    return repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]


def _authorize(repository, capture_id, *, scope=None):
    now = _now(repository)
    return authorize_personal_capture(
        repository,
        capture_id=capture_id,
        actor=ACCOUNT,
        account_authority_basis="I took this photograph",
        authorization_scope=scope or {"purpose": PURPOSE},
        purpose=PURPOSE,
        authorized_at=now - dt.timedelta(hours=1),
        valid_until=now + dt.timedelta(hours=2),
    )


def _grant(repository, capture_id, authorization_id, role: Role, manifest, *, minutes=60):
    handoff = role_handoff(role.value, manifest)
    now = _now(repository)
    return [
        grant_model_right(
            repository,
            capture_id=capture_id,
            authorization_id=authorization_id,
            identity=identity,
            destination=handoff.destination,
            granted_by=ACCOUNT,
            purpose=PURPOSE,
            valid_until=now + dt.timedelta(minutes=minutes),
        )
        for identity in handoff.identities
    ]


def _index(fixture, client, monkeypatch, *, scope=None) -> Indexed:
    repository = fixture.repository
    capture = fixture.rows("select capture_id from capture")[0]["capture_id"]
    authorization = _authorize(repository, capture, scope=scope)
    rights = {
        role: _grant(repository, capture, authorization.authorization_id, role, client.manifest)
        for role in (Role.VISION, Role.EMBEDDING)
    }
    script(client, monkeypatch, vector())
    embed_capture(
        repository.connection, fixture.workspace_id, capture, client, before_send=unchecked
    )
    embedding = fixture.rows("select embedding_id from embedding")
    assert len(embedding) == 1, "the fixture photograph made no search entry"
    return Indexed(
        fixture, capture, authorization.authorization_id, embedding[0]["embedding_id"], rights
    )


def _as_runtime(fixture):
    """A session as the runtime role, which row-level security binds."""
    session = fixture.database(role=_APP_ROLE, password=_APP_PASSWORD).session(fixture.workspace_id)
    return session


def _stop(fixture, right_id) -> None:
    with _as_runtime(fixture) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
        withdraw_model_right(
            IngestRepository(connection, fixture.workspace_id),
            right_id=right_id,
            withdrawn_by=ACCOUNT,
        )


def _search_tombstones(fixture):
    return fixture.rows(
        "select tombstone_id, capture_id, requested_by from tombstone "
        "where scope::text = 'caption_search' order by requested_at"
    )


def _entries(fixture):
    return [row["embedding_id"] for row in fixture.rows("select embedding_id from embedding")]


@pytest.fixture
def indexed(purged, client, monkeypatch):
    from exulanica.db.migrate import provision_workspace

    provision_workspace(purged.repository.connection, purged.workspace_id)
    return _index(purged, client, monkeypatch)


# -- the database -----------------------------------------------------------------------------


def test_stopping_the_search_right_queues_the_purge_and_the_purger_deletes_the_entries(indexed):
    fixture = indexed.fixture
    for right in indexed.rights[Role.EMBEDDING]:
        _stop(fixture, right.right_id)

    tombstones = _search_tombstones(fixture)
    assert tombstones, "stopping the search right wrote no tombstone"
    assert {row["capture_id"] for row in tombstones} == {indexed.capture_id}
    assert all(row["requested_by"] == ACCOUNT for row in tombstones)
    queued = fixture.rows(
        "select target_ref from purge_job where target_kind='embedding' and tombstone_id=any(%s)",
        [row["tombstone_id"] for row in tombstones],
    )
    assert {row["target_ref"] for row in queued} == {str(indexed.embedding_id)}

    outcome = fixture.worker().drain()
    assert outcome.role == _PURGE_ROLE and outcome.failed == 0, outcome.errors
    assert outcome.destroyed == 1
    assert _entries(fixture) == []
    assert all(
        queue.is_purge_complete(fixture.repository.connection, row["tombstone_id"])
        for row in tombstones
    )


def test_a_stopped_entry_is_not_ranked_before_its_purge_runs(indexed, client):
    """The stop takes effect at search time at once: the vector path skips a targeted entry."""
    fixture = indexed.fixture
    model = client.manifest[Role.EMBEDDING].primary.model_id
    # The stored entry's own vector, asked with words its description does not hold, so only the
    # vector path can match it.
    query = QueryEmbedding(vector(), model, client.manifest.pipeline_version)
    assert run(fixture.repository, UNDESCRIBED, embedding=query).total_matched == 1
    assert has_embeddings(fixture.repository.connection, fixture.workspace_id, client)

    for right in indexed.rights[Role.EMBEDDING]:
        _stop(fixture, right.right_id)

    assert _entries(fixture) == [indexed.embedding_id], "the purge must not have run yet"
    assert run(fixture.repository, UNDESCRIBED, embedding=query).total_matched == 0
    assert not has_embeddings(fixture.repository.connection, fixture.workspace_id, client)


def test_the_photograph_survives_and_is_still_found_by_the_words_of_its_description(indexed):
    fixture = indexed.fixture
    assert run(fixture.repository, DESCRIBED).total_matched == 1
    for right in indexed.rights[Role.EMBEDDING]:
        _stop(fixture, right.right_id)
    fixture.worker().drain()
    assert _entries(fixture) == []

    capture = fixture.rows(
        "select deleted_at, tombstone_blocks_capture(workspace_id, capture_id) as blocked "
        "from capture where capture_id=%s",
        indexed.capture_id,
    )[0]
    assert capture == {"deleted_at": None, "blocked": False}
    # The description belongs to the description right, which the stop does not touch.
    vision = fixture.rows(
        "select personal_model_right_allows(workspace_id,right_id,capture_id,model_provider,"
        "model_role,model_id,model_revision,destination,clock_timestamp()) as current "
        "from personal_model_right where model_role=%s",
        Role.VISION.value,
    )
    assert vision and all(row["current"] for row in vision)
    assert run(fixture.repository, DESCRIBED).total_matched == 1


def test_a_result_that_arrives_after_the_stop_is_refused_by_the_database(
    purged, client, monkeypatch
):
    """The call was allowed when it left and the right stopped while the model ran."""
    from exulanica.db.migrate import provision_workspace

    fixture = purged
    provision_workspace(fixture.repository.connection, fixture.workspace_id)
    repository = fixture.repository
    capture = fixture.rows("select capture_id from capture")[0]["capture_id"]
    authorization = _authorize(repository, capture)
    rights = _grant(
        repository, capture, authorization.authorization_id, Role.EMBEDDING, client.manifest
    )
    scripted = script(client, monkeypatch, vector())
    answer = client.embed

    def embed(texts, **kwargs):
        # Another connection, as the person's own request would be, while this call is out.
        stopping = threading.Thread(target=lambda: [_stop(fixture, r.right_id) for r in rights])
        stopping.start()
        stopping.join()
        return answer(texts, **kwargs)

    monkeypatch.setattr(client, "embed", embed)
    result = embed_capture(
        repository.connection, fixture.workspace_id, capture, client, before_send=unchecked
    )
    # The call was made and is counted; the database kept nothing of it.
    assert result is not None and len(scripted) == 1
    assert _entries(fixture) == []
    assert _search_tombstones(fixture)


def test_the_database_refuses_a_vector_for_a_stopped_photograph_from_the_runtime_role(indexed):
    fixture = indexed.fixture
    row = dict(fixture.rows("select * from embedding")[0])
    for right in indexed.rights[Role.EMBEDDING]:
        _stop(fixture, right.right_id)
    fixture.worker().drain()
    assert _entries(fixture) == []
    with (
        _as_runtime(fixture) as connection,
        pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="tombstoned"),
    ):
        connection.execute(
            "insert into embedding (workspace_id,embedding_id,family,ref_type,ref_id,"
            "model_ref,pipeline_version,dims,v) values (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                row["workspace_id"],
                uuid.uuid4(),
                row["family"],
                row["ref_type"],
                row["ref_id"],
                row["model_ref"],
                row["pipeline_version"],
                row["dims"],
                row["v"],
            ),
        )
    assert _entries(fixture) == []


def test_another_current_right_for_the_same_model_keeps_the_entries_until_it_stops(indexed, client):
    fixture = indexed.fixture
    repository = fixture.repository
    again = _grant(
        repository,
        indexed.capture_id,
        indexed.authorization_id,
        Role.EMBEDDING,
        client.manifest,
        minutes=90,
    )
    assert {r.right_id for r in again}.isdisjoint(
        {r.right_id for r in indexed.rights[Role.EMBEDDING]}
    )
    for right in indexed.rights[Role.EMBEDDING]:
        _stop(fixture, right.right_id)
    assert _search_tombstones(fixture), "the stop is recorded even when nothing is deleted"
    fixture.worker().drain()
    assert _entries(fixture) == [indexed.embedding_id]

    for right in again:
        _stop(fixture, right.right_id)
    fixture.worker().drain()
    assert _entries(fixture) == []


def test_stopping_the_description_right_deletes_no_search_entry(indexed):
    fixture = indexed.fixture
    for right in indexed.rights[Role.VISION]:
        _stop(fixture, right.right_id)
    assert _search_tombstones(fixture) == []
    fixture.worker().drain()
    assert _entries(fixture) == [indexed.embedding_id]


def test_a_right_granted_again_after_a_stop_indexes_the_photograph_again(
    indexed, client, monkeypatch
):
    """The stop refuses the old result, not the photograph for ever."""
    fixture = indexed.fixture
    for right in indexed.rights[Role.EMBEDDING]:
        _stop(fixture, right.right_id)
    fixture.worker().drain()
    assert _entries(fixture) == []

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


# -- the words, old and new -------------------------------------------------------------------


def _embedding_use():
    use = MODEL_RIGHT_USES.use(Role.EMBEDDING.value)
    assert use is not None
    return use


def test_the_words_a_person_agrees_to_say_the_entries_are_deleted():
    use = _embedding_use()
    for words in (use.kept, use.stop):
        assert "stay" not in words
        assert "deleted" in words


def test_a_right_granted_under_the_old_words_is_shown_as_such_and_its_stop_also_purges(
    purged, client, monkeypatch
):
    """The old words promised the entries would stay. Stopping deletes them anyway.

    More protective than those words: nothing the person agreed to is taken away by deleting
    what they asked to stop. The drawer says the right was granted against other words, and
    offers the stop in the words that say what happens now.
    """
    from exulanica.db.migrate import provision_workspace

    provision_workspace(purged.repository.connection, purged.workspace_id)
    use = _embedding_use()
    handoff = role_handoff(Role.EMBEDDING.value, client.manifest)
    old = dataclasses.replace(
        use,
        kept="search entries already made stay",
        stop=(
            "Stop sending this photo's descriptions to the search model? Nothing more is sent "
            "from now on. Search entries already made from it stay."
        ),
    )
    old_notice = MODEL_RIGHT_USES.notice(old, handoff)
    assert old_notice != MODEL_RIGHT_USES.notice(use, handoff)
    scope = {
        "purpose": PURPOSE,
        "model_rights": [
            {
                "role": Role.EMBEDDING.value,
                "valid_until": "2099-01-01T00:00:00Z",
                "notice": old_notice,
            }
        ],
    }
    indexed = _index(purged, client, monkeypatch, scope=scope)

    status = admission_status(purged.repository.connection, purged.workspace_id, ACCOUNT)
    [source] = [s for s in status["sources"] if s["capture_id"] == str(indexed.capture_id)]
    search = [r for r in source["model_rights"] if r["model"]["role"] == Role.EMBEDDING.value]
    assert search and all(r["notice_current"] is False for r in search)

    for right in indexed.rights[Role.EMBEDDING]:
        _stop(purged, right.right_id)
    purged.worker().drain()
    assert _entries(purged) == []


# -- the route --------------------------------------------------------------------------------


def test_the_withdraw_route_as_the_runtime_role_deletes_the_entries(indexed, tmp_path):
    fixture = indexed.fixture
    token = "companion-memory-search-stop-token-00000000"
    services = Services(
        database=fixture.database(role=_APP_ROLE, password=_APP_PASSWORD),
        readonly_database=fixture.database(role=_APP_ROLE, password=_APP_PASSWORD),
        store=fixture.store,
        tokens=load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        token: {
                            "workspace_id": str(fixture.workspace_id),
                            "actor": str(ACCOUNT),
                            "permissions": EVERY_PERMISSION,
                        }
                    }
                )
            }
        ),
        executor_shares_the_write_role=True,
        model_client=None,
        environment_admission_root=tmp_path / "admission",
    )
    with TestClient(create_app(services, verify=False)) as http:
        for right in indexed.rights[Role.EMBEDDING]:
            response = http.post(
                f"/personal-admission/model-rights/{right.right_id}/withdraw",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["state"] == "ended"
    assert _search_tombstones(fixture)
    assert fixture.worker().drain().destroyed == 1
    assert _entries(fixture) == []
