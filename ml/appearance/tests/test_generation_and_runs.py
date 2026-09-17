"""A generation record gives a reason for every fixed value; a run record holds its own arithmetic."""

from __future__ import annotations

import pytest

from exulanica_appearance.canonical import Refused, canonical_bytes, parse_canonical
from exulanica_appearance.generation import (
    REGENERATION,
    build_generation,
    components_sha256,
    read_generation,
)
from exulanica_appearance.gpu_run import (
    AUTHORITATIVE,
    build_gpu_run,
    cost_microdollars,
    ledger_line,
    read_gpu_run,
)


def _generation(**changes):
    document = {
        "code": {"commit": "c" * 40, "source_sha256": "d" * 64},
        "components": [
            {
                "id": "Qwen/Qwen-Image-2512",
                "revision": "a" * 40,
                "role": "transformer",
                "subfolder": "",
                "weights_sha256": "1" * 64,
            },
            {
                "id": "alibaba-pai/Qwen-Image-2512-Fun-Controlnet-Union",
                "revision": "b" * 40,
                "role": "control",
                "subfolder": "",
                "weights_sha256": "2" * 64,
            },
        ],
        "conditioning": [
            {
                "encoding": "inverse-depth-v1",
                "file_sha256": "3" * 64,
                "parameters": {"far_um": 60000000, "near_um": 500000},
                "pixels_sha256": "4" * 64,
                "role": "depth",
                "sources": ["5" * 64],
            },
        ],
        "container": {"image": "localhost:5000/exulanica-appearance@sha256:" + "6" * 64},
        "finished_at": "2026-09-18T12:05:00Z",
        "generated": True,
        "guardrails": {"enabled": False},
        "inputs": {"prompt": "a red brick wall with a limestone plinth and a recessed metal door"},
        "outputs": [
            {"byte_length": 1234, "media_type": "image/png", "role": "frame", "sha256": "7" * 64}
        ],
        "profile": "exulanica.appearance-generation/v1",
        "reasons": {
            "components.control": "the union control trained for this base",
            "components.transformer": "the accepted base model",
            "conditioning.depth": "exact depth, the structure the look must keep",
            "container": "the pinned image the lane built",
            "guardrails": "the licence has no guardrail clause and the inputs are synthetic structure with no people",
            "inputs": "the catalog labels of the surfaces in view",
            "sampler.guidance_milli": "the model card's default guidance",
            "sampler.name": "the scheduler the pipeline ships",
            "sampler.steps": "the model card's default step count",
            "seed": "the first of eight fixed seeds",
        },
        "runtime": {
            "cuda": "12.8",
            "driver": "580.126.09",
            "hardware": "NVIDIA RTX PRO 6000 Blackwell 96 GB",
            "libraries": [
                {"name": "diffusers", "version": "0.37.1"},
                {"name": "torch", "version": "2.14.0"},
            ],
        },
        "sampler": {"guidance_milli": 4000, "name": "flow-match-euler", "steps": 50},
        "seed": 2026091801,
        "started_at": "2026-09-18T12:00:00Z",
        "track": "frames",
        "truth": "invented",
    }
    document.update(changes)
    return document


def test_a_complete_record_builds_and_names_its_components_by_one_digest():
    raw = build_generation(_generation())
    document = read_generation(raw)
    assert [c["role"] for c in document["components"]] == ["control", "transformer"]
    assert document["components_sha256"] == components_sha256(
        list(reversed(document["components"]))
    )
    assert document["regeneration"] == REGENERATION
    assert "never a replay" in REGENERATION


def _mutated(change):
    document = parse_canonical(build_generation(_generation()), "test")
    change(document)
    return canonical_bytes(document)


@pytest.mark.parametrize(
    "change, words",
    [
        (lambda d: d["reasons"].pop("sampler.steps"), "missing \\['sampler.steps'\\]"),
        (lambda d: d["reasons"].pop("guardrails"), "missing \\['guardrails'\\]"),
        (
            lambda d: d["reasons"].update({"sampler.eta": "unused"}),
            "unexpected \\['sampler.eta'\\]",
        ),
        (lambda d: d["sampler"].update(shift=3), "missing \\['sampler.shift'\\]"),
        (lambda d: d.pop("guardrails"), "has exactly"),
        (lambda d: d["guardrails"].update(enabled="off"), "true or false"),
        (lambda d: d["container"].update(image="exulanica-appearance:latest"), "pinned by sha256"),
        (lambda d: d.update(components_sha256="0" * 64), "components_sha256"),
        (lambda d: d.update(regeneration="a replay"), "never a replay"),
        (lambda d: d.update(truth="observed"), "never evidence"),
        (lambda d: d.update(seed=2**32), "unsigned 32-bit"),
        (lambda d: d.update(finished_at="2026-09-18T11:00:00Z"), "not before"),
        (lambda d: d["conditioning"][0].update(sources=[]), "came from"),
        (lambda d: d["code"].update(commit="HEAD"), "40-hex commit"),
        (lambda d: d["components"][0].pop("id"), "has exactly"),
        (lambda d: d["components"][0].update(revision="main"), "repository id and 40-hex revision"),
    ],
)
def test_the_generation_reader_refuses_a_record_out_of_shape(change, words):
    with pytest.raises(Refused, match=words):
        read_generation(_mutated(change))


def _run(**changes):
    document = {
        "deleted_at": "2026-09-18T14:30:00Z",
        "estimate_seconds": 8 * 3600,
        "generations": ["b" * 64, "a" * 64],
        "gpu": "NVIDIA RTX PRO 6000 Blackwell 96 GB",
        "gpu_count": 1,
        "hard_deadline_at": "2026-09-18T16:00:00Z",
        "instance_name": "exulanica-appearance-a1",
        "instance_type": "massedcompute_RTXPRO6000",
        "over_estimate_reason": "",
        "profile": "exulanica.appearance-gpu-run/v1",
        "provider": "MassedCompute via Shadeform on NVIDIA Brev",
        "purpose": "track A texture candidates",
        "rate_cents_per_hour": 263,
        "rate_source": "Brev console listing, read 2026-09-17",
        "started_at": "2026-09-18T12:00:00Z",
    }
    document.update(changes)
    return document


def test_a_run_record_computes_seconds_cost_and_stop():
    document = read_gpu_run(build_gpu_run(_run()))
    assert document["billed_seconds"] == 9000
    assert document["cost_microdollars"] == 6_575_000
    assert document["stop_at_seconds"] == 43_200
    assert document["generations"] == ["a" * 64, "b" * 64]
    assert document["authoritative_total"] == AUTHORITATIVE
    assert cost_microdollars(263, 1) == 731


def test_the_ledger_line_names_the_instance_both_instants_and_the_cost():
    line = ledger_line(build_gpu_run(_run()))
    assert "exulanica-appearance-a1" in line
    assert "2026-09-18T12:00:00Z" in line and "2026-09-18T14:30:00Z" in line
    assert "deadline 2026-09-18T16:00:00Z" in line
    assert "$6.58" in line and "263 cents/h" in line


def test_a_deadline_before_the_start_is_refused():
    with pytest.raises(Refused, match="hard_deadline_at is after started_at"):
        build_gpu_run(_run(hard_deadline_at="2026-09-18T11:00:00Z"))


def test_a_run_past_its_stop_must_say_why():
    with pytest.raises(Refused, match="passed its stop"):
        build_gpu_run(_run(estimate_seconds=3600))
    document = read_gpu_run(
        build_gpu_run(
            _run(estimate_seconds=3600, over_estimate_reason="weights download took 70 minutes")
        )
    )
    assert document["billed_seconds"] > document["stop_at_seconds"]


@pytest.mark.parametrize(
    "change, words",
    [
        (lambda d: d.update(cost_microdollars=1), "rounded up"),
        (lambda d: d.update(billed_seconds=1), "interval"),
        (lambda d: d.update(stop_at_seconds=1), "150 per cent"),
        (lambda d: d.update(authoritative_total="our own sum"), "billing page"),
        (lambda d: d.update(instance_name=""), "printable ASCII"),
        (lambda d: d.update(hard_deadline_at="soon"), "UTC instant"),
    ],
)
def test_the_run_reader_refuses_edited_arithmetic(change, words):
    document = parse_canonical(build_gpu_run(_run()), "test")
    change(document)
    with pytest.raises(Refused, match=words):
        read_gpu_run(canonical_bytes(document))


def test_a_ceiling_buys_whole_seconds_and_never_one_more():
    from exulanica_appearance.gpu_run import ceiling_seconds

    # $25 at $2.63 an hour, floored so a run cannot pass the ceiling by a second.
    assert ceiling_seconds(2500, 263) == 34_220
    assert cost_microdollars(263, ceiling_seconds(2500, 263)) <= 25_000_000
    assert cost_microdollars(263, ceiling_seconds(2500, 263) + 1) > 25_000_000
    assert ceiling_seconds(0, 263) == 0
    with pytest.raises(Refused, match="a ceiling is not negative"):
        ceiling_seconds(-1, 263)


def test_the_documented_section_says_what_a_person_needs_later():
    from exulanica_appearance.gpu_run import document_section

    section = document_section(
        build_gpu_run(_run()),
        balance_before_cents=4031,
        balance_after_cents=3373,
        consent="accepted by the operator in the Brev console, MassedCompute named on the Deploy dialog",
        produced=["2 generation records, outputs 9da27a6c and 0fc3b490"],
        taught=["the first build failed on a missing apt package, which cost 4 minutes"],
    )
    assert "| Instance name | `exulanica-appearance-a1` |" in section
    assert "| Rate read that day | $2.63 per hour" in section
    assert "| Created | 2026-09-18T12:00:00Z |" in section
    assert "| Deleted | 2026-09-18T14:30:00Z |" in section
    assert "| Billed | 9000 s (2.50 h) |" in section
    assert "| Cost at the listed rate | $6.58 |" in section
    assert "| Prepaid balance before | $40.31 |" in section
    assert "| Prepaid balance after | $33.73 |" in section
    assert "accepted by the operator" in section
    assert "the first build failed" in section
    with pytest.raises(Refused, match="what it taught"):
        document_section(
            build_gpu_run(_run()),
            balance_before_cents=4031,
            balance_after_cents=3373,
            consent="accepted",
            produced=["nothing"],
            taught=[],
        )
