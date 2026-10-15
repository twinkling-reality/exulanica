"""The operator's run that makes asked creature looks, end to end with stand-in models
(:mod:`exulanica.hosting.creature_look_command`).

A creature is kept and its look asked; the command stages the queued job, writing its request
from the creature's kept documents; route P's stand-ins draw a picture and a model for it and its
fit runs, as the run's middle steps do (``ml/appearance``: ``make-job``, the GPU job, ``fit-run``);
and the command admits what the fit made. What is shown, against PostgreSQL:

*   a dry run of either step writes nothing and changes no job;
*   staging writes the request and marks the job staged under the run, listed in ``staged.json``;
*   admitting keeps the made look in the workspace's store (generated, private, drawn on the
    creature's plan, the fit's receipt in its lineage), ends the job made with its share of the
    cost, and the creature then wears the look by its kind; admitting again keeps nothing more;
*   a refused fit ends its job refused by the fit's code, and a request the job did not make ends
    its job failed; an end the database broke off to end a lock cycle is tried again;
*   a job whose creature was erased between staging and admitting keeps nothing;
*   admitting again after an end that failed once the look was kept wears that look, and keeps no
    second one of the same fit.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import exulanica
import psycopg
import pytest
from exulanica.db.session import set_workspace
from exulanica.env import env_get
from exulanica.hosting.creature_look_command import FITS_PROFILE, made_admits, main
from exulanica.store.configured import content_stores
from exulanica.world import creature_look_jobs as look_jobs
from exulanica.world.thing_store import ThingStore, ThingStoreRefused
from psycopg.rows import dict_row

from test_thing_store_postgres import ACTOR, _creature

pytestmark = pytest.mark.postgres

ROOT = Path(exulanica.__file__).resolve().parents[1]


def _connect():
    return psycopg.connect(env_get("DATABASE_URL"), autocommit=True, row_factory=dict_row)


@pytest.fixture
def kept(cli_database, tmp_path, monkeypatch):
    """A workspace keeping two creatures, a look asked of each."""
    monkeypatch.delenv("EXULANICA_STORE_KIND", raising=False)
    workspace, data = uuid.uuid4(), tmp_path / "data"
    creatures = [_creature("command horse", "horse"), _creature("command dragon", "dragon")]
    with _connect() as connection:
        set_workspace(connection, workspace)
        store = ThingStore(
            connection, workspace, content_stores(data_dir=data).looks.for_workspace(workspace)
        )
        asked = []
        for creature in creatures:
            store.keep_creature(creature, created_by=ACTOR)
            asked.append(
                look_jobs.ask_look(
                    connection, workspace, kind_sha256=creature.kind.sha256, requested_by=ACTOR
                )
            )
    return workspace, data, creatures, asked


def _job(workspace, look_id):
    with _connect() as connection:
        set_workspace(connection, workspace)
        return look_jobs.read_look(connection, workspace, look_id)


def _stage(workspace, data, run, *extra) -> int:
    return main(
        ["stage", "--workspace", str(workspace), "--out", str(run), "--data-dir", str(data), *extra]
    )


def _admit(run, fits, data, *extra, cost="0.50") -> int:
    return main(
        [
            "admit",
            "--run",
            str(run),
            "--fits",
            str(fits),
            "--cost-usd",
            cost,
            "--data-dir",
            str(data),
            *extra,
        ]
    )


def _fits_by_stand_in(run: Path, out: Path, monkeypatch) -> dict:
    """Route P's middle steps with stand-in models: the job record, the pictures and models, the
    fit of each, as ``make-job``, the GPU job and ``fit-run`` write them."""
    monkeypatch.syspath_prepend(str(ROOT / "ml" / "appearance"))
    from exulanica_appearance.creatures.fit import fit_run
    from exulanica_appearance.creatures.pictures import (
        StandIn,
        make_job,
        prepare_picture_job,
        run_picture_job,
    )
    from exulanica_pieces.colour import read_table
    from exulanica_pieces.geometry.mesh import cluster_simplify

    requests = {path.stem: path.read_bytes() for path in sorted((run / "requests").glob("*.json"))}
    job = make_job(list(requests.values()), repository=ROOT, framing="whole-body", seeds=[11])
    prepared = prepare_picture_job(
        job_raw=job, requests=list(requests.values()), pictures={}, repository=ROOT
    )
    pictures = out.parent / "pictures"
    results = run_picture_job(prepared, StandIn(), pictures)
    table, _ = read_table(ROOT)
    return fit_run(
        results=results,
        requests=requests,
        pictures=pictures,
        out=out,
        table=table,
        simplifier=cluster_simplify,
        made_by={"provider": "stand-in", "model_id": "stand-in"},
    )


def test_a_run_stages_the_asked_looks_and_admits_what_the_fit_made(
    kept, tmp_path, capsys, monkeypatch
):
    workspace, data, creatures, asked = kept
    run, fits = tmp_path / "run", tmp_path / "fits"
    # A dry run writes nothing and changes no job.
    assert _stage(workspace, data, run) == 0
    assert "would stage 2 look jobs" in capsys.readouterr().out
    assert not run.exists() and _job(workspace, asked[0].look_id).status == "queued"
    assert _stage(workspace, data, run, "--apply") == 0
    staged = json.loads((run / "staged.json").read_bytes())
    assert [item["look_id"] for item in staged["items"]] == [str(look.look_id) for look in asked]
    for item in staged["items"]:
        request = json.loads((run / "requests" / f"{item['request_sha256']}.json").read_bytes())
        assert request["profile"] == "exulanica.creature-look-request/v1"
        job = _job(workspace, uuid.UUID(item["look_id"]))
        assert (job.status, str(job.run_id), job.request_sha256) == (
            "staged",
            staged["run_id"],
            item["request_sha256"],
        )
    document = _fits_by_stand_in(run, fits, monkeypatch)
    assert [entry["outcome"] for entry in document["requests"].values()] == ["passed"] * 2
    capsys.readouterr()
    assert _admit(run, fits, data) == 0
    assert capsys.readouterr().out.count("would admit") == 2
    assert _job(workspace, asked[0].look_id).status == "staged"
    assert _admit(run, fits, data, "--apply") == 0
    lines = capsys.readouterr().out.splitlines()
    assert sum(line.startswith("made ") for line in lines) == 2
    with _connect() as connection:
        set_workspace(connection, workspace)
        worn = look_jobs.kind_looks(connection, workspace)
        for creature, look in zip(creatures, asked, strict=True):
            job = look_jobs.read_look(connection, workspace, look.look_id)
            assert (job.status, job.cost_usd) == ("made", Decimal("0.25000000"))
            made = worn[creature.kind.sha256]
            assert made.sha256 == job.look_sha256
            assert made.look == f"{creature.plan.key.replace('_', '-')}-made"
            assert made.body_plan == creature.plan.name
            origin = made.document["origin"]
            assert (origin["class"], origin["distribution"]) == ("generated", "private")
            fitted = document["requests"][job.request_sha256]
            assert origin["lineage"]["receipts"] == [fitted["receipt_sha256"]]
            assert origin["lineage"]["ingredients"] == [fitted["cutout_sha256"]]
    # Admitted once: the jobs have ended.
    assert _admit(run, fits, data, "--apply") == 0
    assert capsys.readouterr().out.count("no longer staged under this run") == 2


def _write_fits(fits: Path, outcomes: dict) -> None:
    fits.mkdir(parents=True, exist_ok=True)
    document = {
        "profile": FITS_PROFILE,
        "made_by": {"provider": "stand-in", "model_id": "stand-in"},
        "requests": outcomes,
    }
    (fits / "fits.json").write_text(json.dumps(document))


def test_a_refused_fit_and_an_unmade_request_end_their_jobs_by_code(
    kept, tmp_path, capsys, monkeypatch
):
    workspace, data, _creatures, asked = kept
    run, fits = tmp_path / "run", tmp_path / "fits"
    assert _stage(workspace, data, run, "--apply") == 0
    staged = json.loads((run / "staged.json").read_bytes())
    refused, unmade = (item["request_sha256"] for item in staged["items"])
    _write_fits(
        fits,
        {
            refused: {
                "outcome": "refused",
                "seed": 11,
                "receipt_sha256": "9" * 64,
                "refusal": "rig_chain_not_found",
            }
        },
    )
    # The database ends one end to break a lock cycle; the end is tried again.
    real, broken = look_jobs.end_look, []

    def deadlocked_once(*args, **kwargs):
        if not broken:
            broken.append(True)
            raise psycopg.errors.DeadlockDetected("deadlock detected")
        return real(*args, **kwargs)

    monkeypatch.setattr(look_jobs, "end_look", deadlocked_once)
    assert _admit(run, fits, data, "--apply", cost="0.30") == 0
    assert broken == [True]
    first, second = (_job(workspace, look.look_id) for look in asked)
    assert (first.status, first.refusal_code, first.cost_usd) == (
        "refused",
        "rig_chain_not_found",
        Decimal("0.15000000"),
    )
    assert (second.status, second.failure) == ("failed", "not_made")
    assert unmade not in json.loads((fits / "fits.json").read_bytes())["requests"]


def test_a_job_whose_creature_was_erased_after_staging_keeps_nothing(kept, tmp_path, capsys):
    workspace, data, creatures, asked = kept
    run, fits = tmp_path / "run", tmp_path / "fits"
    assert _stage(workspace, data, run, "--apply") == 0
    staged = json.loads((run / "staged.json").read_bytes())
    with _connect() as connection:
        set_workspace(connection, workspace)
        ThingStore(connection, workspace, None).erase_creature(
            creatures[0].kind.sha256, erased_by=ACTOR
        )
    _write_fits(
        fits,
        {
            item["request_sha256"]: {"outcome": "failed", "failure": "not_made"}
            for item in staged["items"]
        },
    )
    capsys.readouterr()
    assert _admit(run, fits, data, "--apply") == 0
    out = capsys.readouterr().out
    assert f"kept nothing for {asked[0].look_id}: no longer staged under this run" in out
    assert _job(workspace, asked[0].look_id) is None
    assert _job(workspace, asked[1].look_id).status == "failed"


def test_a_made_look_is_admitted_only_generated_private_and_on_its_creature_s_plan():
    admit = made_admits("command_horse/v1")
    origin = {"class": "generated", "distribution": "private"}
    admit(SimpleNamespace(body_plan="command_horse/v1", document={"origin": origin}))
    for body_plan, changed in (
        ("command_dragon/v1", {}),
        ("command_horse/v1", {"class": "imported"}),
        ("command_horse/v1", {"distribution": "public"}),
    ):
        with pytest.raises(ThingStoreRefused) as refused:
            admit(SimpleNamespace(body_plan=body_plan, document={"origin": {**origin, **changed}}))
        assert refused.value.code == "look_not_admitted"


def test_admitting_again_after_a_failed_end_wears_the_look_already_kept(
    kept, tmp_path, capsys, monkeypatch
):
    workspace, data, creatures, asked = kept
    run, fits = tmp_path / "run", tmp_path / "fits"
    assert _stage(workspace, data, run, "--apply") == 0
    _fits_by_stand_in(run, fits, monkeypatch)
    real = look_jobs.end_look

    def crash(*_args, **_kwargs):
        raise RuntimeError("the run's machine went down once the look was kept")

    monkeypatch.setattr(look_jobs, "end_look", crash)
    with pytest.raises(RuntimeError):
        _admit(run, fits, data, "--apply")
    monkeypatch.setattr(look_jobs, "end_look", real)
    # The first job's look was kept and its end never written: it is still staged.
    assert _job(workspace, asked[0].look_id).status == "staged"
    capsys.readouterr()
    assert _admit(run, fits, data) == 0
    assert "kept already" in capsys.readouterr().out
    assert _admit(run, fits, data, "--apply") == 0
    with _connect() as connection:
        set_workspace(connection, workspace)
        worn = look_jobs.kind_looks(connection, workspace)
        for creature, look in zip(creatures, asked, strict=True):
            key = f"{creature.plan.key.replace('_', '-')}-made"
            [row] = connection.execute(
                "select count(*) as n from look_version where workspace_id=%s and key=%s",
                (workspace, key),
            ).fetchall()
            assert row["n"] == 1, key
            job = look_jobs.read_look(connection, workspace, look.look_id)
            assert job.status == "made" and worn[creature.kind.sha256].sha256 == job.look_sha256
