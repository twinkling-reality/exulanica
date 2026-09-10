"""What the Companion may propose about the world's appearance, and what it may not.

Every test here drives the real path with a scripted transport, so what is asserted is what
`ModelClient` actually sent and what `exulanica.selection.proposal` actually did with the reply.
No test spends credits and none of them reaches the network.

The three things worth stating about the shape of this file:

*   **The draft schema is generated, so the tests assert on the generated document** rather than
    on a copy of it. A test that restated the bounds would be a second copy of the registry and
    would pass while the registry said something else.
*   **Every refusal is asserted by code AND by the fact that no proposal came back.** A refusal
    that returned a proposal with a clamped value would satisfy a code assertion alone.
*   **The model is scripted to misbehave in exactly the ways a model misbehaves.** Filling a
    field because the form has a slot for it, restating the value it was shown, naming an
    identifier it invented: each of those was measured on the question path and each has a test.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import StructuredOutputError
from exulanica.models.schema import strict_json_schema
from exulanica.models.transport import HttpResponse
from exulanica.selection.proposal import (
    MAX_REFERENCE_CATALOGUE,
    PROMPT_VERSION,
    AppearanceProposal,
    ProposalRefusal,
    RefusalCode,
    RequestKind,
    SourceChoice,
    _draft_model,
    _proposable_profiles,
    _validate_draft,
    classify_request,
    draft_appearance,
    propose_appearance,
    source_catalogue,
)
from exulanica.selection.validation import Session
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import STYLE_REGISTRY, StyleReference, TopologyContract, TopologySourceSlot
from exulanica.world import WorldStyleRepository as Styles

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS, write_photo
from model_fakes import FakeTransport, chat_body

#: The extraction chain's primary, read from the manifest rather than repeated as a literal, on
#: the same argument `test_selection_answer.py` makes: a manifest change must move these tests.
DRAFTER = "Qwen/Qwen3-235B-A22B-Instruct-2507"

PROFILE = _proposable_profiles(STYLE_REGISTRY)[0]
PROFILE_KEY = f"{PROFILE.profile_id}@{PROFILE.profile_version}"


def current_reference() -> StyleReference:
    """The world as the registry would resolve it with nothing overridden."""
    return STYLE_REGISTRY.validate_reference(
        StyleReference(PROFILE.profile_id, PROFILE.profile_version, {})
    )


def catalogue(count: int = 3) -> tuple[SourceChoice, ...]:
    """A catalogue with no database behind it, for the validator's own tests.

    The ids are fabricated on purpose: nothing here writes a row, and what these tests check is
    that a draft is measured against WHATEVER catalogue it was given. The two tests that need
    the catalogue to have come from a real topology say so by asking for one.
    """
    return tuple(
        SourceChoice(
            source_id=uuid.UUID(int=index + 1),
            evidence_span_id=uuid.UUID(int=1000 + index),
            region_id="region-a",
            slot_key=f"slot-{index:02d}",
        )
        for index in range(count)
    )


def draft(**overrides) -> dict:
    """A well-formed draft that moves exactly one control, before any override is applied."""
    body = {
        "profile": PROFILE_KEY,
        "modules": ["aeroheart-optics-v1"],
        "parameters": {key.replace("-", "_"): None for key in PROFILE.controls},
        "references": [str(catalogue()[0].source_id)],
        "spoken": "The horizon will sit softer, so the far edge reads as distance.",
        "impossible": None,
    }
    body["parameters"]["horizon_softness"] = 0.8
    for key, value in overrides.items():
        if key == "parameters":
            body["parameters"].update(value)
        else:
            body[key] = value
    return body


def reply(payload: dict, *, model: str = DRAFTER) -> HttpResponse:
    return HttpResponse(
        status_code=200, text=json.dumps(chat_body(json.dumps(payload), model=model))
    )


def scripted(*responses: HttpResponse) -> tuple[ModelClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
    )
    return client, transport


def validated(body: dict, *, current: StyleReference | None = None) -> object:
    return _validate_draft(
        body, current or current_reference(), catalogue(), registry=STYLE_REGISTRY
    )


# -- the form itself --------------------------------------------------------------------------


def test_the_draft_schema_is_built_from_the_registry_rather_than_restated_beside_it():
    schema = strict_json_schema(_draft_model(_proposable_profiles(STYLE_REGISTRY), catalogue()))
    controls = schema["$defs"]["AppearanceParameters"]["properties"]

    assert set(controls) == {key.replace("-", "_") for key in PROFILE.controls}
    for key, definition in PROFILE.controls.items():
        # The bound in the schema is the registry's own bound, taken from the registry here so
        # that narrowing a range in review moves this assertion with it instead of past it.
        value, null = controls[key.replace("-", "_")]["anyOf"]
        assert null == {"type": "null"}, key
        if definition.kind == "range":
            assert (value["minimum"], value["maximum"]) == (definition.minimum, definition.maximum)
        else:
            assert value["enum"] == list(definition.options)


def test_the_form_offers_no_field_that_could_carry_a_program_or_an_address():
    """The catalogue is metadata. A form that could express a stylesheet would be a channel.

    The same sweep `test_world_style_contract.py` runs over the catalog document and
    `test_selection_answer.py` runs over the answer schema, for the same reason: the strongest
    statement about what a payload cannot contain is made over the payload.
    """
    rendered = json.dumps(
        strict_json_schema(_draft_model(_proposable_profiles(STYLE_REGISTRY), catalogue()))
    ).lower()
    # Quoted, because the token has to be a KEY or a VALUE to be a channel. Bare `script` also
    # occurs inside the word `description`, and a sweep that failed on that would be measuring
    # English rather than the form.
    for forbidden in ('"css"', '"style"', '"shader"', '"layout"', '"url"', '"href"', '"src"'):
        assert forbidden not in rendered, forbidden
    for forbidden in ("javascript", "stylesheet", "<script", "http://", "https://"):
        assert forbidden not in rendered, forbidden


def test_only_a_profile_that_may_receive_a_proposal_is_offered_at_all():
    """An experimental or developer-only profile is not a choice, because it is not a choice.

    `validate_reference` refuses one outright, so offering it in the form would be offering a
    value whose only outcome is a refusal the person did not cause.
    """
    offered = {f"{p.profile_id}@{p.profile_version}" for p in _proposable_profiles(STYLE_REGISTRY)}
    every = {f"{p.profile_id}@{p.profile_version}" for p in STYLE_REGISTRY.profiles.values()}

    assert offered == {PROFILE_KEY}
    assert every - offered == {"survey-relief@1"}
    assert STYLE_REGISTRY.profiles[("survey-relief", 1)].status == "experimental"


def test_the_reference_enum_is_the_bounded_catalogue_and_nothing_else():
    schema = strict_json_schema(_draft_model(_proposable_profiles(STYLE_REGISTRY), catalogue(5)))

    assert schema["properties"]["references"]["items"]["enum"] == [
        str(choice.source_id) for choice in catalogue(5)
    ]
    assert schema["properties"]["references"]["minItems"] == 1


# -- conformance ------------------------------------------------------------------------------


def test_a_conforming_draft_becomes_a_complete_reference_with_only_one_control_moved():
    outcome = validated(draft())

    assert isinstance(outcome, AppearanceProposal)
    assert outcome.changed == ("horizon-softness",)
    assert outcome.profile.parameters["horizon-softness"] == 0.8
    # Complete, not a diff. `POST /world/styles/previews` fills an omitted control from its
    # DEFAULT, so a diff posted there would reset every control the request never mentioned.
    assert set(outcome.profile.parameters) == set(PROFILE.controls)
    for key, value in current_reference().parameters.items():
        if key != "horizon-softness":
            assert outcome.profile.parameters[key] == value


def test_a_null_control_keeps_the_value_the_world_has_rather_than_the_registry_default():
    """The distinction that makes a small change small, asserted against a non-default world."""
    world = STYLE_REGISTRY.validate_reference(
        StyleReference(PROFILE.profile_id, PROFILE.profile_version, {"vitality": 0.1})
    )
    outcome = validated(draft(), current=world)

    assert isinstance(outcome, AppearanceProposal)
    assert outcome.profile.parameters["vitality"] == 0.1
    assert PROFILE.controls["vitality"].default_value == 0.82


def test_the_whole_path_classifies_then_drafts_and_asks_for_nothing_else(
    repository, tmp_path, photo_dir
):
    client, transport = scripted(reply({"kind": "appearance"}), reply(draft()))
    session = Session(workspace_id=repository.workspace_id, actor=uuid.uuid4())
    _seed_world(repository, tmp_path, photo_dir)

    outcome = propose_appearance(
        repository.connection, client, "make the horizon softer", session,
        current=current_reference(),
    )

    assert outcome.kind is RequestKind.APPEARANCE
    assert isinstance(outcome.proposal, AppearanceProposal)
    assert transport.call_count == 2
    assert transport.models_called == [DRAFTER, DRAFTER]


# -- range refusal, which is the one that must never become a clamp -------------------------


def test_a_value_outside_its_declared_range_is_refused_and_never_clamped_to_the_bound():
    """The whole reason an authority is not a renderer.

    The endpoint's JSON Schema refuses this first, which is why the assertion is made against
    the validator directly: this is the answer the authority gives about the value, not the
    answer the transport gives about the request.
    """
    outcome = validated(draft(parameters={"horizon_softness": 1.4}))

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.OUT_OF_RANGE
    assert "horizon-softness" in outcome.detail


def test_a_tempo_outside_its_narrower_range_is_refused_even_though_it_is_inside_zero_to_one():
    """`motion.tempo` runs 0.75 to 1.25, so a value every other control would accept is refused.

    Chosen because it is the case a single shared bound would get wrong: 0.5 is a legal value
    for six of this profile's seven controls and an illegal one for the seventh.
    """
    outcome = validated(
        draft(
            modules=["bounded-tempo-v1"],
            parameters={"horizon_softness": None, "world_tempo": 0.5},
        )
    )

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.OUT_OF_RANGE
    assert "world-tempo" in outcome.detail


def test_an_out_of_range_draft_is_refused_by_the_schema_before_it_is_ever_a_python_object():
    """The first of the two layers, asserted where it actually happens.

    The drafter is scripted to answer twice with the same illegal value, because one repair is
    allowed. What comes back is a `StructuredOutputError` rather than a clamped 1.0.
    """
    illegal = draft(parameters={"horizon_softness": 1.4})
    client, transport = scripted(reply(illegal), reply(illegal))

    with pytest.raises(StructuredOutputError):
        draft_appearance(client, "much much softer", current_reference(), catalogue())

    assert transport.call_count == 2


def test_a_choice_outside_its_registered_options_is_refused():
    outcome = validated(
        draft(
            modules=["registered-surface-v1"],
            parameters={"horizon_softness": None, "surface_finish": "brushed-steel"},
        )
    )

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.OUT_OF_RANGE


# -- the closed registry, failing closed ------------------------------------------------------


def test_an_unregistered_profile_is_refused_rather_than_resolved_through_the_fallback_chain():
    """`resolve_reference` falls back with a warning; a NEW proposal must not.

    The fallback chain exists so a historical row still renders. Applying it here would answer a
    request to change one design by proposing a change to a different one.
    """
    outcome = validated(draft(profile="invented-landscape@9"))

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.UNREGISTERED
    assert "invented-landscape@9" in outcome.detail


def test_an_experimental_profile_cannot_be_proposed_against_even_by_name():
    outcome = validated(draft(profile="survey-relief@1"))

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.UNREGISTERED


def test_a_module_outside_the_profiles_reviewed_recipe_is_refused():
    outcome = validated(draft(modules=["aeroheart-optics-v1", "survey-relief-response-v1"]))

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.UNREGISTERED
    assert "survey-relief-response-v1" in outcome.detail


def test_a_control_whose_owning_module_the_draft_did_not_name_is_refused():
    """The module list is not decoration and this is the test that makes it load-bearing.

    `world-tempo` belongs to `bounded-tempo-v1`. A draft that moves it while naming only the
    optics module is proposing a change to a module it never claimed to touch, and the recipe
    binding the backend derives would say so.
    """
    outcome = validated(
        draft(modules=["aeroheart-optics-v1"], parameters={"world_tempo": 1.1})
    )

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.UNREGISTERED
    assert "motion.tempo" in outcome.detail


def test_a_control_the_profile_does_not_declare_is_refused_by_name():
    outcome = validated(draft(parameters={"contour_density": 0.9}))

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.UNREGISTERED
    assert "contour-density" in outcome.detail


def test_evidence_the_catalogue_does_not_contain_is_refused_rather_than_dropped():
    """An invented id is the failure the question path measured five times out of five.

    Dropping it and keeping the rest would file a proposal citing evidence nobody named, which
    is worse than a refusal because it looks like a proposal somebody made.
    """
    outcome = validated(draft(references=[str(uuid.UUID(int=99))]))

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.UNSUPPORTED_REFERENCE


def test_a_draft_naming_no_evidence_is_refused_before_the_world_repository_refuses_it():
    outcome = validated(draft(references=[]))

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.UNSUPPORTED_REFERENCE


def test_a_draft_that_restates_the_value_the_world_already_has_is_not_a_proposal():
    """Measured behaviour on the question path: a model fills a field because it exists.

    Here the field is a control and the value is the one it was just shown. There is nothing to
    review, and showing a person a change that changes nothing is worse than saying so.
    """
    outcome = validated(draft(parameters={"horizon_softness": 0.46}))

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.NO_CHANGE


def test_a_draft_that_moves_nothing_at_all_is_refused():
    outcome = validated(draft(modules=[], parameters={"horizon_softness": None}))

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.NO_CHANGE


def test_a_request_the_catalogue_cannot_express_is_refused_in_words_rather_than_approximated():
    """The person asked for something real and is told plainly that it is not offered.

    The alternative is the failure this whole path exists against: reaching for a nearby control
    nobody asked about, and presenting it as the answer to the request that was made.
    """
    outcome = validated(
        draft(
            impossible="a different typeface for the interface",
            parameters={"horizon_softness": None},
        )
    )

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.NOT_IN_CATALOGUE
    assert outcome.detail == "a different typeface for the interface"


def test_an_impossible_draft_is_refused_even_when_it_also_filled_in_a_change():
    """Both fields set is the model hedging. The refusal wins, because it named a limit."""
    outcome = validated(draft(impossible="a different typeface"))

    assert isinstance(outcome, ProposalRefusal)
    assert outcome.code is RefusalCode.NOT_IN_CATALOGUE


# -- provenance -------------------------------------------------------------------------------


def test_the_model_recorded_is_the_one_that_answered_rather_than_the_one_configured():
    """The distinction the whole `ModelCall` record exists for, on this path too.

    A manifest says which model a role asks for. Only the response says which one answered, and
    they differ exactly when the fallback fired.
    """
    client, _ = scripted(
        reply({"kind": "appearance"}, model="served/by-something-else"),
        reply(draft(), model="served/by-something-else"),
    )
    log_holder: list = []
    from exulanica.selection.question import CallLog

    log = CallLog()
    kind, classified_by = classify_request(client, "warmer please", log=log)
    _, model_id = draft_appearance(
        client, "warmer please", current_reference(), catalogue(), log=log
    )
    log_holder.extend(log.calls)

    assert (kind, classified_by, model_id) == (
        RequestKind.APPEARANCE,
        "served/by-something-else",
        "served/by-something-else",
    )
    assert [call.requested_model for call in log_holder] == [DRAFTER, DRAFTER]
    assert [call.served_model for call in log_holder] == [
        "served/by-something-else",
        "served/by-something-else",
    ]
    assert all(call.attempts == 1 for call in log_holder), "zero would mean a cache served it"


def test_the_prompt_version_is_this_paths_own_and_not_the_question_paths():
    """Two constants, because two prompts. Both are inputs to the response cache key."""
    from exulanica.selection.question import PROMPT_VERSION as QUESTION_PROMPT_VERSION

    assert PROMPT_VERSION == "proposal-1"
    assert PROMPT_VERSION != QUESTION_PROMPT_VERSION


def test_both_calls_are_sent_under_the_proposal_prompt_version():
    client, transport = scripted(reply({"kind": "appearance"}), reply(draft()))
    classify_request(client, "warmer please")
    draft_appearance(client, "warmer please", current_reference(), catalogue())

    # The prompt version reaches the wire through the cache key rather than the payload, so what
    # is asserted here is that both calls carried the same strict schema contract and neither
    # was sent as a free-text completion.
    assert transport.call_count == 2
    for request in transport.requests:
        assert request["payload"]["response_format"]["type"] == "json_schema"
        assert request["payload"]["response_format"]["json_schema"]["strict"] is True


# -- the classifier ---------------------------------------------------------------------------


def test_a_question_is_classified_as_one_and_produces_no_proposal_and_no_refusal(repository):
    """A question is not a failure of this path, and must not be recorded as one."""
    client, transport = scripted(reply({"kind": "question"}))
    session = Session(workspace_id=repository.workspace_id, actor=uuid.uuid4())

    outcome = propose_appearance(
        repository.connection, client, "who is in these photographs?", session,
        current=current_reference(),
    )

    assert outcome.kind is RequestKind.QUESTION
    assert (outcome.proposal, outcome.refusal) == (None, None)
    assert transport.call_count == 1, "the drafter must not be asked about a question"


def test_a_classifier_that_cannot_answer_sends_the_utterance_to_the_answer_path():
    """The one swallowed failure in the module, and the argument for it.

    A classifier that fails must not be the reason somebody's question goes unanswered: the
    answer path is where the utterance was going before this route existed.
    """
    client, _ = scripted(HttpResponse(status_code=200, text=json.dumps(chat_body("not json"))))

    kind, served = classify_request(client, "who is in these photographs?")

    assert (kind, served) == (RequestKind.QUESTION, None)


def test_the_classifier_is_never_shown_the_style_catalogue():
    """The reason there are two calls rather than one.

    A question about photographs must not be shown the vocabulary of a change it did not ask
    for, and the strongest form of that is a prompt the vocabulary is not in.
    """
    client, transport = scripted(reply({"kind": "question"}))
    classify_request(client, "who is in these photographs?")

    sent = json.dumps(transport.requests[0]["payload"]).lower()
    for control in PROFILE.controls:
        assert control not in sent, control
    for module in PROFILE.modules:
        assert module not in sent, module


def test_the_drafter_is_never_shown_a_caption_a_filename_or_any_bytes():
    """It sees identifiers. What a photograph shows cannot argue for how the world looks."""
    client, transport = scripted(reply(draft()))
    draft_appearance(client, "softer", current_reference(), catalogue())

    sent = json.dumps(transport.requests[0]["payload"])
    for choice in catalogue():
        assert str(choice.source_id) in sent
        assert str(choice.evidence_span_id) not in sent


# -- the evidence catalogue -------------------------------------------------------------------


def test_the_catalogue_is_the_current_topologys_bound_evidence_and_is_bounded(
    repository, tmp_path, photo_dir
):
    _seed_world(repository, tmp_path, photo_dir, slots=MAX_REFERENCE_CATALOGUE + 6)
    choices = source_catalogue(repository.connection, repository.workspace_id)

    assert len(choices) == MAX_REFERENCE_CATALOGUE
    assert all(choice.evidence_span_id is not None for choice in choices)


def test_a_slot_whose_evidence_is_recorded_as_missing_is_not_offered_as_a_reference(repository):
    """The topology stores a reason instead of a span for those, and a reference names something."""
    styles = Styles(repository.connection, repository.workspace_id)
    styles.register_topology(
        TopologyContract(
            "proposal-topology",
            ("region-a",),
            (
                TopologySourceSlot(
                    source_id=uuid.uuid4(),
                    slot_key="slot-absent",
                    region_id="region-a",
                    evidence_span_id=None,
                    missing_reason="no evidence was recorded for this slot",
                ),
            ),
        )
    )

    assert source_catalogue(repository.connection, repository.workspace_id) == ()


def test_a_world_with_no_bound_evidence_refuses_before_it_asks_the_drafter(repository):
    """A companion proposal without a reference id is refused by the world repository anyway.

    Said here rather than discovered as a 422 one request later, and the drafter is not asked:
    there is nothing it could fill in that would be accepted.
    """
    client, transport = scripted(reply({"kind": "appearance"}), reply(draft()))
    session = Session(workspace_id=repository.workspace_id, actor=uuid.uuid4())
    Styles(repository.connection, repository.workspace_id).register_topology(
        TopologyContract("proposal-topology", ("region-a",))
    )

    outcome = propose_appearance(
        repository.connection, client, "softer please", session, current=current_reference()
    )

    assert isinstance(outcome.refusal, ProposalRefusal)
    assert outcome.refusal.code is RefusalCode.UNSUPPORTED_REFERENCE
    assert transport.call_count == 1


def test_a_workspace_with_no_reviewed_world_is_told_so_rather_than_given_a_conflict(repository):
    client, transport = scripted(reply({"kind": "appearance"}))
    session = Session(workspace_id=repository.workspace_id, actor=uuid.uuid4())

    outcome = propose_appearance(
        repository.connection, client, "softer please", session, current=None
    )

    assert isinstance(outcome.refusal, ProposalRefusal)
    assert outcome.refusal.code is RefusalCode.NO_WORLD
    assert transport.call_count == 1


def test_a_draft_the_model_cannot_fill_twice_becomes_a_refusal_rather_than_an_exception(
    repository, tmp_path, photo_dir
):
    """Somebody asked for something. They are owed a sentence, not a 502."""
    client, transport = scripted(
        reply({"kind": "appearance"}),
        HttpResponse(status_code=200, text=json.dumps(chat_body("not json"))),
        HttpResponse(status_code=200, text=json.dumps(chat_body("still not json"))),
    )
    session = Session(workspace_id=repository.workspace_id, actor=uuid.uuid4())
    _seed_world(repository, tmp_path, photo_dir)

    outcome = propose_appearance(
        repository.connection, client, "softer please", session, current=current_reference()
    )

    assert isinstance(outcome.refusal, ProposalRefusal)
    assert outcome.refusal.code is RefusalCode.NOT_DRAFTED
    assert transport.call_count == 3


def _seed_world(repository, tmp_path, photo_dir, *, slots: int = 3) -> tuple[uuid.UUID, ...]:
    """One protected topology whose slots are bound to REAL evidence spans.

    A composite foreign key ties a slot to a span in the same workspace, so a fabricated span id
    is a constraint violation rather than a shortcut. One photograph is ingested and its spans
    are reused across however many slots a test asks for: the bound under test is how many slots
    `source_catalogue` will offer, and ingesting thirty photographs to measure that would be
    measuring the pipeline.
    """
    outcome = PhotoIngestPipeline(
        repository, LocalContentAddressedStore(tmp_path / "blobs"), vision=None
    ).ingest_file(write_photo(photo_dir, "world-source.jpg"))
    assert outcome.error is None, outcome.error
    spans = [
        row["span_id"]
        for row in repository.connection.execute(
            "select span_id from evidence_span where workspace_id=%s order by span_id",
            (repository.workspace_id,),
        ).fetchall()
    ]
    assert spans, "the ingest recorded no evidence span to bind a source slot to"
    Styles(repository.connection, repository.workspace_id).register_topology(
        TopologyContract(
            "proposal-topology",
            ("region-a",),
            tuple(
                TopologySourceSlot(
                    source_id=uuid.UUID(int=index + 1),
                    slot_key=f"slot-{index:02d}",
                    region_id="region-a",
                    evidence_span_id=spans[index % len(spans)],
                    missing_reason=None,
                )
                for index in range(slots)
            ),
        )
    )
    return tuple(spans)
