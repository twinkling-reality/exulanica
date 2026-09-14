"""R4. The vocabulary row nobody decided on.

``writes_a_name`` cannot be enforced and this file does not pretend to enforce it. What it does
is refuse a predicate that reached a migration without a decision reaching the register, and
refuse a decision that is not an answer.

Deliberately database-free. The assertion that used to carry part of this was ``len(rows) == 12``
in ``test_epistemic_guard_postgres.py``, which skips on any machine with no server, and whose
repair when a predicate was added was to type 13.
"""

from __future__ import annotations

import re

from exulanica.epistemics.vocabulary import DECISIONS
from exulanica.migrations import migrations

#: A value tuple in an ``insert into predicate`` block opens with the key as its first literal.
#: This is a text parse and text parses are the weaker half; the live check in
#: ``test_epistemic_guard_postgres.py`` compares the real table against the same register and
#: catches anything this misses.
_SEEDED_KEY = re.compile(r"\(\s*'([a-z][a-z0-9_]*)'\s*,")


def _seeded_keys() -> dict[str, str]:
    found: dict[str, str] = {}
    for migration in migrations():
        sql = migration.sql
        if "insert into predicate" not in sql:
            continue
        for block in sql.split("insert into predicate")[1:]:
            keys = _SEEDED_KEY.findall(block.split(";")[0])
            # A parse that silently finds nothing passes every check below for the wrong reason.
            # That is a failure here, not an empty set.
            assert keys, f"{migration.path.name} seeds the vocabulary and no key parsed from it"
            for key in keys:
                assert key not in found, f"{key} is seeded twice"
                found[key] = migration.version
    return found


def test_the_parse_finds_the_vocabulary_it_is_supposed_to_check():
    """The coverage check's own coverage. An empty set satisfies every assertion below it.

    This is the lesson the route sweep and the ingest store-write sweep both taught: a check
    over nothing passes. So the parse is asserted to have found the predicates that are known to
    be there by name, and not merely to have found some.
    """
    seeded = _seeded_keys()
    assert {"name_is", "person_present", "reconstruction_rung_is"} <= set(seeded), seeded
    assert len(seeded) >= 12, seeded


def test_every_seeded_predicate_has_a_recorded_decision():
    seeded = _seeded_keys()
    registered = {decision.key: decision.seeded_by for decision in DECISIONS}
    missing = sorted(set(seeded) - set(registered))
    assert not missing, (
        f"{missing} are seeded into `predicate` and no decision is recorded for them.\n"
        "Add a VocabularyDecision to exulanica/epistemics/vocabulary.py. The question it asks is: "
        "is this predicate's object the name a PERSON is called by? If it is, writes_a_name must "
        "be true and allows_kind must be {user} alone, and the database will refuse anything "
        "else. If it is not, say in `object_is` what the object is instead."
    )
    stale = sorted(set(registered) - set(seeded))
    assert not stale, f"{stale} have a recorded decision and no migration seeds them"
    for key, version in seeded.items():
        assert registered[key] == version, (
            f"{key} is seeded by migration {version} and the register says {registered[key]}"
        )


def test_a_recorded_decision_says_what_the_object_is():
    """The register is only worth having if an entry is an answer rather than a placeholder."""
    for decision in DECISIONS:
        # Forty, not sixty. Sixty rejected "A latitude and a longitude. Two numbers, and nothing
        # else is in the box." which is a correct and complete answer, and a floor that punishes
        # an honest short answer teaches people to pad. Forty is enough to stop "no".
        assert len(decision.object_is) >= 40, decision.key
        assert decision.key not in decision.object_is, (
            f"{decision.key}: `object_is` restates the key instead of saying what the object is"
        )
    reasons = [decision.object_is for decision in DECISIONS]
    assert len(set(reasons)) == len(reasons), (
        "two predicates share an `object_is`; copying the row above is not a decision"
    )


def test_a_recorded_naming_predicate_admits_only_the_user():
    """The database already refuses this row. What can drift is the register, which is a file.

    ``a_name_comes_only_from_the_user`` makes this unfailable against the shipped schema.
    Against the register it is not, because the register is a separate artefact that can come to
    claim something the database would have refused.
    """
    for decision in DECISIONS:
        if decision.writes_a_name:
            assert decision.allows_kind == ("user",), decision.key


def test_exactly_one_predicate_writes_a_name():
    """Already true and already asserted with a server. What changes is that this needs none."""
    assert [decision.key for decision in DECISIONS if decision.writes_a_name] == ["name_is"]
