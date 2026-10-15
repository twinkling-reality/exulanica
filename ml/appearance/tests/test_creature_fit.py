"""Route P's fit on a model written here, end to end to a container the product's reader takes.

The model is a creature of ellipsoids and capsules (a round torso, two short legs with feet, two
arms, a head and a tail) whose proportions are not its plan's, coloured in two colours and turned
into the frame a 3D model returns it in (+Z up, front -Y); its cut-out is its own view. The positive
control fits, skins, checks and writes a container read back with the plan's tree; a model with a
leg missing is refused by code with nothing made; one with no arms keeps them still.
"""

from __future__ import annotations

import io
import json

import numpy as np
from exulanica_pieces.canonical import canonical_bytes
from exulanica_pieces.colour import read_table
from exulanica_pieces.geometry.mesh import Mesh, cluster_simplify
from exulanica_pieces.skinned import read_skinned_glb
from PIL import Image

from exulanica_appearance.creatures.fit import fit_look
from exulanica_appearance.creatures.geometry import Camera, rasterise, voxel_surface
from exulanica_appearance.creatures.request import REQUEST_PROFILE, read_request

ELLIPSOIDS = {
    "torso": ((0.0, 0.0, 0.42), (0.20, 0.25, 0.25)),
    "head": ((0.0, 0.04, 0.78), (0.12, 0.12, 0.12)),
}
CAPSULES = {
    "legLeft": ((-0.10, 0.0, 0.25), (-0.10, 0.02, 0.03), 0.035),
    "footLeft": ((-0.10, 0.0, 0.025), (-0.10, 0.14, 0.025), 0.025),
    "legRight": ((0.10, 0.0, 0.25), (0.10, 0.02, 0.03), 0.035),
    "footRight": ((0.10, 0.0, 0.025), (0.10, 0.14, 0.025), 0.025),
    "armLeft": ((-0.15, 0.0, 0.52), (-0.38, 0.0, 0.50), 0.035),
    "armRight": ((0.15, 0.0, 0.52), (0.38, 0.0, 0.50), 0.035),
    "tail": ((0.0, -0.20, 0.40), (0.0, -0.46, 0.45), 0.03),
}
#: Each bone's parent, joint and end (millimetres), as a drafted upright body states them.
BONES = {
    "hips": (None, (0, 0, 420), (0, 0, 520)),
    "spine1": ("hips", (0, 0, 520), (0, 0, 620)),
    "spine2": ("spine1", (0, 0, 620), (0, 0, 720)),
    "head1": ("spine2", (0, 0, 720), (0, 60, 900)),
    "tail1": ("hips", (0, -50, 420), (0, -400, 300)),
    "leg1Left1": ("hips", (-90, 0, 420), (-90, 10, 250)),
    "leg1Left2": ("leg1Left1", (-90, 10, 250), (-100, 0, 80)),
    "leg1Left3": ("leg1Left2", (-100, 0, 80), (-100, 120, 0)),
    "leg1Right1": ("hips", (90, 0, 420), (90, 10, 250)),
    "leg1Right2": ("leg1Right1", (90, 10, 250), (100, 0, 80)),
    "leg1Right3": ("leg1Right2", (100, 0, 80), (100, 120, 0)),
    "arm1Left1": ("spine2", (-130, 0, 660), (-270, 0, 660)),
    "arm1Left2": ("arm1Left1", (-270, 0, 660), (-400, 0, 660)),
    "arm1Right1": ("spine2", (130, 0, 660), (270, 0, 660)),
    "arm1Right2": ("arm1Right1", (270, 0, 660), (400, 0, 660)),
}
CHAINS = [
    {"key": "spine", "role": "spine", "side": "centre", "order": 0, "bones": ["spine1", "spine2"]},
    {"key": "tail", "role": "tail", "side": "centre", "order": 0, "bones": ["tail1"]},
    *(
        {
            "key": f"{limb}1{side}",
            "role": limb,
            "side": side.lower(),
            "order": 0,
            "bones": [f"{limb}1{side}{n}" for n in range(1, count + 1)],
        }
        for limb, count in (("leg", 3), ("arm", 2))
        for side in ("Left", "Right")
    ),
]
BODY, HEAD = (224, 120, 40), (240, 210, 70)


def _request() -> bytes:
    return json.dumps(
        {
            "profile": REQUEST_PROFILE,
            "plan": {
                "key": "two_legged_test_body",
                "version": 1,
                "sha256": "0" * 64,
                "bones": [{"name": bone, "parent": spec[0]} for bone, spec in BONES.items()],
                "limbs": CHAINS,
            },
            "rest": {
                bone: {"joint_mm": list(spec[1]), "end_mm": list(spec[2]), "radius_mm": 40}
                for bone, spec in BONES.items()
            },
            "sketch": {"sha256": "1" * 64, "bytes": 1},
            "appearance": "a round orange body with a yellow head",
            "colours": {
                role: {"word": word, "srgb": list(srgb)}
                for role, word, srgb in (
                    ("body", "orange", BODY),
                    ("belly", "orange", BODY),
                    ("accent", "yellow", HEAD),
                    ("eyes", "yellow", HEAD),
                )
            },
        }
    ).encode()


def _model(capsules=CAPSULES) -> tuple[Mesh, bytes]:
    """The model in a 3D model's frame (+Z up, front -Y), two colours, and its cut-out."""
    voxel = 0.01
    origin = np.array([-0.5, -0.6, -0.05])
    shape = (100, 110, 100)
    centres = origin + (np.indices(shape).reshape(3, -1).T + 0.5) * voxel
    filled = np.zeros(len(centres), dtype=bool)
    for centre, radii in ELLIPSOIDS.values():
        filled |= (((centres - centre) / radii) ** 2).sum(axis=1) <= 1.0
    for start, end, radius in capsules.values():
        start, end = np.asarray(start), np.asarray(end)
        t = np.clip((centres - start) @ (end - start) / ((end - start) @ (end - start)), 0.0, 1.0)
        filled |= np.linalg.norm(centres - (start + t[:, None] * (end - start)), axis=1) <= radius
    positions, triangles = voxel_surface(filled.reshape(shape), origin, voxel)
    colours = np.where((positions[:, 2] > 0.66)[:, None], HEAD, BODY).astype(np.uint8)
    drawn = rasterise(positions[triangles], Camera(145.0, 15.0), 256, margin=0.1)
    face = np.rint(colours[triangles].mean(axis=1)).astype(np.uint8)
    rgba = np.zeros((256, 256, 4), dtype=np.uint8)
    rgba[drawn.mask, :3] = face[drawn.triangle[drawn.mask]]
    rgba[drawn.mask, 3] = 255
    buffer = io.BytesIO()
    Image.fromarray(rgba).save(buffer, format="PNG")
    frame = np.stack([-positions[:, 0], -positions[:, 1], positions[:, 2]], axis=1)
    return Mesh(frame, triangles, colours), buffer.getvalue()


def _fit(repository, capsules=CAPSULES):
    model, cutout = _model(capsules)
    table, _ = read_table(repository)
    return fit_look(
        read_request(_request()),
        model,
        up="+Z",
        front="-Y",
        cutout_png=cutout,
        simplifier=cluster_simplify,
        table=table,
    )


def test_a_model_from_a_picture_becomes_a_skinned_look_the_product_reads(repository):
    fitted = _fit(repository)
    receipt = fitted.receipt
    assert receipt["outcome"] == "passed", receipt.get("refusal")
    assert receipt["route"] == "P" and receipt["embed"]["still"] == []
    assert receipt["embed"]["unmatched"] == []
    read = read_skinned_glb(
        fitted.container,
        bones={bone: f"bone:{bone}" for bone in BONES},
        plan_parents={bone: spec[0] for bone, spec in BONES.items()},
    )
    assert len(read.joints) == len(BONES)
    assert receipt["output"]["triangles"] == read.triangles <= 20_000
    # Stood at the plan's height (to its rest skeleton's top).
    assert abs(receipt["output"]["height_mm"] - 900) <= 20
    # Its likeness to its own view is measured, and high.
    assert receipt["likeness"]["outline_overlap_per_mille"] >= 800
    # The receipt is a record: canonical, every number a whole one in a stated unit.
    assert json.loads(canonical_bytes(receipt)) == receipt


def test_a_model_with_a_leg_missing_is_refused_with_nothing_made(repository):
    lacking = {
        key: shape for key, shape in CAPSULES.items() if key not in ("legRight", "footRight")
    }
    fitted = _fit(repository, lacking)
    assert fitted.container is None
    assert fitted.receipt["outcome"] == "refused"
    assert fitted.receipt["refusal"]["code"] == "rig_chain_not_found"
    assert fitted.receipt["embed"]["missing"] == ["leg1Right"]
    assert json.loads(canonical_bytes(fitted.receipt)) == fitted.receipt


def test_arms_the_model_lacks_are_kept_still_and_hold_no_vertex(repository):
    armless = {key: shape for key, shape in CAPSULES.items() if not key.startswith("arm")}
    fitted = _fit(repository, armless)
    assert fitted.receipt["outcome"] == "passed", fitted.receipt.get("refusal")
    still = fitted.receipt["embed"]["still"]
    assert still == ["arm1Left1", "arm1Left2", "arm1Right1", "arm1Right2"]
    moved = fitted.receipt["rig"]["moved_vertices"]
    assert set(moved).isdisjoint(still) and all(moved[bone] > 0 for bone in ("leg1Left3", "head1"))


def test_triangles_turned_over_are_turned_back_to_face_out():
    from exulanica_appearance.creatures.embed import _relax, solid_inside
    from exulanica_appearance.creatures.fit import _outward
    from exulanica_appearance.creatures.rig import Inside

    model, _cutout = _model()
    positions, triangles = model.positions, model.triangles
    voxel = 0.02
    grid, origin = solid_inside(positions[triangles], voxel)
    depth = _relax(np.where(grid, np.inf, 0.0), np.ones_like(grid)) / 3.0 * voxel
    inside = Inside(grid, origin, voxel, depth)
    _same, untouched = _outward(positions, triangles, inside)
    # Every other triangle turned over, as a simplifier can leave them.
    mixed = triangles.copy()
    mixed[::2] = mixed[::2, ::-1]
    fixed, turned = _outward(positions, mixed, inside)
    assert untouched <= len(triangles) // 100
    # Most come back; a few in limbs a couple of voxels thick read alike on both sides and stay.
    assert turned >= 0.9 * (len(triangles) // 2)
    assert (np.sort(fixed, axis=1) == np.sort(triangles, axis=1)).all()
    agree = (fixed == triangles).all(axis=1) | (fixed == np.roll(triangles, 1, axis=1)).all(axis=1)
    agree |= (fixed == np.roll(triangles, 2, axis=1)).all(axis=1)
    assert agree.mean() >= 0.95
