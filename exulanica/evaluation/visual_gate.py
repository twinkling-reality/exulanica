"""Build a visual gate record from measured inputs, and refuse to build one from anything less.

The gate exists so that a generated corridor can be shown better than what it replaces, which is
only possible if the gate can say FAIL. So this module decides; it does not transcribe:

*   **Every mechanical key is re-decided here** from the measured fields its canonical definition
    names. A caller cannot hand in ``True``; it hands in the numbers, and a number that is missing
    is a key with no evidence, which is refused rather than emitted.
*   **The judged key is decided only from a named human's answers**, under version 2 of
    docs/visual-gate-rubric.md: one question per picture, asked in route order, and the first no
    decides. No name, a placeholder in place of a name, a rubric other than the one the record is
    written with, a picture other than the one bound, an answer somebody else typed, an answer with
    no reason in the judge's own words, an answer given after a decisive no and a key with a
    picture unasked are all refused. Nothing in this module can produce ``readsAsInhabitedStreet``
    from a measurement, and nothing may.
*   **The judge's words stay private.** A public record carries, for each reply, the SHA-256 and
    byte count of the judge's words and binds a companion record under ``.exulanica/judge-words/``
    that holds them. The companion never enters the repository, and
    :func:`refuse_private_words` refuses a public record that would carry any of the words.
*   **The corridor bar is every key.** A candidate passes only when all nine keys hold, the judged
    one by three yes answers, and never against a baseline that itself holds every key, because
    then the gate could not tell the candidate from what it replaces.

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
    AUTHENTICATION_CONDITIONS,
    CANONICAL_KEYS,
    CANONICAL_SPELLINGS,
    CAPTURE_LABELS,
    CLASSIFICATION,
    EVIDENCE_KINDS,
    GATE_KEY_SET_VERSION,
    JUDGED_KEY,
    MELBOURNE_ENVELOPE,
    NOT_ASKED,
    PICTURE_TITLES,
    RETAINED_RECORDS,
    RUBRIC_GUIDANCE,
    RUBRIC_PATH,
    RUBRIC_QUESTION,
    RUBRIC_V1,
    RUBRIC_VERSION,
    THRESHOLDS,
    WORDS_STORAGE,
    GateKey,
    key,
    resolve,
)

__all__ = [
    "BRIEFED_CRITERIA",
    "COMPOSITION",
    "CORRIDOR_BAR",
    "DIGEST_BOUND_PROFILE",
    "JUDGE_WORDS_DIRECTORY",
    "JUDGE_WORDS_PROFILE",
    "GateEvidenceError",
    "JudgedAnswers",
    "PictureAnswer",
    "beats_baseline",
    "build_gate",
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
    "visual_gate_record",
    "words_fingerprint",
    "words_from_companion",
]

DIGEST_BOUND_PROFILE: Final = "exulanica.digest-bound-record/v1"

#: How the judged answers compose under rubric version 2, as the records state it.
COMPOSITION: Final = (
    "Each capture is shown alone, in route order, and the judge answers the one question yes or "
    "no with their own words. The first no makes the key false and the pictures after it are not "
    "asked. The key is true only when all three pictures got yes. There is no score."
)

#: What a corridor has to clear, as the records state it.
CORRIDOR_BAR: Final = (
    "all three pictures answered yes by the named judge, plus every mechanical key, against a "
    "baseline that does not itself hold every key"
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
#: shown those words in the ask itself.
_PRIVATE_RUN: Final = 4

#: A span in quotes, the way prose names a part of what somebody wrote.
_QUOTED: Final = re.compile(r"'([^'\n]{2,})'|\"([^\"\n]{2,})\"|\u201c([^\u201d\n]{2,})\u201d")


class GateEvidenceError(ValueError):
    """Evidence the gate cannot decide from. Nothing is emitted for a key that raises this."""


@dataclass(frozen=True, slots=True)
class PictureAnswer:
    """What the judge gave for one picture, exactly as given, or that the picture was not asked.

    ``picked`` is the option the judge picked, ``"Yes"`` or ``"No"``, or None when the judge typed
    a reply instead. ``words`` is the judge's own words exactly as typed: the notes added to the
    pick, or the typed reply. They go only to the record's private companion. ``typed_by`` names
    who gave them, which has to be the judge, and ``given_at`` when the reply reached the asking
    session, as an ISO time in UTC. A picture that was not asked carries none of these.
    """

    label: str
    capture_sha256: str
    asked: bool
    picked: str | None = None
    words: str | None = None
    typed_by: str | None = None
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
    value: Any, private: Sequence[str], *, shown: Sequence[str] = (), path: str = "$"
) -> None:
    """Refuse a public record that would carry any of the judge's words.

    ``private`` holds every text that stays in the companion, and ``shown`` what the judge was
    shown. No string in ``value`` may contain a private text of three words or more, a run of
    four of its words that the judge was not shown, or a quoted part of one other than an answer
    word.
    """
    texts = [_folded(text) for text in private if isinstance(text, str) and text.strip()]
    if not texts:
        return
    visible = [_folded(text) for text in shown]
    whole = [text for text in texts if len(text.split()) >= 3]
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
            for match in _QUOTED.finditer(item):
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


def _answer(label: str, picture: PictureAnswer, judge: str, judged_on: str) -> tuple[str, str]:
    """The judge's answer for an asked picture and the words given with it, or a refusal."""
    where = f"{JUDGED_KEY}: {PICTURE_TITLES[label]} ({label})"
    if picture.typed_by != judge:
        raise GateEvidenceError(
            f"{where} was not typed by the judge: it names {picture.typed_by!r}, and only "
            f"{judge!r} may answer"
        )
    _given_at(where, picture.given_at, judged_on)
    words = picture.words
    if not isinstance(words, str) or words.strip() == "":
        raise GateEvidenceError(f"{where} has no reason in the judge's own words")
    if " ".join(words.split()).casefold() in _SKIP_MARKERS:
        raise GateEvidenceError(f"{where} was skipped, which is not an answer")
    opening = _OPENING_ANSWER.match(words)
    if picture.picked is None:
        if opening is None:
            raise GateEvidenceError(
                f"{where}: the judge picked no option and their reply does not begin with yes or "
                "no, so there is no answer the judge gave; nothing is inferred from their words"
            )
        answer = opening.group(1).casefold()
    elif picture.picked in ANSWER_OPTIONS:
        answer = picture.picked.casefold()
    else:
        raise GateEvidenceError(
            f"{where}: {picture.picked!r} is not one of the options the judge is offered, "
            f"{' and '.join(ANSWER_OPTIONS)}"
        )
    reason = words[opening.end() :] if opening is not None else words
    if not any(character.isalnum() for character in reason):
        raise GateEvidenceError(
            f"{where} has no reason in the judge's own words: they give an answer without a why"
        )
    return answer, words


def decide_judged(
    evidence: JudgedAnswers, *, rubric_sha256: str, captures: Mapping[str, str]
) -> tuple[bool, dict[str, Any]]:
    """The judged key's value and what it was decided from, under rubric version 2.

    ``rubric_sha256`` is the digest of the rubric the record is written with, and ``captures``
    maps each route label to the SHA-256 of the capture the record binds. The judge's answers
    must name both exactly, so a judgement cannot be carried onto another rubric or picture.
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
    if evidence.rubric_sha256 != rubric_sha256:
        raise GateEvidenceError(
            f"{JUDGED_KEY}: the judge answered against rubric {evidence.rubric_sha256}, and the "
            f"record is written with rubric {rubric_sha256}; a rubric digest mismatch is refused"
        )
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
            answer, words = _answer(label, picture, judge, evidence.judged_on)
            entry.update(
                {
                    "state": "answered",
                    "picked": picture.picked,
                    "answer": answer,
                    "readFrom": (
                        "the option picked"
                        if picture.picked is not None
                        else "the first word of the typed reply"
                    ),
                    "rubricVersion": RUBRIC_VERSION,
                    "givenAt": picture.given_at,
                    **words_fingerprint(words),
                    "typedBy": judge,
                }
            )
            if answer == "no":
                decisive = label
        elif picture.asked is False:
            if (picture.picked, picture.words, picture.typed_by, picture.given_at) != (
                None,
                None,
                None,
                None,
            ):
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
        "rubricSha256": evidence.rubric_sha256,
        "judge": judge,
        "judgedOn": evidence.judged_on,
        "question": RUBRIC_QUESTION,
        "guidance": RUBRIC_GUIDANCE,
        "options": list(ANSWER_OPTIONS),
        "composition": COMPOSITION,
        "pictures": entries,
        "decisiveNo": decisive,
        "value": value,
    }
    return value, detail


def judge_words(evidence: JudgedAnswers) -> list[dict[str, Any]]:
    """Every reply the judge gave, words included, as the record's private companion keeps them."""
    replies: list[dict[str, Any]] = []
    for picture in evidence.pictures:
        if picture.asked is not True:
            continue
        replies.append(
            {
                "label": picture.label,
                "picture": PICTURE_TITLES[picture.label],
                "kind": "reply",
                "rubricVersion": RUBRIC_VERSION,
                "givenAt": picture.given_at,
                "picked": picture.picked,
                "words": picture.words,
                "typedBy": picture.typed_by,
            }
        )
    return replies


def judge_words_file(record_path: str, evidence: JudgedAnswers) -> tuple[str, bytes]:
    """The private companion of the record at ``record_path``: where it lives, and its bytes."""
    document = judge_words_record(
        record_path=record_path, judge=evidence.judge, replies=judge_words(evidence)
    )
    return judge_words_path(record_path), _companion_bytes(document)


def _private_texts(evidence: JudgedAnswers) -> list[str]:
    return [reply["words"] for reply in judge_words(evidence) if reply["words"] is not None]


def _shown_texts() -> list[str]:
    return [RUBRIC_QUESTION, RUBRIC_GUIDANCE, *ANSWER_OPTIONS]


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
            text = None
            digest = entry.get("words_sha256")
            if digest is not None:
                if digest not in words:
                    raise GateEvidenceError(
                        f"the judge's words for {entry['picture']} are not in the private companion"
                    )
                text = words[digest]
            pictures.append(
                PictureAnswer(
                    label=entry["label"],
                    capture_sha256=entry["captureSha256"],
                    asked=entry["state"] == "answered",
                    picked=entry.get("picked"),
                    words=text,
                    typed_by=entry.get("typedBy"),
                    given_at=entry.get("givenAt"),
                )
            )
        return JudgedAnswers(
            judge=detail["judge"],
            judged_on=detail["judgedOn"],
            rubric_sha256=detail["rubricSha256"],
            pictures=tuple(pictures),
        )
    except (KeyError, TypeError) as error:
        raise GateEvidenceError(f"the record's {JUDGED_KEY} block is incomplete") from error


def recompose_judged(detail: Mapping[str, Any]) -> bool:
    """The judged key's value from the answers a public record states, without the judge's words.

    A clone without the private companion cannot read a reply again. It can still check that the
    stated answers compose to the stated value, that no picture was answered after the first no,
    and that every answer was typed by the judge, says when it was given and carries the
    fingerprint of the judge's words.
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
                if (
                    entry["words_private"] is not True
                    or not _SHA256.match(str(entry["words_sha256"]))
                    or entry["words_bytes"] <= 0
                ):
                    raise GateEvidenceError(f"{where} carries no fingerprint of the judge's words")
                _given_at(where, entry["givenAt"], detail["judgedOn"])
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
    answered against exactly that rubric. ``record_path`` is where the record is written, which
    names its private companion; the record binds that companion and carries none of the judge's
    words. ``baseline`` is the calibration record a candidate is read against. Without it the
    record is itself a baseline and its verdict is decided by the nine keys alone.
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
    companion_path, companion = judge_words_file(record_path, judged)
    record["judgeWords"] = {
        "path": companion_path,
        "byte_size": len(companion),
        "sha256": hashlib.sha256(companion).hexdigest(),
        "tracked": False,
        "holds": (
            "every reply the judge gave for this record, words included, with the time and rubric "
            "version each was given under; this record carries the SHA-256 and byte count of the "
            "words in their place"
        ),
    }
    for name, value in (extra or {}).items():
        if name in record:
            raise GateEvidenceError(f"extra field {name!r} would replace a gate field")
        record[name] = value
    refuse_private_words(record, _private_texts(judged), shown=_shown_texts())
    return digest_bound(record)


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
        "scores. Rubric version 2 asks one plain question of each capture and stops at the first "
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
        "block has no key for it, so it is absent there and no value is inferred."
    ),
}

#: Lines the rubric must carry, verbatim, for the reconciliation record to bind it.
_RUBRIC_LINES: Final = (
    f"Rubric version: {RUBRIC_VERSION}\n",
    f"Key set: `{GATE_KEY_SET_VERSION}`",
    RUBRIC_QUESTION,
    RUBRIC_GUIDANCE,
    WORDS_STORAGE,
    f"`{NOT_ASKED}`",
    "**No model may score `readsAsInhabitedStreet`.**",
    *(f"| `{label}` | {title} |" for label, title in PICTURE_TITLES.items()),
)


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _brief_quote_holds(quote: str, brief_text: str) -> bool:
    folded = _normalised(brief_text)
    # Line-wrapped list items keep their leading numerals inside the brief; a quote omits them.
    return _normalised(quote) in folded


def _rubric_binding(rubric: bytes, copy_path: str) -> dict[str, Any]:
    """The rubric the record fixes: checked for the version 2 wording, then bound by digest."""
    text = rubric.decode("utf-8")
    for line in _RUBRIC_LINES:
        if line not in text:
            raise GateEvidenceError(f"FINDING: the rubric does not carry {line.strip()!r}")
    for _, question in RUBRIC_V1.questions:
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
    """The version 1 record, checked to say what version 1 said and to differ only where it may."""
    if document.get("profile") != DIGEST_BOUND_PROFILE:
        raise GateEvidenceError(f"{path} is not a digest-bound record")
    body = document["record"]
    digest = hashlib.sha256(canonical_json(body)).hexdigest()
    if digest != document["record_sha256"]:
        raise GateEvidenceError(f"FINDING: {path} does not reproduce its record_sha256")
    judged = body["judgedKey"]
    questions = [(question["id"], question["text"]) for question in judged["questions"]]
    if (body["keySet"], questions, judged["composition"]) != (
        RUBRIC_V1.key_set,
        list(RUBRIC_V1.questions),
        RUBRIC_V1.composition,
    ):
        raise GateEvidenceError(f"FINDING: {path} is not the version 1 record this supersedes")
    unchanged: list[str] = []
    for entry, item in zip(body["canonicalKeys"], CANONICAL_KEYS, strict=True):
        current = _canonical_entry(item)
        if entry["key"] != item.spelling:
            raise GateEvidenceError(f"FINDING: {path} orders the canonical keys differently")
        if item.spelling == JUDGED_KEY:
            if entry["definition"] != RUBRIC_V1.judged_definition:
                raise GateEvidenceError(f"FINDING: {path} defines {JUDGED_KEY} unexpectedly")
            if {**entry, "definition": current["definition"]} != current:
                raise GateEvidenceError(
                    f"FINDING: {path} changed more of {JUDGED_KEY} than it says"
                )
            continue
        if entry != current:
            raise GateEvidenceError(
                f"FINDING: version 2 changes only {JUDGED_KEY}, but {item.spelling} differs "
                f"from {path}"
            )
        unchanged.append(item.spelling)
    for name, value in (
        ("thresholds", dict(THRESHOLDS)),
        ("melbourneEnvelope", dict(MELBOURNE_ENVELOPE)),
        ("classification", dict(CLASSIFICATION)),
        ("authenticationConditions", list(AUTHENTICATION_CONDITIONS)),
    ):
        if body[name] != value:
            raise GateEvidenceError(
                f"FINDING: version 2 changes only {JUDGED_KEY}, but {name} moved"
            )
    return {
        "path": path,
        "record_sha256": digest,
        "keySet": body["keySet"],
        "questions": judged["questions"],
        "composition": judged["composition"],
        "judgedDefinition": RUBRIC_V1.judged_definition,
        "changedKeys": [JUDGED_KEY],
        "unchangedKeys": unchanged,
        "unchanged": [
            "every spelling and its resolution",
            "the named judge",
            "that no model may answer, suggest, pre-fill or break a tie",
            "that the rubric SHA-256 is bound",
            "that captures are bound by path, byte size and SHA-256",
            "the thresholds, the Melbourne envelope and the classification rules",
        ],
        "why": (
            "Version 1 asked three questions of each of three pictures. Nine answers across three "
            "pictures proved too long to complete, and a gate whose judgement cannot be completed "
            "cannot run. Version 2 asks one question of each picture, shows each picture alone and "
            "stops at the first no."
        ),
        "strictness": (
            "Version 1 held the key only for nine yes answers of nine, so any no made it false; "
            "version 2 holds it only for three yes answers of three, so any no makes it false. "
            "Version 1's score only decided a corridor when a baseline scored nine, and version 2 "
            "refuses a corridor PASS against a baseline that holds every key."
        ),
    }


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
    scored_corridors: Sequence[str],
    scored_against_superseded: Sequence[str],
) -> dict[str, Any]:
    """The key reconciliation record, measured from the retained records, briefs and rubric.

    ``retained`` maps each retained label to its parsed document and ``briefs`` maps it to the
    bytes of its brief. ``superseded`` is the version 1 reconciliation record this one replaces,
    ``rubric`` the bytes of the rubric it fixes, retained at ``rubric_copy_path``.
    ``scored_corridors`` are the retained records that score a corridor and
    ``scored_against_superseded`` those scored against version 1's key set; both must be empty,
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
            "FINDING: records were scored against version 1 "
            f"({', '.join(scored_against_superseded)}); they need their own reconciliation"
        )
    labels = [record.label for record in RETAINED_RECORDS]
    if set(retained) != set(labels) or set(briefs) != set(labels):
        raise GateEvidenceError(f"the three retained records and briefs are required: {labels}")

    supersedes = _superseded_binding(superseded, superseded_path)
    rubric_entry = _rubric_binding(rubric, rubric_copy_path)
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
        raise GateEvidenceError("FINDING: the spelling table moved, and version 2 does not move it")
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
        "profile": "exulanica.visual-gate-key-reconciliation/v2",
        "date": date,
        "status": "reconciled",
        "base": base,
        "branch": branch,
        "keySet": GATE_KEY_SET_VERSION,
        "supersedes": supersedes,
        "predecessor_records": predecessor_records,
        "artifacts": artifacts,
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
            "options": list(ANSWER_OPTIONS),
            "wordsStorage": WORDS_STORAGE,
            "judgeWordsDirectory": JUDGE_WORDS_DIRECTORY,
            "notAsked": NOT_ASKED,
            "composition": COMPOSITION,
            "corridorBar": CORRIDOR_BAR,
            "scoredBy": (
                "the human judge named in the rubric, never a model: no model may answer, "
                "suggest, pre-fill or break a tie"
            ),
            "writerRefuses": [
                "a missing or placeholder judge",
                "a missing reason in the judge's own words",
                "a reply that does not say when it was given",
                "a rubric digest mismatch",
                "a capture not bound by digest, or an answer about another capture",
                "a yes key with any picture unasked",
                "an answer given after a decisive no",
                "any answer not typed by the judge",
                "a public record that would carry any of the judge's words, or a quoted part of "
                "them",
            ],
        },
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
            "againstVersion1": list(scored_against_superseded),
            "measuredAs": (
                "retained records under docs/evaluation whose file name or record profile names "
                "a corridor, and those whose gate block names version 1's key set, read when this "
                "record was written"
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
            "The version 1 record is superseded, not edited, and no record was ever scored "
            "against it.",
            "Nothing here is a judge's answer. The rubric fixes how the judge is asked; only the "
            "named judge answers.",
        ],
    }
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
