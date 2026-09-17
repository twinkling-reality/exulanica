"""Run a staged texture job: verify everything, then generate, record and measure, and stop in time.

The order is fixed and each step refuses before the next begins:

1. The staged directory holds exactly the files its manifest lists, with their digests
   (``staging.verify_staged``), and the job reads as a job.
2. Every weights file every candidate names is present with its size and sha256 or git blob id
   (``weights.verify_directory``), for all candidates, before any backend is built. No model code is
   imported until then.
3. For each generation, in the job's fixed order: if the time run so far plus that candidate's
   estimate per image would pass the job's stop at 150 per cent of its estimate, the run stops,
   says so, and starts nothing more. Otherwise the backend generates, the output's raw RGB bytes are
   stored by sha256 with a PNG beside them for people, the tile is measured (seams, low-frequency
   share), and a generation record is written.
4. A results manifest lists every record, output and measurement, what was verified, and whether and
   why the run stopped.

What leaves the machine is the output directory: raw outputs, PNG previews, generation records, the
results manifest and the run log. Weights and staged inputs never leave; they came from elsewhere.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from exulanica_appearance.canonical import Refused, canonical_bytes, sha256_hex
from exulanica_appearance.generation import build_generation
from exulanica_appearance.metrics.textures import low_frequency_share_ppm, seam_ratio_ppm
from exulanica_appearance.runner.job import generations
from exulanica_appearance.runner.relief import RELIEF_ENCODINGS
from exulanica_appearance.runner.staging import verify_staged
from exulanica_appearance.weights import read_weights, verify_directory

__all__ = [
    "RESULTS_PROFILE",
    "Backend",
    "check_results",
    "make_backend",
    "run_job",
    "source_sha256",
    "weights_directory_name",
]

RESULTS_PROFILE: Final = "exulanica.appearance-results/v1"
GUARDRAILS_REASON: Final = (
    "these models ship no guardrail, and their only inputs are a committed texture set's own "
    "relief and a prompt written from the catalog, with no people and nothing personal"
)


class Backend(Protocol):
    name: str

    def runtime(self) -> dict[str, Any]: ...

    def generate(
        self, *, prompt: str, conditioning: NDArray[np.uint8], seed: int, sampler: Mapping[str, Any]
    ) -> NDArray[np.uint8]: ...


def make_backend(candidate: Mapping[str, Any], directories: Mapping[str, Path]) -> Backend:
    """The backend a candidate names. Model libraries are imported here and nowhere earlier."""
    backend = candidate["backend"]
    if backend == "stub":
        from exulanica_appearance.runner.backends.stub import StubBackend

        return StubBackend(candidate)
    if backend == "videox-qwenimage-fun-control":
        from exulanica_appearance.runner.backends.videox import QwenImageFunControl

        return QwenImageFunControl(candidate, directories)
    if backend == "videox-zimage-fun-control":
        from exulanica_appearance.runner.backends.videox import ZImageFunControl

        return ZImageFunControl(candidate, directories)
    raise Refused(f"no backend is named {backend!r}")


def weights_directory_name(manifest: Mapping[str, Any]) -> str:
    """Where ``scripts/fetch-weights.py`` puts a repository at a revision under the weights root."""
    return f"{manifest['repository'].replace('/', '__')}@{manifest['revision']}"


def source_sha256(package: Path) -> str:
    """The digest of this package's Python source: every ``.py`` file by path and sha256."""
    listing = {
        str(path.relative_to(package.parent)): sha256_hex(path.read_bytes())
        for path in sorted(package.rglob("*.py"))
    }
    return sha256_hex(canonical_bytes(listing))


def _instant(clock: Callable[[], float]) -> str:
    return datetime.fromtimestamp(clock(), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_job(
    *,
    staged: Path,
    weights_root: Path,
    out: Path,
    backend_factory: Callable[[Mapping[str, Any], Mapping[str, Path]], Backend],
    code_commit: str,
    container_image: str,
    wall_clock: Callable[[], float] = time.time,
    elapsed: Callable[[], float] | None = None,
    log: Callable[[str], None] = print,
) -> bytes:
    started = time.monotonic()
    elapsed = elapsed or (lambda: time.monotonic() - started)
    if out.exists() and any(out.iterdir()):
        raise Refused(f"{out} is not empty; a run writes a fresh directory")
    out.mkdir(parents=True, exist_ok=True)
    manifest, job = verify_staged(staged)
    log(f"staged inputs verified: job {manifest['job_sha256']}")

    verified = []
    directories: dict[str, Path] = {}
    pinned: dict[str, dict[str, str]] = {}
    for digest in sorted(
        {c["weights_sha256"] for cand in job["candidates"] for c in cand["components"]}
    ):
        raw = (staged / "weights" / f"{digest}.json").read_bytes()
        weights = read_weights(raw)
        directory = weights_root / weights_directory_name(weights)
        began = elapsed()
        checked = verify_directory(raw, directory)
        directories[digest] = directory
        pinned[digest] = {"id": weights["repository"], "revision": weights["revision"]}
        verified.append(
            {"bytes": checked, "seconds": int(elapsed() - began), "weights_sha256": digest}
        )
        log(f"weights verified: {weights['repository']}@{weights['revision'][:12]} {checked} bytes")

    package = Path(__file__).resolve().parents[1]
    code = {"commit": code_commit, "source_sha256": source_sha256(package)}
    for directory in ("outputs", "previews", "records"):
        (out / directory).mkdir()
    backends: dict[str, Backend] = {}
    produced = []
    stopped = ""
    for generation in generations(job):
        candidate = generation.candidate
        if elapsed() + candidate["seconds_per_image"] > job["stop_at_seconds"]:
            stopped = (
                f"stopped before generation {generation.number}: {int(elapsed())} s run plus "
                f"{candidate['seconds_per_image']} s estimated per image would pass the stop at "
                f"{job['stop_at_seconds']} s"
            )
            log(stopped)
            break
        if candidate["id"] not in backends:
            began = elapsed()
            backends[candidate["id"]] = backend_factory(
                candidate,
                {c["role"]: directories[c["weights_sha256"]] for c in candidate["components"]},
            )
            log(f"backend {candidate['id']} built in {int(elapsed() - began)} s")
        backend = backends[candidate["id"]]
        item = generation.input
        with Image.open(staged / item["file"]) as picture:
            conditioning = np.asarray(picture.convert("RGB"))
        if (
            hashlib.sha256(np.ascontiguousarray(conditioning).tobytes()).hexdigest()
            != item["pixels_sha256"]
        ):
            raise Refused(f"{item['file']} does not decode to the pixels the job names")

        start_instant = _instant(wall_clock)
        began = elapsed()
        rgb = backend.generate(
            prompt=generation.target["prompt"],
            conditioning=conditioning,
            seed=generation.seed,
            sampler=candidate["sampler"],
        )
        seconds = int(elapsed() - began)
        sampler = candidate["sampler"]
        if rgb.shape != (sampler["height"], sampler["width"], 3) or rgb.dtype != np.uint8:
            raise Refused(
                f"backend {candidate['id']} returned {rgb.shape} {rgb.dtype}, not the sampler's RGB8 size"
            )
        raw_output = np.ascontiguousarray(rgb).tobytes()
        output_sha256 = sha256_hex(raw_output)
        (out / "outputs" / f"{output_sha256}.rgb").write_bytes(raw_output)
        Image.fromarray(rgb).save(out / "previews" / f"{output_sha256}.png")

        reasons = {
            f"components.{c['role']}": candidate["reasons"][f"components.{c['role']}"]
            for c in candidate["components"]
        }
        reasons |= {f"sampler.{key}": candidate["reasons"][f"sampler.{key}"] for key in sampler}
        reasons |= {
            f"conditioning.{generation.role}": generation.target["reasons"][
                f"conditioning.{generation.role}"
            ]
            + "; encoding: "
            + RELIEF_ENCODINGS[generation.role]["reason"],
            "container": "the image this lane built from its committed recipe, pinned by digest",
            "guardrails": GUARDRAILS_REASON,
            "inputs": generation.target["reasons"]["prompt"],
            "seed": f"seed index {generation.index} of {job['seeds_per_target']} by the job's seed rule: {job['seed_rule']}",
        }
        record = build_generation(
            {
                "code": code,
                "components": [
                    dict(c) | pinned[c["weights_sha256"]] for c in candidate["components"]
                ],
                "conditioning": [
                    {
                        "encoding": item["encoding"],
                        "file_sha256": item["file_sha256"],
                        "parameters": dict(item["parameters"]),
                        "pixels_sha256": item["pixels_sha256"],
                        "role": generation.role,
                        "sources": [item["source_sha256"]],
                    }
                ],
                "container": {"image": container_image},
                "finished_at": _instant(wall_clock),
                "generated": True,
                "guardrails": {"enabled": False},
                "inputs": {"prompt": generation.target["prompt"]},
                "outputs": [
                    {
                        "byte_length": len(raw_output),
                        "media_type": "application/vnd.exulanica.rgb8",
                        "role": "base-color",
                        "sha256": output_sha256,
                    }
                ],
                "profile": "exulanica.appearance-generation/v1",
                "reasons": reasons,
                "runtime": backend.runtime(),
                "sampler": dict(sampler),
                "seed": generation.seed,
                "started_at": start_instant,
                "track": "texture",
                "truth": "invented",
            }
        )
        record_sha256 = sha256_hex(record)
        (out / "records" / f"{record_sha256}.json").write_bytes(record)
        produced.append(
            {
                "candidate": candidate["id"],
                "index": generation.index,
                "low_frequency_share_ppm": low_frequency_share_ppm(rgb),
                "number": generation.number,
                "output_sha256": output_sha256,
                "record_sha256": record_sha256,
                "role": generation.role,
                "seams_ppm": seam_ratio_ppm(rgb),
                "seconds": seconds,
                "seed": generation.seed,
                "target": generation.target["id"],
            }
        )
        log(
            f"generation {generation.number} {candidate['id']} {generation.target['id']} {generation.role} seed {generation.seed}: {seconds} s, seams {produced[-1]['seams_ppm']}"
        )

    results = canonical_bytes(
        {
            "elapsed_seconds": int(elapsed()),
            "generations": produced,
            "job_sha256": manifest["job_sha256"],
            "profile": RESULTS_PROFILE,
            "stopped": stopped,
            "verified_weights": verified,
        }
    )
    (out / "results.json").write_bytes(results)
    return results


def check_results(out: Path) -> dict[str, Any]:
    """On the Mac, after the pull: every record and output the results name is present and intact."""
    from exulanica_appearance.canonical import parse_canonical
    from exulanica_appearance.generation import read_generation

    results = parse_canonical((out / "results.json").read_bytes(), "the results manifest")
    if results.get("profile") != RESULTS_PROFILE:
        raise Refused(f"the results manifest is not {RESULTS_PROFILE}")
    for item in results["generations"]:
        record_raw = (out / "records" / f"{item['record_sha256']}.json").read_bytes()
        if sha256_hex(record_raw) != item["record_sha256"]:
            raise Refused(f"record {item['record_sha256']} does not have its sha256")
        record = read_generation(record_raw)
        output_raw = (out / "outputs" / f"{item['output_sha256']}.rgb").read_bytes()
        if (
            sha256_hex(output_raw) != item["output_sha256"]
            or record["outputs"][0]["sha256"] != item["output_sha256"]
        ):
            raise Refused(f"output {item['output_sha256']} does not match its record")
    return results
