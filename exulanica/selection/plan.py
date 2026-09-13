"""The Selection plan: a filled-in form, not a query.

ADR-0005 makes one Selection primitive reachable from four equal entry points, and
``architecture-overview.md`` section 5.1 fixes what the model is allowed to emit:

    "The model emits a **closed-vocabulary JSON QueryPlan**: a fixed intent enum, resolved
    entity ids only, no table names, no column names, no operator names, no workspace id. A
    fixed compiler turns the plan into parameterized SQL with **zero string interpolation of
    model output**. Free text exists in exactly one field, the semantic query string, and
    becomes a bound parameter."

The rejected alternative was model-generated SQL behind a parser and an allowlist, and the
reason it was rejected is worth restating because it is the whole design: sanitising generated
SQL is a containment problem, and a form has no expressive surface left to sanitise. Nothing in
this module can express a table, a column, an operator or a join. There is no field a
sufficiently clever string could escape from, because there is no field whose contents reach
SQL as anything but a bound parameter.

Two consequences that look like omissions and are not:

*   **No workspace id.** Authorization comes from the session and only from the session
    (section 5.2 stage 3). A plan that could name a workspace would be a plan that could name
    somebody else's.
*   **No sort order, no offset, no aggregate.** Every one of those is a place where a caller
    could ask the database to do work proportional to something they chose. Ordering is fixed
    per intent and stated there.

The Companion is not privileged: it emits this, the World Index emits this, and the Atlas emits
this. Nothing downstream can tell which surface produced a plan, which is what stops the
conversational path expressing a filter the interface cannot.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "MAX_ENTITY_IDS",
    "MAX_LIMIT",
    "MAX_SEMANTIC_QUERY_CHARS",
    "MAX_TIME_WINDOWS",
    "CaptureSelector",
    "CaptureWindow",
    "ContentPageCursor",
    "ContentScope",
    "ContentSelector",
    "EntityMode",
    "EntitySelector",
    "EpistemicScope",
    "Intent",
    "PlaceSelector",
    "ProcessingState",
    "SelectionPlan",
]

#: Cost bounds, checked by the validator rather than trusted here. They live in this module
#: because they are part of the contract the plan schema describes: a caller reading the schema
#: should see the ceiling, not discover it from a rejection.
MAX_ENTITY_IDS: Final = 16
MAX_TIME_WINDOWS: Final = 8
MAX_SEMANTIC_QUERY_CHARS: Final = 400
MAX_LIMIT: Final = 24


class Intent(StrEnum):
    """What the caller wants back. Fixed, and each one has a fixed ordering.

    Both intents run the same constraint resolution over the same tables. They differ only in
    what they project, which is why "the Companion asked a question" and "the user clicked a
    date range" cannot diverge: there is one resolver.
    """

    #: The captures a Selection matches, with the evidence spans that made them match. This is
    #: what drives Atlas recomposition and what an answer cites.
    CAPTURES = "captures"
    #: The entities that appear within a Selection. The World Index's "who was on this trip".
    ENTITIES = "entities"
    #: Personal memories, admitted geography, and authored variants related through a confirmed
    #: place bridge.
    CONTENT = "content"


class ContentScope(StrEnum):
    """Which origin classes a cross-content Selection may return."""

    RELATED = "related"
    MEMORIES_ONLY = "memories_only"


class ContentPageCursor(BaseModel):
    """A keyset cursor emitted by the executor, never an offset."""

    model_config = ConfigDict(extra="forbid")

    kind_order: Annotated[int, Field(ge=0, le=5)]
    sort_time: dt.datetime
    result_key: Annotated[str, Field(min_length=1, max_length=700)]

    @model_validator(mode="after")
    def _aware_time(self) -> ContentPageCursor:
        if self.sort_time.tzinfo is None:
            raise ValueError("a content page cursor timestamp must carry an offset")
        return self


class ContentSelector(BaseModel):
    """Origin scope and bounded keyset page for unified place retrieval."""

    model_config = ConfigDict(extra="forbid")

    scope: ContentScope
    after: ContentPageCursor | None = None


class EntityMode(StrEnum):
    """Three modes, because two documents specify this and they do not say the same thing.

    ``evaluation-methodology.md`` M6 is the one with tests attached, and it is explicit:

        "``ANY`` means at least one named entity present within the scope. ``ALL`` means every
        named entity present within the scope, **not necessarily in the same photograph**. Scope
        is the memory region. The stricter reading (``ALL`` in a single photograph) is a
        separate, explicitly named filter, ``TOGETHER``. All three are documented in the schema
        and all three are tested."

    ADR-0005 and ``interaction-model.md`` section 7 say something different with two names:
    "ANY or ALL. ALL requires a shared evidence window, not merely co-presence in one capture."
    Read as a two-valued vocabulary those conflict, because M6 makes ALL the looser of the two
    and the ADR makes it the stricter.

    Read as three, they reconcile exactly, and that is what is implemented:

    *   ``ANY`` and ``ALL`` take M6's meanings, including M6's trap (c), which requires that
        TOGETHER return empty for a pair present in the same region but never in the same
        photograph while ALL returns the region.
    *   ``TOGETHER`` is the ADR's strict filter, and "shared evidence window" is what
        distinguishes it from mere co-presence: the occurrences' ``presence`` multiranges must
        overlap inside one capture, not merely both occur somewhere in it. For a photograph
        every presence interval is the degenerate ``[0, 1)``, so the two coincide; for video
        they are different questions, and "these two were together" is the one the product is
        about. Implementing the general form now means the video path needs no second one.

    **The scope of ALL is the Selection's own other dimensions**, and that is a decision this
    code makes rather than one the documents make. M6 says "scope is the memory region", and
    ADR-0005 records that whether a region is one capture or a place-on-a-trip cluster is OPEN
    until the corpus has been measured. Scoping ALL to "the captures matching everything else in
    this plan" is well defined today, satisfies M6's trap (a), and needs no answer to the open
    question.
    """

    ANY = "any"
    ALL = "all"
    TOGETHER = "together"


class EpistemicScope(StrEnum):
    """Whether the user is looking at what is known or at what is guessed.

    ``confirmed`` counts only ``entity_link.state = 'confirmed'``, which by construction means a
    human decided it. ``include_proposals`` also counts ``auto_provisional``, which may drive
    layout and filtering and may never support a historical factual clause. The answer path
    therefore refuses to cite anything reached under ``include_proposals``; see
    :mod:`exulanica.selection.packet`.
    """

    CONFIRMED = "confirmed"
    INCLUDE_PROPOSALS = "include_proposals"


class ProcessingState(StrEnum):
    """How far a capture got, so a user can ask for what is actually explorable."""

    #: Every declared stage produced an artifact.
    COMPLETE = "complete"
    #: Intake and rendition ran; the vision stage did not. Capture-supported facts only.
    CAPTURE_ONLY = "capture_only"


class CaptureWindow(BaseModel):
    """One half-open interval on capture wall-clock time.

    Half-open at the end, matching every other interval in this system, so two adjacent windows
    tile without overlapping and a capture on the boundary belongs to exactly one of them.

    Capture time comes from EXIF. ADR-0005 records why this dimension is the most reliable one
    in the product: it costs no model call and it is correct for effectively every photograph,
    including the ones that can never be reconstructed.
    """

    model_config = ConfigDict(extra="forbid")

    start: dt.datetime
    end: dt.datetime

    @model_validator(mode="after")
    def _non_empty(self) -> CaptureWindow:
        if self.end <= self.start:
            raise ValueError(f"a capture window must be non-empty: [{self.start}, {self.end})")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError(
                "a capture window must carry an offset. A naive datetime is a wall-clock "
                "reading with the one fact that makes it comparable missing."
            )
        return self


class EntitySelector(BaseModel):
    """Which people, objects or places, and how they combine.

    Ids only. ``architecture-overview.md`` 5.1 says "resolved entity ids only", which means the
    surface that produced the plan already turned a name into an id, and the plan carries no
    string a lookup could be built from. A model asked to filter by "Julie" has to have been
    given Julie's id, and it is given ids only for entities the session may already see.
    """

    model_config = ConfigDict(extra="forbid")

    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=MAX_ENTITY_IDS)]
    mode: EntityMode = EntityMode.ANY


class PlaceSelector(BaseModel):
    """Places, as entity ids.

    A place is an entity like any other, so this is not a second entity dimension: it is the
    same dimension named separately because the interface presents it separately, and because
    combining "Julie" with "Gullfoss" is an AND across dimensions while combining "Julie" with
    "Leo" may be an ANY within one.
    """

    model_config = ConfigDict(extra="forbid")

    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=MAX_ENTITY_IDS)]


class CaptureSelector(BaseModel):
    """Properties of the capture itself.

    ADR-0005 names two: reconstruction rung and processing state. Only processing state exists
    here, because reconstruction does not exist yet: there is no rung recorded anywhere in the
    schema, so a rung filter would be a field that silently matches everything, which is worse
    than a field that is absent. It is added when there is something to filter on.
    """

    model_config = ConfigDict(extra="forbid")

    processing_states: Annotated[list[ProcessingState], Field(min_length=1, max_length=2)]


class SelectionPlan(BaseModel):
    """The whole plan. Everything a Selection can say, and nothing else.

    An empty plan, with no dimension set, is legal and means "everything", which is what the
    Atlas shows before a user has asked anything. It is still bounded by ``limit``.
    """

    model_config = ConfigDict(extra="forbid")

    intent: Intent

    entities: EntitySelector | None = None
    time: Annotated[list[CaptureWindow], Field(max_length=MAX_TIME_WINDOWS)] = Field(
        default_factory=list,
        description="Windows are ORed with each other and ANDed with every other dimension.",
    )
    place: PlaceSelector | None = None
    capture: CaptureSelector | None = None
    content: ContentSelector | None = None
    epistemic: EpistemicScope = EpistemicScope.CONFIRMED

    semantic_query: Annotated[str | None, Field(max_length=MAX_SEMANTIC_QUERY_CHARS)] = Field(
        default=None,
        description=(
            "The one free-text field. It becomes a bound parameter in a full-text match over "
            "capture-derived text and nothing else. It is never interpolated, never parsed as a "
            "query language, and never reaches a shell, a path or an identifier."
        ),
    )

    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = MAX_LIMIT

    @model_validator(mode="after")
    def _multi_entity_modes_need_two(self) -> SelectionPlan:
        """ALL or TOGETHER over one entity is ANY over one entity, and asking is a caller bug.

        Accepting it would be harmless and would also hide a class of mistake: a caller that
        meant to pass two ids and passed one gets an answer about a single person under a mode
        that promises they were together with somebody.
        """
        if (
            self.entities is not None
            and self.entities.mode in {EntityMode.ALL, EntityMode.TOGETHER}
            and len(self.entities.ids) < 2
        ):
            raise ValueError(
                f"mode {self.entities.mode!s} is a statement about several entities and needs "
                "at least two of them; over one entity it is the same query as 'any'"
            )
        if self.intent is Intent.CONTENT:
            if self.content is None or self.place is None:
                raise ValueError("content selections require both content and place selectors")
            if self.entities is not None or self.time or self.capture is not None:
                raise ValueError(
                    "entity, time, and capture filters do not apply to cross-content selections"
                )
            if self.semantic_query is not None:
                raise ValueError(
                    "cross-content place membership is relational and does not use semantic text"
                )
        elif self.content is not None:
            raise ValueError("the content selector applies only to the content intent")
        return self

    @property
    def is_unconstrained(self) -> bool:
        """True when nothing narrows the result. Not an error; the Atlas opens this way."""
        return (
            self.entities is None
            and not self.time
            and self.place is None
            and self.capture is None
            and self.content is None
            and self.semantic_query is None
        )
