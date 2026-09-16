"""The visual gate record builder: it decides, it refuses, and it can say FAIL.

A gate that cannot be made to fail in a test is not a gate. Every refusal below is a way a record
could otherwise have been written with less evidence than its keys claim. The judged key follows
rubric version 3: one question per picture, in route order, and the first no decides. The judge's
words never enter a public record, which carries their SHA-256 and byte count; a private companion
holds them.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.errors import CanonicalisationError
from exulanica.evaluation.gate_keys import (
    ANSWER_OPTIONS,
    ANSWER_REQUIREMENT,
    CANONICAL_SPELLINGS,
    CAPTURE_LABELS,
    GATE_KEY_SET_VERSION,
    NOT_ASKED,
    PICTURE_TITLES,
    RETAINED_RECORDS,
    RUBRIC_GUIDANCE,
    RUBRIC_QUESTION,
    RUBRIC_V1,
    RUBRIC_VERSION,
    THRESHOLDS,
    VERSION_2,
    WORDS_STORAGE,
    UnknownGateKey,
    judge_prompt,
    reason_follow_up,
)
from exulanica.evaluation.visual_gate import (
    JUDGE_WORDS_PROFILE,
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
    visual_gate_record,
    words_fingerprint,
    words_from_companion,
)

_ROOT = Path(__file__).resolve().parents[1]
_RUBRIC = _ROOT / "docs/visual-gate-rubric.md"
_BASELINE_PATH = "docs/evaluation/2026-09-15-flatiron-owned-district-baseline.json"
_BASELINE = _ROOT / _BASELINE_PATH
_COMPANION = _ROOT / ".exulanica/judge-words/2026-09-15-flatiron-owned-district-baseline.json"
_RECORD_PATH = "docs/evaluation/2026-09-16-visual-gate-test.json"
_GIVEN_AT = "2026-09-16T12:00:00Z"
_SHA = "0" * 63 + "1"
_RUBRIC_SHA = "0" * 63 + "2"
_CAPTURES = {label: f"{index:064x}" for index, label in enumerate(CAPTURE_LABELS, start=3)}
_JUDGE = "Ada Example"
_REASON = "The ground floors read as a bakery, a pharmacy and a lobby, and the block runs on."


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
    picked: str | None = "Yes",
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
        _asked("start", "No", "Plain coloured blocks; I cannot name a single shop."),
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
            _asked("endpoint", "No", "The far end is one flat wall with nothing behind it."),
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
            _asked("start"), _asked("midpoint", "No", "It stops at a hole."), _unasked("endpoint")
        )
    )
    assert (value, detail["decisiveNo"]) == (False, "midpoint")

    value, detail = _decide(
        _answers(_asked("start"), _asked("midpoint"), _asked("endpoint", "No", "Blank walls."))
    )
    assert (value, detail["decisiveNo"]) == (False, "endpoint")

    value, detail = _decide(_answers())
    assert (value, detail["decisiveNo"]) == (True, None)
    assert [entry["picture"] for entry in detail["pictures"]] == list(PICTURE_TITLES.values())
    assert (detail["question"], detail["guidance"]) == (RUBRIC_QUESTION, RUBRIC_GUIDANCE)
    assert detail["options"] == list(ANSWER_OPTIONS) == ["Yes", "No"]


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
    for later in (_asked("midpoint"), _asked("midpoint", "No", "Still blocks.")):
        answers = _answers(
            _asked("start", "No", "Coloured shapes, not a street."), later, _unasked("endpoint")
        )
        with pytest.raises(GateEvidenceError, match="after the decisive no"):
            _decide(answers)
    answers = _answers(
        _asked("start", "No", "Coloured shapes, not a street."),
        _unasked("midpoint"),
        _asked("endpoint"),
    )
    with pytest.raises(GateEvidenceError, match="after the decisive no"):
        _decide(answers)


@pytest.mark.parametrize(
    ("picked", "words"),
    [
        ("No", None),
        ("No", ""),
        ("No", "   "),
        ("No", "No"),
        ("No", "no."),
        ("Yes", "YES!"),
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
        ("No", "Plain blocks.", "Claude", "not typed by the judge"),
        ("No", "Plain blocks.", None, "not typed by the judge"),
        ("No", "Plain blocks.", "Somebody Else", "not typed by the judge"),
        ("No", "Plain blocks.", "ada example", "not typed by the judge"),
        ("Yes (Recommended)", "It looks lived in.", _JUDGE, "not one of the options"),
        ("yes", "It looks lived in.", _JUDGE, "not one of the options"),
        ("Other", "It looks lived in.", _JUDGE, "not one of the options"),
        (None, "Just coloured shapes, no shops at all.", _JUDGE, "nothing is inferred"),
        (None, "Nobody could live here.", _JUDGE, "nothing is inferred"),
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


def test_a_typed_reply_counts_only_by_the_answer_word_it_opens_with():
    value, detail = _decide(
        _answers(
            _asked("start", None, "NO IT IS JUST COLOURED SHAPES"),
            _unasked("midpoint"),
            _unasked("endpoint"),
        )
    )
    assert value is False
    entry = detail["pictures"][0]
    assert (entry["picked"], entry["answer"]) == (None, "no")
    assert entry["words_sha256"] == hashlib.sha256(b"NO IT IS JUST COLOURED SHAPES").hexdigest()
    value, detail = _decide(
        _answers(
            *(
                _asked(label, None, "yes, shops and a lobby I could name")
                for label in CAPTURE_LABELS
            )
        )
    )
    assert value is True
    assert {entry["answer"] for entry in detail["pictures"]} == {"yes"}


def test_the_judges_words_are_fingerprinted_exactly_as_typed_and_kept_out_of_the_record():
    words = "  omg it is just shapes\nno shops, no people  "
    answers = _answers(_asked("start", "No", words), _unasked("midpoint"), _unasked("endpoint"))
    _, detail = _decide(answers)
    entry = detail["pictures"][0]
    data = words.encode("utf-8")
    assert (entry["words_sha256"], entry["words_bytes"], entry["words_private"]) == (
        hashlib.sha256(data).hexdigest(),
        len(data),
        True,
    )
    assert entry["reason"] == words_fingerprint(words)
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
    assert (reply["words"], reply["givenAt"], reply["picked"]) == (words, _GIVEN_AT, "No")


def test_a_reply_that_does_not_say_when_it_was_given_is_refused():
    for given_at in (None, "2026-09-16", "2026-09-16 12:00:00", "2026-09-15T23:59:59Z"):
        answers = _answers(
            _asked("start", "No", "Blocks, not a street.", given_at=given_at),
            _unasked("midpoint"),
            _unasked("endpoint"),
        )
        with pytest.raises(GateEvidenceError, match="given"):
            _decide(answers)
    late = dataclasses.replace(
        _without_words("start", "No"),
        follow_up=ReasonFollowUp(
            shown=reason_follow_up("No"), words="Flat blocks.", typed_by=_JUDGE, given_at=None
        ),
    )
    with pytest.raises(GateEvidenceError, match="given"):
        _decide(_answers(late, _unasked("midpoint"), _unasked("endpoint")))
    stray = dataclasses.replace(_unasked("midpoint"), given_at=_GIVEN_AT)
    with pytest.raises(GateEvidenceError, match="cannot carry an answer"):
        _decide(_answers(_asked("start", "No", "Blocks."), stray, _unasked("endpoint")))


def test_a_public_record_never_carries_the_judges_words():
    words = "Plain coloured blocks; I cannot name a single shop."
    answers = _answers(_asked("start", "No", words), _unasked("midpoint"), _unasked("endpoint"))
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
    follow = _without_words("start", "No", "Every wall is one flat grey.")
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


def _without_words(
    label: str, picked: str = "Yes", reply: str | None = "Brick fronts, a bakery."
) -> PictureAnswer:
    """An answer picked with no words, followed once for its reason unless ``reply`` is None."""
    follow = None
    if reply is not None:
        follow = ReasonFollowUp(
            shown=reason_follow_up(picked), words=reply, typed_by=_JUDGE, given_at=_GIVEN_AT
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
    assert (entry["picked"], entry["answer"], entry["words_sha256"]) == ("Yes", "yes", None)
    assert entry["reason"] == words_fingerprint("Brick fronts, a bakery.")
    assert entry["reasonFrom"] == "follow-up"
    assert entry["followUp"] == {
        "asked": "You answered Yes. In a few words, why?",
        **words_fingerprint("Brick fronts, a bakery."),
        "typedBy": _JUDGE,
        "givenAt": _GIVEN_AT,
    }
    assert detail["pictures"][1]["reasonFrom"] == "reply"
    assert detail["requirement"] == ANSWER_REQUIREMENT
    answers = _answers(_without_words("start"), _asked("midpoint"), _asked("endpoint"))
    _, companion = judge_words_file(_RECORD_PATH, answers)
    replies = json.loads(companion)["replies"]
    assert [(reply["kind"], reply["words"]) for reply in replies[:2]] == [
        ("reply", None),
        ("follow-up", "Brick fronts, a bakery."),
    ]
    assert replies[1]["shown"] == "You answered Yes. In a few words, why?"


def test_a_follow_up_never_changes_the_answer():
    value, detail = _decide(
        _answers(
            _without_words("start", "No", "yes the colours are fine but it is a block model"),
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
            _followed("Yes", "Real brick, a corner cafe.", reason_follow_up("Yes"), "Because."),
            "already gave",
        ),
        (_followed("No", None, reason_follow_up("Yes"), "Flat blocks."), "rubric's words"),
        (
            _followed("Yes", None, "Why did you say yes? Was it the shops?", "Shops."),
            "rubric's words",
        ),
        (
            _followed("Yes", None, reason_follow_up("Yes"), "Shops.", typed_by="Claude"),
            "not typed by the judge",
        ),
        (
            _followed("Yes", None, reason_follow_up("Yes"), None),
            "no reason in the judge's own words",
        ),
        (
            _followed("Yes", None, reason_follow_up("Yes"), "   "),
            "no reason in the judge's own words",
        ),
        (
            _followed("Yes", None, reason_follow_up("Yes"), "[No preference]"),
            "no reason in the judge's own words",
        ),
        (
            _followed("Yes", None, reason_follow_up("Yes"), "yes"),
            "no reason in the judge's own words",
        ),
        (
            _followed("Yes", "yes", reason_follow_up("Yes"), "No."),
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
        follow_up=ReasonFollowUp(shown=reason_follow_up("No"), words="Flat.", typed_by=_JUDGE),
    )
    with pytest.raises(GateEvidenceError, match="cannot carry an answer"):
        _decide(_answers(_asked("start", "No", "Blocks."), carrying, _unasked("endpoint")))


def test_a_skipped_question_is_not_an_answer():
    for words in (None, "", "  "):
        answers = _answers(_asked("start", None, words), _unasked("midpoint"), _unasked("endpoint"))
        with pytest.raises(GateEvidenceError, match="skipped"):
            _decide(answers)


def test_a_rubric_digest_mismatch_is_refused():
    with pytest.raises(GateEvidenceError, match="rubric digest mismatch"):
        _decide(_answers(), rubric_sha256=_SHA)
    with pytest.raises(GateEvidenceError, match="rubric digest mismatch"):
        _record(_evidence(), rubric_sha256=_SHA)
    with pytest.raises(GateEvidenceError, match="names no rubric digest"):
        _record(_evidence(), rubric_sha256="docs/visual-gate-rubric.md")
    with pytest.raises(GateEvidenceError, match="must name the rubric answered"):
        _decide(dataclasses.replace(_answers(), rubric_sha256="latest"))


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
        _decide(_answers(_asked("start", "No", "Blocks."), carrying, _unasked("endpoint")))
    with pytest.raises(GateEvidenceError, match="needs the named judge's answers"):
        _decide({"start": "no"})  # type: ignore[arg-type]
    with pytest.raises(GateEvidenceError, match="ISO date"):
        _decide(dataclasses.replace(_answers(), judged_on="yesterday"))


def test_a_retained_record_is_decided_again_from_its_private_companion():
    answers = _answers(
        _without_words("start", "No", "Flat blocks."), _unasked("midpoint"), _unasked("endpoint")
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
        words_from_companion(json.loads(companion), "docs/evaluation/another-record.json")
    forged = json.loads(companion)
    forged["replies"][1]["words"] = "Something else entirely."
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
    tampered["value"] = True
    with pytest.raises(GateEvidenceError, match="does not follow"):
        recompose_judged(tampered)
    tampered = copy.deepcopy(judged)
    tampered["pictures"][0]["reason"]["words_private"] = False
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

    one_no = _answers(_asked("start"), _asked("midpoint"), _asked("endpoint", "No", "A cut."))
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
    for option in ANSWER_OPTIONS:
        assert reason_follow_up(option) == f"You answered {option}. In a few words, why?"
        assert reason_follow_up(option) in text
    with pytest.raises(ValueError, match="not an option"):
        reason_follow_up("Maybe")
    with pytest.raises(ValueError, match="not a route capture"):
        judge_prompt("overview")


_V3_RECORD = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v3.json"
_V3_ARTIFACTS = "docs/evaluation/artifacts/2026-09-16-visual-gate-key-reconciliation-v3"


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
    monkeypatch.setattr(module, "RECONCILIATION", root / _V3_RECORD)
    monkeypatch.setattr(module, "RUBRIC_COPY", root / _V3_ARTIFACTS / "visual-gate-rubric.md")
    return module


def _scratch_root(tmp_path: Path, rubric: bytes, measurements_unchanged: bool = True) -> Path:
    root = tmp_path / "root"
    (root / _V3_ARTIFACTS).mkdir(parents=True)
    (root / "docs/visual-gate-rubric.md").write_bytes(rubric)
    (root / _V3_ARTIFACTS / "visual-gate-rubric.md").write_bytes(rubric)
    fixed = {
        "record": {
            "judgedKey": {"rubricSha256": hashlib.sha256(rubric).hexdigest()},
            "supersedes": {
                "keySet": VERSION_2.key_set,
                "measurementsUnchanged": measurements_unchanged,
            },
        }
    }
    (root / _V3_RECORD).write_text(json.dumps(fixed), encoding="utf-8")
    return root


def _judgement_file(path: Path, rubric: bytes, **changes) -> Path:
    judgement = {
        "profile": "exulanica.visual-gate-judgement/v3",
        "judge": "Glendon",
        "judgedOn": "2026-09-16",
        "rubric": "docs/visual-gate-rubric.md",
        "rubricSha256": hashlib.sha256(rubric).hexdigest(),
        "askedIn": "test",
        "options": ["Yes", "No"],
        "pictures": [
            {
                "label": "start",
                "picture": "Picture 1 of 3",
                "prompt": judge_prompt("start"),
                "captureSha256": _CAPTURES["start"],
                "asked": True,
                "picked": "No",
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


def test_the_writer_accepts_a_superseded_key_set_only_when_its_measurements_are_unchanged(
    monkeypatch, tmp_path
):
    rubric = _RUBRIC.read_bytes()
    writer = _writer(monkeypatch, _scratch_root(tmp_path / "same", rubric))
    assert writer._key_sets_measured_alike() == {GATE_KEY_SET_VERSION, VERSION_2.key_set}
    writer = _writer(monkeypatch, _scratch_root(tmp_path / "moved", rubric, False))
    assert writer._key_sets_measured_alike() == {GATE_KEY_SET_VERSION}
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
            "picked": "No",
            "words": None,
            "followUp": {
                "shown": reason_follow_up("No"),
                "words": "Flat colour everywhere.",
                "typedBy": "Glendon",
                "givenAt": "2026-09-16T12:01:00Z",
            },
        }
    )
    answers, asked_as = writer._judgement(
        _judgement_file(tmp_path / "follow.json", rubric, pictures=pictures), rubric
    )
    assert asked_as["followUps"] == {"start": reason_follow_up("No")}
    value, detail = _decide(answers, rubric_sha256=hashlib.sha256(rubric).hexdigest())
    assert value is False
    assert detail["pictures"][0]["reason"] == words_fingerprint("Flat colour everywhere.")
    pictures[0]["followUp"]["shown"] = "You said no. Why not?"
    answers, _ = writer._judgement(
        _judgement_file(tmp_path / "reworded.json", rubric, pictures=pictures), rubric
    )
    with pytest.raises(GateEvidenceError, match="rubric's words"):
        _decide(answers, rubric_sha256=hashlib.sha256(rubric).hexdigest())


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
    leak = root / "docs/evaluation/leak.json"
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
    # Version 2 composition, decided again from what the record carries and nothing else.
    assert judged["rubricVersion"] == RUBRIC_VERSION
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
            assert entry["reason"] and entry["typedBy"] == judged["judge"]
            if "followUp" in entry:
                assert entry["words_sha256"] is None or entry["reasonFrom"] == "follow-up"
                shown = record["judgement"]["followUps"][entry["label"]]
                assert shown == entry["followUp"]["asked"]
                assert shown == reason_follow_up(entry["picked"] or entry["answer"].capitalize())
    for spelling, detail in record["gate"]["keys"].items():
        if detail["evidenceKind"] == "mechanical":
            assert decide_mechanical(spelling, detail["decidedBy"]) is record["hardPass"][spelling]
    assert record["claimsNotMade"]


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
