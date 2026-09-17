"""The whole Track A pipeline on the operator's Mac, with a stub model, no torch and no weights.

    python -m exulanica_appearance runner dry-run --repository . --out DIR

It builds a stub model's weights manifest from synthetic Hugging Face metadata and a weights
directory to match, stages a job whose target is a real published texture set, runs it through the
same runner the container runs, and checks the results. Everything a rented machine would do happens
except the model: the staged manifest, the weights verification file by file, the tiling schedule,
the deadline, the generation records with a reason for every fixed value, the measurements and the
results manifest.

It also runs the two refusals that matter most, so the dry run shows them failing rather than
claiming they would: a staged directory with one more file than its manifest lists, and a weights
file whose bytes were changed after it was verified.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from exulanica_appearance.canonical import Refused, sha256_hex
from exulanica_appearance.runner.job import JOB_PROFILE
from exulanica_appearance.runner.run import (
    check_results,
    run_job,
    source_sha256,
    weights_directory_name,
)
from exulanica_appearance.runner.staging import stage_texture_job, verify_staged
from exulanica_appearance.weights import (
    MetadataDirectory,
    build_weights,
    git_blob_sha1,
    read_weights,
)

__all__ = ["dry_run"]

REPOSITORY = "exulanica/stub-appearance-model"
REVISION = "0" * 40
_CONFIG = b'{"stub": true}\n'
_WEIGHTS = b"stub weights, not a model: " + bytes(range(256)) * 16


def _metadata(directory: Path) -> MetadataDirectory:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "source.txt").write_text(f"{REPOSITORY}\n{REVISION}\n")
    (directory / "revision.json").write_text(
        json.dumps({"id": REPOSITORY, "sha": REVISION, "cardData": {"license": "apache-2.0"}})
    )
    (directory / "tree.json").write_text(
        json.dumps(
            [
                {
                    "type": "file",
                    "path": "config.json",
                    "size": len(_CONFIG),
                    "oid": git_blob_sha1(_CONFIG),
                },
                {
                    "type": "file",
                    "path": "model/stub.safetensors",
                    "size": len(_WEIGHTS),
                    "oid": "0" * 40,
                    "lfs": {"oid": sha256_hex(_WEIGHTS), "size": len(_WEIGHTS)},
                },
            ]
        )
    )
    (directory / "README.md").write_text("---\nlicense: apache-2.0\n---\n\nA stub, not a model.\n")
    return MetadataDirectory.read(directory)


def _job(weights_sha256: str, target: dict[str, Any]) -> dict[str, Any]:
    reasons = {
        "components.base": "the stub model, which stands in for a real one so the pipeline can run with no GPU",
        "sampler.control_context_scale_milli": "0.80, the value the real candidates use, carried so the record's shape matches",
        "sampler.guidance_milli": "4.0, as the real candidates use",
        "sampler.height": "256, small enough to run in a second on a laptop",
        "sampler.name": "the stub's own loop, which is not a sampler any model ships",
        "sampler.negative_prompt": "a single space, as the real candidates use",
        "sampler.steps": "12 steps, enough for the tiling schedule to roll the grid many times",
        "sampler.tiling": "the lane's tiling schedule, the thing this dry run exercises",
        "sampler.width": "256, small enough to run in a second on a laptop",
        "sampler.wrap_margin_px": "64 px, as the real candidates use",
        "seconds_per_image": "one second: the stub is arithmetic, not a model",
    }
    return {
        "candidates": [
            {
                "backend": "stub",
                "components": [{"role": "base", "subfolder": "", "weights_sha256": weights_sha256}],
                "id": "stub",
                "reasons": reasons,
                "sampler": {
                    "control_context_scale_milli": 800,
                    "guidance_milli": 4000,
                    "height": 256,
                    "name": "stub-loop",
                    "negative_prompt": " ",
                    "steps": 12,
                    "tiling": "exulanica.appearance-tiling/v1",
                    "width": 256,
                    "wrap_margin_px": 64,
                },
                "seconds_per_image": 1,
            }
        ],
        "estimate_seconds": 60,
        "name": "track-a-dry-run",
        "reasons": {
            "estimate_seconds": "a minute is far more than the stub needs; the stop is what this exercises, not the time",
            "seeds_per_target": "two seeds, enough to see that the seed reaches the output",
        },
        "seeds_per_target": 2,
        "targets": [target],
    }


def dry_run(repository: Path, out: Path) -> dict[str, Any]:
    """Stage, run and check a stub job under ``out``; return a summary, or refuse."""
    out.mkdir(parents=True, exist_ok=True)
    metadata = _metadata(out / "hf-metadata" / f"stub@{REVISION}")
    manifest = build_weights(
        {
            "repository": REPOSITORY,
            "revision": REVISION,
            "include": ["config.json", "model/*"],
            "reason": "everything the stub loads, which is nothing: it reads the files to prove they verify",
            "lineage": [],
        },
        "2026-09-17",
        {(REPOSITORY, REVISION): metadata},
    )
    weights_root = out / "weights"
    directory = weights_root / weights_directory_name(read_weights(manifest))
    (directory / "model").mkdir(parents=True, exist_ok=True)
    (directory / "config.json").write_bytes(_CONFIG)
    (directory / "model" / "stub.safetensors").write_bytes(_WEIGHTS)

    texture_manifest = json.loads(
        (repository / "assets" / "textures" / "manifest.json").read_bytes()
    )
    entry = next(
        item for item in texture_manifest["sets"] if item["set_id"] == "cc0.brick-running-bond"
    )
    target = {
        "conditioning": ["depth", "edge"],
        "id": "brick-weathered",
        "prompt": "Seamless tileable texture. A stub picture, not a look: this run tests the pipeline, not a model.",
        "reasons": {
            "prompt": "a stated stand-in, so nothing reads this picture as a candidate texture",
            "conditioning.depth": "the set's own height map: the recipe's exact relief",
            "conditioning.edge": "the recipe's joint outlines from the same height map",
        },
        "set": {
            "content_sha256": entry["content_sha256"],
            "set_id": entry["set_id"],
            "version": entry["version"],
        },
    }
    staged = out / "staged"
    staged_manifest = stage_texture_job(
        repository=repository,
        job=_job(sha256_hex(manifest), target),
        weights_manifests={sha256_hex(manifest): manifest},
        out=staged,
    )

    refusals = {}
    intruder = staged / "conditioning" / "brick-weathered" / "not-listed.png"
    intruder.write_bytes(b"not staged")
    try:
        verify_staged(staged)
        raise Refused("a file the staged manifest does not list was accepted")
    except Refused as refusal:
        refusals["an unlisted file in the staged directory"] = str(refusal)
    intruder.unlink()

    kept = (directory / "config.json").read_bytes()
    # The same length, so the sha256 or git blob id is what refuses it, not the size.
    (directory / "config.json").write_bytes(b'{"stub": TRUE}\n')
    try:
        run_job(
            staged=staged,
            weights_root=weights_root,
            out=out / "refused-run",
            backend_factory=lambda candidate, directories: None,  # type: ignore[arg-type,return-value]
            code_commit="0" * 40,
            container_image=f"stub@sha256:{'0' * 64}",
            log=lambda _: None,
        )
        raise Refused("a changed weights file was accepted")
    except Refused as refusal:
        refusals["a weights file changed after its manifest was written"] = str(refusal)
    (directory / "config.json").write_bytes(kept)

    from exulanica_appearance.runner.run import make_backend

    results_raw = run_job(
        staged=staged,
        weights_root=weights_root,
        out=out / "run",
        backend_factory=make_backend,
        code_commit=_commit(repository),
        container_image=f"stub@sha256:{source_sha256(Path(__file__).resolve().parents[1])}",
    )
    results = check_results(out / "run")
    return {
        "job_profile": JOB_PROFILE,
        "refusals": refusals,
        "results_sha256": sha256_hex(results_raw),
        "staged_sha256": sha256_hex(staged_manifest),
        "summary": results,
    }


def _commit(repository: Path) -> str:
    """This checkout's HEAD, asked of git, because a worktree's .git is a file, not a directory."""
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
