"""The traffic catalogs: vehicle classes, right-of-way policies, signal plans and access mappings.

Every number the simulation uses about a vehicle, a rule or a signal comes from one of the
versioned files under ``assets/catalogs/traffic``. None is a constant in code. Two of the files
map the city's own keys to vehicle classes: ``lane-use-access`` says which classes a lane of each
lane use carries (none for a lane that carries no traffic), and ``parking-kind-access`` which
classes a parking space of each kind admits. The city records carry the keys; traffic owns what
they admit.

**Envelope.** ``schema_version`` (1), ``catalog_id``, ``catalog_version``, ``references`` and
``entries``, and nothing else. The id and version match the file name, the same rule the grammar
catalogs follow. ``references`` maps a short id to the full citation of a source that was read.

**Sources.** Every entry has a ``sources`` object naming each numeric field (and each
presentation key list) exactly once. A value is either ``"cited <ref>[ and <ref>]: <where>"``,
where every ``<ref>`` is a key of ``references``, or ``"declared: <reason>"``. A missing, extra
or unparseable source is refused, so a number cannot be added without saying where it came from.
:func:`declared_values` lists the declared ones for review.

**Licence.** The same :class:`~exulanica.grammar.catalogs.Licence` object as the grammar
catalogs. Entries are authored here, so they are ``original`` and Apache-2.0; the facts they
cite are facts, and the citation says where they were read.

**Digest.** :func:`catalogs_digest` covers the canonical form of all five catalogs, references
and sources included, so changing a citation changes the digest. :attr:`TrafficCatalogs.file_sha256`
keeps the SHA-256 of each file's bytes, because a city signal record names the signal-plan catalog
by that byte digest.

The directory is found relative to this source file, so it exists in a checkout.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.catalogs import Licence
from exulanica.grammar.documents import read_json, split_versioned_name
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.records import KEY_PATTERN
from exulanica.traffic.errors import TrafficCatalogError

__all__ = [
    "CATALOG_DIRECTORY",
    "POLICY_RULES",
    "SIGNAL_GROUP_KINDS",
    "TURNS",
    "AccessMapping",
    "RightOfWayPolicy",
    "SignalGroupSpec",
    "SignalInterval",
    "SignalPlan",
    "TrafficCatalogs",
    "VehicleClass",
    "catalogs_digest",
    "declared_values",
    "load_traffic_catalogs",
]

CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "traffic")
)

#: The movements a lane connection can make, in the city vocabulary's spelling.
TURNS: Final = ("left", "straight", "right", "u_turn")
#: How a junction decides who goes. Each is implemented in :mod:`exulanica.traffic.simulation`.
POLICY_RULES: Final = ("signal", "priority", "all_way_stop", "uncontrolled")
ARRIVAL_ORDERS: Final = ("not_applicable", "first_stopped_first_served")
APPROACH_CONTROLS: Final = ("priority", "signal", "stop", "yield")
DRIVING_SIDES: Final = ("right", "left")
SIGNAL_GROUP_KINDS: Final = ("vehicle", "pedestrian")
#: The gap-acceptance movements a policy may give a critical headway for.
HEADWAY_MOVEMENTS: Final = (
    "major_left",
    "minor_left",
    "minor_right",
    "minor_through",
    "permitted_left",
)

_ENVELOPE: Final = frozenset(
    {"schema_version", "catalog_id", "catalog_version", "references", "entries"}
)
_SOURCE: Final = re.compile(
    r"cited ([a-z][a-z0-9_]*(?: and [a-z][a-z0-9_]*)*): \S.*|declared: \S.*"
)
_FILES: Final = {
    "vehicle-class": "vehicle-class.v1.json",
    "right-of-way-policy": "right-of-way-policy.v1.json",
    "signal-plan": "signal-plan.v1.json",
    "lane-use-access": "lane-use-access.v1.json",
    "parking-kind-access": "parking-kind-access.v1.json",
}


def _fail(where: str, message: str) -> TrafficCatalogError:
    return TrafficCatalogError(f"{where}: {message}")


def _int(where: str, value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _fail(where, f"is an int in [{minimum}, {maximum}], got {value!r}")
    return value


def _text(where: str, value: object) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise _fail(where, "is non-empty text with no surrounding space")
    return value


def _key(where: str, value: object) -> str:
    if type(value) is not str or KEY_PATTERN.fullmatch(value) is None:
        raise _fail(where, f"is a lowercase key, got {value!r}")
    return value


def _choice(where: str, value: object, options: tuple[str, ...]) -> str:
    if value not in options:
        raise _fail(where, f"is one of {options}, got {value!r}")
    return value  # type: ignore[return-value]


def _keys(
    where: str, value: object, *, options: tuple[str, ...] | None = None, empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not empty):
        raise _fail(where, "is a non-empty list of keys" if not empty else "is a list of keys")
    keys = tuple(
        _choice(f"{where}[{index}]", item, options)
        if options is not None
        else _key(f"{where}[{index}]", item)
        for index, item in enumerate(value)
    )
    if len(set(keys)) != len(keys):
        raise _fail(where, "repeats a key")
    if options is None and list(keys) != sorted(keys):
        raise _fail(where, "is sorted")
    if options is not None and list(keys) != sorted(keys, key=options.index):
        raise _fail(where, f"is in the order {options}")
    return keys


def _object(where: str, value: object, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(where, "is an object")
    unknown, missing = set(value) - keys, keys - set(value)
    if unknown or missing:
        raise _fail(where, f"unknown keys {sorted(unknown)}, missing keys {sorted(missing)}")
    return value


def _sources(
    where: str, value: object, required: set[str], references: Mapping[str, str]
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        raise _fail(where, "is an object naming a source for every value")
    unknown, missing = set(value) - required, required - set(value)
    if unknown or missing:
        raise _fail(where, f"names unknown values {sorted(unknown)}, misses {sorted(missing)}")
    for name in sorted(value):
        text = _text(f"{where}.{name}", value[name])
        matched = _SOURCE.fullmatch(text)
        if matched is None:
            raise _fail(f"{where}.{name}", "starts 'cited <ref>: ' or 'declared: '")
        if matched.group(1) is not None:
            for ref in matched.group(1).split(" and "):
                if ref not in references:
                    raise _fail(f"{where}.{name}", f"cites {ref!r}, which is not a reference")
    return tuple(sorted(value.items()))


@dataclass(frozen=True, slots=True)
class VehicleClass:
    key: str
    label: str
    design_basis: str
    length_mm: int
    width_mm: int
    height_mm: int
    wheelbase_mm: int
    front_overhang_mm: int
    rear_overhang_mm: int
    minimum_turning_radius_mm: int
    turning_inward_extent_mm: int
    turning_outward_extent_mm: int
    speed_cap_mm_per_s: int
    turning_speed_mm_per_s: int
    acceleration_mm_per_s2: int
    deceleration_mm_per_s2: int
    minimum_gap_mm: int
    parking_entry_ms: int
    parking_exit_ms: int
    body_families: tuple[str, ...]
    colours: tuple[str, ...]
    sources: tuple[tuple[str, str], ...]

    @property
    def half_width_mm(self) -> int:
        """Half the body width, rounded up so a corridor built from it contains the body."""
        return -(-self.width_mm // 2)

    @property
    def turning_half_width_mm(self) -> int:
        """The corridor half-width on a turning piece: the body, or its off-tracking if wider."""
        return max(
            self.half_width_mm, self.turning_inward_extent_mm, self.turning_outward_extent_mm
        )


@dataclass(frozen=True, slots=True)
class RightOfWayPolicy:
    key: str
    label: str
    rule: str
    approach_controls: tuple[str, ...]
    driving_sides: tuple[str, ...]
    turn_priority: tuple[str, ...]
    arrival_order: str
    critical_headway_ms: tuple[tuple[str, int], ...]
    sources: tuple[tuple[str, str], ...]

    def headway_ms(self, movement: str) -> int:
        for name, value in self.critical_headway_ms:
            if name == movement:
                return value
        raise TrafficCatalogError(f"policy {self.key} gives no critical headway for {movement}")

    def turn_rank(self, turn: str) -> int:
        """Lower goes first when two concurrent movements conflict."""
        if turn not in self.turn_priority:
            raise TrafficCatalogError(f"policy {self.key} does not rank the {turn} movement")
        return self.turn_priority.index(turn)


@dataclass(frozen=True, slots=True)
class SignalGroupSpec:
    key: str
    kind: str


@dataclass(frozen=True, slots=True)
class SignalInterval:
    duration_ms: int
    vehicle_green: tuple[str, ...]
    vehicle_amber: tuple[str, ...]
    pedestrian_walk: tuple[str, ...]
    pedestrian_clearance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SignalPlan:
    key: str
    label: str
    groups: tuple[SignalGroupSpec, ...]
    intervals: tuple[SignalInterval, ...]
    pedestrian_clearance_speed_mm_per_s: int
    pedestrian_total_speed_mm_per_s: int
    pedestrian_total_extra_mm: int
    sources: tuple[tuple[str, str], ...]

    @property
    def cycle_ms(self) -> int:
        return sum(interval.duration_ms for interval in self.intervals)

    def group_kind(self, group: str) -> str:
        for spec in self.groups:
            if spec.key == group:
                return spec.kind
        raise TrafficCatalogError(f"plan {self.key} has no group {group!r}")


@dataclass(frozen=True, slots=True)
class AccessMapping:
    """The vehicle classes one city key admits: a lane use's traffic, or a parking kind's."""

    key: str
    label: str
    classes: tuple[str, ...]
    sources: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class TrafficCatalogs:
    vehicle_classes: tuple[VehicleClass, ...]
    policies: tuple[RightOfWayPolicy, ...]
    plans: tuple[SignalPlan, ...]
    lane_uses: tuple[AccessMapping, ...]
    parking_kinds: tuple[AccessMapping, ...]
    #: ``(catalog_id, canonical payload)`` for each file, which is what the digest covers.
    payloads: tuple[tuple[str, Mapping[str, Any]], ...]
    #: ``(catalog_id, sha256 of the file bytes)``, the digest a city signal record carries.
    file_sha256: tuple[tuple[str, str], ...]
    #: :func:`catalogs_digest` of the payloads, computed once when they are loaded, because every
    #: simulated second and every presentation record names it.
    digest: str

    def vehicle_class(self, key: str) -> VehicleClass:
        for entry in self.vehicle_classes:
            if entry.key == key:
                return entry
        raise TrafficCatalogError(f"no vehicle class {key!r}")

    def policy(self, key: str) -> RightOfWayPolicy:
        for entry in self.policies:
            if entry.key == key:
                return entry
        raise TrafficCatalogError(f"no right-of-way policy {key!r}")

    def plan(self, key: str) -> SignalPlan:
        for entry in self.plans:
            if entry.key == key:
                return entry
        raise TrafficCatalogError(f"no signal plan {key!r}")

    def lane_use(self, key: str) -> AccessMapping:
        for entry in self.lane_uses:
            if entry.key == key:
                return entry
        raise TrafficCatalogError(f"no lane use {key!r} in lane-use-access")

    def parking_kind(self, key: str) -> AccessMapping:
        for entry in self.parking_kinds:
            if entry.key == key:
                return entry
        raise TrafficCatalogError(f"no parking kind {key!r} in parking-kind-access")

    def file_digest(self, catalog_id: str) -> str:
        return dict(self.file_sha256)[catalog_id]


_VEHICLE_INTS: Final = {
    "length_mm": (1, 30_000),
    "width_mm": (1, 3_000),
    "height_mm": (1, 5_000),
    "wheelbase_mm": (1, 30_000),
    "front_overhang_mm": (0, 10_000),
    "rear_overhang_mm": (0, 10_000),
    "minimum_turning_radius_mm": (1, 100_000),
    "turning_inward_extent_mm": (1, 20_000),
    "turning_outward_extent_mm": (1, 20_000),
    "speed_cap_mm_per_s": (1, 100_000),
    "turning_speed_mm_per_s": (1, 100_000),
    "acceleration_mm_per_s2": (1, 10_000),
    "deceleration_mm_per_s2": (1, 10_000),
    "minimum_gap_mm": (1, 20_000),
    "parking_entry_ms": (1_000, 600_000),
    "parking_exit_ms": (1_000, 600_000),
}
_VEHICLE_KEYS: Final = frozenset(
    {"key", "label", "design_basis", "body_families", "colours", "sources", "licence"}
    | set(_VEHICLE_INTS)
)
#: Soft conversion to the nearest centimetre can leave overhangs plus wheelbase this far from
#: the overall length; see the AASHTO table note. Anything further is a transcription error.
_SOFT_CONVERSION_MM: Final = 20


def _vehicle(where: str, raw: object, references: Mapping[str, str]) -> VehicleClass:
    entry = _object(where, raw, _VEHICLE_KEYS)
    ints = {
        name: _int(f"{where}.{name}", entry[name], low, high)
        for name, (low, high) in _VEHICLE_INTS.items()
    }
    parts = ints["front_overhang_mm"] + ints["wheelbase_mm"] + ints["rear_overhang_mm"]
    if abs(parts - ints["length_mm"]) > _SOFT_CONVERSION_MM:
        raise _fail(where, f"overhangs and wheelbase sum to {parts}, not {ints['length_mm']}")
    return VehicleClass(
        key=_key(f"{where}.key", entry["key"]),
        label=_text(f"{where}.label", entry["label"]),
        design_basis=_text(f"{where}.design_basis", entry["design_basis"]),
        body_families=_keys(f"{where}.body_families", entry["body_families"]),
        colours=_keys(f"{where}.colours", entry["colours"]),
        sources=_sources(
            f"{where}.sources",
            entry["sources"],
            set(_VEHICLE_INTS) | {"body_families", "colours"},
            references,
        ),
        **ints,
    )


_POLICY_KEYS: Final = frozenset(
    {
        "key",
        "label",
        "rule",
        "approach_controls",
        "driving_sides",
        "turn_priority",
        "arrival_order",
        "critical_headway_ms",
        "sources",
        "licence",
    }
)
#: The headways each rule needs. A rule that reads a headway the entry lacks is refused here.
_RULE_HEADWAYS: Final = {
    "signal": frozenset({"permitted_left"}),
    "priority": frozenset({"major_left", "minor_left", "minor_right", "minor_through"}),
    "all_way_stop": frozenset(),
    "uncontrolled": frozenset(),
}


def _policy(where: str, raw: object, references: Mapping[str, str]) -> RightOfWayPolicy:
    entry = _object(where, raw, _POLICY_KEYS)
    rule = _choice(f"{where}.rule", entry["rule"], POLICY_RULES)
    headways = entry["critical_headway_ms"]
    if not isinstance(headways, dict):
        raise _fail(f"{where}.critical_headway_ms", "is an object")
    if set(headways) != _RULE_HEADWAYS[rule]:
        raise _fail(
            f"{where}.critical_headway_ms",
            f"the {rule} rule reads exactly {sorted(_RULE_HEADWAYS[rule])}",
        )
    for name in headways:
        _choice(f"{where}.critical_headway_ms key", name, HEADWAY_MOVEMENTS)
    critical = tuple(
        (name, _int(f"{where}.critical_headway_ms.{name}", headways[name], 1, 60_000))
        for name in sorted(headways)
    )
    turn_priority = entry["turn_priority"]
    if (
        not isinstance(turn_priority, list)
        or sorted(turn_priority) != sorted(TURNS[:3])
        or len(turn_priority) != 3
    ):
        raise _fail(f"{where}.turn_priority", "orders left, straight and right exactly once")
    arrival = _choice(f"{where}.arrival_order", entry["arrival_order"], ARRIVAL_ORDERS)
    if (rule == "all_way_stop") != (arrival == "first_stopped_first_served"):
        raise _fail(where, "only the all_way_stop rule orders by arrival")
    return RightOfWayPolicy(
        key=_key(f"{where}.key", entry["key"]),
        label=_text(f"{where}.label", entry["label"]),
        rule=rule,
        approach_controls=_keys(
            f"{where}.approach_controls", entry["approach_controls"], options=APPROACH_CONTROLS
        ),
        driving_sides=_keys(
            f"{where}.driving_sides", entry["driving_sides"], options=DRIVING_SIDES
        ),
        turn_priority=tuple(turn_priority),
        arrival_order=arrival,
        critical_headway_ms=critical,
        sources=_sources(
            f"{where}.sources",
            entry["sources"],
            {"rule", "turn_priority", "arrival_order"}
            | {f"critical_headway_ms.{name}" for name in headways},
            references,
        ),
    )


_PLAN_KEYS: Final = frozenset(
    {
        "key",
        "label",
        "groups",
        "intervals",
        "pedestrian_clearance_speed_mm_per_s",
        "pedestrian_total_speed_mm_per_s",
        "pedestrian_total_extra_mm",
        "sources",
        "licence",
    }
)
_INTERVAL_KEYS: Final = frozenset(
    {"duration_ms", "vehicle_green", "vehicle_amber", "pedestrian_walk", "pedestrian_clearance"}
)


def _plan(where: str, raw: object, references: Mapping[str, str]) -> SignalPlan:
    entry = _object(where, raw, _PLAN_KEYS)
    raw_groups = entry["groups"]
    if not isinstance(raw_groups, list) or not raw_groups:
        raise _fail(f"{where}.groups", "is a non-empty list")
    groups = tuple(
        SignalGroupSpec(
            key=_key(f"{where}.groups[{index}].key", group["key"]),
            kind=_choice(f"{where}.groups[{index}].kind", group["kind"], SIGNAL_GROUP_KINDS),
        )
        for index, group in enumerate(
            _object(f"{where}.groups[{index}]", item, frozenset({"key", "kind"}))
            for index, item in enumerate(raw_groups)
        )
    )
    names = [group.key for group in groups]
    if len(set(names)) != len(names):
        raise _fail(f"{where}.groups", "repeats a group key")
    kinds = {group.key: group.kind for group in groups}
    raw_intervals = entry["intervals"]
    if not isinstance(raw_intervals, list) or not raw_intervals:
        raise _fail(f"{where}.intervals", "is a non-empty list")
    intervals = []
    for index, item in enumerate(raw_intervals):
        at = f"{where}.intervals[{index}]"
        interval = _object(at, item, _INTERVAL_KEYS)
        members = {}
        for field, kind in (
            ("vehicle_green", "vehicle"),
            ("vehicle_amber", "vehicle"),
            ("pedestrian_walk", "pedestrian"),
            ("pedestrian_clearance", "pedestrian"),
        ):
            members[field] = _keys(f"{at}.{field}", interval[field], empty=True)
            for group in members[field]:
                if kinds.get(group) != kind:
                    raise _fail(f"{at}.{field}", f"{group!r} is not a {kind} group of the plan")
        if set(members["vehicle_green"]) & set(members["vehicle_amber"]):
            raise _fail(at, "a group is green and amber at once")
        if set(members["pedestrian_walk"]) & set(members["pedestrian_clearance"]):
            raise _fail(at, "a group shows walk and clearance at once")
        duration = _int(f"{at}.duration_ms", interval["duration_ms"], 1_000, 600_000)
        intervals.append(SignalInterval(duration_ms=duration, **members))
    for group in names:
        if not any(
            group in interval.vehicle_green or group in interval.pedestrian_walk
            for interval in intervals
        ):
            raise _fail(where, f"group {group!r} is never given right of way")
    return SignalPlan(
        key=_key(f"{where}.key", entry["key"]),
        label=_text(f"{where}.label", entry["label"]),
        groups=groups,
        intervals=tuple(intervals),
        pedestrian_clearance_speed_mm_per_s=_int(
            f"{where}.pedestrian_clearance_speed_mm_per_s",
            entry["pedestrian_clearance_speed_mm_per_s"],
            1,
            10_000,
        ),
        pedestrian_total_speed_mm_per_s=_int(
            f"{where}.pedestrian_total_speed_mm_per_s",
            entry["pedestrian_total_speed_mm_per_s"],
            1,
            10_000,
        ),
        pedestrian_total_extra_mm=_int(
            f"{where}.pedestrian_total_extra_mm", entry["pedestrian_total_extra_mm"], 0, 10_000
        ),
        sources=_sources(
            f"{where}.sources",
            entry["sources"],
            {f"intervals[{index}].duration_ms" for index in range(len(intervals))}
            | {
                "pedestrian_clearance_speed_mm_per_s",
                "pedestrian_total_speed_mm_per_s",
                "pedestrian_total_extra_mm",
            },
            references,
        ),
    )


_ACCESS_KEYS: Final = frozenset({"key", "label", "classes", "sources", "licence"})


def _access(
    where: str, raw: object, references: Mapping[str, str], *, empty: bool
) -> AccessMapping:
    entry = _object(where, raw, _ACCESS_KEYS)
    return AccessMapping(
        key=_key(f"{where}.key", entry["key"]),
        label=_text(f"{where}.label", entry["label"]),
        classes=_keys(f"{where}.classes", entry["classes"], empty=empty),
        sources=_sources(f"{where}.sources", entry["sources"], {"classes"}, references),
    )


def _lane_use(where: str, raw: object, references: Mapping[str, str]) -> AccessMapping:
    # A lane use may carry no traffic at all: a parking lane or a buffer.
    return _access(where, raw, references, empty=True)


def _parking_kind(where: str, raw: object, references: Mapping[str, str]) -> AccessMapping:
    return _access(where, raw, references, empty=False)


def _read(path: Path, catalog_id: str) -> tuple[dict[str, Any], str]:
    try:
        stem, version = split_versioned_name(path)
        document = read_json(path)
    except CatalogError as error:
        raise TrafficCatalogError(str(error)) from error
    if (stem, version) != (catalog_id, 1):
        raise _fail(path.name, f"is not {catalog_id}.v1.json")
    envelope = _object(path.name, document, _ENVELOPE)
    if type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1:
        raise _fail(path.name, "schema_version is 1")
    if (envelope["catalog_id"], envelope["catalog_version"]) != (stem, version) or type(
        envelope["catalog_version"]
    ) is not int:
        raise _fail(path.name, "declares an id or version that is not its file name")
    references = envelope["references"]
    # A catalog whose every value is declared has nothing to cite, so it may list no reference.
    if not isinstance(references, dict):
        raise _fail(path.name, "references is an object")
    for ref, citation in references.items():
        _key(f"{path.name} references key", ref)
        _text(f"{path.name} references.{ref}", citation)
    if not isinstance(envelope["entries"], list) or not envelope["entries"]:
        raise _fail(path.name, "entries is a non-empty list")
    return envelope, hashlib.sha256(path.read_bytes()).hexdigest()


def _entries(
    path: Path,
    envelope: Mapping[str, Any],
    build: Callable[[str, object, Mapping[str, str]], Any],
) -> tuple[Any, ...]:
    built = []
    for index, raw in enumerate(envelope["entries"]):
        where = f"{path.name} entries[{index}]"
        item = build(where, raw, envelope["references"])
        try:
            Licence.read(f"{where}.licence", raw["licence"])
        except CatalogError as error:
            raise TrafficCatalogError(str(error)) from error
        built.append(item)
    keys = [item.key for item in built]
    if len(set(keys)) != len(keys):
        raise _fail(path.name, "repeats an entry key")
    if keys != sorted(keys):
        raise _fail(path.name, "entries are sorted by key")
    used = {
        ref
        for item in built
        for _, text in item.sources
        if text.startswith("cited ")
        for ref in text[len("cited ") :].split(":", 1)[0].split(" and ")
    }
    unused = set(envelope["references"]) - used
    if unused:
        raise _fail(path.name, f"references {sorted(unused)} are cited by no entry")
    return tuple(built)


def load_traffic_catalogs(directory: Path = CATALOG_DIRECTORY) -> TrafficCatalogs:
    present = sorted(path.name for path in directory.glob("*.json"))
    if present != sorted(_FILES.values()):
        raise TrafficCatalogError(
            f"{directory} holds {present}, expected {sorted(_FILES.values())}"
        )
    envelopes = {}
    digests = []
    for catalog_id, name in sorted(_FILES.items()):
        envelope, file_digest = _read(directory.joinpath(name), catalog_id)
        envelopes[catalog_id] = envelope
        digests.append((catalog_id, file_digest))
    payloads = tuple(sorted(envelopes.items()))
    catalogs = TrafficCatalogs(
        vehicle_classes=_entries(
            directory.joinpath(_FILES["vehicle-class"]), envelopes["vehicle-class"], _vehicle
        ),
        policies=_entries(
            directory.joinpath(_FILES["right-of-way-policy"]),
            envelopes["right-of-way-policy"],
            _policy,
        ),
        plans=_entries(directory.joinpath(_FILES["signal-plan"]), envelopes["signal-plan"], _plan),
        lane_uses=_entries(
            directory.joinpath(_FILES["lane-use-access"]), envelopes["lane-use-access"], _lane_use
        ),
        parking_kinds=_entries(
            directory.joinpath(_FILES["parking-kind-access"]),
            envelopes["parking-kind-access"],
            _parking_kind,
        ),
        payloads=payloads,
        file_sha256=tuple(digests),
        digest=_payloads_digest(payloads),
    )
    known = {vehicle.key for vehicle in catalogs.vehicle_classes}
    for catalog_id, mappings in (
        ("lane-use-access", catalogs.lane_uses),
        ("parking-kind-access", catalogs.parking_kinds),
    ):
        for mapping in mappings:
            unknown = set(mapping.classes) - known
            if unknown:
                raise _fail(
                    _FILES[catalog_id], f"{mapping.key} admits unknown classes {sorted(unknown)}"
                )
    return catalogs


def _payloads_digest(payloads: tuple[tuple[str, Mapping[str, Any]], ...]) -> str:
    return sha256_of_canonical(
        [{"catalog_id": catalog_id, "document": payload} for catalog_id, payload in payloads]
    ).hex()


def catalogs_digest(catalogs: TrafficCatalogs) -> str:
    """SHA-256 over the canonical JSON of the three catalogs, ordered by id. Hex."""
    return _payloads_digest(catalogs.payloads)


def declared_values(catalogs: TrafficCatalogs) -> tuple[tuple[str, str, str, str], ...]:
    """``(catalog, entry, field, reason)`` for every value that is declared rather than cited."""
    rows = []
    for catalog_id, entries in (
        ("vehicle-class", catalogs.vehicle_classes),
        ("right-of-way-policy", catalogs.policies),
        ("signal-plan", catalogs.plans),
        ("lane-use-access", catalogs.lane_uses),
        ("parking-kind-access", catalogs.parking_kinds),
    ):
        for entry in entries:
            for field, text in entry.sources:
                if text.startswith("declared: "):
                    rows.append((catalog_id, entry.key, field, text[len("declared: ") :]))
    return tuple(rows)
