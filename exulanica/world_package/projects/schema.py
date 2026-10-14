"""Closed checkpoint records; native placements retain the world's existing validation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from exulanica.canonical import canonical_json
from exulanica.world.objects import ObjectOrigin, Transform, validate_object_id
from exulanica.world.placed_things import (
    PlacedThing,
    ThingKindReference,
    WorkspaceKindReference,
    validate_placed_thing,
)
from exulanica.world_package.package import scan_payload

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9:._/-]+$")]
Natural = Annotated[int, Field(ge=0)]
Label = Annotated[str, Field(min_length=1, max_length=500)]

# Values that would publish where a file lives on someone's machine or a credential. Field names
# are checked by the WMP scan; these are checked by value, in every string of a project file.
_PRIVATE_VALUE = re.compile(
    r"(?i)(?:^|[\s\"'=(,])(?:/(?:users|home|private|var|tmp|etc|root|volumes|opt|mnt)/|~/"
    r"|[a-z]:\\|file:)"
    r"|\.exulanica/"
    r"|\bgh[pousr]_[a-z0-9]{20,}|\bgithub_pat_[a-z0-9_]{20,}"
    r"|\bsk-[a-z0-9_-]{16,}|\bxox[abprs]-[a-z0-9-]{10,}|\bakia[0-9a-z]{16}\b"
    r"|\bbearer\s+[a-z0-9._~+/-]{16,}|-----begin [a-z ]*private key-----"
)


def scan_values(value: Any, where: str = "") -> None:
    """Refuse a local path or credential-shaped value, naming the field and never the value."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            scan_values(child, f"{where}/{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, child in enumerate(value):
            scan_values(child, f"{where}/{index}")
    elif isinstance(value, str) and _PRIVATE_VALUE.search(value):
        raise ValueError(f"{where or '/'} looks like a local path or a credential")


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Source(Closed):
    world_id: Name
    version_id: Name
    snapshot_id: Name
    state_sha256: Digest
    snapshot_sha256: Digest


class Dependency(Closed):
    kind: Literal["source-snapshot", "thing-kind", "decision-contract", "model-manifest"]
    sha256: Digest
    licence: Name
    # Identifiers, never authenticated fetch URLs, local paths or credentials.
    source_id: Name


class Pose(Closed):
    coordinate_space: Literal["region_local"]
    coordinate_unit: Literal["millimetre"]
    x_mm: int
    y_mm: int
    z_mm: int
    yaw_microradians: int
    scale_milli: Literal[1000]

    def native(self) -> Transform:
        return Transform(**self.model_dump(exclude={"coordinate_space", "coordinate_unit"}))


class Origin(Closed):
    kind: Literal["authored"]
    role: Literal["fictional", "personal"]


class ShippedKind(Closed):
    kind: Name
    version: Annotated[int, Field(ge=1)]
    sha256: Digest


class WorkspaceKind(Closed):
    source: Literal["workspace"]
    sha256: Digest


class Thing(Closed):
    thing_id: Name
    kind: ShippedKind | WorkspaceKind
    region_id: Name
    transform: Pose
    origin: Origin
    removed: bool

    def native(self) -> PlacedThing:
        reference = (
            WorkspaceKindReference(self.kind.sha256)
            if isinstance(self.kind, WorkspaceKind)
            else ThingKindReference(self.kind.kind, self.kind.version, self.kind.sha256)
        )
        return PlacedThing(
            self.thing_id,
            reference,
            self.region_id,
            self.transform.native(),
            ObjectOrigin(self.origin.kind, self.origin.role),
            self.removed,
        )


class ModelBinding(Closed):
    thing_id: Name
    role: Name
    contract_sha256: Digest
    model_manifest_sha256: Digest
    provider: Name
    model_id: Name
    revision: Name


class Option(Closed):
    option_id: Name
    action: Name
    target_id: Name | None


Code = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[a-z0-9_.:-]+$")]
Usd = Annotated[str, Field(pattern=r"^[0-9]{1,6}(\.[0-9]{1,12})?$")]


class Receipt(Closed):
    """What the source receipt and its minute recorded, as codes and numbers: no words.

    `status` is the receipt's (did the model give a usable answer the engine accepted);
    `disposition` is what a minute did with an accepted answer, or null when none has.
    """

    status: Literal["accepted", "rejected", "unavailable", "stale"]
    reason: Code
    disposition: Literal["applied", "rejected", "superseded", "stale"] | None
    disposition_reason: Code | None
    consumed_tick: Natural | None
    served_model_id: Name | None
    cost_usd: Usd | None
    cost_known: bool


class Coverage(Closed):
    """Which of the session's decisions the file holds: those a minute took up, or all."""

    decisions: Literal["consumed", "all"]


class Readable(Closed):
    """What a source decision record itself stores, made readable. Opt-in at capture.

    The situation is the text the model was shown, rebuilt from the record's own context;
    labels, choice and line are as recorded. Nothing comes from outside the record.
    """

    situation: Annotated[str, Field(max_length=20_000)]
    options: Annotated[list[Label], Field(min_length=1, max_length=256)]
    choice: Label | None
    line: Annotated[str, Field(max_length=2_000)] | None
    status: Literal["accepted", "rejected", "unavailable", "stale"]
    reason: Name
    consumed_tick: Natural
    disposition: Name
    served_model_id: Name | None
    cost_usd: Usd | None
    cost_known: bool

    @model_validator(mode="after")
    def chosen(self) -> Self:
        if self.choice is not None and self.choice not in self.options:
            raise ValueError("a readable choice must be one of its offered labels")
        return self


class Decision(Closed):
    """Selected evidence, not a prompt, hidden reasoning, or executable engine receipt."""

    record_id: Name
    thing_id: Name
    tick: Natural
    binding_sha256: Digest
    source_record_sha256: Digest
    observation_sha256: Digest
    options: Annotated[list[Option], Field(min_length=1, max_length=256)]
    chosen_option_id: Name | None
    outcome: Literal["applied", "refused", "not-applied"]
    reason_code: Name
    elapsed_ms: Natural | None
    input_tokens: Natural | None
    output_tokens: Natural | None
    # Optional additions: a record without them keeps its digest (see checkpoint.document).
    readable: Readable | None = None
    receipt: Receipt | None = None

    @model_validator(mode="after")
    def choice(self) -> Self:
        ids = [option.option_id for option in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("decision options must have unique identities")
        if self.chosen_option_id is not None and self.chosen_option_id not in ids:
            raise ValueError("decision choice must be among its recorded options")
        if self.outcome == "applied" and self.chosen_option_id is None:
            raise ValueError("applied evidence requires a recorded choice")
        if self.readable is not None and len(self.readable.options) != len(self.options):
            raise ValueError("readable labels must match the recorded options one for one")
        return self


class Lineage(Closed):
    project_id: Name
    checkpoint_sha256: Digest


class Checkpoint(Closed):
    profile: Literal["exulanica.world-project/v1"]
    project_id: Name
    source: Source
    forked_from: Lineage | None
    # This is an explicit selection, not the full authored delta or a runtime backup.
    region_ids: Annotated[list[Name], Field(min_length=1, max_length=256)]
    things: Annotated[list[Thing], Field(max_length=256)]
    dependencies: Annotated[list[Dependency], Field(min_length=1, max_length=1024)]
    models: Annotated[list[ModelBinding], Field(max_length=256)]
    decisions: Annotated[list[Decision], Field(max_length=1024)]

    @model_validator(mode="after")
    def references(self) -> Self:
        from exulanica.canonical import sha256_of_canonical

        validate_object_id(self.project_id)
        unique(self.region_ids, "region")
        unique([t.thing_id for t in self.things], "thing")
        unique([m.thing_id for m in self.models], "model assignment")
        unique([d.record_id for d in self.decisions], "decision")
        unique([d.sha256 for d in self.dependencies], "dependency")
        available = {(d.kind, d.sha256) for d in self.dependencies}

        def require(kind: str, digest: str) -> None:
            if (kind, digest) not in available:
                raise ValueError(f"missing declared {kind} dependency")

        require("source-snapshot", self.source.snapshot_sha256)
        things = {t.thing_id: t for t in self.things}
        for thing in self.things:
            validate_placed_thing(thing.native(), region_ids=frozenset(self.region_ids))
            require("thing-kind", thing.kind.sha256)
        bindings = {}
        for binding in self.models:
            thing = things.get(binding.thing_id)
            if thing is None or thing.removed:
                raise ValueError("a model assignment names an active selected thing")
            require("decision-contract", binding.contract_sha256)
            require("model-manifest", binding.model_manifest_sha256)
            bindings[binding.thing_id] = sha256_of_canonical(binding.model_dump()).hex()
        for decision in self.decisions:
            if bindings.get(decision.thing_id) != decision.binding_sha256:
                raise ValueError("decision evidence must match its selected model binding")
        if self.forked_from and self.forked_from.project_id == self.project_id:
            raise ValueError("a fork must have a distinct project identity")
        document = self.model_dump()
        canonical_json(document)
        scan_payload("world-project.json", document)
        scan_values(document)
        return self


def binding_sha256(binding: ModelBinding) -> str:
    from exulanica.canonical import sha256_of_canonical

    return sha256_of_canonical(binding.model_dump()).hex()


class Evidence(Closed):
    """One session's decision records, kept beside the checkpoint rather than inside it.

    Evidence is what happened while models played; it is not part of the world definition. Each
    record binds to a model assignment carried in this same file, so it stays verifiable after
    the checkpoint's assignment changes. A file has its own digest.
    """

    profile: Literal["exulanica.world-project-evidence/v1"]
    project_id: Name
    session_id: Name
    source: Source
    models: Annotated[list[ModelBinding], Field(min_length=1, max_length=256)]
    decisions: Annotated[list[Decision], Field(min_length=1, max_length=1024)]
    # Optional additions; an older file without them keeps its digest.
    coverage: Coverage | None = None
    captured_at: (
        Annotated[
            str,
            Field(pattern=r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z$"),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def references(self) -> Self:
        validate_object_id(self.project_id)
        validate_object_id(self.session_id)
        unique([d.record_id for d in self.decisions], "decision")
        bindings = [binding_sha256(model) for model in self.models]
        unique(bindings, "model assignment")
        for decision in self.decisions:
            if decision.binding_sha256 not in bindings:
                raise ValueError("evidence must match a model assignment in the same file")
        document = self.model_dump()
        canonical_json(document)
        scan_payload("evidence.json", document)
        scan_values(document)
        return self


def unique(values: list[Any], name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {name} identity")
