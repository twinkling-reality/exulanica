"""A day's comparison, through the application as deployed: planned, started, played hour by hour
by a host's worker, stopped and resumed, fenced, cancelled and read.

A generated small town's living society is compared over a day of three hours here, a test's own
protocol with every other value the day's, read by a test line measured over that window, so the
mechanics a day of 1440 minutes runs by run in seconds. A scripted model chooses for four named
people. What is held:

- the plan offers a day where a line is measured over it, and states what one decided person's
  run can ask and call; the start records the day; the worker plays every run hour by hour and
  seals each hour; the result is read under the fifth score, the listing counts the hours sealed,
  the day's read sets every minute of every person out with no replay, and each hour is read by a
  replay from the state the hour before it sealed;
- a host that stops part way leaves the run open, and the next claim goes on from its last sealed
  hour: the run is what its receipts make from its genesis, minute for minute, and nothing the host
  recorded was asked again;
- a run whose stored receipts are not the ones its minutes rebuild fails as ``interrupted`` when
  it is resumed, asking nothing;
- a host killed inside a minute, between two of its asks or between two of the receipts its one
  transaction inserts, has stored none of that minute, and the next claim asks from that minute
  on and nothing before it;
- a host whose lease another claim took, while it asked, sealed an hour or finished the day,
  writes nothing more of a day's run;
- a seed whose runs a host stopped part way, one of them not begun, is closed whole by its own
  name where the next claim does not admit it, asking nothing more;
- an hour whose sealed record its receipts do not replay to is refused by name, and a comparison
  over an hour has no later hour and no day;
- a day whose inputs lose their rights fails as ``input_unavailable`` at the end of the hour it
  lost them in, sealing no further hour, and its overview is unavailable while they are lost;
- a cancelled day keeps the hours it sealed, which stay readable;
- with no line measured for a day, and for a society that keeps no day, a day is not offered.
"""

from __future__ import annotations

import dataclasses
import json
import multiprocessing
import os
import signal
import threading
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from exulanica.api import society_comparison_runner as runner_module
from exulanica.api import society_comparison_start as start_module
from exulanica.api.routes import society_comparisons as routes
from exulanica.api.society_comparison_start import StartRefused, window_catalogs
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.world import society_comparison_reading as reading
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_catalogs import DAY_COMPARISON_VERSIONS
from exulanica.world.society_comparison import (
    HOUR_TICKS,
    HourStart,
    first_hour,
    replay_hour,
)
from exulanica.world.society_comparison_repository import SocietyComparisonRepository
from exulanica.world.society_comparison_start_repository import SocietyComparisonStarts
from exulanica.world.society_decision_contract import person_role

import test_society_comparison_postgres as compared
from comparison_support import SEEDS, seeded_catalogs
from test_society_living_town_postgres import (  # noqa: F401
    TOWN,
    _every_town_a_test_makes_is_made,
)
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

MANIFEST = load_manifest()
MODEL = MANIFEST.offered_models(person_role().chosen)[0]
#: The day these tests compare over: three hours, every other value the day's.
HOURS = 3
WINDOW = HOURS * HOUR_TICKS
#: The reading catalog the code ships.
LINE = reading.READING_CATALOG


def _day_catalogs():
    """The day's catalogs with the tests' seeds and a window of three hours."""
    day = seeded_catalogs(versions=DAY_COMPARISON_VERSIONS)
    protocol = dict(day.protocol)
    protocol["window_ticks"] = {**protocol["window_ticks"], "value": WINDOW}
    return dataclasses.replace(day, protocol=protocol)


def _line_over_the_window(tmp_path: Path) -> Path:
    """The reading catalog with a living line over the tests' window beside the hour's: the
    hour's own figures, standing for a line measured over every hour of a day."""
    document = json.loads(LINE.read_text(encoding="utf-8"))
    hour = next(entry for entry in document["entries"] if entry["key"] == "living")
    document["entries"].append({**hour, "key": f"living-{WINDOW}", "window_ticks": WINDOW})
    path = tmp_path / "society-comparison-reading.v2.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class _Counting(compared._Chooser):
    """The scripted chooser, which may stop its host once it has answered ``stop_after`` asks."""

    def __init__(self) -> None:
        super().__init__()
        self.stop_after: int | None = None
        self.stop: threading.Event | None = None
        self.on_ask = None

    def post_json(self, url, *, headers, payload, timeout):
        answered = super().post_json(url, headers=headers, payload=payload, timeout=timeout)
        if self.on_ask is not None:
            self.on_ask(len(self.requests))
        if (
            self.stop is not None
            and self.stop_after is not None
            and len(self.requests) >= self.stop_after
        ):
            self.stop.set()
        return answered


@pytest.fixture(name="town")
def _town(request, monkeypatch, tmp_path) -> dict[str, Any]:
    """A small town made through the application, its living society, a host asking a scripted
    model, and a day of three hours its comparisons may run over."""
    api = request.getfixturevalue("imported_made")
    workspace = api.repository.workspace_id
    transport = _Counting()
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services,
        model_client=ModelClient(
            api_key="test-key-not-real",
            manifest=MANIFEST,
            transport=transport,
            budget=BudgetGuard(ceiling_usd=Decimal("50"), max_calls=1_000_000),
        ),
        society_control_workspaces=(workspace,),
        comparison_seeds=tuple(SEEDS),
        comparison_catalogs=seeded_catalogs(),
        comparisons_played_elsewhere=True,
    )
    day = _day_catalogs()
    real = window_catalogs

    def windows(base, window, engine):
        found = real(base, window, engine)
        return day if window == "day" else found

    monkeypatch.setattr(routes, "window_catalogs", windows)
    monkeypatch.setattr(reading, "READING_CATALOG", _line_over_the_window(tmp_path))
    made = api.post("/worlds/generated", {"recipe": "small_town", "title": "A day's town"})
    assert made.status_code == 201, made.text
    entry = made.json()
    scope = f"?world_id={entry['world_id']}"
    society = api.post(
        f"/world/versions/{entry['authored_version_id']}/society{scope}",
        {"region_id": "region:generated", "profile": TOWN},
    )
    assert society.status_code in (200, 201), society.text
    people = sorted(person["id"] for person in society.json()["state"]["inhabitants"])
    return {
        "api": api,
        "entry": entry,
        "people": people,
        "transport": transport,
        "workspace": workspace,
        "comparisons": f"/world/versions/{entry['authored_version_id']}/society/comparisons",
        "scope": scope,
    }


def _group(town) -> list[str]:
    return town["people"][:4]


def _plan(town, window: str = "day", group: list[str] | None = None) -> dict[str, Any]:
    query = (
        f"{town['scope']}&role={person_role().key}&group=named"
        + "".join(f"&person={person}" for person in group or _group(town))
        + f"&model={MODEL.provider}/{MODEL.model_id}&seeds=1&window={window}"
    )
    planned = town["api"].get(f"{town['comparisons']}/plan{query}")
    assert planned.status_code == 200, planned.text
    return planned.json()


def _start(
    town, *, bound: str | None = None, window: str = "day", group: list[str] | None = None
) -> str:
    """Start the tests' comparison, its bound the most it can cost unless one is named."""
    group = group or _group(town)
    if bound is None:
        bound = _plan(town, window, group)["plan"]["most_usd"]
    comparison_id = str(uuid.uuid4())
    started = town["api"].post(
        f"{town['comparisons']}{town['scope']}",
        {
            "comparison_id": comparison_id,
            "role": person_role().key,
            "group": {"kind": "named", "people": group},
            "models": [{"provider": MODEL.provider, "model_id": MODEL.model_id}],
            "control": False,
            "seeds": 1,
            "bound_usd": bound,
            "window": window,
        },
    )
    assert started.status_code == 201, started.text
    return comparison_id


def _worker(town):
    return town["api"].client.app.state.services.build_comparison_worker(keeps_share=True)


def _result(town, comparison_id: str) -> dict[str, Any]:
    read = town["api"].get(f"{town['comparisons']}/{comparison_id}{town['scope']}")
    assert read.status_code == 200, read.text
    return read.json()


def test_a_day_is_planned_started_played_hour_by_hour_and_read(town):
    api = town["api"]
    plan = _plan(town)
    day = next(window for window in plan["windows"] if window["window"] == "day")
    assert day["refusal"] is None and (day["window_ticks"], day["hours"]) == (WINDOW, HOURS)
    assert plan["plan_refusal"] is None, plan["plan_refusal"]
    assert plan["window_ticks"] == WINDOW
    assert plan["plan"]["per_person"] == {"asks_most": WINDOW, "calls_most": 2 * WINDOW}
    assert plan["plan"]["providers"] == [
        {"provider": MODEL.provider, "calls_most": plan["plan"]["calls_most"]}
    ]
    (arm,) = plan["plan"]["minutes"]
    assert Decimal(arm["most_usd_per_run"]) == Decimal(arm["ask_bound_usd"]) * WINDOW * 4
    comparison_id = _start(town)
    assert _worker(town).run_once(town["workspace"]) is True
    asked = len(town["transport"].requests)
    assert asked > 0
    result = _result(town, comparison_id)
    assert (result["score_version"], result["window_ticks"], result["hours"]) == (5, WINDOW, HOURS)
    assert result["start"]["state"] == "finished"
    (seed,) = result["seeds"]
    assert {run["status"] for run in seed["runs"].values()} == {"completed"}
    assert seed["runs"]["model_a"]["terms"]["ticks"] == WINDOW
    (listed,) = api.get(f"{town['comparisons']}{town['scope']}").json()["comparisons"]
    assert listed["hours_sealed"] == listed["hours_expected"] == 3 * HOURS
    run_id = seed["runs"]["model_a"]["run_id"]
    overview = api.get(f"{town['comparisons']}/{comparison_id}/runs/{run_id}/day{town['scope']}")
    assert overview.status_code == 200, overview.text
    document = overview.json()
    assert (document["hours"], document["hours_sealed"], document["status"]) == (
        HOURS,
        HOURS,
        "completed",
    )
    assert {len(minutes["doing"]) for minutes in document["minutes"].values()} == {WINDOW}
    assert sorted(person["id"] for person in document["people"] if person["in_group"]) == _group(
        town
    )
    for hour in range(HOURS):
        drawn = api.get(
            f"{town['comparisons']}/{comparison_id}/runs/{run_id}{town['scope']}&hour={hour}"
        )
        assert drawn.status_code == 200, drawn.text
        assert drawn.json()["replay_verified"] is True
        assert drawn.json()["window"]["first_tick"] == hour * HOUR_TICKS
        assert drawn.json()["minutes"][0]["tick"] == hour * HOUR_TICKS
    past = api.get(f"{town['comparisons']}/{comparison_id}/runs/{run_id}{town['scope']}&hour=3")
    assert (past.status_code, past.json()["code"]) == (422, "hour_not_in_window")
    # Reading asks nothing.
    assert len(town["transport"].requests) == asked


def _pure_replay_from_genesis(town, comparison_id: str, run_id: str) -> list[str]:
    """The run's every minute digest, replayed from its genesis through the receipts it stored,
    hour by hour, with no stored state."""
    services = town["api"].client.app.state.services
    runner = services.comparison_runner(
        town["workspace"], town["entry"]["world_id"], uuid.UUID(int=0)
    )
    with services.database.session(town["workspace"]) as connection:
        repository = runner._repository(connection)
        plan, _definition = repository.read_plan(uuid.UUID(comparison_id), uuid.UUID(run_id))
        hours = repository.hours(uuid.UUID(run_id))
        start = first_hour(plan)
        digests: list[str] = []
        for row in hours:
            stored = repository.stored_between(
                uuid.UUID(run_id), start.first_sequence, int(row["decision_seq_end"])
            )
            played = replay_hour(
                plan,
                stored,
                start=start,
                minute_digests=row["document"]["minutes"]["state_sha256"],
            )
            digests.extend(played.minute_digests)
            start = HourStart(
                start.hour + 1, played.states[-1], start.first_sequence + len(played.receipts)
            )
    return digests


def test_a_day_stopped_part_way_goes_on_from_its_last_sealed_hour_asking_nothing_twice(town):
    comparison_id = _start(town)
    worker = _worker(town)
    stop = threading.Event()
    transport = town["transport"]

    def stop_once_an_hour_is_sealed(_asks: int) -> None:
        if _sealed_hours(town, comparison_id) >= 1:
            stop.set()

    transport.on_ask = stop_once_an_hour_is_sealed
    assert worker.run_once(town["workspace"], stop) is True
    result = _result(town, comparison_id)
    (seed,) = result["seeds"]
    model_run = seed["runs"]["model_a"]
    # The host stopped inside the day: the model's run is left open, neither closed nor failed.
    assert model_run["status"] == "incomplete", model_run
    services = town["api"].client.app.state.services
    with services.database.session(town["workspace"]) as connection:
        sealed_before = connection.execute(
            "select count(*) as n from society_comparison_hour where run_id=%s",
            (uuid.UUID(model_run["run_id"]),),
        ).fetchone()["n"]
        stored_before = connection.execute(
            "select count(*) as n from society_comparison_decision where run_id=%s",
            (uuid.UUID(model_run["run_id"]),),
        ).fetchone()["n"]
    assert stored_before > 0 and 1 <= sealed_before < HOURS
    assert model_run["progress"]["hours_sealed"] == sealed_before
    transport.on_ask = None
    assert _worker(town).run_once(town["workspace"]) is True
    result = _result(town, comparison_id)
    (seed,) = result["seeds"]
    assert {run["status"] for run in seed["runs"].values()} == {"completed"}
    run_id = seed["runs"]["model_a"]["run_id"]
    with services.database.session(town["workspace"]) as connection:
        receipts = [
            row["receipt"]
            for row in connection.execute(
                "select receipt from society_comparison_decision where run_id=%s "
                "order by decision_seq",
                (uuid.UUID(run_id),),
            ).fetchall()
        ]
        sealed = connection.execute(
            "select document from society_comparison_hour where run_id=%s order by hour",
            (uuid.UUID(run_id),),
        ).fetchall()
    # Every answer the scripted model gave is one receipt's: nothing recorded was asked again.
    assert len(transport.requests) == sum(
        int(receipt["provider"]["answers_asked"]) for receipt in receipts if receipt["provider"]
    )
    # The day is what its receipts make from its genesis, minute for minute.
    recorded = [digest for row in sealed for digest in row["document"]["minutes"]["state_sha256"]]
    assert _pure_replay_from_genesis(town, comparison_id, run_id) == recorded
    assert len(recorded) == WINDOW


def test_a_day_whose_receipts_its_minutes_do_not_rebuild_fails_asking_nothing(town):
    comparison_id = _start(town)
    stop = threading.Event()
    transport = town["transport"]
    transport.stop, transport.stop_after = stop, 3
    assert _worker(town).run_once(town["workspace"], stop) is True
    (seed,) = _result(town, comparison_id)["seeds"]
    assert seed["runs"]["model_a"]["status"] == "incomplete"
    run_id = uuid.UUID(seed["runs"]["model_a"]["run_id"])
    asked = len(transport.requests)
    # The run's last receipt, changed where its rows are never changed: what its minute rebuilds
    # is no longer what the run holds.
    owner = town["api"].repository.connection
    owner.execute("set session_replication_role = replica")
    try:
        owner.execute(
            "update society_comparison_decision set receipt=jsonb_set(receipt,'{document_sha256}',"
            "to_jsonb(%s::text)), receipt_sha256=%s where run_id=%s and decision_seq=(select "
            "max(decision_seq) from society_comparison_decision where run_id=%s)",
            ("f" * 64, "f" * 64, run_id, run_id),
        )
    finally:
        owner.execute("set session_replication_role = origin")
        owner.commit()
    transport.stop = None
    assert _worker(town).run_once(town["workspace"]) is True
    (seed,) = _result(town, comparison_id)["seeds"]
    model_run = seed["runs"]["model_a"]
    assert (model_run["status"], model_run["failure"]) == ("failed", "interrupted")
    # It failed before the first minute after what it recorded was asked.
    assert len(transport.requests) == asked


#: Where a killed host stops: in the first minute past the day's first hour that asks two people
#: or more, so a sealed hour and whole minutes of the hour it is in lie before it.
KILLED_FROM = HOUR_TICKS + 1
#: How many people the killed host's model decides for: enough that minutes past the first hour
#: ask two of them at once (four rarely do).
KILLED_GROUP = 24


def _doomed_host(town, log: Path, where: str) -> None:
    """Play the town's started comparison as a host that is killed (SIGKILL: no handler, no
    rollback of its own) inside a minute of the model's run: before the minute's second ask, once
    its first is answered, or once the minute's transaction has inserted the first of its
    receipts. A forked process's target, so what it changes is its own."""
    lock = threading.Lock()
    minute = {"tick": -1, "asks": 0}
    first = threading.Event()

    def note(line: str) -> None:
        with log.open("a", encoding="utf-8") as written:
            written.write(line + "\n")

    def killed(tick: int) -> None:
        note(f"killed {tick}")
        os.kill(os.getpid(), signal.SIGKILL)

    live_offerable = runner_module._Asking.offerable

    def offerable(self, tick, due):
        with lock:
            minute.update(tick=tick, asks=0)
            first.clear()
        return live_offerable(self, tick, due)

    live_ask = runner_module.ask

    def ask(*args, **kwargs):
        with lock:
            minute["asks"] += 1
            tick, nth = minute["tick"], minute["asks"]
        if where == "between_asks" and tick >= KILLED_FROM and nth == 2:
            assert first.wait(60), "the minute's first ask was answered"
            killed(tick)
        answered = live_ask(*args, **kwargs)
        if nth == 1:
            if tick >= KILLED_FROM:
                note(f"answered {tick}")
            first.set()
        return answered

    live_append = SocietyComparisonRepository.append

    def append(self, comparison_id, run_id, requests, receipts):
        tick = int(requests[0]["base_tick"])
        if (
            where == "between_receipts"
            and tick >= KILLED_FROM
            and len(receipts) >= 2
            and self._run(run_id)["arm"] == "model_a"
        ):
            live_append(self, comparison_id, run_id, requests[:1], receipts[:1])
            note(f"inserted {tick}")
            killed(tick)
        live_append(self, comparison_id, run_id, requests, receipts)

    runner_module._Asking.offerable = offerable
    runner_module.ask = ask
    SocietyComparisonRepository.append = append
    _worker(town).run_once(town["workspace"])


def _model_receipts(town, run_id: str) -> list[tuple[int, str, int]]:
    """The model run's stored receipts, in decision order: each one's minute, digest and how many
    answers its ask took."""
    services = town["api"].client.app.state.services
    with services.database.session(town["workspace"]) as connection:
        rows = connection.execute(
            "select base_tick, receipt_sha256, receipt from society_comparison_decision "
            "where run_id=%s order by decision_seq",
            (uuid.UUID(run_id),),
        ).fetchall()
    return [
        (
            int(row["base_tick"]),
            row["receipt_sha256"],
            int(row["receipt"]["provider"]["answers_asked"]) if row["receipt"]["provider"] else 0,
        )
        for row in rows
    ]


@pytest.mark.parametrize("where", ["between_asks", "between_receipts"])
def test_a_host_killed_inside_a_minute_stores_none_of_it_and_the_next_asks_from_it(
    town, tmp_path, where
):
    comparison_id = _start(town, group=town["people"][:KILLED_GROUP])
    log = tmp_path / "doomed.log"
    doomed = multiprocessing.get_context("fork").Process(
        target=_doomed_host, args=(town, log, where)
    )
    doomed.start()
    doomed.join(timeout=900)
    noted = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    assert doomed.exitcode == -signal.SIGKILL, (doomed.exitcode, noted)
    tick = int(noted[-1].removeprefix("killed "))
    assert tick >= KILLED_FROM
    # What the host had done of the minute when it was killed: answered one of its asks, or
    # inserted one of its receipts in the minute's transaction.
    assert noted[-2] == ("answered" if where == "between_asks" else "inserted") + f" {tick}"
    (seed,) = _result(town, comparison_id)["seeds"]
    run_id = seed["runs"]["model_a"]["run_id"]
    before = _model_receipts(town, run_id)
    # Every minute before it is stored whole, and nothing of the minute it was killed in.
    assert before and max(minute for minute, _, _ in before) < tick
    services = town["api"].client.app.state.services
    with services.database.session(town["workspace"]) as connection:
        assert (
            connection.execute(
                "select count(*) as n from society_comparison_hour where run_id=%s",
                (uuid.UUID(run_id),),
            ).fetchone()["n"]
            == tick // HOUR_TICKS
        )
        # The killed host's lease runs out, as it would 30 s on.
        connection.execute(
            "update society_comparison_start set lease_expires_at=clock_timestamp() "
            "where comparison_id=%s",
            (uuid.UUID(comparison_id),),
        )
    transport = town["transport"]
    assert transport.requests == []
    assert _worker(town).run_once(town["workspace"]) is True
    (seed,) = _result(town, comparison_id)["seeds"]
    assert {run["status"] for run in seed["runs"].values()} == {"completed"}
    after = _model_receipts(town, run_id)
    assert [held for held in after if held[0] < tick] == before
    # The minute is asked whole again, and the next claim asked from it on and nothing before it.
    assert len([held for held in after if held[0] == tick]) >= 2
    assert len(transport.requests) == sum(asks for minute, _, asks in after if minute >= tick)
    sealed = _pure_replay_from_genesis(town, comparison_id, run_id)
    with services.database.session(town["workspace"]) as connection:
        recorded = [
            digest
            for row in connection.execute(
                "select document from society_comparison_hour where run_id=%s order by hour",
                (uuid.UUID(run_id),),
            ).fetchall()
            for digest in row["document"]["minutes"]["state_sha256"]
        ]
    assert sealed == recorded and len(recorded) == WINDOW


def _take_over(town, comparison_id: str) -> Any:
    """The host's lease runs out and another claim takes the start: what that claim is."""
    services = town["api"].client.app.state.services
    with services.database.session(town["workspace"]) as connection, connection.transaction():
        connection.execute(
            "update society_comparison_start set lease_expires_at=clock_timestamp() "
            "where comparison_id=%s",
            (uuid.UUID(comparison_id),),
        )
    with services.database.session(town["workspace"]) as connection:
        return SocietyComparisonStarts(connection, town["workspace"]).claim()


def _model_rows(town, comparison_id: str) -> tuple[int, int, int]:
    """How many receipts, sealed hours and outcomes the model's run holds."""
    services = town["api"].client.app.state.services
    with services.database.session(town["workspace"]) as connection:
        return tuple(
            connection.execute(
                f"select count(*) as n from {table} t join society_comparison_run r on "
                "r.run_id=t.run_id where r.comparison_id=%s and r.arm='model_a'",
                (uuid.UUID(comparison_id),),
            ).fetchone()["n"]
            for table in (
                "society_comparison_decision",
                "society_comparison_hour",
                "society_comparison_outcome",
            )
        )


@pytest.mark.parametrize("when", ["asking", "sealing", "finishing"])
def test_a_host_whose_lease_another_claim_took_writes_nothing_more(town, monkeypatch, when):
    comparison_id = _start(town)
    taken: dict[str, Any] = {}

    def take_over_once() -> None:
        if not taken:
            taken["claim"] = _take_over(town, comparison_id)

    if when == "asking":
        # At the model's first answer, before the minute's receipts are written.
        town["transport"].on_ask = lambda _asks: take_over_once()
    elif when == "sealing":
        # While the model's run's first hour is sealed, after its receipts are written.
        sealing = runner_module.hour_document

        def hour_document(plan, definition, arm, *args, **kwargs):
            if arm == "model_a":
                take_over_once()
            return sealing(plan, definition, arm, *args, **kwargs)

        monkeypatch.setattr(runner_module, "hour_document", hour_document)
    else:
        # While the model's run's completed day is assembled, every hour sealed.
        finishing = runner_module.day_outcome

        def day_outcome(definition, arm, *args, **kwargs):
            if arm == "model_a":
                take_over_once()
            return finishing(definition, arm, *args, **kwargs)

        monkeypatch.setattr(runner_module, "day_outcome", day_outcome)
    assert _worker(town).run_once(town["workspace"]) is True
    assert taken["claim"] is not None and taken["claim"].took_over
    receipts, hours, outcomes = _model_rows(town, comparison_id)
    # What it was writing when its lease was taken is not written, nor anything after it.
    assert outcomes == 0
    if when == "asking":
        assert (receipts, hours) == (0, 0)
    elif when == "sealing":
        assert hours == 0
    else:
        assert hours == HOURS


def test_a_day_stopped_with_a_run_not_begun_closes_its_whole_seed_when_it_is_not_admitted(
    town, monkeypatch
):
    """A seed whose model runs a host stopped part way, one not yet begun, is played on only once
    the next claim admits the run not begun; otherwise the runs it stopped are closed with it, by
    the seed's own name, asking nothing more, their receipts and sealed hours kept."""
    models = MANIFEST.offered_models(person_role().chosen)[:2]
    group = _group(town)
    query = (
        f"{town['scope']}&role={person_role().key}&group=named"
        + "".join(f"&person={person}" for person in group)
        + "".join(f"&model={model.provider}/{model.model_id}" for model in models)
        + "&control=true&seeds=1&window=day"
    )
    planned = town["api"].get(f"{town['comparisons']}/plan{query}")
    assert planned.status_code == 200, planned.text
    comparison_id = str(uuid.uuid4())
    started = town["api"].post(
        f"{town['comparisons']}{town['scope']}",
        {
            "comparison_id": comparison_id,
            "role": person_role().key,
            "group": {"kind": "named", "people": group},
            "models": [{"provider": m.provider, "model_id": m.model_id} for m in models],
            "control": True,
            "seeds": 1,
            "bound_usd": planned.json()["plan"]["most_usd"],
            "window": "day",
        },
    )
    assert started.status_code == 201, started.text
    stop = threading.Event()
    transport = town["transport"]
    transport.stop, transport.stop_after = stop, 3
    assert _worker(town).run_once(town["workspace"], stop) is True
    (seed,) = _result(town, comparison_id)["seeds"]
    asked = len(transport.requests)
    model_runs = {key: run for key, run in seed["runs"].items() if key not in ("routine", "wait")}
    # Two of the three model runs play at once, so one of them has not begun.
    assert asked > 0 and len(model_runs) == 3
    assert all(run["status"] not in ("completed", "failed") for run in model_runs.values())
    sealed_before = {key: _sealed_hours(town, comparison_id, key) for key in model_runs}
    # What runs like the one not begun typically cost no longer fits what is left of the bound.
    dear = {model.model_id: Decimal(1000) for model in models}
    figures = start_module.TypicalFigures("measured here", dear, {})
    monkeypatch.setattr(start_module, "figures_for", lambda *_args: (figures, True))
    transport.stop = None
    assert _worker(town).run_once(town["workspace"]) is True
    (seed,) = _result(town, comparison_id)["seeds"]
    for key in model_runs:
        assert (seed["runs"][key]["status"], seed["runs"][key]["failure"]) == (
            "failed",
            "comparison_bound_before_seed",
        )
        assert _sealed_hours(town, comparison_id, key) == sealed_before[key]
    assert len(transport.requests) == asked


def test_a_sealed_hour_its_receipts_do_not_replay_to_is_refused_by_name(town):
    comparison_id = _start(town)
    assert _worker(town).run_once(town["workspace"]) is True
    (seed,) = _result(town, comparison_id)["seeds"]
    run_id = seed["runs"]["model_a"]["run_id"]
    hour = f"{town['comparisons']}/{comparison_id}/runs/{run_id}{town['scope']}&hour=1"
    # Positive control: the hour is replayed and drawn.
    assert town["api"].get(hour).status_code == 200
    owner = town["api"].repository.connection
    owner.execute("set session_replication_role = replica")
    try:
        owner.execute(
            "update society_comparison_hour set document=jsonb_set(document,'{events_sha256}',"
            "to_jsonb(%s::text)) where run_id=%s and hour=1",
            ("f" * 64, uuid.UUID(run_id)),
        )
    finally:
        owner.execute("set session_replication_role = origin")
        owner.commit()
    refused = town["api"].get(hour)
    assert (refused.status_code, refused.json()["code"]) == (409, "run_replay_mismatch")


def test_an_hours_comparison_has_no_day_and_no_later_hour(town):
    comparison_id = _start(town, window="hour")
    assert _worker(town).run_once(town["workspace"]) is True
    (seed,) = _result(town, comparison_id)["seeds"]
    run = f"{town['comparisons']}/{comparison_id}/runs/{seed['runs']['model_a']['run_id']}"
    first = town["api"].get(f"{run}{town['scope']}&hour=0")
    assert first.status_code == 200, first.text
    later = town["api"].get(f"{run}{town['scope']}&hour=1")
    assert (later.status_code, later.json()["code"]) == (422, "hour_not_in_window")
    day = town["api"].get(f"{run}/day{town['scope']}")
    assert (day.status_code, day.json()["code"]) == (409, "comparison_not_a_day")


def _sealed_hours(town, comparison_id: str, arm: str = "model_a") -> int:
    services = town["api"].client.app.state.services
    with services.database.session(town["workspace"]) as connection:
        return connection.execute(
            "select count(*) as n from society_comparison_hour h join society_comparison_run "
            "r on r.run_id=h.run_id where r.comparison_id=%s and r.arm=%s",
            (uuid.UUID(comparison_id), arm),
        ).fetchone()["n"]


def test_a_day_whose_inputs_lose_their_rights_fails_at_the_end_of_that_hour(town, monkeypatch):
    comparison_id = _start(town)
    api = town["api"]
    runtime = api.client.app.state.services.society_runtime
    withdrawn: list[int] = []

    def lost(_connection, _session, _document) -> None:
        raise UnavailableSocietyInput("a source this society depends on was withdrawn")

    with monkeypatch.context() as patch:

        def withdraw_once_an_hour_is_sealed(_asks: int) -> None:
            sealed = _sealed_hours(town, comparison_id)
            if withdrawn or sealed < 1:
                return
            # The rights check every run and read asks, answering as it does once a source the
            # society depends on is withdrawn.
            patch.setattr(runtime, "authorize", lost)
            patch.setattr(api.client.app.state, "society_input_authorizer", lost)
            withdrawn.append(sealed)

        town["transport"].on_ask = withdraw_once_an_hour_is_sealed
        assert _worker(town).run_once(town["workspace"]) is True
        assert withdrawn, "the rights were withdrawn once the model's run had sealed an hour"
        (seed,) = _result(town, comparison_id)["seeds"]
        model_run = seed["runs"]["model_a"]
        day = f"{town['comparisons']}/{comparison_id}/runs/{model_run['run_id']}/day{town['scope']}"
        unavailable = api.get(day)
        assert (unavailable.status_code, unavailable.json()["code"]) == (
            424,
            "unavailable_society_input",
        )
    assert (model_run["status"], model_run["failure"]) == ("failed", "input_unavailable")
    # The hour it lost them in was not sealed, and nothing of a later hour was asked.
    (sealed,) = withdrawn
    assert _sealed_hours(town, comparison_id) == sealed < HOURS
    receipts = _model_receipts(town, model_run["run_id"])
    assert max(minute for minute, _, _ in receipts) < (sealed + 1) * HOUR_TICKS
    overview = api.get(day).json()
    assert (overview["status"], overview["hours_sealed"]) == ("failed", sealed)


def test_a_cancelled_day_keeps_the_hours_it_sealed_and_they_stay_readable(town):
    comparison_id = _start(town)
    api = town["api"]
    cancelled: dict[str, Any] = {}
    services = town["api"].client.app.state.services

    def cancel_after_an_hour(asks: int) -> None:
        if cancelled:
            return
        with services.database.session(town["workspace"]) as connection:
            sealed = connection.execute(
                "select count(*) as n from society_comparison_hour h join society_comparison_run "
                "r on r.run_id=h.run_id where r.comparison_id=%s and r.arm='model_a'",
                (uuid.UUID(comparison_id),),
            ).fetchone()["n"]
        if sealed >= 1:
            cancelled["answer"] = api.post(
                f"{town['comparisons']}/{comparison_id}/cancel{town['scope']}", {}
            )

    town["transport"].on_ask = cancel_after_an_hour
    assert _worker(town).run_once(town["workspace"]) is True
    assert cancelled["answer"].status_code == 200, cancelled["answer"].text
    result = _result(town, comparison_id)
    (seed,) = result["seeds"]
    model_run = seed["runs"]["model_a"]
    assert (model_run["status"], model_run["failure"]) == ("failed", "comparison_cancelled")
    overview = api.get(
        f"{town['comparisons']}/{comparison_id}/runs/{model_run['run_id']}/day{town['scope']}"
    ).json()
    assert overview["status"] == "failed" and 1 <= overview["hours_sealed"] < HOURS
    drawn = api.get(
        f"{town['comparisons']}/{comparison_id}/runs/{model_run['run_id']}{town['scope']}&hour=0"
    )
    assert drawn.status_code == 200, drawn.text
    unsealed = api.get(
        f"{town['comparisons']}/{comparison_id}/runs/{model_run['run_id']}{town['scope']}"
        f"&hour={HOURS - 1}"
    )
    assert (unsealed.status_code, unsealed.json()["code"]) == (409, "run_not_completed")


def test_a_day_is_not_offered_without_a_line_measured_over_it(town, monkeypatch):
    monkeypatch.setattr(reading, "READING_CATALOG", LINE)
    plan = _plan(town)
    day = next(window for window in plan["windows"] if window["window"] == "day")
    assert day["refusal"]["code"] == "window_not_offered"
    assert plan["plan_refusal"]["code"] == "window_not_offered"
    started = town["api"].post(
        f"{town['comparisons']}{town['scope']}",
        {
            "comparison_id": str(uuid.uuid4()),
            "role": person_role().key,
            "group": {"kind": "named", "people": _group(town)},
            "models": [{"provider": MODEL.provider, "model_id": MODEL.model_id}],
            "control": False,
            "seeds": 1,
            "bound_usd": "1.00",
            "window": "day",
        },
    )
    assert (started.status_code, started.json()["code"]) == (409, "window_not_offered")
    # The hour is offered as before, read by the hour's line.
    hour = next(window for window in plan["windows"] if window["window"] == "hour")
    assert hour["refusal"] is None and hour["window_ticks"] == HOUR_TICKS


def test_a_society_that_keeps_no_day_is_not_compared_over_one():
    with pytest.raises(StartRefused, match="window_not_offered"):
        window_catalogs(None, "day", "exulanica-society/v2")
