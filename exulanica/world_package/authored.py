"""The authored-world extension to WMP 1.0: alternate versions, authored objects, behaviours.

**Why an extension and not a 1.1 profile.** ``REQUIRED_PAYLOAD_PATHS`` is checked before the
signature, so a new required path makes every already-signed 1.0 package unverifiable, and
migration 0028 pins ``world_package_export.profile_version`` to ``exulanica-wmp-1.0``. An optional
directory under ``extensions/`` breaks neither: a 1.0 verifier inventories it, hashes it, scans it
for prohibited content and checks the signature over it, and a verifier that knows this extension
additionally checks the rules below. ``tests/test_world_package_verifier.py`` already holds the
fact this depends on, that an unlisted path rides along with 1.0 verification untouched.

**What the extension carries.** Every alternate version whose source snapshot is not invalidated
by deletion, its canonical delta (authored objects and source-element overrides, byte for byte
the document whose SHA-256 is the version's ``state_sha256``), its edit chain without actors,
the reviewed asset descriptors those objects name by digest, and the reviewed behaviour
descriptors they name by key and version. It carries no asset bytes and no runtime code: an asset
is a digest an authorized resolver must supply, and a behaviour is an identifier with bounded
parameters that a runtime either supports or must visibly refuse.

**What is pure here.** This module imports nothing that opens a database. The digest is
re-derived with :func:`exulanica.canonical.canonical_json` alone rather than through
:mod:`exulanica.world.objects`, so an independent verifier needs only the documented canonical
JSON rule, and a test holds the two derivations equal.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.errors import ExulanicaError

EXTENSION_NAME: Final = "exulanica-wmp-ext-authored-world"
EXTENSION_VERSION: Final = "1.0"
#: The name the command line and the directory use.
EXTENSION_KEY: Final = "authored-world-1.0"
EXTENSION_DIR: Final = f"extensions/{EXTENSION_KEY}"
EXTENSION_PROFILE_ID: Final = (
    "https://exulanica.local/profiles/world-memory-package/extensions/authored-world/1.0"
)
BASE_PROFILE: Final = "exulanica-wmp-1.0"
DECLARATION_PATH: Final = f"{EXTENSION_DIR}/extension.json"
VERSIONS_PATH: Final = f"{EXTENSION_DIR}/versions.json"
ASSETS_PATH: Final = f"{EXTENSION_DIR}/assets.json"
BEHAVIOURS_PATH: Final = f"{EXTENSION_DIR}/behaviours.json"
EXTENSION_PATHS: Final = frozenset({DECLARATION_PATH, VERSIONS_PATH, ASSETS_PATH, BEHAVIOURS_PATH})

#: Capability strings a loader declares. The vocabulary is small on purpose: each names a thing a
#: loader either can or cannot do with this package, and each is required only when content that
#: needs it is present.
EXTENSION_CAPABILITY: Final = f"wmp-extension:{EXTENSION_NAME}@{EXTENSION_VERSION}"
ASSET_RESOLUTION_CAPABILITY: Final = "asset-resolution:sha256-content-address"

ASSET_BYTES: Final = (
    "not embedded: each asset is a SHA-256 content reference an authorized resolver must supply"
)
RUNTIME_CODE: Final = (
    "not carried: a behaviour is a reviewed identifier with bounded parameters, and a runtime "
    "that does not support it must show it as unsupported"
)
COORDINATE_SPACE: Final = (
    "region_local: compose each object transform with its region's placement in "
    "world/placement.json"
)
ASSET_RETRIEVAL: Final = "requires an authorized content-addressed resolver"
WITHHELD_REASON: Final = (
    "a committed deletion invalidated the source snapshot; the version is not exported"
)
_VERSIONS_PROFILE: Final = "exulanica-wmp-ext-authored-world-versions-v1"
_ASSETS_PROFILE: Final = "exulanica-wmp-ext-authored-world-assets-v1"
_BEHAVIOURS_PROFILE: Final = "exulanica-wmp-ext-authored-world-behaviours-v1"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_URN = re.compile(r"^urn:exulanica:wmp:(?P<kind>[a-z-]+):[0-9a-f]{64}$")
_OBJECT_ID = re.compile("^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$")
_EDIT_KINDS: Final = frozenset(
    {"add_object", "move_object", "remove_object", "suppress_element", "transform_element", "undo"}
)
_OBJECT_EDITS: Final = frozenset({"add_object", "move_object", "remove_object"})
_ELEMENT_EDITS: Final = frozenset({"suppress_element", "transform_element"})
_MAX_YAW: Final = 6_283_185
_MAX_SCALE: Final = 1_000_000
_MAX_TRANSLATION: Final = 1_000_000_000

#: The state token of a version with nothing in it. A version created from a source snapshot
#: starts here, so its first edit must name this as its base.
EMPTY_DELTA: Final = {"element_overrides": [], "objects": [], "schema_version": 1}
EMPTY_DELTA_SHA256: Final = hashlib.sha256(canonical_json(EMPTY_DELTA)).hexdigest()


class ExtensionError(ExulanicaError):
    """The authored-world extension is inconsistent with its own rules or with the 1.0 package."""


@dataclass(frozen=True, slots=True)
class AuthoredWorld:
    """The extension's sections after verification, for a loader that supports it."""

    declaration: Mapping[str, Any]
    versions: tuple[Mapping[str, Any], ...]
    assets: Mapping[str, Mapping[str, Any]]
    behaviours: Mapping[tuple[str, int], Mapping[str, Any]]
    source_snapshots: Mapping[str, Mapping[str, Any]]
    withheld_versions: int


def delta_sha256(delta: Mapping[str, Any]) -> str:
    """The version state token, from the exported delta document and the canonical JSON rule."""
    return hashlib.sha256(canonical_json(delta)).hexdigest()


def ni_uri(content_sha256: str) -> str:
    digest = base64.urlsafe_b64encode(bytes.fromhex(content_sha256)).decode("ascii").rstrip("=")
    return f"ni:///sha-256;{digest}"


def required_loader_capabilities(
    versions: Iterable[Mapping[str, Any]], assets: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """What a loader must support to present every object this extension says is present.

    A removed object is part of the state digest and is not drawn, so it requires nothing. That
    keeps a version whose only lantern was removed loadable by a runtime with no motion support.
    """
    required = {EXTENSION_CAPABILITY}
    for version in versions:
        for obj in version["delta"]["objects"]:
            if obj["removed"]:
                continue
            required.add(ASSET_RESOLUTION_CAPABILITY)
            required.add(f"asset-media:{assets[obj['asset_sha256']]['media_type']}")
            if obj["behaviour"] is not None:
                behaviour = obj["behaviour"]
                required.add(
                    f"behaviour:{behaviour['behaviour_key']}@{behaviour['behaviour_version']}"
                )
    return sorted(required)


def declaration(
    versions: Sequence[Mapping[str, Any]],
    assets: Mapping[str, Mapping[str, Any]],
    *,
    withheld_versions: int,
) -> dict[str, Any]:
    objects = [obj for version in versions for obj in version["delta"]["objects"]]
    return {
        "@id": EXTENSION_PROFILE_ID,
        "asset_bytes": ASSET_BYTES,
        "base_profile": BASE_PROFILE,
        "coordinate_space": COORDINATE_SPACE,
        "counts": {
            "alternate_versions": len(versions),
            "authored_objects": len(objects),
            "authored_objects_present": sum(1 for obj in objects if not obj["removed"]),
            "withheld_versions": withheld_versions,
        },
        "extension": EXTENSION_NAME,
        "extension_version": EXTENSION_VERSION,
        "required_loader_capabilities": required_loader_capabilities(versions, assets),
        "runtime_code": RUNTIME_CODE,
        "sections": {
            "assets": ASSETS_PATH,
            "behaviours": BEHAVIOURS_PATH,
            "versions": VERSIONS_PATH,
        },
    }


def build_sections(
    *,
    versions: Sequence[Mapping[str, Any]],
    source_snapshots: Sequence[Mapping[str, Any]],
    assets: Sequence[Mapping[str, Any]],
    behaviours: Sequence[Mapping[str, Any]],
    withheld_versions: int,
) -> dict[str, dict[str, Any]]:
    """Assemble the four extension documents in the one order the verifier accepts."""
    ordered_versions = sorted(versions, key=lambda item: item["version_id"])
    ordered_assets = sorted(assets, key=lambda item: item["content_sha256"])
    by_digest = {item["content_sha256"]: item for item in ordered_assets}
    return {
        ASSETS_PATH: {"items": ordered_assets, "profile": _ASSETS_PROFILE},
        BEHAVIOURS_PATH: {
            "items": sorted(
                behaviours, key=lambda item: (item["behaviour_key"], item["behaviour_version"])
            ),
            "profile": _BEHAVIOURS_PROFILE,
        },
        DECLARATION_PATH: declaration(
            ordered_versions, by_digest, withheld_versions=withheld_versions
        ),
        VERSIONS_PATH: {
            "items": ordered_versions,
            "profile": _VERSIONS_PROFILE,
            "source_snapshots": sorted(source_snapshots, key=lambda item: item["snapshot_id"]),
            "withheld": {
                "invalidated_source_versions": withheld_versions,
                "reason": WITHHELD_REASON,
            },
        },
    }


# ------------------------------------------------------------------------------------------
# Verification. Every rule refuses; none repairs. A package that fails here was signed while
# inconsistent, and a recipient must not be handed a quietly corrected reading of it.
# ------------------------------------------------------------------------------------------


def verify_authored_world(files: Mapping[str, Any], inventory: Iterable[str]) -> AuthoredWorld:
    """Check the extension against its rules and against the 1.0 structure it sits beside."""
    present = {path for path in inventory if path.startswith(f"{EXTENSION_DIR}/")}
    if present != EXTENSION_PATHS:
        raise ExtensionError(
            f"{EXTENSION_DIR} must hold exactly {sorted(EXTENSION_PATHS)}, found {sorted(present)}"
        )
    assets = _verify_assets(files[ASSETS_PATH])
    behaviours = _verify_behaviours(files[BEHAVIOURS_PATH])
    document = _mapping(files[VERSIONS_PATH], VERSIONS_PATH)
    _exact(document, {"items", "profile", "source_snapshots", "withheld"}, VERSIONS_PATH)
    if document["profile"] != _VERSIONS_PROFILE:
        raise ExtensionError(f"{VERSIONS_PATH}: unknown section profile")
    snapshots = _verify_source_snapshots(document["source_snapshots"], files)
    withheld = _mapping(document["withheld"], f"{VERSIONS_PATH}/withheld")
    _exact(withheld, {"invalidated_source_versions", "reason"}, f"{VERSIONS_PATH}/withheld")
    withheld_count = withheld["invalidated_source_versions"]
    if not _natural(withheld_count) or withheld["reason"] != WITHHELD_REASON:
        raise ExtensionError(f"{VERSIONS_PATH}/withheld is malformed")
    versions = _list(document["items"], f"{VERSIONS_PATH}/items")
    _sorted_unique([_mapping(v, VERSIONS_PATH).get("version_id") for v in versions], "versions")
    by_id = {version["version_id"]: version for version in versions}
    referenced_assets: set[str] = set()
    referenced_behaviours: set[tuple[str, int]] = set()
    for version in versions:
        _verify_version(version, by_id, snapshots, assets, behaviours)
        for obj in version["delta"]["objects"]:
            referenced_assets.add(obj["asset_sha256"])
            if obj["behaviour"] is not None:
                referenced_behaviours.add(
                    (obj["behaviour"]["behaviour_key"], obj["behaviour"]["behaviour_version"])
                )
    if referenced_assets != set(assets):
        raise ExtensionError(f"{ASSETS_PATH} must list exactly the assets an object references")
    if referenced_behaviours != set(behaviours):
        raise ExtensionError(
            f"{BEHAVIOURS_PATH} must list exactly the behaviours an object references"
        )
    referenced_snapshots = {version["source_snapshot_id"] for version in versions}
    if referenced_snapshots != set(snapshots):
        raise ExtensionError(
            f"{VERSIONS_PATH}: source_snapshots must be exactly those a version names"
        )
    expected = declaration(versions, assets, withheld_versions=withheld_count)
    if files[DECLARATION_PATH] != expected:
        raise ExtensionError(
            f"{DECLARATION_PATH} does not match the sections it declares; a declaration that "
            "understates what a loader needs would let a runtime drop content silently"
        )
    return AuthoredWorld(
        declaration=expected,
        versions=tuple(versions),
        assets=assets,
        behaviours=behaviours,
        source_snapshots=snapshots,
        withheld_versions=withheld_count,
    )


def _verify_assets(value: Any) -> dict[str, Mapping[str, Any]]:
    document = _mapping(value, ASSETS_PATH)
    _exact(document, {"items", "profile"}, ASSETS_PATH)
    if document["profile"] != _ASSETS_PROFILE:
        raise ExtensionError(f"{ASSETS_PATH}: unknown section profile")
    items = _list(document["items"], ASSETS_PATH)
    digests = []
    for item in items:
        item = _mapping(item, ASSETS_PATH)
        _exact(
            item,
            {
                "asset_key",
                "byte_size",
                "content_sha256",
                "licence_id",
                "licence_sha256",
                "media_type",
                "ni_uri",
                "retrieval",
                "summary",
                "title",
            },
            ASSETS_PATH,
        )
        digest = item["content_sha256"]
        if (
            not _hex64(digest)
            or not _hex64(item["licence_sha256"])
            or not _natural(item["byte_size"])
            or item["byte_size"] == 0
            or item["ni_uri"] != ni_uri(digest)
            or item["retrieval"] != ASSET_RETRIEVAL
            or not all(
                isinstance(item[key], str) and item[key]
                for key in ("asset_key", "licence_id", "media_type", "summary", "title")
            )
        ):
            raise ExtensionError(f"{ASSETS_PATH}: asset {item.get('asset_key')!r} is malformed")
        digests.append(digest)
    _sorted_unique(digests, "assets")
    return {item["content_sha256"]: item for item in items}


def _verify_behaviours(value: Any) -> dict[tuple[str, int], Mapping[str, Any]]:
    document = _mapping(value, BEHAVIOURS_PATH)
    _exact(document, {"items", "profile"}, BEHAVIOURS_PATH)
    if document["profile"] != _BEHAVIOURS_PROFILE:
        raise ExtensionError(f"{BEHAVIOURS_PATH}: unknown section profile")
    items = _list(document["items"], BEHAVIOURS_PATH)
    keys: list[tuple[str, int]] = []
    for item in items:
        item = _mapping(item, BEHAVIOURS_PATH)
        _exact(
            item, {"behaviour_key", "behaviour_version", "parameters", "summary"}, BEHAVIOURS_PATH
        )
        if (
            not isinstance(item["behaviour_key"], str)
            or not _natural(item["behaviour_version"])
            or item["behaviour_version"] < 1
            or not isinstance(item["summary"], str)
        ):
            raise ExtensionError(f"{BEHAVIOURS_PATH}: behaviour is malformed")
        parameters = _mapping(item["parameters"], BEHAVIOURS_PATH)
        for name, bound in parameters.items():
            _verify_bound(item["behaviour_key"], name, bound)
        keys.append((item["behaviour_key"], item["behaviour_version"]))
    _sorted_unique(keys, "behaviours")
    return {(item["behaviour_key"], item["behaviour_version"]): item for item in items}


def _verify_bound(behaviour: str, name: str, bound: Any) -> None:
    where = f"{BEHAVIOURS_PATH}: {behaviour} parameter {name}"
    bound = _mapping(bound, where)
    kind = bound.get("kind")
    if kind == "integer":
        _subset(bound, {"kind", "minimum", "maximum", "default"}, where)
        low, high = bound.get("minimum"), bound.get("maximum")
        if not (_integer(low) and _integer(high) and low <= high):
            raise ExtensionError(f"{where}: integer bounds are malformed")
        if "default" in bound and not (
            _integer(bound["default"]) and low <= bound["default"] <= high
        ):
            raise ExtensionError(f"{where}: default is outside its bounds")
    elif kind == "choice":
        _subset(bound, {"kind", "choices", "default"}, where)
        choices = bound.get("choices")
        if (
            not isinstance(choices, list)
            or len(choices) < 2
            or not all(isinstance(choice, str) for choice in choices)
            or len(set(choices)) != len(choices)
        ):
            raise ExtensionError(f"{where}: choices are malformed")
        if "default" in bound and bound["default"] not in choices:
            raise ExtensionError(f"{where}: default is not a choice")
    elif kind == "toggle":
        _subset(bound, {"kind", "default"}, where)
        if "default" in bound and not isinstance(bound["default"], bool):
            raise ExtensionError(f"{where}: default is not true or false")
    else:
        # Fails closed. A kind this verifier does not know is a bound it cannot check, and an
        # unchecked bound is an unbounded parameter.
        raise ExtensionError(f"{where}: unreviewed parameter kind {kind!r}")


def _verify_source_snapshots(value: Any, files: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    items = _list(value, f"{VERSIONS_PATH}/source_snapshots")
    structure = files.get("world/structure.json")
    topology = files.get("world/topology.json")
    ids = []
    current = []
    for item in items:
        item = _mapping(item, VERSIONS_PATH)
        _exact(
            item,
            {"current", "element_ids", "region_ids", "snapshot_id", "snapshot_sha256"},
            f"{VERSIONS_PATH}/source_snapshots",
        )
        if (
            not _urn_of(item["snapshot_id"], "structure")
            or not _hex64(item["snapshot_sha256"])
            or not isinstance(item["current"], bool)
        ):
            raise ExtensionError(f"{VERSIONS_PATH}: a source snapshot is malformed")
        _sorted_unique(item["region_ids"], "source snapshot region_ids", strings=True)
        _sorted_unique(item["element_ids"], "source snapshot element_ids", strings=True)
        if item["current"]:
            current.append(item)
        ids.append(item["snapshot_id"])
    _sorted_unique(ids, "source snapshots")
    if len(current) > 1:
        raise ExtensionError(f"{VERSIONS_PATH}: more than one source snapshot claims to be current")
    for item in current:
        # The one snapshot the 1.0 package itself describes. Its identity, digest, regions and
        # elements must agree with world/structure.json and world/topology.json, so the extension
        # cannot pose objects against a structure the package does not contain. Malformed 1.0
        # documents raise here as TypeError or KeyError, which the caller reports as a refusal.
        structure = _mapping(structure, "world/structure.json")
        topology = _mapping(topology, "world/topology.json")
        if (
            structure["state"] != "current"
            or structure["lineage"]["snapshot_id"] != item["snapshot_id"]
            or structure["digests"]["snapshot_sha256"] != item["snapshot_sha256"]
            or sorted(region["region_id"] for region in topology["regions"]) != item["region_ids"]
            or sorted(element["element_id"] for element in topology["elements"])
            != item["element_ids"]
        ):
            raise ExtensionError(
                f"{VERSIONS_PATH}: the current source snapshot disagrees with world/structure.json "
                "or world/topology.json"
            )
    return {item["snapshot_id"]: item for item in items}


def _verify_version(
    version: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    snapshots: Mapping[str, Mapping[str, Any]],
    assets: Mapping[str, Mapping[str, Any]],
    behaviours: Mapping[tuple[str, int], Mapping[str, Any]],
) -> None:
    _exact(
        version,
        {
            "created_at",
            "delta",
            "edit_seq",
            "edits",
            "origin",
            "parent_version_id",
            "source_snapshot_id",
            "state_sha256",
            "style_version_id",
            "title",
            "version_id",
        },
        VERSIONS_PATH,
    )
    name = version["version_id"]
    if (
        not _urn_of(name, "alternate-version")
        or version["origin"] != "authored"
        or not isinstance(version["title"], str)
        or not version["title"].strip()
        or not isinstance(version["created_at"], str)
        or not _hex64(version["state_sha256"])
        or not _natural(version["edit_seq"])
        or (
            version["style_version_id"] is not None
            and not _urn_of(version["style_version_id"], "style")
        )
    ):
        raise ExtensionError(f"{VERSIONS_PATH}: version {name} is malformed")
    source = snapshots.get(version["source_snapshot_id"])
    if source is None:
        raise ExtensionError(f"{VERSIONS_PATH}: version {name} names a source snapshot not listed")
    parent = version["parent_version_id"]
    if parent is not None:
        if (
            parent not in by_id
            or by_id[parent]["source_snapshot_id"] != version["source_snapshot_id"]
        ):
            raise ExtensionError(
                f"{VERSIONS_PATH}: version {name} names a parent not in this package or on "
                "another source snapshot"
            )
        seen = {name}
        cursor = parent
        while cursor is not None:
            if cursor in seen:
                raise ExtensionError(f"{VERSIONS_PATH}: version lineage has a cycle at {name}")
            seen.add(cursor)
            cursor = by_id[cursor]["parent_version_id"]
    delta = _mapping(version["delta"], f"{VERSIONS_PATH}/{name}/delta")
    _exact(delta, {"element_overrides", "objects", "schema_version"}, f"{name}/delta")
    if delta["schema_version"] != 1:
        raise ExtensionError(f"{VERSIONS_PATH}: version {name} has an unknown delta schema")
    objects = _list(delta["objects"], f"{name}/delta/objects")
    _sorted_unique([_mapping(o, name).get("object_id") for o in objects], "objects", strings=True)
    regions = set(source["region_ids"])
    for obj in objects:
        _verify_object(name, obj, regions, assets, behaviours)
    overrides = _list(delta["element_overrides"], f"{name}/delta/element_overrides")
    _sorted_unique(
        [_mapping(o, name).get("element_id") for o in overrides], "element overrides", strings=True
    )
    elements = set(source["element_ids"])
    for override in overrides:
        _exact(override, {"element_id", "suppressed", "transform"}, f"{name}/element_overrides")
        if (
            override["element_id"] not in elements
            or not isinstance(override["suppressed"], bool)
            or (not override["suppressed"] and override["transform"] is None)
        ):
            raise ExtensionError(f"{VERSIONS_PATH}: version {name} has a malformed override")
        if override["transform"] is not None:
            _verify_transform(name, override["transform"])
    if delta_sha256(delta) != version["state_sha256"]:
        raise ExtensionError(
            f"{VERSIONS_PATH}: version {name} state_sha256 does not re-derive from its delta"
        )
    _verify_edits(version, objects)


def _verify_object(
    version: str,
    obj: Any,
    regions: set[str],
    assets: Mapping[str, Mapping[str, Any]],
    behaviours: Mapping[tuple[str, int], Mapping[str, Any]],
) -> None:
    where = f"{VERSIONS_PATH}: version {version} object"
    obj = _mapping(obj, where)
    _exact(
        obj,
        {"asset_sha256", "behaviour", "object_id", "origin", "region_id", "removed", "transform"},
        where,
    )
    if not isinstance(obj["object_id"], str) or not _OBJECT_ID.fullmatch(obj["object_id"]):
        raise ExtensionError(f"{where} id is outside the object id contract")
    where = f"{where} {obj['object_id']}"
    if obj["asset_sha256"] not in assets:
        raise ExtensionError(f"{where} names an asset the assets section does not list")
    if obj["region_id"] not in regions:
        raise ExtensionError(f"{where} is posed in a region its source snapshot does not have")
    if not isinstance(obj["removed"], bool):
        raise ExtensionError(f"{where} removed must be true or false")
    origin = _mapping(obj["origin"], where)
    if origin != {"kind": "authored", "role": origin.get("role")} or origin.get("role") not in {
        "fictional",
        "personal",
    }:
        raise ExtensionError(f"{where} origin must be authored, with a role the person chose")
    _verify_transform(where, obj["transform"])
    behaviour = obj["behaviour"]
    if behaviour is None:
        return
    behaviour = _mapping(behaviour, where)
    _exact(behaviour, {"behaviour_key", "behaviour_version", "parameters"}, where)
    descriptor = behaviours.get((behaviour["behaviour_key"], behaviour["behaviour_version"]))
    if descriptor is None:
        raise ExtensionError(f"{where} names a behaviour the behaviours section does not list")
    supplied = _mapping(behaviour["parameters"], where)
    bounds = descriptor["parameters"]
    if set(supplied) != set(bounds):
        raise ExtensionError(f"{where} behaviour parameters do not match the reviewed set")
    for key, bound in bounds.items():
        value = supplied[key]
        kind = bound["kind"]
        if (
            (
                kind == "integer"
                and not (_integer(value) and bound["minimum"] <= value <= bound["maximum"])
            )
            or (kind == "choice" and value not in bound["choices"])
            or (kind == "toggle" and not isinstance(value, bool))
        ):
            raise ExtensionError(f"{where} behaviour parameter {key} is outside its reviewed bound")


def _verify_transform(where: str, value: Any) -> None:
    transform = _mapping(value, where)
    _exact(
        transform,
        {
            "coordinate_space",
            "coordinate_unit",
            "scale_milli",
            "x_mm",
            "y_mm",
            "yaw_microradians",
            "z_mm",
        },
        f"{where} transform",
    )
    if (
        transform["coordinate_space"] != "region_local"
        or transform["coordinate_unit"] != "millimetre"
        or not all(_integer(transform[axis]) for axis in ("x_mm", "y_mm", "z_mm"))
        or not all(abs(transform[axis]) <= _MAX_TRANSLATION for axis in ("x_mm", "y_mm", "z_mm"))
        or not (
            _integer(transform["yaw_microradians"])
            and 0 <= transform["yaw_microradians"] <= _MAX_YAW
        )
        or not (_integer(transform["scale_milli"]) and 1 <= transform["scale_milli"] <= _MAX_SCALE)
    ):
        raise ExtensionError(f"{where} transform is outside the fixed-point contract")


def _verify_edits(version: Mapping[str, Any], objects: Sequence[Mapping[str, Any]]) -> None:
    """The edit chain must be contiguous and must end at the state the delta digests to.

    Each edit names the base it was made against, and the compare-and-swap that recorded it made
    that base the version's state at the time. So the chain is checkable offline: every base is
    the previous result, and the last result is the exported state. A version made from a source
    snapshot starts empty, so its first base is the empty delta's digest.
    """
    name = version["version_id"]
    edits = _list(version["edits"], f"{name}/edits")
    if len(edits) != version["edit_seq"]:
        raise ExtensionError(f"{VERSIONS_PATH}: version {name} edit_seq disagrees with its edits")
    previous = EMPTY_DELTA_SHA256 if version["parent_version_id"] is None else None
    seen: set[str] = set()
    for index, edit in enumerate(edits, start=1):
        edit = _mapping(edit, name)
        _exact(
            edit,
            {
                "base_state_sha256",
                "edit_id",
                "edit_seq",
                "element_id",
                "kind",
                "object_id",
                "recorded_at",
                "result_state_sha256",
                "undone_edit_id",
            },
            f"{name}/edits",
        )
        kind = edit["kind"]
        subject_ok = (
            (
                kind in _OBJECT_EDITS
                and isinstance(edit["object_id"], str)
                and edit["element_id"] is None
            )
            or (
                kind in _ELEMENT_EDITS
                and isinstance(edit["element_id"], str)
                and edit["object_id"] is None
            )
            or kind == "undo"
        )
        if (
            edit["edit_seq"] != index
            or kind not in _EDIT_KINDS
            or not subject_ok
            or not _urn_of(edit["edit_id"], "alternate-edit")
            or edit["edit_id"] in seen
            or not _hex64(edit["base_state_sha256"])
            or not _hex64(edit["result_state_sha256"])
            or not isinstance(edit["recorded_at"], str)
            or (kind == "undo") != (edit["undone_edit_id"] is not None)
            or (edit["undone_edit_id"] is not None and edit["undone_edit_id"] not in seen)
        ):
            raise ExtensionError(f"{VERSIONS_PATH}: version {name} edit {index} is malformed")
        if previous is not None and edit["base_state_sha256"] != previous:
            raise ExtensionError(
                f"{VERSIONS_PATH}: version {name} edit {index} was not made against the state "
                "before it"
            )
        previous = edit["result_state_sha256"]
        seen.add(edit["edit_id"])
    final = (
        previous
        if edits
        else (EMPTY_DELTA_SHA256 if version["parent_version_id"] is None else None)
    )
    if final is not None and final != version["state_sha256"]:
        raise ExtensionError(
            f"{VERSIONS_PATH}: version {name} edit chain does not end at its exported state"
        )


# ------------------------------------------------------------------------------------------
# What a loader may do with the section, given what it says it supports.
# ------------------------------------------------------------------------------------------


def loader_report(world: AuthoredWorld, capabilities: frozenset[str]) -> dict[str, Any]:
    """Name every part of the extension a loader with ``capabilities`` cannot present.

    Nothing here runs a loader. It compares a loader's declared capabilities with what the
    signed content needs, and says what the loader must then refuse, show as unsupported, or
    leave unloaded. A declared capability is the loader's claim, not something this proves.
    """
    required = world.declaration["required_loader_capabilities"]
    unsupported = sorted(set(required) - capabilities)
    counts = world.declaration["counts"]
    if EXTENSION_CAPABILITY not in capabilities:
        return {
            "load": "not loaded",
            "not_loaded": (
                f"this loader does not declare {EXTENSION_CAPABILITY}, so "
                f"{counts['alternate_versions']} alternate version(s) and "
                f"{counts['authored_objects_present']} present authored object(s) in this package "
                "are not loaded; the loader must say so rather than present the source world as "
                "the whole package"
            ),
            "objects_not_drawable": [],
            "objects_with_unsupported_behaviour": [],
            "required_capabilities": required,
            "unsupported_capabilities": unsupported,
        }
    not_drawable: list[dict[str, str]] = []
    unsupported_behaviour: list[dict[str, str]] = []
    for version in world.versions:
        for obj in version["delta"]["objects"]:
            if obj["removed"]:
                continue
            media = f"asset-media:{world.assets[obj['asset_sha256']]['media_type']}"
            missing = sorted({ASSET_RESOLUTION_CAPABILITY, media} - capabilities)
            if missing:
                not_drawable.append(
                    {
                        "missing": ", ".join(missing),
                        "object_id": obj["object_id"],
                        "version_id": version["version_id"],
                    }
                )
            behaviour = obj["behaviour"]
            if behaviour is not None:
                needed = f"behaviour:{behaviour['behaviour_key']}@{behaviour['behaviour_version']}"
                if needed not in capabilities:
                    unsupported_behaviour.append(
                        {
                            "behaviour": needed,
                            "object_id": obj["object_id"],
                            "shown_as": "present, with its behaviour marked unsupported",
                            "version_id": version["version_id"],
                        }
                    )
    return {
        "load": "loaded" if not unsupported else "loaded with unsupported parts named",
        "not_loaded": None,
        "objects_not_drawable": not_drawable,
        "objects_with_unsupported_behaviour": unsupported_behaviour,
        "required_capabilities": required,
        "unsupported_capabilities": unsupported,
    }


# ------------------------------------------------------------------------------------------
# Small strict readers.
# ------------------------------------------------------------------------------------------


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExtensionError(f"{where}: expected an object")
    return value


def _list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExtensionError(f"{where}: expected an array")
    return value


def _exact(value: Mapping[str, Any], keys: set[str], where: str) -> None:
    if set(value) != keys:
        raise ExtensionError(f"{where}: expected exactly {sorted(keys)}, found {sorted(value)}")


def _subset(value: Mapping[str, Any], keys: set[str], where: str) -> None:
    if not set(value) <= keys:
        raise ExtensionError(f"{where}: unexpected fields {sorted(set(value) - keys)}")


def _sorted_unique(values: list[Any], what: str, *, strings: bool = False) -> None:
    if not isinstance(values, list):
        raise ExtensionError(f"{what} must be an array")
    if strings and not all(isinstance(value, str) for value in values):
        raise ExtensionError(f"{what} must be strings")
    if any(value is None for value in values):
        raise ExtensionError(f"{what} is missing an identifier")
    if values != sorted(values) or len(set(values)) != len(values):
        raise ExtensionError(f"{what} must be unique and in sorted order")


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _natural(value: Any) -> bool:
    return _integer(value) and value >= 0


def _hex64(value: Any) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def _urn_of(value: Any, kind: str) -> bool:
    if not isinstance(value, str):
        return False
    match = _URN.fullmatch(value)
    return match is not None and match.group("kind") == kind
