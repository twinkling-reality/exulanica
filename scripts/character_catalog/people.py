"""Prepare the MakeHuman people family: shared bases, part containers, material packs, catalog.

The authored input is ``assets/characters/makehuman-people-v1/definition.json``. Every output is
content-addressed and listed in ``catalog.json`` with its size, digest, licence and source, and
``imports.json`` holds one reviewed-asset import manifest per container.
"""

import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

if __package__:
    from . import packs
    from .glb import accessor_values, read_glb
    from .split import hide_mask_triangles, split_base
else:  # imported with the script directory on sys.path
    import packs
    from glb import accessor_values, read_glb
    from split import hide_mask_triangles, split_base

ROOT = Path(__file__).resolve().parents[2]
CHARACTERS = ROOT / "assets/characters"
FAMILY_ROOT = CHARACTERS / "makehuman-people-v1"
SCRIPTS = Path(__file__).resolve().parent
PREPARATION_SCRIPTS = ["glb.py", "packs.py", "people.py", "people_blender.py", "posture.py", "retarget.py", "split.py"]
PRODUCER = "makehuman-people-prepare/1"
FAMILY_ID = "makehuman-people/v1"
DRAW_DOMAIN = "street-population/v1"
FACE_SLOTS = ("eyes", "brows", "lashes")
MPFB_URL = "https://github.com/makehumancommunity/mpfb2"
SLOT_LABELS = {
    "outfit": "Clothing",
    "shoes": "Shoes",
    "hair": "Hair",
    "brows": "Eyebrows",
    "lashes": "Eyelashes",
    "eyes": "Eyes",
}
#: Posture joints the far form follows, in the order a reader lists them.
POSTURE_JOINTS = (
    "pelvis", "chest", "neck", "head",
    "leftHip", "leftKnee", "leftAnkle", "leftToe", "leftShoulder", "leftElbow", "leftWrist",
    "rightHip", "rightKnee", "rightAnkle", "rightToe", "rightShoulder", "rightElbow", "rightWrist",
)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def load_definition():
    return json.loads((FAMILY_ROOT / "definition.json").read_text())


def key_name(value):
    return value.replace("_", "-").lower()


def wearable_node(wearable):
    return f"{wearable['slot']}.{wearable['source']}"


def base_config(definition, base, source, output, metadata, cache):
    wearables = []
    for wearable in base["wearables"]:
        entry = {
            "id": f"{base['baseId']}/{wearable_node(wearable)}",
            "slot": wearable["slot"],
            "kind": wearable["kind"],
            "source": wearable["source"],
            "node": wearable_node(wearable),
            "material": wearable_node(wearable),
        }
        if "hideBit" in wearable:
            entry["hideBit"] = wearable["hideBit"]
        wearables.append(entry)
    return {
        "mpfb": str(source / "mpfb2"),
        "cache": str(cache),
        "assets": str(source / "system-assets"),
        "animation": str((FAMILY_ROOT / definition["sources"]["motion"]["asset"]).resolve()),
        "base": {"baseId": base["baseId"], "macro": base["macro"]},
        "morphs": definition["morphs"],
        "wearables": wearables,
        "clips": definition["clips"],
        "idleClip": definition["idleClip"],
        "postures": {
            key: {k: v for k, v in spec.items() if k != "label"}
            for key, spec in definition.get("postures", {}).items()
        },
        "occlusion": definition["occlusion"],
        "output": str(output),
        "metadata": str(metadata),
    }


def build_base(definition, base, source, blender, workdir):
    """Run the pinned Blender build for one base and return (glb bytes, metadata)."""
    workdir.mkdir(parents=True, exist_ok=True)
    output = workdir / f"{base['baseId']}.glb"
    metadata = workdir / f"{base['baseId']}.metadata.json"
    config = base_config(definition, base, source, output, metadata, workdir / "mpfb-cache")
    config_path = workdir / f"{base['baseId']}.config.json"
    config_path.write_text(json.dumps(config, indent=1))
    # Reuse a finished build only for identical inputs and identical Blender-side scripts.
    stamp = sha256_bytes(
        json.dumps(
            [
                config,
                # Postures are baked in the order the definition declares them, and the order
                # changes the bytes; the sorted dump of the config would not see it.
                list(config["postures"]),
                sha256_file(SCRIPTS / "people_blender.py"),
                sha256_file(SCRIPTS / "retarget.py"),
                sha256_file(SCRIPTS / "posture.py"),
                sha256_file(blender),
            ],
            sort_keys=True,
        ).encode()
    )
    stamp_path = workdir / f"{base['baseId']}.stamp"
    if output.exists() and metadata.exists() and stamp_path.exists() and stamp_path.read_text() == stamp:
        data = output.read_bytes()
        read_glb(data)
        return data, json.loads(metadata.read_text())
    stamp_path.unlink(missing_ok=True)
    with (workdir / f"{base['baseId']}.build.log").open("w") as stream:
        subprocess.run(
            [
                str(blender),
                "--background",
                "--factory-startup",
                "--python-exit-code",
                "1",
                "--python",
                str(SCRIPTS / "people_blender.py"),
                "--",
                str(config_path),
            ],
            check=True,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=3600,
        )
    data = output.read_bytes()
    read_glb(data)
    stamp_path.write_text(stamp)
    return data, json.loads(metadata.read_text())


def material_jobs(definition, assets):
    """Every material pack the family needs, keyed by material id."""
    settings = definition["materials"]
    repairs = definition["textureRepairs"]
    labels = definition["labels"]
    jobs = {}
    for base in definition["bases"]:
        for index, skin in enumerate(base["skins"], start=1):
            jobs[f"skin/{skin}"] = {
                "kind": "skin",
                "label": f"Skin tone {index}",
                "mhmat": assets / "skins" / skin / f"{skin}.mhmat",
                "settings": settings["skin"],
                "source": f"skins/{skin}",
            }
        for wearable in base["wearables"]:
            kind, name = wearable["kind"], wearable["source"]
            if kind == "eyes":
                continue
            slot_kind = {"clothes": wearable["slot"], "hair": "hair", "eyebrows": "eyebrows", "eyelashes": "eyelashes"}[kind]
            folder = "clothes" if kind == "clothes" else kind
            jobs[f"{wearable['slot']}/{name}"] = {
                "kind": slot_kind,
                "label": labels[name],
                "mhmat": assets / folder / name / f"{name}.mhmat",
                "settings": settings[slot_kind],
                "repairs": repairs.get(name),
                "source": f"{folder}/{name}",
            }
    for colour in definition["eyeColours"]:
        jobs[f"eyeColour/{colour}"] = {
            "kind": "eyes",
            "label": labels[colour],
            "mhmat": assets / "eyes/materials" / f"{colour}.mhmat",
            "settings": settings["eyes"],
            "adjust": definition.get("eyeColourAdjust", {}).get(colour),
            "source": f"eyes/materials/{colour}",
        }
    return jobs


def uv_triangle_mask(part_glb, size, region):
    """Rasterize a part's UV triangles whose centroid lies in ``region`` ('upper'/'lower'/'all')."""
    document, binary = read_glb(part_glb)
    mesh = next(m for m in document["meshes"])
    primitive = mesh["primitives"][0]
    positions = accessor_values(document, binary, primitive["attributes"]["POSITION"])
    uvs = accessor_values(document, binary, primitive["attributes"]["TEXCOORD_0"])
    normalized = document["accessors"][primitive["attributes"]["TEXCOORD_0"]].get("normalized")
    scale = 1 / 65535 if normalized else 1
    indices = accessor_values(document, binary, primitive["indices"])
    heights = positions[1::3]
    top, bottom = max(heights), min(heights)
    split = 0.9 if top > 1.2 else (top + bottom) / 2
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    for t in range(0, len(indices), 3):
        corner = indices[t : t + 3]
        centre = sum(heights[i] for i in corner) / 3
        if region == "upper" and centre < split:
            continue
        if region == "lower" and centre >= split:
            continue
        draw.polygon(
            [(uvs[2 * i] * scale * size, uvs[2 * i + 1] * scale * size) for i in corner],
            fill=255,
        )
    return mask


def far_colours(part_glb, colour_image):
    colours = {}
    for region in ("upper", "lower"):
        mask = uv_triangle_mask(part_glb, 256, region)
        if not mask.getbbox():
            mask = uv_triangle_mask(part_glb, 256, "all")
        colours[region] = packs.average_colour(colour_image, mask)
    return colours


def rest_speed(clip):
    return round(clip["stanceSpeed"] * 1000)


def asset_ref(key, relative, data):
    return {
        "assetKey": key,
        "mediaType": "model/gltf-binary",
        "contentSha256": sha256_bytes(data),
        "byteSize": len(data),
        "file": relative,
    }


def import_manifest(ref, title, summary, licence_sha, source_url, source_revision):
    return {
        "profile": "exulanica.reviewed-asset-import/v1",
        "asset_key": ref["assetKey"],
        "title": title,
        "summary": summary,
        "content_sha256": ref["contentSha256"],
        "byte_size": ref["byteSize"],
        "licence_id": "CC0-1.0",
        "licence_sha256": licence_sha,
        "source_url": source_url,
        "source_revision": source_revision,
        "producer": PRODUCER,
    }


def default_weights(definition, base):
    """Street population weights: everyday clothing most often, formal and work wear less."""
    weights = definition.get("population", {}).get(base["baseId"], {})
    choices = {}
    for wearable in base["wearables"]:
        slot = wearable["slot"]
        part_id = f"{base['baseId']}/{slot}/{wearable['source']}"
        choices.setdefault(slot, {})[part_id] = weights.get(wearable["source"], 10)
    choices["skin"] = {f"skin/{s}": 10 for s in base["skins"]}
    choices["eyeColour"] = {f"eyeColour/{c}": weights.get(c, 10) for c in definition["eyeColours"]}
    if "hair" in choices and weights.get("none", 0):
        choices["hair"]["none"] = weights["none"]
    return choices


def prepare(source, blender, workdir, output=FAMILY_ROOT, inputs=None):
    """Build every output into ``output``; return the catalog family, population and manifests."""
    definition = load_definition()
    assets = source / "system-assets"
    licence = (CHARACTERS / "makehuman-parametric-v1/LICENSE.md").read_bytes()
    licence_sha = sha256_bytes(licence)
    lock = json.loads((CHARACTERS / "makehuman-parametric-v1/source-lock.json").read_text())
    revision = f"mpfb2@{lock['mpfbCommit']};system-assets@{lock['systemAssetsSha256']}"
    output.mkdir(parents=True, exist_ok=True)
    (output / "LICENSE.md").write_bytes(licence)
    manifests = []
    written = {}

    def write(relative, data):
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written[relative] = sha256_bytes(data)

    # Material packs.
    materials = []
    processed = {}
    for material_id, job in sorted(material_jobs(definition, assets).items()):
        name = key_name(material_id.replace("/", "."))
        data, info, image = packs.build_pack(
            name,
            job["kind"],
            job["mhmat"],
            job["settings"],
            job.get("repairs"),
            return_image=True,
            adjust=job.get("adjust"),
        )
        relative = f"materials/{name}.glb"
        write(relative, data)
        ref = asset_ref(f"makehuman.people.material.{name}.v{definition['assetRevisions']['materials']}", f"makehuman-people-v1/{relative}", data)
        processed[material_id] = image
        entry = {
            "materialId": material_id,
            "label": job["label"],
            "kind": job["kind"],
            "asset": ref,
            "roles": info["roles"],
            "alphaMode": info["alphaMode"],
            "doubleSided": info["doubleSided"],
            "roughnessMilli": info["roughnessMilli"],
            "averageColour": info["averageColour"],
            "source": {"title": "MakeHuman system assets", "url": MPFB_URL, "revision": revision, "path": job["source"]},
        }
        if info["alphaCutoffMilli"] is not None:
            entry["alphaCutoffMilli"] = info["alphaCutoffMilli"]
        if info["tint"]:
            entry["tint"] = info["tint"]
        if job["kind"] in definition["occlusion"]["materialKinds"]:
            # Every mesh this material draws carries baked occlusion in its vertex colour.
            entry["vertexOcclusion"] = True
        materials.append(entry)
        manifests.append(import_manifest(ref, f"People material {material_id}", f"CC0 MakeHuman {job['kind']} textures prepared for fitted people.", licence_sha, MPFB_URL, revision))

    bases = []
    choices = {}
    population_parameters = {}
    joints = None
    metadata_all = {}
    for base in definition["bases"]:
        base_id = base["baseId"]
        data, metadata = build_base(definition, base, source, blender, workdir)
        metadata_all[base_id] = metadata
        face_nodes = ["body"] + [wearable_node(w) for w in base["wearables"] if w["slot"] in FACE_SLOTS]
        split = split_base(data, face_nodes)
        base_bytes = split.pop("base")
        write(f"bases/{base_id}.glb", base_bytes)
        revision_tag = f"v{definition['assetRevisions']['containers']}"
        # A base carries every clip, so a new clip is a new base revision and its parts keep theirs.
        base_tag = f"v{definition['assetRevisions'].get('bases', definition['assetRevisions']['containers'])}"
        base_ref = asset_ref(f"makehuman.people.{base_id}.base.{base_tag}", f"makehuman-people-v1/bases/{base_id}.glb", base_bytes)
        manifests.append(import_manifest(base_ref, f"People {base_id} base", "Fitted CC0 MakeHuman body, face and skeleton with Quaternius CC0 locomotion, and seated postures generated by this repository's posture script (scripts/character_catalog/posture.py) under the family's CC0 licence.", licence_sha, MPFB_URL, revision))
        triangles, body_triangles = hide_mask_triangles(base_bytes)
        parts = []
        for wearable in base["wearables"]:
            node = wearable_node(wearable)
            slot, name = wearable["slot"], wearable["source"]
            part_id = f"{base_id}/{slot}/{name}"
            material_id = f"eyeColour/{definition['eyeColours'][0]}" if slot == "eyes" else f"{slot}/{name}"
            node_meta = metadata["nodes"][node]
            part = {
                "partId": part_id,
                "slot": slot,
                "label": definition["labels"][name],
                "node": node,
                "material": material_id,
                "morphTargets": [m["key"] for m in node_meta["morphs"]],
                "triangles": node_meta["triangles"],
                "source": {"title": "MakeHuman system assets", "url": MPFB_URL, "revision": revision, "path": f"{'clothes' if wearable['kind'] == 'clothes' else wearable['kind']}/{name}"},
            }
            if node in split:
                part_bytes = split[node]
                relative = f"parts/{base_id}/{key_name(node)}.glb"
                write(relative, part_bytes)
                part["asset"] = asset_ref(f"makehuman.people.{base_id}.{key_name(node)}.{revision_tag}", f"makehuman-people-v1/{relative}", part_bytes)
                manifests.append(import_manifest(part["asset"], f"People {base_id} {slot} {name}", f"CC0 MakeHuman {slot} fitted to the {base_id} base.", licence_sha, MPFB_URL, revision))
                part["farColours"] = far_colours(part_bytes, processed[material_id])
            else:
                average = next(m["averageColour"] for m in materials if m["materialId"] == material_id)
                part["farColours"] = {"upper": average, "lower": average}
            if "hideBit" in wearable:
                part["hideBit"] = wearable["hideBit"]
                part["hiddenBodyTriangles"] = len(triangles.get(wearable["hideBit"], []))
            if slot == "hair":
                part["tint"] = "hair"
            parts.append(part)
        clips = {}
        for kind, source_name in (("idle", "Idle"), ("walk", "Walk"), ("run", "Run"), ("interact", "Interact"), ("wave", "Wave")):
            clip = metadata["clips"][definition["clips"][source_name]]
            clips[kind] = {
                "name": definition["clips"][source_name],
                "durationMilli": round(clip["durationSeconds"] * 1000),
                "speedMillimetresPerSecond": rest_speed(clip) if kind in ("walk", "run") else 0,
            }
        base_postures = {}
        for key, spec in sorted(definition.get("postures", {}).items()):
            measured = metadata["postures"][key]
            placed = measured["joints"]
            base_postures[key] = {
                "clip": {
                    "name": spec["clip"],
                    "durationMilli": round(measured["durationSeconds"] * 1000),
                    "speedMillimetresPerSecond": 0,
                },
                # How high the lowest point of the seat rests above the ground a standing person
                # stands on, at the base's rest height and the clip's first frame, so a renderer
                # can put that point on a seat.
                "seatMillimetres": round((measured["first"]["seatMetres"] - metadata["idleFloorMetres"]) * 1000),
                # The asset's own frame (Y up, facing +Z), millimetres, at the clip's first frame.
                "jointsMillimetres": {
                    name: [round(placed[name][0] * 1000), round(placed[name][2] * 1000), round(-placed[name][1] * 1000)]
                    for name in POSTURE_JOINTS
                },
            }
        document, _ = read_glb(base_bytes)
        skin_joints = [document["nodes"][j]["name"] for j in document["skins"][0]["joints"]]
        if joints is None:
            joints = skin_joints
        elif joints != skin_joints:
            raise ValueError("bases must share one joint order")
        eye = metadata["eyeCentre"]
        bases.append({
            "baseId": base_id,
            "label": base["label"],
            "asset": base_ref,
            "restHeightMillimetres": round(metadata["restHeightMetres"] * 1000),
            "idleFloorMicrometres": round(metadata["idleFloorMetres"] * 1_000_000),
            "heightMillimetres": base["heightMillimetres"],
            "eyeHeightMillimetres": round(eye[2] * 1000) if eye else round(metadata["restHeightMetres"] * 935),
            "clips": clips,
            "morphTargets": [m["key"] for m in definition["morphs"]],
            "bodyNode": "body",
            "bodyTriangles": body_triangles,
            "farForm": metadata["farWidths"],
            "postures": base_postures,
            "parts": parts,
            "materials": {
                "skin": [f"skin/{s}" for s in base["skins"]],
                "eyeColour": [f"eyeColour/{c}" for c in definition["eyeColours"]],
            },
            "source": {"title": "MakeHuman system assets through MPFB 2", "url": MPFB_URL, "revision": revision},
        })
        choices[base_id] = default_weights(definition, base)
        heights = base["heightMillimetres"]
        spread = definition.get("parameterSpread", {"fullness": [-500, 0, 800], "muscle": [-500, 0, 500]})
        population_parameters[base_id] = {
            "heightMillimetres": {"min": heights["min"], "mode": heights["default"], "max": heights["max"]},
            "fullness": dict(zip(("min", "mode", "max"), spread["fullness"], strict=True)),
            "muscle": dict(zip(("min", "mode", "max"), spread["muscle"], strict=True)),
        }

    studio = definition["studio"]

    def presented(key, entry):
        """A slot or parameter with the studio's declared section, order and wording for it."""
        shown = studio[key]
        return {**entry, **{k: shown[k] for k in ("section", "order", "step", "display", "wording") if k in shown}}

    parameters = [
        presented("heightMillimetres", {"key": "heightMillimetres", "label": "Height", "unit": "mm", "min": min(b["heightMillimetres"]["min"] for b in definition["bases"]), "max": max(b["heightMillimetres"]["max"] for b in definition["bases"])}),
        presented("fullness", {"key": "fullness", "label": definition["parameters"]["fullness"]["label"], "unit": "milli", "min": definition["parameters"]["fullness"]["min"], "max": definition["parameters"]["fullness"]["max"], "negative": "fullness-down", "positive": "fullness-up"}),
        presented("muscle", {"key": "muscle", "label": definition["parameters"]["muscle"]["label"], "unit": "milli", "min": definition["parameters"]["muscle"]["min"], "max": definition["parameters"]["muscle"]["max"], "negative": "muscle-down", "positive": "muscle-up"}),
    ]
    slots = [presented(s, {"slot": s, "label": SLOT_LABELS[s], "kind": "part", "optional": s == "hair"}) for s in ("outfit", "shoes", "hair", "brows", "lashes", "eyes")]
    slots += [
        presented("skin", {"slot": "skin", "label": "Skin", "kind": "material", "optional": False, "appliesTo": "body"}),
        presented("eyeColour", {"slot": "eyeColour", "label": "Eye colour", "kind": "material", "optional": False, "appliesTo": "eyes"}),
        presented("hairColour", {"slot": "hairColour", "label": "Hair colour", "kind": "colour", "optional": False, "appliesTo": "hair"}),
    ]
    family = {
        "familyId": FAMILY_ID,
        "label": definition["label"],
        "summary": definition["summary"],
        "kind": "layered-people",
        "rigId": "makehuman-mixamo-unity/v1",
        "joints": joints,
        "licence": {"id": "CC0-1.0", "file": "makehuman-people-v1/LICENSE.md", "sha256": licence_sha},
        "slots": slots,
        "parameters": parameters,
        "colours": {"hairColour": definition["hairColours"]},
        "bases": bases,
        "materials": materials,
        "postures": [
            {"key": key, "label": spec["label"]} for key, spec in sorted(definition.get("postures", {}).items())
        ],
        "activityPostures": dict(sorted(definition.get("activityPostures", {}).items())),
        "seatPostures": dict(sorted(definition.get("seatPostures", {}).get("activities", {}).items())),
    }
    population = {
        "domain": DRAW_DOMAIN,
        "familyId": FAMILY_ID,
        "bases": {b["baseId"]: definition.get("baseWeights", {}).get(b["baseId"], 10) for b in definition["bases"]},
        "choices": choices,
        "colours": {"hairColour": {c["key"]: definition.get("hairColourWeights", {}).get(c["key"], 10) for c in definition["hairColours"]}},
        "parameters": population_parameters,
    }
    (output / "imports.json").write_text(json.dumps(manifests, indent=1, sort_keys=True) + "\n")
    receipt = {
        "profile": "exulanica.character-preparation-receipt/v1",
        "producer": PRODUCER,
        "definitionSha256": sha256_file(FAMILY_ROOT / "definition.json"),
        "inputs": inputs,
        "scripts": {name: sha256_file(SCRIPTS / name) for name in PREPARATION_SCRIPTS},
        "outputs": dict(sorted(written.items())),
        "measurements": {
            base_id: {
                "restHeightMetres": m["restHeightMetres"],
                "jointMotionMetres": m["jointMotionMetres"],
                "bodyHiddenVertexCounts": m["bodyHiddenVertexCounts"],
                "clipStanceSamples": {k: v["stanceSpeedSamples"] for k, v in m["clips"].items()},
                "postures": {
                    key: {k: v for k, v in posture.items() if k != "joints"}
                    for key, posture in m.get("postures", {}).items()
                },
                "occlusion": m.get("occlusion", {}),
                "farWidths": m.get("farWidths", {}),
            }
            for base_id, m in metadata_all.items()
        },
    }
    (output / "preparation-receipt.json").write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n")
    return family, population, manifests
