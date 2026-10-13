"""The lifecycle of one browser-bound observation grant in its creator's workspace."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import sha256_of_canonical
from exulanica.errors import ExulanicaError
from exulanica.participation.contracts import (
    NOTICE,
    ROLE,
    issue_expiry,
    notice_reference,
    revision_document,
    utc_instant,
    validate_revision,
)
from exulanica.participation.identity import (
    grant_actor,
    grant_id,
    principal_matches,
    principal_sha256,
)
from exulanica.world.workspace_lock import lock_workspace

INVITE_LIFETIME = timedelta(minutes=15)
REFUSALS_PER_MINUTE = 10
Eligibility = Callable[[psycopg.Connection, uuid.UUID, str, uuid.UUID], object]


class ParticipationRefused(ExulanicaError):
    """One non-enumerating refusal for absent, ended and differently bound grants."""

    status = 404
    code = "unknown_reference"
    detail = "nothing at this address is available to this credential"

    def __init__(self) -> None:
        super().__init__(self.detail)


class InvitationConflict(ExulanicaError):
    status = 409
    code = "invitation_conflict"
    detail = "this issue key already names a different invitation"


class RedemptionLimited(ExulanicaError):
    status = 429
    code = "redemption_limited"
    detail = "too many refused invitations; try again in one minute"


@dataclass(frozen=True, slots=True)
class ParticipantScope:
    workspace_id: uuid.UUID
    grant_id: uuid.UUID
    world_id: str
    version_id: uuid.UUID
    principal_sha256: str


def secret_sha256(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class InvitationRepository:
    """Trusted lifecycle persistence. Its owner connection is never given to participant routes."""

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self.connection = connection
        self.workspace_id = workspace_id

    def row(self, grant: uuid.UUID) -> dict:
        row = self.connection.execute(
            "select g.world_id,g.grant_id,g.issued_at,r.version_id,r.expires_at,r.document,"
            "r.document_sha256,p.principal_sha256,p.notice_sha256,e.used_at,e.revoked_at,"
            "e.expires_at as redeem_before,"
            "e.grant_id is not null as has_entry,v.revoked_at as grant_revoked_at,d.departed_at,"
            "statement_timestamp() as now from world_grant g "
            "join lateral (select * from world_grant_revision where workspace_id=g.workspace_id "
            "and grant_id=g.grant_id order by grant_seq desc limit 1) r on true "
            "left join world_grant_principal p on p.workspace_id=g.workspace_id and "
            "p.grant_id=g.grant_id "
            "left join world_grant_entry e on e.workspace_id=g.workspace_id and "
            "e.grant_id=g.grant_id "
            "left join world_grant_revocation v on v.workspace_id=g.workspace_id and "
            "v.grant_id=g.grant_id "
            "left join world_grant_departure d on d.workspace_id=g.workspace_id and "
            "d.grant_id=g.grant_id "
            "where g.workspace_id=%s and g.grant_id=%s",
            (self.workspace_id, grant),
        ).fetchone()
        if row is None:
            raise ParticipationRefused()
        try:
            document = validate_revision(row["document"])
            valid = (
                sha256_of_canonical(document).hex() == row["document_sha256"]
                and document["version_id"] == str(row["version_id"])
                and document["expires_at"] == row["expires_at"].isoformat(timespec="microseconds")
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ParticipationRefused()
        return row

    @staticmethod
    def state(row: dict) -> str:
        if row["departed_at"] is not None:
            return "departed"
        if row["grant_revoked_at"] is not None or row["revoked_at"] is not None:
            return "revoked"
        if row["expires_at"] <= row["now"]:
            return "expired"
        if not row["has_entry"]:
            return "void"
        if row["principal_sha256"] is None and row["redeem_before"] <= row["now"]:
            return "expired"
        return "bound" if row["principal_sha256"] is not None else "issued"

    @classmethod
    def view(cls, row: dict) -> dict:
        return {
            "grant_id": str(row["grant_id"]),
            "world_id": row["world_id"],
            "version_id": str(row["version_id"]),
            "state": cls.state(row),
            "expires_at": row["expires_at"].isoformat(),
            "world_words": row["document"]["world_words"],
            "role": dict(ROLE),
            "notice": dict(NOTICE),
            "notice_sha256": notice_reference()["sha256"],
            "redeem_before": row["redeem_before"].isoformat() if row["redeem_before"] else None,
        }

    def issue(
        self,
        world: str,
        version: uuid.UUID,
        *,
        key: uuid.UUID,
        actor: uuid.UUID,
        expires_at: datetime,
        world_words: str,
        eligible: Eligibility,
    ) -> dict:
        with self.connection.transaction():
            lock_workspace(self.connection, self.workspace_id)
            now = self.connection.execute("select statement_timestamp() as now").fetchone()["now"]
            expiry = utc_instant(expires_at)
            grant = grant_id(self.workspace_id, key)
            document = revision_document(grant, version, expiry, world_words)
            existing = self.connection.execute(
                "select world_id from world_grant where workspace_id=%s and grant_id=%s",
                (self.workspace_id, grant),
            ).fetchone()
            if existing is not None:
                row = self.row(grant)
                if row["document"] != document or row["world_id"] != world:
                    raise InvitationConflict()
                return self.view(row) | {"invitation": None}
            issue_expiry(expiry, now=now)
            eligible(self.connection, self.workspace_id, world, version)
            secret = secrets.token_urlsafe(32)
            self.connection.execute(
                "insert into world_grant(workspace_id,grant_id,world_id,issued_by) "
                "values(%s,%s,%s,%s)",
                (self.workspace_id, grant, world, actor),
            )
            self.connection.execute(
                "insert into world_grant_revision(workspace_id,grant_id,grant_seq,version_id,"
                "expires_at,document,document_sha256,recorded_by) values(%s,%s,1,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    grant,
                    version,
                    expiry,
                    Jsonb(document),
                    sha256_of_canonical(document).hex(),
                    actor,
                ),
            )
            self.connection.execute(
                "insert into world_grant_entry(grant_id,workspace_id,secret_sha256,expires_at) "
                "values(%s,%s,%s,%s)",
                (
                    grant,
                    self.workspace_id,
                    secret_sha256(secret),
                    min(expiry, now + INVITE_LIFETIME),
                ),
            )
            return self.view(self.row(grant)) | {"invitation": secret}

    def listed(self, world: str, *, after: uuid.UUID | None = None, limit: int = 50) -> dict:
        rows = self.connection.execute(
            "select grant_id from world_grant where workspace_id=%s and world_id=%s "
            "and (%s::uuid is null or grant_id>%s) order by grant_id limit %s",
            (self.workspace_id, world, after, after, limit + 1),
        ).fetchall()
        return {
            "invitations": [self.view(self.row(r["grant_id"])) for r in rows[:limit]],
            "next": str(rows[limit - 1]["grant_id"]) if len(rows) > limit else None,
        }

    def redeem(
        self, grant: uuid.UUID, secret: str, actor: uuid.UUID, notice: str, *, eligible: Eligibility
    ) -> dict:
        with self.connection.transaction():
            lock_workspace(self.connection, self.workspace_id)
            row = self.row(grant)
            if self.state(row) != "issued" or notice != notice_reference()["sha256"]:
                raise ParticipationRefused()
            eligible(self.connection, self.workspace_id, row["world_id"], row["version_id"])
            consumed = self.connection.execute(
                "update world_grant_entry set used_at=statement_timestamp() where workspace_id=%s "
                "and grant_id=%s and secret_sha256=%s and used_at is null and revoked_at is null "
                "and expires_at>statement_timestamp() returning grant_id",
                (self.workspace_id, grant, secret_sha256(secret)),
            ).fetchone()
            if consumed is None:
                raise ParticipationRefused()
            self.connection.execute(
                "insert into world_grant_principal(workspace_id,grant_id,"
                "principal_sha256,notice_sha256) "
                "values(%s,%s,%s,%s)",
                (self.workspace_id, grant, principal_sha256(grant, actor), notice),
            )
            return self.view(self.row(grant))

    def scope(
        self, grant: uuid.UUID, actor: uuid.UUID, *, eligible: Eligibility
    ) -> ParticipantScope:
        row = self.row(grant)
        if (
            self.state(row) != "bound"
            or row["used_at"] is None
            or not principal_matches(grant, actor, row["principal_sha256"])
            or row["notice_sha256"] != notice_reference()["sha256"]
        ):
            raise ParticipationRefused()
        eligible(self.connection, self.workspace_id, row["world_id"], row["version_id"])
        return ParticipantScope(
            self.workspace_id, grant, row["world_id"], row["version_id"], row["principal_sha256"]
        )

    def revoke(self, grant: uuid.UUID, actor: uuid.UUID) -> dict:
        with self.connection.transaction():
            lock_workspace(self.connection, self.workspace_id)
            self.row(grant)
            self.connection.execute(
                "insert into world_grant_revocation(workspace_id,grant_id,revoked_by) "
                "values(%s,%s,%s) on conflict(workspace_id,grant_id) do nothing",
                (self.workspace_id, grant, actor),
            )
            return self.view(self.row(grant))

    def leave(self, grant: uuid.UUID, actor: uuid.UUID, *, eligible: Eligibility) -> None:
        with self.connection.transaction():
            lock_workspace(self.connection, self.workspace_id)
            self.scope(grant, actor, eligible=eligible)
            tombstone = self.connection.execute(
                "insert into tombstone(workspace_id,scope,requested_by,reason) "
                "values(%s,'participation',%s,'a participant left an invitation permanently') "
                "returning tombstone_id",
                (self.workspace_id, grant_actor(grant)),
            ).fetchone()["tombstone_id"]
            self.connection.execute(
                "insert into world_grant_departure(workspace_id,grant_id,tombstone_id) "
                "values(%s,%s,%s)",
                (self.workspace_id, grant, tombstone),
            )
