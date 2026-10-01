"""The offline restore command, and the product's writers a replay writes withdrawals with.

``exulanica.deletion.restore`` seals the checkpoint, prepares the marker and replays. Most of the
withdrawals it carries it writes by one statement of its own, but two are not a row alone: a
person's retraction also retracts its claim (``AssertionWriter.retract``), and a place-name
withdrawal whose chain gained a grant after the backup is continued as that chain's next decision
(``withdraw_place_name_chain``). Deletion sits below the claim and consent writers and may not
import them, so this module, above both, gives them to replay under the names the withdrawal
catalog uses, and is the command an operator runs:

    python -m exulanica.orchestration.restore checkpoint --checkpoint <file>
    python -m exulanica.orchestration.restore prepare --checkpoint <file> --marker <file>
    python -m exulanica.orchestration.restore replay --checkpoint <file> --marker <file>

A crash recovery, whose source is lost and was never sealed, replays the newest export instead:

    python -m exulanica.orchestration.restore export --directory <custody directory>
    python -m exulanica.orchestration.restore prepare --checkpoint <export> --marker <file> \
        --declaration <file> --max-export-lag-seconds <n>

ADR-0019 states the procedure around these commands.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import psycopg

from exulanica.api.installation import load_installation
from exulanica.consent.place_name_rights import withdraw_place_name_chain
from exulanica.db.session import Database
from exulanica.deletion.restore import (
    checkpoint,
    export_withdrawals,
    loss_window,
    prepare_restore,
    replay,
)
from exulanica.deletion.withdrawals import Writer
from exulanica.env import env_get, resolve_data_dir
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.models.handoff import ModelIdentity
from exulanica.orchestration.installation.custody import (
    DEFAULT_KEEP,
    prune_exports,
    require_newest,
)
from exulanica.store.configured import purging_content_stores

__all__ = ["WRITERS", "main"]


def _retract(connection: psycopg.Connection[Any], row: Mapping[str, Any]) -> None:
    """The person's retraction again, by the product's retract: the row as it was, and the claim.

    Retracting the claim fires what retracting it fires anywhere: a name it carried leaves its
    place or person (migration 0002), and a place-name right resting on it no longer stands
    (0097).
    """
    AssertionWriter(connection, uuid.UUID(row["workspace_id"])).retract(
        uuid.UUID(row["assertion_id"]),
        retracted_by=uuid.UUID(row["retracted_by"]),
        reason=row["reason"],
        retraction_id=uuid.UUID(row["retraction_id"]),
        retracted_at=dt.datetime.fromisoformat(row["retracted_at"]),
    )


def _continue_place_name_chain(connection: psycopg.Connection[Any], row: Mapping[str, Any]) -> None:
    """Withdraw the chain the carried withdrawal ended, after the last decision this backup holds.

    The carried row follows a grant made after the backup, which the backup lacks, so it cannot be
    written as it is. The account holder's decision is the same one: theirs, made at that time,
    ending that place, model and destination's right. It is appended as the next decision of the
    chain this database holds, with a receipt of its own.
    """
    withdraw_place_name_chain(
        connection,
        uuid.UUID(row["workspace_id"]),
        entity_id=uuid.UUID(row["entity_id"]),
        identity=ModelIdentity(
            provider=row["model_provider"],
            role=row["model_role"],
            model_id=row["model_id"],
            revision=row["model_revision"],
        ),
        destination=row["destination"],
        actor=uuid.UUID(row["decided_by"]),
        at=dt.datetime.fromisoformat(row["decided_at"]),
    )


#: The product's writers, under the names ``exulanica/deletion/withdrawals.v2.json`` uses. Replay
#: refuses a set that is not exactly the catalog's.
WRITERS: Final[Mapping[str, Writer]] = {
    "retract": _retract,
    "place_name_chain": _continue_place_name_chain,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("checkpoint", "export", "prepare", "replay"))
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--directory", type=Path, help="where export writes a fresh file")
    parser.add_argument("--marker", type=Path)
    parser.add_argument("--declaration", type=Path, help="a crash recovery's declaration")
    parser.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_KEEP,
        help="how many of the newest exports custody keeps after an export",
    )
    parser.add_argument(
        "--max-export-lag-seconds",
        type=int,
        help="the installation's bound between the newest export and the declared incident",
    )
    args = parser.parse_args(argv)
    if args.action == "export":
        if args.directory is None:
            parser.error("export requires --directory outside both backup domains")
        installation = load_installation(os.environ)
        data_dir = resolve_data_dir()
        # The content store and, where configured, the database's backup sets and stored-byte copy:
        # custody may lie inside none of them.
        domains = [data_dir] + [
            Path(value)
            for name in ("BACKUP_DIRECTORY", "BACKUP_STORE_DIRECTORY")
            if (value := env_get(name))
        ]
        path, _digest = export_withdrawals(
            Database.from_env(),
            args.directory,
            restore_state_path=installation.restore_state_path or args.marker,
            backup_domains=domains,
        )
        print(path)
        backups = env_get("BACKUP_DIRECTORY")
        referenced = _referenced_exports(Path(backups)) if backups else set()
        identity = json.loads(path.read_bytes())["record"]["source_identity"]
        for removed in prune_exports(
            args.directory, source_identity=identity, keep=args.keep, referenced=referenced
        ):
            print(f"removed {removed.name}")
        return 0
    if args.checkpoint is None:
        parser.error(f"{args.action} requires --checkpoint")
    # The API reads the profile's marker at startup: a restore that wrote another could leave a
    # failed restore served.
    declared = load_installation(os.environ).restore_state_path
    if (
        args.marker is not None
        and declared is not None
        and args.marker.resolve() != declared.resolve()
    ):
        parser.error("--marker differs from the profile's restore marker")
    if args.marker is None and declared is not None:
        args.marker = declared
    if args.action == "checkpoint":
        checkpoint(Database.from_env(), args.checkpoint)
    elif args.marker is None:
        parser.error("prepare and replay require --marker outside both backup domains")
    elif args.action == "prepare":
        if args.declaration is not None:
            # A crash recovery replays the newest export in custody, whatever file was named.
            custody = env_get("CUSTODY_DIRECTORY")
            if not custody:
                parser.error(
                    "a declared recovery needs EXULANICA_CUSTODY_DIRECTORY, the custody whose "
                    "newest export it must replay"
                )
            require_newest(args.checkpoint, Path(custody))
        prepare_restore(
            args.checkpoint,
            args.marker,
            declaration_path=args.declaration,
            max_export_lag=_lag_bound(parser, args),
        )
        if (window := loss_window(args.marker)) is not None:
            print(window)
    else:
        purge_url = env_get("PURGE_DATABASE_URL")
        if not purge_url:
            parser.error("PURGE_DATABASE_URL must name the separately provisioned purge role")
        # Replay erases, so it uses the purge identity's stores: on an object store they are
        # built from credentials no runtime process holds.
        replay(
            Database.from_env(),
            Database(purge_url),
            None,
            args.checkpoint,
            args.marker,
            writers=WRITERS,
            stores=purging_content_stores(),
        )
        if (window := loss_window(args.marker)) is not None:
            print(window)
    return 0


def _lag_bound(parser: argparse.ArgumentParser, args: argparse.Namespace) -> dt.timedelta | None:
    """The export lag bound: the profile's, which ``--max-export-lag-seconds`` may only lower."""
    given = args.max_export_lag_seconds
    profile = load_installation(os.environ).profile
    if args.declaration is None:
        return None if given is None else dt.timedelta(seconds=given)
    if profile is None:
        parser.error(
            "a declared recovery takes its export lag bound from EXULANICA_INSTALLATION_PROFILE"
        )
    bound = profile.recovery.max_export_lag_seconds
    if given is not None and given > bound:
        parser.error(f"--max-export-lag-seconds may lower the profile's {bound}, never raise it")
    return dt.timedelta(seconds=bound if given is None else given)


def _referenced_exports(backups: Path) -> set[str]:
    """The exports the backup sets in ``backups`` name, which custody must keep."""
    from exulanica.orchestration.installation.backup_set import BackupSetRefused, read_backup_set

    referenced = set()
    for directory in sorted(backups.iterdir()) if backups.exists() else ():
        try:
            record = read_backup_set(directory).manifest["record"]
        except BackupSetRefused:
            continue
        referenced.add(record["withdrawal_export"]["sha256"])
    return referenced


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
