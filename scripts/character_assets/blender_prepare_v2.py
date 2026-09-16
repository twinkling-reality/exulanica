"""Realize artist Mirror modifiers and skin groups before exporting complete character geometry."""

import json
from itertools import pairwise
import statistics
import sys
from pathlib import Path

import bpy


def bounds(objects):
    graph = bpy.context.evaluated_depsgraph_get()
    points = []
    for obj in objects:
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        points.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
        evaluated.to_mesh_clear()
    return [
        [min(p[i] for p in points) for i in range(3)],
        [max(p[i] for p in points) for i in range(3)],
    ]


def prepare(config):
    if ".".join(map(str, bpy.app.version)) != config["blender_version"]:
        raise ValueError("Pinned Blender version required")
    bpy.ops.wm.open_mainfile(filepath=config["source"], load_ui=False, use_scripts=False)
    look = config["look"]
    rig = bpy.data.objects["CharacterArmature"]
    names = set(look["mesh_nodes"].values()) | {rig.name}
    for obj in list(bpy.data.objects):
        if obj.name not in names:
            bpy.data.objects.remove(obj, do_unlink=True)
    meshes = [bpy.data.objects[name] for name in look["mesh_nodes"].values()]
    rig.animation_data.action = None
    for track in list(rig.animation_data.nla_tracks):
        rig.animation_data.nla_tracks.remove(track)
    for action in list(bpy.data.actions):
        if action.name not in look["actions"].values():
            bpy.data.actions.remove(action)
    bpy.context.scene.frame_set(0)
    rig.data.pose_position = "REST"
    changes = []
    for obj in bpy.data.objects:
        obj.hide_set(False)
        obj.hide_render = False
        obj.hide_viewport = False
        obj.select_set(True)
    for obj in meshes:
        bpy.context.view_layer.objects.active = obj
        repaired = obj.data.validate(verbose=False, clean_customdata=True)
        if repaired:
            changes.append({"node": obj.name, "operation": "Blender Mesh.validate repair"})
        # Artist source stores only one half for these meshes. glTF has no Mirror modifier.
        # Realize it while the armature is in REST, retaining Blender's .L/.R group remapping.
        for modifier in list(obj.modifiers):
            if modifier.type == "MIRROR":
                if not modifier.use_mirror_vertex_groups:
                    raise ValueError("Source mirror must remap left/right skin groups")
                before_vertices = len(obj.data.vertices)
                bpy.ops.object.modifier_apply(modifier=modifier.name)
                changes.append(
                    {
                        "node": obj.name,
                        "operation": "realize source Mirror with mirrored vertex groups",
                        "vertices_before": before_vertices,
                        "vertices_after": len(obj.data.vertices),
                    }
                )
        if any(m.type == "MIRROR" for m in obj.modifiers):
            raise ValueError("Unrealized source mirror")
        if look["smooth_shading"]:
            for polygon in obj.data.polygons:
                polygon.use_smooth = True
        levels = look["subdivision_levels"]
        if levels:
            modifier = obj.modifiers.new("Prepared smooth topology", "SUBSURF")
            modifier.levels = levels
            modifier.render_levels = levels
            obj.modifiers.move(len(obj.modifiers) - 1, 0)
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        obj.data.update()
    rig.data.pose_position = "POSE"
    bpy.context.view_layer.objects.active = rig
    idle = bpy.data.actions[look["actions"]["idle"]]
    rig.animation_data.action = idle
    bpy.context.scene.frame_set(0)
    # Use a shared shoe-derived source-family origin so outfits retain identical bind matrices.
    idle_bounds = bounds(meshes)
    rig.location.z += config["origin_translation_z_metres"]
    bpy.context.view_layer.update()
    idle_bounds = bounds(meshes)
    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    clips = {}
    for semantic, action_name in look["actions"].items():
        action = bpy.data.actions[action_name]
        rig.animation_data.action = action
        start, end = map(int, action.frame_range)
        feet = {name: [] for name in ("Foot.L", "Foot.R")}
        roots = []
        for frame in range(start, end + 1):
            bpy.context.scene.frame_set(frame)
            roots.append(tuple(rig.matrix_world @ rig.pose.bones["Root"].head))
            for name in feet:
                feet[name].append(tuple(rig.matrix_world @ rig.pose.bones[name].head))
        velocities = []
        for samples in feet.values():
            floor = min(p[2] for p in samples)
            for a, b in pairwise(samples):
                # Facing -Y in Blender; planted feet move +Y in an in-place cycle.
                speed = (b[1] - a[1]) * fps
                if max(a[2], b[2]) <= floor + 0.04 and speed > 0:
                    velocities.append(speed)
        root_delta = [max(p[i] for p in roots) - min(p[i] for p in roots) for i in range(3)]
        if max(root_delta[:2]) > 1e-5:
            raise ValueError("Source locomotion has unhandled horizontal root motion")
        clips[semantic] = {
            "name": action_name,
            "duration_seconds": (end - start) / fps,
            "in_place": True,
            "root_node": "Root",
            "root_horizontal_span_metres": root_delta[:2],
            "nominal_speed_mps": round(statistics.median(velocities), 5)
            if semantic != "idle" and velocities
            else 0,
            "speed_method": "Median backward planted-foot velocity at source 30fps, foot within 4cm of minimum; estimate requires runtime contact review",
            "speed_sample_count": len(velocities),
        }
    rig.animation_data.action = None
    bpy.context.scene.frame_set(0)
    bpy.ops.export_scene.gltf(
        filepath=config["output"],
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_animation_mode="ACTIONS",
        export_force_sampling=True,
        export_skins=True,
        export_yup=True,
        export_materials="EXPORT",
    )
    metadata = {
        "look_id": look["look_id"],
        "source_id": look["source_id"],
        "preparation": {
            "smooth_shading": look["smooth_shading"],
            "subdivision_levels": look["subdivision_levels"],
            "repairs": changes,
            "skin_weights": "Blender glTF export keeps and normalizes the strongest four weights",
        },
        "frame": {
            "unit": "metre",
            "up": "+Y",
            "forward": "+Z",
            "forward_yaw_radians": 0,
            "unit_scale": 1,
            "origin": "shared source-family ground, calibrated from the reference look at Idle frame zero",
            "idle_floor_offset_metres": idle_bounds[0][2],
            "height_metres": idle_bounds[1][2] - idle_bounds[0][2],
        },
        "clips": clips,
        "slots": look["mesh_nodes"],
        "morphs": [],
        "compatibility": {
            "body_family": look["source_id"],
            "within_source_parts": True,
            "cross_body_part_fitting": False,
        },
        "limitations": [
            "Stylized integration exemplar, visual acceptance pending",
            "No facial expression or body-shape morphs; uniform height scaling only",
            "Hair is joined with its head component",
            "No trained/generated character model",
            "No independently validated lower-detail LOD",
            "Native source loop seam and foot contact require runtime review",
        ],
    }
    Path(config["metadata"]).write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    prepare(json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text()))
