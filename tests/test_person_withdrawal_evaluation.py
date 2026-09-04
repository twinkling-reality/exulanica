"""Safety boundary for the destructive synthetic person-withdrawal exercise."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from exulanica.errors import TombstonedError
from exulanica.orchestration.person_withdrawal import (
    _late_publication_refusal,
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


def test_late_publication_probe_records_the_repository_tombstone_error():
    class RefusingRepository:
        @contextmanager
        def transaction(self):
            yield

        def insert_scene_artifact(self, **_values):
            raise TombstonedError("tombstoned: write refused for artifact")

    result = _late_publication_refusal(RefusingRepository(), uuid.uuid4())

    assert result == {
        "refused": True,
        "error_class": "TombstonedError",
        "sqlstate": None,
        "reason": "tombstoned: write refused for artifact",
    }
