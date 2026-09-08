import pytest
from exulanica.migrations import Migration

original = Migration.sql.fget


def mutated(self: Migration) -> str:
    sql = original(self)
    if self.version == "0040":
        assert "and s.receipt_record->'privacy_inputs'=inputs" in sql
        sql = sql.replace("and s.receipt_record->'privacy_inputs'=inputs", "and true")
    return sql


Migration.sql = property(mutated)
raise SystemExit(
    pytest.main(["tests/test_screening_currency.py::test_receipt_input_binding_guard", "-q", "-ra"])
)
