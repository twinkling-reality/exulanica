import pytest
from exulanica.migrations import Migration

original = Migration.sql.fget
BEFORE = "and privacy_mask_matches(p_workspace,c.capture_id,m.artifact_id,inputs)"
AFTER = "and true"


def mutated(self: Migration) -> str:
    sql = original(self)
    if self.version == "0041":
        assert BEFORE in sql
        sql = sql.replace(BEFORE, AFTER)
    return sql


Migration.sql = property(mutated)
SELECTOR = (
    "tests/test_asset_read_currency.py::test_changed_outline_rebuild_does_not_revive_geometry"
)
raise SystemExit(pytest.main([SELECTOR, "-q", "-ra"]))
