"""The door's two global tables are withheld from the read-only role, whatever a default gave it.

``door_secret`` and ``door_redemption_refusal`` hold every workspace's secrets' digests and every
requester's failures, so no role that reads for a person may read them. Provisioning withholds them
(``exulanica/db/roles.py``), and the door's migration that keeps revoked secrets revokes any grant a
default privilege gave the read-only role between the door's first migration and the next
provisioning. A schema migrated to just below the door's first migration grants ``exulanica_ro`` a
default SELECT on every table its migrating role creates, as an operator might; the door's tables
are then created and the read-only role reads both (the arm before: the default really reaches
them); after the migration that keeps revoked secrets it reads neither.
"""

from __future__ import annotations

import pytest
from exulanica.migrations import migrations
from psycopg import sql
from psycopg.rows import dict_row

import pg_harness

pytestmark = pytest.mark.postgres

#: The door's first migration and the one that keeps revoked secrets, found by name, so a number
#: given at landing changes nothing here.
DOOR = "_an_outside_program_decides_for_a_thing_only_under_its_owner_s_grant.sql"
KEPT = "_a_revoked_door_secret_is_kept_and_a_secret_is_stamped.sql"
WITHHELD = ("door_redemption_refusal", "door_secret")


def _reads(admin) -> dict[str, bool]:
    return {
        row["t"]: row["reads"]
        for row in admin.execute(
            "select t, has_table_privilege('exulanica_ro', t, 'SELECT') as reads "
            "from unnest(%s::text[]) t",
            (list(WITHHELD),),
        ).fetchall()
    }


def test_the_read_only_role_reads_no_global_door_table_whatever_a_default_gave_it(monkeypatch):
    everything = list(migrations())
    [door] = [m for m in everything if m.path.name.endswith(DOOR)]
    [kept] = [m for m in everything if m.path.name.endswith(KEPT)]
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness,
            "migrations",
            lambda: iter(m for m in everything if m.version < door.version),
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            admin.commit()
            admin.autocommit = True
            admin.row_factory = dict_row
            if (
                admin.execute("select 1 from pg_roles where rolname = 'exulanica_ro'").fetchone()
                is None
            ):
                admin.execute("create role exulanica_ro nologin")
            schema = admin.execute("select current_schema() as name").fetchone()["name"]
            admin.execute(
                sql.SQL(
                    "alter default privileges in schema {} grant select on tables to {}"
                ).format(sql.Identifier(schema), sql.Identifier("exulanica_ro"))
            )
            for migration in everything:
                if door.version <= migration.version < kept.version:
                    admin.execute(migration.sql)
            assert _reads(admin) == dict.fromkeys(WITHHELD, True)
            admin.execute(kept.sql)
            assert _reads(admin) == dict.fromkeys(WITHHELD, False)
