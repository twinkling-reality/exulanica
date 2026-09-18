"""The Track A runner: tiling arithmetic, relief conditioning, staging, the run, and the handover."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from exulanica_appearance.canonical import Refused, canonical_bytes, parse_canonical, sha256_hex
from exulanica_appearance.handoff import (
    PROCEDURAL_LAYOUT,
    build_candidate,
    check_projection,
    maker_generation,
    read_candidate,
)
from exulanica_appearance.look import (
    CROP_PX,
    build_look,
    crop_sheets,
    look_at_results,
    read_look,
)
from exulanica_appearance.runner import relief, tiling
from exulanica_appearance.runner.dry_run import dry_run
from exulanica_appearance.runner.job import generations, read_job, seed_for
from exulanica_appearance.runner.run import check_results, make_backend, run_job
from exulanica_appearance.runner.staging import verify_staged


def test_the_tiling_schedule_is_arithmetic_anyone_can_redo():
    assert tiling.shift_for_step(7, 0, 64, 64) == tiling.shift_for_step(7, 0, 64, 64)
    assert tiling.shift_for_step(7, 0, 64, 64) != tiling.shift_for_step(7, 1, 64, 64)
    assert tiling.shift_for_step(7, 0, 64, 64) != tiling.shift_for_step(8, 0, 64, 64)
    offsets = {tiling.shift_for_step(7, step, 8, 8) for step in range(200)}
    assert len(offsets) > 32, "the schedule should reach most of an 8 by 8 grid's offsets"
    for rows, columns in ((8, 8), (64, 40)):
        for step in range(50):
            row, column = tiling.shift_for_step(3, step, rows, columns)
            assert 0 <= row < rows and 0 <= column < columns


def test_rolling_and_wrapping_are_exactly_reversible():
    rng = np.random.default_rng(1)
    grid = rng.integers(0, 255, (9, 7, 3), dtype=np.uint8)
    shift = tiling.shift_for_step(5, 2, 9, 7)
    assert np.array_equal(tiling.unroll_grid(tiling.roll_grid(grid, shift), shift), grid)
    padded = tiling.wrap_pad(grid, 3)
    assert padded.shape == (15, 13, 3)
    assert np.array_equal(tiling.wrap_crop(padded, 3), grid)
    assert np.array_equal(padded[0, 3:-3], grid[-3])
    assert np.array_equal(padded[3:-3, -1], grid[:, 2])


def test_relief_pictures_come_from_the_height_map_and_wrap():
    height = np.zeros((8, 8, 1), dtype=np.uint8)
    height[2:6, 2:6] = 200
    height[0, :] = 200  # a raised row across the wrap
    depth = relief.relief_depth(height)
    assert depth.shape == (8, 8, 3)
    assert np.array_equal(depth[..., 0], height[..., 0])
    edges = relief.relief_edges(height)[..., 0]
    assert edges[1, 3] == 255, "the step from the raised row to the row below is an edge"
    assert edges[7, 3] == 255, "the step across the wrap is an edge too"
    assert edges[4, 4] == 0, "the middle of a flat patch is not"
    colour = np.zeros((4, 4, 3), dtype=np.uint8)
    colour[..., 1] = 100
    assert relief.relief_gray(colour)[0, 0, 0] == round(0.7152 * 100)


def _dry(tmp_path, repository) -> dict:
    return dry_run(repository, tmp_path / "dry")


def test_the_dry_run_stages_runs_checks_and_refuses(tmp_path, repository):
    summary = _dry(tmp_path, repository)
    assert set(summary["refusals"]) == {
        "an unlisted file in the staged directory",
        "a weights file changed after its manifest was written",
    }
    assert "not-listed.png" in summary["refusals"]["an unlisted file in the staged directory"]
    assert (
        "git blob" in summary["refusals"]["a weights file changed after its manifest was written"]
    )
    results = summary["summary"]
    # One target, two conditioning roles, two seeds, one candidate.
    assert len(results["generations"]) == 4
    assert results["stopped"] == ""
    assert {item["role"] for item in results["generations"]} == {"depth", "edge"}
    assert len({item["seed"] for item in results["generations"]}) == 4
    assert all(item["seconds"] >= 0 for item in results["generations"])
    assert results["verified_weights"][0]["bytes"] > 0


def test_the_seed_rule_and_the_generation_order_are_the_job_s(tmp_path, repository):
    _dry(tmp_path, repository)
    job = read_job((tmp_path / "dry" / "staged" / "job.json").read_bytes())
    listed = list(generations(job))
    assert [(g.target["id"], g.candidate["id"], g.role, g.index) for g in listed] == [
        ("brick-weathered", "stub", "depth", 0),
        ("brick-weathered", "stub", "depth", 1),
        ("brick-weathered", "stub", "edge", 0),
        ("brick-weathered", "stub", "edge", 1),
    ]
    assert listed[0].seed == seed_for("track-a-dry-run", "brick-weathered", "stub", "depth", 0)


def test_a_record_names_its_model_by_id_revision_and_digest(tmp_path, repository):
    summary = _dry(tmp_path, repository)
    record_path = (
        tmp_path
        / "dry"
        / "run"
        / "records"
        / f"{summary['summary']['generations'][0]['record_sha256']}.json"
    )
    record = parse_canonical(record_path.read_bytes(), "the record")
    (component,) = record["components"]
    assert component["id"] == "exulanica/stub-appearance-model"
    assert component["revision"] == "0" * 40
    assert record["guardrails"] == {"enabled": False}
    assert "no people" in record["reasons"]["guardrails"]
    assert record["track"] == "texture"
    assert record["conditioning"][0]["sources"] == [
        json.loads((repository / "assets" / "textures" / "manifest.json").read_bytes())["sets"][0][
            "content_sha256"
        ]
    ]


def test_a_changed_output_is_refused_when_the_results_are_checked(tmp_path, repository):
    summary = _dry(tmp_path, repository)
    out = tmp_path / "dry" / "run"
    assert check_results(out)["job_sha256"]
    first = summary["summary"]["generations"][0]["output_sha256"]
    path = out / "outputs" / f"{first}.rgb"
    raw = bytearray(path.read_bytes())
    raw[0] ^= 1
    path.write_bytes(bytes(raw))
    with pytest.raises(Refused, match="does not match its record"):
        check_results(out)


def test_a_run_stops_before_it_passes_its_stop(tmp_path, repository):
    _dry(tmp_path, repository)
    staged = tmp_path / "dry" / "staged"
    weights = tmp_path / "dry" / "weights"
    calls = iter(range(10_000))

    def clock() -> float:
        # Verification and the first generation happen at once; then the run is deep into its stop.
        return 0.0 if next(calls) < 6 else 1000.0

    results = parse_canonical(
        run_job(
            staged=staged,
            weights_root=weights,
            out=tmp_path / "stopped",
            backend_factory=make_backend,
            code_commit="0" * 40,
            container_image=f"stub@sha256:{'0' * 64}",
            elapsed=clock,
            log=lambda _: None,
        ),
        "the results",
    )
    assert results["stopped"].startswith("stopped before generation")
    assert len(results["generations"]) < 4


def test_staging_refuses_a_file_it_did_not_write(tmp_path, repository):
    _dry(tmp_path, repository)
    staged = tmp_path / "dry" / "staged"
    manifest, _ = verify_staged(staged)
    changed = staged / manifest["files"][0]["path"]
    kept = changed.read_bytes()
    changed.write_bytes(kept + b"\0")
    with pytest.raises(Refused, match="listed size and sha256"):
        verify_staged(staged)
    changed.write_bytes(kept)
    edited = dict(manifest)
    edited["job_sha256"] = "0" * 64
    (staged / "staged.json").write_bytes(canonical_bytes(edited))
    with pytest.raises(Refused, match="job.json is not the job"):
        verify_staged(staged)


def _record(tmp_path, repository) -> bytes:
    summary = _dry(tmp_path, repository)
    digest = summary["summary"]["generations"][0]["record_sha256"]
    return (tmp_path / "dry" / "run" / "records" / f"{digest}.json").read_bytes()


def test_the_maker_block_states_each_map_s_source(tmp_path, repository):
    record_raw = _record(tmp_path, repository)
    recipe = "c" * 64
    block = maker_generation(
        record_raw, recipe_sha256=recipe, material_class="opaque", model_made=["base_color"]
    )
    assert tuple(block["map_sources"]) == PROCEDURAL_LAYOUT["opaque"]
    assert block["map_sources"]["base_color"] == {"generation_sha256": sha256_hex(record_raw)}
    assert block["map_sources"]["normal"] == {"recipe_sha256": recipe}
    assert block["map_sources"]["orm"] == {"recipe_sha256": recipe}
    assert [model["role"] for model in block["models"]] == ["base"]
    assert block["models"][0]["id"] == "exulanica/stub-appearance-model"
    check_projection(block, record_raw)
    with pytest.raises(Refused, match="not the record's"):
        check_projection({**block, "seed": 1}, record_raw)
    with pytest.raises(Refused, match="layout"):
        maker_generation(
            record_raw, recipe_sha256=recipe, material_class="opaque", model_made=["height"]
        )


def test_a_candidate_carries_cc0_with_its_three_statements(tmp_path, repository):
    record_raw = _record(tmp_path, repository)
    look = "d" * 64
    raw = build_candidate(
        record_raw=record_raw,
        material_class="opaque",
        model_made=["base_color"],
        source_set={
            "content_sha256": "e" * 64,
            "recipe_sha256": "c" * 64,
            "set_id": "cc0.brick-running-bond",
            "version": 1,
        },
        maps={"base_color": {"height": 1024, "sha256": "f" * 64, "width": 1024}},
        measurements={"seams_ppm": {"u": 1000000, "v": 1000000}},
        licence_ids=["Apache-2.0", "OpenMDW-1.1"],
        third_party_look_sha256=look,
    )
    candidate = read_candidate(raw)
    assert candidate["licence"]["id"] == "CC0-1.0"
    assert len(candidate["licence"]["statements"]) == 3
    assert "no condition on what a model's output" in candidate["licence"]["statements"][0]
    assert "lane's reading" in candidate["licence"]["statements"][1]
    assert look in candidate["licence"]["statements"][2]
    with pytest.raises(Refused, match="every map has been looked at"):
        build_candidate(
            record_raw=record_raw,
            material_class="opaque",
            model_made=["base_color"],
            source_set={
                "content_sha256": "e" * 64,
                "recipe_sha256": "c" * 64,
                "set_id": "x",
                "version": 1,
            },
            maps={},
            measurements={},
            licence_ids=["Apache-2.0"],
            third_party_look_sha256="not a digest",
        )


def test_a_run_writes_where_the_latent_stood_out_beside_each_output(tmp_path, repository):
    from exulanica_appearance.metrics.latents import LINE_SIGMA_MILLI, latent_lines

    summary = _dry(tmp_path, repository)
    written = sorted((tmp_path / "dry" / "run" / "diagnostics").glob("*.json"))
    assert len(written) == len(summary["summary"]["generations"])
    document = parse_canonical(written[0].read_bytes(), "the latent lines")
    assert document["profile"] == "exulanica.appearance-latent-lines/v1"
    # The stub's grid is its own and says so, so no reader mistakes it for a model's latent.
    assert document["source"] == "stub-grid"
    assert document["output_sha256"] == written[0].stem
    assert set(document["row"]) == {"beyond_threshold", "index", "sigma_milli", "spread_milli"}

    # A planted line is found at its own index, and a level latent reports nothing beyond it.
    rng = np.random.default_rng(11)
    values = rng.standard_normal((4, 64, 64))
    level = latent_lines(values, source="test")
    assert level["row"]["beyond_threshold"] == 0
    values[:, 37, :] -= 40
    found = latent_lines(values, source="test")
    assert found["row"]["index"] == 37
    assert abs(found["row"]["sigma_milli"]) >= LINE_SIGMA_MILLI
    assert found["row"]["beyond_threshold"] == 1
    assert found["column"]["beyond_threshold"] == 0
    with pytest.raises(Refused, match="channels by rows by columns"):
        latent_lines(values[0], source="test")
    with pytest.raises(Refused, match="says what it was taken from"):
        latent_lines(values, source="")


def test_the_look_covers_every_texel_or_it_is_not_a_look(tmp_path):
    rng = np.random.default_rng(2)
    maps = {
        "base_color": rng.integers(0, 255, (CROP_PX, CROP_PX + 8, 3), dtype=np.uint8),
        "orm": rng.integers(0, 255, (CROP_PX, CROP_PX, 3), dtype=np.uint8),
    }
    crops = crop_sheets(maps, tmp_path / "crops")
    assert len(crops) == 3
    assert all((tmp_path / "crops" / crop["file"]).is_file() for crop in crops)
    raw = build_look(
        output_sha256="a" * 64,
        crops=crops,
        maps={name: (pixels.shape[0], pixels.shape[1]) for name, pixels in maps.items()},
        found="brick faces, joints and grime; no lettering, no logo, no mark",
        suspected=[],
        looked_on="2026-09-17",
        looked_by="the generated appearance lane",
    )
    assert read_look(raw)["crops"][0]["map"] == "base_color"
    document = parse_canonical(raw, "the look")
    with pytest.raises(Refused, match="every texel is looked at"):
        read_look(canonical_bytes({**document, "crops": document["crops"][:1]}))
    with pytest.raises(Refused, match="an empty finding is not a finding"):
        read_look(canonical_bytes({**document, "found": ""}))


def test_the_session_look_reads_the_run_and_refuses_bytes_it_cannot_pin(tmp_path):
    rng = np.random.default_rng(5)
    pixels = rng.integers(0, 255, (CROP_PX, CROP_PX, 3), dtype=np.uint8)
    raw = pixels.tobytes()
    digest = sha256_hex(raw)
    results = tmp_path / "out"
    (results / "records").mkdir(parents=True)
    (results / "outputs").mkdir(parents=True)
    (results / "outputs" / f"{digest}.rgb").write_bytes(raw)
    (results / "records" / f"{'b' * 64}.json").write_bytes(
        canonical_bytes(
            {
                "outputs": [
                    {
                        "byte_length": len(raw),
                        "media_type": "application/vnd.exulanica.rgb8",
                        "role": "base-color",
                        "sha256": digest,
                    }
                ],
                "sampler": {"height": CROP_PX, "width": CROP_PX},
            }
        )
    )
    pick = {
        "found": "brick faces, joints and grime; no lettering, no logo, no mark",
        "name": "brick-a1",
        "output_sha256": digest,
        "suspected": ["a straight dashed line I cannot explain; the operator decides"],
    }
    findings = {
        "looked_by": "the generated appearance lane",
        "looked_on": "2026-09-17",
        "picks": [pick],
    }
    places = {"crops_root": tmp_path / "look", "records_root": tmp_path / "records"}
    looked = look_at_results(findings=findings, results=results, **places)
    assert looked[0]["crops"] == 1
    assert looked[0]["suspected"] == 1
    record = read_look((tmp_path / "records" / "brick-a1.json").read_bytes())
    # The size and the map's name come from the generation record, never from the findings file.
    assert record["maps"] == {"base_color": {"height": CROP_PX, "width": CROP_PX}}
    assert record["crops"][0]["pixels_sha256"] == sha256_hex(raw)
    assert (tmp_path / "look" / "brick-a1" / "contact-sheet.png").is_file()
    unpinned = {**findings, "picks": [{**pick, "output_sha256": "c" * 64}]}
    with pytest.raises(Refused, match="which no record"):
        look_at_results(findings=unpinned, results=results, **places)
    (results / "outputs" / f"{digest}.rgb").write_bytes(bytes(len(raw)))
    with pytest.raises(Refused, match="are not the bytes its record pins"):
        look_at_results(findings=findings, results=results, **places)


def test_the_session_findings_file_names_every_pick_in_words(repository):
    findings = json.loads((repository / "ml/appearance/look/session-1-findings.json").read_bytes())
    assert len(findings["picks"]) == 8
    for pick in findings["picks"]:
        assert set(pick) == {
            "candidate",
            "found",
            "name",
            "output_sha256",
            "role",
            "seed",
            "suspected",
            "target",
        }
        assert pick["name"] == f"{pick['target']}-{pick['candidate']}"
        assert len(pick["found"]) > 120, pick["name"]
        # Every finding says whether it found a mark, because that is what the look is for.
        assert "lettering" in pick["found"], pick["name"]
    names = [pick["name"] for pick in findings["picks"]]
    assert len(set(names)) == len(names)


def test_the_committed_job_specs_stage_and_read(tmp_path, repository):
    from exulanica_appearance.runner.staging import stage_texture_job

    weights = {}
    for path in sorted((Path(__file__).resolve().parents[1] / "weights").glob("*.json")):
        if path.name == "candidates.json":
            continue
        raw = path.read_bytes()
        weights[sha256_hex(raw)] = raw
    for name in ("track-a-smoke", "track-a-session-1"):
        spec = json.loads(
            (Path(__file__).resolve().parents[1] / "jobs" / f"{name}.json").read_bytes()
        )
        manifest = stage_texture_job(
            repository=repository, job=spec, weights_manifests=weights, out=tmp_path / name
        )
        staged_manifest, job = verify_staged(tmp_path / name)
        assert sha256_hex(manifest) == sha256_hex(canonical_bytes(staged_manifest))
        assert job["name"] == name
        assert all(target["recipe_sha256"] for target in job["targets"])
        expected = (
            len(job["targets"])
            * len(job["candidates"])
            * job["seeds_per_target"]
            * len(job["targets"][0]["conditioning"])
        )
        assert len(list(generations(job))) == expected


def _smoke(tmp_path, repository):
    """A finished stub run, and everything the gate reads about it."""
    summary = _dry(tmp_path, repository)
    out = tmp_path / "dry" / "run"
    results_raw = (out / "results.json").read_bytes()
    job = read_job((tmp_path / "dry" / "staged" / "job.json").read_bytes())
    records = {
        item["record_sha256"]: (out / "records" / f"{item['record_sha256']}.json").read_bytes()
        for item in summary["summary"]["generations"]
    }
    return results_raw, job, records


def test_the_smoke_gate_refuses_a_stub_run_because_it_did_not_run_on_a_gpu(tmp_path, repository):
    from exulanica_appearance.runner.gate import CHECKS, read_gate, smoke_gate

    results_raw, job, records = _smoke(tmp_path, repository)
    gate = read_gate(
        smoke_gate(
            results_raw=results_raw,
            job=job,
            records=records,
            billed_seconds=1200,
            budget_seconds=5400,
            rate_cents_per_hour=263,
        )
    )
    assert tuple(sorted(gate["checks"])) == CHECKS
    assert gate["continue"] is False, "the stub is not an NVIDIA device, so no_fallback must fail"
    assert gate["checks"]["no_fallback"]["passed"] is False
    assert "stub backend" in gate["checks"]["no_fallback"]["detail"]
    for name in (
        "backends_loaded",
        "no_refusal",
        "outputs_decoded_at_size",
        "seam_ratio_computed",
        "seconds_within_estimate",
        "spend_within_budget",
    ):
        assert gate["checks"][name]["passed"] is True, name


def _gpu_records(records: dict[str, bytes]) -> dict[str, bytes]:
    """The same records as if they had run on the card, so the other checks can be exercised."""
    out = {}
    for digest, raw in records.items():
        document = parse_canonical(raw, "the record")
        document["runtime"] = {
            **document["runtime"],
            "cuda": "12.8",
            "hardware": "NVIDIA RTX PRO 6000 Blackwell, 103079215104 bytes",
        }
        out[digest] = canonical_bytes(document)
    return out


def test_the_smoke_gate_passes_a_run_that_holds_every_condition(tmp_path, repository):
    from exulanica_appearance.runner.gate import read_gate, smoke_gate

    results_raw, job, records = _smoke(tmp_path, repository)
    gate = read_gate(
        smoke_gate(
            results_raw=results_raw,
            job=job,
            records=_gpu_records(records),
            billed_seconds=1200,
            budget_seconds=5400,
            rate_cents_per_hour=263,
        )
    )
    assert gate["continue"] is True
    assert all(entry["passed"] for entry in gate["checks"].values())
    assert gate["checks"]["spend_within_budget"]["detail"].startswith("1200 s billed")


@pytest.mark.parametrize(
    "name, change",
    [
        ("spend_within_budget", lambda kwargs: kwargs.update(billed_seconds=9000)),
        ("no_refusal", lambda kwargs: kwargs.update(results_raw=_stopped(kwargs["results_raw"]))),
        (
            "seam_ratio_computed",
            lambda kwargs: kwargs.update(results_raw=_without_seams(kwargs["results_raw"])),
        ),
        (
            "seconds_within_estimate",
            lambda kwargs: kwargs.update(results_raw=_slow(kwargs["results_raw"])),
        ),
        (
            "backends_loaded",
            lambda kwargs: kwargs.update(results_raw=_one_candidate_missing(kwargs["results_raw"])),
        ),
    ],
)
def test_each_pass_condition_can_fail(tmp_path, repository, name, change):
    from exulanica_appearance.runner.gate import read_gate, smoke_gate

    results_raw, job, records = _smoke(tmp_path, repository)
    kwargs = {
        "results_raw": results_raw,
        "job": job,
        "records": _gpu_records(records),
        "billed_seconds": 1200,
        "budget_seconds": 5400,
        "rate_cents_per_hour": 263,
    }
    change(kwargs)
    gate = read_gate(smoke_gate(**kwargs))
    assert gate["continue"] is False
    assert gate["checks"][name]["passed"] is False, gate["checks"][name]["detail"]


def _edit_results(raw: bytes, change) -> bytes:
    document = parse_canonical(raw, "the results")
    change(document)
    return canonical_bytes(document)


def _stopped(raw: bytes) -> bytes:
    return _edit_results(
        raw, lambda d: d.update(stopped="stopped before generation 2: out of time")
    )


def _without_seams(raw: bytes) -> bytes:
    return _edit_results(raw, lambda d: d["generations"][0].update(seams_ppm={"u": 1000000}))


def _slow(raw: bytes) -> bytes:
    return _edit_results(raw, lambda d: d["generations"][0].update(seconds=99))


def _one_candidate_missing(raw: bytes) -> bytes:
    return _edit_results(raw, lambda d: d.update(generations=[]))
