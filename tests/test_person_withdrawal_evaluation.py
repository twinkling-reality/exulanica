"""Safety boundary for the destructive synthetic person-withdrawal exercise."""

from __future__ import annotations

from pathlib import Path

import pytest
from exulanica.evaluation.person_withdrawal import (
    assert_exulanica_store_root,
    assert_test_database_url,
)


def test_person_withdrawal_evaluation_accepts_only_the_exact_local_test_database():
    assert_test_database_url("postgresql://localhost:5433/exulanica_spine_test")
    assert_test_database_url("postgresql://exulanica_purge@127.0.0.1:5433/exulanica_spine_test")

    for unsafe in (
        "postgresql://localhost:5433/exulanica_spine",
        "postgresql://localhost:5432/exulanica_spine_test",
        "postgresql://database.example:5433/exulanica_spine_test",
        "postgresql://localhost:5433/orimera_spine_test",
    ):
        with pytest.raises(ValueError, match="requires exactly"):
            assert_test_database_url(unsafe)


def test_person_withdrawal_evaluation_never_uses_historical_orimera_storage(tmp_path: Path):
    accepted = tmp_path / ".exulanica" / "validation" / "blobs"
    assert assert_exulanica_store_root(accepted) == accepted.resolve()

    for unsafe in (tmp_path / "blobs", tmp_path / ".orimera" / "blobs"):
        with pytest.raises(ValueError, match=r"under \.exulanica"):
            assert_exulanica_store_root(unsafe)
