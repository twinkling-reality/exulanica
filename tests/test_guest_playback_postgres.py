"""A visitor's town plays while the visitor is there, and only so many play at once.

Account discovery tells the host which workspaces it plays and asks models for
(:func:`~exulanica.db.account_workspaces.watched_workspaces`): every active owner's, and a guest's
while one of its sessions was used within the play window, at most the playing maximum: a playing
town keeps its place, and with no history a freed place goes to the visitor who entered first;
the others there wait (the history and the play window's tenure are
:func:`~exulanica.db.account_workspaces.allot_places`'s, tested without a database). Each test
names a way that could be wrong: a visitor who left still played (and still spending), a visitor
who logged out or was disabled still played, an owner's world dropped, a playing town losing its
place to a newcomer, or a visitor told it waits on a host that plays no guest's town.

The expected answers come from the timeline each test makes (who entered when, who logged out),
never from the query under test.
"""

from __future__ import annotations

import time
import uuid

import psycopg
import pytest
from exulanica.api.account_repository import AccountRepository
from exulanica.db.account_workspaces import watched_workspaces
from psycopg.rows import dict_row

from account_fixtures import account_role as account_role

pytestmark = pytest.mark.postgres

SESSION_SECONDS = 7 * 24 * 60 * 60
#: Enough guests a day for every test here, above whatever the day already holds.
PER_DAY = 1_000_000


def _connect(account_role) -> psycopg.Connection:
    return psycopg.connect(account_role, autocommit=True, row_factory=dict_row)


def _guest(account_role) -> tuple[uuid.UUID, str]:
    """A guest who has just entered: their workspace and session token."""
    with _connect(account_role) as connection:
        entry = AccountRepository(connection).enter_guest(
            entries_per_day=PER_DAY, session_seconds=SESSION_SECONDS
        )
    return entry.account.session.workspace_id, entry.token


def _owner(account_role) -> uuid.UUID:
    """An account owner's workspace, as a sign-in makes one, with no browser session at all."""
    user, workspace = uuid.uuid4(), uuid.uuid4()
    with _connect(account_role) as connection, connection.transaction():
        connection.execute(
            "insert into account_user (user_id, actor_id) values (%s, %s)", (user, uuid.uuid4())
        )
        connection.execute(
            "insert into account_workspace (workspace_id, owner_user_id) values (%s, %s)",
            (workspace, user),
        )
        connection.execute(
            "insert into account_membership (workspace_id, user_id, membership_role) "
            "values (%s, %s, 'owner')",
            (workspace, user),
        )
    return workspace


def _watched(account_role, *, seconds: int, at_most: int, playing=frozenset()):
    with _connect(account_role) as connection:
        return watched_workspaces(
            connection, guest_seconds=seconds, guests_at_most=at_most, playing=playing
        )


def _seen_ahead(account_role, workspace: uuid.UUID) -> None:
    """Move a guest's last use a day ahead (it only moves forward), so it is there for any
    window however long the machine takes between here and the read."""
    with _connect(account_role) as connection:
        connection.execute(
            "update account_browser_session set seen_at = now() + interval '1 day' "
            "where workspace_id = %s",
            (workspace,),
        )


def test_a_visitor_there_is_played_one_who_left_is_not_and_an_owner_always_is(account_role):
    owner = _owner(account_role)
    left, _ = _guest(account_role)
    time.sleep(2)
    there, there_token = _guest(account_role)
    _seen_ahead(account_role, there)
    # The window is one second: the first visitor was last seen at least two seconds ago, and a
    # slower machine only makes that longer.
    watched = _watched(account_role, seconds=1, at_most=1_000)
    assert owner in watched
    assert there in watched
    assert left not in watched and left not in watched.waiting
    # A long window holds them both.
    assert {left, there} <= _watched(account_role, seconds=3_600, at_most=1_000)
    # The account database is the session's: a visitor seen a day ahead leaves, so later tests'
    # places are their own.
    _logout(account_role, there_token)


def _logout(account_role, *tokens: str) -> None:
    with _connect(account_role) as connection:
        for token in tokens:
            AccountRepository(connection).logout(token)


def test_a_playing_town_keeps_its_place_and_a_freed_place_goes_to_the_first_to_enter(
    account_role,
):
    """Its own three visitors are seen a day ahead and read through a one-second window, so
    visitors other tests left in the session's account database are not there."""
    entered = [_guest(account_role) for _ in range(3)]
    (first, first_token), (second, second_token), (third, third_token) = entered
    every = {first, second, third}
    for workspace in every:
        _seen_ahead(account_role, workspace)

    def watched(at_most: int, playing=frozenset()):
        return _watched(account_role, seconds=1, at_most=at_most, playing=playing)

    try:
        # Nobody played before: the place goes to the one who entered first.
        read = watched(1)
        assert first in read and {second, third} <= read.waiting
        assert not ({second, third} & read)
        # The second was playing: it keeps its place.
        read = watched(1, frozenset({second}))
        assert second in read and {first, third} <= read.waiting
        # It leaves: with no history kept here, its place goes to the one who entered first.
        _logout(account_role, second_token)
        read = watched(1, frozenset({second}))
        assert first in read and third in read.waiting and second not in read.waiting
        # Two places, one kept: the kept one and the longest waiting.
        assert {first, third} <= watched(2, frozenset({third}))
        # No place at all: no guest's town plays here and none is told it waits for one; an
        # owner's world still plays.
        owner = _owner(account_role)
        read = watched(0, frozenset(every))
        assert owner in read and not (every & read) and not (every & read.waiting)
    finally:
        _logout(account_role, first_token, third_token)


def test_a_visitor_who_logged_out_is_neither_played_nor_waiting(account_role):
    workspace, token = _guest(account_role)
    assert workspace in _watched(account_role, seconds=3_600, at_most=1_000)
    with _connect(account_role) as connection:
        AccountRepository(connection).logout(token)
    watched = _watched(account_role, seconds=3_600, at_most=1_000)
    assert workspace not in watched and workspace not in watched.waiting


def test_a_visitor_whose_account_was_disabled_is_neither_played_nor_waiting(account_role):
    """The administrative disable ends the account's sessions; however recently its session was
    used, its town is neither played nor waiting. (A session past its expiry is refused by the
    same query's ``expires_at`` term; a session lasts at least a minute, too long to wait here.)"""
    disabled, _ = _guest(account_role)
    _seen_ahead(account_role, disabled)
    assert disabled in _watched(account_role, seconds=3_600, at_most=1_000)
    with _connect(account_role) as connection:
        (row,) = connection.execute(
            "select owner_user_id from account_workspace where workspace_id = %s", (disabled,)
        ).fetchall()
        AccountRepository(connection).disable_account(row["owner_user_id"])
    watched = _watched(account_role, seconds=3_600, at_most=1_000)
    assert disabled not in watched and disabled not in watched.waiting


@pytest.mark.parametrize(
    "ended",
    [
        # Each guard of the guest query on its own, set directly with the immutability triggers
        # off for the one statement, as no product path sets one without the others.
        "update account_browser_session set expires_at = created_at + interval '1 millisecond' "
        "where workspace_id = %(w)s",
        "update account_user set disabled_at = now() where user_id = "
        "(select owner_user_id from account_workspace where workspace_id = %(w)s)",
        "update account_workspace set disabled_at = now() where workspace_id = %(w)s",
        "update account_membership set revoked_at = now() where workspace_id = %(w)s",
    ],
    ids=["session-expired", "user-disabled", "workspace-disabled", "membership-revoked"],
)
def test_each_ended_authority_stops_a_guest_being_played(account_role, spine_schema, ended):
    from tests_support_api import scratch_database

    workspace, token = _guest(account_role)
    _seen_ahead(account_role, workspace)
    assert workspace in _watched(account_role, seconds=3_600, at_most=1_000)
    _psycopg, scratch = spine_schema
    with scratch_database(scratch).unscoped() as admin, admin.transaction():
        admin.execute("set local session_replication_role = replica")
        admin.execute(ended, {"w": workspace})
    watched = _watched(account_role, seconds=3_600, at_most=1_000)
    assert workspace not in watched and workspace not in watched.waiting
    _logout(account_role, token)


def test_a_workers_recent_read_names_the_owners_and_every_guest_there_and_no_other(account_role):
    """What a background worker drains each pass: every active owner's workspace and every guest
    seen within the window, with no playing maximum, and not a guest who left."""
    from exulanica.db.account_workspaces import AccountWorkspaceSource

    owner = _owner(account_role)
    left, left_token = _guest(account_role)
    time.sleep(2)
    entered = [_guest(account_role) for _ in range(3)]
    for workspace, _ in entered:
        _seen_ahead(account_role, workspace)
    recent = AccountWorkspaceSource(account_role, "not used by this read").recent(1)
    assert owner in recent
    assert {workspace for workspace, _ in entered} <= recent
    assert left not in recent
    _logout(account_role, left_token, *(token for _, token in entered))
