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


def test_a_repository_path_is_found_whatever_directory_the_harness_runs_from(tmp_path):
    """`--walk docs/x.md` means the repository's, not the one under the directory it was started in.

    These runs start in ``web/`` exactly as a real one does, so before the fix this looked for
    ``web/docs/...``, threw on the missing file and never reached a refusal at all. The assertion is
    that the harness READ the file: it gets far enough to compare the stated walk with the URL, and
    names the path relative to the repository.
    """
    stated = "docs/visual-gate-corridor-walk.md"
    assert (ROOT / stated).exists(), "this lane's own stated walk is what the test resolves"
    reason = _harness_halt(tmp_path, "?preview=1&tile=tile-conformance", walk=stated)
    assert stated in reason, reason
    assert "asks for a different walk" in reason, reason


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
        "const measured = { field: null, obstacles: 2, routeRings: 2, routeRingsRefused: [], "
        "groundRefused: [], routeGround: null, fieldBoundsCm: null };\n"
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


# -- the harness itself, type-checked, because nothing else in this repository checks it -----------

# -- what the product showed when it would not start ------------------------------------------------


def _surface(tmp_path: Path, shell_js: str) -> object:
    """What the harness reads from a page whose ``#shell`` element is `shell_js`.

    THE DOM IS FAKED AND NOTHING ELSE IS. The harness's own page-side expression is run here, so the
    slice, the character count and the absent-shell branch under test are the ones a run sends to a
    real page; a test that rebuilt that shape itself would be checking its own arithmetic. Only
    ``document`` is invented, because the one thing not available here is a browser.

    A STUB BECAUSE THE FIXTURE IS TEMPORARY. This path was built against a live page that reliably
    refused to start, and the tile route defect behind that page is being fixed. Once it is, nothing
    here shows an error surface on demand, and a check whose only fixture has gone is a check nobody
    will see refuse anything again.
    """
    driver = tmp_path / "read-surface.mjs"
    driver.write_text(
        f"const harness = await import({str(HARNESS)!r});\n"
        f"const shell = {shell_js};\n"
        "const document = { getElementById: (id) => (id === 'shell' ? shell : null) };\n"
        "const value = new Function('document', `return ${harness.PRODUCT_SURFACE}`)(document);\n"
        "const session = { evaluate: async () => value };\n"
        "console.log(JSON.stringify({ surface: await harness.productSurfaceOf(session) }));\n"
    )
    result = _node(str(driver))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])["surface"]


def _showing(text: str) -> str:
    """A shell in its error state showing `text`, as little of an element as the reader touches."""
    return f"{{ getAttribute: () => 'error', innerText: {json.dumps(text)} }}"


def test_the_halt_carries_what_the_product_said_and_adds_nothing_to_it(tmp_path):
    """The product's own refusal, verbatim, with none of this gate's words mixed into it.

    MEASURED 2026-09-18 and this is the sentence that was lost: two corridor runs halted on "the
    product failed to start" and the record said only that. The refusal below, naming the tile and
    the version the page wanted, reached nobody but a live session watching the page, and had that
    session ended first, a later reader would have had to rediscover the defect from nothing.
    """
    product = (
        "Atlas could not open\n\nTile 7ce4b90f-675b-52dc-b71b-7264aeb00786 refused: .owd refused: "
        "tessellator_version is not 19; there is no upgrade on read, rebake the tile\n\n"
        "Retry opening Atlas"
    )
    surface = _surface(tmp_path, _showing(product))
    assert surface["text"] == product
    assert surface["worldState"] == "error"
    # No field of this gate's own invention beside the product's words.
    assert set(surface) == {"worldState", "text", "textCharacters"}


def test_a_shell_that_is_not_there_is_not_a_shell_showing_nothing(tmp_path):
    """Two different failures, and a record that ran them together could not be asked which."""
    assert _surface(tmp_path, "null") is None
    assert _surface(tmp_path, _showing("")) == {
        "worldState": "error",
        "text": "",
        "textCharacters": 0,
    }


def test_a_cut_surface_says_how_much_there_was(tmp_path):
    """A cut that cannot be seen is a quotation a reader would take for the whole thing."""
    surface = _surface(tmp_path, _showing("x" * 5000))
    assert len(surface["text"]) == 2000
    assert surface["textCharacters"] == 5000


def test_a_surface_that_cannot_be_read_does_not_replace_the_halt(tmp_path):
    """Reading the page is a courtesy to the next reader and must never cost them the halt itself.

    This runs inside the failure handler of the mount wait, so an error thrown here would leave the
    run reporting why the SURFACE could not be read instead of why the PRODUCT would not start.
    """
    driver = tmp_path / "unreadable.mjs"
    driver.write_text(
        f"const harness = await import({str(HARNESS)!r});\n"
        "const session = { evaluate: async () => { throw new Error('the session went away'); } };\n"
        "console.log(JSON.stringify({ surface: await harness.productSurfaceOf(session) }));\n"
    )
    result = _node(str(driver))
    assert result.returncode == 0, result.stderr
    surface = json.loads(result.stdout.strip().splitlines()[-1])["surface"]
    assert "the session went away" in surface["unreadable"]


def test_a_local_path_the_product_shows_does_not_reach_the_record(tmp_path):
    """The product may name a file; a record of this repository may not carry this machine."""
    surface = _surface(tmp_path, _showing("could not read /Users/someone/dev/thing/tile.owd"))
    assert "/Users/" not in surface["text"]
    assert "<local-path>" in surface["text"]


def test_the_support_probe_stays_fine_enough_to_see_the_hole_that_misled_a_run(tmp_path):
    """The spacing is a requirement, not a setting, and nothing held it to that until now.

    MEASURED 2026-09-18: at 0.25 m the probe reported "support for the next 10 m" over a 30 mm hole
    15 mm ahead of a stalled walker, and that one figure misdirected a whole run's diagnosis. A probe
    coarser than the hole does not find fewer holes, IT REPORTS THEIR ABSENCE.

    This asserts the relationship rather than the number: at least two samples must land inside the
    hole that was missed, so the spacing cannot drift back toward it. Retyping 0.005 here would make
    the test a copy of the code and it could then never refuse anything.
    """
    driver = tmp_path / "spacing.mjs"
    driver.write_text(
        f"const harness = await import({str(HARNESS)!r});\n"
        "console.log(JSON.stringify({ spacing: harness.PROBE_SPACING_M, hole: harness.HOLE_THAT_WAS_MISSED_M }));\n"
    )
    result = _node(str(driver))
    assert result.returncode == 0, result.stderr
    read = json.loads(result.stdout.strip().splitlines()[-1])
    assert read["spacing"] <= read["hole"] / 2, read


def _reach(tmp_path: Path, search: str, owned: str = "false") -> object:
    """What the harness would tell the page to compose, for a URL and a target."""
    driver = tmp_path / "reach.mjs"
    driver.write_text(
        f"const harness = await import({str(HARNESS)!r});\n"
        "const rule = (await import("
        f"{str(ROOT / 'web/packages/loom-gate/src/index.ts')!r})).ROUTE_RULE;\n"
        f"const url = new URL('http://127.0.0.1:1/{search}');\n"
        f"const reach = harness.composedWorldReachMm(url, {owned});\n"
        "console.log(JSON.stringify({ reach, lengthMm: rule.lengthMm, stopMarginMm: rule.stopMarginMm }));\n"
    )
    result = _node(str(driver))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_page_is_told_to_compose_the_whole_route_and_its_stopping_margin(tmp_path):
    """The page must not hold a route length, so the gate sends one, and it must be the WHOLE one.

    The assertion is the RELATIONSHIP and not the number 131000. Writing that literal here would put
    a second copy of the rule in a test, which could then never refuse a change to the rule. Summing
    the two fields still refuses the mutation that matters: sending the route length while forgetting
    the stopping margin, which would compose a world 6 m short of where the walk actually stops.
    """
    read = _reach(tmp_path, "?preview=1&city=abc&tile_x=2&tile_y=0")
    assert read["reach"] == read["lengthMm"] + read["stopMarginMm"]
    assert read["reach"] != read["lengthMm"], "the stopping margin is part of what must hold ground"


def test_no_world_is_composed_around_the_committed_fixture(tmp_path):
    """A recorded baseline must keep fetching what it fetched.

    The conformance tile is a committed file with no store rows to compose from, and asking for a
    world around it would change what those runs move over the wire. Two runs that fetched different
    things are not two measurements of the same thing.
    """
    assert _reach(tmp_path, "?preview=1&tile=tile-conformance")["reach"] is None
    assert _reach(tmp_path, "?preview=1&city=abc&tile_x=2&tile_y=0", owned="true")["reach"] is None


# -- a hole and a kerb are different sentences -----------------------------------------------------


def _steepest_rise(tmp_path: Path, heights: list[object], spacing_m: float = 0.005) -> object:
    """What the harness makes of a run of sampled heights. `None` in the list is the product's NaN."""
    driver = tmp_path / "rise.mjs"
    written = ", ".join("Number.NaN" if h is None else repr(float(h)) for h in heights)
    driver.write_text(
        f"const harness = await import({str(HARNESS)!r});\n"
        f"const heights = [{written}];\n"
        f"console.log(JSON.stringify({{ rise: harness.steepestRiseOf(heights, {spacing_m}) }}));\n"
    )
    result = _node(str(driver))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])["rise"]


def test_a_kerb_is_reported_with_where_it_is(tmp_path):
    """The hazard this exists for: a join that rises further than the world says it will climb.

    MEASURED by the tess lane 2026-09-18: inside one tile, where terrain meets its street, a join
    rises 192.987 mm against the 180 mm the world states. The figure below is that one.
    """
    heights = [0.0] * 10 + [0.192987] * 10
    rise = _steepest_rise(tmp_path, heights)
    assert rise["riseMm"] == 192.987
    assert rise["atM"] == pytest.approx(0.05)


def test_no_rise_is_measured_across_missing_ground(tmp_path):
    """Two surfaces either side of a hole are not one step, and calling them one invents a kerb.

    Without this the gate would report the biggest number in sight as a step every time a route ran
    off the end of the ground, which is the case it meets most often.
    """
    # It STARTS on missing ground, which is the case that separates this from arithmetic on NaN:
    # a route beginning off the surface, then flat ground, then a hole, then a higher surface.
    heights = [None, None] + [0.0] * 5 + [None] * 5 + [9.0] * 5
    rise = _steepest_rise(tmp_path, heights)
    # The flat ground IS measured, at zero, because those samples are neighbours.
    assert rise["riseMm"] == 0.0
    # What must never appear is the 9 m between the two surfaces, which no walker ever climbs.
    assert rise["riseMm"] != 9000.0


def test_a_drop_is_not_a_step_up(tmp_path):
    """A fall is not a climb. A route that only descends has a steepest rise of zero, not of 2 m."""
    # The drop must be LARGER than the rise, or the two answers coincide and this asserts nothing.
    # Measured 2026-09-18: written first as [2, 1, 0], where a mutation that ranks by magnitude gives
    # the same number, so the test passed against the defect it names.
    rise = _steepest_rise(tmp_path, [0.0, 1.0, -10.0])
    assert rise["riseMm"] == 1000.0
    assert rise["atM"] == pytest.approx(0.005)


def test_a_flat_route_is_not_the_same_as_nothing_to_measure(tmp_path):
    """Zero is a measurement; null means fewer than two adjacent samples had any surface at all."""
    assert _steepest_rise(tmp_path, [1.0, 1.0, 1.0])["riseMm"] == 0.0
    assert _steepest_rise(tmp_path, [None, 1.0, None]) is None


HARNESS_TSCONFIG = ROOT / "web/tsconfig.scripts.json"


def test_the_harness_type_checks_and_the_checker_looked_at_it():
    """Nothing else checks this file, and a checker that looked at nothing also exits 0.

    MEASURED 2026-09-18: no tsconfig in this repository reaches outside ``web/``, so the gate harness
    was type-checked by nothing; ``node --check`` accepts a duplicate object key because it is legal
    JavaScript; and there is no JavaScript linter here. A duplicated key in the record builder
    therefore replaced a measured count with a derived one in silence, and a hand-run ``tsc`` over a
    copy was what found it.

    The configuration is deliberately lenient: strict typing of untyped JavaScript reports 158
    findings across these three files, none of them a defect, while this reports the syntactic class
    that actually bit. Both were measured, and both catch the duplicate.

    THE SECOND ASSERTION IS THE LOAD BEARING ONE. An empty ``include`` exits 0 exactly as a clean
    file does, so this asserts the compiler listed the harness among the files it read before
    reading its silence as a pass.
    """
    tsc = WEB / "node_modules/.bin/tsc"
    if not tsc.exists():
        pytest.skip(f"the web toolchain is not installed ({tsc} is missing); run pnpm install in web/")
    result = subprocess.run(
        [str(tsc), "-p", str(HARNESS_TSCONFIG), "--listFiles"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    read = [line.strip() for line in result.stdout.splitlines() if line.strip().endswith(".mjs")]
    findings = [line for line in result.stdout.splitlines() if "error TS" in line]
    # FINDINGS FIRST. A syntax error stops the compiler before it lists anything, so asking about
    # coverage first reports "the checker did not read it" for a file it read and refused, which
    # sends the reader to this configuration instead of to the line that is wrong. Measured by
    # breaking it: the duplicate key failed the coverage assertion until this order was fixed.
    assert not findings, "\n".join(findings)
    assert result.returncode == 0, result.stderr
    assert str(HARNESS) in read, f"the checker did not read {HARNESS}; it read {read}"
