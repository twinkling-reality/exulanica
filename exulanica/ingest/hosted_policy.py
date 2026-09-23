"""The workspace's hosted-request policy for a request that carries one photograph's bytes.

The vision stage checks a capture's personal model right before it reads the bytes to send, then
attaches this policy to the model it sends through, so the same right is asked again, by the
boundary every hosted request passes (:mod:`exulanica.models.policy`), as the bytes leave. The
policy is scoped to that one capture: every request it admits is treated as carrying it, and a
request that names any other photograph is refused.

Its place-name resolver is the one that releases nothing, because a place's name is released only
to the roles the place-name right names, and the vision role is not one of them.
"""

from __future__ import annotations

import uuid

import psycopg

from exulanica.epistemics.hosted_requests import (
    WorkspaceRequestPolicy,
    borrowing,
    no_place_released,
)
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.model_rights import require_model_right
from exulanica.ingest.repository import IngestRepository
from exulanica.models.handoff import ModelHandoff

__all__ = ["photograph_policy"]


def photograph_policy(
    repository: IngestRepository, capture_id: uuid.UUID, screening_id: uuid.UUID
) -> WorkspaceRequestPolicy:
    """The workspace's rules for requests that carry ``capture_id``, under ``screening_id``."""

    def right(
        _connection: psycopg.Connection,
        _workspace_id: uuid.UUID,
        photographs: frozenset[uuid.UUID],
        handoff: ModelHandoff,
    ) -> None:
        if photographs != {capture_id}:
            raise PrivacyAdmissionError(
                f"a request sent for capture {capture_id} carries no other photograph"
            )
        require_model_right(repository, capture_id, screening_id, handoff)

    return WorkspaceRequestPolicy(
        repository.workspace_id,
        connection=borrowing(repository.connection),
        photograph_right=right,
        released_places=no_place_released,
        photographs=(capture_id,),
    )
