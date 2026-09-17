"""Transfer Quaternius locomotion onto a fitted MakeHuman skeleton. Runs inside pinned Blender.

The transfer maps each source bone's world-space rotation onto the fitted rig through both
families' authored calibration poses, keeping the fitted limb lengths. The hip translation is
kept vertical only and rescaled by hip height, so a clip can never move the subject.
"""

import json
import statistics
from itertools import pairwise
from pathlib import Path

import bpy
from mathutils import Vector

SOURCE_BONES = {
    "Hips": "Hips",
    "Spine": "Abdomen",
    "Spine1": "Torso",
    "Spine2": "Chest",
    "Neck": "Neck",
    "Head": "Head",
}
SIDE_BONES = [
    ("Shoulder", "Shoulder"),
    ("Arm", "UpperArm"),
    ("ForeArm", "LowerArm"),
    ("Hand", "Wrist"),
    ("UpLeg", "UpperLeg"),
    ("Leg", "LowerLeg"),
    ("Foot", "Foot"),
    ("ToeBase", "PT"),
]
FINGERS = ["Index", "Middle", "Ring", "Pinky", "Thumb"]
FPS = 24


def bone_mapping(rig):
    mapping = dict(SOURCE_BONES)
    for side, suffix in [("Left", "L"), ("Right", "R")]:
        for dst, src in SIDE_BONES:
            mapping[side + dst] = src + "." + suffix
        for finger in FINGERS:
            for index in range(1, 4):
                mapping[f"{side}Hand{finger}{index}"] = f"{finger}{index}.{suffix}"
    return {"mixamorig:" + k: v for k, v in mapping.items() if "mixamorig:" + k in rig.pose.bones}


def transfer_motion(rig, animation_path, mpfb_root, clips):
    """Bake each named source clip onto the rig as an NLA track; return per-clip calibration.

    ``clips`` maps a source action name to the exported clip name.
    """
    scene = bpy.context.scene
    scene.render.fps = FPS
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(animation_path))
    imported = set(bpy.data.objects) - before
    source = next(o for o in imported if o.type == "ARMATURE")
    source_actions = {a.name: a for a in bpy.data.actions}
    mapping = bone_mapping(rig)
    rig.animation_data_create()
    for track in list(source.animation_data.nla_tracks):
        source.animation_data.nla_tracks.remove(track)
    source_rest = {b.name: source.matrix_world @ b.matrix_local for b in source.data.bones}
    target_rest = {b.name: rig.matrix_world @ b.matrix_local for b in rig.data.bones}
    # Calibrate through the fitted family's authored T-pose. Matching arbitrary bone axes
    # independently changes clavicle and foot orientation and is not retargeting.
    tpose = json.loads(
        (Path(mpfb_root) / "src/mpfb/data/poses/mixamo_unity_fk/t-pose.json").read_text()
    )
    for name, rotation in tpose["bone_rotations"].items():
        rig.pose.bones[name].rotation_mode = "XYZ"
        rig.pose.bones[name].rotation_euler = rotation
    bpy.context.view_layer.update()
    corrections = {
        dst: source_rest[src].to_quaternion().inverted()
        @ (rig.matrix_world @ rig.pose.bones[dst].matrix).to_quaternion()
        for dst, src in mapping.items()
    }
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion.identity()
        bone.location = (0, 0, 0)
    bpy.context.view_layer.update()
    calibration = {}
    for source_name, clip_name in clips.items():
        # The importer may suffix an action with its object name; a clip must resolve once.
        candidates = [
            a for n, a in source_actions.items() if n == source_name or n.startswith(source_name + "_")
        ]
        exact = [a for a in candidates if a.name == source_name]
        if len(exact or candidates) != 1:
            raise ValueError(f"Source clip {source_name} is missing or ambiguous")
        source_action = (exact or candidates)[0]
        source.animation_data.action = source_action
        if source_action.slots:
            source.animation_data.action_slot = source_action.slots[0]
        start, end = map(int, source_action.frame_range)
        action = bpy.data.actions.new(clip_name)
        rig.animation_data.action = action
        feet = {side: [] for side in ["Left", "Right"]}
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            for bone in rig.pose.bones:
                if bone.name not in mapping:
                    continue
                source_bone = mapping[bone.name]
                source_pose = source.matrix_world @ source.pose.bones[source_bone].matrix
                desired = (
                    rig.matrix_world.to_quaternion().inverted()
                    @ source_pose.to_quaternion()
                    @ corrections[bone.name]
                )
                inherited = bone.bone.matrix_local.to_quaternion()
                if bone.parent:
                    inherited = (
                        bone.parent.matrix.to_quaternion()
                        @ bone.parent.bone.matrix_local.to_quaternion().inverted()
                        @ inherited
                    )
                bone.rotation_mode = "QUATERNION"
                bone.rotation_quaternion = inherited.inverted() @ desired
                if bone.name == "mixamorig:Hips":
                    ratio = (
                        target_rest[bone.name].translation.z
                        / source_rest[source_bone].translation.z
                    )
                    bob = (
                        source_pose.translation.z - source_rest[source_bone].translation.z
                    ) * ratio
                    bone.location = bone.bone.matrix_local.to_quaternion().inverted() @ Vector(
                        (0, 0, bob)
                    )
                    bone.keyframe_insert("location", frame=frame - start)
                bone.keyframe_insert("rotation_quaternion", frame=frame - start)
                bpy.context.view_layer.update()
            for side in feet:
                feet[side].append(
                    (
                        rig.matrix_world @ rig.pose.bones["mixamorig:" + side + "Foot"].matrix
                    ).translation.copy()
                )
        track = rig.animation_data.nla_tracks.new()
        track.name = clip_name
        track.strips.new(action.name, 0, action)
        track.mute = True
        samples = []
        for path in feet.values():
            floor = min(p.z for p in path)
            samples.extend(
                (b.y - a.y) * FPS
                for a, b in pairwise(path)
                if max(a.z, b.z) < floor + 0.04 and b.y > a.y + 0.0001
            )
        calibration[clip_name] = {
            "sourceAction": source_name,
            "durationSeconds": (end - start) / FPS,
            "frames": end - start + 1,
            "stanceSpeedSamples": len(samples),
            "stanceSpeed": statistics.median(samples) if samples else 0.0,
            "feet": {side: [[p.x, p.y, p.z] for p in path] for side, path in feet.items()},
        }
    rig.animation_data.action = None
    for track in rig.animation_data.nla_tracks:
        track.mute = False
    for obj in imported:
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in source_actions.values():
        bpy.data.actions.remove(action)
    return calibration
