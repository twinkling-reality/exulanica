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

__all__ = [
    "ADMISSIBLE_USES",
    "PLANE",
    "STAGE_STATUSES",
    "DeclaredSemantics",
    "Generation",
    "Grammar",
    "GrammarKey",
    "GrammarReceipt",
    "Stage",
    "StageContext",
    "StageEmission",
    "UnimplementedStage",
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
    """What a stage may read: the seed, the resolved parameters, and earlier emissions."""

    seed: str
    grammar_id: str
    stage_id: str
    parameters: Mapping[str, ParameterValue]
    prior: tuple[StageEmission, ...]

    def cursor(self, name: str) -> DomainCursor:
        """Draws in ``<grammar_id>.<stage_id>.<name>``, so no two stages share a namespace."""
        return DomainCursor(self.seed, f"{self.grammar_id}.{self.stage_id}.{name}")


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


@dataclass(frozen=True, slots=True)
class Grammar:
    key: GrammarKey
    semantics: DeclaredSemantics
    parameters: ParameterSchema
    cascade: ParameterCascade
    stages: tuple[Stage, ...]

    def __post_init__(self) -> None:
        if not self.stages:
            raise InvalidRecordError(f"{self.key.grammar_id} declares no stages")
        ids = [stage.stage_id for stage in self.stages]
        if len(set(ids)) != len(ids):
            raise InvalidRecordError(f"{self.key.grammar_id} repeats a stage id in {ids}")
        for stage_id in ids:
            require_key("stage_id", stage_id)

    @classmethod
    def from_descriptor(cls, path: Path, stages: Sequence[Stage]) -> Grammar:
        """Identity, semantics, parameters and cascade from ``<grammar_id>.v<N>.json``."""
        stem, version = split_versioned_name(path)
        document = read_json(path)
        if not isinstance(document, dict):
            raise InvalidRecordError(f"{path.name} is a JSON object")
        unknown = set(document) - _DESCRIPTOR_KEYS
        missing = _DESCRIPTOR_KEYS - set(document)
        if unknown or missing:
            raise InvalidRecordError(
                f"{path.name}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}"
            )
        if document["schema_version"] != 1:
            raise InvalidRecordError(f"{path.name}: schema_version is 1")
        key = GrammarKey(document["grammar_id"], document["grammar_version"])
        if (key.grammar_id, key.grammar_version) != (stem, version):
            raise InvalidRecordError(
                f"{path.name} declares {key.grammar_id} v{key.grammar_version}"
            )
        uses = document["admissible_uses"]
        levels = document["cascade_levels"]
        if not isinstance(uses, list) or not isinstance(levels, list):
            raise InvalidRecordError(f"{path.name}: admissible_uses and cascade_levels are lists")
        return cls(
            key=key,
            semantics=DeclaredSemantics(
                subject_kind=document["subject_kind"], admissible_uses=tuple(uses)
            ),
            parameters=ParameterSchema.from_document(document["parameters"]),
            cascade=ParameterCascade(tuple(levels)),
            stages=tuple(stages),
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
