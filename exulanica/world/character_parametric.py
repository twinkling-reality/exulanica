"""The parametric body family: declared controls, bodies prepared per recipe, and their pins.

A parametric family is the second kind of character family a host publishes (profile
:data:`~exulanica.world.character_catalogs.PARAMETRIC_PROFILE`). Where a layered family composes a
person from reviewed parts, a parametric family declares body controls and fits one body per
recipe with a pinned preparer. Its capabilities differ and the document says so: controls are
numeric ranges and a few choices, a body has to be prepared before it can be drawn, it is worn by
the player only, and it has no postures and no distant form.

The published document is **derived**, never authored twice: :func:`parametric_catalog` reads the
authored ``family.json`` the development builder also reads, the committed default body's
``default.look.json``, its reviewed import manifest and the preparation lock, and turns every
fractional control into integer thousandths so the document is a canonical digest input
(:mod:`exulanica.canonical` refuses floats). The default body's render descriptor is measured from
its own bytes by :func:`~exulanica.world.character_bodies.measure_prepared_body`, and refused when
it disagrees with what the builder recorded.

A saved recipe names the body it is drawn with by ``representation_id``. A family's revision
covers only what a recipe means (its controls, choices, bounds and rig), so publishing another
reviewed body never turns a saved recipe into an unknown revision; each body is bound to the exact
recipe input it was prepared for.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from exulanica.canonical import canonical_json
from exulanica.world.asset_import import ReviewedAssetImport, validate_asset_import
from exulanica.world.character_appearance import (
    AssetPin,
    CharacterFamily,
    CharacterRecipe,
    Parameter,
    RepresentationBinding,
    SourcePin,
    document_sha256,
)
from exulanica.world.character_bodies import BodyBudget, BodyDeclaration, measure_prepared_body
from exulanica.world.character_catalogs import PARAMETRIC_PROFILE

__all__ = [
    "PARAMETRIC_CATALOG_ID",
    "PARAMETRIC_FAMILY_PRODUCER",
    "PREPARER_ID",
    "ParametricCatalog",
    "ParametricFamily",
    "body_declaration",
    "is_parametric_family",
    "parametric_catalog",
    "parametric_family_document",
    "parametric_recipe_families",
    "parametric_representation",
    "preparer_recipe",
]

PARAMETRIC_CATALOG_ID: Final = "exulanica-parametric-characters"
#: The code that derives a recipe family from a parametric document. Not the Blender preparer:
#: the preparer's identity belongs to each prepared body, never to what a recipe means.
PARAMETRIC_FAMILY_PRODUCER: Final = "exulanica.parametric-character-family"
PARAMETRIC_FAMILY_PRODUCER_REVISION: Final = "1"
#: In the preparation queue's identifier shape (``^[a-z][a-z0-9.-]*$``, migration 0126).
PREPARER_ID: Final = "exulanica.makehuman-parametric-preparer"
PREPARER_VERSION: Final = 1
REVIEWED_PREFIX: Final = "reviewed:"
PREPARATION_PREFIX: Final = "preparation:"
_MILLI: Final = 1000
_HEX = r"^#[0-9a-f]{6}$"

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[
    str, Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")
]
Choice = Annotated[
    str, Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:/-]*$")
]
Text = Annotated[str, Field(min_length=1, max_length=200)]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Control(_Record):
    key: Name
    label: Text
    group: Text
    #: ``cm`` for whole centimetres; ``milli`` for thousandths of the builder's own control value.
    unit: Literal["cm", "milli"]
    min: StrictInt
    max: StrictInt
    default: StrictInt
    step: Annotated[StrictInt, Field(gt=0)]
    lowLabel: Text | None = None
    highLabel: Text | None = None

    @model_validator(mode="after")
    def bounded(self) -> Control:
        if not self.min <= self.default <= self.max:
            raise ValueError(f"{self.key} default is outside its range")
        return self

    @property
    def denominator(self) -> int:
        return 1 if self.unit == "cm" else _MILLI


class Option(_Record):
    value: Choice
    label: Text


class ChoiceControl(_Record):
    key: Name
    label: Text
    default: Choice
    options: tuple[Option, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def declared(self) -> ChoiceControl:
        values = [o.value for o in self.options]
        if len(set(values)) != len(values) or self.default not in values:
            raise ValueError(f"{self.key} options are unique and include the default")
        return self


class Preset(_Record):
    label: Text
    values: dict[Name, StrictInt | Choice]


class Rig(_Record):
    rigId: Name
    joints: tuple[Name, ...] = Field(min_length=1, max_length=256)
    hips: Name
    feet: tuple[Name, Name]

    @model_validator(mode="after")
    def named(self) -> Rig:
        if len(set(self.joints)) != len(self.joints):
            raise ValueError("rig joints are unique")
        if self.hips not in self.joints or any(f not in self.joints for f in self.feet):
            raise ValueError("calibration joints are rig joints")
        return self


class Clip(_Record):
    name: Name
    speedMillimetresPerSecond: Annotated[StrictInt, Field(ge=0)]


class Descriptor(_Record):
    """How the renderer frames one prepared body, measured from its bytes."""

    unitScaleMillionths: Annotated[StrictInt, Field(gt=0)]
    nativeStandingHeightMillionths: Annotated[StrictInt, Field(gt=0)]
    nativeGroundOffsetMillionths: StrictInt
    forwardYawDegrees: StrictInt
    clips: dict[Literal["idle", "walk", "run"], Clip]
    materialSlots: dict[Name, tuple[Name, ...]]


class Budget(_Record):
    maxBytes: Annotated[StrictInt, Field(gt=0, le=32 * 1024 * 1024)]
    maxTriangles: Annotated[StrictInt, Field(gt=0)]
    maxVertices: Annotated[StrictInt, Field(gt=0)]
    maxJoints: Annotated[StrictInt, Field(gt=0, le=256)]
    maxImages: Annotated[StrictInt, Field(ge=0)]
    maxImagePixels: Annotated[StrictInt, Field(gt=0)]


class AssetRef(_Record):
    assetKey: Annotated[str, Field(pattern=r"^[a-z][a-z0-9.-]{0,199}$")]
    mediaType: Literal["model/gltf-binary"]
    contentSha256: Digest
    byteSize: Annotated[StrictInt, Field(gt=0, le=32 * 1024 * 1024)]
    file: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._/-]*\.glb$")]


class Representation(_Record):
    representationId: Annotated[str, Field(pattern=r"^reviewed:[a-z][a-z0-9.-]{0,199}$")]
    values: dict[Name, StrictInt | Choice]
    recipeInputSha256: Digest
    asset: AssetRef
    importReceiptSha256: Digest
    preparationReceiptSha256: Digest
    descriptor: Descriptor
    measurements: dict[Name, StrictInt]


class Licence(_Record):
    id: Literal["CC0-1.0"]
    file: Text
    sha256: Digest


class Source(_Record):
    title: Text
    url: Text
    revision: Text


class Preparation(_Record):
    preparerId: Name
    preparerVersion: Annotated[StrictInt, Field(ge=1)]
    sourceLockSha256: Digest


class ParametricFamily(_Record):
    familyId: Name
    kind: Literal["parametric-body"]
    label: Text
    licence: Licence
    sources: tuple[Source, ...] = Field(min_length=1, max_length=16)
    permittedUses: tuple[Literal["authored-avatar"], ...] = Field(min_length=1, max_length=1)
    controls: tuple[Control, ...] = Field(min_length=1, max_length=64)
    choices: tuple[ChoiceControl, ...] = Field(max_length=16)
    presets: tuple[Preset, ...] = Field(max_length=32)
    rig: Rig
    clips: dict[Literal["idle", "walk", "run"], Name]
    colourSlots: dict[Name, Annotated[str, Field(pattern=_HEX)]]
    preparation: Preparation
    budget: Budget
    representations: tuple[Representation, ...] = Field(max_length=64)

    @model_validator(mode="after")
    def coherent(self) -> ParametricFamily:
        keys = [c.key for c in self.controls] + [c.key for c in self.choices]
        if len(set(keys)) != len(keys):
            raise ValueError("control and choice keys are unique")
        ids = [r.representationId for r in self.representations]
        if len(set(ids)) != len(ids):
            raise ValueError("representation ids are unique")
        for representation in self.representations:
            recipe_values(self, representation.values)
            if representation.recipeInputSha256 != recipe_input_sha256(representation.values):
                raise ValueError(f"{representation.representationId} is bound to another recipe")
        for preset in self.presets:
            if not set(preset.values) <= set(keys):
                raise ValueError("a preset names only declared controls")
        return self


class ParametricCatalog(_Record):
    profile: Literal["exulanica.parametric-character-catalog/v1"]
    catalogId: Annotated[str, Field(pattern=r"^[a-z][a-z0-9.-]{0,99}$")]
    revision: Annotated[StrictInt, Field(ge=1)]
    families: tuple[ParametricFamily, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def unique(self) -> ParametricCatalog:
        ids = [f.familyId for f in self.families]
        if len(set(ids)) != len(ids):
            raise ValueError("family ids are unique")
        return self


# -- recipes ----------------------------------------------------------------------------------


def recipe_input_sha256(values: Mapping[str, Any]) -> str:
    """The digest a prepared body is bound to: :attr:`CharacterRecipe.input_sha256`, seed 0."""
    return document_sha256({"parameters": dict(values), "seed": 0})


def recipe_values(family: ParametricFamily, values: Mapping[str, Any]) -> dict[str, int | str]:
    """Exactly the family's controls and choices, each inside its declaration, or a refusal."""
    expected = {c.key for c in family.controls} | {c.key for c in family.choices}
    if set(values) != expected:
        raise ValueError("a parametric recipe names exactly the family's controls and choices")
    for control in family.controls:
        value = values[control.key]
        if type(value) is not int or not control.min <= value <= control.max:
            raise ValueError(f"{control.key} is outside {control.min}..{control.max}")
    for choice in family.choices:
        if values[choice.key] not in {o.value for o in choice.options}:
            raise ValueError(f"{choice.key} is not a declared choice")
    return dict(values)


def preparer_recipe(family: ParametricFamily, values: Mapping[str, Any]) -> dict[str, Any]:
    """The builder's recipe for integer values: thousandths back to the builder's own numbers.

    ``value / 1000`` is the nearest double to the decimal the authored family names, the same
    double ``json.loads`` gives the development builder, so a body prepared here and one the
    builder fitted from the same controls are fitted from the same numbers.
    """
    checked = recipe_values(family, values)
    recipe: dict[str, Any] = {}
    for control in family.controls:
        value = checked[control.key]
        recipe[control.key] = value if control.denominator == 1 else value / control.denominator
    for choice in family.choices:
        recipe[choice.key] = checked[choice.key]
    return recipe


def _fixed(value: object, denominator: int, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{where} is not a finite number")
    scaled = value * denominator
    fixed = round(scaled)
    if abs(scaled - fixed) > 1e-6:
        raise ValueError(f"{where} is not a whole number of 1/{denominator}")
    return fixed


def _control(authored: Mapping[str, Any]) -> Control:
    whole = all(
        isinstance(authored[k], int) and not isinstance(authored[k], bool)
        for k in ("min", "max", "default", "step")
    )
    unit = "cm" if authored.get("unit") == "cm" and whole else "milli"
    if authored.get("unit") not in (None, "cm") or (authored.get("unit") == "cm" and not whole):
        raise ValueError(f"{authored['key']} declares a unit this family kind does not read")
    denominator = 1 if unit == "cm" else _MILLI
    return Control(
        key=authored["key"],
        label=authored["label"],
        group=authored["group"],
        unit=unit,
        min=_fixed(authored["min"], denominator, f"{authored['key']} min"),
        max=_fixed(authored["max"], denominator, f"{authored['key']} max"),
        default=_fixed(authored["default"], denominator, f"{authored['key']} default"),
        step=_fixed(authored["step"], denominator, f"{authored['key']} step"),
        lowLabel=authored.get("lowLabel"),
        highLabel=authored.get("highLabel"),
    )


def _values(controls: tuple[Control, ...], recipe: Mapping[str, Any]) -> dict[str, int | str]:
    by_key = {c.key: c for c in controls}
    return {
        key: (_fixed(value, by_key[key].denominator, key) if key in by_key else value)
        for key, value in recipe.items()
    }


# -- the document -----------------------------------------------------------------------------


def body_declaration(family: ParametricFamily, values: Mapping[str, Any]) -> BodyDeclaration:
    """What a body prepared for these values must be, from the family's declarations."""
    checked = recipe_values(family, values)
    height = next(c for c in family.controls if c.unit == "cm")
    materials = {"Skin"}
    if checked.get("hair", "none") != "none":
        materials.add("Hair")
    if checked.get("outfit", "none") != "none":
        materials.add("Clothing")
    budget = family.budget
    return BodyDeclaration(
        joints=family.rig.joints,
        clips=dict(family.clips),
        height_cm=checked[height.key],
        materials=frozenset(materials),
        budget=BodyBudget(
            max_bytes=budget.maxBytes,
            max_triangles=budget.maxTriangles,
            max_vertices=budget.maxVertices,
            max_joints=budget.maxJoints,
            max_images=budget.maxImages,
            max_image_pixels=budget.maxImagePixels,
        ),
        hips=family.rig.hips,
        feet=family.rig.feet,
    )


def parametric_family_document(
    directory: Path,
    *,
    characters: Path,
    budget: Mapping[str, int],
) -> dict[str, Any]:
    """The published family derived from one authored family folder, measured and checked.

    ``directory`` holds ``family.json``, ``default.look.json``, ``source-lock.json``, the licence
    and the default body with its reviewed import manifest (``human-default.import.json``).
    ``characters`` is the catalog root the asset's ``file`` is relative to.
    """
    authored = json.loads((directory / "family.json").read_text())
    look = json.loads((directory / "default.look.json").read_text())
    lock_bytes = (directory / "source-lock.json").read_bytes()
    lock = json.loads(lock_bytes)
    licence_bytes = (directory / "LICENSE.md").read_bytes()
    manifest = ReviewedAssetImport.model_validate_json(
        (directory / "human-default.import.json").read_text()
    )
    payload = (directory / look["file"]).read_bytes()
    receipt = validate_asset_import(manifest, payload, licence_bytes)
    descriptor = look["descriptor"]
    if (descriptor["asset"]["contentSha256"], descriptor["asset"]["byteSize"]) != (
        manifest.content_sha256,
        manifest.byte_size,
    ):
        raise ValueError("the default body's import manifest names other bytes")

    controls = tuple(_control(c) for c in authored["controls"])
    choices = tuple(
        ChoiceControl(
            key=c["key"],
            label=c["label"],
            default=c["default"],
            options=tuple(Option(value=o["value"], label=o["label"]) for o in c["options"]),
        )
        for c in authored["choices"]
    )
    presets = tuple(
        Preset(label=p["label"], values=_values(controls, p["recipe"])) for p in authored["presets"]
    )
    joints = tuple(descriptor["joints"])
    clips = {role: descriptor["clips"][role]["name"] for role in ("idle", "walk", "run")}
    relative = (directory / look["file"]).resolve().relative_to(characters.resolve()).as_posix()
    rig = Rig(
        rigId=descriptor["rigId"],
        joints=joints,
        hips="mixamorig:Hips",
        feet=("mixamorig:LeftFoot", "mixamorig:RightFoot"),
    )
    values = _values(controls, look["recipe"])
    family_budget = Budget(**budget)
    draft = ParametricFamily(
        familyId=authored["familyId"],
        kind="parametric-body",
        label=authored["label"],
        licence=Licence(
            id="CC0-1.0",
            file=(directory / "LICENSE.md").resolve().relative_to(characters.resolve()).as_posix(),
            sha256=hashlib.sha256(licence_bytes).hexdigest(),
        ),
        sources=(
            Source(
                title="MakeHuman system assets (CC0) through MPFB 2",
                url=lock["mpfbRepository"],
                revision=lock["mpfbCommit"],
            ),
            Source(
                title="Quaternius Ultimate Modular Men locomotion",
                url="https://quaternius.com/packs/ultimatemodularcharacters.html",
                revision=lock["animationSha256"],
            ),
        ),
        permittedUses=("authored-avatar",),
        controls=controls,
        choices=choices,
        presets=presets,
        rig=rig,
        clips=clips,
        colourSlots={k: v.lower() for k, v in look["defaultColors"].items()},
        preparation=Preparation(
            preparerId=PREPARER_ID,
            preparerVersion=PREPARER_VERSION,
            sourceLockSha256=hashlib.sha256(lock_bytes).hexdigest(),
        ),
        budget=family_budget,
        representations=(),
    )
    measured = measure_prepared_body(payload, body_declaration(draft, values))
    recorded = {
        "unit scale": (measured.unit_scale_millionths, descriptor["unitScale"] * 1_000_000, 2),
        "rest height": (
            measured.native_rest_height_millionths,
            descriptor["standingHeight"] * 1_000_000,
            2,
        ),
        "idle floor": (
            measured.native_idle_floor_millionths,
            descriptor["groundOffset"] * 1_000_000,
            2,
        ),
        "walk speed": (
            measured.walk_speed_mm_per_s,
            descriptor["clips"]["walk"]["metresPerSecond"] * 1000,
            2,
        ),
        "run speed": (
            measured.run_speed_mm_per_s,
            descriptor["clips"]["run"]["metresPerSecond"] * 1000,
            2,
        ),
    }
    for what, (ours, theirs, tolerance) in recorded.items():
        if abs(ours - theirs) > tolerance:
            raise ValueError(
                f"the default body's {what} measures {ours}, the builder recorded {theirs}"
            )
    representation = Representation(
        representationId=REVIEWED_PREFIX + manifest.asset_key,
        values=values,
        recipeInputSha256=recipe_input_sha256(values),
        asset=AssetRef(
            assetKey=manifest.asset_key,
            mediaType="model/gltf-binary",
            contentSha256=manifest.content_sha256,
            byteSize=manifest.byte_size,
            file=relative,
        ),
        importReceiptSha256=hashlib.sha256(receipt).hexdigest(),
        preparationReceiptSha256=hashlib.sha256(
            canonical_json(look["preparationReceipt"])
        ).hexdigest(),
        descriptor=Descriptor(
            unitScaleMillionths=measured.unit_scale_millionths,
            nativeStandingHeightMillionths=measured.native_rest_height_millionths,
            nativeGroundOffsetMillionths=measured.native_idle_floor_millionths,
            forwardYawDegrees=int(descriptor["forwardYawDegrees"]),
            clips={
                "idle": Clip(name=clips["idle"], speedMillimetresPerSecond=0),
                "walk": Clip(
                    name=clips["walk"], speedMillimetresPerSecond=measured.walk_speed_mm_per_s
                ),
                "run": Clip(
                    name=clips["run"], speedMillimetresPerSecond=measured.run_speed_mm_per_s
                ),
            },
            materialSlots={
                k: tuple(v["materials"]) for k, v in descriptor["materialSlots"].items()
            },
        ),
        measurements=measured.document(),
    )
    family = draft.model_copy(update={"representations": (representation,)})
    return ParametricFamily.model_validate(family.model_dump(mode="json")).model_dump(mode="json")


def parametric_catalog(
    families: list[dict[str, Any]], *, revision: int, catalog_id: str = PARAMETRIC_CATALOG_ID
) -> dict[str, Any]:
    """A publishable parametric catalog of already derived family documents."""
    document = {
        "profile": PARAMETRIC_PROFILE,
        "catalogId": catalog_id,
        "revision": revision,
        "families": families,
    }
    return ParametricCatalog.model_validate(document).model_dump(mode="json")


# -- families and representations -------------------------------------------------------------


def _schema_sha256(catalog: ParametricCatalog, family: ParametricFamily) -> str:
    """What a recipe over this family means: controls, choices, bounds and rig, nothing drawn."""
    return document_sha256(
        {
            "profile": catalog.profile,
            "catalogId": catalog.catalogId,
            "family": {
                "familyId": family.familyId,
                "kind": family.kind,
                "rigId": family.rig.rigId,
                "joints": list(family.rig.joints),
                "controls": [
                    {"key": c.key, "unit": c.unit, "min": c.min, "max": c.max}
                    for c in family.controls
                ],
                "choices": [
                    {"key": c.key, "options": [o.value for o in c.options]} for c in family.choices
                ],
            },
        }
    )


def parametric_recipe_families(document: Mapping[str, Any]) -> tuple[CharacterFamily, ...]:
    """One recipe family per parametric family, each authorized for the player's avatar only."""
    catalog = ParametricCatalog.model_validate(document)
    families = []
    for family in catalog.families:
        schema = _schema_sha256(catalog, family)
        parameters = [
            Parameter(
                key=c.key,
                kind="integer",
                minimum=c.min,
                maximum=c.max,
                unit_denominator=c.denominator,
                default=c.default,
            )
            for c in family.controls
        ] + [
            Parameter(
                key=c.key,
                kind="choice",
                choices=tuple(o.value for o in c.options),
                default=c.default,
            )
            for c in family.choices
        ]
        families.append(
            CharacterFamily(
                family_id=family.familyId,
                family_revision=schema[:16],
                schema_revision=PARAMETRIC_PROFILE,
                rig_id=family.rig.rigId,
                rig_revision=f"joints-{len(family.rig.joints)}",
                rig_sha256=document_sha256(list(family.rig.joints)),
                producer=PARAMETRIC_FAMILY_PRODUCER,
                producer_revision=PARAMETRIC_FAMILY_PRODUCER_REVISION,
                sources=(
                    SourcePin(
                        reference=f"catalog:{catalog.catalogId}:{family.familyId}",
                        revision=schema[:16],
                        content_sha256=schema,
                    ),
                    SourcePin(
                        reference=f"licence:{family.familyId}",
                        revision=family.licence.id,
                        content_sha256=family.licence.sha256,
                    ),
                ),
                permitted_uses=tuple(family.permittedUses),
                parameters=tuple(parameters),
            )
        )
    return tuple(families)


def is_parametric_family(family: CharacterFamily) -> bool:
    return (family.producer, family.schema_revision) == (
        PARAMETRIC_FAMILY_PRODUCER,
        PARAMETRIC_PROFILE,
    )


def declared_family(document: Mapping[str, Any], family_id: str) -> ParametricFamily:
    catalog = ParametricCatalog.model_validate(document)
    found = next((f for f in catalog.families if f.familyId == family_id), None)
    if found is None:
        raise ValueError(f"unknown parametric family {family_id}")
    return found


def parametric_representation(
    document: Mapping[str, Any], family: CharacterFamily, representation_id: str
) -> RepresentationBinding | None:
    """The binding of a reviewed body this publication lists, or None when none is so named."""
    if not representation_id.startswith(REVIEWED_PREFIX):
        return None
    declared = declared_family(document, family.family_id)
    found = next(
        (r for r in declared.representations if r.representationId == representation_id), None
    )
    if found is None:
        return None
    return RepresentationBinding(
        binding_id=found.representationId,
        recipe_input_sha256=found.recipeInputSha256,
        asset=AssetPin(
            asset_key=found.asset.assetKey,
            content_sha256=found.asset.contentSha256,
            receipt_sha256=found.importReceiptSha256,
            byte_size=found.asset.byteSize,
        ),
        rig_id=family.rig_id,
        rig_revision=family.rig_revision,
        rig_sha256=family.rig_sha256,
        producer=declared.preparation.preparerId,
        producer_revision=str(declared.preparation.preparerVersion),
        preparation_receipt_sha256=found.preparationReceiptSha256,
    )


def default_recipe(document: Mapping[str, Any], family: CharacterFamily) -> CharacterRecipe:
    """The family's declared defaults as a recipe, with the reviewed body bound to them if any."""
    declared = declared_family(document, family.family_id)
    values = {p.key: p.default for p in family.parameters}
    representation = next(
        (r.representationId for r in declared.representations if r.values == values), None
    )
    return CharacterRecipe(
        family_id=family.family_id,
        family_sha256=family.sha256,
        parameters=values,
        seed=family.default_seed,
        representation_id=representation,
    )
