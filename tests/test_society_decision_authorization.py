"""A society's decisions are read under the authorization of its snapshot, read once per request.

:meth:`~exulanica.world.society_decision_repository.SocietyDecisionRepository.role_decisions`
reads the society's snapshot, which authorizes the society's inputs, unless its caller hands it the
snapshot the caller already read through the same society for the same version. These hold, without
a database, that nothing else stands in for that read: no snapshot, one of another version or of
another society, or an empty one.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from exulanica.world.decision_roles import decision_roles
from exulanica.world.society_decision_repository import SocietyDecisionRepository

SOCIETY = uuid.UUID("11111111-1111-4111-8111-111111111111")
VERSION = uuid.UUID("22222222-2222-4222-8222-222222222222")


class _Society:
    """A society with a fixed row and no decisions recorded; its snapshot reads are counted."""

    def __init__(self) -> None:
        self.connection = self
        self.snapshots: list[uuid.UUID] = []

    def execute(self, *_args: Any, **_kwargs: Any) -> _Society:
        return self

    def fetchall(self) -> list[Any]:
        return []

    def _lock(self) -> None:
        pass

    def _row(self, version_id: uuid.UUID, *, lock: bool = False) -> dict[str, Any]:
        return {
            "workspace_id": uuid.uuid4(),
            "society_id": SOCIETY,
            "version_id": version_id,
            "engine_version": "exulanica-society/v5",
        }

    def snapshot(self, version_id: uuid.UUID) -> dict[str, Any]:
        self.snapshots.append(version_id)
        return {"society_id": SOCIETY, "version_id": version_id}


@pytest.mark.parametrize(
    ("authorized", "reads"),
    [
        (None, 1),
        ({"society_id": SOCIETY, "version_id": VERSION}, 0),
        ({"society_id": SOCIETY, "version_id": uuid.uuid4()}, 1),
        ({"society_id": uuid.uuid4(), "version_id": VERSION}, 1),
        ({}, 1),
    ],
    ids=["none", "this society and version", "another version", "another society", "empty"],
)
def test_a_snapshot_stands_for_the_authorizing_read_only_when_it_is_this_societys(
    authorized, reads
):
    society = _Society()
    decisions = SocietyDecisionRepository(society).role_decisions(  # type: ignore[arg-type]
        decision_roles().deciding_for("person"), VERSION, latest=10, authorized=authorized
    )
    assert decisions == []
    assert society.snapshots == [VERSION] * reads
