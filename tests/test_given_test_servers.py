"""A server of its own for each test worker, from a list of servers somebody else started.

Continuous integration runs the backend suite on pytest-xdist workers with one PostgreSQL container
each, named in ``EXULANICA_TEST_DATABASE_URLS``, because a hosted runner has no server binaries
for the private servers ``scripts/test_postgres.py`` initialises. Two workers on one server fail
each other's tests through the database's advisory locks and the server's roles, so what is held
here is that the list never puts two workers on one server: each worker takes the URL at its own
position, a server named twice is refused, and a worker the list has no server for is refused
rather than given one another worker holds.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import given_server_for, given_servers

ROOT = Path(__file__).resolve().parents[1]

FIRST = "postgresql://postgres@localhost:5432/exulanica_spine_test"
SECOND = "postgresql://postgres@localhost:5433/exulanica_spine_test"
#: A server no test reaches: nothing listens on the discard port, so a refusal that names its
#: own reason was made before anything connected.
UNREACHED = "postgresql://postgres@127.0.0.1:9"


def test_each_worker_takes_the_server_at_its_own_position():
    urls = given_servers(f"  {FIRST}\n{SECOND} ")
    assert urls == [FIRST, SECOND]
    assert given_server_for("gw0", urls) == FIRST
    assert given_server_for("gw1", urls) == SECOND
    # A serial run is one process, and it takes the first.
    assert given_server_for(None, urls) == FIRST


def test_a_worker_past_the_list_is_refused_rather_than_given_a_server_in_use():
    """pytest-xdist numbers a worker that replaces a crashed one past the others."""
    with pytest.raises(pytest.UsageError, match="worker gw2 has no server of its own"):
        given_server_for("gw2", [FIRST, SECOND])


@pytest.mark.parametrize(
    "again",
    [
        pytest.param(
            "postgresql://postgres@localhost:5432/another_test", id="another-database-of-it"
        ),
        pytest.param("postgresql://other@localhost/exulanica_spine_test", id="its-default-port"),
    ],
)
def test_one_server_named_twice_is_refused(again):
    """Two databases of one server share its roles, so they are one server here."""
    with pytest.raises(pytest.UsageError, match="names the server at localhost:5432 twice"):
        given_servers(f"{FIRST} {again}")


@pytest.mark.parametrize(
    ("listed", "refusal"),
    [
        pytest.param(" \n ", "names no server", id="nothing"),
        pytest.param(f"{FIRST} not-a-url", "which is not a URL", id="not-a-url"),
    ],
)
def test_a_list_that_names_no_usable_servers_is_refused(listed, refusal):
    with pytest.raises(pytest.UsageError, match=refusal):
        given_servers(listed)


def test_a_database_the_harness_may_not_touch_is_refused_before_anything_connects():
    """Preparing a server creates roles that belong to all of it, so a database whose name lacks
    "test", the harness's one rule for a database, is refused while the list is read."""
    with pytest.raises(pytest.UsageError, match="does not contain 'test'"):
        given_servers(f"{FIRST} {UNREACHED}/postgres")


def test_a_worker_not_numbered_by_pytest_xdist_is_refused():
    with pytest.raises(pytest.UsageError, match="not numbered gw0, gw1 and on"):
        given_server_for("custom", [FIRST, SECOND])


def test_no_test_sees_the_list_its_process_took_a_server_from():
    """A process that takes a server from the list withdraws the list, so a child pytest a test
    starts sees one URL, as a serial run on a named database does. Under the list, as continuous
    integration runs, this holds only because of that; elsewhere the list was never set."""
    assert "EXULANICA_TEST_DATABASE_URLS" not in os.environ


#: The variables a parent run sets for its own server, which a child must not inherit here.
_PARENTS = (
    "EXULANICA_TEST_DATABASE_URL",
    "EXULANICA_TEST_DATABASE_URLS",
    "EXULANICA_TEST_POSTGRES",
    "EXULANICA_TEST_POSTGRES_OWNER",
)


@pytest.mark.parametrize(
    ("environment", "arguments", "refusal"),
    [
        pytest.param(
            {"EXULANICA_TEST_POSTGRES": "private"},
            [],
            "not more",
            id="the-list-beside-private-servers",
        ),
        pytest.param(
            {"EXULANICA_TEST_DATABASE_URL": f"{UNREACHED}/other_test"},
            [],
            "not more",
            id="the-list-beside-one-url",
        ),
        pytest.param({}, ["-n", "2"], "starts 2 workers", id="fewer-servers-than-workers"),
        pytest.param(
            {"EXULANICA_TEST_DATABASE_URLS": f"{UNREACHED}/a_test {UNREACHED}/b_test"},
            [],
            "names the server at 127.0.0.1:9 twice",
            id="one-server-named-twice",
        ),
        pytest.param(
            {"EXULANICA_TEST_DATABASE_URLS": f"{UNREACHED}/postgres"},
            [],
            "does not contain 'test'",
            id="a-database-not-named-test",
        ),
    ],
)
def test_pytest_itself_stops_on_a_list_it_cannot_use(environment, arguments, refusal):
    """The refusals made in pytest_configure, through a child pytest as a person would meet them:
    each stops the run with a usage error before collection, and none needs a server."""
    child = {key: value for key, value in os.environ.items() if key not in _PARENTS}
    child["EXULANICA_TEST_DATABASE_URLS"] = f"{UNREACHED}/exulanica_spine_test"
    child.update(environment)
    finished = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider", *arguments],
        cwd=ROOT,
        env=child,
        capture_output=True,
        text=True,
        check=False,
    )
    assert finished.returncode == pytest.ExitCode.USAGE_ERROR, finished.stdout + finished.stderr
    assert refusal in finished.stderr, finished.stderr
