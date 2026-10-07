"""An operator's spending commands.

    python -m exulanica.spending issue --provider nebius_token_factory --ceiling-usd 5 \\
        --max-calls 2000 --valid-until 2026-12-31T00:00:00Z --operator ops --reason "..."
    python -m exulanica.spending grant --authority <id> --workspace <id> --ceiling-usd 1 ...
    python -m exulanica.spending status --workspace <id>

Run with an administrative database URL (``EXULANICA_DATABASE_URL``, a role with SUPERUSER or
BYPASSRLS) and the installation's witness directory (``EXULANICA_SPENDING_WITNESS_DIR``). Every
command prints one JSON document. ``--operator`` is a label for the record, never a name, an
address or a key: lower case letters, digits and ``:._-``.

``issue`` names the authority on standard error before it is issued, so an answer that never
arrives is asked again with ``--authority-id``, which never issues a second authority. A step
that committed and whose witness record could not then be confirmed answers as done, with
``"witness_confirmed": false``: asking again would repeat it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from exulanica.db.session import Database
from exulanica.env import env_get
from exulanica.spending.operator import SpendingOperationRefused, SpendingOperator
from exulanica.spending.status import authority_states, workspace_status
from exulanica.spending.witness import FileSpendingWitness, WitnessUnavailable

__all__ = ["main"]


def _instant(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("an instant names its offset, for example Z")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m exulanica.spending", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    def terms(command: argparse.ArgumentParser) -> None:
        command.add_argument("--ceiling-usd", type=Decimal, required=True)
        command.add_argument("--max-calls", type=int, required=True)
        command.add_argument("--valid-until", type=_instant, required=True)

    def decided(command: argparse.ArgumentParser, *, reason: bool = True) -> None:
        command.add_argument("--operator", required=True)
        if reason:
            command.add_argument("--reason", required=True)

    issue = commands.add_parser("issue", help="issue an authority for one provider")
    issue.add_argument("--provider", required=True)
    terms(issue)
    issue.add_argument("--dispatch-seconds", type=int, default=60)
    issue.add_argument(
        "--unwitnessed",
        action="store_true",
        help="no restore protection: for development and tests only",
    )
    issue.add_argument(
        "--authority-id",
        type=uuid.UUID,
        help="the authority's identifier; asking again with it never issues a second authority",
    )
    decided(issue)

    adjust = commands.add_parser("adjust", help="new terms for an authority, as a new epoch")
    adjust.add_argument("--authority", type=uuid.UUID, required=True)
    terms(adjust)
    decided(adjust)

    grant = commands.add_parser("grant", help="grant a workspace an allowance under an authority")
    grant.add_argument("--authority", type=uuid.UUID, required=True)
    grant.add_argument("--workspace", type=uuid.UUID, required=True)
    terms(grant)
    decided(grant)

    guest = commands.add_parser(
        "guest-policy",
        help="set the figures every guest workspace is granted under an authority, once each",
    )
    guest.add_argument("--authority", type=uuid.UUID, required=True)
    guest.add_argument("--ceiling-usd", type=Decimal, required=True)
    guest.add_argument("--max-calls", type=int, required=True)
    guest.add_argument("--valid-for-days", type=int, required=True)
    guest.add_argument("--grants-per-day", type=int, required=True)
    decided(guest)

    withdraw_guest = commands.add_parser(
        "guest-policy-withdraw",
        help="end an authority's guest policy: no guest is granted anything until another is set",
    )
    withdraw_guest.add_argument("--authority", type=uuid.UUID, required=True)
    decided(withdraw_guest)

    revoke = commands.add_parser("revoke", help="revoke an authority, or a grant or bound of it")
    revoke.add_argument("--authority", type=uuid.UUID, required=True)
    revoke.add_argument("--workspace", type=uuid.UUID)
    revoke.add_argument("--grant", type=uuid.UUID)
    decided(revoke)

    reconcile = commands.add_parser(
        "reconcile", help="reconcile one attempt of unknown outcome to what evidence shows"
    )
    reconcile.add_argument("--workspace", type=uuid.UUID, required=True)
    reconcile.add_argument("--reservation", type=uuid.UUID, required=True)
    reconcile.add_argument("--usd", type=Decimal, required=True)
    reconcile.add_argument("--source", required=True)
    reconcile.add_argument("--reference", required=True)
    reconcile.add_argument("--observed-at", type=_instant, required=True)
    decided(reconcile, reason=False)

    restore = commands.add_parser(
        "reconcile-restore",
        help="carry a restored ledger forward to its witness, live or a copy from custody",
    )
    restore.add_argument("--authority", type=uuid.UUID, required=True)
    decided(restore)

    reauthorize = commands.add_parser(
        "reauthorize", help="explicit new terms that end a suspension"
    )
    reauthorize.add_argument("--authority", type=uuid.UUID, required=True)
    terms(reauthorize)
    reauthorize.add_argument(
        "--discard-witness",
        action="store_true",
        help="discard a witness or copy that may hold spending the ledger lacks",
    )
    decided(reauthorize)

    expire = commands.add_parser(
        "expire",
        help="release every workspace's attempts never dispatched in time (run it on a schedule)",
    )
    expire.add_argument("--authority", type=uuid.UUID, required=True)
    expire.add_argument("--limit", type=int, default=1000)

    verify = commands.add_parser("verify", help="check an authority's ledger chain")
    verify.add_argument("--authority", type=uuid.UUID, required=True)

    copy = commands.add_parser(
        "install-witness-copy",
        help="install a retained witness copy; the authority stays suspended until reauthorized",
    )
    copy.add_argument("--authority", type=uuid.UUID, required=True)
    copy.add_argument("--from", dest="source", type=Path, required=True)

    status = commands.add_parser(
        "status", help="one workspace's spending, or every authority's state (--authorities)"
    )
    which = status.add_mutually_exclusive_group(required=True)
    which.add_argument("--workspace", type=uuid.UUID)
    which.add_argument("--authorities", action="store_true")
    return parser


def _run(arguments: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    database = Database.from_env(environ)
    directory = env_get("SPENDING_WITNESS_DIR", environ)
    operator = SpendingOperator(
        database, FileSpendingWitness(Path(directory)) if directory else None
    )
    document = _decided(operator, database, arguments)
    if operator.last_witness_confirmed is False:
        # The step committed; only its record's confirmation failed. Asking again would repeat it.
        document = {**document, "witness_confirmed": False}
    return document


def _decided(
    operator: SpendingOperator, database: Database, arguments: argparse.Namespace
) -> dict[str, Any]:
    command = arguments.command
    if command == "issue":
        # Named before the step, so an answer that never arrives can be asked again by this name.
        authority_id = arguments.authority_id or uuid.uuid4()
        print(
            json.dumps({"issuing": str(authority_id), "ask_again_with": "--authority-id"}),
            file=sys.stderr,
        )
        authority = operator.issue(
            authority_id=authority_id,
            provider=arguments.provider,
            ceiling_usd=arguments.ceiling_usd,
            max_calls=arguments.max_calls,
            valid_until=arguments.valid_until,
            dispatch_seconds=arguments.dispatch_seconds,
            witnessed=not arguments.unwitnessed,
            operator=arguments.operator,
            reason=arguments.reason,
        )
        return {"authority_id": str(authority)}
    if command == "adjust":
        epoch = operator.adjust(
            arguments.authority,
            ceiling_usd=arguments.ceiling_usd,
            max_calls=arguments.max_calls,
            valid_until=arguments.valid_until,
            operator=arguments.operator,
            reason=arguments.reason,
        )
        return {"epoch": epoch}
    if command == "guest-policy":
        policy = operator.set_guest_policy(
            arguments.authority,
            ceiling_usd=arguments.ceiling_usd,
            max_calls=arguments.max_calls,
            valid_for_days=arguments.valid_for_days,
            grants_per_day=arguments.grants_per_day,
            operator=arguments.operator,
            reason=arguments.reason,
        )
        return {"policy_id": str(policy)}
    if command == "guest-policy-withdraw":
        outcome = operator.withdraw_guest_policy(
            arguments.authority, operator=arguments.operator, reason=arguments.reason
        )
        return {"outcome": outcome}
    if command == "grant":
        grant = operator.grant(
            arguments.authority,
            arguments.workspace,
            ceiling_usd=arguments.ceiling_usd,
            max_calls=arguments.max_calls,
            valid_until=arguments.valid_until,
            operator=arguments.operator,
            reason=arguments.reason,
        )
        return {"grant_id": str(grant)}
    if command == "revoke":
        outcome = operator.revoke(
            arguments.authority,
            workspace_id=arguments.workspace,
            grant_id=arguments.grant,
            operator=arguments.operator,
            reason=arguments.reason,
        )
        return {"outcome": outcome}
    if command == "reconcile":
        operator.reconcile(
            arguments.workspace,
            arguments.reservation,
            usd=arguments.usd,
            source=arguments.source,
            reference=arguments.reference,
            observed_at=arguments.observed_at,
            operator=arguments.operator,
        )
        return {"outcome": "reconciled"}
    if command == "reconcile-restore":
        document = operator.reconcile_restore(
            arguments.authority, operator=arguments.operator, reason=arguments.reason
        )
        answer = {key: value for key, value in document.items() if key != "witness"}
        # A restored database can hold a guest policy the operator had replaced or withdrawn; it
        # grants nothing until set again, and this says which.
        answer["guest_policies"] = [
            policy
            for policy in operator.guest_policies()
            if policy["authority_id"] == str(arguments.authority)
        ]
        return answer
    if command == "reauthorize":
        epoch = operator.reauthorize(
            arguments.authority,
            ceiling_usd=arguments.ceiling_usd,
            max_calls=arguments.max_calls,
            valid_until=arguments.valid_until,
            operator=arguments.operator,
            reason=arguments.reason,
            discard_witness=arguments.discard_witness,
        )
        return {"epoch": epoch}
    if command == "expire":
        return {"released": operator.expire(arguments.authority, limit=arguments.limit)}
    if command == "verify":
        return operator.verify_chain(arguments.authority)
    if command == "install-witness-copy":
        operator.install_witness_copy(arguments.authority, arguments.source)
        return {"outcome": "installed", "state": "copy"}
    if command == "status":
        if arguments.authorities:
            return {
                "authorities": authority_states(database),
                "guest_policies": operator.guest_policies(),
            }
        return workspace_status(database, arguments.workspace)
    raise AssertionError(command)


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        document = _run(arguments, os.environ if environ is None else environ)
    except (SpendingOperationRefused, WitnessUnavailable, ValueError) as exc:
        print(json.dumps({"refused": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(document, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
