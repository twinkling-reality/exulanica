"""Integrity and disclosure rules for retained machine-readable campaign evidence."""

from __future__ import annotations

import hashlib
import json
import warnings
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
        assert (
            document["record_sha256"]
            == hashlib.sha256(canonical_json(document["record"])).hexdigest()
        ), path


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


def _bound_images(record: dict) -> list[dict]:
    """Every image a record binds, whether it binds one or a gallery.

    ``screenshot`` was the whole vocabulary while every record retained a single image. The Phase
    10 Atlas record binds eleven under ``captures``, and the first version of this test checked
    only ``screenshot``: ten of those eleven could have been replaced with any other bytes and the
    suite would have stayed green, which makes a digest-bound gallery no better than a folder of
    pictures. Both shapes are collected here so a record cannot escape the check by binding more.
    """
    bound = []
    screenshot = record.get("screenshot")
    if screenshot is not None:
        bound.append(screenshot)
    for capture in record.get("captures", []):
        if isinstance(capture, dict) and {"path", "byte_size", "sha256"} <= set(capture):
            bound.append(capture)
    return bound


def _bound_artifact(record_path: Path, relative: str) -> Path:
    """Resolve a bound path under either convention the retained records actually use.

    ``screenshot`` paths are relative to ``docs/evaluation`` and the 2026-09-05 reconstruction
    record's ``captures`` paths are relative to the repository root. Both are in the tree and
    neither is going to be rewritten, because rewriting one would change a digest that is bound
    into a record about a run that already happened. So this resolves either rather than declaring
    one of them wrong after the fact.
    """
    for candidate in (record_path.parent / relative, _ROOT / relative):
        if candidate.is_file():
            return candidate
    raise AssertionError(f"{record_path.name} binds {relative}, which is in neither location")


def test_retained_screenshots_match_the_artifact_bound_into_their_record():
    checked = 0
    for path in _records():
        record = json.loads(path.read_bytes())["record"]
        for image_ref in _bound_images(record):
            image = _bound_artifact(path, image_ref["path"])
            data = image.read_bytes()
            assert len(data) == image_ref["byte_size"], image
            assert hashlib.sha256(data).hexdigest() == image_ref["sha256"], image
            checked += 1
    # A binding nobody checks is a claim nobody can check. If this ever falls to zero, the rule
    # above has stopped applying to anything rather than having nothing to apply to.
    assert checked > 0, "no retained record binds an image"


def _declared_predecessors(record: dict) -> list[tuple[str, dict]]:
    """Every predecessor a record declares, whether it declares one or several.

    Two shapes are in the tree and both are load bearing (MEASURED 2026-09-07: 12 records declare
    the singular ``predecessor_record``, 2 declare the plural ``predecessor_records``, and the two
    plural ones are the records that followed two goals rather than one:
    2026-09-05-real-reconstruction follows retained-reference-progress and
    source-presentation-correction, 2026-09-05-scene-publication follows placement-alignment and
    gsplat-trainer-verification). Reading only the singular key would check 12 of the 16 declared
    bindings while calling itself universal, which is worse than checking two by name, because a
    rule that names its own scope wrongly stops anyone looking again.

    Only the top level of the record is read. ``counts`` carries a prose field whose NAME contains
    "predecessor_record"; a key search rather than these two exact keys would pick up a sentence
    and try to resolve it as a path.
    """
    declared: list[tuple[str, dict]] = []
    single = record.get("predecessor_record")
    if single is not None:
        declared.append(("predecessor_record", single))
    for entry in record.get("predecessor_records", []):
        declared.append(("predecessor_records", entry))
    return declared


def test_every_declared_predecessor_binding_resolves_and_matches():
    """The chain arithmetic, once, over every record that declares a link.

    This replaced two by-name checks over two records. A record's predecessor binding is the only
    thing that fixes what it was measured against: without it a report can silently be re-parented
    onto a more flattering starting point, and the digest is what stops the predecessor itself
    being edited after the fact.

    Resolution is strict repository-root relative, unlike ``_bound_artifact`` above, which has to
    tolerate two conventions for images. MEASURED 2026-09-07: all 16 declared predecessor paths
    begin with ``docs/evaluation/`` and are root relative, so a second convention here would be a
    new mistake rather than history.
    """
    checked = 0
    for path in _records():
        record = json.loads(path.read_bytes())["record"]
        for key, declared in _declared_predecessors(record):
            predecessor = _ROOT / declared["path"]
            assert predecessor.is_file(), (
                f"{path.name} {key} names {declared['path']}, which is not in the tree"
            )
            digest = hashlib.sha256(
                canonical_json(json.loads(predecessor.read_bytes())["record"])
            ).hexdigest()
            assert declared["record_sha256"] == digest, (
                f"{path.name} {key} binds {declared['path']} at {declared['record_sha256']}, "
                f"but that record now canonicalises to {digest}"
            )
            checked += 1
    # A floor rather than "> 0", in the same spirit as the migration prefix check further down.
    # These records are immutable retained evidence and are only ever added to, so a later record
    # may raise this number; a drop to below 16 means a declaration that existed on 2026-09-07 was
    # removed, which shortens the chain and is exactly the silent re-parenting this test exists to
    # catch. Raise the floor when the chain grows, never lower it.
    assert checked >= 16, f"only {checked} predecessor bindings found, expected at least 16"


def test_records_that_declare_no_predecessor_are_inventoried_rather_than_silent():
    """A missing predecessor is reported, not failed.

    19 of the 33 records predate the convention (MEASURED 2026-09-07). Failing on them would make
    this file red on a tree nobody intends to change, and a permanently red test gets deleted
    rather than fixed, taking the universal rule above with it. So the gap is emitted as a warning
    the pytest summary always shows, which is a thing a reader can act on.

    ``warnings.warn`` rather than ``print`` on purpose: pytest runs with ``-q`` here, which
    captures stdout and shows it only for failures, so a print would say nothing on the green run
    that is the only run this ever has. Nothing configures ``filterwarnings``, so this can neither
    be hidden nor promoted into an error.

    Rejected: freezing today's 19 into an allowlist so any NEW record without a predecessor fails.
    The three 2026-09-06 records are the most recent family in the tree and declare nothing, so
    that gate would fire on the legitimate first record of every new family, and the cheapest way
    past it would be to add a binding that says nothing true.
    """
    bindings = 0
    declaring: list[str] = []
    silent: list[str] = []
    for path in _records():
        record = json.loads(path.read_bytes())["record"]
        declared = _declared_predecessors(record)
        if declared:
            declaring.append(path.name)
            bindings += len(declared)
        else:
            silent.append(path.name)
    # `declaring` is what carries the guard, and the partition count above it does NOT: every
    # path is appended to exactly one of the two lists, so their sum equals the total by
    # construction and can never fail. It was written here as if it caught a blind extractor and
    # it does not, which in a file whose comments are the reasoning is worse than no comment. The
    # blind-extractor case is caught twice over, and neither time is here: the universal rule
    # above fails on its own floor of verified bindings, and this line fails on an empty list.
    total = len(_records())
    assert declaring, "no record declares a predecessor, so the binding rule checks nothing"
    warnings.warn(
        f"predecessor chain: {bindings} bindings verified across {len(declaring)} of {total} "
        f"retained records. {len(silent)} declare no predecessor and are not required to: "
        + ", ".join(sorted(silent)),
        stacklevel=1,
    )


_READINESS = "2026-09-04-readiness-and-architecture-audit.json"


def _readiness() -> dict:
    return json.loads((_ROOT / "docs" / "evaluation" / _READINESS).read_bytes())["record"]


def test_the_readiness_audit_is_bound_to_the_campaign_it_followed():
    """WHICH record the audit follows, which is the half no universal rule can know.

    This asserted only the sha256 arithmetic until 2026-09-07, so despite its name it would have
    stayed green with the audit re-parented onto any other well-formed record in the folder. The
    arithmetic now runs once for every record above; what is left here is the identity claim the
    name always made: a readiness report that says it starts from the validation campaign has to
    start from the validation campaign, not from something more flattering.
    """
    predecessor = _readiness()["predecessor_record"]
    assert predecessor["path"].endswith("2026-09-04-reconstruction-validation-campaign.json")


def test_the_readiness_audit_closes_the_eight_decisions_it_was_asked_to_close():
    record = _readiness()
    numbers = [decision["number"] for decision in record["decisions_closed"]]
    assert numbers == list(range(1, 9)), numbers
    for decision in record["decisions_closed"]:
        for field in (
            "name",
            "invariant",
            "rationale",
            "compatibility_impact",
            "failure_behaviour",
            "affected_surfaces",
            "tests",
        ):
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
    assert goals == gated, goals ^ gated
    for entry in record["subsequent_goal_gates"]:
        assert entry["entry_gates"], entry["goal"]
        assert entry["exit_gates"], entry["goal"]


_ANSWERS = "2026-09-04-semantic-answers-and-memory-lifecycle.json"


def _answers() -> dict:
    return json.loads((_ROOT / "docs" / "evaluation" / _ANSWERS).read_bytes())["record"]


def test_the_answer_record_is_bound_to_the_audit_that_set_its_gates():
    """The gates this goal was measured against came from the audit, so it must follow the audit.

    Identity only; the digest arithmetic that used to be duplicated here is now checked once for
    every declared binding in the folder.
    """
    assert _answers()["predecessor_record"]["path"].endswith(_READINESS)


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
    """ "No retrieval or accuracy number may be published against an OPEN evaluation item."

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
    # This is an immutable historical record. Later forward migrations do not belong to
    # this goal, and must not require rewriting its digest (and every successor's binding).
    # Check its complete migration prefix against the repository, while allowing successors.
    completed_count = len(historical) + record["counts"]["migrations_added"]
    assert versions[:completed_count] == [f"{n:04d}" for n in range(1, completed_count + 1)]
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
            "name",
            "invariant",
            "rationale",
            "canonical_representation",
            "compatibility_impact",
            "failure_behaviour",
            "negative_control",
        ):
            assert decision.get(field), f"decision {decision['number']} has no {field}"
        assert decision["tests"], decision["number"]
        assert set(decision["affected_surfaces"]) == {
            "schema",
            "migrations",
            "workers",
            "evidence",
            "apis",
            "exports",
            "deletion_paths",
            "browser_consumers",
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
