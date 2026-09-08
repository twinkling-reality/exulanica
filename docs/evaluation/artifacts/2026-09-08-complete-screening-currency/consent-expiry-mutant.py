import pytest
from exulanica.migrations import Migration

original = Migration.sql.fget


def mutated(self: Migration) -> str:
    sql = original(self)
    if self.version == "0040":
        needle = "and c.effective_at<=p_at and (c.valid_until is null or c.valid_until>p_at)"
        assert needle in sql
        sql = sql.replace(needle, "and c.effective_at<=p_at")
    return sql


Migration.sql = property(mutated)
raise SystemExit(
    pytest.main(
        ["tests/test_screening_currency.py::test_producer_consent_currency[expired]", "-q", "-ra"]
    )
)
