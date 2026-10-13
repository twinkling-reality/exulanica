"""Authored embedded maps retain their exact bytes under real admission, scope and withdrawal."""

from __future__ import annotations

import uuid

import pytest
from exulanica.things.pieces import Node, write_container
from exulanica.world.thing_store import ThingStore, ThingStoreRefused

import test_thing_store_routes as routes
from test_thing_material_maps import document, look_document, patch

served = routes.served
pytestmark = pytest.mark.postgres


def test_material_maps_are_admitted_retained_served_and_withdrawn_by_existing_contracts(served):
    client, _creature, database, workspace, services = served
    payload = write_container([Node("surface", (0, 0, 0), (patch(),))])
    raw = look_document(payload)
    actor = uuid.uuid4()

    def intake(look):
        assert look.document == raw
        assert look.document["origin"]["class"] == "authored"
        assert look.document["origin"]["licence"]["spdx"] == "CC0-1.0"

    with database.session(workspace) as connection:
        store = ThingStore(
            connection, workspace, services.content_stores.looks.for_workspace(workspace)
        )
        kept = store.admit_look(raw, payload, created_by=actor, admit=intake)
        assert kept.container_profile == "exulanica.static-glb/v1"
        row = connection.execute(
            "select admission, origin_class, container_sha256 from look_version "
            "where workspace_id=%s and sha256=%s",
            (workspace, kept.look.sha256),
        ).fetchone()
        assert row["admission"]["counts"]["images"] == 3
        assert row["admission"]["counts"]["texels"] == 12
        assert row["origin_class"] == "authored"
        with pytest.raises(ThingStoreRefused) as refused:
            store.admit_look(raw, payload + b"other bytes", created_by=actor, admit=intake)
        assert refused.value.code == "look_container_mismatch"
    path = f"/things/looks/{kept.look.sha256}/container"
    response = routes._get(client, path)
    assert response.status_code == 200 and response.content == payload
    assert document(response.content) == document(payload)
    assert routes._get(client, path, routes._STRANGER).status_code == 404
    assert (
        routes._get(client, path, **{"If-None-Match": response.headers["etag"]}).status_code == 304
    )
    with database.session(workspace) as connection:
        store = ThingStore(connection, workspace, None)
        assert store.look_by_digest(kept.look.sha256) is not None
        store.withdraw_look(
            kept.look.look, kept.look.version, "example retired", withdrawn_by=actor
        )
    assert (
        routes._get(client, path, **{"If-None-Match": response.headers["etag"]}).status_code == 404
    )
    with database.session(workspace) as connection:
        held = ThingStore(connection, workspace, None).look_by_digest(
            kept.look.sha256, include_withdrawn=True
        )
        assert held is not None and held.withdrawn
