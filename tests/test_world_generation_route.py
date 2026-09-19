"""Asking for a world over HTTP: what it generates, what it refuses, and what it charges.

Everything a request passes through here ships: the permission floor, the token directory, the
workspace-scoped connection as the non-owner runtime role, migration 0062's ceiling and the error
map in :mod:`exulanica.api.app`. Nothing is stubbed and the worlds are real generations from the
registered city grammar.

**These tests are about the CALL SITE.** The cascade's own refusals are held already by
``tests/test_grammar_draw.py``; a guard proved correct in isolation with nothing proving it is
reached has cost this project four separate findings. So every assertion goes through the real
application, and each guard this lane added is falsified by deleting its call and watching a named
test here fail. The falsification log is in the lane's evidence record.

**Two operands, two paths, wherever a number is checked.**
:func:`test_the_catalog_states_the_bounds_the_cascade_actually_enforces` reads a bound off the
catalog route and asks the generation route to bind one past it. Comparing the catalog against the
descriptor it was read from would assert this route's own arithmetic; comparing it against the
refusal asks whether the published number is the enforced one, which is the only version of the
question worth answering.

**The specification here binds eight values and that is not arbitrary.** Seven of them cannot be
left out: measured by removing each in turn from a specification that generates, seven refuse and
the city descriptor declares exactly one of them (``driving_side``) as ``required``.
:func:`test_the_seven_bindings_a_world_cannot_be_asked_for_without` is that measurement, kept as a
test so the gap between what the grammar declares and what it needs is a checked fact rather than a
paragraph. It will fail when a descriptor is fixed, which is when this file should be revisited.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.permissions import ROUTE_RULES, SELF_CHARGING_TILE_ROUTES, Permission
from exulanica.api.quotas import declare_tile_quota
from exulanica.api.routes.world_generation import GENERATED_LOD, WORLD_COVERAGE
from exulanica.api.services import Services
from exulanica.db.roles import provision_runtime_role
from exulanica.db.session import Database
from exulanica.grammar.errors import CatalogError, GrammarError, InvalidSeedError
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from pg_harness import migrated_schema
from test_route_permissions import ALL_PERMISSIONS, APP_ROLE, app_role_dsn

pytestmark = pytest.mark.postgres

WORLDS = "/world-generation/worlds"
GRAMMARS = "/world-generation/grammars"

#: A five by one tile city that GENERATES, measured rather than assumed: every value here is either
#: one of the seven a world cannot be asked for without, or the block depth that keeps the street
#: count inside the six ``local_street`` names the catalog holds. Five tiles, so a charge of five is
#: distinguishable from the one a generic route charges per request.
FIVE_TILES = {
    "driving_side": "right",
    "city_extent_x_mm": 640_000,
    "city_extent_y_mm": 128_000,
    "terrain_relief_mm": 0,
    "gutter_width_mm": 300,
    "front_setback_mm": 0,
    "block_depth_mm": 56_000,
}
#: The same world on one tile. Used wherever the tile count is not the subject, because a tile of
#: city is about a sixth of the records of five and this suite generates a good many worlds.
ONE_TILE = {**FIVE_TILES, "city_extent_x_mm": 128_000}

#: Two tiles along x, which is where a bound ``storey_band_low`` is refused for the BAND rather than
#: for something else. Which refusal a specification gets is itself a roll, because the seed is
#: derived from the specification and the drawn block length decides whether a district can hold a
#: block at all, so this pair was found by measurement and not by reasoning.
TWO_TILES = {**FIVE_TILES, "city_extent_x_mm": 256_000}
#: A specification with a binding at two levels that GENERATES, found by search over 47 candidates.
#: Almost no two-level specification does, for the same reason: adding a binding is a new seed.
TWO_LEVELS: dict[str, object] = {
    "grammar_id": "city",
    "grammar_version": 3,
    "bindings": [
        {"level": "city", "values": dict(TWO_TILES)},
        {"level": "district", "values": {"lane_width_mm": 3200}},
    ],
}

GRANTS = {
    "asker": ("asker", ALL_PERMISSIONS),
    "cramped": ("cramped", ALL_PERMISSIONS),
    "unmetered": ("unmetered", ALL_PERMISSIONS),
    "reader": ("asker", ["world.read"]),
}
#: ``unmetered`` deliberately gets no ``declare_tile_quota`` call, so "no declared quota is no
#: quota" is exercised rather than assumed. ``cramped`` may have three tiles and will ask for five.
CEILINGS = {"asker": 400, "cramped": 3}


@dataclass
class Asking:
    client: TestClient
    tokens: dict[str, str]
    workspaces: dict[str, uuid.UUID]
    dsn: str

    def ask(self, who: str, body: dict[str, object]):
        return self.client.post(
            WORLDS, json=body, headers={"Authorization": f"Bearer {self.tokens[who]}"}
        )

    def get(self, who: str, path: str):
        return self.client.get(path, headers={"Authorization": f"Bearer {self.tokens[who]}"})

    def used(self, who: str) -> int:
        """How much of its ceiling this workspace has spent, read from the table and not a body."""
        with psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row) as connection:
            connection.execute(
                "select set_config('exulanica.workspace_id', %s, false)",
                (str(self.workspaces[who]),),
            )
            row = connection.execute(
                "select tiles_used from workspace_tile_quota where workspace_id = %s",
                (self.workspaces[who],),
            ).fetchone()
            return int(row["tiles_used"]) if row else 0


def _city(values: dict[str, object] | None = None, **spec: object) -> dict[str, object]:
    """A specification with one binding at the city level. ``values`` replaces it wholesale."""
    body: dict[str, object] = {
        "grammar_id": "city",
        "grammar_version": 3,
        "bindings": [{"level": "city", "values": dict(ONE_TILE if values is None else values)}],
    }
    body.update(spec)
    return body


@pytest.fixture(scope="module")
def asking(tmp_path_factory) -> Iterator[Asking]:
    root = tmp_path_factory.mktemp("world-generation")
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        scratch = admin.execute("select current_schema()").fetchone()["current_schema"]
        provision_runtime_role(admin, role=APP_ROLE)
        admin.commit()
        workspaces = {name: uuid.uuid4() for name in ("asker", "cramped", "unmetered")}
        tokens = {who: f"{who}-token-{uuid.uuid4().hex}" for who in GRANTS}
        directory = load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        tokens[who]: {
                            "workspace_id": str(workspaces[workspace]),
                            "actor": str(uuid.uuid4()),
                            "permissions": granted,
                        }
                        for who, (workspace, granted) in GRANTS.items()
                    }
                )
            }
        )
        dsn = app_role_dsn(scratch)
        database = Database(url=dsn)
        services = Services(
            database=database,
            readonly_database=database,
            store=LocalContentAddressedStore(root / "blobs"),
            tokens=directory,
            executor_shares_the_write_role=True,
            model_client=None,
        )
        app = create_app(services, verify=False)
        for name, limit in CEILINGS.items():
            with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
                connection.execute(
                    "select set_config('exulanica.workspace_id', %s, false)",
                    (str(workspaces[name]),),
                )
                declare_tile_quota(
                    connection, workspaces[name], tiles_limit=limit, declared_by=uuid.uuid4()
                )
        with TestClient(app) as client:
            yield Asking(client=client, tokens=tokens, workspaces=workspaces, dsn=dsn)


# -- what the route is declared to be -------------------------------------------------------


def test_the_route_is_declared_metered_and_charges_its_own_tiles():
    """The permission and the self-charging entry are one decision and both halves are held.

    ``tiles.materialise`` alone would let :func:`authorise_route` charge ONE tile for a request
    covering up to 256, because ``TILES_PER_REQUEST`` is 1 and its own comment says why: "the route
    that will carry it does not exist yet and a batch size is its decision to declare". This is
    that route, so it must ALSO be in ``SELF_CHARGING_TILE_ROUTES`` or the ceiling is wrong by the
    size of the world. Asserting only the permission would leave the other half free to drift.
    """
    rule = ROUTE_RULES[("POST", WORLDS)]
    assert Permission.TILES_MATERIALISE in rule.permissions
    assert ("POST", WORLDS) in SELF_CHARGING_TILE_ROUTES
    assert "charges one tile per tile" in SELF_CHARGING_TILE_ROUTES[("POST", WORLDS)]

    # The catalog reads declared data and materialises nothing, so it must NOT be metered: a human
    # enumerating the parameters they may tune should not spend a tile to do it.
    assert Permission.TILES_MATERIALISE not in ROUTE_RULES[("GET", GRAMMARS)].permissions
    assert ("GET", GRAMMARS) not in SELF_CHARGING_TILE_ROUTES


def test_a_missing_permission_is_refused_before_anything_is_generated(asking):
    answer = asking.ask("reader", _city())
    assert answer.status_code == 403
    assert answer.json()["code"] == "not_authorised"
    assert asking.used("asker") == 0


# -- the four refusals, over HTTP, each naming the thing that was wrong ----------------------


@pytest.mark.parametrize(
    ("what", "body", "must_name"),
    [
        (
            "an unknown parameter name",
            _city({**ONE_TILE, "blok_length_mm": 140_000}),
            ("blok_length_mm", "not a declared parameter"),
        ),
        (
            "a value outside its declared range",
            _city({**ONE_TILE, "city_extent_x_mm": 40_000_000}),
            ("city_extent_x_mm", "40000000", "outside", "2048000"),
        ),
        (
            "two bindings at one level",
            {
                "grammar_id": "city",
                "grammar_version": 3,
                "bindings": [
                    {"level": "city", "values": dict(ONE_TILE)},
                    {"level": "city", "values": {"block_length_mm": 140_000}},
                ],
            },
            ("two bindings at level", "city"),
        ),
        (
            "a level that does not exist",
            {
                "grammar_id": "city",
                "grammar_version": 3,
                "bindings": [
                    {"level": "city", "values": dict(ONE_TILE)},
                    {"level": "attic", "values": {"block_length_mm": 140_000}},
                ],
            },
            ("attic", "not a level of this cascade"),
        ),
    ],
    ids=["unknown-parameter", "out-of-range", "two-at-one-level", "unknown-level"],
)
def test_the_cascade_s_refusal_survives_the_trip_through_http(asking, what, body, must_name):
    """The single most valuable property this route exposes, asked of the real application.

    Not a unit test on the validator: these four go through the error map, so what is measured is
    that the refusal ARRIVES, with the parameter name and the reason in it. With no handler for the
    generator's errors each is a bare 500 saying nothing, which is an API that accepts a typo and
    generates something.
    """
    before = asking.used("asker")
    answer = asking.ask("asker", body)
    assert answer.status_code == 422, f"{what}: {answer.text}"
    payload = answer.json()
    assert payload["code"] == "invalid_parameter", payload
    for fragment in must_name:
        assert fragment in payload["detail"], f"{what} did not name {fragment}: {payload}"
    # A refusal spends nothing. This is the other half of the self-charging decision: with the
    # generic charge in authorise_route still running, a refused request would cost a tile.
    assert asking.used("asker") == before


def test_a_stage_s_refusal_survives_too_even_though_it_names_no_parameter(asking):
    """A value inside its declared range, refused later by a stage. Measured, not hypothesised.

    ``block_length_mm`` is declared [60000, 250000]. Short blocks lay more cross streets than the
    six ``local_street`` names ``assets/catalogs/street-name.v1.json`` holds, and the refusal that
    produces is an ``InvalidRecordError`` whose message names no parameter at all. That is why this
    route generates inside the request instead of resolving and stopping: the caller meets this
    from the thing it called rather than later from a component it did not.

    AND THE FIVE TILES ARE SPENT, which is asserted rather than left implicit. It is the opposite of
    what the four cascade refusals above assert, and both are deliberate: resolution happens before
    the charge, so a specification the cascade refuses costs nothing, and a specification a stage
    refuses costs the whole world. That is ``exulanica.api.quotas``' own rule, "taken before the
    tile is materialised and not refunded when materialisation fails", and a test that did not pin
    it would let a later refactor add a refund nobody decided on.
    """
    before = asking.used("asker")
    answer = asking.ask("asker", _city({**FIVE_TILES, "block_length_mm": 60_000}))
    assert answer.status_code == 422, answer.text
    assert answer.json()["code"] == "invalid_record"
    assert "local_street" in answer.json()["detail"]
    assert asking.used("asker") == before + 5


def test_a_narrowed_range_is_refused_with_the_range_that_actually_applied(asking):
    """``storey_band_low`` is declared up to 40 and refused far below it, and the refusal says so.

    ``massing`` cuts the band to what the district's lots can build, which depends on the frontage
    lengths, which depend on the block length. So the admissible range is a consequence of the
    geometry and no catalog can publish it in advance. What a caller is owed is the range that DID
    apply, and the declared maximum is read off the catalog route here rather than typed, so this
    compares two paths instead of restating one.
    """
    published = _published(asking)
    declared_maximum = published["storey_band_low"]["maximum"]
    # 10 rather than `declared_maximum - 1`, and the difference is a finding rather than a
    # convenience: at 39 this specification is refused for having a district too small to hold a
    # block, because every value added to a specification changes the derived seed and so the drawn
    # block length. 10 was measured to reach the band.
    assert declared_maximum > 10
    answer = asking.ask("asker", _city({**TWO_TILES, "storey_band_low": 10}))
    assert answer.status_code == 422, answer.text
    assert answer.json()["code"] == "invalid_parameter"
    detail = answer.json()["detail"]
    assert "storey_band_low" in detail and "outside" in detail
    applied = re.search(r"outside \[(\d+), (\d+)\]", detail)
    assert applied, f"the refusal did not state the range that applied: {detail!r}"
    assert int(applied.group(2)) < 10 < declared_maximum, (
        f"the refusal restated the declared maximum {declared_maximum} instead of the narrowed one"
    )


def test_a_required_parameter_nobody_set_is_refused_by_name(asking):
    answer = asking.ask("asker", _city({k: v for k, v in ONE_TILE.items() if k != "driving_side"}))
    assert answer.status_code == 422, answer.text
    assert "driving_side is required and no level sets it" in answer.json()["detail"]


def test_a_parameter_set_at_too_fine_a_level_is_refused_by_name(asking):
    """Coarsest wins, and finer than a parameter's own level is refused rather than kept quietly."""
    answer = asking.ask(
        "asker",
        {
            "grammar_id": "city",
            "grammar_version": 3,
            "bindings": [
                {"level": "city", "values": dict(ONE_TILE)},
                {"level": "face", "values": {"block_length_mm": 140_000}},
            ],
        },
    )
    assert answer.status_code == 422, answer.text
    detail = answer.json()["detail"]
    assert "block_length_mm" in detail and "district" in detail and "face" in detail


def test_an_unknown_grammar_is_the_caller_s_mistake_and_not_a_five_hundred(asking):
    answer = asking.ask("asker", _city(grammar_id="forest"))
    assert answer.status_code == 422, answer.text
    assert answer.json()["code"] == "unknown_grammar"
    assert "forest" in answer.json()["detail"]


def test_a_true_is_not_an_integer(asking):
    """Invisible in JSON, where ``true`` and ``1`` look equally like a number, and refused twice.

    ``StrictInt`` on the body refuses it and ``ParameterSpec.check`` would refuse it again with
    ``type(value) is not int``. Whichever fires, no world is generated with a storey band of one.
    """
    answer = asking.ask("asker", _city({**ONE_TILE, "storey_band_low": True}))
    assert answer.status_code == 422, answer.text


def test_the_route_accepts_no_level_of_detail(asking):
    """Nothing reduces detail by level, so a route taking one would answer with a tile record
    claiming a level nothing produced. ``extra="forbid"`` is what makes that a refusal."""
    answer = asking.ask("asker", _city(lod=1))
    assert answer.status_code == 422, answer.text


# -- what the route generates ---------------------------------------------------------------


def test_a_world_is_generated_and_every_tile_it_covers_is_charged(asking):
    before = asking.used("asker")
    answer = asking.ask("asker", _city(FIVE_TILES))
    assert answer.status_code == 200, answer.text
    world = answer.json()

    assert world["tile_count"] == 5
    assert [tuple(tile) for tile in world["tiles"]] == [(x, 0) for x in range(5)]
    assert world["lod"] == GENERATED_LOD == 0
    assert world["record_count"] == sum(stage["records"] for stage in world["records_by_stage"])
    assert world["record_count"] > 0
    assert next(stage["stage"] for stage in world["records_by_stage"]) == "terrain"

    # Five tiles covered, five tiles charged, read back from the table rather than the response.
    assert asking.used("asker") == before + 5
    assert world["tiles_charged"] == 5

    # Every parameter the grammar declares is accounted for, and a derived one states no value
    # rather than a number no stage used.
    sources = {p["name"]: p["source"] for p in world["parameters"]}
    values = {p["name"]: p["value"] for p in world["parameters"]}
    assert len(sources) == 91, f"the city grammar declares 91 parameters, stated {len(sources)}"
    assert sources["driving_side"] == "city"
    assert sources["typology"] == "derive" and values["typology"] is None
    assert values["city_extent_x_mm"] == 640_000

    # The identity is a canonical lowercase UUID, which is what require_identity admits, and the
    # seed is the 64 lowercase hexadecimal characters require_seed admits.
    assert re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", world["world_identity"])
    assert re.fullmatch(r"[0-9a-f]{64}", world["world_seed"])


def test_the_same_specification_is_the_same_world_and_a_different_one_is_not(asking):
    """The property that makes a stored specification unnecessary, and the collision it avoids.

    The seed is derived, so asking twice gives one world and asking differently gives another. A
    caller-chosen seed gives neither, and worse: two worlds sharing a seed share a
    ``tile_inputs_digest`` and a ``baked_tile_id``, which is how a perfectly deterministic pair of
    bakes is recorded as ``nondeterminism_detected``.
    """
    once = asking.ask("asker", _city()).json()
    twice = asking.ask("asker", _city()).json()
    assert (once["world_seed"], once["world_identity"], once["output_digest"]) == (
        twice["world_seed"],
        twice["world_identity"],
        twice["output_digest"],
    )

    other = asking.ask("asker", _city(FIVE_TILES))
    assert other.status_code == 200, other.text
    other = other.json()
    assert other["world_seed"] != once["world_seed"]
    assert other["world_identity"] != once["world_identity"]
    assert other["output_digest"] != once["output_digest"]


def test_stating_one_specification_two_ways_asks_for_one_world(asking):
    """Neither value order nor level order may make two worlds out of one request.

    Both halves matter: a caller writing the same values in another order, and a caller listing two
    levels in another order. If either moved the seed, one ask would bake a second world under a
    second key.
    """
    reordered = dict(reversed(list(ONE_TILE.items())))
    assert list(reordered) != list(ONE_TILE)
    assert (
        asking.ask("asker", _city(reordered)).json()["world_seed"]
        == (asking.ask("asker", _city()).json()["world_seed"])
    )

    swapped = {**TWO_LEVELS, "bindings": list(reversed(TWO_LEVELS["bindings"]))}  # type: ignore[arg-type]
    plain_two, swapped_two = asking.ask("asker", TWO_LEVELS), asking.ask("asker", swapped)
    assert (plain_two.status_code, swapped_two.status_code) == (200, 200), swapped_two.text
    assert plain_two.json()["world_seed"] == swapped_two.json()["world_seed"]
    # And it is one world, not two that happen to share a seed: the same records came out.
    assert plain_two.json()["output_digest"] == swapped_two.json()["output_digest"]
    assert plain_two.json()["record_count"] == swapped_two.json()["record_count"]


def test_the_seven_bindings_a_world_cannot_be_asked_for_without(asking):
    """What the grammar NEEDS bound against what it DECLARES required, measured through the route.

    Each of these is dropped from a specification that generates and the request refused. The city
    descriptor declares exactly one of them ``required``; the rest declare ``derive`` and then
    refuse the derived value, or refuse to derive one at all. That gap is why a caller following
    the catalog cannot generate anything, and it is kept as a test rather than a paragraph so that
    fixing a descriptor fails here and the catalog's honesty gets revisited.

    ``block_depth_mm`` is in the list for a different reason and the distinction is deliberate: its
    declared range is simply far wider than a district of this size can use, so leaving it out
    refuses for varying downstream reasons rather than for one wrong declaration.
    """
    declared_required = {
        name
        for name, parameter in _published(asking).items()
        if parameter["when_unset"] == "required"
    }
    assert declared_required == {"driving_side"}

    refused = {}
    for name in ONE_TILE:
        answer = asking.ask("asker", _city({k: v for k, v in ONE_TILE.items() if k != name}))
        if answer.status_code != 200:
            refused[name] = answer.json()["detail"]
    assert set(refused) == set(ONE_TILE), (
        "every value in this specification was chosen because dropping it refuses; "
        f"these did not: {sorted(set(ONE_TILE) - set(refused))}"
    )
    assert declared_required < set(refused)


# -- what stops a world nobody can afford ---------------------------------------------------


def test_a_world_past_the_ceiling_is_refused_and_nothing_is_generated(asking):
    """The bound on a compute amplifier, and it has to fire BEFORE the generation runs.

    ``cramped`` may have three tiles and asks for five. The refusal is 429 carrying the ceiling's
    own words, the spend is unchanged, and this ceiling is what makes generating inside a request
    affordable at all.
    """
    before = asking.used("cramped")
    answer = asking.ask("cramped", _city(FIVE_TILES))
    assert answer.status_code == 429, answer.text
    assert answer.json()["code"] == "tile_quota_exceeded"
    assert "Do not retry" in answer.json()["detail"]
    assert asking.used("cramped") == before


def test_a_workspace_with_no_declared_ceiling_generates_nothing(asking):
    """ "No declared quota is no quota." There is no default ceiling, and this is what says the
    generation route inherited that rather than a number somebody picked for it."""
    answer = asking.ask("unmetered", _city())
    assert answer.status_code == 429, answer.text
    assert answer.json()["code"] == "tile_quota_undeclared"
    assert asking.used("unmetered") == 0


def test_an_extent_no_level_bound_is_refused_by_name_rather_than_counted(asking):
    """``city_extent_x_mm`` is a ``derive`` parameter, so with nothing binding it there is no single
    value and so no tile count to charge. The route refuses, naming both extents, rather than
    guessing a count, charging the maximum, or re-deriving what the stage would draw."""
    before = asking.used("asker")
    without_extents = {k: v for k, v in ONE_TILE.items() if not k.startswith("city_extent")}
    answer = asking.ask("asker", _city(without_extents))
    assert answer.status_code == 422, answer.text
    detail = answer.json()["detail"]
    assert "city_extent_x_mm" in detail and "city_extent_y_mm" in detail
    assert asking.used("asker") == before


def test_an_extent_that_ends_mid_tile_is_refused_before_the_charge(asking):
    """The likeliest refusal a real caller meets, and it was the one this file did not ask about.

    ``city_extent_x_mm`` is declared [128000, 2048000] and the terrain stage covers a city with
    whole 128000 mm patches, so of the 1,920,001 values the cascade admits, SIXTEEN are acceptable.
    A caller picking a round number in metres almost certainly picks one of the other 1,920,000.

    ``city_tiles`` raises that refusal, and it reaches HTTP through this route's coverage rule while
    it is counting tiles, which is BEFORE the quota is charged. Both halves are asserted: that the
    refusal arrives naming the parameter and the tile size, and that it cost nothing. Found by
    reading the route rather than by a failing test, which is why it is here.
    """
    before = asking.used("asker")
    answer = asking.ask("asker", _city({**ONE_TILE, "city_extent_x_mm": 200_000}))
    assert answer.status_code == 422, answer.text
    assert answer.json()["code"] == "invalid_parameter"
    detail = answer.json()["detail"]
    assert "city_extent_x_mm" in detail and "200000" in detail
    assert "128000" in detail and "mid-tile" in detail
    assert asking.used("asker") == before


def test_a_grammar_whose_tiles_cannot_be_counted_is_refused(asking):
    """``box`` is registered, generates, and is not a world anybody walks. With no coverage rule
    its tiles cannot be counted, so a request naming it cannot be metered and is refused rather
    than run unmetered."""
    assert "box" not in WORLD_COVERAGE
    before = asking.used("asker")
    answer = asking.ask("asker", {"grammar_id": "box", "grammar_version": 1, "bindings": []})
    assert answer.status_code == 422, answer.text
    assert "box" in answer.json()["detail"] and "metered" in answer.json()["detail"]
    assert asking.used("asker") == before


# -- the catalog, and whether it publishes what is enforced ----------------------------------


def _published(asking) -> dict[str, dict]:
    """The city's declared parameters as the catalog route answers them, by name."""
    answer = asking.get("asker", GRAMMARS)
    assert answer.status_code == 200, answer.text
    for grammar in answer.json():
        if grammar["grammar_id"] == "city":
            return {p["name"]: p for p in grammar["parameters"]}
    raise AssertionError("the catalog listed no city grammar")


def test_the_catalog_names_every_declared_parameter_of_every_registered_grammar(asking):
    answer = asking.get("asker", GRAMMARS)
    assert answer.status_code == 200, answer.text
    listed = {(g["grammar_id"], g["grammar_version"]): g for g in answer.json()}
    assert ("city", 3) in listed and ("box", 1) in listed

    city = listed[("city", 3)]
    assert city["cascade_levels"] == ["city", "district", "block", "lot", "building", "face"]
    assert city["generable"] is True
    assert sorted(city["coverage_reads"]) == ["city_extent_x_mm", "city_extent_y_mm"]

    # `box` is registered and cannot be asked for here, and the catalog says which rather than
    # leaving it out: a grammar missing from a listing looks like one that does not exist.
    assert listed[("box", 1)]["generable"] is False
    assert listed[("box", 1)]["coverage_reads"] == []
    assert listed[("box", 1)]["cascade_levels"] == ["collection", "item"]

    # Every parameter carries what a person needs in order to set it: a unit, the level it belongs
    # to, the stage that reads it, and the stated basis of its range. One missing any of those is a
    # declaration a human cannot act on.
    for parameter in city["parameters"]:
        assert parameter["unit"] and parameter["level"] and parameter["stage"]
        assert parameter["basis"] and parameter["basis"].strip() == parameter["basis"]
        assert parameter["when_unset"] in ("draw", "derive", "required")
        assert parameter["level"] in city["cascade_levels"]
        assert parameter["stage"] in city["stages"]
        if parameter["kind"] == "choice":
            assert parameter["options"] and parameter["minimum"] is None
        else:
            assert not parameter["options"] and parameter["minimum"] is not None


def test_the_catalog_states_the_bounds_the_cascade_actually_enforces(asking):
    """Two operands from two paths: the published bound, and the refusal one past it.

    Comparing the catalog against the descriptor it was read from would assert this route's own
    arithmetic. Asking the generation route to bind ``maximum + 1`` asks whether the number a human
    is shown is the number that will refuse them, which is a different question.
    """
    published = _published(asking)
    for name in ("city_extent_x_mm", "block_length_mm", "storey_band_high"):
        stated_maximum = published[name]["maximum"]
        assert stated_maximum is not None
        answer = asking.ask("asker", _city({**ONE_TILE, name: stated_maximum + 1}))
        assert answer.status_code == 422, f"{name}: {answer.text}"
        detail = answer.json()["detail"]
        assert answer.json()["code"] == "invalid_parameter", detail
        assert name in detail and str(stated_maximum) in detail, (
            f"{name}: the catalog published {stated_maximum} and the refusal said {detail!r}"
        )


def test_the_catalog_costs_no_tiles(asking):
    before = asking.used("asker")
    assert asking.get("asker", GRAMMARS).status_code == 200
    assert asking.used("asker") == before


# -- the arm of the error map no request can reach -------------------------------------------


def test_every_generator_error_resolves_to_a_handler_and_the_unmapped_ones_are_loud(asking):
    """The catch-all arm, on the shipped map, for the classes no request can reach.

    ``CatalogError`` needs a broken file on disk and ``InvalidSeedError`` cannot happen because
    this route derives the seed, so neither has an HTTP path and a test claiming one would be
    inventing it. What IS asked here is the question that matters: does Starlette's lookup, which
    walks ``type(exc).__mro__``, find a handler for each of them on the application
    :func:`create_app` built, and is the one it finds the loud arm rather than the caller's?

    The four reachable classes are measured through real requests above. This is the fifth.
    """
    handlers = asking.client.app.exception_handlers

    def resolved(exception_type: type) -> object:
        for candidate in exception_type.__mro__:
            if candidate in handlers:
                return handlers[candidate]
        return None

    class ARefusalNobodyMapped(GrammarError):
        pass

    base = resolved(GrammarError)
    assert base is not None, "nothing in the map handles GrammarError"
    for unreachable in (CatalogError, InvalidSeedError, ARefusalNobodyMapped):
        assert resolved(unreachable) is base, (
            f"{unreachable.__name__} does not fall through to the loud arm"
        )
