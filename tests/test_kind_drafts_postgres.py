"""``POST /worlds/kinds/drafts`` and ``GET /worlds/kinds/drafts/{draft_id}``: a kind of world
drafted from a person's words as a job the page polls. The route answers before the model does;
the job drafts on the kind drafter's role, checks the kind in the kind worker and keeps it in the
workspace with its provenance and never the words; a refused draft is refused by name; saved names
never reach the model. The model is a scripted transport answering with the hand-written test
farm's brief (tests/kind_briefs.py), a test fixture and not a kind a model made."""

from __future__ import annotations

import json
import threading
import time
import uuid
from decimal import Decimal
from typing import Any

import pytest
from exulanica.api import permissions
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection.kind_drafting import DRAFTER_ROLE
from exulanica.world.kinds import repository
from fastapi.testclient import TestClient

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from kind_briefs import brief_of, fixture_kind, held_to_form
from model_fakes import FakeTransport, chat_body
from test_companion_saved_names import named as saved_named  # noqa: F401
from tests_support_api import EVERY_PERMISSION, scratch_database

pytestmark = pytest.mark.postgres

TOKEN = "kind-drafts-owner-token-at-least-32-chars"
OTHER_TOKEN = "kind-drafts-other-token-at-least-32-chars"
#: Another person in the owner's workspace.
NEIGHBOUR_TOKEN = "kind-drafts-neighbour-token-at-least-32-chars"
NO_MODEL_TOKEN = "kind-drafts-no-model-token-at-least-32-chars"
DRAFTER = load_manifest()[DRAFTER_ROLE].primary.model_id


def _reply(value: Any) -> HttpResponse:
    return HttpResponse(
        status_code=200, text=json.dumps(chat_body(json.dumps(value), model=DRAFTER))
    )


def _farm() -> dict[str, Any]:
    return held_to_form(brief_of(fixture_kind("farm")))


class _Held(FakeTransport):
    """A scripted transport that holds every request until ``release`` is set: a model still
    reasoning while the route has long since answered."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.release.set()
        self.arrived = threading.Event()

    def post_json(self, url, *, headers, payload, timeout):  # type: ignore[no-untyped-def]
        self.arrived.set()
        assert self.release.wait(20), "the test never let the model answer"
        return super().post_json(url, headers=headers, payload=payload, timeout=timeout)


@pytest.fixture(name="named")
def _named_alias(request):
    return request.getfixturevalue("saved_named")


@pytest.fixture
def drafts(named, spine_schema, monkeypatch):
    _psycopg, scratch = spine_schema
    repository_, store, _session, _entities = named
    repository_.connection.commit()
    grant = {"workspace_id": str(repository_.workspace_id), "actor": str(uuid.uuid4())}
    other = {"workspace_id": str(uuid.uuid4()), "actor": str(uuid.uuid4())}
    no_model = [p for p in EVERY_PERMISSION if p != str(permissions.Permission.MODEL_INVOKE)]
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {**grant, "permissions": EVERY_PERMISSION},
                OTHER_TOKEN: {**other, "permissions": EVERY_PERMISSION},
                NEIGHBOUR_TOKEN: {
                    **grant,
                    "actor": str(uuid.uuid4()),
                    "permissions": EVERY_PERMISSION,
                },
                NO_MODEL_TOKEN: {**grant, "permissions": no_model},
            }
        ),
    )
    transport = _Held()
    database = scratch_database(scratch)

    def app(model: bool = True, spent: bool = False) -> TestClient:
        return TestClient(
            create_app(
                Services(
                    database=database,
                    readonly_database=database,
                    store=store,
                    tokens=load_token_directory(),
                    executor_shares_the_write_role=True,
                    model_client=ModelClient(
                        api_key="test-key-not-real",
                        transport=transport,
                        budget=BudgetGuard(ceiling_usd=Decimal("0"), max_calls=0)
                        if spent
                        else BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
                    )
                    if model
                    else None,
                ),
                verify=False,
            )
        )

    return app, transport


def _start(client: TestClient, description: str, token: str = TOKEN):
    return client.post(
        "/worlds/kinds/drafts",
        headers={"Authorization": f"Bearer {token}"},
        json={"description": description},
    )


def _read(client: TestClient, draft_id: str, token: str = TOKEN):
    return client.get(
        f"/worlds/kinds/drafts/{draft_id}", headers={"Authorization": f"Bearer {token}"}
    )


def _ended(client: TestClient, draft_id: str) -> dict[str, Any]:
    for _ in range(600):
        body = _read(client, draft_id).json()
        if body["state"] != "drafting":
            return body
        time.sleep(0.1)
    raise AssertionError("the draft never ended")


def test_the_route_answers_before_the_model_and_the_page_reads_the_kept_kind(drafts):
    app, transport = drafts
    transport.release.clear()
    transport.responses.append(_reply(_farm()))
    with app() as client:
        started = _start(client, "a small farm with a farmhouse, a barn and a duck pond")
        assert started.status_code == 202, started.text
        body = started.json()
        assert (body["state"], body["poll_after_seconds"], body["kind"]) == ("drafting", 3, None)
        assert transport.arrived.wait(10), "the job never asked the model"
        running = _read(client, body["draft_id"]).json()
        assert (running["state"], running["description"]) == ("drafting", body["description"])
        transport.release.set()
        ended = _ended(client, body["draft_id"])
        assert ended["state"] == "ready", ended
        # A draft that ended keeps none of the words a person typed.
        assert ended["description"] == ""
        assert ended["kind"]["source"] == "workspace" and ended["kind"]["origin"] == "drafted"
        assert ended["model_id"] == DRAFTER and ended["execution"] is not None
        library = client.get("/worlds/kinds", headers={"Authorization": f"Bearer {TOKEN}"}).json()
        assert ended["kind"]["kind"] in {k["kind"] for k in library["kinds"]}


def test_a_workspace_with_a_draft_running_is_told_which_and_starts_no_other(drafts):
    app, transport = drafts
    transport.release.clear()
    transport.responses.append(_reply(_farm()))
    with app() as client:
        first = _start(client, "a small farm").json()
        busy = _start(client, "a harbour")
        assert busy.status_code == 409 and busy.json()["code"] == "kind_draft_busy"
        assert busy.json()["draft_id"] == first["draft_id"]
        transport.release.set()
        assert _ended(client, first["draft_id"])["state"] == "ready"


def test_a_draft_no_brief_makes_a_kind_of_is_refused_by_name(drafts):
    app, transport = drafts
    for _ in range(3):
        transport.responses.append(_reply({"zones": []}))
    with app() as client:
        ended = _ended(client, _start(client, "a nothing").json()["draft_id"])
    assert ended["state"] == "refused" and ended["refusal"]["code"] == "kind_not_drafted"
    assert ended["kind"] is None and len(transport.requests) == 3


def test_a_second_kind_under_a_key_the_workspace_keeps_is_kept_under_the_next_free_key(drafts):
    app, transport = drafts
    transport.responses.extend([_reply(_farm()), _reply(_farm())])
    with app() as client:
        first = _ended(client, _start(client, "a small farm").json()["draft_id"])
        second = _ended(client, _start(client, "another small farm").json()["draft_id"])
    key = first["kind"]["kind"]
    assert second["kind"]["kind"] == f"{key}_2"


def test_saved_names_never_reach_the_model_and_the_kind_keeps_no_words(drafts):
    app, transport = drafts
    transport.responses.append(_reply(_farm()))
    with app() as client:
        ended = _ended(
            client,
            _start(client, "a farm where Maria Estrada lives beside Lantern House").json()[
                "draft_id"
            ],
        )
    sent = json.dumps(transport.requests[0]["payload"]).lower()
    assert "maria" not in sent and "estrada" not in sent and "lantern" not in sent
    assert ended["state"] == "ready"
    assert "Estrada" not in json.dumps(ended["kind"]) and "Lantern" not in json.dumps(ended["kind"])


def test_an_unknown_or_another_workspace_s_draft_is_unknown(drafts):
    app, transport = drafts
    transport.responses.append(_reply(_farm()))
    with app() as client:
        draft_id = _start(client, "a small farm").json()["draft_id"]
        _ended(client, draft_id)
        assert _read(client, str(uuid.uuid4())).json()["code"] == "kind_draft_unknown"
        foreign = _read(client, draft_id, OTHER_TOKEN)
        assert foreign.status_code == 404 and foreign.json()["code"] == "kind_draft_unknown"


def test_no_model_and_no_room_for_a_kind_are_answered_before_anything_is_spent(drafts, monkeypatch):
    app, transport = drafts
    with app(model=False) as client:
        assert _start(client, "a small farm").status_code == 503
    with app() as client:
        assert _start(client, "a small farm", NO_MODEL_TOKEN).status_code == 403
        monkeypatch.setattr(repository, "KINDS_PER_WORKSPACE", 0)
        full = _start(client, "a small farm")
        assert full.status_code == 409 and full.json()["code"] == "kind_cap_reached"
    assert transport.requests == []


def _drafting(client: TestClient, token: str = TOKEN) -> dict[str, Any]:
    library = client.get("/worlds/kinds", headers={"Authorization": f"Bearer {token}"})
    assert library.status_code == 200, library.text
    return library.json()["drafting"]


def test_the_library_says_before_anything_is_typed_whether_drafting_is_offered(drafts, monkeypatch):
    app, transport = drafts
    with app() as client:
        offered = _drafting(client)
        assert (offered["offered"], offered["code"]) == (True, None)
        listed = {refusal["code"] for refusal in offered["refusals"]}
        assert {"kind_draft_busy", "not_authorised", "provider_credential_absent"} <= listed
        assert _drafting(client, NO_MODEL_TOKEN)["code"] == "not_authorised"
        monkeypatch.setattr(repository, "KINDS_PER_WORKSPACE", 0)
        assert _drafting(client)["code"] == "kind_cap_reached"
    with app(model=False) as client:
        assert _drafting(client)["code"] == "provider_credential_absent"
    assert transport.requests == []


def test_a_person_finds_their_drafts_again_newest_first(drafts):
    app, transport = drafts
    transport.responses.extend([_reply(_farm()), _reply(_farm())])
    with app() as client:
        first = _ended(client, _start(client, "a small farm").json()["draft_id"])
        second = _ended(client, _start(client, "another small farm").json()["draft_id"])
        listed = client.get(
            "/worlds/kinds/drafts", headers={"Authorization": f"Bearer {TOKEN}"}
        ).json()["drafts"]
        assert [d["draft_id"] for d in listed] == [second["draft_id"], first["draft_id"]]
        foreign = client.get(
            "/worlds/kinds/drafts", headers={"Authorization": f"Bearer {OTHER_TOKEN}"}
        ).json()["drafts"]
        assert foreign == []


def test_another_person_in_the_workspace_is_told_neither_the_running_draft_nor_its_words(drafts):
    app, transport = drafts
    transport.release.clear()
    transport.responses.append(_reply(_farm()))
    with app() as client:
        mine = _start(client, "a farm where Maria Estrada lives").json()
        busy = _start(client, "a harbour", NEIGHBOUR_TOKEN)
        assert busy.status_code == 409 and busy.json()["code"] == "kind_draft_busy"
        assert "draft_id" not in busy.json()
        theirs = _read(client, mine["draft_id"], NEIGHBOUR_TOKEN)
        assert theirs.status_code == 404 and theirs.json()["code"] == "kind_draft_unknown"
        assert "Estrada" not in theirs.text
        listed = client.get(
            "/worlds/kinds/drafts", headers={"Authorization": f"Bearer {NEIGHBOUR_TOKEN}"}
        ).json()
        assert listed == {"drafts": []}
        assert _drafting(client, NEIGHBOUR_TOKEN)["code"] == "kind_draft_busy"
        transport.release.set()
        assert _ended(client, mine["draft_id"])["state"] == "ready"


def test_a_spent_allowance_is_named_and_never_read_as_the_model_s_silence(drafts):
    app, transport = drafts
    transport.responses.append(_reply(_farm()))
    with app(spent=True) as client:
        ended = _ended(client, _start(client, "a small farm").json()["draft_id"])
    assert ended["state"] == "refused" and ended["refusal"]["code"] == "budget_exceeded"
    assert transport.requests == []


def test_a_person_who_started_as_many_drafts_as_an_hour_allows_is_told_when_to_return(drafts):
    app, transport = drafts
    transport.responses.append(_reply(_farm()))
    with app() as client:
        client.app.state.services.kind_drafts.starts_per_hour = 1
        _ended(client, _start(client, "a small farm").json()["draft_id"])
        limited = _start(client, "a harbour")
        assert limited.status_code == 429 and limited.json()["code"] == "kind_draft_limit"
        assert 3500 < int(limited.headers["Retry-After"]) <= 3600
        assert _drafting(client)["code"] == "kind_draft_limit"
        # Another person in the workspace may still start one.
        assert _drafting(client, NEIGHBOUR_TOKEN)["offered"] is True
    assert len(transport.requests) == 1


def test_a_refused_draft_says_the_last_check_s_own_sentence(drafts):
    from test_kind_drafting import _crowded

    crowded = _farm()
    _crowded(crowded)
    app, transport = drafts
    transport.responses.extend(_reply(crowded) for _ in range(3))
    with app() as client:
        ended = _ended(client, _start(client, "a crowded farm").json()["draft_id"])
    refusal = ended["refusal"]
    assert (refusal["code"], refusal["check"]) == (
        "kind_not_drafted",
        "kind_population_out_of_bounds",
    )
    assert "houses" in refusal["detail"]
    assert "No kind of world was drafted" not in refusal["detail"]


def test_a_workspace_whose_allowance_is_spent_is_told_before_anything_is_typed(drafts, monkeypatch):
    from exulanica.models.spending import SpendingRefused

    app, transport = drafts
    asked: list[tuple[str, ...]] = []

    def spent(self, connection, workspace_id, providers):  # type: ignore[no-untyped-def]
        asked.append(tuple(providers))
        return SpendingRefused("spending_limit_reached", scope="workspace")

    monkeypatch.setattr(Services, "allowance_refusal", spent)
    with app() as client:
        assert _drafting(client)["code"] == "budget_exceeded"
        refused = _start(client, "a small farm")
        assert refused.status_code == 429 and refused.json()["code"] == "budget_exceeded"
        assert refused.json()["spending"]["reason"] == "spending_limit_reached"
    # The providers asked are the drafting role's.
    assert set(asked) == {tuple(sorted({s.provider for s in load_manifest()[DRAFTER_ROLE].chain}))}
    assert transport.requests == []
