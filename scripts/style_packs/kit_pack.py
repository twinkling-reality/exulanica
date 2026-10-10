"""The kit places pack: ready-made pieces from open kits, drawn on the cozy town.

    uv run python scripts/style_packs/kit_pack.py                    # write the manifest
    uv run python scripts/style_packs/kit_pack.py --check            # refuse if a committed byte differs
    .venv/bin/python -I scripts/style_packs/kit_pack.py --convert DIR  # convert the kits' models

``assets/style-packs/kits/kit-places.v1.json`` states what the pack is made from: each kit's archive
as it was fetched (its size, its SHA-256, the licence file read inside it) and each piece's model,
what is left out of it, how it stands and how long its longest side is. The pack is
``assets/style-packs/packs/exulanica.kit-places/``: a manifest drawn on the cozy town, which states
only what it adds (its own swatches and one module a look role), and the pieces under ``pieces/``.
A ``preview.jpg`` committed in that folder (the pack drawn by the product on a place that has its
pieces, captured once with the interface hidden) is listed as the pack's preview; this script never
makes it.

Two steps, because a kit's archive is not in this repository:

*   ``--convert DIR`` reads each model from the unpacked kits under ``DIR`` (one folder a kit,
    named as the catalog names it) with :mod:`kit_models`, and writes the pieces and
    ``kit-places.built.v1.json``, the record of each conversion: the model's and its pictures'
    digests, what was left out, the size it was given, the swatches, the piece's digest. The archive
    is untrusted data: its files are parsed, never run, and this is run with ``-I`` from outside the
    unpacked folders. It needs numpy and Pillow.
*   With no flag it writes the manifest from the catalog, the built record and the committed
    pieces, and needs neither the kits nor numpy. A pack drawn on a base names that base's version
    and digest, so this is run again when the cozy town moves; the pieces do not change.

A piece keeps its kit's colours. Every triangle of a kit model has one colour (read from the kit's
shared picture, or its material); the colours of all the pieces, heaviest first by the area they
cover, become swatches, a colour joining a swatch already made when it is within the catalog's
distance of it in OKLab, so a gradient's steps become one swatch and a kit's plank brown stays the
kit's. Each triangle then takes its nearest swatch. A catalog whose distance leaves more swatches
than it allows is refused, never trimmed.

A piece is glTF metres, +Y up, +Z front, pivot at the base centre, positions rounded to a tenth of a
millimetre.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from exulanica.world import style_packs  # noqa: E402

CATALOG: Final = Path("assets/style-packs/kits/kit-places.v1.json")
BUILT: Final = Path("assets/style-packs/kits/kit-places.built.v1.json")
PACKS: Final = Path("assets/style-packs/packs")
CATALOG_PROFILE: Final = "exulanica.kit-pack-sources/v1"
BUILT_PROFILE: Final = "exulanica.kit-pack-built/v1"
#: The pack's committed preview picture, inside its folder: listed when it is there, never made here.
PREVIEW: Final = "preview.jpg"
#: A kit swatch's surface: matt, as the cozy town's are.
ROUGHNESS_PERMILLE: Final = 850
#: Triangles thinner than this (square metres, at the piece's stated size) have no normal to write.
_NO_AREA: Final = 1e-10
_AXIS_OF: Final = {"width": 0, "height": 1, "depth": 2}


def read_catalog(root: Path) -> dict[str, Any]:
    catalog = json.loads((root / CATALOG).read_text(encoding="utf-8"))
    if catalog.get("profile") != CATALOG_PROFILE:
        raise ValueError(f"{CATALOG} is not {CATALOG_PROFILE}")
    return dict(catalog)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(document: Any) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def _reader() -> Any:
    """:mod:`kit_models`, loaded by its path: under ``-I`` a script's folder is not searched."""
    spec = importlib.util.spec_from_file_location(
        "exulanica_kit_models", Path(__file__).with_name("kit_models.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pictures(path: Path) -> list[Path]:
    """The picture files a ``.gltf`` names beside itself; a ``.glb`` carries its own."""
    if path.suffix.lower() != ".gltf":
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    named = [
        item.get("uri") for item in (*document.get("images", ()), *document.get("buffers", ()))
    ]
    return [path.parent / uri for uri in named if uri is not None and not uri.startswith("data:")]


def convert(root: Path, kits: Path) -> dict[str, bytes]:
    """Every converted piece and the built record, by path under ``root``."""
    import numpy as np

    from exulanica_pieces.colour import read_table
    from exulanica_pieces.geometry.glb import write_glb
    from exulanica_pieces.geometry.mesh import Mesh, fit, orient
    from exulanica_pieces.geometry.palette import _oklab, nearest_swatch

    reader = _reader()
    catalog = read_catalog(root)
    table, _digest = read_table(root)
    budgets = style_packs.read_piece_budgets(root)
    meshes: list[tuple[dict[str, Any], Mesh, dict[str, Any]]] = []
    for piece in catalog["pieces"]:
        kit = catalog["kits"][piece["kit"]]
        model = kits / piece["kit"] / kit["models"] / piece["model"]
        licence = kits / piece["kit"] / kit["licence_file"]
        raw = reader.read_kit_model(model, tuple(piece["leave_out"]))
        mesh, _step = orient(raw, piece["up"], piece["front"])
        # The longest side as the catalog names it, the others in the kit's own proportion.
        side = piece["longest_mm"]
        mesh, step = fit(mesh, "contain", {"width": side, "height": side, "depth": side})
        size = step["size_mm"]
        if size[piece["longest_is"]] != side:
            raise ValueError(f"{piece['file']}: its longest side is not its {piece['longest_is']}")
        positions = np.round(mesh.positions, 4)
        corners = positions[mesh.triangles]
        area = (
            np.linalg.norm(
                np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1
            )
            / 2
        )
        kept = area > _NO_AREA
        mesh = Mesh(positions, mesh.triangles[kept], mesh.colours).compact()
        record = {
            "file": piece["file"],
            "role": piece["role"],
            "model": {
                "path": piece["model"],
                "bytes": model.stat().st_size,
                "sha256": _sha256(model.read_bytes()),
            },
            "read_with": sorted(
                [
                    {
                        "file": extra.name,
                        "bytes": extra.stat().st_size,
                        "sha256": _sha256(extra.read_bytes()),
                    }
                    for extra in _pictures(model)
                ],
                key=lambda item: item["file"],
            ),
            "licence_file_sha256": _sha256(licence.read_bytes()),
            "left_out": list(piece["leave_out"]),
            "triangles_read": len(raw.triangles),
            "triangles_without_area": int((~kept).sum()),
            "size_mm": [size["width"], size["depth"], size["height"]],
            "scale_per_million": step["scale_per_million"],
        }
        meshes.append((piece, mesh, record))

    # Swatches: every piece's colours, heaviest first by the area they cover.
    weight: dict[tuple[int, int, int], float] = {}
    for _piece, mesh, _record in meshes:
        corners = mesh.positions[mesh.triangles]
        area = (
            np.linalg.norm(
                np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1
            )
            / 2
        )
        for colour, share in zip(
            mesh.colours[mesh.triangles[:, 0]].tolist(), area.tolist(), strict=True
        ):
            weight[tuple(colour)] = weight.get(tuple(colour), 0.0) + share
    ordered = sorted(weight, key=lambda colour: (-round(weight[colour], 6), colour))
    apart = catalog["pack"]["swatch_distance_permille"] / 1000
    chosen: list[tuple[int, int, int]] = []
    for colour in ordered:
        if chosen:
            gaps = np.linalg.norm(_oklab(np.array(chosen)) - _oklab(np.array([colour])), axis=1)
            if float(gaps.min()) <= apart:
                continue
        chosen.append(colour)
    most = catalog["pack"]["swatches_most"]
    if len(chosen) > most:
        raise ValueError(f"{len(chosen)} swatches at {apart} apart, and the catalog allows {most}")
    palette = [list(colour) for colour in chosen]
    swatches = [
        {
            "key": "kit_{:02x}{:02x}{:02x}".format(*colour),
            "srgb8": list(colour),
            "roughness_permille": ROUGHNESS_PERMILLE,
            "metalness_permille": 0,
            "emission_permille": 0,
        }
        for colour in chosen
    ]

    out: dict[str, bytes] = {}
    records = []
    folder = PACKS / catalog["pack"]["pack_id"]
    for piece, mesh, record in meshes:
        swatch = nearest_swatch(mesh.colours[mesh.triangles[:, 0]], palette)
        flat = Mesh(
            mesh.positions[mesh.triangles].reshape(-1, 3),
            np.arange(len(mesh.triangles) * 3, dtype=np.int64).reshape(-1, 3),
            np.asarray(palette, dtype=np.uint8)[np.repeat(swatch, 3)],
        )
        glb = write_glb(flat, swatch, palette, table)
        budget = budgets[piece["role"].split(".")[0]]
        triangles = len(flat.triangles)
        if len(glb) > budget.glb_bytes or triangles > budget.triangle_limit(record["size_mm"][0]):
            raise ValueError(f"{piece['file']} is over its family's budget")
        record |= {
            "triangles": triangles,
            "swatches_used": sorted({swatches[int(index)]["key"] for index in swatch}),
            "bytes": len(glb),
            "sha256": _sha256(glb),
        }
        records.append(record)
        out[str(folder / piece["file"])] = glb
    out[str(BUILT)] = _json(
        {
            "profile": BUILT_PROFILE,
            "written_by": "scripts/style_packs/kit_pack.py --convert",
            "catalog_sha256": _sha256((root / CATALOG).read_bytes()),
            "swatches": swatches,
            "pieces": records,
        }
    )
    return out


def manifest(root: Path) -> dict[str, bytes]:
    """The pack's manifest by its path under ``root``, from the catalog, the built record, the
    committed pieces and the library's current version of its base."""
    catalog = read_catalog(root)
    pack = catalog["pack"]
    built = json.loads((root / BUILT).read_text(encoding="ascii"))
    if built.get("profile") != BUILT_PROFILE:
        raise ValueError(f"{BUILT} is not {BUILT_PROFILE}")
    if built["catalog_sha256"] != _sha256((root / CATALOG).read_bytes()):
        raise ValueError(f"{BUILT} was converted from another {CATALOG.name}; convert again")
    folder = PACKS / pack["pack_id"]
    stated = {(piece["file"], piece["role"]) for piece in catalog["pieces"]}
    if stated != {(record["file"], record["role"]) for record in built["pieces"]}:
        raise ValueError(f"{BUILT} does not hold exactly the catalog's pieces")
    modules: dict[str, Any] = {}
    files = []
    for record in built["pieces"]:
        data = (root / folder / record["file"]).read_bytes()
        if (_sha256(data), len(data)) != (record["sha256"], record["bytes"]):
            raise ValueError(f"{record['file']} is not the piece {BUILT.name} records")
        modules.setdefault(record["role"], {"variants": []})["variants"].append(
            {
                "file": record["file"],
                "lod1": None,
                "size_mm": record["size_mm"],
                "stretch_mm": [None, None, None],
            }
        )
        files.append(
            {
                "path": record["file"],
                "sha256": record["sha256"],
                "bytes": record["bytes"],
                "media_type": "model/gltf-binary",
            }
        )
    preview = root / folder / PREVIEW
    if preview.is_file():
        picture = preview.read_bytes()
        files.append(
            {
                "path": PREVIEW,
                "sha256": _sha256(picture),
                "bytes": len(picture),
                "media_type": "image/jpeg",
            }
        )
    base_text = (root / PACKS / pack["base"] / "manifest.json").read_bytes()
    base = json.loads(base_text)
    document = {
        "profile": style_packs.PROFILE,
        "pack_id": pack["pack_id"],
        "version": pack["version"],
        "title": pack["title"],
        "description": pack["description"],
        "tags": list(pack["tags"]),
        "origin": "imported",
        "provenance": {"kind": "imported", "source_reference": pack["source_reference"]},
        "licence": {"id": "CC0-1.0", "attribution": None},
        "authors": list(pack["authors"]),
        "preview": PREVIEW if preview.is_file() else None,
        "base": {
            "pack_id": base["pack_id"],
            "version": base["version"],
            "manifest_sha256": hashlib.sha256(base_text[:-1]).hexdigest(),
        },
        "light": None,
        "shading": None,
        "edge": None,
        "palette": {"encoding": style_packs.COLOUR_ENCODING, "swatches": built["swatches"]},
        "surfaces": {},
        "modules": modules,
        "files": sorted(files, key=lambda file: file["path"]),
    }
    style_packs.read_manifest(document, style_packs.load_context(root))
    text = (style_packs.canonical_json(document) + "\n").encode("ascii")
    return {str(folder / "manifest.json"): text}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="refuse if a committed file differs")
    parser.add_argument("--convert", type=Path, metavar="DIR", help="the unpacked kits' folder")
    args = parser.parse_args(argv)
    if args.convert is not None:
        if args.check:
            parser.error("--convert writes; it does not check")
        if ROOT in args.convert.resolve().parents or args.convert.resolve() == ROOT:
            parser.error("the unpacked kits stay outside this repository")
        for name, data in convert(ROOT, args.convert).items():
            path = ROOT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    stale = []
    for name, data in manifest(ROOT).items():
        path = ROOT / name
        if args.check:
            if not path.is_file() or path.read_bytes() != data:
                stale.append(name)
            continue
        path.write_bytes(data)
    catalog = read_catalog(ROOT)
    inside = PACKS / catalog["pack"]["pack_id"]
    listed = (
        set(manifest(ROOT))
        | {str(inside / piece["file"]) for piece in catalog["pieces"]}
        | {str(inside / PREVIEW)}
    )
    folder = ROOT / inside
    stale.extend(
        f"{path.relative_to(ROOT)} (nothing lists it)"
        for path in sorted(folder.rglob("*"))
        if path.is_file() and str(path.relative_to(ROOT)) not in listed
    )
    if stale:
        print("stale:\n" + "\n".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
