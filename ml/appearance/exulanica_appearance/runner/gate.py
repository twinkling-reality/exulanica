"""``exulanica.appearance-smoke-gate/v1``: does the smoke run let the session continue?

The orchestrator's condition is that a broken setup costs one smoke job rather than sixty-four
generations, and that the lane does not pay for a rented machine to wait for an answer. So the pass
conditions are fixed here, machine-checkable, and applied by the runner itself the moment the smoke
run ends. Every one must hold to continue:

1. **Both backends loaded**: every candidate the job names produced at least one output.
2. **Every output decoded at the size the job names**: the stored bytes are exactly
   width times height times three, and the record says the same.
3. **The seam ratio was computed on each**: both axes, for every generation.
4. **Seconds per image within 150 per cent** of that candidate's estimate.
5. **No refusal anywhere in the run**: the results exist, nothing stopped the run, and the number of
   generations is the job's whole cross product.
6. **Spend within the smoke budget**: the instance's billed seconds so far are inside the budget the
   session plan states.
7. **No fallback of any kind**: every record's runtime names an NVIDIA device and a CUDA version, so
   nothing ran on the CPU. The GPU backends also refuse at load time if the device, the dtype or the
   weights are not what the job named, which is where a substituted weight or a smaller dtype would
   be caught.

If every check holds the runner continues to the next job. If any fails, or anything surprises the
lane, the machine is deleted and the report says which branch was taken and why.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Final

from exulanica_appearance.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    is_sha256,
    is_text,
    parse_canonical,
)
from exulanica_appearance.generation import read_generation
from exulanica_appearance.gpu_run import cost_microdollars
from exulanica_appearance.runner.job import generations

__all__ = ["CHECKS", "GATE_PROFILE", "read_gate", "smoke_gate"]

GATE_PROFILE: Final = "exulanica.appearance-smoke-gate/v1"
CHECKS: Final = (
    "backends_loaded",
    "no_fallback",
    "no_refusal",
    "outputs_decoded_at_size",
    "seam_ratio_computed",
    "seconds_within_estimate",
    "spend_within_budget",
)
TOLERANCE_PERMILLE: Final = 1500


def smoke_gate(
    *,
    results_raw: bytes,
    job: Mapping[str, Any],
    records: Mapping[str, bytes],
    billed_seconds: int,
    budget_seconds: int,
    rate_cents_per_hour: int,
) -> bytes:
    """Apply every pass condition to a finished smoke run; the record says whether to continue."""
    results = parse_canonical(results_raw, "the results manifest")
    produced = results["generations"]
    checks: dict[str, dict[str, Any]] = {}

    def check(name: str, passed: bool, detail: str) -> None:
        checks[name] = {"detail": detail, "passed": bool(passed)}

    expected = len(list(generations(job)))
    ran = {item["candidate"] for item in produced}
    named = {candidate["id"] for candidate in job["candidates"]}
    check(
        "backends_loaded",
        ran == named,
        f"candidates that produced an output: {sorted(ran) or 'none'}; the job names {sorted(named)}",
    )
    check(
        "no_refusal",
        results["stopped"] == "" and len(produced) == expected,
        f"{len(produced)} of {expected} generations ran; stopped: {results['stopped'] or 'no'}",
    )

    sizes = {candidate["id"]: candidate["sampler"] for candidate in job["candidates"]}
    estimates = {candidate["id"]: candidate["seconds_per_image"] for candidate in job["candidates"]}
    wrong_size = []
    missing_seams = []
    slow = []
    on_cpu = []
    for item in produced:
        sampler = sizes[item["candidate"]]
        record = read_generation(records[item["record_sha256"]])
        (output,) = record["outputs"]
        if (
            output["byte_length"] != sampler["width"] * sampler["height"] * 3
            or output["sha256"] != item["output_sha256"]
        ):
            wrong_size.append(item["record_sha256"][:12])
        seams = item.get("seams_ppm") or {}
        if not all(is_count(seams.get(axis)) for axis in ("u", "v")) or not is_count(
            item.get("low_frequency_share_ppm")
        ):
            missing_seams.append(item["record_sha256"][:12])
        if item["seconds"] * 1000 > estimates[item["candidate"]] * TOLERANCE_PERMILLE:
            slow.append(
                f"{item['record_sha256'][:12]} took {item['seconds']} s against {estimates[item['candidate']]} s"
            )
        runtime = record["runtime"]
        if "NVIDIA" not in runtime["hardware"] or runtime["cuda"].lower() in ("none", "null", ""):
            on_cpu.append(
                f"{item['record_sha256'][:12]} ran on {runtime['hardware']!r} with CUDA {runtime['cuda']!r}"
            )

    check(
        "outputs_decoded_at_size",
        not wrong_size,
        f"outputs of the wrong size: {wrong_size or 'none'}",
    )
    check(
        "seam_ratio_computed",
        not missing_seams,
        f"generations without both seam axes: {missing_seams or 'none'}",
    )
    check(
        "seconds_within_estimate",
        not slow,
        f"over 150 per cent of the estimate: {slow or 'none'}",
    )
    check(
        "no_fallback",
        not on_cpu,
        f"records whose runtime is not an NVIDIA device: {on_cpu or 'none'}",
    )
    check(
        "spend_within_budget",
        billed_seconds <= budget_seconds,
        f"{billed_seconds} s billed against a budget of {budget_seconds} s, "
        f"about ${cost_microdollars(rate_cents_per_hour, billed_seconds) // 10_000 / 100:.2f} at "
        f"{rate_cents_per_hour} cents an hour",
    )

    passed = all(entry["passed"] for entry in checks.values())
    document = {
        "billed_seconds": billed_seconds,
        "budget_seconds": budget_seconds,
        "checks": checks,
        "continue": passed,
        "job_sha256": results["job_sha256"],
        "profile": GATE_PROFILE,
        "results_sha256": hashlib.sha256(results_raw).hexdigest(),
    }
    raw = canonical_bytes(document)
    read_gate(raw)
    return raw


def read_gate(raw: bytes) -> dict[str, Any]:
    where = "the smoke gate record"
    document = exact_keys(
        parse_canonical(raw, where),
        (
            "billed_seconds",
            "budget_seconds",
            "checks",
            "continue",
            "job_sha256",
            "profile",
            "results_sha256",
        ),
        where,
    )
    if document["profile"] != GATE_PROFILE:
        raise Refused(f"{where}: profile is {GATE_PROFILE}")
    if not is_sha256(document["job_sha256"]) or not is_sha256(document["results_sha256"]):
        raise Refused(f"{where}: the job and the results are named by sha256")
    if not is_count(document["billed_seconds"]) or not is_count(document["budget_seconds"], 1):
        raise Refused(f"{where}: billed_seconds and budget_seconds are whole seconds")
    checks = document["checks"]
    if not isinstance(checks, dict) or tuple(sorted(checks)) != CHECKS:
        raise Refused(f"{where}: checks are exactly {', '.join(CHECKS)}")
    for name, entry in checks.items():
        item = exact_keys(entry, ("detail", "passed"), f"{where}: check {name}")
        if not isinstance(item["passed"], bool) or not is_text(item["detail"]):
            raise Refused(f"{where}: check {name} says whether it passed and what it saw")
    if document["continue"] is not all(entry["passed"] for entry in checks.values()):
        raise Refused(f"{where}: continue is true only when every check passed")
    return document
