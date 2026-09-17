"""Premises: a unit, its use class, its sign and the doors that reach it. Record shape only.

The sign is a key into the signage lexicon and the entry's text, so every sign a city shows
traces to a reviewed, licensed catalog entry; a use class whose entry takes no sign (a dwelling)
has neither. The use class is a key the living society maps to roles through its own catalog, and
the premises states what a destination needs: its storeys, its floor area, its ground bays and at
least one entrance a person can reach.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.common import extent_field

__all__ = ["SHAPE", "STAGE", "STAGE_ID", "STAGE_VERSION", "PremisesRecord"]

STAGE_ID: Final = "premises"
STAGE_VERSION: Final = 2


@dataclass(frozen=True, slots=True)
class PremisesRecord:
    RECORD_KIND: ClassVar[str] = "city.premises"
    RECORD_VERSION: ClassVar[int] = 2

    identity: str
    building_identity: str
    unit_ordinal: int
    #: A key into the use-class catalog.
    use_class: str
    #: A key into the signage-lexicon catalog, and that entry's text; both empty or both one.
    sign: tuple[str, ...]
    sign_text: tuple[str, ...]
    first_storey: int
    last_storey: int
    floor_area_mm2: int
    bay_identities: tuple[str, ...]
    entrance_identities: tuple[str, ...]
    extent: Extent


def _premises_rules(record: PremisesRecord) -> None:
    if len(record.sign) != len(record.sign_text):
        raise InvalidRecordError("a sign key and its text come together")
    if record.first_storey > record.last_storey:
        raise InvalidRecordError("a unit's first storey is at most its last")


SHAPE: Final = shapes.RecordShape(
    PremisesRecord,
    (
        shapes.identity("identity"),
        shapes.identity("building_identity", "city.massing"),
        shapes.integer("unit_ordinal", 0),
        shapes.key("use_class", "use-class"),
        shapes.keys("sign", "signage-lexicon", count_maximum=1),
        shapes.optional_text("sign_text"),
        shapes.integer("first_storey", 0, 119),
        shapes.integer("last_storey", 0, 119),
        shapes.integer("floor_area_mm2", 1),
        shapes.identities("bay_identities", "city.ground_bay"),
        shapes.identities("entrance_identities", "city.entrance", count_minimum=1),
        extent_field(),
    ),
    rules=(shapes.RecordRule("premises_sign_and_storeys", _premises_rules),),
    identity=shapes.IdentityRule(
        "premises", owner_field="building_identity", ordinal_field="unit_ordinal"
    ),
    extent_field="extent",
)

STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, SHAPE)
