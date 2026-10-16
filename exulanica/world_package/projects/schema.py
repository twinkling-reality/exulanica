"""Closed checkpoint records; native placements retain the world's existing validation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from exulanica.canonical import canonical_json
from exulanica.world.objects import ObjectOrigin, Transform, validate_object_id
from exulanica.world.placed_things import (
    PlacedThing,
    ThingKindReference,
    WorkspaceKindReference,
    validate_placed_thing,
)
from exulanica.world.society_thing_inputs import (
    CHARACTER_ABOUT_MAXIMUM,
    CHARACTER_NAME_MAXIMUM,
    check_character,
)
from exulanica.world_package.package import scan_payload

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9:._/-]+$")]
Natural = Annotated[int, Field(ge=0)]
#: The longest label a checkpoint keeps (a made part's, a made creature's kind's).
LABEL_MAXIMUM: Final = 500
Label = Annotated[str, Field(min_length=1, max_length=LABEL_MAXIMUM)]
#: The longest world title a checkpoint keeps; capture leaves a longer one out.
TITLE_MAXIMUM: Final = 200
#: The longest resident's name a checkpoint keeps; capture leaves a longer one out.
RESIDENT_NAME_MAXIMUM: Final = 200

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
    #: A creature its workspace made, called by its kind's label (its maker's words), kept only
    #: where the project keeps readable text; never on a shipped kind, whose words are the
    #: library's.
    label: Label | None = None

    @model_validator(mode="after")
    def labelled(self) -> Self:
        if self.label is not None and not isinstance(self.kind, WorkspaceKind):
            raise ValueError("only a thing of a made kind carries its kind's label")
        return self

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


class CharacterWords(Closed):
    """A character's words as its world's owner wrote them, each held to the character module's
    own line rule and bounds. Both absent: the newest record clears the character."""

    name: str | None
    about: str | None

    @model_validator(mode="after")
    def lines(self) -> Self:
        stated = {key: value for key, value in self.model_dump().items() if value is not None}
        if stated:
            check_character(
                stated,
                name_maximum=CHARACTER_NAME_MAXIMUM,
                about_maximum=CHARACTER_ABOUT_MAXIMUM,
            )
        return self


class Character(Closed):
    """Who the world's owner wrote a placed being to be: the newest record's revision always, its
    words only where the project keeps readable text. Written words never reach a repository that
    is not private (:mod:`exulanica.world_package.projects.rights`), and a merged pull request
    never applies them."""

    thing_id: Name
    revision: Annotated[int, Field(ge=1)]
    words: CharacterWords | None = None


class Resident(Closed):
    """One of a town's people who is no placed thing, kept where a model decides for them or
    their decisions are kept. Its identity is its subject in the society, the one its model
    assignment and decision records name as their `thing_id`; its role is the town's key for it
    (null where the society states none a checkpoint can keep). Its name only where the project
    keeps readable text: a name is written words, which never reach a repository that is not
    private (:mod:`exulanica.world_package.projects.rights`)."""

    resident_id: Name
    role: Name | None
    name: Annotated[str, Field(min_length=1, max_length=RESIDENT_NAME_MAXIMUM)] | None = None


class Part(Closed):
    """A part a site world was made with, as the version has it: standing at its centre (east,
    north, millimetres) turned a whole number of quarter turns from how it was made, a building
    with its storeys, or removed.
    Its label only where the project keeps readable text: a world made from a person's words was
    worded from them. A part removed before the project kept it is known by its identity alone."""

    part_id: Name
    kind: Literal["building", "fixture", "area"] | None
    centre_mm: Annotated[list[int], Field(min_length=2, max_length=2)] | None
    quarter_turns: Annotated[int, Field(ge=0, le=3)]
    removed: bool
    label: Label | None = None
    #: How many storeys a building stands, where the parts read states it.
    storeys: Annotated[int, Field(ge=1, le=64)] | None = None

    @model_validator(mode="after")
    def standing(self) -> Self:
        if self.removed != (self.centre_mm is None):
            raise ValueError("a standing part has its centre, and only a standing one")
        if self.storeys is not None and self.kind != "building":
            raise ValueError("only a standing building has storeys")
        if not self.removed and self.kind is None:
            raise ValueError("a standing part says what kind of part it is")
        return self


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


Instant = Annotated[
    str, Field(pattern=r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z$")
]
PERSON_STOPS = frozenset({"stopped_by_person", "paused_by_person"})


class SessionLimits(Closed):
    wall_seconds: Annotated[int, Field(ge=1)]
    minutes: Annotated[int, Field(ge=1)]
    decisions: Annotated[int, Field(ge=1)]
    usd: Usd
    calls: Annotated[int, Field(ge=1)]


class SessionOpened(Closed):
    tick: Natural
    at: Instant
    state_sha256: Digest
    limits: SessionLimits


class SessionClosed(Closed):
    tick: Natural
    at: Instant
    state_sha256: Digest
    #: The society's stop code; the words for it belong to the society's own table.
    reason: Code
    by: Literal["system", "person"]

    @model_validator(mode="after")
    def who(self) -> Self:
        if (self.by == "person") != (self.reason in PERSON_STOPS):
            raise ValueError("a person's stop is said to be a person's, and only that")
        return self


class SessionUsed(Closed):
    wall_seconds: Natural
    minutes: Natural
    decisions: Natural
    usd: Usd
    calls: Natural
    unresolved_count: Natural
    unresolved_usd: Usd


class SessionBound(Closed):
    """One provider's bound under the session, as the spending authority read it."""

    provider: Name
    state: Literal["open", "closed"]
    ceiling_usd: Usd
    committed_usd: Usd
    committed_calls: Natural
    known_usage_usd: Usd
    unresolved_count: Natural
    unresolved_usd: Usd
    reconciled_usd: Usd


class SessionSpending(Closed):
    """Spending as found: the authority's figures when captured, never a bill."""

    used: SessionUsed
    bounds: Annotated[list[SessionBound], Field(max_length=64)]


class LivingSession(Closed):
    """One living session of the society: its two receipts and what it used, no actor ids."""

    session_id: Annotated[
        str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    ]
    state: Literal["open", "closed"]
    opened: SessionOpened
    closed: SessionClosed | None
    spending: SessionSpending

    @model_validator(mode="after")
    def receipts(self) -> Self:
        if (self.state == "closed") != (self.closed is not None):
            raise ValueError("a closed session has its closing receipt, and only a closed one")
        if self.closed is not None and self.closed.tick < self.opened.tick:
            raise ValueError("a session closes at or after the minute it opened")
        unique([bound.provider for bound in self.spending.bounds], "session bound")
        return self


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
    #: The regions of its things; none only for a made world kept for its parts alone.
    region_ids: Annotated[list[Name], Field(max_length=256)]
    things: Annotated[list[Thing], Field(max_length=256)]
    dependencies: Annotated[list[Dependency], Field(min_length=1, max_length=1024)]
    models: Annotated[list[ModelBinding], Field(max_length=256)]
    decisions: Annotated[list[Decision], Field(max_length=1024)]
    # Optional additions; a checkpoint without them keeps its digest (see checkpoint.document).
    #: The world version's title as written, kept only with readable text.
    title: Annotated[str, Field(min_length=1, max_length=TITLE_MAXIMUM)] | None = None
    #: The selected beings whose owner wrote who they are.
    characters: Annotated[list[Character], Field(max_length=256)] | None = None
    #: A site world's made parts as the version has them, where it was made from a world kind.
    parts: Annotated[list[Part], Field(max_length=2_048)] | None = None
    #: The town's people a model decides for, or whose decisions are kept, who are no placed thing.
    residents: Annotated[list[Resident], Field(max_length=256)] | None = None

    @model_validator(mode="after")
    def references(self) -> Self:
        from exulanica.canonical import sha256_of_canonical

        validate_object_id(self.project_id)
        unique(self.region_ids, "region")
        unique([t.thing_id for t in self.things], "thing")
        unique([c.thing_id for c in self.characters or []], "character")
        unique([p.part_id for p in self.parts or []], "part")
        residents = {r.resident_id for r in self.residents or []}
        unique(
            [t.thing_id for t in self.things] + [r.resident_id for r in self.residents or []],
            "thing or resident",
        )
        if not self.region_ids and (self.things or not (self.parts or residents)):
            raise ValueError(
                "a checkpoint holds a region, unless it keeps a made world's parts or its "
                "residents alone"
            )
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
            if (thing is None or thing.removed) and binding.thing_id not in residents:
                raise ValueError("a model assignment names an active selected thing or a resident")
            require("decision-contract", binding.contract_sha256)
            require("model-manifest", binding.model_manifest_sha256)
            bindings[binding.thing_id] = sha256_of_canonical(binding.model_dump()).hex()
        for decision in self.decisions:
            if bindings.get(decision.thing_id) != decision.binding_sha256:
                raise ValueError("decision evidence must match its selected model binding")
        for character in self.characters or []:
            if character.thing_id not in things:
                raise ValueError("a character names a selected thing")
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
    captured_at: Instant | None = None
    #: The living session this file is the evidence of, when it is one.
    living_session: LivingSession | None = None

    @model_validator(mode="after")
    def references(self) -> Self:
        validate_object_id(self.project_id)
        validate_object_id(self.session_id)
        if self.living_session is not None:
            named = f"session:{self.living_session.session_id}"
            if self.session_id != named and not self.session_id.startswith(f"{named}:"):
                raise ValueError("a living session's file is named for that session")
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
