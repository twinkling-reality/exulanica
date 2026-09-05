"""Execute trainer invariant mutations in an isolated copy; never accesses PostgreSQL."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from exulanica.canonical import canonical_json

root = Path(__file__).resolve().parents[1]
python = Path(sys.executable)
work = Path(tempfile.mkdtemp(prefix="exulanica-gsplat-mutants-"))
shutil.copytree(
    root / "exulanica", work / "exulanica", ignore=shutil.ignore_patterns("__pycache__")
)
(work / "tests").mkdir()
for name in (
    "test_gsplat_runner.py",
    "test_reconstruction_splat.py",
    "test_gsplat_dataset.py",
    "test_gsplat_container.py",
    "test_reference_inputs.py",
    "test_corpus_decode.py",
):
    shutil.copy(root / "tests" / name, work / "tests" / name)
runner = "exulanica/reconstruction/gsplat_runner.py"
splat = "exulanica/reconstruction/splat.py"
container = "exulanica/reconstruction/gsplat_container.py"
reference = "exulanica/evaluation/reference_inputs.py"
decoder = "exulanica/corpus/decode.py"
mutants = [
    (
        "sensor_orientation_is_preserved",
        decoder,
        "    return opened",
        "    from PIL import ImageOps\n\n    return ImageOps.exif_transpose(opened)",
        "test_sensor_pixels_preserve_all_exif_orientations",
    ),
    (
        "sensor_pixel_budget",
        decoder,
        "    if pixels > MAX_PIXELS:",
        "    if False:",
        "test_budget_refuses_header_before_loading",
    ),
    (
        "sensor_single_frame_only",
        decoder,
        "    _single_frame(image)",
        "    pass # mutant silently retains only frame one",
        "test_multiple_frames_are_refused_at_probe_and_decode",
    ),
    (
        "sensor_pixels_loaded_before_return",
        decoder,
        "        opened.load()",
        "        pass # mutant returns without decoding payload",
        "test_sensor_decoder_loads_pixels",
    ),
    (
        "ingest_still_normalizes_orientation",
        "exulanica/ingest/decode.py",
        "        return extract_exif_facts(opened)",
        "        _upright, facts = extract_exif_facts(opened)\n        return opened, facts",
        "test_sensor_pixels_preserve_all_exif_orientations",
    ),
    (
        "reference_normalized_paths",
        reference,
        "or pure.as_posix() != relative",
        "or False",
        "test_rehashed_malformed_inventory",
    ),
    (
        "reference_source_digest_shape",
        reference,
        'not re.fullmatch(r"[0-9a-f]{64}", digest)',
        "False",
        "test_rehashed_malformed_inventory",
    ),
    (
        "reference_positive_image_size",
        reference,
        "type(item.get(field)) is not int or item[field] <= 0",
        "False",
        "test_rehashed_malformed_inventory",
    ),
    (
        "reference_unique_split_entries",
        reference,
        "or len(set(split[field])) != len(split[field])",
        "or False",
        "test_rehashed_duplicate_split_entries",
    ),
    (
        "reference_symlinked_parent",
        reference,
        "candidate.is_symlink()",
        "False",
        "test_symlinked_parent_directory",
    ),
    (
        "compressor_version_binding",
        splat,
        "version.returncode != 0 or not re.search(",
        "False and re.search(",
        "test_wrong_compressor_version",
    ),
    (
        "carried_pose_manifest",
        splat,
        "_digest_bytes(_canonical(pose_manifest)) != manifest.pose_manifest_digest",
        "False",
        "test_changed_carried_pose_manifest",
    ),
    (
        "accepted_sparse_model",
        splat,
        "observed != expected",
        "False",
        "test_valid_pose_receipt_cannot_authorize_another_sparse_camera_model",
    ),
    (
        "source_camera_mapping",
        splat,
        "declared != actual",
        "False",
        "test_original_hashes_under_other_filenames",
    ),
    (
        "nonmetric_optimization_is_allowed",
        splat,
        "if scale is not None and (",
        "if (",
        "test_nonmetric_optimization_acceptance",
    ),
    (
        "heldout_source_subset",
        splat,
        "not set(self.heldout_source_sha256) < set(self.source_sha256)",
        "False",
        "test_heldout_split_must_name_predeclared",
    ),
    (
        "interrupted_rectification_recovers",
        runner,
        "            shutil.rmtree(prepared)",
        '            raise ValueError("mutant rejects interrupted preprocessing")',
        "test_real_colmap_rectification",
    ),
    (
        "heldout_survives_rectification",
        runner,
        "in heldout_sources",
        "in ()",
        "test_real_colmap_rectification",
    ),
    (
        "rectification_source_binding",
        runner,
        'receipt.get("source_dataset_digest") != source_digest',
        "False",
        "test_real_colmap_rectification",
    ),
    (
        "daemon_stop_confirmation",
        container,
        "                    _stop_owned(docker, cidfile, owner, grace_seconds)",
        "                    pass # mutant skips owned daemon stop",
        "test_stop_signal_uses_daemon_stop",
    ),
    (
        "forced_daemon_kill",
        container,
        '            _control(docker, "kill", container_id)',
        "            pass # mutant omits daemon kill",
        "test_ignored_stop_requires_confirmed_daemon_kill",
    ),
    (
        "container_owner_binding",
        container,
        "or label != owner",
        "or False",
        "test_foreign_container_id_is_never_stopped",
    ),
    (
        "durable_launch_ownership",
        container,
        '    _mark_uncertain(output, owner, "launch active; owned daemon cleanup not yet confirmed")',
        "    pass # mutant fails to persist ownership before launch",
        "test_stop_signal_uses_daemon_stop",
    ),
    (
        "reconciliation_requires_confirmation",
        container,
        "        _stop_owned(docker, cidfile, owner, 10)",
        "        pass # mutant clears recovery guard without daemon confirmation",
        "test_uncertain_daemon_retains_marker",
    ),
    (
        "disconnected_cli_requires_daemon_cleanup",
        container,
        "\n            _stop_owned(docker, cidfile, owner, grace_seconds)",
        "\n            pass # mutant trusts Docker CLI exit",
        "test_exited_cli_cannot_leave_its_daemon_container_running",
    ),
    (
        "stop_request_exit_race",
        container,
        "        if not stopped:",
        "        if requested_at is None:",
        "test_cli_exiting_after_stop_request",
    ),
    (
        "rng_restore",
        runner,
        '    restore_rng(state["rng"])',
        "    pass # mutant omits RNG restoration",
        "test_actual_adam_resume",
    ),
    (
        "adam_restore",
        runner,
        '        optimizer.load_state_dict(state["optimizers"][key])',
        "        pass # mutant omits Adam state",
        "test_actual_adam_resume",
    ),
    (
        "scheduler_restore",
        runner,
        '    scheduler.load_state_dict(state["scheduler"])',
        "    pass # mutant omits schedule state",
        "test_actual_adam_resume",
    ),
    (
        "strategy_save",
        runner,
        '"strategy": strategy_state,',
        '"strategy": {},',
        "test_actual_adam_resume",
    ),
    (
        "sampler_save",
        runner,
        '"sampler": sampler,',
        '"sampler": {"order": [], "cursor": 0},',
        "test_actual_adam_resume",
    ),
    (
        "checkpoint_identity",
        runner,
        'value.get("identity") != identity',
        "False",
        "test_resume_refuses_changed_camera_model_identity",
    ),
    (
        "checkpoint_digest",
        runner,
        '_digest_file(checkpoint) != value.get("sha256")',
        "False",
        "test_resume_refuses_corrupt_checkpoint_bytes",
    ),
    (
        "checkpoint_complete_state",
        runner,
        "not required <= state.keys()",
        "False",
        "test_resume_refuses_evaluation_only_parameter_checkpoint",
    ),
    (
        "sparse_model_binding",
        runner,
        "if p.is_file())",
        'if p.is_file() and "sparse" not in p.parts)',
        "test_dataset_checkpoint_identity_binds_sparse_model_bytes",
    ),
    (
        "metric_definition_binding",
        runner,
        "if value != manifest.as_payload():",
        "if False:",
        "test_manifest_refuses_changed_metric_definition",
    ),
    (
        "cuda_refusal",
        runner,
        "if not torch.cuda.is_available():",
        "if False:",
        "test_cpu_host_cannot_claim_cuda_runtime",
    ),
    (
        "container_digest",
        container,
        "        manifest.execution_image,",
        '        "gsplat:latest",',
        "test_container_uses_exact_digest",
    ),
    (
        "container_readonly",
        container,
        ' + (",readonly" if readonly else "")',
        ' + ""',
        "test_container_uses_exact_digest",
    ),
    (
        "receipt_manifest_binding",
        splat,
        'runtime.get("manifest_digest") != manifest.digest',
        "False",
        "test_runner_receipts_cannot_claim_unbound_or_incomplete_results",
    ),
    (
        "receipt_duration_complete",
        splat,
        'if runtime.get("duration_accounting_complete") is not True:',
        "if False:",
        "test_runner_receipts_cannot_claim_unbound_or_incomplete_results",
    ),
    (
        "receipt_protocol_binding",
        splat,
        'if runtime.get("training_protocol") != TRAINING_PROTOCOL:',
        "if False:",
        "test_runner_receipts_cannot_claim_unbound_or_incomplete_results",
    ),
    (
        "receipt_ply_binding",
        splat,
        'if runtime.get("ply_sha256") != _digest_file(output / "accepted.ply"):',
        "if False:",
        "test_runner_receipts_cannot_claim_unbound_or_incomplete_results",
    ),
    (
        "receipt_backend_inventory",
        splat,
        'if "gsplat" not in normalized:\n        raise ValueError("runtime package inventory omits gsplat")',
        'if False:\n        raise ValueError("runtime package inventory omits gsplat")',
        "test_runner_receipts_cannot_claim_unbound_or_incomplete_results",
    ),
    (
        "receipt_duration_positive",
        splat,
        "if duration <= 0:",
        "if False:",
        "test_runner_receipts_cannot_claim_unbound_or_incomplete_results",
    ),
    (
        "physical_scale_finite",
        splat,
        "        or not math.isfinite(scale)\n",
        "",
        "test_nonfinite_metric_scale_cannot_start_training",
    ),
]
env = dict(os.environ, PYTHONPATH=str(work), PYTHONDONTWRITEBYTECODE="1")
records = []
for name, file, old, new, test in mutants:
    path = work / file
    original = path.read_text()
    if old not in original:
        records.append({"mutation": name, "status": "mutation-target-not-found", "target": old})
        continue
    mutant = original.replace(old, new, 1)
    if name == "checkpoint_identity":
        mutant = mutant.replace('state["identity"] != identity', "False")
    path.write_text(mutant)
    result = subprocess.run(
        [
            str(python),
            "-m",
            "pytest",
            "-q",
            "--confcutdir=" + str(work / "tests"),
            str(work / "tests"),
            "-k",
            test,
        ],
        cwd=work,
        env=env,
        text=True,
        capture_output=True,
    )
    path.write_text(original)
    records.append(
        {
            "mutation": name,
            "production_file": file,
            "test": test,
            "returncode": result.returncode,
            "killed": result.returncode == 1,
            "replace": old,
            "with": new,
            "observed_output_sha256": hashlib.sha256(
                (result.stdout + result.stderr).encode()
            ).hexdigest(),
            "observed_outcome": "targeted regression failed under production mutation"
            if result.returncode == 1
            else "mutation survived or execution failed",
        }
    )
    print(name, result.returncode, flush=True)
record = {
    "profile": "exulanica.gsplat-trainer-negative-controls/v1",
    "date": "2026-09-05",
    "database_access": False,
    "isolated_source_copy": True,
    "records": records,
}
path = root / "docs/evaluation/2026-09-05-gsplat-trainer-negative-controls.json"
path.write_text(
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
print(path.relative_to(root))
if not all(item.get("killed") for item in records):
    raise SystemExit(1)
