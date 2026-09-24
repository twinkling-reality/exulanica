"""A local database that asks every connection for a password, and the change that makes one so.

What is held here, against real PostgreSQL 18 servers in this test's own files:

*   **``init`` makes a cluster that asks for passwords.** The bootstrap superuser and every role
    the application connects as are refused with no password and admitted with their own; the
    password file is private; and no password is printed, logged, written anywhere else in the
    database's directory, carried by a backup, or visible in the server's process listing.
*   **Every other command works on one**, and a restore gives the roles new passwords.
*   **``require-passwords`` converts a cluster that trusts its connections**, first profile marker
    and all, as a cluster adopted before passwords were required is: it backs up and proves the
    backup, and
    afterwards the cluster holds the same rows, answers on the same port, and its
    ``pg_hba.conf`` differs only in the method words.
*   **Each refusal, by name, leaves the cluster as it was**, and **a failure after the change began
    puts back** the rules, the roles' passwords, the password file and the marker.

The file format, the rewrite of ``pg_hba.conf`` and the refusals of an exposed file need no
server and are checked first.
"""

from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from exulanica.db.local import cluster
from exulanica.db.local import require_passwords as conversion
from exulanica.db.local.backup import check_digest, list_backups, read_backup, take_backup
from exulanica.db.local.database import APPLICATION_ROLES, MARKER_PROFILE, LocalDatabase
from exulanica.db.local.passwords import (
    PASSWORD_FILE_NAME,
    Authentication,
    empty_password_file,
    give_password,
    read_passwords,
    refuse_exposed,
    stored_verifiers,
    write_passwords,
)
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal
from exulanica.db.local.require_passwords import hba_rules, rewrite_methods

from test_local_database import Machine, cli, simulate_machine
from test_local_database_postgres import (
    Servers,
    _init,
    _init_trusted,
    _require_server_binaries,
    _state,
    _write_person_rows,
    migration_files,
)

postgres = pytest.mark.postgres

#: What libpq says when the server asked for a password and none was given.
ASKED_FOR_A_PASSWORD = "no password supplied"

#: The first marker profile, which every cluster made or adopted before passwords were required
#: carries.
FIRST_MARKER_PROFILE = "exulanica.local-database/v1"


# -- the password file and the rules, without a server -----------------------------------------


def test_a_password_file_reads_back_what_was_written_and_only_this_account_may_read_it(tmp_path):
    passfile = tmp_path / PASSWORD_FILE_NAME
    passwords = {"exulanica_app": "a-b_c", "odd:role\\name": "p:w\\d"}

    write_passwords(passfile, passwords)

    assert read_passwords(passfile) == passwords
    assert stat.S_IMODE(passfile.stat().st_mode) == 0o600
    assert passfile.read_text().splitlines()[0] == "localhost:*:*:exulanica_app:a-b_c"


def test_a_url_names_the_password_file_and_holds_no_password(tmp_path):
    passfile = tmp_path / "a directory" / PASSWORD_FILE_NAME
    passfile.parent.mkdir()
    write_passwords(passfile, {"exulanica_app": "the-password"})

    named = cluster.url(60638, "exulanica_app", "exulanica", passfile=passfile)

    assert named == (
        "postgresql://exulanica_app@localhost:60638/exulanica"
        f"?passfile={str(passfile).replace(' ', '%20')}"
    )
    assert "the-password" not in named
    assert psycopg.conninfo.conninfo_to_dict(named)["passfile"] == str(passfile)


def test_a_password_file_another_account_could_read_or_replace_is_refused(tmp_path):
    directory = tmp_path / "database"
    directory.mkdir(mode=0o700)
    passfile = directory / PASSWORD_FILE_NAME
    write_passwords(passfile, {"exulanica_app": "p"})
    refuse_exposed(passfile)  # the positive control: 0600 in a 0700 directory passes

    passfile.chmod(0o640)
    with pytest.raises(LocalDatabaseRefused) as readable:
        refuse_exposed(passfile)
    passfile.chmod(0o600)
    directory.chmod(0o770)
    with pytest.raises(LocalDatabaseRefused) as replaceable:
        refuse_exposed(passfile)
    directory.chmod(0o700)

    assert readable.value.refusal is replaceable.value.refusal is Refusal.PASSWORDS_EXPOSED


HBA = (
    "# a comment that says trust\r\n"
    "local   all   all                    trust\n"
    "host    all   all   127.0.0.1/32     trust   # loopback\n"
    "host    all   all   ::1/128          scram-sha-256\n"
    "host    trust all   ::1/128          trust"
)


def test_the_rewrite_changes_only_the_method_word_of_the_lines_it_is_given():
    rewritten = rewrite_methods(HBA, [2, 3, 5])

    assert rewritten == (
        "# a comment that says trust\r\n"
        "local   all   all                    scram-sha-256\n"
        "host    all   all   127.0.0.1/32     scram-sha-256   # loopback\n"
        "host    all   all   ::1/128          scram-sha-256\n"
        "host    trust all   ::1/128          scram-sha-256"
    )


def test_a_rule_whose_method_is_not_its_last_word_is_refused_rather_than_guessed_at():
    continued = "host all all 127.0.0.1/32 \\\n  trust\n"

    with pytest.raises(LocalDatabaseRefused) as refused:
        rewrite_methods(continued, [1])

    assert refused.value.refusal is Refusal.AUTHENTICATION_RULES


def _marked(root: Path, marker: dict) -> Path:
    (root / "data").mkdir(parents=True)
    (root / "data" / "exulanica-local-database.json").write_text(json.dumps(marker))
    return root


def test_a_first_profile_marker_reads_as_trust_and_a_password_marker_needs_its_file(machine):
    first = _marked(machine.durable / "first", {"profile": FIRST_MARKER_PROFILE})
    asks = _marked(
        machine.durable / "asks",
        {"profile": MARKER_PROFILE, "authentication": Authentication.SCRAM.value},
    )

    assert LocalDatabase.open(first).authentication is Authentication.TRUST
    with pytest.raises(LocalDatabaseRefused) as refused:
        LocalDatabase.open(asks)
    assert refused.value.refusal is Refusal.PASSWORD_FILE_MISSING


@pytest.fixture
def machine(tmp_path, monkeypatch) -> Machine:
    return simulate_machine(tmp_path, monkeypatch)


# -- against servers -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def servers_machine(tmp_path_factory) -> Iterator[Machine]:
    _require_server_binaries()
    with pytest.MonkeyPatch.context() as patch:
        yield simulate_machine(tmp_path_factory.mktemp("passwords"), patch)


@pytest.fixture
def servers(servers_machine) -> Iterator[Servers]:
    made = Servers(roots=[])
    yield made
    made.stop_all()


@pytest.fixture(scope="module")
def trusted_world(servers_machine, tmp_path_factory) -> Iterator[Path]:
    """A stopped cluster that trusts its connections, with a person's rows, marked the way a
    cluster adopted before passwords were required is: the first marker profile, which states no
    authentication."""
    made = Servers(roots=[])
    try:
        database = _init_trusted(made, tmp_path_factory.mktemp("trusted") / "database")
        _write_person_rows(database)
        database.cluster.stop()
        marker = json.loads(database.marker.read_text())
        del marker["authentication"]
        database.marker.write_text(json.dumps({**marker, "profile": FIRST_MARKER_PROFILE}))
        yield database.root
    finally:
        made.stop_all()


def _serving_copy(world: Path, servers: Servers, directory: Path) -> LocalDatabase:
    """A copy of the trusted world, serving the application on a port of its own."""
    shutil.copytree(world, directory, symlinks=True)
    database = servers.track(directory)
    port = cluster._free_port()
    database.cluster.start(port)
    with database.connect(port) as connection:
        connection.execute(f"alter system set port = {port}")
    return database


def _refusal_without_a_password(port: int, role: str, database: str = "exulanica") -> str | None:
    with empty_password_file() as empty:
        try:
            with psycopg.connect(cluster.url(port, role, database, passfile=empty)):
                return None
        except psycopg.OperationalError as error:
            return str(error)


def _asks_every_role(database: LocalDatabase, port: int) -> None:
    """Every role is refused with no password and admitted, as itself, with its own."""
    for role in (database.owner, *APPLICATION_ROLES):
        assert ASKED_FOR_A_PASSWORD in (_refusal_without_a_password(port, role) or "admitted")
        with psycopg.connect(database.role_url(port, role)) as connection:
            assert connection.execute("select current_user").fetchone() == (role,)


def _printed_urls(out: str) -> dict[str, str]:
    return dict(re.findall(r"^export (\w+)=(\S+)$", out, flags=re.MULTILINE))


def _files_holding(root: Path, secrets: list[str], *, besides: Path) -> list[str]:
    """Every file under ``root`` other than ``besides`` whose bytes hold any of ``secrets``."""
    wanted = [secret.encode() for secret in secrets]
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path != besides and any(s in path.read_bytes() for s in wanted)
    )


@postgres
def test_init_makes_a_cluster_that_asks_every_role_for_its_password(servers, tmp_path):
    result = cli("init", "--directory", tmp_path / "database")
    assert result.status == 0, result.err
    database = servers.track(tmp_path / "database")
    port = database.cluster.running_port()
    passwords = read_passwords(database.passfile)

    assert set(passwords) == {database.owner, *APPLICATION_ROLES}
    assert stat.S_IMODE(database.passfile.stat().st_mode) == 0o600
    assert database.authentication is Authentication.SCRAM
    _asks_every_role(database, port)
    with database.connect(port) as connection:
        assert {rule.auth_method for rule in hba_rules(connection)} == {"scram-sha-256"}
    printed = _printed_urls(result.out)
    for url in printed.values():
        with psycopg.connect(url) as connection:
            connection.execute("select 1")
    assert "passfile=" in result.out and "libpq reads the password" in result.out

    stopped = cli("stop", "--directory", database.root)
    assert stopped.status == 0, stopped.err
    secrets = list(passwords.values())
    outputs = result.out + result.err + stopped.out + stopped.err
    assert not [secret for secret in secrets if secret in outputs]
    assert _files_holding(database.root, secrets, besides=database.passfile) == []


@postgres
def test_no_password_reaches_the_process_listing_of_a_running_cluster(servers, tmp_path):
    database = _init(servers, tmp_path / "database")
    listing = subprocess.run(
        ["ps", "-axww", "-o", "command"], capture_output=True, text=True, check=True
    ).stdout

    assert str(database.data) in listing  # the positive control: its server is listed
    assert not [p for p in read_passwords(database.passfile).values() if p in listing]


@postgres
def test_status_says_where_the_passwords_are_and_how_a_process_gets_one(servers, tmp_path):
    database = _init(servers, tmp_path / "database")

    running = cli("status", "--directory", database.root)
    database.cluster.stop()
    stopped = cli("status", "--directory", database.root)

    assert "pg_hba.conf, as the server reads it: scram-sha-256" in running.out
    for result in (running, stopped):
        assert result.status == 0, result.err
        assert "every connection presents a password (scram-sha-256)" in result.out
        assert f"The passwords are in {database.passfile}" in result.out


@postgres
def test_a_scratch_copy_asks_for_the_password_in_its_own_file(servers_machine):
    owner = cluster.bootstrap_user()
    with cluster.scratch_cluster(owner=owner) as (copy, port):
        assert copy.passfile is not None and copy.passfile.parent == copy.data.parent
        assert ASKED_FOR_A_PASSWORD in (_refusal_without_a_password(port, owner, "postgres") or "")
        with psycopg.connect(copy.url(port, owner, "postgres")) as connection:
            assert connection.execute("select current_user").fetchone() == (owner,)


@postgres
def test_a_restore_gives_every_role_a_new_password_and_no_backup_carries_one(servers, tmp_path):
    database = _init(servers, tmp_path / "database")
    _write_person_rows(database)
    before = read_passwords(database.passfile)
    assert cli("stop", "--directory", database.root).status == 0
    backup = list_backups(database.backups)[-1]

    restored_at = tmp_path / "restored"
    restored = cli(
        "restore", "--directory", restored_at, "--port", cluster._free_port(), backup.dump
    )
    assert restored.status == 0, restored.err
    copy = servers.track(restored_at)
    after = read_passwords(copy.passfile)

    assert set(after) == set(before)
    assert not set(after.values()) & set(before.values())
    _asks_every_role(copy, copy.cluster.running_port())
    assert _state(copy)[1] == backup.row_counts
    held = _files_holding(database.backups, list(before.values()), besides=database.passfile)
    assert held == []


@postgres
def test_an_upgrade_gives_a_password_to_an_application_role_the_file_lacks(servers, tmp_path):
    with migration_files(tmp_path / "older-code", drop_last=1):
        database = _init(servers, tmp_path / "database")
    port = database.cluster.running_port()
    held = read_passwords(database.passfile)
    purge = next(role for role in APPLICATION_ROLES if role.endswith("purge"))
    write_passwords(database.passfile, {r: p for r, p in held.items() if r != purge})
    with database.connect(port) as connection:
        connection.execute(f"alter role {purge} password null")

    result = cli("upgrade", "--directory", database.root)

    assert result.status == 0, result.err
    assert purge in read_passwords(database.passfile)
    _asks_every_role(database, database.cluster.running_port())


# -- converting a cluster that trusts its connections ---------------------------------------------


@dataclass(frozen=True)
class Before:
    """What a conversion may change, as it was before a refusal or a failure."""

    hba: bytes
    marker: bytes
    port: int
    verifiers: dict[str, str | None]
    state: tuple[list[str], dict[str, int]]
    backups: list[str]


def _before(database: LocalDatabase) -> Before:
    port = database.cluster.running_port()
    with database.connect(port) as connection:
        verifiers = stored_verifiers(connection, [database.owner, *APPLICATION_ROLES])
    return Before(
        hba=(database.data / "pg_hba.conf").read_bytes(),
        marker=database.marker.read_bytes(),
        port=port,
        verifiers=verifiers,
        state=_state(database),
        backups=sorted(path.name for path in database.backups.iterdir()),
    )


def _as_it_was(database: LocalDatabase, before: Before) -> None:
    """Nothing the conversion may change has changed, and the server trusts connections again."""
    assert (database.data / "pg_hba.conf").read_bytes() == before.hba
    assert database.marker.read_bytes() == before.marker
    assert not database.passfile.exists()
    assert database.cluster.running() and database.cluster.running_port() == before.port
    with database.connect(before.port) as connection:
        assert stored_verifiers(connection, list(before.verifiers)) == before.verifiers
    assert _state(database) == before.state
    assert _refusal_without_a_password(before.port, database.owner) is None
    for role in APPLICATION_ROLES:
        assert ASKED_FOR_A_PASSWORD not in (_refusal_without_a_password(before.port, role) or "")


def _refused(result, name: str) -> None:
    assert result.status == 2, (result.out, result.err)
    assert f"refused ({name})" in result.err


def _require(database: LocalDatabase):
    return cli("require-passwords", "--directory", database.root)


@postgres
def test_a_trusted_cluster_is_converted_backed_up_first_and_proven(
    trusted_world, servers, tmp_path
):
    database = _serving_copy(trusted_world, servers, tmp_path / "database")
    before = _before(database)
    first_marker = json.loads(before.marker)
    assert first_marker["profile"] == FIRST_MARKER_PROFILE
    assert _refusal_without_a_password(before.port, database.owner) is None  # trusted, as given

    result = _require(database)

    assert result.status == 0, result.err
    (backup,) = [
        b
        for b in list_backups(database.backups)
        if b.dump.name.endswith("-before-passwords.pgdump")
    ]
    check_digest(backup)
    assert backup.row_counts == before.state[1]
    assert "restorable: sha256 matches" in result.out
    for role in (database.owner, *APPLICATION_ROLES):
        assert (
            f"proof: {role} is refused without a password and connects with its own" in result.out
        )
    assert database.cluster.running() and database.cluster.running_port() == before.port
    assert _state(database) == before.state
    _asks_every_role(database, before.port)
    for url in _printed_urls(result.out).values():
        with psycopg.connect(url) as connection:
            connection.execute("select 1")

    old, new = (
        before.hba.decode().split("\n"),
        (database.data / "pg_hba.conf").read_text().split("\n"),
    )
    changed = [(a, b) for a, b in zip(old, new, strict=True) if a != b]
    assert changed and all(b == a.replace("trust", "scram-sha-256") for a, b in changed)
    made_asking = _init(servers, tmp_path / "made-asking")
    with made_asking.connect(made_asking.cluster.running_port()) as connection:
        initialised = [(r.admits, r.auth_method) for r in hba_rules(connection)]
    with database.connect(before.port) as connection:
        converted = [(r.admits, r.auth_method) for r in hba_rules(connection)]
    assert converted == initialised

    marker = json.loads(database.marker.read_text())
    assert (marker["profile"], marker["authentication"]) == (MARKER_PROFILE, "scram-sha-256")
    assert marker["passwords_required"]["backup"] == backup.dump.name
    kept = {k: v for k, v in first_marker.items() if k != "profile"}
    assert {k: marker[k] for k in kept} == kept
    passwords = list(read_passwords(database.passfile).values())
    assert not [p for p in passwords if p in result.out + result.err]
    assert _files_holding(database.root, passwords, besides=database.passfile) == []
    _refused(_require(database), "passwords-already-required")


@postgres
def test_a_conversion_refuses_while_the_application_is_connected(trusted_world, servers, tmp_path):
    database = _serving_copy(trusted_world, servers, tmp_path / "database")
    before = _before(database)

    with psycopg.connect(database.role_url(before.port, APPLICATION_ROLES[0])):
        result = _require(database)

    _refused(result, "in-use")
    _as_it_was(database, before)
    assert sorted(path.name for path in database.backups.iterdir()) == before.backups


def _add_md5_rule(database: LocalDatabase) -> None:
    with (database.data / "pg_hba.conf").open("a") as rules:
        rules.write("host all all 10.0.0.0/8 md5\n")


def _stop_a_role_logging_in(database: LocalDatabase) -> None:
    with database.connect(database.cluster.running_port()) as connection:
        connection.execute(f"alter role {APPLICATION_ROLES[1]} nologin")


def _open_the_directory(database: LocalDatabase) -> None:
    database.root.chmod(0o770)


@postgres
@pytest.mark.parametrize(
    ("damage", "name"),
    [
        (_add_md5_rule, "authentication-rules"),
        (_stop_a_role_logging_in, "login-role-missing"),
        (_open_the_directory, "passwords-exposed"),
    ],
)
def test_each_refusal_is_named_and_leaves_the_cluster_as_it_was(
    trusted_world, servers, tmp_path, damage, name
):
    database = _serving_copy(trusted_world, servers, tmp_path / "database")
    damage(database)
    before = _before(database)

    result = _require(database)

    _refused(result, name)
    database.root.chmod(0o700)
    _as_it_was(database, before)
    assert sorted(path.name for path in database.backups.iterdir()) == before.backups


@postgres
def test_a_backup_that_fails_its_proof_stops_the_change_before_it_begins(
    trusted_world, servers, tmp_path, monkeypatch
):
    database = _serving_copy(trusted_world, servers, tmp_path / "database")
    before = _before(database)

    def taken_then_damaged(*arguments, **keywords):
        backup = take_backup(*arguments, **keywords)
        damaged = bytearray(backup.dump.read_bytes())
        damaged[len(damaged) // 2] ^= 0xFF
        backup.dump.write_bytes(bytes(damaged))
        return read_backup(backup.dump)

    monkeypatch.setattr(conversion, "take_backup", taken_then_damaged)

    _refused(_require(database), "digest-mismatch")
    _as_it_was(database, before)


def _fail_proving(*arguments, **keywords):
    raise LocalDatabaseRefused(Refusal.AUTHENTICATION_CHANGE_FAILED, "a proof that failed")


def _fail_rewriting(*arguments, **keywords):
    raise OSError("the disk refused the rewritten rules")


@postgres
@pytest.mark.parametrize(
    ("step", "failure"),
    [("_prove", _fail_proving), ("rewrite_methods", _fail_rewriting)],
)
def test_a_failure_after_the_change_began_puts_everything_back(
    trusted_world, servers, tmp_path, monkeypatch, step, failure
):
    """After the proof fails every change has been made and loaded; after the rewrite fails only
    the passwords have. Either way the cluster is left as it was."""
    database = _serving_copy(trusted_world, servers, tmp_path / "database")
    before = _before(database)
    monkeypatch.setattr(conversion, step, failure)

    result = _require(database)

    assert result.status == 1, (result.out, result.err)
    assert "failed (authentication-change-failed)" in result.err
    assert "Put back:" in result.err
    _as_it_was(database, before)
    assert [
        b.dump.name for b in list_backups(database.backups) if "before-passwords" in b.dump.name
    ]


@postgres
def test_a_conversion_killed_part_way_is_finished_with_the_passwords_it_wrote(
    trusted_world, servers, tmp_path
):
    """What a run killed after step 3 leaves: a password file and passwords, a trusting server,
    and a marker that says trust. Every command still connects, and the next run finishes it."""
    database = _serving_copy(trusted_world, servers, tmp_path / "database")
    port = database.cluster.running_port()
    roles = [database.owner, *APPLICATION_ROLES]
    written = {role: f"written-before-the-kill-{index}" for index, role in enumerate(roles)}
    write_passwords(database.passfile, written)
    with database.connect(port) as connection:
        for role in roles:
            give_password(connection, role, written[role])

    status = cli("status", "--directory", database.root)
    result = _require(database)

    assert status.status == 0, status.err
    assert "trusts every connection from this computer" in status.out
    assert result.status == 0, result.err
    assert read_passwords(database.passfile) == written
    _asks_every_role(database, port)
