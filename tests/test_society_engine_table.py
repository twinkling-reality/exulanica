"""The society engine table is the one statement of which engines exist and what each can do.

Everything that used to restate a list of engines derives it from the newest
``society-engines.v<N>.json``.
These tests hold the places that cannot derive, because they are fixed text, to the table: the
implemented engine modules, the live schema's checks, triggers and indexes, a SQL literal in a
file another lane is restructuring, and the browser's generated copy. Each one fails when the
table and the copy differ, and names the copy.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import re
from pathlib import Path

import pytest
from exulanica.world import society_engines
from exulanica.world.society import SOCIETY_ENGINE_VERSION
from exulanica.world.society_engines import (
    ACTION_ENGINES,
    COMPARISON_ENGINES,
    CREATABLE_ENGINES,
    CREATES,
    CREATES_HOLDING_THINGS,
    DECISION_ENGINES,
    DEFAULT_ENGINE,
    ENGINES,
    ENGINES_PATH,
    EXPERIMENT_ENGINES,
    INPUT_ENGINES,
    LEGACY_ENGINES,
    OWNER_MODEL_CHOICE_ENGINES,
    PLAYABLE_ENGINES,
    PRESENCE_ENGINES,
    SAVED_WORLD_ENGINES,
    RetiredSocietyEngine,
    UnknownSocietyEngine,
    creatable_engine,
    load_engine_table,
    society_engine,
)
from exulanica.world.society_living import LIVING_PROFILE, LIVING_TOWN_PROFILE
from exulanica.world.society_planner import PURPOSEFUL_PROFILE
from exulanica.world.society_social import SOCIAL_PROFILE
from exulanica.world.society_things import THINGS_PROFILE

ROOT = Path(__file__).resolve().parents[1]
QUOTED_ENGINE = re.compile(r"'(exulanica-society/v[0-9]+)'")
#: Python source that still restates an engine list as SQL text, each with why it may for now.
#: An entry whose file no longer holds such a list fails, so this only ever shrinks.
PENDING_SQL_COPIES: dict[str, tuple[frozenset[str], str]] = {}


def test_every_engine_in_the_table_is_implemented_and_every_implementation_is_listed():
    implemented = {
        SOCIETY_ENGINE_VERSION: "legacy",
        PURPOSEFUL_PROFILE: "purposeful",
        SOCIAL_PROFILE: "purposeful",
        LIVING_PROFILE: "living",
        LIVING_TOWN_PROFILE: "living",
        THINGS_PROFILE: "things",
    }
    assert {engine.engine: engine.state_family for engine in ENGINES} == implemented
    assert DEFAULT_ENGINE == SOCIETY_ENGINE_VERSION


def test_each_capability_is_claimed_only_by_engines_that_implement_it():
    # A capability in the table is a promise the code keeps: directed actions are v2 and v3's
    # goal-policy seam, which the society of things' planner minute is, model decisions are v2's
    # person decisions over that same seam and v3's stored social proposals, experiments run the
    # living engine.
    assert ACTION_ENGINES == (PURPOSEFUL_PROFILE, SOCIAL_PROFILE, THINGS_PROFILE)
    assert DECISION_ENGINES == (
        PURPOSEFUL_PROFILE,
        SOCIAL_PROFILE,
        LIVING_TOWN_PROFILE,
        THINGS_PROFILE,
    )
    # v2's people take a model their world's owner chose at the planner's choice points, and so do
    # a society of things' people, and the living town's at its engine's own, through its seam.
    assert OWNER_MODEL_CHOICE_ENGINES == (PURPOSEFUL_PROFILE, LIVING_TOWN_PROFILE, THINGS_PROFILE)
    # v3 is retired: its stored societies read and replay, and nothing new is made with it.
    assert CREATABLE_ENGINES == (
        SOCIETY_ENGINE_VERSION,
        PURPOSEFUL_PROFILE,
        LIVING_PROFILE,
        LIVING_TOWN_PROFILE,
        THINGS_PROFILE,
    )
    assert CREATES == {
        "district": LIVING_PROFILE,
        "saved_world": PURPOSEFUL_PROFILE,
        "town": LIVING_TOWN_PROFILE,
    }
    assert EXPERIMENT_ENGINES == (LIVING_PROFILE,)
    # Comparisons play the purposeful society, the living town or a society of things through each
    # engine's choice seam.
    assert COMPARISON_ENGINES == (PURPOSEFUL_PROFILE, LIVING_TOWN_PROFILE, THINGS_PROFILE)
    assert SAVED_WORLD_ENGINES == (
        PURPOSEFUL_PROFILE,
        SOCIAL_PROFILE,
        LIVING_TOWN_PROFILE,
        THINGS_PROFILE,
    )
    # Sending people away and bringing them back is the purposeful engine's own transition.
    assert PRESENCE_ENGINES == (PURPOSEFUL_PROFILE,)
    assert LEGACY_ENGINES == (SOCIETY_ENGINE_VERSION,)
    assert set(INPUT_ENGINES) == {e.engine for e in ENGINES} - set(LEGACY_ENGINES)
    assert set(PLAYABLE_ENGINES) <= set(INPUT_ENGINES)


def test_an_engine_the_table_does_not_state_is_refused_by_name():
    with pytest.raises(UnknownSocietyEngine, match="exulanica-society/v9"):
        society_engine("exulanica-society/v9")
    with pytest.raises(UnknownSocietyEngine, match="exulanica-society/v9"):
        creatable_engine("exulanica-society/v9")
    with pytest.raises(RetiredSocietyEngine, match="exulanica-society/v3 is retired"):
        creatable_engine(SOCIAL_PROFILE)
    assert creatable_engine(PURPOSEFUL_PROFILE).owner_model_choice
    with pytest.raises(UnknownSocietyEngine, match="None"):
        society_engine(None)
    assert society_engine(LIVING_PROFILE).holds(65_536)
    assert not society_engine(SOCIETY_ENGINE_VERSION).holds(8)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["engines"].reverse(), "once each, in order"),
        (lambda d: d.update(default_engine="exulanica-society/v9"), "default"),
        (lambda d: d["engines"][0].update(playback=True), "invalid society engine row"),
        (lambda d: d["engines"][1].update(takes_inputs=False), "invalid society engine row"),
        (lambda d: d["engines"][3]["population"].update(minimum=0), "invalid society engine row"),
        (lambda d: d["engines"][3]["population"].pop("minimum"), "invalid society engine row"),
        (lambda d: d["engines"][1]["population"].update(most=9), "invalid society engine row"),
        (
            lambda d: d.update(profile="exulanica.society-engines/v3"),
            "invalid society engine row",
        ),
        (lambda d: d["engines"][2].pop("reason"), "capabilities and a reason"),
        (lambda d: d["engines"][3].update(owner_model_choice=True), "invalid society engine row"),
        (lambda d: d["engines"][1].update(owner_model_choice=False), "invalid society engine row"),
        (lambda d: d.update(default_engine="exulanica-society/v3"), "retired"),
        (lambda d: d["creates"]["saved_world"].update(engine="exulanica-society/v3"), "creates"),
        (lambda d: d["creates"]["saved_world"].update(engine="exulanica-society/v4"), "saved"),
        (lambda d: d["creates"].pop("district"), "creates names exactly"),
        (
            lambda d: d["creates_holding_things"].update(engine="exulanica-society/v2"),
            "engine of things",
        ),
        (lambda d: d["creates_holding_things"]["grounds"].reverse(), "grounds once each"),
        (
            lambda d: d.update(profile="exulanica.society-engines/v2"),
            "not a society engine table",
        ),
    ],
    ids=[
        "unordered",
        "unknown-default",
        "playable-without-inputs",
        "actions-without-inputs",
        "empty-population",
        "no-minimum",
        "another-population-figure",
        "no-maximum-in-the-third-profile",
        "no-reason",
        "owner-choice-without-model-decisions",
        "comparisons-without-owner-choice",
        "retired-default",
        "creates-a-retired-engine",
        "saved-world-engine-off-saved-worlds",
        "creates-no-district-engine",
        "holding-things-not-of-things",
        "holding-things-grounds-unordered",
        "holding-things-in-the-second-profile",
    ],
)
def test_a_malformed_table_is_refused(tmp_path, change, message):
    document = json.loads(ENGINES_PATH.read_text(encoding="utf-8"))
    change(document)
    path = tmp_path / ENGINES_PATH.name
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_engine_table(path)


def _sql_copies(root: Path = ROOT) -> dict[str, set[str]]:
    """Every Python module under exulanica/ with a string literal quoting an engine as SQL."""
    found: dict[str, set[str]] = {}
    for path in sorted((root / "exulanica").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                engines = QUOTED_ENGINE.findall(node.value)
                if engines:
                    found.setdefault(path.relative_to(root).as_posix(), set()).update(engines)
    return found


def test_no_module_restates_an_engine_list_as_sql_text():
    copies = _sql_copies()
    assert set(copies) == set(PENDING_SQL_COPIES), (
        f"engine lists as SQL text: {sorted(copies)}; pass the engine table's list as a bound "
        "parameter instead, or say here why a copy is pending"
    )
    for relative, (expected, _why) in PENDING_SQL_COPIES.items():
        assert copies[relative] == set(expected), relative


def test_the_source_scan_sees_a_quoted_engine_list(tmp_path):
    # The positive control: a module that restates a list is found, so an empty result means none.
    package = tmp_path / "exulanica"
    package.mkdir()
    (package / "restated.py").write_text(
        "QUERY = \"select 1 where engine_version in ('exulanica-society/v2')\"\n", encoding="utf-8"
    )
    assert _sql_copies(tmp_path) == {"exulanica/restated.py": {"exulanica-society/v2"}}


# The live schema. Migrations are immutable SQL, so each object that states engines is a copy the
# table cannot write; this reads every such object back and compares it with the table.

SCHEMA_OBJECTS = {
    # Observer projection accepts the same things state family as ParticipationRuntime.eligible.
    "participant_scope": lambda: {e.engine for e in ENGINES if e.state_family == "things"},
    "world_society_engine_version_check": lambda: {e.engine for e in ENGINES},
    "tg_world_society_input_binding": lambda: set(INPUT_ENGINES),
    "tg_world_society_v2_event_binding": lambda: set(INPUT_ENGINES),
    "world_society_event_versioned_order_unique": lambda: set(INPUT_ENGINES),
    "world_society_event_legacy_unique": lambda: set(INPUT_ENGINES),
    "tg_world_society_action_request_binding": lambda: set(ACTION_ENGINES),
    "tg_world_society_decision_binding": lambda: set(DECISION_ENGINES),
    "tg_world_society_decision_request_binding": lambda: set(DECISION_ENGINES),
    "tg_world_society_transition_decision_binding": lambda: set(DECISION_ENGINES),
    "tg_society_experiment_definition_binding": lambda: set(EXPERIMENT_ENGINES),
    "tg_world_society_presence_binding": lambda: set(PRESENCE_ENGINES),
    "world_society_population_size_check": lambda: {e.engine for e in ENGINES},
}
POPULATION_FLOOR = re.compile(
    r"engine_version = (?:'(?P<one>[^']+)'::text|ANY \(ARRAY\[(?P<many>[^\]]+)\]\))\) AND "
    r"\(population_size >= (?P<low>\d+)\)\)"
)
POPULATION = re.compile(
    r"engine_version = (?:'(?P<one>[^']+)'::text|ANY \(ARRAY\[(?P<many>[^\]]+)\]\))\) AND "
    r"\(\(population_size >= (?P<low>\d+)\) AND \(population_size <= (?P<high>\d+)\)\)"
)


def _schema_objects(connection) -> dict[str, str]:
    namespace = "(select oid from pg_namespace where nspname=current_schema())"
    rows = [
        *connection.execute(
            f"select conname as name,pg_get_constraintdef(oid) as body from pg_constraint "
            f"where connamespace={namespace}"
        ).fetchall(),
        *connection.execute(
            f"select proname as name,prosrc as body from pg_proc where pronamespace={namespace}"
        ).fetchall(),
        *connection.execute(
            "select indexname as name,indexdef as body from pg_indexes "
            "where schemaname=current_schema()"
        ).fetchall(),
    ]
    return {row["name"]: row["body"] for row in rows if QUOTED_ENGINE.search(row["body"] or "")}


@pytest.mark.postgres
def test_every_schema_object_that_names_engines_agrees_with_the_table(repository):
    objects = _schema_objects(repository.connection)
    assert set(objects) == set(SCHEMA_OBJECTS), (
        "a schema object states engines that no capability claims, or a claimed one is gone"
    )
    for name, expected in SCHEMA_OBJECTS.items():
        assert set(QUOTED_ENGINE.findall(objects[name])) == expected(), name


@pytest.mark.postgres
def test_the_population_check_states_each_engine_bounds_from_the_table(repository):
    body = _schema_objects(repository.connection)["world_society_population_size_check"]
    stated: dict[str, tuple[int, int]] = {}
    for match in POPULATION.finditer(body):
        bounds = (int(match["low"]), int(match["high"]))
        for engine in [match["one"]] if match["one"] else QUOTED_ENGINE.findall(match["many"]):
            stated[engine] = bounds
    assert stated == {
        e.engine: (e.population_minimum, e.population_maximum)
        for e in ENGINES
        if e.population_maximum is not None
    }, body
    # An engine that states no maximum is held to its minimum alone.
    floors: dict[str, int] = {}
    for match in POPULATION_FLOOR.finditer(body):
        for engine in [match["one"]] if match["one"] else QUOTED_ENGINE.findall(match["many"]):
            floors[engine] = int(match["low"])
    assert floors == {
        e.engine: e.population_minimum for e in ENGINES if e.population_maximum is None
    }, body
    assert floors, "the engines a town's society is made with state no maximum"


@pytest.mark.postgres
def test_an_input_records_a_population_of_any_size(repository):
    """The input check holds a recorded population to its shape (a rule and a whole number of
    people, nobody included) and to no ceiling, and the society check holds an engine that states
    no maximum to its minimum."""
    checks = {
        row["name"]: row["body"]
        for row in repository.connection.execute(
            "select conname as name,pg_get_constraintdef(oid) as body from pg_constraint "
            "where conname in ('world_society_input_population_check',"
            "'world_society_population_size_check')"
        ).fetchall()
    }
    assert set(checks) == {
        "world_society_input_population_check",
        "world_society_population_size_check",
    }
    recorded = checks["world_society_input_population_check"]
    assert "512" not in recorded and "::numeric" not in recorded, recorded
    assert "'^[0-9]+$'" in recorded, recorded
    assert "512" in checks["world_society_population_size_check"], "the retired engine keeps it"


def test_the_first_table_is_this_one_without_its_new_columns():
    """``society-engines.v1.json`` stays because evaluation records name it; it is held to the
    table, so it never reads as a second statement that disagrees. Reasons are prose and may
    differ; every capability it states is the current table's, for every engine it states (an
    engine added after it is the current table's alone)."""
    first = json.loads(ENGINES_PATH.with_name("society-engines.v1.json").read_text("utf-8"))
    current = json.loads(ENGINES_PATH.read_text(encoding="utf-8"))
    assert first["profile"] == "exulanica.society-engines/v1"
    assert first["default_engine"] == current["default_engine"]
    added = {"creatable", "owner_model_choice"}
    stated = {row["engine"] for row in first["engines"]}
    # The maximum population is the one figure a later table states differently: none, from the
    # fourth, for the engines a town's society is made with.
    assert [
        {k: v for k, v in row.items() if k not in {"reason", "population"}}
        for row in first["engines"]
    ] == [
        {k: v for k, v in row.items() if k not in added | {"reason", "population"}}
        for row in current["engines"]
        if row["engine"] in stated
    ]
    assert [row["population"]["minimum"] for row in first["engines"]] == [
        row["population"]["minimum"] for row in current["engines"] if row["engine"] in stated
    ]


def _without_maximum(engines):
    return tuple(dataclasses.replace(engine, population_maximum=None) for engine in engines)


def test_the_earlier_tables_are_this_one_but_for_what_each_version_came_to_state():
    """Every earlier table stays beside this one, read by the same loader by its version. The
    fourth is this one without a site among the grounds a society of things stands on; the third
    is the fourth with a maximum of 512 people stated for the engines a town's society is made
    with; the second is the third without its engine for a world holding things."""
    fourth_path = ENGINES_PATH.with_name("society-engines.v4.json")
    third_path = ENGINES_PATH.with_name("society-engines.v3.json")
    second_path = ENGINES_PATH.with_name("society-engines.v2.json")
    assert ENGINES_PATH.name == f"society-engines.v{society_engines.TABLE_VERSION}.json"
    assert sorted(
        int(path.name.split(".v")[1].split(".")[0])
        for path in ENGINES_PATH.parent.glob("society-engines.v*.json")
    ) == list(range(1, society_engines.TABLE_VERSION + 1))
    fourth = load_engine_table(fourth_path)
    assert fourth[:3] == (ENGINES, DEFAULT_ENGINE, CREATES)
    assert CREATES_HOLDING_THINGS is not None and fourth[3] is not None
    assert fourth[3].engine == CREATES_HOLDING_THINGS.engine
    assert fourth[3].grounds == ("authored_starter", "generated_town", "made_world")
    assert CREATES_HOLDING_THINGS.grounds == (
        "authored_starter",
        "generated_site",
        "generated_town",
        "made_world",
    )
    engines, default, creates, holding = load_engine_table(third_path)
    assert (default, dict(creates), holding) == (DEFAULT_ENGINE, dict(CREATES), fourth[3])
    assert _without_maximum(engines) == _without_maximum(ENGINES)
    assert {e.engine: e.population_maximum for e in engines} == {
        "exulanica-society/v1": 512,
        "exulanica-society/v2": 512,
        "exulanica-society/v3": 512,
        "exulanica-society/v4": 65_536,
        "exulanica-society/v5": 512,
        "exulanica-society/v7": 512,
    }
    assert {e.engine for e in ENGINES if e.population_maximum is None} == {
        "exulanica-society/v2",
        "exulanica-society/v5",
        "exulanica-society/v7",
    }
    assert all(
        new.population_maximum in (None, old.population_maximum)
        for old, new in zip(engines, ENGINES, strict=True)
    )
    assert society_engine("exulanica-society/v7").holds(100_000)
    assert not society_engine("exulanica-society/v7").holds(0)
    assert not society_engine("exulanica-society/v3").holds(513)
    second = load_engine_table(second_path)
    assert second == (engines, default, creates, None)
    third = json.loads(third_path.read_text(encoding="utf-8"))
    third.pop("creates_holding_things")
    third["profile"] = "exulanica.society-engines/v2"
    assert json.loads(second_path.read_text(encoding="utf-8")) == third


def test_a_table_is_read_by_its_version_so_a_later_one_needs_no_new_reader(tmp_path):
    """A version that states nothing new is read with no edit of the loader: what a table may
    state follows from its number. One above the table this host reads is refused, since this
    host cannot know what it came to state, and so is the first, which another shape holds."""
    current = json.loads(ENGINES_PATH.read_text(encoding="utf-8"))
    for version, read in ((society_engines.TABLE_VERSION, True), (99, False), (1, False)):
        stated = tmp_path / f"society-engines.v{version}.json"
        stated.write_text(
            json.dumps({**current, "profile": f"exulanica.society-engines/v{version}"}),
            encoding="utf-8",
        )
        if read:
            assert load_engine_table(stated)[0] == ENGINES
        else:
            with pytest.raises(ValueError, match="not a society engine table"):
                load_engine_table(stated)


def test_every_saved_world_s_ground_holding_things_is_a_society_of_things():
    """The grounds the table names for a world holding things are the society grounds the catalog
    states, a world made from a world kind among them: on a host that offers societies of things
    a version holding a thing its author placed is one, whatever its ground."""
    from exulanica.world.society_grounds import created_engine, society_grounds

    assert CREATES_HOLDING_THINGS is not None
    assert society_engine(CREATES_HOLDING_THINGS.engine).state_family == "things"
    grounds = {ground.key: ground for ground in society_grounds()}
    assert set(CREATES_HOLDING_THINGS.grounds) == set(grounds)
    for key, ground in grounds.items():
        assert created_engine(ground, holding_things=True) == CREATES_HOLDING_THINGS.engine, key
        assert created_engine(ground) != CREATES_HOLDING_THINGS.engine, key


def test_the_browser_copy_is_generated_from_the_table():
    generated = (
        ROOT / "web" / "packages" / "app" / "src" / "society-engines.generated.ts"
    ).read_text(encoding="utf-8")
    text = ENGINES_PATH.read_text(encoding="utf-8")
    assert f"export const SOCIETY_ENGINES_JSON = String.raw`{text}`;" in generated
    assert f"export const SOCIETY_ENGINES_FILE = '{ENGINES_PATH.name}';" in generated
    names = " | ".join(f"'{engine.engine}'" for engine in ENGINES)
    assert f"export type SocietyEngineProfile = {names};" in generated


def test_the_module_exports_only_derived_lists():
    # Every exported list is a projection of ENGINES; none is written out by hand.
    assert tuple(e.engine for e in ENGINES if e.playback) == society_engines.PLAYABLE_ENGINES
