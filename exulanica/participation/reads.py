"""Read the observer's SQL projections without access to any host workspace table."""

from __future__ import annotations

from contextlib import AbstractContextManager

import psycopg

from exulanica.db.participant_role import PARTICIPANT_COLUMNS, participant_connection
from exulanica.db.session import Database
from exulanica.participation import projection
from exulanica.participation.repository import ParticipantScope, ParticipationRefused


def _connection(
    database: Database, scope: ParticipantScope
) -> AbstractContextManager[psycopg.Connection]:
    return participant_connection(
        database,
        workspace_id=scope.workspace_id,
        grant_id=scope.grant_id,
        principal_sha256=scope.principal_sha256,
    )


def world(database: Database, scope: ParticipantScope) -> dict:
    with _connection(database, scope) as connection:
        row = connection.execute("select * from participant_world").fetchone()
        if row is None:
            raise ParticipationRefused()
        objects = connection.execute(
            "select * from participant_objects order by object_id"
        ).fetchall()
        things = connection.execute("select * from participant_things order by thing_id").fetchall()
    return {
        "world_id": row["world_id"],
        "version_id": str(row["version_id"]),
        "kind": row["kind"],
        "edit_seq": row["edit_seq"],
        "state_sha256": row["state_sha256"],
        "objects": [
            {key: o[key] for key in PARTICIPANT_COLUMNS["participant_objects"]} for o in objects
        ],
        "things": [
            {key: t[key] for key in PARTICIPANT_COLUMNS["participant_things"]} for t in things
        ],
    }


def society(database: Database, scope: ParticipantScope) -> dict:
    with _connection(database, scope) as connection:
        row = connection.execute("select * from participant_society").fetchone()
        if row is None:
            raise ParticipationRefused()
        clock = connection.execute("select * from participant_clock").fetchone()
        choices = connection.execute(
            "select choice_seq,document from participant_choices order by choice_seq"
        ).fetchall()
    return projection.society(row) | {"clock": clock, "choices": choices}
