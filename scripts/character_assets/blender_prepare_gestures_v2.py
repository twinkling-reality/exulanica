"""Add original source gesture semantics to the corrected complete character export."""

import json
import runpy
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]


def prepare(config):
    # The complete-body exporter samples every selected original action.
    runpy.run_path(str(ROOT / "scripts/character_assets/blender_prepare_v2.py"))["prepare"](config)
    path = Path(config["metadata"])
    metadata = json.loads(path.read_text())
    for semantic in ("interact", "wave"):
        clip = metadata["clips"][semantic]
        for field in ("nominal_speed_mps", "speed_method", "speed_sample_count"):
            clip.pop(field)
        clip.update(
            playback="one-shot",
            source_action=True,
            semantic="right-hand reach" if semantic == "interact" else "left-hand wave",
            active_hand="right" if semantic == "interact" else "left",
        )
    rig = bpy.data.objects["CharacterArmature"]
    rig.animation_data.action = bpy.data.actions["Idle"]
    bpy.context.scene.frame_set(0)
    head = bpy.data.objects[config["look"]["mesh_nodes"]["head_hair"]]
    evaluated = head.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    material_indices = {i for i, slot in enumerate(head.material_slots) if slot.name == "Eye"}
    vertex_indices = {
        i for p in mesh.polygons if p.material_index in material_indices for i in p.vertices
    }
    eye = (
        (
            sum((evaluated.matrix_world @ mesh.vertices[i].co for i in vertex_indices), Vector())
            / len(vertex_indices)
        )
        if vertex_indices
        else None
    )
    evaluated.to_mesh_clear()
    metadata["first_person_reference"] = {
        "eye_center_model_metres": None if eye is None else [eye.x, eye.z, -eye.y],
        "eye_reference_status": "unavailable, eye surface lacks a distinct source material"
        if eye is None
        else "artist eye-material geometry",
        "method": "Mean unique vertices assigned original Eye material, evaluated at Idle frame zero; glTF frame",
        "not_a_camera_override": True,
        "notes": [
            "Interact reaches the right hand forward; it is not a palm-up summon.",
            "Wave raises the left hand beside the head and may fall outside a forward-looking first-person camera.",
            "Both clips animate the whole body. No upper-body mask, IK retargeting or first-person-specific motion was invented.",
            "Camera placement, head visibility, near-plane clipping and input interruption need runtime framing review.",
            "Return to locomotion after the one-shot. Do not loop Interact to imply a held hand pose.",
        ],
    }
    path.write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    prepare(json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text()))
