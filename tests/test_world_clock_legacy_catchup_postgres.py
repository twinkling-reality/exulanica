"""A legacy world's model-controlled signal catches up at most one episode after downtime.

The controller keeps the wall clock for a legacy world. Before this bound, a controller that had
been stopped sealed every minute it missed, oldest first, and the current minute stayed unsealed,
refused to viewers, until it reached it. Now the span it missed beyond one episode is recorded once
as a ``legacy_signal_gap`` receipt and left unsealed, the chain starts again at the current
episode, and every minute sealed before the gap stays byte for byte what it was, replayed alike.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.api.traffic_signal_controller import TrafficSignalController
from exulanica.models.manifest import load_manifest
from exulanica.world.decision_roles import decision_roles
from exulanica.world.traffic_episodes import EPISODE
from exulanica.world.traffic_host import saved_world_roads
from exulanica.world.traffic_signal_repository import TrafficSignalRepository

from test_world_clock_postgres import (  # noqa: F401
    _every_town_a_test_makes_is_made,
    _made_alias,
    _town,
    imported_made,
)

pytestmark = pytest.mark.postgres


def _segments(api, version: uuid.UUID) -> list[dict]:
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select * from world_traffic_signal_segment where version_id=%s "
            "order by episode,segment",
            (version,),
        ).fetchall()


def test_a_stopped_controller_skips_what_it_missed_and_never_touches_what_it_sealed(made):
    api = made
    entry, _society = _town(api)
    workspace = api.repository.workspace_id
    world_id = entry["world_id"]
    version = uuid.UUID(entry["authored_version_id"])
    role = decision_roles().deciding_for("signal")
    manifest = load_manifest()
    spec = next(
        spec
        for spec in manifest.offered_models(role.chosen)
        if role.contract().mechanism_for(spec) is not None
    )
    now = {"second": 0.0}
    controller = TrafficSignalController(
        api.database, None, (), lambda _workspace: None, clock=lambda: now["second"]
    )
    try:
        with api.database.session(workspace) as connection:
            snapshot = connection.execute(
                "select source_snapshot_id from world_alternate_version where version_id=%s",
                (version,),
            ).fetchone()["source_snapshot_id"]
            value = saved_world_roads(connection, workspace, world_id, snapshot)
        [signal, *_rest] = controller.signals(value)
        with api.database.session(workspace) as connection:
            chosen = TrafficSignalRepository(
                connection, workspace, world_id, version
            ).record_choice(
                role,
                manifest,
                request_id=uuid.uuid4(),
                signal_id=signal["signal_id"],
                known_signals=[signal["signal_id"]],
                model={"provider": spec.provider, "model_id": spec.model_id},
                chosen_by=api.actor,
            )
        # With no model client every point falls back to the fixed plan: the minutes are sealed
        # all the same, and none of this asks a model.
        now["second"] = chosen["effective_second"] + 30
        sealed_first = controller.prepare_world(workspace, world_id, version)
        assert sealed_first > 0
        before = _segments(api, version)
        first = before[0]
        window = controller.replay_window(
            workspace, world_id, version, value, first["start_second"], 60
        )
        # Three episodes of downtime later.
        now["second"] = chosen["effective_second"] + 30 + 3 * EPISODE
        current_episode = int(now["second"]) // EPISODE
        assert controller.prepare_world(workspace, world_id, version) > 0
        after = _segments(api, version)
        kept = [row for row in after if row["episode"] < current_episode]
        assert kept == before, "a minute sealed before the downtime changed"
        assert {row["episode"] for row in after if row not in before} == {current_episode}
        assert min(row["segment"] for row in after if row not in before) == 0
        again = controller.replay_window(
            workspace, world_id, version, value, first["start_second"], 60
        )
        assert again == window
        with api.database.session(workspace) as connection:
            gaps = connection.execute(
                "select document from world_clock_event where version_id=%s "
                "and kind='legacy_signal_gap'",
                (version,),
            ).fetchall()
        [gap] = [row["document"] for row in gaps]
        last = before[-1]
        assert gap["from_second"] == last["end_second"]
        assert gap["to_second"] == current_episode * EPISODE
        assert gap["skipped_seconds"] == gap["to_second"] - gap["from_second"]
        # The next turn goes on from the new chain and records the gap no second time.
        controller.prepare_world(workspace, world_id, version)
        with api.database.session(workspace) as connection:
            count = connection.execute(
                "select count(*) as n from world_clock_event where version_id=%s", (version,)
            ).fetchone()["n"]
        assert count == 1
    finally:
        controller.close()
