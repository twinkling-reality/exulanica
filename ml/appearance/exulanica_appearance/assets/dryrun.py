"""The whole route with a stub in place of the models: requests, a job, pieces and receipts.

The stub stands where the concept picture, the cut-out and the 3D model stand on the rented
machine. It returns fixed shapes in the frame route A's model writes (+Z up, front -Y), coloured
as a model would colour them (near the palette, not on it), so every step after the model runs
for real: orient, simplify, fit, palette, write, measure and the records. Nothing it makes is a
candidate piece; its route is ``S`` and its container ``stub``.
"""

from __future__ import annotations

import io
import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import numpy as np
from exulanica_pieces.budgets import read_budgets
from exulanica_pieces.canonical import canonical_bytes, sha256_hex
from exulanica_pieces.geometry.mesh import Mesh, Simplifier, cluster_simplify
from exulanica_pieces.geometry.postprocess import POSTPROCESS_VERSION
from exulanica_pieces.records import build_job, build_request, cache_key
from PIL import Image

from exulanica_appearance.assets.job import RawMesh, run_job
from exulanica_appearance.assets.sheet import draw_sheet

__all__ = [
    "CASE_PATH",
    "CASE_PROFILE",
    "GRIP_SECTION_MM_MAXIMUM",
    "STUB_PACK",
    "StubBackend",
    "case_bytes",
    "dry_run",
    "stub_mesh",
]

#: One held piece's request, job and receipt from the dry run, for readers outside this package
#: (the origin record's reader) to test against real records. Relative to the repository root.
CASE_PATH: Final = "tests/fixtures/generated-piece/sword-case.v1.json"
CASE_PROFILE: Final = "exulanica.generated-piece-case/v1"

#: humanoid/v1's grip_section_mm_maximum, the widest section a closed adult hand goes around. The
#: body plan catalog states it; this stays the stub's own copy until that catalog lands, then the
#: dry run reads it there.
GRIP_SECTION_MM_MAXIMUM: Final = 60

STUB_PACK: Final = {
    "id": "stub.toon-town",
    "palette": [
        [46, 42, 40],
        [120, 78, 48],
        [176, 120, 72],
        [70, 132, 64],
        [128, 180, 88],
        [214, 72, 58],
        [236, 228, 210],
        [74, 112, 168],
    ],
    "sha256": "0" * 64,
    "style": "toon style, flat colours, chunky simple shapes",
    "version": 1,
}

#: What the stub is asked for: the trial's six pieces, the shopfront dressed per opening. The lantern
#: and the sword take the thing kinds' boxes and grips (slot frame: x across, y deep, z up): the
#: sword extends up from a grip 150 mm above its pommel, the lantern hangs below its ring.
STUB_REQUESTS: Final = (
    {"look_role": "prop.bench", "slot_mm": {"width": 1800, "height": 900, "depth": 700}},
    {
        "look_role": "prop.lantern",
        "slot_mm": {"width": 180, "height": 300, "depth": 180},
        "hold": {
            "axis": "-z",
            "grip": {"x_mm": 0, "y_mm": 0, "z_mm": 290},
            "section_mm_maximum": GRIP_SECTION_MM_MAXIMUM,
        },
    },
    {
        "look_role": "prop.sword",
        "slot_mm": {"width": 120, "height": 1000, "depth": 40},
        "hold": {
            "axis": "+z",
            "grip": {"x_mm": 0, "y_mm": 0, "z_mm": 150},
            "section_mm_maximum": GRIP_SECTION_MM_MAXIMUM,
        },
    },
    {"look_role": "plant.tree", "slot_mm": {"width": 5000, "height": 8000, "depth": 5000}},
    {"look_role": "vehicle.car", "slot_mm": {"width": 1900, "height": 1600, "depth": 4600}},
    {"look_role": "door.shop_door", "slot_mm": {"width": 1200, "height": 2400, "depth": 300}},
    {
        "look_role": "boundary.picket_fence",
        "slot_mm": {"width": 12000, "height": 1000, "depth": 200},
        "tile_module_mm": 2000,
    },
)


def _box(
    low: tuple[float, float, float], high: tuple[float, float, float]
) -> tuple[np.ndarray, np.ndarray]:
    x0, y0, z0 = low
    x1, y1, z1 = high
    v = np.array(
        [[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], dtype=np.float64
    )
    # Outward winding, counter-clockwise seen from outside.
    f = np.array(
        [
            [0, 1, 3],
            [0, 3, 2],  # -X
            [4, 6, 7],
            [4, 7, 5],  # +X
            [0, 4, 5],
            [0, 5, 1],  # -Y
            [2, 3, 7],
            [2, 7, 6],  # +Y
            [0, 2, 6],
            [0, 6, 4],  # -Z
            [1, 5, 7],
            [1, 7, 3],  # +Z
        ]
    )
    return v, f


def _sphere(
    centre: tuple[float, float, float], radius: float, levels: int
) -> tuple[np.ndarray, np.ndarray]:
    t = (1 + 5**0.5) / 2
    v = [
        [-1, t, 0],
        [1, t, 0],
        [-1, -t, 0],
        [1, -t, 0],
        [0, -1, t],
        [0, 1, t],
        [0, -1, -t],
        [0, 1, -t],
        [t, 0, -1],
        [t, 0, 1],
        [-t, 0, -1],
        [-t, 0, 1],
    ]
    f = [
        [0, 11, 5],
        [0, 5, 1],
        [0, 1, 7],
        [0, 7, 10],
        [0, 10, 11],
        [1, 5, 9],
        [5, 11, 4],
        [11, 10, 2],
        [10, 7, 6],
        [7, 1, 8],
        [3, 9, 4],
        [3, 4, 2],
        [3, 2, 6],
        [3, 6, 8],
        [3, 8, 9],
        [4, 9, 5],
        [2, 4, 11],
        [6, 2, 10],
        [8, 6, 7],
        [9, 8, 1],
    ]
    vertices = [np.array(p, dtype=np.float64) / np.linalg.norm(p) for p in v]

    def midpoint(middle: dict[tuple[int, int], int], a: int, b: int) -> int:
        key = (min(a, b), max(a, b))
        if key not in middle:
            point = vertices[a] + vertices[b]
            vertices.append(point / np.linalg.norm(point))
            middle[key] = len(vertices) - 1
        return middle[key]

    for _ in range(levels):
        middle: dict[tuple[int, int], int] = {}

        def mid(a: int, b: int, middle: dict[tuple[int, int], int] = middle) -> int:
            return midpoint(middle, a, b)

        f = [
            face
            for a, b, c in f
            for face in (
                [a, mid(a, b), mid(c, a)],
                [b, mid(b, c), mid(a, b)],
                [c, mid(c, a), mid(b, c)],
                [mid(a, b), mid(b, c), mid(c, a)],
            )
        ]
    return np.array(vertices) * radius + np.array(centre), np.array(f)


def _join(parts: list[tuple[np.ndarray, np.ndarray, tuple[int, int, int]]]) -> Mesh:
    positions, triangles, colours = [], [], []
    base = 0
    for v, f, colour in parts:
        positions.append(v)
        triangles.append(f + base)
        colours.append(np.tile(np.array([colour], dtype=np.uint8), (len(v), 1)))
        base += len(v)
    return Mesh(np.concatenate(positions), np.concatenate(triangles), np.concatenate(colours))


def stub_mesh(look_role: str) -> Mesh:
    """A fixed shape for the role, +Z up and front -Y, in arbitrary units as a model returns."""
    wood, dark, leaf, red, cream = (
        (166, 112, 70),
        (50, 46, 44),
        (78, 140, 70),
        (205, 80, 60),
        (230, 222, 205),
    )
    if look_role == "prop.bench":
        return _join(
            [
                (*_box((0, 0, 0.45), (1.8, 0.6, 0.55)), wood),
                (*_box((0, 0.5, 0.55), (1.8, 0.6, 0.9)), wood),
                (*_box((0.1, 0.05, 0), (0.2, 0.55, 0.45)), dark),
                (*_box((1.6, 0.05, 0), (1.7, 0.55, 0.45)), dark),
            ]
        )
    if look_role == "prop.lantern":
        # Base, glass, cap, then a ring of two posts and a top bar the hand goes around.
        return _join(
            [
                (*_box((-0.09, -0.09, 0), (0.09, 0.09, 0.03)), dark),
                (*_box((-0.065, -0.065, 0.03), (0.065, 0.065, 0.2)), cream),
                (*_box((-0.08, -0.08, 0.2), (0.08, 0.08, 0.23)), dark),
                (*_box((-0.025, -0.004, 0.23), (-0.02, 0.004, 0.3)), dark),
                (*_box((0.02, -0.004, 0.23), (0.025, 0.004, 0.3)), dark),
                (*_box((-0.025, -0.004, 0.28), (0.025, 0.004, 0.3)), dark),
            ]
        )
    if look_role == "prop.sword":
        return _join(
            [
                (*_box((-0.025, -0.02, 0), (0.025, 0.02, 0.03)), dark),
                (*_box((-0.015, -0.015, 0.03), (0.015, 0.015, 0.2)), wood),
                (*_box((-0.06, -0.015, 0.2), (0.06, 0.015, 0.25)), dark),
                (*_box((-0.02, -0.005, 0.25), (0.02, 0.005, 1.0)), cream),
            ]
        )
    if look_role == "plant.tree":
        return _join(
            [(*_box((-0.3, -0.3, 0), (0.3, 0.3, 3)), wood), (*_sphere((0, 0, 4.5), 2.4, 4), leaf)]
        )
    if look_role == "vehicle.car":
        wheels = [
            (*_box((x, y, 0), (x + 0.3, y + 0.7, 0.7)), dark)
            for x in (-0.15, 1.65)
            for y in (0.5, 3.3)
        ]
        return _join(
            [
                (*_box((0, 0, 0.3), (1.8, 4.5, 1.0)), red),
                (*_box((0.15, 1.2, 1.0), (1.65, 3.4, 1.5)), cream),
                *wheels,
            ]
        )
    if look_role == "door.shop_door":
        return _join(
            [
                (*_box((0, 0, 0), (1.1, 0.25, 2.3)), wood),
                (*_box((0.2, -0.02, 1.2), (0.9, 0.0, 2.1)), (90, 120, 170)),
            ]
        )
    if look_role == "boundary.picket_fence":
        pickets = [
            (*_box((x, 0, 0), (x + 0.08, 0.04, 0.95)), cream) for x in np.arange(0, 2.0, 0.2)
        ]
        rails = [(*_box((0, 0.04, z), (2.0, 0.07, z + 0.08)), cream) for z in (0.2, 0.7)]
        return _join([*pickets, *rails])
    raise ValueError(f"the stub has no shape for {look_role}")


class StubBackend:
    """Route S: fixed pictures and fixed shapes, so every step after the models runs for real."""

    route = "S"

    def simplifier(self) -> Simplifier:
        return cluster_simplify

    def concept(self, prompt: str, seed: int) -> bytes:
        # A flat picture whose colour follows the seed: enough to have a digest, nothing to judge.
        shade = (seed % 200) + 30
        return _png(Image.new("RGB", (64, 64), (shade, shade, 220 - shade // 2)))

    def cutout(self, picture: bytes) -> bytes:
        image = Image.open(io.BytesIO(picture)).convert("RGBA")
        alpha = Image.new("L", image.size, 0)
        alpha.paste(255, (8, 8, image.width - 8, image.height - 8))
        image.putalpha(alpha)
        return _png(image)

    def mesh(self, cutout: bytes, seed: int, request: Mapping[str, Any]) -> RawMesh:
        return RawMesh(stub_mesh(request["look_role"]), up="+Z", front="-Y")

    def runtime(self) -> dict[str, Any]:
        return {"machine": "dry run, no GPU"}


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def dry_run(repository: Path, out: Path) -> dict[str, Any]:
    """Run the stub route end to end and write every record, piece and a contact sheet."""
    out.mkdir(parents=True, exist_ok=True)
    requests = []
    budgets = read_budgets(repository)
    for spec in STUB_REQUESTS:
        raw = build_request(pack=STUB_PACK, variants=1, route="S", budgets=budgets, **spec)
        requests.append(raw)
        (out / f"request-{sha256_hex(raw)}.json").write_bytes(raw)
    components_sha256 = sha256_hex(
        canonical_bytes({"route": "S", "stub": "exulanica_appearance.assets.dryrun"})
    )
    job_raw = build_job(
        route="S",
        components_sha256=components_sha256,
        requests=requests,
        code_sha256=sha256_hex(Path(__file__).read_bytes()),
        container="stub",
        estimate_seconds=1,
        budgets=budgets,
    )
    job_sha256 = sha256_hex(job_raw)
    (out / f"job-{job_sha256}.json").write_bytes(job_raw)
    results = run_job(
        job_raw=job_raw, requests=requests, backend=StubBackend(), repository=repository, out=out
    )
    pieces = [
        dict(
            item,
            cache_key=cache_key(item["request_sha256"], components_sha256, POSTPROCESS_VERSION),
        )
        for item in results["items"]
    ]
    draw_sheet(
        [
            (
                (
                    f"{item['look_role']}\n{item['triangles']} triangles\n"
                    f"{item['size_mm']['width']} x {item['size_mm']['height']} x "
                    f"{item['size_mm']['depth']} mm\nstub shape, not a model's"
                ),
                (out / "pieces" / f"{item['piece']}.glb").read_bytes(),
            )
            for item in pieces
            if "piece" in item
        ],
        out / "sheet.png",
    )
    (out / "summary.json").write_text(json.dumps(pieces, indent=1, sort_keys=True) + "\n")
    return {"job": job_sha256, "pieces": pieces}


def case_bytes(repository: Path, look_role: str = "prop.sword") -> bytes:
    """The case file's bytes: a fresh dry run's records for one piece, as canonical JSON.

    Rewrite :data:`CASE_PATH` with these bytes when a record format changes. The receipt's
    seconds and runtime are this run's; everything else is fixed by the request."""
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory)
        run = dry_run(repository, out)
        piece = next(item for item in run["pieces"] if item["look_role"] == look_role)
        receipt = (out / "receipts" / f"{piece['receipt']}.json").read_bytes()
        request = (out / f"request-{piece['request_sha256']}.json").read_bytes()
        job = (out / f"job-{run['job']}.json").read_bytes()
    document = {
        "about": (
            "One generated piece's records from the dry run (route S, a stub in place of the "
            "models): its request, the job that made it and its receipt. Regenerate with "
            "exulanica_appearance.assets.dryrun.case_bytes when a record format changes."
        ),
        "job": json.loads(job),
        "profile": CASE_PROFILE,
        "receipt": json.loads(receipt),
        "request": json.loads(request),
    }
    return canonical_bytes(document) + b"\n"
