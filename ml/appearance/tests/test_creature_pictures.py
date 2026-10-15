"""Route P's paid step with stand-in models, end to end: a creature from its words and one from a
picture kept with it each become a picture, a cut-out and a 3D model, written once; the model is the
one the fit reads, and the stand-in's, the request's own rest skeleton, fits. Every item is checked
before a model runs, and the run stops before an item it could not finish inside the job's stop.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from exulanica_pieces.canonical import Refused, canonical_bytes
from exulanica_pieces.colour import read_table
from exulanica_pieces.geometry.mesh import cluster_simplify
from PIL import Image
from test_creature_fit import _request

from exulanica_appearance.creatures.fit import FIT_RUN_PROFILE, fit_look, fit_run, model_from_npz
from exulanica_appearance.creatures.pictures import (
    CATALOG_PATH,
    JOB_PROFILE,
    StandIn,
    framed_prompt,
    load_framings,
    make_job,
    prepare_picture_job,
    read_framings,
    run_picture_job,
)
from exulanica_appearance.creatures.request import REQUEST_PROFILE_V2, read_request

#: Each bone's thickness at rest (millimetres), as a drafted body states them: a torso thicker than
#: its limbs, so the stand-in's body reads as one.
THICKNESS = {"hips": 150, "spine1": 150, "spine2": 140, "head1": 100, "tail1": 45}


def _words() -> bytes:
    document = json.loads(_request())
    for bone, rest in document["rest"].items():
        rest["radius_mm"] = THICKNESS.get(bone, 45 if bone.startswith("leg") else 40)
    return json.dumps(document).encode()


def _png(colour=(200, 120, 60)) -> bytes:
    image = Image.new("RGB", (96, 96), (255, 255, 255))
    image.paste(colour, (24, 16, 72, 88))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _with_picture(picture: bytes) -> bytes:
    document = json.loads(_words())
    document["profile"] = REQUEST_PROFILE_V2
    document["picture"] = {"sha256": hashlib.sha256(picture).hexdigest(), "bytes": len(picture)}
    return json.dumps(document).encode()


def _job(repository: Path, items, *, item_seconds=60, stop_at=3600) -> bytes:
    _framings, catalog_sha256 = load_framings(repository)
    return canonical_bytes(
        {
            "profile": JOB_PROFILE,
            "route": "P",
            "code_sha256": "0" * 64,
            "components_sha256": "0" * 64,
            "container": "sha256:" + "0" * 64,
            "catalog_sha256": catalog_sha256,
            "items": items,
            "stop": {
                "estimate_seconds": item_seconds * len(items),
                "item_seconds": item_seconds,
                "stop_at_seconds": max(stop_at, item_seconds * len(items)),
            },
        }
    )


def _item(raw: bytes, framing="whole-body", seed=11, variant=0) -> dict:
    return {
        "request_sha256": hashlib.sha256(raw).hexdigest(),
        "seed": seed,
        "variant": variant,
        "framing": framing,
    }


def test_every_framing_in_the_catalog_reads_and_frames_words_with_no_numeral(repository):
    framings, _ = load_framings(repository)
    assert set(framings) == {"whole-body", "limbs-apart"}
    for framing in framings.values():
        prompt = framed_prompt(framing, "a round orange body with a yellow head.")
        assert prompt.startswith("A round orange body with a yellow head. One whole creature")
        assert not any(character.isdigit() for character in prompt)


@pytest.mark.parametrize(
    ("words", "refused"),
    [
        ("{appearance}, with three heads.", None),
        ("{appearance}, with 3 heads.", "numeral"),
        ("A creature alone.", "once and no other braces"),
        ("{appearance} and {appearance}.", "once and no other braces"),
        ("{appearance} {pose}.", "once and no other braces"),
    ],
)
def test_a_framing_holds_the_words_once_and_no_numeral(repository, words, refused):
    document = json.loads((repository / CATALOG_PATH).read_bytes())
    document["entries"][0]["words"] = words
    raw = json.dumps(document).encode()
    if refused is None:
        assert read_framings(raw)["whole-body"].words == words
    else:
        with pytest.raises(Refused, match=refused):
            read_framings(raw)


def test_a_creature_from_its_words_and_one_from_its_picture_become_models_the_fit_reads(
    repository, tmp_path
):
    words = _words()
    picture = _png()
    kept = _with_picture(picture)
    prepared = prepare_picture_job(
        job_raw=_job(repository, [_item(words), _item(kept, framing=None, seed=12)]),
        requests=[words, kept],
        pictures={hashlib.sha256(picture).hexdigest(): picture},
        repository=repository,
    )
    results = run_picture_job(prepared, StandIn(), tmp_path)
    assert results["stopped"] is None
    assert [item["outcome"] for item in results["items"]] == ["made", "made"]
    first, second = results["items"]
    framings, _ = load_framings(repository)
    prompt = framed_prompt(framings["whole-body"], read_request(words).appearance)
    assert first["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
    # The kept picture is the picture: no concept is drawn and no words are sent.
    assert second["prompt_sha256"] is None
    assert second["inputs"]["picture"] == hashlib.sha256(picture).hexdigest()
    for item in results["items"]:
        for name in ("picture", "cutout"):
            assert (tmp_path / "inputs" / f"{item['inputs'][name]}.png").is_file()
        assert item["mesh"]["frame"] == {"front": "-Y", "up": "+Z"}
    ended = list(tmp_path.glob(f"results-{prepared.job_sha256}-*.json"))
    assert len(ended) == 1 and json.loads(ended[0].read_bytes()) == results
    assert len(list(tmp_path.glob(f"progress-{prepared.job_sha256}-*.json"))) == 2
    # The model as written is the one the fit reads, and the stand-in's body is the plan's.
    model = model_from_npz((tmp_path / "meshes" / f"{first['mesh']['sha256']}.npz").read_bytes())
    cutout = (tmp_path / "inputs" / f"{first['inputs']['cutout']}.png").read_bytes()
    table, _ = read_table(repository)
    fitted = fit_look(
        read_request(words),
        model,
        up="+Z",
        front="-Y",
        cutout_png=cutout,
        simplifier=cluster_simplify,
        table=table,
    )
    assert fitted.receipt["outcome"] == "passed", fitted.receipt.get("refusal")


def test_the_job_s_code_archive_carries_the_catalog_the_job_reads(repository):
    """On the rented machine the code archive is the repository: a catalog left out of it fails
    the job after its setup has been paid for."""
    import tarfile

    from exulanica_appearance.assets.nebius import code_archive

    with tarfile.open(fileobj=io.BytesIO(code_archive(repository))) as archive:
        assert CATALOG_PATH in archive.getnames()


def test_every_item_is_checked_before_a_model_runs(repository):
    words = _words()
    picture = _png()
    kept = _with_picture(picture)
    given = {hashlib.sha256(picture).hexdigest(): picture}

    def prepare(items, requests=(words, kept), pictures=given):
        return prepare_picture_job(
            job_raw=_job(repository, items),
            requests=list(requests),
            pictures=pictures,
            repository=repository,
        )

    with pytest.raises(Refused, match="needs a framing"):
        prepare([_item(words, framing=None)])
    with pytest.raises(Refused, match="needs a framing"):
        prepare([_item(words, framing="side-on")])
    with pytest.raises(Refused, match="takes no framing"):
        prepare([_item(kept)])
    with pytest.raises(Refused, match="picture its request names was not given"):
        prepare([_item(kept, framing=None)], pictures={})
    with pytest.raises(Refused, match="not given"):
        prepare([_item(words)], requests=[kept])
    job = json.loads(_job(repository, [_item(words)]))
    job["catalog_sha256"] = "2" * 64
    with pytest.raises(Refused, match="another creature looks catalog"):
        prepare_picture_job(
            job_raw=canonical_bytes(job), requests=[words], pictures={}, repository=repository
        )


def test_the_run_stops_before_an_item_it_could_not_finish_inside_the_stop(repository, tmp_path):
    words = _words()
    items = [_item(words, variant=variant, seed=variant) for variant in range(4)]
    prepared = prepare_picture_job(
        job_raw=_job(repository, items, item_seconds=100, stop_at=400),
        requests=[words],
        pictures={},
        repository=repository,
    )
    ticks = iter(range(0, 10_000, 25))
    # Each clock reading 25 s after the last, seven readings an item: the third item would start
    # at 325 s and end, at its estimate of 100 s half as much again, past the stop at 400 s.
    results = run_picture_job(prepared, StandIn(), tmp_path, started=0, clock=lambda: next(ticks))
    assert len(results["items"]) == 2
    assert results["stopped"].startswith("before item 2:")
    assert list(tmp_path.glob(f"results-{prepared.job_sha256}-*.json"))


def test_a_job_record_draws_every_request_once_a_seed_and_is_checked(repository):
    words, stick = _words(), _request()
    job = json.loads(
        make_job([words, stick], repository=repository, framing="whole-body", seeds=[11, 23])
    )
    digests = [hashlib.sha256(raw).hexdigest() for raw in (words, stick)]
    # Seed-major: a stop still leaves every request drawn once.
    assert [(item["seed"], item["request_sha256"]) for item in job["items"]] == [
        (11, digests[0]),
        (11, digests[1]),
        (23, digests[0]),
        (23, digests[1]),
    ]
    assert job["stop"]["stop_at_seconds"] >= job["stop"]["estimate_seconds"] > 4 * 25
    with pytest.raises(Refused, match="needs a framing"):
        make_job([words], repository=repository, framing="side-on", seeds=[11])
    with pytest.raises(Refused, match="each seed once"):
        make_job([words], repository=repository, framing="whole-body", seeds=[11, 11])


def test_the_fit_of_a_run_keeps_each_request_s_first_passing_model(repository, tmp_path):
    words, stick, absent = _words(), _request(), _with_picture(_png())
    job = make_job([words, stick], repository=repository, framing="whole-body", seeds=[11, 23])
    pictures = tmp_path / "pictures"
    prepared = prepare_picture_job(
        job_raw=job, requests=[words, stick], pictures={}, repository=repository
    )
    results = run_picture_job(prepared, StandIn(), pictures)
    table, _ = read_table(repository)
    requests = {hashlib.sha256(raw).hexdigest(): raw for raw in (words, stick, absent)}
    out = tmp_path / "fits"
    document = fit_run(
        results=results,
        requests=requests,
        pictures=pictures,
        out=out,
        table=table,
        simplifier=cluster_simplify,
        made_by={"provider": "stand-in", "model_id": "stand-in"},
    )
    assert json.loads((out / "fits.json").read_bytes()) == document
    assert document["profile"] == FIT_RUN_PROFILE
    passed = document["requests"][hashlib.sha256(words).hexdigest()]
    # The first seed's model passed, so the second was never fitted.
    assert (passed["outcome"], passed["seed"]) == ("passed", 11)
    container = (out / "looks" / f"{passed['container_sha256']}.glb").read_bytes()
    assert hashlib.sha256(container).hexdigest() == passed["container_sha256"]
    receipt = json.loads((out / "receipts" / f"{passed['receipt_sha256']}.json").read_bytes())
    assert receipt["outcome"] == "passed" and receipt["output"]["height_mm"] == passed["height_mm"]
    # A body of one thickness everywhere is refused by the fit, by code, on both seeds.
    refused = document["requests"][hashlib.sha256(stick).hexdigest()]
    assert (refused["outcome"], refused["refusal"], refused["seed"]) == (
        "refused",
        "rig_chain_not_found",
        11,
    )
    assert document["requests"][hashlib.sha256(absent).hexdigest()] == {
        "outcome": "failed",
        "failure": "not_made",
    }
