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


@pytest.mark.parametrize("route", ["town", "place", "refused"])
def test_whole_world_cold_outcome_and_calls_do_not_restore_erased_identity_words(drafts, route):
    factory, transport = drafts
    # The place tool's drafter takes no answer from a model nobody admitted, so the town tool
    # makes the words instead; where the town's drafter then fails too, the draft is refused.
    town = [_json(_town_form(storey_band_high=5)), *_plain()]
    responses = [_tool("town", "a quiet town"), *town]
    if route != "town":
        responses = [_tool("place", "a quiet town"), _brief(_farm())]
        responses += town if route == "place" else []
    transport.responses.extend(echoed(response) for response in responses)
    if route == "refused":
        transport.responses.extend([HttpResponse(status_code=500, text="the provider failed")] * 4)
    # A world made from the person's words keeps them with the world (0222); nothing else may
    # carry them, and a refused draft keeps nothing.
    kept = "" if route == "refused" else "a quiet town " + ECHO
    with factory() as client:
        started = _start(client, "a quiet town " + ECHO)
        assert started.status_code == 202, started.text
        ident = started.json()["draft_id"]
        ended = _ended(client, ident)
        assert ended["state"] == ("refused" if route == "refused" else "ready"), ended
        assert ended["description"] == kept and ended["model_name"] is None
        assert ECHO not in json.dumps({**ended, "description": ""})
        if route != "town":
            assert ended["tool"] == {"key": "town", "chosen_by": "fallback"}
        calls = ended["execution"]["calls"]
        echoed_calls = {"town": 4, "place": 5, "refused": 2}[route]
        if route != "refused":
            assert len(calls) == echoed_calls
        assert all(call["served_model"] is None for call in calls)
        for call in calls[:echoed_calls]:
            assert call["served_model_unavailable"] == "reported_model_not_admitted"
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
            if route != "town":
                assert (
                    connection.execute("select count(*) as n from world_kind_version").fetchone()[
                        "n"
                    ]
                    == 0
                )
            if route == "refused":
                assert ended["entry"] is None
    # A new metadata-only API cannot get this answer from the original process holder.
    with factory(model=False) as reader:
        cold = _read(reader, ident)
        assert cold.status_code == 200, cold.text
        assert cold.json()["state"] == ended["state"] and cold.json()["description"] == kept
        assert ECHO not in json.dumps({**cold.json(), "description": ""})
        assert cold.json()["execution"]["calls"] == ended["execution"]["calls"]
