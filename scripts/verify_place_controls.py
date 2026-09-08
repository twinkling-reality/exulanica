"""Execute the place plane's invariant mutations in an isolated copy of the tree.

The doctrine and the shape are ``scripts/verify_world_read_controls.py``'s, deliberately, down to
the kill predicate. Reasoning about whether a test would fail has been wrong in this repository
before, and the place work adds a fitter whose whole value is that it refuses: a refusal path that
nothing observes failing is a refusal path nobody has evidence for.

Covers ``exulanica/reconstruction/place_alignment.py``, and the production build and read seams, including live position derivation.
The geometry remains synthetic and the COLMAP executor is scripted.

Uses only ``postgresql://localhost:5433/exulanica_spine_test``. The environment is scrubbed of
ambient ``EXULANICA_`` configuration first, and the unmutated baseline must pass before any mutant
result counts.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from exulanica.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "postgresql://localhost:5433/exulanica_spine_test"
PYTHON = Path(sys.executable)

FITTER = "exulanica/reconstruction/place_alignment.py"

TEST_FILES = (
    "conftest.py",
    "pg_harness.py",
    "model_fakes.py",
    "test_place_alignment.py",
    "test_place_plane.py",
    "test_place_alignment_build.py",
    "test_place_read_bundle.py",
    "test_world_read_bundle.py",
    "test_scene_reconstruction_pipeline.py",
)

#: (name, production file, exact text to replace, replacement, test selector).
#: The selector must name a test that asserts the invariant, so a surviving mutant is a test that
#: proves nothing rather than a mutation that happened to be harmless.
CONTROLS = [
    (
        "the_validation_fold_is_held_out_of_the_fit",
        FITTER,
        "training = [item for index, item in enumerate(ordered) if index % stride != stride - 1]",
        "training = list(ordered)",
        "test_the_validation_fold_is_never_fitted_on",
    ),
    (
        "a_disconnected_joint_model_is_refused_before_the_numbers",
        FITTER,
        'if not connected:\n        return refused("place-alignment-not-connected")',
        'if False:\n        return refused("place-alignment-not-connected")',
        "test_a_disconnected_joint_reconstruction_is_refused_before_any_number_is_looked_at",
    ),
    (
        "a_mirrored_fit_is_refused_rather_than_corrected",
        FITTER,
        "    if _determinant(rotation) <= 0:",
        "    if False:",
        "test_a_mirrored_fit_is_refused_rather_than_corrected",
    ),
    (
        "a_build_refusal_is_recorded_rather_than_raised",
        "exulanica/ingest/place_alignment.py",
        "    accepted = candidate_fit.accepted and against_fit.accepted",
        '    accepted = candidate_fit.accepted and against_fit.accepted\n    if not accepted:\n        raise ValueError("mutant refuses by exception")',
        "test_each_measured_refusal_is_a_row_with_its_reason_and_never_an_exception",
    ),
    (
        "a_composed_frame_records_every_hop",
        "exulanica/ingest/place_alignment.py",
        "    frame_hops = against_version.frame_hops + 1",
        "    frame_hops = 1",
        "test_a_scene_admitted_against_a_non_anchor_version_records_two_hops",
    ),
    (
        "a_composed_transform_reaches_the_anchor_frame",
        "exulanica/ingest/place_alignment.py",
        "            place_from_against,",
        "            (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.),",
        "test_a_scene_admitted_against_a_non_anchor_version_records_two_hops",
    ),
    (
        "a_withdrawn_anchor_blocks_the_place_read",
        "exulanica/graph/places.py",
        "   and not tombstone_blocks_place(p.workspace_id, p.place_id)",
        "   and true",
        "test_a_place_whose_anchor_is_withdrawn_is_not_served",
    ),
    (
        "a_withdrawn_version_contributes_no_position",
        "exulanica/graph/places.py",
        "     and not tombstone_blocks_scene(v.workspace_id, v.scene_id)",
        "     and true",
        "test_withdrawn_version_fixes_stop_contributing_before_any_purge",
    ),
    (
        "only_current_claims_contribute_a_position",
        "exulanica/graph/places.py",
        "   and a.status = 'active'",
        "   and true",
        "test_current_fixes_replace_superseded_and_retracted_positions_in_the_digest",
    ),
    (
        "an_even_fix_set_uses_the_stated_lower_median",
        "exulanica/graph/places.py",
        "        middle = (len(fixes) - 1) // 2",
        "        middle = len(fixes) // 2",
        "test_current_fixes_replace_superseded_and_retracted_positions_in_the_digest",
    ),
    (
        "a_shared_capture_is_counted_once",
        "exulanica/graph/places.py",
        "  select distinct m.capture_id",
        "  select m.capture_id",
        "test_a_capture_shared_by_versions_contributes_its_fix_only_once",
    ),
    (
        "a_historical_claim_does_not_duplicate_the_current_fix",
        "exulanica/graph/places.py",
        "   and a.valid_time is null",
        "   and true",
        "test_a_historical_fix_does_not_duplicate_the_current_capture_position",
    ),
]

#: Two mutations that were executed, survived, and are deliberately NOT in the list above, named
#: here because deleting them silently would lose the finding.
#:
#: MEASURED 2026-09-07. Both aimed at
#: ``test_every_camera_at_one_point_is_refused_rather_than_scoring_zero``, and neither killed it.
#: (1) ``if spread <= 0:`` weakened to ``if spread < 0:``, and (2) the singular-cross-covariance
#: refusal inside ``_kabsch`` removed. The reason is that a coincident camera set is caught by
#: THREE independent guards in ``_kabsch``: the polar factor is singular, the denominator is zero,
#: and the numerator is zero. Whichever survives a mutation still refuses, so that test asserts an
#: outcome no single guard owns and cannot serve as a control for any of them.
#:
#: This is a harmless-mutation finding, not an empty-test finding, and the two need opposite
#: responses. The outcome the test asserts is the one that matters and the test stays. What does
#: not exist is a single-mutation control for the degenerate path, and pretending otherwise by
#: keeping a control that reports SURVIVED would make every run of this script look failed.
NO_SINGLE_MUTATION_CONTROL = (
    "the_spread_guard_is_unreachable_defence_in_depth",
    "the_degenerate_set_is_refused_by_three_guards_not_one",
)


def _environment(work: Path) -> dict[str, str]:
    """Ambient configuration scrubbed, then exactly one permitted database set."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("EXULANICA_")}
    env["PYTHONPATH"] = str(work)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["EXULANICA_TEST_DATABASE_URL"] = DATABASE
    env["EXULANICA_REQUIRE_POSTGRES"] = "1"
    return env


def _targets(work: Path) -> list[str]:
    return [str(work / "tests" / name) for name in TEST_FILES if name.startswith("test_")]


def _run(
    work: Path,
    env: dict[str, str],
    selector: str | None,
    *,
    collect_only: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        str(PYTHON),
        "-m",
        "pytest",
        "-q",
        "-o",
        "addopts=",
        "--confcutdir=" + str(work / "tests"),
    ]
    if collect_only:
        command.append("--collect-only")
    command.extend(_targets(work))
    if selector is not None:
        command.extend(["-k", selector])
    return subprocess.run(command, cwd=work, env=env, text=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", required=True, help="ISO date this run was executed, e.g. 2026-09-07"
    )
    parser.add_argument(
        "--predecessor",
        default=None,
        help="path, relative to the repository root, of the record this one follows",
    )
    parser.add_argument("--label", default="place-negative-controls")
    arguments = parser.parse_args()
    output_path = ROOT / f"docs/evaluation/{arguments.date}-{arguments.label}.json"
    if output_path.exists():
        raise ValueError("a dated observation already exists; choose a new --label")

    work = Path(tempfile.mkdtemp(prefix="exulanica-place-mutants-"))
    shutil.copytree(
        ROOT / "exulanica", work / "exulanica", ignore=shutil.ignore_patterns("__pycache__")
    )
    (work / "tests").mkdir()
    for name in TEST_FILES:
        shutil.copy(ROOT / "tests" / name, work / "tests" / name)
    shutil.copy(ROOT / "pyproject.toml", work / "pyproject.toml")
    env = _environment(work)

    baseline = _run(work, env, None)
    if baseline.returncode != 0:
        sys.stderr.write(baseline.stdout[-4000:] + baseline.stderr[-4000:])
        raise RuntimeError("unmodified isolated baseline failed; no mutant result is valid")
    print("baseline passed", flush=True)

    records = []
    for name, file, old, new, selector in CONTROLS:
        path = work / file
        original = path.read_text()
        if original.count(old) != 1:
            raise ValueError(
                f"mutation {name} needs exactly one target in {file}, found {original.count(old)}"
            )
        # The selector must select something on the UNMUTATED tree first. Without this a renamed
        # `-k` expression deselects everything, pytest exits 5, and the run below records
        # SURVIVED: a control that never executed reads as an invariant that failed to hold.
        collected = _run(work, env, selector, collect_only=True)
        if collected.returncode != 0 or " no tests ran" in collected.stdout:
            raise ValueError(
                f"mutation {name} has a selector that matches no test: -k {selector!r}"
            )
        try:
            path.write_text(original.replace(old, new, 1))
            result = _run(work, env, selector)
        finally:
            path.write_text(original)
        output = result.stdout + result.stderr
        # A kill is THE NAMED TEST failing. Copied verbatim from verify_world_read_controls.py,
        # including the reason it is not a path prefix: that script's MEASURED 2026-09-07 note
        # records that a `"FAILED tests/"` predicate silently inverted and reported all fifteen of
        # its mutants as survivors, because pytest renders node ids from the rootdir it derives
        # and absolute targets do not produce a `tests/` prefix.
        failed_the_named_test = any(
            line.startswith("FAILED") and selector in line for line in output.splitlines()
        )
        killed = result.returncode == 1 and failed_the_named_test and "ERROR tests/" not in output
        records.append(
            {
                "mutation": name,
                "production_file": file,
                "replace": old,
                "with": new,
                "test": selector,
                "returncode": result.returncode,
                "killed": killed,
                "observed_output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                "observed_outcome": (
                    "the named test failed under the production mutation"
                    if killed
                    else "the mutation survived, or execution failed before the assertion"
                ),
            }
        )
        print(name, result.returncode, "killed" if killed else "SURVIVED", flush=True)

    restored = _run(work, env, None)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    record: dict[str, object] = {
        "profile": "exulanica.place-negative-controls/v1",
        "date": arguments.date,
        "head": head,
        "database": DATABASE,
        "isolated_source_copy": True,
        "baseline_passed": True,
        "restored_suite_passed": restored.returncode == 0,
        "records": records,
    }
    if arguments.predecessor:
        predecessor = json.loads((ROOT / arguments.predecessor).read_bytes())
        record["predecessor_record"] = {
            "path": arguments.predecessor,
            "record_sha256": hashlib.sha256(canonical_json(predecessor["record"])).hexdigest(),
        }
    output_path.write_text(
        json.dumps(
            {
                "profile": "exulanica.digest-bound-record/v1",
                "record": record,
                "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    print(output_path.relative_to(ROOT))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if all(row["killed"] for row in records) and restored.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
