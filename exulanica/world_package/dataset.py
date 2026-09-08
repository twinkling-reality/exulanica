"""Explicit training profile, with an offline, fail-closed consent boundary.

A signature authenticates declarations and bytes, not the truth of a screening or masking
claim. The database projection is responsible for grounding those claims in retained receipts.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import shutil
import struct
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from exulanica.consent.training import TrainingReceipt, TrainingTerms, training_is_granted
from exulanica.corpus.decode import UNREADABLE, open_sensor
from exulanica.world_package.package import (
    MANIFEST_PATH,
    SIGNATURE_PATH,
    PackageError,
    VerificationReport,
    build_manifest,
    canonical_file,
    scan_payload,
    sign_manifest,
    verify_package,
)

DATASET_PROFILE_VERSION = "exulanica-wmp-training-1.1"
DATASET_PROFILE_ID = "https://exulanica.local/profiles/world-memory-package/training/1.1"
DATASET_REQUIRED_PATHS = frozenset(
    {
        "wmp/profile.json",
        "ro-crate-metadata.json",
        "dataset/materials.json",
        "consent/training.json",
        "provenance/dataset.json",
    }
)
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ROLES = {
    "source_image",
    "masked_image",
    "sparse_geometry",
    "trained_geometry",
    "provenance_receipt",
}


def _digest(value: Any) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def scan_dataset_asset(path: str, data: bytes) -> None:
    """Allow only decoded images, structural PLY, or scanned canonical JSON geometry."""
    relative = Path(path)
    if not path.startswith("assets/") or ".." in relative.parts or relative.is_absolute():
        raise PackageError(f"{path}: invalid dataset asset path")
    # Preserve directory and secret exclusions while making the format allowance explicit.
    scan_payload(str(relative.with_suffix(".bin")), None)
    suffix = relative.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        try:
            with open_sensor(data) as decoded:
                expected = "PNG" if suffix == ".png" else "JPEG"
                if decoded.format != expected:
                    raise ValueError("image suffix disagrees with decoder")
                if any(
                    key.lower() in {"exif", "xmp", "comment", "description", "xml:com.adobe.xmp"}
                    for key in decoded.info
                ):
                    raise ValueError("image metadata is excluded")
            _image_envelope(path, data, expected)
        except Exception as error:
            raise PackageError(f"{path}: invalid dataset image") from error
    elif suffix == ".json":
        try:
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("geometry receipt must be an object")
            if (
                value.get("profile")
                not in {"exulanica.colmap-pose-receipt/v2", "exulanica.scene-splat-publication/v1"}
                and canonical_file(value) != data
            ):
                raise ValueError("noncanonical JSON")
            scan_payload(path, value)
        except (ValueError, TypeError) as error:
            raise PackageError(f"{path}: invalid geometry JSON") from error
    elif suffix == ".sog":
        _validate_sog(path, data)
    elif suffix == ".ply":
        _validate_ply(path, data)
    else:
        raise PackageError(f"{path}: undeclared dataset format")


def _image_envelope(path: str, data: bytes, kind: str) -> None:
    if kind == "PNG":
        offset = 8
        while offset < len(data):
            if offset + 12 > len(data):
                raise ValueError("truncated PNG")
            size = int.from_bytes(data[offset : offset + 4], "big")
            tag = data[offset + 4 : offset + 8]
            if tag in {b"tEXt", b"zTXt", b"iTXt", b"eXIf"}:
                raise ValueError("PNG metadata is excluded")
            offset += size + 12
            if tag == b"IEND":
                if offset != len(data) or size != 0:
                    raise ValueError("trailing PNG content")
                return
        raise ValueError("PNG has no end marker")
    if kind == "WEBP":
        if (
            data[:4] != b"RIFF"
            or data[8:12] != b"WEBP"
            or int.from_bytes(data[4:8], "little") + 8 != len(data)
        ):
            raise ValueError("invalid WebP envelope")
        offset = 12
        while offset < len(data):
            size = int.from_bytes(data[offset + 4 : offset + 8], "little")
            if data[offset : offset + 4] in {b"EXIF", b"XMP "}:
                raise ValueError("WebP metadata is excluded")
            offset += 8 + size + size % 2
        if offset != len(data):
            raise ValueError("invalid WebP chunk boundary")
        return
    # Parse markers including stuffed entropy bytes, so an earlier EOI cannot hide a trailer.
    offset = 2
    while offset < len(data):
        if data[offset] != 255:
            offset += 1
            continue
        offset += 1
        while offset < len(data) and data[offset] == 255:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker == 217:
            if offset != len(data):
                raise ValueError("trailing JPEG content")
            return
        if marker == 0 or 208 <= marker <= 215:
            continue
        if marker == 254 or 225 <= marker <= 239:
            raise ValueError("JPEG metadata is excluded")
        if offset + 2 > len(data):
            break
        size = int.from_bytes(data[offset : offset + 2], "big")
        if size < 2:
            break
        offset += size
    raise ValueError(f"{path}: missing image end marker")


def _validate_sog(path: str, data: bytes) -> None:
    # Mirrors the existing renderer's self-contained SOG v2 boundary, with decoded textures
    # and prohibited-field scanning added for a distributable training package.
    try:
        if (
            len(data) < 22
            or data[-22:-18] != b"PK\x05\x06"
            or data[-2:] != b"\0\0"
            or not data.startswith(b"PK\x03\x04")
        ):
            raise ValueError("incomplete SOG archive")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if not 1 <= len(entries) <= 32 or archive.comment:
                raise ValueError("SOG member limit")
            names = [entry.filename for entry in entries]
            if len(set(names)) != len(names):
                raise ValueError("duplicate SOG members")
            contents = {}
            expected_offset = 0
            for entry in entries:
                if (
                    not re.fullmatch(r"[A-Za-z0-9_-]+\.(json|webp)", entry.filename)
                    or entry.compress_type != zipfile.ZIP_STORED
                    or entry.flag_bits & ~0x0808
                    or entry.extra
                    or entry.comment
                    or entry.file_size != entry.compress_size
                ):
                    raise ValueError("unsupported SOG member")
                if entry.header_offset != expected_offset:
                    raise ValueError("unreferenced bytes between SOG members")
                header = data[entry.header_offset : entry.header_offset + 30]
                if len(header) != 30 or header[:4] != b"PK\x03\x04":
                    raise ValueError("invalid SOG local header")
                name_size, extra_size = struct.unpack_from("<HH", header, 26)
                if extra_size:
                    raise ValueError("SOG local extra data is excluded")
                expected_offset += 30 + name_size + entry.file_size
                if entry.flag_bits & 8:
                    descriptor = data[expected_offset : expected_offset + 16]
                    if len(descriptor) != 16 or struct.unpack("<4sIII", descriptor) != (
                        b"PK\x07\x08",
                        entry.CRC,
                        entry.file_size,
                        entry.file_size,
                    ):
                        raise ValueError("invalid SOG streamed descriptor")
                    expected_offset += 16
                contents[entry.filename] = archive.read(entry)
            if expected_offset != archive.start_dir:
                raise ValueError("unreferenced SOG bytes before directory")
            if "meta.json" not in contents or len(contents["meta.json"]) > 1_000_000:
                raise ValueError("missing SOG metadata")
            meta = json.loads(contents["meta.json"])
            scan_payload("geometry/meta.json", meta)
            if meta.get("version") != 2 or type(meta.get("count")) is not int or meta["count"] <= 0:
                raise ValueError("unsupported SOG metadata")
            referenced = {"meta.json"}
            for key, count in (("means", 2), ("scales", 1), ("quats", 1), ("sh0", 1), ("shN", 2)):
                if key == "shN" and key not in meta:
                    continue
                textures = meta[key]["files"]
                if not isinstance(textures, list) or len(textures) != count:
                    raise ValueError("missing SOG textures")
                for name in textures:
                    if (
                        not isinstance(name, str)
                        or not name.endswith(".webp")
                        or name not in contents
                    ):
                        raise ValueError("external SOG texture")
                    referenced.add(name)
                    _image_envelope(name, contents[name], "WEBP")
                    with open_sensor(contents[name]) as texture:
                        if texture.format != "WEBP":
                            raise ValueError("invalid SOG texture")
            if referenced != set(contents):
                raise ValueError("unreferenced SOG members")
    except (*UNREADABLE, KeyError, TypeError, zipfile.BadZipFile) as error:
        raise PackageError(f"{path}: invalid self-contained SOG geometry") from error


def _validate_ply(path: str, data: bytes) -> None:
    # PLY is a data format: restrict it to vertex scalar arrays and exact payload length.
    # Reject comments, arbitrary elements and list properties rather than treating a header
    # as proof that the remaining bytes are geometry.
    try:
        header, payload = data.split(b"end_header\n", 1)
        lines = header.decode("ascii").splitlines()
        if lines[:2] not in (
            ["ply", "format binary_little_endian 1.0"],
            ["ply", "format ascii 1.0"],
        ):
            raise ValueError("unsupported PLY format")
        if len(lines) < 4 or not lines[2].startswith("element vertex "):
            raise ValueError("vertex-only geometry required")
        count = int(lines[2].split()[-1])
        if count < 0:
            raise ValueError("negative vertex count")
        sizes = {"float": 4, "float32": 4, "double": 8, "float64": 8, "uchar": 1, "uint8": 1}
        properties = [line.split() for line in lines[3:]]
        if not properties or any(
            len(parts) != 3
            or parts[0] != "property"
            or parts[1] not in sizes
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", parts[2])
            for parts in properties
        ):
            raise ValueError("unsupported PLY properties")
        if not {"x", "y", "z"}.issubset({parts[2] for parts in properties}):
            raise ValueError("geometry has no coordinates")
        if "binary" in lines[1]:
            if len(payload) != count * sum(sizes[parts[1]] for parts in properties):
                raise ValueError("geometry payload size mismatch")
        else:
            rows = payload.decode("ascii").splitlines()
            if len(rows) != count or any(len(row.split()) != len(properties) for row in rows):
                raise ValueError("geometry row count mismatch")
            from decimal import Decimal

            if any(not Decimal(value).is_finite() for row in rows for value in row.split()):
                raise ValueError("nonfinite geometry")
    except (ValueError, UnicodeError, ArithmeticError) as error:
        raise PackageError(f"{path}: invalid restricted PLY geometry") from error


def _crate_document(
    inventory: Mapping[str, Mapping[str, Any]], terms: TrainingTerms
) -> dict[str, Any]:
    payload_paths = sorted(set(inventory) - {"ro-crate-metadata.json"})
    return {
        "@context": "https://w3id.org/ro/crate/1.2/context",
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "about": {"@id": "./"},
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
            },
            {
                "@id": "./",
                "@type": "Dataset",
                "name": "Explicitly consented Exulanica training dataset",
                "description": "Recorded captures; no simulation or adaptation claim",
                "identifier": terms.package_id,
                "conformsTo": {"@id": DATASET_PROFILE_ID},
                "license": {"@id": "#training-license"},
                "hasPart": [{"@id": path} for path in payload_paths],
            },
            {"@id": DATASET_PROFILE_ID, "@type": ["CreativeWork", "Profile"]},
            {"@id": "#licensee", "@type": "Organization", "name": terms.licensee},
            {
                "@id": "#training-license",
                "@type": "CreativeWork",
                "identifier": terms.terms_sha256,
                "name": "Explicit package training-use terms",
                "subjectOf": {"@id": "consent/training.json"},
                "https://exulanica.local/ns/licensee": {"@id": "#licensee"},
            },
            *[
                {
                    "@id": path,
                    "@type": "File",
                    "contentSize": str(inventory[path]["bytes"]),
                    "sha256": inventory[path]["sha256"],
                }
                for path in payload_paths
            ],
        ],
    }


def validate_dataset(parsed: Mapping[str, Any], inventory: Mapping[str, Mapping[str, Any]]) -> None:
    """Validate every asset and every depicted subject against the signed export instant."""
    try:
        profile = parsed["wmp/profile.json"]
        if (
            profile.get("version") != DATASET_PROFILE_VERSION
            or profile.get("@id") != DATASET_PROFILE_ID
        ):
            raise PackageError("dataset profile identity mismatch")
        consent = parsed["consent/training.json"]
        provenance = parsed["provenance/dataset.json"]
        if consent["owner_opt_in"] is not True:
            raise PackageError("training export requires explicit package-owner opt-in")
        terms = TrainingTerms.from_dict(consent["terms"])
        if parsed["ro-crate-metadata.json"] != _crate_document(inventory, terms):
            raise PackageError("training RO-Crate identity, licence or payload inventory differs")
        receipts = tuple(TrainingReceipt.from_dict(item) for item in consent["receipts"])
        at = dt.datetime.fromisoformat(provenance["exported_at"])
        if not training_is_granted(receipts, subject_id="package-owner", terms=terms, at=at):
            raise PackageError("training export requires an immutable package-owner grant")
        if at.tzinfo is None:
            raise PackageError("dataset export instant requires a timezone")
        if provenance["claim"] != "recorded captures; no simulation or adaptation claim":
            raise PackageError("dataset must declare recorded captures without simulation claims")
        if not terms.valid_from <= at < terms.valid_until:
            raise PackageError("training export is outside the licensed term")
        parent = provenance["parent_root"]
        removed = provenance["removed_material_ids"]
        if (
            (parent is not None and not _digest(parent))
            or not isinstance(removed, list)
            or any(not isinstance(item, str) or not item for item in removed)
            or len(set(removed)) != len(removed)
        ):
            raise PackageError("dataset removal lineage is malformed")
        if removed and parent is None:
            raise PackageError("removed material requires a predecessor root")
        materials = parsed["dataset/materials.json"]["materials"]
        if not isinstance(materials, list):
            raise PackageError("dataset materials must be an array")
        ids: set[str] = set()
        paths: set[str] = set()
        content_owners: dict[str, str] = {}
        for material in materials:
            identity = material["material_id"]
            if (
                not isinstance(identity, str)
                or not identity
                or identity in ids
                or identity in removed
            ):
                raise PackageError("duplicate, empty, or removed material")
            ids.add(identity)
            if not isinstance(material["capture_id"], str) or not material["capture_id"]:
                raise PackageError(f"{identity}: capture identity required")
            if material["split"] not in {"train", "held_out"}:
                raise PackageError(f"{identity}: frozen train or held_out split required")
            if not isinstance(material["rung"], str) or not material["rung"]:
                raise PackageError(f"{identity}: measured reconstruction rung required")
            for field in ("camera", "calibration", "metadata", "provenance"):
                if not isinstance(material[field], dict) or not material[field]:
                    raise PackageError(f"{identity}: {field} required")
            screening = material["screening"]
            if screening["decision"] != "approved" or not _digest(screening["receipt_sha256"]):
                raise PackageError(f"{identity}: approved prohibited-content screening required")
            assets = material["assets"]
            if not isinstance(assets, list) or not assets:
                raise PackageError(f"{identity}: exact assets required")
            roles = set()
            for asset in assets:
                path, role, digest = asset["path"], asset["role"], asset["sha256"]
                if (
                    not isinstance(path, str)
                    or not path.startswith("assets/")
                    or path in paths
                    or role not in _ROLES
                    or not _digest(digest)
                ):
                    raise PackageError(f"{identity}: invalid or shared asset")
                if path not in inventory or inventory[path]["sha256"] != digest:
                    raise PackageError(f"{identity}: asset digest differs from manifest")
                if digest in content_owners and content_owners[digest] != identity:
                    raise PackageError(f"{identity}: duplicate asset bytes across materials")
                content_owners[digest] = identity
                suffix = Path(path).suffix.lower()
                if (role.endswith("image") and suffix not in {".png", ".jpg", ".jpeg"}) or (
                    role.endswith("geometry") and suffix not in {".ply", ".json", ".sog"}
                ):
                    raise PackageError(f"{identity}: asset format does not match role")
                if role == "provenance_receipt" and suffix != ".json":
                    raise PackageError(f"{identity}: provenance receipt must be JSON")
                if role == "sparse_geometry" and suffix == ".sog":
                    raise PackageError(f"{identity}: SOG is trained geometry")
                paths.add(path)
                roles.add(role)
            if not roles.intersection({"source_image", "masked_image"}):
                raise PackageError(f"{identity}: source or masked image required")
            people = material["people"]
            if not isinstance(people, list) or len(
                {person["subject_id"] for person in people}
            ) != len(people):
                raise PackageError(f"{identity}: duplicate or malformed pictured people")
            for person in people:
                subject = person["subject_id"]
                if (
                    not isinstance(subject, str)
                    or not subject
                    or type(person["masked"]) is not bool
                ):
                    raise PackageError(f"{identity}: malformed pictured person")
                granted = training_is_granted(receipts, subject_id=subject, terms=terms, at=at)
                if not granted:
                    if person["masked"] is not True:
                        raise PackageError(
                            f"training export refused: person {subject} in material {identity} "
                            "lacks training-use consent and is not masked"
                        )
                    if (
                        not _digest(person.get("mask_receipt_sha256"))
                        or "masked_image" not in roles
                        or "source_image" in roles
                    ):
                        raise PackageError(
                            f"{identity}: unconsented person requires a receipt-bound "
                            "masked export without source images"
                        )
        if set(inventory) != DATASET_REQUIRED_PATHS | paths:
            raise PackageError("dataset contains unreferenced or undeclared payloads")
    except PackageError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise PackageError(f"malformed training dataset: {error}") from error


def write_dataset_package(
    output: Path,
    *,
    files: Mapping[str, bytes],
    materials: Sequence[dict[str, Any]],
    terms: TrainingTerms,
    receipts: Sequence[TrainingReceipt],
    exported_at: dt.datetime,
    private_key: Ed25519PrivateKey,
    owner_opt_in: bool = False,
    parent_root: str | None = None,
    removed_material_ids: Sequence[str] = (),
    licensing: Mapping[str, Any] | None = None,
) -> VerificationReport:
    """Write an explicit, atomic package from already-grounded source declarations."""
    if owner_opt_in is not True:
        raise PackageError("training export requires explicit package-owner opt-in")
    if output.exists():
        raise PackageError(f"output already exists: {output}")
    payloads = dict(files)
    if any(not path.startswith("assets/") for path in payloads):
        raise PackageError("caller assets must live under assets/")
    payloads.update(
        {
            "wmp/profile.json": canonical_file(
                json.loads(
                    (
                        Path(__file__).with_name("profile") / f"{DATASET_PROFILE_VERSION}.json"
                    ).read_text()
                )
            ),
            "dataset/materials.json": canonical_file({"materials": list(materials)}),
            "consent/training.json": canonical_file(
                {
                    "owner_opt_in": owner_opt_in,
                    "terms": terms.as_dict(),
                    "receipts": [receipt.as_dict() for receipt in receipts],
                }
            ),
            "provenance/dataset.json": canonical_file(
                {
                    "exported_at": exported_at.isoformat(),
                    "licensing": dict(licensing or {}),
                    "claim": "recorded captures; no simulation or adaptation claim",
                    "parent_root": parent_root,
                    "removed_material_ids": sorted(removed_material_ids),
                    "trust_boundary": (
                        "signature authenticates bytes and declarations; screening, masking and "
                        "licensor authority require trust in the issuer; later withdrawals require "
                        "a current ledger"
                    ),
                }
            ),
        }
    )
    for path, data in files.items():
        scan_dataset_asset(path, data)
    inventory = {item["path"]: item for item in build_manifest(payloads)["entries"]}
    payloads["ro-crate-metadata.json"] = canonical_file(_crate_document(inventory, terms))
    manifest = build_manifest(payloads, profile_version=DATASET_PROFILE_VERSION)
    parsed = {path: json.loads(value) for path, value in payloads.items() if path.endswith(".json")}
    validate_dataset(parsed, {item["path"]: item for item in manifest["entries"]})
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".training-export-", dir=output.parent))
    try:
        for path, data in payloads.items():
            target = staging / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        manifest_bytes = canonical_file(manifest)
        (staging / MANIFEST_PATH).write_bytes(manifest_bytes)
        (staging / SIGNATURE_PATH).write_bytes(
            canonical_file(sign_manifest(manifest_bytes, private_key))
        )
        report = verify_package(staging)
        os.rename(staging, output)
        return report
    finally:
        if staging.exists():
            shutil.rmtree(staging)
