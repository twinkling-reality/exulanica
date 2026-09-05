"""Integrity and disclosure rules for retained machine-readable campaign evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exulanica.canonical import canonical_json

_ROOT = Path(__file__).resolve().parents[1]


def _records() -> list[Path]:
    return sorted((_ROOT / "docs" / "evaluation").glob("*.json"))


def test_every_retained_evaluation_record_reproduces_its_canonical_digest():
    paths = _records()
    assert paths, "no machine-readable evaluation record is retained"
    for path in paths:
        document = json.loads(path.read_bytes())
        assert document["profile"] == "exulanica.digest-bound-record/v1", path
        assert document["record_sha256"] == hashlib.sha256(
            canonical_json(document["record"])
        ).hexdigest(), path


def test_retained_evaluation_records_contain_no_personal_path_or_credential_material():
    for path in _records():
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text, path
        assert "Bearer " not in text, path
        assert "api-token" not in text, path


def test_depth_image_forward_record_does_not_claim_normal_worker_or_host_performance():
    path = _ROOT / "docs" / "evaluation" / "2026-09-04-linux-amd64-depth-forward.json"
    record = json.loads(path.read_bytes())["record"]
    assert record["corpus_class"] == "synthetic"
    assert record["execution"]["production_adapter"].endswith("MoGeDepthModel")
    assert record["execution"]["production_worker_orchestration"] is False
    assert any("do not represent a production host" in item for item in record["limitations"])


def test_retained_screenshots_match_the_artifact_bound_into_their_record():
    for path in _records():
        record = json.loads(path.read_bytes())["record"]
        screenshot = record.get("screenshot")
        if screenshot is None:
            continue
        image = path.parent / screenshot["path"]
        data = image.read_bytes()
        assert len(data) == screenshot["byte_size"], image
        assert hashlib.sha256(data).hexdigest() == screenshot["sha256"], image


_READINESS = "2026-09-04-readiness-and-architecture-audit.json"


def _readiness() -> dict:
    return json.loads((_ROOT / "docs" / "evaluation" / _READINESS).read_bytes())["record"]


def test_the_readiness_audit_is_bound_to_the_campaign_it_followed():
    """A readiness report that floated free of its predecessor could claim any starting point."""
    record = _readiness()
    predecessor = record["predecessor_record"]
    campaign = json.loads((_ROOT / predecessor["path"]).read_bytes())
    assert predecessor["record_sha256"] == hashlib.sha256(
        canonical_json(campaign["record"])
    ).hexdigest()


def test_the_readiness_audit_closes_the_eight_decisions_it_was_asked_to_close():
    record = _readiness()
    numbers = [decision["number"] for decision in record["decisions_closed"]]
    assert numbers == list(range(1, 9)), numbers
    for decision in record["decisions_closed"]:
        for field in ("name", "invariant", "rationale", "compatibility_impact",
                      "failure_behaviour", "affected_surfaces", "tests"):
            assert decision.get(field), (decision["number"], field)


def test_every_artefact_the_readiness_audit_names_exists():
    """A report citing a file that is not there is a report nobody can check."""
    record = _readiness()
    missing = []
    for decision in record["decisions_closed"]:
        candidates = list(decision["tests"])
        if decision.get("adr"):
            candidates.append(decision["adr"])
        for surface in decision["affected_surfaces"].values():
            candidates.extend(surface)
        for name in decision["affected_surfaces"]["migrations"]:
            candidates.append(f"exulanica/migrations/{name}")
        for relative in candidates:
            if "/" not in relative:
                continue
            if not (_ROOT / relative).exists():
                missing.append(relative)
    assert not missing, missing


def test_the_readiness_audit_does_not_claim_personal_media_or_a_measured_rung():
    """The one disclosure that matters most, asserted rather than trusted to review."""
    record = _readiness()
    limitations = " ".join(record["known_limitations"])
    assert "No personal media was admitted or evaluated at any point." in limitations
    assert "did not measure" in limitations
    open_ids = {item["id"] for item in record["remaining_open_invariants"]}
    assert "P-1" in open_ids and "A-8" in open_ids
    # The two rungs the campaign withheld are ordered after, not claimed.
    positions = {entry["goal"]: entry["position"] for entry in record["dependency_order"]}
    assert positions["Rung 2 corridor"] > positions["Semantic answers and memory lifecycle"]
    assert positions["A measured Rung 1 decision"] > positions["Rung 2 corridor"]


def test_every_subsequent_goal_has_both_gates():
    record = _readiness()
    goals = {entry["goal"] for entry in record["dependency_order"]}
    gated = {entry["goal"] for entry in record["subsequent_goal_gates"]}
    assert goals == gated, (goals ^ gated)
    for entry in record["subsequent_goal_gates"]:
        assert entry["entry_gates"], entry["goal"]
        assert entry["exit_gates"], entry["goal"]
