"""A living society's crossings are what they were before walking became a movement module.

The living society records a crossing when a walker enters a crossing edge. That step moved into the
walking module (``exulanica/movement/walking.py``), where a leg says whether it began at an edge's
near node, and the living society records the crossing from that. The Flatiron pin
(``tests/test_society_living_unchanged.py``) walks a place with no crossings, so it cannot see this
branch. The busier fixture tile has them: over 720 simulated minutes its walkers enter crossings 60
times. These digests were measured on ac5f64b6, the tree before walking moved, from its own code.
"""

from __future__ import annotations

import uuid

from exulanica.world.society import society_state_sha256
from exulanica.world.society_city_place import place_from_city_documents
from exulanica.world.society_living import (
    LivingPlace,
    advance_living_society,
    initial_living_society,
)
from exulanica.world.society_planner import ordered_events_document

from society_city_fixtures import busier_document, city_catalogs
from society_living_fixtures import routine

SEED = "5b" * 32
MINUTES = 720
#: Measured on ac5f64b6.
STATE_SHA256 = "bbf4e685dbc2cfa16ce1576a70b66f2afb836911271c520b86107d5f042bc13f"
EVENTS = (1551, "d28db6359e1e79ef1d98af85a93353883d0e4b6233923d44958cc59d4b6990b5")
CROSSINGS = 60


def test_a_busier_tile_s_walkers_enter_the_crossings_they_entered_before():
    model = routine()
    document = place_from_city_documents(
        place_id="fixture-tile",
        documents=[busier_document()],
        routine=model,
        catalogs=city_catalogs(),
    )
    place = LivingPlace(document, model)
    state = initial_living_society(uuid.UUID(int=9), SEED, place, model, branch_id="b")
    events = []
    for _ in range(MINUTES):
        state, produced = advance_living_society(state, SEED, [place], model)
        events.extend(produced)
    crossings = [crossing for event in events for crossing in event.document["crossings"]]
    assert len(crossings) == CROSSINGS
    assert society_state_sha256(state) == STATE_SHA256
    assert (len(events), society_state_sha256(ordered_events_document(tuple(events)))) == EVENTS
