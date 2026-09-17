"""The generic grammar contract. Nothing here knows what any grammar makes.

A grammar is a :class:`GrammarKey` (id and version), a :class:`DeclaredSemantics`, a closed
:class:`~exulanica.grammar.parameters.ParameterSchema`, its own
:class:`~exulanica.grammar.parameters.ParameterCascade`, and an ordered tuple of stages. Its
identity, semantics, schema and cascade are read from a versioned descriptor file; its stages
are code. :func:`generate` runs the stages in order and returns a :class:`GrammarReceipt` beside
what they emitted. The receipt carries the six fields ``docs/world-memory-model.md`` section 5.1
requires of any durable procedural record: the admitted subject identity, the grammar (id and
version), the resolved parameters, the seed, the output digest, and the declared semantics.

**A stage that is not implemented emits nothing and says so.** :class:`UnimplementedStage`
returns an emission whose status is ``not_implemented`` with a stated reason and no records. A
skeleton is never allowed to look finished by emitting plausible output.

**Every emission is checked twice before it is digested**: by the stage's own validator, record
by record, and by canonical JSON, which refuses any float anywhere.

**Descriptor schema 2** states more of the grammar as data, and :meth:`Grammar.from_descriptor`
holds the code to it:

* ``frame``: the coordinate frame every record is written in, with its metric class. An invented
  grammar may not claim ``metric_measured``.
* ``stages``: every stage id and version in order, and the record kinds and versions each stage
  validates. A stage of a schema 2 grammar exposes ``validators`` so this can be checked.
* ``parameters``: each declared with its unit, cascade level, reading stage, vocabulary and basis
  (see :mod:`exulanica.grammar.parameters`).
* ``projections``: one representation contract per admitted projection, in which what the
  projection preserves and what it does not are separate rows, and every use in
  :data:`PROJECTION_USES` has exactly one verdict row. A preserved property a consumer builds to
  by number (:data:`PROPERTY_MEASURES`) states its integer measures as data, not in the
  statement's prose, so a reader takes the numbers from one place. A projection admits its own
  use. No contract may admit ``personal_world``: a generated world reaches no person's world
  until the superseding governance decision is accepted in writing, and lifting that is a code
  change here, not a descriptor edit. No contract may admit ``citation``: generated content is
  never evidence (ADR-0008).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Final, Protocol

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.grammar.documents import read_json, split_versioned_name
from exulanica.grammar.draw import DomainCursor
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.parameters import (
    CascadeBinding,
    ParameterCascade,
    ParameterSchema,
    ParameterValue,
    ResolvedParameters,
)
from exulanica.grammar.records import (
    KEY_PATTERN,
    record_payload,
    require_hex64,
    require_identity,
    require_integer,
    require_key,
    require_text,
)
from exulanica.grammar.seed import require_seed
from exulanica.grammar.subjects import subject_identity as _derive_subject_identity

__all__ = [
    "ADMISSIBLE_USES",
    "FRAME_METRIC_CLASSES",
    "PLANE",
    "PROJECTION_OWN_USE",
    "PROJECTION_USES",
    "PROPERTY_MEASURES",
    "REFUSED_USES",
    "STAGE_STATUSES",
    "USE_VERDICTS",
    "DeclaredSemantics",
    "Generation",
    "Grammar",
    "GrammarFrame",
    "GrammarKey",
    "GrammarReceipt",
    "ParameterSurface",
    "ProjectionContract",
    "PropertyRow",
    "Stage",
    "StageContext",
    "StageDeclaration",
    "StageEmission",
    "UnimplementedStage",
    "UseRow",
    "generate",
]

#: The one plane this package can declare. Generated content is invented, never recorded,
#: interpreted, authored or simulated, and a receipt says so in a field a consumer reads.
PLANE: Final = "invented"

#: The named projections of the target architecture. A grammar lists the ones its output is
#: admissible for; an empty list means admissible for none of them yet.
ADMISSIBLE_USES: Final = (
    "render_batch",
    "collision_proxy",
    "nav_envelope",
    "pick_geometry",
    "export_gltf",
)

STAGE_STATUSES: Final = ("emitted", "not_implemented")

#: The uses a representation contract gives a verdict on, in order. The first five are the
#: projections' own uses; the last three are contexts a projection may be carried into.
PROJECTION_USES: Final = (
    "display",
    "collision",
    "navigation",
    "picking",
    "interchange_export",
    "evaluation",
    "personal_world",
    "citation",
)
#: The use each projection exists for, which its contract must admit.
PROJECTION_OWN_USE: Final = {
    "render_batch": "display",
    "collision_proxy": "collision",
    "nav_envelope": "navigation",
    "pick_geometry": "picking",
    "export_gltf": "interchange_export",
}
#: Uses no contract may admit, and why, stated where a reader of the refusal will look.
REFUSED_USES: Final = {
    "personal_world": "a generated world is reachable from no person's world until the "
    "superseding governance decision is accepted in writing",
    "citation": "generated content is never evidence (ADR-0008)",
}
USE_VERDICTS: Final = ("admitted", "refused")


def _capsule_measures(measures: Mapping[str, int]) -> None:
    if measures["eye_height_mm"] >= measures["height_mm"]:
        raise InvalidRecordError("capsule_clearance: the eye is below the top of the capsule")
    if 2 * measures["radius_mm"] > measures["height_mm"]:
        raise InvalidRecordError("capsule_clearance: a capsule is at least as tall as it is wide")


#: Properties a consumer builds to by number, the integer measures a preserved row of each states
#: (sorted, each at least 1, the unit the suffix of its name) and the check across them. Every other
#: row, and every unsupported row, states no measures.
PROPERTY_MEASURES: Final[
    Mapping[str, tuple[tuple[str, ...], Callable[[Mapping[str, int]], None]]]
] = {
    "capsule_clearance": (("eye_height_mm", "height_mm", "radius_mm"), _capsule_measures),
}
#: Frame metric classes. An invented grammar never measured anything.
FRAME_METRIC_CLASSES: Final = (
    "metric_measured",
    "metric_authored",
    "metric_unvalidated",
    "nonmetric_arrangement",
)
FRAME_UNITS: Final = ("mm",)
TIME_SCOPES: Final = ("atemporal",)

_DESCRIPTOR_KEYS: Final = frozenset(
    {
        "schema_version",
        "grammar_id",
        "grammar_version",
        "subject_kind",
        "admissible_uses",
        "cascade_levels",
        "parameters",
    }
)
_DESCRIPTOR_KEYS_2: Final = _DESCRIPTOR_KEYS | {"frame", "stages", "projections"}


@dataclass(frozen=True, slots=True)
class GrammarKey:
    grammar_id: str
    grammar_version: int

    def __post_init__(self) -> None:
        if type(self.grammar_id) is not str or KEY_PATTERN.fullmatch(self.grammar_id) is None:
            raise InvalidRecordError(f"grammar_id is a lowercase key, got {self.grammar_id!r}")
        require_integer("grammar_version", self.grammar_version, minimum=1)


@dataclass(frozen=True, slots=True)
class DeclaredSemantics:
    """What a grammar's output is. The plane is fixed, and it is written into every receipt."""

    subject_kind: str
    admissible_uses: tuple[str, ...]
    plane: str = PLANE

    def __post_init__(self) -> None:
        require_key("subject_kind", self.subject_kind)
        if self.plane != PLANE:
            raise InvalidRecordError(f"a grammar declares the {PLANE!r} plane and no other")
        if not isinstance(self.admissible_uses, tuple):
            raise InvalidRecordError("admissible_uses is a tuple")
        if len(set(self.admissible_uses)) != len(self.admissible_uses):
            raise InvalidRecordError("admissible_uses repeats a use")
        for use in self.admissible_uses:
            if use not in ADMISSIBLE_USES:
                raise InvalidRecordError(f"{use!r} is not one of {ADMISSIBLE_USES}")


@dataclass(frozen=True, slots=True)
class StageEmission:
    """What one stage produced, or its statement that it produced nothing."""

    RECORD_KIND: ClassVar[str] = "grammar.stage_emission"
    RECORD_VERSION: ClassVar[int] = 1

    stage_id: str
    stage_version: int
    status: str
    reason: str
    records: tuple[object, ...]

    def __post_init__(self) -> None:
        require_key("stage_id", self.stage_id)
        require_integer("stage_version", self.stage_version, minimum=1)
        if self.status not in STAGE_STATUSES:
            raise InvalidRecordError(f"status {self.status!r} is not one of {STAGE_STATUSES}")
        if not isinstance(self.records, tuple):
            raise InvalidRecordError("records is a tuple")
        if self.status == "not_implemented":
            if self.records:
                raise InvalidRecordError(f"{self.stage_id} is not implemented and emitted records")
            require_text("reason", self.reason)
        elif self.reason != "":
            raise InvalidRecordError(f"{self.stage_id} emitted and still gave a reason")


@dataclass(frozen=True, slots=True)
class StageContext:
    """What a stage may read: the seed, the subject, the parameters, and earlier emissions.

    ``subject_identity`` is the admitted identity of the subject the generation is for. It is
    the root of every identity the stage derives, through :meth:`identity`.
    """

    seed: str
    grammar_id: str
    stage_id: str
    parameters: Mapping[str, ParameterValue]
    prior: tuple[StageEmission, ...]
    subject_identity: str

    def cursor(self, name: str) -> DomainCursor:
        """Draws in ``<grammar_id>.<stage_id>.<name>``, so no two stages share a namespace."""
        return DomainCursor(self.seed, f"{self.grammar_id}.{self.stage_id}.{name}")

    def identity(self, subject_kind: str, owner_identity: str, ordinal: int) -> str:
        """The identity of one generated subject, by the one rule in ``subjects``."""
        return _derive_subject_identity(
            grammar_id=self.grammar_id,
            root_identity=self.subject_identity,
            subject_kind=subject_kind,
            owner_identity=owner_identity,
            ordinal=ordinal,
        )


class Stage(Protocol):
    @property
    def stage_id(self) -> str: ...

    @property
    def stage_version(self) -> int: ...

    def emit(self, context: StageContext) -> StageEmission: ...

    def validate(self, record: object) -> None: ...


@dataclass(frozen=True, slots=True)
class UnimplementedStage:
    """A stage whose record shape and validator exist and whose generator does not."""

    stage_id: str
    stage_version: int
    reason: str
    validators: tuple[tuple[type, Callable[[object], None]], ...] = field(default=())

    def emit(self, context: StageContext) -> StageEmission:
        return StageEmission(
            stage_id=self.stage_id,
            stage_version=self.stage_version,
            status="not_implemented",
            reason=self.reason,
            records=(),
        )

    def validate(self, record: object) -> None:
        for record_type, validator in self.validators:
            if type(record) is record_type:
                validator(record)
                return
        raise InvalidRecordError(f"{self.stage_id} declares no record type {type(record).__name__}")


@dataclass(frozen=True, slots=True)
class GrammarReceipt:
    """The durable record of one generation, and the only thing that needs keeping."""

    RECORD_KIND: ClassVar[str] = "grammar.receipt"
    RECORD_VERSION: ClassVar[int] = 1

    subject_identity: str
    grammar_id: str
    grammar_version: int
    parameters: ResolvedParameters
    seed: str
    output_digest: str
    declared_semantics: DeclaredSemantics

    def __post_init__(self) -> None:
        require_identity("subject_identity", self.subject_identity)
        GrammarKey(self.grammar_id, self.grammar_version)
        require_seed(self.seed)
        require_hex64("output_digest", self.output_digest)
        canonical_json(record_payload(self))


@dataclass(frozen=True, slots=True)
class Generation:
    receipt: GrammarReceipt
    emissions: tuple[StageEmission, ...]

    def payload(self) -> dict[str, object]:
        return {
            "receipt": record_payload(self.receipt),
            "emissions": [record_payload(emission) for emission in self.emissions],
        }


def _object(where: str, value: object, keys: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise InvalidRecordError(f"{where} is an object with exactly {sorted(keys)}")
    return value


def _list(where: str, value: object) -> list[object]:
    if not isinstance(value, list):
        raise InvalidRecordError(f"{where} is a list")
    return value


@dataclass(frozen=True, slots=True)
class GrammarFrame:
    """The coordinate frame a grammar's records are written in."""

    name: str
    units: str
    axes: str
    metric_class: str

    def __post_init__(self) -> None:
        require_key("frame name", self.name)
        require_key("frame axes", self.axes)
        if self.units not in FRAME_UNITS:
            raise InvalidRecordError(f"frame units are one of {FRAME_UNITS}")
        if self.metric_class not in FRAME_METRIC_CLASSES:
            raise InvalidRecordError(f"frame metric class is one of {FRAME_METRIC_CLASSES}")
        if self.metric_class == "metric_measured":
            raise InvalidRecordError(f"a grammar on the {PLANE!r} plane measured nothing")

    @classmethod
    def read(cls, value: object) -> GrammarFrame:
        document = _object("frame", value, frozenset({"name", "units", "axes", "metric_class"}))
        return cls(**document)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class StageDeclaration:
    """A stage as the descriptor states it: id, version, and the record kinds it validates."""

    stage_id: str
    stage_version: int
    records: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        require_key("stage_id", self.stage_id)
        require_integer("stage_version", self.stage_version, minimum=1)
        if len(set(self.records)) != len(self.records):
            raise InvalidRecordError(f"{self.stage_id} lists a record kind twice")
        for kind, version in self.records:
            require_text(f"{self.stage_id} record kind", kind)
            require_integer(f"{self.stage_id} {kind} version", version, minimum=1)

    @classmethod
    def read(cls, index: int, value: object) -> StageDeclaration:
        where = f"stages[{index}]"
        document = _object(where, value, frozenset({"stage_id", "stage_version", "records"}))
        records = []
        for position, entry in enumerate(_list(f"{where}.records", document["records"])):
            item = _object(f"{where}.records[{position}]", entry, frozenset({"kind", "version"}))
            records.append((item["kind"], item["version"]))
        return cls(document["stage_id"], document["stage_version"], tuple(records))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class PropertyRow:
    """One property a projection preserves, or one it does not, with a plain statement.

    ``measures`` are the integer quantities a consumer builds to, sorted by name, for the
    properties :data:`PROPERTY_MEASURES` names; which rows must carry them is the contract's check.
    """

    property: str
    statement: str
    measures: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        require_key("property", self.property)
        require_text(f"{self.property} statement", self.statement)
        if not isinstance(self.measures, tuple):
            raise InvalidRecordError(f"{self.property} measures are a tuple of pairs")
        names = []
        for pair in self.measures:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise InvalidRecordError(f"{self.property} measures are (name, value) pairs")
            require_key(f"{self.property} measure", pair[0])
            require_integer(f"{self.property} {pair[0]}", pair[1], minimum=1)
            names.append(pair[0])
        if names != sorted(set(names)):
            raise InvalidRecordError(f"{self.property} measures are sorted by name, each once")


@dataclass(frozen=True, slots=True)
class UseRow:
    """The verdict a projection's contract gives one use, and its reason."""

    use: str
    verdict: str
    reason: str

    def __post_init__(self) -> None:
        if self.use not in PROJECTION_USES:
            raise InvalidRecordError(f"use {self.use!r} is not one of {PROJECTION_USES}")
        if self.verdict not in USE_VERDICTS:
            raise InvalidRecordError(f"verdict {self.verdict!r} is not one of {USE_VERDICTS}")
        require_text(f"{self.use} reason", self.reason)


@dataclass(frozen=True, slots=True)
class ProjectionContract:
    """The static half of a representation contract (``docs/world-memory-model.md`` section 5).

    The frame and units are the grammar's. What varies per baked artifact (its subjects, input
    digests, producer, seed, quality, content digest and supersession) is the artifact's to state.
    """

    projection: str
    representation_version: int
    time_scope: str
    resolution_mm: int
    preserved: tuple[PropertyRow, ...]
    unsupported: tuple[PropertyRow, ...]
    uses: tuple[UseRow, ...]
    dependencies: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.projection not in ADMISSIBLE_USES:
            raise InvalidRecordError(f"{self.projection!r} is not one of {ADMISSIBLE_USES}")
        require_integer("representation_version", self.representation_version, minimum=1)
        if self.time_scope not in TIME_SCOPES:
            raise InvalidRecordError(f"time scope is one of {TIME_SCOPES}")
        require_integer("resolution_mm", self.resolution_mm, minimum=1)
        if not self.preserved or not self.unsupported:
            raise InvalidRecordError(f"{self.projection} states what it preserves and what not")
        properties = [row.property for row in (*self.preserved, *self.unsupported)]
        if len(set(properties)) != len(properties):
            raise InvalidRecordError(
                f"{self.projection}: a property is preserved and unsupported, or listed twice"
            )
        if tuple(row.use for row in self.uses) != PROJECTION_USES:
            raise InvalidRecordError(
                f"{self.projection} gives one verdict for each of {PROJECTION_USES}, in order"
            )
        for row in self.unsupported:
            if row.measures:
                raise InvalidRecordError(
                    f"{self.projection}: {row.property} is not preserved and states no measures"
                )
        for row in self.preserved:
            declared = PROPERTY_MEASURES.get(row.property)
            names = tuple(name for name, _ in row.measures)
            if declared is None:
                if row.measures:
                    raise InvalidRecordError(
                        f"{self.projection}: {row.property} is not a measured property"
                    )
                continue
            if names != declared[0]:
                raise InvalidRecordError(
                    f"{self.projection}: {row.property} states exactly the measures {declared[0]}"
                )
            declared[1](dict(row.measures))
        verdicts = {row.use: row.verdict for row in self.uses}
        own = PROJECTION_OWN_USE[self.projection]
        if verdicts[own] != "admitted":
            raise InvalidRecordError(f"{self.projection} admits its own use, {own}")
        for use, why in REFUSED_USES.items():
            if verdicts[use] != "refused":
                raise InvalidRecordError(f"{self.projection} may not admit {use}: {why}")
        for dependency in self.dependencies:
            require_key("dependency", dependency)
        if self.dependencies:
            raise InvalidRecordError(
                f"{self.projection}: an invented projection depends on no source or consent"
            )

    @classmethod
    def read(cls, index: int, value: object) -> ProjectionContract:
        where = f"projections[{index}]"
        document = _object(
            where,
            value,
            frozenset(
                {
                    "projection",
                    "representation_version",
                    "time_scope",
                    "resolution_mm",
                    "preserved",
                    "unsupported",
                    "uses",
                    "dependencies",
                }
            ),
        )
        rows = {}
        for label in ("preserved", "unsupported"):
            rows[label] = tuple(
                _property_row(f"{where}.{label}[{position}]", entry)
                for position, entry in enumerate(_list(f"{where}.{label}", document[label]))
            )
        uses = tuple(
            UseRow(
                **_object(
                    f"{where}.uses[{position}]", entry, frozenset({"use", "verdict", "reason"})
                )  # type: ignore[arg-type]
            )
            for position, entry in enumerate(_list(f"{where}.uses", document["uses"]))
        )
        return cls(
            projection=document["projection"],  # type: ignore[arg-type]
            representation_version=document["representation_version"],  # type: ignore[arg-type]
            time_scope=document["time_scope"],  # type: ignore[arg-type]
            resolution_mm=document["resolution_mm"],  # type: ignore[arg-type]
            preserved=rows["preserved"],
            unsupported=rows["unsupported"],
            uses=uses,
            dependencies=tuple(_list(f"{where}.dependencies", document["dependencies"])),  # type: ignore[arg-type]
        )


def _property_row(where: str, value: object) -> PropertyRow:
    """A row as a descriptor writes it; ``measures``, when present, is a non-empty object."""
    keys = frozenset({"property", "statement"})
    if isinstance(value, dict) and "measures" in value:
        keys = keys | {"measures"}
    document = _object(where, value, keys)
    measures: tuple[tuple[str, int], ...] = ()
    if "measures" in document:
        raw = document["measures"]
        if not isinstance(raw, dict) or not raw:
            raise InvalidRecordError(f"{where}.measures is a non-empty object; omit it when empty")
        measures = tuple(sorted(raw.items()))  # type: ignore[arg-type]
    return PropertyRow(document["property"], document["statement"], measures)  # type: ignore[arg-type]


def _stage_record_types(stage: Stage) -> tuple[tuple[str, int], ...]:
    validators = getattr(stage, "validators", None)
    if not isinstance(validators, tuple):
        raise InvalidRecordError(
            f"{stage.stage_id}: a schema 2 grammar's stage exposes its validators"
        )
    return tuple(
        (record_type.RECORD_KIND, record_type.RECORD_VERSION) for record_type, _ in validators
    )


@dataclass(frozen=True, slots=True)
class ParameterSurface:
    """What a descriptor says about parameters, read without any stage code.

    A retired grammar version has no stages left in code, and a migration still needs its
    parameter schema and cascade. This is that part of the descriptor, checked the same way.
    """

    key: GrammarKey
    descriptor_schema: int
    parameters: ParameterSchema
    cascade: ParameterCascade

    @classmethod
    def read(cls, path: Path) -> ParameterSurface:
        stem, version = split_versioned_name(path)
        document = read_json(path)
        if not isinstance(document, dict):
            raise InvalidRecordError(f"{path.name} is a JSON object")
        schema = document.get("schema_version")
        if type(schema) is not int or schema not in (1, 2):
            raise InvalidRecordError(f"{path.name}: schema_version is 1 or 2")
        expected = _DESCRIPTOR_KEYS if schema == 1 else _DESCRIPTOR_KEYS_2
        if set(document) != expected:
            raise InvalidRecordError(f"{path.name} has keys {sorted(document)}")
        key = GrammarKey(document["grammar_id"], document["grammar_version"])
        if (key.grammar_id, key.grammar_version) != (stem, version):
            raise InvalidRecordError(
                f"{path.name} declares {key.grammar_id} v{key.grammar_version}"
            )
        levels = document["cascade_levels"]
        if not isinstance(levels, list):
            raise InvalidRecordError(f"{path.name}: cascade_levels is a list")
        cascade = ParameterCascade(tuple(levels))
        parameters = ParameterSchema.from_document(document["parameters"], schema_version=schema)
        for spec in parameters.parameters:
            if spec.level and spec.level not in cascade.levels:
                raise InvalidRecordError(f"{path.name}: {spec.name} has no level {spec.level!r}")
        return cls(key, schema, parameters, cascade)


@dataclass(frozen=True, slots=True)
class Grammar:
    key: GrammarKey
    semantics: DeclaredSemantics
    parameters: ParameterSchema
    cascade: ParameterCascade
    stages: tuple[Stage, ...]
    descriptor_schema: int = 1
    frame: GrammarFrame | None = None
    declared_stages: tuple[StageDeclaration, ...] = ()
    projections: tuple[ProjectionContract, ...] = ()

    def __post_init__(self) -> None:
        if not self.stages:
            raise InvalidRecordError(f"{self.key.grammar_id} declares no stages")
        ids = [stage.stage_id for stage in self.stages]
        if len(set(ids)) != len(ids):
            raise InvalidRecordError(f"{self.key.grammar_id} repeats a stage id in {ids}")
        for stage_id in ids:
            require_key("stage_id", stage_id)
        if self.descriptor_schema == 1:
            if self.frame is not None or self.declared_stages or self.projections:
                raise InvalidRecordError(
                    "a schema 1 descriptor declares no frame, stages or contracts"
                )
            if any(spec.declared for spec in self.parameters.parameters):
                raise InvalidRecordError("a schema 1 descriptor declares no parameter units")
        elif self.descriptor_schema == 2:
            self._check_schema_2(ids)
        else:
            raise InvalidRecordError(f"descriptor schema {self.descriptor_schema!r} is unknown")

    def _check_schema_2(self, ids: list[str]) -> None:
        name = self.key.grammar_id
        if self.frame is None:
            raise InvalidRecordError(f"{name} states its frame")
        declared = [(stage.stage_id, stage.stage_version) for stage in self.declared_stages]
        actual = [(stage.stage_id, stage.stage_version) for stage in self.stages]
        if declared != actual:
            raise InvalidRecordError(f"{name} declares stages {declared}, code has {actual}")
        for declaration, stage in zip(self.declared_stages, self.stages, strict=True):
            if sorted(declaration.records) != sorted(_stage_record_types(stage)):
                raise InvalidRecordError(
                    f"{name} {stage.stage_id} declares records {sorted(declaration.records)}, "
                    f"its validators take {sorted(_stage_record_types(stage))}"
                )
        kinds = [kind for declaration in self.declared_stages for kind, _ in declaration.records]
        if len(set(kinds)) != len(kinds):
            raise InvalidRecordError(f"{name}: a record kind belongs to two stages")
        for spec in self.parameters.parameters:
            if not spec.declared:
                raise InvalidRecordError(f"{name}: {spec.name} is not declared")
            if spec.level not in self.cascade.levels:
                raise InvalidRecordError(f"{name}: {spec.name} has no level {spec.level!r}")
            if spec.stage not in ids:
                raise InvalidRecordError(f"{name}: {spec.name} is read by no stage {spec.stage!r}")
        contracted = tuple(contract.projection for contract in self.projections)
        if contracted != self.semantics.admissible_uses:
            raise InvalidRecordError(
                f"{name} admits {self.semantics.admissible_uses} and has contracts for {contracted}"
            )

    def projection(self, projection: str) -> ProjectionContract:
        for contract in self.projections:
            if contract.projection == projection:
                return contract
        raise InvalidRecordError(f"{self.key.grammar_id} admits no projection {projection!r}")

    @classmethod
    def from_descriptor(cls, path: Path, stages: Sequence[Stage]) -> Grammar:
        """Identity, semantics, parameters and cascade from ``<grammar_id>.v<N>.json``."""
        stem, version = split_versioned_name(path)
        document = read_json(path)
        if not isinstance(document, dict):
            raise InvalidRecordError(f"{path.name} is a JSON object")
        schema = document.get("schema_version")
        if type(schema) is not int or schema not in (1, 2):
            raise InvalidRecordError(f"{path.name}: schema_version is 1 or 2")
        expected = _DESCRIPTOR_KEYS if schema == 1 else _DESCRIPTOR_KEYS_2
        unknown = set(document) - expected
        missing = expected - set(document)
        if unknown or missing:
            raise InvalidRecordError(
                f"{path.name}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}"
            )
        key = GrammarKey(document["grammar_id"], document["grammar_version"])
        if (key.grammar_id, key.grammar_version) != (stem, version):
            raise InvalidRecordError(
                f"{path.name} declares {key.grammar_id} v{key.grammar_version}"
            )
        uses = document["admissible_uses"]
        levels = document["cascade_levels"]
        if not isinstance(uses, list) or not isinstance(levels, list):
            raise InvalidRecordError(f"{path.name}: admissible_uses and cascade_levels are lists")
        extra: dict[str, object] = {}
        if schema == 2:
            extra = {
                "frame": GrammarFrame.read(document["frame"]),
                "declared_stages": tuple(
                    StageDeclaration.read(index, entry)
                    for index, entry in enumerate(_list("stages", document["stages"]))
                ),
                "projections": tuple(
                    ProjectionContract.read(index, entry)
                    for index, entry in enumerate(_list("projections", document["projections"]))
                ),
            }
        return cls(
            key=key,
            semantics=DeclaredSemantics(
                subject_kind=document["subject_kind"], admissible_uses=tuple(uses)
            ),
            parameters=ParameterSchema.from_document(document["parameters"], schema_version=schema),
            cascade=ParameterCascade(tuple(levels)),
            stages=tuple(stages),
            descriptor_schema=schema,
            **extra,  # type: ignore[arg-type]
        )


def generate(
    grammar: Grammar,
    *,
    seed: str,
    subject_identity: str,
    bindings: Sequence[CascadeBinding] = (),
) -> Generation:
    """Run every stage of ``grammar`` for one admitted subject. Pure: same inputs, same bytes."""
    require_seed(seed)
    require_identity("subject_identity", subject_identity)
    resolved = grammar.cascade.resolve(
        grammar.parameters, bindings, seed=seed, domain_prefix=grammar.key.grammar_id
    )
    parameters = resolved.as_mapping()
    emissions: list[StageEmission] = []
    for stage in grammar.stages:
        emission = stage.emit(
            StageContext(
                seed=seed,
                grammar_id=grammar.key.grammar_id,
                stage_id=stage.stage_id,
                parameters=parameters,
                prior=tuple(emissions),
                subject_identity=subject_identity,
            )
        )
        if not isinstance(emission, StageEmission) or (
            emission.stage_id,
            emission.stage_version,
        ) != (stage.stage_id, stage.stage_version):
            raise InvalidRecordError(f"{stage.stage_id} returned an emission that is not its own")
        for record in emission.records:
            stage.validate(record)
        canonical_json(record_payload(emission))
        emissions.append(emission)
    output_digest = sha256_of_canonical([record_payload(emission) for emission in emissions]).hex()
    receipt = GrammarReceipt(
        subject_identity=subject_identity,
        grammar_id=grammar.key.grammar_id,
        grammar_version=grammar.key.grammar_version,
        parameters=resolved,
        seed=seed,
        output_digest=output_digest,
        declared_semantics=grammar.semantics,
    )
    return Generation(receipt=receipt, emissions=tuple(emissions))
