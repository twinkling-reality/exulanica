"""Host-declared character families and authored recipes, independent of identity and agency.

No development catalog is loaded here. A host explicitly registers reviewed definitions and
current source authorization; saving a recipe neither generates nor certifies a rendered body.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from exulanica.canonical import canonical_json

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[
    str, Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")
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
    choices: tuple[Name, ...] = Field(default=(), max_length=128)

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
