"""Build a visual gate record from measured inputs, and refuse to build one from anything less.

The gate exists so that a generated corridor can be shown better than what it replaces, which is
only possible if the gate can say FAIL. So this module decides; it does not transcribe:

*   **Every mechanical key is re-decided here** from the measured fields its canonical definition
    names. A caller cannot hand in ``True``; it hands in the numbers, and a number that is missing
    is a key with no evidence, which is refused rather than emitted.
*   **The judged key is decided only from a named human's answers**, under version 5 of
    docs/visual-gate-rubric.md: one question per picture, asked in route order, and the first no
    decides. A reply typed in place of a pick can only ever be a no. No name, a placeholder in
    place of a name, a rubric the judge was not shown, a picture other than the one bound, an
    answer somebody else typed, an answer with no reason in the judge's own words, a follow-up
    nobody needed, an answer given after a decisive no and a key with a picture unasked are all
    refused. Nothing in this module can produce ``readsAsInhabitedStreet`` from a measurement, and
    nothing may.
*   **The judge's words stay private.** A public record carries, for each reply, the SHA-256 and
    byte count of the judge's words and binds a companion record under ``.exulanica/judge-words/``
    that holds them. The companion never enters the repository, and
    :func:`refuse_private_words` refuses a public record that would carry any of the words.
*   **The corridor bar is every key.** A candidate passes only when all nine keys hold, the judged
    one by three picked yes answers, and never against a baseline that itself holds every key,
    because then the gate could not tell the candidate from what it replaces.

The record shape follows the three retained rejections, so the four can be read side by side, and
the envelope is the repository's digest-bound profile: ``record_sha256`` is the SHA-256 of
``canonical_json(record)``, which refuses floats. Measured values that are not integers are
therefore written as decimal strings by the caller, the way the retained Melbourne record wrote
``"16.7"``, and never rounded silently here.

Pure: no I/O, no clock, no database. The script that runs a capture reads files and passes the
parsed documents in.
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
    AUTHENTICATION_CONDITIONS,
    CANONICAL_KEYS,
    CANONICAL_SPELLINGS,
    CAPTURE_LABELS,
    CARRIED_WORDS_NOTICE,
    CLASSIFICATION,
    EVIDENCE_KINDS,
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
    SUPERSEDED_VERSIONS,
    THRESHOLDS,
    TYPED_REPLY_RULE,
    VERSION_4,
    WORDS_STORAGE,
    GateKey,
    key,
    reason_follow_up,
    resolve,
)

__all__ = [
    "BRIEFED_CRITERIA",
    "COMPOSITION",
    "CORRIDOR_BAR",
    "DIGEST_BOUND_PROFILE",
    "JUDGE_WORDS_DIRECTORY",
    "JUDGE_WORDS_PROFILE",
    "CarriedWords",
    "GateEvidenceError",
    "JudgedAnswers",
    "PictureAnswer",
    "ReasonFollowUp",
    "beats_baseline",
    "build_gate",
    "calibration_words_file",
    "decide_judged",
    "decide_mechanical",
    "digest_bound",
    "judge_words",
    "judge_words_file",
    "judge_words_path",
    "judge_words_record",
    "judged_answers_from_record",
    "recompose_judged",
    "reconciliation_record",
    "refuse_private_words",
    "typed_reply_answer",
    "visual_gate_record",
    "words_fingerprint",
    "words_from_companion",
]

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

#: Text a record may never carry, the same three the retained-records test refuses.
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


def _integers(spelling: str, measured: Mapping[str, Any], fields: Sequence[str]) -> dict[str, int]:
    values: dict[str, int] = {}
    for field in fields:
        if field not in measured:
            raise GateEvidenceError(
                f"{spelling}: no evidence for {field!r}. A key without its measurement is not "
                "emitted."
            )
        value = measured[field]
        if isinstance(value, bool) or not isinstance(value, int):
            raise GateEvidenceError(
                f"{spelling}: {field!r} must be a measured integer, got {type(value).__name__}"
            )
        if value < 0:
            raise GateEvidenceError(f"{spelling}: {field!r} cannot be negative, got {value}")
        values[field] = value
    return values


def decide_mechanical(spelling: str, measured: Mapping[str, Any]) -> bool:
    """Decide one mechanical key from the fields its definition names, and nothing else."""
    item = key(spelling)
    if item.spelling != spelling:
        raise GateEvidenceError(
            f"{spelling!r} is a retained spelling of {item.spelling!r}; a new record is written "
            "in canonical spellings only"
        )
    if item.evidence_kind != "mechanical":
        raise GateEvidenceError(f"{spelling} is judged, not measured")
    v = _integers(spelling, measured, item.decided_by)
    t = THRESHOLDS
    if spelling == "continuousTexturedStreetAndFacades":
        return (
            v["streetAndFacadeTriangles"] > 0
            and v["untexturedStreetAndFacadeTriangles"] == 0
            and v["routeSupportGapSamples"] == 0
        )
    if spelling == "noCutsOrFloatingGeometry":
        return all(v[field] == 0 for field in item.decided_by)
    if spelling == "usefulEyeLevelMovement":
        return (
            v["walkedDisplacementMm"] >= t["minimumWalkedMm"]
            and v["maxLateralDeviationMm"] <= t["maximumLateralDeviationMm"]
            and v["recoveryEvents"] == 0
            and v["harnessPositionWrites"] == 0
            and v["traceSamples"] > 0
            and v["routeSupportGapSamples"] == 0
            and v["maxEyeHeightErrorMm"] <= t["eyeHeightToleranceMm"]
            and v["maxSupportResampleDeltaMm"] <= t["supportAgreementMm"]
        )
    if spelling == "completeCapsuleClearanceVerification":
        return (
            v["capsuleSamples"] > 0
            and v["capsuleSamplesChecked"] == v["capsuleSamples"]
            and v["capsuleTriangleContactSamples"] == 0
            and v["capsuleRingContactSamples"] == 0
        )
    if spelling == "practicalBrowserBudget":
        return (
            all(v[name] <= limit for name, limit in MELBOURNE_ENVELOPE.items())
            and v["gpuErrors"] == 0
            and v["pageErrors"] == 0
        )
    if spelling in {"companionPresent", "reticlePresent"}:
        shown = (
            "capturesWithCompanionShown"
            if spelling == "companionPresent"
            else ("capturesWithReticleCentred")
        )
        return v["captures"] == len(CAPTURE_LABELS) and v[shown] == v["captures"]
    if spelling == "authenticatedShellAndAuthoredHandlersPreserved":
        return (
            v["captures"] == len(CAPTURE_LABELS)
            and v["capturesInProductShell"] == v["captures"]
            and v["foreignListeners"] == 0
            and v["productWindowKeydownListeners"] > 0
            and v["interactionsNotCarriedByProduct"] == 0
            and v["substitutedPages"] == 0
        )
    raise GateEvidenceError(f"no decision is defined for {spelling}")  # pragma: no cover


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


def _answered_version(answered_sha256: str, rubric_sha256: str) -> dict[str, Any]:
    """The rubric version a judgement was given against, or a digest-mismatch refusal."""
    if answered_sha256 == rubric_sha256:
        return {"rubricVersion": RUBRIC_VERSION, "rubricSha256": rubric_sha256}
    previous = SUPERSEDED_VERSIONS[-1]
    if (
        previous.rubric_version == RUBRIC_VERSION - 1
        and answered_sha256 == previous.rubric_sha256
        and previous.shows_what_is_shown_now()
    ):
        return {
            "rubricVersion": previous.rubric_version,
            "rubricSha256": previous.rubric_sha256,
            "acceptedBecause": (
                f"version {RUBRIC_VERSION} shows the judge exactly what version "
                f"{previous.rubric_version} showed: the same question, guidance, requirement "
                "line, options, carried-words line and follow-up"
            ),
        }
    raise GateEvidenceError(
        f"{JUDGED_KEY}: the judge answered against rubric {answered_sha256}, and the record is "
        f"written with rubric {rubric_sha256}; a rubric digest mismatch is refused"
    )


def decide_judged(
    evidence: JudgedAnswers, *, rubric_sha256: str, captures: Mapping[str, str]
) -> tuple[bool, dict[str, Any]]:
    """The judged key's value and what it was decided from, under rubric version 5.

    ``rubric_sha256`` is the digest of the rubric the record is written with, and ``captures``
    maps each route label to the SHA-256 of the capture the record binds. The judge's answers
    must name both, so a judgement cannot be carried onto another rubric or picture. The one
    exception is a judgement given against the version this one superseded when that version
    showed the judge exactly what this one shows; both digests are then carried.
    """
    if not isinstance(evidence, JudgedAnswers):
        raise GateEvidenceError(f"{JUDGED_KEY} needs the named judge's answers")
    judge = _require_name(evidence.judge, "the named human judge's name")
    if not isinstance(evidence.judged_on, str) or not _ISO_DATE.match(evidence.judged_on):
        raise GateEvidenceError(f"{JUDGED_KEY}: judged_on must be an ISO date")
    if not isinstance(evidence.rubric_sha256, str) or not _SHA256.match(evidence.rubric_sha256):
        raise GateEvidenceError(f"{JUDGED_KEY}: rubric_sha256 must name the rubric answered")
    if not isinstance(rubric_sha256, str) or not _SHA256.match(rubric_sha256):
        raise GateEvidenceError(f"{JUDGED_KEY}: the record names no rubric digest to check against")
    answered = _answered_version(evidence.rubric_sha256, rubric_sha256)
    pictures = tuple(evidence.pictures)
    labels = [getattr(picture, "label", None) for picture in pictures]
    if labels != list(CAPTURE_LABELS) or not all(
        isinstance(picture, PictureAnswer) for picture in pictures
    ):
        raise GateEvidenceError(
            f"{JUDGED_KEY}: one answer entry is required for each of "
            f"{', '.join(CAPTURE_LABELS)}, in that order; got {labels}"
        )
    if set(captures) != set(CAPTURE_LABELS):
        raise GateEvidenceError(f"{JUDGED_KEY}: the record binds no capture for every picture")

    entries: list[dict[str, Any]] = []
    decisive: str | None = None
    for picture in pictures:
        label = picture.label
        bound = captures[label]
        if not isinstance(bound, str) or not _SHA256.match(bound):
            raise GateEvidenceError(f"{JUDGED_KEY}: capture {label} is not bound by digest")
        if picture.capture_sha256 != bound:
            raise GateEvidenceError(
                f"{JUDGED_KEY}: {PICTURE_TITLES[label]} was answered about capture "
                f"{picture.capture_sha256!r}, and the record binds {bound} for {label}"
            )
        entry: dict[str, Any] = {
            "label": label,
            "picture": PICTURE_TITLES[label],
            "captureSha256": bound,
        }
        if picture.asked is True:
            if decisive is not None:
                raise GateEvidenceError(
                    f"{JUDGED_KEY}: {PICTURE_TITLES[label]} ({label}) was answered after the "
                    f"decisive no at {decisive}; the rubric does not ask it"
                )
            entry.update(
                _answer(label, picture, judge, evidence.judged_on, answered["rubricVersion"])
            )
            if entry["answer"] == "no":
                decisive = label
        elif picture.asked is False:
            given = (
                picture.picked,
                picture.words,
                picture.typed_by,
                picture.follow_up,
                tuple(picture.carried),
                picture.notice,
                picture.given_at,
            )
            if given != (None, None, None, None, (), None, None):
                raise GateEvidenceError(
                    f"{JUDGED_KEY}: {PICTURE_TITLES[label]} ({label}) was not asked and cannot "
                    "carry an answer"
                )
            if decisive is None:
                raise GateEvidenceError(
                    f"{JUDGED_KEY}: {PICTURE_TITLES[label]} ({label}) was not asked and no "
                    "earlier picture got a no, so the key cannot be written with a picture unasked"
                )
            entry["state"] = NOT_ASKED
        else:
            raise GateEvidenceError(f"{JUDGED_KEY}: {label}.asked must be true or false")
        entries.append(entry)

    value = decisive is None
    detail: dict[str, Any] = {
        "evidenceKind": "judged",
        "rubric": RUBRIC_PATH,
        "rubricVersion": RUBRIC_VERSION,
        "rubricSha256": rubric_sha256,
        "answeredAgainst": answered,
        "judge": judge,
        "judgedOn": evidence.judged_on,
        "question": RUBRIC_QUESTION,
        "guidance": RUBRIC_GUIDANCE,
        "requirement": ANSWER_REQUIREMENT,
        "options": list(ANSWER_OPTIONS),
        "optionAnswers": dict(OPTION_ANSWERS),
        "typedReplyRule": TYPED_REPLY_RULE,
        "composition": COMPOSITION,
        "pictures": entries,
        "decisiveNo": decisive,
        "value": value,
    }
    return value, detail


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


def build_gate(
    evidence: Mapping[str, Mapping[str, Any] | JudgedAnswers],
    *,
    rubric_sha256: str,
    captures: Mapping[str, str],
) -> tuple[dict[str, bool], dict[str, Any]]:
    """The ``hardPass`` block and the per-key evidence behind it, or :class:`GateEvidenceError`.

    Refuses an unknown spelling, a retained spelling, a missing key and a key whose evidence is of
    the wrong kind. Emits all nine keys or nothing. ``rubric_sha256`` and ``captures`` are what the
    judged answers are checked against; see :func:`decide_judged`.
    """
    for spelling in evidence:
        canonical = resolve(spelling)
        if canonical != spelling:
            raise GateEvidenceError(
                f"{spelling!r} is a retained spelling of {canonical!r}; write canonical spellings"
            )
    missing = [spelling for spelling in CANONICAL_SPELLINGS if spelling not in evidence]
    if missing:
        raise GateEvidenceError(
            f"no evidence for {', '.join(missing)}. A key without evidence is absent, and a gate "
            "record with an absent key is a strict subset of the block, so none is written."
        )
    hard_pass: dict[str, bool] = {}
    detail: dict[str, Any] = {}
    for item in CANONICAL_KEYS:
        given = evidence[item.spelling]
        if item.evidence_kind == "judged":
            if not isinstance(given, JudgedAnswers):
                raise GateEvidenceError(f"{item.spelling} is judged; pass the judge's answers")
            value, detail[item.spelling] = decide_judged(
                given, rubric_sha256=rubric_sha256, captures=captures
            )
        else:
            if isinstance(given, JudgedAnswers):
                raise GateEvidenceError(f"{item.spelling} is measured; pass its measurement")
            value = decide_mechanical(item.spelling, given)
            detail[item.spelling] = {
                "evidenceKind": "mechanical",
                "measurement": item.measurement,
                "decidedBy": {field: given[field] for field in item.decided_by},
                "value": value,
            }
        hard_pass[item.spelling] = value
    return hard_pass, detail


def _hard_pass(record: Mapping[str, Any], what: str) -> dict[str, bool]:
    block = record.get("hardPass") if isinstance(record, Mapping) else None
    if (
        not isinstance(block, Mapping)
        or set(block) != set(CANONICAL_SPELLINGS)
        or not all(isinstance(value, bool) for value in block.values())
    ):
        raise GateEvidenceError(f"the {what} record carries no complete nine-key hardPass block")
    gate = record.get("gate")
    if not isinstance(gate, Mapping) or gate.get("keySet") != GATE_KEY_SET_VERSION:
        raise GateEvidenceError(
            f"the {what} record was not scored against {GATE_KEY_SET_VERSION}, so it is not "
            "comparable"
        )
    return dict(block)


def beats_baseline(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
    """Whether a candidate clears the corridor bar against a baseline the bar can tell it from."""
    return all(_hard_pass(candidate, "candidate").values()) and not all(
        _hard_pass(baseline, "baseline").values()
    )


def _refuse_forbidden_text(value: Any, path: str = "$") -> None:
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


def visual_gate_record(
    *,
    profile: str,
    date: str,
    status: str,
    base: str,
    branch: str,
    predecessor_records: Sequence[Mapping[str, str]],
    artifacts: Sequence[Mapping[str, Any]],
    captures: Sequence[Mapping[str, Any]],
    browser: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any] | JudgedAnswers],
    rubric_sha256: str,
    authentication_condition: str,
    reason: str,
    checks: Mapping[str, Any],
    claims_not_made: Sequence[str],
    record_path: str,
    extra: Mapping[str, Any] | None = None,
    baseline: Mapping[str, Any] | None = None,
    baseline_path: str | None = None,
) -> dict[str, Any]:
    """A digest-bound visual gate record in the retained rejection records' shape.

    ``rubric_sha256`` is the digest of the rubric the record is written with; the judge must have
    answered against that rubric, or against the one it superseded when that showed the judge the
    same words. ``record_path`` is where the record is written, which names its private companion;
    the record binds that companion and carries none of the judge's words. ``baseline`` is the
    calibration record a candidate is read against. Without it the record is itself a baseline
    and its verdict is decided by the nine keys alone.
    """
    if not _ISO_DATE.match(date):
        raise GateEvidenceError("date must be an ISO date")
    if authentication_condition not in AUTHENTICATION_CONDITIONS:
        raise GateEvidenceError(
            f"authentication condition must be one of {', '.join(AUTHENTICATION_CONDITIONS)}"
        )
    if [capture.get("label") for capture in captures] != list(CAPTURE_LABELS):
        raise GateEvidenceError(
            f"captures must be exactly {', '.join(CAPTURE_LABELS)}, in route order"
        )
    for index, capture in enumerate(captures):
        _bound_file(capture, f"captures[{index}]")
    for index, artifact in enumerate(artifacts):
        _bound_file(artifact, f"artifacts[{index}]")
    if len(predecessor_records) == 0:
        raise GateEvidenceError("a gate record names the records it is calibrated against")
    for index, binding in enumerate(predecessor_records):
        if set(binding) != {"path", "record_sha256"} or not _SHA256.match(binding["record_sha256"]):
            raise GateEvidenceError(f"predecessor_records[{index}] needs path and record_sha256")
    if not claims_not_made:
        raise GateEvidenceError("a gate record states what it does not claim")

    hard_pass, detail = build_gate(
        evidence,
        rubric_sha256=rubric_sha256,
        captures={capture["label"]: capture["sha256"] for capture in captures},
    )
    all_hold = all(hard_pass.values())
    comparison: dict[str, Any] | None = None
    if baseline is not None:
        if baseline_path is None:
            raise GateEvidenceError("a baseline comparison names the baseline record's path")
        held_by_baseline = _hard_pass(baseline, "baseline")
        baseline_holds_every_key = all(held_by_baseline.values())
        comparison = {
            "baselineRecord": baseline_path,
            "baselineRecordSha256": hashlib.sha256(canonical_json(baseline)).hexdigest(),
            "bar": CORRIDOR_BAR,
            "baselineFailedKeys": [
                spelling for spelling, value in held_by_baseline.items() if not value
            ],
            "baselineHoldsEveryKey": baseline_holds_every_key,
            "candidateHoldsEveryKey": all_hold,
            "beatsBaseline": all_hold and not baseline_holds_every_key,
        }
        passed = comparison["beatsBaseline"]
    else:
        passed = all_hold
    record: dict[str, Any] = {
        "profile": profile,
        "date": date,
        "status": status,
        "verdict": "PASS" if passed else "FAIL",
        "base": base,
        "branch": branch,
        "predecessor_records": [dict(binding) for binding in predecessor_records],
        "artifacts": [dict(artifact) for artifact in artifacts],
        "captures": [dict(capture) for capture in captures],
        "browser": dict(browser),
        "authenticationCondition": authentication_condition,
        "hardPass": hard_pass,
        "gate": {
            "keySet": GATE_KEY_SET_VERSION,
            "corridorBar": CORRIDOR_BAR,
            "keys": detail,
            "failedKeys": [spelling for spelling, value in hard_pass.items() if not value],
        },
        "reason": reason,
        "checks": dict(checks),
        "claimsNotMade": list(claims_not_made),
    }
    if comparison is not None:
        record["baselineComparison"] = comparison
    judged = evidence[JUDGED_KEY]
    assert isinstance(judged, JudgedAnswers)  # build_gate refuses anything else
    answered = _answered_version(judged.rubric_sha256, rubric_sha256)
    companion_path, companion = judge_words_file(record_path, judged, answered["rubricVersion"])
    record["judgeWords"] = _companion_binding(companion_path, companion)
    for name, value in (extra or {}).items():
        if name in record:
            raise GateEvidenceError(f"extra field {name!r} would replace a gate field")
        record[name] = value
    refuse_private_words(record, _private_texts(judged), shown=_shown_texts())
    return digest_bound(record)


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


#: What each retained brief required for each key it named, quoted. The reconciliation record
#: carries these, and :func:`reconciliation_record` refuses any quote the brief does not contain,
#: so a paraphrase cannot stand in for the criterion a run was actually held to.
BRIEFED_CRITERIA: Final[Mapping[str, Mapping[str, str]]] = {
    "helsinki-visual-feasibility": {
        "continuousTexturedStreetAndFacades": (
            "Continuous source-textured ground along the initial route."
        ),
        "readsAsInhabitedStreet": "A recognizable Helsinki urban street at the pilot.",
        "noCutsOrFloatingGeometry": "No floating or cut geometry visible on the initial route.",
        "usefulEyeLevelMovement": (
            "Correct eye-level first-person movement on simplified verified support."
        ),
        "companionPresent": "Existing Companion and reticle remain present.",
        "reticlePresent": "Existing Companion and reticle remain present.",
        "authenticatedShellAndAuthoredHandlersPreserved": (
            "Existing authored-object and authentication handlers are not replaced."
        ),
    },
    "helsinki-terminal-lod-successor": {
        "continuousTexturedStreetAndFacades": (
            "continuous source-textured street along the initial route;"
        ),
        "readsAsInhabitedStreet": "a recognizable Helsinki urban scene;",
        "noCutsOrFloatingGeometry": "no cut, floating or camera-occluding geometry;",
        "usefulEyeLevelMovement": (
            "movement only over stable terminal support with full capsule clearance;"
        ),
        "completeCapsuleClearanceVerification": (
            "A vertical capsule of radius 0.34 metres and total height 1.9 metres, grounded "
            "on that support, intersects no visual triangle except the support surface."
        ),
        "companionPresent": "Companion and reticle present;",
        "reticlePresent": "Companion and reticle present;",
        "authenticatedShellAndAuthoredHandlersPreserved": (
            "authenticated shell and authored handlers preserved."
        ),
    },
    "melbourne-c4-29-visual-feasibility": {
        "continuousTexturedStreetAndFacades": (
            "continuous source-textured street and facades along the complete route;"
        ),
        "readsAsInhabitedStreet": "a recognizable Melbourne urban scene;",
        "noCutsOrFloatingGeometry": (
            "no large cuts, floating geometry, or camera-occluding surfaces;"
        ),
        "usefulEyeLevelMovement": "useful eye-level movement over verified route support;",
        "completeCapsuleClearanceVerification": (
            "a vertical capsule of radius 0.34 metres and total height 1.9 metres, grounded on "
            "that support, has full clearance from visual geometry except the support surface;"
        ),
        "practicalBrowserBudget": (
            "practical measured browser transfer, decoded-memory, draw-call and frame budgets."
        ),
        "companionPresent": "Companion and reticle present;",
        "reticlePresent": "Companion and reticle present;",
        "authenticatedShellAndAuthoredHandlersPreserved": (
            "authenticated shell and authored handlers preserved;"
        ),
    },
}

#: Where a retained criterion differs in substance from the canonical definition, said once.
_SCOPE_NOTES: Final[Mapping[str, str]] = {
    "continuousTexturedStreetAndFacades": (
        "All three briefs required SOURCE texture, and the first two named only the ground or the "
        "street. The canonical key drops the source condition, because a generated corridor has "
        "no source texture and a key naming one could not be scored against it, and it widens the "
        "surface to street and facades. It is also mechanised: the retained values were judged "
        "from captures."
    ),
    "readsAsInhabitedStreet": (
        "Renamed and redefined by the operator's binding. The retained keys asked whether a real, "
        "named city was recognisable, were scored before the rubric existed, and are not rubric "
        "scores. Rubric version 4 asks one plain question of each capture, whether it is a "
        "finished, lived-in street, with options that say what they mean, and stops at the first "
        "no."
    ),
    "noCutsOrFloatingGeometry": (
        "The retained criteria were judged from captures, Melbourne's only for LARGE cuts, and "
        "the successor briefs also named camera-occluding surfaces, which the canonical set "
        "measures under completeCapsuleClearanceVerification. The canonical key is measured over "
        "all drawn geometry."
    ),
    "usefulEyeLevelMovement": (
        "The first Helsinki brief asked for correct movement on simplified verified support, the "
        "successor folded full capsule clearance into this key, and Melbourne asked for useful "
        "movement over verified support while its recorder retained only a static camera segment. "
        "The canonical key requires a live numeric trace and keeps capsule clearance separate."
    ),
    "completeCapsuleClearanceVerification": (
        "Scored as its own key only by Melbourne. The successor brief required the same capsule "
        "inside its movement criterion and its record carries no separate key for it, so it is "
        "absent there, as it is in the first Helsinki record, whose brief never named a capsule."
    ),
    "practicalBrowserBudget": (
        "Melbourne's brief named frame budgets among the practical budgets. The canonical key "
        "reports frame time and heap beside Melbourne's but decides only on the values that do "
        "not vary between runs of one build."
    ),
    "companionPresent": "Presence of the product's Companion, now read from the live document.",
    "reticlePresent": "Presence of the product's reticle, now read from the live document.",
    "authenticatedShellAndAuthoredHandlersPreserved": (
        "The first Helsinki brief required authored-object and authentication handlers to remain, "
        "and its record says handler preservation was verified structurally, but its hardPass "
        "block has no key for it, so it is absent there and no value is inferred. Version 3 "
        "names pointer listeners beside keyboard listeners, because the product enters its world "
        "with a click."
    ),
}

#: Lines the rubric must carry, verbatim, for the reconciliation record to bind it.
_RUBRIC_LINES: Final = (
    f"Rubric version: {RUBRIC_VERSION}\n",
    f"Key set: `{GATE_KEY_SET_VERSION}`",
    RUBRIC_QUESTION,
    RUBRIC_GUIDANCE,
    ANSWER_REQUIREMENT,
    CARRIED_WORDS_NOTICE,
    WORDS_STORAGE,
    TYPED_REPLY_RULE,
    *(reason_follow_up(answer) for answer in OPTION_ANSWERS.values()),
    *(f"**{option}**" for option in ANSWER_OPTIONS),
    f"`{NOT_ASKED}`",
    "**No model may score `readsAsInhabitedStreet`.**",
    *(f"| `{label}` | {title} |" for label, title in PICTURE_TITLES.items()),
)

#: What version 4 said a corridor has to clear, before the bar said the yes answers are picked.
_V4_CORRIDOR_BAR: Final = (
    "all three pictures answered yes by the named judge, plus every mechanical key, against a "
    "baseline that does not itself hold every key"
)

#: Every refusal the record writer makes, as the records state them.
_WRITER_REFUSES: Final = (
    "a missing or placeholder judge",
    "a missing reason in the judge's own words, including a follow-up that gets no words",
    "a reply that does not say when it was given",
    "a rubric digest mismatch, except a judgement given against the version this one superseded "
    "when that version showed the judge exactly what this one shows",
    "a capture not bound by digest, or an answer about another capture",
    "a yes key with any picture unasked",
    "an answer given after a decisive no",
    "a typed reply that does not hold the whole word no, or that holds the whole word yes",
    "a follow-up for an answer that already gave its reason, or one not in the rubric's words",
    "a pick that is not one of the options",
    "carried words without the line that says they are kept, or from a rubric version that was "
    "never fixed",
    "a yes whose only words are carried words, and a follow-up for a picture whose earlier words "
    "are carried",
    "any answer or follow-up reply not typed by the judge",
    "a public record that would carry any of the judge's words, or a quoted part of them",
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


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _brief_quote_holds(quote: str, brief_text: str) -> bool:
    folded = _normalised(brief_text)
    # Line-wrapped list items keep their leading numerals inside the brief; a quote omits them.
    return _normalised(quote) in folded


def _rubric_binding(rubric: bytes, copy_path: str) -> dict[str, Any]:
    """The rubric the record fixes: checked for the version 5 wording, then bound by digest."""
    text = rubric.decode("utf-8")
    for line in _RUBRIC_LINES:
        if line not in text:
            raise GateEvidenceError(f"FINDING: the rubric does not carry {line.strip()!r}")
    earlier = {
        *(question for _, question in RUBRIC_V1.questions),
        *(version.question for version in SUPERSEDED_VERSIONS),
    } - {RUBRIC_QUESTION}
    for question in sorted(earlier):
        if question in text:
            raise GateEvidenceError(f"FINDING: the rubric still asks {question!r}")
    judges = re.findall(r"^Named human judge: (.*)$", text, flags=re.MULTILINE)
    if len(judges) != 1:
        raise GateEvidenceError("FINDING: the rubric must name exactly one judge")
    judge = _require_name(judges[0].strip(), "a judge named in the rubric")
    return {
        "path": copy_path,
        "byte_size": len(rubric),
        "sha256": hashlib.sha256(rubric).hexdigest(),
        "copyOf": RUBRIC_PATH,
        "rubricVersion": RUBRIC_VERSION,
        "judge": judge,
    }


def _superseded_binding(document: Mapping[str, Any], path: str) -> dict[str, Any]:
    """The version 4 record, checked to say what version 4 said and to differ only where it may."""
    if document.get("profile") != DIGEST_BOUND_PROFILE:
        raise GateEvidenceError(f"{path} is not a digest-bound record")
    body = document["record"]
    digest = hashlib.sha256(canonical_json(body)).hexdigest()
    if digest != document["record_sha256"]:
        raise GateEvidenceError(f"FINDING: {path} does not reproduce its record_sha256")
    judged = body["judgedKey"]
    stated = (
        body["keySet"],
        judged["rubricVersion"],
        judged["rubricSha256"],
        judged["question"],
        judged["guidance"],
        judged["requirement"],
        judged["reasonFollowUp"],
        judged["carriedWordsNotice"],
        judged["options"],
        judged["composition"],
        judged["corridorBar"],
        judged["wordsStorage"],
        judged.get("typedReplyRule"),
    )
    expected = (
        VERSION_4.key_set,
        VERSION_4.rubric_version,
        VERSION_4.rubric_sha256,
        VERSION_4.question,
        VERSION_4.guidance,
        VERSION_4.requirement,
        REASON_FOLLOW_UP,
        VERSION_4.carried_notice,
        list(VERSION_4.options),
        VERSION_4.composition,
        _V4_CORRIDOR_BAR,
        WORDS_STORAGE,
        None,
    )
    if stated != expected:
        raise GateEvidenceError(f"FINDING: {path} is not the version 4 record this supersedes")
    if not VERSION_4.shows_what_is_shown_now():
        raise GateEvidenceError(
            "FINDING: version 5 may change only how a typed reply is read, and it changes what "
            "the judge is shown"
        )
    changed: dict[str, dict[str, str]] = {}
    unchanged: list[str] = []
    for entry, item in zip(body["canonicalKeys"], CANONICAL_KEYS, strict=True):
        current = _canonical_entry(item)
        if entry["key"] != item.spelling:
            raise GateEvidenceError(f"FINDING: {path} orders the canonical keys differently")
        before = VERSION_4.definitions.get(item.spelling, item.definition)
        if entry["definition"] != before:
            raise GateEvidenceError(f"FINDING: {path} defines {item.spelling} unexpectedly")
        if {**entry, "definition": current["definition"]} != current:
            raise GateEvidenceError(
                f"FINDING: {item.spelling} changed more than its wording since {path}; version 5 "
                "moves no measurement"
            )
        if before == item.definition:
            unchanged.append(item.spelling)
        else:
            changed[item.spelling] = {"before": before, "after": item.definition}
    for name, value in (
        ("thresholds", dict(THRESHOLDS)),
        ("melbourneEnvelope", dict(MELBOURNE_ENVELOPE)),
        ("classification", dict(CLASSIFICATION)),
        ("authenticationConditions", list(AUTHENTICATION_CONDITIONS)),
    ):
        if body[name] != value:
            raise GateEvidenceError(f"FINDING: {name} moved since {path}; version 5 moves none")
    return {
        "path": path,
        "record_sha256": digest,
        "keySet": VERSION_4.key_set,
        "rubricVersion": VERSION_4.rubric_version,
        "rubricSha256": VERSION_4.rubric_sha256,
        "changes": {
            "typedReplyRule": {"before": VERSION_4.typed_reply_rule, "after": TYPED_REPLY_RULE},
            "composition": {"before": VERSION_4.composition, "after": COMPOSITION},
            "corridorBar": {"before": _V4_CORRIDOR_BAR, "after": CORRIDOR_BAR},
            "writerRefuses": {"before": judged["writerRefuses"], "after": list(_WRITER_REFUSES)},
            "definitions": changed,
        },
        "shownUnchanged": True,
        "keysWithUnchangedDefinitions": unchanged,
        "measurementsUnchanged": True,
        "keyValuesChanged": [],
        "unchanged": [
            "every spelling, definition and resolution",
            "every measurement, threshold and mechanical decision, so no key value changes",
            "everything the judge is shown: the picture titles, the question, the guidance, the "
            "line asking for words, the two options, the carried-words line and the one follow-up",
            "that the answer is the option the judge picks",
            "that each picture is shown alone, the first no decides, and the key holds only for "
            "three yes answers",
            "that there is no score",
            "the named judge",
            "that no model may answer, suggest, pre-fill or break a tie",
            "that the judge's own words are kept exactly as typed in a private companion record, "
            "never in a public one, and are the reason; and that an answer without a reason is not "
            "recorded",
            "that the rubric SHA-256 is bound",
            "that captures are bound by path, byte size and SHA-256",
        ],
        "why": {
            "typedReplyRule": (
                "Under version 4 a typed reply counted only when its first word was yes or no, so "
                "a reply that says no without opening with it could not be read. Version 5 reads "
                "a typed reply as no when it holds the whole word no and not the whole word yes, "
                "and never as yes. A typed reply can therefore only fail a key, never pass one. "
                "That is the cautious direction for a stop condition, so the rule cannot inflate "
                "a result."
            ),
            "corridorBar": (
                "The bar stays absolute: three picked yes answers from the named judge, plus every "
                "mechanical key. It now says picked, because a typed reply can never be a yes."
            ),
        },
        "adoption": (
            "This rule was adopted after the version 4 reply described under calibrationEvidence "
            "was given, and that reply is the rule's first application. The judge had declined "
            "further questions about these pictures, so none was asked again."
        ),
        "knownCost": (
            "The whole word no inside a favourable sentence would read as a no. That can only "
            "ever fail a key, never pass one. Every ask therefore presents the two options, so "
            "that a reply typed in place of a pick stays rare."
        ),
        "notReRead": (
            "The replies given under version 2, kept as calibration evidence by the version 3 "
            "reconciliation record, are not re-read. They were given under version 2, which asked "
            "a different question. One of them, typed in place of a pick, holds the whole word no "
            "and not the whole word yes, so this rule would read it as a no; the rule is not "
            "applied to them, and nothing is taken from them."
        ),
        "answersAcceptedFromVersion4": (
            "A judgement given against version 4 is read under version 5, because version 4 "
            "showed the judge exactly what version 5 shows. A record written from one carries "
            "both digests and labels the judge's reasons with version 4. A judgement given "
            "against any other version is refused."
        ),
        "strictness": (
            "Version 4 could read a typed reply as a yes; version 5 reads one only as a no, and "
            "the key still needs three picked yes answers, so version 5 is at least as strict as "
            "version 4."
        ),
    }


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


def reconciliation_record(
    *,
    date: str,
    base: str,
    branch: str,
    retained: Mapping[str, Mapping[str, Any]],
    briefs: Mapping[str, bytes],
    superseded: Mapping[str, Any],
    superseded_path: str,
    rubric: bytes,
    rubric_copy_path: str,
    calibration: Mapping[str, Any],
    calibration_captures: Sequence[Mapping[str, Any]],
    scored_corridors: Sequence[str],
    scored_against_superseded: Sequence[str],
    record_path: str,
) -> dict[str, Any]:
    """The key reconciliation record, measured from the retained records, briefs and rubric.

    ``retained`` maps each retained label to its parsed document and ``briefs`` maps it to the
    bytes of its brief. ``superseded`` is the version 4 reconciliation record this one replaces,
    ``rubric`` the bytes of the rubric it fixes, retained at ``rubric_copy_path``, and
    ``calibration`` the reply typed under version 4 about ``calibration_captures``, whose
    words go only to the private companion named by ``record_path``.
    ``scored_corridors`` are the retained records that score a corridor and
    ``scored_against_superseded`` those scored against an earlier key set; both must be empty,
    because a rubric may change only before anything is read against it. Every fact is re-derived
    from those inputs and compared with :data:`exulanica.evaluation.gate_keys.RETAINED_RECORDS`;
    any disagreement is a finding and raises rather than being written.
    """
    if not _ISO_DATE.match(date):
        raise GateEvidenceError("date must be an ISO date")
    if scored_corridors:
        raise GateEvidenceError(
            "FINDING: a corridor has been scored "
            f"({', '.join(scored_corridors)}), so the rubric cannot be revised by this record"
        )
    if scored_against_superseded:
        raise GateEvidenceError(
            "FINDING: records were scored against an earlier key set "
            f"({', '.join(scored_against_superseded)}); they need their own reconciliation"
        )
    labels = [record.label for record in RETAINED_RECORDS]
    if set(retained) != set(labels) or set(briefs) != set(labels):
        raise GateEvidenceError(f"the three retained records and briefs are required: {labels}")

    supersedes = _superseded_binding(superseded, superseded_path)
    rubric_entry = _rubric_binding(rubric, rubric_copy_path)
    if rubric_entry["sha256"] in {version.rubric_sha256 for version in SUPERSEDED_VERSIONS}:
        raise GateEvidenceError("FINDING: the rubric is a superseded version's; nothing is revised")
    evidence, private_replies, private_lines = _calibration(
        calibration, calibration_captures, rubric_entry["judge"]
    )
    companion_path, companion = calibration_words_file(
        record_path, calibration, calibration_captures, rubric_entry["judge"]
    )
    predecessor_records: list[dict[str, str]] = [
        {"path": superseded_path, "record_sha256": supersedes["record_sha256"]}
    ]
    retained_entries: list[dict[str, Any]] = []
    spelling_uses: dict[str, list[str]] = {}
    artifacts: list[dict[str, Any]] = []
    melbourne_preview: dict[str, Any] | None = None

    for expected in RETAINED_RECORDS:
        document = retained[expected.label]
        if document.get("profile") != DIGEST_BOUND_PROFILE:
            raise GateEvidenceError(f"{expected.path} is not a digest-bound record")
        body = document["record"]
        digest = hashlib.sha256(canonical_json(body)).hexdigest()
        if digest != document["record_sha256"] or digest != expected.record_sha256:
            raise GateEvidenceError(
                f"FINDING: {expected.path} canonicalises to {digest}, declares "
                f"{document['record_sha256']} and was reconciled at {expected.record_sha256}"
            )
        hard_pass = body["hardPass"]
        actual = {resolve(spelling): spelling for spelling in hard_pass}
        if len(actual) != len(hard_pass):
            raise GateEvidenceError(
                f"FINDING: two spellings in {expected.path} resolve to one canonical key"
            )
        if actual != dict(expected.spellings):
            raise GateEvidenceError(
                f"FINDING: {expected.path} scored {sorted(hard_pass)}, which is not the spelling "
                "set this module reconciled"
            )
        brief_bytes = briefs[expected.label]
        brief_text = brief_bytes.decode("utf-8")
        brief_binding = next(
            (item for item in body["artifacts"] if item["path"] == expected.brief_path), None
        )
        brief_digest = hashlib.sha256(brief_bytes).hexdigest()
        if (
            brief_binding is None
            or brief_binding["sha256"] != brief_digest
            or brief_binding["byte_size"] != len(brief_bytes)
        ):
            raise GateEvidenceError(
                f"FINDING: {expected.brief_path} is not the brief {expected.path} binds"
            )
        artifacts.append(
            {"path": expected.brief_path, "byte_size": len(brief_bytes), "sha256": brief_digest}
        )
        criteria = BRIEFED_CRITERIA[expected.label]
        for quote in criteria.values():
            if not _brief_quote_holds(quote, brief_text):
                raise GateEvidenceError(
                    f"FINDING: {expected.brief_path} does not contain the quoted criterion "
                    f"{quote!r}"
                )
        keys: dict[str, Any] = {}
        for item in CANONICAL_KEYS:
            spelling = actual.get(item.spelling)
            entry: dict[str, Any]
            if spelling is None:
                entry = {"state": "absent", "note": "not scored in this record's hardPass block"}
            else:
                value = hard_pass[spelling]
                if not isinstance(value, bool):
                    raise GateEvidenceError(f"FINDING: {expected.path} {spelling} is not a boolean")
                entry = {"state": "scored", "spelling": spelling, "retainedValue": value}
                spelling_uses.setdefault(spelling, []).append(expected.label)
            if item.spelling in criteria:
                entry["briefedCriterion"] = criteria[item.spelling]
            keys[item.spelling] = entry
        predecessor_records.append({"path": expected.path, "record_sha256": digest})
        retained_entries.append(
            {
                "label": expected.label,
                "path": expected.path,
                "record_sha256": digest,
                "brief": expected.brief_path,
                "verdict": body["verdict"],
                "browserEngine": body["browser"]["engine"],
                "viewport": body["browser"]["viewport"],
                "hardPassKeyCount": len(hard_pass),
                "keys": keys,
            }
        )
        if expected.label == "melbourne-c4-29-visual-feasibility":
            browser = body["browser"]
            melbourne_preview = {
                "key": "authenticatedShellAndAuthoredHandlersPreserved",
                "retainedValue": hard_pass["authenticatedShellAndAuthoredHandlersPreserved"],
                "authenticatedShellPresent": browser["authenticatedShellPresent"],
                "previewApi404s": [
                    {"url": item["url"], "status": item["status"]}
                    for item in browser["previewApi404s"]
                ],
                "statement": (
                    "Melbourne set authenticatedShellAndAuthoredHandlersPreserved to true while "
                    "its browser block recorded these three 404 responses from the Vite-only "
                    "preview API, not from a credentialed backend. As the retained evidence used "
                    "it, the key means the product shell and its authored handlers were present "
                    "and were not replaced by a bespoke harness page; it does not by itself "
                    "assert a real bearer token. Every canonical record therefore carries "
                    "authenticationCondition: vite-preview-api is Melbourne's condition, and "
                    "credentialed-api, a real token against a real API, is strictly stronger."
                ),
            }
    artifacts.append({key: rubric_entry[key] for key in ("path", "byte_size", "sha256")})

    if melbourne_preview is None:  # pragma: no cover - labels are checked above
        raise GateEvidenceError("the Melbourne record was not read")
    if len(melbourne_preview["previewApi404s"]) != 3:
        raise GateEvidenceError("FINDING: Melbourne does not record exactly three preview 404s")

    mapping: list[dict[str, Any]] = []
    for item in CANONICAL_KEYS:
        for spelling in (item.spelling, *item.predecessor_spellings):
            mapping.append(
                {
                    "spelling": spelling,
                    "resolvesTo": resolve(spelling),
                    "usedBy": sorted(spelling_uses.get(spelling, [])),
                    "isCanonicalSpelling": spelling == item.spelling,
                }
            )
    if mapping != superseded["record"]["mapping"]:
        raise GateEvidenceError("FINDING: the spelling table moved, and version 5 does not move it")
    used = set(spelling_uses)
    listed = {entry["spelling"] for entry in mapping}
    if not used <= listed:
        raise GateEvidenceError(f"FINDING: unmapped retained spellings {sorted(used - listed)}")
    resolved_targets: dict[str, set[str]] = {}
    for entry in mapping:
        resolved_targets.setdefault(entry["spelling"], set()).add(entry["resolvesTo"])
    ambiguous = sorted(name for name, targets in resolved_targets.items() if len(targets) > 1)
    if ambiguous:
        raise GateEvidenceError(f"FINDING: ambiguous spellings {ambiguous}")

    canonical_entries = [_canonical_entry(item) for item in CANONICAL_KEYS]
    for spelling in CANONICAL_SPELLINGS:
        if "Source" in spelling or "Melbourne" in spelling:
            raise GateEvidenceError(f"{spelling} names a source or a city")

    record: dict[str, Any] = {
        "profile": "exulanica.visual-gate-key-reconciliation/v5",
        "date": date,
        "status": "reconciled",
        "base": base,
        "branch": branch,
        "keySet": GATE_KEY_SET_VERSION,
        "rubricVersion": RUBRIC_VERSION,
        "supersedes": supersedes,
        "predecessor_records": predecessor_records,
        "artifacts": artifacts,
        "captures": [dict(capture) for capture in calibration_captures],
        "canonicalKeys": canonical_entries,
        "evidenceKinds": list(EVIDENCE_KINDS),
        "judgedKey": {
            "key": JUDGED_KEY,
            "rubric": RUBRIC_PATH,
            "rubricVersion": RUBRIC_VERSION,
            "rubricSha256": rubric_entry["sha256"],
            "rubricCopy": rubric_entry["path"],
            "judge": rubric_entry["judge"],
            "captures": list(CAPTURE_LABELS),
            "pictures": [
                {"label": label, "title": title} for label, title in PICTURE_TITLES.items()
            ],
            "question": RUBRIC_QUESTION,
            "guidance": RUBRIC_GUIDANCE,
            "requirement": ANSWER_REQUIREMENT,
            "reasonFollowUp": REASON_FOLLOW_UP,
            "carriedWordsNotice": CARRIED_WORDS_NOTICE,
            "options": list(ANSWER_OPTIONS),
            "optionAnswers": dict(OPTION_ANSWERS),
            "wordsStorage": WORDS_STORAGE,
            "judgeWordsDirectory": JUDGE_WORDS_DIRECTORY,
            "typedReplyRule": TYPED_REPLY_RULE,
            "answersAcceptedAgainst": [
                {"rubricVersion": RUBRIC_VERSION, "rubricSha256": rubric_entry["sha256"]},
                {
                    "rubricVersion": VERSION_4.rubric_version,
                    "rubricSha256": VERSION_4.rubric_sha256,
                },
            ],
            "notAsked": NOT_ASKED,
            "composition": COMPOSITION,
            "corridorBar": CORRIDOR_BAR,
            "scoredBy": (
                "the human judge named in the rubric, never a model: no model may answer, "
                "suggest, pre-fill or break a tie"
            ),
            "writerRefuses": list(_WRITER_REFUSES),
        },
        "calibrationEvidence": evidence,
        "judgeWords": _companion_binding(companion_path, companion),
        "thresholds": dict(THRESHOLDS),
        "melbourneEnvelope": dict(MELBOURNE_ENVELOPE),
        "classification": dict(CLASSIFICATION),
        "authenticationConditions": list(AUTHENTICATION_CONDITIONS),
        "retainedRecords": retained_entries,
        "mapping": mapping,
        "mappingChecks": {
            "retainedSpellings": len(used),
            "retainedSpellingsResolved": len(used & listed),
            "total": used <= listed,
            "unambiguous": not ambiguous,
            "canonicalKeys": len(CANONICAL_KEYS),
        },
        "scoredBeforeRevision": {
            "corridors": list(scored_corridors),
            "againstEarlierKeySets": list(scored_against_superseded),
            "measuredAs": (
                "retained records under docs/evaluation whose file name or record profile names "
                "a corridor, and those whose gate block names key set version 1, 2, 3 or 4, read "
                "when this record was written"
            ),
        },
        "authenticatedShellUnderMelbourne": melbourne_preview,
        "scopeNotes": dict(_SCOPE_NOTES),
        "claimsNotMade": [
            "No canonical value is asserted for any retained run. Retained values are quoted "
            "under the spelling each record used, and the retained records are not edited.",
            "No key absent from a retained record is inferred true or false.",
            "No generated geometry is scored here, and none existed in this repository when the "
            "rubric was revised.",
            "The canonical definitions do not make any retained rejection pass or fail anew.",
            "The version 4 record is superseded, not edited. No corridor was scored, and no "
            "record was written, under versions 1, 2, 3 or 4, and no answer was scored under "
            "version 4.",
            "The version 4 reply is calibration evidence here, and this record takes no key value "
            "from it. Its words are not in this record: it carries their SHA-256 and byte count, "
            "and its private companion holds them.",
            "The replies given under version 2 are not re-read under version 5, because they were "
            "given under version 2.",
            "The typed-reply rule is not presented as fixed before any answer: it was adopted "
            "after the version 4 reply was given, and that reply is its first application.",
            "Nothing here is an answer under version 5. The rubric fixes how the judge is asked "
            "and how a typed reply is read; only the named judge answers, and no model judged any "
            "picture.",
        ],
    }
    shown = [
        *_shown_texts(),
        *(f"{VERSION_4.carried_notice}\n\n{VERSION_4.prompt(label)}" for label in CAPTURE_LABELS),
    ]
    refuse_private_words(
        record,
        [item["words"] for item in private_replies if item["words"] is not None],
        shown=shown,
        lines=[item["words"] for item in private_lines],
    )
    return digest_bound(record)


def _canonical_entry(item: GateKey) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": item.spelling,
        "definition": item.definition,
        "evidenceKind": item.evidence_kind,
        "predecessorSpellings": list(item.predecessor_spellings),
    }
    if item.evidence_kind == "mechanical":
        entry["measurement"] = item.measurement
        entry["decidedBy"] = list(item.decided_by)
    else:
        entry["rubric"] = RUBRIC_PATH
    return entry
