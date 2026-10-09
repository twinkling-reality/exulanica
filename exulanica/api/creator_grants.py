"""``exulanica-creator-grant``: the operator's grant of who may upload from a browser.

A browser session admits a creator's bytes (``POST /workspace-style-packs`` and
``POST /workspace-assets``) only while its account holds the creator grant
(:data:`exulanica.api.permissions.CREATOR_GRANT_ROUTES`). Sign-in makes any Google identity the
owner of a workspace, so this is how an installation where sign-in is open names the accounts that
may upload; a bearer token is the operator's own grant to a program and needs none.

``grant`` and ``revoke`` append an event to the account's chain in ``account_creator_grant_event``
(migration a_creator_uploads_only_under_the_operator_s_grant): numbered from 1, a grant first, the
kinds alternating, each with a reason and the operator as codes, never words. Asking for what the
account already has records nothing. ``list`` names every account that holds the grant now. All
three connect as the account role (``EXULANICA_ACCOUNT_DATABASE_URL``), which resolves browser
sessions and reads the grant there; no route writes it. A revocation is carried across a restore
from an older backup (``exulanica/deletion/withdrawals.v2.json``, kind ``creator_grant``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

from exulanica.db.account_workspaces import ACCOUNT_DATABASE_URL_ENV

__all__ = ["CreatorGrantRefused", "creators", "grant", "main", "revoke"]

#: How long the command waits for the account database to answer before it says so.
_CONNECT_SECONDS = 5

_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}")
_OPERATOR = re.compile(r"[a-z0-9][a-z0-9:._-]{0,95}")


class CreatorGrantRefused(ValueError):
    """The command cannot record what was asked: a code out of shape or an account that is not."""


def _record(
    connection: psycopg.Connection, user_id: uuid.UUID, kind: str, *, reason: str, operator: str
) -> bool:
    if _REASON.fullmatch(reason) is None:
        raise CreatorGrantRefused("a reason is a code: lower case letters, digits and _")
    if _OPERATOR.fullmatch(operator) is None:
        raise CreatorGrantRefused("an operator is a code: lower case letters, digits and :._-")
    with connection.transaction():
        # One account's events are written in turn, so two operators' commands for it never meet
        # the chain's unique number. Taken first, before any read, so the second reads after the
        # first has committed under any isolation level.
        connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s,880059))",
            (f"creator_grant:{user_id}",),
        )
        if (
            connection.execute("select 1 from account_user where user_id=%s", (user_id,)).fetchone()
            is None
        ):
            raise CreatorGrantRefused(f"no account {user_id} is held here")
        last = connection.execute(
            "select sequence,kind from account_creator_grant_event where user_id=%s "
            "order by sequence desc limit 1",
            (user_id,),
        ).fetchone()
        holds = last is not None and last["kind"] == "grant"
        if holds == (kind == "grant"):
            return False
        connection.execute(
            "insert into account_creator_grant_event"
            "(event_id,user_id,sequence,kind,reason,operator) values(%s,%s,%s,%s,%s,%s)",
            (
                uuid.uuid4(),
                user_id,
                (last["sequence"] if last else 0) + 1,
                kind,
                reason,
                operator,
            ),
        )
        return True


def grant(
    connection: psycopg.Connection, user_id: uuid.UUID, *, reason: str, operator: str
) -> bool:
    """Grant ``user_id`` the creator grant. True when this recorded it, False when it is held."""
    return _record(connection, user_id, "grant", reason=reason, operator=operator)


def revoke(
    connection: psycopg.Connection, user_id: uuid.UUID, *, reason: str, operator: str
) -> bool:
    """Revoke ``user_id``'s creator grant. True when this recorded it, False when none is held."""
    return _record(connection, user_id, "revoke", reason=reason, operator=operator)


def creators(connection: psycopg.Connection) -> list[dict[str, Any]]:
    """Every account holding the creator grant now, with the grant that holds it."""
    rows = connection.execute(
        "select * from (select distinct on (user_id) user_id,kind,reason,operator,recorded_at "
        "from account_creator_grant_event order by user_id,sequence desc) newest "
        "where kind='grant' order by recorded_at,user_id"
    ).fetchall()
    return [
        {
            "user_id": str(row["user_id"]),
            "granted_at": row["recorded_at"].isoformat(),
            "reason": row["reason"],
            "operator": row["operator"],
        }
        for row in rows
    ]


def main(
    argv: Sequence[str] | None = None,
    *,
    stream: Any = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="exulanica-creator-grant",
        description="Grant or revoke an account's creator grant, or list who holds it.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="every account that holds the creator grant")
    for name, purpose in (("grant", "let an account upload"), ("revoke", "stop its uploads")):
        command = commands.add_parser(name, help=purpose)
        command.add_argument("--user", type=uuid.UUID, required=True)
        command.add_argument("--reason", required=True)
        command.add_argument("--operator", required=True)
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    url = (os.environ if environ is None else environ).get(ACCOUNT_DATABASE_URL_ENV)
    if not url:
        print(f"exulanica-creator-grant: {ACCOUNT_DATABASE_URL_ENV} is required", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(
            url, autocommit=True, row_factory=dict_row, connect_timeout=_CONNECT_SECONDS
        ) as connection:
            if args.command == "list":
                document: Any = {"creators": creators(connection)}
            else:
                write = grant if args.command == "grant" else revoke
                recorded = write(connection, args.user, reason=args.reason, operator=args.operator)
                document = {"user_id": str(args.user), "kind": args.command, "recorded": recorded}
    except CreatorGrantRefused as refused:
        print(f"exulanica-creator-grant: {refused}", file=sys.stderr)
        return 1
    except psycopg.Error as error:
        # The database's own refusal by its message: a sealed restore checkpoint refuses every
        # grant event, and an account database that does not answer is said so.
        message = (error.diag.message_primary if error.diag else None) or str(error)
        print(f"exulanica-creator-grant: {message}", file=sys.stderr)
        return 1
    print(json.dumps(document, sort_keys=True), file=output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
