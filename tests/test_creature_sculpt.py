"""A creature's sculpted look end to end with no model: its sketch, filled into a closed surface
that stands in for a sculpted mesh, rigged with the plan's own skeleton, written as a skinned
container and read back by the product's reader against the plan's own tree.

The rig and the writer live outside the product (``ml/appearance`` and the numpy half of the piece
formats); the reader is the product's. The creatures are the development set of
``tests/fixtures/creatures/creatures.v1.json``: the held-out set is kept for the rig trial.
"""

from __future__ import annotations

import pytest

#: The rig and the writer compute with numpy, which arrives with the `reconstruction` extra; a plain
#: `uv sync`, as CI runs, does not install it.
pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)

import copy
from pathlib import Path

import exulanica
import numpy as np
from exulanica.things.bodies import build_body, read_body_recipe
from exulanica.things.sketch import sketch_look
from exulanica_pieces.colour import read_table
from exulanica_pieces.skinned import LIMITS, read_skinned_glb

from creature_support import FIXTURES

ROOT = Path(exulanica.__file__).resolve().parents[1]
AUTHORED = {
    "profile": "exulanica.origin/v1",
    "class": "authored",
    "by": {"kind": "project"},
    "sources": [],
    "licence": {
        "spdx": "CC0-1.0",
        "verdict": "SHIP",
        "attribution": None,
        "share_alike": False,
        "licence_url": None,
        "licence_text_sha256": None,
    },
    "authors": [],
    "lineage": {"ingredients": [], "receipts": [], "translation_manifest_sha256": None},
    "distribution": "private",
}


@pytest.fixture
def sculpt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(ROOT / "ml" / "appearance"))
    from exulanica_appearance.creatures import geometry, rig
    from exulanica_pieces.geometry.skinned import write_skinned_glb

    return geometry, rig, write_skinned_glb


@pytest.mark.parametrize("name", sorted(FIXTURES["development"]))
def test_a_sketch_filled_and_rigged_is_a_skinned_look_the_product_reads(name, sculpt):
    geometry, rig, write_skinned_glb = sculpt
    recipe = read_body_recipe(copy.deepcopy(FIXTURES["development"][name]["recipe"]))
    built = build_body(recipe, key=name, version=1, title=name, origin=AUTHORED)
    _document, container = sketch_look(
        built, recipe, look=f"{name}-sketch", version=1, plan_name=f"{name}/v1", origin=AUTHORED
    )
    triangles, _bones_of = geometry.sketch_triangles(container)
    corners = triangles.reshape(-1, 3)
    longest = float((corners.max(axis=0) - corners.min(axis=0)).max())
    grid, origin = geometry.voxel_inside(triangles, longest / 64)
    positions, faces = geometry.voxel_surface(grid, origin, longest / 64)
    inside = rig.inside_of(positions, faces, longest / 96)
    bones = [bone["name"] for bone in built.plan["bones"]]
    parents = {bone["name"]: bone["parent"] for bone in built.plan["bones"]}
    joints = {bone: np.asarray(built.joints[bone], dtype=np.float64) / 1000 for bone in bones}
    ends = {bone: np.asarray(built.ends[bone], dtype=np.float64) / 1000 for bone in bones}
    radii = {bone: built.radii[bone][0] / 1000 for bone in bones}
    chains = built.plan["limbs"]
    fitted, fitted_ends = rig.fit_joints(joints, ends, chains, radii, inside)
    indices, weights = rig.bone_heat(positions, faces, bones, fitted, fitted_ends, inside)
    rig.check_rig(
        positions=positions,
        indices=indices,
        weights=weights,
        bones=bones,
        parents=parents,
        plan_joints=joints,
        joints=fitted,
        ends=fitted_ends,
        chains=chains,
        inside=inside,
        size=max(recipe.extent.values()) / 1000,
    )
    table, _table_sha256 = read_table(ROOT)
    data = write_skinned_glb(
        positions_m=positions,
        triangles=faces,
        triangle_colours_srgb8=np.full((len(faces), 3), 128, dtype=np.uint8),
        joint_indices=indices,
        joint_weights=weights,
        bones=bones,
        parents=parents,
        rest_m=fitted,
        table=table,
    )
    read = read_skinned_glb(
        data, bones={bone: f"bone:{bone}" for bone in bones}, plan_parents=parents
    )
    assert read.joints == tuple(f"bone:{bone}" for bone in bones)
    assert read.triangles == len(faces) <= LIMITS.triangles
    # The container's frame is glTF's: (x, y, z) across, forward and up are (-X, Z, Y).
    for bone in bones:
        x, y, z = (float(value) for value in fitted[bone])
        assert read.rest_m[f"bone:{bone}"] == pytest.approx((-x, z, y), abs=1e-6)


def _requested(name: str, *, sketch_of: str | None = None) -> tuple[bytes, bytes]:
    """A creature's look request and the sketch container it names: by default its own sketch,
    or another creature's, so its body is not its plan's."""
    from exulanica.things.catalogs import read_body_plan
    from exulanica.things.creature_looks import creature_look_request

    recipe = read_body_recipe(copy.deepcopy(FIXTURES["development"][name]["recipe"]))
    built = build_body(recipe, key=name, version=1, title=name, origin=AUTHORED)
    plan = read_body_plan(dict(built.plan))
    drawn = sketch_of or name
    drawn_recipe = read_body_recipe(copy.deepcopy(FIXTURES["development"][drawn]["recipe"]))
    drawn_built = build_body(drawn_recipe, key=drawn, version=1, title=drawn, origin=AUTHORED)
    _document, container = sketch_look(
        drawn_built,
        drawn_recipe,
        look=f"{drawn}-sketch",
        version=1,
        plan_name=f"{drawn}/v1",
        origin=AUTHORED,
    )
    return creature_look_request(
        built=built, recipe=recipe, plan_sha256=plan.sha256, sketch=container
    ), container


def test_the_creature_job_with_stand_in_models_writes_looks_the_product_reads(sculpt, tmp_path):
    import hashlib
    import json

    from exulanica_appearance.creatures.job import JOB_PROFILE, run_creature_job
    from exulanica_appearance.creatures.standin import StandInBackend
    from exulanica_pieces.canonical import canonical_bytes

    asked = [("horse", None), ("bat", None), ("horse", "bat")]
    requests, sketches, items = [], {}, []
    for index, (name, sketch_of) in enumerate(asked):
        raw, container = _requested(name, sketch_of=sketch_of)
        requests.append(raw)
        sketches[hashlib.sha256(container).hexdigest()] = container
        items.append(
            {"request_sha256": hashlib.sha256(raw).hexdigest(), "seed": 37 + index, "variant": 0}
        )
    job = canonical_bytes(
        {
            "profile": JOB_PROFILE,
            "route": "C",
            "code_sha256": "0" * 64,
            "components_sha256": "0" * 64,
            "container": "sha256:" + "0" * 64,
            "settings": {"concept": {}, "triangles": 20000, "rig_voxels": 96},
            "items": items,
            "stop": {"estimate_seconds": 600, "stop_at_seconds": 900},
        }
    )
    results = run_creature_job(
        job_raw=job,
        requests=requests,
        sketches=sketches,
        backend=StandInBackend(),
        repository=ROOT,
        out=tmp_path,
    )
    outcomes = [(item["outcome"], item.get("refusal")) for item in results["items"]]
    # A body that is not its plan's (the bat drawn for the horse's plan) is refused by the rig.
    assert outcomes[:2] == [("passed", None), ("passed", None)]
    assert outcomes[2][0] == "refused" and outcomes[2][1].startswith("rig_"), outcomes[2]
    # The refused item's receipt keeps what registration and the rig's checks measured, every
    # bone of its plan, and the measure its refusal names is the one recorded.
    refused = json.loads(
        (tmp_path / "receipts" / f"{results['items'][2]['receipt']}.json").read_bytes()
    )
    horse = json.loads(requests[2])["plan"]
    assert {"yaw_degrees", "scale_per_mille", "scores_per_mille"} <= set(refused["registration"])
    assert set(refused["rig"]["joint_moved_mm"]) == {bone["name"] for bone in horse["bones"]}
    assert set(refused["rig"]["leaked_per_mille"]) <= {limb["key"] for limb in horse["limbs"]}
    if refused["refusal"]["code"] == "rig_joint_far_from_plan":
        bone, millimetres = refused["refusal"]["detail"].split()[1:4:2]
        assert refused["rig"]["joint_moved_mm"][bone] == int(millimetres)
    for item, raw in zip(results["items"][:2], requests[:2], strict=True):
        plan = json.loads(raw)["plan"]
        parents = {bone["name"]: bone["parent"] for bone in plan["bones"]}
        look = (tmp_path / "looks" / f"{item['look']}.glb").read_bytes()
        read_skinned_glb(
            look, bones={bone: f"bone:{bone}" for bone in parents}, plan_parents=parents
        )
        receipt = json.loads((tmp_path / "receipts" / f"{item['receipt']}.json").read_bytes())
        assert receipt["outcome"] == "passed" and receipt["output"]["sha256"] == item["look"]
    # Every item, refused or not, has its row of the contact sheet.
    assert len(results["rows"]) == 3


@pytest.mark.parametrize("name", sorted(FIXTURES["development"]))
def test_the_control_camera_sees_each_development_creature_from_its_front(name, sculpt):
    # The concept's words ask for the front left: the camera must draw the plan's head nearer
    # than its tail, or the picture model paints a face on the plan's back.
    geometry, _rig, _write = sculpt
    recipe = read_body_recipe(copy.deepcopy(FIXTURES["development"][name]["recipe"]))
    built = build_body(recipe, key=name, version=1, title=name, origin=AUTHORED)
    _document, container = sketch_look(
        built, recipe, look=f"{name}-sketch", version=1, plan_name=f"{name}/v1", origin=AUTHORED
    )
    triangles, bones_of = geometry.sketch_triangles(container)
    bones = np.asarray(bones_of)
    centres = triangles.mean(axis=1)
    toward = geometry.project(centres, geometry.CONTROL_CAMERA)[:, 2]
    head = np.char.startswith(bones, "head")
    tail = np.char.startswith(bones, "tail")
    assert head.any(), name
    if tail.any():
        assert toward[head].mean() > toward[tail].mean(), name
    # Every body faces +y: its head lies ahead of the middle of its sketch.
    assert centres[head, 1].mean() > (centres[:, 1].max() + centres[:, 1].min()) / 2, name
