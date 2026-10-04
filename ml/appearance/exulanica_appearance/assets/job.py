"""Run one generated asset job: every item of its record, through one route's backend, to pieces.

The same runner serves the dry run on this Mac (the stub backend) and the job on a rented GPU (the
route backends, which need CUDA). For each item it draws the concept picture or takes the cut-out
the item names, cuts it out, asks the route's 3D model for a raw mesh in the model's own frame,
runs the post-process, and writes the piece, its receipt and every intermediate by digest. An item
that fails is recorded with its reason and the run goes on; the results record says what was made.

Everything is written once under the output directory (a bucket mount in the job):

    inputs/<sha256>.png      concept pictures and cut-outs
    meshes/<sha256>.npz      raw meshes, as the model returned them
    pieces/<sha256>.glb      the pieces
    receipts/<sha256>.json   their receipts
    results-<job sha256>-<ended at>.json
"""

from __future__ import annotations

import io
import platform
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
from exulanica_pieces.canonical import Refused, canonical_bytes, sha256_hex
from exulanica_pieces.colour import read_table
from exulanica_pieces.geometry.mesh import Mesh, Simplifier
from exulanica_pieces.geometry.postprocess import POSTPROCESS_VERSION, make_piece
from exulanica_pieces.records import (
    RECEIPT_PROFILE,
    REGENERATION,
    build_receipt,
    read_job,
    read_request,
)

__all__ = ["RESULTS_PROFILE", "Backend", "RawMesh", "run_job"]

RESULTS_PROFILE: Final = "exulanica.generated-asset-results/v1"


@dataclass(frozen=True)
class RawMesh:
    """What a route's 3D model returned, in its own frame, and how that frame is oriented."""

    mesh: Mesh
    up: str
    front: str


class Backend(Protocol):
    route: str

    def simplifier(self) -> Simplifier: ...

    def concept(self, prompt: str, seed: int) -> bytes:
        """A PNG of the piece on a plain background."""

    def cutout(self, picture: bytes) -> bytes:
        """An RGBA PNG: the piece, its background transparent."""

    def mesh(self, cutout: bytes, seed: int, request: Mapping[str, Any]) -> RawMesh:
        """The route's 3D model on the cut-out; ``request`` is there for a stub, not a model."""

    def runtime(self) -> dict[str, Any]:
        """The machine and library versions the receipts state."""


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise Refused(f"{path} already holds other bytes; output is written once")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_bytes(data)
    partial.replace(path)


def _mesh_bytes(mesh: Mesh) -> bytes:
    buffer = io.BytesIO()
    np.savez(buffer, positions=mesh.positions, triangles=mesh.triangles, colours=mesh.colours)
    return buffer.getvalue()


def _seconds(start: float) -> int:
    return round(time.monotonic() - start)


def run_job(
    *,
    job_raw: bytes,
    requests: Sequence[bytes],
    backend: Backend,
    repository: Path,
    out: Path,
    cutouts: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """Run every item; ``cutouts`` holds cut-outs by sha256 for items that name one."""
    job = read_job(job_raw)
    if job["route"] != backend.route:
        raise Refused(f"the job takes route {job['route']}, the backend is route {backend.route}")
    job_sha256 = sha256_hex(job_raw)
    by_digest = {sha256_hex(raw): read_request(raw) for raw in requests}
    table, table_sha256 = read_table(repository)
    runtime = backend.runtime()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    outcomes = []
    for item in job["items"]:
        request = by_digest.get(item["request_sha256"])
        if request is None:
            raise Refused(f"the job names request {item['request_sha256']}, which was not given")
        outcome: dict[str, Any] = {
            "request_sha256": item["request_sha256"],
            "variant": item["variant"],
        }
        try:
            seconds = {"concept": 0, "cutout": 0, "mesh": 0, "postprocess": 0}
            inputs = {"colour_table": table_sha256}
            if "cutout_sha256" in item:
                cutout = (cutouts or {}).get(item["cutout_sha256"])
                if cutout is None or sha256_hex(cutout) != item["cutout_sha256"]:
                    raise Refused("the cut-out the item names was not given")
            else:
                start = time.monotonic()
                picture = backend.concept(item["prompt"], item["seed"])
                seconds["concept"] = _seconds(start)
                inputs["concept_picture"] = sha256_hex(picture)
                _write_once(out / "inputs" / f"{inputs['concept_picture']}.png", picture)
                start = time.monotonic()
                cutout = backend.cutout(picture)
                seconds["cutout"] = _seconds(start)
            inputs["cutout"] = sha256_hex(cutout)
            _write_once(out / "inputs" / f"{inputs['cutout']}.png", cutout)
            start = time.monotonic()
            raw = backend.mesh(cutout, item["seed"], request)
            seconds["mesh"] = _seconds(start)
            raw_bytes = _mesh_bytes(raw.mesh)
            inputs["raw_mesh"] = sha256_hex(raw_bytes)
            _write_once(out / "meshes" / f"{inputs['raw_mesh']}.npz", raw_bytes)
            start = time.monotonic()
            piece = make_piece(
                raw.mesh,
                up=raw.up,
                front=raw.front,
                request=request,
                simplifier=backend.simplifier(),
                table=table,
            )
            seconds["postprocess"] = _seconds(start)
            _write_once(out / "pieces" / f"{piece.sha256}.glb", piece.glb)
            receipt = build_receipt(
                {
                    "components_sha256": job["components_sha256"],
                    "inputs": inputs,
                    "job_sha256": job_sha256,
                    "licence": "CC0-1.0",
                    "measured": piece.measured,
                    "origin": "generated",
                    "output": {"bytes": len(piece.glb), "sha256": piece.sha256},
                    "postprocess": {"steps": piece.steps, "version": POSTPROCESS_VERSION},
                    "profile": RECEIPT_PROFILE,
                    "regeneration": REGENERATION,
                    "request_sha256": item["request_sha256"],
                    "runtime": runtime,
                    "seconds": seconds,
                    "seed": item["seed"],
                    "truth": "invented",
                    "variant": item["variant"],
                    "verdict": piece.verdict,
                },
                request,
            )
            receipt_sha256 = sha256_hex(receipt)
            _write_once(out / "receipts" / f"{receipt_sha256}.json", receipt)
            outcome.update(
                {
                    "look_role": request["look_role"],
                    "piece": piece.sha256,
                    "receipt": receipt_sha256,
                    "size_mm": piece.measured["size_mm"],
                    "triangles": piece.measured["triangles"],
                    "within": piece.verdict["within"],
                }
            )
        except Refused as refusal:
            outcome["refused"] = str(refusal)
        except Exception as error:  # noqa: BLE001 - one item's failure must not lose a paid batch
            outcome["failed"] = f"{type(error).__name__}: {error}"
        outcomes.append(outcome)
    results = {
        "ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "items": outcomes,
        "job_sha256": job_sha256,
        "machine": platform.platform(),
        "profile": RESULTS_PROFILE,
        "started_at": started,
    }
    stamp = results["ended_at"].replace(":", "").replace("-", "")
    _write_once(out / f"results-{job_sha256}-{stamp}.json", canonical_bytes(results))
    return results
