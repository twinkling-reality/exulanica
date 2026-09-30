"""How a city stage with a generator is declared, and what every generator shares.

A :class:`GeneratorStage` is a stage whose ``emit`` returns records, each validated by the stage's
own record shapes, exactly as :func:`exulanica.grammar.contract.generate` requires. It exposes the
same ``validators`` a skeleton stage does, so the descriptor's stage declarations still hold the
code to the record kinds each stage takes.

**Parameters.** A ``derive`` parameter is derived by the one stage that reads it, per subject, and
:func:`derived` is the only way a generator does so: it takes the value a binding set when one did,
and otherwise draws within the declared range narrowed by whatever catalog range applies, in a
domain named for the parameter and the subject. The narrowing never widens the declared range: a
catalog range that does not meet it is refused, not clamped.

**Weights.** A choice may be derived in proportion to weights (:func:`weighted_pick`): a subject
draws among the options it admits in proportion to each one's weight, and evenly among them when
every one weighs 0, so a weight states a preference among what fits and never leaves a subject with
nothing. A version that states no weights draws evenly, exactly as before weights existed.

**Earlier stages.** :func:`prior_records` returns what an earlier stage emitted, by kind, and
refuses a stage that has not run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, Final

from exulanica.grammar.catalogs import Catalog
from exulanica.grammar.contract import StageContext, StageEmission
from exulanica.grammar.draw import draw_integer
from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city.catalogs import entry_fields, load_city_catalogs
from exulanica.grammar.grammars.city.descriptor import CITY_GRAMMAR_VERSION, CITY_SURFACES
from exulanica.grammar.parameters import ParameterValue
from exulanica.grammar.shapes import RecordShape, validate_record

__all__ = [
    "GeneratorStage",
    "catalog",
    "covering",
    "derived",
    "draw",
    "entry",
    "pick",
    "prior_records",
    "weighted_pick",
]

#: Every bounded draw's span is below this, so a choice among catalog keys is always one draw.
_KEY_LIMIT: Final = 1 << 16


@dataclass(frozen=True, slots=True)
class GeneratorStage:
    """A city stage that generates its records."""

    stage_id: str
    stage_version: int
    shapes: tuple[RecordShape, ...]
    generate: Callable[[StageContext], Iterable[object]]

    @property
    def validators(self) -> tuple[tuple[type, Callable[[object], None]], ...]:
        def validator(shape: RecordShape) -> Callable[[object], None]:
            def validate(record: object) -> None:
                validate_record(record, shape)

            validate.__name__ = f"validate_{shape.record_type.__name__}"
            return validate

        return tuple((shape.record_type, validator(shape)) for shape in self.shapes)

    def emit(self, context: StageContext) -> StageEmission:
        return StageEmission(
            stage_id=self.stage_id,
            stage_version=self.stage_version,
            status="emitted",
            reason="",
            records=tuple(self.generate(context)),
        )

    def validate(self, record: object) -> None:
        for shape in self.shapes:
            if type(record) is shape.record_type:
                validate_record(record, shape)
                return
        raise InvalidRecordError(f"{self.stage_id} declares no record type {type(record).__name__}")


def prior_records(context: StageContext, stage_id: str, record_type: type) -> list[Any]:
    """What an earlier stage emitted of one record type, in emission order."""
    for emission in context.prior:
        if emission.stage_id == stage_id:
            if emission.status != "emitted":
                raise InvalidRecordError(
                    f"{context.stage_id} reads the {stage_id} stage, which emitted nothing"
                )
            return [record for record in emission.records if type(record) is record_type]
    raise InvalidRecordError(f"{context.stage_id} reads the {stage_id} stage, which has not run")


@cache
def _catalogs(grammar_version: int) -> Mapping[str, Catalog]:
    return {item.catalog_id: item for item in load_city_catalogs(grammar_version=grammar_version)}


def catalog(catalog_id: str, grammar_version: int = CITY_GRAMMAR_VERSION) -> Catalog:
    """A catalog as ``grammar_version`` reads it. Every field two versions' editions both state
    has the same value in each, so a reader of such a field may name neither."""
    return _catalogs(grammar_version)[catalog_id]


def entry(catalog_id: str, key: str, grammar_version: int = CITY_GRAMMAR_VERSION) -> dict[str, Any]:
    return entry_fields(catalog(catalog_id, grammar_version), key)


def draw(context: StageContext, decision: str, ordinal: int, minimum: int, maximum: int) -> int:
    """One bounded draw for one subject: domain ``city.<stage>.<decision>``, the subject's ordinal.

    A decision is one domain and a subject is one ordinal in it, so a new decision never moves an
    earlier one and one subject's draw never depends on another's.
    """
    domain = f"{context.grammar_id}.{context.stage_id}.{decision}"
    return draw_integer(context.seed, domain, ordinal, minimum, maximum)


def pick(context: StageContext, decision: str, ordinal: int, options: Sequence[Any]) -> Any:
    """One of ``options``, in their stated order, by one bounded draw."""
    if not options or len(options) > _KEY_LIMIT:
        raise InvalidParameterError(f"a pick is among 1 to {_KEY_LIMIT} options")
    return options[draw(context, decision, ordinal, 0, len(options) - 1)]


def weighted_pick(
    context: StageContext,
    decision: str,
    ordinal: int,
    options: Sequence[str],
    weights: Mapping[str, int],
) -> str:
    """One of ``options`` in proportion to its weight, by one bounded draw; evenly when every
    option weighs 0. Every option must have a weight: an option with none is refused by name
    rather than read as 0."""
    missing = [option for option in options if option not in weights]
    if missing:
        raise InvalidParameterError(f"{decision}: no weight states {missing}")
    total = sum(weights[option] for option in options)
    if total == 0:
        return pick(context, decision, ordinal, options)  # type: ignore[no-any-return]
    point = draw(context, decision, ordinal, 0, total - 1)
    for option in options:
        if point < weights[option]:
            return option
        point -= weights[option]
    raise InvalidParameterError(f"{decision}: a draw of {point} fell past its {total} weights")


def derived(
    context: StageContext,
    name: str,
    ordinal: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    options: Sequence[str] | None = None,
    weights: Mapping[str, int] | None = None,
) -> ParameterValue:
    """A parameter's value for the subject ``ordinal``: the bound value, or a derivation.

    The draw is in the parameter's own decision domain, ``city.<stage>.<name>``. ``minimum`` and
    ``maximum`` narrow an integer's declared range, and ``options`` narrow a choice's, when a
    catalog entry the subject already has says so; a narrowing that misses the declared range is
    refused. A bound value outside the narrowed range is refused too, never clamped. ``weights``
    make a choice's draw proportional (:func:`weighted_pick`); without them it is even.
    """
    spec = CITY_SURFACES[context.grammar_version].parameters.get(name)
    if spec.stage != context.stage_id:
        raise InvalidParameterError(f"{name} is read by {spec.stage}, not {context.stage_id}")
    bound = context.parameters.get(name)
    if spec.kind == "integer":
        low = spec.minimum if minimum is None else max(spec.minimum, minimum)
        high = spec.maximum if maximum is None else min(spec.maximum, maximum)
        if low > high:
            raise InvalidParameterError(
                f"{name}: the range [{minimum}, {maximum}] a subject narrows to misses "
                f"[{spec.minimum}, {spec.maximum}]"
            )
        if bound is not None:
            if not low <= bound <= high:  # type: ignore[operator]
                raise InvalidParameterError(f"{name} is bound to {bound}, outside [{low}, {high}]")
            return bound
        return draw(context, name, ordinal, low, high)
    allowed = tuple(option for option in spec.options if options is None or option in options)
    if not allowed:
        raise InvalidParameterError(f"{name}: no option of {spec.options} is among {options}")
    if bound is not None:
        if bound not in allowed:
            raise InvalidParameterError(f"{name} is bound to {bound!r}, not one of {allowed}")
        return bound
    if weights is not None:
        return weighted_pick(context, name, ordinal, allowed, weights)
    return pick(context, name, ordinal, allowed)


def covering(*extents: Extent) -> Extent:
    """The smallest extent containing every one given."""
    return Extent(
        min(extent.min_x_mm for extent in extents),
        min(extent.min_y_mm for extent in extents),
        min(extent.min_z_mm for extent in extents),
        max(extent.max_x_mm for extent in extents),
        max(extent.max_y_mm for extent in extents),
        max(extent.max_z_mm for extent in extents),
    )
