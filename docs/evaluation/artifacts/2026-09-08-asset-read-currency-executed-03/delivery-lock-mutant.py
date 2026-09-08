import pytest
from exulanica.migrations import Migration

original = Migration.sql.fget
BEFORE = "perform pg_advisory_xact_lock(119622341);"
AFTER = "null;"


def mutated(self: Migration) -> str:
    sql = original(self)
    if self.version == "0041":
        assert BEFORE in sql
        sql = sql.replace(BEFORE, AFTER)
    return sql


Migration.sql = property(mutated)
SELECTOR = (
    "tests/test_asset_read_currency.py::test_reader_waits_for_prior_writer_and_later_writer_retries"
)
raise SystemExit(pytest.main([SELECTOR, "-q", "-ra"]))
