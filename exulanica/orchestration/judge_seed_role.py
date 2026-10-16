"""The database role a judge deployment's API connects as, and the bearer token that reaches it.

:func:`provision_judge_role` creates the role and grants it reading and an allowlist of writes,
:data:`JUDGE_WRITE_TABLES` and :data:`JUDGE_INSERT_ONLY_TABLES`. :func:`judge_grants` reads back
what the role holds from the live catalog, and :func:`judge_grant_mismatches` names each table
where that differs from the allowlist. :func:`mint_judge_token` builds the token directory the
deployment serves, whose grant carries :data:`JUDGE_PERMISSIONS`.
:mod:`exulanica.orchestration.judge_seed` exports these with the seed's operations.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Final

import psycopg
from psycopg import sql

from exulanica.db.roles import (
    SPENDING_ADMIN_TABLES,
    SPENDING_READ_FUNCTIONS,
    take_provisioning_locks,
)
from exulanica.orchestration.judge_seed_archive import SeedRefused

#: The role the judge deployment's API connects as. Not ``exulanica_app``: the point of the
#: deployment is that it cannot write a source row or a deletion marker even if a route tried,
#: and a database role is the only place that can be true rather than merely intended.
JUDGE_ROLE: Final = "exulanica_judge"

#: Tables the judge role may write, and nothing else in the schema.
#:
#: Derived from the routes a judge is given rather than from a category: create a sandbox version
#: and edit the objects in it, preview and apply an appearance, and let the Companion record what
#: it was asked and answered. Everything absent is readable and not writable.
#:
#: ``capture``, ``intake_batch``, ``artifact``, ``blob``, ``entity_link``, ``identity_event``,
#: ``person_subject``, ``person_withdrawal_receipt``, ``tombstone`` and ``purge_job`` are what
#: this is about, and they are absent because absence is the grant.
JUDGE_WRITE_TABLES: Final[tuple[str, ...]] = (
    # A sandbox version and the authored objects inside it.
    "world_alternate_version",
    "world_alternate_version_edit",
    "world_alternate_object",
    "world_alternate_element_override",
    # A judge's edits and appearance changes advance the saved entry the page opened, so the page
    # can keep its saved_entry binding.
    "saved_world_entry",
    # Appearance: preview, apply, discard, rollback, and the audit row each leaves behind.
    "world_style_proposal",
    "world_style_preview",
    "world_style_version",
    "world_style_state",
    "world_style_audit_event",
    "world_region_style_version",
    # Asking the Companion, and what it remembers across a reload.
    "companion_answer",
    "companion_answer_citation",
    "companion_escape",
    # A judge's world projects: what it keeps about its work in a world, shares and deletes.
    "world_project",
    "world_project_item",
    "world_project_share",
    # A judge can choose a model for a world's signals and keep its immutable traffic decisions.
    "world_traffic_signal_choice",
    "world_traffic_signal_decision_request",
    "world_traffic_signal_decision",
    "world_traffic_signal_segment",
)

#: Tables the judge role may append to and never update, because the runtime may only insert into
#: them (``exulanica.db.roles.INSERT_ONLY_TABLES``): what a judge's remembered answers about a
#: world's people cite, and the bindings, revisions and sources of its world projects. Erasing a
#: deleted item's revisions is an owner-rights trigger's update, not the judge's.
JUDGE_INSERT_ONLY_TABLES: Final[tuple[str, ...]] = (
    "companion_answer_simulation_citation",
    "companion_answer_simulation_label",
    "world_project_binding",
    "world_project_item_revision",
    "world_project_item_source",
)

#: What the judge's bearer token may do, named from ``exulanica.api.permissions.Permission``.
#:
#: The same routes as :data:`JUDGE_WRITE_TABLES`, stated at the other boundary: every read, the
#: authored world and its appearance, the Companion and what it remembers, deleting a memory the
#: judge made, and the model calls those routes need. ``being.act`` is what the three routes that
#: act as a being ask for, which editing the world does not cover: a token minted with this grant
#: plays a being where the API connects as the application role, as the public server's minted
#: reviewers do. On the reviewer stack the judge role writes no society table
#: (:data:`JUDGE_WRITE_TABLES`), so no being is played there whatever the token holds. Intake,
#: admission, consent writes, operations writes and tile materialisation are absent, and absence
#: is the grant. Plain strings rather than the enum, because importing the API package would load
#: the whole application into the seed job; ``load_token_directory`` refuses any name outside the
#: vocabulary, and ``tests/test_judge_seed.py`` loads what :func:`mint_judge_token` mints.
JUDGE_PERMISSIONS: Final[tuple[str, ...]] = (
    "admission.read",
    "being.act",
    "consent.read",
    "deletion.write",
    "library.read",
    "library.write",
    "model.invoke",
    "operations.read",
    "world.read",
    "world.write",
)

#: The advisory key :func:`provision_judge_role` holds while it writes ``pg_authid``. The same
#: reasoning as ``exulanica.db.roles._ROLE_LOCK_KEY`` and deliberately a different value, so a
#: judge provision and a runtime provision serialise rather than deadlock.
_JUDGE_ROLE_LOCK_KEY: Final = 119_622_351


def provision_judge_role(
    connection: psycopg.Connection,
    *,
    role: str = JUDGE_ROLE,
    password: str | None = None,
) -> None:
    """Create the role a judge deployment's API connects as, and grant it reading and a list of
    writes.

    **SELECT on everything but** :data:`~exulanica.db.roles.SPENDING_ADMIN_TABLES`**, INSERT and
    UPDATE on** :data:`JUDGE_WRITE_TABLES`**, INSERT on** :data:`JUDGE_INSERT_ONLY_TABLES`**,
    EXECUTE on** :data:`~exulanica.db.roles.SPENDING_READ_FUNCTIONS` **and nothing else.** Not
    "revoke the dangerous ones": the grant is an allowlist, so a table a later migration adds
    arrives readable and not writable without anybody remembering to come back here. That is the
    direction this has to fail in. The spending authority's tables are the one exclusion from
    reading, because they hold every workspace's spending together.

    **No DELETE anywhere, for the same reason** ``exulanica_app`` **has none.** Deletion in this
    system is a tombstone and a purge job, both of them writes to tables absent from the
    allowlist, so the judge cannot reach erasure through the front door either.

    ``nobypassrls`` and no ownership, so the workspace policy is a boundary for this role rather
    than a decoration. The same advisory-lock discipline as
    :func:`exulanica.db.roles.provision_runtime_role`, because roles are cluster-global and two
    stacks starting at once otherwise collide in ``pg_authid``.

    Idempotent, and re-running it after a migration is how the allowlist reaches a new table.
    """
    role_name = sql.Identifier(role)
    row = connection.execute("select current_schema()").fetchone()
    assert row is not None
    schema = sql.Identifier(row["current_schema"] if isinstance(row, dict) else row[0])

    with connection.transaction():
        connection.execute("select pg_advisory_xact_lock(%s)", (_JUDGE_ROLE_LOCK_KEY,))
        take_provisioning_locks(connection)
        exists = connection.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone()
        if exists is None:
            connection.execute(sql.SQL("create role {} login nobypassrls").format(role_name))
        else:
            connection.execute(sql.SQL("alter role {} nobypassrls").format(role_name))
        if password is not None:
            connection.execute(
                sql.SQL("alter role {} password {}").format(role_name, sql.Literal(password))
            )

        connection.execute(sql.SQL("grant usage on schema {} to {}").format(schema, role_name))
        # Start from nothing every time, so removing a table from the allowlist actually removes
        # the grant rather than leaving one an earlier run made.
        connection.execute(
            sql.SQL("revoke all on all tables in schema {} from {}").format(schema, role_name)
        )
        connection.execute(
            sql.SQL("grant select on all tables in schema {} to {}").format(schema, role_name)
        )
        # Except migration 0124's authority tables and ledger: an authority's committed total is
        # every workspace's spending together. The judge reads an authority's state, and no
        # amount, through SPENDING_READ_FUNCTIONS, as the runtime roles do.
        for table in SPENDING_ADMIN_TABLES:
            found = connection.execute(
                "select to_regclass(format('%%I.%%I', current_schema(), %s::text)) as relation",
                (table,),
            ).fetchone()
            relation = found["relation"] if isinstance(found, dict) else (found or (None,))[0]
            if relation is not None:
                connection.execute(
                    sql.SQL("revoke all on {} from {}").format(sql.Identifier(table), role_name)
                )
        for table, privileges in (
            *((table, sql.SQL("insert, update")) for table in JUDGE_WRITE_TABLES),
            *((table, sql.SQL("insert")) for table in JUDGE_INSERT_ONLY_TABLES),
        ):
            present = connection.execute(
                "select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace"
                " where n.nspname = current_schema() and c.relname = %s"
                "   and c.relkind in ('r', 'p')",
                (table,),
            ).fetchone()
            if present is None:
                raise SeedRefused(
                    f"the judge write allowlist names {table}, which is not in this schema"
                )
            connection.execute(
                sql.SQL("grant {} on {} to {}").format(privileges, sql.Identifier(table), role_name)
            )
        connection.execute(
            sql.SQL("grant usage, select on all sequences in schema {} to {}").format(
                schema, role_name
            )
        )
        # GET /spending reads an authority's state through migration 0124's owner-rights
        # functions, which state no amount; the judge reads them as the runtime roles do.
        for name, arguments in SPENDING_READ_FUNCTIONS:
            found = connection.execute(
                "select to_regprocedure(format('%%I.%%I(%%s)', current_schema(), %s::text, "
                "%s::text)) as function_ref",
                (name, arguments),
            ).fetchone()
            if found is not None and (
                found["function_ref"] if isinstance(found, dict) else found[0]
            ):
                connection.execute(
                    sql.SQL("grant execute on function {}.{}({}) to {}").format(
                        schema, sql.Identifier(name), sql.SQL(arguments), role_name
                    )
                )
        # Partitions created later by provision_workspace, and any table a later migration adds,
        # arrive readable. Writability is never a default.
        connection.execute(
            sql.SQL("alter default privileges in schema {} grant select on tables to {}").format(
                schema, role_name
            )
        )


def judge_grants(connection: psycopg.Connection, *, role: str = JUDGE_ROLE) -> dict[str, set[str]]:
    """What ``role`` may actually do, read back from the live catalog.

    Read back rather than recorded. A test comparing the allowlist against itself would pass on a
    database where not one of those statements ran.
    """
    rows = connection.execute(
        "select c.relname as name, p.privilege_type as privilege"
        "  from pg_class c"
        "  join pg_namespace n on n.oid = c.relnamespace"
        "  cross join lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) p"
        "  join pg_roles r on r.oid = p.grantee"
        " where n.nspname = current_schema() and c.relkind in ('r', 'p') and r.rolname = %s",
        (role,),
    ).fetchall()
    grants: dict[str, set[str]] = {}
    for row in rows:
        grants.setdefault(row["name"], set()).add(row["privilege"])
    return grants


def judge_grant_mismatches(grants: Mapping[str, set[str]]) -> list[str]:
    """Each table whose privileges beyond SELECT differ from what the judge is granted.

    Exactly INSERT and UPDATE on :data:`JUDGE_WRITE_TABLES`, exactly INSERT on
    :data:`JUDGE_INSERT_ONLY_TABLES`, and nothing beyond SELECT on any other table. Empty when
    ``grants``, read back by :func:`judge_grants`, is exactly that.
    """
    granted = {
        **{table: {"INSERT", "UPDATE"} for table in JUDGE_WRITE_TABLES},
        **{table: {"INSERT"} for table in JUDGE_INSERT_ONLY_TABLES},
    }
    mismatches = []
    for table in sorted(set(granted) | set(grants)):
        held = set(grants.get(table, set())) - {"SELECT"}
        allowed = granted.get(table, set())
        if held != allowed:
            mismatches.append(
                f"{table} holds {', '.join(sorted(held)) or 'nothing'} beyond SELECT; "
                f"the allowlist grants {', '.join(sorted(allowed)) or 'nothing'}"
            )
    return mismatches


def mint_judge_token(*, workspace_id: uuid.UUID, actor: uuid.UUID, token: str) -> dict[str, Any]:
    """Build the one-entry token directory a judge deployment serves.

    The token value is supplied rather than generated here, so the caller owns where the entropy
    came from and this stays testable without a random source. It is checked against the same
    32-character floor :func:`exulanica.api.authorisation.load_token_directory` enforces, because
    a token minted here and refused there is a deployment that starts and accepts nobody.

    ``may_include_proposals`` is false. A judge is shown what the system has confirmed rather
    than what it has guessed, and the Selection plan must not be able to widen that. The grant
    carries :data:`JUDGE_PERMISSIONS`, because the API loads no grant that does not name its
    permissions.
    """
    if len(token) < 32:
        raise SeedRefused(
            "a bearer token shorter than 32 characters is refused by the API at load time, so "
            "minting one here would produce a deployment that cannot start"
        )
    return {
        token: {
            "workspace_id": str(workspace_id),
            "actor": str(actor),
            "permissions": list(JUDGE_PERMISSIONS),
            "may_include_proposals": False,
        }
    }
