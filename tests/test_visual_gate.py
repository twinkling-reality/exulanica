"""The visual gate record builder: it decides, it refuses, and it can say FAIL.

A gate that cannot be made to fail in a test is not a gate. Every refusal below is a way a record
could otherwise have been written with less evidence than its keys claim. The judged key follows
rubric version 5: one question per picture, in route order, the first no decides, and a reply typed
in place of a pick can only ever be a no. The judge's words never enter a public record, which
carries their SHA-256 and byte count; a private companion holds them.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.errors import CanonicalisationError
from exulanica.evaluation import visual_gate
from exulanica.evaluation.gate_keys import (
    ANSWER_OPTIONS,
    ANSWER_REQUIREMENT,
    CANONICAL_SPELLINGS,
    CAPTURE_LABELS,
    CARRIED_WORDS_NOTICE,
    GATE_KEY_SET_VERSION,
    JUDGED_KEY,
    MELBOURNE_ENVELOPE,
    NOT_ASKED,
    OPTION_ANSWERS,
    PICTURE_TITLES,
    RETAINED_RECORDS,
    RUBRIC_GUIDANCE,
    RUBRIC_QUESTION,
    RUBRIC_V1,
    RUBRIC_VERSION,
    THRESHOLDS,
    TYPED_REPLY_RULE,
    VERSION_2,
    VERSION_3,
    VERSION_4,
    WORDS_STORAGE,
    UnknownGateKey,
    judge_prompt,
    reason_follow_up,
)
from exulanica.evaluation.visual_gate import (
    JUDGE_WORDS_PROFILE,
    CarriedWords,
    GateEvidenceError,
    JudgedAnswers,
    PictureAnswer,
    ReasonFollowUp,
    beats_baseline,
    build_gate,
    decide_judged,
    decide_mechanical,
    digest_bound,
    judge_words_file,
    judged_answers_from_record,
    recompose_judged,
    refuse_private_words,
    typed_reply_answer,
    visual_gate_record,
    words_fingerprint,
    words_from_companion,
)

_ROOT = Path(__file__).resolve().parents[1]
_RUBRIC = _ROOT / "docs/visual-gate-rubric.md"
_BASELINE_PATH = "docs/evaluation/2026-09-15-flatiron-owned-district-baseline.json"
_BASELINE = _ROOT / _BASELINE_PATH
_COMPANION = _ROOT / ".exulanica/judge-words/2026-09-15-flatiron-owned-district-baseline.json"
_RECORD_PATH = "records/2026-09-16-visual-gate-test.json"
_GIVEN_AT = "2026-09-16T12:00:00Z"
_SHA = "0" * 63 + "1"
_RUBRIC_SHA = "0" * 63 + "2"
_CAPTURES = {label: f"{index:064x}" for index, label in enumerate(CAPTURE_LABELS, start=3)}
_JUDGE = "Ada Example"
_REASON = "The ground floors read as a bakery, a pharmacy and a lobby, and the block runs on."
_YES, _NO = ANSWER_OPTIONS


def _passing_measurements() -> dict[str, dict[str, int]]:
    return {
        "continuousTexturedStreetAndFacades": {
            "streetAndFacadeTriangles": 5000,
            "untexturedStreetAndFacadeTriangles": 0,
            "routeSupportGapSamples": 0,
        },
        "noCutsOrFloatingGeometry": {
            "routeSupportGapSamples": 0,
            "ringEdgesWithoutDrawnFacade": 0,
            "componentsDetachedFromSupport": 0,
            "trianglesInsideBuildings": 0,
        },
        "usefulEyeLevelMovement": {
            "walkedDisplacementMm": 124_800,
            "maxLateralDeviationMm": 3,
            "recoveryEvents": 0,
            "harnessPositionWrites": 0,
            "traceSamples": 2497,
            "routeSupportGapSamples": 0,
            "maxEyeHeightErrorMm": 25,
            "maxSupportResampleDeltaMm": 25,
        },
        "completeCapsuleClearanceVerification": {
            "capsuleSamples": 2497,
            "capsuleSamplesChecked": 2497,
            "capsuleTriangleContactSamples": 0,
            "capsuleRingContactSamples": 0,
        },
        "practicalBrowserBudget": {
            "environmentTransferredBytes": 232_454,
            "drawnTriangles": 34_000,
            "environmentDecodedTextureBytes": 0,
            "maxDrawCalls": 40,
            "gpuErrors": 0,
            "pageErrors": 0,
        },
        "companionPresent": {"captures": 3, "capturesWithCompanionShown": 3},
        "reticlePresent": {"captures": 3, "capturesWithReticleCentred": 3},
        "authenticatedShellAndAuthoredHandlersPreserved": {
            "captures": 3,
            "capturesInProductShell": 3,
            "foreignListeners": 0,
            "productWindowKeydownListeners": 2,
            "interactionsNotCarriedByProduct": 0,
            "substitutedPages": 0,
        },
    }


def _asked(
    label: str,
    picked: str | None = _YES,
    words: str | None = _REASON,
    typed_by: str | None = _JUDGE,
    given_at: str | None = _GIVEN_AT,
) -> PictureAnswer:
    return PictureAnswer(
        label=label,
        capture_sha256=_CAPTURES[label],
        asked=True,
        picked=picked,
        words=words,
        typed_by=typed_by,
        given_at=given_at,
    )


def _unasked(label: str) -> PictureAnswer:
    return PictureAnswer(label=label, capture_sha256=_CAPTURES[label], asked=False)


def _answers(*pictures: PictureAnswer, judge: str = _JUDGE) -> JudgedAnswers:
    return JudgedAnswers(
        judge=judge,
        judged_on="2026-09-16",
        rubric_sha256=_RUBRIC_SHA,
        pictures=pictures or tuple(_asked(label) for label in CAPTURE_LABELS),
    )


def _no_at_start() -> JudgedAnswers:
    return _answers(
        _asked("start", _NO, "Plain coloured blocks; I cannot name a single shop."),
        _unasked("midpoint"),
        _unasked("endpoint"),
    )


def _decide(answers: JudgedAnswers, **overrides):
    arguments = {"rubric_sha256": _RUBRIC_SHA, "captures": dict(_CAPTURES)}
    arguments.update(overrides)
    return decide_judged(answers, **arguments)


def _gate(evidence: dict):
    return build_gate(evidence, rubric_sha256=_RUBRIC_SHA, captures=dict(_CAPTURES))


def _evidence(**overrides) -> dict:
    evidence: dict = _passing_measurements()
    evidence["readsAsInhabitedStreet"] = _answers()
    evidence.update(overrides)
    return evidence


def _record(evidence: dict, **overrides) -> dict:
    arguments = {
        "profile": "exulanica.visual-gate-test/v1",
        "date": "2026-09-16",
        "status": "test",
        "base": "0" * 40,
        "branch": "test",
        "predecessor_records": [
            {"path": record.path, "record_sha256": record.record_sha256}
            for record in RETAINED_RECORDS
        ],
        "artifacts": [],
        "captures": [
            {"label": label, "path": f"x/{label}.png", "byte_size": 1, "sha256": _CAPTURES[label]}
            for label in CAPTURE_LABELS
        ],
        "browser": {"engine": "test"},
        "evidence": evidence,
        "rubric_sha256": _RUBRIC_SHA,
        "authentication_condition": "credentialed-api",
        "reason": "test",
        "checks": {},
        "claims_not_made": ["nothing"],
        "record_path": _RECORD_PATH,
    }
    arguments.update(overrides)
    return visual_gate_record(**arguments)


def test_a_complete_passing_block_passes_so_the_gate_is_not_a_constant():
    document = _record(_evidence())
    assert document["record"]["verdict"] == "PASS"
    assert set(document["record"]["hardPass"]) == set(CANONICAL_SPELLINGS)
    assert all(document["record"]["hardPass"].values())
    judged = document["record"]["gate"]["keys"]["readsAsInhabitedStreet"]
    assert [entry["answer"] for entry in judged["pictures"]] == ["yes", "yes", "yes"]
    assert judged["decisiveNo"] is None
    assert document["record"]["gate"]["keySet"] == GATE_KEY_SET_VERSION


def test_a_plausible_failing_input_produces_fail():
    """The shipped district's shape: nothing textured, trees in buildings, flat colour."""
    measured = _passing_measurements()
    measured["continuousTexturedStreetAndFacades"]["untexturedStreetAndFacadeTriangles"] = 21_540
    measured["noCutsOrFloatingGeometry"]["trianglesInsideBuildings"] = 216
    document = _record({**measured, "readsAsInhabitedStreet": _no_at_start()})
    record = document["record"]
    assert record["verdict"] == "FAIL"
    assert record["hardPass"]["continuousTexturedStreetAndFacades"] is False
    assert record["hardPass"]["noCutsOrFloatingGeometry"] is False
    assert record["hardPass"]["readsAsInhabitedStreet"] is False
    judged = record["gate"]["keys"]["readsAsInhabitedStreet"]
    assert judged["decisiveNo"] == "start"
    assert [entry["state"] for entry in judged["pictures"]] == ["answered", NOT_ASKED, NOT_ASKED]
    assert "yesAnswers" not in judged and "possibleAnswers" not in judged
    assert set(record["gate"]["failedKeys"]) == {
        "continuousTexturedStreetAndFacades",
        "noCutsOrFloatingGeometry",
        "readsAsInhabitedStreet",
    }


@pytest.mark.parametrize("spelling", [s for s in CANONICAL_SPELLINGS])
def test_every_single_key_can_fail_the_verdict_on_its_own(spelling):
    measured = _passing_measurements()
    if spelling == "readsAsInhabitedStreet":
        judged = _answers(
            _asked("start"),
            _asked("midpoint"),
            _asked("endpoint", _NO, "The far end is one flat wall with nothing behind it."),
        )
        document = _record({**measured, "readsAsInhabitedStreet": judged})
    else:
        field = next(iter(measured[spelling]))
        broken = {
            "streetAndFacadeTriangles": 0,
            "routeSupportGapSamples": 1,
            "walkedDisplacementMm": THRESHOLDS["minimumWalkedMm"] - 1,
            "capsuleSamples": 0,
            "environmentTransferredBytes": 28_247_007,
            "captures": 2,
        }[field]
        measured[spelling][field] = broken
        document = _record({**measured, "readsAsInhabitedStreet": _answers()})
    assert document["record"]["verdict"] == "FAIL"
    assert document["record"]["hardPass"][spelling] is False
    assert document["record"]["gate"]["failedKeys"] == [spelling]


def test_the_builder_refuses_a_missing_key():
    evidence = _evidence()
    del evidence["completeCapsuleClearanceVerification"]
    with pytest.raises(GateEvidenceError, match="no evidence for completeCapsuleClearance"):
        _gate(evidence)
    with pytest.raises(GateEvidenceError):
        _record(evidence)


def test_the_builder_refuses_a_measurement_with_a_missing_field():
    evidence = _evidence()
    del evidence["practicalBrowserBudget"]["gpuErrors"]
    with pytest.raises(GateEvidenceError, match="no evidence for 'gpuErrors'"):
        _gate(evidence)


def test_the_builder_refuses_a_value_handed_in_instead_of_a_measurement():
    evidence = _evidence()
    evidence["reticlePresent"] = {"captures": 3, "capturesWithReticleCentred": True}
    with pytest.raises(GateEvidenceError, match="measured integer"):
        _gate(evidence)
    evidence["reticlePresent"] = {"captures": 3, "capturesWithReticleCentred": -1}
    with pytest.raises(GateEvidenceError, match="negative"):
        _gate(evidence)


def test_the_builder_refuses_retained_and_invented_spellings():
    evidence = _evidence()
    evidence["recognizableUrbanScene"] = evidence.pop("readsAsInhabitedStreet")
    with pytest.raises(GateEvidenceError, match="retained spelling"):
        _gate(evidence)
    evidence = _evidence()
    evidence["looksLikeACity"] = {}
    with pytest.raises(UnknownGateKey):
        _gate(evidence)
    with pytest.raises(GateEvidenceError, match="canonical spellings only"):
        decide_mechanical("continuousTexturedStreet", {})


@pytest.mark.parametrize(
    "judge",
    [
        "",
        "   ",
        "the operator",
        "Operator",
        "judge",
        "JUDGE NOT YET NAMED",
        "TBD",
        "Claude",
        "model",
        "assistant",
        "placeholder",
        "<judge>",
        "{name}",
        "[judge name]",
        "anonymous",
    ],
)
def test_a_missing_or_placeholder_judge_is_refused(judge):
    with pytest.raises(GateEvidenceError, match="name"):
        _gate(_evidence(readsAsInhabitedStreet=_answers(judge=judge)))
    with pytest.raises(GateEvidenceError, match="name"):
        _decide(dataclasses.replace(_answers(), judge=None))  # type: ignore[arg-type]


def test_the_builder_refuses_a_judged_key_from_a_measurement():
    with pytest.raises(GateEvidenceError, match="judged"):
        _gate(_evidence(readsAsInhabitedStreet={"yesAnswers": 9}))
    with pytest.raises(GateEvidenceError, match="judged, not measured"):
        decide_mechanical("readsAsInhabitedStreet", {})


def test_the_first_no_decides_and_the_pictures_after_it_are_not_asked():
    value, detail = _decide(_no_at_start())
    assert value is False
    assert detail["decisiveNo"] == "start"
    assert [entry["state"] for entry in detail["pictures"]] == ["answered", NOT_ASKED, NOT_ASKED]
    assert "words_sha256" not in detail["pictures"][1] and "answer" not in detail["pictures"][2]

    value, detail = _decide(
        _answers(
            _asked("start"), _asked("midpoint", _NO, "It stops at a hole."), _unasked("endpoint")
        )
    )
    assert (value, detail["decisiveNo"]) == (False, "midpoint")

    value, detail = _decide(
        _answers(_asked("start"), _asked("midpoint"), _asked("endpoint", _NO, "Blank walls."))
    )
    assert (value, detail["decisiveNo"]) == (False, "endpoint")

    value, detail = _decide(_answers())
    assert (value, detail["decisiveNo"]) == (True, None)
    assert [entry["picture"] for entry in detail["pictures"]] == list(PICTURE_TITLES.values())
    assert (detail["question"], detail["guidance"]) == (RUBRIC_QUESTION, RUBRIC_GUIDANCE)
    assert (
        detail["options"]
        == list(ANSWER_OPTIONS)
        == [
            "Yes, a finished, lived-in street",
            "No, a plain block mock-up",
        ]
    )
    assert detail["optionAnswers"] == dict(OPTION_ANSWERS) == {_YES: "yes", _NO: "no"}


@pytest.mark.parametrize(
    "pictures",
    [
        ("start", "midpoint", None),
        ("start", None, None),
        (None, None, None),
        (None, "midpoint", "endpoint"),
    ],
)
def test_a_yes_key_with_any_picture_unasked_is_refused(pictures):
    answers = _answers(
        *(
            _asked(label) if asked is not None else _unasked(label)
            for label, asked in zip(CAPTURE_LABELS, pictures, strict=True)
        )
    )
    with pytest.raises(GateEvidenceError, match="unasked"):
        _decide(answers)
    with pytest.raises(GateEvidenceError, match="unasked"):
        _record(_evidence(readsAsInhabitedStreet=answers))


def test_an_answer_given_after_a_decisive_no_is_refused():
    for later in (_asked("midpoint"), _asked("midpoint", _NO, "Still blocks.")):
        answers = _answers(
            _asked("start", _NO, "Coloured shapes, not a street."), later, _unasked("endpoint")
        )
        with pytest.raises(GateEvidenceError, match="after the decisive no"):
            _decide(answers)
    answers = _answers(
        _asked("start", _NO, "Coloured shapes, not a street."),
        _unasked("midpoint"),
        _asked("endpoint"),
    )
    with pytest.raises(GateEvidenceError, match="after the decisive no"):
        _decide(answers)


@pytest.mark.parametrize(
    ("picked", "words"),
    [
        (_NO, None),
        (_NO, ""),
        (_NO, "   "),
        (_NO, "No"),
        (_NO, "no."),
        (_YES, "YES!"),
        (None, "no"),
        (None, " No ... "),
    ],
)
def test_an_answer_without_a_reason_in_the_judges_own_words_is_refused(picked, words):
    answers = _answers(_asked("start", picked, words), _asked("midpoint"), _asked("endpoint"))
    with pytest.raises(GateEvidenceError, match="no reason in the judge's own words"):
        _decide(answers)
    with pytest.raises(GateEvidenceError, match="no reason in the judge's own words"):
        _record(_evidence(readsAsInhabitedStreet=answers))


@pytest.mark.parametrize(
    ("picked", "words", "typed_by", "match"),
    [
        (_NO, "Plain blocks.", "Claude", "not typed by the judge"),
        (_NO, "Plain blocks.", None, "not typed by the judge"),
        (_NO, "Plain blocks.", "Somebody Else", "not typed by the judge"),
        (_NO, "Plain blocks.", "ada example", "not typed by the judge"),
        ("Yes", "It looks lived in.", _JUDGE, "not one of the options"),
        ("No", "Plain blocks.", _JUDGE, "not one of the options"),
        ("Yes (Recommended)", "It looks lived in.", _JUDGE, "not one of the options"),
        ("yes", "It looks lived in.", _JUDGE, "not one of the options"),
        ("Other", "It looks lived in.", _JUDGE, "not one of the options"),
        (None, "Just coloured shapes, not one shop.", _JUDGE, "nothing is inferred"),
        (None, "Nobody could live here.", _JUDGE, "nothing is inferred"),
        (None, "Yes, shops and a lobby I could name.", _JUDGE, "nothing is inferred"),
        (None, "No shops, yes, but it is a street.", _JUDGE, "nothing is inferred"),
        (None, "[No preference]", _JUDGE, "skipped"),
        (None, "No preference", _JUDGE, "skipped"),
    ],
)
def test_an_answer_not_typed_by_the_judge_is_refused(picked, words, typed_by, match):
    answers = _answers(
        _asked("start", picked, words, typed_by), _unasked("midpoint"), _unasked("endpoint")
    )
    with pytest.raises(GateEvidenceError, match=re.escape(match)):
        _decide(answers)
    with pytest.raises(GateEvidenceError, match=re.escape(match)):
        _record(_evidence(readsAsInhabitedStreet=answers))


#: Replies typed in place of a pick, one for each way the typed-reply rule can read a reply. They
#: are invented for the tests; the judge's own replies stay in the private companions.
_TYPED_NO = "Honestly this is still a bare block model, no shops or signs at all."
_TYPED_BOTH_WORDS = "Yes the street is there, but no, nothing looks built."
_TYPED_YES = "Yes, though the fronts are plain, the street edge holds."
_TYPED_NEITHER = "The street shape reads, the surfaces do not."


@pytest.mark.parametrize(
    ("words", "answer"),
    [
        (_TYPED_NO, "no"),
        # No as a determiner is still the whole word no.
        ("There are no shops, and every front is one colour.", "no"),
        # The rule's known cost: the whole word no inside praise reads as a no.
        ("A lovely street, no complaints from me.", "no"),
        ("NO", "no"),
        ("no-one would call this finished", "no"),
        ("Yesterday it looked no better.", "no"),
        (_TYPED_BOTH_WORDS, None),
        ("No, and yes, the shapes are there.", None),
        (_TYPED_YES, None),
        ("yes", None),
        ("Yes, a finished, lived-in street", None),
        (_TYPED_NEITHER, None),
        ("Nobody lives here.", None),
        ("nope", None),
        ("not really", None),
        ("[No preference]", None),
        ("", None),
    ],
)
def test_the_typed_reply_rule_reads_only_a_whole_no_without_a_whole_yes(words, answer):
    assert typed_reply_answer(words) == answer


def test_a_typed_reply_can_only_ever_be_a_no():
    value, detail = _decide(
        _answers(
            _asked("start", None, "NO IT IS JUST COLOURED SHAPES"),
            _unasked("midpoint"),
            _unasked("endpoint"),
        )
    )
    assert value is False
    entry = detail["pictures"][0]
    assert (entry["picked"], entry["answer"], entry["readFrom"]) == (
        None,
        "no",
        "the typed-reply rule",
    )
    assert entry["words_sha256"] == hashlib.sha256(b"NO IT IS JUST COLOURED SHAPES").hexdigest()
    assert detail["typedReplyRule"] == TYPED_REPLY_RULE
    value, detail = _decide(
        _answers(_asked("start", None, _TYPED_NO), _unasked("midpoint"), _unasked("endpoint"))
    )
    assert value is False
    assert detail["pictures"][0]["answer"] == "no"
    assert detail["pictures"][0]["reason"] == [
        {
            "from": "reply",
            "rubricVersion": RUBRIC_VERSION,
            "givenAt": _GIVEN_AT,
            "givenAs": "in reply to this ask",
            **words_fingerprint(_TYPED_NO),
        }
    ]
    for words in (_TYPED_YES, _TYPED_BOTH_WORDS, _TYPED_NEITHER):
        typed = _answers(*(_asked(label, None, words) for label in CAPTURE_LABELS))
        with pytest.raises(GateEvidenceError, match="nothing is inferred"):
            _decide(typed)
        with pytest.raises(GateEvidenceError, match="nothing is inferred"):
            _record(_evidence(readsAsInhabitedStreet=typed))


def test_the_judges_words_are_fingerprinted_exactly_as_typed_and_kept_out_of_the_record():
    words = "  omg it is just shapes\nno shops, no people  "
    answers = _answers(_asked("start", _NO, words), _unasked("midpoint"), _unasked("endpoint"))
    _, detail = _decide(answers)
    entry = detail["pictures"][0]
    data = words.encode("utf-8")
    assert (entry["words_sha256"], entry["words_bytes"], entry["words_private"]) == (
        hashlib.sha256(data).hexdigest(),
        len(data),
        True,
    )
    assert entry["reason"] == [
        {
            "from": "reply",
            "rubricVersion": RUBRIC_VERSION,
            "givenAt": _GIVEN_AT,
            "givenAs": "in reply to this ask",
            **words_fingerprint(words),
        }
    ]
    assert (entry["typedBy"], entry["givenAt"], entry["rubricVersion"]) == (
        _JUDGE,
        _GIVEN_AT,
        RUBRIC_VERSION,
    )
    assert "shapes" not in json.dumps(detail)
    record = _record({**_passing_measurements(), "readsAsInhabitedStreet": answers})
    assert "shapes" not in json.dumps(record)
    path, companion = judge_words_file(_RECORD_PATH, answers)
    assert path == ".exulanica/judge-words/2026-09-16-visual-gate-test.json"
    binding = record["record"]["judgeWords"]
    assert (binding["path"], binding["byte_size"], binding["sha256"], binding["tracked"]) == (
        path,
        len(companion),
        hashlib.sha256(companion).hexdigest(),
        False,
    )
    document = json.loads(companion)
    assert (document["profile"], document["publicRecord"]) == (JUDGE_WORDS_PROFILE, _RECORD_PATH)
    (reply,) = document["replies"]
    assert (reply["words"], reply["givenAt"], reply["picked"]) == (words, _GIVEN_AT, _NO)


def test_a_reply_that_does_not_say_when_it_was_given_is_refused():
    for given_at in (None, "2026-09-16", "2026-09-16 12:00:00", "2026-09-15T23:59:59Z"):
        answers = _answers(
            _asked("start", _NO, "Blocks, not a street.", given_at=given_at),
            _unasked("midpoint"),
            _unasked("endpoint"),
        )
        with pytest.raises(GateEvidenceError, match="given"):
            _decide(answers)
    late = dataclasses.replace(
        _without_words("start", _NO),
        follow_up=ReasonFollowUp(
            shown=reason_follow_up("no"), words="Flat blocks.", typed_by=_JUDGE, given_at=None
        ),
    )
    with pytest.raises(GateEvidenceError, match="given"):
        _decide(_answers(late, _unasked("midpoint"), _unasked("endpoint")))
    stray = dataclasses.replace(_unasked("midpoint"), given_at=_GIVEN_AT)
    with pytest.raises(GateEvidenceError, match="cannot carry an answer"):
        _decide(_answers(_asked("start", _NO, "Blocks."), stray, _unasked("endpoint")))


def test_a_public_record_never_carries_the_judges_words():
    words = "Plain coloured blocks; I cannot name a single shop."
    answers = _answers(_asked("start", _NO, words), _unasked("midpoint"), _unasked("endpoint"))
    evidence = {**_passing_measurements(), "readsAsInhabitedStreet": answers}
    _record(evidence)
    for leak in (
        {"reason": f"The judge wrote: {words}"},
        {"reason": "The judge said: I CANNOT NAME A SINGLE shop, sadly."},
        {"claims_not_made": ['The judge called them "coloured blocks"']},
        {"extra": {"note": {"judge": "plain, coloured blocks! i cannot name"}}},
    ):
        with pytest.raises(GateEvidenceError, match="judge's words"):
            _record(evidence, **leak)
    # The question the judge was shown and the answer words are not the judge's own words.
    _record(evidence, reason=f'Asked "{RUBRIC_QUESTION}", the judge picked "No".')
    refuse_private_words(["A single run of three: coloured blocks name"], [words])
    line = "Your reply began 'Plain'. Your own words are kept."
    refuse_private_words(["The judge's own words are kept as typed."], [words], lines=[line])
    with pytest.raises(GateEvidenceError, match="judge's words"):
        refuse_private_words([f"Shown: {line}"], [words], lines=[line])
    with pytest.raises(GateEvidenceError, match="quotes the judge's words"):
        refuse_private_words(["The reply began 'Plain'."], [words], lines=[line])
    with pytest.raises(GateEvidenceError, match="judge's words"):
        refuse_private_words({"key": ["a", {"deep": "coloured blocks I cannot name"}]}, [words])
    refuse_private_words(["blocks I cannot name; only four words run on"], [words])
    follow = _without_words("start", _NO, "Every wall is one flat grey.")
    with pytest.raises(GateEvidenceError, match="judge's words"):
        _record(
            {
                **_passing_measurements(),
                "readsAsInhabitedStreet": _answers(
                    follow, _unasked("midpoint"), _unasked("endpoint")
                ),
            },
            reason="The follow-up said every wall is one flat grey.",
        )
    carrying = _with_carried(_NO)
    with pytest.raises(GateEvidenceError, match="judge's words"):
        _record(
            {
                **_passing_measurements(),
                "readsAsInhabitedStreet": _answers(
                    carrying, _unasked("midpoint"), _unasked("endpoint")
                ),
            },
            reason=f"Carried: {_EARLIER}",
        )


def _without_words(
    label: str, picked: str = _YES, reply: str | None = "Brick fronts, a bakery."
) -> PictureAnswer:
    """An answer picked with no words, followed once for its reason unless ``reply`` is None."""
    follow = None
    if reply is not None:
        follow = ReasonFollowUp(
            shown=reason_follow_up(OPTION_ANSWERS[picked]),
            words=reply,
            typed_by=_JUDGE,
            given_at=_GIVEN_AT,
        )
    return PictureAnswer(
        label=label,
        capture_sha256=_CAPTURES[label],
        asked=True,
        picked=picked,
        words=None,
        typed_by=_JUDGE,
        follow_up=follow,
        given_at=_GIVEN_AT,
    )


def test_an_answer_without_words_takes_its_reason_from_one_follow_up():
    value, detail = _decide(
        _answers(_without_words("start"), _asked("midpoint"), _asked("endpoint"))
    )
    assert value is True
    entry = detail["pictures"][0]
    assert (entry["picked"], entry["answer"], entry["words_sha256"]) == (_YES, "yes", None)
    assert entry["reason"] == [
        {
            "from": "follow-up",
            "rubricVersion": RUBRIC_VERSION,
            "givenAt": _GIVEN_AT,
            "givenAs": "in reply to the follow-up",
            **words_fingerprint("Brick fronts, a bakery."),
        }
    ]
    assert entry["followUp"] == {
        "asked": "You answered Yes. In a few words, why?",
        **words_fingerprint("Brick fronts, a bakery."),
        "typedBy": _JUDGE,
        "givenAt": _GIVEN_AT,
    }
    answers = _answers(_without_words("start"), _asked("midpoint"), _asked("endpoint"))
    replies = json.loads(judge_words_file(_RECORD_PATH, answers)[1])["replies"]
    assert [(reply["kind"], reply["words"]) for reply in replies[:2]] == [
        ("reply", None),
        ("follow-up", "Brick fronts, a bakery."),
    ]
    assert replies[1]["shown"] == "You answered Yes. In a few words, why?"
    assert [item["from"] for item in detail["pictures"][1]["reason"]] == ["reply"]
    assert detail["requirement"] == ANSWER_REQUIREMENT


def test_a_follow_up_never_changes_the_answer():
    value, detail = _decide(
        _answers(
            _without_words("start", _NO, "yes the colours are fine but it is a block model"),
            _unasked("midpoint"),
            _unasked("endpoint"),
        )
    )
    assert value is False
    assert detail["pictures"][0]["answer"] == "no"
    assert detail["decisiveNo"] == "start"


def _followed(
    picked: str | None, words: str | None, shown: str, reply: str | None, typed_by: str = _JUDGE
) -> PictureAnswer:
    return PictureAnswer(
        label="start",
        capture_sha256=_CAPTURES["start"],
        asked=True,
        picked=picked,
        words=words,
        typed_by=_JUDGE,
        follow_up=ReasonFollowUp(shown=shown, words=reply, typed_by=typed_by, given_at=_GIVEN_AT),
        given_at=_GIVEN_AT,
    )


@pytest.mark.parametrize(
    ("picture", "match"),
    [
        (
            _followed(_YES, "Real brick, a corner cafe.", reason_follow_up("yes"), "Because."),
            "already gave",
        ),
        (_followed(_NO, None, reason_follow_up("yes"), "Flat blocks."), "rubric's words"),
        (
            _followed(_YES, None, "Why did you say yes? Was it the shops?", "Shops."),
            "rubric's words",
        ),
        (
            _followed(_YES, None, reason_follow_up("yes"), "Shops.", typed_by="Claude"),
            "not typed by the judge",
        ),
        (
            _followed(_YES, None, reason_follow_up("yes"), None),
            "no reason in the judge's own words",
        ),
        (
            _followed(_YES, None, reason_follow_up("yes"), "   "),
            "no reason in the judge's own words",
        ),
        (
            _followed(_YES, None, reason_follow_up("yes"), "[No preference]"),
            "no reason in the judge's own words",
        ),
        (
            _followed(_YES, None, reason_follow_up("yes"), "yes"),
            "no reason in the judge's own words",
        ),
        (
            _followed(_YES, "yes", reason_follow_up("yes"), "No."),
            "no reason in the judge's own words",
        ),
    ],
)
def test_a_follow_up_that_is_not_allowed_or_gives_no_reason_is_refused(picture, match):
    answers = _answers(picture, _asked("midpoint"), _asked("endpoint"))
    with pytest.raises(GateEvidenceError, match=re.escape(match)):
        _decide(answers)
    with pytest.raises(GateEvidenceError, match=re.escape(match)):
        _record(_evidence(readsAsInhabitedStreet=answers))


def test_an_answer_with_no_words_and_no_follow_up_is_refused():
    answers = _answers(_without_words("start", reply=None), _asked("midpoint"), _asked("endpoint"))
    with pytest.raises(GateEvidenceError, match="no reason in the judge's own words"):
        _decide(answers)


def test_an_unasked_picture_cannot_carry_a_follow_up():
    carrying = dataclasses.replace(
        _unasked("midpoint"),
        follow_up=ReasonFollowUp(shown=reason_follow_up("no"), words="Flat.", typed_by=_JUDGE),
    )
    with pytest.raises(GateEvidenceError, match="cannot carry an answer"):
        _decide(_answers(_asked("start", _NO, "Blocks."), carrying, _unasked("endpoint")))


def test_a_skipped_question_is_not_an_answer():
    for words in (None, "", "  "):
        answers = _answers(_asked("start", None, words), _unasked("midpoint"), _unasked("endpoint"))
        with pytest.raises(GateEvidenceError, match="skipped"):
            _decide(answers)


#: Words written under rubric version 3 and carried into a later ask. Invented for the tests.
_EARLIER = "The walls still read as one flat colour, whatever the pick said."
_EARLIER_AT = "2026-09-16T11:00:00Z"
_EARLIER_AS = "a message sent right after a Yes pick under rubric version 3"


def _earlier(**changes) -> CarriedWords:
    fields = {
        "words": _EARLIER,
        "typed_by": _JUDGE,
        "rubric_version": VERSION_3.rubric_version,
        "rubric_sha256": VERSION_3.rubric_sha256,
        "given_at": _EARLIER_AT,
        "given_as": _EARLIER_AS,
    }
    fields.update(changes)
    return CarriedWords(**fields)


def _with_carried(
    picked: str | None,
    words: str | None = None,
    carried: tuple[CarriedWords, ...] | None = None,
    notice: str | None = CARRIED_WORDS_NOTICE,
    follow_up: ReasonFollowUp | None = None,
) -> PictureAnswer:
    return PictureAnswer(
        label="start",
        capture_sha256=_CAPTURES["start"],
        asked=True,
        picked=picked,
        words=words,
        typed_by=_JUDGE,
        follow_up=follow_up,
        carried=(_earlier(),) if carried is None else carried,
        notice=notice,
        given_at=_GIVEN_AT,
    )


def _companion_words(answers: JudgedAnswers) -> dict[str, str]:
    _, companion = judge_words_file(_RECORD_PATH, answers)
    return words_from_companion(json.loads(companion), _RECORD_PATH)


def test_a_no_takes_its_reason_from_words_carried_across_a_rewording():
    value, detail = _decide(
        _answers(_with_carried(_NO), _unasked("midpoint"), _unasked("endpoint"))
    )
    assert value is False
    entry = detail["pictures"][0]
    assert entry["noticeAboveTheQuestion"] == CARRIED_WORDS_NOTICE
    assert entry["carried"] == [
        {
            **words_fingerprint(_EARLIER),
            "typedBy": _JUDGE,
            "rubricVersion": 3,
            "rubricSha256": VERSION_3.rubric_sha256,
            "givenAt": _EARLIER_AT,
            "givenAs": _EARLIER_AS,
        }
    ]
    assert entry["reason"] == [
        {
            "from": "earlier words",
            "rubricVersion": 3,
            "givenAt": _EARLIER_AT,
            "givenAs": _EARLIER_AS,
            **words_fingerprint(_EARLIER),
        }
    ]
    answers = _answers(
        _with_carried(_NO, "Flat colour, no shops."), _unasked("midpoint"), _unasked("endpoint")
    )
    value, detail = _decide(answers)
    assert [item["from"] for item in detail["pictures"][0]["reason"]] == [
        "earlier words",
        "reply",
    ]
    rebuilt = judged_answers_from_record(detail, _companion_words(answers))
    assert _decide(rebuilt) == (False, detail)
    kinds = [
        reply["kind"] for reply in json.loads(judge_words_file(_RECORD_PATH, answers)[1])["replies"]
    ]
    assert kinds == ["carried", "reply"]


def test_a_yes_after_carried_words_needs_new_words():
    with pytest.raises(GateEvidenceError, match="needs new words"):
        _decide(_answers(_with_carried(_YES), _asked("midpoint"), _asked("endpoint")))
    follow = ReasonFollowUp(
        shown=reason_follow_up("yes"), words="Real brick.", typed_by=_JUDGE, given_at=_GIVEN_AT
    )
    with pytest.raises(GateEvidenceError, match="needs new words"):
        _decide(
            _answers(_with_carried(_YES, follow_up=follow), _asked("midpoint"), _asked("endpoint"))
        )
    value, detail = _decide(
        _answers(
            _with_carried(_YES, "Brick, glass and a corner cafe."),
            _asked("midpoint"),
            _asked("endpoint"),
        )
    )
    assert value is True
    assert [item["from"] for item in detail["pictures"][0]["reason"]] == ["reply"]
    carried = detail["pictures"][0]["carried"][0]
    assert carried["words_sha256"] == words_fingerprint(_EARLIER)["words_sha256"]


@pytest.mark.parametrize(
    ("picture", "match"),
    [
        (_with_carried(_NO, notice=None), "need the line"),
        (_with_carried(_NO, notice="Please answer again."), "need the line"),
        (_with_carried(_NO, carried=(), notice=CARRIED_WORDS_NOTICE), "with no reason"),
        (_with_carried(_NO, carried=(_earlier(typed_by="Claude"),)), "not typed by the judge"),
        (_with_carried(_NO, carried=(_earlier(rubric_version=9),)), "superseded rubric"),
        (_with_carried(_NO, carried=(_earlier(rubric_sha256=_SHA),)), "superseded rubric"),
        (_with_carried(_NO, carried=(_earlier(words="no"),)), "must say something"),
        (_with_carried(_NO, carried=(_earlier(given_at="yesterday"),)), "when it was given"),
        (_with_carried(_NO, carried=(_earlier(given_as=" "),)), "how they were given"),
        (
            _with_carried(
                _NO,
                follow_up=ReasonFollowUp(
                    shown=reason_follow_up("no"), words="Flat.", typed_by=_JUDGE, given_at=_GIVEN_AT
                ),
            ),
            "already gave",
        ),
    ],
)
def test_carried_words_that_are_not_allowed_are_refused(picture, match):
    answers = _answers(picture, _unasked("midpoint"), _unasked("endpoint"))
    with pytest.raises(GateEvidenceError, match=re.escape(match)):
        _decide(answers)


def test_an_unasked_picture_cannot_carry_earlier_words():
    carrying = dataclasses.replace(
        _unasked("midpoint"), carried=(_earlier(),), notice=CARRIED_WORDS_NOTICE
    )
    with pytest.raises(GateEvidenceError, match="cannot carry an answer"):
        _decide(_answers(_asked("start", _NO, "Blocks."), carrying, _unasked("endpoint")))


def test_a_typed_no_after_carried_words_keeps_both_reasons_in_the_order_given():
    value, detail = _decide(
        _answers(_with_carried(None, _TYPED_NO), _unasked("midpoint"), _unasked("endpoint"))
    )
    assert value is False
    entry = detail["pictures"][0]
    assert (entry["picked"], entry["answer"]) == (None, "no")
    assert entry["words_sha256"] == words_fingerprint(_TYPED_NO)["words_sha256"]
    assert entry["reason"] == [
        {
            "from": "earlier words",
            "rubricVersion": 3,
            "givenAt": _EARLIER_AT,
            "givenAs": _EARLIER_AS,
            **words_fingerprint(_EARLIER),
        },
        {
            "from": "reply",
            "rubricVersion": RUBRIC_VERSION,
            "givenAt": _GIVEN_AT,
            "givenAs": "in reply to this ask",
            **words_fingerprint(_TYPED_NO),
        },
    ]
    with pytest.raises(GateEvidenceError, match="nothing is inferred"):
        _decide(_answers(_with_carried(None, _TYPED_YES), _asked("midpoint"), _asked("endpoint")))


def test_a_rubric_digest_mismatch_is_refused():
    with pytest.raises(GateEvidenceError, match="rubric digest mismatch"):
        _decide(_answers(), rubric_sha256=_SHA)
    with pytest.raises(GateEvidenceError, match="rubric digest mismatch"):
        _record(_evidence(), rubric_sha256=_SHA)
    with pytest.raises(GateEvidenceError, match="names no rubric digest"):
        _record(_evidence(), rubric_sha256="docs/visual-gate-rubric.md")
    with pytest.raises(GateEvidenceError, match="must name the rubric answered"):
        _decide(dataclasses.replace(_answers(), rubric_sha256="latest"))


def test_only_an_answer_given_against_version_4_is_read_under_another_digest():
    against_v4 = dataclasses.replace(
        _answers(_asked("start", None, _TYPED_NO), _unasked("midpoint"), _unasked("endpoint")),
        rubric_sha256=VERSION_4.rubric_sha256,
    )
    value, detail = _decide(against_v4)
    assert value is False
    assert detail["rubricSha256"] == _RUBRIC_SHA
    assert detail["rubricVersion"] == RUBRIC_VERSION == VERSION_4.rubric_version + 1
    answered = detail["answeredAgainst"]
    assert (answered["rubricVersion"], answered["rubricSha256"]) == (4, VERSION_4.rubric_sha256)
    assert "exactly what version 4 showed" in answered["acceptedBecause"]
    assert [reason["rubricVersion"] for reason in detail["pictures"][0]["reason"]] == [4]
    _, companion = judge_words_file(_RECORD_PATH, against_v4, 4)
    assert json.loads(companion)["replies"][0]["rubricVersion"] == 4
    words = words_from_companion(json.loads(companion), _RECORD_PATH)
    assert _decide(judged_answers_from_record(detail, words)) == (False, detail)
    record = _record(_evidence(readsAsInhabitedStreet=against_v4))["record"]
    assert record["gate"]["keys"]["readsAsInhabitedStreet"] == detail
    assert record["judgeWords"]["sha256"] == hashlib.sha256(companion).hexdigest()

    _, current = _decide(_no_at_start())
    assert current["answeredAgainst"] == {
        "rubricVersion": RUBRIC_VERSION,
        "rubricSha256": _RUBRIC_SHA,
    }

    earlier = (
        VERSION_3.rubric_sha256,
        VERSION_2.rubric_sha256,
        hashlib.sha256(b"rubric version 1").hexdigest(),
        _SHA,
    )
    for digest in earlier:
        with pytest.raises(GateEvidenceError, match="rubric digest mismatch"):
            _decide(dataclasses.replace(against_v4, rubric_sha256=digest))


@pytest.mark.parametrize(
    "shown",
    [
        {"question": "Is this a street?"},
        {"guidance": "A yes means it looks real."},
        {"requirement": "Pick one."},
        {"options": ("Yes", "No")},
        {"carried_notice": None},
    ],
)
def test_version_4_answers_are_refused_once_version_4_showed_anything_else(monkeypatch, shown):
    changed = dataclasses.replace(VERSION_4, **shown)
    assert not changed.shows_what_is_shown_now()
    monkeypatch.setattr(visual_gate, "SUPERSEDED_VERSIONS", (VERSION_2, VERSION_3, changed))
    against_v4 = dataclasses.replace(_no_at_start(), rubric_sha256=VERSION_4.rubric_sha256)
    with pytest.raises(GateEvidenceError, match="rubric digest mismatch"):
        _decide(against_v4)


def test_a_capture_not_bound_by_digest_or_another_capture_is_refused():
    with pytest.raises(GateEvidenceError, match="not bound by digest"):
        _decide(_answers(), captures={**_CAPTURES, "midpoint": "x/midpoint.png"})
    with pytest.raises(GateEvidenceError, match="binds no capture"):
        _decide(_answers(), captures={"start": _CAPTURES["start"]})
    moved = dataclasses.replace(_asked("endpoint"), capture_sha256=_CAPTURES["start"])
    with pytest.raises(GateEvidenceError, match="was answered about capture"):
        _decide(_answers(_asked("start"), _asked("midpoint"), moved))
    shifted = [
        {"label": label, "path": f"x/{label}.png", "byte_size": 1, "sha256": _SHA}
        for label in CAPTURE_LABELS
    ]
    with pytest.raises(GateEvidenceError, match="was answered about capture"):
        _record(_evidence(), captures=shifted)
    unbound = [{"label": label, "path": f"x/{label}.png"} for label in CAPTURE_LABELS]
    with pytest.raises(GateEvidenceError, match="byte_size and sha256"):
        _record(_evidence(), captures=unbound)


def test_answers_out_of_route_order_or_malformed_are_refused():
    ordered = [_asked(label) for label in CAPTURE_LABELS]
    with pytest.raises(GateEvidenceError, match="in that order"):
        _decide(_answers(*reversed(ordered)))
    with pytest.raises(GateEvidenceError, match="in that order"):
        _decide(_answers(*ordered[:2]))
    with pytest.raises(GateEvidenceError, match="in that order"):
        _decide(_answers(*ordered, _asked("endpoint")))
    with pytest.raises(GateEvidenceError, match="true or false"):
        _decide(_answers(ordered[0], dataclasses.replace(ordered[1], asked=1), ordered[2]))
    carrying = dataclasses.replace(_unasked("midpoint"), words="It was fine.")
    with pytest.raises(GateEvidenceError, match="cannot carry an answer"):
        _decide(_answers(_asked("start", _NO, "Blocks."), carrying, _unasked("endpoint")))
    with pytest.raises(GateEvidenceError, match="needs the named judge's answers"):
        _decide({"start": "no"})  # type: ignore[arg-type]
    with pytest.raises(GateEvidenceError, match="ISO date"):
        _decide(dataclasses.replace(_answers(), judged_on="yesterday"))


def test_a_retained_record_is_decided_again_from_its_private_companion():
    answers = _answers(
        _with_carried(_NO, "Flat colour, no shops."), _unasked("midpoint"), _unasked("endpoint")
    )
    record = _record({**_passing_measurements(), "readsAsInhabitedStreet": answers})
    judged = record["record"]["gate"]["keys"]["readsAsInhabitedStreet"]
    _, companion = judge_words_file(_RECORD_PATH, answers)
    words = words_from_companion(json.loads(companion), _RECORD_PATH)
    value, detail = _decide(judged_answers_from_record(judged, words))
    assert value is False
    assert detail == judged
    assert recompose_judged(judged) is False
    with pytest.raises(GateEvidenceError, match="not in the private companion"):
        judged_answers_from_record(judged, {})
    with pytest.raises(GateEvidenceError, match="not the private companion"):
        words_from_companion(json.loads(companion), "records/another-record.json")
    forged = json.loads(companion)
    forged["replies"][0]["words"] = "Something else entirely."
    with pytest.raises(GateEvidenceError, match="does not match its own digest"):
        words_from_companion(forged, _RECORD_PATH)
    tampered = copy.deepcopy(judged)
    tampered["pictures"][1]["state"] = "skipped"
    with pytest.raises(GateEvidenceError, match="unknown states"):
        judged_answers_from_record(tampered, words)
    with pytest.raises(GateEvidenceError, match="unknown state"):
        recompose_judged(tampered)
    tampered = copy.deepcopy(judged)
    tampered["pictures"][0]["typedBy"] = "Claude"
    with pytest.raises(GateEvidenceError, match="not typed by the judge"):
        _decide(judged_answers_from_record(tampered, words))
    with pytest.raises(GateEvidenceError, match="not an answer the judge gave"):
        recompose_judged(tampered)
    tampered = copy.deepcopy(judged)
    tampered["pictures"][0]["carried"][0]["typedBy"] = "Claude"
    with pytest.raises(GateEvidenceError, match="did not give"):
        recompose_judged(tampered)
    tampered = copy.deepcopy(judged)
    tampered["value"] = True
    with pytest.raises(GateEvidenceError, match="does not follow"):
        recompose_judged(tampered)
    tampered = copy.deepcopy(judged)
    tampered["pictures"][0]["reason"][1]["words_private"] = False
    with pytest.raises(GateEvidenceError, match="no fingerprint"):
        recompose_judged(tampered)
    tampered["pictures"][0]["reason"] = []
    with pytest.raises(GateEvidenceError, match="no fingerprint"):
        recompose_judged(tampered)
    del tampered["judge"]
    with pytest.raises(GateEvidenceError, match="incomplete"):
        judged_answers_from_record(tampered, words)
    with pytest.raises(GateEvidenceError, match="incomplete"):
        recompose_judged(tampered)


def test_the_record_digest_reproduces_under_canonical_json():
    document = _record(_evidence())
    assert (
        document["record_sha256"] == hashlib.sha256(canonical_json(document["record"])).hexdigest()
    )
    round_tripped = json.loads(json.dumps(document, indent=2))
    assert (
        round_tripped["record_sha256"]
        == hashlib.sha256(canonical_json(round_tripped["record"])).hexdigest()
    )


def test_the_record_refuses_floats_and_forbidden_text():
    with pytest.raises(CanonicalisationError):
        _record(_evidence(), browser={"frameP95Ms": 16.7})
    for text in ("/Users/somebody/file", "Bearer abc", "x-api-token"):
        with pytest.raises(GateEvidenceError, match="no record may contain"):
            _record(_evidence(), reason=text)
    with pytest.raises(GateEvidenceError):
        digest_bound({"nested": [{"path": "/Users/x"}]})


def test_the_record_refuses_misordered_captures_and_unknown_conditions():
    captures = [
        {"label": label, "path": f"x/{label}.png", "byte_size": 1, "sha256": _CAPTURES[label]}
        for label in reversed(CAPTURE_LABELS)
    ]
    with pytest.raises(GateEvidenceError, match="route order"):
        _record(_evidence(), captures=captures)
    with pytest.raises(GateEvidenceError, match="authentication condition"):
        _record(_evidence(), authentication_condition="assumed")
    with pytest.raises(GateEvidenceError, match="calibrated against"):
        _record(_evidence(), predecessor_records=[])
    with pytest.raises(GateEvidenceError, match="does not claim"):
        _record(_evidence(), claims_not_made=[])


def test_the_corridor_bar_is_every_key_against_a_baseline_that_fails():
    failing_baseline = _record(
        {**_passing_measurements(), "readsAsInhabitedStreet": _no_at_start()}
    )["record"]
    candidate = _record(_evidence(), baseline=failing_baseline, baseline_path="baseline.json")
    comparison = candidate["record"]["baselineComparison"]
    assert candidate["record"]["verdict"] == "PASS"
    assert comparison["beatsBaseline"] is True
    assert comparison["baselineFailedKeys"] == ["readsAsInhabitedStreet"]
    assert (
        comparison["baselineRecordSha256"]
        == hashlib.sha256(canonical_json(failing_baseline)).hexdigest()
    )
    assert beats_baseline(candidate["record"], failing_baseline)
    assert not beats_baseline(failing_baseline, candidate["record"])

    one_no = _answers(_asked("start"), _asked("midpoint"), _asked("endpoint", _NO, "A cut."))
    weaker = _record(
        {**_passing_measurements(), "readsAsInhabitedStreet": one_no},
        baseline=failing_baseline,
        baseline_path="baseline.json",
    )
    assert weaker["record"]["verdict"] == "FAIL"
    assert weaker["record"]["baselineComparison"]["beatsBaseline"] is False

    # A baseline that already holds every key cannot be told from a corridor, so nothing passes.
    passing_baseline = _record(_evidence())["record"]
    tied = _record(_evidence(), baseline=passing_baseline, baseline_path="baseline.json")
    assert tied["record"]["verdict"] == "FAIL"
    assert tied["record"]["baselineComparison"]["baselineHoldsEveryKey"] is True
    assert not beats_baseline(tied["record"], passing_baseline)

    stale = copy.deepcopy(failing_baseline)
    stale["gate"]["keySet"] = RUBRIC_V1.key_set
    with pytest.raises(GateEvidenceError, match="not comparable"):
        _record(_evidence(), baseline=stale, baseline_path="baseline.json")
    scored = copy.deepcopy(failing_baseline)
    scored["gate"]["keys"]["readsAsInhabitedStreet"]["yesAnswers"] = 1
    del scored["hardPass"]["readsAsInhabitedStreet"]
    with pytest.raises(GateEvidenceError, match="nine-key hardPass"):
        beats_baseline(candidate["record"], scored)
    with pytest.raises(GateEvidenceError, match="names the baseline record's path"):
        _record(_evidence(), baseline=failing_baseline)


def test_the_rubric_names_a_judge_and_fixes_the_one_question():
    text = _RUBRIC.read_text(encoding="utf-8")
    assert f"Rubric version: {RUBRIC_VERSION}\n" in text
    assert f"Key set: `{GATE_KEY_SET_VERSION}`" in text
    assert RUBRIC_QUESTION in text
    assert RUBRIC_GUIDANCE in text
    assert WORDS_STORAGE in text
    assert ANSWER_REQUIREMENT in text
    assert f"`{NOT_ASKED}`" in text
    for _, question in RUBRIC_V1.questions:
        assert question not in text, "the rubric still asks a version 1 question"
    assert VERSION_2.question not in text, "the rubric still asks the version 2 question"
    assert VERSION_3.question not in text, "the rubric still asks the version 3 question"
    assert VERSION_4.question == RUBRIC_QUESTION, "version 5 changed what the judge is asked"
    assert TYPED_REPLY_RULE in text
    assert "counts only when its first word" not in text
    assert CARRIED_WORDS_NOTICE in text
    assert RUBRIC_GUIDANCE.index("real materials") < RUBRIC_GUIDANCE.index("ground-floor")
    assert "No model may score `readsAsInhabitedStreet`" in text
    for label, title in PICTURE_TITLES.items():
        assert f"| `{label}` | {title} |" in text
    for option in ANSWER_OPTIONS:
        assert f"**{option}**" in text
    for record in RETAINED_RECORDS:
        assert record.path in text
    assert "docs/evaluation/2026-09-15-flatiron-owned-district-baseline.json" in text
    assert "0 to 9" not in text and "score is the number" not in text
    match = re.search(r"^Named human judge: (.+)$", text, flags=re.MULTILINE)
    assert match is not None, "the rubric has no judge line"
    judge = match.group(1).strip()
    assert judge != "JUDGE NOT YET NAMED", "the rubric's judge has not been named by the operator"
    assert judge.casefold() not in {"operator", "the operator", "owner", "judge", "tbd"}


def test_the_judge_reads_exactly_the_rubrics_words_for_each_picture():
    text = _RUBRIC.read_text(encoding="utf-8")
    for index, label in enumerate(CAPTURE_LABELS, start=1):
        prompt = judge_prompt(label)
        title, question, guidance, requirement = prompt.split("\n\n")
        assert title == f"Picture {index} of 3"
        assert (question, guidance) == (RUBRIC_QUESTION, RUBRIC_GUIDANCE)
        assert requirement == ANSWER_REQUIREMENT
        assert question in text and guidance in text and requirement in text
    for answer in ("yes", "no"):
        wording = reason_follow_up(answer)
        assert wording == f"You answered {answer.capitalize()}. In a few words, why?"
        assert wording in text
    for wrong in ("Maybe", "Yes", _YES):
        with pytest.raises(ValueError, match="not an answer"):
            reason_follow_up(wrong)
    with pytest.raises(ValueError, match="not a route capture"):
        judge_prompt("overview")


_V2_RECORD = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v2.json"
_V3_RECORD = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v3.json"
_V4_RECORD = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v4.json"
_V5_RECORD = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v5.json"
_V5_ARTIFACTS = "docs/evaluation/artifacts/2026-09-16-visual-gate-key-reconciliation-v5"


def _writer(monkeypatch, root: Path):
    """The record writer, loaded as a module and pointed at a scratch document root."""
    spec = importlib.util.spec_from_file_location(
        "record_visual_gate_evidence_under_test", _ROOT / "scripts/record_visual_gate_evidence.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = root.resolve()
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "RECONCILIATION", root / _V5_RECORD)
    monkeypatch.setattr(module, "RUBRIC_COPY", root / _V5_ARTIFACTS / "visual-gate-rubric.md")
    return module


#: The record writer loaded once, for its own constants. A test that needs it pointed at a
#: document root loads its own copy through _writer, which is what every writer test below does.
_WRITER_CONSTANTS = importlib.util.module_from_spec(
    importlib.util.spec_from_file_location(
        "record_visual_gate_evidence_constants",
        _ROOT / "scripts/record_visual_gate_evidence.py",
    )
)
_WRITER_CONSTANTS.__loader__.exec_module(_WRITER_CONSTANTS)
RECORD_JUDGEMENT_KEYS = (
    *_WRITER_CONSTANTS.JUDGEMENT_KEYS,
    *_WRITER_CONSTANTS.ASKED_PICTURE_KEYS,
)


def _scratch_root(tmp_path: Path, rubric: bytes, v3_measurements_unchanged: bool = True) -> Path:
    """A document root holding the rubric and stubs of the reconciliation chain, v5 at its head."""
    root = tmp_path / "root"
    (root / _V5_ARTIFACTS).mkdir(parents=True)
    (root / "docs/visual-gate-rubric.md").write_bytes(rubric)
    (root / _V5_ARTIFACTS / "visual-gate-rubric.md").write_bytes(rubric)
    chain = {
        _V5_RECORD: {
            "judgedKey": {"rubricSha256": hashlib.sha256(rubric).hexdigest()},
            "supersedes": {
                "keySet": VERSION_4.key_set,
                "measurementsUnchanged": True,
                "path": _V4_RECORD,
            },
        },
        _V4_RECORD: {
            "supersedes": {
                "keySet": VERSION_3.key_set,
                "measurementsUnchanged": True,
                "path": _V3_RECORD,
            },
        },
        _V3_RECORD: {
            "supersedes": {
                "keySet": VERSION_2.key_set,
                "measurementsUnchanged": v3_measurements_unchanged,
                "path": _V2_RECORD,
            }
        },
        _V2_RECORD: {"supersedes": {"keySet": RUBRIC_V1.key_set, "path": "unused"}},
    }
    for relative, record in chain.items():
        (root / relative).write_text(json.dumps({"record": record}), encoding="utf-8")
    return root


def _judgement_file(path: Path, rubric: bytes, **changes) -> Path:
    judgement = {
        "profile": "exulanica.visual-gate-judgement/v3",
        "judge": "Glendon",
        "judgedOn": "2026-09-16",
        "rubric": "docs/visual-gate-rubric.md",
        "rubricSha256": hashlib.sha256(rubric).hexdigest(),
        "askedIn": "test",
        "options": list(ANSWER_OPTIONS),
        "pictures": [
            {
                "label": "start",
                "picture": "Picture 1 of 3",
                "prompt": judge_prompt("start"),
                "captureSha256": _CAPTURES["start"],
                "asked": True,
                "picked": _NO,
                "words": "Blocks, not a street.",
                "typedBy": "Glendon",
                "givenAt": "2026-09-16T12:00:00Z",
            },
            *(
                {
                    "label": label,
                    "picture": PICTURE_TITLES[label],
                    "captureSha256": _CAPTURES[label],
                    "asked": False,
                }
                for label in ("midpoint", "endpoint")
            ),
        ],
    }
    judgement.update(changes)
    path.write_text(json.dumps(judgement), encoding="utf-8")
    return path


def test_the_writer_refuses_a_rubric_the_reconciliation_did_not_fix(monkeypatch, tmp_path):
    rubric = _RUBRIC.read_bytes()
    root = _scratch_root(tmp_path, rubric)
    writer = _writer(monkeypatch, root)
    assert writer._rubric() == (rubric, hashlib.sha256(rubric).hexdigest())
    (root / "docs/visual-gate-rubric.md").write_bytes(rubric + b"\nOne more line.\n")
    with pytest.raises(SystemExit, match="is not the rubric"):
        writer._rubric()


def test_the_writer_refuses_a_judgement_not_asked_in_the_rubrics_words(monkeypatch, tmp_path):
    rubric = _RUBRIC.read_bytes()
    writer = _writer(monkeypatch, _scratch_root(tmp_path, rubric))
    good = _judgement_file(tmp_path / "good.json", rubric)
    answers, asked_as = writer._judgement(good, rubric)
    assert asked_as["prompts"] == {"start": judge_prompt("start")}
    value, detail = _decide(answers, rubric_sha256=hashlib.sha256(rubric).hexdigest())
    assert value is False and detail["judge"] == "Glendon"

    pictures = json.loads(good.read_text())["pictures"]
    reworded = copy.deepcopy(pictures)
    reworded[0]["prompt"] = "Picture 1 of 3\n\nIs this a nice street?"
    with pytest.raises(SystemExit, match="rubric's words"):
        writer._judgement(_judgement_file(tmp_path / "a.json", rubric, pictures=reworded), rubric)
    retitled = copy.deepcopy(pictures)
    retitled[1]["picture"] = "Picture 1 of 3"
    with pytest.raises(SystemExit, match="picture title"):
        writer._judgement(_judgement_file(tmp_path / "b.json", rubric, pictures=retitled), rubric)
    with pytest.raises(SystemExit, match="not the judge the rubric names"):
        writer._judgement(_judgement_file(tmp_path / "c.json", rubric, judge="Ada"), rubric)
    with pytest.raises(SystemExit, match="judgement"):
        writer._judgement(
            _judgement_file(tmp_path / "d.json", rubric, profile="exulanica.judgement/v1"), rubric
        )
    stale = _judgement_file(tmp_path / "e.json", rubric, rubricSha256=_SHA)
    answers, _ = writer._judgement(stale, rubric)
    with pytest.raises(GateEvidenceError, match="rubric digest mismatch"):
        _decide(answers, rubric_sha256=hashlib.sha256(rubric).hexdigest())
    for digest in (VERSION_3.rubric_sha256, VERSION_2.rubric_sha256):
        earlier = _judgement_file(tmp_path / "f.json", rubric, rubricSha256=digest)
        answers, _ = writer._judgement(earlier, rubric)
        with pytest.raises(GateEvidenceError, match="rubric digest mismatch"):
            _decide(answers, rubric_sha256=hashlib.sha256(rubric).hexdigest())
    fourth = _judgement_file(tmp_path / "g.json", rubric, rubricSha256=VERSION_4.rubric_sha256)
    answers, _ = writer._judgement(fourth, rubric)
    value, detail = _decide(answers, rubric_sha256=hashlib.sha256(rubric).hexdigest())
    assert value is False
    assert detail["answeredAgainst"]["rubricSha256"] == VERSION_4.rubric_sha256


def test_the_writer_accepts_a_superseded_key_set_only_when_its_measurements_are_unchanged(
    monkeypatch, tmp_path
):
    rubric = _RUBRIC.read_bytes()
    writer = _writer(monkeypatch, _scratch_root(tmp_path / "same", rubric))
    assert writer._key_sets_measured_alike() == {
        GATE_KEY_SET_VERSION,
        VERSION_4.key_set,
        VERSION_3.key_set,
        VERSION_2.key_set,
    }
    writer = _writer(monkeypatch, _scratch_root(tmp_path / "moved", rubric, False))
    assert writer._key_sets_measured_alike() == {
        GATE_KEY_SET_VERSION,
        VERSION_4.key_set,
        VERSION_3.key_set,
    }
    run = tmp_path / "run.json"
    run.write_text(
        json.dumps({"profile": "exulanica.visual-gate-run/v1", "keySet": VERSION_2.key_set}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="does not share"):
        writer._load_run(run)


def test_the_writer_reads_a_follow_up_exactly_as_it_was_asked(monkeypatch, tmp_path):
    rubric = _RUBRIC.read_bytes()
    writer = _writer(monkeypatch, _scratch_root(tmp_path, rubric))
    pictures = json.loads(_judgement_file(tmp_path / "base.json", rubric).read_text())["pictures"]
    pictures[0].update(
        {
            "picked": _NO,
            "words": None,
            "followUp": {
                "shown": reason_follow_up("no"),
                "words": "Flat colour everywhere.",
                "typedBy": "Glendon",
                "givenAt": "2026-09-16T12:01:00Z",
            },
        }
    )
    answers, asked_as = writer._judgement(
        _judgement_file(tmp_path / "follow.json", rubric, pictures=pictures), rubric
    )
    assert asked_as["followUps"] == {"start": reason_follow_up("no")}
    value, detail = _decide(answers, rubric_sha256=hashlib.sha256(rubric).hexdigest())
    assert value is False
    assert [item["words_sha256"] for item in detail["pictures"][0]["reason"]] == [
        words_fingerprint("Flat colour everywhere.")["words_sha256"]
    ]
    pictures[0]["followUp"]["shown"] = "You said no. Why not?"
    answers, _ = writer._judgement(
        _judgement_file(tmp_path / "reworded.json", rubric, pictures=pictures), rubric
    )
    with pytest.raises(GateEvidenceError, match="rubric's words"):
        _decide(answers, rubric_sha256=hashlib.sha256(rubric).hexdigest())


def test_the_writer_reads_carried_words_under_the_line_that_was_shown(monkeypatch, tmp_path):
    rubric = _RUBRIC.read_bytes()
    writer = _writer(monkeypatch, _scratch_root(tmp_path, rubric))
    pictures = json.loads(_judgement_file(tmp_path / "base.json", rubric).read_text())["pictures"]
    pictures[0].update(
        {
            "words": None,
            "notice": CARRIED_WORDS_NOTICE,
            "shown": f"{CARRIED_WORDS_NOTICE}\n\n{judge_prompt('start')}",
            "carried": [
                {
                    "words": _EARLIER,
                    "typedBy": "Glendon",
                    "rubricVersion": 3,
                    "rubricSha256": VERSION_3.rubric_sha256,
                    "givenAt": _EARLIER_AT,
                    "givenAs": _EARLIER_AS,
                }
            ],
        }
    )
    answers, asked_as = writer._judgement(
        _judgement_file(tmp_path / "carried.json", rubric, pictures=pictures), rubric
    )
    assert asked_as["shown"]["start"].startswith(CARRIED_WORDS_NOTICE)
    value, detail = _decide(answers, rubric_sha256=hashlib.sha256(rubric).hexdigest())
    assert value is False
    assert (
        detail["pictures"][0]["reason"][0]["words_sha256"]
        == (words_fingerprint(_EARLIER)["words_sha256"])
    )
    pictures[0]["shown"] = judge_prompt("start")
    with pytest.raises(SystemExit, match="shown something other"):
        writer._judgement(
            _judgement_file(tmp_path / "unshown.json", rubric, pictures=pictures), rubric
        )


def test_the_writer_keeps_the_judges_words_in_the_private_companion(monkeypatch, tmp_path):
    rubric = _RUBRIC.read_bytes()
    root = _scratch_root(tmp_path, rubric)
    writer = _writer(monkeypatch, root)
    answers, _ = writer._judgement(_judgement_file(tmp_path / "j.json", rubric), rubric)
    path, companion = judge_words_file(_RECORD_PATH, answers)
    writer._write_private(path, companion, replace=False)
    assert (root / path).read_bytes() == companion
    assert (root / path).stat().st_mode & 0o077 == 0
    writer._write_private(path, companion, replace=False)
    with pytest.raises(SystemExit, match="other words"):
        writer._write_private(path, companion + b" ", replace=False)
    assert writer._private_words(companion) == (["Blocks, not a street."], [])
    leak = root / "leak.json"
    with pytest.raises(SystemExit, match="judge's words"):
        writer._write(
            leak,
            {"record": {"note": "blocks, NOT a street"}},
            replace=False,
            private=["Blocks, not a street."],
        )
    assert not leak.exists()


def test_the_retained_baseline_scores_all_nine_keys_against_the_rubric_it_names():
    if not _BASELINE.is_file():
        pytest.fail(f"{_BASELINE.relative_to(_ROOT)} is a phase 0 deliverable and is missing")
    record = json.loads(_BASELINE.read_bytes())["record"]
    assert set(record["hardPass"]) == set(CANONICAL_SPELLINGS)
    assert record["authenticationCondition"] in {"credentialed-api", "vite-preview-api"}
    assert [capture["label"] for capture in record["captures"]] == list(CAPTURE_LABELS)
    bindings = {item["path"]: item["record_sha256"] for item in record["predecessor_records"]}
    for retained in RETAINED_RECORDS:
        assert bindings[retained.path] == retained.record_sha256
    assert record["gate"]["keySet"] == GATE_KEY_SET_VERSION
    judged = record["gate"]["keys"]["readsAsInhabitedStreet"]
    rubric = _RUBRIC.read_text(encoding="utf-8")
    assert f"Named human judge: {judged['judge']}\n" in rubric
    rubric_sha = hashlib.sha256(_RUBRIC.read_bytes()).hexdigest()
    assert judged["rubricSha256"] == rubric_sha
    # Version 5 composition, decided again from what the record carries and nothing else.
    assert judged["rubricVersion"] == RUBRIC_VERSION
    assert judged["typedReplyRule"] == TYPED_REPLY_RULE
    answered = judged["answeredAgainst"]
    assert (answered["rubricVersion"], answered["rubricSha256"]) in {
        (RUBRIC_VERSION, rubric_sha),
        (VERSION_4.rubric_version, VERSION_4.rubric_sha256),
    }
    assert (judged["question"], judged["guidance"]) == (RUBRIC_QUESTION, RUBRIC_GUIDANCE)
    assert [entry["picture"] for entry in judged["pictures"]] == list(PICTURE_TITLES.values())
    value = recompose_judged(judged)
    assert value is judged["value"] is record["hardPass"]["readsAsInhabitedStreet"]
    binding = record["judgeWords"]
    assert binding["path"] == ".exulanica/judge-words/" + _BASELINE.name
    assert binding["tracked"] is False
    assert judged["requirement"] == ANSWER_REQUIREMENT
    for entry in judged["pictures"]:
        if entry["state"] == "answered":
            assert record["judgement"]["prompts"][entry["label"]] == judge_prompt(entry["label"])
            assert entry["typedBy"] == judged["judge"]
            assert entry["reason"], "an answer is recorded with its reason"
            for reason in entry["reason"]:
                assert reason["words_private"] is True and reason["words_bytes"] > 0
                assert reason["rubricVersion"] <= RUBRIC_VERSION
                assert reason["givenAt"] and reason["givenAs"].strip()
            if entry["picked"] is None:
                assert (entry["answer"], entry["readFrom"]) == ("no", "the typed-reply rule")
            prompt = judge_prompt(entry["label"])
            notice = entry.get("noticeAboveTheQuestion")
            shown = prompt if notice is None else f"{notice}\n\n{prompt}"
            assert record["judgement"]["shown"][entry["label"]] == shown
            if entry.get("carried"):
                assert notice == CARRIED_WORDS_NOTICE
                assert entry["answer"] == "no" or any(
                    reason["from"] != "earlier words" for reason in entry["reason"]
                )
            if "followUp" in entry:
                asked = record["judgement"]["followUps"][entry["label"]]
                assert asked == entry["followUp"]["asked"] == reason_follow_up(entry["answer"])
    for spelling, detail in record["gate"]["keys"].items():
        if detail["evidenceKind"] == "mechanical":
            assert decide_mechanical(spelling, detail["decidedBy"]) is record["hardPass"][spelling]
    assert record["claimsNotMade"]
    assert any("No model judged any picture" in claim for claim in record["claimsNotMade"])


def test_the_retained_baseline_is_decided_again_from_its_private_companion():
    """The judge's words exist only on the machine they were given on, so this check runs there."""
    if not _BASELINE.is_file():
        pytest.skip("there is no Flatiron baseline record to decide again")
    if not _COMPANION.is_file():
        pytest.skip(
            "the judge's words are kept only on the machine they were given on, and this "
            "checkout has no private companion for the Flatiron baseline"
        )
    record = json.loads(_BASELINE.read_bytes())["record"]
    data = _COMPANION.read_bytes()
    binding = record["judgeWords"]
    assert (len(data), hashlib.sha256(data).hexdigest()) == (
        binding["byte_size"],
        binding["sha256"],
    )
    judged = record["gate"]["keys"]["readsAsInhabitedStreet"]
    words = words_from_companion(json.loads(data), _BASELINE_PATH)
    bound = {capture["label"]: capture["sha256"] for capture in record["captures"]}
    value, redecided = decide_judged(
        judged_answers_from_record(judged, words),
        rubric_sha256=hashlib.sha256(_RUBRIC.read_bytes()).hexdigest(),
        captures=bound,
    )
    assert value is record["hardPass"]["readsAsInhabitedStreet"]
    assert redecided == judged


# ---- the corridor verb ------------------------------------------------------------------------
#
# The judgement given on 2026-09-19 was refused, so the verb's accepted path has no real input to
# exercise it. These tests give it one: the real harness run, which the refusal record retains, and
# a judgement whose words are INVENTED. No test here holds anything the judge wrote.

_REFUSED_RECORD = "docs/evaluation/2026-09-19-corridor-composed-world-judgement-refused.json"
_REFUSED_ARTIFACTS = (
    _ROOT / "docs/evaluation/artifacts/2026-09-19-corridor-composed-world-judgement-refused"
)
_SUPPLEMENT = "docs/evaluation/2026-09-19-corridor-composed-world-private-store.json"
_CORRIDOR_RECORD = "docs/evaluation/2026-09-19-corridor-under-test.json"
#: Invented. Every word of it is mine, and none of it is any judge's.
_INVENTED = "Invented placeholder words standing in for a reason nobody gave."


def _corridor_writer(monkeypatch, tmp_path: Path):
    """The writer pointed at a document root holding the real rubric, chain, baseline and store."""
    root = tmp_path / "root"
    (root / "docs/evaluation").mkdir(parents=True)
    for name in ("visual-gate-rubric.md", "visual-gate-corridor-walk.md"):
        shutil.copyfile(_ROOT / "docs" / name, root / "docs" / name)
    for path in (_ROOT / "docs/evaluation").glob("*.json"):
        shutil.copyfile(path, root / "docs/evaluation" / path.name)
    copy = root / _V5_ARTIFACTS / "visual-gate-rubric.md"
    copy.parent.mkdir(parents=True)
    shutil.copyfile(_ROOT / _V5_ARTIFACTS / "visual-gate-rubric.md", copy)
    writer = _writer(monkeypatch, root)
    monkeypatch.setattr(writer, "BASELINE", root / _BASELINE_PATH)
    return writer, root


def _corridor_run(tmp_path: Path, **changes) -> Path:
    """The real harness run the refusal record retains, laid out as the harness wrote it."""
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    run = json.loads((_REFUSED_ARTIFACTS / "run.json").read_bytes())
    if changes:
        # A changed run is different bytes, so the record that states its store has to bind those
        # bytes; _rebind_supplement does that. An unchanged run is copied byte for byte, which is
        # what makes the unchanged case a real check of the binding.
        for name, value in changes.items():
            run[name] = value
        (run_dir / "composed-run.json").write_text(json.dumps(run), encoding="utf-8")
    else:
        shutil.copyfile(_REFUSED_ARTIFACTS / "run.json", run_dir / "composed-run.json")
    shutil.copyfile(_REFUSED_ARTIFACTS / "route-trace.json", run_dir / "composed-trace.json")
    for index, capture in enumerate(run["captures"], start=1):
        shutil.copyfile(
            _REFUSED_ARTIFACTS / f"capture-{index:02d}-route-{capture['label']}.png",
            run_dir / capture["file"],
        )
    return run_dir / "composed-run.json"


def _rebind_supplement(root: Path, run_path: Path) -> None:
    """Point the store record at a run the test changed, so only the change under test differs."""
    document = json.loads((root / _SUPPLEMENT).read_bytes())
    data = run_path.read_bytes()
    document["record"]["binds"]["run_record"] = {
        "bytes": len(data),
        "name": run_path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    document["record"]["binds"]["keys"] = json.loads(data)["keys"]
    document["record_sha256"] = hashlib.sha256(canonical_json(document["record"])).hexdigest()
    (root / _SUPPLEMENT).write_text(json.dumps(document), encoding="utf-8")


def _corridor_judgement_file(tmp_path: Path, name: str = "judgement.json", **changes) -> Path:
    """A judgement of the three real captures, picked yes three times, with invented words."""
    run = json.loads((_REFUSED_ARTIFACTS / "run.json").read_bytes())
    document = {
        "profile": "exulanica.visual-gate-judgement/v3",
        "judge": "Glendon",
        "judgedOn": "2026-09-19",
        "rubric": "docs/visual-gate-rubric.md",
        # Version 4's digest, not the rubric on disk: see the comparability test below.
        "rubricSha256": VERSION_4.rubric_sha256,
        "askedIn": "a test of the writer; every word the judge is said to have typed is invented",
        "options": list(ANSWER_OPTIONS),
        "pictures": [
            {
                "label": capture["label"],
                "picture": PICTURE_TITLES[capture["label"]],
                "prompt": judge_prompt(capture["label"]),
                "captureSha256": capture["sha256"],
                "asked": True,
                "picked": _YES,
                "words": f"{_INVENTED} Picture {index}.",
                "typedBy": "Glendon",
                "givenAt": f"2026-09-19T08:3{index}:00Z",
            }
            for index, capture in enumerate(run["captures"])
        ],
    }
    document.update(changes)
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    assert _INVENTED in path.read_text(encoding="utf-8")
    return path


def _corridor(writer, run: Path, judgement: Path, record: str = _CORRIDOR_RECORD, **changes):
    arguments = argparse.Namespace(
        date="2026-09-19",
        run=str(run),
        judgement=str(judgement),
        supplementary=_SUPPLEMENT,
        record=record,
        measured_at="bd4db95a",
        replace=False,
    )
    for name, value in changes.items():
        setattr(arguments, name, value)
    return writer.corridor(arguments)


def _all_true(run: dict) -> dict:
    """The same run with the two keys it fails measured as holding, harness and numbers together."""
    mechanical = copy.deepcopy(run["mechanical"])
    mechanical["noCutsOrFloatingGeometry"]["componentsDetachedFromSupport"] = 0
    mechanical["practicalBrowserBudget"]["maxDrawCalls"] = MELBOURNE_ENVELOPE["maxDrawCalls"]
    keys = {**run["keys"], "noCutsOrFloatingGeometry": True, "practicalBrowserBudget": True}
    return {"mechanical": mechanical, "keys": keys}


def test_the_corridor_verb_writes_a_gate_record_when_the_judgement_holds(monkeypatch, tmp_path):
    writer, root = _corridor_writer(monkeypatch, tmp_path)
    assert _corridor(writer, _corridor_run(tmp_path), _corridor_judgement_file(tmp_path)) == 0
    document = json.loads((root / _CORRIDOR_RECORD).read_bytes())
    record = document["record"]
    assert record["profile"] == writer.CORRIDOR_PROFILE
    assert record["target"] == "generated-tile-evaluation"
    assert set(record["hardPass"]) == set(CANONICAL_SPELLINGS)
    assert record["hardPass"][JUDGED_KEY] is True
    assert record["gate"]["failedKeys"] == ["noCutsOrFloatingGeometry", "practicalBrowserBudget"]
    assert record["verdict"] == "FAIL"
    assert record["baselineComparison"]["beatsBaseline"] is False
    assert record["baselineComparison"]["baselineHoldsEveryKey"] is False
    assert document["record_sha256"] == hashlib.sha256(canonical_json(record)).hexdigest()
    # The captures the judge answered about are bound, and they are the ones the run took.
    run = json.loads((_REFUSED_ARTIFACTS / "run.json").read_bytes())
    assert [capture["sha256"] for capture in record["captures"]] == [
        capture["sha256"] for capture in run["captures"]
    ]


def test_the_corridor_verb_can_say_pass_so_the_bar_is_not_a_constant(monkeypatch, tmp_path):
    writer, root = _corridor_writer(monkeypatch, tmp_path)
    run = json.loads((_REFUSED_ARTIFACTS / "run.json").read_bytes())
    run_path = _corridor_run(tmp_path, **_all_true(run))
    _rebind_supplement(root, run_path)
    assert _corridor(writer, run_path, _corridor_judgement_file(tmp_path)) == 0
    record = json.loads((root / _CORRIDOR_RECORD).read_bytes())["record"]
    assert all(record["hardPass"].values())
    assert record["verdict"] == "PASS"
    assert record["baselineComparison"]["beatsBaseline"] is True


def test_the_corridor_verb_refuses_when_it_and_the_harness_disagree(monkeypatch, tmp_path):
    writer, root = _corridor_writer(monkeypatch, tmp_path)
    run = json.loads((_REFUSED_ARTIFACTS / "run.json").read_bytes())
    keys = {**run["keys"], "usefulEyeLevelMovement": False}
    with pytest.raises(SystemExit, match="the record builder decides"):
        _corridor(writer, _corridor_run(tmp_path, keys=keys), _corridor_judgement_file(tmp_path))
    assert not (root / _CORRIDOR_RECORD).exists()


def test_a_judgement_the_rubric_does_not_allow_is_recorded_and_not_scored(monkeypatch, tmp_path):
    writer, root = _corridor_writer(monkeypatch, tmp_path)
    departures = ["Picture 2 was asked twice.", "The pictures were shown together first."]
    judgement = _corridor_judgement_file(tmp_path, departuresFromProtocol=departures)
    assert _corridor(writer, _corridor_run(tmp_path), judgement) == 1
    record = json.loads((root / _CORRIDOR_RECORD).read_bytes())["record"]
    assert record["profile"] == writer.REFUSED_PROFILE
    assert record["judgedKey"]["state"] == "refused"
    assert record["judgedKey"]["value"] is None
    assert record["judgedKey"]["departuresTheSessionRecorded"] == departures
    # It is not a gate record and nothing can read a verdict out of it.
    assert "hardPass" not in record and "verdict" not in record and "gate" not in record
    # It reports no answer: the words "yes" and "no" appear nowhere as an answer value.
    assert "picked" not in json.dumps(record)
    # And it binds the three pictures, which is what a proper re-ask has to be about.
    assert len(record["captures"]) == 3
    assert all(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in record["captures"])


def test_every_rubric_clause_a_refusal_rests_on_is_in_the_rubric(monkeypatch, tmp_path):
    writer, root = _corridor_writer(monkeypatch, tmp_path)
    rubric = _RUBRIC.read_bytes()
    clauses = writer._rubric_clauses(rubric)
    assert len(clauses) == len(writer.REFUSAL_CLAUSES)
    flat = " ".join(rubric.decode("utf-8").split())
    assert all(" ".join(item["rubricSays"].split()) in flat for item in clauses)
    (root / "docs/visual-gate-rubric.md").write_bytes(
        rubric.replace(b"Pictures are never shown together", b"Pictures may be shown together")
    )
    with pytest.raises(SystemExit, match="does not carry"):
        writer._rubric_clauses((root / "docs/visual-gate-rubric.md").read_bytes())


@pytest.mark.parametrize("name", RECORD_JUDGEMENT_KEYS)
def test_every_key_the_reader_names_is_a_key_it_actually_needs(monkeypatch, tmp_path, name):
    """Remove one key from a complete judgement and the reader has to name it, not crash."""
    writer, _ = _corridor_writer(monkeypatch, tmp_path)
    document = json.loads(_corridor_judgement_file(tmp_path).read_text())
    if name in document:
        del document[name]
    else:
        del document["pictures"][0][name]
    path = tmp_path / "short.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    said = writer._judgement_shape(json.loads(path.read_bytes()))
    assert any(name in line for line in said), said


def test_the_corridor_verb_refuses_a_store_record_that_binds_other_bytes(monkeypatch, tmp_path):
    writer, root = _corridor_writer(monkeypatch, tmp_path)
    document = json.loads((root / _SUPPLEMENT).read_bytes())
    document["record"]["binds"]["captures"][0]["sha256"] = _SHA
    document["record_sha256"] = hashlib.sha256(canonical_json(document["record"])).hexdigest()
    (root / _SUPPLEMENT).write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SystemExit, match="the file copied here is"):
        _corridor(writer, _corridor_run(tmp_path), _corridor_judgement_file(tmp_path))


def test_the_corridor_verb_refuses_a_store_record_whose_digest_is_not_its_own(
    monkeypatch, tmp_path
):
    writer, root = _corridor_writer(monkeypatch, tmp_path)
    document = json.loads((root / _SUPPLEMENT).read_bytes())
    document["record_sha256"] = _SHA
    (root / _SUPPLEMENT).write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SystemExit, match="states record_sha256"):
        _corridor(writer, _corridor_run(tmp_path), _corridor_judgement_file(tmp_path))


def test_the_writer_refuses_a_record_carrying_words_it_was_told_are_private(monkeypatch, tmp_path):
    """The private-words check, controlled with a string built here rather than found anywhere."""
    writer, root = _corridor_writer(monkeypatch, tmp_path)
    secret = "A sentence written in this test and nowhere else, to see the check fire."
    target = root / "docs/evaluation/2026-09-19-control.json"
    with pytest.raises(SystemExit, match="carries the judge's words"):
        writer._write(target, {"note": secret}, replace=False, private=[secret])
    assert not target.exists()
    writer._write(target, {"note": "Something else entirely."}, replace=False, private=[secret])
    assert json.loads(target.read_bytes()) == {"note": "Something else entirely."}


def test_the_judgement_words_collector_keeps_what_it_does_not_recognise(monkeypatch, tmp_path):
    """It collects by default: a reason under a field name nobody listed is still collected."""
    writer, _ = _corridor_writer(monkeypatch, tmp_path)
    rubric = _RUBRIC.read_bytes()
    path = tmp_path / "oddly-spelled.json"
    path.write_text(
        json.dumps({"answers": [{"whyTheyPickedIt": _INVENTED}], "profile": "x"}),
        encoding="utf-8",
    )
    assert writer._judgement_words(path, rubric) == [_INVENTED]
    # And it does not collect what the judge was shown, which the record carries.
    shown = tmp_path / "shown.json"
    shown.write_text(json.dumps({"prompt": judge_prompt("start")}), encoding="utf-8")
    assert writer._judgement_words(shown, rubric) == []


def test_a_corridor_judged_under_the_current_rubric_is_read_against_the_baseline(
    monkeypatch, tmp_path
):
    """The comparison the gate refused until 2026-09-19, and the one it must still refuse.

    The baseline's judge answered under rubric version 4 and a fresh judgement is given under
    version 5, which the rubric declares shows the judge the same words. Both must compare. A
    digest _answered_version does not reconcile must not.
    """
    writer, root = _corridor_writer(monkeypatch, tmp_path)
    current = hashlib.sha256(_RUBRIC.read_bytes()).hexdigest()
    baseline = json.loads((root / _BASELINE_PATH).read_bytes())["record"]
    answered = baseline["gate"]["keys"][JUDGED_KEY]["answeredAgainst"]
    assert answered["rubricSha256"] == VERSION_4.rubric_sha256 != current

    equivalence = writer._rubric_equivalence(baseline, current)
    assert equivalence["theGateReconcilesThem"] is True
    assert equivalence["baselineAnsweredAgainst"] == VERSION_4.rubric_sha256
    assert equivalence["aFreshJudgementAnswersAgainst"] == current

    # Both directions end to end: a version 5 judgement and a version 4 one both write a record.
    run_path = _corridor_run(tmp_path)
    for index, digest in enumerate((current, VERSION_4.rubric_sha256)):
        record = f"docs/evaluation/2026-09-19-corridor-under-test-{index}.json"
        judgement = _corridor_judgement_file(tmp_path, name=f"j{index}.json", rubricSha256=digest)
        assert _corridor(writer, run_path, judgement, record=record) == 0
        written = json.loads((root / record).read_bytes())["record"]
        assert written["baselineComparison"]["baselineRecord"] == _BASELINE_PATH

    # And no wider. A third digest never reaches the comparison: decide_judged refuses it first,
    # so the verb records a refusal and scores nothing. That the COMPARISON also refuses it is the
    # next test, which asks _comparable directly rather than through a judgement it would reject.
    judgement = _corridor_judgement_file(tmp_path, name="third.json", rubricSha256=_SHA)
    assert _corridor(writer, run_path, judgement, record=_CORRIDOR_RECORD) == 1
    refused = json.loads((root / _CORRIDOR_RECORD).read_bytes())["record"]
    assert refused["profile"] == writer.REFUSED_PROFILE
    assert any("rubric digest mismatch" in line for line in refused["judgedKey"]["refusedBecause"])


def test_the_comparison_refuses_a_rubric_the_answer_version_rule_does_not_reconcile():
    """_comparable applies one equivalence and not a licence to compare any two rubrics."""
    current = hashlib.sha256(_RUBRIC.read_bytes()).hexdigest()

    def holder(written, answered_against, target="generated-tile-evaluation"):
        return {
            "target": target,
            "gate": {
                "keySet": GATE_KEY_SET_VERSION,
                "keys": {
                    JUDGED_KEY: {
                        "rubricSha256": written,
                        "answeredAgainst": {"rubricSha256": answered_against},
                    }
                },
            },
        }

    baseline = holder(current, VERSION_4.rubric_sha256, target="owned-district")
    visual_gate._comparable(holder(current, current), baseline)
    visual_gate._comparable(holder(current, VERSION_4.rubric_sha256), baseline)
    for refused in (VERSION_3.rubric_sha256, VERSION_2.rubric_sha256, _SHA):
        with pytest.raises(GateEvidenceError, match="does not reconcile"):
            visual_gate._comparable(holder(current, refused), baseline)
    # Two records written with different rubrics are not comparable whatever they answered.
    with pytest.raises(GateEvidenceError, match="a comparison needs one rubric"):
        visual_gate._comparable(holder(_RUBRIC_SHA, _RUBRIC_SHA), baseline)


def test_the_re_ask_this_record_states_is_one_the_writer_would_accept(monkeypatch, tmp_path):
    """Every ask the procedure states is fed back through the reader, which has to accept it."""
    writer, _ = _corridor_writer(monkeypatch, tmp_path)
    procedure = writer._re_ask()
    run = json.loads((_REFUSED_ARTIFACTS / "run.json").read_bytes())
    pictures = [
        {
            "label": capture["label"],
            "picture": PICTURE_TITLES[capture["label"]],
            "prompt": procedure["theAsk"][capture["label"]],
            "captureSha256": capture["sha256"],
            "asked": True,
            "picked": _YES,
            "words": None,
            "typedBy": "Glendon",
            "givenAt": f"2026-09-19T09:3{index}:00Z",
            "followUp": {
                "shown": procedure["theFollowUp"]["yes"],
                "words": f"{_INVENTED} Picture {index}.",
                "typedBy": "Glendon",
                "givenAt": f"2026-09-19T09:3{index}:30Z",
            },
        }
        for index, capture in enumerate(run["captures"])
    ]
    path = _corridor_judgement_file(tmp_path, name="re-ask.json", pictures=pictures)
    answers, _ = writer._judgement(path, _RUBRIC.read_bytes())
    value, _ = _decide(
        answers,
        rubric_sha256=hashlib.sha256(_RUBRIC.read_bytes()).hexdigest(),
        captures={capture["label"]: capture["sha256"] for capture in run["captures"]},
    )
    assert value is True


def test_the_refused_record_says_which_pictures_the_judgement_was_about(monkeypatch, tmp_path):
    """And the check can say no, which is the only thing that makes its yes worth reading."""
    writer, root = _corridor_writer(monkeypatch, tmp_path)
    run_path = _corridor_run(tmp_path)
    run = json.loads(run_path.read_bytes())
    captures = [
        {"label": capture["label"], "sha256": capture["sha256"]} for capture in run["captures"]
    ]
    about = _corridor_judgement_file(tmp_path, departuresFromProtocol=["Asked wrongly."])
    named = writer._names_the_captures(about, captures)
    assert named["everyBoundCaptureIsNamedInTheJudgement"] is True

    document = json.loads(about.read_text())
    document["pictures"][1]["captureSha256"] = _SHA
    elsewhere = tmp_path / "about-another-picture.json"
    elsewhere.write_text(json.dumps(document), encoding="utf-8")
    named = writer._names_the_captures(elsewhere, captures)
    assert named["everyBoundCaptureIsNamedInTheJudgement"] is False
    assert named["byPicture"] == {"start": True, "midpoint": False, "endpoint": True}

    # And the record carries the answer rather than the question.
    assert _corridor(writer, run_path, about) == 1
    record = json.loads((root / _CORRIDOR_RECORD).read_bytes())["record"]
    assert (
        record["theRefusedJudgementWasAboutThesePictures"]["everyBoundCaptureIsNamedInTheJudgement"]
        is True
    )
