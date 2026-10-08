"""Which workspaces a host plays and asks models for, once guests can enter (no database).

A guest's town plays, and its people's chosen models are asked, while the guest is there; only
under durable spending is a workspace the environment does not list asked for at all, because
only a grant bounds what one visitor spends. Each test names a way that could be wrong: a guest's
model asked under process spending, a watched workspace refused, the account role read on every
request, a comparison dropped when its visitor leaves, a waiting town told it is not played here,
or a separate playback process paired with an API that plays guests differently.
"""

from __future__ import annotations

import threading
import uuid
from types import SimpleNamespace

import pytest
from exulanica.api.account_runtime import (
    GUEST_PLAY_SECONDS_DEFAULT,
    GUEST_PLAYING_MAXIMUM_DEFAULT,
    AccountUnavailable,
    GuestEntryConfig,
    load_guest_entry,
)
from exulanica.api.authorisation import TokenDirectory
from exulanica.api.decision_host import DecisionHost
from exulanica.api.services import (
    WATCHED_READ_SECONDS,
    WATCHED_STALE_SECONDS,
    Services,
    WatchedRead,
)
from exulanica.api.society_comparison_worker import (
    SLOW_SCAN_SECONDS,
    SOURCE_READ_SECONDS,
    SocietyComparisonWorker,
)
from exulanica.api.society_control_worker import (
    HOST_PLAYBACK_REFUSALS,
    PlaybackProcess,
    SocietyControlWorker,
    host_playback_refusal,
    playback_configuration_sha256,
)
from exulanica.db.account_workspaces import WatchedWorkspaces
from exulanica.models.client import PROVIDER_CREDENTIAL_ABSENT
from exulanica.spending.config import DURABLE, PROCESS
from exulanica.world.decision_roles import decision_roles

LISTED, WATCHED, WAITING, ELSEWHERE = (uuid.UUID(int=n) for n in (1, 2, 3, 4))
ORIGIN = "https://app.test"


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _Connection:
    """A connection whose transaction() is a savepoint that records how it ended."""

    def __init__(self, latest: str | None = None) -> None:
        self.savepoints: list[str] = []
        self.latest = latest
        self.asked: list[uuid.UUID] = []

    def execute(self, statement, parameters):
        self.asked.append(parameters[1])
        row = None if self.latest is None else {"reason": self.latest}
        return SimpleNamespace(fetchone=lambda: row)

    def transaction(self):
        import contextlib

        @contextlib.contextmanager
        def savepoint():
            self.savepoints.append("entered")
            try:
                yield
            except BaseException:
                self.savepoints.append("rolled back")
                raise

        return savepoint()


class _Accounts:
    """What Services reads of the account runtime: its guest entry and the watched workspaces."""

    def __init__(self, guest: GuestEntryConfig | None = None) -> None:
        self.guest = guest
        self.reads = 0

    def watched_workspaces(self) -> WatchedWorkspaces:
        self.reads += 1
        return WatchedWorkspaces(frozenset({WATCHED}), frozenset({WAITING}))

    def active_owned_workspaces(self) -> frozenset[uuid.UUID]:
        return frozenset({WATCHED, WAITING, ELSEWHERE})


def _guest(**figures) -> GuestEntryConfig:
    return GuestEntryConfig(mode="open", browser_origins=(ORIGIN,), entries_per_day=10, **figures)


def _services(*, spending_mode: str | None = DURABLE, discovery: bool = True, **changes):
    accounts = changes.pop("accounts", _Accounts(_guest()))
    return Services(
        database=None,  # type: ignore[arg-type]
        readonly_database=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        tokens=TokenDirectory(sessions={}),
        executor_shares_the_write_role=True,
        model_client=None,
        accounts=accounts,  # type: ignore[arg-type]
        society_control_workspaces=changes.pop("society_control_workspaces", (LISTED,)),
        runs_society_control_worker=discovery,
        spending_mode=spending_mode,
        spending=object() if spending_mode == DURABLE else None,  # type: ignore[arg-type]
        **changes,
    )


# -- the settings --------------------------------------------------------------------------------


def test_the_play_window_and_maximum_default_and_refuse_by_range():
    guest = _guest()
    assert (guest.play_seconds, guest.playing_maximum) == (15 * 60, 24)
    assert (GUEST_PLAY_SECONDS_DEFAULT, GUEST_PLAYING_MAXIMUM_DEFAULT) == (15 * 60, 24)
    assert _guest(playing_maximum=0).playing_maximum == 0
    for figures in (
        {"play_seconds": 59},
        {"play_seconds": 86_401},
        {"playing_maximum": -1},
        {"playing_maximum": 1_001},
    ):
        with pytest.raises(ValueError):
            _guest(**figures)


def test_the_settings_are_read_from_the_environment_and_a_bad_one_stops_startup():
    base = {
        "EXULANICA_GUEST_ENTRY": "open",
        "EXULANICA_GUEST_ENTRIES_PER_DAY": "10",
        "EXULANICA_ACCOUNT_BROWSER_ORIGINS": f'["{ORIGIN}"]',
        "EXULANICA_ACCOUNT_DATABASE_URL": "postgresql://accounts@db/x",
    }
    read = load_guest_entry(
        {**base, "EXULANICA_GUEST_PLAY_SECONDS": "600", "EXULANICA_GUEST_PLAYING_MAXIMUM": "8"}
    )
    assert read is not None and (read.play_seconds, read.playing_maximum) == (600, 8)
    with pytest.raises(AccountUnavailable):
        load_guest_entry({**base, "EXULANICA_GUEST_PLAYING_MAXIMUM": "many"})


# -- which workspaces are asked for --------------------------------------------------------------


def test_a_watched_workspace_is_asked_for_only_under_durable_spending_with_discovery():
    durable = _services()
    assert durable.discovers_model_workspaces
    assert durable.asks_models_for(LISTED) and durable.asks_models_for(WATCHED)
    assert not durable.asks_models_for(WAITING) and not durable.asks_models_for(ELSEWHERE)
    # Process spending: nothing bounds one visitor's spend, so only the listed workspace.
    process = _services(spending_mode=PROCESS)
    assert not process.discovers_model_workspaces
    assert process.asks_models_for(LISTED) and not process.asks_models_for(WATCHED)
    # Durable spending without account discovery: the listed workspace alone, as before.
    listed_only = _services(discovery=False)
    assert listed_only.asks_models_for(LISTED) and not listed_only.asks_models_for(WATCHED)


def test_the_refusals_follow_what_is_asked_for():
    role = decision_roles().deciding_for("person")
    services = _services(comparison_seeds=("a seed",), runs_comparison_worker=True)
    assert services.model_host_refusal(ELSEWHERE, role) == "models_not_run_here"
    assert services.comparison_refusal(ELSEWHERE) == "comparisons_not_run_here"
    assert services.signal_comparison_refusal(ELSEWHERE) == "comparisons_not_run_here"
    # A watched workspace passes the host's own listing and meets the next fact: no credential.
    assert services.model_host_refusal(WATCHED, role) != "models_not_run_here"
    assert services.comparison_refusal(WATCHED) == PROVIDER_CREDENTIAL_ABSENT
    assert services.signal_comparison_refusal(WATCHED) == PROVIDER_CREDENTIAL_ABSENT


def test_the_account_role_is_read_at_most_once_in_its_reuse_time():
    clock, accounts = _Clock(), _Accounts(_guest())
    services = _services(accounts=accounts, watched=WatchedRead(clock=clock))
    for _ in range(5):
        services.asks_models_for(WATCHED)
    assert accounts.reads == 1
    clock.now += WATCHED_READ_SECONDS
    services.asks_models_for(WATCHED)
    assert accounts.reads == 2


def test_a_failed_read_keeps_the_last_good_one_for_a_while_and_is_not_retried_at_once():
    clock, tries = _Clock(), []
    read = WatchedRead(clock=clock)
    assert read.get(lambda: frozenset({WATCHED})) == frozenset({WATCHED})
    clock.now += WATCHED_READ_SECONDS

    def unavailable() -> frozenset[uuid.UUID]:
        tries.append(clock.now)
        raise AccountUnavailable("the account database did not answer")

    assert read.get(unavailable) == frozenset({WATCHED})
    # Callers after a failure do not each try again: one try per reuse time.
    for _ in range(5):
        assert read.get(unavailable) == frozenset({WATCHED})
    assert len(tries) == 1
    # Past the stale limit nothing is watched, so a departed visitor's models are not asked.
    clock.now += WATCHED_STALE_SECONDS
    assert read.get(unavailable) == frozenset()
    assert len(tries) == 2
    assert WatchedRead(clock=clock).get(unavailable) == frozenset()


class _Reached(Exception):
    """Raised by the fake database: the host went past its workspace check."""


def _host(discovered) -> DecisionHost:
    def session(_workspace):
        raise _Reached

    return DecisionHost(
        database=SimpleNamespace(session=session),  # type: ignore[arg-type]
        runtime=None,  # type: ignore[arg-type]
        client=None,
        workspaces=frozenset({LISTED}),
        policy_for=lambda _workspace: None,  # type: ignore[arg-type,return-value]
        manifest=None,  # type: ignore[arg-type]
        manifest_sha256="0" * 64,
        discovered=discovered,
    )


def _claim(workspace: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(workspace_id=workspace, actor=uuid.uuid4(), world_id="world:test")


def test_the_decision_host_asks_for_a_discovered_workspace_and_no_other():
    host = _host(lambda: frozenset({WATCHED}))
    for asked in (LISTED, WATCHED):
        with pytest.raises(_Reached):
            host.before_minute(_claim(asked), lease_ends=0.0)  # type: ignore[arg-type]
    assert host.before_minute(_claim(ELSEWHERE), lease_ends=0.0) is False  # type: ignore[arg-type]
    # Without a discovered reader, as under process spending, only the listed one.
    assert _host(None).before_minute(_claim(WATCHED), lease_ends=0.0) is False  # type: ignore[arg-type]
    services = _services()
    assert services.society_runtime is None  # no runtime here, so no host is built
    assert _services(spending_mode=PROCESS).discovers_model_workspaces is False


# -- comparisons ---------------------------------------------------------------------------------


def test_a_comparison_worker_plays_the_watched_every_round_and_the_rest_on_a_slow_scan():
    """Every account workspace a server ever admitted would cost two sessions a round; only the
    watched ones are visited each round, and the rest once every slow scan, where a comparison
    whose visitor left (ELSEWHERE) is still found and played."""
    clock, reads, scans = _Clock(), [], []

    def watched() -> frozenset[uuid.UUID]:
        reads.append(clock.now)
        return frozenset({WATCHED})

    def every() -> frozenset[uuid.UUID]:
        scans.append(clock.now)
        return frozenset({WATCHED, ELSEWHERE})

    worker = SocietyComparisonWorker(
        None,  # type: ignore[arg-type]
        runner_for=lambda *_: None,
        client=None,
        manifest=None,  # type: ignore[arg-type]
        workspaces=(LISTED,),
        keeps_share=True,
        workspace_source=watched,
        slow_source=every,
        clock=clock,
    )
    assert set(worker.played_workspaces()) == {LISTED, WATCHED, ELSEWHERE}
    assert set(worker.played_workspaces()) == {LISTED, WATCHED}
    assert (len(reads), len(scans)) == (1, 1)
    clock.now += SOURCE_READ_SECONDS
    assert set(worker.played_workspaces()) == {LISTED, WATCHED}
    assert (len(reads), len(scans)) == (2, 1)
    clock.now += SLOW_SCAN_SECONDS
    assert set(worker.played_workspaces()) == {LISTED, WATCHED, ELSEWHERE}
    assert (len(reads), len(scans)) == (3, 2)

    def failing() -> frozenset[uuid.UUID]:
        scans.append(clock.now)
        raise OSError("the account database is away")

    worker._slow_source = failing
    clock.now += SLOW_SCAN_SECONDS
    assert set(worker.played_workspaces()) == {LISTED, WATCHED}
    # A failed scan waits for the next one rather than asking every round.
    assert set(worker.played_workspaces()) == {LISTED, WATCHED}
    assert len(scans) == 3


def test_a_comparison_workers_round_claims_in_every_workspace_it_plays():
    worker = SocietyComparisonWorker(
        None,  # type: ignore[arg-type]
        runner_for=lambda *_: None,
        client=None,
        manifest=None,  # type: ignore[arg-type]
        workspaces=(LISTED,),
        keeps_share=True,
        workspace_source=lambda: frozenset({WATCHED}),
        slow_source=lambda: frozenset({WATCHED, ELSEWHERE}),
    )
    stop, claimed = threading.Event(), []

    def run_once(workspace: uuid.UUID, _stop: threading.Event) -> bool:
        claimed.append(workspace)
        if len(claimed) == 3:
            stop.set()
        return False

    worker.run_once = run_once  # type: ignore[method-assign]
    worker.run(stop, poll_seconds=0.01)
    assert set(claimed) == {LISTED, WATCHED, ELSEWHERE}


def test_a_host_that_discovers_builds_a_comparison_worker_on_the_watched_and_a_slow_scan():
    services = _services(society_runtime=object(), society_control_workspaces=())
    worker = services.build_comparison_worker(keeps_share=True)
    assert worker is not None
    # The first round includes the slow scan of every account workspace; later rounds within it
    # visit only the watched ones.
    assert set(worker.played_workspaces()) == {WATCHED, WAITING, ELSEWHERE}
    assert set(worker.played_workspaces()) == {WATCHED}
    # Under process spending, with nothing listed, there is nothing to play.
    process = _services(
        spending_mode=PROCESS, society_runtime=object(), society_control_workspaces=()
    )
    assert process.build_comparison_worker(keeps_share=True) is None


# -- playback ------------------------------------------------------------------------------------


def test_a_waiting_town_is_told_so_and_one_not_watched_is_told_it_is_not_played():
    worker = SocietyControlWorker(
        None,  # type: ignore[arg-type]
        runtime=None,  # type: ignore[arg-type]
        workspaces=(LISTED,),
        workspace_source=_Accounts().watched_workspaces,
    )
    worker._workspace_snapshot()
    assert set(worker.workspaces) == {LISTED, WATCHED}
    assert worker.waiting == frozenset({WAITING})
    stop = threading.Event()
    thread = threading.Thread(target=stop.wait)
    thread.start()
    try:
        assert host_playback_refusal(worker, thread, WATCHED) is None
        assert host_playback_refusal(worker, thread, WAITING) == "guest_towns_full"
        assert host_playback_refusal(worker, thread, ELSEWHERE) == "workspace_not_played"
    finally:
        stop.set()
        thread.join()
    sentence = HOST_PLAYBACK_REFUSALS["guest_towns_full"]
    assert "waits" in sentence and "Advance one simulated minute" in sentence


def test_the_playback_digest_names_the_guests_figures_and_nothing_else_moves_it():
    def digest(guests):
        return playback_configuration_sha256(
            [LISTED], account_discovery=True, base_tick_interval_ms=8000, guests=guests
        )

    without = digest(None)
    # A host with no guests keeps the digest it had before guests existed.
    assert without == playback_configuration_sha256(
        [LISTED], account_discovery=True, base_tick_interval_ms=8000
    )
    assert len({without, digest((900, 24)), digest((600, 24)), digest((900, 8))}) == 4
    services = _services()
    assert services.playback_configuration_sha256() == digest((900, 24))
    assert _services(discovery=False).playback_configuration_sha256() != digest((900, 24))


@pytest.mark.parametrize(
    ("refused", "latest", "code"),
    [
        ({"nebius": None}, None, None),
        # A guest's own allowance spent, then the authority every guest shares spent.
        ({"nebius": ("spending_limit_reached", "workspace")}, None, "spending_cap_reached"),
        ({"nebius": ("spending_limit_reached", "authority")}, None, "spending_cap_reached"),
        # A provider never granted is not the workspace's allowance.
        (
            {"nebius": ("spending_limit_reached", "workspace"), "other": ("spending_not_granted",)},
            None,
            "spending_cap_reached",
        ),
        # One provider spent while another's allowance remains: models of the other are asked.
        ({"nebius": None, "other": ("spending_limit_reached", "authority")}, None, None),
        # The remainder fits no attempt's reservation, which the state cannot foresee: the
        # society's latest receipt says so.
        ({"nebius": None}, "spending_limit_reached", "spending_cap_reached"),
        ({"nebius": None}, "validated_choice", None),
        # Other refusals are other conditions with their own words, not the cap.
        ({"nebius": ("spending_expired", "authority")}, None, None),
        ({"nebius": ("spending_not_granted", "workspace")}, None, None),
    ],
)
def test_the_control_read_says_the_cap_is_reached_only_when_an_allowance_is_spent(
    refused, latest, code
):
    from exulanica.api.routes.society_control import MODEL_MINDS_REASONS, model_minds_code
    from exulanica.models.spending import SpendingRefused
    from exulanica.spending.status import SpendingRefusals

    refusals = SpendingRefusals(
        by_provider={
            provider: None
            if value is None
            else SpendingRefused(value[0], scope=value[1] if len(value) > 1 else "workspace")
            for provider, value in refused.items()
        }
    )
    services = SimpleNamespace(spending_refusals=lambda connection, workspace: refusals)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=services)))
    society = str(uuid.uuid4())
    connection = _Connection(latest)
    assert model_minds_code(request, connection, uuid.uuid4(), society) == code
    assert connection.asked == [uuid.UUID(society)]
    if code is not None:
        assert "keeps playing" in MODEL_MINDS_REASONS[code]


def test_no_durable_authority_states_no_cap():
    """A process no durable authority admits spends within its fuse, refused at call time."""
    from exulanica.api.routes.society_control import model_minds_code

    services = SimpleNamespace(spending_refusals=lambda connection, workspace: None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=services)))
    assert model_minds_code(request, _Connection(), uuid.uuid4()) is None


def test_a_failed_spending_read_leaves_the_control_read_answering_without_the_cap():
    """The read runs in a savepoint and its failure is logged by class: the control read, a PUT
    and a committed step answer as before."""
    from exulanica.api.routes.society_control import model_minds_code

    def failing(connection, workspace):
        raise RuntimeError("postgresql://secret@host/db is unreachable")

    connection = _Connection()
    services = SimpleNamespace(spending_refusals=failing)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=services)))
    assert model_minds_code(request, connection, uuid.uuid4()) is None
    assert connection.savepoints == ["entered", "rolled back"]


def test_services_hand_the_decision_host_the_watched_reader_only_under_durable_spending():
    """A host built with accounts asks models for watched workspaces only where every ask is
    admitted against the asking workspace's own grant."""
    durable = _services(society_runtime=object())
    host = durable.decision_host()
    assert host is not None and host.discovered is not None
    assert host.discovered() == frozenset({WATCHED})
    for spending_mode in (PROCESS, None):
        host = _services(spending_mode=spending_mode, society_runtime=object()).decision_host()
        assert host is not None and host.discovered is None, spending_mode
    # Discovery off: the listed workspaces alone, whatever the spending.
    host = _services(discovery=False, society_runtime=object()).decision_host()
    assert host is not None and host.discovered is None


def test_the_account_runtime_hands_each_read_the_guests_it_played_last():
    """Every reader in the process shares one memory of the playing guests, so a playing town
    keeps its place from one read to the next."""
    import contextlib

    from exulanica.api.account_runtime import AccountRuntime

    runtime = AccountRuntime(None, "postgresql://unused.invalid/db", None, _guest())
    asked: list[frozenset[uuid.UUID]] = []
    histories: list[dict] = []
    first = WatchedWorkspaces(frozenset({WATCHED}), frozenset({WAITING}))
    first.since = {WATCHED: 5.0, WAITING: 6.0}
    answers = iter([first, WatchedWorkspaces(frozenset({WAITING}), frozenset())])

    class _Repository:
        def watched_workspaces(self, *, guest_seconds, guests_at_most, playing, **history):
            asked.append(playing)
            histories.append(history)
            return next(answers)

    @contextlib.contextmanager
    def repository():
        yield _Repository()

    object.__setattr__(runtime, "repository", repository)
    runtime.watched_workspaces()
    runtime.watched_workspaces()
    assert asked == [frozenset(), frozenset({WATCHED})]
    # The history and the play window's tenure go with each read.
    assert [history["since"] for history in histories] == [{}, {WATCHED: 5.0, WAITING: 6.0}]
    assert {history["tenure_seconds"] for history in histories} == {_guest().play_seconds}


def test_a_playback_process_says_which_town_waits_and_which_is_not_played():
    """An API that leaves playback to a process of its own answers as the thread's host does,
    from what it last read of that process (held here as its last read)."""
    clock = _Clock()
    process = PlaybackProcess(
        None,  # type: ignore[arg-type]
        workspaces=(LISTED,),
        account_discovery=True,
        workspace_source=None,
        base_tick_interval_ms=8000,
        guests=(900, 24),
        clock=clock,
    )
    process._read = (clock.now, True, frozenset({LISTED, WATCHED}), frozenset({WAITING}))
    assert process.refusal(WATCHED) is None
    assert process.refusal(WAITING) == "guest_towns_full"
    assert process.refusal(ELSEWHERE) == "workspace_not_played"
    process._read = (clock.now, False, frozenset({LISTED, WATCHED}), frozenset({WAITING}))
    assert process.refusal(WATCHED) == "playback_worker_stopped"


def test_a_read_that_took_its_whole_timeout_is_not_tried_again_at_once():
    """The time of the last try is taken when the read ends, so the caller after a slow failure
    does not start another slow read straight away."""
    clock, tries = _Clock(), []
    read = WatchedRead(clock=clock)

    def slow_failure() -> frozenset[uuid.UUID]:
        tries.append(clock.now)
        clock.now += WATCHED_READ_SECONDS  # the account database's own timeout
        raise AccountUnavailable("the account database did not answer in time")

    assert read.get(slow_failure) == frozenset()
    clock.now += 1.0
    assert read.get(slow_failure) == frozenset()
    assert len(tries) == 1


# -- places --------------------------------------------------------------------------------------

A, B, C = (uuid.UUID(int=n) for n in (11, 12, 13))


def _allot(there, *, at_most, playing=(), since=None, now=1_000.0, tenure=900.0):
    from exulanica.db.account_workspaces import allot_places

    return allot_places(
        list(there),
        at_most=at_most,
        playing=frozenset(playing),
        since=dict(since or {}),
        now=now,
        tenure_seconds=tenure,
    )


def test_a_kept_place_is_given_up_after_the_play_window_while_another_waits():
    # A has played since 100; at 1,000 it has held its place 900 s and B waits: B plays, and A
    # joins the back of the queue from now.
    places = _allot([A, B], at_most=1, playing={A}, since={A: 100.0, B: 500.0})
    assert (places.playing, places.waiting) == ((B,), (A,))
    assert places.since[A] == 1_000.0 and places.since[B] == 1_000.0
    # Nobody waits: A keeps its place however long it has held it.
    places = _allot([A], at_most=1, playing={A}, since={A: 100.0})
    assert (places.playing, places.waiting) == ((A,), ())
    # Within the window it keeps it although B waits.
    places = _allot([A, B], at_most=1, playing={A}, since={A: 500.0, B: 600.0})
    assert (places.playing, places.waiting) == ((A,), (B,))


def test_a_freed_place_goes_to_the_one_waiting_longest_and_a_newcomer_waits_behind():
    # A entered first but began waiting after C; C has waited longest. B is new this read.
    places = _allot([A, B, C], at_most=1, since={A: 300.0, C: 200.0})
    assert places.playing == (C,) and places.waiting == (A, B)
    # With no history at all, entry order decides.
    assert _allot([A, B, C], at_most=1).playing == (A,)
    # No place: nothing plays and none waits.
    places = _allot([A, B], at_most=0, playing={A})
    assert (places.playing, places.waiting) == ((), ())


def test_with_no_guest_entry_no_guest_town_plays_and_none_waits():
    """An installation with Google sign-in and no guest entry plays no guest's town, whatever
    guest memberships remain: no place and no tenure is asked for."""
    import contextlib

    from exulanica.api.account_runtime import AccountRuntime

    runtime = AccountRuntime(None, "postgresql://unused.invalid/db", None, _guest())
    object.__setattr__(runtime, "guest", None)
    asked: list[dict] = []

    class _Repository:
        def watched_workspaces(self, **figures):
            asked.append(figures)
            return WatchedWorkspaces(frozenset({WATCHED}), frozenset())

    @contextlib.contextmanager
    def repository():
        yield _Repository()

    object.__setattr__(runtime, "repository", repository)
    runtime.watched_workspaces()
    ((figures,),) = [asked]
    assert figures["guests_at_most"] == 0 and figures["tenure_seconds"] is None


def test_services_hand_the_playback_worker_its_number_of_workers():
    assert _services(society_runtime=object()).build_society_control_worker().workers == 1
    built = _services(society_runtime=object(), society_playback_workers=3)
    assert built.build_society_control_worker().workers == 3
