"""Closed checkpoint records; native placements retain the world's existing validation."""

from __future__ import annotations

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

    @model_validator(mode="after")
    def choice(self) -> Self:
        ids = [option.option_id for option in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("decision options must have unique identities")
        if self.chosen_option_id is not None and self.chosen_option_id not in ids:
            raise ValueError("decision choice must be among its recorded options")
        if self.outcome == "applied" and self.chosen_option_id is None:
            raise ValueError("applied evidence requires a recorded choice")
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
        return self


def unique(values: list[Any], name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {name} identity")
