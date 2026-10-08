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
*   each route needs a session.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
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
        token: {"workspace_id": str(workspace), "actor": str(actor), "permissions": ["world.read"]}
        for token, workspace in ((_OWNER, repository.workspace_id), (_STRANGER, uuid.uuid4()))
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
