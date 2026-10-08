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
from exulanica.abilities.registry import MODULES_PATH as ABILITY_MODULES_PATH
from exulanica.api.routes import society_comparisons
from exulanica.api.society_comparison_runner import SocietyComparisonRunner
from exulanica.models.manifest import load_manifest
from exulanica.movement.registry import MODULES_PATH
from exulanica.things.catalogs import CATALOG_DIRECTORY as THING_CATALOG_DIRECTORY
from exulanica.things.kinds import KINDS_DIRECTORY
from exulanica.world import society_comparison_drawing as drawing_module
from exulanica.world.decision_roles import REGISTRY_DIRECTORY
from exulanica.world.society_catalogs import ROUTINE_DIRECTORY
from exulanica.world.society_comparison import play
from exulanica.world.society_comparison_drawing import (
    DRAWING_MODULES,
    DrawingCorrupt,
    StoredDrawing,
    decode,
    drawing_data,
    drawing_sha256,
    encode,
    with_names,
)
from exulanica.world.society_comparison_result import (
    REPLAY_PROFILE,
    replay_document,
    verified_replay,
)
from exulanica.world.society_engines import ENGINES_PATH
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


@pytest.mark.parametrize("family", ["living", "things"])
def test_a_family_s_drawing_trace_is_covered_by_its_digest(family):
    plan, stored, outcome = _living_played() if family == "living" else _things_played()
    executed: set[str] = set()

    def traced(frame, event, _arg):
        if event == "call":
            found = Path(frame.f_code.co_filename)
            if found.is_relative_to(PACKAGE):
                executed.add(".".join(found.relative_to(PACKAGE.parent).with_suffix("").parts))

    sys.setprofile(traced)
    try:
        replayed = verified_replay(plan, stored, outcome)
        drawing = replay_document(plan, {}, "model", "0" * 64, replayed, model_name=str)
    finally:
        sys.setprofile(None)
    assert drawing["profile"] == (
        "exulanica.society-comparison-run-replay/v3"
        if family == "living"
        else "exulanica.society-comparison-run-replay/v2"
    )
    assert executed <= set(DRAWING_MODULES), sorted(executed - set(DRAWING_MODULES))


def test_the_digest_covers_the_data_a_replay_reads_as_well_as_its_code():
    data = set(drawing_data())
    assert {MODULES_PATH, ENGINES_PATH} <= data
    assert set(REGISTRY_DIRECTORY.glob("*.json")) <= data
    seeds = set(ROUTINE_DIRECTORY.glob("society-comparison-seeds.v*.json"))
    assert len(seeds) >= 6
    assert set(ROUTINE_DIRECTORY.glob("*.json")) - seeds <= data
    # A society of things' replay reads the ability modules, the thing catalogs and the kinds.
    assert {ABILITY_MODULES_PATH, *KINDS_DIRECTORY.glob("*.json")} <= data
    assert set(THING_CATALOG_DIRECTORY.glob("*.json")) <= data
    # A drawing names no seed and its replay reads no comparison catalog (below), so a new set of
    # held-out seeds is no drawing input.
    assert not seeds & data


def _outcome(played):
    return {
        "status": "completed",
        "minutes": {"state_sha256": played.minute_digests},
        "events_sha256": played.events_sha256,
        "receipts": {"count": len(played.receipts), "sha256": played.receipts_sha256},
    }


def _things_played():
    from test_society_things_comparison import _Choosing, _knights, _plan

    plan = _plan("model", group=_knights(), ticks=20)
    played = play(plan, _Choosing())
    return plan, list(zip(played.requests, played.receipts, strict=True)), _outcome(played)


def _living_played():
    from test_society_living_comparison import _Choosing, _plan

    plan = _plan("model")
    played = play(plan, _Choosing())
    stored = list(zip(played.requests, played.receipts, strict=True))
    outcome = {
        "status": "completed",
        "minutes": {"state_sha256": played.minute_digests},
        "events_sha256": played.events_sha256,
        "receipts": {"count": len(played.receipts), "sha256": played.receipts_sha256},
    }
    return plan, stored, outcome


@pytest.mark.parametrize("arm", ["model", "group", "routine", "living", "things"])
def test_a_replay_and_its_drawing_read_no_comparison_catalog(monkeypatch, arm):
    from exulanica.world import society_catalogs

    plan, stored, outcome = (
        _living_played()
        if arm == "living"
        else _things_played()
        if arm == "things"
        else _played(arm)
    )
    read: list[str] = []

    def refused(*_args, **_kwargs):
        read.append("load_comparison_catalogs")
        raise AssertionError("a replay read a comparison catalog")

    real_load = society_catalogs.load_catalog

    def load(path, *args, **kwargs):
        if Path(path).name.startswith("society-comparison-"):
            read.append(Path(path).name)
        return real_load(path, *args, **kwargs)

    # Every module that holds the loader by name, so no import path reaches the real one.
    for module in list(sys.modules.values()):
        if (
            getattr(module, "load_comparison_catalogs", None)
            is society_catalogs.load_comparison_catalogs
        ):
            monkeypatch.setattr(module, "load_comparison_catalogs", refused)
    monkeypatch.setattr(society_catalogs, "load_catalog", load)
    replayed = verified_replay(plan, stored, outcome)
    drawn = replay_document(
        plan,
        {},
        "model" if arm in ("living", "things") else arm,
        "0" * 64,
        replayed,
        model_name=str,
    )
    assert drawn["profile"]
    assert read == []


def test_a_new_set_of_seeds_leaves_the_digest_and_every_stored_drawing_current(
    monkeypatch, tmp_path
):
    from exulanica.world import society_comparison_seeds

    assert society_comparison_seeds.__name__ not in DRAWING_MODULES
    copy = tmp_path / "society"
    copy.mkdir()
    for file in ROUTINE_DIRECTORY.glob("*.json"):
        (copy / file.name).write_bytes(file.read_bytes())
    monkeypatch.setattr(drawing_module, "ROUTINE_DIRECTORY", copy)
    # The digest is taken over the files in path order, so the copy's is its own baseline; the
    # last assertion shows the copy is what it reads.
    before = drawing_module._code_sha256()
    newest = sorted(copy.glob("society-comparison-seeds.v*.json"))[-1]
    (copy / "society-comparison-seeds.v99.json").write_bytes(newest.read_bytes())
    newest.write_bytes(newest.read_bytes() + b" ")
    assert drawing_module._code_sha256() == before
    # Any other society catalog is still covered: the same change to it is a new digest.
    other = copy / "society-need.v1.json"
    other.write_bytes(other.read_bytes() + b" ")
    assert drawing_module._code_sha256() != before


@pytest.mark.parametrize("changed", ["module", "movement", "engines", "roles"])
def test_a_change_to_any_file_the_digest_covers_is_a_new_digest(monkeypatch, tmp_path, changed):
    before = drawing_module._code_sha256()
    assert before == drawing_module.CODE_SHA256, "taken once, at import"
    targets = {
        "movement": MODULES_PATH,
        "engines": ENGINES_PATH,
        "roles": sorted(REGISTRY_DIRECTORY.glob("*.json"))[0],
    }
    if changed == "module":
        planner = drawing_module._module_path("exulanica.world.society_planner")
        copy = tmp_path / planner.name
        copy.write_bytes(planner.read_bytes() + b"#")
        real = drawing_module._module_path
        monkeypatch.setattr(
            drawing_module,
            "_module_path",
            lambda name: copy if name == "exulanica.world.society_planner" else real(name),
        )
    else:
        target = targets[changed]
        copy = tmp_path / target.name
        copy.write_bytes(target.read_bytes() + b" ")
        files = tuple(copy if path == target else path for path in drawing_data())
        monkeypatch.setattr(drawing_module, "drawing_data", lambda: files)
    assert drawing_module._code_sha256() != before


@pytest.mark.parametrize("damage", ["not-gzip", "cut-short", "longer"])
def test_stored_bytes_that_are_not_the_drawing_are_refused_by_name(damage):
    plan, stored, outcome = _played("routine")
    encoded = encode(
        replay_document(
            plan, {}, "routine", "0" * 64, verified_replay(plan, stored, outcome), model_name=str
        )
    )
    broken = {
        "not-gzip": StoredDrawing(b"not gzip", encoded.document_sha256, encoded.document_bytes),
        "cut-short": StoredDrawing(
            encoded.document_gzip[: len(encoded.document_gzip) // 2],
            encoded.document_sha256,
            encoded.document_bytes,
        ),
        "longer": StoredDrawing(
            encoded.document_gzip, encoded.document_sha256, encoded.document_bytes - 1
        ),
    }[damage]
    with pytest.raises(DrawingCorrupt):
        decode(broken)


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
    assert _runner(client, world).draw_all(comparison_id) == 1
    return comparison_id, run_id


@pytest.mark.postgres
@route_support.CURRENT_GROUND
def test_draw_all_continues_after_one_run_cannot_be_drawn(runtime_app, monkeypatch):
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        comparison_id, routine_id = route_support._completed_routine_run(client, world)
        runner = _runner(client, world)
        with runner.database.session(world["workspace"]) as connection:
            runs = runner._repository(connection).runs(comparison_id)
            wait_id = next(run["run_id"] for run in runs if run["arm"] == "wait")
        assert runner.run(comparison_id, wait_id)["status"] == "completed"
        tried = []

        def draw(_runner, _comparison_id, run_id):
            tried.append(run_id)
            if run_id == routine_id:
                raise RuntimeError("one drawing failed")
            return True

        monkeypatch.setattr(SocietyComparisonRunner, "draw", draw)
        assert runner.draw_all(comparison_id) == 1
        assert set(tried) == {routine_id, wait_id}


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


@pytest.mark.postgres
@route_support.CURRENT_GROUND
def test_a_stored_drawing_that_is_not_its_drawing_is_read_by_a_replay(runtime_app):
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        comparison_id, run_id = route_support._completed_routine_run(client, world)
        services = client.app.state.services
        # Bytes stored under this code's digest that are not gzip: what a damaged row reads as.
        with services.database.session(world["workspace"]) as connection, connection.transaction():
            connection.execute(
                "insert into society_comparison_replay(workspace_id,world_id,comparison_id,"
                "run_id,drawing_sha256,document_sha256,document_bytes,document_gzip) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    world["workspace"],
                    world["binding"].world_id,
                    comparison_id,
                    run_id,
                    drawing_sha256(REPLAY_PROFILE),
                    "0" * 64,
                    10,
                    b"not gzip at all",
                ),
            )
        read = route_support._read(client, world, comparison_id, run_id)
        assert read.status_code == 200, read.text
        assert read.json()["replay_verified"] is True
        # The row is never changed, so the run is not drawn again, and reads keep replaying it.
        assert _runner(client, world).draw_all(comparison_id) == 0
