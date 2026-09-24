"""Changing a local database that trusts its connections into one that asks for passwords.

``exulanica-local-db require-passwords --directory <dir>`` converts a cluster that ``init`` made
before passwords were required, or that ``adopt`` took on, so that it admits only connections that
present a password (``scram-sha-256``). Inside one maintenance session, with the server on a
private port and this command its only client (:meth:`~exulanica.db.local.database.LocalDatabase.
maintenance` refuses while anything else is connected), it:

1.  **checks, before anything changes**, each refusing by name: the marker says the cluster trusts
    its connections; no other account may write in ``<dir>``; the server's authentication file is
    the data directory's own ``pg_hba.conf``, every rule in it parses, includes nothing, carries no
    options and has the method ``trust``, ``scram-sha-256`` or ``reject``; and every role the
    application connects as exists and may log in;
2.  **backs up** and proves the backup restores, the way back whatever follows;
3.  **gives every role a password**: the bootstrap superuser and each application role, written to
    the password file first and then set as a SCRAM verifier (:mod:`~exulanica.db.local.passwords`);
4.  **rewrites** ``pg_hba.conf``, changing the method word of each ``trust`` rule to
    ``scram-sha-256`` and keeping every other byte, reads the file back through the server's own
    parser before it is loaded, then reloads the server's configuration;
5.  **proves** it: the bootstrap superuser and every application role are refused with no password
    and connect, as themselves, with their own;
6.  **writes the marker** last, naming the backup.

**A failure leaves the cluster as it was.** Any failure after the backup puts back ``pg_hba.conf``'s
bytes and reloads, puts back each role's previous password (none, for a cluster that trusted its
connections), puts back or removes the password file and the marker, and shows the server admits a
connection without a password again, then stops with ``authentication-change-failed``. Should
putting it back fail too, the server is left stopped and the message names the backup.

A run killed outright between steps 3 and 6 leaves a password file beside a marker that still says
trust. Every URL names that file whenever it exists, so every command still connects, and running
this command again finishes the change with the passwords the file holds.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TextIO

import psycopg
from psycopg.rows import dict_row

from exulanica.db.local.backup import take_backup, verify_backup
from exulanica.db.local.cluster import url
from exulanica.db.local.database import (
    APPLICATION_ROLES,
    MARKER_PROFILE,
    LocalDatabase,
    MaintenanceSession,
    utc_now,
)
from exulanica.db.local.files import write_atomically, write_private
from exulanica.db.local.passwords import (
    Authentication,
    empty_password_file,
    give_password,
    new_password,
    read_passwords,
    refuse_exposed,
    restore_verifier,
    stored_verifiers,
    write_passwords,
)
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal

__all__ = ["BEFORE_PASSWORDS", "HbaRule", "hba_rules", "require_passwords", "rewrite_methods"]

#: What the backup taken before the change is named by.
BEFORE_PASSWORDS: Final = "before-passwords"

#: The methods a rule may have for the change to carry it over: ``trust``, which it changes, and
#: the two that already admit no connection without a password.
_REJECT: Final = "reject"
_CARRIED_OVER: Final = frozenset({Authentication.TRUST.value, Authentication.SCRAM.value, _REJECT})

#: How long a reload may take to reach a new connection: the postmaster applies it when it
#: handles the signal, with room for a loaded machine. Polled at the interval below.
RELOAD_DEADLINE_SECONDS: Final = 10
_POLL_SECONDS: Final = 0.05

#: What libpq reports when the server asks for a password and none was given (fe-auth.c,
#: ``PQnoPasswordSupplied``): the proof that the server asked.
_ASKED_FOR_A_PASSWORD: Final = "no password supplied"


@dataclass(frozen=True, slots=True)
class HbaRule:
    """One rule of ``pg_hba.conf`` as the server's own parser reads it (``pg_hba_file_rules``)."""

    file_name: str | None
    line_number: int | None
    type: str | None
    database: tuple[str, ...]
    user_name: tuple[str, ...]
    address: str | None
    netmask: str | None
    auth_method: str | None
    options: tuple[str, ...]
    error: str | None

    @property
    def admits(self) -> tuple[Any, ...]:
        """Whom the rule is for, which the change must never alter."""
        return (self.type, self.database, self.user_name, self.address, self.netmask)

    def describe(self) -> str:
        if self.error:
            return f"line {self.line_number}: {self.error}"
        who = " ".join(filter(None, (self.type, ",".join(self.database), ",".join(self.user_name))))
        where = f" {self.address}/{self.netmask}" if self.address else ""
        options = f" {' '.join(self.options)}" if self.options else ""
        return f"line {self.line_number}: {who}{where} {self.auth_method}{options}"


def hba_rules(connection: psycopg.Connection[Any]) -> list[HbaRule]:
    """``pg_hba.conf`` as it is on disk, read by the server's parser, in the order it applies."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "select file_name, line_number, type, database, user_name, address, netmask, "
            "auth_method, options, error from pg_hba_file_rules order by rule_number nulls last"
        ).fetchall()
    return [
        HbaRule(
            file_name=row["file_name"],
            line_number=row["line_number"],
            type=row["type"],
            database=tuple(row["database"] or ()),
            user_name=tuple(row["user_name"] or ()),
            address=row["address"],
            netmask=row["netmask"],
            auth_method=row["auth_method"],
            options=tuple(row["options"] or ()),
            error=row["error"],
        )
        for row in rows
    ]


def _refuse_rules(rules: Sequence[HbaRule], hba_file: Path, data: Path) -> list[int]:
    """The lines of the ``trust`` rules to change, or a refusal naming each rule it cannot carry."""
    if hba_file.resolve() != (data / "pg_hba.conf").resolve():
        raise LocalDatabaseRefused(
            Refusal.AUTHENTICATION_RULES,
            f"the server reads its authentication rules from {hba_file}, outside {data}; this "
            "command changes only the data directory's own pg_hba.conf",
        )
    wrong = [
        rule
        for rule in rules
        if rule.error
        or rule.file_name is None
        or Path(rule.file_name).resolve() != hba_file.resolve()
        or rule.options
        or rule.auth_method not in _CARRIED_OVER
    ]
    if wrong or not rules:
        raise LocalDatabaseRefused(
            Refusal.AUTHENTICATION_RULES,
            f"{hba_file} holds rules this change cannot carry over: "
            f"{'; '.join(rule.describe() for rule in wrong) or 'none at all'}. It changes the "
            f"method of a rule without options from trust to {Authentication.SCRAM.value}, in "
            f"this file only, and keeps rules that already say {Authentication.SCRAM.value} or "
            f"{_REJECT}; change the others by hand first.",
        )
    return [
        rule.line_number
        for rule in rules
        if rule.auth_method == Authentication.TRUST.value and rule.line_number is not None
    ]


#: A rule whose last word before an optional comment is ``trust``: the method, since the rule
#: carries no options.
_TRUST_METHOD: Final = re.compile(
    rf"^(?P<head>.*\s){Authentication.TRUST.value}(?P<tail>\s*(?:#.*)?)$"
)


def rewrite_methods(text: str, lines: Sequence[int]) -> str:
    """``text`` with the method word on each of ``lines`` changed from trust to scram-sha-256.

    Every other character stays, comments and spacing included. A named line whose method is not
    its last word, as when a rule continues onto the next line, is refused rather than guessed at.
    """
    kept = text.split("\n")
    for number in lines:
        line = kept[number - 1] if 0 < number <= len(kept) else ""
        body = line.rstrip("\r")
        found = _TRUST_METHOD.match(body)
        if found is None:
            raise LocalDatabaseRefused(
                Refusal.AUTHENTICATION_RULES,
                f"line {number} of pg_hba.conf does not end in its method, trust: {line.strip()}",
            )
        kept[number - 1] = (
            f"{found['head']}{Authentication.SCRAM.value}{found['tail']}{line[len(body) :]}"
        )
    return "\n".join(kept)


def _application_roles_may_log_in(connection: psycopg.Connection[Any]) -> None:
    rows = connection.execute(
        "select rolname, rolcanlogin from pg_roles where rolname = any(%s)",
        (list(APPLICATION_ROLES),),
    ).fetchall()
    can_log_in = {row["rolname"]: row["rolcanlogin"] for row in rows}
    wrong = [
        f"{role} ({'may not log in' if role in can_log_in else 'absent'})"
        for role in APPLICATION_ROLES
        if not can_log_in.get(role)
    ]
    if wrong:
        raise LocalDatabaseRefused(
            Refusal.LOGIN_ROLE_MISSING,
            f"the application connects as roles this cluster cannot admit: {', '.join(wrong)}. "
            "This change gives passwords and never makes roles; `exulanica-local-db upgrade` "
            "provisions them.",
        )


def _left_without_a_password(connection: psycopg.Connection[Any], owner: str) -> list[str]:
    """Other roles that may log in and have no password, so the change shuts them out."""
    rows = connection.execute(
        "select rolname from pg_authid where rolcanlogin and rolpassword is null "
        "and rolname <> all(%s) order by rolname",
        ([owner, *APPLICATION_ROLES],),
    ).fetchall()
    return [row["rolname"] for row in rows]


def _refused_without_a_password(port: int, role: str, database: str) -> str | None:
    """Why the server refused ``role`` with no password, or ``None`` when it admitted it."""
    with empty_password_file() as empty:
        try:
            with psycopg.connect(url(port, role, database, passfile=empty)):
                return None
        except psycopg.OperationalError as error:
            return " ".join(str(error).split())


def _wait_until(condition: Callable[[], bool], *, what: str) -> None:
    deadline = time.monotonic() + RELOAD_DEADLINE_SECONDS
    while not condition():
        if time.monotonic() > deadline:
            raise LocalDatabaseRefused(
                Refusal.AUTHENTICATION_CHANGE_FAILED,
                f"{what} did not happen within {RELOAD_DEADLINE_SECONDS} seconds",
            )
        time.sleep(_POLL_SECONDS)


def _asked_for_a_password(reason: str | None) -> bool:
    return reason is not None and _ASKED_FOR_A_PASSWORD in reason


def _prove(database: LocalDatabase, port: int, roles: Sequence[str], stream: TextIO) -> None:
    """Every role is refused with no password, and connects as itself with its own."""
    name = database.database_name
    _wait_until(
        lambda: _asked_for_a_password(_refused_without_a_password(port, database.owner, name)),
        what="the reloaded rules asking the bootstrap superuser for a password",
    )
    for role in roles:
        reason = _refused_without_a_password(port, role, name)
        if not _asked_for_a_password(reason):
            raise LocalDatabaseRefused(
                Refusal.AUTHENTICATION_CHANGE_FAILED,
                f"{role} was not asked for a password: "
                f"{reason or 'the server admitted it without one'}",
            )
        with psycopg.connect(database.role_url(port, role)) as connection:
            row = connection.execute("select current_user").fetchone()
        if row is None or row[0] != role:
            raise LocalDatabaseRefused(
                Refusal.AUTHENTICATION_CHANGE_FAILED,
                f"connecting with {role}'s password reached {row[0] if row else 'nobody'}",
            )
        print(f"proof: {role} is refused without a password and connects with its own", file=stream)


@dataclass(frozen=True, slots=True)
class _Before:
    """What the change may alter, as it was when this run began."""

    hba_file: Path
    hba: bytes
    hba_mode: int
    rules: tuple[HbaRule, ...]
    hba_trusted_every_connection: bool
    verifiers: Mapping[str, str | None]
    passfile: bytes | None
    marker: bytes


def _put_back(database: LocalDatabase, port: int, before: _Before) -> None:
    """Undo the change: the rules, the roles' passwords, the password file, then the marker."""
    write_atomically(before.hba_file, before.hba, mode=before.hba_mode)
    with database.connect(port) as connection:
        connection.execute("select pg_reload_conf()")
    if before.hba_trusted_every_connection:
        _wait_until(
            lambda: (
                _refused_without_a_password(port, database.owner, database.database_name) is None
            ),
            what="the restored rules admitting the bootstrap superuser without a password",
        )
    with database.connect(port) as connection:
        for role, verifier in before.verifiers.items():
            restore_verifier(connection, role, verifier)
    if before.passfile is None:
        database.passfile.unlink(missing_ok=True)
    else:
        write_atomically(database.passfile, before.passfile, mode=0o600)
    if database.marker.read_bytes() != before.marker:
        write_atomically(database.marker, before.marker, mode=0o600)


def _change(
    database: LocalDatabase,
    session: MaintenanceSession,
    roles: Sequence[str],
    lines: Sequence[int],
    before: _Before,
    backup_name: str,
    stream: TextIO,
) -> None:
    """Steps 3 to 6: passwords, rules, proof, marker."""
    port = session.port
    held = read_passwords(database.passfile) if before.passfile is not None else {}
    write_passwords(database.passfile, {role: held.get(role) or new_password() for role in roles})
    passwords = read_passwords(database.passfile)
    with database.connect(port) as connection:
        for role in roles:
            give_password(connection, role, passwords[role])
    print(
        f"passwords: {database.passfile} (mode 0600) holds one for each of {', '.join(roles)}; "
        "each role's SCRAM verifier is set",
        file=stream,
    )
    changed = rewrite_methods(before.hba.decode("utf-8"), lines)
    write_atomically(before.hba_file, changed.encode("utf-8"), mode=before.hba_mode)
    with database.connect(port) as connection:
        after = hba_rules(connection)
    methods = {rule.auth_method for rule in after}
    if (
        any(rule.error for rule in after)
        or not methods <= {Authentication.SCRAM.value, _REJECT}
        or [rule.admits for rule in after] != [rule.admits for rule in before.rules]
    ):
        raise LocalDatabaseRefused(
            Refusal.AUTHENTICATION_CHANGE_FAILED,
            "the rewritten pg_hba.conf reads back as: "
            + "; ".join(rule.describe() for rule in after)
            + f", not as the same {len(before.rules)} rules with trust changed",
        )
    with database.connect(port) as connection:
        connection.execute("select pg_reload_conf()")
    print(
        f"pg_hba.conf: {len(lines)} rules changed from trust to {Authentication.SCRAM.value} "
        f"(lines {', '.join(map(str, lines)) or 'none'}); every other byte kept; reloaded",
        file=stream,
    )
    _prove(database, port, roles, stream)
    marker = database.read_marker()
    write_private(
        database.marker,
        json.dumps(
            {
                **marker,
                "profile": MARKER_PROFILE,
                "authentication": Authentication.SCRAM.value,
                "passwords_required": {
                    "at": utc_now(),
                    "backup": backup_name,
                    "roles": list(roles),
                },
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
    )


def require_passwords(database: LocalDatabase, stream: TextIO) -> None:
    """Check, back up and prove the backup, give passwords, change the rules, prove, then mark."""
    if database.authentication is Authentication.SCRAM:
        raise LocalDatabaseRefused(
            Refusal.PASSWORDS_ALREADY_REQUIRED,
            f"{database.root} already asks every connection for a password; its passwords are "
            f"in {database.passfile}",
        )
    refuse_exposed(database.passfile)
    roles = (database.owner, *APPLICATION_ROLES)
    with database.maintenance() as session:
        with database.connect(session.port) as connection:
            shown = connection.execute("show hba_file").fetchone()
            assert shown is not None
            hba_file = Path(shown["hba_file"])
            rules = hba_rules(connection)
            lines = _refuse_rules(rules, hba_file, database.data)
            _application_roles_may_log_in(connection)
            shut_out = _left_without_a_password(connection, database.owner)
            verifiers = stored_verifiers(connection, roles)
        before = _Before(
            hba_file=hba_file,
            hba=hba_file.read_bytes(),
            hba_mode=hba_file.stat().st_mode & 0o777,
            rules=tuple(rules),
            hba_trusted_every_connection=all(
                rule.auth_method == Authentication.TRUST.value for rule in rules
            ),
            verifiers=verifiers,
            passfile=database.passfile.read_bytes() if database.passfile.is_file() else None,
            marker=database.marker.read_bytes(),
        )
        print(
            f"requiring passwords for {database.root}: {len(rules)} rules in {hba_file}, "
            f"{len(lines)} of them trust; the server is on private port {session.port}",
            file=stream,
        )
        if shut_out:
            print(
                f"note: {', '.join(shut_out)} may log in and have no password, so they will be "
                "refused once passwords are required",
                file=stream,
            )
        backup = take_backup(database, session.port, BEFORE_PASSWORDS)
        print(f"backup: {backup.describe()}", file=stream)
        counts = verify_backup(backup)
        print(
            f"restorable: sha256 matches; a scratch restore holds {len(counts)} tables and "
            f"{sum(counts.values())} rows, and its row counts and migrations equal its manifest",
            file=stream,
        )
        try:
            _change(database, session, roles, lines, before, backup.dump.name, stream)
        except BaseException as error:
            try:
                _put_back(database, session.port, before)
            except BaseException as undo:
                session.leave_stopped = True
                raise LocalDatabaseRefused(
                    Refusal.AUTHENTICATION_CHANGE_FAILED,
                    f"{_reason(error)}; putting the cluster back failed too ({_reason(undo)}), "
                    f"so the server is left stopped. {backup.dump} holds the database as it was: "
                    "restore it into an empty directory with `exulanica-local-db restore`.",
                ) from error
            if not isinstance(error, Exception):
                raise
            raise LocalDatabaseRefused(
                Refusal.AUTHENTICATION_CHANGE_FAILED,
                f"{_reason(error)}. Put back: pg_hba.conf's bytes, each role's previous password, "
                "the password file and the marker; the server admits connections as it did.",
            ) from error
    print(
        f"passwords required: {database.marker} says {Authentication.SCRAM.value} and names "
        f"{backup.dump.name}",
        file=stream,
    )


def _reason(error: BaseException) -> str:
    if isinstance(error, LocalDatabaseRefused):
        return f"{error.refusal.value}: {error.detail}"
    return f"{type(error).__name__}: {error}"
