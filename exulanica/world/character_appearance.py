"""Host-declared character families and authored recipes, independent of identity and agency.

No development catalog is loaded here. A host explicitly registers reviewed definitions and
current source authorization; saving a recipe neither generates nor certifies a rendered body.
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from exulanica.canonical import canonical_json

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[
    str, Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")
]
# Catalog entry ids keep their upstream asset names, which use underscores.
ChoiceName = Annotated[
    str, Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:/-]*$")
]
# Fixed-point integer values keep the existing canonical digest contract deterministic.
# A numeric parameter's unit_denominator declares how its stored integer is displayed.
Value = StrictInt | Annotated[str, Field(strict=True, max_length=200)]


class AppearanceUnavailable(ValueError):
    """A configured source or subject cannot currently authorize this operation."""


class StaleAppearance(ValueError):
    """Another committed appearance revision changed the caller's base."""


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CharacterSubject(Record):
    kind: Literal["avatar", "synthetic-inhabitant"]
    subject_id: uuid.UUID
    society_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def binding(self) -> CharacterSubject:
        if (self.kind == "synthetic-inhabitant") != (self.society_id is not None):
            raise ValueError("only a synthetic inhabitant names a society")
        return self


class SourcePin(Record):
    reference: Name
    revision: Name
    content_sha256: Digest


class AssetPin(Record):
    asset_key: Name
    content_sha256: Digest
    receipt_sha256: Digest
    byte_size: Annotated[StrictInt, Field(gt=0, le=32 * 1024 * 1024)]


class Parameter(Record):
    key: Name
    kind: Literal["integer", "choice", "color"]
    default: Value
    minimum: StrictInt | None = None
    maximum: StrictInt | None = None
    unit_denominator: Annotated[StrictInt, Field(ge=1, le=1000000)] = 1
    choices: tuple[ChoiceName, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def definition(self) -> Parameter:
        if self.kind == "integer":
            if (
                self.minimum is None
                or self.maximum is None
                or self.minimum > self.maximum
                or self.choices
            ):
                raise ValueError("integer parameters require an ordered bounded range")
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError("only integer parameters have numeric bounds")
        if self.kind == "choice" and (
            not self.choices or len(set(self.choices)) != len(self.choices)
        ):
            raise ValueError("choice parameters require unique choices")
        if self.kind != "choice" and self.choices:
            raise ValueError("only choice parameters have choices")
        self.validate_value(self.default)
        return self

    def validate_value(self, value: Value) -> None:
        if self.kind == "integer":
            if type(value) is not int or not self.minimum <= value <= self.maximum:
                raise ValueError(f"{self.key} is outside its declared numeric range")
        elif self.kind == "choice":
            if value not in self.choices:
                raise ValueError(f"{self.key} is not a declared choice")
        elif not isinstance(value, str) or re.fullmatch(r"#[0-9a-f]{6}", value) is None:
            raise ValueError(f"{self.key} must be a lowercase RGB hex color")


class RepresentationBinding(Record):
    binding_id: Name
    # Exact parameter/seed input that this prepared asset represents, never any future edit.
    recipe_input_sha256: Digest
    asset: AssetPin
    rig_id: Name
    rig_revision: Name
    rig_sha256: Digest
    producer: Name
    producer_revision: Name
    preparation_receipt_sha256: Digest


class CharacterFamily(Record):
    profile: Literal["exulanica.character-family/v1"] = "exulanica.character-family/v1"
    family_id: Name
    family_revision: Name
    schema_revision: Name
    rig_id: Name
    rig_revision: Name
    rig_sha256: Digest
    producer: Name
    producer_revision: Name
    sources: tuple[SourcePin, ...] = Field(min_length=1, max_length=128)
    permitted_uses: tuple[Literal["authored-avatar", "synthetic-inhabitant"], ...] = Field(
        min_length=1, max_length=2
    )
    parameters: tuple[Parameter, ...] = Field(min_length=1, max_length=128)
    default_seed: Annotated[StrictInt, Field(ge=0, le=2**32 - 1)] = 0
    representations: tuple[RepresentationBinding, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def unique_bindings(self) -> CharacterFamily:
        for values in (
            [p.key for p in self.parameters],
            [r.binding_id for r in self.representations],
            [s.reference for s in self.sources],
        ):
            if len(values) != len(set(values)):
                raise ValueError("family declarations must have unique keys")
        for binding in self.representations:
            if (binding.rig_id, binding.rig_revision, binding.rig_sha256) != (
                self.rig_id,
                self.rig_revision,
                self.rig_sha256,
            ):
                raise ValueError("representation must use the family's exact rig")
        return self

    @property
    def sha256(self) -> str:
        return document_sha256(self.model_dump(mode="json"))


class CharacterRecipe(Record):
    profile: Literal["exulanica.character-recipe/v1"] = "exulanica.character-recipe/v1"
    family_id: Name
    family_sha256: Digest
    parameters: dict[Name, Value] = Field(min_length=1, max_length=128)
    seed: Annotated[StrictInt, Field(ge=0, le=2**32 - 1)]
    representation_id: Name | None = None

    @property
    def input_sha256(self) -> str:
        return document_sha256({"parameters": self.parameters, "seed": self.seed})


def document_sha256(document: object) -> str:
    return hashlib.sha256(canonical_json(document)).hexdigest()


def validate_recipe(
    recipe: CharacterRecipe, family: CharacterFamily, subject: CharacterSubject
) -> RepresentationBinding | None:
    if recipe.family_id != family.family_id or recipe.family_sha256 != family.sha256:
        raise ValueError("recipe must name the exact configured family revision")
    use = "authored-avatar" if subject.kind == "avatar" else "synthetic-inhabitant"
    if use not in family.permitted_uses:
        raise AppearanceUnavailable("family does not permit this use")
    if set(recipe.parameters) != {p.key for p in family.parameters}:
        raise ValueError("recipe must provide exactly the declared parameters")
    for parameter in family.parameters:
        parameter.validate_value(recipe.parameters[parameter.key])
    if recipe.representation_id is None:
        return None
    binding = next(
        (r for r in family.representations if r.binding_id == recipe.representation_id), None
    )
    if binding is None or binding.recipe_input_sha256 != recipe.input_sha256:
        raise ValueError("representation is not prepared for these exact recipe inputs")
    return binding


# Catalog looks. The backend twin of web/packages/atlas-react/src/playcanvas/character/look.ts:
# the same draw, byte for byte, and the recipe families a saved look is validated against.

CHARACTER_CATALOG_PROFILE: Final = "exulanica.character-catalog/v1"
CHARACTER_LOOK_PROFILE: Final = "exulanica.character-look/v1"
CHARACTER_LOOKS_PROFILE: Final = "exulanica.character-looks/v1"
CHARACTER_DRAW_PROFILE: Final = "exulanica.character-draw/v1"
CATALOG_FAMILY_PRODUCER: Final = "exulanica.character-catalog-family"
CATALOG_FAMILY_PRODUCER_REVISION: Final = "1"
_PRINTABLE_ASCII = re.compile(r"[\x20-\x7e]*")
_SLOT_KINDS: Final = ("part", "material", "colour")
_U32 = 1 << 32


class DrawStream:
    """A reproducible stream of 32-bit integers from SHA-256 in counter mode."""

    def __init__(self, domain: str, subject_id: str) -> None:
        for text in (domain, subject_id):
            if not isinstance(text, str) or _PRINTABLE_ASCII.fullmatch(text) is None:
                raise ValueError("draw domains and subjects are printable ASCII")
        self._seed = canonical_json(
            {"domain": domain, "profile": CHARACTER_DRAW_PROFILE, "subject": subject_id}
        )
        self._block = b""
        self._offset = 0
        self._counter = 0

    def next(self) -> int:
        if self._offset + 4 > len(self._block):
            counter = self._counter.to_bytes(4, "big")
            self._block = hashlib.sha256(self._seed + counter).digest()
            self._counter += 1
            self._offset = 0
        value = int.from_bytes(self._block[self._offset : self._offset + 4], "big")
        self._offset += 4
        return value

    def below(self, bound: int) -> int:
        """An integer in [0, bound), exact: floor(u32 * bound / 2**32)."""
        if type(bound) is not int or not 1 <= bound <= 0x200000:
            raise ValueError("draw bound out of range")
        return (self.next() * bound) >> 32

    def weighted(self, weights: Mapping[str, int]) -> str:
        """A weighted key; keys are visited in sorted order, never insertion order."""
        keys = sorted(weights)
        pick = self.below(sum(weights[key] for key in keys))
        for key in keys:
            pick -= weights[key]
            if pick < 0:
                return key
        raise AssertionError("unreachable weighted draw")

    def triangular(self, minimum: int, mode: int, maximum: int) -> int:
        """Triangular integer draw by exact inverse CDF."""
        span = maximum - minimum
        if span == 0:
            return minimum
        left, right = mode - minimum, maximum - mode
        u = self.next()
        if span > 0x100000 or span * left > 0x1FFFFF or span * right > 0x1FFFFF:
            raise ValueError("triangular range too wide")
        if u * span < left * _U32:
            return minimum + math.isqrt((u * span * left) >> 32)
        return maximum - math.isqrt(((_U32 - 1 - u) * span * right) >> 32)


def catalog_family(catalog: Mapping[str, Any], family_id: str) -> Mapping[str, Any]:
    family = next((f for f in catalog["families"] if f["familyId"] == family_id), None)
    if family is None:
        raise ValueError(f"unknown character family {family_id}")
    return family


def catalog_base(family: Mapping[str, Any], base_id: str) -> Mapping[str, Any]:
    base = next((b for b in family["bases"] if b["baseId"] == base_id), None)
    if base is None:
        raise ValueError(f"unknown {family['familyId']} base {base_id}")
    return base


def look_sha256(look: Mapping[str, Any]) -> str:
    return document_sha256(look)


def validate_look(
    catalog: Mapping[str, Any], look: Mapping[str, Any]
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Refuse anything but exactly a recipe over one base of a catalog family."""
    expected = {"profile", "familyId", "baseId", "parts", "materials", "colours", "parameters"}
    if not isinstance(look, Mapping) or set(look) != expected:
        raise ValueError("a look has exactly the declared fields")
    if look["profile"] != CHARACTER_LOOK_PROFILE:
        raise ValueError("unsupported look profile")
    family = catalog_family(catalog, look["familyId"])
    base = catalog_base(family, look["baseId"])
    slots = {kind: [s for s in family["slots"] if s["kind"] == kind] for kind in _SLOT_KINDS}
    for field, names in (
        ("parts", [s["slot"] for s in slots["part"]]),
        ("materials", [s["slot"] for s in slots["material"]]),
        ("colours", [s["slot"] for s in slots["colour"]]),
        ("parameters", [p["key"] for p in family["parameters"]]),
    ):
        if not isinstance(look[field], Mapping) or set(look[field]) != set(names):
            raise ValueError(f"{field} must be exactly {', '.join(sorted(names))}")
    for slot in slots["part"]:
        chosen = look["parts"][slot["slot"]]
        if chosen is None:
            if not slot["optional"]:
                raise ValueError(f"{slot['slot']} is required")
        elif not any(p["partId"] == chosen and p["slot"] == slot["slot"] for p in base["parts"]):
            raise ValueError(f"{chosen} is not a {slot['slot']} on {base['baseId']}")
    for slot in slots["material"]:
        if look["materials"][slot["slot"]] not in base["materials"].get(slot["slot"], ()):
            raise ValueError(f"not a {slot['slot']} on {base['baseId']}")
    for slot in slots["colour"]:
        keys = [c["key"] for c in family["colours"].get(slot["slot"], ())]
        if look["colours"][slot["slot"]] not in keys:
            raise ValueError(f"not a {slot['slot']}")
    for parameter in family["parameters"]:
        value = look["parameters"][parameter["key"]]
        bounds = base["heightMillimetres"] if parameter["unit"] == "mm" else parameter
        if type(value) is not int or not bounds["min"] <= value <= bounds["max"]:
            raise ValueError(f"{parameter['key']} is outside {bounds['min']}..{bounds['max']}")
    return family, base


def draw_look(catalog: Mapping[str, Any], domain: str, subject_id: str) -> dict[str, Any]:
    """The default look of a subject in a named draw domain; identical to the browser's draw."""
    profile = next((p for p in catalog["population"] if p["domain"] == domain), None)
    if profile is None:
        raise ValueError(f"unknown character draw domain {domain}")
    family = catalog_family(catalog, profile["familyId"])
    stream = DrawStream(domain, subject_id)
    base_id = stream.weighted(profile["bases"])
    base = catalog_base(family, base_id)
    choices = profile["choices"][base_id]
    parts: dict[str, str | None] = {}
    materials: dict[str, str] = {}
    colours: dict[str, str] = {}
    parameters: dict[str, int] = {}
    for slot in family["slots"]:
        if slot["kind"] == "part":
            chosen = stream.weighted(choices[slot["slot"]])
            parts[slot["slot"]] = None if chosen == "none" else chosen
        elif slot["kind"] == "material":
            materials[slot["slot"]] = stream.weighted(choices[slot["slot"]])
        else:
            colours[slot["slot"]] = stream.weighted(profile["colours"][slot["slot"]])
    for parameter in family["parameters"]:
        spread = profile["parameters"][base_id][parameter["key"]]
        parameters[parameter["key"]] = stream.triangular(
            spread["min"], spread["mode"], spread["max"]
        )
    look = {
        "profile": CHARACTER_LOOK_PROFILE,
        "familyId": family["familyId"],
        "baseId": base["baseId"],
        "parts": parts,
        "materials": materials,
        "colours": colours,
        "parameters": parameters,
    }
    validate_look(catalog, look)
    return look


def catalog_base_schema_sha256(
    catalog: Mapping[str, Any], family: Mapping[str, Any], base: Mapping[str, Any]
) -> str:
    """Digest of what a saved look over one base depends on.

    Population weights, draw domains and the other bases are left out, so tuning the street
    population or adding to another body never turns a saved look into an unknown revision.
    """
    used = {part["material"] for part in base["parts"]}
    used.update(material for ids in base["materials"].values() for material in ids)
    return document_sha256(
        {
            "profile": catalog["profile"],
            "catalogId": catalog["catalogId"],
            "family": {
                key: family[key]
                for key in (
                    "familyId",
                    "kind",
                    "rigId",
                    "joints",
                    "licence",
                    "slots",
                    "parameters",
                    "colours",
                )
            },
            "base": base,
            "materials": [m for m in family["materials"] if m["materialId"] in used],
        }
    )


def catalog_recipe_families(
    catalog: Mapping[str, Any], looks: Mapping[str, Any]
) -> tuple[CharacterFamily, ...]:
    """One authored-avatar recipe family per catalog base, defaulting to its designed look.

    A recipe over a base family names parts, materials and colours by catalog id and carries
    height and morph weights as integers, so the existing revision history saves and resets it
    unchanged. Changing the body is choosing the other base's family.
    """
    if catalog.get("profile") != CHARACTER_CATALOG_PROFILE:
        raise ValueError("unsupported character catalog profile")
    designed = designed_looks(catalog, looks)
    families = []
    for family in catalog["families"]:
        for base in family["bases"]:
            default = designed[looks["defaults"]["bases"][base["baseId"]]]["look"]
            if (default["familyId"], default["baseId"]) != (family["familyId"], base["baseId"]):
                raise ValueError(f"{base['baseId']} default look is over another base")
            parameters = []
            for slot in family["slots"]:
                key = slot["slot"]
                if slot["kind"] == "part":
                    choices = [p["partId"] for p in base["parts"] if p["slot"] == key]
                    choices += ["none"] if slot["optional"] else []
                    value = default["parts"][key] or "none"
                elif slot["kind"] == "material":
                    choices, value = list(base["materials"][key]), default["materials"][key]
                else:
                    choices = [c["key"] for c in family["colours"][key]]
                    value = default["colours"][key]
                parameters.append(
                    Parameter(key=key, kind="choice", choices=tuple(choices), default=value)
                )
            for parameter in family["parameters"]:
                bounds = base["heightMillimetres"] if parameter["unit"] == "mm" else parameter
                parameters.append(
                    Parameter(
                        key=parameter["key"],
                        kind="integer",
                        minimum=bounds["min"],
                        maximum=bounds["max"],
                        unit_denominator=1 if parameter["unit"] == "mm" else 1000,
                        default=default["parameters"][parameter["key"]],
                    )
                )
            schema = catalog_base_schema_sha256(catalog, family, base)
            licence = family["licence"]
            families.append(
                CharacterFamily(
                    family_id=f"{family['familyId']}/{base['baseId']}",
                    family_revision=schema[:16],
                    schema_revision=catalog["profile"],
                    rig_id=family["rigId"],
                    rig_revision=f"joints-{len(family['joints'])}",
                    rig_sha256=document_sha256(family["joints"]),
                    producer=CATALOG_FAMILY_PRODUCER,
                    producer_revision=CATALOG_FAMILY_PRODUCER_REVISION,
                    sources=(
                        SourcePin(
                            reference=f"catalog:{catalog['catalogId']}:{family['familyId']}/"
                            f"{base['baseId']}",
                            revision=schema[:16],
                            content_sha256=schema,
                        ),
                        SourcePin(
                            reference=f"licence:{family['familyId']}",
                            revision=licence["id"],
                            content_sha256=licence["sha256"],
                        ),
                    ),
                    permitted_uses=("authored-avatar",),
                    parameters=tuple(parameters),
                )
            )
    return tuple(families)


def designed_looks(
    catalog: Mapping[str, Any], looks: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    """The committed designed looks, each validated against the catalog, by look id."""
    if looks.get("profile") != CHARACTER_LOOKS_PROFILE or looks.get("catalogId") != catalog.get(
        "catalogId"
    ):
        raise ValueError("designed looks name another catalog or profile")
    by_id: dict[str, Mapping[str, Any]] = {}
    for entry in looks["looks"]:
        if set(entry) != {"lookId", "label", "look"} or entry["lookId"] in by_id:
            raise ValueError("designed looks have unique ids, a label and a look")
        validate_look(catalog, entry["look"])
        by_id[entry["lookId"]] = entry
    defaults = looks["defaults"]
    named = [defaults["player"], *defaults["bases"].values()]
    if set(defaults) != {"player", "bases"} or any(name not in by_id for name in named):
        raise ValueError("designed defaults name unknown looks")
    bases = {b["baseId"] for f in catalog["families"] for b in f["bases"]}
    if set(defaults["bases"]) != bases:
        raise ValueError("every catalog base needs exactly one designed default")
    return by_id


def recipe_from_look(look: Mapping[str, Any], family: CharacterFamily) -> CharacterRecipe:
    """The saved-recipe form of a look over the base this family was derived from."""
    if family.family_id != f"{look['familyId']}/{look['baseId']}":
        raise ValueError("look is over another base family")
    values: dict[str, int | str] = {}
    for record in ("parts", "materials", "colours", "parameters"):
        for key, value in look[record].items():
            values[key] = "none" if value is None else value
    return CharacterRecipe(
        family_id=family.family_id,
        family_sha256=family.sha256,
        parameters=values,
        seed=family.default_seed,
    )


def look_from_recipe(
    catalog: Mapping[str, Any], recipe: CharacterRecipe, family: CharacterFamily
) -> dict[str, Any]:
    """The look a saved recipe over a catalog base family names, validated against the catalog."""
    family_id, _, base_id = recipe.family_id.rpartition("/")
    if recipe.family_id != family.family_id or recipe.family_sha256 != family.sha256:
        raise ValueError("recipe must name the exact configured family revision")
    declared = catalog_family(catalog, family_id)
    look: dict[str, Any] = {
        "profile": CHARACTER_LOOK_PROFILE,
        "familyId": family_id,
        "baseId": base_id,
        "parts": {},
        "materials": {},
        "colours": {},
        "parameters": {},
    }
    record = {"part": "parts", "material": "materials", "colour": "colours"}
    for slot in declared["slots"]:
        value = recipe.parameters.get(slot["slot"])
        look[record[slot["kind"]]][slot["slot"]] = None if value == "none" else value
    for parameter in declared["parameters"]:
        look["parameters"][parameter["key"]] = recipe.parameters.get(parameter["key"])
    validate_look(catalog, look)
    return look
