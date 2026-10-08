"""The ability modules' table: what each module version serves and declares, read as data.

What is shown here, with no database:

*   every module the abilities catalog names is a row, and each row serves exactly the abilities
    naming it; every module keeps each of its versions from 1;
*   a module's figures that a request is also asked under are the same figures in both places;
*   what a society records, and what it runs where it recorded nothing;
*   a table that breaks a rule is refused by name.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exulanica.abilities.registry import (
    BEFORE_RECORDED,
    CROSSING,
    MODULES_PATH,
    SAY,
    AbilityError,
    AbilityModuleNotConnected,
    UnknownAbilityModule,
    ability_module,
    ability_modules,
    current_modules,
    load_ability_modules,
    recorded_modules,
)
from exulanica.things.catalogs import thing_catalogs
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_things import THINGS_PROFILE


def test_every_module_the_abilities_catalog_names_is_a_row_serving_exactly_its_abilities():
    catalogs = thing_catalogs()
    named: dict[str, set[str]] = {}
    for ability in catalogs.abilities.values():
        named.setdefault(ability.module, set()).add(ability.key)
    rows = ability_modules()
    newest = {}
    for row in rows.values():
        if row.name not in newest or row.version > newest[row.name].version:
            newest[row.name] = row
    assert {row.module for row in newest.values()} >= set(named)
    for module, abilities in named.items():
        assert set(ability_module(module).abilities) == abilities, module


def test_a_module_s_figures_are_the_ones_its_requests_are_asked_under():
    role = person_role()
    contract = role.contract(role.terms(THINGS_PROFILE).versions)
    say = ability_module(SAY)
    for name in ("hearing_reach_mm", "lines_heard_maximum", "line_characters_maximum"):
        assert say.value(name) == contract.value(name), name
    # A visitor's quiet minutes are each kind's, within the bounds the abilities catalog states.
    leave = thing_catalogs().abilities["leave"]
    (bound,) = [p for p in leave.parameters if p.name == "quiet_minutes"]
    quiet = ability_module(CROSSING).parameters["quiet_minutes"]
    assert (quiet.value, quiet.minimum, quiet.maximum) == (None, bound.minimum, bound.maximum)


def test_a_society_runs_what_its_first_input_records_or_what_every_society_ran_before():
    assert recorded_modules({}) == BEFORE_RECORDED
    assert recorded_modules({"modules": list(current_modules())}) == current_modules()
    assert set(BEFORE_RECORDED) <= set(current_modules())
    with pytest.raises(UnknownAbilityModule):
        recorded_modules({"modules": ["exulanica-ability/juggling/v1"]})
    with pytest.raises(AbilityModuleNotConnected) as refused:
        recorded_modules({"modules": ["exulanica-ability/follow/v1"]})
    assert refused.value.code == "follow_not_built"


def _table(tmp_path: Path, change) -> Path:
    document = json.loads(MODULES_PATH.read_text(encoding="utf-8"))
    change(document)
    path = tmp_path / "ability-modules.v1.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["modules"][0].update(extra=1), "states exactly"),
        (lambda d: d["modules"][0].update(module="ability/purposeful/v1"), "is named"),
        (lambda d: d["modules"][1]["parameters"][0].update(value=10**6), "inside its bounds"),
        (lambda d: d["modules"][0].update(refusal="nothing"), "no refusal"),
        (lambda d: d["modules"].append(dict(d["modules"][0])), "twice"),
        (
            lambda d: d["modules"].append(
                {**d["modules"][0], "module": "exulanica-ability/purposeful/v3"}
            ),
            "every version from 1",
        ),
        (lambda d: d.update(profile="exulanica.ability-modules/v9"), "ability-modules/v1"),
    ],
    ids=[
        "extra-key",
        "bad-name",
        "value-out-of-bounds",
        "built-with-refusal",
        "twice",
        "gap",
        "profile",
    ],
)
def test_a_table_that_breaks_a_rule_is_refused_by_name(tmp_path, change, message):
    load_ability_modules(_table(tmp_path, lambda d: None))  # the positive control
    with pytest.raises(AbilityError, match=message):
        load_ability_modules(_table(tmp_path, change))
