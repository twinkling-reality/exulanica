"""Parameter migrations: the city's version 1 to 2 migration, and the machinery on probe grammars.

**The city migration is vacuous, and says so.** City version 1 declared no parameters, so no
binding written for it can name one: every version 2 parameter is ``introduced``, and the identity
policy is ``introduced`` because version 1 derived no identities. What is tested is that the
migration is total over both surfaces, that empty bindings at every level carry across unchanged,
and that a version 1 binding naming any parameter is refused rather than dropped.

**The machinery is exercised on probe grammars** written under ``tmp_path``: an integer carried by
``value * multiply + add``, a choice mapped option by option, a removed parameter reported among
``dropped`` with its reason, an introduced one, and a chain from version 1 to 3. Then every way a
migration can fail to be total, lossless or order-keeping is refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.contract import ParameterSurface
from exulanica.grammar.errors import GrammarError, InvalidParameterError
from exulanica.grammar.grammars.city.descriptor import (
    CITY_GRAMMAR_VERSION,
    CITY_MIGRATION_PATHS,
    CITY_SURFACE,
    CITY_V1_SURFACE,
)
from exulanica.grammar.migration import (
    DroppedBinding,
    ParameterMigration,
    migrate_chain,
)
from exulanica.grammar.parameters import CascadeBinding

# -------------------------------------------------------------------------------------------
# The city


def _city_migration() -> ParameterMigration:
    return ParameterMigration.read(CITY_MIGRATION_PATHS[2])


def test_every_city_version_after_the_first_ships_its_migration():
    assert set(CITY_MIGRATION_PATHS) == set(range(2, CITY_GRAMMAR_VERSION + 1))
    for version, path in CITY_MIGRATION_PATHS.items():
        migration = ParameterMigration.read(path)
        assert (migration.source_version, migration.target_version) == (version - 1, version)


def test_the_city_migration_is_total_and_introduces_every_parameter():
    migration = _city_migration()
    migration.check(CITY_V1_SURFACE, CITY_SURFACE)
    assert (migration.carried, migration.mapped, migration.removed) == ((), (), ())
    assert sorted(entry.target for entry in migration.introduced) == sorted(
        CITY_SURFACE.parameters.names()
    )
    assert len(migration.introduced) == 72
    assert migration.identity_policy == "introduced"
    assert "derived no subject identities" in migration.identity_reason
    assert migration.levels == tuple((level, level) for level in CITY_V1_SURFACE.cascade.levels)


def test_empty_city_bindings_at_every_level_carry_across_unchanged():
    migration = _city_migration()
    levels = CITY_V1_SURFACE.cascade.levels
    everything = tuple(CascadeBinding.of(level, {}) for level in levels)
    result = migration.migrate(CITY_V1_SURFACE, CITY_SURFACE, everything)
    assert result.bindings == everything
    assert result.dropped == ()
    for level in levels:
        alone = migration.migrate(CITY_V1_SURFACE, CITY_SURFACE, (CascadeBinding.of(level, {}),))
        assert alone.bindings == (CascadeBinding.of(level, {}),)
    chained = migrate_chain(
        [migration],
        {1: CITY_V1_SURFACE, 2: CITY_SURFACE},
        everything,
        from_version=1,
        to_version=2,
    )
    assert chained == result


@pytest.mark.parametrize("name", ["driving_side", "storeys", "bay_pitch_mm", "wall_material"])
@pytest.mark.parametrize("level", ["city", "face"])
def test_a_city_version_1_binding_naming_any_parameter_is_refused(name, level):
    with pytest.raises(InvalidParameterError, match="is not a declared parameter"):
        _city_migration().migrate(
            CITY_V1_SURFACE, CITY_SURFACE, (CascadeBinding.of(level, {name: 1}),)
        )


def test_a_city_binding_at_a_level_version_1_does_not_have_is_refused():
    with pytest.raises(InvalidParameterError):
        _city_migration().migrate(CITY_V1_SURFACE, CITY_SURFACE, (CascadeBinding.of("room", {}),))


# -------------------------------------------------------------------------------------------
# Probe grammars


def _integer(name: str, level: str, low: int, high: int, unit: str = "mm") -> dict[str, Any]:
    return {
        "name": name,
        "kind": "integer",
        "unit": unit,
        "level": level,
        "stage": "shape",
        "when_unset": "derive",
        "vocabulary": "",
        "basis": "authored for this test",
        "minimum": low,
        "maximum": high,
    }


def _choice(name: str, level: str, options: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "choice",
        "unit": "key",
        "level": level,
        "stage": "shape",
        "when_unset": "derive",
        "vocabulary": "closed",
        "basis": "authored for this test",
        "options": options,
    }


def _descriptor(version: int, levels: list[str], parameters: list[dict[str, Any]]) -> dict:
    return {
        "schema_version": 2,
        "grammar_id": "probe",
        "grammar_version": version,
        "subject_kind": "probe",
        "frame": {},
        "admissible_uses": [],
        "cascade_levels": levels,
        "stages": [],
        "parameters": parameters,
        "projections": [],
        "navigation": [],
    }


_DESCRIPTORS = {
    1: _descriptor(
        1,
        ["world", "item"],
        [
            _integer("width_mm", "world", 1, 100),
            _choice("finish", "item", ["matte", "gloss"]),
            _integer("legacy_count", "item", 0, 3, unit="count"),
        ],
    ),
    2: _descriptor(
        2,
        ["world", "district", "item"],
        [
            _integer("size_mm", "world", 10, 1_000),
            _choice("surface", "item", ["flat", "shiny", "satin"]),
            _choice("colour", "item", ["red", "blue"]),
        ],
    ),
    3: _descriptor(
        3,
        ["world", "district", "item"],
        [
            _integer("size_mm", "world", 15, 1_005),
            _choice("surface", "item", ["flat", "shiny", "satin"]),
            _choice("colour", "item", ["red", "blue"]),
        ],
    ),
}

_MIGRATIONS = {
    2: {
        "schema_version": 1,
        "grammar_id": "probe",
        "source_version": 1,
        "target_version": 2,
        "identity_policy": "preserved",
        "identity_reason": "Version 2 assigns every kind, owner and ordinal as version 1 did.",
        "levels": [
            {"source": "world", "target": "world"},
            {"source": "item", "target": "item"},
        ],
        "carried": [{"source": "width_mm", "target": "size_mm", "multiply": 10, "add": 0}],
        "mapped": [
            {
                "source": "finish",
                "target": "surface",
                "options": [
                    {"source": "matte", "target": "flat"},
                    {"source": "gloss", "target": "shiny"},
                ],
            }
        ],
        "removed": [{"source": "legacy_count", "reason": "Nothing reads a count any more."}],
        "introduced": [{"target": "colour", "reason": "Version 2 colours an item."}],
    },
    3: {
        "schema_version": 1,
        "grammar_id": "probe",
        "source_version": 2,
        "target_version": 3,
        "identity_policy": "rekeyed",
        "identity_reason": "Version 3 numbers items from the other end.",
        "levels": [
            {"source": "world", "target": "world"},
            {"source": "district", "target": "district"},
            {"source": "item", "target": "item"},
        ],
        "carried": [{"source": "size_mm", "target": "size_mm", "multiply": 1, "add": 5}],
        "mapped": [
            {
                "source": "surface",
                "target": "surface",
                "options": [{"source": key, "target": key} for key in ("flat", "shiny", "satin")],
            },
            {
                "source": "colour",
                "target": "colour",
                "options": [{"source": key, "target": key} for key in ("red", "blue")],
            },
        ],
        "removed": [],
        "introduced": [],
    },
}


def _write(tmp_path: Path, name: str, document: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _surfaces(tmp_path: Path) -> dict[int, ParameterSurface]:
    return {
        version: ParameterSurface.read(_write(tmp_path, f"probe.v{version}.json", document))
        for version, document in _DESCRIPTORS.items()
    }


def _migration(tmp_path: Path, target: int, document: dict[str, Any] | None = None):
    """The migration to ``target``, or ``document`` written under the version it names."""
    document = document or _MIGRATIONS[target]
    named = document["target_version"] if type(document["target_version"]) is int else target
    return ParameterMigration.read(_write(tmp_path, f"probe-migration.v{named}.json", document))


def test_a_probe_migration_carries_maps_drops_and_introduces(tmp_path):
    surfaces = _surfaces(tmp_path)
    result = _migration(tmp_path, 2).migrate(
        surfaces[1],
        surfaces[2],
        (
            CascadeBinding.of("world", {"width_mm": 40}),
            CascadeBinding.of("item", {"finish": "gloss", "legacy_count": 2}),
        ),
    )
    assert result.bindings == (
        CascadeBinding.of("world", {"size_mm": 400}),
        CascadeBinding.of("item", {"surface": "shiny"}),
    )
    assert result.dropped == (
        DroppedBinding("item", "legacy_count", 2, "Nothing reads a count any more."),
    )


def test_a_probe_chain_runs_from_version_1_to_3_and_keeps_what_it_dropped(tmp_path):
    surfaces = _surfaces(tmp_path)
    result = migrate_chain(
        [_migration(tmp_path, 3), _migration(tmp_path, 2)],
        surfaces,
        (
            CascadeBinding.of("world", {"width_mm": 100}),
            CascadeBinding.of("item", {"finish": "matte", "legacy_count": 0}),
        ),
        from_version=1,
        to_version=3,
    )
    assert result.bindings == (
        CascadeBinding.of("world", {"size_mm": 1_005}),
        CascadeBinding.of("item", {"surface": "flat"}),
    )
    assert [dropped.name for dropped in result.dropped] == ["legacy_count"]


def test_a_chain_with_a_missing_step_is_refused(tmp_path):
    surfaces = _surfaces(tmp_path)
    with pytest.raises(InvalidParameterError, match="no migration from version 2"):
        migrate_chain([_migration(tmp_path, 2)], surfaces, (), from_version=1, to_version=3)


def _changed(target: int, change) -> dict[str, Any]:
    document = json.loads(json.dumps(_MIGRATIONS[target]))
    change(document)
    return document


_NOT_TOTAL = [
    (
        "a source parameter left out",
        lambda d: d.update(removed=[]),
        "every source parameter",
    ),
    (
        "a target parameter left out",
        lambda d: d.update(introduced=[]),
        "every target parameter",
    ),
    (
        "a source parameter listed twice",
        lambda d: d["removed"].append({"source": "width_mm", "reason": "Twice."}),
        "every source parameter",
    ),
    (
        "a carried range that overflows",
        lambda d: d["carried"][0].update(multiply=11),
        "lands in",
    ),
    (
        "a carried range that underflows",
        lambda d: d["carried"][0].update(add=-1),
        "lands in",
    ),
    (
        "a level map that leaves a level out",
        lambda d: d.update(levels=d["levels"][:1]),
        "lists every source level once",
    ),
    (
        "a level map that reorders",
        lambda d: d.update(
            levels=[{"source": "world", "target": "item"}, {"source": "item", "target": "world"}]
        ),
        "keeps the order",
    ),
    (
        "a level map that merges",
        lambda d: d.update(
            levels=[{"source": "world", "target": "item"}, {"source": "item", "target": "item"}]
        ),
        "never merges",
    ),
    (
        "a level map to no target level",
        lambda d: d["levels"][1].update(target="room"),
        "is not a target level",
    ),
    (
        "a choice mapped with an option left out",
        lambda d: d["mapped"][0]["options"].pop(),
        "every source option",
    ),
    (
        "a choice mapped to an option the target lacks",
        lambda d: d["mapped"][0]["options"][0].update(target="glossy"),
        "is not a target option",
    ),
    (
        "a choice carried as an integer",
        lambda d: (
            d["carried"].append({"source": "finish", "target": "colour", "multiply": 1, "add": 0}),
            d["mapped"].clear(),
            d["introduced"].append({"target": "surface", "reason": "New."}),
            d["introduced"].remove({"target": "colour", "reason": "Version 2 colours an item."}),
        ),
        "only an integer is carried",
    ),
    (
        "an integer mapped as a choice",
        lambda d: (
            d["mapped"].append({"source": "width_mm", "target": "size_mm", "options": []}),
            d["carried"].clear(),
        ),
        "only a choice is mapped",
    ),
    (
        "a world parameter whose level maps finer than its target admits",
        lambda d: d["levels"][0].update(target="district"),
        "does not admit",
    ),
]


@pytest.mark.parametrize("why,change,message", _NOT_TOTAL, ids=[case[0] for case in _NOT_TOTAL])
def test_a_migration_that_is_not_total_lossless_or_order_keeping_is_refused(
    tmp_path, why, change, message
):
    surfaces = _surfaces(tmp_path)
    migration = _migration(tmp_path, 2, _changed(2, change))
    with pytest.raises(InvalidParameterError, match=message):
        migration.check(surfaces[1], surfaces[2])


_MALFORMED = [
    (
        "an identity policy that does not exist",
        lambda d: d.update(identity_policy="kept"),
        "identity policy is one of",
    ),
    (
        "an identity policy with no reason",
        lambda d: d.update(identity_reason=""),
        "identity_reason is non-empty text",
    ),
    ("a multiplier of zero", lambda d: d["carried"][0].update(multiply=0), "multiply >= 1"),
    ("a jump of two versions", lambda d: d.update(target_version=3), "one version to the next"),
    ("another grammar's name", lambda d: d.update(grammar_id="crate"), "not named for its grammar"),
    (
        "a removal with no reason",
        lambda d: d["removed"][0].update(reason=" "),
        "reason is non-empty text",
    ),
    ("an unknown key", lambda d: d.update(notes="none"), "is an object with exactly"),
    ("a later schema", lambda d: d.update(schema_version=2), "schema_version is 1"),
]


@pytest.mark.parametrize("why,change,message", _MALFORMED, ids=[case[0] for case in _MALFORMED])
def test_a_migration_document_outside_its_shape_is_refused(tmp_path, why, change, message):
    with pytest.raises(GrammarError, match=message):
        _migration(tmp_path, 2, _changed(2, change))


def test_a_migration_is_refused_between_surfaces_it_does_not_join(tmp_path):
    surfaces = _surfaces(tmp_path)
    with pytest.raises(InvalidParameterError, match="this migration joins"):
        _migration(tmp_path, 2).check(surfaces[2], surfaces[3])


_REFUSED_BINDINGS = [
    ("a level the source lacks", (CascadeBinding.of("district", {}),), "unrepeated level"),
    (
        "one level bound twice",
        (CascadeBinding.of("item", {}), CascadeBinding.of("item", {})),
        "unrepeated level",
    ),
    ("an unknown parameter", (CascadeBinding.of("item", {"depth_mm": 1}),), "not a declared"),
    ("a value out of range", (CascadeBinding.of("world", {"width_mm": 101}),), "outside"),
    (
        "a world parameter set on an item",
        (CascadeBinding.of("item", {"width_mm": 5}),),
        "cannot be set at",
    ),
]


@pytest.mark.parametrize(
    "why,bindings,message", _REFUSED_BINDINGS, ids=[case[0] for case in _REFUSED_BINDINGS]
)
def test_a_binding_the_source_version_would_refuse_is_refused(tmp_path, why, bindings, message):
    surfaces = _surfaces(tmp_path)
    with pytest.raises(InvalidParameterError, match=message):
        _migration(tmp_path, 2).migrate(surfaces[1], surfaces[2], bindings)
