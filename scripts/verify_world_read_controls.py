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
        'recorded = {key: value for key, value in bundle.items() if key != "generated"}',
        "recorded = bundle",
        "test_filing_a_generation_leaves_the_recorded_digest_untouched",
    ),
    (
        "measured_numbers_never_reach_a_digest_as_floats",
        NUMBERS,
        '    quantised = Decimal(value).quantize(Decimal(1).scaleb(-NUMBER_DECIMALS))\n    return f"{quantised:f}"',
        "    return value  # mutant: a float in a digest input",
        "test_every_number_in_the_bundle_survives_canonical_json",
    ),
    (
        "the_release_state_is_internal_only_without_person_consent",
        CONSENT,
        '        "state": "internal_only",',
        '        "state": "public",',
        "test_the_release_state_is_internal_only_until_person_consent_lands",
    ),
    (
        "absence_of_a_person_layer_is_never_reported_as_absence_of_people",
        CONSENT,
        '            "person_consent": "unavailable",\n            "person_consent_reason": (',
        '            "person_consent": "none",\n            "person_consent_reason": (',
        "test_consent_reports_the_screening_basis_and_refuses_to_infer_people",
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
        "    return sha256_of_canonical(receipt.identity())",
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


def _run(work: Path, env: dict[str, str], selector: str | None) -> subprocess.CompletedProcess[str]:
    command = [
        str(PYTHON),
        "-m",
        "pytest",
        "-q",
        "-o",
        "addopts=",
        "--confcutdir=" + str(work / "tests"),
    ]
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
        try:
            path.write_text(original.replace(old, new, 1))
            result = _run(work, env, selector)
        finally:
            path.write_text(original)
        output = result.stdout + result.stderr
        # A kill is the named test failing, not any non-zero exit. A collection error or an
        # import failure exits non-zero too and would prove nothing about the invariant.
        killed = result.returncode == 1 and "FAILED" in output and "ERROR tests/" not in output
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
    record = {
        "profile": "exulanica.world-read-negative-controls/v1",
        "date": "2026-09-06",
        "database": DATABASE,
        "isolated_source_copy": True,
        "baseline_passed": True,
        "restored_suite_passed": restored.returncode == 0,
        "records": records,
    }
    output_path = ROOT / "docs/evaluation/2026-09-06-world-read-negative-controls.json"
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
