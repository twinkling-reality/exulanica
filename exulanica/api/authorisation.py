"""Who is asking, and the two things a request is never allowed to say about itself.

Every endpoint is authorised, and authorisation resolves to a
:class:`~exulanica.selection.validation.Session`, which is the same type the Selection validator
takes. That is deliberate: there is one notion of "who is asking" in this system, and the query
path's rule that "authorization derived from the session only, never from anything in the plan"
is the same rule as the API's.

Two things a request body may never contain, and they are absent from every request model in
this package rather than stripped from it:

*   **A workspace id.** It comes from the token. A request that could name a workspace could
    name somebody else's.
*   **An actor.** It comes from the token. ``entity_link.decided_by`` is what makes a confirmed
    link a human decision rather than a model's, and a client-supplied actor would make that
    column say whatever the client wanted.

**What this is, stated plainly, because overstating it would be worse than not having it.** This
is bearer-token authentication against a table of tokens the operator configures out of band. It
is not an account system, there is no registration, no password, no session expiry and no
refresh. The schema has no user table and inventing one here would be inventing a product
decision. What it does provide is the property the rest of the system depends on: a request
arrives already bound to exactly one workspace, and nothing downstream can widen that.

**What the token may do is part of its grant.** Each grant names its permissions from the closed
vocabulary in :mod:`exulanica.api.permissions`, and
:func:`exulanica.api.dependencies.authorise_route` refuses a route whose declaration the grant
does not cover. A grant with no ``permissions`` does
not load, and neither does one naming a permission outside the vocabulary. Absence is not read as
"everything", because that reading is the gap this closes: a token issued to upload photographs
reached every router. A :class:`TokenDirectory` built by hand with sessions and no permissions
holds nothing, which is deny by default rather than a fallback grant.

Tokens are compared with :func:`secrets.compare_digest` against the SHA-256 of the presented
value, so the comparison is constant time and the configured secret is never held next to a
user-supplied string in a way that a timing difference could separate.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from exulanica.api.permissions import Permission, parse_permissions
from exulanica.env import env_get, env_name
from exulanica.errors import ExulanicaError
from exulanica.selection.validation import Session

__all__ = [
    "API_TOKENS_ENV",
    "TokenDirectory",
    "TokenNotAccepted",
    "load_token_directory",
]

#: A JSON object mapping token to ``{"workspace_id": ..., "actor": ..., "permissions": [...],
#: "may_include_proposals": bool}``. Injected at run time and never committed, per the deployment
#: rule that "secrets are not committed and are not baked into images".
API_TOKENS_ENV: Final = env_name("API_TOKENS")


class TokenNotAccepted(ExulanicaError):
    """The presented credential does not name a workspace.

    One error for "no token", "unknown token" and "malformed token", because distinguishing them
    tells an unauthenticated caller which of their guesses was closer.
    """


@dataclass(frozen=True, slots=True)
class TokenDirectory:
    """The configured tokens, keyed by digest rather than by the secret itself."""

    #: sha256 hex of the token -> the session it grants.
    sessions: Mapping[str, Session]
    #: sha256 hex of the token -> what that session may do. A digest absent here holds nothing.
    permissions: Mapping[str, frozenset[Permission]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.sessions)

    @property
    def workspaces(self) -> frozenset[uuid.UUID]:
        """Every workspace some configured token can reach.

        This is what a background worker is given, and giving it a value rather than a
        dependency is what keeps the layering true: ``exulanica.ingest`` sits under
        ``exulanica.api``, so a worker that imported this module to ask the question would invert
        the contract and ``uv run lint-imports`` would say so.
        """
        return frozenset(session.workspace_id for session in self.sessions.values())

    def session_for(self, presented: str | None) -> Session:
        """Resolve a bearer token, in constant time, or refuse."""
        return self.grant_for(presented)[0]

    def grant_for(self, presented: str | None) -> tuple[Session, frozenset[Permission]]:
        """Resolve a bearer token to its session and its permissions, in constant time, or refuse.

        The loop runs over every configured token even after a match, and the comparison is
        :func:`secrets.compare_digest`, so neither the number of configured tokens nor which one
        matched is observable from how long this took. The permissions are read by the digest
        that matched, after the loop, so they add nothing to what the timing could separate.
        """
        if not presented:
            raise TokenNotAccepted("no bearer token was presented")
        digest = hashlib.sha256(presented.encode("utf-8")).hexdigest()
        found: str | None = None
        for candidate in self.sessions:
            if secrets.compare_digest(candidate, digest):
                found = candidate
        if found is None:
            raise TokenNotAccepted("the presented bearer token is not configured")
        return self.sessions[found], self.permissions.get(found, frozenset())


def load_token_directory(environ: Mapping[str, str] | None = None) -> TokenDirectory:
    """Read the configured tokens, or raise.

    Raises rather than returning an empty directory. An API that started with no tokens would
    serve 401 to everybody, which reads as a credential problem at the client rather than as a
    deployment that forgot its own configuration.
    """
    environ = os.environ if environ is None else environ
    raw = env_get("API_TOKENS", environ)
    if not raw:
        raise TokenNotAccepted(
            f"{API_TOKENS_ENV} is not set. It is a JSON object mapping a bearer token to "
            '{"workspace_id": "<uuid>", "actor": "<uuid>", "permissions": ["<permission>", ...]}. '
            "There is no default, because a default would be a credential in a repository."
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TokenNotAccepted(f"{API_TOKENS_ENV} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise TokenNotAccepted(f"{API_TOKENS_ENV} must be a non-empty JSON object")

    sessions: dict[str, Session] = {}
    permissions: dict[str, frozenset[Permission]] = {}
    for token, grant in parsed.items():
        if not isinstance(grant, dict):
            raise TokenNotAccepted(f"{API_TOKENS_ENV}: the grant for a token is not an object")
        try:
            session = Session(
                workspace_id=uuid.UUID(grant["workspace_id"]),
                actor=uuid.UUID(grant["actor"]),
                may_include_proposals=bool(grant.get("may_include_proposals", True)),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise TokenNotAccepted(
                f"{API_TOKENS_ENV}: a grant needs workspace_id and actor as uuids ({exc})"
            ) from exc
        if len(token) < 32:
            raise TokenNotAccepted(
                "a bearer token shorter than 32 characters is refused at load time rather than "
                "accepted and relied upon"
            )
        try:
            # Named by the workspace rather than by the token, which is a secret and must not
            # reach a startup log.
            held = parse_permissions(
                grant.get("permissions"),
                where=f"{API_TOKENS_ENV}: the grant for workspace {session.workspace_id}",
            )
        except ValueError as exc:
            raise TokenNotAccepted(str(exc)) from exc
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        sessions[digest] = session
        permissions[digest] = held
    return TokenDirectory(sessions=sessions, permissions=permissions)
