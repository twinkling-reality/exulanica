"""A building selected from the admitted NYC layer, as the Selection a question about it runs.

``POST /selection/ask`` takes a building selected from the independently admitted semantic city
layer. The building's identity is read from its admitted NYC Open Data record alone, and a
question about it runs over the memory place a confirmed place bridge ties to the building's
place. A building with no bridge is stated and nothing is retrieved. Google content is consulted
for neither.
"""

from __future__ import annotations

import re
import uuid

import psycopg

from exulanica.environment.nyc_open_data import PROVIDER_KEY as NYC_OPEN_DATA_PROVIDER_KEY
from exulanica.environment.repository import EnvironmentRepository
from exulanica.errors import ExulanicaError
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.place_bridge import PlaceBridgeRepository
from exulanica.selection.plan import (
    ContentScope,
    ContentSelector,
    Intent,
    PlaceSelector,
    SelectionPlan,
)
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "CitySelectionRefused",
    "answer_led_by",
    "answer_without_a_bridge",
    "resolve_city_selection",
]


class CitySelectionRefused(ExulanicaError):
    """A city selection no question can be asked about, and the sentence that says why."""


def resolve_city_selection(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    store: ContentAddressedStore,
    *,
    admission_id: uuid.UUID,
    feature_id: str,
    supplied_plan: SelectionPlan | None,
) -> tuple[SelectionPlan | None, AnswerClause]:
    """Resolve semantic identity and its place bridge without consulting Google content.

    Raises :class:`CitySelectionRefused` for a selection that is not one admitted NYC Open Data
    building, a building record whose identifiers are malformed, and a supplied plan the bridge
    cannot verify or does not match. The repository's own refusals to read the selection are
    raised as they are.
    """
    catalog = EnvironmentRepository(connection, workspace_id, store).read_features(
        admission_id, feature_id=feature_id
    )
    if catalog.provider_key != NYC_OPEN_DATA_PROVIDER_KEY or len(catalog.features) != 1:
        raise CitySelectionRefused("the city selection is not admitted NYC Open Data")
    feature = catalog.features[0]
    provider_feature_id = feature.get("provider_feature_id")
    properties = feature.get("semantic_properties")
    if (
        not isinstance(provider_feature_id, str)
        or re.fullmatch(r"doitt_id:[1-9][0-9]*", provider_feature_id) is None
        or not isinstance(properties, dict)
    ):
        raise CitySelectionRefused("the semantic city feature is malformed")
    bridges = PlaceBridgeRepository(connection, workspace_id).confirmed()
    bridge = next((held for held in bridges if held.place_id == catalog.place_id), None)
    if bridge is None:
        if supplied_plan is not None:
            raise CitySelectionRefused(
                "the supplied plan cannot be verified without a confirmed place bridge"
            )
        plan = None
    else:
        if supplied_plan is not None and (
            supplied_plan.intent is not Intent.CONTENT
            or supplied_plan.place is None
            or bridge.entity_id not in supplied_plan.place.ids
        ):
            raise CitySelectionRefused(
                "the supplied plan does not match the selected semantic city place"
            )
        plan = supplied_plan or SelectionPlan(
            intent=Intent.CONTENT,
            place=PlaceSelector(ids=[bridge.entity_id]),
            content=ContentSelector(scope=ContentScope.RELATED),
        )
    name = properties.get("name")
    bin_value = properties.get("bin")
    label = name if isinstance(name, str) and name else "an unnamed NYC building footprint"
    bin_text = (
        bin_value.removeprefix("bin:")
        if isinstance(bin_value, str) and bin_value.startswith("bin:")
        else "not supplied"
    )
    return plan, AnswerClause(
        text=(
            f"{label} is selected from official NYC BUILDING data. Its semantic identifiers "
            f"are {provider_feature_id.upper()} and BIN {bin_text}; Google supplied no identity."
        ),
        type=ClauseType.META,
    )


def answer_without_a_bridge(clause: AnswerClause) -> Answer:
    """The answer about a building no confirmed place bridge ties to a memory place.

    It states the selection and that no retrieval ran, and claims no memory for the building.
    """
    return Answer(
        clauses=[
            clause,
            AnswerClause(
                text=(
                    "Unified place retrieval was not run because this admitted NYC "
                    "place has no confirmed memory-place bridge. No memory is claimed "
                    "to belong to the selected building."
                ),
                type=ClauseType.META,
            ),
        ]
    )


def answer_led_by(clause: AnswerClause, answer: Answer) -> Answer:
    """``answer`` led by the city selection's clause, keeping its first seven clauses."""
    return Answer(clauses=[clause, *answer.clauses[:7]])
