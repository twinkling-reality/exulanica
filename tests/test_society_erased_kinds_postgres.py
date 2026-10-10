"""A society finds out by itself, at its next minute, that a creature it runs was erased.

An erasure tells the societies it reaches at once. One it does not reach (its input could not be
composed then, a restore replayed the erasure, the society was not running) is told by nobody, so
every minute asks first: where the latest input still lists a placed thing whose kind is gone, the
input that leaves it out is composed before the minute, and the being leaves in that minute as
``kind_erased``. What is shown, through the deployed routes and the playback worker:

*   an erasure that told nobody (written by the store alone, as a restore's replay writes it) is
    found by the next step, the next manual step and the next playback round, with no edit and no
    second ask, and nothing a person's words reached is left in any table after that minute;
*   a minute that cannot compose that input runs nothing and is refused by name; a playback round
    whose society cannot be told pauses it with the reason a person reads for a source that cannot
    be read, and a round an erasure overtook stops without a pause and is told before its next;
*   a creature whose thing was removed, before or after its erasure, leaves at the next minute as
    any removed thing does: the society is not behind, and no step or round is refused;
*   no model is asked about a state that still holds an erased being, whoever told the society;
*   a minute waiting on the workspace's lock while an erasure commits does not run the erased
    creature, and a placing edit waiting on it is refused the erased kind;
*   a society with no made kind is asked nothing, and one whose creature is kept is told nothing.

Every world here has a fixed workspace and saved world, so its society's seed is the same every
run. Even so, nothing asserts where a being stands or which minute something happens in: only that
the being is gone after the first minute that begins after the erasure commits (or never arrives),
why it left, and that the society replays.
"""

from __future__ import annotations

import dataclasses
import threading
import time
import uuid
from typing import Any

import pytest
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.db.roles import RUNTIME_ROLE
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_repository import SocietyInputBehind, SocietyRepository
from exulanica.world.thing_store import ThingStore
from exulanica.world.workspace_lock import lock_workspace
from fastapi.testclient import TestClient

import test_society_made_kinds_postgres as made
import test_society_things_postgres as things_api
from conftest import scratch_role_database
from test_society_made_kinds import CANARIES
from test_society_saved_world_api import OWNER, routes
from tests_support_api import scratch_database

saved_world = made.saved_world
saved_world_app = made.saved_world_app
world_app = made.world_app
kept = made.kept
#: Every world here is the same world each run: its workspace and its saved world are fixed, which
#: together name its society's seed (tests/conftest.py), so no run meets a society another did not.
WORKSPACE = uuid.UUID("a11e0000-0000-4000-8000-0000000e4a5e")
SAVED_WORLD = "world:authored:a11e0000-0000-4000-8000-00000000d001"
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.parametrize(
        ("workspace_id", "saved_world_id"), [(WORKSPACE, SAVED_WORLD)], ids=["fixed-world"]
    ),
]
CREATURE = made.CREATURE


def _erase_telling_nobody(world, spine_schema, sha256: str) -> None:
    """Erase the creature through the store alone, as the deployed role: the erasure's row and
    what its trigger deletes, and no society told. This is what a restore's replay of an erasure
    writes, and what an erasure whose telling reached nobody leaves."""
    writer = scratch_role_database(spine_schema[1], RUNTIME_ROLE)
    with writer.session(world["workspace"]) as session:
        ThingStore(session, world["workspace"], None).erase_creature(
            sha256, erased_by=world["session"].actor
        )


def _read(client, world) -> dict[str, Any]:
    scope, _, society_route = routes(world)
    read = client.get(society_route, headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    return read.json()


def _here(society: dict[str, Any], being: dict[str, Any]) -> bool:
    return any(person["id"] == being["id"] for person in society["state"]["inhabitants"])


def _being(society: dict[str, Any]) -> dict[str, Any]:
    return next(p for p in society["state"]["inhabitants"] if p["placed_id"] == CREATURE)


def _departures(client, world) -> list[tuple[str, str]]:
    return [
        (event["document"]["subject_id"], event["document"]["reason"])
        for event in things_api._events(client, world)
        if event["event_kind"] == "thing_departed"
    ]


def test_the_next_step_after_an_erasure_nobody_told_sends_the_being_away(
    world_app, kept, spine_schema
):
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        society = things_api._step(client, world, society)
        assert _here(society, being)
        # The positive control: the search finds the creature's words while it is kept.
        assert made._rows_holding(database, world, CANARIES)
        _erase_telling_nobody(world, spine_schema, kept.kind.sha256)
        # Nobody was told: the society's one input still lists the thing.
        inputs = made._inputs(database, world)
        assert len(inputs) == 1
        assert CREATURE in [entry["placed_id"] for entry in inputs[0]["things"]]
        # The very next minute composes the input that leaves it out, and the being leaves in it.
        society = things_api._step(client, world, society)
        assert not _here(society, being)
        assert "kinds" not in society["state"]
        inputs = made._inputs(database, world)
        assert len(inputs) == 2
        assert CREATURE not in [entry["placed_id"] for entry in inputs[1]["things"]]
        assert "kinds" not in inputs[1] and inputs[1]["things_gone"] == [CREATURE]
        assert _departures(client, world) == [(being["id"], "kind_erased")]
        # Nothing a person's words reached is left in any table after that minute.
        assert made._rows_holding(database, world, CANARIES) == {}
        # Told once: later minutes append nothing, and the society replays.
        for _ in range(3):
            society = things_api._step(client, world, society)
        assert len(made._inputs(database, world)) == 2
        assert things_api._replayed(client, world) is True


def test_a_paused_society_is_told_at_its_first_manual_step_back(world_app, kept, spine_schema):
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        _erase_telling_nobody(world, spine_schema, kept.kind.sha256)
        assert len(made._inputs(database, world)) == 1
        scope, _, society_route = routes(world)
        stepped = client.post(
            society_route + "/control/steps",
            headers=OWNER,
            params=scope,
            json={
                "base_revision": 0,
                "base_tick": society["current_tick"],
                "base_state_sha256": society["state_sha256"],
            },
        )
        assert stepped.status_code == 200, stepped.text
        assert not _here(stepped.json()["society"], being)
        assert made._inputs(database, world)[1]["things_gone"] == [CREATURE]
        assert _departures(client, world) == [(being["id"], "kind_erased")]
        assert things_api._replayed(client, world) is True


def test_a_minute_that_cannot_compose_the_input_runs_nothing_and_is_refused_by_name(
    world_app, kept, spine_schema
):
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        _erase_telling_nobody(world, spine_schema, kept.kind.sha256)
        scope, _, society_route = routes(world)
        body = {
            "base_tick": society["current_tick"],
            "base_state_sha256": society["state_sha256"],
        }
        # An application that holds no hook to compose with: the minute is refused, not run.
        hook = client.app.state.society_authored_edit
        client.app.state.society_authored_edit = None
        refused = client.post(society_route + "/steps", headers=OWNER, params=scope, json=body)
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "stale_society_state"
        assert "erased" in refused.json()["detail"]
        # One whose hook fails: the failure is the answer, and again nothing is run.

        def failing(*_args, **_kwargs):
            raise RuntimeError("the input could not be composed")

        client.app.state.society_authored_edit = failing
        with pytest.raises(RuntimeError, match="could not be composed"):
            client.post(society_route + "/steps", headers=OWNER, params=scope, json=body)
        # And one whose hook composes nothing: the input still lists the thing, so it is refused.
        client.app.state.society_authored_edit = lambda *_args, **_kwargs: None
        still = client.post(society_route + "/steps", headers=OWNER, params=scope, json=body)
        assert still.status_code == 409, still.text
        assert still.json()["code"] == "stale_society_state"
        assert "still holds it" in still.json()["detail"]
        after = _read(client, world)
        assert (after["current_tick"], after["state_sha256"]) == (
            society["current_tick"],
            society["state_sha256"],
        )
        assert _here(after, being) and len(made._inputs(database, world)) == 1
        assert _departures(client, world) == []
        # With the hook back, the same minute is asked again, told first, and run.
        client.app.state.society_authored_edit = hook
        society = things_api._step(client, world, society)
        assert not _here(society, being)
        assert things_api._replayed(client, world) is True


def test_a_repository_given_no_refresher_refuses_and_one_with_no_made_kind_is_asked_nothing(
    world_app, kept, spine_schema
):
    world, make_app, _, database = world_app
    # Neither the latest input nor the state names a made thing: answered without a connection
    # to ask, as is a society of any other engine whatever its input lists.
    nobody = SocietyRepository(None, world["workspace"], world_id=world["binding"].world_id)  # type: ignore[arg-type]
    shipped = {"placed_id": "well", "kind": {"kind": "well", "version": 2, "sha256": "0" * 64}}
    made_thing = {"placed_id": CREATURE, "kind": {"source": "workspace", "sha256": "0" * 64}}
    assert (
        nobody._erased_and_untold(
            {"engine_version": made.V7, "state": {"inhabitants": []}}, {"things": [shipped]}
        )
        is False
    )
    assert (
        nobody._erased_and_untold(
            {"engine_version": "exulanica-society/v2", "state": {"inhabitants": []}},
            {"things": [made_thing]},
        )
        is False
    )
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        with database.session(world["workspace"]) as connection:
            repository = SocietyRepository(
                connection, world["workspace"], world_id=world["binding"].world_id
            )
            # A creature that is kept: nothing is behind, and nothing is composed.
            assert repository.tell_of_erased_kinds(world["binding"].version_id) == "clear"
            _erase_telling_nobody(world, spine_schema, kept.kind.sha256)
            with pytest.raises(SocietyInputBehind, match="erased"):
                repository.tell_of_erased_kinds(world["binding"].version_id)
            with pytest.raises(SocietyInputBehind, match="erased"):
                repository.advance(
                    world["binding"].version_id,
                    base_tick=society["current_tick"],
                    base_state_sha256=society["state_sha256"],
                )
        assert len(made._inputs(database, world)) == 1
        assert _read(client, world)["current_tick"] == society["current_tick"]


def test_an_erasure_whose_telling_budget_is_spent_leaves_the_society_to_tell_itself(
    world_app, kept, monkeypatch
):
    """The erase route tells societies only while its budget lasts. With none (a host may set
    0), it tells nobody inline and the erasure still stands; the society's next minute tells
    itself. The positive control, the same route telling at once under the shipped budget, is
    tests/test_society_made_kinds_postgres.py's erasure test."""
    from exulanica.api.routes import thing_store

    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        assert thing_store.TELLING_SECONDS == 2
        monkeypatch.setattr(thing_store, "TELLING_SECONDS", 0)
        erased = client.delete(f"/things/kinds/{kept.kind.sha256}", headers=OWNER)
        assert erased.status_code == 204, erased.text
        assert len(made._inputs(database, world)) == 1
        society = things_api._step(client, world, society)
        assert not _here(society, being)
        assert made._inputs(database, world)[1]["things_gone"] == [CREATURE]
        assert _departures(client, world) == [(being["id"], "kind_erased")]
        assert made._rows_holding(database, world, CANARIES) == {}
        assert things_api._replayed(client, world) is True


def _play(client, world) -> None:
    scope, _, society_route = routes(world)
    played = client.put(
        society_route + "/control",
        headers=OWNER,
        params=scope,
        json={"base_revision": 0, "mode": "playing", "speed": 1},
    )
    assert played.status_code == 200, played.text


def _due_now(database, world) -> None:
    """Make the society's next minute due, as the passing of its interval does."""
    with database.session(world["workspace"]) as connection:
        connection.execute(
            "update world_society_control set next_due_at=clock_timestamp() - interval '1 second' "
            "where workspace_id=%s",
            (world["workspace"],),
        )


def _mode(client, world) -> str:
    scope, _, society_route = routes(world)
    read = client.get(society_route + "/control", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    return str(read.json()["mode"])


def _worker(world, spine_schema, runtime, **options) -> SocietyControlWorker:
    return SocietyControlWorker(
        scratch_database(spine_schema[1]),
        runtime=runtime,
        workspaces=[world["workspace"]],
        **options,
    )


def _revision(client, world) -> int:
    scope, _, society_route = routes(world)
    return int(
        client.get(society_route + "/control", headers=OWNER, params=scope).json()["revision"]
    )


def test_playback_tells_a_society_before_its_round_and_asks_no_model_about_the_erased_being(
    world_app, kept, spine_schema
):
    world, make_app, runtime, database = world_app
    asked: list[Any] = []

    def before_minute(claim, _lease_ends) -> bool:
        asked.append(claim.version_id)
        return False

    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        _play(client, world)
        worker = _worker(world, spine_schema, runtime, before_minute=before_minute)
        # The positive control: a round with nothing erased asks before its minute.
        _due_now(database, world)
        assert worker.run_once(world["workspace"]) is not None
        assert asked == [world["binding"].version_id]
        _erase_telling_nobody(world, spine_schema, kept.kind.sha256)
        # The next round is told first, in a transaction of its own; the state still holds the
        # erased being until the minute runs, so no model is asked, and the minute sends it away.
        _due_now(database, world)
        ran = worker.run_once(world["workspace"])
        assert ran is not None and ran["receipt"]["executed_ticks"] == 1
        assert asked == [world["binding"].version_id], "a model was asked about the erased being"
        assert _mode(client, world) == "playing"
        assert not _here(_read(client, world), being)
        assert made._inputs(database, world)[1]["things_gone"] == [CREATURE]
        assert _departures(client, world) == [(being["id"], "kind_erased")]
        # With the being gone, rounds ask again.
        _due_now(database, world)
        assert worker.run_once(world["workspace"]) is not None
        assert len(asked) == 2
        assert things_api._replayed(client, world) is True


def test_a_round_whose_society_cannot_be_told_pauses_it_with_the_reason_a_person_reads(
    world_app, kept, spine_schema, monkeypatch
):
    """Where the composer runs and what it appends does not send the erased being away, the
    society is paused as one whose source cannot be read, with that reason, and no model is
    asked; it is not left playing and standing still. Once the input can be composed and the
    owner plays it again, the first round tells it and its minute sends the being away."""
    world, make_app, runtime, database = world_app
    asked: list[Any] = []
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        _play(client, world)
        worker = _worker(
            world,
            spine_schema,
            runtime,
            before_minute=lambda claim, _: asked.append(claim) or False,
        )
        _erase_telling_nobody(world, spine_schema, kept.kind.sha256)
        composing = runtime.authored_edit

        monkeypatch.setattr(runtime, "authored_edit", lambda *_args, **_kwargs: None)
        _due_now(database, world)
        held = worker.run_once(world["workspace"])
        assert held is not None
        assert held["receipt"]["kind"] == "paused_due_to_error"
        assert held["receipt"]["reason"] == "source_unavailable"
        assert held["receipt"]["executed_ticks"] == 0
        assert held["receipt"]["tick_to"] == society["current_tick"]
        assert _mode(client, world) == "paused"
        assert asked == []
        assert _here(_read(client, world), being)
        assert len(made._inputs(database, world)) == 1 and _departures(client, world) == []
        # Composing works again and the owner presses play: told first, then the minute.
        monkeypatch.setattr(runtime, "authored_edit", composing)
        scope, _, society_route = routes(world)
        played = client.put(
            society_route + "/control",
            headers=OWNER,
            params=scope,
            json={"base_revision": _revision(client, world), "mode": "playing", "speed": 1},
        )
        assert played.status_code == 200, played.text
        _due_now(database, world)
        ran = worker.run_once(world["workspace"])
        assert ran is not None and ran["receipt"]["executed_ticks"] == 1
        assert _mode(client, world) == "playing"
        assert not _here(_read(client, world), being)
        assert _departures(client, world) == [(being["id"], "kind_erased")]
        assert things_api._replayed(client, world) is True


def test_an_erasure_that_commits_after_the_worker_asked_stops_the_round_without_a_pause(
    world_app, kept, spine_schema
):
    """The harmless race: the worker asked, nothing was behind, and the erasure committed before
    the round's minute. The round composes nothing, so it runs no minute and does not pause; the
    next round is told first."""
    world, make_app, runtime, database = world_app
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        _play(client, world)
        worker = _worker(world, spine_schema, runtime)
        _due_now(database, world)
        with scratch_database(spine_schema[1]).session(world["workspace"]) as connection:
            claim = SocietyControlRepository.claim_in_workspace(
                connection,
                world["workspace"],
                input_authorizer=worker._authorizer(connection, world["workspace"]),
            )
        assert claim is not None
        assert worker._tell_of_erased_kinds(world["workspace"], claim) == "clear"
        _erase_telling_nobody(world, spine_schema, kept.kind.sha256)
        with scratch_database(spine_schema[1]).session(world["workspace"]) as connection:
            stopped = worker._repository(connection, world["workspace"], claim.world_id).execute(
                claim
            )
        assert stopped["receipt"]["kind"] == "advanced"
        assert stopped["receipt"]["executed_ticks"] == 0
        assert stopped["receipt"]["tick_to"] == society["current_tick"]
        assert _mode(client, world) == "playing"
        assert _here(_read(client, world), being) and _departures(client, world) == []
        _due_now(database, world)
        ran = worker.run_once(world["workspace"])
        assert ran is not None and ran["receipt"]["executed_ticks"] == 1
        assert not _here(_read(client, world), being)
        assert things_api._replayed(client, world) is True


def test_a_creature_placed_and_erased_before_any_minute_never_arrives(
    world_app, kept, spine_schema
):
    """The society holds no made kind when the creature is placed, so its state names none: only
    its latest input lists the thing. Erased before any minute, with nobody told, the creature
    must not arrive in the first minute after its erasure."""
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        client.app.state.services = dataclasses.replace(
            client.app.state.services, societies_of_things=True
        )
        things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
        society = things_api._make_society(client, world)
        assert "kinds" not in society["state"]
        made._place_made(client, world, CREATURE, kept.kind.sha256, 3_000, 3_000)
        inputs = made._inputs(database, world)
        assert CREATURE in [entry["placed_id"] for entry in inputs[-1]["things"]]
        before = len(inputs)
        _erase_telling_nobody(world, spine_schema, kept.kind.sha256)
        assert len(made._inputs(database, world)) == before
        for _ in range(3):
            society = things_api._step(client, world, society)
            assert all(p["placed_id"] != CREATURE for p in society["state"]["inhabitants"])
            assert "kinds" not in society["state"]
        inputs = made._inputs(database, world)
        assert len(inputs) == before + 1
        assert inputs[-1]["things_gone"] == [CREATURE] and "kinds" not in inputs[-1]
        arrivals = [
            event
            for event in things_api._events(client, world)
            if event["event_kind"] == "thing_arrived"
            and event["document"].get("thing", {}).get("placed_id") == CREATURE
        ]
        assert arrivals == [] and _departures(client, world) == []
        assert made._rows_holding(database, world, CANARIES) == {}
        assert things_api._replayed(client, world) is True


def test_a_being_whose_kind_is_gone_is_untold_under_an_input_that_lists_nothing(
    world_app, kept, spine_schema
):
    """An unavailable input lists no thing and names nobody gone. A society whose state holds a
    placed being of an erased kind is still untold under it. Under an AVAILABLE input that does
    not list the being the society is not behind: the next minute sends the being away, and
    until then it is one about to leave."""
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        made._society(client, world, kept)
        with database.session(world["workspace"]) as connection:
            repository = SocietyRepository(
                connection, world["workspace"], world_id=world["binding"].world_id
            )
            row = repository._row(world["binding"].version_id)
            latest = repository._latest_input(row)
            nothing = {**latest, "availability": "unavailable", "things": []}
            # The positive control: while the kind is kept, nothing is untold.
            assert repository._erased_and_untold(row, latest) is False
            assert repository._erased_and_untold(row, nothing) is False
            _erase_telling_nobody(world, spine_schema, kept.kind.sha256)
            assert repository._erased_and_untold(row, latest) is True
            assert repository._erased_and_untold(row, nothing) is True
            for unlisted in (
                {**latest, "things": []},
                {**latest, "things": [], "things_gone": [CREATURE]},
            ):
                assert repository._erased_and_untold(row, unlisted) is False
                assert repository._holds_a_being_about_to_leave(row, unlisted) is True
            # One the input still lists is behind, not leaving; an unavailable input sends nobody.
            assert repository._holds_a_being_about_to_leave(row, latest) is False
            assert repository._holds_a_being_about_to_leave(row, nothing) is False


def _remove(client, world, thing_id: str) -> None:
    """Remove a placed thing as its person does: an authored edit, which appends the society an
    input that no longer lists it."""
    scope, root, _ = routes(world)
    base = client.get(root, headers=OWNER, params=scope).json()["state_sha256"]
    removed = client.post(
        f"{root}/things/{thing_id}/remove",
        headers=OWNER,
        params=scope,
        json={"base_state_sha256": base},
    )
    assert removed.status_code == 200, removed.text


def test_a_creature_removed_and_then_erased_leaves_at_the_next_step_as_a_removed_thing_does(
    world_app, kept, spine_schema
):
    """Its person removes the creature's thing, then erases the creature, telling nobody. The
    latest input is available and does not list the thing, so the society is not behind: the
    step runs and the being leaves in it, as on a world where nothing was erased."""
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        _remove(client, world, CREATURE)
        inputs = made._inputs(database, world)
        assert CREATURE not in [entry["placed_id"] for entry in inputs[-1]["things"]]
        told = len(inputs)
        _erase_telling_nobody(world, spine_schema, kept.kind.sha256)
        society = things_api._step(client, world, society)
        assert not _here(society, being)
        assert _departures(client, world) == [(being["id"], "removed_by_author")]
        # Nothing had to be composed, later steps run, and nothing of the creature is left.
        for _ in range(2):
            society = things_api._step(client, world, society)
        assert len(made._inputs(database, world)) == told
        assert made._rows_holding(database, world, CANARIES) == {}
        assert things_api._replayed(client, world) is True


def test_a_creature_erased_and_then_removed_leaves_at_the_next_step(world_app, kept):
    """The other order: the erasing request tells the society at once, and then its person
    removes the gone thing, which appends an input that neither lists it nor names it gone."""
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        erased = client.delete(f"/things/kinds/{kept.kind.sha256}", headers=OWNER)
        assert erased.status_code == 204, erased.text
        assert made._inputs(database, world)[-1]["things_gone"] == [CREATURE]
        _remove(client, world, CREATURE)
        latest = made._inputs(database, world)[-1]
        assert CREATURE not in [entry["placed_id"] for entry in latest["things"]]
        society = things_api._step(client, world, society)
        assert not _here(society, being)
        assert [subject for subject, _ in _departures(client, world)] == [being["id"]]
        society = things_api._step(client, world, society)
        assert made._rows_holding(database, world, CANARIES) == {}
        assert things_api._replayed(client, world) is True


def test_a_round_after_a_removal_and_an_erasure_is_not_paused_and_asks_no_model(
    world_app, kept, spine_schema
):
    """The first of those through playback: the round is not behind, so nothing pauses it, and
    the state still holds the erased being until its minute, so no model is asked about it."""
    world, make_app, runtime, database = world_app
    asked: list[Any] = []
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        _play(client, world)
        worker = _worker(
            world,
            spine_schema,
            runtime,
            before_minute=lambda claim, _: asked.append(claim.version_id) or False,
        )
        _remove(client, world, CREATURE)
        # The positive control: a removal alone asks models as ever. The round's minute sends
        # the being away, so the creature is placed again for the case itself.
        _due_now(database, world)
        assert worker.run_once(world["workspace"]) is not None
        assert asked == [world["binding"].version_id]
        assert not _here(_read(client, world), being)
        made._place_made(client, world, "second", kept.kind.sha256, 2_000, 2_000)
        _due_now(database, world)
        assert worker.run_once(world["workspace"]) is not None
        second = next(
            p for p in _read(client, world)["state"]["inhabitants"] if p["placed_id"] == "second"
        )
        asked.clear()
        _remove(client, world, "second")
        _erase_telling_nobody(world, spine_schema, kept.kind.sha256)
        _due_now(database, world)
        ran = worker.run_once(world["workspace"])
        assert ran is not None
        assert ran["receipt"]["kind"] == "advanced" and ran["receipt"]["executed_ticks"] == 1
        assert _mode(client, world) == "playing"
        assert asked == [], "a model was asked about the erased being"
        assert not _here(_read(client, world), second)
        # With the being gone, rounds ask again.
        _due_now(database, world)
        assert worker.run_once(world["workspace"]) is not None
        assert asked == [world["binding"].version_id]
        assert things_api._replayed(client, world) is True


def test_a_round_after_the_erasing_request_told_the_society_asks_no_model(
    world_app, kept, spine_schema
):
    """The usual case: the erasing request tells the society within its shipped budget, so the
    worker has nothing to compose. The state still holds the erased being until the minute, so
    that round asks no model; the next one does."""
    from exulanica.api.routes import thing_store

    world, make_app, runtime, database = world_app
    asked: list[Any] = []
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        _play(client, world)
        worker = _worker(
            world,
            spine_schema,
            runtime,
            before_minute=lambda claim, _: asked.append(claim.version_id) or False,
        )
        assert thing_store.TELLING_SECONDS == 2
        erased = client.delete(f"/things/kinds/{kept.kind.sha256}", headers=OWNER)
        assert erased.status_code == 204, erased.text
        told = made._inputs(database, world)
        assert told[-1]["things_gone"] == [CREATURE]
        assert _here(_read(client, world), being)
        _due_now(database, world)
        ran = worker.run_once(world["workspace"])
        assert ran is not None and ran["receipt"]["executed_ticks"] == 1
        assert asked == [], "a model was asked about the erased being"
        assert len(made._inputs(database, world)) == len(told)
        assert not _here(_read(client, world), being)
        assert _departures(client, world) == [(being["id"], "kind_erased")]
        _due_now(database, world)
        assert worker.run_once(world["workspace"]) is not None
        assert asked == [world["binding"].version_id]
        assert things_api._replayed(client, world) is True


def _lease_expired(database, world) -> None:
    """Let the claimed round's lease run out, as the passing of its seconds does."""
    with database.session(world["workspace"]) as connection:
        connection.execute(
            "update world_society_control set lease_expires_at=clock_timestamp() - "
            "interval '1 second' where workspace_id=%s and lease_token is not null",
            (world["workspace"],),
        )


def _control(client, world) -> dict[str, Any]:
    scope, _, society_route = routes(world)
    read = client.get(society_route + "/control", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    return dict(read.json())


def test_a_fault_that_is_no_refusal_fails_the_round_and_a_lasting_one_pauses_with_its_reason(
    world_app, kept, spine_schema, monkeypatch
):
    """The society is behind and the composer itself raises, every round: a fault, not an answer
    about the society. Each round fails as any failed round does (no minute runs, so the erased
    creature is not run, and no model is asked), and once the attempts a lease is given are
    spent the society is paused with the reason a person reads for that: it is not left playing
    and standing still. When the fault has passed and its person plays it again, the first round
    tells it and the being leaves."""
    from exulanica.world.society_controls import MAX_CLAIM_ATTEMPTS

    world, make_app, runtime, database = world_app
    asked: list[Any] = []
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        _play(client, world)
        worker = _worker(
            world,
            spine_schema,
            runtime,
            before_minute=lambda claim, _: asked.append(claim.version_id) or False,
        )
        _erase_telling_nobody(world, spine_schema, kept.kind.sha256)

        def failing(*_args, **_kwargs):
            raise RuntimeError("the input could not be composed")

        monkeypatch.setattr(runtime, "authored_edit", failing)
        _due_now(database, world)
        assert MAX_CLAIM_ATTEMPTS == 3
        for _ in range(MAX_CLAIM_ATTEMPTS):
            with pytest.raises(RuntimeError, match="could not be composed"):
                worker.run_once(world["workspace"])
            assert _control(client, world)["mode"] == "playing"
            _lease_expired(database, world)
        # The next claim finds the attempts spent and pauses the society; no round runs.
        assert worker.run_once(world["workspace"]) is None
        control = _control(client, world)
        assert (control["mode"], control["reason"]) == ("paused", "lease_recovery_limit")
        now = _read(client, world)
        assert now["current_tick"] == society["current_tick"] and _here(now, being)
        assert asked == [] and _departures(client, world) == []
        assert len(made._inputs(database, world)) == 1
        # The fault passes and the owner plays again: told first, then the minute.
        monkeypatch.undo()
        scope, _, society_route = routes(world)
        played = client.put(
            society_route + "/control",
            headers=OWNER,
            params=scope,
            json={"base_revision": control["revision"], "mode": "playing", "speed": 1},
        )
        assert played.status_code == 200, played.text
        _due_now(database, world)
        ran = worker.run_once(world["workspace"])
        assert ran is not None and ran["receipt"]["executed_ticks"] == 1
        assert asked == []
        assert not _here(_read(client, world), being)
        assert _departures(client, world) == [(being["id"], "kind_erased")]
        assert things_api._replayed(client, world) is True


def _waiting_on_a_lock(database, world, what: str) -> None:
    """Wait until a session waits on an advisory lock: the thing itself, with a limit."""
    deadline = time.monotonic() + 60
    with database.session(world["workspace"]) as watcher:
        while time.monotonic() < deadline:
            row = watcher.execute(
                "select count(*) as waiting from pg_locks where locktype='advisory' and not granted"
            ).fetchone()
            if row["waiting"]:
                return
            time.sleep(0.05)
    raise AssertionError(f"{what} never waited on the workspace's lock")


def _while_an_erasure_holds_the_lock(world, spine_schema, database, sha256, request, what):
    """Run ``request`` in a thread while a transaction that holds the workspace's lock erases
    the creature: the request waits on the lock, the erasure commits, the request goes on.
    Answers what the request answered."""
    answers: list[Any] = []
    writer = scratch_role_database(spine_schema[1], RUNTIME_ROLE)
    with writer.session(world["workspace"]) as holder, holder.transaction():
        lock_workspace(holder, world["workspace"])
        thread = threading.Thread(target=lambda: answers.append(request()), daemon=True)
        thread.start()
        _waiting_on_a_lock(database, world, what)
        ThingStore(holder, world["workspace"], None).erase_creature(
            sha256, erased_by=world["session"].actor
        )
    thread.join(timeout=120)
    assert not thread.is_alive(), f"{what} did not finish after the erasure committed"
    [answer] = answers
    return answer


def test_a_minute_waiting_while_an_erasure_commits_does_not_run_the_erased_creature(
    world_app, kept, spine_schema
):
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        scope, _, society_route = routes(world)

        def step():
            return client.post(
                society_route + "/steps",
                headers=OWNER,
                params=scope,
                json={
                    "base_tick": society["current_tick"],
                    "base_state_sha256": society["state_sha256"],
                },
            )

        stepped = _while_an_erasure_holds_the_lock(
            world, spine_schema, database, kept.kind.sha256, step, "the minute"
        )
        assert stepped.status_code == 200, stepped.text
        # The minute began after the erasure committed: it was told first, and the being left.
        assert not _here(stepped.json(), being)
        assert made._inputs(database, world)[1]["things_gone"] == [CREATURE]
        assert _departures(client, world) == [(being["id"], "kind_erased")]
        assert things_api._replayed(client, world) is True


def test_a_placing_edit_waiting_while_an_erasure_commits_is_refused_the_erased_kind(
    world_app, kept, spine_schema
):
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        society = made._society(client, world, kept)
        being = _being(society)
        scope, root, _ = routes(world)
        base = client.get(root, headers=OWNER, params=scope).json()["state_sha256"]

        def place():
            return client.post(
                root + "/things",
                headers=OWNER,
                params=scope,
                json={
                    "base_state_sha256": base,
                    "thing_id": "creature:second",
                    "kind": {"source": "workspace", "sha256": kept.kind.sha256},
                    "region_id": world["binding"].region_id,
                    "pose": {"x_mm": -3_000, "y_mm": 0, "z_mm": 3_000, "yaw_microradians": 0},
                    "origin_role": "fictional",
                },
            )

        placed = _while_an_erasure_holds_the_lock(
            world, spine_schema, database, kept.kind.sha256, place, "the placing edit"
        )
        # The edit began after the erasure committed: the workspace holds no such kind to place.
        assert placed.status_code == 422, placed.text
        assert placed.json()["code"] == "invalid_thing_placement"
        assert "holds no thing kind" in placed.json()["detail"]
        # The society, told by nobody, loses the being it had at its next minute.
        society = things_api._step(client, world, society)
        assert not _here(society, being)
        assert all(p["placed_id"] != "creature:second" for p in society["state"]["inhabitants"])
        assert things_api._replayed(client, world) is True
