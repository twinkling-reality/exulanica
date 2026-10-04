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

The contract a model answers under when it runs a person in a world lives in the same directory:
``society-decision-action``, what such a person may be asked to do and how each option reads, and
``society-decision-policy``, the bounds on asking. The person's decision role names them in its
registry entry, with the versions a new request records, and reads them by the schemas every
role's contract is read by (:mod:`exulanica.world.decision_roles`). A decision request records the
versions it was asked under, and a new contract is a new version published beside the old one.

How such a person's hour is scored, and the protocol and seeds a comparison of the models that run
them is made under, are read from the same directory too, :func:`load_comparison_catalogs`:
``society-person-score``, ``society-comparison-protocol`` and ``society-comparison-seeds``, whose
entries commit each seed by the SHA-256 of its text and never state the seed. A comparison records
the versions it was defined under and is read under them, so the first version of each stays beside
the second for as long as a comparison names it. From its third version the seed catalog also
commits each development seed's text beside its digest, which its schema holds to the digest, so a
comparison runs on development seeds with no file beside the server; a held-out seed stays
committed by its digest alone, and an entry that states a held-out seed's text is refused.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from types import MappingProxyType
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
from exulanica.world.role_catalogs import role_action_schema, role_policy_schema
from exulanica.world.society_engines import society_engine

if TYPE_CHECKING:
    from exulanica.world.object_catalog import WorldObjectCatalog

__all__ = [
    "ACTIVITY_SETTINGS",
    "AFFORDANCE_CATALOG",
    "AFFORDANCE_DIGESTS",
    "AFFORDANCE_REASON_CODES",
    "COMPARISON_PROTOCOL_CATALOG",
    "COMPARISON_SCORE_BY_FAMILY",
    "COMPARISON_SEEDS_CATALOG",
    "COMPARISON_VERSIONS",
    "COMPARISON_WINDOWS",
    "DAY_COMPARISON_VERSIONS",
    "DAY_SCORE_BY_FAMILY",
    "HELD_OUT_SEED_TEXT",
    "LEGACY_IDENTITY_CATALOG",
    "LEGACY_IDENTITY_DIGESTS",
    "PERSON_SCORE_CATALOG",
    "POLICY_KEYS_BY_VERSION",
    "PURPOSEFUL_CATALOG",
    "PURPOSEFUL_ROUTINE_VERSIONS",
    "ROUTINE_CATALOG_SETS",
    "ROUTINE_DIRECTORY",
    "ROUTINE_VERSIONS",
    "SHIFT_CATALOG",
    "TOWN_ROUTINE_VERSIONS",
    "UNRECORDED_ROUTINE_VERSIONS",
    "Activity",
    "ActivityKind",
    "CapacityRule",
    "ComparisonCatalogs",
    "LegacyIdentity",
    "Need",
    "PurposefulActivity",
    "PurposefulRoutine",
    "RoutineModel",
    "Shift",
    "UseClass",
    "check_object_kinds",
    "comparison_catalogs_for_engine",
    "legacy_identity",
    "load_comparison_catalogs",
    "load_purposeful_routine",
    "load_routine_model",
    "purposeful_routine",
]

ROUTINE_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "society")
)


def _versions_present(catalog_id: str, directory: Path = ROUTINE_DIRECTORY) -> tuple[int, ...]:
    """Every version of ``catalog_id`` the directory holds a file for, from its file names: a
    catalog whose versions differ only in their values is claimed by one schema, so a new version
    of it is a new file and nothing else."""
    found = []
    for file in directory.glob(f"{catalog_id}.v*.json"):
        number = file.name[len(catalog_id) + 2 : -len(".json")]
        if number.isdigit():
            found.append(int(number))
    return tuple(sorted(found))


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
#: The catalog of the shifts a workplace's positions work, which a town's routine reads beside the
#: others: a use class names the shifts its positions take in turn.
SHIFT_CATALOG: Final = "society-shift"
#: The catalog versions a new town's living society reads (``exulanica-society/v5``): the living
#: routine with each workplace's opening hours and the shifts its positions work
#: (``society-use-class`` v2 over ``society-shift`` v1), and a policy that employs a share of the
#: town's residents and starts its day early (``society-policy`` v2). A town's input records the
#: versions its living place was built under, and its society reads them from there.
TOWN_ROUTINE_VERSIONS: Final = {
    "society-activity": 1,
    "society-capacity": 1,
    "society-need": 1,
    "society-policy": 2,
    SHIFT_CATALOG: 1,
    "society-use-class": 2,
}
#: Every set of catalogs one living routine reads: a district's, and a town's, which adds the
#: shifts its use classes name.
ROUTINE_CATALOG_SETS: Final = (frozenset(ROUTINE_VERSIONS), frozenset(TOWN_ROUTINE_VERSIONS))
#: The one catalog the purposeful society's routine reads.
PURPOSEFUL_CATALOG: Final = "society-purposeful-activity"
#: The purposeful routine a saved world's new input records: people stay a while, varied, at what
#: they use, and some stand or stop to talk.
PURPOSEFUL_ROUTINE_VERSIONS: Final = {PURPOSEFUL_CATALOG: 2}
#: The purposeful routine an input that records none is read under: every input composed before
#: inputs recorded a routine, and every district input, keeps the rules it was recorded with.
UNRECORDED_ROUTINE_VERSIONS: Final = {PURPOSEFUL_CATALOG: 1}
#: What the society records of each kind of activity a purposeful routine offers: the reason codes
#: a goal carries and the outcome a finished stay records. Each entry names the purposeful routine
#: versions it serves, so a recorded routine always resolves the same entries; changing a code is a
#: new version, served to a new routine version. What is said of each kind is the words catalog's
#: (``society-words/society-activity-words``), which changes without a version of this one.
AFFORDANCE_CATALOG: Final = "society-affordance"
#: The digest of each published version, which the loader refuses a file to differ from: the codes
#: in it are recorded in stored societies, and a replay must produce them unchanged.
#: The names, roles, weather and resources the first three engine profiles give a new society:
#: a published version is frozen by its digest, because every stored genesis of those profiles
#: hashes its values, and each version names the profiles it serves.
LEGACY_IDENTITY_CATALOG: Final = "society-legacy-identity"
LEGACY_IDENTITY_DIGESTS: Final = {
    1: "5f8c5a040fe346e7fe61b22f20e3210507f4828d6fc1c93690cb909d09aee455"
}
LEGACY_IDENTITY_KINDS: Final = ("profile", "role", "first_name", "last_name", "weather", "resource")
AFFORDANCE_DIGESTS: Final = {1: "ca280468cc1051bd5f4dfadc72625c9b14be9a9fdeec840b72696349a2d0986b"}
#: The catalogs of the contract a model answers under when it runs a person, and the versions this
#: directory keeps of each: the first offered places and waiting alone, and the second also what
#: the routine has people do at no place. Every request records the versions it was asked under,
#: so every version any request names stays beside the next; the person role's registry entry
#: states which versions a new request records.
_DECISION_CATALOG_VERSIONS: Final = {
    "society-decision-action": (1, 2),
    "society-decision-policy": (1, 2),
}
#: How a person's hour is scored, and the protocol and seeds a comparison of models is made under.
PERSON_SCORE_CATALOG: Final = "society-person-score"
COMPARISON_PROTOCOL_CATALOG: Final = "society-comparison-protocol"
COMPARISON_SEEDS_CATALOG: Final = "society-comparison-seeds"
#: The versions a new comparison is defined under: the score of how people fared, half the need
#: they were spared and half the variety of their hour, with what each model answered reported
#: apart; the protocol whose population bound is derived from a measured replay; and seeds whose
#: development text is committed, with held-out seeds drawn afresh for each judged comparison.
COMPARISON_VERSIONS: Final = {
    PERSON_SCORE_CATALOG: 3,
    COMPARISON_PROTOCOL_CATALOG: 3,
    COMPARISON_SEEDS_CATALOG: 5,
}
#: A run keeps the score semantics for the state family its stored engine writes. The
#: comparison protocol and seed catalog remain the same for both families.
COMPARISON_SCORE_BY_FAMILY: Final = {"purposeful": 3, "living": 4}
#: The windows a comparison runs over: an hour, under the versions above, or a day.
COMPARISON_WINDOWS: Final = ("hour", "day")
#: The versions a comparison over a day is defined under: the fifth score, the fourth's terms over
#: the day assembled exactly from its hours, the fourth protocol, whose window is a day, and the
#: sixth seeds, whose held-out seeds no comparison has run: the fifth's, which an hour's comparison
#: is still defined under, were spent by a judged comparison of a town's hour.
DAY_COMPARISON_VERSIONS: Final = {
    PERSON_SCORE_CATALOG: 5,
    COMPARISON_PROTOCOL_CATALOG: 4,
    COMPARISON_SEEDS_CATALOG: 6,
}
#: The state families a comparison may run over a day, by the score its day is scored under: a
#: living town's, whose people keep the day of its clock. A purposeful society keeps no time of
#: day, so its comparisons run an hour.
DAY_SCORE_BY_FAMILY: Final = {"living": 5}
#: Whether a score term is weighed or only reported, and what a term reads: a run's minutes, the
#: events the engine appended, or the host's record of each call, which only a reader outside the
#: score reads.
SCORE_PARTS: Final = ("primary", "held_out")
SCORE_READS: Final = ("states", "events", "calls")
#: The second score's parts: its one weighed term, what each model answered, reported beside the
#: score and never weighed, and the measures it reports with no weight.
RELIABILITY_PART: Final = "reliability"
SCORE_V2_PARTS: Final = ("primary", RELIABILITY_PART, "held_out")
#: The seeds a comparison may run: development seeds, looked at freely, and held-out seeds, judged.
SEED_PHASES: Final = ("development", "held_out")
#: What a third-version seed entry states as its text where it commits none: a held-out seed.
NO_SEED_TEXT: Final = "none"
#: Why a seed entry is refused: a held-out seed whose text is committed.
HELD_OUT_SEED_TEXT: Final = "held_out_seed_text"
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
#: The policy keys each version of the policy catalog states, compared for exact equality as
#: :data:`POLICY_KEYS` is: the second adds the share of a town's residents who hold a job.
POLICY_KEYS_BY_VERSION: Final = {
    1: POLICY_KEYS,
    2: POLICY_KEYS | {"employment_share_milli"},
}


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


def _optional_key(where: str, value: object) -> FieldValue:
    """A lowercase key, or ``none`` where the entry has nothing of that kind."""
    return _key(where, value)


def _routine_versions(where: str, value: object) -> FieldValue:
    if (
        not isinstance(value, list)
        or not value
        or not all(type(v) is str and v.isdigit() and v[0] != "0" for v in value)
        or value != sorted(set(value), key=int)
    ):
        raise CatalogError(f"{where} lists purposeful routine versions as ascending whole numbers")
    return tuple(value)


def _affordance_bounds(where: str, values: dict[str, FieldValue]) -> None:
    # The planner sends somebody to the nearest place of an object activity under any routine when
    # a goal policy names no preferred target, so every object activity states that reason.
    objects = values["setting"] == "object"
    if objects == (values["nearest_reason"] == NO_KIND):
        raise CatalogError(f"{where}: exactly an object activity states a nearest reason")
    if not objects and values["needed_reason"] != NO_KIND:
        raise CatalogError(f"{where}: only an object activity is needed")


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


def _score_v2_bounds(where: str, values: dict[str, FieldValue]) -> None:
    """The second score's rule, held by the catalog itself: exactly a primary term carries a
    weight and it reads states alone, so no answer, answer time or disposition reaches the score;
    what a model answered is reliability, which reads the engine's events, names the dispositions
    it counts and is never weighed."""
    part, reads = values["part"], values["reads"]
    if (part == "primary") == (values["weight_milli"] == 0):
        raise CatalogError(f"{where}: exactly a primary term carries a weight")
    if part == "primary" and reads != "states":
        raise CatalogError(f"{where}: a weighed term reads states alone")
    if (part == RELIABILITY_PART) != (reads == "events"):
        raise CatalogError(f"{where}: exactly the reliability terms read the engine's events")
    if (part == RELIABILITY_PART) != bool(values["dispositions"]):
        raise CatalogError(f"{where}: exactly a reliability term names the dispositions it counts")
    if values["reasons"] and part != RELIABILITY_PART:
        raise CatalogError(f"{where}: only a reliability term names reason codes")


def _seed_text(where: str, value: object) -> FieldValue:
    if type(value) is not str or not value or value != value.strip() or "\n" in value:
        raise CatalogError(f"{where} is one line of seed text, or {NO_SEED_TEXT!r}")
    return value


def _seed_v3_bounds(where: str, values: dict[str, FieldValue]) -> None:
    """A development seed commits its text, which is the text of its digest; a held-out seed
    commits its digest alone, and an entry stating a held-out seed's text is refused by name."""
    seed = values["seed"]
    if values["phase"] == "held_out":
        if seed != NO_SEED_TEXT:
            raise CatalogError(
                f"{where}: {HELD_OUT_SEED_TEXT}: a held-out seed is committed by its digest alone"
            )
        return
    if hashlib.sha256(str(seed).encode("utf-8")).hexdigest() != values["seed_digest"]:
        raise CatalogError(f"{where}: a development seed's text is the text of its digest")


def _sha256_text(where: str, value: object) -> FieldValue:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CatalogError(f"{where} is a SHA-256 in lowercase hexadecimal, got {value!r}")
    return value


def _use_class_kind_bounds(where: str, values: dict[str, FieldValue]) -> None:
    kind = values["kind"]
    if (kind == "workplace") != (values["staff_per_unit"] != 0):
        raise CatalogError(f"{where}: exactly the workplaces have staff")
    if (kind == "furniture") != (values["role_key"] == "none"):
        raise CatalogError(f"{where}: workplaces and homes name a role, furniture does not")
    if (kind == "residential") != (values["resident_capacity"] != 0):
        raise CatalogError(f"{where}: exactly the residential units house residents")


def _use_class_bounds(where: str, values: dict[str, FieldValue]) -> None:
    _use_class_kind_bounds(where, values)
    if values["kind"] == "workplace" and values["shift_minutes"] == 0:
        raise CatalogError(f"{where}: a workplace declares its shift")


def _shift_keys(where: str, value: object) -> FieldValue:
    """The shifts a use class's positions take in turn, by the shift catalog's keys; a key may
    repeat, since two positions may work one shift."""
    if not isinstance(value, list) or not all(
        type(v) is str and KEY_PATTERN.fullmatch(v) for v in value
    ):
        raise CatalogError(f"{where} lists shift keys")
    return tuple(value)


def _use_class_v2_bounds(where: str, values: dict[str, FieldValue]) -> None:
    """A second-version use class states its opening hours and, exactly for a workplace, the
    shifts its positions work; a closing minute before the opening one wraps past midnight, and an
    opening minute equal to the closing one is refused, since it says neither always nor never."""
    _use_class_kind_bounds(where, values)
    if (values["kind"] == "workplace") != bool(values["shifts"]):
        raise CatalogError(f"{where}: exactly a workplace names the shifts its positions work")
    if values["opening_minute"] == values["closing_minute"]:
        raise CatalogError(f"{where}: opening and closing minutes differ; 0 to 1440 is always")


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
    ("society-use-class", 2): CatalogSchema(
        "society-use-class",
        2,
        (
            ("label", text_field),
            ("kind", _choice(USE_CLASS_KINDS)),
            ("role_key", _key),
            ("role_label", text_field),
            ("staff_per_unit", integer_field(0, 4096)),
            ("visitor_capacity", integer_field(0, 4096)),
            ("resident_capacity", integer_field(0, 4096)),
            ("visitor_affordances", key_list_field),
            ("opening_minute", _MINUTE),
            ("closing_minute", _MINUTE),
            ("shifts", _shift_keys),
            ("reason", text_field),
        ),
        entry_check=_use_class_v2_bounds,
    ),
    (SHIFT_CATALOG, 1): CatalogSchema(
        SHIFT_CATALOG,
        1,
        (
            ("label", text_field),
            ("start_minute", integer_field(0, MINUTES_PER_DAY - 1)),
            ("minutes", _TICKS),
            ("reason", text_field),
        ),
    ),
    **{
        ("society-policy", version): CatalogSchema(
            "society-policy",
            version,
            (("value", integer_field(0, 10**9)), ("reason", text_field)),
        )
        for version in (1, 2)
    },
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
    (LEGACY_IDENTITY_CATALOG, 1): CatalogSchema(
        LEGACY_IDENTITY_CATALOG,
        1,
        (
            ("kind", _choice(LEGACY_IDENTITY_KINDS)),
            ("text", text_field),
            ("milli", integer_field(0, 10**6)),
            ("reason", text_field),
        ),
    ),
    (AFFORDANCE_CATALOG, 1): CatalogSchema(
        AFFORDANCE_CATALOG,
        1,
        (
            ("setting", _choice(PURPOSEFUL_SETTINGS)),
            ("routine_versions", _routine_versions),
            ("drawn_reason", _key),
            ("needed_reason", _optional_key),
            ("nearest_reason", _optional_key),
            ("completed_outcome", _key),
            ("reason", text_field),
        ),
        entry_check=_affordance_bounds,
    ),
    **{
        ("society-decision-action", version): role_action_schema("society-decision-action", version)
        for version in _DECISION_CATALOG_VERSIONS["society-decision-action"]
    },
    **{
        ("society-decision-policy", version): role_policy_schema("society-decision-policy", version)
        for version in _DECISION_CATALOG_VERSIONS["society-decision-policy"]
    },
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
    **{
        (PERSON_SCORE_CATALOG, version): CatalogSchema(
            PERSON_SCORE_CATALOG,
            version,
            (
                ("part", _choice(SCORE_V2_PARTS)),
                ("weight_milli", integer_field(-1000, 1000)),
                ("reads", _choice(SCORE_READS)),
                ("dispositions", key_list_field),
                ("reasons", key_list_field),
                ("reason", text_field),
            ),
            entry_check=_score_v2_bounds,
        )
        for version in (2, 3, 4, 5)
    },
    **{
        (COMPARISON_PROTOCOL_CATALOG, version): CatalogSchema(
            COMPARISON_PROTOCOL_CATALOG,
            version,
            (("value", integer_field(0, 10**9)), ("reason", text_field)),
        )
        for version in _versions_present(COMPARISON_PROTOCOL_CATALOG)
    },
    **{
        (COMPARISON_SEEDS_CATALOG, version): CatalogSchema(
            COMPARISON_SEEDS_CATALOG,
            version,
            (
                ("phase", _choice(SEED_PHASES)),
                ("seed_digest", _sha256_text),
                ("reason", text_field),
            ),
        )
        for version in (1, 2)
    },
    **{
        (COMPARISON_SEEDS_CATALOG, version): CatalogSchema(
            COMPARISON_SEEDS_CATALOG,
            version,
            (
                ("phase", _choice(SEED_PHASES)),
                ("seed_digest", _sha256_text),
                ("seed", _seed_text),
                ("reason", text_field),
            ),
            entry_check=_seed_v3_bounds,
        )
        for version in (3, 4, 5, 6)
    },
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
    #: The shift the use class's first position works, which a place records as its shift.
    shift_start: int
    shift_minutes: int
    #: When it admits visitors, as minutes of the day, or None where its catalog version states
    #: no hours: then its activity's own window is the only one.
    opening: tuple[int, int] | None = None
    #: The shifts its positions work in turn, by the shift catalog's keys; empty where its
    #: catalog version names none, and every position works :attr:`shift_start`.
    shifts: tuple[str, ...] = ()

    def open_at(self, minute: int) -> bool:
        """Whether its hours admit a visitor at this minute of the day; hours may wrap midnight."""
        if self.opening is None:
            return True
        start, end = self.opening
        if start == 0 and end == MINUTES_PER_DAY:
            return True
        if start <= end:
            return start <= minute < end
        return minute >= start or minute < end


@dataclass(frozen=True, slots=True)
class Shift:
    key: str
    label: str
    start_minute: int
    minutes: int


@dataclass(frozen=True, slots=True)
class RoutineModel:
    needs: Mapping[str, Need]
    activities: Mapping[str, Activity]
    capacities: Mapping[str, CapacityRule]
    use_classes: Mapping[str, UseClass]
    policy: Mapping[str, int]
    versions: Mapping[str, int]
    sha256: str
    #: The shifts its use classes name; empty for a routine that reads no shift catalog.
    shifts: Mapping[str, Shift] = field(default_factory=dict)

    @property
    def keeps_hours(self) -> bool:
        """Whether its premises admit visitors by their own hours while a worker is there: a
        routine whose use classes state opening hours."""
        return any(use.opening is not None for use in self.use_classes.values())

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
class ActivityKind:
    """What the society records of one kind of activity (``society-affordance``): the codes a goal
    and a finished stay carry, which stored societies record. What is said of it is the words
    catalog's (``society-words/society-activity-words``), which may change without a new version.

    ``nearest_reason`` is stated for every activity at an object, because the planner sends
    somebody to the nearest one under any routine when a goal policy names no preferred target,
    and is ``None`` for an open or pair activity; ``needed_reason`` is ``None`` for a kind no need
    prefers.
    """

    key: str
    setting: str
    #: The purposeful routine versions this entry serves.
    routine_versions: tuple[int, ...]
    drawn_reason: str
    needed_reason: str | None
    nearest_reason: str | None
    completed_outcome: str


@dataclass(frozen=True, slots=True)
class PurposefulRoutine:
    """The activities of one purposeful routine version, looked up as the planner asks for them."""

    activities: Mapping[str, PurposefulActivity]
    versions: Mapping[str, int]
    sha256: str
    #: Each kind of activity this routine offers, by affordance for an object activity and by its
    #: own key for an open or pair one. Not part of ``sha256``: it is resolved from the version.
    kinds: Mapping[str, ActivityKind] = field(default_factory=dict)

    def kind(self, key: str) -> ActivityKind:
        """What the society records of ``key``, or a refusal naming a kind this routine lacks."""
        try:
            return self.kinds[key]
        except KeyError:
            raise CatalogError(f"this purposeful routine offers no activity {key!r}") from None

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
    if frozenset(chosen) not in ROUTINE_CATALOG_SETS:
        raise CatalogError(
            "a routine model reads exactly one of "
            f"{[sorted(catalogs) for catalogs in ROUTINE_CATALOG_SETS]}"
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
    shifts = {
        key: Shift(
            key,
            str(v["label"]),
            int(v["start_minute"]),  # type: ignore[arg-type]
            int(v["minutes"]),  # type: ignore[arg-type]
        )
        for key, v in by_id.get(SHIFT_CATALOG, {}).items()
    }
    use_classes = {}
    for key, v in by_id["society-use-class"].items():
        offered = tuple(v["visitor_affordances"])  # type: ignore[arg-type]
        if not set(offered) <= affordances:
            raise CatalogError(f"use class {key} offers an affordance no activity uses")
        if bool(offered) != (v["visitor_capacity"] != 0):
            raise CatalogError(f"use class {key}: visitors need both a capacity and an affordance")
        named = tuple(v.get("shifts", ()))  # type: ignore[arg-type]
        if not set(named) <= set(shifts):
            raise CatalogError(f"use class {key} names a shift the shift catalog does not state")
        if named:
            # The first position's shift is the one a place records for the premises.
            first = shifts[named[0]]
            start, minutes = first.start_minute, first.minutes
        else:
            start = int(v.get("shift_start_minute", 0))  # type: ignore[arg-type]
            minutes = int(v.get("shift_minutes", 0))  # type: ignore[arg-type]
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
            start,
            minutes,
            opening=(
                (int(v["opening_minute"]), int(v["closing_minute"]))  # type: ignore[arg-type]
                if "opening_minute" in v
                else None
            ),
            shifts=named,
        )
    policy = {key: int(v["value"]) for key, v in by_id["society-policy"].items()}  # type: ignore[arg-type]
    policy_keys = POLICY_KEYS_BY_VERSION[chosen["society-policy"]]
    if set(policy) != policy_keys:
        raise CatalogError(f"the policy catalog holds exactly {sorted(policy_keys)}")
    if not 0 < policy.get("employment_share_milli", 1000) <= 1000:
        raise CatalogError("the employment share is a positive share of residents, at most 1000")
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
        shifts=shifts,
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
        activities=activities,
        versions=chosen,
        sha256=catalog_digest(catalogs),
        kinds=_activity_kinds(directory, chosen[PURPOSEFUL_CATALOG], activities),
    )


@cache
def _published_activity_kinds(directory: Path) -> tuple[ActivityKind, ...]:
    """Every entry of every published affordance catalog version, each version held to the digest
    it was published with."""
    kinds = []
    for version, digest in sorted(AFFORDANCE_DIGESTS.items()):
        catalog = load_catalog(
            directory.joinpath(f"{AFFORDANCE_CATALOG}.v{version}.json"),
            SCHEMAS[(AFFORDANCE_CATALOG, version)],
        )
        if catalog_digest([catalog]) != digest:
            raise CatalogError(
                f"{AFFORDANCE_CATALOG} v{version} is published and stored societies record its "
                "codes: a change is a new version, never an edit to this one"
            )
        kinds.extend(
            ActivityKind(
                key,
                str(v["setting"]),
                tuple(int(n) for n in v["routine_versions"]),  # type: ignore[union-attr]
                str(v["drawn_reason"]),
                None if v["needed_reason"] == NO_KIND else str(v["needed_reason"]),
                None if v["nearest_reason"] == NO_KIND else str(v["nearest_reason"]),
                str(v["completed_outcome"]),
            )
            for key, v in _values(catalog).items()
        )
    return tuple(kinds)


def _activity_kinds(
    directory: Path, routine_version: int, activities: Mapping[str, PurposefulActivity]
) -> dict[str, ActivityKind]:
    """Every kind of activity one routine version offers, each resolved to exactly one entry of
    one published affordance catalog version that names the routine version."""
    offered = {
        (a.affordance if a.setting == "object" else a.key): a.setting for a in activities.values()
    }
    found: dict[str, ActivityKind] = {}
    for kind in _published_activity_kinds(directory):
        if routine_version not in kind.routine_versions:
            continue
        if kind.key in found:
            raise CatalogError(f"two {AFFORDANCE_CATALOG} entries serve {kind.key!r}")
        found[kind.key] = kind
    stated = {key: kind.setting for key, kind in found.items()}
    if stated != offered:
        raise CatalogError(
            f"purposeful routine v{routine_version} offers {sorted(offered.items())}, and "
            f"{AFFORDANCE_CATALOG} states {sorted(stated.items())} for it"
        )
    for activity in activities.values():
        kind = found[activity.affordance if activity.setting == "object" else activity.key]
        if activity.preferred_at_need and kind.needed_reason is None:
            raise CatalogError(
                f"{activity.key} is preferred at a need, and {kind.key} states no needed reason"
            )
    return found


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


def comparison_catalogs_for_engine(engine_profile: str, window: str = "hour") -> ComparisonCatalogs:
    """The catalogs a new comparison of this stored engine's state family is defined under over
    ``window``: an hour's, with the score of its family, or a day's, for a family whose people
    keep a day (:data:`DAY_SCORE_BY_FAMILY`)."""
    family = society_engine(engine_profile).state_family
    if window == "day":
        score = DAY_SCORE_BY_FAMILY.get(family)
        if score is None:
            raise CatalogError(f"no comparison over a day of a {family} society")
        return load_comparison_catalogs(
            versions={**DAY_COMPARISON_VERSIONS, PERSON_SCORE_CATALOG: score}
        )
    if window != "hour":
        raise CatalogError(f"no comparison window {window!r}")
    score = COMPARISON_SCORE_BY_FAMILY.get(family)
    if score is None:
        raise CatalogError(f"no comparison score for {family} society")
    return load_comparison_catalogs(versions={**COMPARISON_VERSIONS, PERSON_SCORE_CATALOG: score})


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


#: Every reason code a goal may carry for a kind of activity, in any published version: the
#: planner's ``REASON_CODES`` includes them, so the browser has words for each.
AFFORDANCE_REASON_CODES: Final = frozenset(
    code
    for kind in _published_activity_kinds(ROUTINE_DIRECTORY)
    for code in (kind.drawn_reason, kind.needed_reason, kind.nearest_reason)
    if code is not None
)


def _settings_by_kind(directory: Path = ROUTINE_DIRECTORY) -> dict[str, str]:
    """Each kind of activity any published version states, by its key, with its setting: every
    version that states a kind gives it the same setting."""
    found: dict[str, str] = {}
    for kind in _published_activity_kinds(directory):
        if found.setdefault(kind.key, kind.setting) != kind.setting:
            raise CatalogError(f"two {AFFORDANCE_CATALOG} versions set {kind.key!r} differently")
    return found


#: Each kind of activity by its key, with its setting: the kinds the words catalog words.
ACTIVITY_SETTINGS: Final = MappingProxyType(_settings_by_kind())


@dataclass(frozen=True, slots=True)
class LegacyIdentity:
    """What a v1 to v3 society's genesis gives its people and its world, from one version."""

    roles: tuple[str, ...]
    first_names: tuple[str, ...]
    last_names: tuple[str, ...]
    weather: Mapping[str, object]
    resources: Mapping[str, int]


@cache
def legacy_identity(profile: str, directory: Path = ROUTINE_DIRECTORY) -> LegacyIdentity:
    """The identity catalog version serving ``profile``, held to its published digest, or a
    refusal naming a profile no version serves."""
    for version, digest in sorted(LEGACY_IDENTITY_DIGESTS.items()):
        catalog = load_catalog(
            directory.joinpath(f"{LEGACY_IDENTITY_CATALOG}.v{version}.json"),
            SCHEMAS[(LEGACY_IDENTITY_CATALOG, version)],
        )
        if catalog_digest([catalog]) != digest:
            raise CatalogError(
                f"{LEGACY_IDENTITY_CATALOG} v{version} is published and stored societies hash its "
                "values: a change is a new version, never an edit to this one"
            )
        entries = _values(catalog)

        def of(
            kind: str, entries: dict[str, dict[str, FieldValue]] = entries
        ) -> list[tuple[str, dict[str, FieldValue]]]:
            return [(key, v) for key, v in entries.items() if v["kind"] == kind]

        if profile not in {str(v["text"]) for _, v in of("profile")}:
            continue
        (weather,) = (v for _, v in of("weather"))
        return LegacyIdentity(
            roles=tuple(str(v["text"]) for _, v in of("role")),
            first_names=tuple(str(v["text"]) for _, v in of("first_name")),
            last_names=tuple(str(v["text"]) for _, v in of("last_name")),
            weather=MappingProxyType(
                {"kind": str(weather["text"]), "temperature_c_milli": int(weather["milli"])}  # type: ignore[arg-type]
            ),
            resources=MappingProxyType(
                {key: int(v["milli"]) for key, v in of("resource")}  # type: ignore[arg-type]
            ),
        )
    raise CatalogError(f"no {LEGACY_IDENTITY_CATALOG} version serves the profile {profile!r}")
