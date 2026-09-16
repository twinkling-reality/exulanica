#!/usr/bin/env python3
"""Corrected complete artist characters; v1 omitted source Mirror modifiers and is rejected here."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import runpy
import subprocess
import tempfile

from exulanica.env import resolve_briefs_path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/characters/quaternius-modular-v2"
OUTPUT = ROOT / "assets/characters/quaternius-modular-v2"
TOOLS = runpy.run_path(str(ROOT / "scripts/character_assets/validation.py"))
digest, canonical = TOOLS["digest"], TOOLS["canonical"]


def inspect_complete(data):
    audit = TOOLS["inspect_gestures"](data)
    doc, binary = TOOLS["read_glb"](data)
    joints = [doc["nodes"][j]["name"] for j in doc["skins"][0]["joints"]]
    parts = []
    for node in doc["nodes"]:
        if "mesh" not in node:
            continue
        xs = []
        influence = {"negative_L": 0.0, "negative_R": 0.0, "positive_L": 0.0, "positive_R": 0.0}
        triangle_sides = {"negative": 0, "positive": 0}
        for primitive in doc["meshes"][node["mesh"]]["primitives"]:
            attrs = primitive["attributes"]
            points, weights, joint_indices = (
                TOOLS["accessor"](doc, binary, attrs[k])
                for k in ("POSITION", "WEIGHTS_0", "JOINTS_0")
            )
            xs.extend(p[0] for p in points)
            for point, vertex_weights, vertex_joints in zip(
                points, weights, joint_indices, strict=True
            ):
                if abs(point[0]) <= 0.02:
                    continue
                side = "positive" if point[0] > 0 else "negative"
                for weight, index in zip(vertex_weights, vertex_joints, strict=True):
                    name = joints[index]
                    if name.endswith(".L"):
                        influence[side + "_L"] += weight
                    elif name.endswith(".R"):
                        influence[side + "_R"] += weight
            indices = TOOLS["accessor"](doc, binary, primitive["indices"])
            for i in range(0, len(indices), 3):
                center_x = sum(points[indices[i + j][0]][0] for j in range(3)) / 3
                if center_x < -0.02:
                    triangle_sides["negative"] += 1
                elif center_x > 0.02:
                    triangle_sides["positive"] += 1
        if not min(xs) < -0.05 < 0.05 < max(xs) or min(triangle_sides.values()) < 30:
            raise ValueError("Incomplete bilateral geometry: " + node["name"])
        if not node["name"].endswith("_Head") and (
            influence["negative_R"] <= influence["negative_L"]
            or influence["positive_L"] <= influence["positive_R"]
        ):
            raise ValueError("Mirrored limb skin groups missing or reversed: " + node["name"])
        parts.append(
            {
                "node": node["name"],
                "x_extent_metres": [min(xs), max(xs)],
                "triangle_sides": triangle_sides,
                "limb_weight_sums": influence,
            }
        )
    audit["bilateral_geometry"] = parts
    return audit


def import_document(look_id, source, audit):
    return {
        "profile": "exulanica.reviewed-asset-import/v1",
        "asset_key": "quaternius.modular." + look_id + ".v2",
        "title": "Quaternius " + look_id + ", complete geometry v2",
        "summary": "Corrected CC0 skinned artist character with complete mirrored body and original locomotion, reach and wave.",
        "content_sha256": audit["content_sha256"],
        "byte_size": audit["byte_size"],
        "licence_id": "CC0-1.0",
        "licence_sha256": source["license_sha256"],
        "source_url": source["page_url"],
        "source_revision": "sha256:" + source["sha256"],
        "producer": "quaternius-modular-prepare/2",
    }


def prepare(blender, source_dir, output_dir):
    if output_dir.resolve() in (
        (ROOT / "assets/characters/quaternius-modular-v1").resolve(),
        (ROOT / "assets/characters/quaternius-modular-gestures-v1").resolve(),
    ):
        raise ValueError("Corrected revision must not overwrite frozen v1 bytes")
    lock_bytes = (SOURCE / "source-lock.json").read_bytes()
    lock = json.loads(lock_bytes)
    sources = {s["source_id"]: s for s in lock["sources"]}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "source-lock.json").write_bytes(lock_bytes)
    for source in sources.values():
        TOOLS["fetch_pinned"](source, source_dir)
        licence = (SOURCE / source["license_file"]).read_bytes()
        if digest(licence) != source["license_sha256"]:
            raise ValueError("Source licence drift")
        (output_dir / source["license_file"]).write_bytes(licence)
    evidence_bytes = (SOURCE / "source-page-evidence.json").read_bytes()
    evidence = json.loads(evidence_bytes)
    (output_dir / "source-page-evidence.json").write_bytes(evidence_bytes)
    for page in evidence["pages"]:
        payload = (SOURCE / page["file"]).read_bytes()
        if digest(payload) != page["sha256"]:
            raise ValueError("Source page evidence drift")
        (output_dir / page["file"]).write_bytes(payload)
    scripts = [
        Path(__file__),
        ROOT / "scripts/character_assets/blender_prepare_v2.py",
        ROOT / "scripts/character_assets/blender_prepare_gestures_v2.py",
        ROOT / "scripts/character_assets/validation.py",
    ]
    manifest = {
        "profile": "exulanica.character-asset-bundle/v2",
        "producer": "quaternius-modular-prepare/2",
        "supersedes": ["quaternius-modular-v1", "quaternius-modular-gestures-v1"],
        "correction": "Realize source Mirror modifiers and .L/.R skin groups before subdivision; v1 exported incomplete body halves.",
        "status": "complete-geometry-candidate-pending-native-visual-review",
        "source_lock_sha256": digest(lock_bytes),
        "source_page_evidence_sha256": digest(evidence_bytes),
        "preparation_scripts": {p.name: digest(p.read_bytes()) for p in scripts},
        "assets": [],
    }
    for look in lock["looks"]:
        look = deepcopy(look)
        look["actions"].update({"interact": "Interact", "wave": "Wave"})
        source = sources[look["source_id"]]
        stem = look["look_id"]
        glb = (output_dir / (stem + ".glb")).resolve()
        with tempfile.TemporaryDirectory(prefix="complete-character-") as temporary:
            temporary = Path(temporary)
            metadata = temporary / "metadata.json"
            config = {
                "blender_version": lock["blender_version"],
                "look": look,
                "source": str((source_dir / source["filename"]).resolve()),
                "origin_translation_z_metres": source["origin_translation_z_metres"],
                "output": str(glb),
                "metadata": str(metadata),
            }
            path = temporary / "config.json"
            path.write_text(json.dumps(config))
            subprocess.run(
                [
                    str(blender),
                    "-b",
                    "--disable-autoexec",
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(ROOT / "scripts/character_assets/blender_prepare_gestures_v2.py"),
                    "--",
                    str(path),
                ],
                check=True,
            )
            item = json.loads(metadata.read_text())
        audit = inspect_complete(glb.read_bytes())
        item.update(
            file=glb.name,
            audit=audit,
            source_sha256=source["sha256"],
            license_file=source["license_file"],
            license_sha256=source["license_sha256"],
        )
        item["rig_profile"] = (
            "quaternius-modular/" + source["source_id"] + "/" + audit["rig_sha256"]
        )
        item["material_slots"] = {
            m["name"]: {
                "material_name": m["name"],
                "parameter": "baseColorFactor",
                "range": [0, 1],
                "source_default": m["base_color_factor"],
            }
            for m in audit["materials"]
        }
        imported = import_document(stem, source, audit)
        (output_dir / (stem + ".import.json")).write_text(json.dumps(imported, indent=2) + "\n")
        manifest["assets"].append(item)
    manifest["document_sha256"] = digest(canonical(manifest))
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def verify(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    expected = manifest.pop("document_sha256")
    if digest(canonical(manifest)) != expected:
        raise ValueError("Manifest digest mismatch")
    lock_bytes = (directory / "source-lock.json").read_bytes()
    if digest(lock_bytes) != manifest["source_lock_sha256"]:
        raise ValueError("Source lock digest mismatch")
    sources = {s["source_id"]: s for s in json.loads(lock_bytes)["sources"]}
    evidence_bytes = (directory / "source-page-evidence.json").read_bytes()
    if digest(evidence_bytes) != manifest["source_page_evidence_sha256"]:
        raise ValueError("Source page evidence digest mismatch")
    for page in json.loads(evidence_bytes)["pages"]:
        if digest((directory / page["file"]).read_bytes()) != page["sha256"]:
            raise ValueError("Source page digest mismatch")
    for item in manifest["assets"]:
        source = sources[item["source_id"]]
        if item["source_sha256"] != source["sha256"]:
            raise ValueError("Source pin mismatch")
        if (
            item["license_file"] != source["license_file"]
            or item["license_sha256"] != source["license_sha256"]
            or digest((directory / item["license_file"]).read_bytes()) != source["license_sha256"]
        ):
            raise ValueError("Source licence digest mismatch")
        imported = json.loads((directory / (item["look_id"] + ".import.json")).read_text())
        if imported != import_document(item["look_id"], source, item["audit"]):
            raise ValueError("Import document mismatch")
        if inspect_complete((directory / item["file"]).read_bytes()) != item["audit"]:
            raise ValueError("Asset or audit changed")
    print("Verified complete bilateral geometry, mirrored skin groups and original clips.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", type=Path)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=resolve_briefs_path("character-preparation", "source", root=ROOT),
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify(args.output_dir)
    elif args.blender:
        prepare(args.blender.resolve(), args.source_dir, args.output_dir)
        verify(args.output_dir)
    else:
        parser.error("--blender or --verify-only required")


if __name__ == "__main__":
    main()
