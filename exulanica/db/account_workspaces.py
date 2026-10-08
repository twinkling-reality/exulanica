"""Current account-owned workspace discovery through the isolated account database role."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final

import psycopg
from psycopg.rows import dict_row

from exulanica.db.account_roles import AccountRoleUnsafe, assert_account_role
from exulanica.errors import ExulanicaError

__all__ = [
    "ACCOUNT_DATABASE_URL_ENV",
    "GUEST_PLAY_SECONDS_ENV",
    "AccountWorkspaceSource",
    "AccountWorkspaceUnavailable",
    "GuestPlaces",
    "PacedWorkspaces",
    "WatchedWorkspaces",
    "active_owned_workspaces",
    "allot_places",
    "paced_account_source",
    "watched_workspaces",
]

ACCOUNT_DATABASE_URL_ENV: Final = "EXULANICA_ACCOUNT_DATABASE_URL"
#: How long after a guest's last request the guest counts as there (the API's play window).
GUEST_PLAY_SECONDS_ENV: Final = "EXULANICA_GUEST_PLAY_SECONDS"
_GUEST_PLAY_SECONDS_DEFAULT: Final = 900
#: How often a paced source also names every active account workspace, in seconds.
SLOW_SCAN_SECONDS: Final = 300.0
_DATABASE_TIMEOUT_SECONDS: Final = 5


class AccountWorkspaceUnavailable(ExulanicaError):
    """Discovery cannot establish its narrow role or matching world database boundary."""


def active_owned_workspaces(connection: psycopg.Connection) -> frozenset[uuid.UUID]:
    """Read current owner and guest authority without treating a browser session as membership.

    A guest's workspace is theirs as an owner's is (migration 0139): the workers that drain an
    account's queues drain a guest's too, so a town a visitor makes is baked."""
    rows = connection.execute(
        "select w.workspace_id from account_workspace w "
        "join account_user u on u.user_id=w.owner_user_id "
        "join account_membership m on m.workspace_id=w.workspace_id "
        "and m.user_id=w.owner_user_id "
        "where u.disabled_at is null and w.disabled_at is null "
        "and m.revoked_at is null and m.membership_role in ('owner','guest') "
        "order by w.workspace_id"
    ).fetchall()
    return frozenset(row["workspace_id"] for row in rows)


class WatchedWorkspaces(frozenset):
    """The workspaces a host plays and asks models for, with :attr:`waiting`, the guests'
    workspaces whose visitor is there but that the playing maximum leaves unplayed."""

    waiting: frozenset[uuid.UUID]
    #: When each guest there got its place or began waiting, for the next read.
    since: dict[uuid.UUID, float]

    def __new__(
        cls, played: frozenset[uuid.UUID], waiting: frozenset[uuid.UUID] = frozenset()
    ) -> WatchedWorkspaces:
        watched = super().__new__(cls, played)
        watched.waiting = frozenset(waiting)
        watched.since = {}
        return watched


@dataclass(frozen=True)
class GuestPlaces:
    """Which guests' towns play: ``playing`` and, in the order they would take a freed place,
    ``waiting``; ``since`` holds when each got its place or began waiting (a caller's clock)."""

    playing: tuple[uuid.UUID, ...]
    waiting: tuple[uuid.UUID, ...]
    since: dict[uuid.UUID, float]


def allot_places(
    there: list[uuid.UUID],
    *,
    at_most: int,
    playing: frozenset[uuid.UUID],
    since: dict[uuid.UUID, float],
    now: float,
    tenure_seconds: float | None,
) -> GuestPlaces:
    """At most ``at_most`` of the guests ``there`` (in the order they entered) play.

    A guest in ``playing`` keeps its place while it is there, except that one which has held it
    ``tenure_seconds`` or longer gives it up while another waits, and joins the back of the queue.
    A freed place goes to the guest waiting longest (``since``), a newcomer waiting from ``now``.
    With no place at all none waits. Pure: the caller keeps ``since`` between reads."""
    if at_most <= 0:
        return GuestPlaces((), (), {})
    known = {guest: since.get(guest, now) for guest in there}
    kept = [guest for guest in there if guest in playing]
    kept.sort(key=lambda guest: known[guest])
    kept = kept[:at_most]
    rotated: list[uuid.UUID] = []
    if tenure_seconds is not None and len(there) > at_most:
        rotated = [guest for guest in kept if now - known[guest] >= tenure_seconds]
        kept = [guest for guest in kept if guest not in rotated]
    for guest in rotated:
        known[guest] = now
    order = {guest: position for position, guest in enumerate(there)}
    queue = sorted(
        (guest for guest in there if guest not in kept),
        key=lambda guest: (guest in rotated, known[guest], order[guest]),
    )
    taken = queue[: at_most - len(kept)]
    for guest in taken:
        known[guest] = now
    return GuestPlaces(tuple(kept) + tuple(taken), tuple(queue[len(taken) :]), known)


def watched_workspaces(
    connection: psycopg.Connection,
    *,
    guest_seconds: int,
    guests_at_most: int,
    playing: frozenset[uuid.UUID] = frozenset(),
    since: dict[uuid.UUID, float] | None = None,
    now: float = 0.0,
    tenure_seconds: float | None = None,
) -> WatchedWorkspaces:
    """The workspaces a host plays and asks models for: every active owner's, and the guests'
    whose visitor was there lately.

    A guest's workspace is there while one of its browser sessions, unrevoked and unexpired, was
    used within ``guest_seconds`` (its ``seen_at``, migration 0139). Which play is
    :func:`allot_places`'s: at most ``guests_at_most``; a guest in ``playing``, the set the caller
    played last, keeps its place while it is there, for ``tenure_seconds`` at most while another
    waits; a freed place goes to the guest waiting longest (``since``, which the caller keeps), or,
    with no history, the one who entered first (its first session's ``created_at``); the rest wait
    (:attr:`WatchedWorkspaces.waiting`). With no place at all (``guests_at_most`` 0) none waits:
    no guest's town plays here, which a reader says as it says any workspace this host does not
    play. A visitor who left stops being played, so a town whose people a model runs spends
    nothing after them. :attr:`WatchedWorkspaces.since` is the history to hand back next time."""
    owners = connection.execute(
        "select w.workspace_id from account_workspace w "
        "join account_user u on u.user_id=w.owner_user_id "
        "join account_membership m on m.workspace_id=w.workspace_id "
        "and m.user_id=w.owner_user_id "
        "where u.disabled_at is null and w.disabled_at is null "
        "and m.revoked_at is null and m.membership_role='owner'"
    ).fetchall()
    guests = connection.execute(
        "select w.workspace_id from account_workspace w "
        "join account_user u on u.user_id=w.owner_user_id "
        "join account_membership m on m.workspace_id=w.workspace_id "
        "and m.user_id=w.owner_user_id "
        "join account_browser_session s on s.workspace_id=w.workspace_id "
        "and s.user_id=w.owner_user_id "
        "where u.disabled_at is null and w.disabled_at is null "
        "and m.revoked_at is null and m.membership_role='guest' "
        "and s.revoked_at is null and s.expires_at > now() "
        "and s.seen_at >= now() - make_interval(secs => %s) "
        "group by w.workspace_id order by min(s.created_at), w.workspace_id",
        (guest_seconds,),
    ).fetchall()
    places = allot_places(
        [row["workspace_id"] for row in guests],
        at_most=guests_at_most,
        playing=playing,
        since={} if since is None else since,
        now=now,
        tenure_seconds=tenure_seconds,
    )
    watched = WatchedWorkspaces(
        frozenset(row["workspace_id"] for row in owners) | frozenset(places.playing),
        frozenset(places.waiting),
    )
    watched.since = places.since
    return watched


def _prepare(connection: psycopg.Connection) -> None:
    connection.execute("set time zone 'UTC'")
    connection.execute(
        "select set_config('statement_timeout', %s, false)",
        (f"{_DATABASE_TIMEOUT_SECONDS}s",),
    )


def _binding(connection: psycopg.Connection) -> tuple[object, ...]:
    """Compare resolved endpoints and effective schemas, not opaque DSN strings."""
    row = connection.execute(
        "select current_database() database_name,current_schema() schema_name,"
        "current_setting('search_path') search_path,inet_server_addr()::text server_address,"
        "inet_server_port() server_port"
    ).fetchone()
    if row is None or row["schema_name"] is None:
        raise AccountWorkspaceUnavailable("account workspace database has no effective schema")
    return (
        connection.info.host,
        connection.info.port,
        connection.info.dbname,
        row["database_name"],
        row["schema_name"],
        row["search_path"],
        row["server_address"],
        row["server_port"],
    )


@dataclass(frozen=True, slots=True)
class AccountWorkspaceSource:
    """Callable fresh-authority source for a separately hosted background worker."""

    account_database_url: str = field(repr=False)
    application_database_url: str = field(repr=False)

    def verify(self) -> AccountWorkspaceSource:
        """Fail startup unless account and world roles are narrow peers on one schema."""
        try:
            with psycopg.connect(
                self.account_database_url,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=_DATABASE_TIMEOUT_SECONDS,
            ) as account:
                _prepare(account)
                assert_account_role(account)
                account_binding = _binding(account)
            with psycopg.connect(
                self.application_database_url,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=_DATABASE_TIMEOUT_SECONDS,
            ) as application:
                _prepare(application)
                application_binding = _binding(application)
        except (psycopg.Error, AccountRoleUnsafe) as exc:
            raise AccountWorkspaceUnavailable(
                "account workspace database role is unavailable or unsafe"
            ) from exc
        if account_binding != application_binding:
            raise AccountWorkspaceUnavailable(
                "account and application URLs must name the same database/schema"
            )
        return self

    def __call__(self) -> frozenset[uuid.UUID]:
        """Open a fresh account-role connection so revocation is never a retained cache."""
        try:
            with psycopg.connect(
                self.account_database_url,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=_DATABASE_TIMEOUT_SECONDS,
            ) as connection:
                _prepare(connection)
                return active_owned_workspaces(connection)
        except psycopg.Error as exc:
            raise AccountWorkspaceUnavailable("account workspace discovery is unavailable") from exc

    def recent(self, guest_seconds: int) -> frozenset[uuid.UUID]:
        """Every active owner's workspace and every guest's seen within ``guest_seconds``, on a
        fresh account-role connection: the workspaces whose people are there."""
        try:
            with psycopg.connect(
                self.account_database_url,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=_DATABASE_TIMEOUT_SECONDS,
            ) as connection:
                _prepare(connection)
                return frozenset(
                    watched_workspaces(
                        connection, guest_seconds=guest_seconds, guests_at_most=1_000_000
                    )
                )
        except psycopg.Error as exc:
            raise AccountWorkspaceUnavailable("account workspace discovery is unavailable") from exc


@dataclass
class PacedWorkspaces:
    """A worker's account workspaces, paced: every pass the ones whose people are there (owners,
    and guests seen within the play window, :meth:`AccountWorkspaceSource.recent`), and once every
    :data:`SLOW_SCAN_SECONDS` every active one (the source itself). A guest's work is queued while
    the guest is there, so it is drained at once; work left when a guest leaves, or whose claim
    lapsed, is drained by the slow scan; guests who are not there cost a pass nothing."""

    source: AccountWorkspaceSource
    guest_seconds: int = _GUEST_PLAY_SECONDS_DEFAULT
    slow_seconds: float = SLOW_SCAN_SECONDS
    clock: Callable[[], float] = time.monotonic
    _scanned_at: float | None = field(default=None, init=False, repr=False)

    def __call__(self) -> frozenset[uuid.UUID]:
        now = self.clock()
        recent = self.source.recent(self.guest_seconds)
        if self._scanned_at is None or now - self._scanned_at >= self.slow_seconds:
            self._scanned_at = now
            return recent | self.source()
        return recent


def paced_account_source(
    account_url: str | None, application_url: str, environ: Mapping[str, str]
) -> PacedWorkspaces | None:
    """A verified, paced account workspace source for a worker, or None without an account URL.
    The play window is the API's (:data:`GUEST_PLAY_SECONDS_ENV`, default 900 seconds)."""
    if not account_url:
        return None
    raw = (environ.get(GUEST_PLAY_SECONDS_ENV) or "").strip()
    guest_seconds = int(raw) if raw else _GUEST_PLAY_SECONDS_DEFAULT
    if not 60 <= guest_seconds <= 86_400:
        raise ValueError(f"{GUEST_PLAY_SECONDS_ENV} is 60 to 86,400 seconds")
    return PacedWorkspaces(
        AccountWorkspaceSource(account_url, application_url).verify(), guest_seconds
    )
