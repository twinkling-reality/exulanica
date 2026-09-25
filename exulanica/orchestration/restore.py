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

ADR-0019 states the procedure around these commands.
"""

from __future__ import annotations

import argparse
import datetime as dt
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import psycopg

from exulanica.consent.place_name_rights import withdraw_place_name_chain
from exulanica.db.session import Database
from exulanica.deletion.restore import checkpoint, prepare_restore, replay
from exulanica.deletion.withdrawals import Writer
from exulanica.env import env_get, resolve_data_dir
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.models.handoff import ModelIdentity
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import BLOB_NAMESPACE, material_stores

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
    parser.add_argument("action", choices=("checkpoint", "prepare", "replay"))
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--marker", type=Path)
    args = parser.parse_args(argv)
    if args.action == "checkpoint":
        checkpoint(Database.from_env(), args.checkpoint)
    elif args.marker is None:
        parser.error("prepare and replay require --marker outside both backup domains")
    elif args.action == "prepare":
        prepare_restore(args.checkpoint, args.marker)
    else:
        purge_url = env_get("PURGE_DATABASE_URL")
        if not purge_url:
            parser.error("PURGE_DATABASE_URL must name the separately provisioned purge role")
        data_dir = resolve_data_dir()
        replay(
            Database.from_env(),
            Database(purge_url),
            LocalContentAddressedStore(data_dir / BLOB_NAMESPACE),
            args.checkpoint,
            args.marker,
            writers=WRITERS,
            materials=material_stores(data_dir),
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
