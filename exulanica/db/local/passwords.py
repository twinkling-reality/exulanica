"""Where a local database's passwords live, how a process gets them, and how a role is given one.

**Where.** One file per local database, ``<directory>/passwords.pgpass``, beside ``data/``,
``backups/`` and ``server.log``, readable and writable by this account only. It is in libpq's own
password-file format, one line per role::

    localhost:*:*:exulanica_app:<password>

**How a process gets one.** Every URL the command builds or prints names that file with libpq's
``passfile`` connection parameter, ``postgresql://exulanica_app@localhost:60638/exulanica?passfile=
<directory>/passwords.pgpass``. libpq, which psycopg, ``pg_dump``, ``pg_restore`` and ``psql`` all
connect through, opens the file when it connects and answers the server's SCRAM challenge from it.
So no password is in a URL, an environment variable, a command line or a log line, and the
application reads its URLs exactly as it reads any other. A URL naming its own file also keeps
libpq from consulting ``~/.pgpass``, which would otherwise answer for every URL without a password.

**How a role is given one.** The file is written first, then the role's SCRAM verifier, computed
here with libpq's ``PQencryptPasswordConn``, is set with ``ALTER ROLE``. The server receives a
verifier and never the password, so neither a statement it logs nor its catalog holds one. The
bootstrap superuser's password reaches ``initdb`` through ``--pwfile``, a private file removed as
soon as ``initdb`` exits (:meth:`~exulanica.db.local.cluster.Cluster.initialise`).

**Why not elsewhere.** libpq cannot read the macOS Keychain, so a password kept there would have
to be handed to libpq in a URL or ``PGPASSWORD``, which is the exposure this avoids; an environment
variable is readable in a process listing by the same account; ``~/.pgpass`` is one file for every
cluster and every tool, outside the directory the database lives in.

**What it protects, and what it does not.** A cluster that asks for passwords admits no
connection from another account on this computer, or from any process that can open a loopback
connection but cannot read this account's files. A process running as this account can read the
password file, as it can read the data directory itself: the boundary is the account, the same as
the data files'. libpq ignores a password file that grants group or world any access, and this
command refuses one (:data:`~exulanica.db.local.refusals.Refusal.PASSWORDS_EXPOSED`).
"""

from __future__ import annotations

import contextlib
import secrets
import stat
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

import psycopg
from psycopg import sql
from psycopg.rows import tuple_row

from exulanica.db.local.files import write_private
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal

__all__ = [
    "HOST",
    "PASSWORD_BYTES",
    "PASSWORD_FILE_NAME",
    "Authentication",
    "empty_password_file",
    "give_password",
    "new_password",
    "passfile_parameter",
    "read_passwords",
    "refuse_exposed",
    "restore_verifier",
    "stored_verifiers",
    "write_passwords",
]


class Authentication(StrEnum):
    """How a local database's server admits a connection. The value is PostgreSQL's method name.

    ``init``, ``restore`` and every scratch copy make :attr:`SCRAM` clusters. :attr:`TRUST` is how
    a cluster made before passwords were required, or one another tool made and ``adopt`` took on,
    admits connections; ``require-passwords`` changes one to :attr:`SCRAM`.
    """

    TRUST = "trust"
    SCRAM = "scram-sha-256"


#: The password file, in the local database's own directory (and a scratch copy's).
PASSWORD_FILE_NAME: Final = "passwords.pgpass"

#: Every URL names this host, and every line of a password file matches it: libpq compares a
#: line's host with the host the connection names, not with the address it resolves to.
HOST: Final = "localhost"

#: Random bytes behind each password: 256 bits, the length of a SCRAM-SHA-256 key.
#: ``secrets.token_urlsafe`` spells them with letters, digits, ``-`` and ``_``.
PASSWORD_BYTES: Final = 32

#: A line of a password file matches any port and any database: a maintenance session serves on
#: a port chosen when it starts, and a role connects to ``postgres`` as well as the schema's.
_ANY: Final = "*"

#: The fields of a password file line, and the characters libpq reads a backslash before.
_FIELDS: Final = 5
_ESCAPED: Final = ("\\", ":")


def new_password() -> str:
    return secrets.token_urlsafe(PASSWORD_BYTES)


def _escape(value: str) -> str:
    for character in _ESCAPED:
        value = value.replace(character, "\\" + character)
    return value


def _fields(line: str) -> list[str]:
    """A password file line's fields, read as libpq reads them."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":" and len(fields) < _FIELDS - 1:
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    fields.append("".join(current))
    return fields


def read_passwords(passfile: Path) -> dict[str, str]:
    """Each role's password in ``passfile``, which this command wrote."""
    passwords: dict[str, str] = {}
    for number, line in enumerate(passfile.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.startswith("#"):
            continue
        fields = _fields(line)
        if len(fields) != _FIELDS or fields[:3] != [HOST, _ANY, _ANY]:
            raise LocalDatabaseRefused(
                Refusal.PASSWORD_FILE_UNREADABLE,
                f"line {number} of {passfile} is not a line this command writes "
                f"({HOST}:{_ANY}:{_ANY}:<role>:<password>)",
            )
        passwords[fields[3]] = fields[4]
    return passwords


def write_passwords(passfile: Path, passwords: Mapping[str, str]) -> None:
    """Write every role's password to ``passfile`` in one step, readable by this account only."""
    write_private(
        passfile,
        "".join(
            f"{HOST}:{_ANY}:{_ANY}:{_escape(role)}:{_escape(password)}\n"
            for role, password in sorted(passwords.items())
        ),
    )


def passfile_parameter(passfile: Path) -> str:
    """The URL query that names ``passfile``, spelled so any path survives a URL."""
    return f"passfile={quote(str(passfile), safe='/')}"


#: The permission bits that let another account read the password file, or replace it.
_FILE_EXPOSED: Final = stat.S_IRWXG | stat.S_IRWXO
_DIRECTORY_EXPOSED: Final = stat.S_IWGRP | stat.S_IWOTH


def refuse_exposed(passfile: Path) -> None:
    """Refuse a password file another account could read, or a directory where it could swap one.

    libpq itself ignores a file with group or world access, and then every connection fails as
    though it had no password; this says why first.
    """
    directory = passfile.parent
    if directory.stat().st_mode & _DIRECTORY_EXPOSED:
        raise LocalDatabaseRefused(
            Refusal.PASSWORDS_EXPOSED,
            f"{directory} may be written by other accounts (mode "
            f"{stat.filemode(directory.stat().st_mode)}), so one could replace {passfile.name}. "
            f"Run `chmod go-w {directory}` first.",
        )
    if passfile.exists() and passfile.stat().st_mode & _FILE_EXPOSED:
        raise LocalDatabaseRefused(
            Refusal.PASSWORDS_EXPOSED,
            f"{passfile} may be read by other accounts (mode "
            f"{stat.filemode(passfile.stat().st_mode)}), and libpq ignores such a file. Run "
            f"`chmod 600 {passfile}`; if another account could have read it, change the "
            "passwords by restoring a backup into a new directory.",
        )


def give_password(connection: psycopg.Connection[Any], role: str, password: str) -> None:
    """Set ``role``'s password as a SCRAM verifier computed here, so the server never sees it."""
    verifier = connection.pgconn.encrypt_password(
        password.encode("utf-8"), role.encode("utf-8"), Authentication.SCRAM.value.encode()
    )
    restore_verifier(connection, role, verifier.decode("ascii"))


def restore_verifier(connection: psycopg.Connection[Any], role: str, verifier: str | None) -> None:
    """Put back what ``pg_authid`` held for ``role``: a verifier, or no password at all."""
    connection.execute(
        sql.SQL("alter role {} password {}").format(
            sql.Identifier(role), sql.Literal(verifier) if verifier is not None else sql.NULL
        )
    )


def stored_verifiers(
    connection: psycopg.Connection[Any], roles: Iterable[str]
) -> dict[str, str | None]:
    """What ``pg_authid`` holds for each of ``roles``: a verifier or hash, or ``None``."""
    with connection.cursor(row_factory=tuple_row) as cursor:
        rows = cursor.execute(
            "select rolname, rolpassword from pg_authid where rolname = any(%s)", (list(roles),)
        ).fetchall()
    return {str(name): verifier for name, verifier in rows}


@contextlib.contextmanager
def empty_password_file() -> Iterator[Path]:
    """A private password file with no lines: a URL naming it presents no password at all.

    Naming it, rather than no file, keeps libpq from answering from ``~/.pgpass``, so a refusal
    seen through it is the server asking for a password nobody gave.
    """
    with tempfile.TemporaryDirectory(prefix="exulanica-no-password-") as directory:
        empty = Path(directory) / PASSWORD_FILE_NAME
        write_private(empty, "")
        yield empty
