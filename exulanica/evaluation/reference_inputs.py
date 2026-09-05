"""Freeze exact photographic inputs and an evaluation split before reconstruction.

This is preparation, never privacy admission. The review gallery links the exact
hashed originals; its blank review form cannot be mistaken for a human receipt.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from exulanica.canonical import canonical_json
from exulanica.corpus.decode import open_sensor

PROFILE = "exulanica.reference-inputs/v1"
ENVELOPE = "exulanica.digest-bound-record/v1"
RUBRIC = {
    "profile": "exulanica.reference-visual-rubric/v1",
    "score_meaning": {
        "0": "unusable or unavailable",
        "1": "major distracting defects",
        "2": "usable with visible defects",
        "3": "strong baseline with minor defects",
        "4": "excellent throughout the declared viewing envelope",
    },
    "dimensions": [
        "surface coherence, doubling, holes and thin structures",
        "colour, exposure, texture detail and floaters",
        "arrival, orientation and camera movement",
        "reconstruction boundary against authored world",
        "source inspection, loading, failure and return navigation",
    ],
    "acceptance": "every dimension at least 3; no concealed or unreported defects",
    "comparison": "same camera matrices, viewport, render settings and source split",
    "traversal": "first, central and last registered source poses plus adjacent-camera midpoints",
    "duration_seconds": 60,
    "viewport_css_px": [1280, 720],
    "prohibitions": ["fog or blur to conceal defects", "authored geometry hiding holes"],
    "numerical_results": "held-out PSNR, SSIM and LPIPS reported separately from visual scores",
    "physical_scale": "unmeasured until independently referenced; no inferred metre claims",
}


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def envelope(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": ENVELOPE,
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }


def read_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("reference inputs require a digest-bound record object")
    record = value.get("record")
    if value.get("profile") != ENVELOPE or not isinstance(record, dict):
        raise ValueError("reference inputs require a digest-bound record")
    if value != envelope(record) or record.get("profile") != PROFILE:
        raise ValueError("reference input manifest digest or profile does not verify")
    files = record.get("files")
    if not isinstance(files, list) or len(files) < 2:
        raise ValueError("reference input manifest needs at least two photographs")
    paths: set[str] = set()
    digests: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("reference input entries require a relative path string")
        relative = item["path"]
        pure = PurePosixPath(relative)
        if (
            not relative
            or relative == "."
            or pure.as_posix() != relative
            or pure.is_absolute()
            or ".." in pure.parts
            or "\\" in relative
        ):
            raise ValueError("reference input path escapes the source directory")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("reference source hashes must be lowercase SHA-256 hex")
        if any(
            type(item.get(field)) is not int or item[field] <= 0
            for field in ("bytes", "width", "height")
        ):
            raise ValueError("reference image sizes and dimensions must be positive integers")
        if relative in paths or item["sha256"] in digests:
            raise ValueError("reference inputs must have unique paths and unique source bytes")
        paths.add(relative)
        digests.add(item["sha256"])
    split = record.get("evaluation_split")
    if not isinstance(split, dict) or any(
        not isinstance(split.get(field), list)
        or any(not isinstance(value, str) for value in split[field])
        or len(set(split[field])) != len(split[field])
        for field in ("training_sha256", "heldout_sha256")
    ):
        raise ValueError("evaluation split must contain unique arrays of source hashes")
    train, heldout = set(split["training_sha256"]), set(split["heldout_sha256"])
    if not train or not heldout or train & heldout or train | heldout != digests:
        raise ValueError("training and held-out sets must partition the exact source inventory")
    return value


def verify_inputs(manifest: Path, source_directory: Path) -> dict[str, Any]:
    value = read_manifest(manifest)
    root = source_directory.resolve(strict=True)
    for item in value["record"]["files"]:
        path = root / item["path"]
        if (
            not path.is_file()
            or any(
                candidate.is_symlink()
                for candidate in (path, *path.parents)
                if candidate.is_relative_to(root)
            )
            or not path.resolve(strict=True).is_relative_to(root)
        ):
            raise ValueError("reference source must be a regular file within its source directory")
        if path.stat().st_size != item["bytes"] or digest_file(path) != item["sha256"]:
            raise ValueError(f"reference source changed: {item['path']}")
    return value


def prepare_inputs(
    source_directory: Path,
    output_directory: Path,
    *,
    title: str,
    official_source_url: str,
    license_name: str,
    license_file: Path,
    license_url: str,
    attribution: str,
    retrieval_date: str,
    heldout_every: int = 8,
) -> Path:
    """Create an immutable manifest, review page and intentionally unanswered review form."""
    if heldout_every < 2:
        raise ValueError("heldout_every must leave both training and evaluation images")
    if not official_source_url.startswith("https://") or not license_url.startswith("https://"):
        raise ValueError("official source and license URLs must use HTTPS")
    files = []
    root = source_directory.resolve(strict=True)
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
            continue
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError("symlinked reference inputs are refused")
        with open_sensor(path.read_bytes()) as image:
            width, height = image.size
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest_file(path),
                "width": width,
                "height": height,
            }
        )
    if len(files) < 2:
        raise ValueError("at least two distinct photographs are required")
    heldout = [item["sha256"] for i, item in enumerate(files) if i % heldout_every == 0]
    record = {
        "profile": PROFILE,
        "title": title,
        "corpus_class": "benchmark",
        "official_source_url": official_source_url,
        "retrieval_date": retrieval_date,
        "license": {
            "name": license_name,
            "url": license_url,
            "document_sha256": digest_file(license_file),
            "attribution": attribution,
        },
        "files": files,
        "evaluation_split": {
            "method": "lexicographically sorted relative path, index modulo heldout_every is zero",
            "heldout_every": heldout_every,
            "training_sha256": [item["sha256"] for item in files if item["sha256"] not in heldout],
            "heldout_sha256": heldout,
            "scope": "held-out RGB excluded from optimization; pose estimation may use all images",
        },
        "visual_rubric": RUBRIC,
        "privacy": {"state": "awaiting_named_human_exact_byte_review", "human_receipt": None},
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    manifest = output_directory / "inputs.json"
    payload = canonical_json(envelope(record))
    if manifest.exists() and manifest.read_bytes() != payload:
        raise ValueError("a frozen reference manifest exists; use a new output directory")
    manifest.write_bytes(payload)
    value = verify_inputs(manifest, root)
    review = {
        "profile": "exulanica.reference-human-review/v1",
        "source_manifest_sha256": value["record_sha256"],
        "reviewed_by_name": None,
        "reviewed_at": None,
        "attestation": None,
        "members": [
            {
                "sha256": item["sha256"],
                "path": item["path"],
                "no_visible_people_or_sensitive_regions": None,
            }
            for item in files
        ],
    }
    request = output_directory / "review-request.json"
    if not request.exists():
        request.write_text(json.dumps(review, indent=2) + "\n")
    cards = []
    for i, item in enumerate(files):
        uri = (root / item["path"]).as_uri()
        # File URLs preserve exact source bytes without generating replacement media.
        safe_uri = html.escape(uri, quote=True)
        cards.append(
            f'<figure><a href="{safe_uri}" target="_blank"><img loading="lazy" '
            f'src="{safe_uri}" alt="Photograph {i + 1}"></a><figcaption>'
            f"{i + 1}. {html.escape(item['path'])}<br>{item['width']} &times; {item['height']}"
            f"<br><code>{item['sha256']}</code></figcaption></figure>"
        )
    title_html = html.escape(title)
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title_html} — exact source review</title><style>"
        "body{font:16px system-ui;background:#eeeae2;color:#1e292d;margin:32px}"
        "main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}"
        "figure{margin:0;background:white;padding:12px}img{width:100%;height:300px;object-fit:contain}"
        "code{font-size:10px;overflow-wrap:anywhere}figcaption{line-height:1.6}</style>"
        f"<h1>{title_html}</h1><p>{len(files)} exact photographs. Click each to inspect the full "
        "original. No privacy screening has been recorded. An automated inspection cannot "
        "supply the named human review required by the reconstruction policy.</p>"
        f"<p>Inventory: <code>{value['record_sha256']}</code></p>"
        f'<p>{html.escape(attribution)} · <a href="{html.escape(license_url, quote=True)}">'
        f"{html.escape(license_name)}</a></p><main>{''.join(cards)}</main></html>"
    )
    (output_directory / "review.html").write_text(page)
    return manifest


def gallery_http_html(path: Path, source_root: Path, source_prefix: str) -> str:
    """Adapt file links for a local static server rooted at the retained input directory."""
    return path.read_text().replace(source_root.resolve().as_uri(), quote(source_prefix, safe="/"))
