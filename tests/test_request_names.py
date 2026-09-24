"""The Companion's one record of names for a request, with no database and no model.

:class:`~exulanica.selection.request_names.RequestNames` decides what the Companion's call sites
send: every name no right can release as its placeholder, a place's name as saved for the boundary
to decide, and one placeholder per entity for the whole request. The boundary's side of the same
record is held in ``tests/test_hosted_request_policy.py``; what leaves on each product path is held
at the transport in ``tests/test_companion_place_release.py``.
"""

from __future__ import annotations

import uuid

from exulanica.epistemics.saved_names import SavedName, redact_names
from exulanica.selection.request_names import RequestNames

PERSON = SavedName(uuid.uuid4(), "person", "Victoria Estrada")
STATION = SavedName(uuid.uuid4(), "place", "Victoria Station")
HOUSE = SavedName(uuid.uuid4(), "place", "Lantern House")
MUG = SavedName(uuid.uuid4(), "object", "Lantern House Mug")


def test_a_person_is_replaced_and_a_place_is_left_as_saved():
    names = RequestNames([PERSON, HOUSE])
    sent = names.sendable("Did victoria wave at lantern house?")
    assert sent == "Did [person A] wave at Lantern House?"
    assert dict(names.placeholders) == {
        PERSON.entity_id: "[person A]",
        HOUSE.entity_id: "[place A]",
    }


def test_a_place_is_read_before_a_shorter_name_inside_it():
    """Replacing the person first would send "[person A] Station" and lose the place."""
    names = RequestNames([PERSON, STATION])
    assert names.sendable("Meet at Victoria Station") == "Meet at Victoria Station"
    assert list(names.placeholders) == [STATION.entity_id]
    # Positive control: the person alone is still replaced.
    assert names.sendable("Victoria waited") == "[person A] waited"


def test_a_longer_name_of_another_class_takes_a_place_inside_it():
    names = RequestNames([HOUSE, MUG])
    assert names.sendable("the Lantern House Mug") == "the [object A]"
    assert HOUSE.entity_id not in names.placeholders


def test_one_placeholder_per_entity_across_the_request():
    names = RequestNames([PERSON, HOUSE])
    names.sendable("Where is Victoria?")
    names.sendable("A sign reads LANTERN HOUSE and VICTORIA ESTRADA")
    assert dict(names.placeholders) == {
        PERSON.entity_id: "[person A]",
        HOUSE.entity_id: "[place A]",
    }


def test_a_label_a_text_already_carries_is_never_handed_to_an_entity():
    names = RequestNames([PERSON])
    assert names.sendable("Is [person A] Victoria?") == "Is [person A] [person B]?"
    assert names.reference(PERSON.entity_id) == "[person B]"


def test_sending_a_sent_text_again_changes_nothing():
    names = RequestNames([PERSON, HOUSE])
    once = names.sendable("Victoria at Lantern House")
    assert names.sendable(once) == once


def test_a_place_another_saved_name_reads_as_stays_its_placeholder():
    """Words cannot say which of two entities they name, so neither is sent by name."""
    namesake = SavedName(uuid.uuid4(), "place", "lantern  house")
    names = RequestNames([HOUSE, namesake])
    sent = names.sendable("at Lantern House")
    (label,) = names.placeholders.values()
    assert sent == f"at {label}"
    assert names.reference(HOUSE.entity_id).startswith("[place ")


def test_a_place_referred_to_by_id_is_named_by_its_own_saved_name():
    names = RequestNames([PERSON, HOUSE])
    assert names.reference(HOUSE.entity_id) == "Lantern House"
    assert names.reference(PERSON.entity_id) == "[person A]"
    assert names.reference(uuid.uuid4()) is None
    assert dict(names.placeholders) == {
        HOUSE.entity_id: "[place A]",
        PERSON.entity_id: "[person A]",
    }


def test_labelled_reads_a_recorded_name_back_as_its_placeholder():
    names = RequestNames([PERSON, HOUSE])
    names.sendable("Victoria at Lantern House")
    assert names.labelled("lantern house sign") == "[place A] sign"
    # Only the record: a saved name the request never met is left as it is.
    other = RequestNames([HOUSE])
    assert other.labelled("lantern house sign") == "lantern house sign"


def test_the_record_is_the_one_redact_names_would_build():
    """The placeholders are the ones the product's recognition gives, in the same order."""
    names = RequestNames([PERSON, HOUSE, STATION])
    text = "Victoria Estrada met us at Victoria Station, then Lantern House"
    names.sendable(text)
    assert dict(names.placeholders) == dict(
        redact_names(text, [PERSON, HOUSE, STATION]).placeholders
    )
