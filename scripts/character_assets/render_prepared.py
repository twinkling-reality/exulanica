"""Blender QA from exported GLB bytes only, never a source .blend or unapplied modifier."""

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def render(asset, output, view, action_name="Idle", seconds=0):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(asset))
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for track in list(rig.animation_data.nla_tracks):
        rig.animation_data.nla_tracks.remove(track)
    action = bpy.data.actions[action_name]
    rig.animation_data.action = action
    rig.animation_data.action_slot = action.slots[0]
    scene = bpy.context.scene
    frame = seconds * scene.render.fps / scene.render.fps_base
    scene.frame_set(int(frame), subframe=frame - int(frame))
    geometry = {}
    graph = bpy.context.evaluated_depsgraph_get()
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        points = [evaluated.matrix_world @ v.co for v in mesh.vertices]
        geometry[obj.name] = {
            "x_extent_metres": [min(p.x for p in points), max(p.x for p in points)],
            "negative_vertices": sum(p.x < -0.02 for p in points),
            "positive_vertices": sum(p.x > 0.02 for p in points),
        }
        evaluated.to_mesh_clear()
    camera_location = (0, -5, 1.0) if view == "front" else (0, 5, 1.0)
    bpy.ops.object.camera_add(location=camera_location)
    camera = bpy.context.object
    camera.rotation_euler = (
        (Vector((0, 0, 0.95)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 2.15
    scene.camera = camera
    for location, energy in (((3, -4, 5), 500), ((-3, 4, 4), 400), ((-3, -2, 3), 200)):
        bpy.ops.object.light_add(type="AREA", location=location)
        bpy.context.object.data.energy = energy
        bpy.context.object.data.size = 5
    scene.world = bpy.data.worlds.new("Exported asset QA")
    scene.world.color = (0.15, 0.15, 0.15)
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.render.resolution_x = 512
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    return {
        "asset": asset.name,
        "view": view,
        "action": action_name,
        "seconds": seconds,
        "source": "fresh GLB import with one active original action",
        "geometry": geometry,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for asset in sorted(args.assets_dir.glob("*.glb")):
        for view in ("front", "back"):
            results.append(
                render(asset, args.output_dir / (asset.stem + "-" + view + ".png"), view)
            )
    for action, seconds in (("Walk", 0.4), ("Run", 0.25), ("Interact", 19 / 30), ("Wave", 20 / 30)):
        results.append(
            render(
                args.assets_dir / "hoodie.glb",
                args.output_dir / ("hoodie-" + action + ".png"),
                "front",
                action,
                seconds,
            )
        )
    (args.output_dir / "decoded-pose-audit.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
