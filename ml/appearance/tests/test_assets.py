"""The stub route end to end: receipts the dry run writes, read back and refused when tampered.

The formats themselves are tested in the repository's tests (test_pieces_format.py,
test_pieces_geometry.py); this file holds what needs the appearance package's dry run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exulanica_pieces.budgets import read_budgets
from exulanica_pieces.canonical import Refused, canonical_bytes, sha256_hex
from exulanica_pieces.records import REGENERATION, read_receipt, read_request

from exulanica_appearance.assets.dryrun import (
    CASE_PATH,
    GRIP_SECTION_MM_MAXIMUM,
    case_bytes,
    dry_run,
)


def test_dry_run_receipts_read_back_and_refuse_tampering(repository: Path, tmp_path: Path) -> None:
    run = dry_run(repository, tmp_path)
    receipts = sorted((tmp_path / "receipts").glob("*.json"))
    requests = {
        sha256_hex(p.read_bytes()): read_request(p.read_bytes(), read_budgets(repository))
        for p in tmp_path.glob("request-*.json")
    }
    document = json.loads(receipts[0].read_bytes())
    request_of = requests[document["request_sha256"]]
    read_receipt(receipts[0].read_bytes(), request_of)
    assert document["regeneration"] == REGENERATION
    for change, match in (
        (
            {
                "verdict": {"over": [], "within": True},
                "measured": dict(document["measured"], triangles=10**6),
            },
            "verdict",
        ),
        ({"origin": "authored"}, "origin generated"),
        (
            {
                "postprocess": dict(
                    document["postprocess"], steps=document["postprocess"]["steps"][::-1]
                )
            },
            "in that order",
        ),
    ):
        with pytest.raises(Refused, match=match):
            read_receipt(canonical_bytes(dict(document, **change)), request_of)
    assert all(piece["within"] for piece in run["pieces"])
    assert len(run["pieces"]) == 7  # bench, lantern, sword, tree, car, shop door, picket fence


def test_the_hand_figure_is_the_body_plan_s() -> None:
    # THINGS's humanoid/v1 grip_section_mm_maximum, 60 mm (stated to GEN on 2026-10-06). Read from
    # the body plan catalog once it lands, and this copy goes.
    assert GRIP_SECTION_MM_MAXIMUM == 60


def test_a_held_receipt_refuses_a_changed_grip_measure(repository: Path, tmp_path: Path) -> None:
    dry_run(repository, tmp_path)
    budgets = read_budgets(repository)
    requests = {
        sha256_hex(p.read_bytes()): read_request(p.read_bytes(), budgets)
        for p in tmp_path.glob("request-*.json")
    }
    receipts = [p.read_bytes() for p in sorted((tmp_path / "receipts").glob("*.json"))]
    held = [
        (raw, requests[json.loads(raw)["request_sha256"]])
        for raw in receipts
        if "hold" in requests[json.loads(raw)["request_sha256"]]
    ]
    assert sorted(request["look_role"] for _, request in held) == ["prop.lantern", "prop.sword"]
    for raw, request in held:
        read_receipt(raw, request)
        document = json.loads(raw)
        wide = dict(document["measured"]["hold"], section_mm={"x_mm": 70, "y_mm": 8})
        changed = dict(document, measured=dict(document["measured"], hold=wide))
        with pytest.raises(Refused, match="verdict"):
            read_receipt(canonical_bytes(changed), request)
        bare = {k: v for k, v in document["measured"].items() if k != "hold"}
        with pytest.raises(Refused, match="exactly"):
            read_receipt(canonical_bytes(dict(document, measured=bare)), request)


def test_the_committed_case_is_what_the_dry_run_makes_now(repository: Path) -> None:
    fresh = json.loads(case_bytes(repository))
    committed = json.loads((repository / CASE_PATH).read_bytes())
    for document in (fresh, committed):
        document["receipt"].pop("seconds")  # the only figure a run measures by the clock
    assert committed == fresh, f"rewrite {CASE_PATH} with dryrun.case_bytes"


def test_the_trial_evidence_reads_strictly_and_its_run_record_names_every_receipt(
    repository: Path,
) -> None:
    """The first rented run's records, as the job wrote them (evidence/generated-assets-trial-1)."""
    from exulanica_pieces.records import read_job

    from exulanica_appearance.gpu_run import read_gpu_run

    root = repository / "ml/appearance/evidence/generated-assets-trial-1"
    budgets = read_budgets(repository)
    requests = {
        sha256_hex(p.read_bytes()): read_request(p.read_bytes(), budgets)
        for p in (root / "requests").glob("*.json")
    }
    job_raw = (root / "job-a.json").read_bytes()
    job = read_job(job_raw)
    assert job["route"] == "A" and len(job["items"]) == 16
    receipts = {}
    for path in (root / "receipts").glob("*.json"):
        document = json.loads(path.read_bytes())
        read_receipt(canonical_bytes(document), requests[document["request_sha256"]])
        assert path.stem == sha256_hex(path.read_bytes()) and document["job_sha256"] == sha256_hex(
            job_raw
        )
        receipts[path.stem] = document
    roles = sorted(requests[r["request_sha256"]]["look_role"] for r in receipts.values())
    assert roles.count("door.shopfront_bay") == 0 and len(roles) == 13
    within = [r for r in receipts.values() if r["verdict"]["within"]]
    assert len(within) == 11
    run = read_gpu_run(
        (repository / "ml/appearance/evidence/gpu-run-aijob-e05tkzsmaghtp23jvc.json").read_bytes()
    )
    assert run["generations"] == sorted(receipts)
