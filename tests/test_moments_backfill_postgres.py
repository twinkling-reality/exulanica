"""The moments back-fill on a living town played before moments were written (private PostgreSQL).

A town whose model chose a place for one of its people is played with the minute's moment hook
turned off, as a town played before moments existed was. The back-fill command replays it from what
it stored: a run without ``--apply`` writes nothing and says what it would write; with it, the going
the model chose is written once, with the id the minute's own hook gives it; a second run writes
nothing. A society whose stored input is no longer authorized is refused by name, none of its
moments written, while the workspace's other societies are still back-filled.
"""

from __future__ import annotations

import dataclasses
import io
import json
import uuid

import pytest
from exulanica.api import moments_backfill
from exulanica.world import society_repository
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_moments import load_rules, moment_id_of

from test_society_living_town_postgres import (  # noqa: F401
    _decided,
    _every_town_a_test_makes_is_made,
    _made_alias,
    _town_society,
    imported_made,
)

pytestmark = pytest.mark.postgres


def _rows(api, society_id: uuid.UUID) -> list[dict]:
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select moment_id, kind, tick, subjects, anchor_event_id, request_id, document "
            "from world_society_moment where workspace_id=%s and society_id=%s "
            "order by tick, moment_id",
            (api.repository.workspace_id, society_id),
        ).fetchall()


def _run(services, workspace: uuid.UUID, *arguments: str) -> tuple[int, list[dict]]:
    output = io.StringIO()
    code = moments_backfill.main(
        ["--workspace", str(workspace), *arguments], services=services, stream=output
    )
    lines = [json.loads(line) for line in output.getvalue().splitlines()]
    return code, [line for line in lines if line["event"] == "society"]


def _played_without_moments(api, monkeypatch) -> tuple[dict, dict, str, dict]:
    with monkeypatch.context() as quiet:
        # As a town played before moments were written: its minutes write none.
        quiet.setattr(society_repository, "record_moments", lambda *_args, **_keywords: [])
        return _decided(api, "target")


def test_a_town_played_before_moments_is_back_filled_once_as_its_minute_would_have(
    made, monkeypatch
):
    entry, body, subject, chosen = _played_without_moments(made, monkeypatch)
    services = made.client.app.state.services
    workspace = made.repository.workspace_id
    society_id = uuid.UUID(body["society_id"])
    assert _rows(made, society_id) == [], "the positive control: played with no moment written"

    code, [report] = _run(services, workspace)
    assert code == 0, report
    assert report["outcome"] == "would_write"
    assert report["minutes_seen"] == body["current_tick"] == report["minutes"]
    assert report["moments_before"] == 0 and report["moments"] >= 1
    assert _rows(made, society_id) == [], "a run without --apply writes nothing"

    code, [report] = _run(services, workspace, "--apply")
    assert code == 0, report
    assert report["outcome"] == "written"
    rows = _rows(made, society_id)
    assert len(rows) == report["moments"]
    [went] = [row for row in rows if row["kind"] == "went"]
    assert went["subjects"] == [uuid.UUID(subject)]
    assert went["tick"] == body["current_tick"]
    assert went["request_id"] is not None
    assert went["document"]["target"] == {
        "target_id": str(chosen["target_id"]),
        "activity": chosen.get("activity"),
    }
    # The id the minute's hook gives the same moment, so neither writes it twice.
    version = uuid.UUID(entry["authored_version_id"])
    assert went["moment_id"] == moment_id_of(version, load_rules(), went["anchor_event_id"])

    code, [report] = _run(services, workspace, "--apply")
    assert (code, report["outcome"], report["moments"]) == (0, "written", 0)
    assert _rows(made, society_id) == rows


def test_a_society_whose_input_is_withdrawn_is_refused_and_the_others_are_still_back_filled(
    made, monkeypatch
):
    entry, body, _subject, _chosen = _played_without_moments(made, monkeypatch)
    other, _society, _created = _town_society(made)
    services = made.client.app.state.services
    runtime = services.society_runtime

    class Withdrawn:
        """The API's runtime, but the first town's stored input is no longer authorized."""

        def authorize(self, connection, session, document):
            if document["world_id"] == entry["world_id"]:
                raise UnavailableSocietyInput("the input's assets were withdrawn")
            return runtime.authorize(connection, session, document)

    code, reports = _run(
        dataclasses.replace(services, society_runtime=Withdrawn()),
        made.repository.workspace_id,
        "--apply",
    )
    assert code == 1
    by_world = {report["world_id"]: report for report in reports}
    assert by_world[entry["world_id"]]["outcome"] == "refused"
    assert by_world[entry["world_id"]]["reason"] == "UnavailableSocietyInput"
    assert by_world[other["world_id"]]["outcome"] == "written"
    assert _rows(made, uuid.UUID(body["society_id"])) == [], "nothing of a refused society"
