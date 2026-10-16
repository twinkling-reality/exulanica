"""The calibration reply a visual gate key reconciliation carries, and its private companion.

The reply typed under rubric version 4, how versions 4 and 5 read it, and the companion file that
keeps its words apart from the public record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.evaluation.gate_keys import (
    CAPTURE_LABELS,
    PICTURE_TITLES,
    VERSION_4,
)
from exulanica.evaluation.visual_gate_words import (
    _OPENING_ANSWER,
    CarriedWords,
    GateEvidenceError,
    PictureAnswer,
    _bound_file,
    _carried,
    _companion_bytes,
    _given_at,
    _has_reason,
    judge_words_path,
    judge_words_record,
    typed_reply_answer,
    words_fingerprint,
)


def _storage_note(version: int) -> str:
    """How the rubric a calibration reply was given under stored the judge's words, told plainly."""
    return (
        f"The rubric digest above names version {version} as published. When these replies were "
        f"given, version {version} said the judge's words would be carried verbatim in records. "
        "Before this repository was first published, the storage clause of every rubric version "
        "was changed to keep the words in a private companion record, and nothing the judge is "
        "shown changed. The words of these replies are in this record's private companion."
    )


def _calibration(
    calibration: Mapping[str, Any],
    captures: Sequence[Mapping[str, Any]],
    judge: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """The reply typed under version 4, with how versions 4 and 5 read it and its words apart.

    Returns the public evidence, which carries the reply's time, readings and the SHA-256 and
    byte count of its words, the replies the record's private companion keeps word for word, and
    the lines shown above a question beside them, of which version 4's ask had none of its own.
    """
    if calibration.get("judge") != judge:
        raise GateEvidenceError("FINDING: the calibration evidence is not the rubric's judge's")
    if calibration.get("rubricSha256") != VERSION_4.rubric_sha256:
        raise GateEvidenceError("FINDING: the calibration evidence was not given under version 4")
    pictures = list(calibration.get("pictures", []))
    labels = [picture.get("label") for picture in pictures]
    if labels != list(CAPTURE_LABELS[: len(labels)]) or not labels:
        raise GateEvidenceError("the calibration evidence must start at the first picture")
    if [capture.get("label") for capture in captures] != labels:
        raise GateEvidenceError("the calibration captures must be the pictures asked")
    for index, capture in enumerate(captures):
        _bound_file(capture, f"captures[{index}]")
    not_asked = list(CAPTURE_LABELS[len(labels) :])
    if list(calibration.get("notAsked", [])) != not_asked:
        raise GateEvidenceError("the calibration evidence must list the pictures not asked")
    bound = {capture["label"]: capture["sha256"] for capture in captures}
    entries: list[dict[str, Any]] = []
    private_replies: list[dict[str, Any]] = []
    for picture in pictures:
        label = picture["label"]
        title = PICTURE_TITLES[label]
        if picture.get("captureSha256") != bound[label]:
            raise GateEvidenceError(f"FINDING: {title} was answered about another capture")
        replies = list(picture.get("replies", []))
        if [reply.get("kind") for reply in replies] != ["typed"]:
            raise GateEvidenceError(f"FINDING: {title} does not carry one typed reply")
        (reply,) = replies
        if reply.get("typedBy") != judge:
            raise GateEvidenceError(f"FINDING: the reply about {title} was not the judge's")
        given_at = _given_at(f"FINDING: the reply about {title}", reply.get("givenAt"))
        shown = f"{VERSION_4.carried_notice}\n\n{VERSION_4.prompt(label)}"
        if reply.get("shown") != shown:
            raise GateEvidenceError(f"FINDING: {title} was not asked in version 4's words")
        if reply.get("picked") is not None:
            raise GateEvidenceError(f"FINDING: {title}'s reply was not typed in place of a pick")
        words = reply.get("words")
        if not isinstance(words, str) or not _has_reason(words):
            raise GateEvidenceError(f"FINDING: {title}'s typed reply says nothing")
        if _OPENING_ANSWER.match(words):
            raise GateEvidenceError(
                f"FINDING: version 4 could read {title}'s reply, so it calibrates nothing"
            )
        now = typed_reply_answer(words)
        if now != "no":
            raise GateEvidenceError(f"FINDING: version 5 does not read {title}'s reply as a no")
        earlier = tuple(
            CarriedWords(
                words=item.get("words"),
                typed_by=item.get("typedBy"),
                rubric_version=item.get("rubricVersion"),
                rubric_sha256=item.get("rubricSha256"),
                given_at=item.get("givenAt"),
                given_as=item.get("givenAs"),
            )
            for item in reply.get("carried", [])
        )
        carried = _carried(
            f"calibration {title}",
            PictureAnswer(
                label=label,
                capture_sha256=bound[label],
                asked=True,
                carried=earlier,
                notice=VERSION_4.carried_notice,
            ),
            judge,
        )
        for item in earlier:
            private_replies.append(
                {
                    "label": label,
                    "picture": title,
                    "kind": "carried",
                    "rubricVersion": item.rubric_version,
                    "rubricSha256": item.rubric_sha256,
                    "givenAt": item.given_at,
                    "givenAs": item.given_as,
                    "picked": None,
                    "words": item.words,
                    "typedBy": judge,
                }
            )
        private_replies.append(
            {
                "label": label,
                "picture": title,
                "kind": "typed",
                "rubricVersion": VERSION_4.rubric_version,
                "givenAt": given_at,
                "shownAbove": VERSION_4.carried_notice,
                "picked": None,
                "words": words,
                "typedBy": judge,
            }
        )
        entries.append(
            {
                "label": label,
                "picture": title,
                "captureSha256": bound[label],
                "replies": [
                    {
                        "kind": "typed",
                        "shown": shown,
                        "picked": None,
                        "rubricVersion": VERSION_4.rubric_version,
                        "givenAt": given_at,
                        **words_fingerprint(words),
                        "typedBy": judge,
                        "carriedIntoTheAsk": carried,
                        "readUnderVersion4": {
                            "answer": None,
                            "why": (
                                "a typed reply counted only when its first word was yes or no, "
                                "and this one begins with neither"
                            ),
                        },
                        "readUnderVersion5": {
                            "answer": now,
                            "why": "it holds the whole word no and not the whole word yes",
                        },
                    }
                ],
            }
        )
    evidence = {
        "underRubricVersion": VERSION_4.rubric_version,
        "rubricSha256": VERSION_4.rubric_sha256,
        "wordsKept": _storage_note(VERSION_4.rubric_version),
        "judge": judge,
        "askedIn": calibration.get("askedIn"),
        "pictures": entries,
        "notAsked": [PICTURE_TITLES[label] for label in not_asked],
        "summary": {
            "answersScoredUnderVersion4": 0,
            "typedRepliesVersion4CouldNotRead": len(entries),
        },
        "firstApplication": (
            "Version 5's typed-reply rule was adopted after this reply was given. This reply is "
            "the first the rule reads, and no other reply has been read under it."
        ),
        "judgeDeclinedFurtherQuestions": True,
        "finding": (
            "Under version 4 a typed reply counted only when its first word was yes or no. The "
            "judge typed a reply in place of a pick that begins with neither and holds the whole "
            "word no, so version 4 could not read it and the judgement stopped unscored. Version "
            "5 reads a typed reply as no when it holds the whole word no and not the whole word "
            "yes, and never as yes."
        ),
        "status": (
            "Calibration evidence, not a key value. No answer was scored and no record was "
            "written under version 4. A gate record may read this reply under version 5, because "
            "version 4 showed the judge exactly what version 5 shows; this record takes no key "
            "value from it."
        ),
    }
    return evidence, private_replies, []


def calibration_words_file(
    record_path: str,
    calibration: Mapping[str, Any],
    captures: Sequence[Mapping[str, Any]],
    judge: str,
) -> tuple[str, bytes]:
    """The private companion of a reconciliation record: where it lives, and its bytes."""
    _, replies, lines = _calibration(calibration, captures, judge)
    document = judge_words_record(record_path=record_path, judge=judge, replies=replies)
    if lines:
        document["shownLines"] = [{**line, **words_fingerprint(line["words"])} for line in lines]
    return judge_words_path(record_path), _companion_bytes(document)
