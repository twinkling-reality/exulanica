"""Executed boundaries for the independent, explicitly consented dataset profile."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.consent.training import TrainingReceipt, TrainingTerms
from exulanica.world_package.dataset import DATASET_PROFILE_VERSION, write_dataset_package
from exulanica.world_package.package import PackageError, verify_package
from PIL import Image

NOW = dt.datetime(2026, 9, 8, 12, tzinfo=dt.UTC)


def specimen():
    terms = TrainingTerms(
        "package",
        "licensee",
        ("world-model",),
        NOW - dt.timedelta(days=1),
        NOW + dt.timedelta(days=1),
        "a" * 64,
    )
    owner = TrainingReceipt(
        "package-owner", terms, "granted", "owner", 0, NOW - dt.timedelta(hours=1)
    )
    person = TrainingReceipt("person", terms, "granted", "person", 0, NOW - dt.timedelta(hours=1))
    stream = io.BytesIO()
    Image.new("RGB", (3, 3), (80, 120, 160)).save(stream, format="PNG")
    data = stream.getvalue()
    material = {
        "material_id": "capture-1",
        "capture_id": "capture-1",
        "assets": [
            {
                "path": "assets/capture.png",
                "role": "source_image",
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ],
        "people": [{"subject_id": "person", "masked": False}],
        "screening": {"decision": "approved", "receipt_sha256": "b" * 64},
        "camera": {"fixture": "scripted camera"},
        "calibration": {"fixture": "scripted calibration"},
        "metadata": {"fixture": "synthetic test image, not a retained capture"},
        "split": "held_out",
        "provenance": {"fixture": "synthetic test only"},
        "rung": "scripted test fixture",
    }
    return {
        "files": {"assets/capture.png": data},
        "materials": [material],
        "terms": terms,
        "receipts": [owner, person],
        "exported_at": NOW,
        "private_key": Ed25519PrivateKey.generate(),
        "owner_opt_in": True,
    }


def test_training_export_refuses_unconsented_unmasked_person(tmp_path):
    request = specimen()
    request["receipts"] = request["receipts"][:1]
    with pytest.raises(
        PackageError,
        match="person person in material capture-1 lacks training-use consent and is not masked",
    ):
        write_dataset_package(tmp_path / "refused", **request)
    assert not (tmp_path / "refused").exists()


def test_training_export_requires_opt_in_even_without_people(tmp_path):
    request = specimen()
    request["materials"][0]["people"] = []
    request.pop("owner_opt_in")
    with pytest.raises(PackageError, match="explicit package-owner opt-in"):
        write_dataset_package(tmp_path / "refused", **request)
    request["owner_opt_in"] = True
    request["receipts"] = []
    with pytest.raises(PackageError, match="immutable package-owner grant"):
        write_dataset_package(tmp_path / "refused", **request)


def test_licensee_verifies_training_export_without_database_in_clean_process(tmp_path):
    output = tmp_path / "dataset"
    report = write_dataset_package(output, **specimen())
    assert report.profile_version == DATASET_PROFILE_VERSION
    env = {key: value for key, value in os.environ.items() if not key.startswith("EXULANICA_")}
    source = Path(__file__).resolve().parents[1]
    code = """import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from exulanica.world_package.package import verify_package
assert 'exulanica.db' not in sys.modules
print(verify_package(Path(sys.argv[2])).profile_version)
assert 'exulanica.db' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(source), str(output)],
        env=env,
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == DATASET_PROFILE_VERSION


def test_revocation_blocks_retained_material_and_changes_next_root_with_named_removal(tmp_path):
    request = specimen()
    before = write_dataset_package(tmp_path / "before", **request)
    request["receipts"].append(
        TrainingReceipt("person", request["terms"], "revoked", "person", 1, NOW)
    )
    with pytest.raises(PackageError, match="lacks training-use consent"):
        write_dataset_package(tmp_path / "blocked", **request)
    request.update(
        files={},
        materials=[],
        parent_root=before.merkle_root_sha256,
        removed_material_ids=["capture-1"],
    )
    after = write_dataset_package(tmp_path / "after", **request)
    assert after.merkle_root_sha256 != before.merkle_root_sha256
    provenance = json.loads((tmp_path / "after/provenance/dataset.json").read_text())
    assert provenance["removed_material_ids"] == ["capture-1"]
    assert provenance["parent_root"] == before.merkle_root_sha256
    assert verify_package(tmp_path / "before") == before


def test_masked_flag_cannot_carry_unconsented_original(tmp_path):
    request = specimen()
    request["receipts"] = request["receipts"][:1]
    request["materials"][0]["people"][0].update(masked=True, mask_receipt_sha256="c" * 64)
    with pytest.raises(PackageError, match="without source images"):
        write_dataset_package(tmp_path / "refused", **request)


def test_uninventoried_asset_or_disguised_executable_is_refused(tmp_path):
    request = specimen()
    request["files"]["assets/extra.png"] = request["files"]["assets/capture.png"]
    with pytest.raises(PackageError, match="unreferenced"):
        write_dataset_package(tmp_path / "refused", **request)
    request = specimen()
    request["files"]["assets/capture.png"] = b"<script>secret</script>"
    with pytest.raises(PackageError, match="invalid dataset image"):
        write_dataset_package(tmp_path / "refused", **request)


def test_path_traversal_is_rejected_before_writing_any_asset(tmp_path):
    request = specimen()
    request["files"]["assets/../../escaped.png"] = request["files"].pop("assets/capture.png")
    request["materials"][0]["assets"][0]["path"] = "assets/../../escaped.png"
    with pytest.raises(PackageError, match="invalid dataset asset path"):
        write_dataset_package(tmp_path / "refused", **request)
    assert not (tmp_path / "escaped.png").exists()


@pytest.mark.parametrize("kind", ["png-text", "trailer"])
def test_image_metadata_and_hidden_trailing_content_are_excluded(tmp_path, kind):
    from PIL.PngImagePlugin import PngInfo

    request = specimen()
    if kind == "trailer":
        data = request["files"]["assets/capture.png"] + b"credential=private"
    else:
        stream = io.BytesIO()
        metadata = PngInfo()
        metadata.add_text("description", "credential=private")
        Image.new("RGB", (3, 3)).save(stream, format="PNG", pnginfo=metadata)
        data = stream.getvalue()
    request["files"]["assets/capture.png"] = data
    request["materials"][0]["assets"][0]["sha256"] = hashlib.sha256(data).hexdigest()
    with pytest.raises(PackageError, match="invalid dataset image"):
        write_dataset_package(tmp_path / "refused", **request)


def test_native_pose_receipt_bytes_remain_exact_in_signed_inventory(tmp_path):
    request = specimen()
    path = "assets/pose.json"
    pose = b'{"profile":"exulanica.colmap-pose-receipt/v2","quality":{"measured":0.125}}\n'
    request["files"][path] = pose
    request["materials"][0]["assets"].append(
        {"path": path, "role": "sparse_geometry", "sha256": hashlib.sha256(pose).hexdigest()}
    )
    write_dataset_package(tmp_path / "package", **request)
    assert (tmp_path / "package" / path).read_bytes() == pose
    verify_package(tmp_path / "package")


def sog_fixture(*, extra=False):
    import zipfile

    stream = io.BytesIO()
    Image.new("RGBA", (1, 1), (0, 0, 0, 255)).save(stream, format="WEBP", lossless=True)
    texture = stream.getvalue()
    metadata = {"version": 2, "count": 1}
    names = []
    for key, count in (("means", 2), ("scales", 1), ("quats", 1), ("sh0", 1)):
        metadata[key] = {"files": [f"{key}_{index}.webp" for index in range(count)]}
        names.extend(metadata[key]["files"])
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        output.writestr("meta.json", json.dumps(metadata))
        for name in names:
            output.writestr(name, texture)
        if extra:
            output.writestr("secret.json", '{"credential":"private"}')
    return archive.getvalue()


def test_sog_geometry_is_self_contained_and_rejects_unreferenced_members(tmp_path):
    request = specimen()
    path = "assets/scene.sog"
    for extra in (False, True):
        data = sog_fixture(extra=extra)
        request["files"][path] = data
        asset = {
            "path": path,
            "role": "trained_geometry",
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        request["materials"][0]["assets"] = [*request["materials"][0]["assets"][:1], asset]
        if extra:
            with pytest.raises(PackageError, match="invalid self-contained SOG"):
                write_dataset_package(tmp_path / "refused", **request)
        else:
            write_dataset_package(tmp_path / "accepted", **request)
            verify_package(tmp_path / "accepted")


def test_training_crate_covers_every_payload_and_rejects_resigned_omissions(tmp_path):
    from exulanica.world_package.package import (
        MANIFEST_PATH,
        SIGNATURE_PATH,
        build_manifest,
        canonical_file,
        sign_manifest,
    )

    request = specimen()
    output = tmp_path / "package"
    write_dataset_package(output, **request)
    crate_path = output / "ro-crate-metadata.json"
    crate = json.loads(crate_path.read_bytes())
    root = next(node for node in crate["@graph"] if node["@id"] == "./")
    assert {item["@id"] for item in root["hasPart"]} == {
        "assets/capture.png",
        "wmp/profile.json",
        "dataset/materials.json",
        "consent/training.json",
        "provenance/dataset.json",
    }
    root["hasPart"] = [item for item in root["hasPart"] if item["@id"] != "assets/capture.png"]
    crate_path.write_bytes(canonical_file(crate))
    files = {
        str(path.relative_to(output)): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file() and str(path.relative_to(output)) not in {MANIFEST_PATH, SIGNATURE_PATH}
    }
    manifest_bytes = canonical_file(build_manifest(files, profile_version=DATASET_PROFILE_VERSION))
    (output / MANIFEST_PATH).write_bytes(manifest_bytes)
    (output / SIGNATURE_PATH).write_bytes(
        canonical_file(sign_manifest(manifest_bytes, request["private_key"]))
    )
    with pytest.raises(PackageError, match="RO-Crate"):
        verify_package(output)
