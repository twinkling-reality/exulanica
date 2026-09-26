"""The Companion names the model behind a person's decision, in the words the People panel uses.

In a world whose owner chose a model for someone, the minute that applies the model's choice records
the person's goal with the reason ``chosen_by_their_model`` and a ``decision_applied`` event naming
the model and its receipt. The Companion's line for that goal says the model picked it; it names the
model from that minute's decision event, read through the same withdrawal rule as every event it
cites, and only when exactly one applied decision event of that minute and person names one. The
name is the manifest's one rule (``Manifest.model_name``), which the People panel shows too. The
panel's words for why a model was or was not followed live in the words catalog with the rest.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.models.manifest import Role, load_manifest
from exulanica.selection.inhabitant_words import inhabitant_words_catalog
from exulanica.selection.society_question import (
    _APPLIED,
    _CHOSEN_BY_THEIR_MODEL,
    SocietyScene,
    _authorized_events,
    _AuthorizedOnce,
    _Builder,
    _deciding_models,
)
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_decision_contract import DECISION_REASONS
from exulanica.world.society_model_decisions import _DISPOSITIONS
from exulanica.world.society_planner import REASON_CODES

import test_society_person_decisions_postgres as pg

# -- the words and the name ---------------------------------------------------------------------


def test_the_catalog_has_words_for_exactly_the_reasons_a_decision_records():
    decision_words = inhabitant_words_catalog().tables["decision_reason"]
    # A positive control: reasons the host is known to record are found by the same reading.
    assert {"validated_choice", "model_timed_out", "place_taken_this_minute"} <= set(decision_words)
    assert set(decision_words) == set(DECISION_REASONS)


def test_the_codes_this_reads_are_the_ones_the_planner_and_the_minute_record():
    assert _CHOSEN_BY_THEIR_MODEL in REASON_CODES
    assert _APPLIED in _DISPOSITIONS


def test_a_model_is_named_by_its_description_up_to_the_first_comma():
    manifest = load_manifest()
    offered = manifest.offered_models(Role.SOCIETY_DECISION)
    assert offered, "the manifest offers no model for a person's decisions"
    for spec in offered:
        name = manifest.model_name(spec.model_id)
        assert name and "," not in name
        assert spec.description.startswith(name)
        assert spec.description == name or spec.description[len(name)] == ","


def test_a_description_with_no_comma_is_the_whole_name_and_an_undeclared_model_its_id():
    manifest = load_manifest()
    spec = manifest.offered_models(Role.SOCIETY_DECISION)[0]
    plain = dataclasses.replace(spec, description="A model with a one-part description")
    changed = dataclasses.replace(manifest, models={**manifest.models, spec.model_id: plain})
    assert changed.model_name(spec.model_id) == "A model with a one-part description"
    assert manifest.model_name("vendor/not-in-this-manifest") == "vendor/not-in-this-manifest"


# -- which decision event names the model --------------------------------------------------------

SUBJECT = str(uuid.uuid4())
OTHER = str(uuid.uuid4())
MODEL = "vendor/model-a"


def _decision(tick: int, subject: str, disposition: str, model: str | None = MODEL) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "tick": tick,
        "event_kind": "decision_applied",
        "subject_id": subject,
        "document": {
            "disposition": disposition,
            "outcome": f"decision_{disposition}",
            "model": None if model is None else {"provider": "vendor", "model_id": model},
        },
    }


def test_exactly_one_applied_decision_names_the_model():
    manifest = load_manifest()
    named = _deciding_models([_decision(7, SUBJECT, "applied")], manifest)
    assert named == {(7, SUBJECT): manifest.model_name(MODEL)}


def test_a_minute_with_no_applied_decision_names_no_model():
    named = _deciding_models(
        [_decision(7, SUBJECT, "superseded"), _decision(7, SUBJECT, "rejected")], load_manifest()
    )
    assert named == {}


def test_several_applied_decisions_for_one_person_and_minute_name_no_model():
    named = _deciding_models(
        [_decision(7, SUBJECT, "applied"), _decision(7, SUBJECT, "applied", "vendor/model-b")],
        load_manifest(),
    )
    assert named == {}


def test_an_applied_decision_that_names_no_model_names_none():
    assert _deciding_models([_decision(7, SUBJECT, "applied", None)], load_manifest()) == {}


def test_each_person_and_minute_is_read_on_its_own():
    manifest = load_manifest()
    named = _deciding_models(
        [
            _decision(7, SUBJECT, "applied"),
            _decision(7, OTHER, "applied"),
            _decision(7, OTHER, "applied"),
            _decision(8, SUBJECT, "superseded"),
        ],
        manifest,
    )
    assert named == {(7, SUBJECT): manifest.model_name(MODEL)}


# -- the line --------------------------------------------------------------------------------------


def _scene(deciding: dict[tuple[int, str], str]) -> SocietyScene:
    return SocietyScene(
        society_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        profile="exulanica-society/v2",
        tick=9,
        people={SUBJECT: {"id": SUBJECT, "display_name": "Ari Vale"}},
        usable_targets=frozenset(),
        events=(),
        explaining={},
        selected=None,
        deciding_models=deciding,
    )


def _goal(reason: str) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "tick": 7,
        "event_kind": "goal_selected",
        "subject_id": SUBJECT,
        "document": {"outcome": "goal_selected", "reason": reason, "goal": None},
    }


def test_the_line_of_a_goal_the_model_chose_names_the_model():
    catalog = inhabitant_words_catalog()
    item = _Builder(_scene({(7, SUBJECT): "Model A"}), catalog).event(_goal(_CHOSEN_BY_THEIR_MODEL))
    assert catalog.reason(_CHOSEN_BY_THEIR_MODEL) in item.line
    assert item.line.endswith(
        catalog.words("line", "chosen_model").format(line="", model="Model A").strip()
    )


def test_the_line_names_no_model_it_has_no_decision_for():
    catalog = inhabitant_words_catalog()
    item = _Builder(_scene({}), catalog).event(_goal(_CHOSEN_BY_THEIR_MODEL))
    assert "That model was" not in item.line


def test_a_goal_the_model_did_not_choose_names_no_model():
    catalog = inhabitant_words_catalog()
    item = _Builder(_scene({(7, SUBJECT): "Model A"}), catalog).event(_goal("restore_need"))
    assert "Model A" not in item.line


# -- the running world -----------------------------------------------------------------------------

saved_world = pg.saved_world
app = pg.app


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_minute_that_applied_a_model_s_choice_names_that_model_to_the_companion(app):
    world, client = app
    services = pg._services(client)
    manifest, model_id = pg._offered()
    snapshot, _ = pg._choosing(world, client, services, manifest, model_id, pg._Chooser())
    after = pg.stays._step(world, client, snapshot)
    scope, _, society = pg.routes(world)
    response = client.post(
        "/selection/ask",
        headers=pg.OWNER,
        params=scope,
        json={
            "question": "what happened?",
            "plan": {"intent": "society", "society": {"scope": "world", "aspect": "recent"}},
            "society_context": {
                "version_id": str(world["binding"].version_id),
                "inhabitant_id": None,
            },
        },
    )
    assert response.status_code == 200, response.text
    catalog = inhabitant_words_catalog()
    named = catalog.words("line", "chosen_model").format(
        line="", model=load_manifest().model_name(model_id)
    )
    chose = [
        view["line"]
        for view in response.json()["simulation"].values()
        if catalog.reason(_CHOSEN_BY_THEIR_MODEL) in view["line"]
        and view["tick"] == after["current_tick"]
    ]
    # A positive control: the applying minute has a line that says the model chose.
    assert chose
    assert all(line.endswith(named.strip()) for line in chose), chose
    # And the People panel is served the same name for the same model, wherever the read names one:
    # the models offered, each person's choice, each latest decision and each model's summary.
    read = client.get(society + "/models", headers=pg.OWNER, params=scope).json()
    chosen = [choice["model"] for choice in read["choices"] if choice["model"] is not None]
    decided = [*chosen, *read["latest"], *read["by_model"]]
    # A positive control: the read names the chosen model in each of those places.
    assert read["models"] and chosen and read["latest"] and read["by_model"]
    assert {ref["name"] for ref in decided} == {load_manifest().model_name(model_id)}
    named_refs = [*read["models"], *decided]
    assert all(ref["name"] == load_manifest().model_name(ref["model_id"]) for ref in named_refs)


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_decision_event_under_an_input_a_withdrawal_no_longer_authorizes_is_left_out(app):
    """The decision read is the event read's own withdrawal rule: refused input, no event."""
    world, client = app
    services = pg._services(client)
    manifest, model_id = pg._offered()
    snapshot, _ = pg._choosing(world, client, services, manifest, model_id, pg._Chooser())
    after = pg.stays._step(world, client, snapshot)
    scope, _, society = pg.routes(world)
    events = client.get(society + "/events", headers=pg.OWNER, params=scope).json()["events"]
    applied = [
        (event["tick"], event["subject_id"])
        for event in events
        if event["event_kind"] == "decision_applied"
        and event["document"]["disposition"] == "applied"
        and event["tick"] == after["current_tick"]
    ]
    assert applied, "no receipt applied, so there is nothing to withdraw"

    def withdrawn(document):
        raise UnavailableSocietyInput("the photograph behind this input was withdrawn")

    def read(authorize) -> list:
        from exulanica.world.society_repository import SocietyRepository

        once = _AuthorizedOnce(authorize)
        with services.database.session(world["workspace"]) as connection:
            repository = SocietyRepository(
                connection,
                world["workspace"],
                world_id=world["binding"].world_id,
                input_authorizer=lambda document: None,
            )
            current = repository.snapshot(world["binding"].version_id)
            return _authorized_events(
                connection,
                world["workspace"],
                world["binding"].world_id,
                current,
                repository,
                once,
                decisions_at=applied,
            )

    # A positive control: with the input authorized, the same read finds the decision events.
    found = read(lambda document: None)
    assert {(event["tick"], str(event["subject_id"])) for event in found} == set(applied)
    assert {event["event_kind"] for event in found} == {"decision_applied"}
    assert read(withdrawn) == []
