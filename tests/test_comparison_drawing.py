"""A completed comparison run's drawing is verified once, stored, and served under its code's
digest.

The host that plays a run replays it once its outcome is recorded, holds the replay to what the run
recorded and stores the document the page draws (migration 0121's ``society_comparison_replay``),
under :func:`~exulanica.world.society_comparison_drawing.drawing_sha256`. A read serves that
drawing, asking the inputs' rights before it answers, and replays where none is stored under its
code's digest. These tests hold the list the digest covers to what a verified replay executes, the
stored form, the read path and the rights asked on it, and the table's rules.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import exulanica
import psycopg
import pytest
from exulanica.api.routes import society_comparisons
from exulanica.api.society_comparison_runner import SocietyComparisonRunner
from exulanica.models.manifest import load_manifest
from exulanica.world import society_comparison_drawing as drawing_module
from exulanica.world.society_comparison import play
from exulanica.world.society_comparison_drawing import (
    DRAWING_MODULES,
    DrawingCorrupt,
    StoredDrawing,
    decode,
    drawing_sha256,
    encode,
    with_names,
)
from exulanica.world.society_comparison_result import (
    REPLAY_PROFILE,
    replay_document,
    verified_replay,
)
from fastapi.testclient import TestClient

import test_comparison_play_goldens as goldens
import test_comparison_run_route_authorizes_last as route_support
from comparison_support import seeded_catalogs

PACKAGE = Path(exulanica.__file__).resolve().parent


def _played(arm: str):
    plan = goldens._plans()[arm]
    played = play(plan, goldens._Scripted(held_back=None))
    stored = list(zip(played.requests, played.receipts, strict=True))
    outcome = {
        "status": "completed",
        "minutes": {"state_sha256": played.minute_digests},
        "events_sha256": played.events_sha256,
        "receipts": {"count": len(played.receipts), "sha256": played.receipts_sha256},
    }
    return plan, stored, outcome


@pytest.mark.parametrize("arm", ["model", "group", "routine"])
def test_the_digest_covers_every_module_a_verified_replay_and_its_drawing_execute(arm):
    plan, stored, outcome = _played(arm)
    executed: set[str] = set()

    def traced(frame, event, _arg):
        if event == "call":
            found = Path(frame.f_code.co_filename)
            if found.is_relative_to(PACKAGE):
                executed.add(".".join(found.relative_to(PACKAGE.parent).with_suffix("").parts))

    sys.setprofile(traced)
    try:
        replayed = verified_replay(plan, stored, outcome)
        replay_document(plan, {}, arm, "0" * 64, replayed, model_name=str)
    finally:
        sys.setprofile(None)
    # The trace saw the replay: the engine and the drawing ran.
    assert {"exulanica.world.society_comparison", "exulanica.world.society_planner"} <= executed
    assert executed <= set(DRAWING_MODULES), sorted(executed - set(DRAWING_MODULES))


def test_a_change_to_a_drawing_module_is_a_new_digest(monkeypatch):
    before = drawing_sha256(REPLAY_PROFILE)
    real = drawing_module._module_bytes
    monkeypatch.setattr(
        drawing_module,
        "_module_bytes",
        lambda name: real(name) + (b"#" if name == "exulanica.world.society_planner" else b""),
    )
    drawing_sha256.cache_clear()
    try:
        assert drawing_sha256(REPLAY_PROFILE) != before
    finally:
        monkeypatch.undo()
        drawing_sha256.cache_clear()
    assert drawing_sha256(REPLAY_PROFILE) == before


def test_a_stored_drawing_names_models_by_id_and_is_held_to_its_digest():
    plan, stored, outcome = _played("model")
    document = replay_document(
        plan, {}, "model", "0" * 64, verified_replay(plan, stored, outcome), model_name=str.upper
    )
    encoded = encode(document)
    decoded = decode(encoded)
    models = [p["decider"] for p in decoded["people"] if p["decider"]["kind"] == "model"]
    assert models and all(decider["name"] == "" for decider in models)
    assert with_names(decoded, str.upper) == document
    tampered = StoredDrawing(encoded.document_gzip, "0" * 64, encoded.document_bytes)
    with pytest.raises(DrawingCorrupt):
        decode(tampered)


# -- the stored drawing, read through the application --------------------------------------------

saved_world = route_support.saved_world
runtime_app = route_support.runtime_app


def _runner(client, world) -> SocietyComparisonRunner:
    services = client.app.state.services
    return SocietyComparisonRunner(
        database=services.database,
        runtime=services.society_runtime,
        client=None,
        policy_for=services.person_decision_policy,
        manifest=load_manifest(),
        manifest_sha256="a" * 64,
        workspace_id=world["workspace"],
        world_id=world["binding"].world_id,
        actor=world["session"].actor,
        catalogs=seeded_catalogs(population_maximum=512),
    )


def _drawn_routine_run(client, world):
    """A completed routine run, drawn as a host draws its runs once they are played."""
    comparison_id, run_id = route_support._completed_routine_run(client, world)
    assert not _drawings(world["connection"], run_id), "playing a run draws nothing"
    assert _runner(client, world).draw_all(comparison_id, [run_id]) == 1
    return comparison_id, run_id


def _drawings(connection, run_id) -> list[dict]:
    return connection.execute(
        "select drawing_sha256, document_bytes, octet_length(document_gzip) as stored "
        "from society_comparison_replay where run_id=%s",
        (run_id,),
    ).fetchall()


@pytest.mark.postgres
@route_support.CURRENT_GROUND
def test_a_completed_run_is_drawn_once_and_read_without_a_replay(runtime_app, monkeypatch):
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        comparison_id, run_id = _drawn_routine_run(client, world)
        stored = _drawings(world["connection"], run_id)
        assert [row["drawing_sha256"] for row in stored] == [drawing_sha256(REPLAY_PROFILE)]
        # Positive control: under a digest nothing is stored under, the read replays the run.
        with monkeypatch.context() as patch:
            patch.setattr(society_comparisons, "drawing_sha256", lambda _profile: "f" * 64)
            replayed = route_support._read(client, world, comparison_id, run_id)
        assert replayed.status_code == 200, replayed.text

        def no_replay(*_args, **_kwargs):
            raise AssertionError("a stored drawing is served without a replay")

        monkeypatch.setattr(society_comparisons, "verified_replay", no_replay)
        served = route_support._read(client, world, comparison_id, run_id)
    assert served.status_code == 200, served.text
    assert served.json() == replayed.json()


@pytest.mark.postgres
@route_support.CURRENT_GROUND
def test_a_stored_drawing_is_never_served_once_an_input_lost_its_right(runtime_app, monkeypatch):
    world, make_app = runtime_app
    key = world["plate"].asset_key
    connection = world["connection"]
    licence = connection.execute(
        "select licence_sha256 from world_reviewed_asset where asset_key=%s", (key,)
    ).fetchone()["licence_sha256"]
    connection.commit()
    try:
        with TestClient(make_app()) as client:
            comparison_id, run_id = _drawn_routine_run(client, world)
            assert _drawings(connection, run_id), "the run's drawing is stored"
            monkeypatch.setattr(
                society_comparisons,
                "verified_replay",
                lambda *_a, **_k: pytest.fail("the stored drawing is the one read"),
            )
            # Positive control: with every right held, the stored drawing is served.
            assert route_support._read(client, world, comparison_id, run_id).status_code == 200
            connection.execute(
                "update world_reviewed_asset set licence_sha256=%s where asset_key=%s",
                ("0" * 64, key),
            )
            connection.commit()
            refused = route_support._read(client, world, comparison_id, run_id)
        assert refused.status_code == 424, refused.text
        assert refused.json()["code"] == "unavailable_society_input"
    finally:
        connection.execute(
            "update world_reviewed_asset set licence_sha256=%s where asset_key=%s", (licence, key)
        )
        connection.commit()


@pytest.mark.postgres
@route_support.CURRENT_GROUND
def test_a_drawing_is_appended_once_and_never_changed(runtime_app):
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        comparison_id, run_id = _drawn_routine_run(client, world)
        services = client.app.state.services
        runner = _runner(client, world)
        # Drawing it again finds it stored and stores nothing more.
        assert runner.draw(comparison_id, run_id) is True
        assert len(_drawings(world["connection"], run_id)) == 1
        with services.database.session(world["workspace"]) as connection:
            for statement in (
                "update society_comparison_replay set document_bytes=1 where run_id=%s",
                "delete from society_comparison_replay where run_id=%s",
            ):
                with pytest.raises(psycopg.Error), connection.transaction():
                    connection.execute(statement, (run_id,))
            # A drawing of a run with no completed outcome is refused.
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(
                    "insert into society_comparison_replay(workspace_id,world_id,comparison_id,"
                    "run_id,drawing_sha256,document_sha256,document_bytes,document_gzip) "
                    "values(%s,%s,%s,%s,%s,%s,1,'\\x00')",
                    (
                        world["workspace"],
                        world["binding"].world_id,
                        comparison_id,
                        uuid.uuid4(),
                        "a" * 64,
                        "b" * 64,
                    ),
                )
    assert len(_drawings(world["connection"], run_id)) == 1
