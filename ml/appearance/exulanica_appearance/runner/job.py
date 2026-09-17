"""``exulanica.appearance-texture-job/v1``: everything a Track A session will run, fixed before it runs.

A job names the texture manifest it read, its candidates (a backend, its weights components by
manifest digest, its sampler settings and an estimate of seconds per image), its targets (a pinned
texture set, the prompt and the conditioning roles), how many seeds each target gets and the rule
that derives them, the conditioning pictures by digest, and the session's estimate and stop at 150
per cent. Every fixed value carries its reason, and the reader refuses a job that leaves one out.

The generations are the job's cross product, in a fixed order: target, then candidate, then
conditioning role, then seed index. The runner derives nothing else.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
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

__all__ = [
    "BACKENDS",
    "JOB_PROFILE",
    "Generation",
    "build_job",
    "generations",
    "read_job",
    "seed_for",
]

JOB_PROFILE: Final = "exulanica.appearance-texture-job/v1"
BACKENDS: Final = ("stub", "videox-qwenimage-fun-control", "videox-zimage-fun-control")
SAMPLER_KEYS: Final = (
    "control_context_scale_milli",
    "guidance_milli",
    "height",
    "name",
    "negative_prompt",
    "steps",
    "tiling",
    "width",
    "wrap_margin_px",
)
_ID: Final = re.compile(r"[a-z][a-z0-9-]*")
_KEYS: Final = (
    "candidates",
    "estimate_seconds",
    "inputs",
    "name",
    "profile",
    "reasons",
    "seed_rule",
    "seeds_per_target",
    "stop_at_seconds",
    "targets",
    "texture_manifest_sha256",
    "truth",
)
SEED_RULE: Final = (
    "the first four bytes, big-endian, of sha256 of "
    "'exulanica.appearance-seed/v1:<job>:<target>:<candidate>:<role>:<index>'"
)
JOB_REASONS: Final = ("estimate_seconds", "seeds_per_target")


def seed_for(job: str, target: str, candidate: str, role: str, index: int) -> int:
    text = f"exulanica.appearance-seed/v1:{job}:{target}:{candidate}:{role}:{index}"
    return int.from_bytes(hashlib.sha256(text.encode("ascii")).digest()[:4], "big")


@dataclass(frozen=True, slots=True)
class Generation:
    number: int
    target: Mapping[str, Any]
    candidate: Mapping[str, Any]
    role: str
    index: int
    seed: int
    input: Mapping[str, Any]


def generations(job: Mapping[str, Any]) -> Iterator[Generation]:
    inputs = {(item["target"], item["role"]): item for item in job["inputs"]}
    number = 0
    for target in job["targets"]:
        for candidate in job["candidates"]:
            for role in target["conditioning"]:
                for index in range(job["seeds_per_target"]):
                    yield Generation(
                        number=number,
                        target=target,
                        candidate=candidate,
                        role=role,
                        index=index,
                        seed=seed_for(job["name"], target["id"], candidate["id"], role, index),
                        input=inputs[(target["id"], role)],
                    )
                    number += 1


def build_job(document: Mapping[str, Any]) -> bytes:
    full = dict(document)
    full["seed_rule"] = SEED_RULE
    full["stop_at_seconds"] = full["estimate_seconds"] * 3 // 2
    full["truth"] = "invented"
    full["profile"] = JOB_PROFILE
    raw = canonical_bytes(full)
    read_job(raw)
    return raw


def _reasons(reasons: object, expected: set[str], where: str) -> None:
    if (
        not isinstance(reasons, dict)
        or set(reasons) != expected
        or not all(is_text(v) for v in reasons.values())
    ):
        given = set(reasons) if isinstance(reasons, dict) else set()
        raise Refused(
            f"{where}: reasons give exactly one reason for {sorted(expected)}; "
            f"missing {sorted(expected - given)}, unexpected {sorted(given - expected)}"
        )


def read_job(raw: bytes) -> dict[str, Any]:
    where = "the texture job"
    job = exact_keys(parse_canonical(raw, where), _KEYS, where)
    if job["profile"] != JOB_PROFILE or job["truth"] != "invented":
        raise Refused(f"{where}: profile is {JOB_PROFILE} and truth is invented")
    if not isinstance(job["name"], str) or not _ID.fullmatch(job["name"]):
        raise Refused(f"{where}: name is lowercase words joined by hyphens")
    if job["seed_rule"] != SEED_RULE:
        raise Refused(f"{where}: seed_rule is the one rule the runner applies")
    if not is_sha256(job["texture_manifest_sha256"]):
        raise Refused(f"{where}: texture_manifest_sha256 is 64 lowercase hex")
    if not is_count(job["seeds_per_target"], 1) or not is_count(job["estimate_seconds"], 1):
        raise Refused(f"{where}: seeds_per_target and estimate_seconds are positive")
    if job["stop_at_seconds"] != job["estimate_seconds"] * 3 // 2:
        raise Refused(f"{where}: stop_at_seconds is 150 per cent of estimate_seconds")
    _reasons(job["reasons"], set(JOB_REASONS), where)

    candidate_ids = []
    for candidate in job["candidates"]:
        at = f"{where}: candidate"
        exact_keys(
            candidate,
            ("backend", "components", "id", "reasons", "sampler", "seconds_per_image"),
            at,
        )
        if not isinstance(candidate["id"], str) or not _ID.fullmatch(candidate["id"]):
            raise Refused(f"{at} id is lowercase words joined by hyphens")
        if candidate["backend"] not in BACKENDS:
            raise Refused(f"{at} {candidate['id']}: backend is one of {', '.join(BACKENDS)}")
        if not is_count(candidate["seconds_per_image"], 1):
            raise Refused(f"{at} {candidate['id']}: seconds_per_image is a positive estimate")
        roles = []
        for component in candidate["components"]:
            exact_keys(component, ("role", "subfolder", "weights_sha256"), f"{at} component")
            if not is_sha256(component["weights_sha256"]) or not _ID.fullmatch(component["role"]):
                raise Refused(
                    f"{at} {candidate['id']}: a component is a role and a weights manifest digest"
                )
            roles.append(component["role"])
        if not roles or roles != sorted(set(roles)):
            raise Refused(f"{at} {candidate['id']}: components are sorted by role, each once")
        sampler = exact_keys(candidate["sampler"], SAMPLER_KEYS, f"{at} {candidate['id']} sampler")
        for key in SAMPLER_KEYS:
            value = sampler[key]
            if key in ("name", "negative_prompt", "tiling"):
                if (
                    not isinstance(value, str)
                    or not value
                    or not all(0x20 <= ord(c) <= 0x7E for c in value)
                ):
                    raise Refused(f"{at} {candidate['id']}: sampler {key} is printable ASCII")
            elif not is_count(value, 0):
                raise Refused(f"{at} {candidate['id']}: sampler {key} is a non-negative integer")
        if sampler["width"] % 16 or sampler["height"] % 16 or sampler["wrap_margin_px"] % 16:
            raise Refused(
                f"{at} {candidate['id']}: width, height and wrap margin are whole tokens of 16 px"
            )
        _reasons(
            candidate["reasons"],
            {f"components.{role}" for role in roles}
            | {f"sampler.{key}" for key in SAMPLER_KEYS}
            | {"seconds_per_image"},
            f"{at} {candidate['id']}",
        )
        candidate_ids.append(candidate["id"])
    if not candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
        raise Refused(f"{where}: candidates have distinct ids")

    target_ids = []
    for target in job["targets"]:
        at = f"{where}: target"
        exact_keys(target, ("conditioning", "id", "prompt", "reasons", "recipe_sha256", "set"), at)
        if not is_sha256(target["recipe_sha256"]):
            raise Refused(
                f"{at}: recipe_sha256 is the recipe object the kept maps are rebakeable from"
            )
        if not isinstance(target["id"], str) or not _ID.fullmatch(target["id"]):
            raise Refused(f"{at} id is lowercase words joined by hyphens")
        pinned = exact_keys(
            target["set"], ("content_sha256", "set_id", "version"), f"{at} {target['id']} set"
        )
        if (
            not is_sha256(pinned["content_sha256"])
            or not is_text(pinned["set_id"])
            or not is_count(pinned["version"], 1)
        ):
            raise Refused(f"{at} {target['id']}: set names a pinned texture set")
        if not is_text(target["prompt"]):
            raise Refused(f"{at} {target['id']}: prompt is printable ASCII")
        roles = target["conditioning"]
        if (
            not isinstance(roles, list)
            or not roles
            or roles != sorted(set(roles))
            or not all(r in ("depth", "edge", "gray") for r in roles)
        ):
            raise Refused(
                f"{at} {target['id']}: conditioning is a sorted list of depth, edge and gray"
            )
        _reasons(
            target["reasons"],
            {"prompt"} | {f"conditioning.{role}" for role in roles},
            f"{at} {target['id']}",
        )
        target_ids.append(target["id"])
    if not target_ids or len(set(target_ids)) != len(target_ids):
        raise Refused(f"{where}: targets have distinct ids")

    expected_inputs = {(t["id"], role) for t in job["targets"] for role in t["conditioning"]}
    seen = set()
    for item in job["inputs"]:
        at = f"{where}: input"
        exact_keys(
            item,
            (
                "encoding",
                "file",
                "file_sha256",
                "parameters",
                "pixels_sha256",
                "role",
                "source_sha256",
                "target",
            ),
            at,
        )
        if not all(is_sha256(item[k]) for k in ("file_sha256", "pixels_sha256", "source_sha256")):
            raise Refused(f"{at}: an input names its file, pixels and source by sha256")
        if (
            not isinstance(item["file"], str)
            or not item["file"].startswith("conditioning/")
            or ".." in item["file"]
        ):
            raise Refused(f"{at}: file is a path under conditioning/")
        if not isinstance(item["parameters"], dict):
            raise Refused(f"{at}: parameters is an object")
        seen.add((item["target"], item["role"]))
    if seen != expected_inputs or len(job["inputs"]) != len(expected_inputs):
        raise Refused(f"{where}: inputs are exactly one picture per target and conditioning role")
    sources = {t["id"]: t["set"]["content_sha256"] for t in job["targets"]}
    for item in job["inputs"]:
        if item["source_sha256"] != sources[item["target"]]:
            raise Refused(f"{where}: an input's source is its target's pinned set")
    return job
