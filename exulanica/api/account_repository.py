"""Authentication persistence on a dedicated role, before any workspace connection is opened.

Provider verification is a runtime responsibility. This module accepts only that verified issuer
and subject, allocates its own IDs, and never treats a client's email/workspace as authority.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

import psycopg

from exulanica.db.account_workspaces import active_owned_workspaces
from exulanica.selection.validation import Session

ISSUER = "https://accounts.google.com"


class AccountRejected(ValueError):
    """No usable authenticated account/session or login transaction."""


class AccountUnavailable(ValueError):
    """The account provider or deployment boundary is not configured/available."""


def secret_digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def require_secret(value: str | None) -> str:
    if value is None or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", value) is None:
        raise AccountRejected("invalid credential")
    return value


@dataclass(frozen=True)
class AccountSession:
    user_id: uuid.UUID
    session: Session
    csrf_token: str
    expires_at: datetime


class AccountRepository:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def active_owned_workspaces(self) -> frozenset[uuid.UUID]:
        """Workspaces whose owner still has the same authority required by a browser session.

        Background workers call this through the dedicated account role, then open separate
        workspace-scoped application connections. Keeping the query here prevents the world role
        from gaining account-table access just to discover queues. No browser session is required:
        logging out stops a browser credential, while membership/account/workspace revocation
        stops both browser access and background processing.
        """
        return active_owned_workspaces(self.connection)

    def begin_login(
        self,
        *,
        state: str,
        browser: str,
        nonce: str,
        verifier: str,
        config_sha256: str,
        callback_uri: str,
        return_uri: str,
    ) -> None:
        with self.connection.transaction():
            # Bounded opportunistic destruction of expired, never-claimed login secrets.
            self.connection.execute(
                "update account_login_attempt set nonce=null,verifier=null,outcome='expired' "
                "where state_sha256 in (select state_sha256 from account_login_attempt "
                "where outcome='pending' and expires_at<=now() limit 1000 for update skip locked)"
            )
            self.connection.execute(
                "insert into account_login_attempt(state_sha256,browser_sha256,config_sha256,"
                "nonce,verifier,callback_uri,return_uri,expires_at) "
                "values(%s,%s,%s,%s,%s,%s,%s,now()+interval '10 minutes')",
                (
                    secret_digest(require_secret(state)),
                    secret_digest(require_secret(browser)),
                    config_sha256,
                    require_secret(nonce),
                    require_secret(verifier),
                    callback_uri,
                    return_uri,
                ),
            )

    def claim_login(self, state: str, browser: str, config_sha256: str) -> dict:
        # Commit before any network request. A second callback cannot exchange the same flow.
        state_sha = secret_digest(require_secret(state))
        browser_sha = secret_digest(require_secret(browser))
        with self.connection.transaction():
            row = self.connection.execute(
                "select * from account_login_attempt where state_sha256=%s "
                "and browser_sha256=%s and config_sha256=%s and outcome='pending' "
                "and expires_at>now() for update",
                (state_sha, browser_sha, config_sha256),
            ).fetchone()
            if row is None:
                raise AccountRejected("invalid or expired login")
            self.connection.execute(
                "update account_login_attempt set nonce=null,verifier=null,claimed_at=now(),"
                "outcome='claimed' where state_sha256=%s",
                (state_sha,),
            )
            return row

    def fail_login(self, state_sha: str) -> None:
        with self.connection.transaction():
            self.connection.execute(
                "update account_login_attempt set outcome='failed' where state_sha256=%s "
                "and outcome='claimed'",
                (state_sha,),
            )

    def finish_login(
        self,
        attempt: dict,
        *,
        issuer: str,
        subject: str,
        session_seconds: int,
        previous_token: str | None = None,
    ) -> tuple[str, AccountSession]:
        if (
            issuer != ISSUER
            or not isinstance(subject, str)
            or re.fullmatch(r"[\x21-\x7e]{1,255}", subject) is None
        ):
            raise AccountRejected("invalid provider identity")
        if type(session_seconds) is not int or not 60 <= session_seconds <= 86400:
            raise ValueError("session lifetime must be between one minute and one day")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connection.transaction():
            held = self.connection.execute(
                "select 1 from account_login_attempt where state_sha256=%s and outcome='claimed' "
                "and expires_at>now() for update",
                (attempt["state_sha256"],),
            ).fetchone()
            if held is None:
                raise AccountRejected("login no longer usable")
            self.connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s,880058))",
                (issuer + ":" + subject,),
            )
            row = self.connection.execute(
                "select u.* from account_identity i join account_user u using(user_id) "
                "where i.issuer=%s and i.subject=%s for update of u",
                (issuer, subject),
            ).fetchone()
            if row is None:
                user_id, actor, workspace = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
                self.connection.execute(
                    "insert into account_user(user_id,actor_id) values(%s,%s)", (user_id, actor)
                )
                self.connection.execute(
                    "insert into account_identity(issuer,subject,user_id) values(%s,%s,%s)",
                    (issuer, subject, user_id),
                )
                self.connection.execute(
                    "insert into account_workspace(workspace_id,owner_user_id) values(%s,%s)",
                    (workspace, user_id),
                )
                self.connection.execute(
                    "insert into "
                    "account_membership(workspace_id,user_id,membership_role) "
                    "values(%s,%s,'owner')",
                    (workspace, user_id),
                )
            else:
                if row["disabled_at"] is not None:
                    raise AccountRejected("account unavailable")
                user_id, actor = row["user_id"], row["actor_id"]
                member = self.connection.execute(
                    "select m.workspace_id from account_membership m join account_workspace w "
                    "using(workspace_id) where m.user_id=%s and w.owner_user_id=m.user_id "
                    "and m.membership_role='owner' and m.revoked_at is null and "
                    "w.disabled_at is null "
                    "for share of m,w",
                    (user_id,),
                ).fetchone()
                if member is None:
                    raise AccountRejected("account membership unavailable")
                workspace = member["workspace_id"]
            if previous_token is not None:
                try:
                    old_sha = secret_digest(require_secret(previous_token))
                except AccountRejected:
                    pass
                else:
                    self.connection.execute(
                        "update account_browser_session set revoked_at=now() where "
                        "session_sha256=%s and revoked_at is null",
                        (old_sha,),
                    )
            row = self.connection.execute(
                "insert into "
                "account_browser_session(session_sha256,user_id,workspace_id,csrf_token,"
                "login_state_sha256,expires_at) "
                "values(%s,%s,%s,%s,%s,now()+%s*interval '1 second') "
                "returning expires_at",
                (
                    secret_digest(token),
                    user_id,
                    workspace,
                    csrf,
                    attempt["state_sha256"],
                    session_seconds,
                ),
            ).fetchone()
            self.connection.execute(
                "update account_login_attempt set outcome='succeeded' where state_sha256=%s",
                (attempt["state_sha256"],),
            )
            return token, AccountSession(
                user_id, Session(workspace_id=workspace, actor=actor), csrf, row["expires_at"]
            )

    def session(self, token: str | None) -> AccountSession:
        digest = secret_digest(require_secret(token))
        row = self.connection.execute(
            "select s.user_id,s.workspace_id,s.csrf_token,s.expires_at,u.actor_id "
            "from account_browser_session s join account_user u using(user_id) "
            "join account_membership m using(user_id,workspace_id) "
            "join account_workspace w using(workspace_id) where s.session_sha256=%s "
            "and s.revoked_at is null and s.expires_at>now() and u.disabled_at is null "
            "and m.revoked_at is null and m.membership_role='owner' "
            "and w.owner_user_id=u.user_id and w.disabled_at is null",
            (digest,),
        ).fetchone()
        if row is None:
            raise AccountRejected("session unavailable")
        return AccountSession(
            row["user_id"],
            Session(workspace_id=row["workspace_id"], actor=row["actor_id"]),
            row["csrf_token"],
            row["expires_at"],
        )

    def logout(self, token: str) -> None:
        with self.connection.transaction():
            self.connection.execute(
                "update account_browser_session set revoked_at=now() where "
                "session_sha256=%s and revoked_at is null",
                (secret_digest(require_secret(token)),),
            )

    def disable_account(self, user_id: uuid.UUID) -> None:
        """Administrative revocation hook; never renumber evidence actors or erase their history.

        Account/content deletion and provider subject retention policy are separate operations.
        This hook is not exposed as a browser account-deletion endpoint.
        """
        with self.connection.transaction():
            self.connection.execute(
                "update account_user set disabled_at=now() where user_id=%s and "
                "disabled_at is null",
                (user_id,),
            )
            self.connection.execute(
                "update account_browser_session set revoked_at=now() where user_id=%s "
                "and revoked_at is null",
                (user_id,),
            )
