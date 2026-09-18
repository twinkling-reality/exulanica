"""What the seed script may destroy, and what it refuses to.

Written 2026-09-17 after a lane's scratch database on the shared server was dropped by something
that left no trace. This script held the only unguarded drop path in the repository: --force
dropped whatever its target named. The property these tests hold is that a run cannot destroy a
database it was not told, by name, to replace, and that a refusal says which database and what was
in it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import seed_workspace  # noqa: E402

TARGET = "exulanica_judgeseed_test"
HOLDINGS = "105 tables and 84 MB"


def refusal(**arguments):
    settings = dict(exists=True, force=True, replace=TARGET, holdings=HOLDINGS)
    settings.update(arguments)
    return seed_workspace.replacement_refusal(arguments.pop("name", TARGET), **settings)


def test_a_run_that_named_the_database_may_replace_it():
    assert refusal() is None


def test_a_database_that_does_not_exist_yet_is_simply_made():
    assert refusal(exists=False, replace=None, force=False) is None


@pytest.mark.parametrize("replace", [None, "exulanica_corridor_0917_test"])
def test_force_alone_refuses_and_says_what_it_would_have_destroyed(replace):
    """The case that cost a lane its database: a run forcing a target it never named.

    A name pattern would not have refused either of these, because the database that was lost
    matched every plausible scratch pattern, as this script's own default target does.
    """
    message = refusal(replace=replace)
    assert message is not None
    assert TARGET in message
    assert HOLDINGS in message
    assert (replace or "nothing") in message


def test_an_existing_database_without_force_says_both_flags_it_would_take():
    message = refusal(force=False, replace=None)
    assert message is not None
    assert "--force" in message and f"--replace {TARGET}" in message
    assert HOLDINGS in message


@pytest.mark.parametrize("name", sorted(seed_workspace.PROTECTED))
def test_the_retained_database_and_the_read_copy_are_refused_at_any_confirmation(name):
    """Agreeing twice is not enough for these two: this script never replaces them at all."""
    message = seed_workspace.replacement_refusal(
        name, exists=True, force=True, replace=name, holdings=HOLDINGS
    )
    assert message is not None
    assert name in message


def test_every_refusal_names_the_database_it_is_protecting():
    messages = [
        seed_workspace.replacement_refusal(
            TARGET, exists=True, force=force, replace=replace, holdings=HOLDINGS
        )
        for force, replace in [(False, None), (True, None), (True, "somewhere_else")]
    ]
    assert all(message and TARGET in message for message in messages)
