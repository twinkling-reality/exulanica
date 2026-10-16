"""Unknown provider identities cannot survive terminal draft input erasure."""

import json
import uuid

import pytest
from exulanica.models.transport import HttpResponse
from exulanica.selection import creature_drafts
from exulanica.world.thing_store import ThingStore

from creature_support import form_of
from test_creature_drafts_postgres import _kept_of, _queue, _transport, _worker
from test_creature_drafts_postgres import served as served
from test_world_making_postgres import (  # noqa: F401
    _brief,
    _drafts_alias,
    _ended,
    _farm,
    _json,
    _named_alias,
    _plain,
    _read,
    _start,
    _tool,
    _town_form,
    _workspace,
)
from test_world_making_postgres import (
    bench as bench,
)
from test_world_making_postgres import (
    imported_drafts as imported_drafts,
)
from test_world_making_postgres import (
    saved_named as saved_named,
)

pytestmark = pytest.mark.postgres
ECHO = "PRIVATE_WORDS_SENTINEL terminal original words"


def echoed(response):
    body = json.loads(response.text)
    body["model"] = ECHO
    return HttpResponse(response.status_code, json.dumps(body), response.headers)


def test_creature_identity_refuses_before_keep_and_cold_read_contains_no_words(served):
    database, workspace, stores = served
    actor = uuid.uuid4()
    with database.session(workspace) as connection:
        queued = _queue(connection, workspace, actor, words=ECHO)
    transport = _transport(form_of("horse", label="echoed creature"))
    transport.by_model = {key: echoed(response) for key, response in transport.by_model.items()}
    worker = _worker(database, workspace, stores, transport)
    assert worker.run_once(workspace) == "failed"
    assert transport.call_count == 1
    with database.session(workspace) as connection:
        ended = creature_drafts.read_draft(
            connection, workspace, queued.draft_id, owner_actor_id=actor
        )
        assert ended.status == "failed" and ended.model_id is None and ended.kind_sha256 is None
        assert ECHO not in _kept_of(connection, queued)
        assert ThingStore(connection, workspace, None).kind("echoed_creature", 1) is None


@pytest.mark.parametrize("tool", ["town", "place"])
def test_whole_world_cold_outcome_and_calls_do_not_restore_erased_identity_words(drafts, tool):
    factory, transport = drafts
    responses = [
        _tool(tool, "a quiet town"),
        _json(_town_form(storey_band_high=5)) if tool == "town" else _brief(_farm()),
    ]
    if tool == "town":
        responses += _plain()
    transport.responses.extend(echoed(response) for response in responses)
    # A world made from the person's words keeps them with the world (0222); nothing else may
    # carry them, and a refused draft keeps nothing.
    kept = "a quiet town " + ECHO if tool == "town" else ""
    with factory() as client:
        started = _start(client, "a quiet town " + ECHO)
        assert started.status_code == 202, started.text
        ident = started.json()["draft_id"]
        ended = _ended(client, ident)
        assert ended["state"] == ("ready" if tool == "town" else "refused"), ended
        assert ended["description"] == kept and ended["model_name"] is None
        assert ECHO not in json.dumps({**ended, "description": ""})
        assert len(ended["execution"]["calls"]) == (4 if tool == "town" else 2)
        for call in ended["execution"]["calls"]:
            assert (
                call["served_model"] is None
                and call["served_model_unavailable"] == "reported_model_not_admitted"
            )
        with client.app.state.services.database.session(_workspace()) as connection:
            assert (
                connection.execute(
                    "select 1 from world_draft_input where draft_id=%s", (uuid.UUID(ident),)
                ).fetchone()
                is None
            )
            outcome = connection.execute(
                "select document from world_draft_outcome where draft_id=%s", (uuid.UUID(ident),)
            ).fetchone()["document"]
            assert outcome["model_id"] is None and ECHO not in json.dumps(outcome)
            if tool == "place":
                assert (
                    connection.execute("select count(*) as n from world_kind_version").fetchone()[
                        "n"
                    ]
                    == 0
                )
                assert ended["entry"] is None
    # A new metadata-only API cannot get this answer from the original process holder.
    with factory(model=False) as reader:
        cold = _read(reader, ident)
        assert cold.status_code == 200, cold.text
        assert cold.json()["state"] == ended["state"] and cold.json()["description"] == kept
        assert ECHO not in json.dumps({**cold.json(), "description": ""})
        assert cold.json()["execution"]["calls"] == ended["execution"]["calls"]
