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
import shutil
import subprocess
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


# -- the walk a committed file states, through the harness itself ---------------------------------

WEB = ROOT / "web"
TSX = WEB / "node_modules/.bin/tsx"
CORRIDOR_WALK = ROOT / "docs/generated-corridor-street.md"
WALK_PARAMETERS = ("pose_x_mm", "pose_y_mm", "facing_dx", "facing_dy")


def _node(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run something under the web toolchain's tsx, because the harness imports TypeScript."""
    if not TSX.exists():
        pytest.skip(f"the web toolchain is not installed ({TSX} is missing); run pnpm install in web/")
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    return subprocess.run(
        [str(TSX), *arguments], cwd=WEB, capture_output=True, text=True, timeout=300
    )


def _read_walk(tmp_path: Path, text: str) -> dict[str, object]:
    """What the harness's own reader makes of `text`: the walk, or the refusal it raised."""
    source = tmp_path / "walk.md"
    source.write_text(text)
    driver = tmp_path / "read-walk.mjs"
    driver.write_text(
        "import { readFileSync } from 'node:fs';\n"
        f"const harness = await import({str(HARNESS)!r});\n"
        f"const text = readFileSync({str(source)!r}, 'utf8');\n"
        "try { console.log(JSON.stringify({ walk: harness.statedWalkOf(text) })); }\n"
        "catch (error) { console.log(JSON.stringify({ refused: error.message })); }\n"
    )
    result = _node(str(driver))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_committed_corridor_walk_reads_as_exactly_one_walk(tmp_path):
    """The file the gate will bind states one walk, and the harness reads it as one.

    The values are not pinned here. The corridor owns where its walk begins and may move it; what
    this holds is that the file states a walk at all, states only one, and states it in whole
    millimetres, which is what makes a bound pose reproducible.
    """
    read = _read_walk(tmp_path, CORRIDOR_WALK.read_text())
    assert "refused" not in read, read
    walk = read["walk"]
    assert set(walk) == {"xMm", "yMm", "facingDx", "facingDy"}
    assert all(isinstance(value, int) for value in walk.values()), walk
    assert (walk["facingDx"], walk["facingDy"]) != (0, 0), "a facing of no direction states nothing"


def test_a_file_stating_no_walk_is_refused_by_name(tmp_path):
    read = _read_walk(tmp_path, "This paragraph mentions a walk and states no pose.")
    assert "walk" not in read, read
    for name in WALK_PARAMETERS:
        assert name in read["refused"], read


def test_a_file_stating_two_different_walks_is_refused_rather_than_chosen_between(tmp_path):
    """Two walks in one file is the failure a lenient reader would hide.

    A reader that took the first match would score whichever paragraph came first, and a superseded
    example would silently become the opening frame of a scored run.
    """
    read = _read_walk(
        tmp_path,
        "one `?pose_x_mm=262000&pose_y_mm=70300&facing_dx=1&facing_dy=0`\n"
        "two `?pose_x_mm=320000&pose_y_mm=70300&facing_dx=1&facing_dy=0`\n",
    )
    assert "walk" not in read, read
    assert "262000" in read["refused"] and "320000" in read["refused"], read


def test_one_walk_written_twice_is_one_walk(tmp_path):
    """Repetition is not disagreement: a file may state its walk in prose and again in a table."""
    stated = "`?preview=1&tile_x=2&pose_x_mm=262000&pose_y_mm=70300&facing_dx=1&facing_dy=0`"
    read = _read_walk(tmp_path, f"{stated}\nand again later: {stated}\n")
    assert read == {"walk": {"xMm": 262000, "yMm": 70300, "facingDx": 1, "facingDy": 0}}


@pytest.mark.parametrize(
    "written",
    ["pose_x_mm=262000.5&pose_y_mm=70300&facing_dx=1&facing_dy=0", "pose_x_mm=262000&pose_y_mm=70300&facing_dx=1"],
)
def test_a_walk_stated_incompletely_or_in_fractions_is_not_a_walk(tmp_path, written):
    read = _read_walk(tmp_path, f"`?{written}`")
    assert "walk" not in read, read


def _harness_halt(tmp_path: Path, search: str, walk: str | None) -> str:
    """The reason the harness stopped, from the halt it writes, for a run that never opens a browser.

    The walk rule is checked before Chrome is launched, so these runs cost no browser and no server:
    a halt here is the refusal itself and not a failure to reach a page.
    """
    out = tmp_path / "out"
    arguments = [
        str(HARNESS), "--target", "generated-tile-evaluation",
        "--app", f"http://127.0.0.1:1/{search}", "--out", str(out), "--label", "walk-rule",
    ]
    if walk is not None:
        arguments += ["--walk", walk]
    result = _node(*arguments)
    assert result.returncode == 3, (result.returncode, result.stdout, result.stderr)
    halted = json.loads((out / "walk-rule-halt.json").read_text())
    assert halted["halted"] is True
    return halted["reason"]


def test_a_pose_the_run_chose_is_refused_when_no_committed_file_states_it(tmp_path):
    reason = _harness_halt(
        tmp_path,
        "?preview=1&tile=tile-conformance&pose_x_mm=1&pose_y_mm=2&facing_dx=1&facing_dy=0",
        walk=None,
    )
    assert "chosen per run" in reason and "--walk" in reason, reason


def test_a_committed_walk_the_page_was_never_asked_to_take_is_refused(tmp_path):
    """A file naming a walk, and a URL that opens somewhere else, is not a stated walk.

    The record would name a pose nobody walked from. Both halves have to agree or the binding says
    nothing about the frame that was captured.
    """
    reason = _harness_halt(tmp_path, "?preview=1&tile=tile-conformance", walk=str(CORRIDOR_WALK))
    assert all(name in reason for name in WALK_PARAMETERS), reason
    assert "unset" in reason, reason


def test_a_run_asking_for_a_different_walk_than_the_file_states_is_refused(tmp_path):
    reason = _harness_halt(
        tmp_path,
        "?preview=1&tile=tile-conformance&pose_x_mm=262000&pose_y_mm=70300&facing_dx=0&facing_dy=1",
        walk=str(CORRIDOR_WALK),
    )
    assert "facing_dx" in reason and "facing_dy" in reason, reason
    # The parameters that agree are not named as differences.
    assert "pose_x_mm" not in reason and "pose_y_mm" not in reason, reason


def test_a_walk_outside_the_repository_is_refused(tmp_path):
    outside = tmp_path / "somebody-elses-walk.md"
    outside.write_text("`?pose_x_mm=1&pose_y_mm=2&facing_dx=1&facing_dy=0`")
    reason = _harness_halt(tmp_path, "?preview=1&tile=tile-conformance", walk=str(outside))
    assert "outside the repository" in reason, reason


# -- what a record states about the route, against what the rule returned -------------------------

def _route_record(tmp_path: Path, tamper: str) -> dict[str, object]:
    """Build a route record from a real plan, apply `tamper` to it, and hand it back to the check.

    The plan comes from the rule itself rather than from a literal here, so the set of numbers the
    check compares is the set the rule actually returns. A list of field names written in this file
    would be a second source of truth for the thing under test.

    The rings are two long walls either side of the start, because a plan with no frontage on both
    sides makes the derived value below equal the measured one, and the tamper that matters becomes
    a no-op. `derived` is reported so a test can assert the tamper changed something.
    """
    driver = tmp_path / "route-record.mjs"
    driver.write_text(
        "import { planRoute } from "
        f"{str(ROOT / 'web/packages/loom-gate/src/index.ts')!r};\n"
        f"const harness = await import({str(HARNESS)!r});\n"
        "const wall = (x, from, to) => ({ id: `test:wall${x}:${from}`, ring: "
        "[[x, from], [x + 1, from], [x + 1, to], [x, to], [x, from]] });\n"
        # One wall the whole length and one only on the southern half, so some qualifying headings
        # see rings on both sides and some see one. A corridor walled on both sides for its whole
        # length gives every qualifying heading frontage, and then the derived value the tamper
        # writes equals the measured one and the overwrite it is testing becomes invisible.
        "const plan = planRoute([0, 0], [wall(-5, -200, 200), wall(4, -200, -1)], [-500, -500, 500, 500]);\n"
        "const derived = plan.frontageBothSidesSamples > 0 ? plan.candidatesQualified : 0;\n"
        "const measured = { field: null, obstacles: 2, routeRings: 2, routeRingsRefused: [], fieldBoundsCm: null };\n"
        "try {\n"
        "  const record = harness.routeRecordOf(plan, measured);\n"
        f"  {tamper}\n"
        "  console.log(JSON.stringify({ record: harness.checkedRouteRecord(plan, record), plan, derived }));\n"
        "} catch (error) { console.log(JSON.stringify({ refused: error.message, plan, derived })); }\n"
    )
    result = _node(str(driver))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_record_states_every_number_the_route_rule_returned(tmp_path):
    """The literal itself, exercised. It is on a path no run reaches until a walk completes."""
    built = _route_record(tmp_path, "")
    assert "refused" not in built, built
    record, plan = built["record"], built["plan"]
    numbers = {name for name, value in plan.items() if isinstance(value, (int, float))}
    # `yaw` is the heading in radians, stated as integer millidegrees instead.
    assert numbers - set(record) == {"yaw"}, numbers - set(record)
    for name in numbers - {"yaw"}:
        assert record[name] == plan[name], name


def test_a_measured_count_overwritten_by_a_derived_one_is_refused(tmp_path):
    """The defect this check was written for: a repeated key in the record's own literal.

    JavaScript takes the last assignment silently, so the derived value won and a record would have
    stated every qualifying heading where the rule counted the ones with frontage.
    """
    built = _route_record(
        tmp_path,
        "record.candidatesWithFrontage = plan.frontageBothSidesSamples > 0 ? plan.candidatesQualified : 0;",
    )
    # The tamper has to change the value, or this test passes over a fixture that cannot reach the
    # case. The first version of it did exactly that: with no frontage on both sides the derived
    # value is the measured one and the overwrite was invisible.
    assert built["derived"] != built["plan"]["candidatesWithFrontage"], built
    assert "refused" in built, built
    assert "candidatesWithFrontage" in built["refused"], built


def test_a_number_dropped_from_the_record_is_refused(tmp_path):
    """The direction a value-by-value comparison could not have noticed.

    A loop over the fields the record happens to carry passes a record that carries fewer, so the
    check compares the two sets as sets.
    """
    built = _route_record(tmp_path, "delete record.candidatesTried;")
    assert "refused" in built, built
    assert "candidatesTried" in built["refused"], built


def test_a_number_the_rule_does_not_record_is_refused_if_it_appears(tmp_path):
    """And the other side of the same set comparison, so the exclusion cannot grow silently."""
    built = _route_record(tmp_path, "record.yaw = plan.yaw;")
    assert "refused" in built, built
    assert "yaw" in built["refused"], built
