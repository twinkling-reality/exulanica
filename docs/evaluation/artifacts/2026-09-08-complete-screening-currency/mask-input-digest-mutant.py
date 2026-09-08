import re

import pytest
from exulanica.migrations import Migration

original = Migration.sql.fget


def mutated(self: Migration) -> str:
    sql = original(self)
    if self.version == "0040":
        sql, count = re.subn(
            r"and m.input_digest=\(select digest.*?x\(h\)\)", "and true", sql, flags=re.S
        )
        assert count == 1
    return sql


Migration.sql = property(mutated)
raise SystemExit(
    pytest.main(["tests/test_screening_currency.py::test_input_digest_guard", "-q", "-ra"])
)
