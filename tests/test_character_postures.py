"""Postures in the character catalog: what they answer to in a society, and that each was baked.

A posture is drawn for an activity the simulation states. The catalog names those activities by the
society's own keys, so a renamed or removed activity must fail here rather than leave resting people
standing. Every base carries every posture as a clip in its own container, and the preparation's
receipt shows the limbs reached their declared targets and the seat rests on the ground a standing
person stands on.
"""

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


def animation_names(path: Path) -> set[str]:
    data = path.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + length])
    return {animation["name"] for animation in document.get("animations", [])}


def test_every_activity_the_catalog_draws_is_one_a_society_states():
    known = society_activities()
    assert "rest" in known
    for family in CATALOG["families"]:
        postures = {posture["key"] for posture in family["postures"]}
        assert family["activityPostures"], "a family with postures draws at least one activity"
        for activity, posture in family["activityPostures"].items():
            assert activity in known, f"{activity} is not an activity any society states"
            assert posture in postures


def test_every_base_carries_every_posture_as_a_clip_in_its_own_container():
    for family in CATALOG["families"]:
        declared = {posture["key"] for posture in family["postures"]}
        for base in family["bases"]:
            assert set(base["postures"]) == declared
            clips = animation_names(CHARACTERS / base["asset"]["file"])
            for key, posture in base["postures"].items():
                assert posture["clip"]["name"] in clips, f"{base['baseId']} {key}"
                joints = posture["jointsMillimetres"]
                # Seated on the ground: the pelvis is below the knees and the feet rest in front.
                for side in ("left", "right"):
                    assert joints["pelvis"][1] < joints[f"{side}Knee"][1]
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
                target = ground - spec["seatSink"] * measured["restHeightMetres"]
                low, high = posture["seatMetres"]
                where = (base["baseId"], key)
                assert target - MILLIMETRE <= low <= high <= target + MILLIMETRE, where
