"""A workspace's own looks and kinds over HTTP, as a deployment serves them.

The application connects as provisioned runtime roles, neither a superuser nor exempt from row-level
security. What is shown:

*   a held look's document is the canonical bytes its digest names, never cached; its container is
    the bytes the look names, tagged with the look's digest and revalidated before each use: a
    revalidation naming the tag is answered 304 with no body, needing no store; a held kind's
    document is served like a look's;
*   a withdrawn look, another workspace's look or kind, and an absent digest all answer 404
    ``unknown_reference`` alike, a revalidation of a withdrawn look's container as well, and so
    do container bytes the store no longer holds;
*   a server holding no looks answers 503 ``look_store_unavailable``;
*   a workspace's writer erases a drafted creature by its kind's digest (204), after which its
    kind, its look and its container all answer 404; a reader, a token granted ``world.write``
    without ``deletion.write``, a stranger, an invented digest and a second erasure all answer 404
    ``unknown_reference`` and erase nothing; an installation sealed for a restore answers 409
    ``restore_sealed``, erasing nothing;
*   only the person who drafted a creature or an owner of the workspace erases it: a guest who did
    not draft it is refused 403 ``kind_not_yours`` with nothing erased, and so is a bearer token for
    another actor, alone or sent beside an owner's browser session, since a token holds no
    membership; an owner who did not draft it erases it, and a guest who drafted it erases it;
*   each route needs a session.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid

import pytest
from exulanica.api.account_repository import AccountSession
from exulanica.api.app import create_app
from exulanica.api.authorisation import TokenNotAccepted, load_token_directory
from exulanica.api.services import Services
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.selection.validation import Session
from exulanica.store.configured import local_content_stores
from exulanica.store.local import LocalContentAddressedStore
from exulanica.things.creatures import assemble_creature
from exulanica.world.thing_store import ThingStore
from fastapi.testclient import TestClient

from conftest import scratch_role_database
from test_creature_bodies import BY, _form, _recipe

pytestmark = pytest.mark.postgres

_READER_ROLE = "exulanica_thing_store_reader"
_OWNER = "thing-store-owner-token-long-enough-to-be-accepted"
_STRANGER = "thing-store-stranger-token-long-enough-to-be-accepted"
_WRITER = "thing-store-writer-token-long-enough-to-be-accepted"
_WORLD_WRITER = "thing-store-world-writer-token-long-enough-to-be-accepted"
#: A token of the same workspace with every permission the erasure needs, for an actor who drafted
#: nothing there.
_OTHER_ACTOR = "thing-store-other-actor-token-long-enough-to-be-accepted"


@pytest.fixture
def served(repository, spine_schema, tmp_path):
    scratch = spine_schema[1]
    provision_runtime_role(repository.connection)
    provision_runtime_role(repository.connection, role=_READER_ROLE, read_only=True)
    repository.connection.commit()
    database = scratch_role_database(scratch, RUNTIME_ROLE)
    stores = local_content_stores(tmp_path / "data")
    creature = assemble_creature(_form(_recipe("ten_legs"), label="served ten legs"), by=BY)
    actor = uuid.uuid4()
    with database.session(repository.workspace_id) as connection:
        ThingStore(
            connection, repository.workspace_id, stores.looks.for_workspace(repository.workspace_id)
        ).keep_creature(creature, created_by=actor)
    grants = {
        token: {"workspace_id": str(workspace), "actor": str(holder), "permissions": permissions}
        for token, workspace, holder, permissions in (
            (_OWNER, repository.workspace_id, actor, ["world.read"]),
            (_STRANGER, uuid.uuid4(), actor, ["world.read", "world.write", "deletion.write"]),
            (
                _WRITER,
                repository.workspace_id,
                actor,
                ["world.read", "world.write", "deletion.write"],
            ),
            (_WORLD_WRITER, repository.workspace_id, actor, ["world.read", "world.write"]),
            (
                _OTHER_ACTOR,
                repository.workspace_id,
                uuid.uuid4(),
                ["world.read", "world.write", "deletion.write"],
            ),
        )
    }
    services = Services(
        database=database,
        readonly_database=scratch_role_database(scratch, _READER_ROLE),
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=False,
        model_client=None,
        content_stores=stores,
    )
    with TestClient(create_app(services, verify=False)) as client:
        yield client, creature, database, repository.workspace_id, services


def _get(client, path: str, token: str | None = _OWNER, **headers: str):
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.get(path, headers=headers)


def test_a_held_look_and_kind_are_served_by_their_digests(served):
    client, creature, _database, _workspace, _services = served
    look = _get(client, f"/things/looks/{creature.sketch.sha256}")
    assert look.status_code == 200
    # The canonical bytes the digest in the URL names, as the shipped library serves its own.
    assert hashlib.sha256(look.content).hexdigest() == creature.sketch.sha256
    assert look.json() == dict(creature.sketch.document)
    assert look.headers["cache-control"] == "private, no-store"
    path = f"/things/looks/{creature.sketch.sha256}/container"
    container = _get(client, path)
    assert container.status_code == 200
    assert container.content == creature.sketch_container
    assert container.headers["content-type"] == "model/gltf-binary"
    tag = f'"{creature.sketch.sha256}"'
    assert container.headers["etag"] == tag
    assert container.headers["cache-control"] == "private, no-cache"
    assert container.headers["x-content-type-options"] == "nosniff"
    # A revalidation naming the tag, strong or weak, is answered with no body.
    for named in (tag, f"W/{tag}", f'"{"0" * 64}", {tag}'):
        revalidated = _get(client, path, **{"If-None-Match": named})
        assert (revalidated.status_code, revalidated.content) == (304, b""), named
        assert revalidated.headers["etag"] == tag
        assert revalidated.headers["cache-control"] == "private, no-cache"
    assert _get(client, path, **{"If-None-Match": f'"{"0" * 64}"'}).status_code == 200
    kind = _get(client, f"/things/kinds/{creature.kind.sha256}")
    assert kind.status_code == 200
    assert hashlib.sha256(kind.content).hexdigest() == creature.kind.sha256


def test_what_the_workspace_does_not_hold_answers_404_alike(served):
    client, creature, database, workspace, _services = served
    sketch, kind = creature.sketch.sha256, creature.kind.sha256
    paths = [
        f"/things/looks/{sketch}",
        f"/things/looks/{sketch}/container",
        f"/things/kinds/{kind}",
    ]
    absent = {"code": "unknown_reference", "detail": "this workspace holds no such thing"}
    for path in paths:
        assert _get(client, path, _STRANGER).json() == absent, path
        assert _get(client, path, None).status_code == 401, path
    invented = "f" * 64
    for path in (f"/things/looks/{invented}", f"/things/kinds/{invented}"):
        response = _get(client, path)
        assert (response.status_code, response.json()) == (404, absent), path
    # Withdrawn: the look and its container are no longer served; its kind still is.
    with database.session(workspace) as connection:
        ThingStore(connection, workspace, None).withdraw_look(
            creature.sketch.look,
            creature.sketch.version,
            "no longer worn",
            withdrawn_by=uuid.uuid4(),
        )
    for path in paths[:2]:
        response = _get(client, path)
        assert (response.status_code, response.json()) == (404, absent), path
    # A browser holding the bytes asks again and is told they are gone.
    response = _get(client, paths[1], **{"If-None-Match": f'"{sketch}"'})
    assert (response.status_code, response.json()) == (404, absent)
    assert _get(client, paths[2]).status_code == 200


def test_a_server_without_the_container_says_so(served, tmp_path):
    client, creature, _database, _workspace, services = served
    path = f"/things/looks/{creature.sketch.sha256}/container"
    tag = f'"{creature.sketch.sha256}"'
    with TestClient(
        create_app(dataclasses.replace(services, content_stores=None), verify=False)
    ) as storeless:
        response = _get(storeless, path)
        assert response.status_code == 503
        assert response.json()["code"] == "look_store_unavailable"
        # A revalidation needs no store.
        assert _get(storeless, path, **{"If-None-Match": tag}).status_code == 304
    # Bytes the store no longer holds answer as an absent reference does.
    digest = hashlib.sha256(creature.sketch_container).hexdigest()
    held = [found for found in (tmp_path / "data").rglob(f"*{digest}*") if found.is_file()]
    assert len(held) == 1
    held[0].unlink()
    response = _get(client, path)
    assert (response.status_code, response.json()["code"]) == (404, "unknown_reference")


def test_a_writer_erases_a_drafted_creature_whole(served):
    client, creature, _database, _workspace, _services = served
    kind = f"/things/kinds/{creature.kind.sha256}"
    reads = [
        f"/things/looks/{creature.sketch.sha256}",
        f"/things/looks/{creature.sketch.sha256}/container",
        kind,
    ]
    absent = {"code": "unknown_reference", "detail": "this workspace holds no such thing"}

    def erase(path: str, token: str | None):
        headers = {} if token is None else {"Authorization": f"Bearer {token}"}
        return client.delete(path, headers=headers)

    # A reader of the workspace, and a token that may change its world but not delete a person's
    # content, are refused before any lookup, as for every id; a stranger and an invented digest
    # learn nothing. None of them erases anything.
    for token in (_OWNER, _WORLD_WRITER):
        response = erase(kind, token)
        assert (response.status_code, response.json()["code"]) == (404, "unknown_reference")
        assert response.json() != absent, token
    for path, token in ((kind, _STRANGER), (f"/things/kinds/{'f' * 64}", _WRITER)):
        response = erase(path, token)
        assert (response.status_code, response.json()) == (404, absent), (path, token)
    assert erase(kind, None).status_code == 401
    assert all(_get(client, path).status_code == 200 for path in reads)
    response = erase(kind, _WRITER)
    assert (response.status_code, response.content) == (204, b"")
    for path in reads:
        response = _get(client, path)
        assert (response.status_code, response.json()) == (404, absent), path
    response = erase(kind, _WRITER)
    assert (response.status_code, response.json()) == (404, absent)


def test_an_installation_sealed_for_a_restore_erases_nothing(served, repository):
    client, creature, _database, _workspace, _services = served
    kind = f"/things/kinds/{creature.kind.sha256}"
    owner = repository.connection
    owner.execute(
        "insert into restore_control (checkpoint_id, checkpoint_sha256, state) "
        "values (%s, %s, 'sealed')",
        (uuid.uuid4(), "a" * 64),
    )
    owner.commit()
    try:
        response = client.delete(kind, headers={"Authorization": f"Bearer {_WRITER}"})
        assert (response.status_code, response.json()["code"]) == (409, "restore_sealed")
    finally:
        owner.execute("delete from restore_control")
        owner.commit()
    assert _get(client, kind).status_code == 200


#: The account a stub browser session belongs to, named by this header in a test's request.
_ACCOUNT_HEADER = "x-test-account"


class _Accounts:
    """The account runtime's one method the permission floor and the erase route call: the
    browser session, in its membership role, of the account a test names in a header."""

    def __init__(self, sessions: dict[str, tuple[Session, str]]) -> None:
        self.sessions = sessions

    def browser_session(self, request) -> AccountSession:
        found = self.sessions.get(request.headers.get(_ACCOUNT_HEADER, ""))
        if found is None:
            raise TokenNotAccepted("browser session was not accepted")
        session, role = found
        return AccountSession(uuid.uuid4(), session, "c" * 43, None, role)  # type: ignore[arg-type]


def _drafter_of(database, workspace, creature) -> uuid.UUID:
    with database.session(workspace) as connection:
        return connection.execute(
            "select created_by from thing_kind_version where workspace_id=%s and sha256=%s",
            (workspace, creature.kind.sha256),
        ).fetchone()["created_by"]


def test_only_the_drafter_or_an_owner_erases_a_creature(served):
    client, creature, _database, workspace, services = served
    kind = f"/things/kinds/{creature.kind.sha256}"
    accounts = _Accounts(
        {
            "guest": (Session(workspace_id=workspace, actor=uuid.uuid4()), "guest"),
            "owner": (Session(workspace_id=workspace, actor=uuid.uuid4()), "owner"),
        }
    )
    with TestClient(
        create_app(dataclasses.replace(services, accounts=accounts), verify=False)
    ) as browser:
        # A guest who did not draft it is refused by name, and nothing is erased.
        refused = browser.delete(kind, headers={_ACCOUNT_HEADER: "guest"})
        assert (refused.status_code, refused.json()["code"]) == (403, "kind_not_yours")
        assert _get(client, kind).status_code == 200
        # A bearer token holds no membership: one for another actor is refused, and so is the same
        # token sent with an owner's browser session beside it.
        for headers in (
            {"Authorization": f"Bearer {_OTHER_ACTOR}"},
            {"Authorization": f"Bearer {_OTHER_ACTOR}", _ACCOUNT_HEADER: "owner"},
        ):
            refused = browser.delete(kind, headers=headers)
            assert (refused.status_code, refused.json()["code"]) == (403, "kind_not_yours"), headers
        assert _get(client, kind).status_code == 200
        # An owner who did not draft it erases it.
        erased = browser.delete(kind, headers={_ACCOUNT_HEADER: "owner"})
        assert (erased.status_code, erased.content) == (204, b"")
    assert _get(client, kind).status_code == 404


def test_a_guest_who_drafted_a_creature_erases_it(served):
    client, creature, database, workspace, services = served
    kind = f"/things/kinds/{creature.kind.sha256}"
    drafter = _drafter_of(database, workspace, creature)
    accounts = _Accounts({"drafter": (Session(workspace_id=workspace, actor=drafter), "guest")})
    with TestClient(
        create_app(dataclasses.replace(services, accounts=accounts), verify=False)
    ) as browser:
        erased = browser.delete(kind, headers={_ACCOUNT_HEADER: "drafter"})
        assert (erased.status_code, erased.content) == (204, b"")
    assert _get(client, kind).status_code == 404
