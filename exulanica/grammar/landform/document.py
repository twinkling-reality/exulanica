"""A world's land as data: ``exulanica.landform/v1``.

What a world says about its land: the height of its level ground above the sea's level, and the
features it lists, each a kind from the landform catalog with its values held to that catalog's
bounds. Placement is in words (a compass side of the world, or its centre, and distances from
its edge), so a person or a model can write it; the realizer turns the words into heights.

**Closed and bounded.** Top keys are exactly ``profile``, ``ground_mm`` and ``features``. A
feature states ``id`` and ``kind`` and only values its kind's catalog entries name; a required
value must be stated; every integer is held to its bound and every word to its words. A refusal
names the path of what it refused and the bound it broke.

**Defaults are written in.** The canonical document carries every value of every feature, with
the catalog's defaults filled in at reading, so a later catalog default never changes a world
that was made before it. Its identity is the SHA-256 of its canonical JSON.

Integers and keys only; nothing here holds a person's words.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.documents import parse_json
from exulanica.grammar.landform.catalog import LandformCatalog, landform_catalog
from exulanica.grammar.records import KEY_PATTERN

__all__ = [
    "PROFILE",
    "LandDocument",
    "LandFeature",
    "LandformRefused",
    "level_land",
    "read_land_document",
]

PROFILE: Final = "exulanica.landform/v1"
_TOP: Final = frozenset({"profile", "ground_mm", "features"})


class LandformRefused(ValueError):
    """A land document, its realization or its grading cannot be admitted. Says where and why."""

    def __init__(self, detail: str, *, path: str = "", code: str = "landform_invalid") -> None:
        self.detail = detail
        self.path = path
        self.code = code
        super().__init__(f"{path}: {detail}" if path else detail)


@dataclass(frozen=True, slots=True)
class LandFeature:
    id: str
    kind: str
    #: Every value the kind's catalog entries name, stated or defaulted.
    values: Mapping[str, int | str]


@dataclass(frozen=True, slots=True)
class LandDocument:
    ground_mm: int
    features: tuple[LandFeature, ...]
    canonical_bytes: bytes
    sha256: str

    def canonical(self) -> dict[str, Any]:
        return parse_json(self.canonical_bytes.decode(), PROFILE)


def _integer(raw: object, low: int, high: int, path: str, owner: str) -> int:
    if type(raw) is not int:
        raise LandformRefused(f"{owner} states a whole number here, got {raw!r}", path=path)
    if not low <= raw <= high:
        raise LandformRefused(f"{owner} states {raw}, outside {low} to {high}", path=path)
    return raw


def _feature(raw: object, index: int, catalog: LandformCatalog) -> LandFeature:
    path = f"features[{index}]"
    if not isinstance(raw, dict):
        raise LandformRefused("a feature is an object", path=path)
    feature_id = raw.get("id")
    if type(feature_id) is not str or KEY_PATTERN.fullmatch(feature_id) is None:
        raise LandformRefused(f"an id is a lowercase key, got {feature_id!r}", path=f"{path}.id")
    kind = raw.get("kind")
    if kind not in catalog.features:
        raise LandformRefused(
            f"{feature_id}: kind {kind!r} is not one of {sorted(catalog.features)}",
            path=f"{path}.kind",
        )
    bounds = catalog.values_of(str(kind))
    unknown = sorted(set(raw) - {"id", "kind"} - set(bounds))
    if unknown:
        raise LandformRefused(
            f"{feature_id}: a {kind} states no {', '.join(unknown)}; it states {sorted(bounds)}",
            path=path,
        )
    values: dict[str, int | str] = {}
    for name, bound in sorted(bounds.items()):
        where = f"{path}.{name}"
        if name not in raw:
            if bound.required:
                raise LandformRefused(f"{feature_id}: {name} is required", path=where)
            values[name] = bound.words[bound.default] if bound.words else bound.default
        elif bound.words:
            if raw[name] not in bound.words:
                raise LandformRefused(
                    f"{feature_id}: {name} is one of {', '.join(bound.words)}, got {raw[name]!r}",
                    path=where,
                )
            values[name] = raw[name]
        else:
            values[name] = _integer(raw[name], bound.minimum, bound.maximum, where, feature_id)
    return LandFeature(id=feature_id, kind=str(kind), values=values)


def read_land_document(raw: object, catalog: LandformCatalog | None = None) -> LandDocument:
    """Admit a land document against the catalog, or refuse it by path."""
    catalog = catalog or landform_catalog()
    if not isinstance(raw, dict) or set(raw) != _TOP:
        keys = sorted(raw) if isinstance(raw, dict) else type(raw).__name__
        raise LandformRefused(f"a land document has exactly {sorted(_TOP)}, got {keys}")
    if raw["profile"] != PROFILE:
        raise LandformRefused(f"profile is {PROFILE}, got {raw['profile']!r}", path="profile")
    land = catalog.values_of("land")
    ground = _integer(
        raw["ground_mm"], land["ground_mm"].minimum, land["ground_mm"].maximum, "ground_mm", "land"
    )
    features_raw = raw["features"]
    if not isinstance(features_raw, list):
        raise LandformRefused("features is a list", path="features")
    if len(features_raw) > land["features"].maximum:
        raise LandformRefused(
            f"a land lists at most {land['features'].maximum} features, got {len(features_raw)}",
            path="features",
        )
    features: list[LandFeature] = []
    seen: set[str] = set()
    counts: dict[str, int] = {}
    for index, item in enumerate(features_raw):
        feature = _feature(item, index, catalog)
        if feature.id in seen:
            raise LandformRefused(f"id {feature.id} is used twice", path=f"features[{index}].id")
        seen.add(feature.id)
        counts[feature.kind] = counts.get(feature.kind, 0) + 1
        most = catalog.features[feature.kind].most
        if counts[feature.kind] > most:
            raise LandformRefused(
                f"a land lists at most {most} {feature.kind} features", path=f"features[{index}]"
            )
        features.append(feature)
    for index, feature in enumerate(features):
        if feature.kind == "cascade" and int(feature.values["from_mm"]) >= int(
            feature.values["to_mm"]
        ):
            raise LandformRefused(
                f"cascade {feature.id} runs from {feature.values['from_mm']} mm to "
                f"{feature.values['to_mm']} mm; it ends beyond where it begins",
                path=f"features[{index}].to_mm",
            )
        if feature.kind == "shore" and ground < int(feature.values["beach_top_mm"]):
            raise LandformRefused(
                f"shore {feature.id} needs level ground at or above its beach top "
                f"{feature.values['beach_top_mm']} mm, got {ground}",
                path="ground_mm",
            )
    canonical = {
        "profile": PROFILE,
        "ground_mm": ground,
        "features": [
            {"id": feature.id, "kind": feature.kind, **feature.values} for feature in features
        ],
    }
    encoded = canonical_json(canonical)
    return LandDocument(
        ground_mm=ground,
        features=tuple(features),
        canonical_bytes=encoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )


def level_land(ground_mm: int = 0) -> LandDocument:
    """Land with no features: one height everywhere. Every world made before land reads as this."""
    return read_land_document({"profile": PROFILE, "ground_mm": ground_mm, "features": []})
