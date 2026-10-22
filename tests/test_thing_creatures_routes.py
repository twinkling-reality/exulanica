"""A creature from a person's words over HTTP, as a deployment serves it.

The application connects as provisioned runtime roles, with the drafter's replies scripted and the
worker played by the test, so each step is seen. What is shown:

*   asking answers 202 with a queued draft at once; the requester reads it as it goes, and once kept
    the draft names its kind and its sketch, which the workspace's look routes then serve, and its
    creature's made look, asked as it was kept and read as the look route reads it; a draft
    conditioned on a reference asks no look; once the creature is erased, the draft reads as erased
    and names nothing of it;
*   a refused draft answers its code, the form's field and the code's fixed sentence;
*   another requester, another workspace and an absent draft all read as absent;
*   words that are not one plain line are refused before anything is queued; a workspace this
    installation does not list is told so; one requester has one draft open at a time;
*   asking needs world.write and model.invoke;
*   the offer names the model a draft asks first and the most a draft may be charged, with the
    account it is charged to: the route's dearest model at a whole context window of input and its
    answer bound, for a form and one repair each sent as often as the client may send it; a draft
    states no spend where no durable spending authority records this process's calls;
*   a made look of a kept creature is asked once, answered 202 and queued, and read by any member
    of the workspace; a kind the workspace does not keep, asked anywhere, is absent, and so is the
    route to a caller without world.write and model.invoke.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.usage import usd_string
from exulanica.store.configured import local_content_stores
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient

from conftest import scratch_role_database
from creature_support import form_of
from model_fakes import RecordingPolicy
from test_creature_drafts_postgres import _transport, _worker

pytestmark = pytest.mark.postgres

_READER_ROLE = "exulanica_creature_reader"
_OWNER = "creature-owner-token-long-enough-to-be-accepted"
_OTHER = "creature-other-token-long-enough-to-be-accepted"
_ELSEWHERE = "creature-elsewhere-token-long-enough-to-be-accepted"
_READER = "creature-reader-token-long-enough-to-be-accepted"


@pytest.fixture
def served(repository, spine_schema, tmp_path, monkeypatch):
    scratch = spine_schema[1]
    provision_runtime_role(repository.connection)
    provision_runtime_role(repository.connection, role=_READER_ROLE, read_only=True)
    repository.connection.commit()
    workspace_id = repository.workspace_id
    every = ["world.read", "world.write", "model.invoke"]
    grants = {
        # The requester; erasing a creature it drafted also needs deletion.write.
        _OWNER: (workspace_id, [*every, "deletion.write"]),
        _OTHER: (workspace_id, every),
        _ELSEWHERE: (uuid.uuid4(), every),
        _READER: (workspace_id, ["world.read"]),
    }
    database = scratch_role_database(scratch, RUNTIME_ROLE)
    stores = local_content_stores(tmp_path / "data")
    services = Services(
        database=database,
        readonly_database=scratch_role_database(scratch, _READER_ROLE),
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        token: {
                            "workspace_id": str(workspace),
                            "actor": str(uuid.uuid4()),
                            "permissions": permissions,
                        }
                        for token, (workspace, permissions) in grants.items()
                    }
                )
            }
        ),
        executor_shares_the_write_role=False,
        model_client=ModelClient(
            api_key="test-key-not-real",
            manifest=load_manifest(),
            transport=_transport(),
            budget=BudgetGuard(),
            policy=RecordingPolicy(),
        ),
        content_stores=stores,
        runs_creature_worker=True,
        creature_workspaces=(workspace_id,),
    )
    # The test plays the worker itself, step by step; the application starts none.
    monkeypatch.setattr(Services, "build_creature_worker", lambda _self: None)
    with TestClient(create_app(services, verify=False)) as client:
        yield client, database, workspace_id, stores


def _ask(client, words: str, token: str = _OWNER):
    return client.post(
        "/things/creatures", json={"words": words}, headers={"Authorization": f"Bearer {token}"}
    )


def _get(client, path: str, token: str = _OWNER):
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


def test_asking_queues_a_draft_that_is_kept_and_served(served):
    client, database, workspace_id, stores = served
    asked = _ask(client, "a gentle horse that walks the hills")
    assert asked.status_code == 202
    draft = asked.json()
    assert "references" not in draft and "look_job" not in draft
    # No durable authority admits this process's calls, so no spend is recorded to read.
    assert draft["spend"] is None
    assert (draft["profile"], draft["status"], draft["kind"]) == (
        "exulanica.creature-draft/v1",
        "queued",
        None,
    )
    path = f"/things/creatures/drafts/{draft['draft_id']}"
    assert _get(client, path).json()["status"] == "queued"
    worker = _worker(
        database, workspace_id, stores, _transport(form_of("horse", label="hill walker"))
    )
    assert worker.run_once(workspace_id) == "kept"
    kept = _get(client, path).json()
    assert "references" not in kept
    assert kept["status"] == "kept" and kept["label"] == "hill walker"
    assert kept["spend"] is None
    assert kept["kind"]["kind"] == "hill_walker" and kept["model"]["model_id"]
    # The sketch the draft names is served by the workspace's own look routes.
    look = _get(client, f"/things/looks/{kept['look']['sha256']}")
    assert look.status_code == 200 and look.json()["look"] == kept["look"]["look"]
    assert _get(client, f"/things/kinds/{kept['kind']['sha256']}").status_code == 200
    # Kept, the creature's made look was asked for the requester: the draft names the job as the
    # look route answers it, queued, spending nothing until an operator's run makes it.
    asked_look = kept["look_job"]
    assert (asked_look["profile"], asked_look["status"], asked_look["kind_sha256"]) == (
        "exulanica.creature-look/v1",
        "queued",
        kept["kind"]["sha256"],
    )
    assert _get(client, f"/things/creatures/looks/{asked_look['look_id']}").json() == asked_look


def test_reference_identity_is_opt_in_and_only_the_requester_reads_its_use(served):
    from reference_fixtures import finished_reference

    client, database, workspace_id, stores = served
    actor = client.app.state.services.tokens.session_for(_OWNER).actor
    with database.session(workspace_id) as connection:
        reference_id = finished_reference(
            connection,
            workspace_id,
            actor=actor,
            purpose="things",
        )
    asked = client.post(
        "/things/creatures",
        json={"words": "a gentle horse", "reference_id": str(reference_id)},
        headers={"Authorization": f"Bearer {_OWNER}"},
    )
    assert asked.status_code == 202
    assert asked.json()["references"] == {"reference_id": str(reference_id), "state": "pending"}
    path = f"/things/creatures/drafts/{asked.json()['draft_id']}"
    assert _get(client, path, _OTHER).status_code == 404
    assert _get(client, path, _ELSEWHERE).status_code == 404
    assert (
        _worker(
            database,
            workspace_id,
            stores,
            _transport(
                form_of("horse", label="hill walker"),
            ),
        ).run_once(workspace_id)
        == "kept"
    )
    kept = _get(client, path).json()
    used = kept["references"]
    assert used["state"] == "used" and used["reference_id"] == str(reference_id)
    # Words conditioned on a reference may carry what notes read from a picture: no look is asked.
    assert kept["status"] == "kept" and "look_job" not in kept
    with database.session(workspace_id) as connection:
        assert connection.execute("select count(*) as n from creature_look").fetchone()["n"] == 0
    assert used["basis"] == ["web_description"] and used["notes"] == 3


def test_a_kept_draft_reads_as_erased_once_its_creature_is_erased(served):
    client, database, workspace_id, stores = served
    path = f"/things/creatures/drafts/{_ask(client, 'a gentle horse').json()['draft_id']}"
    worker = _worker(
        database, workspace_id, stores, _transport(form_of("horse", label="hill walker"))
    )
    assert worker.run_once(workspace_id) == "kept"
    kind = _get(client, path).json()["kind"]
    erased = client.delete(
        f"/things/kinds/{kind['sha256']}", headers={"Authorization": f"Bearer {_OWNER}"}
    )
    assert erased.status_code == 204
    after = _get(client, path).json()
    assert (after["status"], after["kind"], after["look"], after["label"]) == (
        "erased",
        None,
        None,
        None,
    )
    # Its look job went with it.
    assert "look_job" not in after


def test_a_kept_draft_reads_as_erased_once_nothing_holds_its_kind(served, repository):
    # A workspace tombstone's purge deletes the kind and writes no erasure: the draft still reads
    # erased, because nothing holds its digest.
    client, database, workspace_id, stores = served
    path = f"/things/creatures/drafts/{_ask(client, 'a gentle horse').json()['draft_id']}"
    worker = _worker(
        database, workspace_id, stores, _transport(form_of("horse", label="hill walker"))
    )
    assert worker.run_once(workspace_id) == "kept"
    kind = _get(client, path).json()["kind"]
    connection = repository.connection
    connection.commit()
    # Only the purge's definer deletes from the store (0172's append-only trigger).
    with connection.transaction():
        connection.execute("set local role exulanica_definer")
        deleted = connection.execute(
            "delete from thing_kind_version where workspace_id=%s and sha256=%s",
            (workspace_id, kind["sha256"]),
        )
        assert deleted.rowcount == 1
    after = _get(client, path).json()
    assert (after["status"], after["kind"], after["look"], after["label"]) == (
        "erased",
        None,
        None,
        None,
    )


def test_a_refused_draft_answers_its_code_field_and_fixed_sentence(served):
    client, database, workspace_id, stores = served
    path = f"/things/creatures/drafts/{_ask(client, 'a red dragon').json()['draft_id']}"
    form = form_of("dragon", label="red wyrm", moves=["walking", "flight"])
    assert _worker(database, workspace_id, stores, _transport(form)).run_once(workspace_id) == (
        "refused"
    )
    refused = _get(client, path).json()
    assert (refused["status"], refused["kind"], refused["label"]) == ("refused", None, None)
    assert refused["refusal"] == {
        "code": "creature_movement_unbuilt",
        "field": "moves_flight",
        "detail": "This world has no flying creatures yet.",
    }


def test_only_its_requester_reads_a_draft(served):
    client, *_ = served
    draft_id = _ask(client, "a gentle horse that walks the hills").json()["draft_id"]
    path = f"/things/creatures/drafts/{draft_id}"
    absent = {
        "code": "unknown_reference",
        "detail": "nothing at this address is available to this credential",
    }
    for token in (_OTHER, _ELSEWHERE):
        response = _get(client, path, token)
        assert (response.status_code, response.json()) == (404, absent), token
    response = _get(client, f"/things/creatures/drafts/{uuid.uuid4()}")
    assert (response.status_code, response.json()) == (404, absent)


def test_asking_is_refused_by_name_before_anything_is_queued(served):
    client, *_ = served
    refused = _ask(client, "two lines\nof words")
    assert (refused.status_code, refused.json()["code"]) == (422, "words_refused")
    elsewhere = _ask(client, "a gentle horse", _ELSEWHERE)
    assert (elsewhere.status_code, elsewhere.json()["code"]) == (409, "creatures_not_run_here")
    assert _ask(client, "a gentle horse").status_code == 202
    again = _ask(client, "a second horse")
    assert (again.status_code, again.json()["code"]) == (429, "creature_limit_reached")
    assert _ask(client, "a gentle horse", _READER).status_code == 403


def test_the_offer_says_whether_a_workspace_may_ask_and_how_long_drafts_take(served):
    client, *_ = served
    offer = _get(client, "/things/creatures/offered").json()
    binding = load_manifest()[Role.CREATURE_DRAFTER]
    assert (offer["profile"], offer["offered"], offer["code"]) == (
        "exulanica.creature-offer/v1",
        True,
        None,
    )
    # The timing is the role's own measured basis (17,439 and 24,898 ms), rounded up to whole
    # seconds, and its timeout.
    assert offer["timing"] == {
        "record": binding.timeout_basis["record"],
        "call_p50_seconds": 18,
        "call_longest_seconds": 25,
        "call_timeout_seconds": 50,
    }
    # The model a draft asks first, by the name a person reads.
    primary = binding.primary.model_id
    assert offer["model"] == {"model_id": primary, "name": load_manifest().model_name(primary)}
    # The most one draft may be charged: no request sends more than a context window of input and
    # the answer bound, priced at the route's dearest model, for a form and one repair, each sent
    # once to the primary and once to the fallback a withdrawn primary is answered by.
    answer = binding.max_tokens.value
    dearest = max(
        spec.cost_usd(prompt_tokens=spec.context_window_tokens, completion_tokens=answer)
        for spec in binding.chain
    )
    assert len(binding.chain) == 2
    assert offer["price"] == {
        "usd_at_most": usd_string(dearest * 2 * 2),
        "provider": binding.provider,
        "provider_description": load_manifest().provider(binding.provider).description,
        "basis": {
            "kind": "full_context_ceiling",
            "attempts_at_most": 2,
            "wire_attempts_per_attempt_at_most": 2,
            "input_tokens_at_most": max(spec.context_window_tokens for spec in binding.chain),
            "answer_tokens_at_most": answer,
        },
    }
    assert "creature_movement_unbuilt" in offer["codes"]["refused"]
    assert "creature_not_drafted" in offer["codes"]["refused"]
    assert offer["codes"]["failed"] == [
        "drafter_unavailable",
        "expired",
        "not_served",
        "request_refused",
        "reference_withdrawn",
        "spending_refused",
        "stranded",
    ]
    assert offer["codes"]["cancelled"] == ["workspace_deleted"]
    elsewhere = _get(client, "/things/creatures/offered", _ELSEWHERE).json()
    assert (elsewhere["offered"], elsewhere["code"]) == (False, "creatures_not_run_here")


def test_a_requester_lists_their_own_drafts_newest_first(served):
    client, database, workspace_id, stores = served
    first = _ask(client, "a gentle horse that walks the hills").json()
    _worker(database, workspace_id, stores, _transport()).run_once(workspace_id)
    second = _ask(client, "a second horse").json()
    listed = _get(client, "/things/creatures/drafts").json()
    assert listed["profile"] == "exulanica.creature-drafts/v1"
    assert [draft["draft_id"] for draft in listed["drafts"]] == [
        second["draft_id"],
        first["draft_id"],
    ]
    ended = listed["drafts"][1]
    assert ended["status"] == "failed" and ended["started_at"] is not None
    assert _get(client, "/things/creatures/drafts", _OTHER).json()["drafts"] == []


def test_a_kept_creature_s_look_is_asked_once_and_read_by_any_member(served):
    from exulanica.world.thing_store import ThingStore

    from test_thing_store_postgres import _creature

    client, database, workspace_id, stores = served
    creature = _creature()
    with database.session(workspace_id) as connection:
        ThingStore(
            connection, workspace_id, stores.looks.for_workspace(workspace_id)
        ).keep_creature(creature, created_by=uuid.uuid4())
    path = f"/things/creatures/{creature.kind.sha256}/looks"
    headers = {"Authorization": f"Bearer {_OWNER}"}
    asked = client.post(path, headers=headers)
    assert asked.status_code == 202
    look = asked.json()
    assert (look["profile"], look["status"], look["kind_sha256"], look["look_sha256"]) == (
        "exulanica.creature-look/v1",
        "queued",
        creature.kind.sha256,
        None,
    )
    assert client.post(path, headers=headers).json()["look_id"] == look["look_id"]
    read = f"/things/creatures/looks/{look['look_id']}"
    assert _get(client, read).json() == look
    # Another member asking for the same creature is answered with the same job, and reads it.
    other = client.post(path, headers={"Authorization": f"Bearer {_OTHER}"})
    assert (other.status_code, other.json()["look_id"]) == (202, look["look_id"])
    assert _get(client, read, _OTHER).json() == look
    assert _get(client, read, _ELSEWHERE).status_code == 404
    assert _get(client, f"/things/creatures/looks/{uuid.uuid4()}").status_code == 404
    # A kind this workspace does not keep, and a kept one asked from another workspace, are absent.
    missing = client.post(f"/things/creatures/{'6' * 64}/looks", headers=headers)
    elsewhere = client.post(path, headers={"Authorization": f"Bearer {_ELSEWHERE}"})
    assert (missing.status_code, elsewhere.status_code) == (404, 404)
    assert missing.json() == elsewhere.json()
    # Asking needs world.write and model.invoke; a route that takes an id answers a caller without
    # them as it answers an absent id, and queues nothing.
    refused = client.post(path, headers={"Authorization": f"Bearer {_READER}"})
    assert refused.status_code == 404
    with database.session(workspace_id) as connection:
        assert connection.execute("select count(*) as n from creature_look").fetchone()["n"] == 1
