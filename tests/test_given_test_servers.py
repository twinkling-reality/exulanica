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

import pytest

from conftest import given_server_for, given_servers

FIRST = "postgresql://postgres@localhost:5432/exulanica_spine_test"
SECOND = "postgresql://postgres@localhost:5433/exulanica_spine_test"


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
