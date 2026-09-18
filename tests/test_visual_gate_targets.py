"""Which page a gate record scored, and what that must not change.

A target says where a run happened. The gate exists to stop a run scoring something easier than the
thing it claims, so the target is refused when it is not declared, a record of the owned district is
byte-identical to the records already retained, and a comparison across targets is allowed only when
the keys and the rubric are the same question.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.evaluation import visual_gate
from exulanica.evaluation.gate_keys import (
    AUTHENTICATION_CONDITIONS,
    GATE_TARGET_IDS,
    GATE_TARGETS,
    GENERATED_TILE_TARGET,
    JUDGED_KEY,
    OWNED_DISTRICT_TARGET,
    gate_target,
    target_of,
)
from exulanica.evaluation.visual_gate import GateEvidenceError, beats_baseline
from tests.test_visual_gate import _evidence, _record

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs/evaluation/2026-09-15-flatiron-owned-district-baseline.json"


def test_every_declared_target_states_what_makes_a_run_of_it_comparable():
    assert GATE_TARGET_IDS == (OWNED_DISTRICT_TARGET, GENERATED_TILE_TARGET)
    for target in GATE_TARGETS:
        assert target.path == "/"
        assert target.title_source and target.title_symbol
        assert target.mounted and target.route_inputs and target.binds
        assert target.authentication_conditions
        # The title is derived from the product, never written down here, so this file cannot be
        # the place a page check quietly drifts from what the product shows.
        assert "Exulanica" not in (target.mounted + target.route_inputs + "".join(target.binds))


def test_an_undeclared_target_is_refused_rather_than_scored():
    with pytest.raises(ValueError, match="is not a gate target"):
        gate_target("owned-district-but-easier")
    with pytest.raises(GateEvidenceError, match="target must be one of"):
        _record(_evidence(), target="owned-district-but-easier")


def test_a_record_of_the_owned_district_is_byte_identical_to_one_written_without_a_target():
    """The proof that this lane did not move the product target.

    Same inputs, one record built with the target stated and one with it left to default. If the
    canonical bytes differ at all, every retained record's digest would have to be re-derived, and
    a retained record is immutable, so the difference would be a defect rather than a change.
    """
    stated = _record(_evidence(), target=OWNED_DISTRICT_TARGET)
    defaulted = _record(_evidence())
    assert canonical_json(stated) == canonical_json(defaulted)
    assert "target" not in stated["record"]
    assert stated["record_sha256"] == defaulted["record_sha256"]


def test_a_generated_tile_record_says_so_and_the_absence_reads_as_the_owned_district():
    generated = _record(_evidence(), target=GENERATED_TILE_TARGET)
    assert generated["record"]["target"] == GENERATED_TILE_TARGET
    assert target_of(generated["record"]) == GENERATED_TILE_TARGET
    assert canonical_json(generated) != canonical_json(_record(_evidence()))
    assert target_of(_record(_evidence())["record"]) == OWNED_DISTRICT_TARGET


def test_the_retained_baseline_reads_as_the_owned_district_and_still_verifies():
    document = json.loads(BASELINE.read_text())
    record = document["record"]
    assert "target" not in record
    assert target_of(record) == OWNED_DISTRICT_TARGET
    assert visual_gate.digest_bound(record)["record_sha256"] == document["record_sha256"]


def _failing_baseline() -> dict:
    """A record of the owned district that does not hold every key, as a baseline must not."""
    baseline = copy.deepcopy(_record(_evidence())["record"])
    baseline["hardPass"]["readsAsInhabitedStreet"] = False
    return baseline


def test_a_comparison_across_targets_needs_the_same_keys_and_the_same_rubric():
    candidate = _record(_evidence(), target=GENERATED_TILE_TARGET)["record"]
    baseline = _failing_baseline()
    # Same key set, same rubric, different pages: the keys do not know which page they measured.
    assert beats_baseline(candidate, baseline) is True

    other_keys = copy.deepcopy(baseline)
    other_keys["gate"]["keySet"] = "exulanica.visual-gate-keys/v4"
    with pytest.raises(GateEvidenceError, match="a comparison needs one key set"):
        beats_baseline(candidate, other_keys)

    other_rubric = copy.deepcopy(baseline)
    other_rubric["gate"]["keys"][JUDGED_KEY]["answeredAgainst"]["rubricSha256"] = "0" * 64
    with pytest.raises(GateEvidenceError, match="a comparison needs one rubric"):
        beats_baseline(candidate, other_rubric)


def test_a_comparison_states_both_targets():
    baseline = _failing_baseline()
    document = _record(
        _evidence(),
        target=GENERATED_TILE_TARGET,
        baseline=baseline,
        # Not a docs/ path: a record path this test invents would read as a retained record that
        # does not exist, and the documentation link test is right to refuse one.
        baseline_path="tests/fixtures/visual-gate/a-baseline-this-test-invented.json",
    )
    comparison = document["record"]["baselineComparison"]
    assert comparison["candidateTarget"] == GENERATED_TILE_TARGET
    assert comparison["baselineTarget"] == OWNED_DISTRICT_TARGET


def test_each_target_declares_conditions_the_gate_knows():
    """Both targets declare both conditions today, so no refusal case exists to assert.

    The check in the record builder reads each target's own tuple rather than the global one, so it
    starts refusing the moment a target declares fewer, which is the point of storing them per
    target. Writing a fake target here to force the refusal would be the same-stub defect: the
    assertion would be about a target this test invented.
    """
    for target in GATE_TARGETS:
        assert set(target.authentication_conditions) <= set(AUTHENTICATION_CONDITIONS)
        assert target.authentication_conditions


HARNESS = ROOT / "scripts/capture_visual_gate.mjs"
CONFIG = ROOT / "web/packages/app/src/config.ts"


def _harness_targets() -> dict[str, dict[str, object]]:
    """The harness's own target table, read out of the harness."""
    source = HARNESS.read_text()
    block = re.search(r"const TARGETS = Object\.freeze\(\{(.*?)\n\}\);", source, re.S)
    assert block is not None, "the harness no longer declares a TARGETS table"
    body = block.group(1)
    starts = [
        (match.start(), match.group(1))
        for match in re.finditer(r"'([a-z-]+)': Object\.freeze\(\{", body)
    ]
    # Assert the parse found something before comparing it: an empty table would agree with an
    # empty expectation and this test would assert nothing at all.
    assert len(starts) >= 2, f"parsed {len(starts)} targets out of the harness"
    found: dict[str, dict[str, object]] = {}
    for index, (offset, identifier) in enumerate(starts):
        chunk = body[offset : starts[index + 1][0] if index + 1 < len(starts) else len(body)]
        path = re.search(r"path: '([^']*)'", chunk)
        title = re.search(r"titleSymbol: '([^']*)'", chunk)
        required = re.search(r"requiredParameters: Object\.freeze\(\[([^\]]*)\]\)", chunk)
        assert path is not None and title is not None and required is not None, identifier
        found[identifier] = {
            "path": path.group(1),
            "titleSymbol": title.group(1),
            "requiredParameters": tuple(re.findall(r"'([a-z_]+)'", required.group(1))),
        }
    return found


def test_the_harness_and_the_record_declare_the_same_targets_both_ways():
    """Two lists of targets, held to each other from both sides.

    A target the harness can run and the record cannot state would produce a run nobody can write
    down; a target the record states and the harness cannot run would be a page nothing can reach.
    Asserting the SET both ways is what catches either, where "each of mine appears in yours" would
    not.
    """
    harness = _harness_targets()
    declared = {target.identifier: target for target in GATE_TARGETS}
    assert set(harness) == set(declared)
    for identifier, entry in harness.items():
        target = declared[identifier]
        assert entry["path"] == target.path
        assert entry["titleSymbol"] == target.title_symbol
        assert entry["requiredParameters"] == target.required_parameters


def test_every_declared_title_is_one_the_product_states():
    """The titles the harness will compare against exist in the product's own source.

    The harness halts when a title cannot be derived rather than comparing against nothing. This
    holds the other end: each symbol a target names is one config.ts actually states today, so the
    halt is a guard against future drift and not the normal path.
    """
    source = CONFIG.read_text()
    for target in GATE_TARGETS:
        stated = re.search(rf"const {target.title_symbol} = '([^']+)';", source)
        assert stated is not None, f"{CONFIG} no longer states {target.title_symbol}"
        assert stated.group(1).strip(), (
            f"{target.title_symbol} is empty, which equals an empty title"
        )
