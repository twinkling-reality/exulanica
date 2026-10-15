"""Write original reusable palette modules and self-contained looks from an authoring document.

No world layout or simulation is generated here. Output is admitted through workspace style-pack
uploads; the repository's default library is unaffected. Dimensions and roles are declared data.

A ``tree`` row names a species of the tree maker's catalog (``tree_maker.py``), a height, an
optional width and a seed: the tree is grown to that box as a textured piece with its second level
(``<file stem>-far.glb``), from the scans in the folder ``--sources`` names. Rows of one role become
that role's variants, at most eight, in the document's order. What made each tree is written beside
the packs as ``<pack id>.trees.json``.
"""

from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.style_packs.authored_packs import Piece  # noqa: E402, standalone CLI bootstrap
from scripts.style_packs.architecture import (  # noqa: E402, standalone CLI bootstrap
    ARCHITECTURE_RECIPES,
    ARCHITECTURE_SWATCHES,
    validate_architecture_row,
)
from scripts.style_packs import tree_maker  # noqa: E402, standalone CLI bootstrap
from exulanica.world import style_packs  # noqa: E402, standalone CLI bootstrap
from exulanica.world.style_pack_pieces import read_palette_piece  # noqa: E402, standalone CLI bootstrap

#: The fields a ``tree`` row states, the width optional.
TREE_ROW = frozenset({"recipe", "role", "file", "species", "height_mm", "seed"})


def rounded_slab(piece, width, depth, bottom, top, radius, segments, key):
    ring = []
    for x, z, start in [
        (width / 2 - radius, depth / 2 - radius, 0),
        (-width / 2 + radius, depth / 2 - radius, 90),
        (-width / 2 + radius, -depth / 2 + radius, 180),
        (width / 2 - radius, -depth / 2 + radius, 270),
    ]:
        for i in range(segments + 1):
            a = math.radians(start + i * 90 / segments)
            ring.append((x + radius * math.cos(a), z + radius * math.sin(a)))
    piece.face([(x, top, z) for x, z in ring], key, (0, 1, 0))
    piece.face([(x, bottom, z) for x, z in ring], key, (0, -1, 0))
    for i, (x, z) in enumerate(ring):
        nx, nz = ring[(i + 1) % len(ring)]
        piece.face(
            [(x, bottom, z), (nx, bottom, nz), (nx, top, nz), (x, top, z)],
            key,
            ((x + nx) / 2, 0, (z + nz) / 2),
        )


def vault_shell(row):
    w, d, h = [n / 1000 for n in row["size_mm"]]
    piece = Piece()
    count = row["segments"]

    def top(q):
        return h * 0.5 * (1 - q * q)

    def bottom(q):
        return top(q) - h * row["shell_share_permille"] / 1000 * (1 - abs(q))

    for i in range(count):
        q0 = -1 + 2 * i / count
        q1 = -1 + 2 * (i + 1) / count
        z0 = q0 * d / 2
        z1 = q1 * d / 2
        piece.face(
            [
                (-w / 2, top(q0), z0),
                (w / 2, top(q0), z0),
                (w / 2, top(q1), z1),
                (-w / 2, top(q1), z1),
            ],
            "porcelain",
            (0, 1, (q0 + q1) / 2),
        )
        piece.face(
            [
                (-w / 2, bottom(q0), z0),
                (w / 2, bottom(q0), z0),
                (w / 2, bottom(q1), z1),
                (-w / 2, bottom(q1), z1),
            ],
            "porcelain",
            (0, -1, -(q0 + q1) / 2),
        )
        for sign in [-1, 1]:
            x = sign * w / 2
            piece.face(
                [(x, bottom(q0), z0), (x, top(q0), z0), (x, top(q1), z1), (x, bottom(q1), z1)],
                "accent",
                (sign, 0, 0),
            )
    # Every vertex is inside the served gable's occupied envelope, not just its box.
    for x, y, z in piece.corners:
        if not (
            abs(x) <= w / 2 + 1e-8
            and abs(z) <= d / 2 + 1e-8
            and -1e-8 <= y <= h * (1 - abs(z) / (d / 2)) + 1e-8
        ):
            raise ValueError("vault leaves its gabled roof envelope")
    return piece


def rounded_seat(row):
    w, d, h = [n / 1000 for n in row["size_mm"]]
    piece = Piece()
    r = min(row["corner_radius_mm"] / 1000, w / 2, d / 2)
    rounded_slab(piece, w, d, h * 0.16, h * 0.76, r, row["segments"], "porcelain")
    rounded_slab(piece, w * 0.98, d * 0.98, h * 0.76, h, r * 0.95, row["segments"], "accent")
    for sign in [-1, 1]:
        piece.box(
            (sign * w * 0.33 - w * 0.07, sign * w * 0.33 + w * 0.07),
            (0, h * 0.17),
            (-d * 0.34, d * 0.34),
            "porcelain",
        )
    return piece


def fan_tree(row):
    w, d, h = [n / 1000 for n in row["size_mm"]]
    piece = Piece()
    piece.prism(1, (0, h * 0.325, 0), min(w, d) * 0.055, h * 0.65, 12, "bark")
    radius = min(w, d) * 0.49
    for k in range(row["fronds"]):
        angle = 2 * math.pi * k / row["fronds"]
        dx, dz = math.cos(angle), math.sin(angle)
        tier = (k % 3) * 0.1
        for i in range(row["segments"]):
            t0 = i / row["segments"]
            t1 = (i + 1) / row["segments"]

            def p(t, side, dx=dx, dz=dz, tier=tier):
                spread = radius * 0.46 * math.sin(math.pi * t)
                return (
                    dx * radius * t - dz * spread * side,
                    h * (0.48 + tier) + h * 0.22 * math.sin(math.pi * t) - h * 0.03 * t * t,
                    dz * radius * t + dx * spread * side,
                )

            piece.face([p(t0, -1), p(t1, -1), p(t1, 1), p(t0, 1)], "leaf", (0, 1, 0))
            piece.face([p(t0, -1), p(t1, -1), p(t1, 1), p(t0, 1)], "leaf", (0, -1, 0))
    return piece


def flower_cluster(row):
    width, depth, height = [n / 1000 for n in row["size_mm"]]
    piece = Piece()
    for bloom in range(row["blooms"]):
        angle = 2 * math.pi * bloom / row["blooms"]
        x = math.cos(angle) * width * 0.29
        z = math.sin(angle) * depth * 0.29
        top = height * (0.63 + 0.12 * (bloom % 3))
        piece.prism(1, (x, top / 2, z), min(width, depth) * 0.012, top, 6, "leaf")
        for side in [-1, 1]:
            piece.face(
                [
                    (x, top * 0.4, z),
                    (x + side * width * 0.12, top * 0.52, z + depth * 0.04),
                    (x + side * width * 0.18, top * 0.6, z),
                    (x, top * 0.5, z - depth * 0.025),
                ],
                "leaf",
                (0, 1, 0),
            )
        for petal in range(5):
            a = angle + petal * 2 * math.pi / 5
            cx = x + math.cos(a) * width * 0.07
            cz = z + math.sin(a) * depth * 0.07
            ring = []
            for sample in range(row["segments"]):
                theta = sample * 2 * math.pi / row["segments"]
                along = math.cos(theta) * width * 0.085
                across = math.sin(theta) * depth * 0.04
                ring.append(
                    (
                        cx + along * math.cos(a) - across * math.sin(a),
                        top + height * 0.055 * math.sin(theta) ** 2,
                        cz + along * math.sin(a) + across * math.cos(a),
                    )
                )
            piece.face(ring, "flower", (0, 1, 0))
            piece.face(list(reversed(ring)), "flower", (0, -1, 0))
    return piece


RECIPES = {
    "vault_shell": vault_shell,
    "rounded_seat": rounded_seat,
    "fan_tree": fan_tree,
    "flower_cluster": flower_cluster,
    **ARCHITECTURE_RECIPES,
}


def validate_document(document):
    if document.get("profile") != "exulanica.authored-garden-kit/v1":
        raise ValueError("unknown kit profile")
    if type(document.get("look_family_catalog_version")) is not int or document[
        "look_family_catalog_version"
    ] not in (1, 2):
        raise ValueError("the kit selects a retained appearance catalog")
    if (
        not 1 <= len(document.get("pieces", [])) <= 128
        or not 1 <= len(document.get("variants", [])) <= 16
    ):
        raise ValueError("the kit has bounded piece and variant counts")
    for variant in document["variants"]:
        colours = variant.get("architecture_srgb8", {})
        keys = {key for key, *_ in ARCHITECTURE_SWATCHES}
        if (
            not isinstance(colours, dict)
            or not set(colours) <= keys
            or any(
                not isinstance(rgb, list)
                or len(rgb) != 3
                or any(type(c) is not int or not 0 <= c <= 255 for c in rgb)
                for rgb in colours.values()
            )
        ):
            raise ValueError("architecture colours name its swatches with three 8-bit channels")
    roles: dict[str, int] = {}
    for row in document["pieces"]:
        roles[row.get("role")] = roles.get(row.get("role"), 0) + 1
        if roles[row.get("role")] > 8:
            raise ValueError("a role takes at most eight variants")
        if row.get("recipe") == "tree":
            if not TREE_ROW <= set(row) <= TREE_ROW | {"width_mm"}:
                raise ValueError(
                    "a tree row states its role, file, species, height, seed and width"
                )
            if not isinstance(row["species"], str) or not isinstance(row["role"], str):
                raise ValueError("a tree row names its species and role")
            for key in ("height_mm", "seed", "width_mm"):
                if key in row and type(row[key]) is not int:
                    raise ValueError("a tree row's numbers are whole")
            path = Path(row["file"])
            if path.is_absolute() or ".." in path.parts or path.suffix != ".glb":
                raise ValueError("a module is written inside its pack")
            continue
        if row.get("recipe") not in RECIPES:
            raise ValueError("unknown module recipe")
        if len(row.get("size_mm", [])) != 3 or any(
            type(n) is not int or not 1 <= n <= 50_000 for n in row["size_mm"]
        ):
            raise ValueError(
                "module dimensions are positive integer millimetres within the piece contract"
            )
        if type(row.get("segments")) is not int or not 3 <= row["segments"] <= 96:
            raise ValueError("module segments are bounded integers")
        if row["recipe"] == "vault_shell" and (
            type(row.get("shell_share_permille")) is not int
            or not 1 <= row["shell_share_permille"] <= 100
        ):
            raise ValueError("vault shell thickness is bounded")
        if row["recipe"] == "rounded_seat" and (
            type(row.get("corner_radius_mm")) is not int
            or not 1 <= row["corner_radius_mm"] <= min(row["size_mm"][:2]) // 2
        ):
            raise ValueError("seat radius fits its declared footprint")
        if row["recipe"] == "fan_tree" and (
            type(row.get("fronds")) is not int or not 1 <= row["fronds"] <= 24
        ):
            raise ValueError("frond count is bounded")
        if row["recipe"] == "flower_cluster" and (
            type(row.get("blooms")) is not int or not 1 <= row["blooms"] <= 16
        ):
            raise ValueError("bloom count is bounded")
        if row["recipe"] in ARCHITECTURE_RECIPES:
            validate_architecture_row(row)
        path = Path(row["file"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("a module is written inside its pack")


def _far(file: str) -> str:
    """A tree's second level beside its first: ``pieces/pine.glb`` to ``pieces/pine-far.glb``."""
    return file[: -len(".glb")] + "-far.glb"


def _trees(document, sources):
    """Every tree row made once, by its index: the maker's MadeTree."""
    rows = [(index, row) for index, row in enumerate(document["pieces"]) if row["recipe"] == "tree"]
    if not rows:
        return {}
    if sources is None:
        raise ValueError("a kit with trees names the folder of its scans (--sources)")
    catalog = tree_maker.read_catalog(json.loads((ROOT / tree_maker.CATALOG).read_text()))
    found = tree_maker.Sources(catalog, sources)
    return {
        index: tree_maker.make_tree(
            catalog, row["species"], row["height_mm"], row["seed"], found, row.get("width_mm")
        )
        for index, row in rows
    }


def build(document, output, sources=None):
    validate_document(document)
    trees = _trees(document, sources)
    table = json.loads((ROOT / "assets/colour/srgb8-linear16.v1.json").read_text())["values"]
    base = json.loads(
        (ROOT / "assets/style-packs/published/exulanica.finished-town/2/manifest.json").read_text()
    )
    version = document["look_family_catalog_version"]
    catalog = ROOT / f"assets/catalogs/world-kinds/look-family.v{version}.json"
    pin = {"version": version, "sha256": hashlib.sha256(catalog.read_bytes()).hexdigest()}
    for variant in document["variants"]:
        folder = output / variant["pack_id"]
        (folder / "pieces").mkdir(parents=True, exist_ok=True)
        manifest = json.loads(json.dumps(base))
        manifest.update(
            pack_id=variant["pack_id"],
            version=variant.get("version", 1),
            title=variant["title"],
            description=variant["description"],
            origin="uploaded",
            provenance={"kind": "uploaded"},
            authors=["Exulanica"],
            tags=["garden", "glass", "original"],
            base=None,
            preview=None,
            look_family_catalog=pin,
            modules={},
            files=[],
        )
        palette = []
        for key, rgb, rough, metal in [
            ("porcelain", [237, 244, 239], 220, 0),
            ("accent", variant["accent"], 280, 0),
            ("leaf", variant["leaf"], 750, 0),
            ("bark", [150, 168, 137], 850, 0),
            ("grass", [95, 136, 105], 950, 0),
            ("paving", [208, 220, 215], 650, 0),
            ("water", [49, 146, 164], 90, 0),
            ("flower", variant.get("flower", [241, 192, 209]), 650, 0),
        ]:
            palette.append(
                dict(
                    key=key,
                    srgb8=rgb,
                    roughness_permille=rough,
                    metalness_permille=metal,
                    emission_permille=0,
                )
            )
        # Architecture pieces draw with six more swatches, added only when the kit has one, so a
        # kit without them keeps its palette and its bytes.
        if any(row["recipe"] in ARCHITECTURE_RECIPES for row in document["pieces"]):
            colours = variant.get("architecture_srgb8", {})
            for key, rgb, rough, metal in ARCHITECTURE_SWATCHES:
                palette.append(
                    dict(
                        key=key,
                        srgb8=list(colours.get(key, rgb)),
                        roughness_permille=rough,
                        metalness_permille=metal,
                        emission_permille=0,
                    )
                )
        manifest["palette"]["swatches"] = palette
        manifest["surfaces"] = {
            **{
                role: {"swatch": key, "up": None}
                for role, key in [
                    ("ground.default", "grass"),
                    ("ground.grass", "grass"),
                    ("ground.paving", "paving"),
                    ("path.paving", "paving"),
                    ("roof.default", "porcelain"),
                    ("roof.concrete", "porcelain"),
                    ("water.default", "water"),
                    ("water.pond", "water"),
                ]
            },
            "wall.glass": {"texture_set": "cc0.float-glazing", "up": None},
            "wall.default": {"swatch": "porcelain", "up": None},
        }
        # A roof leaf takes its module before the family's surface default.
        receipts = []
        for index, row in enumerate(document["pieces"]):
            variants = manifest["modules"].setdefault(row["role"], {"variants": []})["variants"]
            if index in trees:
                made = trees[index]
                for path, payload in ((row["file"], made.lod0), (_far(row["file"]), made.lod1)):
                    (folder / path).write_bytes(payload)
                    manifest["files"].append(
                        dict(
                            path=path,
                            sha256=hashlib.sha256(payload).hexdigest(),
                            bytes=len(payload),
                            media_type="model/gltf-binary",
                        )
                    )
                variants.append(
                    dict(
                        file=row["file"],
                        lod1=_far(row["file"]),
                        size_mm=list(made.size_mm),
                        stretch_mm=[None, None, None],
                    )
                )
                receipts.append({"file": row["file"], "role": row["role"], **made.receipt})
                continue
            piece = RECIPES[row["recipe"]](row)
            # Tapered ends meet at one point. Omit their zero-area fan triangles before writing.
            corners = []
            keys = []
            for i, key in enumerate(piece.keys):
                triangle = np.round(np.asarray(piece.corners[i * 3 : i * 3 + 3]), 4)
                if (
                    np.linalg.norm(np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0]))
                    > 1e-10
                ):
                    corners.extend(tuple(p) for p in triangle)
                    keys.append(key)
            piece.corners = corners
            piece.keys = keys
            points = np.asarray(piece.corners)
            w, d, h = [value / 1000 for value in row["size_mm"]]
            minimum = points.min(axis=0)
            maximum = points.max(axis=0)
            if np.any(minimum < np.asarray([-w / 2, 0, -d / 2]) - 0.0001) or np.any(
                maximum > np.asarray([w / 2, h, d / 2]) + 0.0001
            ):
                raise ValueError("a module leaves its declared dimensions")
            payload = piece.bytes(palette, table)
            read_palette_piece(payload, table)
            (folder / row["file"]).write_bytes(payload)
            variants.append(
                dict(
                    file=row["file"],
                    lod1=None,
                    size_mm=row["size_mm"],
                    stretch_mm=[None, None, None],
                )
            )
            manifest["files"].append(
                dict(
                    path=row["file"],
                    sha256=hashlib.sha256(payload).hexdigest(),
                    bytes=len(payload),
                    media_type="model/gltf-binary",
                )
            )
        manifest["files"].sort(key=lambda f: f["path"])
        day = manifest["light"]["presets"]["day"]
        manifest["light"]["presets"] = {"day": day}
        manifest["light"]["default_preset"] = "day"
        day["sky"].update(
            zenith=variant["sky_zenith"],
            horizon=variant["sky_horizon"],
            ground=[107, 144, 121],
            bounce_ground=[146, 172, 149],
            sun_glow_permille=700,
            face_texels=128,
        )
        day["sky"]["clouds"].update(cover_permille=170, scale_permille=1800)
        day["sun"].update(
            elevation_mdeg=variant["sun_elevation_mdeg"],
            azimuth_mdeg=142000,
            intensity_permille=1550,
            colour=[255, 242, 217],
        )
        day["fog"].update(colour=variant["sky_horizon"], density_micro=600)
        day["exposure_permille"] = 920
        day["environment"]["intensity_permille"] = 650
        day["post"]["enhance"].update(shadows_permille=0, highlights_permille=-20)
        day["post"]["vignette"] = None
        day["post"]["bloom"]["intensity_permille"] = 25
        manifest["edge"].update(ground=[95, 136, 105], reach_mm=2000000, drop_mm=200)
        # A variant may state the optional finish: an analytic sky (with the sky's brightness it
        # is drawn at), haze, and a water finish. The reader below holds every value to its range.
        finish = variant.get("finish")
        if finish is not None:
            if "sky_model" in finish:
                day["sky"]["model"] = finish["sky_model"]
                day["sky"]["intensity_permille"] = finish["sky_intensity_permille"]
            if "haze" in finish:
                day["haze"] = finish["haze"]
            if "water" in finish:
                manifest["water"] = finish["water"]
        checked = style_packs.read_manifest(manifest, style_packs.load_context(ROOT))
        (folder / "manifest.json").write_text(style_packs.canonical_json(checked) + "\n")
        if receipts:
            (output / f"{variant['pack_id']}.trees.json").write_text(
                json.dumps(receipts, indent=1, sort_keys=True) + "\n"
            )
        print(
            variant["pack_id"],
            hashlib.sha256(style_packs.canonical_json(checked).encode()).hexdigest(),
            sum(f["bytes"] for f in checked["files"]),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sources", type=Path, help="the folder of the unpacked scans trees read")
    args = parser.parse_args()
    build(json.loads(args.document.read_text()), args.out, args.sources)
