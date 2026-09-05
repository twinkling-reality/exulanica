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


def _numeric_fields(node, path=""):
    """Every (path, key, value) whose value is a number. Depth first; list members kept."""
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                yield here, key, value
            else:
                yield from _numeric_fields(value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _numeric_fields(value, f"{path}[{index}]")


def test_the_answer_record_publishes_no_number_against_a_blocked_metric():
    """"No retrieval or accuracy number may be published against an OPEN evaluation item."

    Enforced against ``metrics.py`` rather than against a copied list, so a component that
    becomes runnable later does not leave this test asserting a stale set.

    Over the WHOLE record rather than over its counts block, and that is not fussiness: the
    first version of this test read ``record["counts"]`` alone, which would have let a measured
    hallucination rate or a p50 latency published anywhere else in the same digest-bound
    document pass green.

    It walks numeric values rather than searching text, because the record's own disclosures
    name these metrics on purpose. "M2 hallucination_rate ... blocked_on 'no question set
    exists'" is the sentence the gate asks for; a substring scan would refuse the disclosure and
    permit the number, which is exactly backwards.
    """
    from exulanica.evaluation.metrics import METRICS

    record = _answers()
    blocked = {c.key for c in METRICS if c.blocked_on is not None}
    assert {"hallucination_rate", "false_answer_rate", "answer_latency"} <= blocked

    numbers = list(_numeric_fields(record))
    assert numbers, "a record with no numeric field would pass this vacuously"
    for path, key, value in numbers:
        assert key not in blocked, f"{path} = {value} is a number against a blocked metric"
    assert "not measurements of answer quality" in record["counts"]["what_these_are"]


def test_the_answer_records_counts_agree_with_each_other():
    """The record's own arithmetic, which is the error that actually happened.

    Its first two revisions each stated a tests_added figure that was five short, because the
    numbers were taken before the commit that retained them added its own tests. Nothing caught
    it: the per-gate breakdown summed to the wrong total and agreed with it.

    This does not re-run the suite, so it cannot tell whether 1480 is the true collection. It
    tells whether the three numbers the record derives from each other are consistent, which is
    what silently drifted.
    """
    counts = _answers()["counts"]
    added = counts["backend_collected_now"] - counts["backend_collected_at_starting_revision"]
    assert added == counts["backend_tests_added"], (
        f"{counts['backend_collected_now']} - "
        f"{counts['backend_collected_at_starting_revision']} is {added}, not "
        f"{counts['backend_tests_added']}"
    )
    assert sum(counts["tests_added_per_gate"].values()) == counts["backend_tests_added"]
    assert counts["backend_passed"] + counts["backend_skipped"] == counts["backend_collected_now"]


def test_the_answer_records_migration_counts_describe_the_repository():
    """The counts a reader would check first, checked against the tree rather than themselves.

    These three fields are the record saying it stayed inside the goal's constraints, and the
    first version of this test asserted them against the document's own literals, which a
    thirty-fifth migration would not have disturbed. The forward-only count is checked against
    the files; "not rewritten" is checked as "all thirty-four are still there", because the
    migration runner's checksums and Git are what hold the rest of that claim.
    """
    from exulanica.migrations import migrations

    record = _answers()
    versions = sorted(migration.version for migration in migrations())
    historical = [f"{n:04d}" for n in range(1, 35)]
    assert versions[: len(historical)] == historical, "a migration 0001-0034 is missing"
    assert len(versions) - len(historical) == record["counts"]["migrations_added"]
    assert record["counts"]["historical_migrations_rewritten"] == 0


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
    assert record["counts"]["span_digests_changed"] == 0


def test_the_answer_record_numbers_its_decisions_contiguously_and_states_all_five_fields():
    """Every decision carries the five things this project asks a decision to state.

    The contiguity check is the cheap half and it earns its place: this record was renumbered
    once while a decision was inserted mid-series, and a gap would read as a decision that was
    dropped rather than as a numbering slip.
    """
    record = _answers()
    numbers = [decision["number"] for decision in record["decisions"]]
    assert numbers == list(range(1, len(numbers) + 1)), numbers
    for decision in record["decisions"]:
        for field in (
            "name", "invariant", "rationale", "canonical_representation",
            "compatibility_impact", "failure_behaviour", "negative_control",
        ):
            assert decision.get(field), f"decision {decision['number']} has no {field}"
        assert decision["tests"], decision["number"]
        assert set(decision["affected_surfaces"]) == {
            "schema", "migrations", "workers", "evidence", "apis", "exports",
            "deletion_paths", "browser_consumers",
        }, decision["number"]


def test_every_artefact_the_answer_record_names_exists():
    """A record naming a test that does not exist is a record nobody can check."""
    record = _answers()
    for decision in record["decisions"]:
        for target in decision["tests"]:
            path, _, node = target.partition("::")
            assert (_ROOT / path).is_file(), target
            if node:
                assert node in (_ROOT / path).read_text(encoding="utf-8"), target
        for name in decision["affected_surfaces"]["migrations"]:
            assert (_ROOT / "exulanica" / "migrations" / name).is_file(), name
        for name in decision["affected_surfaces"]["apis"]:
            assert (_ROOT / name).is_file(), name


def test_the_answer_record_says_what_reviewing_it_found_and_what_it_did_not_fix():
    """A review that only records what it fixed is a review that hid what it did not.

    Two findings were deliberately left open, and both are pre-existing weaknesses this goal did
    not introduce. Recording them with their reasons is the difference between a decision and an
    omission.
    """
    record = _answers()
    findings = record["found_by_reviewing_this_goal"]
    assert len(findings) >= 5
    dispositions = [item["disposition"] for item in findings]
    assert any(d.startswith("FIXED") for d in dispositions)
    unfixed = [item for item in findings if item["disposition"].startswith("NOT FIXED")]
    assert unfixed, "a review of this size that found nothing it declined to fix is not a review"
    for item in unfixed:
        assert "disclosed" in item["disposition"]
        assert len(item["finding"]) > 60, "an undisclosed reason is not a disclosure"
