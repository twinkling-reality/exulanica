"""The living society over a district is untouched by the purposeful society's routine.

The purposeful routine's catalog lives in the same directory as the living society's five, and the
directory is checked as a whole, so this pins what a living society is: its routine's digest, and
sixty simulated minutes over the Flatiron district from genesis, state and events, measured on the
tree before the purposeful routine left code (374dfc6a).
"""

from __future__ import annotations

from exulanica.world.society import society_state_sha256
from exulanica.world.society_catalogs import load_routine_model
from exulanica.world.society_living import (
    LivingPlace,
    advance_living_society,
    initial_living_society,
)
from exulanica.world.society_place import place_from_society_input
from exulanica.world.society_planner import ordered_events_document

from society_living_fixtures import GRID_SOCIETY, SEEDS, flatiron_input

#: Measured on 374dfc6a from its five catalog files.
ROUTINE_SHA256 = "5ed1a63d6589763693bec365d41f46b00de3a6ee8b9c25fa0cd35e2381f10931"
GENESIS_SHA256 = "803651da94da4a91b4445abbf9f6c1b937800191183d6bcc4db49e9f9f14c658"
MINUTE_60_SHA256 = "f8d0cccfd50f6da218f2aa9ceb590334fafe8a42ad3201ebbcb5335d39c4753c"
EVENTS = (2781, "9a1c5ffc145a24e4454d7224687e9596dd23ca4586db3db69476ae434db83be0")
MINUTES = 60


def test_a_living_society_over_a_district_is_what_it_was():
    model = load_routine_model()
    assert model.sha256 == ROUTINE_SHA256
    place = LivingPlace(place_from_society_input(flatiron_input(), model), model)
    state = initial_living_society(GRID_SOCIETY, SEEDS[0], place, model, branch_id="branch")
    assert society_state_sha256(state) == GENESIS_SHA256
    events = []
    for _ in range(MINUTES):
        state, produced = advance_living_society(state, SEEDS[0], [place], model)
        events.extend(produced)
    assert society_state_sha256(state) == MINUTE_60_SHA256
    assert (len(events), society_state_sha256(ordered_events_document(tuple(events)))) == EVENTS
