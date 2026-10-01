"""A world version's clock as a deployment stores it: a town made through the API, its living
society coupled to its traffic, as the runtime role under row-level security.

Legacy versions keep their timing and write nothing new; the transition refuses by name and writes
nothing on a refusal; a coupled town commits each minute's crossing occupancy with the minute, its
society waits at the lead, traffic seals each minute once after the minute after it, windows and
verification rebuild what was sealed without a model, and the database itself refuses a minute past
the lead and a legacy segment inside the coupled timeline.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from exulanica.api.traffic_signal_controller import TrafficSignalController
from exulanica.models.manifest import load_manifest
from exulanica.traffic.signal_actuation import signal_actuation
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.decision_roles import decision_roles
from exulanica.world.role_decisions import seal
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_engines import CREATES
from exulanica.world.traffic_signal_repository import SignalChoiceRefused, TrafficSignalRepository
from exulanica.world.world_clock import ClockRefused
from exulanica.world.world_clock_repository import WorldClockRepository
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM

import test_world_traffic_route as traffic
from test_signal_unreachable_point_postgres import OBSERVATION
from test_society_made_world import made as imported_made  # noqa: F401
from test_world_models_route import _signalled

pytestmark = pytest.mark.postgres

TOWN = CREATES["town"]


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _every_town_a_test_makes_is_made(monkeypatch):
    """Each town is tried with the catalog's most candidates, as the living town's own tests do."""
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in recipe_catalog.world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


# -- helpers --------------------------------------------------------------------------------------


def _town(api) -> tuple[dict, dict]:
    made = api.post("/worlds/generated", {"recipe": "small_town", "title": "A coupled town"})
    assert made.status_code == 201, made.text
    entry = made.json()
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(society, {"region_id": "region:generated", "profile": TOWN})
    assert created.status_code in (200, 201), created.text
    return entry, created.json()


def _path(entry: dict, tail: str, **query: Any) -> str:
    extra = "".join(f"&{key}={value}" for key, value in query.items())
    return (
        f"/world/versions/{entry['authored_version_id']}{tail}?world_id={entry['world_id']}{extra}"
    )


def _step(api, entry: dict, body: dict, **pins: Any):
    return api.post(
        _path(entry, "/society/steps"),
        {"base_tick": body["current_tick"], "base_state_sha256": body["state_sha256"], **pins},
    )


def _stepped(api, entry: dict, body: dict) -> dict:
    stepped = _step(api, entry, body)
    assert stepped.status_code == 200, stepped.text
    return stepped.json()


def _clock(api, entry: dict) -> dict:
    read = api.get(_path(entry, "/clock"))
    assert read.status_code == 200, read.text
    return read.json()


def _couple(api, entry: dict, revision: int = 0):
    return api.put(_path(entry, "/clock"), {"base_revision": revision, "profile": "coupled"})


def _controller(api) -> TrafficSignalController:
    return api.client.app.state.traffic_signal_controller


def _seal(api, entry: dict) -> int:
    return _controller(api).prepare_world(
        api.repository.workspace_id, entry["world_id"], uuid.UUID(entry["authored_version_id"])
    )


def _rows(api, sql: str, *params: Any) -> list[dict]:
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(sql, params).fetchall()


# -- legacy ---------------------------------------------------------------------------------------


def test_a_legacy_version_reads_its_own_timing_and_its_minutes_write_no_clock(made):
    api = made
    entry, body = _town(api)
    clock = _clock(api, entry)
    assert clock["clock_profile"] == "exulanica.world-clock/legacy-v1"
    assert (clock["revision"], clock["era"], clock["lead_ticks"]) == (0, 0, 0)
    assert clock["timebases"] == {"society": "tick", "traffic": "unix", "flight": "unix"}
    assert clock["crossings_fed"] is False and clock["presented_through_tick"] is None
    assert clock["society"]["tick"] == body["current_tick"] == 0
    body = _stepped(api, entry, body)
    assert body["current_tick"] == 1
    assert _rows(api, "select * from world_clock") == []
    assert _rows(api, "select * from world_crossing_occupancy") == []
    # A pin a caller sends against a legacy clock is revision 0; any other is stale.
    stale = _step(api, entry, body, base_clock_revision=1)
    assert stale.status_code == 409 and stale.json()["code"] == "stale_clock_revision"
    assert _stepped(api, entry, body)["current_tick"] == 2


# -- the transition -------------------------------------------------------------------------------


def test_the_transition_refuses_by_name_and_writes_nothing(made):
    api = made
    entry, _body = _town(api)
    stale = _couple(api, entry, revision=3)
    assert stale.status_code == 409 and stale.json()["code"] == "stale_clock_revision"
    playing = api.put(
        _path(entry, "/society/control"), {"base_revision": 0, "mode": "playing", "speed": 1}
    )
    assert playing.status_code == 200, playing.text
    refused = _couple(api, entry)
    assert refused.status_code == 409
    assert refused.json()["code"] == "clock_transition_requires_pause"
    # The same predicate answers a read as the read-only role: it takes no lock.
    reader = api.client.app.state.services.readonly_database
    with reader.session(api.repository.workspace_id) as connection:
        clocks = WorldClockRepository(connection, api.repository.workspace_id, entry["world_id"])
        version = uuid.UUID(entry["authored_version_id"])
        assert clocks.transition_refusal(version, roads=None).code == (
            "clock_transition_requires_pause"
        )
    assert _rows(api, "select * from world_clock") == []
    assert _rows(api, "select * from world_clock_event") == []
    unknown = api.put(_path(entry, "/clock"), {"base_revision": 0, "profile": "legacy"})
    assert unknown.status_code == 422
    # A generated world with no society yet has nothing to take the time from.
    bare = api.post("/worlds/generated", {"recipe": "small_town", "title": "No people yet"})
    assert bare.status_code == 201, bare.text
    empty = _couple(api, bare.json())
    assert empty.status_code == 409 and empty.json()["code"] == "clock_requires_society"


def test_a_coupled_town_commits_occupancy_waits_at_the_lead_and_seals_each_minute_once(
    made, monkeypatch
):
    api = made
    asked: list[str] = []

    def counted(*_args, **_kwargs):
        asked.append("ask")
        raise AssertionError("a coupled town with no model choice asks no model")

    # Every path that could reach a model from the host or the traffic controller is counted.
    monkeypatch.setattr("exulanica.api.decision_host.ask", counted)
    monkeypatch.setattr("exulanica.api.traffic_signal_controller.ask", counted)
    entry, body = _town(api)
    # Some of the town's people are out by 06:40.
    for _ in range(40):
        body = _stepped(api, entry, body)
    coupled = _couple(api, entry)
    assert coupled.status_code == 200, coupled.text
    clock = coupled.json()
    start = clock["era_mapping"]["start_tick"]
    assert start == 40 and clock["revision"] == 1 and clock["era"] == 1
    assert clock["clock_profile"] == "exulanica.world-clock/coupled-v1"
    assert clock["timebases"] == {"society": "tick", "traffic": "world", "flight": "world"}
    assert clock["crossings_fed"] is True
    assert clock["era_mapping"]["timeline_origin_second"] % 1200 == 0
    assert clock["traffic"]["state"] == "waiting_for_society"
    assert clock["presented_through_tick"] == start
    # Nothing is sealed yet: a read that names no second asks for the era's first minute.
    unsealed = api.get(_path(entry, "/traffic"))
    assert unsealed.status_code == 409 and unsealed.json()["code"] == "traffic_not_yet_sealed"
    again = _couple(api, entry, revision=1)
    assert again.status_code == 409 and again.json()["code"] == "clock_already_coupled"

    body = _stepped(api, entry, body)
    body = _stepped(api, entry, body)
    # The society is two minutes ahead of sealed traffic: the next minute waits for traffic.
    held = _step(api, entry, body)
    assert held.status_code == 409 and held.json()["code"] == "clock_lead_exhausted"
    assert _clock(api, entry)["state"] == "paused"
    occupancy = _rows(api, "select tick,document from world_crossing_occupancy order by tick")
    assert [row["tick"] for row in occupancy] == [start + 1, start + 2]
    transitions = {
        row["tick"]: row
        for row in _rows(api, "select * from world_society_transition where tick>%s", start)
    }
    for row in occupancy:
        assert row["document"]["state_sha256"] == transitions[row["tick"]]["state_sha256"]

    # Traffic seals the minute the society let through, and only that one.
    assert _seal(api, entry) == 1
    assert _seal(api, entry) == 0
    clock = _clock(api, entry)
    assert clock["traffic"]["sealed_through_tick"] == start + 1
    assert clock["presented_through_tick"] == start + 1
    body = _stepped(api, entry, body)
    assert body["current_tick"] == start + 3

    # A coupled window: the sealed minute on the world's traffic timeline, crossings fed.
    window = api.get(_path(entry, "/traffic"))
    assert window.status_code == 200, window.text
    served = window.json()
    origin = clock["era_mapping"]["timeline_origin_second"]
    assert served["profile"] == "exulanica.traffic-window/v3"
    assert served["timebase"] == "world" and served["crossings_fed"] is True
    assert (served["from_second"], served["seconds"], served["clock_second"]) == (
        origin,
        60,
        origin + 60,
    )
    assert [minute["world_tick"] for minute in served["sealed_minutes"]] == [start + 1]
    ahead = api.get(_path(entry, "/traffic", from_second=origin + 30, seconds=60))
    assert ahead.status_code == 409 and ahead.json()["code"] == "traffic_not_yet_sealed"
    # A second client reads the same positions: the same sealed minute, the same frames.
    second = api.get(_path(entry, "/traffic", from_second=origin, seconds=60))
    assert second.json()["vehicles"] == served["vehicles"]
    assert second.json()["sealed_minutes"] == served["sealed_minutes"]

    # A sealed minute is sealed once: an exact retry is the same row, another is refused.
    version = uuid.UUID(entry["authored_version_id"])
    with api.database.session(api.repository.workspace_id) as connection:
        clocks = WorldClockRepository(connection, api.repository.workspace_id, entry["world_id"])
        row = clocks.minute(clocks.row(version), start + 1)
        document = row["document"]
        continuation = {
            "document_sha256": document["continuation_sha256"],
            "signal_choices": document["signal_choices"],
            "signal_cursors": document["signal_cursors"],
            "initial_signal_cursors": document["initial_signal_cursors"],
        }
        kept = dict(
            era=1,
            world_tick=start + 1,
            occupancy_through_tick=start + 2,
            feed_sha256=document["feed_sha256"],
            frames_sha256=document["frames_sha256"],
            continuation=continuation,
            selected_generations={},
            role=decision_roles().deciding_for("signal"),
        )
        assert clocks.seal_minute(version, **kept)["document_sha256"] == row["document_sha256"]
        with pytest.raises(ClockRefused) as refused:
            clocks.seal_minute(version, **{**kept, "frames_sha256": "f" * 64})
        assert refused.value.code == "traffic_minute_sealed_differently"

    # Verification replays the minutes from what was stored and asks no model.
    checked = api.get(_path(entry, "/clock/verify", from_tick=start + 1, to_tick=start + 2))
    assert checked.status_code == 200, checked.text
    receipt = checked.json()
    assert receipt["society"]["replayed"] is True
    assert receipt["society"]["occupancy_checked"] == 2
    assert receipt["traffic"]["verified"] is True
    assert receipt["traffic"]["minutes_checked"] == 1
    assert receipt["model_client"] is None
    assert asked == []


def test_a_restarted_follower_rebuilds_the_episode_and_goes_on(made):
    api = made
    entry, body = _town(api)
    assert _couple(api, entry).status_code == 200
    for _ in range(2):
        body = _stepped(api, entry, body)
    assert _seal(api, entry) == 1
    body = _stepped(api, entry, body)
    # A follower that holds nothing from before, as after a restart, rebuilds minute one from the
    # episode's genesis, checks it against what was sealed, and seals minute two.
    fresh = TrafficSignalController(
        api.database, None, (), lambda _workspace: None, probe_pool=None
    )
    try:
        assert (
            fresh.prepare_world(
                api.repository.workspace_id,
                entry["world_id"],
                uuid.UUID(entry["authored_version_id"]),
            )
            == 1
        )
    finally:
        fresh.close()
    minutes = _rows(api, "select world_tick,segment from world_clock_traffic_minute order by 1")
    assert [(row["world_tick"], row["segment"]) for row in minutes] == [(1, 0), (2, 1)]


# -- what the database refuses on its own --------------------------------------------------------


def test_the_database_refuses_a_minute_past_the_lead_and_a_legacy_segment_in_the_era(made):
    api = made
    entry, _body = _town(api)
    assert _couple(api, entry).status_code == 200
    version = uuid.UUID(entry["authored_version_id"])
    with (
        api.database.session(api.repository.workspace_id) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        connection.execute(
            "update world_clock set society_tick=society_tick+3 where version_id=%s",
            (version,),
        )
    with (
        api.database.session(api.repository.workspace_id) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        connection.execute(
            "update world_clock set society_tick=society_tick-1 where version_id=%s",
            (version,),
        )
    with api.database.session(api.repository.workspace_id) as connection:
        clock = WorldClockRepository(
            connection, api.repository.workspace_id, entry["world_id"]
        ).row(version)
        origin = clock["timeline_origin_second"]
        repository = TrafficSignalRepository(
            connection, api.repository.workspace_id, entry["world_id"], version
        )
        continuation = seal(
            {
                "profile": "exulanica.traffic-continuation/v1",
                "input_sha256": clock["input_sha256"],
                "episode": origin // 1200,
                "next_second": 60,
                "state": {"second": 59},
                "signal_choices": {},
                "initial_signal_cursors": {},
            }
        )
        with pytest.raises(SignalChoiceRefused, match="segment_after_clock_transition"):
            repository.seal_segment(
                role=decision_roles().deciding_for("signal"),
                roads_version=clock["roads_version"],
                input_sha256=clock["input_sha256"],
                episode=origin // 1200,
                segment=0,
                states=[{"second": second} for second in range(60)],
                continuation=continuation,
                selected_generations={},
            )
    with (
        api.database.session(api.repository.workspace_id) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        connection.execute(
            "insert into world_traffic_signal_segment(workspace_id,world_id,version_id,"
            "roads_version,input_sha256,episode,segment,start_second,end_second,"
            "previous_sha256,choice_seq,active_second,decisions_sha256,frames_sha256,"
            "continuation,continuation_sha256) values (%s,%s,%s,%s,%s,%s,0,%s,%s,null,"
            "null,null,%s,%s,%s,%s)",
            (
                api.repository.workspace_id,
                entry["world_id"],
                version,
                clock["roads_version"],
                clock["input_sha256"],
                origin // 1200,
                origin,
                origin + 60,
                "a" * 64,
                "b" * 64,
                json.dumps(continuation),
                continuation["document_sha256"],
            ),
        )
    # A minute's occupancy may name only a committed transition of its era.
    with api.database.session(api.repository.workspace_id) as connection:
        society = connection.execute(
            "select society_id,current_tick from world_society where version_id=%s", (version,)
        ).fetchone()
        document = {
            "profile": "exulanica.crossing-occupancy/v1",
            "society_id": str(society["society_id"]),
            "era": 1,
            "tick": society["current_tick"] + 1,
            "previous_state_sha256": "a" * 64,
            "state_sha256": "b" * 64,
            "document_sha256": "c" * 64,
        }
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into world_crossing_occupancy(workspace_id,world_id,version_id,society_id,"
                "era,tick,previous_state_sha256,state_sha256,document,document_sha256) "
                "values (%s,%s,%s,%s,1,%s,%s,%s,%s,%s)",
                (
                    api.repository.workspace_id,
                    entry["world_id"],
                    version,
                    society["society_id"],
                    document["tick"],
                    document["previous_state_sha256"],
                    document["state_sha256"],
                    json.dumps(document),
                    document["document_sha256"],
                ),
            )


def test_the_playback_worker_does_not_claim_a_world_waiting_for_its_traffic(made):
    api = made
    entry, body = _town(api)
    assert _couple(api, entry).status_code == 200
    for _ in range(2):
        body = _stepped(api, entry, body)
    playing = api.put(
        _path(entry, "/society/control"),
        {"base_revision": 0, "mode": "playing", "speed": 4, "base_clock_revision": 1},
    )
    assert playing.status_code == 200, playing.text
    workspace = api.repository.workspace_id
    with api.database.session(workspace) as connection:
        connection.execute(
            "update world_society_control set next_due_at=clock_timestamp()-interval '1 minute'"
        )
    with api.database.session(workspace) as connection:
        assert SocietyControlRepository.claim_in_workspace(connection, workspace) is None
    assert _clock(api, entry)["state"] == "waiting"
    assert _seal(api, entry) == 1
    with api.database.session(workspace) as connection:
        claim = SocietyControlRepository.claim_in_workspace(connection, workspace)
    assert claim is not None and str(claim.version_id) == entry["authored_version_id"]
    stale = api.put(
        _path(entry, "/society/control"),
        {"base_revision": 1, "mode": "paused", "speed": 1, "base_clock_revision": 0},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "stale_clock_revision"


# -- signal choices on the traffic timeline ------------------------------------------------------


def _signal_choice(api, entry: dict, subject: str) -> dict:
    read = api.get(_path(entry, "/models"))
    assert read.status_code == 200, read.text
    role = next(role for role in read.json()["roles"] if role["key"] == "junction_signal")
    return next(choice for choice in role["choices"] if choice["subject_id"] == subject)


def _signalled_town(api, monkeypatch) -> tuple[dict, dict, dict, str]:
    traffic._identity(monkeypatch, _signalled())
    entry, body = _town(api)
    coupled = _couple(api, entry)
    assert coupled.status_code == 200, coupled.text
    read = api.get(_path(entry, "/models"))
    assert read.status_code == 200, read.text
    role = next(role for role in read.json()["roles"] if role["key"] == "junction_signal")
    return entry, body, role, role["subjects"][0]["signal_id"]


def test_a_coupled_towns_signal_choice_is_judged_by_its_sealed_traffic(made, monkeypatch):
    """A coupled version's choice takes effect a minute of preparation after its sealed traffic,
    on a timeline that starts a whole episode after the wall clock. The models read states that
    timeline and judges the choice by the traffic sealed on it: by the wall clock, a fixed timing
    choice would read pending until real time caught up with the era."""
    api = made
    entry, body, _role, subject = _signalled_town(api, monkeypatch)
    origin = _clock(api, entry)["era_mapping"]["timeline_origin_second"]
    chosen = api.post(
        _path(entry, "/models/junction_signal"),
        {"idempotency_key": str(uuid.uuid4()), "subjects": [subject], "model": None},
    )
    assert chosen.status_code == 200, chosen.text
    lead = signal_actuation().preparation_lead_seconds
    assert chosen.json()["effective_second"] == origin + lead == origin + 60
    choice = _signal_choice(api, entry, subject)
    assert (choice["timebase"], choice["status"]) == ("world", "pending")
    body = _stepped(api, entry, body)
    body = _stepped(api, entry, body)
    assert _seal(api, entry) == 1
    assert _clock(api, entry)["traffic"]["sealed_through_second"] == origin + 60
    choice = _signal_choice(api, entry, subject)
    assert (choice["timebase"], choice["status"]) == ("world", "fixed")


def test_a_coupled_towns_model_signal_reads_active_once_a_sealed_minute_applied_it(
    made, monkeypatch
):
    """A model's accepted answer counts as its signal's activation once the coupled minute that
    applied it is sealed, as a legacy segment's does, and a decision for a point inside a sealed
    minute arrives after it: the database refuses it."""
    api = made
    entry, body, role, subject = _signalled_town(api, monkeypatch)
    model = role["models"][0]
    chosen = api.post(
        _path(entry, "/models/junction_signal"),
        {
            "idempotency_key": str(uuid.uuid4()),
            "subjects": [subject],
            "model": {"provider": model["provider"], "model_id": model["model_id"]},
        },
    )
    assert chosen.status_code == 200, chosen.text
    answered: list[str] = []

    def ask(_asking, asked, _contract, _ends_at, **_kept) -> dict:
        # A model that follows the plan at every point it is asked about.
        option = next(o for o in asked.request["context"]["options"] if o["kind"] == "switch")
        answered.append(asked.request["request_id"])
        return {
            "status": "accepted",
            "reason": "validated_choice",
            "proposal": {"label": option["label"], "option": option},
            "provider": None,
        }

    host = "exulanica.api.traffic_signal_controller"
    monkeypatch.setattr(f"{host}.ask", ask)
    for name in ("host_refusal", "model_refusal", "question_refusal"):
        monkeypatch.setattr(f"{host}.{name}", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(f"{host}.share_kept", lambda *_args, **_kwargs: (Decimal(0), 0))
    monkeypatch.setattr(f"{host}.ask_bound_usd", lambda *_args, **_kwargs: Decimal(0))
    controller = _controller(api)
    monkeypatch.setattr(controller, "policy_for", lambda _workspace: None)
    monkeypatch.setattr(
        controller, "client", SimpleNamespace(budget=None, with_policy=lambda _policy: None)
    )
    body = _stepped(api, entry, body)
    for _ in range(8):
        body = _stepped(api, entry, body)
        assert _seal(api, entry) == 1
        if answered:
            break
    assert answered, "no choice point in eight sealed minutes"
    choice = _signal_choice(api, entry, subject)
    sealed = _clock(api, entry)["traffic"]["sealed_through_second"]
    assert (choice["timebase"], choice["status"]) == ("world", "active")
    assert choice["effective_second"] <= choice["active_second"] < sealed
    assert choice["running_model"]["model_id"] == model["model_id"]

    signal_role = decision_roles().deciding_for("signal")
    spec = load_manifest().offered(signal_role.chosen, model["model_id"])
    mechanism = signal_role.contract().mechanism_for(spec)
    assert mechanism is not None
    workspace = api.repository.workspace_id
    version = uuid.UUID(entry["authored_version_id"])
    with api.database.session(workspace) as connection:
        repository = TrafficSignalRepository(connection, workspace, entry["world_id"], version)
        reserved = {
            row["choice_second"]
            for row in connection.execute(
                "select choice_second from world_traffic_signal_decision_request "
                "where version_id=%s",
                (version,),
            ).fetchall()
        }
        second = next(s for s in range(sealed - 1, sealed - 61, -1) if s not in reserved)
        episode, local = divmod(second, 1200)
        reservation = repository.reserve_point(
            signal_role,
            roads_version=repository.clock()["roads_version"],
            episode=episode,
            segment=local // 60,
            choice=repository.current_choices()[subject],
            choice_second=second,
            state_sha256="0" * 64,
            observation=OBSERVATION,
            manifest_sha256="c" * 64,
            mechanism=mechanism.value,
        )
        assert reservation is not None
        request = reservation["request"]
        keep = next(o for o in request["context"]["options"] if o["kind"] == "keep")
        with pytest.raises(psycopg.errors.CheckViolation, match="after its segment was sealed"):
            repository.record_result(
                signal_role,
                uuid.UUID(request["request_id"]),
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": keep["label"], "option": keep},
                    "provider": None,
                },
            )


# -- holds ----------------------------------------------------------------------------------------


def test_a_block_keeps_the_people_at_the_lead_and_a_suspension_lets_them_go_on(made):
    """A blocked era's people wait at the lead; an unavailable era's go on, presented at their
    head. Each hold is one receipt, and the clock row names the latest."""
    api = made
    entry, body = _town(api)
    assert _couple(api, entry).status_code == 200
    body = _stepped(api, entry, body)
    body = _stepped(api, entry, body)
    version = uuid.UUID(entry["authored_version_id"])
    workspace = api.repository.workspace_id
    with api.database.session(workspace) as connection:
        clocks = WorldClockRepository(connection, workspace, entry["world_id"])
        clocks.hold_traffic(version, era=1, state="blocked", code="traffic_replay_mismatch")
        # Held again for the same reason: nothing more is written.
        clocks.hold_traffic(version, era=1, state="blocked", code="traffic_replay_mismatch")
        assert clocks.row(version)["last_event_seq"] == 2
    clock = _clock(api, entry)
    assert clock["state"] == "blocked" and clock["traffic"]["code"] == "traffic_replay_mismatch"
    held = _step(api, entry, body)
    assert held.status_code == 409 and held.json()["code"] == "clock_lead_exhausted"
    with api.database.session(workspace) as connection:
        clocks = WorldClockRepository(connection, workspace, entry["world_id"])
        clocks.hold_traffic(version, era=1, state="unavailable", code="roads_unavailable")
        row = clocks.row(version)
    assert row["last_event_seq"] == 3
    assert row["presented_through_tick"] == row["society_tick"]
    body = _stepped(api, entry, body)
    assert _clock(api, entry)["presented_through_tick"] == body["current_tick"]
    events = api.get(_path(entry, "/clock/events"))
    assert [event["kind"] for event in events.json()["events"]] == [
        "traffic_unavailable",
        "traffic_blocked",
        "transitioned",
    ]
    window = api.get(_path(entry, "/traffic"))
    assert window.status_code == 409 and window.json()["code"] == "roads_unavailable"
