"""The ability modules' table: what each module version serves and declares, read as data.

What is shown here, with no database:

*   every module the abilities catalog names is a row, and each of its versions serves exactly the
    abilities naming it; every module keeps each of its versions from 1;
*   a module's figures that a request is also asked under are the same figures in both places;
*   what a society records, and what it runs where it recorded nothing: a new society records each
    built module at its newest version, and every version a stored society names stays readable;
*   a table that breaks a rule is refused by name, and every row keeps its bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from exulanica.abilities.registry import (
    BEFORE_RECORDED,
    CROSSING,
    MODULES_PATH,
    PURPOSEFUL,
    PURPOSEFUL_BY_KIND,
    SAY,
    AbilityError,
    AbilityModuleNotConnected,
    UnknownAbilityModule,
    ability_module,
    ability_modules,
    built_module,
    current_modules,
    load_ability_modules,
    recorded_modules,
    recorded_row,
)
from exulanica.canonical import canonical_json
from exulanica.things.catalogs import thing_catalogs
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_things import THINGS_PROFILE


def test_every_module_the_abilities_catalog_names_is_a_row_serving_exactly_its_abilities():
    catalogs = thing_catalogs()
    named: dict[str, set[str]] = {}
    for ability in catalogs.abilities.values():
        named.setdefault(ability.module, set()).add(ability.key)
    for module, abilities in named.items():
        assert set(ability_module(module).abilities) == abilities, module
        # A later version of a module changes how it serves its abilities, never which: the
        # catalog naming one version names what every version serves.
        name = ability_module(module).name
        versions = [row for row in ability_modules().values() if row.name == name]
        assert all(set(row.abilities) == abilities for row in versions), module


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
    with pytest.raises(UnknownAbilityModule):
        recorded_modules({"modules": ["exulanica-ability/juggling/v1"]})
    with pytest.raises(AbilityModuleNotConnected) as refused:
        recorded_modules({"modules": ["exulanica-ability/follow/v1"]})
    assert refused.value.code == "follow_not_built"


def test_a_new_society_records_each_module_at_its_newest_built_version_and_older_ones_read():
    """A new society records the routine held to each being's kind; the first version, which every
    society made before it runs, stays a built row every reader reads
    (tests/test_society_kind_gates.py reads a stored society of it through the planner, the
    options, a request and the card)."""
    newest = current_modules()
    assert PURPOSEFUL_BY_KIND in newest and PURPOSEFUL not in newest
    for module in newest:
        row = ability_module(module)
        built = [
            other.version
            for other in ability_modules().values()
            if other.name == row.name and other.status == "built"
        ]
        assert recorded_row(newest, row.name) == row and row.version == max(built), module
    # The version a stored society recorded, by the table, by what it runs and by its row.
    assert built_module(PURPOSEFUL).abilities == built_module(PURPOSEFUL_BY_KIND).abilities
    assert recorded_modules({"modules": list(BEFORE_RECORDED)}) == BEFORE_RECORDED
    assert recorded_row(recorded_modules({}), "purposeful") == built_module(PURPOSEFUL)
    assert recorded_row(newest, "follow") is None
    with pytest.raises(AbilityError, match="one version of the purposeful module"):
        recorded_row([PURPOSEFUL, PURPOSEFUL_BY_KIND], "purposeful")


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
                {**d["modules"][0], "module": "exulanica-ability/purposeful/v99"}
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


#: Every row of the table, by the digest of its canonical JSON. A society replays by the rows its
#: first input recorded, so a row is never edited: a change is a new version beside it, and a new
#: row joins this list with its digest.
ROWS_SHA256 = {
    "exulanica-ability/crossing/v1": (
        "fa49cfcedc547827a63dd9376ad2fd3f3b0c6401d810db711986f2ae4c086c27"
    ),
    "exulanica-ability/follow/v1": (
        "ae012193437836a90eed9f9e1cb3cc1c4cc4db13626cee9b43777611ceddc491"
    ),
    "exulanica-ability/hands/v1": (
        "be1b97b54ef116a851ff9d4452a22fbf6311110c237f65b178ffd1f242d52719"
    ),
    "exulanica-ability/notice/v1": (
        "de80c0e505dcda86983300fbee44af82046e0817a21c4718f809af447a46e42c"
    ),
    "exulanica-ability/purposeful/v1": (
        "1602c6b84373e041535ae6c4dd3ee7136ce18e51cb0887270c8d532f5ecf7903"
    ),
    "exulanica-ability/purposeful/v2": (
        "6b0441b5bc9b980070864ea1368d6c1d4595116131289752d02d73ffd06102be"
    ),
    "exulanica-ability/remember/v1": (
        "b81b95345ce5f21521cc1f93cdf9c0f080bfe90aad9ee95cb75d0c1d7f01b1af"
    ),
    "exulanica-ability/say/v1": (
        "8732fe7e835dfcc80892e8218c2d4817bbe200c5ee113de4158a48b6fe584778"
    ),
}


def test_every_row_keeps_its_bytes_and_every_row_is_pinned():
    table = json.loads(MODULES_PATH.read_text(encoding="utf-8"))
    found = {
        row["module"]: hashlib.sha256(canonical_json(row)).hexdigest() for row in table["modules"]
    }
    assert found == ROWS_SHA256
