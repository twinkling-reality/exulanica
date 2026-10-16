"""Write the moments of the minutes a workspace's societies played before moments were written.

    python -m exulanica.api.moments_backfill --workspace <uuid> [--version <uuid>]... [--apply]

A minute writes its moments as it is played (``docs/synthetic-society-contract.md``, "A world's
moments"), so a society played before then has none and its History starts where moments started.
This one-shot replays each society of the workspace from what it stored, asking nothing again, and
hands every verified minute to the rule the minute's own hook runs
(:func:`exulanica.world.society_moments.backfill`), each minute formed from the moments before it
alone. A moment's id is derived from its version, its rule and the event it is anchored on, so a
moment already written is left as it is and a second run writes nothing.

Run it once, before the workspace's societies play on under code that writes moments: a minute
played in between is formed without the earlier moments, so a meeting before it can be told twice.

It runs as the runtime role, as the API does, and refuses an owner or a superuser, a schema it does
not recognise and a restored database whose withdrawals are not replayed. Each stored input is
authorized by the society runtime the API authorizes it with, so a society whose input is no longer
authorized is refused by name and none of its moments are written. A society is replayed in one
transaction under its workspace's lock, the lock a minute is played under: a back-fill waits for a
minute in progress and the next minute waits for it. Without ``--apply`` every transaction is
rolled back and the run reports what it would write. Every engine's minutes are handed over but a
legacy society's, which is passed over: its minutes record arrivals and departures, which make no
moment.

It asks no model and needs no provider key. Each society is one line of JSON on standard output and
the run ends with a line of totals; it exits 1 when any society was refused, and says
``startup_failed`` or ``run_failed`` (the workspace could not be read) when it wrote nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

import psycopg

from exulanica.world.society import SocietyError
from exulanica.world.society_engines import society_engine
from exulanica.world.society_moments import backfill
from exulanica.world.society_repository import SocietyRepository

__all__ = ["BACKFILL_ACTOR", "backfill_workspace", "main"]

#: The actor a back-fill's session names. Authorizing a stored input reads its workspace and the
#: world's records, never who asks, so this names the installation's one-shot, not a person.
BACKFILL_ACTOR: Final = uuid.uuid5(uuid.NAMESPACE_URL, "exulanica:installation:moments-backfill")


def _emit(stream: Any, event: str, **fields: Any) -> None:
    print(
        json.dumps({"component": "moments-backfill", "event": event, **fields}, sort_keys=True),
        file=stream,
        flush=True,
    )


def _moments(connection: Any, workspace_id: uuid.UUID, society_id: uuid.UUID) -> int:
    row = connection.execute(
        "select count(*) as moments from world_society_moment "
        "where workspace_id=%s and society_id=%s",
        (workspace_id, society_id),
    ).fetchone()
    return int(row["moments"])


def _one(
    connection: Any, runtime: Any, session: Any, society: Mapping[str, Any], apply: bool
) -> dict[str, Any]:
    """Back-fill one society in a transaction of its own; answers its report."""
    report: dict[str, Any] = {
        "world_id": society["world_id"],
        "version_id": str(society["version_id"]),
        "engine": society["engine_version"],
        "minutes": int(society["current_tick"]),
    }
    try:
        family = society_engine(society["engine_version"]).state_family
    except ValueError as error:
        return report | {"outcome": "refused", "reason": type(error).__name__, "detail": str(error)}
    if family == "legacy":
        return report | {"outcome": "passed_over", "reason": "legacy_engine"}
    workspace_id = session.workspace_id
    repository = SocietyRepository(
        connection,
        workspace_id,
        world_id=society["world_id"],
        input_authorizer=lambda document: runtime.authorize(connection, session, document),
    )
    before = seen = after = 0
    try:
        before = _moments(connection, workspace_id, society["society_id"])
        with connection.transaction():
            seen = backfill(
                repository.replay, connection, workspace_id, society, society["version_id"]
            )
            after = _moments(connection, workspace_id, society["society_id"])
            if not apply:
                raise psycopg.Rollback()
    except (SocietyError, ValueError, psycopg.Error) as error:
        # A replay that does not verify, an input no longer authorized, or the database refusing
        # this society's statements: its transaction is rolled back, nothing of it is written, and
        # the next society is still back-filled.
        return report | {"outcome": "refused", "reason": type(error).__name__, "detail": str(error)}
    return report | {
        "outcome": "written" if apply else "would_write",
        "minutes_seen": seen,
        "moments_before": before,
        "moments": after - before,
    }


def backfill_workspace(
    runtime: Any,
    database: Any,
    workspace_id: uuid.UUID,
    *,
    versions: Iterable[uuid.UUID] = (),
    apply: bool = False,
) -> list[dict[str, Any]]:
    """Back-fill every society of ``workspace_id`` (or only those of ``versions``), each in its own
    transaction, authorizing stored inputs through ``runtime`` (the API's society runtime). Answers
    one report a society, in the order of its world and version, and one ``refused`` report for a
    named version the workspace has no society for."""
    from exulanica.selection.validation import Session

    wanted = frozenset(versions)
    session = Session(workspace_id=workspace_id, actor=BACKFILL_ACTOR)
    reports: list[dict[str, Any]] = []
    with database.session(workspace_id) as connection:
        societies = connection.execute(
            "select society_id, world_id, version_id, engine_version, current_tick "
            "from world_society where workspace_id=%s order by world_id, version_id",
            (workspace_id,),
        ).fetchall()
        found = {society["version_id"] for society in societies}
        for society in societies:
            if wanted and society["version_id"] not in wanted:
                continue
            reports.append(_one(connection, runtime, session, society, apply))
    for version in sorted(wanted - found, key=str):
        reports.append(
            {"version_id": str(version), "outcome": "refused", "reason": "no_society_for_version"}
        )
    return reports


def main(
    argv: Sequence[str] | None = None,
    *,
    services: Any = None,
    stream: Any = None,
) -> int:
    """Back-fill a workspace's moments; ``services`` is injectable so a test can pass its own."""
    parser = argparse.ArgumentParser(
        prog="python -m exulanica.api.moments_backfill",
        description=(
            "Write the moments of minutes played before moments were written. Run it once, before "
            "the workspace's worlds play on."
        ),
    )
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    parser.add_argument(
        "--version", type=uuid.UUID, action="append", default=[], help="only this world version"
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the moments (default: report and roll back)"
    )
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    try:
        if services is None:
            from exulanica.api.services import build_services

            services = build_services(spending_label="moments-backfill")
        from exulanica.db.migrate import verify_schema
        from exulanica.db.roles import assert_runtime_role
        from exulanica.deletion.restore import verify_restore

        verify_schema(services.database)
        with services.database.unscoped() as connection:
            assert_runtime_role(connection)
        verify_restore(services.database, services.restore_state_path)
        if services.society_runtime is None:
            raise ValueError(
                "this environment configures no society runtime, so no stored input can be "
                "authorized"
            )
    except Exception as error:
        _emit(output, "startup_failed", failure_class=type(error).__name__, message=str(error))
        return 1
    try:
        reports = backfill_workspace(
            services.society_runtime,
            services.database,
            args.workspace,
            versions=args.version,
            apply=args.apply,
        )
    except Exception as error:
        # Not one society's refusal (those are reported and the run goes on): the workspace
        # could not be read at all.
        _emit(output, "run_failed", failure_class=type(error).__name__, message=str(error))
        return 1
    for report in reports:
        _emit(output, "society", workspace_id=str(args.workspace), **report)
    refused = sum(1 for report in reports if report["outcome"] == "refused")
    _emit(
        output,
        "finished",
        workspace_id=str(args.workspace),
        apply=args.apply,
        societies=len(reports),
        refused=refused,
        moments=sum(int(report.get("moments", 0)) for report in reports),
    )
    return 1 if refused else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
