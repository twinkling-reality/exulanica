import pytest
from exulanica.migrations import Migration

original = Migration.sql.fget


def mutated(self: Migration) -> str:
    sql = original(self)
    if self.version == "0040":
        needle = "and c.consent_id<>new.consent_id)"
        assert needle in sql
        sql = sql.replace(needle, "and false)")
    return sql


Migration.sql = property(mutated)
raise SystemExit(
    pytest.main(
        [
            "tests/test_screening_currency.py::test_concurrent_subject_writers_refuse_duplicate_allocation",
            "-q",
            "-ra",
        ]
    )
)
