"""Author a posture on a fitted skeleton from declared targets. Runs inside the pinned Blender.

A posture is data (``definition.json`` ``postures``): how far forward and apart the feet rest, where
the hands go, how the pelvis and trunk tilt and how the chest breathes, every distance in units of
the base's rest height, so each base gets the same posture fitted to its own body. The limbs are
placed with a two-bone solve in the plane their declared pole gives, the feet stay flat at their
standing height, and the pelvis is then lowered until the lowest point of the seat, measured on the
skinned surface, rests on the ground, or on a seat ``seatHeight`` above it where the posture is one
drawn on a seat (0 where it states none). Nothing here is tuned for a person: a look differs only in the
morph weights and height the renderer applies over the same clip.
"""

import math

import bpy
from mathutils import Matrix, Vector

PREFIX = "mixamorig:"
SIDES = (("Left", 1.0), ("Right", -1.0))
#: Bones whose surface is what a seated body rests on, unless a posture states its own
#: (``seatBones``): on a seat the thighs slope down to the knees, so their lowest point is not what
#: the body rests on.
SEAT_BONES = ("Hips", "LeftUpLeg", "RightUpLeg", "LeftButtock", "RightButtock")
#: Pelvis settling: each round solves the limbs, measures the seat and moves the pelvis by the gap.
#: The gap shrinks by a steady share each round; a pose not settled within the rounds is refused.
SETTLE_ROUNDS = 20
#: How close the seat must come to its target: a quarter of a millimetre.
SETTLED_METRES = 0.00025


def _bone(rig, name):
    return rig.pose.bones[PREFIX + name]


def _update():
    bpy.context.view_layer.update()


def _set_rotation(pose_bone, rotation, head=None):
    """Put a bone at ``head`` (armature space) with the given armature-space rotation.

    The rotation is made orthonormal first: a product of posed matrices carries floating-point
    scale and shear, and setting it would leave a bone scaled, which grows over every frame baked.
    """
    matrix = rotation.to_quaternion().normalized().to_matrix().to_4x4()
    matrix.translation = pose_bone.matrix.translation if head is None else head
    pose_bone.matrix = matrix
    _update()


def _rotate(pose_bone, rotation):
    """Turn a bone about its own head by an armature-space rotation."""
    _set_rotation(pose_bone, rotation @ pose_bone.matrix.to_quaternion().to_matrix())


def _aim(pose_bone, target, toward=None):
    """Swing a bone about its head, with the least rotation, so ``toward`` points at ``target``.

    ``toward`` is where the next joint of the chain is now; without one, the bone's own axis is
    turned. A fitted rig's bone axis need not pass through its child's head, so a chain is aimed by
    its joints.
    """
    matrix = pose_bone.matrix
    along = (matrix.col[1].xyz if toward is None else toward - matrix.translation).normalized()
    wanted = (target - matrix.translation).normalized()
    _rotate(pose_bone, along.rotation_difference(wanted).to_matrix())


def _two_bone(start, target, upper, lower, pole):
    """The middle joint of a two-bone chain reaching from ``start`` toward ``target``."""
    reach = target - start
    distance = max(1e-4, min(upper + lower - 1e-4, reach.length))
    direction = reach.normalized()
    bend = pole - direction * pole.dot(direction)
    if bend.length < 1e-6:
        raise ValueError("a posture pole lies along its limb")
    bend.normalize()
    cosine = (upper * upper + distance * distance - lower * lower) / (2 * upper * distance)
    angle = math.acos(max(-1.0, min(1.0, cosine)))
    return start + direction * (math.cos(angle) * upper) + bend * (math.sin(angle) * upper)


def _span(rig, joint, child):
    """The rest distance between a joint and the next joint of its chain."""
    bones = rig.data.bones
    return (bones[PREFIX + child].head_local - bones[PREFIX + joint].head_local).length


def _limb(rig, upper, lower, end, target, pole, end_rotation):
    """Place a two-bone limb so its end joint reaches ``target``; the end takes ``end_rotation``."""
    start = _bone(rig, upper).matrix.translation.copy()
    middle = _two_bone(start, target, _span(rig, upper, lower), _span(rig, lower, end), pole)
    _aim(_bone(rig, upper), middle, _bone(rig, lower).matrix.translation.copy())
    _aim(_bone(rig, lower), target, _bone(rig, end).matrix.translation.copy())
    tip = _bone(rig, end).matrix.translation.copy()
    if end_rotation is not None:
        _set_rotation(_bone(rig, end), end_rotation, tip)
    return (tip - target).length


def _seat_height(rig, body, bones=SEAT_BONES):
    """The lowest point of the seat, in the rig's space, from the skinned surface of ``bones``."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    groups = {group.index: group.name for group in body.vertex_groups}
    seat = {PREFIX + name for name in bones}
    lowest = math.inf
    for vertex in mesh.vertices:
        source = body.data.vertices[vertex.index]
        strongest = max(source.groups, key=lambda element: element.weight, default=None)
        if strongest is None or groups.get(strongest.group) not in seat:
            continue
        lowest = min(lowest, (body.matrix_world @ vertex.co).z)
    evaluated.to_mesh_clear()
    if not math.isfinite(lowest):
        raise ValueError("the body has no seat surface to rest on")
    return lowest


def seat_target(posture, rest_height, ground=0.0):
    """Where the lowest point of the seat settles, in the rig's space."""
    return ground + (posture.get("seatHeight", 0.0) - posture["seatSink"]) * rest_height


def pose(rig, body, posture, rest_height, phase=0.0, ground=0.0):
    """Pose ``rig`` in ``posture`` at a breathing ``phase`` in [0, 1). Returns measurements.

    Every declared distance is a share of ``rest_height``; angles are degrees. Forward is -Y in
    Blender's space, which is the direction the fitted body faces. ``ground`` is the height the
    renderer's ground sits at in the rig's space: the idle clip's measured floor, which the
    renderer lifts to its ground, so a posture rests on the same ground a standing person does.
    """
    seat_bones = tuple(posture.get("seatBones", SEAT_BONES))
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion.identity()
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)
    _update()
    rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    x_axis = Vector((1.0, 0.0, 0.0))
    hips = _bone(rig, "Hips")
    _rotate(hips, Matrix.Rotation(math.radians(-posture["pelvisTiltDegrees"]), 3, x_axis))
    lean = math.radians(posture["trunkLeanDegrees"])
    breath = math.radians(posture["breathDegrees"]) * math.sin(2 * math.pi * phase)
    spine = ("Spine", "Spine1", "Spine2")
    for name in spine:
        share = lean / len(spine) + (breath if name == "Spine2" else 0.0)
        _rotate(_bone(rig, name), Matrix.Rotation(share, 3, x_axis))
    # The head comes back level, so the face looks ahead rather than down at the knees.
    level = -(lean - math.radians(posture["pelvisTiltDegrees"])) - breath
    for name, share in (("Neck", 0.5), ("Head", 0.5)):
        _rotate(_bone(rig, name), Matrix.Rotation(level * share, 3, x_axis))

    feet = {}
    for side, sign in SIDES:
        ankle = rest[PREFIX + side + "Foot"].translation
        feet[side] = Vector(
            (
                sign * posture["feetApart"] * rest_height,
                -posture["feetForward"] * rest_height,
                ankle.z + ground,
            )
        )
    for _round in range(SETTLE_ROUNDS):
        worst = {"foot": 0.0, "hand": 0.0}
        for side, sign in SIDES:
            knee_pole = Vector((sign * posture["kneeOut"], -1.0, posture["kneeUp"]))
            foot_rest = rest[PREFIX + side + "Foot"].to_3x3()
            reach = _limb(
                rig, side + "UpLeg", side + "Leg", side + "Foot", feet[side], knee_pole, foot_rest
            )
            worst["foot"] = max(worst["foot"], reach)
        knees = {side: _bone(rig, side + "Leg").matrix.translation.copy() for side, _ in SIDES}
        for side, sign in SIDES:
            hand = knees[side] + Vector(
                (
                    sign * posture["handOut"] * rest_height,
                    -posture["handForward"] * rest_height,
                    posture["handAbove"] * rest_height,
                )
            )
            elbow_pole = Vector((sign * posture["elbowOut"], posture["elbowBack"], -1.0))
            reach = _limb(
                rig, side + "Arm", side + "ForeArm", side + "Hand", hand, elbow_pole, None
            )
            worst["hand"] = max(worst["hand"], reach)
            forearm = (
                _bone(rig, side + "Hand").matrix.translation
                - _bone(rig, side + "ForeArm").matrix.translation
            ).normalized()
            # Rotating about up x forearm turns the hand down past the wrist for a positive drop.
            wrist = Matrix.Rotation(
                math.radians(posture["wristDropDegrees"]), 3, Vector((0.0, 0.0, 1.0)).cross(forearm)
            )
            _aim(
                _bone(rig, side + "Hand"),
                _bone(rig, side + "Hand").matrix.translation + wrist @ forearm,
            )
        # The seat settles a declared depth into what it rests on, the ground or a seat
        # ``seatHeight`` above it, so no gap of light shows beneath it.
        gap = _seat_height(rig, body, seat_bones) - seat_target(posture, rest_height, ground)
        if abs(gap) < SETTLED_METRES:
            break
        placed = hips.matrix.copy()
        placed.translation.z -= gap
        hips.matrix = placed
        _update()
    else:
        raise ValueError(f"the seat did not settle within {SETTLE_ROUNDS} rounds (gap {gap:.5f} m)")
    return {
        "footReachErrorMetres": round(worst["foot"], 6),
        "handReachErrorMetres": round(worst["hand"], 6),
        "seatMetres": round(_seat_height(rig, body, seat_bones), 6),
        "pelvisMetres": round(hips.matrix.translation.z, 6),
    }


def joints(rig):
    """Joint positions in the rig's space, for a far form to follow the same posture."""
    names = {
        "pelvis": "Hips",
        "chest": "Spine2",
        "neck": "Neck",
        "head": "Head",
    }
    result = {key: list(_bone(rig, name).matrix.translation) for key, name in names.items()}
    for side, _ in SIDES:
        prefix = side.lower()
        for key, name in (
            ("Hip", "UpLeg"),
            ("Knee", "Leg"),
            ("Ankle", "Foot"),
            ("Toe", "ToeBase"),
            ("Shoulder", "Arm"),
            ("Elbow", "ForeArm"),
            ("Wrist", "Hand"),
        ):
            result[prefix + key] = list(_bone(rig, side + name).matrix.translation)
    return {key: [round(v, 6) for v in value] for key, value in sorted(result.items())}


def bake(rig, body, posture, rest_height, clip_name, fps, ground=0.0):
    """Key the posture over one breath as an action named ``clip_name``; return measurements.

    Every other clip's track is muted while the pose is set bone by bone, so nothing else plays
    into it, and the tracks are left as they were found.
    """
    frames = max(2, round(posture["breathSeconds"] * fps))
    rig.animation_data_create()
    held = [(track, track.mute) for track in rig.animation_data.nla_tracks]
    for track, _ in held:
        track.mute = True
    action = bpy.data.actions.new(clip_name)
    rig.animation_data.action = action
    measured = []
    for frame in range(frames + 1):
        measured.append(pose(rig, body, posture, rest_height, phase=frame / frames, ground=ground))
        for bone in rig.pose.bones:
            bone.keyframe_insert("rotation_quaternion", frame=frame)
            bone.keyframe_insert("location", frame=frame)
    first = pose(rig, body, posture, rest_height, phase=0.0, ground=ground)
    placed = joints(rig)
    rig.animation_data.action = None
    track = rig.animation_data.nla_tracks.new()
    track.name = clip_name
    track.strips.new(action.name, 0, action)
    track.mute = True
    for other, mute in held:
        other.mute = mute
    return {
        "durationSeconds": frames / fps,
        "frames": frames + 1,
        "first": first,
        "worstFootReachErrorMetres": max(m["footReachErrorMetres"] for m in measured),
        "worstHandReachErrorMetres": max(m["handReachErrorMetres"] for m in measured),
        "seatMetres": [
            min(m["seatMetres"] for m in measured),
            max(m["seatMetres"] for m in measured),
        ],
        "joints": placed,
    }
