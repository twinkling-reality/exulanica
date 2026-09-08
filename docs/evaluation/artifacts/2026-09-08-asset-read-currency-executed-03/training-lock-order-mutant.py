import pytest
from exulanica.migrations import Migration

original = Migration.sql.fget
BEFORE = (
    "perform pg_advisory_xact_lock_shared(\n    hashtextextended('"
    "training-source:' || p_workspace::text, 0));\n  perform pg_ad"
    "visory_xact_lock(hashtextextended('privacy-currency:' || p_w"
    "orkspace::text, 0));"
)
AFTER = (
    "perform pg_advisory_xact_lock(hashtextextended('privacy-curr"
    "ency:' || p_workspace::text, 0));\n  perform pg_advisory_xact"
    "_lock_shared(\n    hashtextextended('training-source:' || p_w"
    "orkspace::text, 0));"
)


def mutated(self: Migration) -> str:
    sql = original(self)
    if self.version == "0041":
        assert BEFORE in sql
        sql = sql.replace(BEFORE, AFTER)
    return sql


Migration.sql = property(mutated)
SELECTOR = (
    "tests/test_training_export_postgres.py::test_training_export"
    "_and_presentation_writer_share_a_lock_order"
)
raise SystemExit(pytest.main([SELECTOR, "-q", "-ra"]))
