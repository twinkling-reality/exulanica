"""The living society routine model as versioned data, not planner constants.

Needs, activities, capacity rules, the premises use-class to role mapping and the policy values
live in ``assets/catalogs/society``, one reviewed file per catalog version, in the same envelope
the city grammar's catalogs use. They sit in a subdirectory because the grammar's directory
loader refuses any file in ``assets/catalogs`` it has no schema for. Every entry carries a licence
and a ``reason``. The model's digest covers every catalog it loads, and a society records the
versions and the digest, so changing the routine means publishing a new catalog version beside
the old one, never editing the one a society replays.

Schemas are keyed by catalog id and version, so two versions of one catalog can be read side by
side. The directory keeps every version any schema names, and holds nothing a schema does not
name. A model reads one version of each catalog: a new society reads ``ROUTINE_VERSIONS``, and a
stored society reads the versions it recorded.

The purposeful society (``exulanica-society/v2`` and ``v3``) reads a routine of its own from the
same directory, :func:`load_purposeful_routine`: one catalog, ``society-purposeful-activity``, of
what its people do, how long each stay lasts and how it varies, what it relieves and how often it
is chosen. It is not the living society's activity catalog, whose activities relieve that model's
five needs and whose versions living states record by digest. An input a saved world composes
records the purposeful routine it was composed under (``PURPOSEFUL_ROUTINE_VERSIONS``), and an
input that records none is read under ``UNRECORDED_ROUTINE_VERSIONS``, the rules the society was
first released with, so no stored input changes meaning.

The contract a model answers under when it runs a person in a world is read from the same
directory, :func:`load_decision_catalogs`: ``society-decision-action``, what such a person may be
asked to do and how each option reads, and ``society-decision-policy``, the bounds on asking.
A decision request records the versions it was asked under, and a new contract is a new version
published beside the old one.

How such a person's hour is scored, and the protocol and seeds a comparison of the models that run
them is made under, are read from the same directory too, :func:`load_comparison_catalogs`:
``society-person-score``, ``society-comparison-protocol`` and ``society-comparison-seeds``, whose
entries commit each seed by the SHA-256 of its text and never state the seed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Final

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

if TYPE_CHECKING:
    from exulanica.world.object_catalog import WorldObjectCatalog

__all__ = [
    "COMPARISON_PROTOCOL_CATALOG",
    "COMPARISON_SEEDS_CATALOG",
    "COMPARISON_VERSIONS",
    "DECISION_ACTION_CATALOG",
    "DECISION_ACTION_KINDS",
    "DECISION_CONTRACT_VERSIONS",
    "DECISION_POLICY_CATALOG",
    "PERSON_SCORE_CATALOG",
    "PURPOSEFUL_CATALOG",
    "PURPOSEFUL_ROUTINE_VERSIONS",
    "ROUTINE_DIRECTORY",
    "ROUTINE_VERSIONS",
    "UNRECORDED_ROUTINE_VERSIONS",
    "Activity",
    "CapacityRule",
    "ComparisonCatalogs",
    "Need",
    "PurposefulActivity",
    "PurposefulRoutine",
    "RoutineModel",
    "UseClass",
    "check_object_kinds",
    "load_comparison_catalogs",
    "load_decision_catalogs",
    "load_purposeful_routine",
    "load_routine_model",
    "purposeful_routine",
]

ROUTINE_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "society")
)
#: The catalog versions a new society's model reads. A society records its model's versions and
#: digest, and a new routine is a new catalog version listed here, published beside the old one,
#: so an older society keeps reading the versions it recorded and keeps replaying.
ROUTINE_VERSIONS: Final = {
    "society-activity": 1,
    "society-capacity": 1,
    "society-need": 1,
    "society-policy": 1,
    "society-use-class": 1,
}
#: The one catalog the purposeful society's routine reads.
PURPOSEFUL_CATALOG: Final = "society-purposeful-activity"
#: The purposeful routine a saved world's new input records: people stay a while, varied, at what
#: they use, and some stand or stop to talk.
PURPOSEFUL_ROUTINE_VERSIONS: Final = {PURPOSEFUL_CATALOG: 2}
#: The purposeful routine an input that records none is read under: every input composed before
#: inputs recorded a routine, and every district input, keeps the rules it was recorded with.
UNRECORDED_ROUTINE_VERSIONS: Final = {PURPOSEFUL_CATALOG: 1}
#: The contract a model answers under when it runs a person: what it may be asked to do, and the
#: bounds on asking. A new decision request records these versions.
DECISION_ACTION_CATALOG: Final = "society-decision-action"
DECISION_POLICY_CATALOG: Final = "society-decision-policy"
DECISION_CONTRACT_VERSIONS: Final = {DECISION_ACTION_CATALOG: 1, DECISION_POLICY_CATALOG: 1}
#: What an action asks of the engine: to go to one place for its activity, or to wait a minute.
DECISION_ACTION_KINDS: Final = ("target", "wait")
#: How a person's hour is scored, and the protocol and seeds a comparison of models is made under.
PERSON_SCORE_CATALOG: Final = "society-person-score"
COMPARISON_PROTOCOL_CATALOG: Final = "society-comparison-protocol"
COMPARISON_SEEDS_CATALOG: Final = "society-comparison-seeds"
COMPARISON_VERSIONS: Final = {
    PERSON_SCORE_CATALOG: 1,
    COMPARISON_PROTOCOL_CATALOG: 1,
    COMPARISON_SEEDS_CATALOG: 1,
}
#: Whether a score term is weighed or only reported, and what a term reads: a run's minutes, the
#: events the engine appended, or the host's record of each call, which only a reader outside the
#: score reads.
SCORE_PARTS: Final = ("primary", "held_out")
SCORE_READS: Final = ("states", "events", "calls")
#: The seeds a comparison may run: development seeds, looked at freely, and held-out seeds, judged.
SEED_PHASES: Final = ("development", "held_out")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
#: Where a purposeful activity happens: at a place an object states, at an open spot of the
#: ground, or at two open spots beside each other, one for each of two people.
PURPOSEFUL_SETTINGS: Final = ("object", "open", "pair")
#: How a person picks where: the nearest free place they have not just used, the rule the society
#: was released with, or a draw from the seed among every free one.
PURPOSEFUL_CHOICES: Final = ("nearest", "drawn")
#: An object entry's kind that stands for every kind of its affordance with no entry of its own,
#: and the kind of an activity that is at no object.
ANY_KIND: Final = "any"
NO_KIND: Final = "none"
MINUTES_PER_DAY: Final = 1440
MODES: Final = ("need", "shift")
SETTINGS: Final = ("destination", "home", "standing", "work")
CAPACITY_RULES: Final = ("fixed", "node_clearance", "use_class")
USE_CLASS_KINDS: Final = ("furniture", "residential", "workplace")
#: The policy keys the engine reads. Enumerated on purpose, and safe because it is compared for
#: exact equality against the catalog's own keys in load_routine_model: a key added to the catalog
#: and a key removed from it are both refused, rather than one of them being read by nobody.
POLICY_KEYS: Final = frozenset(
    {
        "commute_lead_minutes",
        "footway_station_spacing_mm",
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
#: A reach or a spacing on a saved world's ground, bounded as every reach is (``MAX_REACH_MM``).
_REACH = integer_field(0, 10_000)


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


def _purposeful_bounds(where: str, values: dict[str, FieldValue]) -> None:
    if values["duration_minimum_ticks"] > values["duration_maximum_ticks"]:  # type: ignore[operator]
        raise CatalogError(f"{where}: duration_minimum_ticks is at most duration_maximum_ticks")
    setting, affordance, kind = values["setting"], values["affordance"], values["object_kind"]
    if (setting == "object") == (affordance == NO_KIND) or (setting == "object") == (
        kind == NO_KIND
    ):
        raise CatalogError(f"{where}: exactly the object activities name an affordance and a kind")
    reach, spacing = values["reach_mm"], values["spacing_mm"]
    if (setting == "object") != (reach == 0) or (setting == "pair") != (spacing != 0):
        raise CatalogError(
            f"{where}: an open or pair activity states how far it reaches, and only a pair how "
            "far apart its two people stand; an object's reach is its registry row's"
        )
    if (
        values["choice"] == "nearest"
        and values["duration_minimum_ticks"] != values["duration_maximum_ticks"]
    ):
        raise CatalogError(f"{where}: the nearest-place rule stays a fixed time")
    if kind not in (ANY_KIND, NO_KIND) and (
        values["weight_milli"] != 0 or values["preferred_at_need_milli"] != 0
    ):
        raise CatalogError(
            f"{where}: how often an activity is chosen is its affordance's, so an entry for one "
            "kind states weight 0 and preference 0"
        )


def _score_bounds(where: str, values: dict[str, FieldValue]) -> None:
    if (values["part"] == "primary") == (values["weight_milli"] == 0):
        raise CatalogError(f"{where}: exactly a primary term carries a weight")
    if (values["reads"] == "events") != bool(values["dispositions"]):
        raise CatalogError(f"{where}: exactly a term that reads events names what it counts")
    if values["part"] == "primary" and values["reads"] == "calls":
        raise CatalogError(f"{where}: no weighed term reads the host's record of a call")


def _sha256_text(where: str, value: object) -> FieldValue:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CatalogError(f"{where} is a SHA-256 in lowercase hexadecimal, got {value!r}")
    return value


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


#: Every schema the society reads, keyed by catalog id and version. A version a stored society
#: names keeps its schema here and its file in the directory for as long as the society exists.
SCHEMAS: Final[dict[tuple[str, int], CatalogSchema]] = {
    ("society-need", 1): CatalogSchema(
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
    ("society-activity", 1): CatalogSchema(
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
    ("society-capacity", 1): CatalogSchema(
        "society-capacity",
        1,
        (
            ("rule", _choice(CAPACITY_RULES)),
            ("capacity", integer_field(0, 4096)),
            ("reason", text_field),
        ),
    ),
    ("society-use-class", 1): CatalogSchema(
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
    ("society-policy", 1): CatalogSchema(
        "society-policy",
        1,
        (("value", integer_field(0, 10**9)), ("reason", text_field)),
    ),
    **{
        (PURPOSEFUL_CATALOG, version): CatalogSchema(
            PURPOSEFUL_CATALOG,
            version,
            (
                ("label", text_field),
                ("setting", _choice(PURPOSEFUL_SETTINGS)),
                ("affordance", _key),
                ("object_kind", _key),
                ("choice", _choice(PURPOSEFUL_CHOICES)),
                ("duration_minimum_ticks", _TICKS),
                ("duration_maximum_ticks", _TICKS),
                ("relief_milli", _MILLI),
                # 0 is never: no need is below zero, so a threshold of 0 would always prefer it.
                ("preferred_at_need_milli", _MILLI),
                ("weight_milli", integer_field(0, 10_000)),
                ("reach_mm", _REACH),
                ("spacing_mm", _REACH),
                ("reason", text_field),
            ),
            entry_check=_purposeful_bounds,
        )
        for version in (1, 2)
    },
    (DECISION_ACTION_CATALOG, 1): CatalogSchema(
        DECISION_ACTION_CATALOG,
        1,
        (
            ("kind", _choice(DECISION_ACTION_KINDS)),
            ("words", text_field),
            ("reason", text_field),
        ),
    ),
    (DECISION_POLICY_CATALOG, 1): CatalogSchema(
        DECISION_POLICY_CATALOG,
        1,
        (("value", integer_field(0, 10**9)), ("reason", text_field)),
    ),
    (PERSON_SCORE_CATALOG, 1): CatalogSchema(
        PERSON_SCORE_CATALOG,
        1,
        (
            ("part", _choice(SCORE_PARTS)),
            ("weight_milli", integer_field(-1000, 1000)),
            ("reads", _choice(SCORE_READS)),
            ("dispositions", key_list_field),
            ("reason", text_field),
        ),
        entry_check=_score_bounds,
    ),
    (COMPARISON_PROTOCOL_CATALOG, 1): CatalogSchema(
        COMPARISON_PROTOCOL_CATALOG,
        1,
        (("value", integer_field(0, 10**9)), ("reason", text_field)),
    ),
    (COMPARISON_SEEDS_CATALOG, 1): CatalogSchema(
        COMPARISON_SEEDS_CATALOG,
        1,
        (
            ("phase", _choice(SEED_PHASES)),
            ("seed_digest", _sha256_text),
            ("reason", text_field),
        ),
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


@dataclass(frozen=True, slots=True)
class PurposefulActivity:
    """One thing a purposeful society's people do: where, for how long, and how it is chosen."""

    key: str
    label: str
    setting: str
    affordance: str
    object_kind: str
    choice: str
    duration_minimum: int
    duration_maximum: int
    relief: int
    #: The need at or above which a person prefers this to every other activity; 0 is never.
    preferred_at_need: int
    weight: int
    reach_mm: int
    spacing_mm: int


@dataclass(frozen=True, slots=True)
class PurposefulRoutine:
    """The activities of one purposeful routine version, looked up as the planner asks for them."""

    activities: Mapping[str, PurposefulActivity]
    versions: Mapping[str, int]
    sha256: str

    def binding(self) -> dict[str, object]:
        """What an input records about the routine it was composed under."""
        return {"catalog_versions": dict(sorted(self.versions.items())), "sha256": self.sha256}

    @property
    def choice(self) -> str:
        """How a person picks where, the same for every activity of one routine."""
        return next(iter(self.activities.values())).choice

    def default(self, affordance: str) -> PurposefulActivity:
        """The activity of an affordance at a kind that states none of its own."""
        return next(
            activity
            for activity in self.activities.values()
            if activity.affordance == affordance and activity.object_kind == ANY_KIND
        )

    def at_object(self, affordance: str, kind: str) -> PurposefulActivity:
        """What people do at an object of ``kind`` offering ``affordance``: its own entry, else
        the affordance's default."""
        for activity in self.activities.values():
            if activity.affordance == affordance and activity.object_kind == kind:
                return activity
        return self.default(affordance)

    def in_setting(self, setting: str) -> PurposefulActivity | None:
        """The one open or pair activity, or None when this routine has none."""
        return next((a for a in self.activities.values() if a.setting == setting), None)

    @property
    def affordances(self) -> tuple[str, ...]:
        """The affordances an object may offer under this routine, in order."""
        return tuple(
            sorted(a.affordance for a in self.activities.values() if a.object_kind == ANY_KIND)
        )


def _values(catalog: Catalog) -> dict[str, dict[str, FieldValue]]:
    return {entry.key: dict(entry.values) for entry in catalog.entries}


def _claimed(directory: Path) -> None:
    """Refuse a directory holding a file no schema claims, or missing one a schema names.

    The directory is asked what is in it, rather than the versions a model reads being taken as an
    account of it: a catalog dropped in here therefore cannot sit outside every model and every
    digest a society records, and a version a stored society names cannot quietly leave it.
    """
    claimed = {
        f"{schema.catalog_id}.v{schema.catalog_version}.json": schema for schema in SCHEMAS.values()
    }
    present = sorted(path.name for path in directory.glob("*.json"))
    unexpected = sorted(set(present) - set(claimed))
    absent = sorted(set(claimed) - set(present))
    if unexpected or absent:
        raise CatalogError(
            f"{directory}: files with no schema {unexpected}, schemas with no file {absent}"
        )


def load_routine_model(
    directory: Path = ROUTINE_DIRECTORY, versions: Mapping[str, int] | None = None
) -> RoutineModel:
    """Read and cross-check one version of each routine catalog. Every inconsistency is a
    CatalogError.

    ``versions`` names the version of each catalog to read; left out, it is the versions a new
    society reads. A stored society passes the versions it recorded.
    """
    chosen = dict(ROUTINE_VERSIONS if versions is None else versions)
    if set(chosen) != set(ROUTINE_VERSIONS):
        raise CatalogError(f"a routine model reads exactly {sorted(ROUTINE_VERSIONS)}")
    for catalog_id, version in sorted(chosen.items()):
        if (catalog_id, version) not in SCHEMAS:
            raise CatalogError(f"{catalog_id} v{version} has no schema")
    _claimed(directory)
    catalogs = [
        load_catalog(
            directory.joinpath(f"{catalog_id}.v{version}.json"), SCHEMAS[(catalog_id, version)]
        )
        for catalog_id, version in sorted(chosen.items())
    ]
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


def load_purposeful_routine(
    directory: Path = ROUTINE_DIRECTORY, versions: Mapping[str, int] | None = None
) -> PurposefulRoutine:
    """Read and cross-check one version of the purposeful routine. Every inconsistency is a
    CatalogError.

    ``versions`` names the version of each catalog to read; left out, it is the routine a new input
    records. A kind with no entry of its own is used at its affordance's default entry. Reading a
    version never consults the world object catalog, so an input that recorded this version stays
    readable whatever that catalog later drops: whether an entry names a kind that catalog states,
    offering the entry's own affordance, is asked of a routine about to be recorded
    (:func:`check_object_kinds`).
    """
    chosen = dict(PURPOSEFUL_ROUTINE_VERSIONS if versions is None else versions)
    if set(chosen) != set(PURPOSEFUL_ROUTINE_VERSIONS):
        raise CatalogError(
            f"a purposeful routine reads exactly {sorted(PURPOSEFUL_ROUTINE_VERSIONS)}"
        )
    for catalog_id, version in sorted(chosen.items()):
        if (catalog_id, version) not in SCHEMAS:
            raise CatalogError(f"{catalog_id} v{version} has no schema")
    _claimed(directory)
    catalogs = [
        load_catalog(
            directory.joinpath(f"{catalog_id}.v{version}.json"), SCHEMAS[(catalog_id, version)]
        )
        for catalog_id, version in sorted(chosen.items())
    ]
    activities = {
        key: PurposefulActivity(
            key,
            str(v["label"]),
            str(v["setting"]),
            str(v["affordance"]),
            str(v["object_kind"]),
            str(v["choice"]),
            int(v["duration_minimum_ticks"]),  # type: ignore[arg-type]
            int(v["duration_maximum_ticks"]),  # type: ignore[arg-type]
            int(v["relief_milli"]),  # type: ignore[arg-type]
            int(v["preferred_at_need_milli"]),  # type: ignore[arg-type]
            int(v["weight_milli"]),  # type: ignore[arg-type]
            int(v["reach_mm"]),  # type: ignore[arg-type]
            int(v["spacing_mm"]),  # type: ignore[arg-type]
        )
        for key, v in _values(catalogs[0]).items()
    }
    if len({activity.choice for activity in activities.values()}) != 1:
        raise CatalogError("every activity of one routine is chosen by the same rule")
    objects = [a for a in activities.values() if a.setting == "object"]
    defaults = [a.affordance for a in objects if a.object_kind == ANY_KIND]
    if not defaults or len(defaults) != len(set(defaults)):
        raise CatalogError("each affordance has exactly one entry for every kind without its own")
    kinds = [a.object_kind for a in objects if a.object_kind != ANY_KIND]
    if len(kinds) != len(set(kinds)):
        raise CatalogError("an object kind has at most one entry")
    for setting in ("open", "pair"):
        if sum(1 for a in activities.values() if a.setting == setting) > 1:
            raise CatalogError(f"a routine has at most one {setting} activity")
    if any(activity.affordance not in defaults for activity in objects):
        raise CatalogError(
            "every affordance a kind entry offers has an entry for every kind without its own"
        )
    return PurposefulRoutine(
        activities=activities, versions=chosen, sha256=catalog_digest(catalogs)
    )


def load_decision_catalogs(
    directory: Path = ROUTINE_DIRECTORY, versions: Mapping[str, int] | None = None
) -> tuple[dict[str, dict[str, FieldValue]], dict[str, dict[str, FieldValue]], dict[str, int], str]:
    """Read one version of each decision contract catalog: actions, policy, versions and digest.

    ``versions`` names the version of each; left out, it is the contract a new decision request
    records. What the values mean is checked by :mod:`exulanica.world.society_decision_contract`.
    """
    chosen = dict(DECISION_CONTRACT_VERSIONS if versions is None else versions)
    if set(chosen) != set(DECISION_CONTRACT_VERSIONS):
        raise CatalogError(
            f"a decision contract reads exactly {sorted(DECISION_CONTRACT_VERSIONS)}"
        )
    for catalog_id, version in sorted(chosen.items()):
        if (catalog_id, version) not in SCHEMAS:
            raise CatalogError(f"{catalog_id} v{version} has no schema")
    _claimed(directory)
    catalogs = {
        catalog_id: load_catalog(
            directory.joinpath(f"{catalog_id}.v{version}.json"), SCHEMAS[(catalog_id, version)]
        )
        for catalog_id, version in sorted(chosen.items())
    }
    return (
        _values(catalogs[DECISION_ACTION_CATALOG]),
        _values(catalogs[DECISION_POLICY_CATALOG]),
        chosen,
        catalog_digest([catalogs[key] for key in sorted(catalogs)]),
    )


@dataclass(frozen=True, slots=True)
class ComparisonCatalogs:
    """One version each of the score, the comparison protocol and its seeds, by entry key."""

    score: Mapping[str, Mapping[str, FieldValue]]
    protocol: Mapping[str, Mapping[str, FieldValue]]
    seeds: Mapping[str, Mapping[str, FieldValue]]
    versions: Mapping[str, int]
    #: One digest over the three catalogs, as a comparison records what it was scored under.
    sha256: str


def load_comparison_catalogs(
    directory: Path = ROUTINE_DIRECTORY, versions: Mapping[str, int] | None = None
) -> ComparisonCatalogs:
    """Read one version of each comparison catalog. What the values mean is checked by
    :mod:`exulanica.world.society_score` and :mod:`exulanica.world.society_comparison`."""
    chosen = dict(COMPARISON_VERSIONS if versions is None else versions)
    if set(chosen) != set(COMPARISON_VERSIONS):
        raise CatalogError(f"a comparison reads exactly {sorted(COMPARISON_VERSIONS)}")
    for catalog_id, version in sorted(chosen.items()):
        if (catalog_id, version) not in SCHEMAS:
            raise CatalogError(f"{catalog_id} v{version} has no schema")
    _claimed(directory)
    catalogs = {
        catalog_id: load_catalog(
            directory.joinpath(f"{catalog_id}.v{version}.json"), SCHEMAS[(catalog_id, version)]
        )
        for catalog_id, version in sorted(chosen.items())
    }
    return ComparisonCatalogs(
        score=_values(catalogs[PERSON_SCORE_CATALOG]),
        protocol=_values(catalogs[COMPARISON_PROTOCOL_CATALOG]),
        seeds=_values(catalogs[COMPARISON_SEEDS_CATALOG]),
        versions=chosen,
        sha256=catalog_digest([catalogs[key] for key in sorted(catalogs)]),
    )


def check_object_kinds(
    routine: PurposefulRoutine, catalog: WorldObjectCatalog | None = None
) -> None:
    """Refuse by name an entry whose kind the world object catalog lacks or uses otherwise.

    Asked of the routine an input is about to record, against ``catalog`` (left out, the one a
    running host reads), and by a parity test of the catalogs as they are; never when a recorded
    routine is read.
    """
    from exulanica.world.object_catalog import world_object_catalog

    stated = (world_object_catalog() if catalog is None else catalog).by_key()
    for activity in routine.activities.values():
        if activity.setting != "object" or activity.object_kind == ANY_KIND:
            continue
        kind = stated.get(activity.object_kind)
        if kind is None:
            raise CatalogError(
                f"{activity.key} names object kind {activity.object_kind!r}, which the world "
                "object catalog does not state"
            )
        if kind.use.affordance != activity.affordance:
            raise CatalogError(
                f"{activity.key}: object kind {activity.object_kind!r} offers "
                f"{kind.use.affordance!r}, not {activity.affordance!r}"
            )


@cache
def _purposeful(versions: tuple[tuple[str, int], ...], directory: Path) -> PurposefulRoutine:
    return load_purposeful_routine(directory, versions=dict(versions))


def purposeful_routine(versions: Mapping[str, int] | None = None) -> PurposefulRoutine:
    """The purposeful routine of these catalog versions from the directory as it is, read once.

    Left out, the routine a new input records.
    """
    chosen = PURPOSEFUL_ROUTINE_VERSIONS if versions is None else versions
    return _purposeful(
        tuple(sorted((str(k), int(v)) for k, v in chosen.items())), ROUTINE_DIRECTORY
    )
