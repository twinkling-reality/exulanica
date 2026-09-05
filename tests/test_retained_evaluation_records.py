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


_ANSWERS = "2026-09-04-semantic-answers-and-memory-lifecycle.json"


def _answers() -> dict:
    return json.loads((_ROOT / "docs" / "evaluation" / _ANSWERS).read_bytes())["record"]


def test_the_answer_record_is_bound_to_the_audit_that_set_its_gates():
    """A record that floated free of its predecessor could claim any starting point."""
    record = _answers()
    predecessor = record["predecessor_record"]
    assert predecessor["path"].endswith(_READINESS)
    audit = json.loads((_ROOT / predecessor["path"]).read_bytes())
    assert predecessor["record_sha256"] == hashlib.sha256(
        canonical_json(audit["record"])
    ).hexdigest()


def test_the_answer_record_names_its_corpus_and_publishes_no_accuracy():
    """The gate sentence: say which corpus produced any number, and do not pass plumbing off
    as accuracy.

    ``measured_accuracy`` is ``None`` rather than absent, and that is the assertion. A missing
    key reads as an oversight; an explicit null is the record saying there is none, and it is
    the one field a later reader would look for first.
    """
    record = _answers()
    assert record["corpus_class"] == "synthetic"
    assert record["corpus"]["personal_media_admitted"] is False
    assert record["corpus"]["ogc_1_present"] is False

    split = record["what_is_plumbing_and_what_is_accuracy"]
    assert "measured_accuracy" in split and split["measured_accuracy"] is None
    assert split["plumbing_exercised_against_a_real_server"]
    assert "FakeTransport" in split["faked_and_named"]["what"]
    assert "no hallucination rate" in split["faked_and_named"]["consequence"]

    disclaimers = " ".join(record["what_this_record_does_not_claim"])
    assert "No accuracy of any kind was measured" in disclaimers
    assert "no question set exists" in disclaimers
    assert "composed by a live model endpoint" in disclaimers


def test_the_answer_record_publishes_no_number_against_a_blocked_metric():
    """"No retrieval or accuracy number may be published against an OPEN evaluation item."

    Enforced against ``metrics.py`` rather than against a copied list, so a component that
    becomes runnable later does not leave this test asserting a stale set. Every metric whose
    ``blocked_on`` is set is one no number may be attached to, and the record's counts are
    keyed by gate rather than by metric precisely so none of them can be read as one.
    """
    from exulanica.evaluation.metrics import METRICS

    record = _answers()
    blocked = {f"{c.metric}.{c.key}" for c in METRICS if c.blocked_on is not None}
    assert {"M2.hallucination_rate", "M3.false_answer_rate", "M13.answer_latency"} <= blocked

    counts = json.dumps(record["counts"])
    for name in blocked:
        _metric, key = name.split(".", 1)
        assert key not in counts, f"the counts block names {name}, which is blocked"
    assert "not measurements of answer quality" in record["counts"]["what_these_are"]


def test_the_answer_record_discloses_what_it_left_vacuous_or_unreachable():
    """Four holes this goal found and did not fill, each recorded rather than tidied away.

    Every one of them is a thing a later reader would otherwise have to rediscover, and three
    are cases where the honest answer was to disclose rather than to build: giving
    NOT_IN_MODALITY a producer, giving mark_stale a synthetic producer, and giving an entity's
    withdrawal a second home in the identity ledger.
    """
    record = _answers()
    limitations = " ".join(record["known_limitations"])
    assert "Abstention.NOT_IN_MODALITY has no producer" in limitations
    assert "No answer is persisted" in limitations
    assert "Recomputation.mark_stale is vacuous over shipping producers" in limitations
    assert "not recorded in the ledger its creation is in" in limitations

    deferred = {item["item"] for item in record["intentionally_deferred"]}
    assert any("gold question set" in item for item in deferred)
    assert {item["id"] for item in record["still_open_after_this_goal"]} >= {"P-1", "A-8"}


def test_the_answer_record_says_the_biometric_pin_still_holds():
    """The entry gate the audit attached to this goal: the pin must stay pinned."""
    record = _answers()
    held = " ".join(record["entry_gates_held_throughout"])
    assert "absence of an embedding writer" in held
    assert record["counts"]["migrations_added"] == 0
    assert record["counts"]["historical_migrations_rewritten"] == 0
    assert record["counts"]["span_digests_changed"] == 0
