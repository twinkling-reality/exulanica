"""Build one shared people base: a fitted MakeHuman body with every declared wearable.

Runs inside the pinned Blender/MPFB preparation environment, never in the web runtime:

    Blender --background --factory-startup --python-exit-code 1 \
        --python scripts/character_catalog/people_blender.py -- <config.json>

The output GLB holds one skeleton, the body, and each wearable as its own skinned node. Body
shape parameters are morph targets computed by refitting every mesh at the declared macro
extremes, so garments follow the body. Materials are named placeholders; the catalog binds
reviewed material packs to them at runtime. A per-vertex ``_HIDE`` bitmask on the body records
which wearables cover each body vertex, replacing MakeHuman's delete groups without needing a
separate body mesh per outfit.

Declared postures are baked as further clips on the same skeleton (``posture.py``), and every
occlusion-bearing mesh carries its ambient occlusion at rest as a colour attribute named
``Occlusion`` (exported as ``COLOR_0``): the share of a fixed hemisphere of rays that leave the
surface unobstructed, cast against that mesh and the body. The far form's shoulder and hip widths
are measured on the fitted body.
"""

import json
import math
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import posture as postures
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from retarget import FPS, transfer_motion

KINDS = {
    "clothes": "Clothes",
    "hair": "Hair",
    "eyes": "Eyes",
    "eyebrows": "Eyebrows",
    "eyelashes": "Eyelashes",
}
NEUTRAL_FACE = [
    # A relaxed MakeHuman mouth reads as a slight frown on a game-ready mesh, and its default
    # eye opening reads as staring. These restore a neutral face without implying a mood.
    ("mouth/mouth-angles-up", 0.08),
    ("eyes/l-eye-scale-decr", 0.16),
    ("eyes/r-eye-scale-decr", 0.16),
]


def setup(config):
    data = Path(config["cache"]) / "data"
    data.mkdir(parents=True, exist_ok=True)
    for folder in Path(config["assets"]).iterdir():
        if not folder.is_dir():
            continue
        link = data / folder.name
        if link.exists() or link.is_symlink():
            if not link.is_symlink() or link.resolve() != folder.resolve():
                raise ValueError("MPFB asset cache does not point to the verified source: " + folder.name)
        else:
            link.symlink_to(folder, target_is_directory=True)
    sys.path.insert(0, str(Path(config["mpfb"]) / "src"))
    import addon_utils

    # Headless preparation uses its own cache, not a user's installed extension or preferences.
    bpy.utils.extension_path_user = lambda *a, **kw: config["cache"]
    addon_utils.enable("mpfb", default_set=True)


def material_sources(obj):
    """The texture files and alpha use of an MPFB game-engine material, for pack building."""
    result = {}
    for material in obj.data.materials:
        if material is None or not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image is not None:
                result[node.name] = bpy.path.abspath(node.image.filepath)
    return result


def evaluated_positions(objects, body, rig):
    """Rest-pose surfaces with only the body's helper mask applied."""
    rig.data.pose_position = "REST"
    saved = []
    for obj in objects:
        for modifier in obj.modifiers:
            hide = modifier.type == "ARMATURE" or (
                obj is body and modifier.type == "MASK" and modifier.name.startswith("Delete.")
            )
            if hide and modifier.show_viewport:
                saved.append(modifier)
                modifier.show_viewport = False
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    result = {}
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        result[obj.name] = [v.co.copy() for v in mesh.vertices]
        evaluated.to_mesh_clear()
    joints = {b.name: (rig.matrix_world @ b.head_local).copy() for b in rig.data.bones}
    for modifier in saved:
        modifier.show_viewport = True
    rig.data.pose_position = "POSE"
    return result, joints


def apply_macro(body, values, human_service, target_service, properties):
    for key, value in values.items():
        properties.set_value(key, value, entity_reference=body)
    target_service.reapply_macro_details(body)
    human_service.refit(body)
    bpy.context.view_layer.update()


def bake(obj, body, rig):
    """Replace an object's data with its rest surface, keeping vertex groups, then re-skin it."""
    rig.data.pose_position = "REST"
    for modifier in obj.modifiers:
        if modifier.type == "ARMATURE" or (
            obj is body and modifier.type == "MASK" and modifier.name.startswith("Delete.")
        ):
            modifier.show_viewport = False
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(
        obj.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph
    )
    obj.modifiers.clear()
    if obj.data.shape_keys:
        obj.shape_key_clear()
    obj.data = mesh
    modifier = obj.modifiers.new("Fitted skeleton", "ARMATURE")
    modifier.object = rig
    rig.data.pose_position = "POSE"
    for face in mesh.polygons:
        face.use_smooth = True


def _hemisphere(count):
    """``count`` fixed directions over the +Z hemisphere, cosine weighted (a Fibonacci spiral)."""
    golden = math.pi * (3.0 - math.sqrt(5.0))
    directions = []
    for index in range(count):
        radius = math.sqrt((index + 0.5) / count)
        angle = index * golden
        directions.append(Vector((radius * math.cos(angle), radius * math.sin(angle), math.sqrt(max(0.0, 1.0 - radius * radius)))))
    return directions


def _dominant(obj):
    """Each vertex's strongest bone name, or None."""
    groups = {g.index: g.name for g in obj.vertex_groups}
    names = []
    for vertex in obj.data.vertices:
        strongest = max(vertex.groups, key=lambda element: element.weight, default=None)
        names.append(groups.get(strongest.group) if strongest else None)
    return names


def _world_surface(objects, keep):
    """World-space vertices and the polygons ``keep(obj, dominant bones)`` admits, as one list."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    vertices, polygons = [], []
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        offset = len(vertices)
        vertices.extend(obj.matrix_world @ v.co for v in mesh.vertices)
        bones = _dominant(obj)
        polygons.extend(
            [offset + i for i in polygon.vertices]
            for polygon in mesh.polygons
            if keep([bones[i] for i in polygon.vertices])
        )
        evaluated.to_mesh_clear()
    return vertices, polygons


def bake_occlusion(obj, occluders, settings, rest_height):
    """Store ambient occlusion at rest on ``obj`` as the ``Occlusion`` colour attribute.

    For each vertex a fixed set of rays over the hemisphere about its normal is cast against
    ``occluders``; the stored value is the share that travel ``reachShare`` of the rest height
    unobstructed, raised to ``floor`` at the least. Surface the rest pose holds apart from the
    body only by chance (the declared ``detachedBones``: forearms and hands hang beside the hips
    at rest and swing away when walking) occludes nothing but itself. Returns the mean and the
    share of darkened vertices, for the preparation receipt.
    """
    detached = tuple(settings["detachedBones"])

    def is_detached(bone):
        return bone is not None and any(part in bone for part in detached)

    def tree(keep):
        vertices, polygons = _world_surface(occluders, keep)
        return BVHTree.FromPolygons(vertices, polygons, all_triangles=False, epsilon=0.0)

    everything = tree(lambda bones: True)
    attached = tree(lambda bones: not all(is_detached(b) for b in bones))
    directions = _hemisphere(settings["rays"])
    reach = settings["reachShare"] * rest_height
    lift = settings["liftMetres"]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    bones = _dominant(obj)
    values = []
    for vertex in mesh.vertices:
        origin = obj.matrix_world @ vertex.co
        normal = (obj.matrix_world.to_3x3() @ vertex.normal).normalized()
        tangent = normal.orthogonal().normalized()
        bitangent = normal.cross(tangent)
        start = origin + normal * lift
        against = everything if is_detached(bones[vertex.index]) else attached
        open_rays = 0
        for d in directions:
            ray = tangent * d.x + bitangent * d.y + normal * d.z
            hit, *_ = against.ray_cast(start, ray, reach)
            if hit is None:
                open_rays += 1
        values.append(max(settings["floor"], open_rays / len(directions)))
    evaluated.to_mesh_clear()
    if len(values) != len(obj.data.vertices):
        raise ValueError(f"occlusion for {obj.name} does not match its vertices")
    attribute = obj.data.color_attributes.new(name="Occlusion", type="FLOAT_COLOR", domain="POINT")
    attribute.data.foreach_set("color", [c for value in values for c in (value, value, value, 1.0)])
    return {
        "meanMilli": round(1000 * sum(values) / len(values)),
        "darkenedMilli": round(1000 * sum(1 for v in values if v < 0.9) / len(values)),
    }


def far_widths(body, rest_height):
    """Shoulder and hip widths of the fitted body at rest, for the far form's build."""
    rig = body.find_armature()
    joints = {b.name: rig.matrix_world @ b.head_local for b in rig.data.bones}
    groups = {g.index: g.name for g in body.vertex_groups}
    band = 0.012 * rest_height

    def width(height, excluded):
        xs = []
        for vertex in body.data.vertices:
            strongest = max(vertex.groups, key=lambda element: element.weight, default=None)
            name = groups.get(strongest.group) if strongest else None
            if name is None or any(part in name for part in excluded):
                continue
            point = body.matrix_world @ vertex.co
            if abs(point.z - height) <= band:
                xs.append(point.x)
        return round((max(xs) - min(xs)) * 1000)

    return {
        "shoulderWidthMillimetres": width(joints["mixamorig:LeftArm"].z, ("Hand", "ForeArm")),
        "hipWidthMillimetres": width(joints["mixamorig:LeftUpLeg"].z, ("Hand", "ForeArm", "Arm")),
    }


def idle_floor(rig, body, config):
    """The lowest point of the body in the idle clip's first frame, which the renderer lifts to its ground."""
    held = [(track, track.mute) for track in rig.animation_data.nla_tracks]
    for track, _ in held:
        track.mute = True
    rig.animation_data.action = bpy.data.actions[config["clips"][config["idleClip"]]]
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    floor = min((evaluated.matrix_world @ v.co).z for v in mesh.vertices)
    evaluated.to_mesh_clear()
    rig.animation_data.action = None
    for track, mute in held:
        track.mute = mute
    return floor


def build(config):
    setup(config)
    from mpfb.entities.objectproperties import HumanObjectProperties
    from mpfb.services.humanservice import HumanService
    from mpfb.services.targetservice import TargetService

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    base = config["base"]
    macro = TargetService.get_default_macro_info_dict()
    macro.update(base["macro"])
    body = HumanService.create_human(macro_detail_dict=macro)
    body.name = "body"
    targets = Path(config["mpfb"]) / "src/mpfb/data/targets"
    for target, weight in NEUTRAL_FACE:
        TargetService.load_target(body, str(targets / (target + ".target.gz")), weight=weight)
    bpy.context.view_layer.update()
    rig = HumanService.add_builtin_rig(body, "mixamo_unity")
    rig.name = "rig"
    assets = Path(config["assets"])
    wearables = []
    for wearable in config["wearables"]:
        path = assets / wearable["kind"] / wearable["source"] / (wearable["source"] + ".mhclo")
        before = set(bpy.data.objects)
        HumanService.add_mhclo_asset(
            str(path),
            body,
            asset_type=KINDS[wearable["kind"]],
            subdiv_levels=0,
            material_type="GAMEENGINE",
        )
        created = [o for o in set(bpy.data.objects) - before if o.type == "MESH"]
        if len(created) != 1:
            raise ValueError(f"{wearable['id']} produced {len(created)} meshes")
        obj = created[0]
        obj.name = wearable["node"]
        wearables.append((wearable, obj, material_sources(obj)))
    HumanService.refit(body)
    bpy.context.view_layer.update()
    objects = [body] + [w[1] for w in wearables]

    base_positions, base_joints = evaluated_positions(objects, body, rig)
    morph_positions = {}
    joint_motion = {}
    restore = {key: macro[key] for morph in config["morphs"] for key in morph["macro"]}
    for morph in config["morphs"]:
        apply_macro(body, morph["macro"], HumanService, TargetService, HumanObjectProperties)
        positions, joints = evaluated_positions(objects, body, rig)
        for name, values in positions.items():
            if len(values) != len(base_positions[name]):
                raise ValueError(f"{morph['key']} changed the vertex count of {name}")
        morph_positions[morph["key"]] = positions
        joint_motion[morph["key"]] = max(
            (joints[n] - base_joints[n]).length for n in base_joints
        )
        apply_macro(body, restore, HumanService, TargetService, HumanObjectProperties)
    restored, _ = evaluated_positions(objects, body, rig)
    for name, values in restored.items():
        drift = max((a - b).length for a, b in zip(values, base_positions[name], strict=True))
        if drift > 1e-5:
            raise ValueError(f"restoring the base macros did not restore {name} ({drift} m)")

    # Record which wearables cover each body vertex before the delete groups are dropped.
    hide_bits = {w[0]["node"]: w[0]["hideBit"] for w in wearables if "hideBit" in w[0]}
    for obj in objects:
        bake(obj, body, rig)
    hidden = [0] * len(body.data.vertices)
    groups = {g.index: g.name for g in body.vertex_groups}
    for wearable, _, _ in wearables:
        if "hideBit" not in wearable:
            continue
        group = body.vertex_groups.get("Delete." + wearable["source"])
        if group is None:
            raise ValueError(f"{wearable['id']} declares a hide bit but has no delete group")
        for vertex in body.data.vertices:
            for element in vertex.groups:
                if element.group == group.index and element.weight > 0.5:
                    hidden[vertex.index] |= 1 << wearable["hideBit"]
    bone_names = {b.name for b in rig.data.bones}
    for obj in objects:
        for group in list(obj.vertex_groups):
            if group.name not in bone_names:
                obj.vertex_groups.remove(group)
    attribute = body.data.attributes.new(name="_HIDE", type="FLOAT", domain="POINT")
    attribute.data.foreach_set("value", [float(v) for v in hidden])
    del groups

    # Morph targets, relative to the baked rest surface. Unmoved meshes carry no target.
    morph_nodes = {}
    for obj in objects:
        count = len(obj.data.vertices)
        if count != len(base_positions[obj.name]):
            raise ValueError(f"baking changed the vertex count of {obj.name}")
        keys = []
        for morph in config["morphs"]:
            positions = morph_positions[morph["key"]][obj.name]
            largest = max((a - b).length for a, b in zip(positions, base_positions[obj.name], strict=True))
            if largest < config.get("morphEpsilonMetres", 0.0005):
                continue
            if obj.data.shape_keys is None:
                obj.shape_key_add(name="Basis", from_mix=False)
            key = obj.shape_key_add(name=morph["key"], from_mix=False)
            for index, position in enumerate(positions):
                key.data[index].co = position
            keys.append({"key": morph["key"], "maxMillimetres": round(largest * 1000, 1)})
        morph_nodes[obj.name] = keys

    # Placeholder materials named for the catalog's bindings.
    placeholders = {}
    for obj, name in [(body, "skin")] + [(w[1], w[0]["material"]) for w in wearables]:
        material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        material.use_nodes = True
        obj.data.materials.clear()
        obj.data.materials.append(material)
        for face in obj.data.polygons:
            face.material_index = 0
        placeholders[obj.name] = name

    calibration = transfer_motion(rig, config["animation"], config["mpfb"], config["clips"])

    rest_points = [body.matrix_world @ v for v in base_positions["body"]]
    rest_height = max(p.z for p in rest_points) - min(p.z for p in rest_points)
    # Baked in the order the definition declares them: each bake leaves the rig's floating-point
    # state a little changed, so a posture declared after the others leaves their clips as they were.
    posture_measurements = {
        key: postures.bake(rig, body, spec, rest_height, spec["clip"], FPS, ground=idle_floor(rig, body, config))
        for key, spec in config.get("postures", {}).items()
    }
    for bone in rig.pose.bones:
        bone.rotation_quaternion.identity()
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    widths = far_widths(body, rest_height)
    occlusion = {}
    rig.data.pose_position = "REST"
    bpy.context.view_layer.update()
    occluding = {w[0]["node"]: w[1] for w in wearables if w[0]["kind"] in config["occlusion"]["kinds"]}
    occlusion["body"] = bake_occlusion(body, [body], config["occlusion"], rest_height)
    for node, obj in sorted(occluding.items()):
        occlusion[node] = bake_occlusion(obj, [body, obj], config["occlusion"], rest_height)
    rig.data.pose_position = "POSE"
    bpy.context.view_layer.update()

    # Height and ground from the idle's first frame, measured on the actual skinned surface.
    scene = bpy.context.scene
    for track in rig.animation_data.nla_tracks:
        track.mute = True
    rig.animation_data.action = bpy.data.actions[config["clips"][config["idleClip"]]]
    scene.frame_set(0)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    idle = [evaluated.matrix_world @ v.co for v in mesh.vertices]
    evaluated.to_mesh_clear()
    rest = [body.matrix_world @ v for v in base_positions["body"]]
    eyes = next((w[1] for w in wearables if w[0]["kind"] == "eyes"), None)
    eye_centre = None
    if eyes is not None:
        points = [eyes.matrix_world @ v.co for v in eyes.data.vertices]
        eye_centre = [sum(p[i] for p in points) / len(points) for i in range(3)]
    rig.animation_data.action = None
    for track in rig.animation_data.nla_tracks:
        track.mute = False

    bpy.ops.object.select_all(action="DESELECT")
    for obj in [rig, *objects]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = rig
    scene.frame_set(0)
    bpy.ops.export_scene.gltf(
        filepath=config["output"],
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_animation_mode="ACTIONS",
        export_force_sampling=True,
        export_skins=True,
        export_morph=True,
        export_morph_normal=config.get("morphNormals", True),
        export_morph_tangent=False,
        export_try_sparse_sk=True,
        export_attributes=True,
        export_vertex_color="NAME",
        export_vertex_color_name="Occlusion",
        export_all_vertex_colors=False,
        export_yup=True,
        export_apply=False,
        export_image_format="NONE",
        export_materials="PLACEHOLDER" if config.get("placeholderMaterials") else "EXPORT",
    )
    metadata = {
        "baseId": base["baseId"],
        "restHeightMetres": max(p.z for p in rest) - min(p.z for p in rest),
        "idleFloorMetres": min(p.z for p in idle),
        "eyeCentre": eye_centre,
        "jointMotionMetres": joint_motion,
        "clips": calibration,
        "nodes": {
            obj.name: {
                "vertices": len(obj.data.vertices),
                "triangles": sum(len(p.vertices) - 2 for p in obj.data.polygons),
                "material": placeholders[obj.name],
                "morphs": morph_nodes[obj.name],
            }
            for obj in objects
        },
        "wearables": {
            w[0]["id"]: {"node": w[1].name, "textures": w[2]} for w in wearables
        },
        "bodyHiddenVertexCounts": {
            node: sum(1 for v in hidden if v & (1 << bit)) for node, bit in hide_bits.items()
        },
        "bones": [b.name for b in rig.data.bones],
        "postures": posture_measurements,
        "farWidths": widths,
        "occlusion": occlusion,
    }
    for value in metadata["jointMotionMetres"].values():
        if not math.isfinite(value):
            raise ValueError("non-finite joint motion")
    Path(config["metadata"]).write_text(json.dumps(metadata, indent=1, sort_keys=True))


if __name__ == "__main__":
    build(json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text()))
