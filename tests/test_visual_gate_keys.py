"""The nine canonical visual gate keys, the drift table, and the reconciliation records.

The three retained rejection records are local-only evidence: they are listed in the checkout's
exclude file and exist only where they were produced. Every assertion that reads one runs when the
file is present and skips, naming the file, when it is not, so a checkout without them says what
it could not check instead of passing it silently.

Five reconciliation records are retained. Version 1 fixed the keys and the first rubric; version 2
changed only the judged key; version 3 changed the question and one definition's wording and
carries version 2's answers as calibration evidence; version 4 gave the question one meaning and
carries version 3's pick and message; version 5 changed only how a typed reply is read and carries
version 4's typed reply. The latest is checked against this module, and the earlier four against
the wording :data:`RUBRIC_V1`, :data:`VERSION_2`, :data:`VERSION_3` and :data:`VERSION_4` keep.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.evaluation import gate_keys
from exulanica.evaluation.gate_keys import (
    ANSWER_OPTIONS,
    ANSWER_REQUIREMENT,
    CANONICAL_KEYS,
    CANONICAL_SPELLINGS,
    CAPTURE_LABELS,
    CARRIED_WORDS_NOTICE,
    GATE_KEY_SET_VERSION,
    JUDGED_KEY,
    MELBOURNE_ENVELOPE,
    NOT_ASKED,
    OPTION_ANSWERS,
    PICTURE_TITLES,
    REASON_FOLLOW_UP,
    RETAINED_RECORDS,
    RUBRIC_GUIDANCE,
    RUBRIC_PATH,
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
    resolve,
)

_ROOT = Path(__file__).resolve().parents[1]
_FIRST = "docs/evaluation/2026-09-15-visual-gate-key-reconciliation.json"
_SECOND = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v2.json"
_THIRD = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v3.json"
_FOURTH = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v4.json"
_LATEST = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v5.json"
_RECONCILIATIONS = (_FIRST, _SECOND, _THIRD, _FOURTH, _LATEST)
#: Each record and the reconciliation record it superseded.
_PREVIOUS = {_SECOND: _FIRST, _THIRD: _SECOND, _FOURTH: _THIRD, _LATEST: _FOURTH}

#: The drift the operator's plan proposed, restated here so the module is checked against it
#: rather than against itself.
_PROPOSED = {
    "continuousTexturedStreetAndFacades": {
        "continuousTexturedGround",
        "continuousTexturedStreet",
        "continuousSourceTexturedStreetAndFacades",
    },
    "readsAsInhabitedStreet": {
        "recognizableUrbanStreet",
        "recognizableUrbanScene",
        "recognizableMelbourneUrbanScene",
    },
    "noCutsOrFloatingGeometry": {
        "noFloatingOrCutGeometry",
        "noCutOrFloatingGeometry",
        "noLargeCutsOrFloatingGeometry",
    },
    "usefulEyeLevelMovement": {
        "eyeLevelMovement",
        "verifiedEyeLevelMovement",
        "usefulEyeLevelMovement",
    },
    "completeCapsuleClearanceVerification": {"completeCapsuleClearanceVerification"},
    "practicalBrowserBudget": {"practicalBrowserBudget"},
    "companionPresent": {"companionPresent"},
    "reticlePresent": {"reticlePresent"},
    "authenticatedShellAndAuthoredHandlersPreserved": {
        "authenticatedShellAndAuthoredHandlersPreserved"
    },
}


def _retained(path: str) -> dict:
    file = _ROOT / path
    if not file.is_file():
        pytest.skip(f"{path} is local-only retained evidence and is not in this checkout")
    return json.loads(file.read_bytes())


def _reconciliation(path: str = _LATEST) -> dict:
    file = _ROOT / path
    assert file.is_file(), f"{path} is a retained deliverable"
    return json.loads(file.read_bytes())


def test_the_canonical_set_has_exactly_nine_members_in_one_spelling_each():
    assert len(CANONICAL_KEYS) == 9
    assert len(set(CANONICAL_SPELLINGS)) == 9
    assert set(CANONICAL_SPELLINGS) == set(_PROPOSED)
    assert {item.evidence_kind for item in CANONICAL_KEYS} == {"mechanical", "judged"}
    judged = [item.spelling for item in CANONICAL_KEYS if item.evidence_kind == "judged"]
    assert judged == ["readsAsInhabitedStreet"]


def test_no_canonical_spelling_names_a_source_or_a_city():
    for spelling in CANONICAL_SPELLINGS:
        assert "Source" not in spelling, spelling
        assert "Melbourne" not in spelling, spelling
        assert "Helsinki" not in spelling, spelling


def test_every_mechanical_key_names_the_measurement_that_decides_it():
    for item in CANONICAL_KEYS:
        assert item.definition.startswith("True only when"), item.spelling
        if item.evidence_kind == "mechanical":
            assert item.measurement, item.spelling
            assert item.decided_by, item.spelling
        else:
            assert item.measurement is None
            assert item.decided_by == ()


def test_the_mapping_is_the_proposed_one_and_is_unambiguous():
    resolved: dict[str, set[str]] = {}
    for canonical, spellings in _PROPOSED.items():
        for spelling in spellings:
            resolved.setdefault(spelling, set()).add(resolve(spelling))
            assert resolve(spelling) == canonical, spelling
    assert all(len(targets) == 1 for targets in resolved.values()), resolved
    for item in CANONICAL_KEYS:
        assert set(item.predecessor_spellings) | {item.spelling} == _PROPOSED[item.spelling] | {
            item.spelling
        }


def test_the_resolver_raises_on_an_invented_spelling_rather_than_passing_it_through():
    for invented in (
        "recognisableUrbanScene",
        "continuousTexturedFacades",
        "readsAsInhabitedStreets",
        "noFloatingGeometry",
        "",
        "companionpresent",
    ):
        with pytest.raises(UnknownGateKey):
            resolve(invented)


def test_an_ambiguous_table_refuses_to_build(monkeypatch):
    duplicate = gate_keys.GateKey(
        spelling="reticlePresent",
        definition="True only when duplicated.",
        evidence_kind="mechanical",
        measurement="x",
        decided_by=("captures",),
        predecessor_spellings=("companionPresent",),
    )
    monkeypatch.setattr(gate_keys, "CANONICAL_KEYS", (*gate_keys.CANONICAL_KEYS, duplicate))
    with pytest.raises(RuntimeError, match="resolves to both"):
        gate_keys._resolution_table()


@pytest.mark.parametrize("retained", RETAINED_RECORDS, ids=lambda record: record.label)
def test_every_retained_spelling_resolves_and_the_table_matches_the_record(retained):
    document = _retained(retained.path)
    hard_pass = document["record"]["hardPass"]
    resolved = {resolve(spelling): spelling for spelling in hard_pass}
    assert len(resolved) == len(hard_pass), "two spellings of one record resolve to one key"
    assert resolved == dict(retained.spellings)
    digest = hashlib.sha256(canonical_json(document["record"])).hexdigest()
    assert digest == document["record_sha256"] == retained.record_sha256


def test_the_retained_key_counts_are_six_seven_and_nine():
    counts = {record.label: len(record.spellings) for record in RETAINED_RECORDS}
    assert counts == {
        "helsinki-visual-feasibility": 6,
        "helsinki-terminal-lod-successor": 7,
        "melbourne-c4-29-visual-feasibility": 9,
    }


@pytest.mark.parametrize("path", _RECONCILIATIONS)
def test_each_reconciliation_record_reproduces_its_digest_and_binds_the_three_rejections(path):
    document = _reconciliation(path)
    record = document["record"]
    assert document["profile"] == "exulanica.digest-bound-record/v1"
    assert document["record_sha256"] == hashlib.sha256(canonical_json(record)).hexdigest()
    bindings = {item["path"]: item["record_sha256"] for item in record["predecessor_records"]}
    expected = {record.path: record.record_sha256 for record in RETAINED_RECORDS}
    if path in _PREVIOUS:
        expected[_PREVIOUS[path]] = _reconciliation(_PREVIOUS[path])["record_sha256"]
    assert bindings == expected
    assert record["mappingChecks"] == {
        "retainedSpellings": 17,
        "retainedSpellingsResolved": 17,
        "total": True,
        "unambiguous": True,
        "canonicalKeys": 9,
    }


def test_the_latest_reconciliation_record_states_the_module_it_was_written_from():
    """A later edit to the definitions has to come with a new record, not drift past this one."""
    record = _reconciliation()["record"]
    assert record["keySet"] == GATE_KEY_SET_VERSION
    assert [entry["key"] for entry in record["canonicalKeys"]] == list(CANONICAL_SPELLINGS)
    for entry, item in zip(record["canonicalKeys"], CANONICAL_KEYS, strict=True):
        assert entry["definition"] == item.definition
        assert entry["evidenceKind"] == item.evidence_kind
        assert entry["predecessorSpellings"] == list(item.predecessor_spellings)
        if item.evidence_kind == "mechanical":
            assert entry["measurement"] == item.measurement
            assert entry["decidedBy"] == list(item.decided_by)
        else:
            assert entry["rubric"] == RUBRIC_PATH
    assert record["thresholds"] == dict(THRESHOLDS)
    assert record["melbourneEnvelope"] == dict(MELBOURNE_ENVELOPE)
    judged = record["judgedKey"]
    assert judged["captures"] == list(CAPTURE_LABELS)
    assert judged["rubricVersion"] == RUBRIC_VERSION
    assert judged["question"] == RUBRIC_QUESTION
    assert judged["guidance"] == RUBRIC_GUIDANCE
    assert judged["requirement"] == ANSWER_REQUIREMENT
    assert judged["reasonFollowUp"] == REASON_FOLLOW_UP
    assert judged["carriedWordsNotice"] == CARRIED_WORDS_NOTICE
    assert judged["options"] == list(ANSWER_OPTIONS)
    assert judged["wordsStorage"] == WORDS_STORAGE
    assert judged["optionAnswers"] == dict(OPTION_ANSWERS)
    assert judged["typedReplyRule"] == TYPED_REPLY_RULE
    assert record["rubricVersion"] == RUBRIC_VERSION
    assert judged["notAsked"] == NOT_ASKED
    assert {item["label"]: item["title"] for item in judged["pictures"]} == dict(PICTURE_TITLES)
    assert "questions" not in judged


def test_the_latest_reconciliation_fixes_the_rubric_on_disk_and_retains_a_copy():
    record = _reconciliation()["record"]
    rubric = (_ROOT / RUBRIC_PATH).read_bytes()
    digest = hashlib.sha256(rubric).hexdigest()
    assert record["judgedKey"]["rubricSha256"] == digest
    copy = record["judgedKey"]["rubricCopy"]
    bound = next(item for item in record["artifacts"] if item["path"] == copy)
    assert bound == {"path": copy, "byte_size": len(rubric), "sha256": digest}
    assert (_ROOT / copy).read_bytes() == rubric
    judge = record["judgedKey"]["judge"]
    assert f"Named human judge: {judge}\n".encode() in rubric


def test_version_2_came_before_anything_was_scored_and_changed_only_the_judged_key():
    record = _reconciliation(_SECOND)["record"]
    assert record["scoredBeforeRevision"]["corridors"] == []
    assert record["scoredBeforeRevision"]["againstVersion1"] == []
    supersedes = record["supersedes"]
    assert supersedes["path"] == _FIRST
    assert supersedes["record_sha256"] == _reconciliation(_FIRST)["record_sha256"]
    assert supersedes["changedKeys"] == [JUDGED_KEY]
    assert supersedes["keySet"] == RUBRIC_V1.key_set
    assert record["mapping"] == _reconciliation(_FIRST)["record"]["mapping"]


def test_the_version_2_record_still_states_version_2():
    """Version 2 is retained as written; version 3 changed its question and one definition."""
    record = _reconciliation(_SECOND)["record"]
    assert record["keySet"] == VERSION_2.key_set
    judged = record["judgedKey"]
    assert judged["rubricVersion"] == VERSION_2.rubric_version
    assert judged["rubricSha256"] == VERSION_2.rubric_sha256
    assert (judged["question"], judged["guidance"]) == (VERSION_2.question, VERSION_2.guidance)
    assert judged["composition"] == VERSION_2.composition
    for entry, item in zip(record["canonicalKeys"], CANONICAL_KEYS, strict=True):
        assert entry["definition"] == VERSION_2.definitions.get(item.spelling, item.definition)
        if item.evidence_kind == "mechanical":
            assert entry["decidedBy"] == list(item.decided_by)
            assert entry["measurement"] == item.measurement


def test_version_3_came_before_anything_was_scored_and_moved_no_measurement():
    record = _reconciliation(_THIRD)["record"]
    assert record["scoredBeforeRevision"]["corridors"] == []
    assert record["scoredBeforeRevision"]["againstEarlierKeySets"] == []
    supersedes = record["supersedes"]
    assert supersedes["path"] == _SECOND
    assert supersedes["record_sha256"] == _reconciliation(_SECOND)["record_sha256"]
    assert supersedes["keySet"] == VERSION_2.key_set
    assert record["keySet"] == VERSION_3.key_set
    assert supersedes["rubricSha256"] == VERSION_2.rubric_sha256
    assert record["judgedKey"]["rubricSha256"] == VERSION_3.rubric_sha256
    assert supersedes["measurementsUnchanged"] is True
    assert supersedes["keyValuesChanged"] == []
    changes = supersedes["changes"]
    assert changes["question"] == {"before": VERSION_2.question, "after": VERSION_3.question}
    assert changes["guidance"] == {"before": VERSION_2.guidance, "after": VERSION_3.guidance}
    assert set(changes["definitions"]) == {"authenticatedShellAndAuthoredHandlersPreserved"}
    assert (
        "pointer"
        in changes["definitions"]["authenticatedShellAndAuthoredHandlersPreserved"]["after"]
    )
    assert record["mapping"] == _reconciliation(_SECOND)["record"]["mapping"]


def test_the_version_3_record_still_states_version_3():
    record = _reconciliation(_THIRD)["record"]
    judged = record["judgedKey"]
    assert (judged["question"], judged["guidance"]) == (VERSION_3.question, VERSION_3.guidance)
    assert judged["requirement"] == VERSION_3.requirement
    assert judged["options"] == list(VERSION_3.options)
    assert judged["composition"] == VERSION_3.composition
    assert (judged["rubricVersion"], judged["rubricSha256"]) == (
        VERSION_3.rubric_version,
        VERSION_3.rubric_sha256,
    )
    for entry, item in zip(record["canonicalKeys"], CANONICAL_KEYS, strict=True):
        assert entry["definition"] == VERSION_3.definitions.get(item.spelling, item.definition)


def test_version_4_came_before_anything_was_scored_and_changed_only_the_question():
    record = _reconciliation(_FOURTH)["record"]
    assert record["keySet"] == VERSION_4.key_set
    assert record["scoredBeforeRevision"]["corridors"] == []
    assert record["scoredBeforeRevision"]["againstEarlierKeySets"] == []
    supersedes = record["supersedes"]
    assert supersedes["path"] == _THIRD
    assert supersedes["record_sha256"] == _reconciliation(_THIRD)["record_sha256"]
    assert (supersedes["keySet"], supersedes["rubricSha256"]) == (
        VERSION_3.key_set,
        VERSION_3.rubric_sha256,
    )
    assert supersedes["measurementsUnchanged"] is True
    assert supersedes["keyValuesChanged"] == []
    changes = supersedes["changes"]
    assert changes["question"] == {"before": VERSION_3.question, "after": VERSION_4.question}
    assert changes["guidance"] == {"before": VERSION_3.guidance, "after": VERSION_4.guidance}
    assert changes["options"] == {"before": ["Yes", "No"], "after": list(VERSION_4.options)}
    assert changes["definitions"] == {}
    assert supersedes["keysWithUnchangedDefinitions"] == list(CANONICAL_SPELLINGS)
    assert record["mapping"] == _reconciliation(_THIRD)["record"]["mapping"]


def test_the_version_4_record_still_states_version_4():
    record = _reconciliation(_FOURTH)["record"]
    judged = record["judgedKey"]
    assert (judged["rubricVersion"], judged["rubricSha256"]) == (
        VERSION_4.rubric_version,
        VERSION_4.rubric_sha256,
    )
    assert (judged["question"], judged["guidance"]) == (VERSION_4.question, VERSION_4.guidance)
    assert judged["requirement"] == VERSION_4.requirement
    assert judged["options"] == list(VERSION_4.options)
    assert judged["carriedWordsNotice"] == VERSION_4.carried_notice
    assert judged["composition"] == VERSION_4.composition
    assert "typedReplyRule" not in judged
    assert "answered yes by the named judge" in judged["corridorBar"]
    for entry, item in zip(record["canonicalKeys"], CANONICAL_KEYS, strict=True):
        assert entry["definition"] == VERSION_4.definitions.get(item.spelling, item.definition)


def test_version_4_carries_the_version_3_pick_and_message_as_calibration_evidence():
    record = _reconciliation(_FOURTH)["record"]
    evidence = record["calibrationEvidence"]
    assert evidence["underRubricVersion"] == 3
    assert evidence["rubricSha256"] == VERSION_3.rubric_sha256
    assert evidence["judge"] == record["judgedKey"]["judge"]
    third = _reconciliation(_THIRD)["record"]
    start = next(capture for capture in third["captures"] if capture["label"] == "start")
    assert record["captures"] == [start]
    (picture,) = evidence["pictures"]
    assert picture["label"] == "start" and picture["captureSha256"] == start["sha256"]
    pick, message = picture["replies"]
    assert (pick["kind"], pick["picked"], pick["words_sha256"], pick["counted"]) == (
        "pick",
        "Yes",
        None,
        False,
    )
    assert pick["shown"] == VERSION_3.prompt("start")
    assert (message["kind"], message["shown"], message["counted"]) == ("message", None, False)
    assert message["words_private"] is True and message["words_bytes"] > 0
    assert (pick["rubricVersion"], message["rubricVersion"]) == (3, 3)
    assert pick["givenAt"] < message["givenAt"]
    assert "verbatim" not in pick and "verbatim" not in message
    assert "quotedFragments" not in evidence
    assert "private companion" in evidence["wordsKept"]
    assert evidence["notAsked"] == ["Picture 2 of 3", "Picture 3 of 3"]
    assert evidence["summary"] == {
        "answersScored": 0,
        "picksNotRecorded": 1,
        "messagesNotCounted": 1,
    }
    assert evidence["claimsJoined"] == ["a finished, lived-in street", "not a plain block mock-up"]
    assert all(claim in VERSION_3.question for claim in evidence["claimsJoined"])
    assert "mock-up" not in RUBRIC_QUESTION
    assert "not a key value" in evidence["status"]


def test_version_5_came_before_anything_was_scored_and_changed_only_how_a_reply_is_read():
    record = _reconciliation()["record"]
    assert record["keySet"] == GATE_KEY_SET_VERSION
    assert record["scoredBeforeRevision"]["corridors"] == []
    assert record["scoredBeforeRevision"]["againstEarlierKeySets"] == []
    supersedes = record["supersedes"]
    assert supersedes["path"] == _FOURTH
    assert supersedes["record_sha256"] == _reconciliation(_FOURTH)["record_sha256"]
    assert (supersedes["keySet"], supersedes["rubricSha256"]) == (
        VERSION_4.key_set,
        VERSION_4.rubric_sha256,
    )
    assert supersedes["measurementsUnchanged"] is True
    assert supersedes["keyValuesChanged"] == []
    assert supersedes["shownUnchanged"] is True
    assert VERSION_4.shows_what_is_shown_now()
    fourth = _reconciliation(_FOURTH)["record"]["judgedKey"]
    judged = record["judgedKey"]
    for name in ("question", "guidance", "requirement", "reasonFollowUp", "carriedWordsNotice"):
        assert judged[name] == fourth[name], name
    assert judged["options"] == fourth["options"]
    assert judged["pictures"] == fourth["pictures"]
    changes = supersedes["changes"]
    assert set(changes) == {
        "typedReplyRule",
        "composition",
        "corridorBar",
        "writerRefuses",
        "definitions",
    }
    assert changes["typedReplyRule"]["before"] == VERSION_4.typed_reply_rule
    assert changes["typedReplyRule"]["after"] == TYPED_REPLY_RULE
    assert changes["composition"]["before"] == fourth["composition"]
    assert changes["corridorBar"] == {
        "before": fourth["corridorBar"],
        "after": judged["corridorBar"],
    }
    assert "picking yes" in judged["corridorBar"]
    assert changes["writerRefuses"]["before"] == fourth["writerRefuses"]
    assert changes["writerRefuses"]["after"] == judged["writerRefuses"]
    assert changes["definitions"] == {}
    assert supersedes["keysWithUnchangedDefinitions"] == list(CANONICAL_SPELLINGS)
    assert "only fail a key, never pass one" in supersedes["why"]["typedReplyRule"]
    assert "three picked yes answers" in supersedes["why"]["corridorBar"]
    adoption = supersedes["adoption"]
    assert "adopted after the version 4 reply" in adoption
    assert "first application" in adoption
    assert "declined further questions" in adoption
    assert "can only ever fail a key" in supersedes["knownCost"]
    assert "two options" in supersedes["knownCost"]
    assert "version 2" in supersedes["notReRead"]
    assert "are not re-read" in supersedes["notReRead"]
    assert judged["answersAcceptedAgainst"] == [
        {"rubricVersion": RUBRIC_VERSION, "rubricSha256": judged["rubricSha256"]},
        {"rubricVersion": VERSION_4.rubric_version, "rubricSha256": VERSION_4.rubric_sha256},
    ]
    assert record["mapping"] == _reconciliation(_FOURTH)["record"]["mapping"]
    claims = " ".join(record["claimsNotMade"])
    assert "no model judged any picture" in claims
    assert "not re-read under version 5" in claims


def test_version_5_carries_the_version_4_reply_as_calibration_evidence():
    record = _reconciliation()["record"]
    evidence = record["calibrationEvidence"]
    assert evidence["underRubricVersion"] == VERSION_4.rubric_version
    assert evidence["rubricSha256"] == VERSION_4.rubric_sha256
    assert evidence["judge"] == record["judgedKey"]["judge"]
    assert record["captures"] == _reconciliation(_FOURTH)["record"]["captures"]
    (picture,) = evidence["pictures"]
    assert picture["label"] == "start"
    assert picture["captureSha256"] == record["captures"][0]["sha256"]
    (reply,) = picture["replies"]
    assert (reply["kind"], reply["picked"], reply["typedBy"]) == (
        "typed",
        None,
        evidence["judge"],
    )
    assert "verbatim" not in reply
    assert reply["words_private"] is True and reply["words_bytes"] > 0
    assert (reply["rubricVersion"], reply["givenAt"][:11]) == (4, "2026-09-16T")
    assert reply["shown"] == f"{VERSION_4.carried_notice}\n\n{VERSION_4.prompt('start')}"
    assert reply["readUnderVersion4"]["answer"] is None
    assert reply["readUnderVersion4"]["why"].endswith("begins with neither")
    assert reply["readUnderVersion5"]["answer"] == "no"
    (carried,) = reply["carriedIntoTheAsk"]
    message = _reconciliation(_FOURTH)["record"]["calibrationEvidence"]["pictures"][0]
    message = message["replies"][1]
    assert (carried["words_sha256"], carried["words_bytes"]) == (
        message["words_sha256"],
        message["words_bytes"],
    )
    assert (carried["rubricVersion"], carried["rubricSha256"]) == (
        VERSION_3.rubric_version,
        VERSION_3.rubric_sha256,
    )
    assert carried["givenAt"] == message["givenAt"] and carried["givenAs"].strip()
    assert "private companion" in evidence["wordsKept"]
    assert record["judgeWords"]["path"] == ".exulanica/judge-words/" + Path(_LATEST).name
    assert evidence["notAsked"] == ["Picture 2 of 3", "Picture 3 of 3"]
    assert evidence["summary"] == {
        "answersScoredUnderVersion4": 0,
        "typedRepliesVersion4CouldNotRead": 1,
    }
    assert "adopted after this reply was given" in evidence["firstApplication"]
    assert evidence["judgeDeclinedFurtherQuestions"] is True
    assert "not a key value" in evidence["status"]


def test_version_3_carries_the_version_2_answers_as_calibration_evidence():
    record = _reconciliation(_THIRD)["record"]
    evidence = record["calibrationEvidence"]
    assert evidence["underRubricVersion"] == 2
    assert evidence["rubricSha256"] == VERSION_2.rubric_sha256
    assert evidence["judge"] == record["judgedKey"]["judge"]
    assert [capture["label"] for capture in record["captures"]] == list(CAPTURE_LABELS)
    bound = {capture["label"]: capture["sha256"] for capture in record["captures"]}
    for picture in evidence["pictures"]:
        assert picture["captureSha256"] == bound[picture["label"]]
        replies = picture["replies"]
        assert [reply["counted"] for reply in replies] == [False] * (len(replies) - 1) + [True]
        assert replies[-1]["answer"] == "yes"
        for reply in replies:
            assert reply["prompt"] == VERSION_2.prompt(picture["label"])
            assert reply["typedBy"] == evidence["judge"]
            assert reply["rubricVersion"] == 2 and reply["givenAt"].startswith("2026-09-16T")
            assert "verbatim" not in reply and "words" not in reply
            assert reply["words_private"] is (reply["words_sha256"] is not None)
    first, second = evidence["pictures"][0]["replies"]
    assert first["counted"] is False and first["picked"] is None and first["words_private"]
    assert first["addedAboveTheQuestion"] is None
    assert second["addedAboveTheQuestion"]["words_private"] is True
    assert evidence["summary"] == {
        "yesAnswers": 3,
        "noAnswers": 0,
        "uncountedReplies": 1,
        "answersWithoutWords": ["Picture 1 of 3", "Picture 3 of 3"],
    }
    assert "quotedFragments" not in evidence
    assert "private companion" in evidence["wordsKept"]
    assert "did not separate" in evidence["finding"]
    assert "not a key value" in evidence["status"]
    assert record["judgeWords"]["path"] == ".exulanica/judge-words/" + Path(_THIRD).name


def test_the_superseded_record_still_states_version_1():
    """Version 1 is retained as written. Only the judged key's wording differs from the module."""
    record = _reconciliation(_FIRST)["record"]
    assert record["keySet"] == RUBRIC_V1.key_set
    judged = record["judgedKey"]
    assert [(q["id"], q["text"]) for q in judged["questions"]] == list(RUBRIC_V1.questions)
    assert judged["composition"] == RUBRIC_V1.composition
    for entry, item in zip(record["canonicalKeys"], CANONICAL_KEYS, strict=True):
        assert entry["key"] == item.spelling
        if item.spelling == JUDGED_KEY:
            assert entry["definition"] == RUBRIC_V1.judged_definition != item.definition
        elif item.spelling in VERSION_2.definitions:
            assert entry["definition"] == VERSION_2.definitions[item.spelling] != item.definition
            assert entry["decidedBy"] == list(item.decided_by)
        else:
            assert entry["definition"] == item.definition
            assert entry["decidedBy"] == list(item.decided_by)
    assert record["thresholds"] == dict(THRESHOLDS)
    assert record["melbourneEnvelope"] == dict(MELBOURNE_ENVELOPE)


@pytest.mark.parametrize("path", _RECONCILIATIONS)
@pytest.mark.parametrize("retained", RETAINED_RECORDS, ids=lambda record: record.label)
def test_each_reconciliation_declares_each_records_actual_spellings(retained, path):
    document = _retained(retained.path)
    actual = set(document["record"]["hardPass"])
    entry = next(
        item
        for item in _reconciliation(path)["record"]["retainedRecords"]
        if item["label"] == retained.label
    )
    assert entry["record_sha256"] == retained.record_sha256
    declared = {value["spelling"] for value in entry["keys"].values() if value["state"] == "scored"}
    assert declared == actual
    for canonical, value in entry["keys"].items():
        if value["state"] == "scored":
            assert value["retainedValue"] is document["record"]["hardPass"][value["spelling"]]
            assert resolve(value["spelling"]) == canonical


def _booleans(node) -> list:
    if isinstance(node, bool):
        return [node]
    if isinstance(node, dict):
        return [found for item in node.values() for found in _booleans(item)]
    if isinstance(node, list):
        return [found for item in node for found in _booleans(item)]
    return []


@pytest.mark.parametrize("path", _RECONCILIATIONS)
def test_absence_is_recorded_as_absence_and_never_as_a_boolean(path):
    entries = {item["label"]: item for item in _reconciliation(path)["record"]["retainedRecords"]}
    expected_absent = {
        "helsinki-visual-feasibility": {
            "completeCapsuleClearanceVerification",
            "practicalBrowserBudget",
            "authenticatedShellAndAuthoredHandlersPreserved",
        },
        "helsinki-terminal-lod-successor": {
            "completeCapsuleClearanceVerification",
            "practicalBrowserBudget",
        },
        "melbourne-c4-29-visual-feasibility": set(),
    }
    for label, absent in expected_absent.items():
        keys = entries[label]["keys"]
        assert set(keys) == set(CANONICAL_SPELLINGS)
        found = {name for name, value in keys.items() if value["state"] == "absent"}
        assert found == absent, label
        for name in absent:
            assert set(keys[name]) <= {"state", "note", "briefedCriterion"}
            assert _booleans(keys[name]) == [], (label, name)
            assert "retainedValue" not in keys[name]


@pytest.mark.parametrize("path", _RECONCILIATIONS)
def test_the_shell_key_is_anchored_to_melbournes_preview_condition(path):
    anchor = _reconciliation(path)["record"]["authenticatedShellUnderMelbourne"]
    assert anchor["retainedValue"] is True
    assert [item["status"] for item in anchor["previewApi404s"]] == [404, 404, 404]
    assert all("/preview-api/" in item["url"] for item in anchor["previewApi404s"])
    assert "does not by itself assert a real bearer token" in anchor["statement"]
    melbourne = _retained("docs/evaluation/2026-09-12-melbourne-c4-29-visual-feasibility.json")
    assert anchor["previewApi404s"] == melbourne["record"]["browser"]["previewApi404s"]
