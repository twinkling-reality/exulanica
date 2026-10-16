"""Every kind a workspace holds, listed over HTTP for build mode to offer (``GET /things/kinds``).

Against PostgreSQL as a deployment serves it, through the served application of
``tests/test_thing_store_routes.py``, whose workspace keeps one drafted creature; a second is kept
here. What is shown:

*   the list names each held kind newest first, with its reference, label, class, body plan, looks
    and body (a drafted creature's extent) as its own document states them, and when it was kept,
    never cached;
*   another workspace lists none of them, an erased creature leaves the list, and the route needs a
    session.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from exulanica.things.creatures import assemble_creature
from exulanica.world.thing_store import ThingStore

from test_creature_bodies import BY, _form, _recipe
from test_thing_store_routes import _OWNER, _STRANGER, _WRITER, _get
from test_thing_store_routes import served as imported_served  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="served")
def _served_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_served")


def _keep(database, workspace, services, name: str, label: str):  # type: ignore[no-untyped-def]
    creature = assemble_creature(_form(_recipe(name), label=label), by=BY)
    looks = services.content_stores.looks.for_workspace(workspace)
    with database.session(workspace) as connection:
        ThingStore(connection, workspace, looks).keep_creature(creature, created_by=workspace)
    return creature


def test_the_held_kinds_are_listed_newest_first_with_what_placing_one_needs(served):
    client, first, database, workspace, services = served
    second = _keep(database, workspace, services, "serpent", "listed serpent")
    listed = _get(client, "/things/kinds")
    assert listed.status_code == 200, listed.text
    assert listed.headers["cache-control"] == "private, no-store"
    body = listed.json()
    assert body["profile"] == "exulanica.held-thing-kinds/v1"
    assert [kind["sha256"] for kind in body["kinds"]] == [second.kind.sha256, first.kind.sha256]
    named = zip(body["kinds"], (second, first), ("serpent", "ten_legs"), strict=True)
    for item, creature, name in named:
        document = creature.kind.document
        assert item["kind"] == document["kind"]
        assert item["version"] == document["version"]
        assert item["label"] == document["label"]
        assert item["class"] == document["class"] == "being"
        assert item["body_plan"] == document["body"]["plan"]
        assert item["body"] == document["body"]
        assert item["body"]["extent_mm"] == _recipe(name)["extent_mm"]
        assert item["looks"] == document["looks"]
    made = [datetime.fromisoformat(kind["made_at"]) for kind in body["kinds"]]
    assert made[0] >= made[1]
    assert made[0].tzinfo is not None


def test_another_workspace_lists_none_an_erased_creature_leaves_and_a_session_is_needed(served):
    client, creature, _database, _workspace, _services = served
    assert [k["sha256"] for k in _get(client, "/things/kinds").json()["kinds"]] == [
        creature.kind.sha256
    ]
    stranger = _get(client, "/things/kinds", token=_STRANGER)
    assert stranger.status_code == 200, stranger.text
    assert stranger.json()["kinds"] == []
    assert _get(client, "/things/kinds", token=None).status_code == 401
    erased = client.delete(
        f"/things/kinds/{creature.kind.sha256}", headers={"Authorization": f"Bearer {_WRITER}"}
    )
    assert erased.status_code == 204, erased.text
    assert _get(client, "/things/kinds", token=_OWNER).json()["kinds"] == []
