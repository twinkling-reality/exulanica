"""Fit a catalog-declared MakeHuman recipe, then export an independently rigged GLB.

Run in the pinned Blender/MPFB preparation environment, never in the web runtime.
The supplied source programs are kept outside the distributable application.
"""
import json
import statistics
import sys
from itertools import pairwise
from pathlib import Path

import bpy
from mathutils import Vector


def build(config):
    data = Path(config['cache']) / 'data'
    data.mkdir(parents=True, exist_ok=True)
    for folder in Path(config['assets']).iterdir():
        if folder.is_dir():
            link = data / folder.name
            if link.exists() or link.is_symlink():
                if not link.is_symlink() or link.resolve() != folder.resolve():
                    raise ValueError('MPFB asset cache does not point to the verified source: ' + folder.name)
            else:
                link.symlink_to(folder, target_is_directory=True)
    sys.path.insert(0, str(Path(config['mpfb']) / 'src'))
    import addon_utils
    # Headless preparation uses its own cache, not a user's installed extension/preferences.
    bpy.utils.extension_path_user = lambda *a, **kw: config['cache']
    addon_utils.enable('mpfb', default_set=True)
    from mpfb.services.humanservice import HumanService
    from mpfb.services.targetservice import TargetService

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    recipe, family = config['recipe'], config['family']
    macro = TargetService.get_default_macro_info_dict()
    macro['age'] = .4  # This initial family is an adult representation.
    for control in family['controls']:
        if 'macro' in control:
            macro[control['macro']] = recipe[control['key']]
    body = HumanService.create_human(macro_detail_dict=macro)
    body.name = 'Body'
    for control in family['controls']:
        amount = recipe[control['key']]
        for target in control.get('targets', []):
            if amount:
                path = Path(config['mpfb']) / 'src/mpfb/data/targets' / (target + ('-incr' if amount > 0 else '-decr') + '.target.gz')
                TargetService.load_target(body, str(path), weight=abs(amount))
    # A completely relaxed MakeHuman mouth reads as a slight frown once the face is
    # reduced to a game-ready mesh. Lift the corners just enough to retain a neutral
    # expression without baking a smile into every generated character.
    TargetService.load_target(
        body,
        str(Path(config['mpfb']) / 'src/mpfb/data/targets/mouth/mouth-angles-up.target.gz'),
        weight=.08,
    )
    for side in ('l', 'r'):
        TargetService.load_target(
            body,
            str(Path(config['mpfb']) / f'src/mpfb/data/targets/eyes/{side}-eye-scale-decr.target.gz'),
            weight=.16,
        )
    bpy.context.view_layer.update()
    rig = HumanService.add_builtin_rig(body, 'mixamo_unity')
    rig.name = 'HumanRig'
    assets = Path(config['assets'])
    components = [(body, 'Skin', '#9a756f')]
    for kind, name, label, color in [('eyes', 'low-poly', 'Eyes', None),
                                    ('eyebrows', 'eyebrow003', 'Eyebrows', None),
                                    ('eyelashes', 'eyelashes01', 'Eyelashes', None),
                                    ('hair', recipe['hair'], 'Hair', '#393444'),
                                    ('clothes', recipe['outfit'], 'Clothing', '#718294')]:
        if name == 'none':
            continue
        path = assets / kind / name / (name + '.mhclo')
        before = set(bpy.data.objects)
        HumanService.add_mhclo_asset(str(path), body, asset_type={
            'eyes': 'Eyes', 'eyebrows': 'Eyebrows', 'eyelashes': 'Eyelashes',
            'hair': 'Hair', 'clothes': 'Clothes',
        }[kind],
                                   subdiv_levels=0, material_type='GAMEENGINE')
        for obj in set(bpy.data.objects) - before:
            if obj.type == 'MESH':
                obj.name = label
                components.append((obj, label, color))
    HumanService.refit(body)
    bpy.context.view_layer.update()
    # Bake the fitted rest surfaces including clothing masks, preserving vertex weights.
    # Reattach only the fitted armature. No shared source mesh is mutated by the runtime.
    rig.data.pose_position = 'REST'
    for obj, label, color in components:
        authored_materials = list(obj.data.materials)
        for modifier in obj.modifiers:
            if modifier.type == 'ARMATURE':
                modifier.show_viewport = False
        bpy.context.view_layer.update()
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()), preserve_all_data_layers=True,
                                              depsgraph=bpy.context.evaluated_depsgraph_get())
        obj.modifiers.clear()
        obj.data = mesh
        modifier = obj.modifiers.new('Fitted human skeleton', 'ARMATURE')
        modifier.object = rig
        if color is None:
            # The eye asset carries an atlas with sclera, iris, pupil and highlights.
            # Replacing it with a generic color collapses the entire eye into one dark
            # sphere, so retain the inspected CC0 material through the fitted bake.
            obj.data.materials.clear()
            for material in authored_materials:
                obj.data.materials.append(material)
        else:
            material = bpy.data.materials.new(label)
            material.diffuse_color = (
                *((int(color[i:i+2], 16) / 255) ** 2.2 for i in (1, 3, 5)),
                1,
            )
            material.use_nodes = True
            bsdf = material.node_tree.nodes.get('Principled BSDF')
            bsdf.inputs['Base Color'].default_value = material.diffuse_color
            bsdf.inputs['Roughness'].default_value = .62 if label == 'Skin' else .72
            obj.data.materials.clear()
            obj.data.materials.append(material)
            for face in mesh.polygons:
                face.material_index = 0
        for face in mesh.polygons:
            face.use_smooth = True
    points = [body.matrix_world @ v.co for v in body.data.vertices]
    low, high = min(p.z for p in points), max(p.z for p in points)
    height = high - low
    scale = recipe['heightCm'] / 100 / height
    rig.data.pose_position = 'POSE'
    # Transfer existing authored motion through rest-pose world rotations, retaining the
    # fitted limb lengths. This is an explicit adapter between two inspected rig families.
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=config['animation'])
    imported = set(bpy.data.objects) - before
    source = next(o for o in imported if o.type == 'ARMATURE')
    source_actions = {a.name: a for a in bpy.data.actions}
    mapping = {'Hips': 'Hips', 'Spine': 'Abdomen', 'Spine1': 'Torso', 'Spine2': 'Chest', 'Neck': 'Neck', 'Head': 'Head'}
    for side, suffix in [('Left', 'L'), ('Right', 'R')]:
        for dst, src in [('Shoulder', 'Shoulder'), ('Arm', 'UpperArm'), ('ForeArm', 'LowerArm'), ('Hand', 'Wrist'),
                         ('UpLeg', 'UpperLeg'), ('Leg', 'LowerLeg'), ('Foot', 'Foot'), ('ToeBase', 'PT')]:
            mapping[side + dst] = src + '.' + suffix
        for finger in ['Index', 'Middle', 'Ring', 'Pinky', 'Thumb']:
            for index in range(1, 4):
                mapping[f'{side}Hand{finger}{index}'] = f'{finger}{index}.{suffix}'
    mapping = {'mixamorig:' + k: v for k, v in mapping.items() if 'mixamorig:' + k in rig.pose.bones}
    scene = bpy.context.scene
    scene.render.fps = 24
    rig.animation_data_create()
    for track in list(source.animation_data.nla_tracks):
        source.animation_data.nla_tracks.remove(track)
    clips = {}
    source_rest = {b.name: source.matrix_world @ b.matrix_local for b in source.data.bones}
    target_rest = {b.name: rig.matrix_world @ b.matrix_local for b in rig.data.bones}
    # Use the source family's authored T-pose for calibration. Matching arbitrary
    # bone axes independently changes clavicle/foot orientation and is not retargeting.
    tpose = json.loads((Path(config['mpfb']) / 'src/mpfb/data/poses/mixamo_unity_fk/t-pose.json').read_text())
    for name, rotation in tpose['bone_rotations'].items():
        rig.pose.bones[name].rotation_mode = 'XYZ'
        rig.pose.bones[name].rotation_euler = rotation
    bpy.context.view_layer.update()
    corrections = {dst: source_rest[src].to_quaternion().inverted() @ (rig.matrix_world @ rig.pose.bones[dst].matrix).to_quaternion()
                   for dst, src in mapping.items()}
    for bone in rig.pose.bones:
        bone.rotation_mode = 'QUATERNION'
        bone.rotation_quaternion.identity()
    bpy.context.view_layer.update()
    for name in ['Idle', 'Walk', 'Run', 'Interact']:
        source_action = next(a for n, a in source_actions.items() if n == name or n.startswith(name + '_'))
        source.animation_data.action = source_action
        if source_action.slots:
            source.animation_data.action_slot = source_action.slots[0]
        start, end = map(int, source_action.frame_range)
        action = bpy.data.actions.new('Human' + name)
        rig.animation_data.action = action
        feet = {side: [] for side in ['Left', 'Right']}
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            for bone in rig.pose.bones:
                if bone.name not in mapping:
                    continue
                source_name = mapping[bone.name]
                source_pose = source.matrix_world @ source.pose.bones[source_name].matrix
                desired = rig.matrix_world.to_quaternion().inverted() @ source_pose.to_quaternion() @ corrections[bone.name]
                inherited = bone.bone.matrix_local.to_quaternion()
                if bone.parent:
                    inherited = bone.parent.matrix.to_quaternion() @ bone.parent.bone.matrix_local.to_quaternion().inverted() @ inherited
                bone.rotation_mode = 'QUATERNION'
                bone.rotation_quaternion = inherited.inverted() @ desired
                if bone.name == 'mixamorig:Hips':
                    ratio = target_rest[bone.name].translation.z / source_rest[source_name].translation.z
                    bob = (source_pose.translation.z - source_rest[source_name].translation.z) * ratio
                    bone.location = bone.bone.matrix_local.to_quaternion().inverted() @ Vector((0, 0, bob))
                    bone.keyframe_insert('location', frame=frame - start)
                bone.keyframe_insert('rotation_quaternion', frame=frame - start)
                bpy.context.view_layer.update()
            for side in feet:
                feet[side].append((rig.matrix_world @ rig.pose.bones['mixamorig:' + side + 'Foot'].matrix).translation.copy())
        track = rig.animation_data.nla_tracks.new()
        track.name = name
        track.strips.new(action.name, 0, action)
        track.mute = True
        samples = []
        for path in feet.values():
            floor = min(p.z for p in path)
            samples.extend((b.y - a.y) * 24 for a, b in pairwise(path)
                           if max(a.z, b.z) < floor + .04 and b.y > a.y + .0001)
        clips[name.lower()] = {'name': 'Human' + name, 'durationSeconds': (end - start) / 24,
            'metresPerSecond': 0 if name in ('Idle', 'Interact') else statistics.median(samples),
            'calibrationSamples': len(samples)}
    rig.animation_data.action = None
    for track in rig.animation_data.nla_tracks:
        track.mute = False
    for obj in imported:
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in source_actions.values():
        bpy.data.actions.remove(action)
    # Ground reference comes from the actual skinned idle frame, not the undeformed rest mesh.
    for track in rig.animation_data.nla_tracks:
        track.mute = True
    rig.animation_data.action = bpy.data.actions['HumanIdle']
    scene.frame_set(0)
    bpy.context.view_layer.update()
    idle_points = []
    for obj, _, _ in components:
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        idle_points.extend(evaluated.matrix_world @ v.co for v in mesh.vertices)
        evaluated.to_mesh_clear()
    idle_floor = min(p.z for p in idle_points)
    rig.animation_data.action = None
    for track in rig.animation_data.nla_tracks:
        track.mute = False
    bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True)
    for obj, _, _ in components:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = rig
    scene.frame_set(0)
    bpy.ops.export_scene.gltf(filepath=config['output'], export_format='GLB', use_selection=True,
                             export_animations=True, export_animation_mode='ACTIONS', export_force_sampling=True,
                             export_skins=True, export_morph=False, export_yup=True)
    Path(config['metadata']).write_text(json.dumps({'height': height, 'scale': scale, 'floor': idle_floor,
        'colors': {label: color for _, label, color in components if color is not None}, 'clips': clips,
        'vertices': sum(len(obj.data.vertices) for obj, _, _ in components),
        'bodyBounds': [[min(p[i] for p in points), max(p[i] for p in points)] for i in range(3)],
        'restJoints': {b.name: list(rig.matrix_world @ b.head_local) for b in rig.data.bones}}, indent=2))


if __name__ == '__main__':
    build(json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text()))
