"""A town's society is byte for byte the society it was before people could live in site worlds.

People living in a world made from a world kind taught four modules every town's society runs
through about a routine overlay, a site's navigation profile, its record subjects and its place
dependency (``society_catalogs``, ``society_input_policy``, ``society_living`` and
``society_planner``). With no overlay nothing of that applies, so a town keeps its behaviour
exactly: the first input of its society, the routine binding that input records, and every
state and event of an hour played from it.

The digests below were produced by the tree without those changes (main 8a02c283 with KINDS
package 2, before package 2B), by the same steps as ``_hour`` below; this tree must reproduce them.
``EXULANICA_TOWN_UNCHANGED=print`` prints what this tree produces.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.routine import kind_routine
from exulanica.world.society import SocietyEvent
from exulanica.world.society_living import (
    LIVING_TOWN_PROFILE,
    advance_living_society,
    initial_living_society,
    input_routine,
    living_places,
    town_routine,
)
from exulanica.world.society_planner import validate_society_input

from living_town_support import SEED, town_input

CAFE = Path(__file__).parent / "fixtures" / "world-kinds" / "fixture-cafe.json"
SOCIETY = uuid.UUID("5a5a5a5a-0000-4000-8000-000000000005")
MINUTES = 60
#: Produced on the tree without package 2B (see the module's documentation).
INPUT_SHA256 = "386223fcfe96a3679839ecf6345128e3129832e20913bd5c95eaa64069b164e0"
BINDING = (
    b'{"catalog_versions":{"society-activity":1,"society-capacity":1,"society-need":1,'
    b'"society-policy":2,"society-shift":1,"society-use-class":2},'
    b'"sha256":"28e67bed00264f93d0791bec7eae39dba68cf66c94927142c0f071bafe2e1023"}'
)
HOUR_STATES_SHA256 = "69354106a857e09fc68723919abd88f0ec72e094fcb4902dd3e2d112bd70285a"
HOUR_EVENTS_SHA256 = "d93e232601047e81b71cb612a936e5d55a3f8e8efe7418b1bd97be67a39a7c15"


def _event(event: SocietyEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "tick": event.tick,
        "kind": event.kind,
        "subject_id": str(event.subject_id),
        "object_id": None if event.object_id is None else str(event.object_id),
        "document": event.document,
    }


def _hour(document: dict[str, Any]) -> tuple[str, str]:
    """The digests of every state and every event of an hour played from ``document``."""
    routine = input_routine(document)
    [place] = living_places([document], routine, {})
    state = initial_living_society(
        SOCIETY,
        SEED,
        place,
        routine,
        branch_id=document["version_id"],
        population=document["population"]["size"],
        profile=LIVING_TOWN_PROFILE,
    )
    states = hashlib.sha256(canonical_json(state))
    events = hashlib.sha256()
    for _ in range(MINUTES):
        state, produced = advance_living_society(state, SEED, [place], routine)
        states.update(canonical_json(state))
        for event in produced:
            events.update(canonical_json(_event(event)))
    return states.hexdigest(), events.hexdigest()


def test_a_town_s_input_binding_and_hour_are_the_bytes_they_were():
    document = town_input()
    validate_society_input(document)
    produced = {
        "input": hashlib.sha256(canonical_json(document)).hexdigest(),
        "binding": canonical_json(town_routine().binding()),
        "hour": _hour(document),
    }
    if os.environ.get("EXULANICA_TOWN_UNCHANGED") == "print":
        print(produced)
    assert "overlay" not in document["living"]["routine"]
    assert produced["input"] == INPUT_SHA256
    assert produced["binding"] == BINDING
    assert produced["hour"] == (HOUR_STATES_SHA256, HOUR_EVENTS_SHA256)


def test_the_control_an_overlay_is_a_different_binding_that_states_itself():
    # The positive control: the comparison above can tell a routine with an overlay from one
    # without, because an overlaid routine's binding states its overlay and its own digest.
    overlaid = kind_routine(read_kind(json.loads(CAFE.read_text(encoding="utf-8")))).binding()
    assert "overlay" in overlaid and canonical_json(overlaid) != BINDING
    assert overlaid["catalog_versions"] == town_routine().binding()["catalog_versions"]
