"""The society engine table is the one statement of which engines exist and what each can do.

Everything that used to restate a list of engines derives it from ``society-engines.v1.json``.
These tests hold the places that cannot derive, because they are fixed text, to the table: the
implemented engine modules, the live schema's checks, triggers and indexes, a SQL literal in a
file another lane is restructuring, and the browser's generated copy. Each one fails when the
table and the copy differ, and names the copy.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from exulanica.world import society_engines
from exulanica.world.society import SOCIETY_ENGINE_VERSION
from exulanica.world.society_engines import (
    ACTION_ENGINES,
    COMPARISON_ENGINES,
    DECISION_ENGINES,
    DEFAULT_ENGINE,
    ENGINES,
    ENGINES_PATH,
    EXPERIMENT_ENGINES,
    INPUT_ENGINES,
    LEGACY_ENGINES,
    PLAYABLE_ENGINES,
    PRESENCE_ENGINES,
    SAVED_WORLD_ENGINES,
    UnknownSocietyEngine,
    load_engine_table,
    society_engine,
)
from exulanica.world.society_living import LIVING_PROFILE
from exulanica.world.society_planner import PURPOSEFUL_PROFILE
from exulanica.world.society_social import SOCIAL_PROFILE

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
    }
    assert {engine.engine: engine.state_family for engine in ENGINES} == implemented
    assert DEFAULT_ENGINE == SOCIETY_ENGINE_VERSION


def test_each_capability_is_claimed_only_by_engines_that_implement_it():
    # A capability in the table is a promise the code keeps: directed actions are v2 and v3's
    # goal-policy seam, model decisions are v2's person decisions over that same seam and v3's
    # social policy, experiments run the living engine.
    assert ACTION_ENGINES == (PURPOSEFUL_PROFILE, SOCIAL_PROFILE)
    assert DECISION_ENGINES == (PURPOSEFUL_PROFILE, SOCIAL_PROFILE)
    assert EXPERIMENT_ENGINES == (LIVING_PROFILE,)
    # A comparison plays the purposeful engine's genesis and minutes with person decisions.
    assert COMPARISON_ENGINES == (PURPOSEFUL_PROFILE,)
    assert SAVED_WORLD_ENGINES == (PURPOSEFUL_PROFILE, SOCIAL_PROFILE)
    # Sending people away and bringing them back is the purposeful engine's own transition.
    assert PRESENCE_ENGINES == (PURPOSEFUL_PROFILE,)
    assert LEGACY_ENGINES == (SOCIETY_ENGINE_VERSION,)
    assert set(INPUT_ENGINES) == {e.engine for e in ENGINES} - set(LEGACY_ENGINES)
    assert set(PLAYABLE_ENGINES) <= set(INPUT_ENGINES)


def test_an_engine_the_table_does_not_state_is_refused_by_name():
    with pytest.raises(UnknownSocietyEngine, match="exulanica-society/v5"):
        society_engine("exulanica-society/v5")
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
        (lambda d: d["engines"][2].pop("reason"), "capabilities and a reason"),
    ],
    ids=[
        "unordered",
        "unknown-default",
        "playable-without-inputs",
        "actions-without-inputs",
        "empty-population",
        "no-reason",
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
    assert stated == {e.engine: (e.population_minimum, e.population_maximum) for e in ENGINES}, body


def test_the_browser_copy_is_generated_from_the_table():
    generated = (
        ROOT / "web" / "packages" / "app" / "src" / "society-engines.generated.ts"
    ).read_text(encoding="utf-8")
    text = ENGINES_PATH.read_text(encoding="utf-8")
    assert f"export const SOCIETY_ENGINES_V1_JSON = String.raw`{text}`;" in generated
    names = " | ".join(f"'{engine.engine}'" for engine in ENGINES)
    assert f"export type SocietyEngineProfile = {names};" in generated


def test_the_module_exports_only_derived_lists():
    # Every exported list is a projection of ENGINES; none is written out by hand.
    assert tuple(e.engine for e in ENGINES if e.playback) == society_engines.PLAYABLE_ENGINES
