import pytest
from exulanica.migrations import Migration

original = Migration.sql.fget


def mutated(self: Migration) -> str:
    sql = original(self)
    if self.version == "0040":
        needle = "and sr->'silhouette'=r->'silhouette'"
        assert needle in sql
        sql = sql.replace(needle, "and true")
    return sql


Migration.sql = property(mutated)
raise SystemExit(
    pytest.main(
        [
            "tests/test_screening_currency.py::test_stale_or_missing_claimed_review_inputs_do_not_authorize",
            "-q",
            "-ra",
        ]
    )
)
