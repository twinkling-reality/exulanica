"""Canonical package layout, Merkle construction, signing, and offline verification.

The verifier deliberately imports no database module.  A copied directory plus the public key
embedded in its signature document is sufficient to establish byte integrity, profile identity,
the prohibited-content boundary, and the Ed25519 signature.  It does not claim that the signer
was authorised; that trust decision belongs to whoever distributes the public-key fingerprint.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from exulanica.canonical import canonical_json
from exulanica.errors import ExulanicaError

PROFILE_VERSION: Final = "exulanica-wmp-1.0"
PROFILE_ID: Final = "https://exulanica.local/profiles/world-memory-package/1.0"
MANIFEST_PATH: Final = "wmp/manifest.json"
SIGNATURE_PATH: Final = "wmp/signature.json"
REQUIRED_PAYLOAD_PATHS: Final = frozenset(
    {
        "appearance/style.json",
        "deletion/tombstones.json",
        "evaluation/results.json",
        "evidence/descriptors.json",
        "external/fetch.json",
        "interaction/policy.json",
        "memory/graph.json",
        "policy/export.json",
        "provenance/events.json",
        "provenance/package.json",
        "reconstruction/artifacts.json",
        "ro-crate-metadata.json",
        "wmp/profile.json",
        "world/layout.json",
        "world/neighborhood.json",
        "world/placement.json",
        "world/structure.json",
        "world/topology.json",
    }
)
_LEAF_PREFIX: Final = b"exulanica-wmp-leaf-v1\0"
_NODE_PREFIX: Final = b"exulanica-wmp-node-v1\0"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_FORBIDDEN_SUFFIXES: Final = frozenset(
    {
        ".css",
        ".glsl",
        ".html",
        ".jpeg",
        ".jpg",
        ".js",
        ".mov",
        ".mp3",
        ".mp4",
        ".npy",
        ".npz",
        ".onnx",
        ".png",
        ".pt",
        ".pth",
        ".safetensors",
        ".shader",
        ".wav",
        ".webp",
        ".wgsl",
    }
)
_FORBIDDEN_SEGMENTS: Final = frozenset(
    {
        "biometrics",
        "credentials",
        "embeddings",
        "model-cache",
        "raw-media",
        "training-intermediates",
    }
)
_FORBIDDEN_KEYS: Final = frozenset(
    {
        "access_token",
        "bearer_token",
        "biometric_template",
        "conversation",
        "credential",
        "css",
        "embedding",
        "executable",
        "javascript",
        "messages",
        "model_cache",
        "model_internal",
        "password",
        "private_key",
        "prompt_text",
        "raw_media",
        "raw_utterance",
        "remote_code_url",
        "remote_executable",
        "remote_module",
        "renderer_program",
        "secret",
        "shader",
        "storage_key",
        "token",
        "training_intermediate",
        "transcript",
    }
)
_PRIVATE_KEY_MARKER: Final = "-----BEGIN PRIVATE KEY-----"


class PackageError(ExulanicaError):
    """A World Memory Package is malformed, inconsistent, or fails verification."""


class ProhibitedContentError(PackageError):
    """A package contains a payload class WMP v1 excludes by default."""


@dataclass(frozen=True, slots=True)
class VerificationReport:
    profile_version: str
    merkle_root_sha256: str
    manifest_sha256: str
    signing_public_key_sha256: str
    file_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_count": self.file_count,
            "manifest_sha256": self.manifest_sha256,
            "merkle_root_sha256": self.merkle_root_sha256,
            "profile_version": self.profile_version,
            "signing_public_key_sha256": self.signing_public_key_sha256,
            "verified": True,
        }


def normalize_value(value: Any) -> Any:
    """Convert database values to the no-float canonical package value domain.

    Binary floating-point is preserved exactly as ``float.hex()`` and is visibly tagged.  This
    avoids both silent rounding and the false claim that Python's decimal spelling is the source
    value.  New code should still use fixed-point integers for protected state; the tagged form
    exists for historical confidence, score, and cost fields.
    """
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PackageError("non-finite floating-point data cannot enter a WMP")
        return {"@type": "exulanica:IEEE754Binary64", "hex": value.hex()}
    if isinstance(value, Decimal):
        return {"@type": "exulanica:Decimal", "value": str(value)}
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            raise PackageError("naive datetime cannot enter a WMP")
        return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    if isinstance(value, Mapping):
        return {str(key): normalize_value(sub) for key, sub in value.items()}
    if isinstance(value, Sequence):
        return [normalize_value(sub) for sub in value]
    # psycopg range and multirange objects have a stable PostgreSQL textual representation.
    if value.__class__.__module__.startswith("psycopg.types.range"):
        return {"@type": "exulanica:PostgreSQLRange", "value": str(value)}
    raise PackageError(f"unsupported package value type: {type(value).__name__}")


def canonical_file(value: Any) -> bytes:
    return canonical_json(normalize_value(value))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manifest(
    files: Mapping[str, bytes], *, profile_version: str = PROFILE_VERSION
) -> dict[str, Any]:
    entries = [
        {"bytes": len(files[path]), "path": path, "sha256": _sha256(files[path])}
        for path in sorted(files)
    ]
    return {
        "entries": entries,
        "merkle_root_sha256": merkle_root(entries),
        "profile_version": profile_version,
    }


def merkle_root(entries: Sequence[Mapping[str, Any]]) -> str:
    if not entries:
        return hashlib.sha256(_LEAF_PREFIX).hexdigest()
    level = [
        hashlib.sha256(
            _LEAF_PREFIX
            + str(entry["path"]).encode("utf-8")
            + b"\0"
            + bytes.fromhex(str(entry["sha256"]))
        ).digest()
        for entry in entries
    ]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(_NODE_PREFIX + level[index] + level[index + 1]).digest()
            for index in range(0, len(level), 2)
        ]
    return level[0].hex()


def sign_manifest(manifest_bytes: bytes, private_key: Ed25519PrivateKey) -> dict[str, Any]:
    manifest = _load_canonical_json(manifest_bytes, MANIFEST_PATH)
    manifest_sha256 = _sha256(manifest_bytes)
    payload = canonical_json(
        {
            "manifest_sha256": manifest_sha256,
            "merkle_root_sha256": manifest["merkle_root_sha256"],
            "profile_version": manifest["profile_version"],
        }
    )
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return {
        "algorithm": "Ed25519",
        "manifest_sha256": manifest_sha256,
        "merkle_root_sha256": manifest["merkle_root_sha256"],
        "profile_version": manifest["profile_version"],
        "public_key_base64": base64.b64encode(public_raw).decode("ascii"),
        "signature_base64": base64.b64encode(private_key.sign(payload)).decode("ascii"),
        "signed_payload_profile": "exulanica-wmp-signature-payload-v1",
    }


def scan_payload(path: str, value: Any) -> None:
    pure = Path(path)
    if pure.suffix.lower() in _FORBIDDEN_SUFFIXES:
        raise ProhibitedContentError(f"{path}: prohibited executable, model, or media suffix")
    if {part.lower() for part in pure.parts} & _FORBIDDEN_SEGMENTS:
        raise ProhibitedContentError(f"{path}: prohibited content directory")

    def walk(node: Any, pointer: str) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                normalized_key = str(key).lower().replace("-", "_").replace(" ", "_")
                if normalized_key in _FORBIDDEN_KEYS:
                    raise ProhibitedContentError(f"{path}{pointer}/{key}: prohibited field")
                walk(child, f"{pointer}/{key}")
        elif isinstance(node, Sequence) and not isinstance(node, str | bytes | bytearray):
            for index, child in enumerate(node):
                walk(child, f"{pointer}/{index}")
        elif isinstance(node, str):
            lowered = node.lower()
            if _PRIVATE_KEY_MARKER.lower() in lowered:
                raise ProhibitedContentError(f"{path}{pointer}: private signing material")
            if lowered.startswith(("data:image/", "data:audio/", "data:video/")):
                raise ProhibitedContentError(f"{path}{pointer}: inline raw media")

    walk(value, "")


def verify_package(directory: Path) -> VerificationReport:
    root = directory.resolve()
    if not root.is_dir():
        raise PackageError(f"package directory does not exist: {directory}")
    manifest_bytes = _read_regular(root, MANIFEST_PATH)
    signature_bytes = _read_regular(root, SIGNATURE_PATH)
    manifest = _load_canonical_json(manifest_bytes, MANIFEST_PATH)
    signature = _load_canonical_json(signature_bytes, SIGNATURE_PATH)
    from exulanica.world_package.dataset import DATASET_PROFILE_VERSION, validate_dataset

    version = manifest.get("profile_version")
    if version not in {PROFILE_VERSION, DATASET_PROFILE_VERSION}:
        raise PackageError(f"unsupported profile: {manifest.get('profile_version')!r}")
    if signature.get("profile_version") != version:
        raise PackageError("signature profile does not match the manifest")

    expected_entries = manifest.get("entries")
    if not isinstance(expected_entries, list):
        raise PackageError("manifest entries must be an array")
    if not all(_valid_entry(entry) for entry in expected_entries):
        raise PackageError("manifest contains a malformed inventory entry")
    expected_paths = [entry["path"] for entry in expected_entries]
    if expected_paths != sorted(expected_paths):
        raise PackageError("manifest paths must be unique objects in sorted order")
    if len(set(expected_paths)) != len(expected_paths):
        raise PackageError("manifest contains a duplicate path")
    from exulanica.world_package.dataset import DATASET_REQUIRED_PATHS, scan_dataset_asset

    required = REQUIRED_PAYLOAD_PATHS if version == PROFILE_VERSION else DATASET_REQUIRED_PATHS
    missing_required = sorted(required - set(expected_paths))
    if missing_required:
        raise PackageError(f"package is incomplete for {version}: {missing_required}")
    actual_paths = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and str(path.relative_to(root)) not in {MANIFEST_PATH, SIGNATURE_PATH}
    )
    if actual_paths != expected_paths:
        raise PackageError(
            f"manifest inventory mismatch: expected {expected_paths}, found {actual_paths}"
        )

    actual_entries: list[dict[str, Any]] = []
    parsed: dict[str, Any] = {}
    for expected in expected_entries:
        path = str(expected["path"])
        data = _read_regular(root, path)
        if version == DATASET_PROFILE_VERSION and path.startswith("assets/"):
            scan_dataset_asset(path, data)
        else:
            scan_payload(path, None)
        if path.endswith(".json") and not (
            version == DATASET_PROFILE_VERSION and path.startswith("assets/")
        ):
            value = _load_canonical_json(data, path)
            scan_payload(path, value)
            parsed[path] = value
        actual_entries.append({"bytes": len(data), "path": path, "sha256": _sha256(data)})
    if actual_entries != expected_entries:
        raise PackageError("one or more payload bytes do not match the canonical manifest")
    root_hash = merkle_root(actual_entries)
    if root_hash != manifest.get("merkle_root_sha256"):
        raise PackageError("Merkle root does not match the manifest entries")
    if version == PROFILE_VERSION:
        _validate_profile(parsed)
    else:
        validate_dataset(parsed, {entry["path"]: entry for entry in actual_entries})
    manifest_sha256 = _sha256(manifest_bytes)
    if manifest_sha256 != signature.get("manifest_sha256"):
        raise PackageError("signature names a different manifest")
    if root_hash != signature.get("merkle_root_sha256"):
        raise PackageError("signature names a different Merkle root")
    if signature.get("algorithm") != "Ed25519":
        raise PackageError("unsupported signature algorithm")
    try:
        public_raw = base64.b64decode(signature["public_key_base64"], validate=True)
        signed = base64.b64decode(signature["signature_base64"], validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(public_raw)
        public_key.verify(
            signed,
            canonical_json(
                {
                    "manifest_sha256": manifest_sha256,
                    "merkle_root_sha256": root_hash,
                    "profile_version": version,
                }
            ),
        )
    except (KeyError, TypeError, ValueError, InvalidSignature) as error:
        raise PackageError("Ed25519 signature verification failed") from error
    return VerificationReport(
        profile_version=version,
        merkle_root_sha256=root_hash,
        manifest_sha256=manifest_sha256,
        signing_public_key_sha256=_sha256(public_raw),
        file_count=len(actual_entries),
    )


def inspect_package(directory: Path) -> dict[str, Any]:
    verification = verify_package(directory)
    if verification.profile_version != PROFILE_VERSION:
        materials = json.loads((directory / "dataset/materials.json").read_text())["materials"]
        consent = json.loads((directory / "consent/training.json").read_text())
        return {
            **verification.as_dict(),
            "materials": len(materials),
            "training_terms": consent["terms"],
            "consent_receipts": len(consent["receipts"]),
            "lineage": json.loads((directory / "provenance/dataset.json").read_text()),
        }
    components: dict[str, Any] = {}
    for path in (
        "memory/graph.json",
        "reconstruction/artifacts.json",
        "world/structure.json",
        "appearance/style.json",
        "interaction/policy.json",
        "provenance/events.json",
        "evaluation/results.json",
        "deletion/tombstones.json",
        "external/fetch.json",
    ):
        value = json.loads((directory / path).read_text(encoding="utf-8"))
        items = value.get("items") if isinstance(value, dict) else None
        components[path] = {"items": len(items)} if isinstance(items, list) else value.get("state")
    return {"components": components, **verification.as_dict()}


def import_check_package(
    directory: Path,
    *,
    supported_style_profiles: frozenset[str] = frozenset(),
    supported_interaction_capabilities: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Inspect receiver compatibility without writing a database or importing package state."""
    verification = verify_package(directory)
    if verification.profile_version != PROFILE_VERSION:
        raise PackageError(
            "training datasets are not interactive-world imports; use verify or inspect"
        )
    style = json.loads((directory / "appearance/style.json").read_text(encoding="utf-8"))
    interaction = json.loads((directory / "interaction/policy.json").read_text(encoding="utf-8"))
    structure = json.loads((directory / "world/structure.json").read_text(encoding="utf-8"))
    required_profiles: set[str] = set()
    required_capabilities: set[str] = set()
    warnings: list[str] = []
    if style.get("state") == "current":
        global_style = style["global"]
        required_profiles.add(f"{global_style['profile_id']}@{global_style['profile_version']}")
        required_profiles.update(
            f"{region['profile_id']}@{region['profile_version']}"
            for region in style.get("regions", [])
        )
    else:
        warnings.append("appearance state is unavailable")
    if interaction.get("state") == "current":
        versions = {
            row["capability_key"]: row["capability_version"]
            for row in interaction.get("registry", [])
        }
        required_capabilities.update(
            f"{key}@{versions[key]}" for key in interaction.get("parameters", {}) if key in versions
        )
    else:
        warnings.append("interaction state is unavailable")
    if structure.get("state") == "unavailable":
        warnings.append("spatial structure is unavailable")
    missing_profiles = sorted(required_profiles - supported_style_profiles)
    missing_capabilities = sorted(required_capabilities - supported_interaction_capabilities)
    declarations_supplied = bool(supported_style_profiles or supported_interaction_capabilities)
    compatible: bool | None = (
        not (missing_profiles or missing_capabilities) if declarations_supplied else None
    )
    if not declarations_supplied:
        warnings.append("receiver capabilities were not declared; compatibility is indeterminate")
    return {
        "compatible": compatible,
        "manifest_sha256": verification.manifest_sha256,
        "merkle_root_sha256": verification.merkle_root_sha256,
        "missing_interaction_capabilities": missing_capabilities,
        "missing_style_profiles": missing_profiles,
        "mutated": False,
        "required_interaction_capabilities": sorted(required_capabilities),
        "required_style_profiles": sorted(required_profiles),
        "warnings": warnings,
    }


def load_private_key(path: Path) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as error:
        raise PackageError(f"cannot load Ed25519 private key: {path}") from error
    if not isinstance(key, Ed25519PrivateKey):
        raise PackageError("the supplied signing key is not Ed25519")
    return key


def _read_regular(root: Path, relative: str) -> bytes:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise PackageError(f"{relative}: missing, not regular, or symbolic link")
    try:
        path.resolve().relative_to(root)
    except ValueError as error:
        raise PackageError(f"{relative}: escapes package root") from error
    return path.read_bytes()


def _load_canonical_json(data: bytes, path: str) -> Any:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackageError(f"{path}: invalid UTF-8 JSON") from error
    try:
        expected = canonical_json(value)
    except Exception as error:
        raise PackageError(f"{path}: outside the canonical no-float JSON domain") from error
    if data != expected:
        raise PackageError(f"{path}: JSON is not in canonical byte form")
    return value


def _valid_entry(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"bytes", "path", "sha256"}:
        return False
    path = value["path"]
    size = value["bytes"]
    digest = value["sha256"]
    return (
        isinstance(path, str)
        and bool(path)
        and not path.startswith("/")
        and ".." not in Path(path).parts
        and isinstance(size, int)
        and not isinstance(size, bool)
        and size >= 0
        and isinstance(digest, str)
        and _HEX64.fullmatch(digest) is not None
    )


def _validate_profile(files: Mapping[str, Any]) -> None:
    profile = files["wmp/profile.json"]
    if (
        not isinstance(profile, dict)
        or profile.get("@id") != PROFILE_ID
        or profile.get("version") != PROFILE_VERSION
    ):
        raise PackageError("wmp/profile.json does not identify the supported WMP profile")
    crate = files["ro-crate-metadata.json"]
    if (
        not isinstance(crate, dict)
        or crate.get("@context") != "https://w3id.org/ro/crate/1.2/context"
    ):
        raise PackageError("RO-Crate metadata does not use the required 1.2 context")
    graph = crate.get("@graph")
    if not isinstance(graph, list):
        raise PackageError("RO-Crate metadata has no JSON-LD graph")
    by_id = {
        node["@id"]: node
        for node in graph
        if isinstance(node, dict) and isinstance(node.get("@id"), str)
    }
    descriptor = by_id.get("ro-crate-metadata.json", {})
    root = by_id.get("./", {})
    declared_profile = by_id.get(PROFILE_ID, {})
    rai = by_id.get("#responsible-ai-boundary", {})
    root_types = root.get("@type", [])
    profile_types = declared_profile.get("@type", [])
    if isinstance(root_types, str):
        root_types = [root_types]
    if isinstance(profile_types, str):
        profile_types = [profile_types]
    if (
        descriptor.get("@type") != "CreativeWork"
        or descriptor.get("about") != {"@id": "./"}
        or descriptor.get("conformsTo") != {"@id": "https://w3id.org/ro/crate/1.2"}
        or "Dataset" not in root_types
        or not root.get("name")
        or not root.get("description")
        or root.get("conformsTo") != {"@id": PROFILE_ID}
        or "Profile" not in profile_types
    ):
        raise PackageError(
            "RO-Crate descriptor, root dataset, or profile declaration is incomplete"
        )
    rai_conformance = rai.get("http://purl.org/dc/terms/conformsTo", [])
    if not {
        "http://mlcommons.org/croissant/1.0",
        "http://mlcommons.org/croissant/RAI/1.0",
    }.issubset(set(rai_conformance)):
        raise PackageError("RO-Crate graph has no Croissant 1.0 plus RAI 1.0 compatibility node")
    fetch = files["external/fetch.json"]
    if not isinstance(fetch, dict) or not isinstance(fetch.get("items"), list):
        raise PackageError("external fetch references are malformed")
    for item in fetch["items"]:
        if (
            not isinstance(item, dict)
            or "url" in item
            or not str(item.get("ni_uri", "")).startswith("ni:///sha-256;")
            or item.get("retrieval") != "requires an authorized content-addressed resolver"
        ):
            raise PackageError("an external media reference overstates fetch availability")


def profile_bytes() -> bytes:
    path = Path(__file__).with_name("profile") / "exulanica-wmp-1.0.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    return canonical_json(value)
