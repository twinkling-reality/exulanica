"""``POST /worlds/drafts`` and ``GET /worlds/drafts/{draft_id}``: a world made from a person's
words as one job the page polls. The job chooses the tool, drafts with it and makes the world; a
place keeps no kind in the workspace; a refused draft writes nothing.

``GET /worlds/drafts`` says before a word is typed whether a draft would be taken and what one may
spend, and every refusal known before a model is asked is answered before one is. A server whose
deployment takes no kind of place from a person drafts nothing.

The models are a scripted transport: the tool chooser's answer, then the hand-written test farm's
brief (tests/kind_briefs.py, a test fixture and not a kind a model made) or a town's form.

EVERY WORLD MADE HERE HAS A FIXED IDENTITY: the identities a making draws are replaced by a fixed
sequence (``fixed_identities``), so each test makes the same world every run. The tests assert
rules read from the made world's own receipt and rows, never one world's counts.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import os
import re
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from exulanica.api import world_making
from exulanica.api.routes import world_making as world_making_routes
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection import kind_drafting, tool_choosing, world_drafting
from exulanica.selection.tool_choosing import CHOOSER_ROLE
from exulanica.world import saved_entries, specification_source, worlds
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.kinds.library import town_adapter
from exulanica.world.worlds import WorldsReadOnly
from fastapi.testclient import TestClient

from model_fakes import chat_body
from test_companion_saved_names import named as saved_named  # noqa: F401
from test_kind_drafts_postgres import NEIGHBOUR_TOKEN, NO_MODEL_TOKEN, OTHER_TOKEN, TOKEN, _farm
from test_kind_drafts_postgres import _reply as _brief
from test_kind_drafts_postgres import _start as _start_kind
from test_kind_drafts_postgres import drafts as imported_drafts  # noqa: F401

pytestmark = pytest.mark.postgres

CHOOSER = load_manifest()[CHOOSER_ROLE].primary.model_id
#: What the draft routes answer, as the page's own tests read them
#: (web/packages/app/test/world-sentence.test.ts): written by this file's snapshot test when
#: ``EXULANICA_WRITE_SERVED_SNAPSHOTS`` is set, and held by it otherwise.
SERVED = Path(__file__).resolve().parent / "snapshots" / "world-drafts.served.json"
WRITE_SERVED = "EXULANICA_WRITE_SERVED_SNAPSHOTS"
FARM_WORDS = "a small farm with a farmhouse, a barn and a duck pond"
TOWN_WORDS = "a quiet town with two cafes and low buildings"


def _json(value: Any) -> HttpResponse:
    return HttpResponse(
        status_code=200, text=json.dumps(chat_body(json.dumps(value), model=CHOOSER))
    )


def _tool(key: str | None, *words: str) -> HttpResponse:
    return _json({"tool": key, "tool_words": list(words)})


def _town_form(**changes: Any) -> dict[str, Any]:
    """The specification drafter's form with every value left as its preset's."""
    served = specification_source.served_document()
    form: dict[str, Any] = {"preset": "small_town", "fit": "all", "not_supported": []}
    form.update({value["key"]: None for value in served["values"] if value["adjustable"]})
    form.update(changes)
    return form


@pytest.fixture(name="named")
def _named_alias(request):
    return request.getfixturevalue("saved_named")


@pytest.fixture(name="drafts")
def _drafts_alias(request):
    return request.getfixturevalue("imported_drafts")


@pytest.fixture
def fixed_identities(monkeypatch):
    """Every identity a making draws, replaced by a fixed sequence: the same world every run."""
    drawn = itertools.count()

    def fixed(kind: str) -> str:
        name = f"exulanica-test:world-making:{next(drawn)}"
        return f"{worlds.world_kind(kind).id_prefix}{uuid.uuid5(uuid.NAMESPACE_URL, name)}"

    monkeypatch.setattr(saved_entries, "new_world_id", fixed)


def _start(client: TestClient, description: str, token: str = TOKEN):
    return client.post(
        "/worlds/drafts",
        headers={"Authorization": f"Bearer {token}"},
        json={"description": description},
    )


def _read(client: TestClient, draft_id: str, token: str = TOKEN):
    return client.get(f"/worlds/drafts/{draft_id}", headers={"Authorization": f"Bearer {token}"})


def _ended(client: TestClient, draft_id: str) -> dict[str, Any]:
    """The draft once it is ready or refused: waited for itself, with a limit that names it."""
    limit = time.monotonic() + 120
    while time.monotonic() < limit:
        body = _read(client, draft_id).json()
        if body["state"] in ("ready", "refused"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"the world's draft never ended; it was last {body['state']}")


def _workspace() -> uuid.UUID:
    """The owner token's workspace, as the fixture granted it."""
    return uuid.UUID(json.loads(os.environ["EXULANICA_API_TOKENS"])[TOKEN]["workspace_id"])


def _count(client: TestClient, table: str) -> int:
    database = client.app.state.services.database
    workspace = _workspace()
    with database.session(workspace) as connection:
        return int(connection.execute(f"select count(*) as n from {table}").fetchone()["n"])


def _receipt(client: TestClient, entry: dict[str, Any]) -> dict[str, Any]:
    database = client.app.state.services.database
    workspace = _workspace()
    with database.session(workspace) as connection:
        _sha256, receipt = generation_receipt(
            connection, workspace, entry["world_id"], uuid.UUID(entry["source_snapshot_id"])
        )
    return receipt


def test_a_sentence_becomes_a_place_made_with_no_kind_kept(drafts, fixed_identities):
    app, transport = drafts
    transport.release.clear()
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm())])
    with app() as client:
        started = _start(client, FARM_WORDS)
        assert started.status_code == 202, started.text
        body = started.json()
        # The route answered before any model: the job has chosen nothing yet.
        assert (body["state"], body["poll_after_seconds"], body["entry"]) == ("choosing", 3, None)
        assert transport.arrived.wait(10), "the job never asked a model"
        assert _read(client, body["draft_id"]).json()["description"] == FARM_WORDS
        transport.release.set()
        ended = _ended(client, body["draft_id"])
        assert ended["state"] == "ready", ended
        # A draft that ended keeps none of the words a person typed.
        assert ended["description"] == ""
        assert ended["tool"] == {"key": "place", "chosen_by": "model"}
        entry = ended["entry"]
        assert entry["source_kind"] == "generated" and entry["generated_site"] is not None
        # The world's own receipt carries the whole kind; the workspace keeps none for it.
        receipt = _receipt(client, entry)
        document = receipt["kind"]["document"]
        assert _count(client, "world_kind_version") == 0
        listed = client.get("/worlds/kinds", headers={"Authorization": f"Bearer {TOKEN}"}).json()
        assert {kind["source"] for kind in listed["kinds"]} == {"shipped"}
        # What was made is the receipt's kind, part for part, each with its look role, and every
        # part drawn as a thing of its own with the box it is drawn in.
        parts = {part["key"]: part for part in document["parts"]}
        assert [made["key"] for made in ended["made"]] == list(parts)
        for made in ended["made"]:
            stated = parts[made["key"]]
            assert (made["label"], made["form"], made["look"]) == (
                stated["label"],
                stated["form"],
                stated["look"],
            )
            if made["form"] == "fixture" and made["drawn"]:
                assert len(made["box_mm"]) == 3 and min(made["box_mm"]) > 0
            assert (made["box_mm"] is None) == (made["drawn"] == 0)
        assert any(made["form"] == "structure" and made["box_mm"] for made in ended["made"])
        # Both steps' calls are shown with what they cost: the chooser's, then the drafter's.
        roles = [call["role"] for call in ended["execution"]["calls"]]
        assert roles == ["world_tool_chooser", "kind_drafter"]
        # The page reads the made world's drawing next: it was kept with the world.
        site = client.get(
            f"/world/versions/{entry['authored_version_id']}/site?world_id={entry['world_id']}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert site.status_code == 200, site.text


def test_where_the_chooser_is_unsure_the_place_tool_is_taken_and_said(drafts, fixed_identities):
    app, transport = drafts
    transport.responses.extend([_tool(None), _brief(_farm())])
    with app() as client:
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert ended["tool"] == {"key": "place", "chosen_by": "unsure"}
        assert ended["entry"]["generated_site"] is not None


def test_a_sentence_that_asks_for_a_town_is_made_by_the_town_tool(drafts, fixed_identities):
    app, transport = drafts
    left_out = ["two cafes"]
    transport.responses.extend(
        [_tool("town", "a quiet town"), _json(_town_form(fit="part", not_supported=left_out))]
    )
    with app() as client:
        ended = _ended(client, _start(client, TOWN_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert ended["tool"] == {"key": "town", "chosen_by": "model"}
        entry = ended["entry"]
        # A town, made from the preset the form named, through the gate every town passes.
        assert entry["generated_site"] is None
        assert entry["generated_ground"]["recipe_key"] == "small_town"
        assert _receipt(client, entry)["recipe"]["key"] == "small_town"
        # What the words asked for that no value says is said back in the person's own words.
        assert ended["left_out"] == left_out
        # A town's parts are the town adapter's, which state no box.
        stated = [part["key"] for part in town_adapter().document["parts"]]
        assert [made["key"] for made in ended["made"]] == stated
        assert all(made["box_mm"] is None and made["drawn"] is None for made in ended["made"])
        assert _count(client, "world_kind_version") == 0


def test_a_draft_no_brief_makes_a_place_of_is_refused_by_name_and_writes_nothing(drafts):
    app, transport = drafts
    broken = _farm()
    broken["zones"] = []
    transport.responses.extend([_tool("place", "a small farm")] + [_brief(broken)] * 3)
    with app() as client:
        before = _count(client, "world_identity")
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert ended["state"] == "refused", ended
        assert ended["refusal"]["code"] == "kind_not_drafted"
        assert ended["refusal"]["code"] in {code["code"] for code in ended["refusals"]}
        assert ended["entry"] is None and ended["made"] == []
        # Every call it made is still shown: the chooser's and each of the drafter's attempts.
        assert len(ended["execution"]["calls"]) == 4
        assert _count(client, "world_identity") == before
        assert _count(client, "world_kind_version") == 0


def test_words_that_ask_for_no_place_are_refused_by_the_town_tool_by_name(drafts):
    app, transport = drafts
    transport.responses.extend(
        [_tool("town", "a quiet town"), _json(_town_form(fit="none", not_supported=["cafes"]))]
    )
    with app() as client:
        before = _count(client, "world_identity")
        ended = _ended(client, _start(client, TOWN_WORDS).json()["draft_id"])
        assert (ended["state"], ended["refusal"]["code"]) == ("refused", "world_not_a_place")
        assert _count(client, "world_identity") == before


def test_a_world_s_draft_is_read_by_its_own_person_and_its_own_route_only(drafts, fixed_identities):
    app, transport = drafts
    transport.release.clear()
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm())])
    with app() as client:
        draft_id = _start(client, FARM_WORDS).json()["draft_id"]
        assert transport.arrived.wait(10), "the job never asked a model"
        other = _read(client, draft_id, OTHER_TOKEN)
        assert (other.status_code, other.json()["code"]) == (404, "world_draft_unknown")
        unknown = _read(client, str(uuid.uuid4()))
        assert (unknown.status_code, unknown.json()["code"]) == (404, "world_draft_unknown")
        # A kind's routes neither read nor list a world's draft.
        headers = {"Authorization": f"Bearer {TOKEN}"}
        assert client.get(f"/worlds/kinds/drafts/{draft_id}", headers=headers).status_code == 404
        assert client.get("/worlds/kinds/drafts", headers=headers).json()["drafts"] == []
        # One holder and one budget: while it runs, the workspace starts no other draft. The
        # kinds' route tells no id of a world's draft: it would read 404 there.
        busy = _start_kind(client, "a vineyard")
        assert (busy.status_code, busy.json()["code"]) == (409, "kind_draft_busy")
        assert "draft_id" not in busy.json()
        again = _start(client, "a harbour")
        assert (again.status_code, again.json()["draft_id"]) == (409, draft_id)
        transport.release.set()
        assert _ended(client, draft_id)["state"] == "ready"


def _offer(client: TestClient, token: str = TOKEN) -> dict[str, Any]:
    answer = client.get("/worlds/drafts", headers={"Authorization": f"Bearer {token}"})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_offer_says_what_a_draft_may_spend_before_a_word_is_typed(drafts, fixed_identities):
    app, transport = drafts
    transport.release.clear()
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm())])
    with app() as client:
        registry = client.app.state.services.kind_drafts
        registry.starts_per_hour = 2
        before = _offer(client)
        assert (before["offered"], before["code"], before["detail"]) == (True, None, None)
        # The most calls a draft makes is counted from the steps' own bounds: the chooser's call
        # and its repair, then the attempts of whichever tool's drafter makes the most.
        most = max(kind_drafting.DRAFT_ATTEMPTS, world_drafting.DRAFT_ATTEMPTS)
        assert before["calls_at_most"] == tool_choosing.ATTEMPTS + most
        assert before["starts"] == {"an_hour": 2, "left": 2, "retry_after_seconds": None}
        assert before["description_characters"] == 1000
        assert before["running_draft_id"] is None
        # A caller who may not draft is told so, and nothing else about the workspace.
        without = _offer(client, NO_MODEL_TOKEN)
        assert (without["offered"], without["code"]) == (False, "not_authorised")
        draft_id = _start(client, FARM_WORDS).json()["draft_id"]
        assert transport.arrived.wait(10), "the job never asked a model"
        # While it runs: its own person is handed it to follow; a neighbour in the workspace is
        # told a draft runs and no id; another workspace is told nothing of it.
        mine = _offer(client)
        assert (mine["code"], mine["running_draft_id"]) == ("kind_draft_busy", draft_id)
        assert mine["starts"]["left"] == 1
        neighbour = _offer(client, NEIGHBOUR_TOKEN)
        assert (neighbour["code"], neighbour["running_draft_id"]) == ("kind_draft_busy", None)
        # Nor does the neighbour read it by an id they were never told.
        assert _read(client, draft_id, NEIGHBOUR_TOKEN).status_code == 404
        elsewhere = _offer(client, OTHER_TOKEN)
        assert (elsewhere["offered"], elsewhere["running_draft_id"]) == (True, None)
        transport.release.set()
        assert _ended(client, draft_id)["state"] == "ready"
        after = _offer(client)
        assert (after["offered"], after["running_draft_id"]) == (True, None)
        # The hour's starts used up are said before a word is typed, with when the next frees.
        transport.responses.extend([_tool("place", "a small farm"), _brief(_farm())])
        _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        spent = _offer(client)
        assert (spent["offered"], spent["code"]) == (False, "kind_draft_limit")
        assert spent["starts"]["left"] == 0 and spent["starts"]["retry_after_seconds"] >= 1
        assert spent["code"] in {code["code"] for code in spent["refusals"]}
        again = _start(client, FARM_WORDS)
        assert (again.status_code, again.json()["code"]) == (429, "kind_draft_limit")


def test_a_server_that_takes_no_kind_from_a_person_drafts_no_world_and_says_so(drafts):
    app, transport = drafts
    with app(words=False) as client:
        refused = _start(client, FARM_WORDS)
        assert (refused.status_code, refused.json()["code"]) == (
            403,
            "kinds_from_people_not_offered",
        )
        offer = _offer(client)
        assert (offer["offered"], offer["code"]) == (False, "kinds_from_people_not_offered")
        assert offer["code"] in {code["code"] for code in offer["refusals"]}
        assert _count(client, "world_identity") == 0
    assert not transport.arrived.is_set()
    assert transport.requests == []


def test_a_workspace_at_its_world_limit_is_told_before_any_model_is_asked(
    drafts, fixed_identities, monkeypatch
):
    app, transport = drafts
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm())])
    with app() as client:
        assert _ended(client, _start(client, FARM_WORDS).json()["draft_id"])["state"] == "ready"
        asked = len(transport.requests)
        # The deployment's own figure: this workspace now holds as many generated worlds as it may.
        monkeypatch.setenv("EXULANICA_WORLDS_HELD", str(_count(client, "world_identity")))
        offer = _offer(client)
        assert (offer["offered"], offer["code"]) == (False, "world_limit_reached")
        refused = _start(client, "a harbour with fishing boats")
        assert (refused.status_code, refused.json()["code"]) == (409, "world_limit_reached")
        assert len(transport.requests) == asked


def test_a_database_role_that_cannot_register_a_world_is_told_before_any_model_is_asked(
    drafts, monkeypatch
):
    """The judge stack's shape. The role's own answer is the registration probe's
    (exulanica.world.worlds.may_register_worlds), stood in for here: the rule under test is that
    the route asks it of the role that would write, before the job starts."""
    app, transport = drafts
    asked_of: list[Any] = []

    def read_only(connection: Any) -> None:
        asked_of.append(connection)
        raise WorldsReadOnly()

    monkeypatch.setattr(world_making_routes, "require_world_registration", read_only)
    with app() as client:
        offer = _offer(client)
        assert (offer["offered"], offer["code"]) == (False, "worlds_read_only")
        refused = _start(client, FARM_WORDS)
        assert (refused.status_code, refused.json()["code"]) == (403, "worlds_read_only")
        assert len(asked_of) == 2
    assert transport.requests == []


def test_a_guest_makes_a_world_through_the_route_and_is_held_to_a_guest_s_figures(
    drafts, fixed_identities, monkeypatch
):
    app, transport = drafts
    monkeypatch.setenv("EXULANICA_GUEST_DRAFT_STARTS_AN_HOUR", "2")
    monkeypatch.setenv("EXULANICA_GUEST_WORLDS_HELD", "1")
    # A signed-in person's figures, which a guest is never read by.
    monkeypatch.setenv("EXULANICA_DRAFT_STARTS_AN_HOUR", "9")
    monkeypatch.setenv("EXULANICA_WORLDS_HELD", "9")
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm())])
    with app(guest=True) as client:
        assert _offer(client)["starts"] == {"an_hour": 2, "left": 2, "retry_after_seconds": None}
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert ended["entry"]["generated_site"] is not None
        assert _count(client, "world_identity") == 1
        # The guest's own world limit is now reached, and said before any further call.
        asked = len(transport.requests)
        offer = _offer(client)
        assert (offer["code"], offer["starts"]["left"]) == ("world_limit_reached", 1)
        refused = _start(client, "a harbour with fishing boats")
        assert (refused.status_code, refused.json()["code"]) == (409, "world_limit_reached")
        assert len(transport.requests) == asked


def test_a_making_that_is_refused_ends_refused_by_name_and_leaves_nothing_behind(
    drafts, fixed_identities, monkeypatch
):
    """The world limit asked again where it holds, at the registration: reached between the
    start and the making, the making writes nothing and the draft says why with what it cost."""
    app, transport = drafts
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm())])
    with app() as client:
        assert _ended(client, _start(client, FARM_WORDS).json()["draft_id"])["state"] == "ready"
        held = _count(client, "world_identity")
        receipts = _count(client, "world_generation_receipt")
        entries = _count(client, "saved_world_entry")
        monkeypatch.setenv("EXULANICA_WORLDS_HELD", str(held + 1))
        transport.release.clear()
        transport.arrived.clear()
        transport.responses.extend([_tool("place", "a small farm"), _brief(_farm())])
        draft_id = _start(client, FARM_WORDS).json()["draft_id"]
        assert transport.arrived.wait(10), "the job never asked a model"
        # The limit falls while the model reasons.
        monkeypatch.setenv("EXULANICA_WORLDS_HELD", str(held))
        transport.release.set()
        ended = _ended(client, draft_id)
        assert (ended["state"], ended["refusal"]["code"]) == ("refused", "world_limit_reached")
        assert ended["entry"] is None and ended["made"] == []
        assert len(ended["execution"]["calls"]) == 2
        assert _count(client, "world_identity") == held
        assert _count(client, "world_generation_receipt") == receipts
        assert _count(client, "saved_world_entry") == entries


def test_a_world_that_was_made_ends_ready_whatever_follows_its_making(
    drafts, fixed_identities, monkeypatch
):
    app, transport = drafts
    counted = world_making.site_parts

    def failing(kind: Any, drawing: Any) -> Any:
        if drawing is not None:
            raise RuntimeError("counting the drawn parts failed")
        return counted(kind, drawing)

    monkeypatch.setattr(world_making, "site_parts", failing)
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm())])
    with app() as client:
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        # Never "say it again" for a world that exists: ready, with its parts by name and no box.
        assert ended["state"] == "ready", ended
        assert ended["entry"]["generated_site"] is not None
        document = _receipt(client, ended["entry"])["kind"]["document"]
        assert [made["key"] for made in ended["made"]] == [p["key"] for p in document["parts"]]
        assert all(made["box_mm"] is None for made in ended["made"])


def test_a_chooser_that_fails_for_any_reason_leaves_the_unsure_tool_standing(
    drafts, fixed_identities, monkeypatch
):
    app, transport = drafts

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("the chooser's own fault, no model's")

    monkeypatch.setattr(world_making, "choose_tool", broken)
    transport.responses.extend([_brief(_farm())])
    with app() as client:
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert ended["tool"] == {"key": "place", "chosen_by": "unsure"}


def test_every_call_of_a_draft_is_reserved_and_settled_against_the_workspace_s_grant(
    drafts, fixed_identities, spine_schema, tmp_path
):
    """Under the durable spending authority, as a public server runs: each model request the job
    makes is one reservation of the workspace's own grant, settled when the call returns."""
    from exulanica.spending.ledger import DurableSpending, holder_label
    from exulanica.spending.operator import SpendingOperator
    from exulanica.spending.witness import FileSpendingWitness

    from tests_support_api import scratch_database

    app, transport = drafts
    _psycopg, scratch = spine_schema
    database = scratch_database(scratch)
    witness = FileSpendingWitness(tmp_path / "spending-witness", lock_timeout_s=5.0)
    operator = SpendingOperator(database, witness)
    workspace = _workspace()
    manifest = load_manifest()
    until = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
    grants = set()
    for provider in sorted({manifest[CHOOSER_ROLE].provider, manifest[Role.KIND_DRAFTER].provider}):
        authority = operator.issue(
            provider=provider,
            ceiling_usd=Decimal("10"),
            max_calls=1000,
            valid_until=until,
            dispatch_seconds=60,
            witnessed=True,
            operator="test-operator",
            reason="a test installation's allowance",
        )
        grants.add(
            operator.grant(
                authority,
                workspace,
                ceiling_usd=Decimal("1"),
                max_calls=100,
                valid_until=until,
                operator="test-operator",
                reason="a test workspace's allowance",
            )
        )
    durable = DurableSpending(database, witness, holder=holder_label("world-drafts"))
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm())])
    with app(spending=durable) as client:
        assert _offer(client)["offered"] is True
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
        calls = ended["execution"]["calls"]
    with database.session(workspace) as connection:
        reservations = connection.execute(
            "select state, grant_id from spending_reservation where workspace_id = %s",
            (workspace,),
        ).fetchall()
    assert len(reservations) == len(calls) == len(transport.requests) == 2
    assert {row["state"] for row in reservations} == {"settled"}
    assert {row["grant_id"] for row in reservations} <= grants


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_SHA256 = re.compile(r"\b[0-9a-f]{64}\b")
_MOMENT = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)")


def _as_served(body: Any) -> Any:
    """An answer with everything a run draws replaced by a stand-in of the same shape: each
    identity by one numbered in the order it is met, each digest and each moment by a fixed one,
    the seconds by zero and what the calls cost left out. What stays is what the page reads by:
    every member's name and kind, the states, the words and the figures the policy states."""
    met: dict[str, str] = {}

    def identity(found: re.Match[str]) -> str:
        return met.setdefault(found.group(0), str(uuid.UUID(int=len(met) + 1)))

    def walk(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {name: walk(inner, name) for name, inner in value.items()}
        if isinstance(value, list):
            return [walk(inner, key) for inner in value]
        if isinstance(value, str):
            value = _UUID.sub(identity, value)
            value = _SHA256.sub("0" * 64, value)
            return _MOMENT.sub("2026-01-01T00:00:00Z", value)
        if key == "elapsed_seconds":
            return 0
        return value

    cleared = walk(body)
    if isinstance(cleared, dict) and cleared.get("execution") is not None:
        cleared["execution"] = None
    return cleared


def test_the_page_s_fixture_is_what_the_draft_routes_answer(drafts, fixed_identities):
    """The page's tests read ``tests/snapshots/world-drafts.served.json``; this holds that file
    to the server's own answers, so an answer the page cannot read fails the page's tests in the
    same change. Written again with ``EXULANICA_WRITE_SERVED_SNAPSHOTS=1``."""
    app, transport = drafts
    served: dict[str, Any] = {}
    with app() as client:
        served["offer"] = _as_served(_offer(client))
        transport.release.clear()
        transport.responses.extend([_tool("place", "a small farm"), _brief(_farm())])
        started = _start(client, FARM_WORDS).json()
        served["started"] = _as_served(started)
        assert transport.arrived.wait(10), "the job never asked a model"
        served["offer_while_mine_runs"] = _as_served(_offer(client))
        transport.release.set()
        served["ready_place"] = _as_served(_ended(client, started["draft_id"]))
        transport.responses.extend(
            [
                _tool("town", "a quiet town"),
                _json(_town_form(fit="part", not_supported=["two cafes"])),
            ]
        )
        served["ready_town"] = _as_served(
            _ended(client, _start(client, TOWN_WORDS).json()["draft_id"])
        )
        broken = _farm()
        broken["zones"] = []
        transport.responses.extend([_tool("place", "a small farm")] + [_brief(broken)] * 3)
        served["refused"] = _as_served(
            _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        )
    text = json.dumps(served, indent=1, ensure_ascii=False) + "\n"
    if os.environ.get(WRITE_SERVED):
        SERVED.write_text(text, encoding="utf-8")
    assert SERVED.read_text(encoding="utf-8") == text, (
        "what the draft routes answer moved: write the snapshot again "
        f"({WRITE_SERVED}=1 with this test), run the page's tests, and commit both with the change"
    )
