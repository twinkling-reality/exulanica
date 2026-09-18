"""``exulanica.appearance-staged-inputs/v1``: the only directory a rented machine receives.

Staging runs on the operator's Mac. It reads the committed texture manifest, holds every target's
container to its pinned sha256, derives the conditioning pictures from each set's own relief, copies
the weights manifests the job names, writes the job, and lists every file with its size, sha256,
kind and source in ``staged.json``. Three kinds exist and no other is accepted:

- ``job``: the job record;
- ``weights-manifest``: an ``appearance-weights`` manifest the job names;
- ``conditioning``: a picture derived from a committed, invented texture set, whose sha256 is its
  source and must be pinned by the committed texture manifest.

Nothing personal can enter: no photograph, capture or workspace file has a kind, and staging refuses
a conditioning source the committed manifest does not pin. The machine, before anything else, checks
the directory holds exactly the listed files with exactly those digests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import numpy as np
from PIL import Image

from exulanica_appearance.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    is_sha256,
    parse_canonical,
    sha256_hex,
)
from exulanica_appearance.containers import read_container
from exulanica_appearance.runner import relief
from exulanica_appearance.runner.job import build_job, read_job
from exulanica_appearance.weights import read_weights

__all__ = ["STAGED_PROFILE", "stage_texture_job", "verify_staged"]

STAGED_PROFILE: Final = "exulanica.appearance-staged-inputs/v1"
MANIFEST_NAME: Final = "staged.json"
KINDS: Final = ("conditioning", "job", "weights-manifest")


def _png(path: Path, pixels: np.ndarray) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels).save(path, format="PNG")
    return (
        hashlib.sha256(np.ascontiguousarray(pixels).tobytes()).hexdigest(),
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _picture(role: str, maps: Mapping[str, np.ndarray], target: str) -> np.ndarray:
    if role == "depth":
        picture = relief.relief_depth(maps["height"])
    elif role == "edge":
        picture = relief.relief_edges(maps["height"])
    elif role == "gray":
        picture = relief.relief_gray(maps["base_color"])
    else:
        raise Refused(f"there is no conditioning role {role!r}")
    if int(picture.max()) == int(picture.min()):
        # MEASURED 2026-09-18: cc0.storefront-metal's edge picture is every pixel black, because the
        # recipe's relief is a 1 mm field of brush lines with no step a crease or plane test can
        # find. Conditioning on one flat colour is conditioning on nothing: the model would invent
        # the whole surface and the record would still say it was given this target's structure.
        raise Refused(
            f"the conditioning picture for {target} as {role} is one flat value "
            f"({int(picture.min())}); that structure has nothing this role can show, so this role "
            "is not available for this target"
        )
    return picture


def stage_texture_job(
    *,
    repository: Path,
    job: Mapping[str, Any],
    weights_manifests: Mapping[str, bytes],
    out: Path,
) -> bytes:
    """Stage ``job`` (without its inputs, which staging derives) into the empty directory ``out``."""
    if out.exists() and any(out.iterdir()):
        raise Refused(f"{out} is not empty; a staged directory is written once")
    texture_manifest_raw = (repository / "assets" / "textures" / "manifest.json").read_bytes()
    pinned = {entry["content_sha256"]: entry for entry in json.loads(texture_manifest_raw)["sets"]}
    catalog = json.loads((repository / "assets" / "textures" / "catalog.json").read_bytes())
    receipts = {entry["content_sha256"]: entry["receipt_sha256"] for entry in catalog["sets"]}
    files: list[dict[str, Any]] = []
    inputs = []
    targets = []
    for target in job["targets"]:
        entry = pinned.get(target["set"]["content_sha256"])
        if (
            entry is None
            or entry["set_id"] != target["set"]["set_id"]
            or entry["version"] != target["set"]["version"]
        ):
            raise Refused(
                f"target {target['id']}: its set is not pinned by the committed texture manifest"
            )
        receipt_sha256 = receipts.get(entry["content_sha256"])
        if receipt_sha256 is None:
            raise Refused(
                f"target {target['id']}: the committed catalog holds no bake receipt for its set"
            )
        receipt = json.loads(
            (repository / "assets" / "textures" / "objects" / f"{receipt_sha256}.json").read_bytes()
        )
        if receipt.get("content_sha256") != entry["content_sha256"]:
            raise Refused(f"target {target['id']}: its bake receipt names another set's bytes")
        targets.append({**target, "recipe_sha256": receipt["recipe_sha256"]})
        raw = (
            repository / "assets" / "textures" / "blobs" / f"{entry['content_sha256']}.ltex"
        ).read_bytes()
        _, maps = read_container(raw, entry)
        parameters = {
            "depth": {},
            "edge": {"edge_step_levels": relief.EDGE_STEP_LEVELS},
            "gray": {},
        }
        for role in target["conditioning"]:
            relative = f"conditioning/{target['id']}/{role}.png"
            pixels_sha256, file_sha256 = _png(out / relative, _picture(role, maps, target["id"]))
            inputs.append(
                {
                    "encoding": relief.RELIEF_ENCODINGS[role]["name"],
                    "file": relative,
                    "file_sha256": file_sha256,
                    "parameters": parameters[role],
                    "pixels_sha256": pixels_sha256,
                    "role": role,
                    "source_sha256": entry["content_sha256"],
                    "target": target["id"],
                }
            )
            files.append(
                {
                    "kind": "conditioning",
                    "path": relative,
                    "sha256": file_sha256,
                    "size": (out / relative).stat().st_size,
                    "source_sha256": entry["content_sha256"],
                }
            )
    named = {
        c["weights_sha256"] for candidate in job["candidates"] for c in candidate["components"]
    }
    for digest in sorted(named):
        raw_manifest = weights_manifests.get(digest)
        if raw_manifest is None or sha256_hex(raw_manifest) != digest:
            raise Refused(f"no weights manifest with sha256 {digest} was given")
        read_weights(raw_manifest)
        relative = f"weights/{digest}.json"
        (out / "weights").mkdir(parents=True, exist_ok=True)
        (out / relative).write_bytes(raw_manifest)
        files.append(
            {
                "kind": "weights-manifest",
                "path": relative,
                "sha256": digest,
                "size": len(raw_manifest),
                "source_sha256": digest,
            }
        )
    job_raw = build_job(
        {
            **job,
            "inputs": inputs,
            "targets": targets,
            "texture_manifest_sha256": sha256_hex(texture_manifest_raw),
        }
    )
    (out / "job.json").write_bytes(job_raw)
    files.append(
        {
            "kind": "job",
            "path": "job.json",
            "sha256": sha256_hex(job_raw),
            "size": len(job_raw),
            "source_sha256": sha256_hex(job_raw),
        }
    )
    manifest = canonical_bytes(
        {
            "files": sorted(files, key=lambda item: item["path"]),
            "job_sha256": sha256_hex(job_raw),
            "profile": STAGED_PROFILE,
            "texture_manifest_sha256": sha256_hex(texture_manifest_raw),
        }
    )
    (out / MANIFEST_NAME).write_bytes(manifest)
    verify_staged(out)
    return manifest


def verify_staged(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hold ``directory`` to its staged manifest exactly; return the manifest and the job."""
    raw = (directory / MANIFEST_NAME).read_bytes()
    where = "the staged inputs"
    manifest = exact_keys(
        parse_canonical(raw, where),
        ("files", "job_sha256", "profile", "texture_manifest_sha256"),
        where,
    )
    if manifest["profile"] != STAGED_PROFILE:
        raise Refused(f"{where}: profile is {STAGED_PROFILE}")
    listed: dict[str, Mapping[str, Any]] = {}
    for item in manifest["files"]:
        exact_keys(item, ("kind", "path", "sha256", "size", "source_sha256"), f"{where}: file")
        if item["kind"] not in KINDS:
            raise Refused(
                f"{where}: {item['path']} is of kind {item['kind']!r}; only {', '.join(KINDS)} may be staged"
            )
        if (
            not is_sha256(item["sha256"])
            or not is_sha256(item["source_sha256"])
            or not is_count(item["size"])
        ):
            raise Refused(f"{where}: {item['path']} names its size, sha256 and source")
        listed[item["path"]] = item
    present = sorted(
        str(path.relative_to(directory))
        for path in directory.rglob("*")
        if path.is_file() and path.name != MANIFEST_NAME
    )
    if present != sorted(listed):
        extra = sorted(set(present) - set(listed))
        missing = sorted(set(listed) - set(present))
        raise Refused(
            f"{where}: the directory does not hold exactly the listed files; extra {extra}, missing {missing}"
        )
    for path, item in listed.items():
        data = (directory / path).read_bytes()
        if len(data) != item["size"] or sha256_hex(data) != item["sha256"]:
            raise Refused(f"{where}: {path} does not have its listed size and sha256")
    job_raw = (directory / "job.json").read_bytes()
    if sha256_hex(job_raw) != manifest["job_sha256"]:
        raise Refused(f"{where}: job.json is not the job the manifest names")
    job = read_job(job_raw)
    if job["texture_manifest_sha256"] != manifest["texture_manifest_sha256"]:
        raise Refused(f"{where}: the job and the manifest name different texture manifests")
    for item in job["inputs"]:
        entry = listed.get(item["file"])
        if (
            entry is None
            or entry["kind"] != "conditioning"
            or entry["sha256"] != item["file_sha256"]
            or entry["source_sha256"] != item["source_sha256"]
        ):
            raise Refused(
                f"{where}: input {item['file']} is not a listed conditioning picture from its source"
            )
    for candidate in job["candidates"]:
        for component in candidate["components"]:
            if f"weights/{component['weights_sha256']}.json" not in listed:
                raise Refused(
                    f"{where}: candidate {candidate['id']} names weights that were not staged"
                )
    return manifest, job
