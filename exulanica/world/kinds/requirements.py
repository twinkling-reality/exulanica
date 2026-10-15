"""Text-free, declared world requirements bound to placed parts, not their display labels."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.grammar.grammars.site.plan import FORMS, ROOF_FORMS

OMISSION_CODES = (
    "unsupported_geometry",
    "unsupported_layout",
    "unsupported_behavior",
    "unavailable_asset",
    "outside_bounds",
)


def check_requirements(
    raw: Mapping[str, Any],
    parts: Mapping[str, Any],
    zones: Sequence[Any],
    site: Mapping[str, Any],
    reader: Any,
) -> None:
    """Validate every declared claim over all admissible values; extraction completeness is
    outside this deterministic contract."""
    from exulanica.world.kinds.document import _HEX64
    from exulanica.world.kinds.reader import (
        _LOOK,
        KindRefused,
        _int,
        _invalid,
        _key,
        _keys,
        _list,
    )

    source = _keys(
        "requirement_source", raw["requirement_source"], frozenset({"sha256", "characters"})
    )
    characters = _int("requirement_source.characters", source["characters"], (1, 1000))
    if type(source["sha256"]) is not str or _HEX64.fullmatch(source["sha256"]) is None:
        raise _invalid("requirement_source.sha256", "is a lowercase SHA-256")
    if raw["origin"] == "drafted" and source["sha256"] != raw["provenance"]["words_sha256"]:
        raise _invalid("requirement_source.sha256", "matches the sent words' provenance")

    counts: dict[str, int] = defaultdict(int)

    def placed(key: str, n: int) -> None:
        counts[key] += n
        part = parts[key]
        if part.form == "structure":
            for child, number in part.fields["rooms"]:
                placed(child, n * reader.limits(number)[0])
        elif part.form == "room":
            for child, number, _pattern in part.fields["holds"]:
                placed(child, n * reader.limits(number)[0])

    counts[site["spine"]] = 1
    if site["boundary"]:
        counts[site["boundary"]] += 1
    for zone in zones:
        if zone.boundary:
            counts[zone.boundary] += 1
        for key, number, _pattern in zone.holds:
            placed(key, reader.limits(number)[0])

    keys = set()
    for index, item in enumerate(_list("requirements", raw["requirements"], (1, 48))):
        where = f"requirements[{index}]"
        requirement = _keys(
            where,
            item,
            frozenset(
                {
                    "key",
                    "source_span",
                    "status",
                    "omission",
                    "form",
                    "roles",
                    "look",
                    "shape_class",
                    "roof_form",
                    "minimum_count",
                    "parts",
                }
            ),
        )
        key = _key(f"{where}.key", requirement["key"])
        if key in keys:
            raise _invalid(where, "does not repeat a requirement key")
        keys.add(key)
        span = _list(f"{where}.source_span", requirement["source_span"], (2, 2))
        start = _int(f"{where}.source_span[0]", span[0], (0, characters - 1))
        _int(f"{where}.source_span[1]", span[1], (start + 1, characters))
        if requirement["status"] not in ("fulfilled", "omitted"):
            raise _invalid(f"{where}.status", "is fulfilled or omitted")
        if requirement["form"] not in ("", *FORMS):
            raise _invalid(f"{where}.form", "is a supported part form or empty")
        if requirement["roof_form"] not in ("", *ROOF_FORMS):
            raise _invalid(f"{where}.roof_form", "is a supported roof form or empty")
        roles = _list(f"{where}.roles", requirement["roles"], (0, len(reader.catalogs.role_forms)))
        if any(type(role) is not str or role not in reader.catalogs.role_forms for role in roles):
            raise _invalid(f"{where}.roles", "names only supported engine roles")
        if len(set(roles)) != len(roles):
            raise _invalid(f"{where}.roles", "does not repeat an engine role")
        look = requirement["look"]
        if look != "" and (
            type(look) is not str
            or _LOOK.fullmatch(look) is None
            or look.split(".")[0] not in reader.catalogs.families
        ):
            raise _invalid(f"{where}.look", "is a supported family.leaf or empty")
        shape = requirement["shape_class"]
        if shape != "":
            _key(f"{where}.shape_class", shape)
            from exulanica.world.kinds.shape_classes import load_shape_classes

            if shape not in load_shape_classes().entries:
                raise _invalid(f"{where}.shape_class", "names a supported structural class")
        minimum = _int(f"{where}.minimum_count", requirement["minimum_count"], (1, 512))
        targets = _list(f"{where}.parts", requirement["parts"], (0, 48))
        for target in targets:
            _key(f"{where}.parts", target)
        if len(set(targets)) != len(targets):
            raise _invalid(f"{where}.parts", "does not repeat a target")
        if requirement["status"] == "omitted":
            if targets or requirement["omission"] not in OMISSION_CODES:
                raise _invalid(where, "an omission has no targets and states a supported reason")
            continue
        if requirement["omission"] != "" or not targets:
            raise _invalid(where, "a fulfilled requirement has targets and no omission")
        if not any((requirement["form"], roles, look, shape, requirement["roof_form"])):
            raise _invalid(where, "a fulfilled requirement declares a form, role, look or shape")
        for target in targets:
            part = parts.get(target)
            if part is None:
                raise KindRefused(
                    "kind_requirement_unmet", "target does not exist", f"{where}.parts"
                )
            if not counts[target]:
                raise KindRefused(
                    "kind_requirement_unmet", "target is not placed", f"{where}.parts"
                )
            if (
                (requirement["form"] and part.form != requirement["form"])
                or not set(roles) <= set(part.roles)
                or (look and part.look.role != look)
                or (shape and (part.fields.get("shape_class") or {}).get("key") != shape)
                or (
                    requirement["roof_form"]
                    and part.fields.get("roof_form") != requirement["roof_form"]
                )
            ):
                raise KindRefused(
                    "kind_requirement_unmet",
                    "placed target does not meet the declared form, roles, look, shape or roof",
                    f"{where}.parts",
                )
        if sum(counts[target] for target in targets) < minimum:
            raise KindRefused(
                "kind_requirement_unmet",
                "minimum placed quantity does not meet the requirement",
                where,
            )
