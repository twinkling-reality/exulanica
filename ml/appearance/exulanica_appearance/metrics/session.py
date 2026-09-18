"""Every number a finished session is judged on, in one pass over its own records.

A session's evidence must be reproducible from what the run wrote and what the repository holds:
the results summary, one generation record per output, the raw outputs, and the published sets the
generations were conditioned on. This walks all of that and writes one document with a row per
generation and a summary over them, so the evidence log and the report quote a file rather than an
ad-hoc script.

Every value is an integer. Medians are the lower of the two middle values on an even count, so a
median is always a value that was actually measured.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median_low
from typing import Any, Final

import numpy as np

from exulanica_appearance.canonical import Refused, canonical_bytes, parse_canonical, sha256_hex
from exulanica_appearance.containers import read_container
from exulanica_appearance.generation import read_generation
from exulanica_appearance.metrics.edges import edge_agreement, image_edges
from exulanica_appearance.metrics.textures import (
    dominant_cycles,
    low_frequency_share_ppm,
    module_amplitude_milli,
    seam_ratio_ppm,
)

__all__ = ["MODULES", "measure_session"]

#: Which recipe parameter states the module count along each axis, by maker. A maker not named here
#: paints scattered cells and not a repeating module (asphalt stones, render relief cells), so it has
#: no period of its own and a retention ratio at some other period would mean nothing: none is
#: measured for those. The counts are the recipe's own, never this file's.
MODULES: Final = {
    "loom.brick": {"u": "units_per_course", "v": "courses"},
    "loom.paving": {"u": "flags_per_row", "v": "rows"},
}


def _recipe(repository: Path, digest: str) -> dict[str, Any]:
    """The recipe that painted a published set, through the catalog's bake receipt."""
    objects = repository / "assets" / "textures" / "objects"
    catalog = json.loads((repository / "assets" / "textures" / "catalog.json").read_bytes())
    sets = {entry["content_sha256"]: entry for entry in catalog["sets"]}
    if digest not in sets:
        raise Refused(f"the published set {digest} is not in assets/textures/catalog.json")
    receipt = json.loads((objects / f"{sets[digest]['receipt_sha256']}.json").read_bytes())
    return json.loads((objects / f"{receipt['recipe_sha256']}.json").read_bytes())


def _published(repository: Path, digest: str) -> dict[str, Any]:
    manifest = json.loads((repository / "assets" / "textures" / "manifest.json").read_bytes())
    pinned = {entry["content_sha256"]: entry for entry in manifest["sets"]}
    if digest not in pinned:
        raise Refused(f"the published set {digest} is not in assets/textures/manifest.json")
    entry = pinned[digest]
    raw = (repository / "assets" / "textures" / "blobs" / f"{digest}.ltex").read_bytes()
    _, maps = read_container(raw, entry)
    colour = maps["base_color"]
    recipe = _recipe(repository, digest)
    maker = recipe["maker"]["id"]
    named = MODULES.get(maker)
    module: dict[str, Any] = {"maker": maker}
    if named is None:
        module["states_a_module"] = 0
    else:
        cycles = {axis: int(recipe["parameters"][named[axis]]) for axis in ("u", "v")}
        module["cycles"] = cycles
        module["from"] = {axis: named[axis] for axis in ("u", "v")}
        module["states_a_module"] = 1
        module["amplitude_milli"] = module_amplitude_milli(colour, cycles)
    return {
        "dominant_cycles": dominant_cycles(colour),
        "low_frequency_share_ppm": low_frequency_share_ppm(colour),
        "module": module,
        "seams_ppm": seam_ratio_ppm(colour),
        "set_id": entry["set_id"],
    }


def _conditioning(staged: Path, record: dict[str, Any], target: str) -> Any:
    """The picture the model was conditioned on, verified against the digest its record pins."""
    from PIL import Image

    entry = record["conditioning"][0]
    picture = staged / "conditioning" / target / f"{entry['role']}.png"
    with Image.open(picture) as opened:
        pixels = np.array(opened.convert("RGB"), dtype=np.uint8)
    if sha256_hex(pixels.tobytes()) != entry["pixels_sha256"]:
        raise Refused(
            f"the conditioning picture {picture} is not the pixels the record pins; "
            "the structure a run was given cannot be reconstructed from a changed file"
        )
    return pixels


def measure_session(*, repository: Path, results: Path, staged: Path | None = None) -> bytes:
    """Measure every generation a finished run wrote, against the published set it dresses.

    With ``staged``, the directory the run was given, each output's edges are also compared with
    the edges of its own conditioning picture: recall is the share of the structure's edges that
    survive into the generated tile, which is the measurement the lane's rule rests on.
    """
    summary = parse_canonical((results / "results.json").read_bytes(), "the results")
    published: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for item in summary["generations"]:
        record_raw = (results / "records" / f"{item['record_sha256']}.json").read_bytes()
        record = read_generation(record_raw)
        source = record["conditioning"][0]["sources"][0]
        if source not in published:
            published[source] = _published(repository, source)
        before = published[source]
        digest = record["outputs"][0]["sha256"]
        raw = (results / "outputs" / f"{digest}.rgb").read_bytes()
        if sha256_hex(raw) != digest:
            raise Refused(f"the bytes of {digest} are not the bytes its record pins")
        height, width = record["sampler"]["height"], record["sampler"]["width"]
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
        module = before["module"]
        amplitude: dict[str, int] = {}
        retention: dict[str, int] = {}
        if module["states_a_module"]:
            amplitude = module_amplitude_milli(pixels, module["cycles"])
            for axis in ("u", "v"):
                painted = module["amplitude_milli"][axis]
                if painted < 1:
                    raise Refused(
                        f"{before['set_id']} states a module along {axis} but does not vary at it"
                    )
                retention[axis] = 1000 * amplitude[axis] // painted
        agreement: dict[str, int] = {}
        unmeasured = ""
        if staged is not None:
            given = _conditioning(staged, record, item["target"])
            if given.shape[:2] == pixels.shape[:2]:
                agreement = edge_agreement(image_edges(pixels), image_edges(given).astype(np.uint8))
            else:
                # Never resampled: a resized picture is not the structure that was given, and an
                # agreement measured against a resize would be a measurement of the resize.
                unmeasured = (
                    f"the conditioning is {given.shape[1]} by {given.shape[0]} and the output is "
                    f"{pixels.shape[1]} by {pixels.shape[0]}"
                )
        rows.append(
            {
                "amplitude_milli": amplitude,
                "conditioning_agreement": agreement,
                "conditioning_not_measured": unmeasured,
                "candidate": item["candidate"],
                "index": item["index"],
                "low_frequency_share_ppm": low_frequency_share_ppm(pixels),
                "output_sha256": digest,
                "published_module": module,
                "published_set": before["set_id"],
                "record_sha256": item["record_sha256"],
                "retention_permille": retention,
                "role": item["role"],
                "seams_ppm": seam_ratio_ppm(pixels),
                "seconds": item["seconds"],
                "seed": item["seed"],
                "source_sha256": source,
                "target": item["target"],
            }
        )
    document = {
        "elapsed_seconds": summary["elapsed_seconds"],
        "generations": sorted(rows, key=lambda row: row["index"]),
        "profile": "exulanica.appearance-session-measurements/v1",
        "published": published,
        "results_sha256": sha256_hex((results / "results.json").read_bytes()),
        "summary": _summary(rows),
    }
    return canonical_bytes(document)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    seams = [row["seams_ppm"][axis] for row in rows for axis in ("u", "v")]
    recalls = [
        row["conditioning_agreement"]["recall_ppm"] for row in rows if row["conditioning_agreement"]
    ]
    out: dict[str, Any] = {
        "count": len(rows),
        "seams_ppm": {
            "max": max(seams),
            "median": median_low(seams),
            "min": min(seams),
        },
    }
    unmeasured = [row for row in rows if row["conditioning_not_measured"]]
    if unmeasured:
        out["conditioning_not_measured"] = {
            "count": len(unmeasured),
            "why": unmeasured[0]["conditioning_not_measured"],
        }
    if recalls:
        out["conditioning_recall_ppm"] = {
            "max": max(recalls),
            "measured_over": len(recalls),
            "median": median_low(recalls),
            "min": min(recalls),
        }
    by_candidate: dict[str, Any] = {}
    for candidate in sorted({row["candidate"] for row in rows}):
        mine = [row for row in rows if row["candidate"] == candidate]
        seconds = [row["seconds"] for row in mine]
        retention = [
            row["retention_permille"][axis]
            for row in mine
            for axis in ("u", "v")
            if row["retention_permille"]
        ]
        by_candidate[candidate] = {
            "count": len(mine),
            "seconds": {"max": max(seconds), "median": median_low(seconds), "min": min(seconds)},
        }
        mine_recall = [
            row["conditioning_agreement"]["recall_ppm"]
            for row in mine
            if row["conditioning_agreement"]
        ]
        if mine_recall:
            by_candidate[candidate]["conditioning_recall_ppm"] = {
                "max": max(mine_recall),
                "median": median_low(mine_recall),
                "min": min(mine_recall),
            }
        if retention:
            by_candidate[candidate]["retention_permille"] = {
                "max": max(retention),
                "measured_over": len(retention),
                "median": median_low(retention),
                "min": min(retention),
            }
    out["by_candidate"] = by_candidate
    by_target: dict[str, Any] = {}
    for target in sorted({row["target"] for row in rows}):
        by_target[target] = {}
        for candidate in sorted({row["candidate"] for row in rows}):
            mine = [
                row for row in rows if row["target"] == target and row["candidate"] == candidate
            ]
            if not mine:
                continue
            low = [row["low_frequency_share_ppm"] for row in mine]
            entry: dict[str, Any] = {
                "low_frequency_share_ppm": {
                    "max": max(low),
                    "median": median_low(low),
                    "min": min(low),
                }
            }
            with_module = [row for row in mine if row["retention_permille"]]
            if with_module:
                entry["retention_permille"] = {
                    axis: {
                        "max": max(row["retention_permille"][axis] for row in with_module),
                        "median": median_low(
                            [row["retention_permille"][axis] for row in with_module]
                        ),
                        "min": min(row["retention_permille"][axis] for row in with_module),
                    }
                    for axis in ("u", "v")
                }
            by_target[target][candidate] = entry
    out["by_target"] = by_target
    return out
