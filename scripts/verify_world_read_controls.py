"""Execute Phase 10 invariant mutations in an isolated copy of the tree.

Every test in this repository is supposed to have an executed negative control: mutate the
production code so the invariant is violated, watch the named test fail, restore. The doctrine is
in ``docs/goal-brief-2026-09-05-unblocked-backend-program.md``, and the reason it is a script
rather than a habit is that reasoning about whether a test would fail has already been wrong here:
one previous session found a digest check that had never been observed to fire.

Covers the World Read bundle, the consent seam, the generated tier, and the observation graph.

Uses only ``postgresql://localhost:5433/exulanica_spine_test``. The environment is scrubbed of
ambient ``EXULANICA_`` configuration first, so a control cannot pass or fail because of whatever
the operator's shell happened to hold, and the unmutated baseline must pass before any mutant
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

WORLD_READ = "exulanica/graph/world_read.py"
CONSENT = "exulanica/graph/read_consent.py"
NUMBERS = "exulanica/graph/wire_numbers.py"
GENERATED = "exulanica/reconstruction/generated.py"
WRITER = "exulanica/ingest/generated_scene.py"
GATE = "exulanica/reconstruction/scene_gate.py"
OBSERVATIONS = "exulanica/graph/observations.py"

TEST_FILES = (
    "conftest.py",
    "test_wire_numbers.py",
    "pg_harness.py",
    "model_fakes.py",
    "test_world_read_bundle.py",
    "test_generated_tier.py",
    "test_scene_observations.py",
    "test_scene_reconstruction_pipeline.py",
)

#: (name, production file, exact text to replace, replacement, test selector).
#: The selector must name a test that asserts the invariant, so a surviving mutant is a test that
#: proves nothing rather than a mutation that happened to be harmless.
CONTROLS = [
    (
        "the_recorded_digest_excludes_generated_content",
        WORLD_READ,
        'bundle["recorded_keys"] = sorted(key for key in bundle if key != "generated")',
        'bundle["recorded_keys"] = sorted(bundle)',
        "test_filing_a_generation_leaves_the_recorded_digest_untouched",
    ),
    (
        "a_non_finite_measurement_is_refused_rather_than_encoded",
        NUMBERS,
        "    if not math.isfinite(value):",
        "    if False:  # mutant: a non-finite value is encoded rather than refused",
        "test_a_non_finite_measurement_is_refused_rather_than_encoded",
    ),
    (
        "an_unencodable_magnitude_is_refused_rather_than_crashing",
        NUMBERS,
        "    if abs(value) >= _LIMIT:",
        "    if False:  # mutant: an oversized coordinate reaches the decimal context",
        "test_a_coordinate_too_large_to_encode_is_refused_rather_than_crashing",
    ),
    (
        "the_two_zeros_encode_to_one_string",
        NUMBERS,
        "    if quantised.is_zero():\n",
        "    if False:\n",
        "test_the_two_zeros_encode_to_the_same_string",
    ),
    (
        # The invariant survived the person-consent merge; the reason for it changed. The bundle
        # carries no per-person state, so no recipient can check a more permissive claim, and the
        # test this kills now pins that absence rather than the absence of the layer.
        "the_release_state_is_internal_only_without_person_consent",
        CONSENT,
        '        "state": "internal_only",',
        '        "state": "releasable",',
        "test_the_release_state_is_internal_only_while_no_person_state_reaches_the_bundle",
    ),
    (
        # Renamed with the fact it protects. The old mutation flipped a hardcoded "unavailable" to
        # "none", which stopped existing when the layer merged and the field started describing
        # the photograph rather than the build. The mutation that carries the same meaning now is
        # the default: a photograph nobody screened must never be reported as one whose people
        # have decisions on file.
        "an_unscreened_photograph_is_never_reported_as_one_with_decisions",
        CONSENT,
        '            "recorded" if reviewed.get(key) == "screened" else "unscreened"',
        '            "recorded"',
        "test_consent_reports_the_screening_basis_and_refuses_to_infer_people",
    ),
    (
        # The scene-level fold, which is where the pre-merge bundle contradicted itself: a scene
        # said one thing about people and every capture in it said another. A permissive fold
        # would restore exactly that.
        "one_unscreened_photograph_makes_the_whole_scene_unscreened",
        CONSENT,
        '    if all(record["person_consent"] == "recorded" for record in consent.values()):',
        '    if any(record["person_consent"] == "recorded" for record in consent.values()):',
        "test_the_scene_consent_answer_is_the_weakest_of_its_photographs",
    ),
    (
        "a_generation_is_labelled_generated_in_the_read_bundle",
        WORLD_READ,
        '            "tier": "generated",\n            "artifact_id": str(row.artifact_id),',
        '            "tier": "recorded",\n            "artifact_id": str(row.artifact_id),',
        "test_the_read_bundle_keeps_generated_out_of_the_recorded_geometry_list",
    ),
    (
        "a_generation_must_name_the_bundle_it_actually_read",
        WRITER,
        "    if receipt.bundle_sha256 != expected_recorded_sha256:",
        "    if False:  # mutant: any conditioning digest is accepted",
        "test_a_generation_naming_the_wrong_bundle_is_refused",
    ),
    (
        "model_identity_enters_the_generated_artifact_key",
        GENERATED,
        "    return sha256_of_canonical(receipt.document())",
        '    return sha256_of_canonical({"constant": "mutant"})',
        "test_a_model_swap_produces_a_different_artifact_identity",
    ),
    (
        "a_generation_without_a_seam_is_refused",
        GENERATED,
        "_MIN_SEAM_CHARACTERS: Final = 24",
        "_MIN_SEAM_CHARACTERS: Final = 1",
        "test_a_generation_without_a_seam_is_refused",
    ),
    (
        "a_generated_receipt_kind_cannot_enter_a_gate",
        GATE,
        '        if kind not in ("pose", "placement", "scale", "coverage", "corridor", "splat"):',
        "        if False:  # mutant: any receipt kind is a gate receipt",
        "test_a_generation_cannot_satisfy_any_reconstruction_gate",
    ),
    (
        # The mutant that matters is the ORIGINAL defect: reading through artifact_current, whose
        # distinct-on key every generation for one scene shares, so all but one become invisible.
        # An earlier version of this control removed the supersession filter instead and survived,
        # correctly: that mutation makes the read more permissive and the test files nothing
        # superseded, so nothing changes. The control now reinstates the actual defect.
        "every_generation_for_a_scene_stays_visible",
        "exulanica/graph/generated_geometry.py",
        "  from artifact a\n",
        "  from artifact_current a\n",
        "test_two_generations_for_one_scene_are_both_visible",
    ),
    (
        "a_superseded_generation_is_not_offered_beside_its_replacement",
        "exulanica/graph/generated_geometry.py",
        "   and a.superseded_by is null",
        "   and a.artifact_id is not null  -- mutant: no supersession filter",
        "test_a_superseded_generation_is_withdrawn_from_the_graph",
    ),
    (
        "the_observation_graph_is_guarded_scene_wide",
        OBSERVATIONS,
        "   and not tombstone_blocks_scene(s.workspace_id, s.scene_id)",
        "   and not tombstone_blocks_capture(s.workspace_id, s.scene_id)",
        "test_withdrawing_a_member_withdraws_the_whole_observation_graph",
    ),
]


def _environment(work: Path) -> dict[str, str]:
    """Ambient configuration scrubbed, then exactly one permitted database set."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("EXULANICA_")}
    env["PYTHONPATH"] = str(work)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["EXULANICA_TEST_DATABASE_URL"] = DATABASE
    env["EXULANICA_REQUIRE_POSTGRES"] = "1"
    return env


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
        # Collection alone answers "does this selector name a test", and it answers it without a
        # database, so the check costs a fraction of a run rather than a run.
        command.append("--collect-only")
    if selector is None:
        command.extend(
            str(work / "tests" / name)
            for name in TEST_FILES
            if name.startswith("test_") and name != "test_scene_reconstruction_pipeline.py"
        )
    else:
        command.extend(
            [
                *(
                    str(work / "tests" / name)
                    for name in TEST_FILES
                    if name.startswith("test_") and name != "test_scene_reconstruction_pipeline.py"
                ),
                "-k",
                selector,
            ]
        )
    return subprocess.run(command, cwd=work, env=env, text=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # A record is a dated observation of a tree. Re-running against a changed tree writes a new
    # record bound to the one it follows, rather than overwriting a true statement about a tree
    # that can no longer be checked out.
    parser.add_argument(
        "--date", required=True, help="ISO date this run was executed, e.g. 2026-09-07"
    )
    parser.add_argument(
        "--predecessor",
        default=None,
        help="path, relative to the repository root, of the record this one follows",
    )
    # Two runs on one date against two different trees are two observations, and the second must
    # not overwrite the first. The date alone cannot separate them, so a label can.
    parser.add_argument(
        "--label",
        default="world-read",
        help="filename stem after the date, so a same-day re-run against a changed tree writes a "
        "new record rather than replacing a true statement about a tree nobody can check out",
    )
    arguments = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="exulanica-world-read-mutants-"))
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
        # or misspelled `-k` expression deselects everything, pytest exits 5, and the run below
        # records SURVIVED: a control that never executed reads as an invariant that failed to
        # hold, and the two need opposite responses. Checked before the mutation so a failure here
        # is unambiguously about the selector and not about the edit.
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
        # A kill is THE NAMED TEST failing, and the predicate says so literally rather than
        # inferring it from a path prefix.
        #
        # MEASURED 2026-09-07, and this is why the shape is what it is. The predicate was first
        # `"FAILED" in output`, which a passing bare word in a traceback could satisfy. Tightening
        # it to `"FAILED tests/"` to match verify_reference_controls.py reported all fifteen
        # mutants SURVIVED: this script passes absolute test paths, so pytest renders node ids
        # from the rootdir it derives, and the prefix is not reliably `tests/`. A predicate that
        # depends on how pytest chose to spell a path is a predicate that will silently invert
        # again. Requiring the selector's own name on a FAILED line is stronger than either form
        # and depends on nothing but the test's identity.
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
        "profile": "exulanica.world-read-negative-controls/v1",
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
    output_path = (
        ROOT / f"docs/evaluation/{arguments.date}-{arguments.label}-negative-controls.json"
    )
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
