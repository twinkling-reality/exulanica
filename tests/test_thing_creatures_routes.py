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
    account it is charged to: the route's dearest model at the drafter's request envelope of
    input and its answer bound, for a form and one repair each sent as often as the client may
    send it; a draft states no spend where no durable spending authority records this process's
    calls;
*   before anyone types, the offer says spending is paused (the durable authority held closed for
    the drafter's provider) or spent (refused otherwise, or less left than one attempt), each by
    its own code;
*   a made look of a kept creature is asked once, answered 202 and queued, and read by any member
    of the workspace; a kind the workspace does not keep, asked anywhere, is absent, and so is the
    route to a caller without world.write and model.invoke;
*   the offer says whether web notes may be asked for with a draft, by the references read's code
    or that this person may not, with the planner's limit and the most they add where offered; a
    draft asked with notes says what its own requester's notes request searched and spent, and
    nothing of another person's.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.request_envelopes import request_bytes_at_most
from exulanica.models.spending import SpendingRefused
from exulanica.models.usage import usd_string
from exulanica.spending.status import SpendingRefusals
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
_NOTES = "creature-notes-token-long-enough-to-be-accepted"


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
        # One who may also ask for web notes.
        _NOTES: (workspace_id, [*every, "references.request"]),
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
    # The request's own figures for the page's spend: its one search and its model call's dollars.
    assert asked.json()["references"] == {
        "reference_id": str(reference_id),
        "state": "pending",
        "searches": 1,
        "spent_usd": "0.00020000",
    }
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
    # The most one draft may be charged: no request sends more than the drafter's request
    # envelope of input and the answer bound, priced at the route's dearest model, for a form and
    # one repair, each sent once to the primary and once to the fallback a withdrawn primary is
    # answered by.
    answer = binding.max_tokens.value
    envelope = request_bytes_at_most(Role.CREATURE_DRAFTER)
    dearest = max(
        spec.cost_usd(
            prompt_tokens=min(envelope, spec.context_window_tokens), completion_tokens=answer
        )
        for spec in binding.chain
    )
    assert len(binding.chain) == 2
    assert offer["price"] == {
        "usd_at_most": usd_string(dearest * 2 * 2),
        "provider": binding.provider,
        "provider_description": load_manifest().provider(binding.provider).description,
        "basis": {
            "kind": "request_envelope_ceiling",
            "attempts_at_most": 2,
            "wire_attempts_per_attempt_at_most": 2,
            "input_tokens_at_most": max(
                min(envelope, spec.context_window_tokens) for spec in binding.chain
            ),
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
        "spending_suspended",
        "stranded",
    ]
    assert offer["codes"]["cancelled"] == ["workspace_deleted"]
    elsewhere = _get(client, "/things/creatures/offered", _ELSEWHERE).json()
    assert (elsewhere["offered"], elsewhere["code"]) == (False, "creatures_not_run_here")


def test_the_offer_says_spending_paused_or_spent_before_anyone_types(served, monkeypatch):
    client, *_ = served
    provider = load_manifest()[Role.CREATURE_DRAFTER].primary.provider
    read: dict[str, SpendingRefusals] = {}
    # The durable authority's answer for the drafter's provider, as the workspace's spending reads.
    monkeypatch.setattr(Services, "spending_refusals", lambda _self, _connection, _ws: read["now"])

    def offer(refusals: SpendingRefusals) -> tuple[bool, str | None]:
        read["now"] = refusals
        answered = _get(client, "/things/creatures/offered").json()
        return answered["offered"], answered["code"]

    # Enough left, nothing refused: offered (the control).
    assert offer(SpendingRefusals({provider: None}, {provider: Decimal("5")})) == (True, None)
    # Held closed until an operator acts: paused, told apart from spent by its code.
    paused = SpendingRefusals({provider: SpendingRefused("spending_suspended")})
    assert offer(paused) == (False, "spending_suspended")
    spent = SpendingRefused("spending_limit_reached", scope="workspace", detail="usd")
    assert offer(SpendingRefusals({provider: spent})) == (False, "budget_exceeded")
    # Less left than one attempt's floor admits no attempt: spent, said before typing.
    short = SpendingRefusals({provider: None}, {provider: Decimal("0.000001")})
    assert offer(short) == (False, "budget_exceeded")


def test_an_offer_whose_spending_read_fails_stays_up(served, monkeypatch):
    client, *_ = served

    def broken(_self, _connection, _workspace):
        raise RuntimeError("the spending state is not readable here")

    # A failed read is no refusal: the offer answers as it did before spending was read, and a
    # draft is still refused by admission at its attempt.
    monkeypatch.setattr(Services, "spending_refusals", broken)
    answered = _get(client, "/things/creatures/offered")
    assert answered.status_code == 200
    assert (answered.json()["offered"], answered.json()["code"]) == (True, None)


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


def test_the_offer_says_whether_web_notes_may_be_asked_for_and_what_they_add(served, monkeypatch):
    from exulanica.api.routes import references

    client, *_ = served
    # The owner may draft but not ask for web notes: said by name, with the planner's limit.
    assert _get(client, "/things/creatures/offered").json()["notes"] == {
        "offered": False,
        "code": "references_not_permitted",
        "searches_at_most": 3,
        "maximum_usd": None,
    }
    # One who may is told why not here by the references read's own code, and no figure.
    notes = _get(client, "/things/creatures/offered", _NOTES).json()["notes"]
    capability = _get(client, "/worlds/references", _NOTES).json()["capabilities"][0]
    assert (notes["offered"], notes["code"], notes["maximum_usd"]) == (
        False,
        capability["code"],
        None,
    )
    # Offered: the most their model calls add, as a dollar string the page reads.
    monkeypatch.setattr(references, "unavailable_because", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(references, "notes_maximum_usd", lambda _client: "0.0213456")
    notes = _get(client, "/things/creatures/offered", _NOTES).json()["notes"]
    assert notes == {
        "offered": True,
        "code": None,
        "searches_at_most": 3,
        "maximum_usd": "0.02134560",
    }
    # No current rate prices them: not offered, by name.
    monkeypatch.setattr(references, "notes_maximum_usd", lambda _client: None)
    notes = _get(client, "/things/creatures/offered", _NOTES).json()["notes"]
    assert (notes["offered"], notes["code"]) == (False, "references_price_unavailable")
    # Where no draft is offered, nothing of notes either.
    assert _get(client, "/things/creatures/offered", _ELSEWHERE).json()["notes"] is None


def test_a_draft_says_nothing_of_another_person_s_notes_request(served):
    from reference_fixtures import finished_reference

    client, database, workspace_id, _stores = served
    other = client.app.state.services.tokens.session_for(_OTHER).actor
    with database.session(workspace_id) as connection:
        reference_id = finished_reference(connection, workspace_id, actor=other, purpose="things")
    asked = client.post(
        "/things/creatures",
        json={"words": "a gentle horse", "reference_id": str(reference_id)},
        headers={"Authorization": f"Bearer {_OWNER}"},
    )
    assert asked.status_code == 202
    assert (asked.json()["references"]["searches"], asked.json()["references"]["spent_usd"]) == (
        None,
        None,
    )


def test_a_workspace_the_list_does_not_name_asks_only_where_creatures_are_for_everyone(served):
    """On a public installation the list names nobody. Off by default, a workspace is refused
    before anything is queued and its offer says why; offered to everyone, it asks as a listed one
    does, and a caller without the model grant is still refused."""
    import dataclasses
    from types import SimpleNamespace

    client, database, workspace_id, _stores = served
    public = SimpleNamespace(profile=SimpleNamespace(id="public"))
    listed = client.app.state.services
    client.app.state.services = dataclasses.replace(
        listed, creature_workspaces=(), installation=public
    )
    refused = _ask(client, "a gentle horse that walks the hills")
    assert (refused.status_code, refused.json()["code"]) == (409, "creatures_not_run_here")
    assert _get(client, "/things/creatures/offered").json()["code"] == "creatures_not_run_here"
    with database.session(workspace_id) as connection:
        assert connection.execute("select count(*) as n from creature_draft").fetchone()["n"] == 0
    client.app.state.services = dataclasses.replace(
        client.app.state.services, notes_and_creatures_for_everyone=True
    )
    offer = _get(client, "/things/creatures/offered").json()
    assert (offer["offered"], offer["code"]) == (True, None)
    asked = _ask(client, "a gentle horse that walks the hills")
    assert asked.status_code == 202, asked.text
    assert _ask(client, "a gentle horse", _READER).status_code == 403
    assert client.post("/things/creatures", json={"words": "a horse"}).status_code == 401
