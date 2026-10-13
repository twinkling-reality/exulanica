"""Grant-scoped identities, independent of browser sessions and stored simulation records.

The host stores a digest binding a grant to a browser account's actor, never that actor itself.
Any future simulation record names the grant's actor instead. Neither identity grants access:
the request must also establish the grant's current standing and the account's authentication.
"""

from __future__ import annotations

import hmac
import uuid

from exulanica.canonical import sha256_of_canonical


def grant_id(workspace_id: uuid.UUID, idempotency_key: uuid.UUID) -> uuid.UUID:
    """A stable issue identity, separate from door grants and another workspace's same key."""
    return uuid.uuid5(workspace_id, f"world-grant:{idempotency_key}")


def principal_sha256(grant: uuid.UUID, actor: uuid.UUID) -> str:
    """Bind one account actor to this grant without storing its cross-world identifier."""
    return sha256_of_canonical(
        {
            "profile": "exulanica.participation-principal/v1",
            "grant_id": str(grant),
            "actor": str(actor),
        }
    ).hex()


def principal_matches(grant: uuid.UUID, actor: uuid.UUID, recorded: object) -> bool:
    """An absent or malformed binding confers no authority."""
    return (
        isinstance(recorded, str)
        and len(recorded) == 64
        and recorded.isascii()
        and hmac.compare_digest(principal_sha256(grant, actor), recorded)
    )


def grant_actor(grant: uuid.UUID) -> uuid.UUID:
    """The grant's simulation identity, independent of the person who redeems it."""
    return uuid.uuid5(grant, "exulanica.participation-actor/v1")
