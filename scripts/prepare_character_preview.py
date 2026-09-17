"""Derive the committed stylized character looks.

    uv run python scripts/prepare_character_preview.py          # write the list
    uv run python scripts/prepare_character_preview.py --check  # compare the committed list

The committed list, assets/characters/stylized-looks.json, is derived from the pinned Quaternius
manifest, its import receipts and the pinned container bytes; nothing else decides its content.
The app reads it, and the editable human's committed default look beside it, directly: nothing is
copied into the app's public folder, so no build can carry these containers by accident.
"""

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/characters/quaternius-modular-v2"
STYLIZED_LOOKS = ROOT / "assets/characters/stylized-looks.json"
PROFILE = "exulanica.character-stylized-looks/v1"
NAMES = {
    "hoodie": "Hoodie",
    "casual": "Everyday",
    "casual-f": "Relaxed",
    "formal-f": "Tailored",
}
# The world faces -Z. A container authored facing +Z turns half a turn to face the same way.
WORLD_FORWARD_YAW_DEGREES = {"+Z": 180, "-Z": 0}


def component_materials(document, node_name):
    node = next(node for node in document["nodes"] if node.get("name") == node_name)
    return {
        document["materials"][part["material"]]["name"]
        for part in document["meshes"][node["mesh"]]["primitives"]
    }


def forward_yaw_degrees(frame) -> int:
    axis = WORLD_FORWARD_YAW_DEGREES.get(frame["forward"])
    if axis is None or frame["forward_yaw_radians"] != 0 or frame["up"] != "+Y":
        raise ValueError(f"Unsupported source frame: {frame['forward']} forward, {frame['up']} up")
    return axis


def stylized_look(asset) -> dict:
    receipt = json.loads((SOURCE / (asset["look_id"] + ".import.json")).read_text())
    descriptor = {
        "asset": {
            "assetKey": receipt["asset_key"],
            "mediaType": "model/gltf-binary",
            "contentSha256": receipt["content_sha256"],
            "byteSize": receipt["byte_size"],
        },
        "rigId": asset["rig_profile"],
        "joints": [joint["name"] for joint in asset["audit"]["joints"]],
        "unitScale": asset["frame"]["unit_scale"],
        "forwardYawDegrees": forward_yaw_degrees(asset["frame"]),
        "groundOffset": asset["frame"]["idle_floor_offset_metres"],
        "standingHeight": asset["frame"]["height_metres"],
        "clips": {
            name: {
                "name": asset["clips"][name]["name"],
                "metresPerSecond": asset["clips"][name]["nominal_speed_mps"],
            }
            for name in ["idle", "walk", "run"]
        },
        "rootMotion": {"mode": "in-place"},
        "materialSlots": {
            name: {"materials": [slot["material_name"]]}
            for name, slot in asset["material_slots"].items()
        },
        "morphParameters": {},
        "variantSlots": {},
    }
    item = {"lookId": asset["look_id"], "file": asset["file"], "descriptor": descriptor}
    path = SOURCE / asset["file"]
    data = path.read_bytes()
    reference = item["descriptor"]["asset"]
    if (
        len(data) != reference["byteSize"]
        or hashlib.sha256(data).hexdigest() != reference["contentSha256"]
    ):
        raise ValueError(f"Pinned character bytes changed: {path.name}")
    size = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20 : 20 + size])

    # glTF base color is linear. The color picker and native edits use sRGB.
    def hex_color(values):
        def channel(v):
            return round(255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055))

        return "#" + "".join(f"{channel(v):02x}" for v in values[:3])

    colors = {
        m["name"]: hex_color(m.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1]))
        for m in gltf["materials"]
    }
    item["label"] = NAMES.get(item["lookId"], item["lookId"])
    item["defaultColors"] = {
        slot: colors[spec["materials"][0]]
        for slot, spec in item["descriptor"]["materialSlots"].items()
    }
    # Derive editable clothing surfaces from the artist's component/material bindings.
    # Materials shared with the head (skin, hair, eyes) retain the original look.
    head_materials = component_materials(gltf, asset["slots"]["head_hair"])
    garment_materials = set().union(
        *(
            component_materials(gltf, node)
            for slot, node in asset["slots"].items()
            if slot != "head_hair"
        )
    )
    item["variationSlots"] = sorted(
        slot
        for slot, spec in descriptor["materialSlots"].items()
        if set(spec["materials"]) <= garment_materials - head_materials
    )
    item["creator"] = "Quaternius"
    item["license"] = "CC0"
    # The first-person camera is presentation framing. An unmeasured eye position is not
    # turned into a measured body trait or used to change the canonical traversal camera.
    eye = asset["first_person_reference"]["eye_center_model_metres"] or [
        0,
        asset["frame"]["height_metres"] * 0.91,
        0.20,
    ]
    item["gesture"] = {
        "file": item["file"],
        "descriptor": {
            "character": descriptor,
            "clip": asset["clips"]["interact"]["name"],
            "durationSeconds": asset["clips"]["interact"]["duration_seconds"],
            "eye": eye,
            "hiddenNodes": [asset["slots"][slot] for slot in ["head_hair", "lower", "feet"]],
        },
    }
    return item


def stylized_looks() -> dict:
    manifest_bytes = (SOURCE / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    return {
        "profile": PROFILE,
        "source": {
            "manifest": "quaternius-modular-v2/manifest.json",
            "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
        "looks": [stylized_look(asset) for asset in manifest["assets"]],
    }


def render(document: dict) -> str:
    return json.dumps(document, indent=2) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare the committed list only")
    arguments = parser.parse_args(argv)
    expected = render(stylized_looks())
    if arguments.check:
        current = STYLIZED_LOOKS.read_text() if STYLIZED_LOOKS.is_file() else ""
        if current != expected:
            print(f"{STYLIZED_LOOKS.relative_to(ROOT)} differs from its pinned sources")
            return 1
        print(f"{STYLIZED_LOOKS.relative_to(ROOT)} matches its pinned sources")
        return 0
    STYLIZED_LOOKS.write_text(expected)
    print(f"Wrote {STYLIZED_LOOKS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
