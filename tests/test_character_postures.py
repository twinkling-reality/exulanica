"""Postures in the character catalog: what they answer to in a society, and that each was baked.

A posture is drawn for an activity the simulation states, on the ground or, where the person is
drawn at a seat, on the seat. The catalog names those activities by the society's own keys, so a
renamed or removed activity must fail here rather than leave resting people standing. Every base
carries every posture as a clip in its own container, and the preparation's receipt shows the limbs
reached their declared targets and the seat rests where the posture declares: on the ground a
standing person stands on, or a declared share of the body's rest height above it.
"""

import hashlib
import json
import struct
from pathlib import Path

from exulanica.world.society_planner import DURATIONS

ROOT = Path(__file__).parents[1]
CHARACTERS = ROOT / "assets/characters"
CATALOG = json.loads((CHARACTERS / "catalog.json").read_text())
DEFINITION = json.loads((CHARACTERS / "makehuman-people-v1/definition.json").read_text())
RECEIPT = json.loads((CHARACTERS / "makehuman-people-v1/preparation-receipt.json").read_text())
ACTIVITIES = json.loads((ROOT / "assets/catalogs/society/society-activity.v1.json").read_text())
#: A millimetre: the reach and seat tolerance the preparation is held to.
MILLIMETRE = 0.001


def society_activities() -> set[str]:
    """Every activity a society states: the living society's catalog and the planner's."""
    return {entry["key"] for entry in ACTIVITIES["entries"]} | set(DURATIONS)


def _glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    binary = 20 + length
    size = struct.unpack_from("<I", data, binary)[0]
    return json.loads(data[20 : 20 + length]), data[binary + 8 : binary + 8 + size]


def animation_names(path: Path) -> set[str]:
    document, _ = _glb(path)
    return {animation["name"] for animation in document.get("animations", [])}


def clip_sha256(path: Path, name: str) -> str:
    """One clip's keyed bytes: each channel's target and interpolation, its times and its values."""
    document, blob = _glb(path)
    animation = next(a for a in document["animations"] if a["name"] == name)
    digest = hashlib.sha256()
    for channel in animation["channels"]:
        sampler = animation["samplers"][channel["sampler"]]
        node = document["nodes"][channel["target"]["node"]]["name"]
        interpolation = sampler.get("interpolation", "LINEAR")
        digest.update(f"{node}|{channel['target']['path']}|{interpolation}|".encode())
        for index in (sampler["input"], sampler["output"]):
            accessor = document["accessors"][index]
            view = document["bufferViews"][accessor["bufferView"]]
            width = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[accessor["type"]] * 4
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            digest.update(blob[start : start + width * accessor["count"]])
    return digest.hexdigest()


#: The ground rest's clip on each base as main held it before the seat posture was added
#: (base revision 2), digested by :func:`clip_sha256`. Adding a posture must not move it.
GROUND_REST_CLIP_SHA256 = {
    "feminine": "cd94a5ef46a48120e36d9a3ed578ba854c52643d693937647aaa5c845a186d24",
    "masculine": "788361124a0d353e70c95d1e69b9543e00406d9dd9fc03559bc94357737b6d1d",
}


def seat_share(key: str) -> float:
    """How far above the ground a posture rests its seat, as a share of rest height: 0 on it."""
    return DEFINITION["postures"][key].get("seatHeight", 0.0)


def test_every_activity_the_catalog_draws_is_one_a_society_states():
    known = society_activities()
    assert "rest" in known
    for family in CATALOG["families"]:
        postures = {posture["key"] for posture in family["postures"]}
        assert family["activityPostures"], "a family with postures draws at least one activity"
        for activity, posture in family["activityPostures"].items():
            assert activity in known, f"{activity} is not an activity any society states"
            assert posture in postures
            # An activity drawn where there is no seat rests on the ground.
            assert seat_share(posture) == 0.0, posture
        for activity, posture in family["seatPostures"].items():
            assert activity in known, f"{activity} is not an activity any society states"
            assert posture in postures
            # And one drawn on a seat rests above it.
            assert seat_share(posture) > 0.0, posture
    assert CATALOG["families"][0]["seatPostures"] == DEFINITION["seatPostures"]["activities"]


def test_every_base_carries_every_posture_as_a_clip_in_its_own_container():
    for family in CATALOG["families"]:
        declared = {posture["key"] for posture in family["postures"]}
        for base in family["bases"]:
            assert set(base["postures"]) == declared
            clips = animation_names(CHARACTERS / base["asset"]["file"])
            for key, posture in base["postures"].items():
                assert posture["clip"]["name"] in clips, f"{base['baseId']} {key}"
                joints = posture["jointsMillimetres"]
                for side in ("left", "right"):
                    # On the ground the pelvis is below the knees; on a seat it is above them.
                    below = joints["pelvis"][1] < joints[f"{side}Knee"][1]
                    assert below == (seat_share(key) == 0.0), (base["baseId"], key)
                    # Either way the feet rest in front of the pelvis.
                    assert joints[f"{side}Ankle"][2] > joints["pelvis"][2]


def test_the_preparation_reached_every_target_and_seated_the_body_on_the_ground():
    for family in CATALOG["families"]:
        for base in family["bases"]:
            measured = RECEIPT["measurements"][base["baseId"]]
            ground = base["idleFloorMicrometres"] / 1_000_000
            for key, posture in measured["postures"].items():
                spec = DEFINITION["postures"][key]
                assert posture["worstFootReachErrorMetres"] < MILLIMETRE
                assert posture["worstHandReachErrorMetres"] < MILLIMETRE
                share = spec.get("seatHeight", 0.0) - spec["seatSink"]
                target = ground + share * measured["restHeightMetres"]
                low, high = posture["seatMetres"]
                where = (base["baseId"], key)
                assert target - MILLIMETRE <= low <= high <= target + MILLIMETRE, where


def test_the_catalog_states_the_seat_height_the_preparation_measured():
    for family in CATALOG["families"]:
        for base in family["bases"]:
            measured = RECEIPT["measurements"][base["baseId"]]["postures"]
            ground = base["idleFloorMicrometres"] / 1_000_000
            for key, posture in base["postures"].items():
                seat = measured[key]["first"]["seatMetres"]
                assert posture["seatMillimetres"] == round((seat - ground) * 1000), (base, key)


def test_adding_a_posture_left_the_ground_rest_clip_as_it_was():
    for family in CATALOG["families"]:
        clip = next(
            posture["clip"]["name"]
            for key, posture in family["bases"][0]["postures"].items()
            if key == family["activityPostures"]["rest"]
        )
        for base in family["bases"]:
            path = CHARACTERS / base["asset"]["file"]
            assert clip_sha256(path, clip) == GROUND_REST_CLIP_SHA256[base["baseId"]]
