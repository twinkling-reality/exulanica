"""A visual gate's judged answers as read and refused, the judge's private words, and the envelope.

The answer types and a picture's answer, the companion record that holds the judge's words under
``.exulanica/judge-words/`` (never in the repository), the refusal of a public record that would
carry any of them, and the repository's digest-bound profile every record is written in.
:mod:`exulanica.evaluation.visual_gate` decides the keys and builds the record from them.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.evaluation.gate_keys import (
    ANSWER_OPTIONS,
    ANSWER_REQUIREMENT,
    CAPTURE_LABELS,
    CARRIED_WORDS_NOTICE,
    JUDGED_KEY,
    NOT_ASKED,
    OPTION_ANSWERS,
    PICTURE_TITLES,
    RUBRIC_GUIDANCE,
    RUBRIC_QUESTION,
    RUBRIC_VERSION,
    SUPERSEDED_VERSIONS,
    reason_follow_up,
)

DIGEST_BOUND_PROFILE: Final = "exulanica.digest-bound-record/v1"

#: How the judged answers compose under rubric version 5, as the records state it.
COMPOSITION: Final = (
    "Each capture is shown alone, in route order, and the judge answers the one question with the "
    "option they mean and their own words. A typed reply with no pick counts as no when it holds "
    "the whole word no and not the whole word yes, and never counts as yes. An answer that arrives "
    "without words may be followed once, with the picture shown alone again, by a request for the "
    "reason, and that reply never changes the answer. A pick that the judge's own words, given "
    "right after it, may contradict is not recorded. Words the judge wrote about a picture before "
    "its question was reworded are carried into its next ask, under a line that says so; they are "
    "part of the reason for a no, and a yes needs new words. The first no makes the key false and "
    "the pictures after it are not asked. The key is true only when all three pictures got a "
    "picked yes. There is no score."
)

#: What a corridor has to clear, as the records state it.
CORRIDOR_BAR: Final = (
    "all three pictures answered by picking yes, by the named judge, plus every mechanical key, "
    "against a baseline that does not itself hold every key"
)

#: Text a record may never carry. A floor, not an account of what must not leak: it names the
#: three kinds of string that have actually appeared in this repository's records. Anything
#: sensitive in a shape nobody listed passes this check, so a record that clears it is not thereby
#: clean. tests/test_retained_evaluation_records.py refuses these over the retained records by
#: reading this tuple, rather than repeating the three where nothing would keep them in step.
_FORBIDDEN_TEXT: Final = ("/Users/", "Bearer ", "api-token")

#: Words that name a role or stand in for a name. A judge field holding one is not a name, which
#: the rubric forbids as plainly as it forbids an invented name.
_ROLE_WORDS: Final = frozenset(
    {
        "operator",
        "the operator",
        "owner",
        "the owner",
        "judge",
        "the judge",
        "human judge",
        "named judge",
        "judge not yet named",
        "reviewer",
        "the reviewer",
        "user",
        "the user",
        "human",
        "a human",
        "person",
        "the person",
        "someone",
        "somebody",
        "nobody",
        "anonymous",
        "name",
        "placeholder",
        "tbd",
        "tba",
        "todo",
        "unknown",
        "n/a",
        "none",
        "null",
        "claude",
        "model",
        "assistant",
    }
)

#: A name written as a template slot, ``<judge>``, ``{judge}`` or ``[judge]``, is a placeholder.
_TEMPLATE_SLOT: Final = re.compile(r"^[<{\[].*[>}\]]$")

#: The answer word a typed reply has to open with. Nothing may precede it but white space, so the
#: bracketed marker a question tool shows for a skipped question can never read as a no.
_OPENING_ANSWER: Final = re.compile(r"^\s*(yes|no)\b", flags=re.IGNORECASE)

#: The whole words the typed-reply rule reads, in any case.
_WHOLE_NO: Final = re.compile(r"\bno\b", flags=re.IGNORECASE)

_WHOLE_YES: Final = re.compile(r"\byes\b", flags=re.IGNORECASE)

#: A skipped question as a question tool reports it. Not an answer, whatever its first word is.
_SKIP_MARKERS: Final = frozenset({"no preference", "[no preference]"})

_ISO_DATE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")

_ISO_TIME: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

#: Where the private companion of a public record lives, relative to the repository root. The
#: directory is ignored by git and shared by every worktree, so the judge's words stay on the
#: machine they were given on.
JUDGE_WORDS_DIRECTORY: Final = ".exulanica/judge-words"

JUDGE_WORDS_PROFILE: Final = "exulanica.visual-gate-judge-words/v1"

#: What an asking session writes there: the judge's answers, before any record reads them. It
#: holds words exactly as a companion does and is the reason the guard over that directory must
#: know more than one shape. It lives here rather than in the script that reads it because two
#: files needing the same profile string is how a directory comes to hold a shape nobody guards.
JUDGEMENT_ANSWERS_PROFILE: Final = "exulanica.visual-gate-judgement/v3"

#: A public string may not repeat this many consecutive words of a reply, unless the judge was
#: shown those words in the ask itself. Four is too few: short runs of ordinary English, which
#: the rubric's own prose uses, recur in any reply.
_PRIVATE_RUN: Final = 5

#: A span in quotes, the way prose names a part of what somebody wrote.
_QUOTED: Final = re.compile(r"'([^'\n]{2,})'|\"([^\"\n]{2,})\"|\u201c([^\u201d\n]{2,})\u201d")


class GateEvidenceError(ValueError):
    """Evidence the gate cannot decide from. Nothing is emitted for a key that raises this."""


@dataclass(frozen=True, slots=True)
class ReasonFollowUp:
    """The one follow-up a picture may get, when its answer arrived without words.

    ``shown`` is exactly what the judge read, ``words`` their reply exactly as typed, which goes
    only to the record's private companion, ``typed_by`` who typed it, which has to be the judge,
    and ``given_at`` when it reached the asking session, as an ISO time in UTC. The reply is the
    answer's reason and never its answer.
    """

    shown: str
    words: str | None
    typed_by: str | None
    given_at: str | None = None


@dataclass(frozen=True, slots=True)
class CarriedWords:
    """Words the judge wrote about a picture under an earlier rubric version, kept for its ask.

    ``rubric_version`` and ``rubric_sha256`` name the version they were written under,
    ``given_at`` when they reached the asking session, as an ISO time in UTC, and ``given_as``
    how they were given, in words that quote nothing the judge wrote. The words go only to the
    record's private companion and are never an answer.
    """

    words: str
    typed_by: str
    rubric_version: int
    rubric_sha256: str
    given_at: str
    given_as: str


@dataclass(frozen=True, slots=True)
class PictureAnswer:
    """What the judge gave for one picture, exactly as given, or that the picture was not asked.

    ``picked`` is the option the judge picked, one of the rubric's options, or None when the judge
    typed a reply instead. ``words`` is the judge's own words exactly as typed: the notes added to
    the pick, or the typed reply, or None when the judge picked an option and wrote nothing. They
    go only to the record's private companion. ``typed_by`` names who gave them, which has to be
    the judge, and ``given_at`` when the reply reached the asking session, as an ISO time in UTC.
    ``follow_up`` is the one request for a reason a picture may get when its answer arrived
    without words. ``carried`` holds words the judge wrote about this picture under an earlier
    rubric version, and ``notice`` the line shown above the question because of them. A picture
    that was not asked carries none of these.
    """

    label: str
    capture_sha256: str
    asked: bool
    picked: str | None = None
    words: str | None = None
    typed_by: str | None = None
    follow_up: ReasonFollowUp | None = None
    carried: tuple[CarriedWords, ...] = ()
    notice: str | None = None
    given_at: str | None = None


@dataclass(frozen=True, slots=True)
class JudgedAnswers:
    """The named judge's answers for the three route captures, one per picture, in route order."""

    judge: str
    judged_on: str
    rubric_sha256: str
    pictures: Sequence[PictureAnswer]


def _is_placeholder(name: str) -> bool:
    folded = " ".join(name.split()).casefold()
    return folded == "" or folded in _ROLE_WORDS or _TEMPLATE_SLOT.match(folded) is not None


def _require_name(value: object, what: str) -> str:
    if not isinstance(value, str) or _is_placeholder(value):
        raise GateEvidenceError(
            f"{JUDGED_KEY} needs {what}; a blank, a role or a placeholder is not a name"
        )
    return value


def _has_reason(words: str) -> bool:
    """Whether words say more than yes or no: an opening answer word is not a reason."""
    opening = _OPENING_ANSWER.match(words)
    rest = words[opening.end() :] if opening is not None else words
    return any(character.isalnum() for character in rest)


def _is_skip(words: str) -> bool:
    return " ".join(words.split()).casefold() in _SKIP_MARKERS


def words_fingerprint(words: str | None) -> dict[str, Any]:
    """What a public record carries in place of the judge's words: their SHA-256 and byte count.

    The words themselves are kept only in the record's private companion. A reply without words
    has a null digest and a zero count, and nothing of it is private.
    """
    if words is None:
        return {"words_sha256": None, "words_bytes": 0, "words_private": False}
    data = words.encode("utf-8")
    return {
        "words_sha256": hashlib.sha256(data).hexdigest(),
        "words_bytes": len(data),
        "words_private": True,
    }


def judge_words_path(record_path: str) -> str:
    """Where the private companion of the public record at ``record_path`` lives."""
    name = record_path.rsplit("/", 1)[-1]
    if not name.endswith(".json") or name == ".json":
        raise GateEvidenceError(f"{record_path} does not name a JSON record")
    return f"{JUDGE_WORDS_DIRECTORY}/{name}"


def _given_at(where: str, value: object, judged_on: str | None = None) -> str:
    if not isinstance(value, str) or not _ISO_TIME.match(value):
        raise GateEvidenceError(f"{where} does not say when it was given, as an ISO time in UTC")
    if judged_on is not None and value[:10] != judged_on:
        raise GateEvidenceError(f"{where} was given on {value[:10]}, not on {judged_on}")
    return value


def _folded(text: str) -> str:
    """Text as the private-words check compares it: case, punctuation and spacing folded away."""
    return " ".join(re.sub(r"[^\w']+", " ", text.casefold()).split())


def refuse_private_words(
    value: Any,
    private: Sequence[str],
    *,
    shown: Sequence[str] = (),
    lines: Sequence[str] = (),
    quoted: bool = True,
    path: str = "$",
) -> None:
    """Refuse a public record that would carry any of the judge's words.

    ``private`` holds the judge's words, ``lines`` any line written for an ask that may quote
    them, and ``shown`` what the judge was shown. No string in ``value`` may contain a private
    text or line of three words or more, a run of five of the judge's words that the judge was
    not shown, or, unless ``quoted`` is false, a quoted part of the judge's words other than an
    answer word. Prose quotes to name what somebody wrote; source code quotes single common words
    for other reasons, so a check over code turns the last test off.
    """
    texts = [_folded(text) for text in private if isinstance(text, str) and text.strip()]
    written = [_folded(line) for line in lines if isinstance(line, str) and line.strip()]
    if not texts and not written:
        return
    visible = [_folded(text) for text in shown]
    whole = [text for text in (*texts, *written) if len(text.split()) >= 3]
    runs: set[str] = set()
    for text in texts:
        words = text.split()
        for index in range(len(words) - _PRIVATE_RUN + 1):
            run = " ".join(words[index : index + _PRIVATE_RUN])
            if not any(f" {run} " in f" {line} " for line in visible):
                runs.add(run)

    def check(item: Any, where: str) -> None:
        if isinstance(item, str):
            folded = f" {_folded(item)} "
            if any(f" {text} " in folded for text in whole) or any(
                f" {run} " in folded for run in runs
            ):
                raise GateEvidenceError(
                    f"{where} carries the judge's words, which stay in the private companion"
                )
            for match in _QUOTED.finditer(item) if quoted else ():
                span = _folded(next(group for group in match.groups() if group is not None))
                if len(span) < 2 or span in {"yes", "no"}:
                    continue
                pattern = re.compile(rf"(?<!\w){re.escape(span)}(?!\w)")
                if any(pattern.search(text) for text in texts):
                    raise GateEvidenceError(
                        f"{where} quotes the judge's words, which stay in the private companion"
                    )
        elif isinstance(item, Mapping):
            for name, entry in item.items():
                check(name, f"{where}.<key>")
                check(entry, f"{where}.{name}")
        elif isinstance(item, list | tuple):
            for index, entry in enumerate(item):
                check(entry, f"{where}[{index}]")

    check(value, path)


def judge_words_record(
    *, record_path: str, judge: str, replies: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """The private companion of a public record: every reply the judge gave, words included."""
    entries = []
    for reply in replies:
        words = reply.get("words")
        if words is not None and not isinstance(words, str):
            raise GateEvidenceError("the judge's words must be text")
        entries.append({**reply, **words_fingerprint(words)})
    return {
        "profile": JUDGE_WORDS_PROFILE,
        "publicRecord": record_path,
        "judge": judge,
        "replies": entries,
    }


def _companion_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def words_from_companion(document: Mapping[str, Any], record_path: str) -> dict[str, str]:
    """The judge's words a private companion holds, keyed by SHA-256, each checked against it."""
    if (
        not isinstance(document, Mapping)
        or document.get("profile") != JUDGE_WORDS_PROFILE
        or document.get("publicRecord") != record_path
    ):
        raise GateEvidenceError(f"this is not the private companion of {record_path}")
    words: dict[str, str] = {}
    for reply in document.get("replies", []):
        text = reply.get("words")
        stated = (reply.get("words_sha256"), reply.get("words_bytes"))
        fingerprint = words_fingerprint(text)
        if stated != (fingerprint["words_sha256"], fingerprint["words_bytes"]):
            raise GateEvidenceError(
                f"a reply in the companion of {record_path} does not match its own digest"
            )
        if text is not None:
            words[fingerprint["words_sha256"]] = text
    return words


def _words_or_none(words: object) -> str | None:
    return words if isinstance(words, str) and words.strip() != "" else None


def _carried(where: str, picture: PictureAnswer, judge: str) -> list[dict[str, Any]]:
    """The earlier words an ask carries, checked, or a refusal. Empty when there are none."""
    carried = tuple(picture.carried)
    if not carried:
        if picture.notice is not None:
            raise GateEvidenceError(
                f"{where}: a notice was shown above the question with no reason"
            )
        return []
    if picture.notice != CARRIED_WORDS_NOTICE:
        raise GateEvidenceError(
            f"{where}: carried words need the line {CARRIED_WORDS_NOTICE!r} above the question"
        )
    superseded = {version.rubric_version: version for version in SUPERSEDED_VERSIONS}
    entries = []
    for item in carried:
        if not isinstance(item, CarriedWords):
            raise GateEvidenceError(f"{where}: carried words must be CarriedWords")
        if item.typed_by != judge:
            raise GateEvidenceError(f"{where}: carried words were not typed by the judge")
        version = superseded.get(item.rubric_version)
        if version is None or version.rubric_sha256 != item.rubric_sha256:
            raise GateEvidenceError(
                f"{where}: carried words must name a superseded rubric version and its digest"
            )
        if not isinstance(item.words, str) or not _has_reason(item.words):
            raise GateEvidenceError(f"{where}: carried words must say something")
        _given_at(f"{where}: carried words", item.given_at)
        if not isinstance(item.given_as, str) or item.given_as.strip() == "":
            raise GateEvidenceError(f"{where}: carried words must say how they were given")
        entries.append(
            {
                **words_fingerprint(item.words),
                "typedBy": judge,
                "rubricVersion": item.rubric_version,
                "rubricSha256": item.rubric_sha256,
                "givenAt": item.given_at,
                "givenAs": item.given_as,
            }
        )
    return entries


def typed_reply_answer(words: str) -> str | None:
    """How a reply typed in place of a pick is read: ``"no"``, or None when it is not an answer.

    It is no only when it holds the whole word no, in any case, and not the whole word yes. It is
    never yes: a yes must be picked, so a typed reply can fail the key and never pass it.
    """
    if not isinstance(words, str) or _is_skip(words):
        return None
    if _WHOLE_NO.search(words) and not _WHOLE_YES.search(words):
        return "no"
    return None


def _answer(
    label: str, picture: PictureAnswer, judge: str, judged_on: str, answered_version: int
) -> dict[str, Any]:
    """The judge's answer for an asked picture and the fingerprints it is recorded with.

    ``answered_version`` is the rubric version the judge was asked under, and every reason the
    judge gave in this ask is labelled with it and with the time it was given.
    """
    where = f"{JUDGED_KEY}: {PICTURE_TITLES[label]} ({label})"
    if picture.typed_by != judge:
        raise GateEvidenceError(
            f"{where} was not typed by the judge: it names {picture.typed_by!r}, and only "
            f"{judge!r} may answer"
        )
    _given_at(where, picture.given_at, judged_on)
    words = picture.words
    if words is not None and not isinstance(words, str):
        raise GateEvidenceError(f"{where}: the judge's words must be text")
    blank = words is None or words.strip() == ""
    if not blank and _is_skip(words):
        raise GateEvidenceError(f"{where} was skipped, which is not an answer")
    if picture.picked is None:
        if blank:
            raise GateEvidenceError(f"{where} was skipped, which is not an answer")
        typed = typed_reply_answer(words)
        if typed is None:
            raise GateEvidenceError(
                f"{where}: the judge picked no option, and a typed reply counts only as a no, "
                "when it holds the whole word no and not the whole word yes; this one does not, "
                "so it is not an answer and nothing is inferred from it"
            )
        answer = typed
    elif picture.picked in OPTION_ANSWERS:
        answer = OPTION_ANSWERS[picture.picked]
    else:
        raise GateEvidenceError(
            f"{where}: {picture.picked!r} is not one of the options the judge is offered, "
            f"{' and '.join(repr(option) for option in ANSWER_OPTIONS)}"
        )
    own_reason = not blank and _has_reason(words)
    entry: dict[str, Any] = {
        "state": "answered",
        "picked": picture.picked,
        "answer": answer,
        "readFrom": ("the option picked" if picture.picked is not None else "the typed-reply rule"),
        "rubricVersion": answered_version,
        "givenAt": picture.given_at,
        **words_fingerprint(None if blank else words),
        "typedBy": judge,
    }
    reasons: list[dict[str, Any]] = []
    carried = _carried(where, picture, judge)
    if carried:
        entry["noticeAboveTheQuestion"] = picture.notice
        entry["carried"] = carried
        if answer == "no":
            reasons.extend(
                {
                    "from": "earlier words",
                    "rubricVersion": item["rubricVersion"],
                    "givenAt": item["givenAt"],
                    "givenAs": item["givenAs"],
                    **words_fingerprint(earlier.words),
                }
                for item, earlier in zip(carried, picture.carried, strict=True)
            )
        elif not own_reason:
            raise GateEvidenceError(
                f"{where}: a yes after carried words needs new words, because the earlier words "
                "may contradict it; the picture is not asked again"
            )
    if own_reason:
        reasons.append(
            {
                "from": "reply",
                "rubricVersion": answered_version,
                "givenAt": picture.given_at,
                "givenAs": "in reply to this ask",
                **words_fingerprint(words),
            }
        )
    follow = picture.follow_up
    if follow is None:
        if not reasons:
            raise GateEvidenceError(
                f"{where} has no reason in the judge's own words: an answer without the judge's "
                "own words about why is not recorded"
            )
        entry["reason"] = reasons
        return entry
    if not isinstance(follow, ReasonFollowUp):
        raise GateEvidenceError(f"{where}: a follow-up must be a ReasonFollowUp")
    if reasons:
        raise GateEvidenceError(
            f"{where} was asked for a reason its answer already gave; only an answer without "
            "words gets a follow-up"
        )
    wording = reason_follow_up(answer)
    if follow.shown != wording:
        raise GateEvidenceError(
            f"{where}: the follow-up was not asked in the rubric's words, {wording!r}"
        )
    if follow.typed_by != judge:
        raise GateEvidenceError(
            f"{where}: the follow-up was not typed by the judge: it names {follow.typed_by!r}"
        )
    _given_at(f"{where}: the follow-up", follow.given_at, judged_on)
    reply = follow.words
    if not isinstance(reply, str) or reply.strip() == "" or _is_skip(reply):
        raise GateEvidenceError(
            f"{where} has no reason in the judge's own words: the follow-up got no words"
        )
    if not _has_reason(reply):
        raise GateEvidenceError(
            f"{where} has no reason in the judge's own words: the follow-up reply does not say why"
        )
    entry["followUp"] = {
        "asked": follow.shown,
        **words_fingerprint(reply),
        "typedBy": judge,
        "givenAt": follow.given_at,
    }
    entry["reason"] = [
        {
            "from": "follow-up",
            "rubricVersion": answered_version,
            "givenAt": follow.given_at,
            "givenAs": "in reply to the follow-up",
            **words_fingerprint(reply),
        }
    ]
    return entry


def judge_words(
    evidence: JudgedAnswers, answered_version: int = RUBRIC_VERSION
) -> list[dict[str, Any]]:
    """Every reply the judge gave, words included, as the record's private companion keeps them."""
    replies: list[dict[str, Any]] = []
    for picture in evidence.pictures:
        if picture.asked is not True:
            continue
        common = {"label": picture.label, "picture": PICTURE_TITLES[picture.label]}
        for item in picture.carried:
            replies.append(
                {
                    **common,
                    "kind": "carried",
                    "rubricVersion": item.rubric_version,
                    "rubricSha256": item.rubric_sha256,
                    "givenAt": item.given_at,
                    "givenAs": item.given_as,
                    "picked": None,
                    "words": _words_or_none(item.words),
                    "typedBy": item.typed_by,
                }
            )
        replies.append(
            {
                **common,
                "kind": "reply",
                "rubricVersion": answered_version,
                "givenAt": picture.given_at,
                "shownAbove": picture.notice,
                "picked": picture.picked,
                "words": _words_or_none(picture.words),
                "typedBy": picture.typed_by,
            }
        )
        follow = picture.follow_up
        if isinstance(follow, ReasonFollowUp):
            replies.append(
                {
                    **common,
                    "kind": "follow-up",
                    "rubricVersion": answered_version,
                    "givenAt": follow.given_at,
                    "shown": follow.shown,
                    "picked": None,
                    "words": _words_or_none(follow.words),
                    "typedBy": follow.typed_by,
                }
            )
    return replies


def judge_words_file(
    record_path: str, evidence: JudgedAnswers, answered_version: int = RUBRIC_VERSION
) -> tuple[str, bytes]:
    """The private companion of the record at ``record_path``: where it lives, and its bytes."""
    document = judge_words_record(
        record_path=record_path,
        judge=evidence.judge,
        replies=judge_words(evidence, answered_version),
    )
    return judge_words_path(record_path), _companion_bytes(document)


def _private_texts(evidence: JudgedAnswers) -> list[str]:
    return [reply["words"] for reply in judge_words(evidence) if reply["words"] is not None]


def _shown_texts() -> list[str]:
    return [
        RUBRIC_QUESTION,
        RUBRIC_GUIDANCE,
        ANSWER_REQUIREMENT,
        CARRIED_WORDS_NOTICE,
        *ANSWER_OPTIONS,
        *(reason_follow_up(answer) for answer in OPTION_ANSWERS.values()),
    ]


def _words_for(holder: Mapping[str, Any], words: Mapping[str, str], what: str) -> str | None:
    digest = holder.get("words_sha256")
    if digest is None:
        return None
    if digest not in words:
        raise GateEvidenceError(f"the judge's words for {what} are not in the private companion")
    return words[digest]


def judged_answers_from_record(
    detail: Mapping[str, Any], words: Mapping[str, str]
) -> JudgedAnswers:
    """The answers a retained record carries, with the judge's words from its private companion.

    ``words`` maps each SHA-256 the record carries to the words, as :func:`words_from_companion`
    reads them, so that the key can be decided again from exactly what the judge gave.
    """
    try:
        states = [entry["state"] for entry in detail["pictures"]]
        if not set(states) <= {"answered", NOT_ASKED}:
            raise GateEvidenceError(f"the record's {JUDGED_KEY} block has unknown states {states}")
        pictures = []
        for entry in detail["pictures"]:
            follow = entry.get("followUp")
            title = entry["picture"]
            pictures.append(
                PictureAnswer(
                    label=entry["label"],
                    capture_sha256=entry["captureSha256"],
                    asked=entry["state"] == "answered",
                    picked=entry.get("picked"),
                    words=_words_for(entry, words, title),
                    typed_by=entry.get("typedBy"),
                    follow_up=None
                    if follow is None
                    else ReasonFollowUp(
                        shown=follow["asked"],
                        words=_words_for(follow, words, f"the follow-up of {title}"),
                        typed_by=follow["typedBy"],
                        given_at=follow["givenAt"],
                    ),
                    carried=tuple(
                        CarriedWords(
                            words=_words_for(item, words, f"the earlier words of {title}"),
                            typed_by=item["typedBy"],
                            rubric_version=item["rubricVersion"],
                            rubric_sha256=item["rubricSha256"],
                            given_at=item["givenAt"],
                            given_as=item["givenAs"],
                        )
                        for item in entry.get("carried", [])
                    ),
                    notice=entry.get("noticeAboveTheQuestion"),
                    given_at=entry.get("givenAt"),
                )
            )
        return JudgedAnswers(
            judge=detail["judge"],
            judged_on=detail["judgedOn"],
            rubric_sha256=detail["answeredAgainst"]["rubricSha256"],
            pictures=tuple(pictures),
        )
    except (KeyError, TypeError) as error:
        raise GateEvidenceError(f"the record's {JUDGED_KEY} block is incomplete") from error


def _fingerprinted(holder: Mapping[str, Any]) -> bool:
    return (
        holder["words_private"] is True
        and _SHA256.match(str(holder["words_sha256"])) is not None
        and holder["words_bytes"] > 0
    )


def recompose_judged(detail: Mapping[str, Any]) -> bool:
    """The judged key's value from the answers a public record states, without the judge's words.

    A clone without the private companion cannot read a reply again. It can still check that the
    stated answers compose to the stated value, that no picture was answered after the first no,
    and that every answer was typed by the judge, says when it was given and carries the
    fingerprints of the judge's words for each of its reasons.
    """
    try:
        entries = list(detail["pictures"])
        if [entry["label"] for entry in entries] != list(CAPTURE_LABELS):
            raise GateEvidenceError(f"the record's {JUDGED_KEY} block is not in route order")
        decisive: str | None = None
        for entry in entries:
            where = f"{JUDGED_KEY}: {entry['picture']}"
            if entry["state"] == "answered":
                if decisive is not None:
                    raise GateEvidenceError(f"{where} was answered after the decisive no")
                if entry["answer"] not in ("yes", "no") or entry["typedBy"] != detail["judge"]:
                    raise GateEvidenceError(f"{where} is not an answer the judge gave")
                if entry["picked"] is None and entry["answer"] != "no":
                    raise GateEvidenceError(f"{where} reads a typed reply as a yes")
                reasons = list(entry["reason"])
                if not reasons or not all(_fingerprinted(reason) for reason in reasons):
                    raise GateEvidenceError(f"{where} carries no fingerprint of the judge's words")
                _given_at(where, entry["givenAt"], detail["judgedOn"])
                for reason in reasons:
                    _given_at(where, reason["givenAt"])
                for item in entry.get("carried", []):
                    if item["typedBy"] != detail["judge"] or not _fingerprinted(item):
                        raise GateEvidenceError(f"{where} carries words the judge did not give")
                    _given_at(where, item["givenAt"])
                follow = entry.get("followUp")
                if follow is not None:
                    if follow["typedBy"] != detail["judge"] or not _fingerprinted(follow):
                        raise GateEvidenceError(f"{where} is not an answer the judge gave")
                    _given_at(where, follow["givenAt"], detail["judgedOn"])
                if entry["answer"] == "no":
                    decisive = entry["label"]
            elif entry["state"] == NOT_ASKED:
                if decisive is None:
                    raise GateEvidenceError(
                        f"{where} was not asked, and no earlier picture got a no"
                    )
            else:
                raise GateEvidenceError(f"the record's {JUDGED_KEY} block has an unknown state")
        value = decisive is None
        if (detail["decisiveNo"], detail["value"]) != (decisive, value):
            raise GateEvidenceError(
                f"the record's {JUDGED_KEY} value does not follow from its answers"
            )
        return value
    except (KeyError, TypeError) as error:
        raise GateEvidenceError(f"the record's {JUDGED_KEY} block is incomplete") from error


def _refuse_forbidden_text(value: Any, path: str = "$") -> None:
    """Walk a record for forbidden text. Complete over canonical JSON, which is the premise.

    A string can carry text, a mapping and a list can hold one, and no other JSON type can, so
    this needs no list of record kinds. It is complete only because what reaches it is canonical
    JSON: a set, a dataclass or any other container would be walked past in silence, and
    :func:`digest_bound` is what holds callers to that form.
    """
    if isinstance(value, str):
        for text in _FORBIDDEN_TEXT:
            if text in value:
                raise GateEvidenceError(f"{path} carries {text!r}, which no record may contain")
    elif isinstance(value, Mapping):
        for name, item in value.items():
            _refuse_forbidden_text(name, f"{path}.<key>")
            _refuse_forbidden_text(item, f"{path}.{name}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _refuse_forbidden_text(item, f"{path}[{index}]")


def digest_bound(record: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap ``record`` in the digest-bound envelope, refusing floats and forbidden text."""
    _refuse_forbidden_text(record)
    encoded = canonical_json(record)
    return {
        "profile": DIGEST_BOUND_PROFILE,
        "record": dict(record),
        "record_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _bound_file(entry: Mapping[str, Any], where: str) -> None:
    if not {"path", "byte_size", "sha256"} <= set(entry):
        raise GateEvidenceError(f"{where} needs path, byte_size and sha256")
    if not isinstance(entry["byte_size"], int) or isinstance(entry["byte_size"], bool):
        raise GateEvidenceError(f"{where}.byte_size must be an integer")
    if not _SHA256.match(str(entry["sha256"])):
        raise GateEvidenceError(f"{where}.sha256 must be a hex SHA-256")


def _companion_binding(path: str, companion: bytes) -> dict[str, Any]:
    return {
        "path": path,
        "byte_size": len(companion),
        "sha256": hashlib.sha256(companion).hexdigest(),
        "tracked": False,
        "holds": (
            "every reply the judge gave for this record, words included, with the time and rubric "
            "version each was given under; this record carries the SHA-256 and byte count of the "
            "words in their place"
        ),
    }
