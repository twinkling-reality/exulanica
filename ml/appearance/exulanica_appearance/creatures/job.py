"""Run a creature look job: each item from its plan's sketch to a checked skinned look, or a refusal.

The same runner serves the dry run on this Mac (a stand-in backend) and the job on a rented GPU
(route C). For each item it draws the control picture from the plan's sketch, asks the backend for
a concept picture following it, cuts the figure out, asks the 3D model for a mesh, turns the mesh
into the slot frame, simplifies it to the budget, registers it onto the sketch, colours it with
its own swatches, rigs it with the plan's skeleton, checks the rig, writes the skinned container
and reads it back with the product's reader. An item that fails or is refused is recorded with its
stage and reason, and the run goes on. A registration or rig refused by its checks keeps its
measures in the receipt, as a passed one does.

Everything is written once under the output directory:

    inputs/<sha256>.png      control pictures, concept pictures and cut-outs
    meshes/<sha256>.npz      raw meshes as the model returned them
    looks/<sha256>.glb       skinned containers
    receipts/<sha256>.json   their receipts
    rows/<sha256>.png        each item's row of the contact sheet
    results-<job sha256>-<ended at>.json
"""

from __future__ import annotations

import io
import json
import platform
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
from exulanica_pieces.canonical import Refused, canonical_bytes, sha256_hex
from exulanica_pieces.colour import read_table
from exulanica_pieces.geometry.mesh import Mesh, Simplifier, orient, simplify_to
from exulanica_pieces.geometry.skinned import write_skinned_glb
from exulanica_pieces.skinned import read_skinned_glb

from exulanica_appearance.creatures.colour import flat_colours
from exulanica_appearance.creatures.control import concept_prompt, control_picture
from exulanica_appearance.creatures.geometry import CONTROL_CAMERA, sketch_triangles
from exulanica_appearance.creatures.register import Registered, RegistrationRefused, register
from exulanica_appearance.creatures.request import CreatureRequest, RequestRefused, read_request
from exulanica_appearance.creatures.rig import (
    Inside,
    RigChecks,
    RigRefused,
    bone_heat,
    check_rig,
    fit_joints,
    inside_of,
)
from exulanica_appearance.creatures.views import pose, render, sheet_row, views

__all__ = [
    "JOB_PROFILE",
    "RECEIPT_PROFILE",
    "RESULTS_PROFILE",
    "CreatureBackend",
    "CreatureMesh",
    "read_creature_job",
    "run_creature_job",
]

JOB_PROFILE: Final = "exulanica.creature-look-job/v1"
RESULTS_PROFILE: Final = "exulanica.creature-look-results/v1"
RECEIPT_PROFILE: Final = "exulanica.creature-look-receipt/v1"
_HEX: Final = re.compile(r"[0-9a-f]{64}")
_SEED_MAXIMUM: Final = (1 << 63) - 1
#: The side of each picture in a contact sheet row, in pixels.
_TILE: Final = 256


class CreatureMesh(Protocol):
    mesh: Mesh
    up: str
    front: str


class CreatureBackend(Protocol):
    route: str

    def simplifier(self) -> Simplifier: ...

    def concept(self, prompt: str, control: np.ndarray, seed: int) -> bytes:
        """A PNG of the figure following the control picture (H x W x 3, uint8)."""

    def cutout(self, picture: bytes) -> bytes:
        """An RGBA PNG: the figure, its background transparent."""

    def mesh(self, cutout: bytes, seed: int, sketch: np.ndarray) -> CreatureMesh:
        """The 3D model on the cut-out; ``sketch`` is there for a stand-in, not a model."""

    def runtime(self) -> dict[str, Any]:
        """The machine and library versions the receipts state."""


def read_creature_job(raw: bytes) -> dict[str, Any]:
    """A creature look job record, or :class:`Refused` naming the field at fault."""
    try:
        job = json.loads(raw)
    except ValueError as exc:
        raise Refused(f"the job record is not JSON: {exc}") from exc
    expected = {
        "profile",
        "route",
        "code_sha256",
        "components_sha256",
        "container",
        "settings",
        "items",
        "stop",
    }
    if not isinstance(job, dict) or job.get("profile") != JOB_PROFILE or set(job) != expected:
        raise Refused(f"a job record is {JOB_PROFILE} holding {sorted(expected)}")
    if job["route"] != "C":
        raise Refused("a creature job takes route C")
    for field in ("code_sha256", "components_sha256"):
        if not isinstance(job[field], str) or not _HEX.fullmatch(job[field]):
            raise Refused(f"{field} is 64 lowercase hex digits")
    if not isinstance(job["container"], str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", job["container"]
    ):
        raise Refused("container is the image's sha256 digest")
    settings = job["settings"]
    if not isinstance(settings, dict) or set(settings) != {"concept", "triangles", "rig_voxels"}:
        raise Refused("settings holds concept, triangles and rig_voxels")
    if not isinstance(settings["triangles"], int) or not 1_000 <= settings["triangles"] <= 20_000:
        raise Refused("settings.triangles is 1,000 to 20,000")
    if not isinstance(settings["rig_voxels"], int) or not 32 <= settings["rig_voxels"] <= 256:
        raise Refused("settings.rig_voxels is 32 to 256")
    items = job["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= 64:
        raise Refused("a job holds 1 to 64 items")
    seen = set()
    for index, item in enumerate(items):
        if (
            not isinstance(item, dict)
            or set(item) != {"request_sha256", "seed", "variant"}
            or not isinstance(item["request_sha256"], str)
            or not _HEX.fullmatch(item["request_sha256"])
            or not isinstance(item["seed"], int)
            or not 0 <= item["seed"] <= _SEED_MAXIMUM
            or not isinstance(item["variant"], int)
            or not 0 <= item["variant"] < 16
        ):
            raise Refused(f"items[{index}] is a request's sha256, a seed and a variant")
        key = (item["request_sha256"], item["variant"])
        if key in seen:
            raise Refused(f"items[{index}] repeats a request's variant")
        seen.add(key)
    stop = job["stop"]
    if (
        not isinstance(stop, dict)
        or set(stop) != {"estimate_seconds", "stop_at_seconds"}
        or not all(isinstance(value, int) and value > 0 for value in stop.values())
        or stop["stop_at_seconds"] < stop["estimate_seconds"]
    ):
        raise Refused("stop holds an estimate and a stop at or after it, in whole seconds")
    return job


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise Refused(f"{path} already holds other bytes; output is written once")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_bytes(data)
    partial.replace(path)


def _png(picture: np.ndarray) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(picture).save(buffer, format="PNG")
    return buffer.getvalue()


def _picture(data: bytes) -> np.ndarray:
    """A PNG as RGB (a cut-out's transparency on white)."""
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    if image.mode == "RGBA":
        white = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(white, image)
    return np.asarray(image.convert("RGB"))


def _mesh_bytes(mesh: Mesh) -> bytes:
    buffer = io.BytesIO()
    np.savez(buffer, positions=mesh.positions, triangles=mesh.triangles, colours=mesh.colours)
    return buffer.getvalue()


def _slot(mesh: Mesh) -> Mesh:
    """A mesh oriented to glTF (+Y up, front +Z) in the slot frame: (x, y, z) = (-X, Z, Y)."""
    p = mesh.positions
    return Mesh(np.stack([-p[:, 0], p[:, 2], p[:, 1]], axis=1), mesh.triangles, mesh.colours)


def _without_slivers(mesh: Mesh) -> tuple[Mesh, int]:
    """The mesh without triangles of no area, which have no normal and no heat."""
    corners = mesh.positions[mesh.triangles]
    area = np.linalg.norm(
        np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1
    )
    keep = area > 1e-12
    if not keep.any():
        raise Refused("the mesh has no triangle with area")
    return Mesh(mesh.positions, mesh.triangles[keep], mesh.colours).compact(), int((~keep).sum())


#: A part of a mesh (triangles joined by shared vertices) with less than this share of its surface,
#: per mille, is a stray fragment and is dropped; the largest part is always kept.
_PART_PER_MILLE: Final = 20


def _main_parts(mesh: Mesh) -> tuple[Mesh, dict[str, int]]:
    """The mesh without its stray fragments: a 3D model's output can hold small pieces apart from
    the body, which would stretch the box it is fitted by and draw nothing of the creature."""
    count = len(mesh.positions)
    edges = mesh.triangles[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    labels = np.arange(count)
    while True:
        lowest = np.minimum(labels[edges[:, 0]], labels[edges[:, 1]])
        joined = labels.copy()
        np.minimum.at(joined, edges[:, 0], lowest)
        np.minimum.at(joined, edges[:, 1], lowest)
        joined = joined[joined]
        if np.array_equal(joined, labels):
            break
        labels = joined
    corners = mesh.positions[mesh.triangles]
    area = np.linalg.norm(
        np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1
    )
    part = labels[mesh.triangles[:, 0]]
    names, inverse = np.unique(part, return_inverse=True)
    totals = np.bincount(inverse, weights=area)
    keep_parts = totals * 1000 >= _PART_PER_MILLE * totals.sum()
    keep_parts[int(np.argmax(totals))] = True
    kept = keep_parts[inverse]
    return Mesh(mesh.positions, mesh.triangles[kept], mesh.colours).compact(), {
        "dropped_area_per_mille": round(float(totals[~keep_parts].sum() * 1000 / totals.sum())),
        "parts": len(names),
        "parts_kept": int(keep_parts.sum()),
        "step": "parts",
    }


def _seconds(start: float) -> int:
    return round(time.monotonic() - start)


def _per_mille(value: float) -> int:
    return round(value * 1000)


def _mm(value: float) -> int:
    return round(value * 1000)


def _registration_record(registered: Registered) -> dict[str, Any]:
    """What registration measured, as a receipt holds it, kept or refused."""
    return {
        "yaw_degrees": registered.yaw_degrees,
        "scale_per_mille": [_per_mille(value) for value in registered.scale],
        "overlap_per_mille": registered.overlap_kept_per_mille,
        "depth_agreement_per_mille": registered.depth_agreement_kept_per_mille,
        "scores_per_mille": {str(yaw): score for yaw, score in registered.score_per_mille.items()},
    }


def _rig_record(checks: RigChecks, inside: Inside) -> dict[str, Any]:
    """What the rig's checks measured, as a receipt holds it, passed or refused."""
    return {
        "route": "R2",
        "voxel_mm": _mm(inside.voxel),
        "joint_moved_mm": {bone: _mm(value) for bone, value in checks.joint_moved_m.items()},
        "inside_per_mille": {
            bone: _per_mille(value) for bone, value in checks.inside_share.items()
        },
        "moved_vertices": dict(checks.moved_vertices),
        "leaked_per_mille": {key: _per_mille(value) for key, value in checks.leaked_share.items()},
    }


def _sculpt(
    request: CreatureRequest,
    sketch: np.ndarray,
    item: Mapping[str, Any],
    settings: Mapping[str, Any],
    backend: CreatureBackend,
    table: Sequence[int],
    out: Path,
    record: dict[str, Any],
    pictures: list[np.ndarray],
) -> bytes:
    """One item, stage by stage: every stage's digests, measures and seconds go into ``record``,
    and every picture made on the way into ``pictures``, so a refused item still shows how far
    it came."""
    seconds: dict[str, int] = {}
    record["seconds"] = seconds
    inputs: dict[str, str] = record["inputs"]
    record["stage"] = "control"
    start = time.monotonic()
    control_png, _drawn = control_picture(sketch)
    inputs["control_picture"] = sha256_hex(control_png)
    _write_once(out / "inputs" / f"{inputs['control_picture']}.png", control_png)
    pictures.append(_picture(control_png))
    seconds["control"] = _seconds(start)
    record["stage"] = "concept"
    prompt = concept_prompt(request.appearance, request.colour_words)
    record["prompt"] = prompt
    start = time.monotonic()
    concept = backend.concept(prompt, _picture(control_png), item["seed"])
    seconds["concept"] = _seconds(start)
    inputs["concept_picture"] = sha256_hex(concept)
    _write_once(out / "inputs" / f"{inputs['concept_picture']}.png", concept)
    pictures.append(_picture(concept))
    record["stage"] = "cutout"
    start = time.monotonic()
    cutout = backend.cutout(concept)
    seconds["cutout"] = _seconds(start)
    inputs["cutout"] = sha256_hex(cutout)
    _write_once(out / "inputs" / f"{inputs['cutout']}.png", cutout)
    pictures.append(_picture(cutout))
    record["stage"] = "mesh"
    start = time.monotonic()
    raw = backend.mesh(cutout, item["seed"], sketch)
    seconds["mesh"] = _seconds(start)
    raw_bytes = _mesh_bytes(raw.mesh)
    inputs["raw_mesh"] = sha256_hex(raw_bytes)
    _write_once(out / "meshes" / f"{inputs['raw_mesh']}.npz", raw_bytes)
    record["stage"] = "simplify"
    start = time.monotonic()
    turned, turn_record = orient(raw.mesh, raw.up, raw.front)
    simplified, simplify_record = simplify_to(
        _slot(turned).compact(), settings["triangles"], backend.simplifier()
    )
    cleaned, slivers = _without_slivers(simplified)
    cleaned, parts_record = _main_parts(cleaned)
    record["steps"] = [
        turn_record,
        simplify_record,
        {"step": "slivers", "removed": slivers},
        parts_record,
    ]
    seconds["simplify"] = _seconds(start)
    record["stage"] = "register"
    start = time.monotonic()
    try:
        registered = register(cleaned.positions, cleaned.triangles, sketch)
    except RegistrationRefused as refusal:
        seconds["register"] = _seconds(start)
        if refusal.refused is not None:
            record["registration"] = _registration_record(refusal.refused)
        raise
    seconds["register"] = _seconds(start)
    record["registration"] = _registration_record(registered)
    positions, triangles = registered.positions, cleaned.triangles
    colours, palette = flat_colours(cleaned.colours, triangles)
    record["swatches"] = len(palette)
    pictures += views(positions, triangles, colours, (), _TILE)
    record["stage"] = "rig"
    start = time.monotonic()
    largest = float((positions.max(axis=0) - positions.min(axis=0)).max())
    inside = inside_of(positions, triangles, largest / settings["rig_voxels"])
    joints, ends = fit_joints(request.joints, request.ends, request.chains, request.radii, inside)
    indices, weights = bone_heat(positions, triangles, request.bones, joints, ends, inside)
    seconds["rig"] = _seconds(start)
    for phase in (1, -1):
        moved = pose(
            positions,
            indices,
            weights,
            request.bones,
            request.parents,
            joints,
            ends,
            request.chains,
            phase,
        )
        pictures.append(render(moved, triangles, colours, CONTROL_CAMERA, _TILE))
    record["stage"] = "check"
    start = time.monotonic()
    size = float(max(np.ptp(sketch.reshape(-1, 3), axis=0)))
    try:
        checks = check_rig(
            positions=positions,
            indices=indices,
            weights=weights,
            bones=request.bones,
            parents=request.parents,
            plan_joints=request.joints,
            joints=joints,
            ends=ends,
            chains=request.chains,
            inside=inside,
            size=size,
        )
    except RigRefused as refusal:
        if refusal.checks is not None:
            record["rig"] = _rig_record(refusal.checks, inside)
        raise
    record["rig"] = _rig_record(checks, inside)
    record["stage"] = "container"
    container = write_skinned_glb(
        positions_m=positions,
        triangles=triangles,
        triangle_colours_srgb8=colours,
        joint_indices=indices,
        joint_weights=weights,
        bones=request.bones,
        parents=request.parents,
        rest_m=joints,
        table=table,
    )
    read = read_skinned_glb(
        container,
        bones={bone: f"bone:{bone}" for bone in request.bones},
        plan_parents=request.parents,
    )
    seconds["check"] = _seconds(start)
    del record["stage"]
    record["output"] = {
        "bytes": len(container),
        "joints": len(read.joints),
        "sha256": sha256_hex(container),
        "triangles": read.triangles,
    }
    return container


def run_creature_job(
    *,
    job_raw: bytes,
    requests: Sequence[bytes],
    sketches: Mapping[str, bytes],
    backend: CreatureBackend,
    repository: Path,
    out: Path,
) -> dict[str, Any]:
    """Run every item; ``sketches`` holds the sketch containers by sha256."""
    job = read_creature_job(job_raw)
    # A stand-in runs any job on this Mac; a real backend runs only its own route.
    if backend.route not in (job["route"], "stand-in"):
        raise Refused(f"the job takes route {job['route']}, the backend is route {backend.route}")
    job_sha256 = sha256_hex(job_raw)
    by_digest: dict[str, CreatureRequest] = {}
    for raw in requests:
        try:
            by_digest[sha256_hex(raw)] = read_request(raw)
        except RequestRefused as exc:
            raise Refused(f"request {sha256_hex(raw)}: {exc}") from exc
    table, table_sha256 = read_table(repository)
    runtime = backend.runtime()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    outcomes: list[dict[str, Any]] = []
    rows: list[str] = []
    for item in job["items"]:
        request = by_digest.get(item["request_sha256"])
        if request is None:
            raise Refused(f"the job names request {item['request_sha256']}, which was not given")
        container_raw = sketches.get(request.sketch_sha256)
        if container_raw is None or len(container_raw) != request.sketch_bytes:
            raise Refused(f"the sketch request {item['request_sha256']} names was not given")
        sketch, _bones_of = sketch_triangles(container_raw)
        record: dict[str, Any] = {
            "inputs": {"colour_table": table_sha256, "sketch": request.sketch_sha256},
            "plan": {
                "key": request.plan_key,
                "sha256": request.plan_sha256,
                "version": request.plan_version,
            },
            "request_sha256": item["request_sha256"],
            "seed": item["seed"],
            "variant": item["variant"],
        }
        pictures: list[np.ndarray] = []
        try:
            container = _sculpt(
                request, sketch, item, job["settings"], backend, table, out, record, pictures
            )
            _write_once(out / "looks" / f"{record['output']['sha256']}.glb", container)
            record["outcome"] = "passed"
        except (RigRefused, RegistrationRefused) as refusal:
            record["outcome"] = "refused"
            record["refusal"] = {"code": refusal.code, "detail": refusal.detail}
        except Refused as refusal:
            record["outcome"] = "refused"
            record["refusal"] = {"code": f"{record['stage']}_refused", "detail": str(refusal)}
        except Exception as error:  # noqa: BLE001 - one item's failure must not lose a paid batch
            record["outcome"] = "failed"
            record["refusal"] = {
                "code": f"{record['stage']}_failed",
                "detail": f"{type(error).__name__}: {error}",
            }
        receipt = canonical_bytes(
            {
                **record,
                "components_sha256": job["components_sha256"],
                "job_sha256": job_sha256,
                "licence": "CC0-1.0",
                "origin": "generated",
                "profile": RECEIPT_PROFILE,
                "runtime": runtime,
                "truth": "invented",
            }
        )
        receipt_sha256 = sha256_hex(receipt)
        _write_once(out / "receipts" / f"{receipt_sha256}.json", receipt)
        label = f"{request.plan_key} variant {item['variant']}: {record['outcome']}" + (
            f" ({record['refusal']['code']})" if "refusal" in record else ""
        )
        # Every item has its row, an item that failed before any picture a row of its label alone.
        row = sheet_row(pictures or [np.full((_TILE, _TILE, 3), 255, np.uint8)], label, _TILE)
        row_sha256 = sha256_hex(row)
        _write_once(out / "rows" / f"{row_sha256}.png", row)
        rows.append(row_sha256)
        outcomes.append(
            {
                "outcome": record["outcome"],
                "receipt": receipt_sha256,
                "request_sha256": item["request_sha256"],
                "row": row_sha256,
                "variant": item["variant"],
                **({"refusal": record["refusal"]["code"]} if "refusal" in record else {}),
                **({"look": record["output"]["sha256"]} if record["outcome"] == "passed" else {}),
            }
        )
    results = {
        "ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "items": outcomes,
        "job_sha256": job_sha256,
        "machine": platform.platform(),
        "profile": RESULTS_PROFILE,
        "rows": rows,
        "started_at": started,
    }
    stamp = results["ended_at"].replace(":", "").replace("-", "")
    _write_once(out / f"results-{job_sha256}-{stamp}.json", canonical_bytes(results))
    return results
