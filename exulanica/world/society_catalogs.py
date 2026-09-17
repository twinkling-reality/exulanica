"""The living society routine model as versioned data, not planner constants.

Needs, activities, capacity rules, the premises use-class to role mapping and the policy values
live in ``assets/catalogs/society``, one reviewed file per catalog, in the same envelope the
city grammar's catalogs use. They sit in a subdirectory because the grammar's directory loader
refuses any file in ``assets/catalogs`` it has no schema for. Every entry carries a licence and a
``reason``. The model's digest covers every loaded catalog, and a society records it, so changing
the routine means publishing a new catalog version, never editing the one a society replays.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from exulanica.grammar.catalogs import (
    Catalog,
    CatalogSchema,
    FieldValue,
    catalog_digest,
    integer_field,
    key_list_field,
    load_catalog,
    text_field,
)
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.records import KEY_PATTERN

__all__ = [
    "ROUTINE_DIRECTORY",
    "ROUTINE_VERSIONS",
    "Activity",
    "CapacityRule",
    "Need",
    "RoutineModel",
    "UseClass",
    "load_routine_model",
]

ROUTINE_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "society")
)
#: The catalog versions a model reads by default. A society records its model's digest, and a
#: new routine is a new catalog version listed here, so an older society keeps replaying.
ROUTINE_VERSIONS: Final = {
    "society-activity": 1,
    "society-capacity": 1,
    "society-need": 1,
    "society-policy": 1,
    "society-use-class": 1,
}
MINUTES_PER_DAY: Final = 1440
MODES: Final = ("need", "shift")
SETTINGS: Final = ("destination", "home", "standing", "work")
CAPACITY_RULES: Final = ("fixed", "node_clearance", "use_class")
USE_CLASS_KINDS: Final = ("furniture", "residential", "workplace")
POLICY_KEYS: Final = frozenset(
    {
        "commute_lead_minutes",
        "memory_limit",
        "occupancy_maximum_milli",
        "occupancy_target_milli",
        "preference_spread_milli",
        "shift_jitter_minutes",
        "standing_radius_mm",
        "standing_spacing_mm",
        "start_minute_of_day",
        "walk_speed_maximum_mm_per_tick",
        "walk_speed_minimum_mm_per_tick",
    }
)


def _key(where: str, value: object) -> FieldValue:
    if type(value) is not str or KEY_PATTERN.fullmatch(value) is None:
        raise CatalogError(f"{where} is a lowercase key, got {value!r}")
    return value


def _choice(options: tuple[str, ...]) -> Callable[[str, object], FieldValue]:
    def check(where: str, value: object) -> FieldValue:
        if value not in options:
            raise CatalogError(f"{where} is one of {options}, got {value!r}")
        return value  # type: ignore[return-value]

    return check


_MILLI = integer_field(0, 1000)
_MINUTE = integer_field(0, MINUTES_PER_DAY)
_TICKS = integer_field(1, MINUTES_PER_DAY)


def _need_bounds(where: str, values: dict[str, FieldValue]) -> None:
    if values["initial_minimum_milli"] > values["initial_maximum_milli"]:  # type: ignore[operator]
        raise CatalogError(f"{where}: initial_minimum_milli is at most initial_maximum_milli")


def _activity_bounds(where: str, values: dict[str, FieldValue]) -> None:
    if values["duration_minimum_ticks"] > values["duration_maximum_ticks"]:  # type: ignore[operator]
        raise CatalogError(f"{where}: duration_minimum_ticks is at most duration_maximum_ticks")
    if (values["mode"] == "shift") != (values["need"] == "none"):
        raise CatalogError(f"{where}: a shift activity has need 'none', and only a shift does")
    if (values["mode"] == "shift") != (values["setting"] == "work"):
        raise CatalogError(f"{where}: only a shift activity takes place at work")
    if values["indoors"] not in (0, 1):
        raise CatalogError(f"{where}: indoors is 0 or 1")


def _use_class_bounds(where: str, values: dict[str, FieldValue]) -> None:
    kind = values["kind"]
    if (kind == "workplace") != (values["staff_per_unit"] != 0):
        raise CatalogError(f"{where}: exactly the workplaces have staff")
    if (kind == "furniture") != (values["role_key"] == "none"):
        raise CatalogError(f"{where}: workplaces and homes name a role, furniture does not")
    if (kind == "residential") != (values["resident_capacity"] != 0):
        raise CatalogError(f"{where}: exactly the residential units house residents")
    if kind == "workplace" and values["shift_minutes"] == 0:
        raise CatalogError(f"{where}: a workplace declares its shift")


SCHEMAS: Final = {
    "society-need": CatalogSchema(
        "society-need",
        1,
        (
            ("label", text_field),
            ("initial_minimum_milli", _MILLI),
            ("initial_maximum_milli", _MILLI),
            ("growth_milli_per_tick", integer_field(1, 1000)),
            ("urgency_threshold_milli", _MILLI),
            ("reason", text_field),
        ),
        entry_check=_need_bounds,
    ),
    "society-activity": CatalogSchema(
        "society-activity",
        1,
        (
            ("label", text_field),
            ("mode", _choice(MODES)),
            ("need", _key),
            ("relief_milli", _MILLI),
            ("duration_minimum_ticks", _TICKS),
            ("duration_maximum_ticks", _TICKS),
            ("window_start_minute", _MINUTE),
            ("window_end_minute", _MINUTE),
            ("setting", _choice(SETTINGS)),
            ("affordance", _key),
            ("indoors", integer_field(0, 1)),
            ("weight_milli", integer_field(1, 10_000)),
            ("reason", text_field),
        ),
        entry_check=_activity_bounds,
    ),
    "society-capacity": CatalogSchema(
        "society-capacity",
        1,
        (
            ("rule", _choice(CAPACITY_RULES)),
            ("capacity", integer_field(0, 4096)),
            ("reason", text_field),
        ),
    ),
    "society-use-class": CatalogSchema(
        "society-use-class",
        1,
        (
            ("label", text_field),
            ("kind", _choice(USE_CLASS_KINDS)),
            ("role_key", _key),
            ("role_label", text_field),
            ("staff_per_unit", integer_field(0, 4096)),
            ("visitor_capacity", integer_field(0, 4096)),
            ("resident_capacity", integer_field(0, 4096)),
            ("visitor_affordances", key_list_field),
            ("shift_start_minute", _MINUTE),
            ("shift_minutes", _MINUTE),
            ("reason", text_field),
        ),
        entry_check=_use_class_bounds,
    ),
    "society-policy": CatalogSchema(
        "society-policy",
        1,
        (("value", integer_field(0, 10**9)), ("reason", text_field)),
    ),
}


@dataclass(frozen=True, slots=True)
class Need:
    key: str
    label: str
    initial_minimum: int
    initial_maximum: int
    growth: int
    threshold: int


@dataclass(frozen=True, slots=True)
class Activity:
    key: str
    label: str
    mode: str
    need: str
    relief: int
    duration_minimum: int
    duration_maximum: int
    window_start: int
    window_end: int
    setting: str
    affordance: str
    indoors: bool
    weight: int

    def open_at(self, minute: int) -> bool:
        """Whether an activity may start at this minute of the day; windows may wrap midnight."""
        start, end = self.window_start, self.window_end
        if start == 0 and end == MINUTES_PER_DAY:
            return True
        if start <= end:
            return start <= minute < end
        return minute >= start or minute < end


@dataclass(frozen=True, slots=True)
class CapacityRule:
    key: str
    rule: str
    capacity: int


@dataclass(frozen=True, slots=True)
class UseClass:
    key: str
    label: str
    kind: str
    role_key: str
    role_label: str
    staff_per_unit: int
    visitor_capacity: int
    resident_capacity: int
    visitor_affordances: tuple[str, ...]
    shift_start: int
    shift_minutes: int


@dataclass(frozen=True, slots=True)
class RoutineModel:
    needs: Mapping[str, Need]
    activities: Mapping[str, Activity]
    capacities: Mapping[str, CapacityRule]
    use_classes: Mapping[str, UseClass]
    policy: Mapping[str, int]
    versions: Mapping[str, int]
    sha256: str

    def binding(self) -> dict[str, object]:
        """What a society records about the model it was advanced under."""
        return {"catalog_versions": dict(sorted(self.versions.items())), "sha256": self.sha256}


def _values(catalog: Catalog) -> dict[str, dict[str, FieldValue]]:
    return {entry.key: dict(entry.values) for entry in catalog.entries}


def load_routine_model(
    directory: Path = ROUTINE_DIRECTORY, versions: Mapping[str, int] | None = None
) -> RoutineModel:
    """Read and cross-check the routine catalogs. Every inconsistency is a CatalogError."""
    chosen = dict(ROUTINE_VERSIONS if versions is None else versions)
    if set(chosen) != set(ROUTINE_VERSIONS):
        raise CatalogError(f"a routine model reads exactly {sorted(ROUTINE_VERSIONS)}")
    catalogs = []
    for catalog_id, version in sorted(chosen.items()):
        schema = SCHEMAS[catalog_id]
        if version != schema.catalog_version:
            raise CatalogError(f"{catalog_id} v{version} has no schema")
        catalogs.append(load_catalog(directory.joinpath(f"{catalog_id}.v{version}.json"), schema))
    by_id = {catalog.catalog_id: _values(catalog) for catalog in catalogs}
    needs = {
        key: Need(
            key,
            str(v["label"]),
            int(v["initial_minimum_milli"]),  # type: ignore[arg-type]
            int(v["initial_maximum_milli"]),  # type: ignore[arg-type]
            int(v["growth_milli_per_tick"]),  # type: ignore[arg-type]
            int(v["urgency_threshold_milli"]),  # type: ignore[arg-type]
        )
        for key, v in by_id["society-need"].items()
    }
    activities = {}
    for key, v in by_id["society-activity"].items():
        if v["mode"] == "need" and v["need"] not in needs:
            raise CatalogError(f"activity {key} relieves unknown need {v['need']!r}")
        activities[key] = Activity(
            key,
            str(v["label"]),
            str(v["mode"]),
            str(v["need"]),
            int(v["relief_milli"]),  # type: ignore[arg-type]
            int(v["duration_minimum_ticks"]),  # type: ignore[arg-type]
            int(v["duration_maximum_ticks"]),  # type: ignore[arg-type]
            int(v["window_start_minute"]),  # type: ignore[arg-type]
            int(v["window_end_minute"]),  # type: ignore[arg-type]
            str(v["setting"]),
            str(v["affordance"]),
            v["indoors"] == 1,
            int(v["weight_milli"]),  # type: ignore[arg-type]
        )
    if [a for a in activities.values() if a.setting == "standing"] == []:
        raise CatalogError("a routine needs a standing activity, the one that needs no destination")
    for need in needs.values():
        if not any(a.need == need.key and a.relief > 0 for a in activities.values()):
            raise CatalogError(f"need {need.key} has no activity that relieves it")
    capacities = {
        key: CapacityRule(key, str(v["rule"]), int(v["capacity"]))  # type: ignore[arg-type]
        for key, v in by_id["society-capacity"].items()
    }
    for key in ("authored_object", "district_target", "standing_node"):
        if key not in capacities:
            raise CatalogError(f"the capacity catalog needs a {key} rule")
    for rule in capacities.values():
        if (rule.rule == "use_class") != (rule.capacity == 0):
            raise CatalogError(f"capacity {rule.key}: only use-class rules defer their capacity")
    affordances = {a.affordance for a in activities.values() if a.setting == "destination"}
    use_classes = {}
    for key, v in by_id["society-use-class"].items():
        offered = tuple(v["visitor_affordances"])  # type: ignore[arg-type]
        if not set(offered) <= affordances:
            raise CatalogError(f"use class {key} offers an affordance no activity uses")
        if bool(offered) != (v["visitor_capacity"] != 0):
            raise CatalogError(f"use class {key}: visitors need both a capacity and an affordance")
        use_classes[key] = UseClass(
            key,
            str(v["label"]),
            str(v["kind"]),
            str(v["role_key"]),
            str(v["role_label"]),
            int(v["staff_per_unit"]),  # type: ignore[arg-type]
            int(v["visitor_capacity"]),  # type: ignore[arg-type]
            int(v["resident_capacity"]),  # type: ignore[arg-type]
            offered,
            int(v["shift_start_minute"]),  # type: ignore[arg-type]
            int(v["shift_minutes"]),  # type: ignore[arg-type]
        )
    policy = {key: int(v["value"]) for key, v in by_id["society-policy"].items()}  # type: ignore[arg-type]
    if set(policy) != POLICY_KEYS:
        raise CatalogError(f"the policy catalog holds exactly {sorted(POLICY_KEYS)}")
    if not 0 < policy["occupancy_target_milli"] <= policy["occupancy_maximum_milli"] <= 1000:
        raise CatalogError("occupancy target is positive and at most the maximum, at most 1000")
    if not 0 < policy["walk_speed_minimum_mm_per_tick"] <= policy["walk_speed_maximum_mm_per_tick"]:
        raise CatalogError("walking speeds are positive and ordered")
    if policy["standing_spacing_mm"] < 2 * policy["standing_radius_mm"]:
        raise CatalogError("standing spacing keeps two standing radii apart")
    if not 0 <= policy["start_minute_of_day"] < MINUTES_PER_DAY:
        raise CatalogError("the start minute is a minute of the day")
    if policy["preference_spread_milli"] >= 1000 or policy["memory_limit"] < 1:
        raise CatalogError("preference spread is below 1000 and memory holds at least one event")
    return RoutineModel(
        needs=needs,
        activities=activities,
        capacities=capacities,
        use_classes=use_classes,
        policy=policy,
        versions=chosen,
        sha256=catalog_digest(catalogs),
    )
