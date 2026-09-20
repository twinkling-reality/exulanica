"""Asking for a world, and the refusal that is the point of asking.

The parameter cascade in :mod:`exulanica.grammar.parameters` validates, scopes, and refuses four
distinct mistakes by name, and outside the tests exactly one file originates a
:class:`~exulanica.grammar.parameters.CascadeBinding`: the corridor's own specification.
``exulanica/grammar/migration.py`` constructs one too, but only by rewriting a binding it was
handed, so it cannot originate one. This route is the door.

**Why this is not under ``/world``.** ``/world`` is the appearance API for the one world the
product shows, and its own module says "There is no topology mutation endpoint". A style parameter
and a generation parameter are not two names for one idea and must not share a mechanism:

====================  ==================================  ==================================
                      style (``exulanica.world.registry``) generation (this module)
====================  ==================================  ==================================
an unset value        every control declares a            refused. ``draw``, ``derive`` or
                      ``default_value``                   ``required``, never a constant
what a value is       a unitless float, or a              an integer with a declared unit,
                      registered key                      or a key
what a scope is       ``global`` or ``region``            an ordered cascade of levels,
                                                          coarsest binding wins
what it reaches       the look of a world that exists     what the world IS: extents, block
                                                          length, storey band
====================  ==================================  ==================================

The first row is the decisive one. A style has a current value to fall back on; a world that does
not exist yet has nothing, and the cascade's own words for why a default is refused are that "a
constant that silently stands in for a missing input is how a generated world starts carrying facts
nobody chose". Sharing a mechanism would have to give that up. So this is a separate prefix, for
the reason ``world_read`` and ``world_write`` are separate prefixes: two surfaces that would share a
code path only because their names rhyme.

**The seed is derived, never chosen, and that is not a convenience.** A caller states a
specification and the seed is the SHA-256 over it. Same specification, same world, every time;
different specification, different world, always. A caller-chosen seed delivers neither, because
the seed is what makes every drawn value and every record identity.

It also avoids a collision that a caller-chosen seed could cause, MEASURED on 15e8198c: two cities
differing only in ``block_length_mm`` have different generation digests and different record counts
and the SAME ``tile_inputs_digest`` and the same ``baked_tile_id``, because
:class:`~exulanica.grammar.grammars.city.tile.TileRecord` states the seed, the grammar pins, the
catalog digest and the tile's own coordinate and NOT the bindings. Since
``baked_tile.tile_inputs_digest`` is unique and ``record_baked_tile_bake`` answers a stored row
whose container differs with ``nondeterminism_detected``, a caller who could choose a seed could
mark a tile nondeterministic with two perfectly deterministic bakes. Deriving the seed here stops
that for callers who come through this route and NOT for anyone else, so the record's own blindness
is filed separately as a finding against ``TileRecord`` identity rather than treated as closed.

**Every refusal the cascade makes arrives with its parameter and its reason.** That is this route's
subject, not a side effect of it. :mod:`exulanica.api.app` maps the generator's error hierarchy on
the line ``exulanica.grammar.errors`` itself draws, between a caller's mistake and a data file's,
and passes each message through verbatim, because the cascade already names the parameter, the
value and the bound or level that refused it. An API that accepted a typo'd parameter name and
generated something anyway would be worse than no API.

**Generation runs inside the request, and the quota is why it can.** Resolving the cascade and
stopping there would leave an unchecked reach: two values INSIDE their declared ranges are still
refused later, by a stage, and MEASURED on 15e8198c one of them names no parameter at all
(``block_length_mm`` at 90000 mm asks for more cross streets than the street-name catalog has
``local_street`` names, refused as an ``InvalidRecordError``; ``storey_band_low`` at 8, declared
``[1, 40]``, is refused "outside [1, 4]" because ``massing`` narrows the band to what the
district's lots can build). A caller meeting either of those later, from a component it did not
call, is worse served than by a slow route. So this route generates, and the cost is bounded by
charging the workspace's tile quota for every tile the specification covers, before a record is
made.

**One level of detail, stated rather than defaulted.** Nothing reduces detail by level:
``exulanica/grammar/grammars/city/document.py``, which selects a tile's records out of a city's,
names ``lod`` zero times, and the only level in any stored tile is 0. A route accepting ``lod: 1``
would answer with tile records claiming a detail level nothing produced, so it accepts no level and
states the one it makes.

**What this route does NOT promise, measured on 15e8198c.** A specification is not enough to make a
world, and this route does not hide that. With ``CORRIDOR_BINDINGS``, all eleven values, over
40 seeds, 15 GENERATED A WORLD: 17 exhausted the six ``local_street`` names in
``assets/catalogs/street-name.v1.json``, and 8 wrote a ``clearance_mm`` a rooftop placement
legitimately kept and ``RooftopObjectRecord`` declares a maximum of 10000 for. Every layout value
was bound identically in all 40, so what decides whether the world exists is a value some stage
draws from the seed. The corridor is therefore a specification PLUS a seed that happened to work,
which is why a specification alone does not make a world.

This route does not retry with another seed. Retrying would break the property that makes a stored
specification unnecessary, that one specification is one world, and it would be choosing a value on
a caller's behalf, which is the thing the cascade's module refuses to do at length. So the caller
gets the stage's own refusal, and the two defects behind it are the city grammar's to fix rather
than this route's to paper over.

**AND A STAGE'S REFUSAL HAS ALREADY SPENT THE TILES**, which is worth saying plainly because it
compounds with the figures above. The charge is taken before a record is made, from
``exulanica.api.quotas``, whose own rule is that a charge "is taken before the tile is materialised
and not refunded when materialisation fails": charging less than a request can cost lets the last
request cross the ceiling, which is the one thing a ceiling prevents. The connection is in
autocommit, so the charge stands even though the request ends in an exception, deliberately. A
refusal the CASCADE makes spends nothing, because resolution happens first; a refusal a STAGE makes
spends the world. So a ceiling of 400 tiles buys about fifteen attempts at a five-tile world
and about six of them come back with a world. Both halves of that are held by tests.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Final, TypeAlias

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.quotas import charge_tiles
from exulanica.canonical import canonical_json
from exulanica.grammar import Grammar, generate
from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.grammars import builtin_registry
from exulanica.grammar.grammars.city.generation.terrain import city_tiles
from exulanica.grammar.parameters import (
    CascadeBinding,
    ParameterSpec,
    ParameterValue,
    ResolvedParameters,
)

router = APIRouter(prefix="/world-generation", tags=["world-generation"])

#: Every grammar this instance can generate from. Built once: registration is the grammars'
#: business and a request never adds to it.
REGISTRY: Final = builtin_registry()

#: The one level of detail any stage produces. See the module docstring: nothing reduces detail by
#: level, so this is a statement about what is made rather than a default standing in for a choice.
GENERATED_LOD: Final = 0

BoundValue: TypeAlias = StrictInt | StrictStr
#: How many tiles a resolved parameter set covers, for one grammar's own coverage rule.
_Tiles: TypeAlias = Callable[[Mapping[str, ParameterValue]], list[tuple[int, int]]]


class WorldCoverage:
    """How many tiles one grammar's world covers, and which parameters say so.

    ``reads`` is the point of this being data. The route must know a request's tile count BEFORE
    it generates, because that count is what the quota charges, and a parameter whose
    ``when_unset`` is ``derive`` has no single value until a stage derives one per subject. So the
    route refuses a specification that leaves any of ``reads`` unbound, naming each one, rather
    than guessing a count, charging the maximum, or re-deriving what the stage will draw. The last
    of those would be a second implementation of the stage's own rule, free to drift from it.
    """

    __slots__ = ("_tiles", "reads")

    def __init__(self, *reads: str, tiles: _Tiles) -> None:
        self.reads = reads
        self._tiles = tiles

    def tiles(self, values: Mapping[str, ParameterValue]) -> list[tuple[int, int]]:
        return self._tiles(values)


#: A grammar with no entry here is refused rather than generated, because a world whose tiles
#: cannot be counted cannot be metered. ``exulanica.api.quotas`` meters this route. ``box`` has
#: no entry and no tiles: it makes one box to prove the contract is generic, and it is not a
#: world anybody walks.
WORLD_COVERAGE: Final[Mapping[str, WorldCoverage]] = {
    "city": WorldCoverage(
        "city_extent_x_mm",
        "city_extent_y_mm",
        tiles=lambda values: city_tiles(
            int(values["city_extent_x_mm"]), int(values["city_extent_y_mm"])
        ),
    ),
}


class BindingBody(BaseModel):
    """One enclosing scope's values, as a caller states them.

    Deliberately almost unvalidated here. ``level`` and every key of ``values`` are checked by
    :meth:`CascadeBinding.of` and the cascade, which refuse an unknown level, an unknown
    parameter, a level too fine for a parameter, a second binding at one level and a value outside
    its declared range, each naming the thing that was wrong. A pattern on this model would refuse
    first and name a field path instead, which is a worse answer to the same question.
    """

    model_config = ConfigDict(extra="forbid")

    level: StrictStr = Field(min_length=1, max_length=100)
    #: A bool is not accepted: ``StrictInt`` refuses one, and so does ``ParameterSpec.check``,
    #: which tests ``type(value) is not int``. Two independent refusals for one mistake, kept
    #: because this one is invisible in JSON, where ``true`` and ``1`` look equally like a number.
    values: dict[StrictStr, BoundValue] = Field(default_factory=dict, max_length=200)


class SpecificationBody(BaseModel):
    """A world, as a request states it: which grammar, and what its scopes bind."""

    model_config = ConfigDict(extra="forbid")

    grammar_id: StrictStr = Field(min_length=1, max_length=100)
    grammar_version: StrictInt = Field(ge=1)
    #: A list rather than a mapping by level, so that two bindings at one level REACH the cascade
    #: and are refused by it. A mapping would silently keep the last of them, which is the exact
    #: class of mistake this route exists to surface.
    bindings: list[BindingBody] = Field(default_factory=list, max_length=20)


class ParameterView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    #: Absent for a parameter whose value each reading stage derives per subject. There is no
    #: single value to state, and stating one would name a number no stage used.
    value: int | str | None = None
    #: The cascade level whose binding set it, ``draw``, or ``derive``.
    source: str


class DeclaredParameterView(BaseModel):
    """One parameter as the grammar declares it. What a human needs to tune it themselves."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    when_unset: str
    unit: str
    level: str
    stage: str
    vocabulary: str
    basis: str
    minimum: int | None = None
    maximum: int | None = None
    options: list[str] = Field(default_factory=list)


class GrammarView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grammar_id: str
    grammar_version: int
    #: Coarsest first. A binding may set a parameter at its own level or any coarser one.
    cascade_levels: list[str]
    stages: list[str]
    #: The parameters whose values this route needs bound before it will generate, because they
    #: are what tells it how many tiles to charge. Empty means this grammar cannot be generated
    #: here at all, and ``generable`` says so.
    coverage_reads: list[str]
    generable: bool
    parameters: list[DeclaredParameterView]


class StageRecordCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    stage_version: int
    records: int


class GeneratedWorldView(BaseModel):
    """What a caller got, and everything an offline bake needs to make the same world again."""

    model_config = ConfigDict(extra="forbid")

    world_seed: str
    world_identity: str
    grammar_id: str
    grammar_version: int
    lod: int
    tile_count: int
    tiles: list[tuple[int, int]]
    #: The generation's own digest over every record it emitted. A bake that re-derives this world
    #: from ``world_seed`` and the same specification can compare its own against this one, which
    #: is a second, independent statement of the same fact rather than a restatement of it.
    output_digest: str
    record_count: int
    records_by_stage: list[StageRecordCount]
    parameters: list[ParameterView]
    tiles_charged: int
    tiles_remaining: int


def specification_payload(
    grammar_id: str, grammar_version: int, bindings: Sequence[CascadeBinding]
) -> dict[str, object]:
    """The canonical form of a specification: what the seed is taken over.

    Bindings are sorted by level and their values are already sorted by name by
    :meth:`CascadeBinding.of`, so two requests stating the same specification in a different order
    produce the same payload and therefore the same world.

    The level of detail is NOT in here. Two levels of detail of one world are one world, and a
    tile's level is a property of the tile record, so folding it in would make two seeds for one
    thing.
    """
    return {
        "profile": "exulanica.world-specification/v1",
        "grammar_id": grammar_id,
        "grammar_version": grammar_version,
        "bindings": [
            {"level": binding.level, "values": dict(binding.values)}
            for binding in sorted(bindings, key=lambda binding: binding.level)
        ],
    }


def derived_seed(payload: Mapping[str, object]) -> str:
    """The seed a specification makes: SHA-256 over its canonical JSON, as lowercase hex.

    Over canonical JSON rather than a concatenation of the fields, because
    ``exulanica.ingest.stages`` records what an unframed concatenation cost: version 1 of its
    idempotency key joined variable-length fields with no framing, so ``("vision", 11)`` and
    ``("vision1", 1)`` hashed identically and two stages could share one row. Canonical JSON
    frames every field by construction and refuses a float outright.
    """
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def derived_identity(seed: str) -> str:
    """The world identity a specification admits: uuid5 of its seed, under the URL namespace.

    From the SEED rather than from the payload again, and that is the whole reason this is one
    line. The seed is already a SHA-256 over the specification and is a fixed-length hex string,
    so there is no variable-length field to frame and nothing to get wrong. Under the invalid
    documentation domain, as the corridor's own identity is, because no such URL is ever fetched.

    ``require_identity`` says a subject identity is "supplied by whoever admitted it". This route
    is what admits one, and it admits exactly one per specification, which is the same property
    the derived seed carries: ask twice, get the same world.
    """
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"https://exulanica.invalid/world-generation/1/{seed}")
    )


def _declared_view(spec: ParameterSpec) -> DeclaredParameterView:
    return DeclaredParameterView(
        name=spec.name,
        kind=spec.kind,
        when_unset=spec.when_unset,
        unit=spec.unit,
        level=spec.level,
        stage=spec.stage,
        vocabulary=spec.vocabulary,
        basis=spec.basis,
        minimum=spec.minimum if spec.kind == "integer" else None,
        maximum=spec.maximum if spec.kind == "integer" else None,
        options=list(spec.options),
    )


def _grammar_view(grammar: Grammar) -> GrammarView:
    coverage = WORLD_COVERAGE.get(grammar.key.grammar_id)
    return GrammarView(
        grammar_id=grammar.key.grammar_id,
        grammar_version=grammar.key.grammar_version,
        cascade_levels=list(grammar.cascade.levels),
        stages=[stage.stage_id for stage in grammar.stages],
        coverage_reads=list(coverage.reads) if coverage else [],
        generable=coverage is not None,
        parameters=[_declared_view(spec) for spec in grammar.parameters.parameters],
    )


def _parameter_views(resolved: ResolvedParameters) -> list[ParameterView]:
    values = dict(resolved.values)
    return [
        ParameterView(name=name, value=values.get(name), source=source)
        for name, source in resolved.sources
    ]


@router.get(
    "/grammars",
    summary="Every parameter a world can be asked for by, as its grammar declares it.",
)
def grammars(_session: CurrentSession) -> list[GrammarView]:
    """The catalog. Nobody can tune a parameter they cannot enumerate.

    Every declared parameter, with its unit, the cascade level it belongs to, the one stage that
    reads it, what happens when nothing sets it, its range or its options, and the stated basis of
    that range. All of it read off the registered grammar rather than restated here, so this
    cannot drift from what the cascade will actually enforce.
    """
    return [
        _grammar_view(REGISTRY.get(key.grammar_id, key.grammar_version))
        for key in REGISTRY.registered_keys()
    ]


@router.post(
    "/worlds",
    summary="State a specification; get the world it makes, or a refusal naming the parameter.",
)
def ask_for_a_world(
    body: SpecificationBody, connection: ScopedConnection, session: CurrentSession
) -> GeneratedWorldView:
    """Resolve, charge, generate.

    In that order, and the order is the point. The charge is taken from the tile count the
    RESOLVED specification covers, before any record is made, so a request the workspace cannot
    afford costs nothing but the resolution. That mirrors ``exulanica.models.budget``, which
    reserves before a call for the same reason ``exulanica.api.quotas`` gives: charging less than
    a request can cost lets the last request cross the ceiling, which is the one thing a ceiling
    exists to prevent.

    Nothing is stored. A specification needs no row, because the seed is derived from it: the
    request body and this route are together enough to make the same world again, and a table
    would be a second copy of a fact that is already reproducible.
    """
    grammar = REGISTRY.get(body.grammar_id, body.grammar_version)
    coverage = WORLD_COVERAGE.get(grammar.key.grammar_id)
    if coverage is None:
        raise InvalidParameterError(
            f"{grammar.key.grammar_id} declares no world coverage rule, so the tiles a request "
            "for it would materialise cannot be counted and cannot be metered"
        )

    bindings = tuple(CascadeBinding.of(item.level, item.values) for item in body.bindings)
    payload = specification_payload(body.grammar_id, body.grammar_version, bindings)
    seed = derived_seed(payload)
    identity = derived_identity(seed)

    resolved = grammar.cascade.resolve(
        grammar.parameters, bindings, seed=seed, domain_prefix=grammar.key.grammar_id
    )
    values = dict(resolved.values)
    unbound = [name for name in coverage.reads if name not in values]
    if unbound:
        raise InvalidParameterError(
            f"{', '.join(unbound)} must be bound by some level: the tiles this request would "
            "materialise are counted from them before anything is generated, and a parameter a "
            "stage derives per subject has no single value to count"
        )

    tiles = coverage.tiles(values)
    quota = charge_tiles(connection, session.workspace_id, len(tiles))

    generation = generate(grammar, seed=seed, subject_identity=identity, bindings=bindings)
    return GeneratedWorldView(
        world_seed=seed,
        world_identity=identity,
        grammar_id=grammar.key.grammar_id,
        grammar_version=grammar.key.grammar_version,
        lod=GENERATED_LOD,
        tile_count=len(tiles),
        tiles=tiles,
        output_digest=generation.receipt.output_digest,
        record_count=sum(len(emission.records) for emission in generation.emissions),
        records_by_stage=[
            StageRecordCount(
                stage=emission.stage_id,
                stage_version=emission.stage_version,
                records=len(emission.records),
            )
            for emission in generation.emissions
        ],
        parameters=_parameter_views(resolved),
        tiles_charged=len(tiles),
        tiles_remaining=quota.tiles_remaining,
    )
