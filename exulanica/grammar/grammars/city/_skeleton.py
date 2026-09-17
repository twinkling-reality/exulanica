"""How a city stage with no generator is declared. One sentence, the same for every stage."""

from __future__ import annotations

from collections.abc import Callable

from exulanica.grammar.contract import UnimplementedStage
from exulanica.grammar.shapes import RecordShape, validate_record


def _validator(shape: RecordShape) -> Callable[[object], None]:
    def validate(record: object) -> None:
        validate_record(record, shape)

    validate.__name__ = f"validate_{shape.record_type.__name__}"
    return validate


def skeleton(stage_id: str, stage_version: int, *record_shapes: RecordShape) -> UnimplementedStage:
    return UnimplementedStage(
        stage_id=stage_id,
        stage_version=stage_version,
        reason=(
            f"the {stage_id} stage has a record shape and a validator and no generator; "
            "it emits nothing rather than plausible output"
        ),
        validators=tuple((shape.record_type, _validator(shape)) for shape in record_shapes),
    )
