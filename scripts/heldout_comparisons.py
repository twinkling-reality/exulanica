"""Lay a trained scene's held-out renders beside the photographs they were scored against.

The scene worker retains one private evaluation bundle per training run: the held-out renders,
the undistorted reference images, and ``metrics.json`` with the per-view scores. The numbers say
how far the render is from the photograph; they do not show a reviewer what that distance looks
like. This tool reads a retained bundle, verifies every file it uses against the bundle's own
inventory, and writes one side-by-side JPEG per held-out view with the measured scores printed on
it, plus a digest-bound summary so a record can cite exactly which pixels were looked at.

    uv run python scripts/heldout_comparisons.py --bundle <zip> --output <directory>
    uv run python scripts/heldout_comparisons.py --sha256 <hex> --store <blob root> --output <dir>

Comparisons are visual evidence of appearance at photographed viewpoints only. They establish no
physical scale, completeness or navigability, and the renders remain reconstructions.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

PROFILE = "exulanica.heldout-comparison-set/v1"
CAPTION_HEIGHT = 44
GUTTER = 12


class BundleIntegrityError(ValueError):
    """The bundle's inventory does not describe the bytes it contains."""


def _inventory(archive: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
    entries = json.loads(archive.read("inventory.json"))["files"]
    return {entry["path"]: entry for entry in entries}


def _verified_bytes(
    archive: zipfile.ZipFile, inventory: dict[str, dict[str, Any]], path: str
) -> bytes:
    entry = inventory.get(path)
    if entry is None:
        raise BundleIntegrityError(f"{path} is not listed in the bundle inventory")
    data = archive.read(path)
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry["sha256"] or len(data) != entry["byte_size"]:
        raise BundleIntegrityError(f"{path} does not match its inventory digest or size")
    return data


def _fit(image: Image.Image, width: int) -> Image.Image:
    height = max(1, round(image.height * width / image.width))
    return image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)


def compose_view(
    photograph: Image.Image, render: Image.Image, scores: dict[str, Any], *, max_width: int
) -> Image.Image:
    """One canvas: photograph left, render right, captions and measured scores below."""
    panel_width = max(64, (max_width - GUTTER) // 2)
    left = _fit(photograph, panel_width)
    right = _fit(render, panel_width)
    height = max(left.height, right.height)
    canvas = Image.new("RGB", (panel_width * 2 + GUTTER, height + CAPTION_HEIGHT), (24, 24, 24))
    canvas.paste(left, (0, 0))
    canvas.paste(right, (panel_width + GUTTER, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, height + 6), "held-out photograph, undistorted", fill=(235, 235, 235))
    draw.text(
        (panel_width + GUTTER + 8, height + 6),
        "render from the trained scene",
        fill=(235, 235, 235),
    )
    measured = (
        f"PSNR {scores['psnr']:.2f} dB   SSIM {scores['ssim']:.3f}   LPIPS {scores['lpips']:.3f}   "
        f"coverage {scores['coverage_fraction']:.3f}"
    )
    draw.text((8, height + 24), measured, fill=(200, 200, 200))
    return canvas


def compose_bundle(
    bundle: Path, output: Path, *, max_width: int = 1600, views: set[str] | None = None
) -> dict[str, Any]:
    """Write every requested comparison and return the digest-bound summary that was also saved."""
    output.mkdir(parents=True, exist_ok=True)
    bundle_bytes = bundle.read_bytes()
    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
        inventory = _inventory(archive)
        metrics = json.loads(_verified_bytes(archive, inventory, "metrics.json"))
        comparisons = []
        for view in metrics["per_view"]:
            render_path = view["render"]
            stem = Path(render_path).stem
            if views is not None and stem not in views:
                continue
            reference_path = f"training/undistorted/images/{view['source_name']}"
            render_bytes = _verified_bytes(archive, inventory, render_path)
            if hashlib.sha256(render_bytes).hexdigest() != view["render_sha256"]:
                raise BundleIntegrityError(
                    f"{render_path} differs from the render the metrics scored"
                )
            reference_bytes = _verified_bytes(archive, inventory, reference_path)
            canvas = compose_view(
                Image.open(io.BytesIO(reference_bytes)),
                Image.open(io.BytesIO(render_bytes)),
                view,
                max_width=max_width,
            )
            target = output / f"{stem}-photograph-vs-render.jpg"
            canvas.save(target, format="JPEG", quality=88, optimize=True)
            comparisons.append(
                {
                    "view": stem,
                    "comparison": target.name,
                    "comparison_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "render": render_path,
                    "render_sha256": view["render_sha256"],
                    "reference": reference_path,
                    "reference_sha256": inventory[reference_path]["sha256"],
                    "source_sha256": view["source_sha256"],
                    "scores": {
                        key: view[key] for key in ("psnr", "ssim", "lpips", "coverage_fraction")
                    },
                }
            )
    summary = {
        "profile": PROFILE,
        "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "manifest_digest": metrics["manifest_digest"],
        "dataset_digest": metrics["dataset_digest"],
        "aggregate": {
            key: metrics[key]
            for key in (
                "psnr",
                "ssim",
                "lpips",
                "coverage_fraction",
                "floaters_fraction",
                "heldout_views",
            )
        },
        "max_width": max_width,
        "comparisons": comparisons,
        "claim": "appearance at held-out photographed viewpoints only; no physical scale, "
        "completeness or navigability",
    }
    (output / "comparisons.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def _resolve_bundle(args: argparse.Namespace) -> Path:
    if args.bundle is not None:
        return Path(args.bundle)
    digest = args.sha256.lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise SystemExit("--sha256 must be 64 hexadecimal characters")
    return Path(args.store) / "sha-256" / digest[:2] / digest[2:4] / digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--bundle", help="path to a retained scene_splat_evaluation_bundle ZIP")
    source.add_argument("--sha256", help="content digest of the bundle inside --store")
    parser.add_argument("--store", default=".exulanica/reference-baseline/runtime/blobs")
    parser.add_argument("--output", required=True, help="directory for the comparison JPEGs")
    parser.add_argument("--max-width", type=int, default=1600)
    parser.add_argument("--view", action="append", help="only this held-out view stem (repeatable)")
    args = parser.parse_args(argv)
    bundle = _resolve_bundle(args)
    if not bundle.is_file():
        raise SystemExit(f"bundle not found: {bundle}")
    try:
        summary = compose_bundle(
            bundle,
            Path(args.output),
            max_width=args.max_width,
            views=None if args.view is None else set(args.view),
        )
    except BundleIntegrityError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    for comparison in summary["comparisons"]:
        scores = comparison["scores"]
        print(f"{comparison['comparison']}  PSNR {scores['psnr']:.2f}  SSIM {scores['ssim']:.3f}")
    print(f"bundle {summary['bundle_sha256']}  {len(summary['comparisons'])} comparisons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
