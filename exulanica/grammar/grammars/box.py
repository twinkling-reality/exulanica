"""The box grammar: three integer extents.

It makes an axis-aligned box and nothing else. It shares no vocabulary with the city and goes
through the same descriptor, cascade, draw, validation and receipt.

Its extent bounds, 1 to 10,000 mm, are authored for the proof and describe no real object. Its
declared semantics admit it to no projection. An unset extent is drawn from the seed in
``box.parameters.<name>``, and the receipt records that it was drawn.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

from exulanica.grammar.contract import Grammar, StageContext, StageEmission
from exulanica.grammar.records import require_integer, require_record

__all__ = ["BOX_GRAMMAR", "EXTENT_STAGE_VERSION", "BoxExtentRecord", "validate_box_extent"]

EXTENT_STAGE_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class BoxExtentRecord:
    RECORD_KIND: ClassVar[str] = "box.extent"
    RECORD_VERSION: ClassVar[int] = 1

    width_mm: int
    depth_mm: int
    height_mm: int


def validate_box_extent(record: object) -> None:
    require_record(record, BoxExtentRecord)
    for name in ("width_mm", "depth_mm", "height_mm"):
        require_integer(name, getattr(record, name), minimum=1)


@dataclass(frozen=True, slots=True)
class _ExtentStage:
    stage_id: str = "extent"
    stage_version: int = EXTENT_STAGE_VERSION

    def emit(self, context: StageContext) -> StageEmission:
        record = BoxExtentRecord(
            width_mm=context.parameters["width_mm"],  # type: ignore[arg-type]
            depth_mm=context.parameters["depth_mm"],  # type: ignore[arg-type]
            height_mm=context.parameters["height_mm"],  # type: ignore[arg-type]
        )
        return StageEmission(
            stage_id=self.stage_id,
            stage_version=self.stage_version,
            status="emitted",
            reason="",
            records=(record,),
        )

    def validate(self, record: object) -> None:
        validate_box_extent(record)


BOX_GRAMMAR: Final = Grammar.from_descriptor(
    Path(__file__).with_name("box.v1.json"), stages=(_ExtentStage(),)
)
