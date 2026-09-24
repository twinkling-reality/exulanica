"""The environment-instances extension to WMP 1.0.

**Why a second extension.** Live authored state that includes ``environment_instances``
selects delta schema version 2. ``exulanica-wmp-ext-authored-world`` 1.0 freezes schema
version 1, re-derives ``state_sha256`` from that schema, and refuses any other edit kind.
Putting schema version 2 under that name would make every verifier that knows
authored-world 1.0 reject a sound package, or would force that verifier to accept
a document the 1.0 contract never named. An optional directory under
``extensions/`` breaks neither WMP 1.0 nor authored-world 1.0: a verifier that
predates this extension inventories the files, hashes them, scans them, and
checks the signature, and reports the directory as not checked.

**What the extension carries.** Every alternate version whose current delta includes environment
instances, or whose edit chain names an environment edit, provided its source snapshot is not
invalidated by deletion; every kept ancestor a parent pointer in that set needs; and every kept
descendant that cannot live in authored-world 1.0 because an ancestor is environment-bearing.
The directory is lineage-closed: a ``parent_version_id`` resolves here. A schema-v1 ancestor is
exported with its honest schema-v1 delta, not rewritten as schema version 2. The exported
``delta`` is the environment-inclusive document the product digests: schema version 2 with
``environment_instances`` when any instance remains, schema version 1 when the current state has
none. ``state_sha256`` re-derives from that document. Availability is stated beside each instance
and is not in the digest. Undone additions are omitted from the delta the same way authored-world
1.0 omits an undone object. Asset bytes, environment source bytes, and runtime code are not
embedded. A signed package does not grant compose, export, or reuse rights on a pinned source.

**What stays out of authored-world 1.0.** An environment-bearing version is absent from
``extensions/authored-world-1.0``. A schema-v1 descendant of such a version is absent there too,
because that parent cannot be written under the 1.0 name and a parent pointer must resolve in
the same directory. A schema-v1 ancestor required by an environment-bearing child remains in
authored-world 1.0 when that extension is requested, so 1.0 stays a complete schema-v1 subset,
and is also copied here so this directory verifies alone. A receiver that only declares
authored-world 1.0 must treat the versions that live only here as omitted, not infer objects
from the 1.0 directory as the whole authored state. Projecting ``authored-world-1.0`` alone
refuses when an environment-bearing version would otherwise be kept. Dual export does not write
an authored-world directory that lists zero versions while this directory holds the versions
that were moved.

**Two versions.** Environment-instances 1.1 admits ``set_object_behaviour``, like authored-world
1.1, and counts the versions it withholds by reason; its declaration names authored-world 1.1
where 1.0's names authored-world 1.0. Every function here takes the
:class:`~exulanica.world_package.extension_formats.ExtensionFormat` it builds or checks, and
:mod:`exulanica.world_package.export_partition` decides which versions each one writes.

**What is pure here.** This module imports nothing that opens a database. The digest is
re-derived with :func:`exulanica.canonical.canonical_json` alone.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.world_package.authored import (
    ASSET_RESOLUTION_CAPABILITY,
    ASSET_RETRIEVAL,
    EMPTY_DELTA_SHA256,
    ExtensionError,
    delta_sha256,
    ni_uri,
    verify_withheld,
    withheld_section,
)
from exulanica.world_package.extension_formats import (
    AUTHORED_WORLD_1_0,
    ENVIRONMENT_INSTANCES_1_0,
    UNDO,
    ExtensionFormat,
    counterpart,
)

#: The family whose directory this one is not, and whose objects a receiver must not take for
#: the whole authored state.
AUTHORED_WORLD: Final = AUTHORED_WORLD_1_0.family

#: The 1.0 names, which the command line, the 1.0 directory and earlier callers use. Every
#: function below takes the version it builds or checks.
EXTENSION_NAME: Final = ENVIRONMENT_INSTANCES_1_0.name
EXTENSION_VERSION: Final = ENVIRONMENT_INSTANCES_1_0.version
EXTENSION_KEY: Final = ENVIRONMENT_INSTANCES_1_0.key
EXTENSION_DIR: Final = ENVIRONMENT_INSTANCES_1_0.directory
EXTENSION_PROFILE_ID: Final = ENVIRONMENT_INSTANCES_1_0.profile_id
BASE_PROFILE: Final = "exulanica-wmp-1.0"
DECLARATION_PATH: Final = ENVIRONMENT_INSTANCES_1_0.declaration_path
VERSIONS_PATH: Final = ENVIRONMENT_INSTANCES_1_0.section_path("versions")
ASSETS_PATH: Final = ENVIRONMENT_INSTANCES_1_0.section_path("assets")
BEHAVIOURS_PATH: Final = ENVIRONMENT_INSTANCES_1_0.section_path("behaviours")
EXTENSION_PATHS: Final = ENVIRONMENT_INSTANCES_1_0.paths

EXTENSION_CAPABILITY: Final = ENVIRONMENT_INSTANCES_1_0.capability
ENVIRONMENT_SOURCE_CAPABILITY: Final = "environment-source:sha256-content-address"

ASSET_BYTES: Final = (
    "not embedded: each reviewed object asset is a SHA-256 content reference an authorized "
    "resolver must supply"
)
SOURCE_BYTES: Final = (
    "not embedded: each environment source, render and index is a SHA-256 content reference "
    "an authorized resolver must supply"
)
SOURCE_RIGHTS: Final = (
    "not granted: a signed package does not transfer compose, export or reuse rights on a "
    "pinned environment source"
)
RUNTIME_CODE: Final = (
    "not carried: a behaviour is a reviewed identifier with bounded parameters, and a runtime "
    "that does not support it must show it as unsupported"
)
COORDINATE_SPACE: Final = (
    "region_local: compose each instance and object transform with its region's placement in "
    "world/placement.json"
)
AVAILABILITY_RULE: Final = (
    "stated beside each instance and not part of state_sha256; a blob disappearing must not "
    "pretend the person authored a new version"
)


def delta_rule(format_: ExtensionFormat) -> str:
    """What the exported delta is, naming the authored-world directory of the same version."""
    return (
        "the environment-inclusive authored delta: schema version 2 when environment_instances "
        "are present, schema version 1 when they are not. This directory is not "
        f"{counterpart(AUTHORED_WORLD, format_.version).directory}"
    )


def omission_rule(format_: ExtensionFormat) -> str:
    """What a receiver without this extension must do, naming authored-world of the same version."""
    authored_world = counterpart(AUTHORED_WORLD, format_.version)
    return (
        "a receiver that does not declare this extension must omit these versions and must not "
        f"infer objects from {authored_world.name}@{authored_world.version} as the whole "
        "authored state"
    )


DELTA_RULE: Final = delta_rule(ENVIRONMENT_INSTANCES_1_0)
OMISSION_RULE: Final = omission_rule(ENVIRONMENT_INSTANCES_1_0)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_URN = re.compile(r"^urn:exulanica:wmp:(?P<kind>[a-z-]+):[0-9a-f]{64}$")
_OBJECT_ID = re.compile("^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_AVAILABILITIES: Final = frozenset(
    {"available", "unavailable_bytes", "withdrawn", "binding_drift", "unknown"}
)
_MAX_YAW: Final = 6_283_185
_MAX_SCALE: Final = 1_000_000
_MAX_TRANSLATION: Final = 1_000_000_000


class EnvironmentExtensionError(ExtensionError):
    """The environment-instances extension is inconsistent with its own rules."""


@dataclass(frozen=True, slots=True)
class EnvironmentInstances:
    """The extension's sections after verification, for a loader that supports it."""

    declaration: Mapping[str, Any]
    versions: tuple[Mapping[str, Any], ...]
    assets: Mapping[str, Mapping[str, Any]]
    behaviours: Mapping[tuple[str, int], Mapping[str, Any]]
    source_snapshots: Mapping[str, Mapping[str, Any]]
    withheld_versions: int
    #: The extension version these sections were checked against.
    format: ExtensionFormat


def required_loader_capabilities(
    format_: ExtensionFormat,
    versions: Iterable[Mapping[str, Any]],
    assets: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """What a loader must support to present every instance and object this extension exports.

    A removed instance or object is part of the state digest and is not drawn, so it requires
    nothing. Availability is not a capability: withdrawn and unavailable instances stay named.
    """
    required = {format_.capability}
    for version in versions:
        delta = version["delta"]
        for obj in delta["objects"]:
            if obj["removed"]:
                continue
            required.add(ASSET_RESOLUTION_CAPABILITY)
            required.add(f"asset-media:{assets[obj['asset_sha256']]['media_type']}")
            if obj["behaviour"] is not None:
                behaviour = obj["behaviour"]
                required.add(
                    f"behaviour:{behaviour['behaviour_key']}@{behaviour['behaviour_version']}"
                )
        for instance in delta.get("environment_instances", ()):
            if not instance["removed"]:
                required.add(ENVIRONMENT_SOURCE_CAPABILITY)
    return sorted(required)


def declaration(
    format_: ExtensionFormat,
    versions: Sequence[Mapping[str, Any]],
    assets: Mapping[str, Mapping[str, Any]],
    *,
    withheld_versions: int,
) -> dict[str, Any]:
    objects = [obj for version in versions for obj in version["delta"]["objects"]]
    instances = [
        instance
        for version in versions
        for instance in version["delta"].get("environment_instances", ())
    ]
    return {
        "@id": format_.profile_id,
        "asset_bytes": ASSET_BYTES,
        "availability": AVAILABILITY_RULE,
        "base_profile": BASE_PROFILE,
        "coordinate_space": COORDINATE_SPACE,
        "counts": {
            "alternate_versions": len(versions),
            "authored_objects": len(objects),
            "authored_objects_present": sum(1 for obj in objects if not obj["removed"]),
            "environment_instances": len(instances),
            "environment_instances_present": sum(
                1 for instance in instances if not instance["removed"]
            ),
            "withheld_versions": withheld_versions,
        },
        "delta": delta_rule(format_),
        "extension": format_.name,
        "extension_version": format_.version,
        "omission": omission_rule(format_),
        "required_loader_capabilities": required_loader_capabilities(format_, versions, assets),
        "runtime_code": RUNTIME_CODE,
        "sections": {
            section: format_.section_path(section) for section in format_.section_profiles
        },
        "source_bytes": SOURCE_BYTES,
        "source_rights": SOURCE_RIGHTS,
    }


def build_sections(
    format_: ExtensionFormat,
    *,
    versions: Sequence[Mapping[str, Any]],
    source_snapshots: Sequence[Mapping[str, Any]],
    assets: Sequence[Mapping[str, Any]],
    behaviours: Sequence[Mapping[str, Any]],
    withheld: Sequence[tuple[str, Sequence[str]]],
) -> dict[str, dict[str, Any]]:
    """Assemble the four extension documents in the one order the verifier accepts.

    ``withheld`` holds one ``(reason, names)`` pair for every version this extension counts and
    does not carry.
    """
    ordered_versions = sorted(versions, key=lambda item: item["version_id"])
    ordered_assets = sorted(assets, key=lambda item: item["content_sha256"])
    by_digest = {item["content_sha256"]: item for item in ordered_assets}
    return {
        format_.section_path("assets"): {
            "items": ordered_assets,
            "profile": format_.section_profiles["assets"],
        },
        format_.section_path("behaviours"): {
            "items": sorted(
                behaviours, key=lambda item: (item["behaviour_key"], item["behaviour_version"])
            ),
            "profile": format_.section_profiles["behaviours"],
        },
        format_.declaration_path: declaration(
            format_, ordered_versions, by_digest, withheld_versions=len(withheld)
        ),
        format_.section_path("versions"): {
            "items": ordered_versions,
            "profile": format_.section_profiles["versions"],
            "source_snapshots": sorted(source_snapshots, key=lambda item: item["snapshot_id"]),
            "withheld": withheld_section(format_, withheld),
        },
    }


def verify_environment_instances(
    format_: ExtensionFormat, files: Mapping[str, Any], inventory: Iterable[str]
) -> EnvironmentInstances:
    """Check the extension against its version's rules and against the 1.0 structure beside it."""
    directory = format_.directory
    versions_path = format_.section_path("versions")
    present = {path for path in inventory if path.startswith(f"{directory}/")}
    if present != format_.paths:
        raise EnvironmentExtensionError(
            f"{directory} must hold exactly {sorted(format_.paths)}, found {sorted(present)}"
        )
    assets = _verify_assets(format_, files[format_.section_path("assets")])
    behaviours = _verify_behaviours(format_, files[format_.section_path("behaviours")])
    document = _mapping(files[versions_path], versions_path)
    _exact(document, {"items", "profile", "source_snapshots", "withheld"}, versions_path)
    if document["profile"] != format_.section_profiles["versions"]:
        raise EnvironmentExtensionError(f"{versions_path}: unknown section profile")
    snapshots = _verify_source_snapshots(format_, document["source_snapshots"], files)
    withheld_count = verify_withheld(
        format_, document["withheld"], f"{versions_path}/withheld", EnvironmentExtensionError
    )
    versions = _list(document["items"], f"{versions_path}/items")
    _sorted_unique([_mapping(v, versions_path).get("version_id") for v in versions], "versions")
    by_id = {version["version_id"]: version for version in versions}
    referenced_assets: set[str] = set()
    referenced_behaviours: set[tuple[str, int]] = set()
    for version in versions:
        _verify_version(format_, version, by_id, snapshots, assets, behaviours)
        for obj in version["delta"]["objects"]:
            referenced_assets.add(obj["asset_sha256"])
            if obj["behaviour"] is not None:
                referenced_behaviours.add(
                    (obj["behaviour"]["behaviour_key"], obj["behaviour"]["behaviour_version"])
                )
    if referenced_assets != set(assets):
        raise EnvironmentExtensionError(
            f"{format_.section_path('assets')} must list exactly the assets an object references"
        )
    if referenced_behaviours != set(behaviours):
        raise EnvironmentExtensionError(
            f"{format_.section_path('behaviours')} must list exactly the behaviours an object "
            "references"
        )
    referenced_snapshots = {version["source_snapshot_id"] for version in versions}
    if referenced_snapshots != set(snapshots):
        raise EnvironmentExtensionError(
            f"{versions_path}: source_snapshots must be exactly those a version names"
        )
    expected = declaration(format_, versions, assets, withheld_versions=withheld_count)
    if files[format_.declaration_path] != expected:
        raise EnvironmentExtensionError(
            f"{format_.declaration_path} does not match the sections it declares; a declaration "
            "that understates what a loader needs would let a runtime drop content silently"
        )
    return EnvironmentInstances(
        declaration=expected,
        versions=tuple(versions),
        assets=assets,
        behaviours=behaviours,
        source_snapshots=snapshots,
        withheld_versions=withheld_count,
        format=format_,
    )


def loader_report(world: EnvironmentInstances, capabilities: frozenset[str]) -> dict[str, Any]:
    """Name every part of the extension a loader with ``capabilities`` cannot present.

    Nothing here runs a loader. A loader without this capability must omit these versions and
    must not treat the authored-world objects of the same version as the whole authored state.
    """
    required = world.declaration["required_loader_capabilities"]
    unsupported = sorted(set(required) - capabilities)
    counts = world.declaration["counts"]
    if world.format.capability not in capabilities:
        return {
            "instances_not_drawable": [],
            "instances_unavailable": [],
            "load": "not loaded",
            "not_loaded": (
                f"this loader does not declare {world.format.capability}, so "
                f"{counts['alternate_versions']} alternate version(s) and "
                f"{counts['environment_instances_present']} present environment instance(s) "
                "in this package are not loaded; the loader must say so rather than infer "
                f"objects from {_authored_capability_name(world.format)} as the whole authored "
                "state"
            ),
            "objects_not_drawable": [],
            "objects_with_unsupported_behaviour": [],
            "required_capabilities": required,
            "unsupported_capabilities": unsupported,
        }
    not_drawable: list[dict[str, str]] = []
    unsupported_behaviour: list[dict[str, str]] = []
    instances_not_drawable: list[dict[str, str]] = []
    instances_unavailable: list[dict[str, str]] = []
    for version in world.versions:
        availability = {
            item["instance_id"]: item["availability"]
            for item in version["environment_availability"]
        }
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
        for instance in version["delta"].get("environment_instances", ()):
            if instance["removed"]:
                continue
            state = availability[instance["instance_id"]]
            if state != "available":
                instances_unavailable.append(
                    {
                        "availability": state,
                        "instance_id": instance["instance_id"],
                        "version_id": version["version_id"],
                    }
                )
            if ENVIRONMENT_SOURCE_CAPABILITY not in capabilities:
                instances_not_drawable.append(
                    {
                        "missing": ENVIRONMENT_SOURCE_CAPABILITY,
                        "instance_id": instance["instance_id"],
                        "version_id": version["version_id"],
                    }
                )
    return {
        "instances_not_drawable": instances_not_drawable,
        "instances_unavailable": instances_unavailable,
        "load": "loaded" if not unsupported else "loaded with unsupported parts named",
        "not_loaded": None,
        "objects_not_drawable": not_drawable,
        "objects_with_unsupported_behaviour": unsupported_behaviour,
        "required_capabilities": required,
        "unsupported_capabilities": unsupported,
    }


def _authored_capability_name(format_: ExtensionFormat) -> str:
    authored_world = counterpart(AUTHORED_WORLD, format_.version)
    return f"{authored_world.name}@{authored_world.version}"


def _verify_assets(format_: ExtensionFormat, value: Any) -> dict[str, Mapping[str, Any]]:
    assets_path = format_.section_path("assets")
    document = _mapping(value, assets_path)
    _exact(document, {"items", "profile"}, assets_path)
    if document["profile"] != format_.section_profiles["assets"]:
        raise EnvironmentExtensionError(f"{assets_path}: unknown section profile")
    items = _list(document["items"], assets_path)
    digests = []
    for item in items:
        item = _mapping(item, assets_path)
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
            assets_path,
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
            raise EnvironmentExtensionError(
                f"{assets_path}: asset {item.get('asset_key')!r} is malformed"
            )
        digests.append(digest)
    _sorted_unique(digests, "assets")
    return {item["content_sha256"]: item for item in items}


def _verify_behaviours(
    format_: ExtensionFormat, value: Any
) -> dict[tuple[str, int], Mapping[str, Any]]:
    behaviours_path = format_.section_path("behaviours")
    document = _mapping(value, behaviours_path)
    _exact(document, {"items", "profile"}, behaviours_path)
    if document["profile"] != format_.section_profiles["behaviours"]:
        raise EnvironmentExtensionError(f"{behaviours_path}: unknown section profile")
    items = _list(document["items"], behaviours_path)
    keys: list[tuple[str, int]] = []
    for item in items:
        item = _mapping(item, behaviours_path)
        _exact(
            item, {"behaviour_key", "behaviour_version", "parameters", "summary"}, behaviours_path
        )
        if (
            not isinstance(item["behaviour_key"], str)
            or not _natural(item["behaviour_version"])
            or item["behaviour_version"] < 1
            or not isinstance(item["summary"], str)
        ):
            raise EnvironmentExtensionError(f"{behaviours_path}: behaviour is malformed")
        parameters = _mapping(item["parameters"], behaviours_path)
        for name, bound in parameters.items():
            _verify_bound(behaviours_path, item["behaviour_key"], name, bound)
        keys.append((item["behaviour_key"], item["behaviour_version"]))
    _sorted_unique(keys, "behaviours")
    return {(item["behaviour_key"], item["behaviour_version"]): item for item in items}


def _verify_bound(behaviours_path: str, behaviour: str, name: str, bound: Any) -> None:
    where = f"{behaviours_path}: {behaviour} parameter {name}"
    bound = _mapping(bound, where)
    kind = bound.get("kind")
    if kind == "integer":
        _subset(bound, {"kind", "minimum", "maximum", "default"}, where)
        low, high = bound.get("minimum"), bound.get("maximum")
        if not (_integer(low) and _integer(high) and low <= high):
            raise EnvironmentExtensionError(f"{where}: integer bounds are malformed")
        if "default" in bound and not (
            _integer(bound["default"]) and low <= bound["default"] <= high
        ):
            raise EnvironmentExtensionError(f"{where}: default is outside its bounds")
    elif kind == "choice":
        _subset(bound, {"kind", "choices", "default"}, where)
        choices = bound.get("choices")
        if (
            not isinstance(choices, list)
            or len(choices) < 2
            or not all(isinstance(choice, str) for choice in choices)
            or len(set(choices)) != len(choices)
        ):
            raise EnvironmentExtensionError(f"{where}: choices are malformed")
        if "default" in bound and bound["default"] not in choices:
            raise EnvironmentExtensionError(f"{where}: default is not a choice")
    elif kind == "toggle":
        _subset(bound, {"kind", "default"}, where)
        if "default" in bound and not isinstance(bound["default"], bool):
            raise EnvironmentExtensionError(f"{where}: default is not true or false")
    else:
        raise EnvironmentExtensionError(f"{where}: unreviewed parameter kind {kind!r}")


def _verify_source_snapshots(
    format_: ExtensionFormat, value: Any, files: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    versions_path = format_.section_path("versions")
    items = _list(value, f"{versions_path}/source_snapshots")
    structure = files.get("world/structure.json")
    topology = files.get("world/topology.json")
    ids = []
    current = []
    for item in items:
        item = _mapping(item, versions_path)
        _exact(
            item,
            {"current", "element_ids", "region_ids", "snapshot_id", "snapshot_sha256"},
            f"{versions_path}/source_snapshots",
        )
        if (
            not _urn_of(item["snapshot_id"], "structure")
            or not _hex64(item["snapshot_sha256"])
            or not isinstance(item["current"], bool)
        ):
            raise EnvironmentExtensionError(f"{versions_path}: a source snapshot is malformed")
        _sorted_unique(item["region_ids"], "source snapshot region_ids", strings=True)
        _sorted_unique(item["element_ids"], "source snapshot element_ids", strings=True)
        if item["current"]:
            current.append(item)
        ids.append(item["snapshot_id"])
    _sorted_unique(ids, "source snapshots")
    if len(current) > 1:
        raise EnvironmentExtensionError(
            f"{versions_path}: more than one source snapshot claims to be current"
        )
    for item in current:
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
            raise EnvironmentExtensionError(
                f"{versions_path}: the current source snapshot disagrees with world/structure.json "
                "or world/topology.json"
            )
    return {item["snapshot_id"]: item for item in items}


def _verify_version(
    format_: ExtensionFormat,
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
            "environment_availability",
            "origin",
            "parent_version_id",
            "source_snapshot_id",
            "state_sha256",
            "style_version_id",
            "title",
            "version_id",
        },
        format_.section_path("versions"),
    )
    versions_path = format_.section_path("versions")
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
        raise EnvironmentExtensionError(f"{versions_path}: version {name} is malformed")
    source = snapshots.get(version["source_snapshot_id"])
    if source is None:
        raise EnvironmentExtensionError(
            f"{versions_path}: version {name} names a source snapshot not listed"
        )
    parent = version["parent_version_id"]
    if parent is not None:
        if (
            parent not in by_id
            or by_id[parent]["source_snapshot_id"] != version["source_snapshot_id"]
        ):
            raise EnvironmentExtensionError(
                f"{versions_path}: version {name} names a parent not in this package or on "
                "another source snapshot"
            )
        seen = {name}
        cursor = parent
        while cursor is not None:
            if cursor in seen:
                raise EnvironmentExtensionError(
                    f"{versions_path}: version lineage has a cycle at {name}"
                )
            seen.add(cursor)
            cursor = by_id[cursor]["parent_version_id"]
    delta = _mapping(version["delta"], f"{versions_path}/{name}/delta")
    schema = delta.get("schema_version")
    if schema == 1:
        _exact(delta, {"element_overrides", "objects", "schema_version"}, f"{name}/delta")
        instances: list[Any] = []
    elif schema == 2:
        _exact(
            delta,
            {"element_overrides", "environment_instances", "objects", "schema_version"},
            f"{name}/delta",
        )
        instances = _list(delta["environment_instances"], f"{name}/delta/environment_instances")
        if not instances:
            raise EnvironmentExtensionError(
                f"{versions_path}: version {name} schema version 2 requires environment_instances"
            )
    else:
        raise EnvironmentExtensionError(
            f"{versions_path}: version {name} has an unknown delta schema"
        )
    objects = _list(delta["objects"], f"{name}/delta/objects")
    _sorted_unique([_mapping(o, name).get("object_id") for o in objects], "objects", strings=True)
    regions = set(source["region_ids"])
    for obj in objects:
        _verify_object(versions_path, name, obj, regions, assets, behaviours)
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
            raise EnvironmentExtensionError(
                f"{versions_path}: version {name} has a malformed override"
            )
        if override["transform"] is not None:
            _verify_transform(name, override["transform"])
    instance_ids = [_mapping(item, name).get("instance_id") for item in instances]
    _sorted_unique(instance_ids, "environment instances", strings=True)
    for instance in instances:
        _verify_instance(versions_path, name, instance, regions)
    if delta_sha256(delta) != version["state_sha256"]:
        raise EnvironmentExtensionError(
            f"{versions_path}: version {name} state_sha256 does not re-derive from its "
            "environment-inclusive delta"
        )
    _verify_availability(versions_path, name, version["environment_availability"], instance_ids)
    _verify_edits(format_, version)


def _verify_object(
    versions_path: str,
    version: str,
    obj: Any,
    regions: set[str],
    assets: Mapping[str, Mapping[str, Any]],
    behaviours: Mapping[tuple[str, int], Mapping[str, Any]],
) -> None:
    where = f"{versions_path}: version {version} object"
    obj = _mapping(obj, where)
    _exact(
        obj,
        {"asset_sha256", "behaviour", "object_id", "origin", "region_id", "removed", "transform"},
        where,
    )
    if not isinstance(obj["object_id"], str) or not _OBJECT_ID.fullmatch(obj["object_id"]):
        raise EnvironmentExtensionError(f"{where} id is outside the object id contract")
    where = f"{where} {obj['object_id']}"
    if obj["asset_sha256"] not in assets:
        raise EnvironmentExtensionError(f"{where} names an asset the assets section does not list")
    if obj["region_id"] not in regions:
        raise EnvironmentExtensionError(
            f"{where} is posed in a region its source snapshot does not have"
        )
    if not isinstance(obj["removed"], bool):
        raise EnvironmentExtensionError(f"{where} removed must be true or false")
    _verify_origin(where, obj["origin"])
    _verify_transform(where, obj["transform"])
    behaviour = obj["behaviour"]
    if behaviour is None:
        return
    behaviour = _mapping(behaviour, where)
    _exact(behaviour, {"behaviour_key", "behaviour_version", "parameters"}, where)
    descriptor = behaviours.get((behaviour["behaviour_key"], behaviour["behaviour_version"]))
    if descriptor is None:
        raise EnvironmentExtensionError(
            f"{where} names a behaviour the behaviours section does not list"
        )
    supplied = _mapping(behaviour["parameters"], where)
    bounds = descriptor["parameters"]
    if set(supplied) != set(bounds):
        raise EnvironmentExtensionError(
            f"{where} behaviour parameters do not match the reviewed set"
        )
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
            raise EnvironmentExtensionError(
                f"{where} behaviour parameter {key} is outside its reviewed bound"
            )


def _verify_instance(versions_path: str, version: str, instance: Any, regions: set[str]) -> None:
    where = f"{versions_path}: version {version} environment instance"
    instance = _mapping(instance, where)
    _exact(
        instance,
        {"instance_id", "origin", "region_id", "removed", "source", "transform"},
        where,
    )
    if not isinstance(instance["instance_id"], str) or not _OBJECT_ID.fullmatch(
        instance["instance_id"]
    ):
        raise EnvironmentExtensionError(f"{where} id is outside the instance id contract")
    where = f"{where} {instance['instance_id']}"
    if instance["region_id"] not in regions:
        raise EnvironmentExtensionError(
            f"{where} is posed in a region its source snapshot does not have"
        )
    if not isinstance(instance["removed"], bool):
        raise EnvironmentExtensionError(f"{where} removed must be true or false")
    _verify_origin(where, instance["origin"])
    _verify_transform(where, instance["transform"])
    _verify_source(where, instance["source"])


def _verify_source(where: str, value: Any) -> None:
    source = _mapping(value, f"{where} source")
    _exact(
        source,
        {
            "admission_id",
            "anchor",
            "bounds",
            "frame",
            "index",
            "place_id",
            "render_asset",
            "selection",
            "source",
        },
        f"{where} source",
    )
    if not _uuid(source["admission_id"]) or not _uuid(source["place_id"]):
        raise EnvironmentExtensionError(f"{where} source identifiers are malformed")
    render = _mapping(source["render_asset"], f"{where} render_asset")
    _exact(render, {"asset_id", "content_sha256", "receipt_sha256"}, f"{where} render_asset")
    if (
        not _uuid(render["asset_id"])
        or not _hex64(render["content_sha256"])
        or not _hex64(render["receipt_sha256"])
    ):
        raise EnvironmentExtensionError(f"{where} render_asset is malformed")
    pinned = _mapping(source["source"], f"{where} source bytes")
    _exact(pinned, {"content_sha256", "receipt_sha256"}, f"{where} source bytes")
    if not _hex64(pinned["content_sha256"]) or not _hex64(pinned["receipt_sha256"]):
        raise EnvironmentExtensionError(f"{where} source bytes are malformed")
    if not isinstance(source["frame"], Mapping) or not isinstance(source["bounds"], Mapping):
        raise EnvironmentExtensionError(f"{where} frame and bounds must be objects")
    anchor = _mapping(source["anchor"], f"{where} anchor")
    _exact(anchor, {"coordinate_scale", "coordinates", "frame_name"}, f"{where} anchor")
    coordinates = anchor["coordinates"]
    if (
        not isinstance(anchor["frame_name"], str)
        or not anchor["frame_name"]
        or not _natural(anchor["coordinate_scale"])
        or anchor["coordinate_scale"] == 0
        or not isinstance(coordinates, list)
        or not coordinates
        or not all(_integer(value) for value in coordinates)
    ):
        raise EnvironmentExtensionError(f"{where} anchor is malformed")
    selection = _mapping(source["selection"], f"{where} selection")
    _exact(selection, {"feature_id", "kind", "render_batch_id"}, f"{where} selection")
    kind = selection["kind"]
    index = source["index"]
    if kind == "whole_asset":
        if (
            selection["feature_id"] is not None
            or selection["render_batch_id"] is not None
            or index is not None
        ):
            raise EnvironmentExtensionError(f"{where} whole-asset placement cannot name a feature")
        return
    if kind != "feature":
        raise EnvironmentExtensionError(f"{where} selection kind is unreviewed")
    index = _mapping(index, f"{where} index")
    _exact(
        index,
        {
            "content_sha256",
            "publication_id",
            "publication_receipt_sha256",
            "receipt_sha256",
        },
        f"{where} index",
    )
    if (
        not isinstance(selection["feature_id"], str)
        or not _HEX32.fullmatch(selection["feature_id"])
        or not _natural(selection["render_batch_id"])
        or not _uuid(index["publication_id"])
        or not _hex64(index["content_sha256"])
        or not _hex64(index["publication_receipt_sha256"])
        or not _hex64(index["receipt_sha256"])
    ):
        raise EnvironmentExtensionError(f"{where} feature placement is malformed")


def _verify_availability(
    versions_path: str, version: str, value: Any, instance_ids: Sequence[Any]
) -> None:
    items = _list(value, f"{version}/environment_availability")
    seen: list[str] = []
    for item in items:
        item = _mapping(item, f"{version}/environment_availability")
        _exact(item, {"availability", "instance_id"}, f"{version}/environment_availability")
        if item["availability"] not in _AVAILABILITIES or not isinstance(item["instance_id"], str):
            raise EnvironmentExtensionError(
                f"{versions_path}: version {version} environment availability is malformed"
            )
        seen.append(item["instance_id"])
    if seen != list(instance_ids):
        raise EnvironmentExtensionError(
            f"{versions_path}: version {version} environment_availability must name exactly "
            "the exported instances, in the same order"
        )


def _verify_edits(format_: ExtensionFormat, version: Mapping[str, Any]) -> None:
    versions_path = format_.section_path("versions")
    name = version["version_id"]
    edits = _list(version["edits"], f"{name}/edits")
    if len(edits) != version["edit_seq"]:
        raise EnvironmentExtensionError(
            f"{versions_path}: version {name} edit_seq disagrees with its edits"
        )
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
                "environment_instance_id",
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
                kind in format_.kinds_changing("object")
                and isinstance(edit["object_id"], str)
                and edit["element_id"] is None
                and edit["environment_instance_id"] is None
            )
            or (
                kind in format_.kinds_changing("element")
                and isinstance(edit["element_id"], str)
                and edit["object_id"] is None
                and edit["environment_instance_id"] is None
            )
            or (
                kind in format_.kinds_changing("environment_instance")
                and isinstance(edit["environment_instance_id"], str)
                and edit["object_id"] is None
                and edit["element_id"] is None
            )
            or kind == UNDO
        )
        if (
            edit["edit_seq"] != index
            or kind not in format_.admitted_kinds
            or not subject_ok
            or not _urn_of(edit["edit_id"], "alternate-edit")
            or edit["edit_id"] in seen
            or not _hex64(edit["base_state_sha256"])
            or not _hex64(edit["result_state_sha256"])
            or not isinstance(edit["recorded_at"], str)
            or (kind == UNDO) != (edit["undone_edit_id"] is not None)
            or (edit["undone_edit_id"] is not None and edit["undone_edit_id"] not in seen)
        ):
            raise EnvironmentExtensionError(
                f"{versions_path}: version {name} edit {index} is malformed"
            )
        if previous is not None and edit["base_state_sha256"] != previous:
            raise EnvironmentExtensionError(
                f"{versions_path}: version {name} edit {index} was not made against the state "
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
        raise EnvironmentExtensionError(
            f"{versions_path}: version {name} edit chain does not end at its exported state"
        )


def _verify_origin(where: str, value: Any) -> None:
    origin = _mapping(value, where)
    if origin != {"kind": "authored", "role": origin.get("role")} or origin.get("role") not in {
        "fictional",
        "personal",
    }:
        raise EnvironmentExtensionError(
            f"{where} origin must be authored, with a role the person chose"
        )


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
        raise EnvironmentExtensionError(f"{where} transform is outside the fixed-point contract")


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EnvironmentExtensionError(f"{where}: expected an object")
    return value


def _list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise EnvironmentExtensionError(f"{where}: expected an array")
    return value


def _exact(value: Mapping[str, Any], keys: set[str], where: str) -> None:
    if set(value) != keys:
        raise EnvironmentExtensionError(
            f"{where}: expected exactly {sorted(keys)}, found {sorted(value)}"
        )


def _subset(value: Mapping[str, Any], keys: set[str], where: str) -> None:
    if not set(value) <= keys:
        raise EnvironmentExtensionError(f"{where}: unexpected fields {sorted(set(value) - keys)}")


def _sorted_unique(values: list[Any], what: str, *, strings: bool = False) -> None:
    if not isinstance(values, list):
        raise EnvironmentExtensionError(f"{what} must be an array")
    if strings and not all(isinstance(value, str) for value in values):
        raise EnvironmentExtensionError(f"{what} must be strings")
    if any(value is None for value in values):
        raise EnvironmentExtensionError(f"{what} is missing an identifier")
    if values != sorted(values) or len(set(values)) != len(values):
        raise EnvironmentExtensionError(f"{what} must be unique and in sorted order")


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _natural(value: Any) -> bool:
    return _integer(value) and value >= 0


def _hex64(value: Any) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def _uuid(value: Any) -> bool:
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def _urn_of(value: Any, kind: str) -> bool:
    if not isinstance(value, str):
        return False
    match = _URN.fullmatch(value)
    return match is not None and match.group("kind") == kind
