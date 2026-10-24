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
from exulanica.api.app import create_app
from exulanica.api.instance_settings import SocietySettingRefused, _host_keeps_until
from exulanica.api.routes import world_making as world_making_routes
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection.tool_choosing import CHOOSER_ROLE
from exulanica.world import saved_entries, specification_source, worlds
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.kinds.library import town_adapter
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.world_settings import setting_parts
from exulanica.world.worlds import WorldsReadOnly
from fastapi.testclient import TestClient

from model_fakes import FakeTransport, chat_body
from spending_support import bench as bench
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


def _look(pack_id: str | None, *words: str) -> HttpResponse:
    """The look chooser's answer: a listed look and the words that chose it, or none."""
    return _json({"look": pack_id, "look_words": list(words)})


def _setting(*words: str, **parts: str) -> HttpResponse:
    """The setting chooser's answer: a part for the axes named, and the words that chose them."""
    axes = {key: parts.get(key) for key, _title in setting_parts().axes}
    return _json({**axes, "words": list(words)})


def _plain() -> list[HttpResponse]:
    """The two steps' answers for words that ask for no look and no setting."""
    return [_look(None), _setting()]


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
def _drafts_alias(request, bench, monkeypatch):
    """Native world drafts use private durable spending and metadata fixtures."""
    import datetime as dt
    from dataclasses import replace

    from exulanica.models.provider_catalog import ProviderPrice

    factory, transport = request.getfixturevalue("imported_drafts")
    durable = bench.durable("native-world-maker")
    sample = factory(spending=durable)
    workspace = sample.app.state.services.tokens.session_for(TOKEN).workspace_id

    def price_read(client, provider):
        return {
            s.model_id: ProviderPrice(
                s.model_id,
                s.input_usd_per_mtok,
                s.output_usd_per_mtok,
                s.context_window_tokens,
                "f" * 64,
            )
            for s in client.manifest.models.values()
            if s.provider == provider
        }

    monkeypatch.setattr(ModelClient, "provider_prices", price_read)

    def app(*args, on_land: bool = False, keeps_until: dt.date | None = None, **kwargs):
        """``on_land``: a deployment that makes places from a sentence on land; ``keeps_until``: the
        day a host keeps what is made on it until."""
        if kwargs.get("spending") is None:
            for provider in load_manifest().providers:
                if bench.query(
                    "select 1 from spending_grant g join spending_authority a using(authority_id) "
                    "where g.workspace_id=%s and a.provider=%s and g.parent_grant_id is null",
                    workspace,
                    provider,
                ):
                    continue
                until = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
                authority = bench.operator.issue(
                    provider=provider,
                    ceiling_usd=Decimal("1000"),
                    max_calls=100000,
                    valid_until=until,
                    dispatch_seconds=60,
                    witnessed=True,
                    operator="test-operator",
                    reason="Private native world fixture",
                )
                bench.operator.grant(
                    authority,
                    workspace,
                    ceiling_usd=Decimal("100"),
                    max_calls=10000,
                    valid_until=until,
                    operator="test-operator",
                    reason="Private native world fixture",
                )
            kwargs["spending"] = durable
        original = factory(*args, **kwargs)
        services = replace(
            original.app.state.services,
            database=bench.runtime,
            readonly_database=bench.runtime,
            worlds_on_land=on_land,
            host_keeps_until=keeps_until,
        )
        application = create_app(services, verify=False)
        application.dependency_overrides.update(original.app.dependency_overrides)
        return TestClient(application)

    return app, transport


@pytest.fixture
def fixed_identities(monkeypatch):
    """Every identity a making draws, replaced by a fixed sequence: the same world every run."""
    drawn = itertools.count()

    def fixed(kind: str) -> str:
        name = f"exulanica-test:world-making:{next(drawn)}"
        return f"{worlds.world_kind(kind).id_prefix}{uuid.uuid5(uuid.NAMESPACE_URL, name)}"

    monkeypatch.setattr(saved_entries, "new_world_id", fixed)
    from exulanica.world import world_draft_jobs

    class FixedDraftUUID:
        def __getattr__(self, name):
            return getattr(uuid, name)

        def uuid5(self, namespace, name):
            return uuid.UUID(fixed("generated").removeprefix("world:generated:"))

    monkeypatch.setattr(world_draft_jobs, "uuid", FixedDraftUUID())


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
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
    with app() as client:
        started = _start(client, FARM_WORDS)
        assert started.status_code == 202, started.text
        body = started.json()
        # The route answered before any model: the job has chosen nothing yet.
        assert (body["state"], body["poll_after_seconds"], body["entry"]) == ("queued", 3, None)
        assert transport.arrived.wait(10), "the job never asked a model"
        assert _read(client, body["draft_id"]).json()["description"] == FARM_WORDS
        transport.release.set()
        ended = _ended(client, body["draft_id"])
        assert ended["state"] == "ready", ended
        # The ended draft forgets the words; the world it made keeps the sentence, and the draft
        # read answers it from there (0222).
        assert ended["description"] == FARM_WORDS
        assert (_count(client, "world_draft_input"), _count(client, "world_made_from")) == (0, 1)
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
        assert roles == ["world_tool_chooser", "kind_drafter", "look_chooser", "setting_chooser"]
        # The words asked for no look and no setting, and none was taken; the server makes
        # places on level ground unless its deployment says on land.
        assert (ended["look"], ended["setting"], ended["land"]) == (None, None, None)
        assert receipt["composer"] == {"key": "site-plan", "version": 1}
        # The page reads the made world's drawing next: it was kept with the world.
        site = client.get(
            f"/world/versions/{entry['authored_version_id']}/site?world_id={entry['world_id']}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert site.status_code == 200, site.text


def test_a_site_reports_missing_content_even_when_an_overlapping_setting_is_taken(
    drafts, fixed_identities
):
    app, transport = drafts
    words = "a small farm beside the sea with flying boats"
    brief = _farm()
    brief["requirements"].append(
        {
            "words": "sea with flying boats",
            "status": "omitted",
            "omission": "unsupported_behavior",
            "form": "",
            "roles": [],
            "look": "",
            "shape_class": "",
            "roof_form": "",
            "minimum_count": 1,
            "part_labels": [],
        }
    )
    transport.responses.extend(
        [
            _tool("place", "a small farm"),
            _brief(brief),
            _look(None),
            _setting("sea", ground="sea"),
        ]
    )
    with app() as client:
        ended = _ended(client, _start(client, words).json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert ended["left_out"] == ["sea with flying boats"]
        assert "not_supported" not in _receipt(client, ended["entry"])["kind"]["document"]


def test_on_land_a_place_stands_on_the_land_its_words_name_and_says_so(drafts, fixed_identities):
    from exulanica.grammar.landform import land_recipes

    coast = next(recipe for recipe in land_recipes() if recipe.key == "coast")
    app, transport = drafts
    transport.responses.extend(
        [
            _tool("place", "a small farm"),
            _brief(_farm()),
            _look(None),
            _setting("sea", ground="sea"),
        ]
    )
    with app(on_land=True) as client:
        ended = _ended(client, _start(client, "a small farm by the sea").json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert ended["land"] == {
            "recipe": "coast",
            "title": coast.title,
            "chosen_by": "words",
            "words": ["sea"],
            "fell_back": False,
        }
        receipt = _receipt(client, ended["entry"])
        assert receipt["composer"] == {"key": "site-plan", "version": 5}
        assert receipt["land_sha256"] == coast.land_sha256
        # The setting the words chose is taken as ever, beside the land.
        assert [part["key"] for part in ended["setting"]["parts"]] == ["sea"]
        entry = ended["entry"]
        site = client.get(
            f"/world/versions/{entry['authored_version_id']}/site?world_id={entry['world_id']}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert site.status_code == 200 and site.json()["profile"] == "exulanica.site-drawing/v5"


def test_on_land_words_that_name_no_land_stand_on_the_default(drafts, fixed_identities):
    app, transport = drafts
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
    with app(on_land=True) as client:
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert (ended["land"]["recipe"], ended["land"]["chosen_by"]) == ("rolling", "default")
        assert (ended["land"]["words"], ended["land"]["fell_back"]) == ([], False)
        assert _receipt(client, ended["entry"])["composer"]["version"] == 5


def test_on_land_a_place_no_layout_of_which_fits_its_land_is_made_level_and_says_so(
    drafts, fixed_identities, monkeypatch
):
    from exulanica.grammar.landform import LandRecipe, read_land_document
    from exulanica.world.land_choice import LandChoice

    # Land rising higher than near land may stand: every layout candidate is refused on it.
    land = read_land_document(
        {
            "profile": "exulanica.landform/v1",
            "ground_mm": 40000,
            "features": [
                {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 120},
                {"id": "wall", "kind": "rise", "side": "north", "distance_mm": 0,
                 "width_mm": 600000, "depth_mm": 100000, "height_mm": 40000,
                 "roughness_permille": 0},
            ],
        }
    )  # fmt: skip
    steep = LandRecipe(
        key="steep",
        title="a steep test slope",
        words=(),
        for_ground=(),
        default=False,
        land=land.canonical(),
        land_sha256=land.sha256,
    )
    monkeypatch.setattr(
        world_making,
        "choose_land",
        lambda *args, **kwargs: LandChoice(recipe=steep, chosen_by="default", spans=()),
    )
    app, transport = drafts
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
    with app(on_land=True) as client:
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert (ended["land"]["recipe"], ended["land"]["fell_back"]) == ("steep", True)
        receipt = _receipt(client, ended["entry"])
        assert receipt["composer"] == {"key": "site-plan", "version": 1} and "land" not in receipt


def test_where_the_chooser_is_unsure_the_place_tool_is_taken_and_said(drafts, fixed_identities):
    app, transport = drafts
    transport.responses.extend([_tool(None), _brief(_farm()), *_plain()])
    with app() as client:
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert ended["tool"] == {"key": "place", "chosen_by": "unsure"}
        assert ended["entry"]["generated_site"] is not None


def test_a_sentence_that_asks_for_a_town_is_made_by_the_town_tool(drafts, fixed_identities):
    app, transport = drafts
    left_out = ["two cafes"]
    transport.responses.extend(
        [
            _tool("town", "a quiet town"),
            _json(_town_form(fit="part", not_supported=left_out)),
            *_plain(),
        ]
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
        # Titled from the person's own words (N33), not by the preset's label.
        assert entry["title"] == "A quiet town with two cafes and low buildings"
        # What the words asked for that no value says is said back in the person's own words.
        assert ended["left_out"] == left_out
        # A town's parts are the town adapter's, which state no box.
        stated = [part["key"] for part in town_adapter().document["parts"]]
        assert [made["key"] for made in ended["made"]] == stated
        assert all(made["box_mm"] is None and made["drawn"] is None for made in ended["made"])
        assert _count(client, "world_kind_version") == 0


def test_on_land_a_town_stands_on_the_land_its_words_name_and_says_so(drafts, fixed_identities):
    from exulanica.grammar.landform import land_recipes

    coast = next(recipe for recipe in land_recipes() if recipe.key == "coast")
    app, transport = drafts
    transport.responses.extend(
        [
            _tool("town", "a quiet town"),
            _json(_town_form()),
            _look(None),
            _setting("sea", ground="sea"),
        ]
    )
    with app(on_land=True) as client:
        ended = _ended(client, _start(client, "a quiet town by the sea").json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert ended["land"] == {
            "recipe": "coast",
            "title": coast.title,
            "chosen_by": "words",
            "words": ["sea"],
            "fell_back": False,
        }
        receipt = _receipt(client, ended["entry"])
        assert receipt["composer"] == {"key": "city-grammar-town", "version": 3}
        assert receipt["land_sha256"] == coast.land_sha256


def test_on_land_a_town_no_candidate_of_which_fits_its_land_is_made_level_and_says_so(
    drafts, fixed_identities, monkeypatch
):
    from exulanica.grammar.landform import LandRecipe, read_land_document
    from exulanica.world.land_choice import LandChoice

    # Land tilting across the town faster than its streets and banks can take: every candidate
    # is refused on it.
    land = read_land_document(
        {
            "profile": "exulanica.landform/v1",
            "ground_mm": 20000,
            "features": [{"id": "tilt", "kind": "tilt", "side": "east", "grade_permille": 120}],
        }
    )
    steep = LandRecipe(
        key="steep",
        title="a steep test slope",
        words=(),
        for_ground=(),
        default=False,
        land=land.canonical(),
        land_sha256=land.sha256,
    )
    monkeypatch.setattr(
        world_making,
        "choose_land",
        lambda *args, **kwargs: LandChoice(recipe=steep, chosen_by="default", spans=()),
    )
    app, transport = drafts
    transport.responses.extend([_tool("town", "a quiet town"), _json(_town_form()), *_plain()])
    with app(on_land=True) as client:
        ended = _ended(client, _start(client, TOWN_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert (ended["land"]["recipe"], ended["land"]["fell_back"]) == ("steep", True)
        receipt = _receipt(client, ended["entry"])
        assert receipt["composer"] == {"key": "city-grammar-town", "version": 2}
        assert "land" not in receipt


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
        # A draft that made no world keeps no sentence: it is forgotten as before (0222).
        assert ended["description"] == "" and _count(client, "world_made_from") == 0
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
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
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
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
    with app() as client:
        registry = client.app.state.services.kind_drafts
        registry.starts_per_hour = 2
        before = _offer(client)
        assert (before["offered"], before["code"], before["detail"]) == (True, None, None)
        assert before["left_usd"] is None  # Nothing short: no figure of what is left is said.
        # The operation sheet includes bounded transport attempts and both native paths.
        assert before["calls_at_most"] == before["operation"]["calls_at_most"]
        assert before["operation"]["estimate_is_expected_spend"] is False
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
        assert (elsewhere["offered"], elsewhere["running_draft_id"]) == (False, None)
        assert elsewhere["code"] == "budget_exceeded"  # Its separate workspace holds no grant.
        transport.release.set()
        assert _ended(client, draft_id)["state"] == "ready"
        after = _offer(client)
        assert (after["offered"], after["running_draft_id"]) == (True, None)
        # The hour's starts used up are said before a word is typed, with when the next frees.
        transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
        _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        spent = _offer(client)
        assert (spent["offered"], spent["code"]) == (False, "kind_draft_limit")
        assert spent["starts"]["left"] == 0 and spent["starts"]["retry_after_seconds"] >= 1
        assert spent["code"] in {code["code"] for code in spent["refusals"]}
        again = _start(client, FARM_WORDS)
        assert (again.status_code, again.json()["code"]) == (429, "kind_draft_limit")


def test_the_offer_says_the_day_a_host_keeps_what_is_made_on_it_until(drafts):
    app, _transport = drafts
    with app() as client:
        assert _offer(client)["host_keeps_until"] is None
    with app(keeps_until=dt.date(2026, 12, 15)) as client:
        assert _offer(client)["host_keeps_until"] == "2026-12-15"
        # Stated whatever else the offer says: to one who may not draft too.
        assert _offer(client, NO_MODEL_TOKEN)["host_keeps_until"] == "2026-12-15"


@pytest.mark.parametrize(
    "stated", ["15/12/2026", "2026-13-01", "2026-12-15T00:00", "20261215", "soon"]
)
def test_a_host_keeps_until_only_a_calendar_date(stated):
    assert _host_keeps_until(None) is None and _host_keeps_until("  ") is None
    assert _host_keeps_until(" 2026-12-15 ") == dt.date(2026, 12, 15)
    with pytest.raises(SocietySettingRefused) as refused:
        _host_keeps_until(stated)
    assert refused.value.code == "host_keeps_until_not_a_date"


def test_a_refused_offer_says_the_same_most_calls_as_the_offered_one(drafts):
    """The most calls a draft can make is said the same way whether the offer is open or refused,
    so a page never tells one person "up to 9 times" and another "up to 16" for the same draft."""
    app, transport = drafts
    with app() as client:
        offered = _offer(client)
        assert offered["offered"] is True
        expected = offered["operation"]["calls_at_most"]
        assert offered["calls_at_most"] == expected
        for token in (NO_MODEL_TOKEN, OTHER_TOKEN):
            refused = _offer(client, token)
            assert refused["offered"] is False and refused["operation"] is None
            assert refused["calls_at_most"] == expected, refused["code"]
    assert transport.requests == []


def test_with_no_model_on_the_server_the_most_calls_are_as_its_own_client_would_make():
    """With no client, each model of a role's chain is counted once, as the server's own client
    (one attempt a model) asks it."""
    server_client = ModelClient(
        api_key={provider: "test-not-a-key" for provider in load_manifest().providers},
        transport=FakeTransport(),
    )
    assert world_making.calls_at_most(None) == world_making.calls_at_most(server_client)


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
        # Said first and to everybody, as the kinds library says it: also to one who may not draft.
        assert _offer(client, NO_MODEL_TOKEN)["code"] == "kinds_from_people_not_offered"
        assert _count(client, "world_identity") == 0
    assert not transport.arrived.is_set()
    assert transport.requests == []


def test_a_workspace_at_its_world_limit_is_told_before_any_model_is_asked(
    drafts, fixed_identities, monkeypatch
):
    app, transport = drafts
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
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


def _made_one_town(client: TestClient, transport: Any) -> int:
    """Make one small town through the route and answer the tiles it came to, which the day's
    tile budget now counts."""
    transport.responses.extend([_tool("town", "a quiet town"), _json(_town_form()), *_plain()])
    ended = _ended(client, _start(client, TOWN_WORDS).json()["draft_id"])
    assert ended["state"] == "ready", ended
    return len(_receipt(client, ended["entry"])["tiles"])


def test_a_town_draft_on_a_day_with_no_tile_left_is_refused_before_its_drafter_is_asked(
    drafts, fixed_identities, monkeypatch
):
    """Nobody pays for a town that cannot be made today: once the tool chooser picks the town, a
    day whose tiles are all spent refuses the draft by the budget's own name, with no draft of
    the town asked for and nothing made."""
    app, transport = drafts
    with app() as client:
        spent = _made_one_town(client, transport)
        monkeypatch.setenv("EXULANICA_TILES_A_DAY", str(spent))
        held = _count(client, "world_identity")
        asked = len(transport.requests)
        transport.responses.extend([_tool("town", "a quiet town")])
        ended = _ended(client, _start(client, TOWN_WORDS).json()["draft_id"])
        assert (ended["state"], ended["refusal"]["code"]) == ("refused", "tile_budget_reached")
        assert "as many towns as it may in one day" in ended["refusal"]["detail"]
        # The chooser's call alone: the town's drafter, its look and its setting were not asked.
        assert len(transport.requests) == asked + 1
        assert len(ended["execution"]["calls"]) == 1
        assert ended["entry"] is None and ended["made"] == []
        assert _count(client, "world_identity") == held


def test_a_drafted_town_too_large_for_the_tiles_left_today_is_refused_before_its_look_is_chosen(
    drafts, fixed_identities, monkeypatch
):
    """The drafted town's own tiles are asked of the day's budget before its look and setting are
    chosen, so a refusal the making would give costs no more than the draft that found it."""
    app, transport = drafts
    with app() as client:
        spent = _made_one_town(client, transport)
        # One tile left today: a town of any preset takes at least two.
        monkeypatch.setenv("EXULANICA_TILES_A_DAY", str(spent + 1))
        held = _count(client, "world_identity")
        asked = len(transport.requests)
        transport.responses.extend([_tool("town", "a quiet town"), _json(_town_form())])
        ended = _ended(client, _start(client, TOWN_WORDS).json()["draft_id"])
        assert (ended["state"], ended["refusal"]["code"]) == ("refused", "tile_budget_reached")
        assert len(transport.requests) == asked + 2
        assert len(ended["execution"]["calls"]) == 2
        assert ended["entry"] is None and ended["made"] == []
        assert _count(client, "world_identity") == held


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
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
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
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
    with app() as client:
        assert _ended(client, _start(client, FARM_WORDS).json()["draft_id"])["state"] == "ready"
        held = _count(client, "world_identity")
        receipts = _count(client, "world_generation_receipt")
        entries = _count(client, "saved_world_entry")
        monkeypatch.setenv("EXULANICA_WORLDS_HELD", str(held + 1))
        transport.release.clear()
        transport.arrived.clear()
        transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
        draft_id = _start(client, FARM_WORDS).json()["draft_id"]
        assert transport.arrived.wait(10), "the job never asked a model"
        # The limit falls while the model reasons.
        monkeypatch.setenv("EXULANICA_WORLDS_HELD", str(held))
        transport.release.set()
        ended = _ended(client, draft_id)
        assert (ended["state"], ended["refusal"]["code"]) == ("refused", "world_limit_reached")
        assert ended["entry"] is None and ended["made"] == []
        assert len(ended["execution"]["calls"]) == 4
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
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
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
    transport.responses.extend([_brief(_farm()), *_plain()])
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
                ceiling_usd=Decimal("10"),
                max_calls=100,
                valid_until=until,
                operator="test-operator",
                reason="a test workspace's allowance",
            )
        )
    durable = DurableSpending(database, witness, holder=holder_label("world-drafts"))
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
    with app(spending=durable) as client:
        offered = _offer(client)
        assert offered["offered"] is True
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
        calls = ended["execution"]["calls"]
    with database.session(workspace) as connection:
        reservations = connection.execute(
            "select state, grant_id, role, model_id, reserved_usd from spending_reservation "
            "where workspace_id = %s",
            (workspace,),
        ).fetchall()
    # Each attempt is held at its stage model's quoted worst case, never an estimate below it.
    quoted = {
        (stage["role"], model["model_id"]): Decimal(model["reservation_usd"])
        for path in offered["operation"]["paths"]
        for stage in path["stages"]
        for model in stage["models"]
    }
    assert [row["reserved_usd"] for row in reservations] == [
        quoted[row["role"], row["model_id"]] for row in reservations
    ]
    assert len(reservations) == len(calls) == len(transport.requests) == 4
    assert {row["state"] for row in reservations} == {"settled"}
    assert {row["grant_id"] for row in reservations} <= grants
    with database.session(workspace) as connection:
        bound = connection.execute("select bound_id from world_draft_bound").fetchall()
        used = connection.execute("select bound_id from spending_reservation").fetchall()
    assert {row["bound_id"] for row in used} <= {row["bound_id"] for row in bound}


def _durable(spine_schema, tmp_path) -> tuple[Any, Any, Any]:
    """The durable spending a public server runs, its database and its operator, with nothing
    granted yet."""
    from exulanica.spending.ledger import DurableSpending, holder_label
    from exulanica.spending.operator import SpendingOperator
    from exulanica.spending.witness import FileSpendingWitness

    from tests_support_api import scratch_database

    _psycopg, scratch = spine_schema
    database = scratch_database(scratch)
    witness = FileSpendingWitness(tmp_path / "spending-witness", lock_timeout_s=5.0)
    durable = DurableSpending(database, witness, holder=holder_label("world-drafts"))
    return database, SpendingOperator(database, witness), durable


def _grant(operator: Any, ceilings: dict[str, Decimal]) -> None:
    """The owner's workspace granted ``ceilings`` (a figure for each provider) by each provider's
    authority."""
    until = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
    for provider, ceiling in sorted(ceilings.items()):
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
        operator.grant(
            authority,
            _workspace(),
            ceiling_usd=ceiling,
            max_calls=100,
            valid_until=until,
            operator="test-operator",
            reason="a test workspace's small allowance",
        )


def _bounds(database) -> dict[str, Decimal]:
    """Each world draft bound opened in the owner's workspace, by provider: its ceiling."""
    with database.session(_workspace()) as connection:
        rows = connection.execute(
            "select b.provider, g.ceiling_usd from world_draft_bound b "
            "join spending_grant g on g.grant_id = b.bound_id"
        ).fetchall()
    return {row["provider"]: row["ceiling_usd"] for row in rows}


def test_an_allowance_left_below_a_draft_s_most_is_offered_and_bounds_the_draft_at_what_is_left(
    drafts, spine_schema, tmp_path
):
    """A workspace whose allowances have less left than the most one draft may spend, but at least
    one step of it, is offered the draft with what is left (a guest's small allowance): the draft
    holds each step as it is sent, within a bound of what was left, never the whole operation."""
    from exulanica.api.world_draft_offer import read_operation_sheet

    app, transport = drafts
    database, operator, durable = _durable(spine_schema, tmp_path)
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
    with app(spending=durable) as client:
        quoted = read_operation_sheet(client.app.state.services.model_client)
        # Each provider the operation reserves against is granted half its ceiling: more than
        # one step, less than the whole.
        halves = {p["provider"]: Decimal(p["ceiling_usd"]) / 2 for p in quoted["providers"]}
        steps = {p["provider"]: Decimal(p["step_usd_at_most"]) for p in quoted["providers"]}
        assert all(halves[provider] >= steps[provider] for provider in halves)
        _grant(operator, halves)
        offered = _offer(client)
        assert (offered["offered"], offered["code"]) == (True, None)
        # Both figures are served: the most a draft may spend, and what is left for it here.
        assert Decimal(offered["operation"]["maximum_usd"]) == Decimal(quoted["maximum_usd"])
        assert Decimal(offered["left_usd"]) == sum(halves.values())
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
    # Each provider's bound is what its grant had left, not the operation's ceiling for it, and the
    # draft says that is the most it may spend.
    assert _bounds(database) == halves
    assert Decimal(ended["funded_usd"]) == sum(halves.values()) < Decimal(quoted["maximum_usd"])


def test_an_allowance_left_below_one_step_is_refused_before_a_word_with_what_is_left(
    drafts, spine_schema, tmp_path
):
    """Less left than one step of a draft may hold is said by the offer before a word is typed,
    with what is left (N31), and a start is refused before anything is sent or bound."""
    from exulanica.api.world_draft_offer import read_operation_sheet

    app, transport = drafts
    database, operator, durable = _durable(spine_schema, tmp_path)
    with app(spending=durable) as client:
        quoted = read_operation_sheet(client.app.state.services.model_client)
        shorts = {p["provider"]: Decimal(p["step_usd_at_most"]) / 2 for p in quoted["providers"]}
        _grant(operator, shorts)
        short = _offer(client)
        assert (short["offered"], short["code"]) == (False, "world_draft_bound_exceeds_left")
        assert short["code"] in {code["code"] for code in short["refusals"]}
        assert Decimal(short["left_usd"]) == sum(shorts.values())
        refused = _start(client, FARM_WORDS)
        assert (refused.status_code, refused.json()["code"]) == (
            409,
            "world_draft_bound_exceeds_left",
        )
    assert transport.requests == []
    assert _bounds(database) == {}


def test_a_draft_whose_allowance_runs_out_part_way_stops_before_the_step_it_cannot_hold(
    drafts, spine_schema, tmp_path
):
    """A draft holds each step as it is sent: where what is left no longer covers the next step's
    worst case, that step is refused before it is sent, the draft ends saying so with what it spent,
    and nothing is spent past what was left."""
    from exulanica.api.world_draft_offer import read_operation_sheet

    app, transport = drafts
    database, operator, durable = _durable(spine_schema, tmp_path)
    with app(spending=durable) as client:
        quoted = read_operation_sheet(client.app.state.services.model_client)
    steps = {p["provider"]: Decimal(p["step_usd_at_most"]) for p in quoted["providers"]}
    _grant(operator, steps)
    # The tool chooser answers at its worst case (its whole envelope in, its whole answer out), so
    # what is left after it is less than the specification drafter's step.
    chooser = next(
        stage
        for path in quoted["paths"]
        for stage in path["stages"]
        if stage["role"] == str(CHOOSER_ROLE)
    )
    worst = HttpResponse(
        status_code=200,
        text=json.dumps(
            chat_body(
                json.dumps({"tool": "town", "tool_words": ["a quiet town"]}),
                model=CHOOSER,
                prompt_tokens=chooser["request_bytes_at_most"],
                completion_tokens=chooser["answer_tokens_at_most"],
            )
        ),
    )
    transport.responses.extend([worst, _json(_town_form()), *_plain()])
    with app(spending=durable) as client:
        assert _offer(client)["offered"] is True
        ended = _ended(client, _start(client, TOWN_WORDS).json()["draft_id"])
    # Refused by the durable authority at the draft's bound, said as a spent allowance.
    assert (ended["state"], ended["refusal"]["code"]) == ("refused", "budget_exceeded")
    # Only the step it could hold was sent; the drafter's was refused before it left.
    assert len(transport.requests) == 1
    with database.session(_workspace()) as connection:
        held = connection.execute(
            "select role, state, settled_usd from spending_reservation where workspace_id = %s",
            (_workspace(),),
        ).fetchall()
    assert [(row["role"], row["state"]) for row in held] == [(str(CHOOSER_ROLE), "settled")]
    assert 0 < held[0]["settled_usd"] <= sum(steps.values())
    # The refusal states the bound's own figures, which the page says it with: what it held, what
    # its steps committed, and the step it could not hold, more than what was left.
    spending = ended["refusal"]["spending"]
    assert (spending["reason"], spending["scope"], spending["detail"]) == (
        "spending_limit_reached",
        "workspace",
        "usd",
    )
    assert Decimal(spending["limit"]) == sum(steps.values())
    assert Decimal(spending["committed"]) == held[0]["settled_usd"]
    assert Decimal(spending["requested"]) > Decimal(spending["limit"]) - held[0]["settled_usd"]
    # The draft says what it spent: its calls add up to what was settled, nothing past it.
    calls = ended["execution"]["calls"]
    assert sum(Decimal(str(call["usd"] or 0)) for call in calls) == held[0]["settled_usd"]


def test_a_start_stopped_before_its_bounds_opened_is_funded_on_recovery_as_it_stored(
    drafts, spine_schema, tmp_path, monkeypatch
):
    """A start whose process stopped after it was stored and before its bounds were opened is
    funded on recovery with the bounds its definition stored, what its grants had left at its
    start: never the operation's ceilings, which those grants could not open."""
    from exulanica.api.world_draft_offer import read_operation_sheet
    from exulanica.world.world_draft_jobs import WorldDraftRepository

    app, transport = drafts
    database, operator, durable = _durable(spine_schema, tmp_path)
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
    with app(spending=durable) as client:
        quoted = read_operation_sheet(client.app.state.services.model_client)
        halves = {p["provider"]: Decimal(p["ceiling_usd"]) / 2 for p in quoted["providers"]}
        _grant(operator, halves)
        # The start is stored and its process stops: no bound opened, nothing queued to run.
        enqueue = WorldDraftRepository.enqueue
        monkeypatch.setattr(world_making_routes, "funding_of", lambda _definition: [])
        monkeypatch.setattr(WorldDraftRepository, "enqueue", lambda *_: None)
        started = _start(client, FARM_WORDS)
        assert started.status_code == 202, started.text
        assert transport.requests == []
        # The worker recovers it.
        monkeypatch.setattr(WorldDraftRepository, "enqueue", enqueue)
        client.app.state.world_draft_worker.notify(_workspace())
        ended = _ended(client, started.json()["draft_id"])
        assert ended["state"] == "ready", ended
    assert _bounds(database) == halves


def test_what_is_left_for_a_draft_counts_each_provider_at_most_its_ceiling():
    """A provider with more left than its ceiling does not cover another that is short (N31, AUDIT's
    O1): each provider's grant counts at most what the draft could reserve against it, so the offer
    says the draft is short wherever one of its providers is, however much another has left."""
    from types import SimpleNamespace

    from exulanica.api.routes.world_making import _left_by_provider, _short_of_a_step

    quote = {
        "maximum_usd": "2",
        "providers": [
            {"provider": "plenty", "ceiling_usd": "1", "step_usd_at_most": "0.3"},
            {"provider": "short", "ceiling_usd": "1", "step_usd_at_most": "0.3"},
        ],
    }
    figures = SimpleNamespace(available_usd={"plenty": Decimal("5"), "short": Decimal("0.2")})
    services = SimpleNamespace(spending_refusals=lambda _connection, _workspace: figures)
    lefts = _left_by_provider(services, None, uuid.uuid4(), quote)
    assert lefts == {"plenty": Decimal("1"), "short": Decimal("0.2")}
    # One provider below its step: no draft could send that provider's step.
    assert _short_of_a_step(quote, lefts)
    # Every provider at a step or more: offered, whatever is short of the whole.
    figures.available_usd["short"] = Decimal("0.5")
    lefts = _left_by_provider(services, None, uuid.uuid4(), quote)
    assert not _short_of_a_step(quote, lefts) and sum(lefts.values()) == Decimal("1.5")
    # A quote priced before steps were stated needs each provider's whole ceiling.
    old = {
        "providers": [
            {k: v for k, v in p.items() if k != "step_usd_at_most"} for p in quote["providers"]
        ]
    }
    assert _short_of_a_step(old, lefts)


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
            moment = "2026-01-01T00:01:00Z" if key == "expires_at" else "2026-01-01T00:00:00Z"
            return _MOMENT.sub(moment, value)
        if key in {"elapsed_seconds", "latency_ms"}:
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
        transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
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
                *_plain(),
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


def _wears(client: TestClient, entry: dict[str, Any]) -> tuple[str | None, list[dict[str, str]]]:
    """The look the world's appearance names and the named parts of its setting, read from the
    world's own current appearance."""
    database = client.app.state.services.database
    workspace = _workspace()
    with database.session(workspace) as connection:
        pack = WorldStyleRepository(connection, workspace, world_id=entry["world_id"]).current()
    binding = pack.style_pack
    if binding is None:
        return None, []
    setting = [] if binding.setting is None else json.loads(binding.setting)["parts"]
    return binding.pack_id, setting


TOON = "exulanica.toon-town"


def test_what_the_words_ask_for_is_taken_said_in_their_words_and_worn_by_the_world(
    drafts, fixed_identities
):
    """The look and the setting are taken, not offered: the draft says each with the person's own
    words, and the made world's appearance names them, for a place and a town alike."""
    app, transport = drafts
    words = FARM_WORDS + ", at dusk by the sea, drawn like a cartoon"
    transport.responses.extend(
        [
            _tool("place", "a small farm"),
            _brief(_farm()),
            _look(TOON, "drawn like a cartoon"),
            _setting("at dusk", "by the sea", sky="dusk", ground="sea"),
        ]
    )
    with app() as client:
        ended = _ended(client, _start(client, words).json()["draft_id"])
        assert ended["state"] == "ready", ended
        titles = {pack.pack_id: pack.title for pack in style_pack_library().packs}
        assert ended["look"] == {
            "pack_id": TOON,
            "title": titles[TOON],
            "words": ["drawn like a cartoon"],
        }
        named = {(part["axis"], part["key"]): part["title"] for part in setting_parts().listed()}
        assert ended["setting"] == {
            "parts": [
                {"axis": "sky", "key": "dusk", "title": named[("sky", "dusk")]},
                {"axis": "ground", "key": "sea", "title": named[("ground", "sea")]},
            ],
            "words": ["at dusk", "by the sea"],
        }
        assert _wears(client, ended["entry"]) == (
            TOON,
            [{"axis": "sky", "key": "dusk"}, {"axis": "ground", "key": "sea"}],
        )
        # A town the same way.
        town_words = TOWN_WORDS + " under an overcast sky"
        transport.responses.extend(
            [
                _tool("town", "a quiet town"),
                _json(_town_form()),
                _look(None),
                _setting("overcast sky", sky="overcast"),
            ]
        )
        town = _ended(client, _start(client, town_words).json()["draft_id"])
        assert town["state"] == "ready", town
        assert town["look"] is None
        assert [part["key"] for part in town["setting"]["parts"]] == ["overcast"]
        default = style_pack_library().default_pack.pack_id
        assert _wears(client, town["entry"]) == (default, [{"axis": "sky", "key": "overcast"}])


def test_the_look_step_is_offered_only_the_looks_it_was_measured_with(drafts, fixed_identities):
    """The library may hold a look the step never saw in a recorded run; the job offers it only
    the ones the library file lists, as the town's draft route does."""
    library = style_pack_library()
    listed = set(library.chooser_offers)
    others = {pack.pack_id for pack in library.packs} - listed
    assert listed and others, "the library offers the step some of its looks and holds another"
    app, transport = drafts
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
    with app() as client:
        assert _ended(client, _start(client, FARM_WORDS).json()["draft_id"])["state"] == "ready"
    asked = [
        json.dumps(request["payload"]["messages"])
        for request in transport.requests
        if "The looks:" in json.dumps(request["payload"]["messages"])
    ]
    assert len(asked) == 1
    assert all(pack_id in asked[0] for pack_id in listed)
    assert not any(pack_id in asked[0] for pack_id in others)


def test_words_that_ask_for_nothing_make_a_world_in_the_default_look_with_no_setting(
    drafts, fixed_identities
):
    app, transport = drafts
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
    with app() as client:
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert (ended["state"], ended["look"], ended["setting"]) == ("ready", None, None)
        # Made already wearing a look, so a later change of the default restyles no made world.
        assert _wears(client, ended["entry"]) == (style_pack_library().default_pack.pack_id, [])


def test_one_phrase_carries_no_three_parts(drafts, fixed_identities):
    """The answer the setting step gave a farm with wheat fields when it was measured on places
    (night, wheat fields and snow, on the one phrase "wheat fields"): the job takes none of it,
    since a part invented is worse than a part missed."""
    assert world_making.guarded(None, (), {"sky": "night", "ground": "wheat_fields"}, [(3, 9)]) == (
        None,
        {},
    )
    app, transport = drafts
    words = "a farm with a farmhouse, two barns, wheat fields and a duck pond"
    transport.responses.extend(
        [
            _tool("place", "a farm"),
            _brief(_farm()),
            _look(None),
            _setting("wheat fields", sky="night", ground="wheat_fields", cover="snow"),
        ]
    )
    with app() as client:
        ended = _ended(client, _start(client, words).json()["draft_id"])
        assert (ended["state"], ended["setting"]) == ("ready", None)
        assert _wears(client, ended["entry"])[1] == []


def test_weather_words_ask_for_a_sky_and_never_for_a_look(drafts, fixed_identities):
    """The look step took a look on "at dusk" when it was measured; the same words chose the
    sky, so the job takes the sky and no look. Words of their own still choose a look."""
    assert world_making.guarded("a.look", [(10, 17)], {"sky": "dusk"}, [(10, 17)]) == (
        None,
        {"sky": "dusk"},
    )
    assert world_making.guarded("a.look", [(20, 30)], {"sky": "dusk"}, [(10, 17)]) == (
        "a.look",
        {"sky": "dusk"},
    )
    assert world_making.guarded("a.look", [(20, 30)], {}, ()) == ("a.look", {})
    app, transport = drafts
    transport.responses.extend(
        [
            _tool("place", "a small farm"),
            _brief(_farm()),
            _look("exulanica.cozy-town", "at dusk"),
            _setting("at dusk", sky="dusk"),
        ]
    )
    with app() as client:
        ended = _ended(client, _start(client, FARM_WORDS + ", at dusk").json()["draft_id"])
        assert (ended["state"], ended["look"]) == ("ready", None)
        assert [part["key"] for part in ended["setting"]["parts"]] == ["dusk"]


def test_a_step_that_fails_takes_nothing_and_the_world_is_made_all_the_same(
    drafts, fixed_identities
):
    app, transport = drafts
    transport.responses.extend(
        [
            _tool("place", "a small farm"),
            _brief(_farm()),
            HttpResponse(status_code=500, text="the provider failed"),
            HttpResponse(status_code=500, text="the provider failed"),
        ]
    )
    with app() as client:
        ended = _ended(client, _start(client, FARM_WORDS + ", at dusk").json()["draft_id"])
        assert (ended["state"], ended["look"], ended["setting"]) == ("ready", None, None)
        assert ended["entry"]["generated_site"] is not None


def test_a_phrase_the_setting_took_is_not_also_said_to_be_left_out(drafts, fixed_identities):
    """A town's drafter names what no value says; the setting step takes some of the same words.
    What was taken is said by the setting, so it is not then listed as not in the world."""
    app, transport = drafts
    words = TOWN_WORDS + " on the slopes, with snow on the roofs"
    transport.responses.extend(
        [
            _tool("town", "a quiet town"),
            _json(_town_form(fit="part", not_supported=["on the slopes", "snow on the roofs"])),
            _look(None),
            _setting("snow on the roofs", cover="snow"),
        ]
    )
    with app() as client:
        ended = _ended(client, _start(client, words).json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert ended["setting"]["words"] == ["snow on the roofs"]
        assert ended["left_out"] == ["on the slopes"]


def test_a_worker_busy_for_a_moment_is_asked_once_more_before_a_paid_draft_is_lost(
    drafts, fixed_identities, monkeypatch
):
    from exulanica.world.kinds import worker

    app, transport = drafts
    composed = worker.WorkerComposer.__call__
    asked = []

    def busy_once(self: Any, *args: Any, **kwargs: Any) -> Any:
        asked.append(1)
        if len(asked) == 1:
            raise worker.KindWorkWaiting("busy")
        return composed(self, *args, **kwargs)

    monkeypatch.setattr(worker.WorkerComposer, "__call__", busy_once)
    transport.responses.extend([_tool("place", "a small farm"), _brief(_farm()), *_plain()])
    with app() as client:
        ended = _ended(client, _start(client, FARM_WORDS).json()["draft_id"])
        assert ended["state"] == "ready", ended
        assert len(asked) >= 2
