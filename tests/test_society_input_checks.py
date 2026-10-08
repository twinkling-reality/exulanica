"""Each restated input check names every profile the application composes under it.

The input table's checks (``world_society_input_*_check``) are restated whole by each migration
that changes one, and the newest restatement is the check a database holds. A migration copied
from an older restatement drops the profiles added since, and every input of a dropped profile is
then refused, which only a stored input meets. This reads each check's newest restatement from the
migration files, with no database, and holds it to the profiles the application composes under it.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from exulanica.world.society_input_policy import (
    ARRIVAL_INPUTS,
    AUTHORED_GROUND_INPUTS,
    LEGACY_INPUT,
    LIVING_INPUTS,
    LOCAL_INPUT,
    POPULATION_INPUTS,
    ROUTINE_INPUTS,
    THING_INPUTS,
    UNREAD_PLACEMENT_REASONS,
)

MIGRATIONS = Path(__file__).resolve().parents[1] / "exulanica" / "migrations"

#: Each check by name, with every profile the application composes that the check must name.
CHECKS = {
    "world_society_input_profile_check": (LEGACY_INPUT, LOCAL_INPUT, *AUTHORED_GROUND_INPUTS),
    "world_society_input_unread_placements_check": tuple(UNREAD_PLACEMENT_REASONS),
    "world_society_input_routine_check": ROUTINE_INPUTS,
    "world_society_input_arrival_check": ARRIVAL_INPUTS,
    "world_society_input_things_check": THING_INPUTS,
    "world_society_input_population_check": POPULATION_INPUTS,
    "world_society_input_living_check": LIVING_INPUTS,
}


def newest_restatement(name: str, directory: Path = MIGRATIONS) -> tuple[str, str]:
    """The migration that last adds the check ``name``, and the check's text there."""
    found = []
    for path in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        for match in re.finditer(
            rf"add constraint {name}\b(.*?);", path.read_text(encoding="utf-8"), re.S
        ):
            found.append((path.name, match.group(1)))
    assert found, f"no migration adds {name}"
    return found[-1]


def missing(name: str, directory: Path = MIGRATIONS) -> tuple[str, list[str]]:
    where, body = newest_restatement(name, directory)
    return where, [profile for profile in CHECKS[name] if f"'{profile}'" not in body]


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_the_newest_restatement_of_each_input_check_names_every_profile_composed_under_it(name):
    where, absent = missing(name)
    assert absent == [], f"{where} restates {name} without {absent}"


def test_a_restatement_copied_from_an_older_one_is_found(tmp_path):
    # The positive control: a later migration restating the profile check as 0123 wrote it, before
    # the things composition, is the newest restatement, and the profile it drops is named.
    older_directory = tmp_path / "before-0151"
    older_directory.mkdir()
    for path in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"):
        shutil.copy(path, tmp_path / path.name)
        if int(path.name[:4]) < 151:
            shutil.copy(path, older_directory / path.name)
    _, older = newest_restatement("world_society_input_profile_check", older_directory)
    (tmp_path / "9999_a_copied_restatement.sql").write_text(
        "alter table world_society_input add constraint world_society_input_profile_check"
        f"{older};\n",
        encoding="utf-8",
    )
    where, absent = missing("world_society_input_profile_check", tmp_path)
    assert where == "9999_a_copied_restatement.sql"
    # Every profile composed since 0151 is named, the things composition's first among them, and
    # nothing the older restatement already admitted.
    assert "exulanica.society-input/authored-ground-v5" in absent
    assert all(profile not in older for profile in absent)
