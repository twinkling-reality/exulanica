"""A world generated from a recipe: made through the API, saved, and read back through its receipt.

The small town is a preset of two tiles. These tests make it through ``POST /worlds/generated`` as
a person's browser would, and hold what the server writes: a ``generated`` world, the receipt its
snapshot names, the saved entry that declares what the page draws, and one bake job per tile. The
tests of one tile's bake job make their world from version 1's small town, one tile of city grammar
version 3, which the catalog keeps for the worlds made from it.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import hashlib
import itertools
import json
import math
import pathlib
import re
import uuid
from collections import OrderedDict
from types import MappingProxyType

import psycopg
import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.grammars.city.common import TILE_SIZE_MM
from exulanica.grammar.grammars.city.streets import StreetSegmentRecord
from exulanica.ingest import generated_tiles as bake_worker
from exulanica.ingest.generated_tiles import MAXIMUM_CLAIMS, GeneratedTileBaker
from exulanica.ingest.stages import STAGES
from exulanica.store.namespaces import tile_store
from exulanica.world import generated_worlds as generated_worlds_module
from exulanica.world import society_authored_ground as ground_builder
from exulanica.world import society_grounds
from exulanica.world import society_walking_surfaces as walking_surfaces_module
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.baked_tiles import BakedTileRepository
from exulanica.world.composers import (
    GeneratedWorldRefused,
    composer_module,
    seed_candidate,
)
from exulanica.world.composers import city_grammar_town as town_composer
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import (
    BAKE_JOB_KIND,
    compose_generated_world,
    generation_receipt,
    town_records,
)
from exulanica.world.society_authored_ground import authored_ground_from_snapshot
from exulanica.world.society_city_place import place_from_city_records
from exulanica.world.society_engines import CREATES
from exulanica.world.society_living import current_routine
from exulanica.world.society_place import seal_place
from exulanica.world.world_recipes import (
    CANDIDATES_MAXIMUM,
    CATALOG_DIRECTORY,
    TILES_MAXIMUM,
    load_world_recipes,
    world_recipe,
)
from exulanica.world.worlds import GENERATED, WORLD_COUNT_POLICY, workspace_worlds
from psycopg.types.json import Jsonb

from baked_tile_stages import stated_stage
from personal_world_support import STRANGER_TOKEN
from pg_harness import open_scratch_connection
from test_society_made_world import made as imported_made  # noqa: F401
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

pytestmark = pytest.mark.postgres

#: The engine a new society over a saved world is created with, the engine table's own choice.
PURPOSEFUL = CREATES["saved_world"]


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


@pytest.fixture(name="made")
def _made_alias(request):
    """The application as a deployment runs it: the runtime role, under row-level security, with
    the society runtime every instance builds."""
    return request.getfixturevalue("imported_made")


def _make(objects_api, recipe: str = "small_town", title: str = "Our town"):
    return objects_api.post("/worlds/generated", {"recipe": recipe, "title": title})


def _town(api, title: str) -> dict:
    """A small town made through the API as the runtime role, asserted made."""
    response = api.post("/worlds/generated", {"recipe": "small_town", "title": title})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(autouse=True)
def _every_town_a_test_makes_is_made(monkeypatch):
    """A test's towns are tried with the catalog's most candidates, not a preset's four.

    Now and then an identity has none of a preset's four candidates generate, and the server then
    refuses the world by name. A run making dozens of towns would meet that as a refusal it did
    not ask for. The seed of each candidate is unchanged, and a test that names a preset's own
    count reads it from the preset it is given."""
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in recipe_catalog.world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


def _version_1(key: str):
    """Version 1's recipe of ``key``: a whole specification file, one tile of city grammar 3."""
    return next(recipe for recipe in load_world_recipes(catalog_version=1) if recipe.key == key)


@pytest.fixture
def one_tile_town(monkeypatch):
    """Worlds made through the API from version 1's small town, one tile, for the tests of one
    tile's bake job; the preset of the same key is two tiles. Its candidates are the catalog's
    most, as every test's are."""
    recipe = dataclasses.replace(_version_1("small_town"), candidates=CANDIDATES_MAXIMUM)
    monkeypatch.setattr(recipe_catalog, "town_recipe", lambda key, values=None: recipe)
    return recipe


def _society_input(api, entry) -> dict:
    """The first input of the society over a saved entry's version, as the runtime role reads it."""
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select i.document from world_society_input i join world_society s on "
            "s.workspace_id=i.workspace_id and s.society_id=i.society_id where "
            "s.workspace_id=%s and s.world_id=%s and s.version_id=%s and i.input_seq=1",
            (api.repository.workspace_id, entry["world_id"], entry["authored_version_id"]),
        ).fetchone()["document"]


def test_a_recipe_makes_a_generated_world_with_its_receipt_entry_and_bakes(objects_api, repository):
    response = _make(objects_api)
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["source_kind"] == "generated"
    assert entry["world_id"].startswith("world:generated:")
    ground = entry["generated_ground"]
    assert ground["recipe_key"] == "small_town"
    assert ground["region_id"] == "region:generated"
    tiles = world_recipe("small_town").tiles
    assert [tile["state"] for tile in ground["tiles"]] == ["baking"] * len(tiles)
    connection, workspace = repository.connection, repository.workspace_id
    kinds = {world.world_id: world.kind for world in workspace_worlds(connection, workspace)}
    assert kinds[entry["world_id"]] == GENERATED
    digest, receipt = generation_receipt(
        connection, workspace, entry["world_id"], uuid.UUID(entry["source_snapshot_id"])
    )
    assert receipt["recipe"]["key"] == "small_town"
    assert receipt["world_id"] == entry["world_id"]
    generated = town_records(
        connection, workspace, entry["world_id"], uuid.UUID(entry["source_snapshot_id"])
    )
    assert generated.receipt_sha256 == digest
    assert len(generated.records) == receipt["record_count"]
    jobs = connection.execute(
        "select payload from job where workspace_id=%s and kind=%s",
        (workspace, BAKE_JOB_KIND),
    ).fetchall()
    assert sorted(job["payload"]["tile"] for job in jobs) == sorted(receipt["tiles"])
    assert receipt["tiles"] == [list(tile) for tile in tiles]


def test_a_saved_generated_world_states_every_value_it_was_made_with_and_no_other_world_does(
    made, monkeypatch
):
    """A generated world's entry states its schema and every adjustable value it was made with:
    the preset's, read here from the catalog file itself, with the values asked for in their
    place. Both routes say the same; an authored world, a world of a version 1 recipe and another
    workspace's world state none."""
    api = made
    starter = api.post("/world-entries/starter", {"title": "My world"})
    assert starter.status_code == 200, starter.text
    catalog = json.loads(
        CATALOG_DIRECTORY.joinpath(
            f"world-recipe.v{recipe_catalog.CATALOG_VERSION}.json"
        ).read_text()
    )
    preset = next(entry for entry in catalog["entries"] if entry["key"] == "small_town")
    asked = {"typology_weight_rowhouse_permille": 900, "ground_floor_use_weight_cafe_permille": 800}
    assert all(preset["values"][key] != value for key, value in asked.items())
    response = api.post(
        "/worlds/generated", {"recipe": "small_town", "title": "Asked", "values": asked}
    )
    assert response.status_code == 201, response.text
    tweaked = response.json()
    plain = _town(api, "Plain")
    listed = {row["entry_id"]: row for row in api.get("/world-entries").json()}
    for town, expected in ((tweaked, {**preset["values"], **asked}), (plain, preset["values"])):
        for ground in (
            api.entry(town["entry_id"])["generated_ground"],
            listed[town["entry_id"]]["generated_ground"],
        ):
            assert ground["specification"] == preset["specification"]
            assert ground["values"] == expected
            assert list(ground["values"]) == sorted(expected)
        # A stranger is told the world does not exist, and lists none of it.
        assert (
            api.get(f"/world-entries/{town['entry_id']}", token=STRANGER_TOKEN).status_code == 404
        )
    strangers = api.get("/world-entries", token=STRANGER_TOKEN)
    assert strangers.status_code == 200, strangers.text
    assert not {row["entry_id"] for row in strangers.json()} & {
        tweaked["entry_id"],
        plain["entry_id"],
    }
    assert listed[starter.json()["entry_id"]]["generated_ground"] is None
    # Version 1's recipe named a whole specification file and recorded no values: its world is
    # drawn as before and states neither.
    recipe = dataclasses.replace(_version_1("small_town"), candidates=CANDIDATES_MAXIMUM)
    monkeypatch.setattr(recipe_catalog, "town_recipe", lambda key, values=None: recipe)
    old = api.entry(_town(api, "Old")["entry_id"])["generated_ground"]
    assert old["recipe_key"] == "small_town" and old["tiles"]
    assert (old["specification"], old["values"]) == (None, None)


def test_a_town_s_people_are_its_residents_walking_its_own_surfaces(made):
    api = made
    response = api.post("/worlds/generated", {"recipe": "small_town", "title": "Our town"})
    assert response.status_code == 201, response.text
    entry = response.json()
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(society, {"region_id": "region:generated", "profile": PURPOSEFUL})
    assert created.status_code in (200, 201), created.text
    body = created.json()
    document = _society_input(api, entry)
    assert document["profile"] == "exulanica.society-input/walking-surfaces-v1"
    assert document["navigation"]["profile"] == "city-walking-surfaces/v1"
    assert document["population"]["rule"] == "residents"
    # One person per place in a home the town's premises offer, and every one of them is here.
    residents = document["population"]["size"]
    assert residents > 0
    assert body["population_size"] == residents
    assert len(body["state"]["inhabitants"]) == residents
    # Where a person arrives is the spawn the town's snapshot states, derived when it was made.
    arrival = entry["generated_ground"]["arrival_mm"]
    assert document["navigation"]["arrival_mm"] == [arrival[0], arrival[2]]
    # The town's premises and benches are what people do: each target is one of its own records.
    assert document["targets"]
    assert {target["origin"] for target in document["targets"]} <= {"premises", "furniture"}


def test_an_unknown_recipe_is_refused_by_name_and_nothing_is_written(objects_api, repository):
    before = workspace_worlds(repository.connection, repository.workspace_id)
    response = _make(objects_api, recipe="a_recipe_nobody_states")
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "unknown_world_recipe"
    assert "a_recipe_nobody_states" in response.json()["detail"]
    assert workspace_worlds(repository.connection, repository.workspace_id) == before


def test_a_title_empty_once_trimmed_is_refused_by_name_and_nothing_is_written(
    objects_api, repository
):
    """A title of only spaces is refused with the code a saved entry's edit answers it with."""
    before = workspace_worlds(repository.connection, repository.workspace_id)
    response = _make(objects_api, title="   ")
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_saved_world_entry"
    assert workspace_worlds(repository.connection, repository.workspace_id) == before


def test_a_recipe_of_a_grammar_version_its_composer_does_not_generate_is_refused_by_name(
    objects_api, repository, monkeypatch
):
    """A composer generates the city grammar versions it states, each with that version's own
    catalogs; a recipe naming another version is refused by name before anything is written."""
    monkeypatch.setattr(town_composer, "GRAMMAR_VERSIONS", ())
    before = workspace_worlds(repository.connection, repository.workspace_id)
    response = _make(objects_api)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "unknown_world_composer"
    version = world_recipe("small_town").specification["grammar_version"]
    assert f"recipe small_town names version {version}" in response.json()["detail"]
    assert workspace_worlds(repository.connection, repository.workspace_id) == before


def test_a_workspace_holds_at_most_the_policy_s_generated_worlds(objects_api, monkeypatch):
    # A deployment states its own figure, three here; the policy's 24 is a figure, not a rule.
    monkeypatch.setenv("EXULANICA_WORLDS_HELD", "3")
    limit = WORLD_COUNT_POLICY.limit(GENERATED)
    assert limit == 3
    made = [_make(objects_api, title=f"Town {n}") for n in range(limit)]
    assert [response.status_code for response in made] == [201] * limit
    # A workspace at its limit is refused before any world is generated for it.
    composed = []
    compose = generated_worlds_module.compose_generated_world
    monkeypatch.setattr(
        generated_worlds_module,
        "compose_generated_world",
        lambda recipe, world_id: composed.append(world_id) or compose(recipe, world_id),
    )
    refused = _make(objects_api, title="One too many")
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "world_limit_reached"
    assert composed == []


def test_a_workspace_s_towns_come_to_at_most_the_day_s_tiles_and_it_is_told_when_room_returns(
    objects_api, repository, monkeypatch
):
    """The cost the count of three stood for has its own bound: the tiles of the worlds a
    workspace made in the last day. Past it a making is refused before anything is generated, by
    name, with the instant room returns: a day after the oldest of those worlds was made."""
    import datetime as dt

    from exulanica.world.world_recipes import town_recipe

    tiles = len(town_recipe("small_town", None).tiles)
    monkeypatch.setenv("EXULANICA_TILES_A_DAY", str(2 * tiles))
    made = [_make(objects_api, title=f"Town {n}") for n in range(2)]
    assert [response.status_code for response in made] == [201, 201]
    composed = []
    compose = generated_worlds_module.compose_generated_world
    monkeypatch.setattr(
        generated_worlds_module,
        "compose_generated_world",
        lambda recipe, world_id: composed.append(world_id) or compose(recipe, world_id),
    )
    refused = _make(objects_api, title="One too many today")
    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert body["code"] == "tile_budget_reached"
    assert "has made as many towns as it may in one day" in body["detail"]
    assert composed == []
    # Room returns a day after the oldest of those worlds was made: said in the words, and given
    # as an instant for a page to say in the person's own time.
    worlds = workspace_worlds(repository.connection, repository.workspace_id)
    oldest = min(world.created_at for world in worlds if world.kind == GENERATED)
    returns = (oldest + dt.timedelta(days=1)).astimezone(dt.UTC)
    assert f"from {returns:%H:%M} UTC on {returns.day} {returns:%B}" in body["detail"]
    assert dt.datetime.fromisoformat(body["returns_at"]) == returns
    # The worlds held are still under their own bound: it is the day's tiles that refused.
    assert len(worlds) < WORLD_COUNT_POLICY.limit(GENERATED)
    # A deployment that states more has room at once.
    monkeypatch.setenv("EXULANICA_TILES_A_DAY", str(3 * tiles))
    monkeypatch.setattr(generated_worlds_module, "compose_generated_world", compose)
    assert _make(objects_api, title="Room again").status_code == 201


def test_a_guest_s_workspace_is_held_to_a_guest_s_figures(repository, monkeypatch):
    """A guest's workspace has budgets of its own: the repository a guest's request is given
    reads them, and the same workspace asked as a person's is not refused by them."""
    from exulanica.world.saved_entries import SavedWorldEntryRepository
    from exulanica.world.worlds import TileBudgetReached, WorldLimitReached

    connection, workspace = repository.connection, repository.workspace_id
    actor = uuid.uuid4()
    guests = SavedWorldEntryRepository(connection, workspace, guest=True)
    persons = SavedWorldEntryRepository(connection, workspace)
    monkeypatch.setenv("EXULANICA_GUEST_WORLDS_HELD", "1")
    first = guests.create_generated(
        title="A guest's town", recipe_key="small_town", created_by=actor
    )
    with pytest.raises(WorldLimitReached) as held:
        guests.create_generated(title="A second", recipe_key="small_town", created_by=actor)
    assert (held.value.code, held.value.limit) == ("world_limit_reached", 1)
    # The day's tiles, a guest's figure: one two-tile town is all of it.
    monkeypatch.setenv("EXULANICA_GUEST_WORLDS_HELD", "5")
    monkeypatch.setenv("EXULANICA_GUEST_TILES_A_DAY", "2")
    with pytest.raises(TileBudgetReached) as spent:
        guests.create_generated(title="A second", recipe_key="small_town", created_by=actor)
    assert (spent.value.code, spent.value.limit, spent.value.asked) == ("tile_budget_reached", 2, 2)
    # Neither figure is a signed-in person's: the same workspace asked as theirs makes the town.
    second = persons.create_generated(title="A person's", recipe_key="small_town", created_by=actor)
    assert first.world_id != second.world_id


def test_each_world_of_a_recipe_draws_its_own_seed_and_one_world_always_the_same():
    recipe = world_recipe("small_town")
    first = compose_generated_world(recipe, "world:generated:first")
    again = compose_generated_world(recipe, "world:generated:first")
    other = compose_generated_world(recipe, "world:generated:second")
    assert first.receipt == again.receipt and first.receipt_sha256 == again.receipt_sha256
    assert first.receipt["seed"] != other.receipt["seed"]
    kept = first.receipt["candidate"]
    assert first.receipt["seed"] == seed_candidate(recipe, "world:generated:first", kept)
    assert [r["candidate"] for r in first.receipt["refused_candidates"]] == list(range(kept))
    assert first.receipt["output_digest"] != other.receipt["output_digest"]


def test_a_recipe_none_of_whose_candidates_generate_is_refused_with_every_refusal(monkeypatch):
    """Blocks a 140 m long cannot fit a one-tile district (measured: 0 of 16 seeds), so every
    candidate is refused by the grammar, and the world is refused with each one's sentence."""
    recipe = _version_1("small_town")
    specification = copy.deepcopy(recipe.specification)
    specification["bindings"][0]["values"]["block_length_mm"] = 140_000
    narrow = dataclasses.replace(recipe, specification=specification)
    with pytest.raises(GeneratedWorldRefused) as refused:
        compose_generated_world(narrow, "world:generated:crowded")
    assert [r["candidate"] for r in refused.value.refusals] == list(range(recipe.candidates))
    assert all("too small for a block" in str(r["refusal"]) for r in refused.value.refusals)


def test_a_receipt_is_held_to_the_records_it_generates_and_its_snapshot_to_the_receipt():
    recipe = world_recipe("small_town")
    composed = compose_generated_world(recipe, "world:generated:held")
    module = composer_module(recipe.composer_key, recipe.composer_version)
    assert module.records(composed.receipt) == composed.records
    other = 1 if composed.receipt["candidate"] != 1 else 2
    tampered = {**composed.receipt, "seed": seed_candidate(recipe, "world:generated:held", other)}
    with pytest.raises(InvalidStructuralData, match="generated_world_output_changed"):
        module.records(tampered)
    assert module.receipt_digest_of(composed.candidate.topology) == composed.receipt_sha256
    topology = copy.deepcopy(dict(composed.candidate.topology))
    topology["elements"][0]["streaming_key"] = "builtin:region.generated-tile@1"
    with pytest.raises(InvalidStructuralData, match="names no receipt"):
        module.receipt_digest_of(topology)


def test_a_town_whose_homes_hold_more_than_its_ground_s_bound_starts_no_society(made, monkeypatch):
    stated = society_grounds.society_ground_for_navigation
    monkeypatch.setattr(
        society_grounds,
        "society_ground_for_navigation",
        lambda profile: dataclasses.replace(stated(profile), population=3),
    )
    api = made
    entry = _town(api, "Crowded")
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    refused = api.post(society, {"region_id": "region:generated", "profile": PURPOSEFUL})
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "population_over_tick_budget"
    assert "at most 3" in refused.json()["detail"]


def _stub_tessellator(tmp_path, monkeypatch) -> pathlib.Path:
    """A web directory holding the files the baker checks for, and a bake that writes bytes named
    by the tile document it was given, so a second bake of one document is identical."""
    web = tmp_path / "web"
    for relative in ("packages/loom-tess/src/node/cli.ts", "node_modules/.bin/tsx"):
        (web / relative).parent.mkdir(parents=True, exist_ok=True)
        (web / relative).write_text("")

    def bake(self, document, container):
        data = b"owd:" + hashlib.sha256(document.read_bytes()).digest()
        container.write_bytes(data)
        return {
            "container_sha256": hashlib.sha256(data).hexdigest(),
            "triangle_digests": {"render_batch": "a" * 64, "nav_envelope": "b" * 64},
        }

    monkeypatch.setattr(GeneratedTileBaker, "_bake", bake)
    return web


def _baker(api, store, tmp_path, monkeypatch) -> GeneratedTileBaker:
    """A baker as the worker runs one: claiming as the runtime role, publishing as the owner."""

    @contextlib.contextmanager
    def publisher():
        # The owner connection, the only one migration 0072 lets publish a baked tile.
        yield api.repository.connection
        api.repository.connection.commit()

    return GeneratedTileBaker(
        session=api.database.session,
        publisher=publisher,
        store=store,
        web_directory=_stub_tessellator(tmp_path, monkeypatch),
        worker="test",
    )


def test_a_generated_world_s_tile_is_baked_off_the_request_and_served_only_to_its_world(
    made, tmp_path, monkeypatch
):
    api = made
    store = tile_store(tmp_path / "data")
    api.client.app.state.services = dataclasses.replace(api.client.app.state.services, tiles=store)
    entry = _town(api, "Baked")
    neighbour = _town(api, "Next")
    count = len(world_recipe("small_town").tiles)
    waiting = entry["generated_ground"]["tiles"]
    assert [(one["state"], one["baked_tile_id"]) for one in waiting] == [("baking", None)] * count
    baker = _baker(api, store, tmp_path, monkeypatch)
    outcomes = baker.drain([api.repository.workspace_id])
    assert [(o.status, o.detail) for o in outcomes] == [("baked", "stored then identical")] * (
        2 * count
    )
    assert baker.drain([api.repository.workspace_id]) == []

    tile, *_ = api.entry(entry["entry_id"])["generated_ground"]["tiles"]
    next_tile, *_ = api.entry(neighbour["entry_id"])["generated_ground"]["tiles"]
    assert {
        one["state"]
        for world in (entry, neighbour)
        for one in api.entry(world["entry_id"])["generated_ground"]["tiles"]
    } == {"baked"}
    assert tile["baked_tile_id"] != next_tile["baked_tile_id"]
    # The stored bake is a row of a table no workspace owns, so it does not name the world.
    stored = api.repository.connection.execute(
        "select receipt from baked_tile where baked_tile_id=%s", (tile["baked_tile_id"],)
    ).fetchone()["receipt"]
    assert stored["generated_from"]["recipe"]["key"] == "small_town"
    assert entry["world_id"] not in json.dumps(stored)
    path = (
        f"/world/versions/{entry['authored_version_id']}/tiles/{tile['baked_tile_id']}/bytes"
        f"?world_id={entry['world_id']}"
    )
    served = api.get(path)
    assert served.status_code == 200, served.text
    assert served.headers["content-type"] == "application/vnd.exulanica.owd"
    assert served.headers["etag"] == f'"{hashlib.sha256(served.content).hexdigest()}"'
    # A stranger is told the world does not exist, and a tile this world does not name, even one
    # baked and stored for another world, is refused.
    assert api.get(path, token=STRANGER_TOKEN).status_code == 404
    for other in (next_tile["baked_tile_id"], str(uuid.uuid4())):
        refused = api.get(path.replace(tile["baked_tile_id"], other))
        assert refused.status_code == 404, refused.text
        assert refused.json()["code"] == "unknown_reference"


def test_a_world_is_never_left_being_built_when_a_bake_fails_or_is_stranded(
    made, tmp_path, monkeypatch
):
    """A bake the tessellator refuses ends its job failed; a bake stranded on every claim it may
    have is ended failed by the next drain. Either way the world's entry says its tile failed, which
    the page says instead of waiting for a tile that will never come."""
    api = made
    store = tile_store(tmp_path / "data")
    api.client.app.state.services = dataclasses.replace(api.client.app.state.services, tiles=store)
    workspace = api.repository.workspace_id
    baker = _baker(api, store, tmp_path, monkeypatch)

    def refuse(self, document, container):
        raise RuntimeError(f"the tessellator refused {document.name}: planted")

    monkeypatch.setattr(GeneratedTileBaker, "_bake", refuse)
    refused = _town(api, "Refused")
    count = len(world_recipe("small_town").tiles)
    outcomes = baker.drain([workspace])
    assert len(outcomes) == count
    assert all(outcome.status == "failed" and "planted" in outcome.detail for outcome in outcomes)
    tiles = api.entry(refused["entry_id"])["generated_ground"]["tiles"]
    assert [(tile["state"], tile["baked_tile_id"]) for tile in tiles] == [("failed", None)] * count

    stranded = _town(api, "Stranded")
    owner = api.repository.connection
    owner.execute(
        "update job set state='running', attempts=%s, claimed_by='a worker that died', "
        "claimed_at=now(), claim_token=gen_random_uuid(), "
        "lease_expires_at=now() - interval '1 second' "
        "where workspace_id=%s and kind=%s and state='queued'",
        (MAXIMUM_CLAIMS, workspace, BAKE_JOB_KIND),
    )
    owner.commit()
    tiles = api.entry(stranded["entry_id"])["generated_ground"]["tiles"]
    assert [tile["state"] for tile in tiles] == ["baking"] * count
    ended = baker.drain([workspace])
    failed = ("failed", stranded["world_id"])
    assert [(one.status, one.world_id) for one in ended] == [failed] * count
    assert {one.detail for one in ended} == {
        f"claimed {MAXIMUM_CLAIMS} times and stranded every time"
    }
    tiles = api.entry(stranded["entry_id"])["generated_ground"]["tiles"]
    assert [tile["state"] for tile in tiles] == ["failed"] * count
    assert baker.drain([workspace]) == []


def test_a_receipt_is_append_only_and_a_town_s_population_is_checked_by_the_schema(
    objects_api, repository
):
    """Migration 0118's own guards, read from the schema: the receipt table is forced row secure
    and refuses every update and delete, and the population check admits exactly what the planner
    admits, a rule's name and a whole size from 0 to 512, and only on the walking-surfaces input."""
    entry = _make(objects_api).json()
    connection = repository.connection
    forced = connection.execute(
        "select relrowsecurity, relforcerowsecurity from pg_class "
        "where oid='world_generation_receipt'::regclass"
    ).fetchone()
    assert (forced["relrowsecurity"], forced["relforcerowsecurity"]) == (True, True)
    for statement in (
        "update world_generation_receipt set created_by=created_by where world_id=%s",
        "delete from world_generation_receipt where world_id=%s",
    ):
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
            connection.execute(statement, (entry["world_id"],))
    definition = connection.execute(
        "select pg_get_constraintdef(oid) as sql from pg_constraint "
        "where conname='world_society_input_population_check'"
    ).fetchone()["sql"]
    connection.execute(f"create temp table population_probe (document jsonb, {definition})")

    def admits(document: dict) -> bool:
        try:
            with connection.transaction():
                connection.execute("insert into population_probe values (%s)", (Jsonb(document),))
        except psycopg.errors.CheckViolation:
            return False
        return True

    town = "exulanica.society-input/walking-surfaces-v1"
    assert admits({"profile": town, "population": {"rule": "residents", "size": 42}})
    assert admits({"profile": "exulanica.society-input/authored-v3"})
    # A town records as many people as its homes house: the schema states no most (migration
    # 0191), and nobody is a population an input may record.
    for size in (0, 513, 100_000):
        assert admits({"profile": town, "population": {"rule": "residents", "size": size}}), size
    for population in (
        {"rule": "residents", "size": 2.5},
        {"rule": "", "size": 4},
        {"rule": "residents", "size": -1},
        {"rule": "residents", "size": "513"},
        {"rule": "residents", "size": 4, "note": "more"},
        {"rule": "residents"},
        None,
    ):
        stated = {} if population is None else {"population": population}
        assert not admits({"profile": town, **stated}), population
    assert not admits(
        {
            "profile": "exulanica.society-input/authored-v3",
            "population": {"rule": "residents", "size": 4},
        }
    )


def test_a_generated_world_takes_no_photographs(objects_api, repository):
    """A photograph reaches a world's geometry only through its entry's attachments, so a world
    whose kind is never composed with photographs refuses the attachment by name."""
    entry = _make(objects_api).json()
    # The page offers adding photographs by this served capability of the world's kind.
    assert entry["takes_photographs"] is False
    response = objects_api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments",
        {
            "operation_id": str(uuid.uuid4()),
            "base_revision": entry["revision"],
            "authored_version_id": entry["authored_version_id"],
            "authored_state_sha256": entry["current_authored_state_sha256"],
            "authored_edit_seq": entry["current_authored_edit_seq"],
            "style_version_id": entry["style_version_id"],
            "sources": [{"capture_id": str(uuid.uuid4()), "evidence_span_id": str(uuid.uuid4())}],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "world_takes_no_photographs"


def _to_piece(point: tuple[float, float], a: tuple[int, ...], b: tuple[int, ...]) -> float:
    """How far a plan point lies from a crown line piece, in millimetres."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    along = 0.0 if length == 0 else ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length
    along = min(1.0, max(0.0, along))
    return math.dist(point, (a[0] + dx * along, a[1] + dy * along))


def test_a_person_arrives_on_the_central_standing_spot_facing_the_nearest_street():
    # Composer v1's central-spot rule belongs to the released recipe edition that names it.
    recipe = next(r for r in load_world_recipes(catalog_version=3) if r.key == "small_town")
    composed = compose_generated_world(recipe, "world:generated:arrival")
    arrival = composed.receipt["arrival"]
    place = place_from_city_records(
        place_id="measured", records=list(composed.records), routine=current_routine()
    )
    spots = {spot["spot_id"]: spot["position_mm"] for spot in place["spots"]}
    assert spots[arrival["spot_id"]] == arrival["position_mm"]
    # The central spot: no standing spot is nearer the middle of the tiles the town covers.
    xs = [tile[0] for tile in recipe.tiles]
    ys = [tile[1] for tile in recipe.tiles]
    middle = (
        (min(xs) + max(xs) + 1) * TILE_SIZE_MM / 2,
        (min(ys) + max(ys) + 1) * TILE_SIZE_MM / 2,
    )
    nearest = min(math.dist(position, middle) for position in spots.values())
    assert math.dist(arrival["position_mm"], middle) == nearest
    # The snapshot states the same point as the world's spawn, in the region's frame.
    [spawn] = composed.candidate.placement["destinations"]
    assert (spawn["x_mm"], spawn["z_mm"]) == (arrival["position_mm"][0], -arrival["position_mm"][1])
    # The facing ends on a street's crown line, and no crown line passes nearer the spot.
    pieces = [
        pair
        for record in composed.records
        if isinstance(record, StreetSegmentRecord)
        for pair in itertools.pairwise(record.centreline_mm)
    ]
    here = tuple(arrival["position_mm"])
    end = (here[0] + arrival["facing_mm"][0], here[1] + arrival["facing_mm"][1])
    assert min(_to_piece(end, a, b) for a, b in pieces) <= 1.5
    assert min(_to_piece(here, a, b) for a, b in pieces) >= math.hypot(*arrival["facing_mm"]) - 1.5


def test_a_ground_is_read_by_its_forms_and_forms_with_no_reader_are_refused(monkeypatch):
    """The ground builder picks its reader by the entry's navigation and floor forms, never by
    the entry's name: the town's entry under another name reads the same, and forms no reader
    serves are refused by name."""
    recipe = world_recipe("small_town")
    composed = compose_generated_world(recipe, "world:generated:forms")
    stated = society_grounds.society_ground_for_composer

    def read():
        return authored_ground_from_snapshot(
            world_id="world:generated:forms",
            snapshot_id=uuid.uuid4(),
            snapshot_sha256="ab" * 32,
            composer_key=composed.candidate.composer_key,
            composer_version=composed.candidate.composer_version,
            topology=composed.candidate.topology,
            placement=composed.candidate.placement,
        )

    renamed = dataclasses.replace(stated(recipe.composer_key), key="another_name")
    monkeypatch.setattr(ground_builder, "society_ground_for_composer", lambda key: renamed)
    assert read().navigation_form == "walking_surfaces"
    unread = dataclasses.replace(renamed, navigation="walking_surfaces", floor="declared")
    monkeypatch.setattr(ground_builder, "society_ground_for_composer", lambda key: unread)
    with pytest.raises(InvalidStructuralData, match="no reader is implemented"):
        read()


def test_a_candidate_whose_tile_documents_the_grammar_refuses_is_not_kept():
    """Every world a recipe makes can be baked: a candidate whose records generate but whose tile
    documents fail the grammar's own checks is refused with the grammar's sentence and the next
    candidate is tried. For this identity the first two candidates each place a street tree
    reaching outside its owner's extent, found by composing identities until one did."""
    composed = compose_generated_world(_version_1("small_town"), "world:generated:measured-2")
    refused = composed.receipt["refused_candidates"]
    assert composed.receipt["candidate"] == 2
    assert [r["candidate"] for r in refused] == [0, 1]
    assert all("owner_extent" in str(r["refusal"]) for r in refused)


def _wide_catalog(directory: pathlib.Path, *, tiles: int, extent_x_mm: int) -> pathlib.Path:
    """A recipe catalog of one recipe, ``wide_town``: the small town's specification over
    ``extent_x_mm`` of city from west to east, stating ``tiles`` tiles."""
    specification = copy.deepcopy(world_recipe("small_town").specification)
    specification["bindings"][0]["values"]["city_extent_x_mm"] = extent_x_mm
    directory.joinpath("specifications").mkdir(parents=True)
    directory.joinpath("specifications", "wide-town.v1.json").write_text(json.dumps(specification))
    catalog = json.loads(CATALOG_DIRECTORY.joinpath("world-recipe.v1.json").read_text())
    small = next(entry for entry in catalog["entries"] if entry["key"] == "small_town")
    catalog["entries"] = [
        {
            **small,
            "key": "wide_town",
            "label": "A wide town",
            "specification": "wide-town.v1",
            "tiles": tiles,
            "candidates": CANDIDATES_MAXIMUM,
        }
    ]
    directory.joinpath("world-recipe.v1.json").write_text(json.dumps(catalog))
    return directory


def test_a_recipe_is_read_only_when_the_tiles_it_states_are_the_tiles_it_covers(tmp_path):
    """A recipe states how many tiles its worlds cover, and the catalog is refused by name when its
    specification covers another count or the count is above the most a recipe may state, so no
    world is made whose bakes, entry and page could disagree on its tiles."""
    [wide] = load_world_recipes(
        _wide_catalog(tmp_path / "two", tiles=2, extent_x_mm=2 * TILE_SIZE_MM), catalog_version=1
    )
    assert wide.tiles == ((0, 0), (1, 0))
    with pytest.raises(CatalogError, match=r"states 1 tiles and its specification wide-town\.v1"):
        load_world_recipes(
            _wide_catalog(tmp_path / "one", tiles=1, extent_x_mm=2 * TILE_SIZE_MM),
            catalog_version=1,
        )
    over = TILES_MAXIMUM + 1
    with pytest.raises(CatalogError, match=rf"tiles is an int in \[1, {TILES_MAXIMUM}\]"):
        load_world_recipes(
            _wide_catalog(tmp_path / "over", tiles=over, extent_x_mm=over * TILE_SIZE_MM),
            catalog_version=1,
        )


def test_a_world_of_two_tiles_is_drawn_once_both_are_baked_and_its_people_cross_the_seam(
    made, tmp_path, monkeypatch
):
    """Nothing assumes a world is one tile. The small town covers two, so it queues a bake for
    each, the world's entry says it is being built until both are stored (and the page draws
    nothing until then, ``web/packages/app/test/generated-world.test.ts``), each tile is then
    served through the world, and its people's ground runs across the seam between the two: the
    town's walking graph is its whole city's records, so its premises and paths stand on both
    tiles and an edge crosses the seam."""
    wide = world_recipe("small_town")
    assert wide.tiles == ((0, 0), (1, 0))
    api = made
    store = tile_store(tmp_path / "data")
    api.client.app.state.services = dataclasses.replace(api.client.app.state.services, tiles=store)
    response = api.post("/worlds/generated", {"recipe": wide.key, "title": "Wide"})
    assert response.status_code == 201, response.text
    entry = response.json()
    workspace = api.repository.workspace_id

    def tiles() -> dict[tuple[int, int], dict]:
        ground = api.entry(entry["entry_id"])["generated_ground"]
        return {(tile["tile_x"], tile["tile_y"]): tile for tile in ground["tiles"]}

    assert {key: tile["state"] for key, tile in tiles().items()} == {
        (0, 0): "baking",
        (1, 0): "baking",
    }
    with api.database.session(workspace) as connection:
        jobs = connection.execute(
            "select payload from job where workspace_id=%s and kind=%s", (workspace, BAKE_JOB_KIND)
        ).fetchall()
    assert sorted(job["payload"]["tile"] for job in jobs) == [[0, 0], [1, 0]]

    baker = _baker(api, store, tmp_path, monkeypatch)
    first = baker.bake_one(workspace)
    assert first is not None and first.status == "baked"
    assert sorted(tile["state"] for tile in tiles().values()) == ["baked", "baking"]
    assert [outcome.status for outcome in baker.drain([workspace])] == ["baked"]
    baked = tiles()
    assert [tile["state"] for tile in baked.values()] == ["baked", "baked"]
    assert len({tile["baked_tile_id"] for tile in baked.values()}) == 2
    for tile in baked.values():
        served = api.get(
            f"/world/versions/{entry['authored_version_id']}/tiles/{tile['baked_tile_id']}/bytes"
            f"?world_id={entry['world_id']}"
        )
        assert served.status_code == 200, served.text

    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(society, {"region_id": "region:generated", "profile": PURPOSEFUL})
    assert created.status_code in (200, 201), created.text
    document = _society_input(api, entry)
    assert created.json()["population_size"] == document["population"]["size"] > 0
    west = {
        node["node_id"]: node["position_mm"][0] < TILE_SIZE_MM
        for node in document["navigation"]["nodes"]
    }
    assert set(west.values()) == {True, False}
    assert any(
        west[edge["from_node_id"]] != west[edge["to_node_id"]]
        for edge in document["navigation"]["edges"]
    )
    premises = [target for target in document["targets"] if target["origin"] == "premises"]
    assert {west[target["node_id"]] for target in premises} == {True, False}


@contextlib.contextmanager
def _session_of_the_test(spine_schema):
    """A session of the test's own, in the schema the application under test runs in."""
    psycopg_module, scratch = spine_schema
    session = open_scratch_connection(psycopg_module, scratch)
    try:
        yield session
    finally:
        session.close()


def _a_reader_holds_the_asset_lock(session: psycopg.Connection) -> None:
    """Take the asset read lock as a final read check does, in a transaction left open."""
    session.execute("begin")
    session.execute("select asset_read_lock()")


def _the_reader_is_done(session: psycopg.Connection) -> None:
    session.execute("rollback")


def _asset_lock_held(probe: psycopg.Connection) -> int:
    """How many sessions hold the asset read lock exclusively in this test's database, read from
    ``pg_locks`` by a session of the test's own; the key is read from ``asset_read_lock()``."""
    [source] = probe.execute(
        "select prosrc from pg_proc where proname = 'asset_read_lock' "
        "and pronamespace = current_schema()::regnamespace"
    ).fetchone()
    key = int(source.split("pg_advisory_xact_lock(", 1)[1].split(")", 1)[0])
    [held] = probe.execute(
        "select count(*) from pg_locks where locktype = 'advisory' and classid = 0 "
        "and objid = %s and objsubid = 1 and granted and mode = 'ExclusiveLock' "
        "and database = (select oid from pg_database where datname = current_database())",
        (key,),
    ).fetchone()
    return int(held)


def test_a_publish_refused_while_a_reader_holds_the_asset_lock_is_tried_again(
    made, spine_schema, tmp_path, monkeypatch, one_tile_town
):
    """Migration 0041's guard refuses a baked tile's publish (40001) while any session holds the
    asset read lock, as every final read check does. The worker waits and tries the same write
    again, so a reader's moment never fails a tile."""
    api = made
    store = tile_store(tmp_path / "data")
    api.client.app.state.services = dataclasses.replace(api.client.app.state.services, tiles=store)
    entry = _town(api, "Raced")
    baker = _baker(api, store, tmp_path, monkeypatch)
    waits: list[float] = []
    with _session_of_the_test(spine_schema) as reader:
        _a_reader_holds_the_asset_lock(reader)

        def reader_finishes(seconds: float) -> None:
            waits.append(seconds)
            _the_reader_is_done(reader)

        monkeypatch.setattr(bake_worker, "_pause", reader_finishes)
        [outcome] = baker.drain([api.repository.workspace_id])
    assert (outcome.status, outcome.detail) == ("baked", "stored then identical")
    # Exactly the first publish met the reader's lock, and was tried again once it was gone.
    assert len(waits) == 1
    [tile] = api.entry(entry["entry_id"])["generated_ground"]["tiles"]
    assert tile["state"] == "baked"


def test_a_tile_whose_determinism_check_was_refused_waits_and_is_not_drawn(
    made, spine_schema, tmp_path, monkeypatch, one_tile_town
):
    """A second bake that disagrees with the first is recorded by a write the asset read lock
    guards; an identical one writes nothing. A reader that arrives between the two publishes and
    holds the lock through every try refuses that write, and the job goes back to the queue,
    never to failed. The first bake stays stored as baked, but the tile is not drawn until its
    job is done: the entry says it is still baking and names no bake, and the tile route does not
    serve it. The next claim bakes the tile again, and it is drawn only once both bakes agreed."""
    api = made
    store = tile_store(tmp_path / "data")
    api.client.app.state.services = dataclasses.replace(api.client.app.state.services, tiles=store)
    entry = _town(api, "Waiting")
    workspace = api.repository.workspace_id
    baker = _baker(api, store, tmp_path, monkeypatch)
    monkeypatch.setattr(bake_worker, "_pause", lambda seconds: None)
    stub = GeneratedTileBaker._bake
    bakes: list[str] = []

    def second_bake_disagrees(self, document, container):
        statement = stub(self, document, container)
        bakes.append(container.name)
        if len(bakes) == 2:
            data = container.read_bytes() + b"!"
            container.write_bytes(data)
            statement = {**statement, "container_sha256": hashlib.sha256(data).hexdigest()}
        return statement

    monkeypatch.setattr(GeneratedTileBaker, "_bake", second_bake_disagrees)
    psycopg_module, scratch = spine_schema
    reader = open_scratch_connection(psycopg_module, scratch)
    record = BakedTileRepository.record

    def record_then_a_reader_arrives(self, **fields):
        answer = record(self, **fields)
        if answer == "stored":
            _a_reader_holds_the_asset_lock(reader)
        return answer

    monkeypatch.setattr(BakedTileRepository, "record", record_then_a_reader_arrives)
    try:
        [outcome] = baker.drain([workspace])
        assert outcome.status == "requeued", outcome
        [tile] = api.entry(entry["entry_id"])["generated_ground"]["tiles"]
        assert (tile["state"], tile["baked_tile_id"]) == ("baking", None)
        row = api.repository.connection.execute(
            "select baked_tile_id, state from baked_tile where tile_inputs_digest=%s",
            (bytes.fromhex(tile["tile_inputs_digest"]),),
        ).fetchone()
        # The refused write never marked it: a tile served from this row would be one whose two
        # bakes disagreed.
        stored = row["baked_tile_id"]
        assert row["state"] == "baked"
        path = (
            f"/world/versions/{entry['authored_version_id']}/tiles/{stored}/bytes"
            f"?world_id={entry['world_id']}"
        )
        assert api.get(path).status_code == 404
        with api.database.session(workspace) as connection:
            job = connection.execute(
                "select state, attempts, run_after > now() as later, failure_class from job "
                "where workspace_id=%s and kind=%s",
                (workspace, BAKE_JOB_KIND),
            ).fetchone()
        assert (job["state"], job["attempts"], job["later"], job["failure_class"]) == (
            "queued",
            1,
            True,
            "publish_refused",
        )
    finally:
        _the_reader_is_done(reader)
        reader.close()
    api.repository.connection.execute(
        "update job set run_after=now() where workspace_id=%s and kind=%s",
        (workspace, BAKE_JOB_KIND),
    )
    api.repository.connection.commit()
    [again] = baker.drain([workspace])
    assert (again.status, again.detail) == ("baked", "identical then identical")
    [tile] = api.entry(entry["entry_id"])["generated_ground"]["tiles"]
    assert (tile["state"], tile["baked_tile_id"]) == ("baked", str(stored))
    assert api.get(path).status_code == 200


def test_a_publish_refused_through_every_claim_is_failed_by_name_and_bounded(
    made, spine_schema, tmp_path, monkeypatch, one_tile_town
):
    """A reader that held the lock through every try of every claim is the one lock race a tile
    fails for: after :data:`MAXIMUM_CLAIMS` claims, named ``retry_exhausted``, so a stuck lock
    costs a bounded number of bakes."""
    api = made
    store = tile_store(tmp_path / "data")
    api.client.app.state.services = dataclasses.replace(api.client.app.state.services, tiles=store)
    entry = _town(api, "Held")
    workspace = api.repository.workspace_id
    baker = _baker(api, store, tmp_path, monkeypatch)
    monkeypatch.setattr(bake_worker, "_pause", lambda seconds: None)
    monkeypatch.setattr(bake_worker, "REQUEUE_SECONDS", 0.0)
    # One drain claims the job again at once each time it goes back; past the bound it would
    # claim for ever, so a claim beyond the bound's last is this test's failure, not a hang.
    claimed: list[uuid.UUID] = []
    bake_one = baker.bake_one

    def claim(workspace_id: uuid.UUID):
        claimed.append(workspace_id)
        assert len(claimed) <= MAXIMUM_CLAIMS + 1, "a lock race was claimed past the bound"
        return bake_one(workspace_id)

    monkeypatch.setattr(baker, "bake_one", claim)
    with _session_of_the_test(spine_schema) as reader:
        _a_reader_holds_the_asset_lock(reader)
        outcomes = baker.drain([workspace])
        _the_reader_is_done(reader)
    assert [outcome.status for outcome in outcomes] == ["requeued"] * (MAXIMUM_CLAIMS - 1) + [
        "failed"
    ]
    with api.database.session(workspace) as connection:
        job = connection.execute(
            "select state, attempts, failure_class from job where workspace_id=%s and kind=%s",
            (workspace, BAKE_JOB_KIND),
        ).fetchone()
    assert (job["state"], job["attempts"], job["failure_class"]) == (
        "failed",
        MAXIMUM_CLAIMS,
        "retry_exhausted",
    )
    [tile] = api.entry(entry["entry_id"])["generated_ground"]["tiles"]
    assert tile["state"] == "failed"


def test_a_town_is_generated_before_the_asset_read_lock_and_never_under_it(
    made, spine_schema, monkeypatch
):
    """Every guarded write in the deployment is refused while the asset read lock is held, so a
    society over a town generates the town's records and the place they make before taking it:
    with the records cache cold, neither runs while any session holds the lock."""
    api = made
    entry = _town(api, "Cold")
    monkeypatch.setattr(generated_worlds_module, "_records_kept", OrderedDict())
    with _session_of_the_test(spine_schema) as probe:
        # The probe sees the lock when a session holds it, and not otherwise.
        with _session_of_the_test(spine_schema) as holder:
            _a_reader_holds_the_asset_lock(holder)
            assert _asset_lock_held(probe) == 1
            _the_reader_is_done(holder)
        assert _asset_lock_held(probe) == 0
        calls: list[tuple[str, int]] = []

        def watched(name, original):
            def call(*args, **kwargs):
                calls.append((name, _asset_lock_held(probe)))
                return original(*args, **kwargs)

            return call

        monkeypatch.setattr(town_composer, "records", watched("records", town_composer.records))
        monkeypatch.setattr(
            walking_surfaces_module,
            "place_from_city_records",
            watched("place", walking_surfaces_module.place_from_city_records),
        )
        society = (
            f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
        )
        created = api.post(society, {"region_id": "region:generated", "profile": PURPOSEFUL})
        assert created.status_code in (200, 201), created.text
    assert {name for name, _ in calls} == {"records", "place"}
    assert [call for call in calls if call[1]] == []


def test_the_tessellator_child_is_given_no_database_url_or_credential(tmp_path, monkeypatch):
    """The worker holds the owner's and the runtime role's database URLs; a Node child and every
    web dependency it loads is given only the names the worker allows. A stand-in tessellator
    records the environment it was given."""
    web = tmp_path / "web"
    cli = web / "packages" / "loom-tess" / "src" / "node" / "cli.ts"
    cli.parent.mkdir(parents=True)
    cli.write_text("")
    tsx = web / "node_modules" / ".bin" / "tsx"
    tsx.parent.mkdir(parents=True)
    tsx.write_text(
        "#!/bin/sh\n"
        'env > "$4.environment"\n'
        """printf '{"container_sha256": "0", "triangle_digests": {}}\\n'\n"""
    )
    tsx.chmod(0o755)
    secrets = {
        "EXULANICA_DATABASE_URL": "postgresql://runtime:hidden@db/exulanica",
        "EXULANICA_TILE_PUBLISHER_DATABASE_URL": "postgresql://owner:hidden@db/exulanica",
        "EXULANICA_READONLY_DATABASE_URL": "postgresql://reader:hidden@db/exulanica",
        "PGPASSWORD": "hidden",
        "NEBIUS_API_KEY": "hidden",
        "NODE_AUTH_TOKEN": "hidden",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)
    baker = GeneratedTileBaker(
        session=None,  # type: ignore[arg-type]
        publisher=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        web_directory=web,
        worker="test",
    )
    container = tmp_path / "tile.owd"
    assert baker._bake(tmp_path / "tile.json", container)["container_sha256"] == "0"
    given = dict(
        line.split("=", 1)
        for line in (tmp_path / "tile.owd.environment").read_text().splitlines()
        if "=" in line
    )
    assert "PATH" in given
    assert not set(secrets) & set(given)
    assert not [name for name, value in given.items() if "hidden" in value or "postgres" in value]


def test_a_generated_world_its_grammar_no_longer_generates_is_listed_unavailable_by_name(
    made, monkeypatch
):
    """A town whose receipt no longer generates what it recorded, because the grammar's
    descriptor or its catalogs changed under it, is that one entry's unavailability, named. The
    listing still reads, with every other world as it was."""
    api = made
    starter = api.post("/world-entries/starter", {"title": "My world"})
    assert starter.status_code == 200, starter.text
    town = _town(api, "Moved")
    for patched, value, reason in (
        ("descriptor_sha256", lambda path=None: "0" * 64, "generated_world_grammar_changed"),
        ("catalog_digest", lambda catalogs: "1" * 64, "generated_world_catalogs_changed"),
    ):
        with monkeypatch.context() as moved:
            moved.setattr(town_composer, patched, value)
            listed = api.get("/world-entries")
            assert listed.status_code == 200, listed.text
            entries = {row["entry_id"]: row for row in listed.json()}
            assert (
                entries[town["entry_id"]]["availability"],
                entries[town["entry_id"]]["unavailable_reason"],
                entries[town["entry_id"]]["generated_ground"],
            ) == ("unavailable", reason, None)
            assert entries[starter.json()["entry_id"]]["availability"] == "available"
            one = api.get(f"/world-entries/{town['entry_id']}")
            assert (one.status_code, one.json()["unavailable_reason"]) == (200, reason)
    listed = {row["entry_id"]: row for row in api.get("/world-entries").json()}
    assert listed[town["entry_id"]]["availability"] == "available"


def test_a_tile_names_its_current_bake_when_two_tessellators_baked_it(
    made, tmp_path, monkeypatch, one_tile_town
):
    """A tile document baked by two tessellators has two rows (migration 0077); the entry names
    the current one, the most recently published, not whichever row a plan yields."""
    api = made
    store = tile_store(tmp_path / "data")
    api.client.app.state.services = dataclasses.replace(api.client.app.state.services, tiles=store)
    entry = _town(api, "Rebaked")
    workspace = api.repository.workspace_id
    baker = _baker(api, store, tmp_path, monkeypatch)
    [first] = baker.drain([workspace])
    owner = api.repository.connection
    owner.execute(
        "insert into job (workspace_id, kind, payload) "
        "select workspace_id, kind, payload from job where workspace_id=%s and kind=%s",
        (workspace, BAKE_JOB_KIND),
    )
    owner.commit()
    spec = STAGES["baked_tile"]
    monkeypatch.setitem(
        bake_worker.STAGES, "baked_tile", dataclasses.replace(spec, version=spec.version + 1)
    )
    # A new stage is a schema fact (migration 0144): the migration that comes with it retires the
    # stage the schema states and states the next. Done here as that migration would, and undone
    # after, because the stage table is kept across tests.
    with stated_stage(owner, spec.version + 1, spec.params_digest):
        [second] = baker.drain([workspace])
        assert first.baked_tile_id != second.baked_tile_id
        [tile] = api.entry(entry["entry_id"])["generated_ground"]["tiles"]
        assert (tile["state"], tile["baked_tile_id"]) == ("baked", str(second.baked_tile_id))


def test_a_town_whose_homes_hold_more_than_this_host_runs_is_refused_by_name(made, monkeypatch):
    """A town whose homes hold more people than this host runs a minute of is refused by that name
    where its society is made, and not as a malformed input: an input records a population of any
    size. The town is made first; what a server can run is no part of making one."""
    api = made
    entry = _town(api, "Crowded")
    make_place = walking_surfaces_module.place_from_city_records

    def crowded(**kwargs):
        place = make_place(**kwargs)
        return seal_place(
            {
                **place,
                "destinations": [
                    {**d, "resident_capacity": d.get("resident_capacity", 0) * 100}
                    for d in place["destinations"]
                ],
            }
        )

    monkeypatch.setattr(walking_surfaces_module, "place_from_city_records", crowded)
    monkeypatch.setattr(generated_worlds_module, "_records_kept", OrderedDict())
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    refused = api.post(society, {"region_id": "region:generated", "profile": PURPOSEFUL})
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "people_over_cost"
    detail = refused.json()["detail"]
    # A hundred times the town's own people, past every measured point, against the people the
    # refusal itself says this host runs.
    said = re.fullmatch(
        r"a minute of (\d+) people here takes about (\d+) ms \(an estimate, read past the last "
        r"measured point\), and this server gives a minute 800 ms; it runs about (\d+) people "
        r"\(an estimate, read past the last measured point\) here",
        detail,
    )
    assert said is not None, detail
    people, minute_ms, runs = (int(figure) for figure in said.groups())
    assert people % 100 == 0 and people > runs and minute_ms > 800
