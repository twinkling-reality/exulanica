"""Copy pinned, licensed character examples into the disposable development preview."""

from pathlib import Path
import hashlib
import json
import shutil
import struct

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/characters/quaternius-modular-v2"
OUTPUT = ROOT / "web/packages/app/public/fixtures/characters"


def component_materials(document, node_name):
    node = next(node for node in document["nodes"] if node.get("name") == node_name)
    return {
        document["materials"][part["material"]]["name"]
        for part in document["meshes"][node["mesh"]]["primitives"]
    }


def prepare() -> None:
    manifest = json.loads((SOURCE / "manifest.json").read_text())
    catalog = []
    OUTPUT.mkdir(parents=True, exist_ok=True)
    names = {
        "hoodie": "Hoodie",
        "casual": "Everyday",
        "casual-f": "Relaxed",
        "formal-f": "Tailored",
    }
    for asset in manifest["assets"]:
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
            "forwardYawDegrees": 180,
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
                return round(
                    255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)
                )

            return "#" + "".join(f"{channel(v):02x}" for v in values[:3])

        colors = {
            m["name"]: hex_color(
                m.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
            )
            for m in gltf["materials"]
        }
        item["label"] = names.get(item["lookId"], item["lookId"])
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
        catalog.append(item)
        shutil.copy2(path, OUTPUT / path.name)
    parametric = ROOT / "assets/characters/makehuman-parametric-v1"
    if (parametric / "default.look.json").is_file():
        editable = json.loads((parametric / "default.look.json").read_text())
        body = (parametric / editable["file"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != editable["descriptor"]["asset"]["contentSha256"]:
            raise ValueError("Editable human digest mismatch")
        shutil.copy2(parametric / editable["file"], OUTPUT / editable["file"])
        catalog.insert(0, editable)
    (OUTPUT / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"Prepared verified character preview at {OUTPUT}")


if __name__ == "__main__":
    prepare()
