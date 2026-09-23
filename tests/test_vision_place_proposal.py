"""A proposed place is written only as the place proposal policy decides.

The vision role proposes a place; ``exulanica.ingest.place_proposal`` decides, in code, whether it
is written and under which label. The label keeps only words the observation transcribed from a
sign, spelled as the transcription spells them, and the proposal is refused unless a separate
call, the probe's completeness question, judged that same sign whole. Every refusal is a named
outcome of a versioned policy, stored beside the model's verbatim reply.

These tests drive the real vision model over the real client over a scripted transport, and the
real ingest stage over the real spine, so what they assert is what production does with the
replies they script.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.ingest import place_proposal
from exulanica.ingest import vision as vision_module
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.place_proposal import (
    JUDGED_SIGN_DOES_NOT_CARRY_THE_NAME,
    NO_SIGN_SEEN,
    NO_WORD_READ_FROM_A_SIGN,
    NOTHING_PROPOSED,
    OUTCOMES,
    PLACE_PROPOSAL_POLICY,
    SIGN_CHECK_FAILED,
    SIGN_JUDGE_NOT_ADMITTED,
    SIGN_PARTLY_HIDDEN,
    SIGN_QUESTION,
    SIGN_SCHEMA,
    SIGN_SYSTEM,
    UNKNOWN_COMPLETENESS_ANSWER,
    WRITTEN,
    AdmittedJudge,
    SignJudgement,
    decide,
    read_label,
)
from exulanica.ingest.stages import vision_stage_params
from exulanica.models.manifest import Role, load_manifest
from exulanica.store.local import LocalContentAddressedStore

from conftest import ingest_observed, write_photo
from model_fakes import FakeTransport, model_not_found
from test_vision_contract import VALID, _model, _ok

_ROOT = Path(__file__).resolve().parents[1]
_PROBE_PREREGISTRATION = (
    _ROOT / "docs/evaluation/2026-09-22-sign-completeness-probe-preregistration.json"
)

PRIMARY = load_manifest()[Role.VISION].primary.model_id
FALLBACK = load_manifest()[Role.VISION].fallback.model_id


def _proposing(label: str, *signs: str, basis: str = "signage") -> dict[str, Any]:
    """An observation that transcribed ``signs`` as signage and proposed ``label``."""
    return {
        **copy.deepcopy(VALID),
        "legible_text": [
            {"text": text, "is_signage": True, "confidence": "high", "box": None} for text in signs
        ],
        "proposed_place": {
            "label": label,
            "basis": basis,
            "supporting_evidence": f"A sign reads '{' '.join(signs)}'.",
            "confidence": "medium",
        },
    }


def _answer(completeness: str, readable: str, *, present: bool = True) -> str:
    return json.dumps(
        {"sign_present": present, "completeness": completeness, "readable_text": readable}
    )


def _observe(responses):
    transport = FakeTransport(responses)
    result = _model(transport).observe(image_bytes=b"\x89PNG", media_type="image/png")
    return result, transport


# -- the label rule ---------------------------------------------------------------------


def test_a_word_no_sign_carries_is_dropped_and_the_label_is_spelled_as_transcribed():
    """The held-out failure of the previous design: a descriptive word written into the label."""
    reading = read_label("Ashcombe (partial)", ["ASHCOMBE TE"])
    assert reading.label == "ASHCOMBE", "the transcription's spelling, never the folded form"
    assert reading.dropped == ("partial",)
    assert reading.kept == ("ashcombe",)


def test_the_label_is_the_transcriptions_own_span_with_its_punctuation_and_spacing():
    reading = read_label("St Marys  church", ["OPEN DAILY", "ST. MARY'S  CHURCH"])
    assert reading.label == "ST. MARY'S  CHURCH"
    assert reading.dropped == ()


def test_words_read_from_two_transcriptions_are_joined_as_each_spells_them():
    """A sign on two lines is often transcribed as two entries."""
    assert read_label("Lantern House", ["LANTERN", "House"]).label == "LANTERN House"


def test_a_label_with_no_word_read_from_a_sign_keeps_nothing():
    """Landmarks, world knowledge and a fallback's generic scene labels all end here."""
    assert read_label("Outdoor urban area", []).label is None
    assert read_label("Outdoor urban area", ["SYNTHETIC TEST IMAGE"]).label is None


# -- the decision -----------------------------------------------------------------------

_WHOLE = read_label("Lantern House", ["LANTERN HOUSE"])

#: One case per outcome: (reading, judgement, expected outcome, expected label).
_CASES = {
    "nothing proposed": (None, None, NOTHING_PROPOSED, None),
    "no word from a sign": (
        read_label("Somewhere", ["LANTERN"]),
        None,
        NO_WORD_READ_FROM_A_SIGN,
        None,
    ),
    "check failed": (
        _WHOLE,
        SignJudgement(None, None, "TransportError: down"),
        SIGN_CHECK_FAILED,
        None,
    ),
    "check never asked": (_WHOLE, None, SIGN_CHECK_FAILED, None),
    "judged by the fallback": (
        _WHOLE,
        SignJudgement(
            {"sign_present": True, "completeness": "whole", "readable_text": "LANTERN HOUSE"},
            FALLBACK,
        ),
        SIGN_JUDGE_NOT_ADMITTED,
        None,
    ),
    "no sign seen": (
        _WHOLE,
        SignJudgement(
            {"sign_present": False, "completeness": "no_sign", "readable_text": ""}, PRIMARY
        ),
        NO_SIGN_SEEN,
        None,
    ),
    "present contradicts whole": (
        _WHOLE,
        SignJudgement(
            {"sign_present": False, "completeness": "whole", "readable_text": "LANTERN HOUSE"},
            PRIMARY,
        ),
        NO_SIGN_SEEN,
        None,
    ),
    "partly hidden": (
        _WHOLE,
        SignJudgement(
            {"sign_present": True, "completeness": "partly_hidden", "readable_text": "LANTERN"},
            PRIMARY,
        ),
        SIGN_PARTLY_HIDDEN,
        None,
    ),
    "unknown answer": (
        _WHOLE,
        SignJudgement(
            {"sign_present": True, "completeness": "mostly", "readable_text": "LANTERN HOUSE"},
            PRIMARY,
        ),
        UNKNOWN_COMPLETENESS_ANSWER,
        None,
    ),
    "another sign judged": (
        _WHOLE,
        SignJudgement(
            {"sign_present": True, "completeness": "whole", "readable_text": "SUMMER SALE"}, PRIMARY
        ),
        JUDGED_SIGN_DOES_NOT_CARRY_THE_NAME,
        None,
    ),
    "written": (
        _WHOLE,
        SignJudgement(
            {"sign_present": True, "completeness": "whole", "readable_text": "Lantern House"},
            PRIMARY,
        ),
        WRITTEN,
        "LANTERN HOUSE",
    ),
}


@pytest.mark.parametrize("case", sorted(_CASES))
def test_each_case_reaches_its_named_outcome(case):
    reading, judgement, expected, label = _CASES[case]
    decision = decide(reading, judgement)
    assert decision.outcome is expected
    assert decision.label == label
    assert decision.writes is (expected is WRITTEN)


def test_every_outcome_the_policy_names_is_reached_by_a_case_above():
    """A new outcome added to the policy without a case here fails, rather than going untested."""
    reached = {case[2] for case in _CASES.values()}
    assert reached == set(OUTCOMES)
    assert [o for o in OUTCOMES if o.writes] == [WRITTEN], "exactly one outcome writes"


def test_a_model_is_admitted_as_a_judge_by_data_and_the_digest_says_so():
    """A later measurement admits the fallback by adding it to the policy, not by editing code."""
    judged = _CASES["judged by the fallback"][1]
    admitting = dataclasses.replace(
        PLACE_PROPOSAL_POLICY,
        admitted_judges=(
            *PLACE_PROPOSAL_POLICY.admitted_judges,
            AdmittedJudge(model_id=FALLBACK, evidence="a later measurement of its sign judgement"),
        ),
    )
    assert decide(_WHOLE, judged).outcome is SIGN_JUDGE_NOT_ADMITTED
    assert decide(_WHOLE, judged, admitting).outcome is WRITTEN
    assert admitting.digest() != PLACE_PROPOSAL_POLICY.digest()


def test_the_completeness_table_names_exactly_the_answers_the_schema_allows():
    enum = SIGN_SCHEMA["properties"]["completeness"]["enum"]
    assert set(PLACE_PROPOSAL_POLICY.completeness) == set(enum)


def test_the_sign_question_is_word_for_word_the_one_the_probe_measured():
    """The probe's measurement applies only to the question it asked."""
    probe = json.loads(_PROBE_PREREGISTRATION.read_bytes())["record"]["probe"]
    assert probe["system"] == SIGN_SYSTEM
    assert probe["question"] == SIGN_QUESTION
    assert probe["schema"] == SIGN_SCHEMA


def test_every_admitted_judge_names_a_record_that_measured_it():
    for judge in PLACE_PROPOSAL_POLICY.admitted_judges:
        record = json.loads((_ROOT / judge.evidence).read_bytes())["record"]
        assert record["can_tell"] is True, judge
    probe = json.loads(_PROBE_PREREGISTRATION.read_bytes())["record"]["model"]
    assert [judge.model_id for judge in PLACE_PROPOSAL_POLICY.admitted_judges] == [
        probe["model_id"]
    ]


# -- the vision model -------------------------------------------------------------------


def test_no_proposal_means_one_call_and_nothing_written():
    result, transport = _observe([_ok(json.dumps(VALID))])
    assert transport.call_count == 1
    assert result.calls == 1
    assert result.observation.proposed_place is None
    assert result.place_check["outcome"] == NOTHING_PROPOSED.code


def test_a_label_no_sign_supports_is_refused_without_asking_the_sign_question():
    landmark = _proposing("Old Harbour Lighthouse", basis="landmark")
    result, transport = _observe([_ok(json.dumps(landmark))])
    assert transport.call_count == 1, "the sign question is asked only when a word survives"
    assert result.observation.proposed_place is None
    assert result.payload["proposed_place"]["label"] == "Old Harbour Lighthouse"
    assert result.place_check["outcome"] == NO_WORD_READ_FROM_A_SIGN.code


def test_a_whole_sign_writes_the_transcribed_label_and_counts_both_calls():
    result, transport = _observe(
        [
            _ok(
                json.dumps(_proposing("Lantern House", "LANTERN HOUSE")),
                prompt_tokens=700,
                completion_tokens=300,
            ),
            _ok(_answer("whole", "LANTERN HOUSE"), prompt_tokens=400, completion_tokens=40),
        ]
    )
    assert transport.call_count == 2
    second = transport.requests[1]["payload"]["messages"]
    assert second[0]["content"] == SIGN_SYSTEM
    assert second[1]["content"][0]["text"] == SIGN_QUESTION
    assert result.observation.proposed_place.label == "LANTERN HOUSE"
    assert result.payload["proposed_place"]["label"] == "Lantern House", "the reply stays verbatim"
    assert result.calls == 2
    assert result.cost["input_tokens"] == 1100 and result.cost["output_tokens"] == 340
    check = result.place_check
    assert check["outcome"] == WRITTEN.code
    assert check["policy"]["sha256"] == PLACE_PROPOSAL_POLICY.digest()
    assert check["sign_judgement"]["completeness"] == "whole"
    assert check["sign_judge"] == PRIMARY
    assert check["sign_usage"]["input_tokens"] == 400


def test_a_partly_hidden_sign_withholds_the_proposal_and_keeps_the_reply_verbatim():
    result, _ = _observe(
        [
            _ok(json.dumps(_proposing("Halcyon", "HALCYON"))),
            _ok(_answer("partly_hidden", "HALCYON")),
        ]
    )
    assert result.observation.proposed_place is None
    assert result.payload["proposed_place"]["label"] == "Halcyon"
    assert result.place_check["outcome"] == SIGN_PARTLY_HIDDEN.code
    assert result.place_check["written_label"] is None


def test_a_failed_sign_question_withholds_the_proposal_and_keeps_the_observation():
    """The previous design failed the whole photograph here; a check that fails must degrade.

    The second reply is the observation again, which is what a transport scripted with one reply
    per model returns, and it does not satisfy the sign question's schema.
    """
    proposing = json.dumps(_proposing("Lantern House", "LANTERN HOUSE"))
    result, transport = _observe([_ok(proposing), _ok(proposing)])
    assert transport.call_count == 2
    assert result.observation.proposed_place is None
    assert result.observation.legible_text[0].text == "LANTERN HOUSE"
    assert result.calls == 1, "a call that returned nothing usable is not counted as answered"
    check = result.place_check
    assert check["outcome"] == SIGN_CHECK_FAILED.code
    assert check["sign_check_failure"].startswith("SchemaViolationError")


def test_a_sign_judged_by_the_fallback_is_refused_by_name(transport):
    transport.responses = [
        _ok(json.dumps(_proposing("Lantern House", "LANTERN HOUSE"))),
        model_not_found(PRIMARY),
        _ok(_answer("whole", "LANTERN HOUSE")),
    ]
    result = _model(transport).observe(image_bytes=b"\x89PNG", media_type="image/png")
    assert transport.models_called == [PRIMARY, PRIMARY, FALLBACK]
    assert result.observation.proposed_place is None
    assert result.place_check["outcome"] == SIGN_JUDGE_NOT_ADMITTED.code
    assert result.place_check["sign_judge"] == FALLBACK


def test_a_judgement_about_another_sign_does_not_admit_the_proposal():
    """The question asks about the most prominent sign, which may not be the one named."""
    result, _ = _observe(
        [
            _ok(json.dumps(_proposing("Mariner Street", "MARINER STREET", "SUMMER SALE"))),
            _ok(_answer("whole", "SUMMER SALE")),
        ]
    )
    assert result.observation.proposed_place is None
    assert result.place_check["outcome"] == JUDGED_SIGN_DOES_NOT_CARRY_THE_NAME.code


# -- the reprocessing key ---------------------------------------------------------------


def test_editing_only_a_schema_description_moves_the_reprocessing_key(monkeypatch):
    """The schema's descriptions are instructions the model reads beside the prompt."""
    before = vision_stage_params()["prompt_sha256"]
    edited = copy.deepcopy(vision_module.OBSERVATION_SCHEMA)
    edited["properties"]["proposed_place"]["description"] = "Always propose a place."
    monkeypatch.setattr(vision_module, "OBSERVATION_SCHEMA", edited)
    assert vision_stage_params()["prompt_sha256"] != before


def test_changing_the_place_policy_moves_the_reprocessing_key(monkeypatch):
    """A stored decision names the rule that made it, and a new rule decides again."""
    before = vision_stage_params()["prompt_sha256"]
    stricter = dataclasses.replace(PLACE_PROPOSAL_POLICY, admitted_judges=())
    monkeypatch.setattr(vision_module, "PLACE_PROPOSAL_POLICY", stricter)
    assert vision_stage_params()["prompt_sha256"] != before


def test_the_sign_question_is_inside_the_policy_digest():
    edited = dataclasses.replace(PLACE_PROPOSAL_POLICY, sign_question=SIGN_QUESTION + " Please.")
    assert edited.digest() != PLACE_PROPOSAL_POLICY.digest()
    assert place_proposal.PLACE_PROPOSAL_POLICY.sign_question == SIGN_QUESTION


# -- the stage --------------------------------------------------------------------------


def _ingest(tmp_path, photo_dir, repository, responses):
    store = LocalContentAddressedStore(tmp_path / "blobs")
    transport = FakeTransport(responses)
    pipeline = PhotoIngestPipeline(repository, store, vision=_model(transport))
    outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, "sign.jpg"))
    key = repository.connection.execute(
        "select storage_key from artifact where kind = 'vision_observation'"
    ).fetchone()["storage_key"]
    document = json.loads((tmp_path / "blobs" / key).read_bytes())
    places = repository.connection.execute(
        "select a.object_value #>> '{}' as v from assertion a "
        "join predicate p on p.predicate_id = a.predicate_id "
        "where a.workspace_id = %s and p.key = 'place_is'",
        (repository.workspace_id,),
    ).fetchall()
    occurrences = repository.connection.execute(
        "select count(*) as n from occurrence where workspace_id = %s and class = 'place'",
        (repository.workspace_id,),
    ).fetchone()["n"]
    texts = repository.connection.execute(
        "select count(*) as n from assertion a join predicate p on p.predicate_id = a.predicate_id "
        "where a.workspace_id = %s and p.key = 'ocr_text_is'",
        (repository.workspace_id,),
    ).fetchone()["n"]
    return outcome, document, [row["v"] for row in places], occurrences, texts


def test_the_stage_writes_the_decided_label_and_records_the_decision(
    tmp_path, photo_dir, repository
):
    outcome, document, places, occurrences, _ = _ingest(
        tmp_path,
        photo_dir,
        repository,
        [
            _ok(json.dumps(_proposing("Lantern House (sign)", "LANTERN HOUSE"))),
            _ok(_answer("whole", "LANTERN HOUSE")),
        ],
    )
    assert outcome.error is None, outcome.error
    assert outcome.model_calls == 2
    assert places == ["LANTERN HOUSE"] and occurrences == 1
    assert document["observation"]["proposed_place"]["label"] == "Lantern House (sign)"
    assert document["place_check"]["outcome"] == WRITTEN.code
    assert document["place_check"]["dropped_words"] == ["sign"]
    assert document["place_check"]["policy"]["sha256"] == PLACE_PROPOSAL_POLICY.digest()


def test_the_stage_writes_no_place_from_a_withheld_proposal_and_keeps_the_rest(
    tmp_path, photo_dir, repository
):
    outcome, document, places, occurrences, texts = _ingest(
        tmp_path,
        photo_dir,
        repository,
        [
            _ok(json.dumps(_proposing("Halcyon", "HALCYON"))),
            _ok(_answer("partly_hidden", "HALCYON")),
        ],
    )
    assert outcome.error is None, outcome.error
    assert places == [] and occurrences == 0
    assert texts == 1, "the transcription is kept; only the proposal is withheld"
    assert document["place_check"]["outcome"] == SIGN_PARTLY_HIDDEN.code
    assert document["observation"]["proposed_place"]["label"] == "Halcyon"


def test_the_stage_survives_a_failed_sign_question(tmp_path, photo_dir, repository):
    proposing = json.dumps(_proposing("Lantern House", "LANTERN HOUSE"))
    outcome, document, places, occurrences, texts = _ingest(
        tmp_path, photo_dir, repository, [_ok(proposing), _ok(proposing)]
    )
    assert outcome.error is None, outcome.error
    assert outcome.model_calls == 1
    assert places == [] and occurrences == 0 and texts == 1
    assert document["place_check"]["outcome"] == SIGN_CHECK_FAILED.code
