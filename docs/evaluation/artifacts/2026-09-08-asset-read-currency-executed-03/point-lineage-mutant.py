import pytest
from exulanica.migrations import Migration

original = Migration.sql.fget
BEFORE = "if not found or not asset_screening_allows(p_workspace,s.capture_id,s.screening_id,p_at)"
AFTER = (
    "return true;\n if not found or not asset_screening_allows(p_w"
    "orkspace,s.capture_id,s.screening_id,p_at)"
)


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
