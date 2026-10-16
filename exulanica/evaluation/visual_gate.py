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

This module decides the keys and builds the record. The judge's answers, the private words and the
envelope are in :mod:`~exulanica.evaluation.visual_gate_words`, the calibration words file in
:mod:`~exulanica.evaluation.visual_gate_calibration`, and the key reconciliation record in
:mod:`~exulanica.evaluation.visual_gate_reconciliation`; their public names are re-exported
here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.evaluation.gate_keys import (
    ANSWER_OPTIONS,
    ANSWER_REQUIREMENT,
    AUTHENTICATION_CONDITIONS,
    CANONICAL_KEYS,
    CANONICAL_SPELLINGS,
    CAPTURE_LABELS,
    GATE_KEY_SET_VERSION,
    GATE_TARGET_IDS,
    JUDGED_KEY,
    MELBOURNE_ENVELOPE,
    NOT_ASKED,
    OPTION_ANSWERS,
    OWNED_DISTRICT_TARGET,
    PICTURE_TITLES,
    RUBRIC_GUIDANCE,
    RUBRIC_PATH,
    RUBRIC_QUESTION,
    RUBRIC_VERSION,
    SUPERSEDED_VERSIONS,
    THRESHOLDS,
    TYPED_REPLY_RULE,
    gate_target,
    key,
    resolve,
    target_of,
)
from exulanica.evaluation.visual_gate_calibration import (
    calibration_words_file,
)
from exulanica.evaluation.visual_gate_reconciliation import (
    BRIEFED_CRITERIA,
    reconciliation_record,
)
from exulanica.evaluation.visual_gate_words import (
    _FORBIDDEN_TEXT as _FORBIDDEN_TEXT,
)
from exulanica.evaluation.visual_gate_words import (
    _ISO_DATE,
    _SHA256,
    COMPOSITION,
    CORRIDOR_BAR,
    DIGEST_BOUND_PROFILE,
    JUDGE_WORDS_DIRECTORY,
    JUDGE_WORDS_PROFILE,
    JUDGEMENT_ANSWERS_PROFILE,
    CarriedWords,
    GateEvidenceError,
    JudgedAnswers,
    PictureAnswer,
    ReasonFollowUp,
    _answer,
    _bound_file,
    _companion_binding,
    _private_texts,
    _require_name,
    _shown_texts,
    digest_bound,
    judge_words,
    judge_words_file,
    judge_words_path,
    judge_words_record,
    judged_answers_from_record,
    recompose_judged,
    refuse_private_words,
    typed_reply_answer,
    words_fingerprint,
    words_from_companion,
)

__all__ = [
    "BRIEFED_CRITERIA",
    "COMPOSITION",
    "CORRIDOR_BAR",
    "DIGEST_BOUND_PROFILE",
    "JUDGEMENT_ANSWERS_PROFILE",
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


def _read(holder: Mapping[str, Any], *path: str) -> Any:
    """One value down a path of names, or None where the path stops."""
    value: Any = holder
    for step in path:
        value = value.get(step) if isinstance(value, Mapping) else None
    return value


def _comparable(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> None:
    """Refuse a comparison the keys cannot carry, naming both targets when they differ.

    Two records are comparable when they were measured by the same key set and answered against
    the same rubric. Across targets that is the whole requirement: the keys do not know which page
    they measured, so two pages scored by one key set under one rubric are as comparable as two
    runs of one page. What is NOT comparable is a different key set or a different rubric, because
    then the same verdict word stands for different questions.

    **The same rubric, by the same equivalence that reads an answer at all.** Until 2026-09-19 the
    rubric axis compared ``answeredAgainst.rubricSha256`` for equality, and that refused every
    comparison this gate exists to make. :func:`_answered_version` reads an answer given against
    the version this one superseded, when that version showed the judge exactly what this one
    shows; the Flatiron baseline's judge answered under version 4 for that reason, and every
    judgement from now on is given under version 5. So one file reconciled two versions in one
    function and refused them in another, over a difference the rubric itself declares immaterial,
    and NO CORRIDOR COULD EVER HAVE BEEN READ AGAINST THAT BASELINE.

    The fix applies that one equivalence and nothing wider: both records must be WRITTEN with the
    same rubric, and each must have been answered against a digest that rubric reconciles, which
    is :func:`_answered_version`'s own question, asked here rather than restated. A digest that
    function does not reconcile still refuses, which is what keeps this from becoming "any two
    rubric digests compare".
    """
    keys = ("key set", ("gate", "keySet")), ("rubric", ("gate", "keys", JUDGED_KEY, "rubricSha256"))
    for name, path in keys:
        values = [_read(holder, *path) for holder in (candidate, baseline)]
        if values[0] != values[1]:
            raise GateEvidenceError(
                f"a comparison needs one {name}: the candidate scored "
                f"{target_of(candidate)} with {values[0]!r} and the baseline scored "
                f"{target_of(baseline)} with {values[1]!r}"
            )
    written = _read(candidate, "gate", "keys", JUDGED_KEY, "rubricSha256")
    for holder, what in ((candidate, "candidate"), (baseline, "baseline")):
        answered = _read(holder, "gate", "keys", JUDGED_KEY, "answeredAgainst", "rubricSha256")
        if answered == written:
            continue
        try:
            _answered_version(answered, written)
        except GateEvidenceError as error:
            raise GateEvidenceError(
                f"a comparison needs one rubric: the {what} scored "
                f"{target_of(holder)} answered against {answered!r}, which the rubric both "
                f"records are written with, {written!r}, does not reconcile"
            ) from error


def beats_baseline(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
    """Whether a candidate clears the corridor bar against a baseline the bar can tell it from."""
    _comparable(candidate, baseline)
    return all(_hard_pass(candidate, "candidate").values()) and not all(
        _hard_pass(baseline, "baseline").values()
    )


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
    target: str = OWNED_DISTRICT_TARGET,
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
    if target not in GATE_TARGET_IDS:
        raise GateEvidenceError(f"target must be one of {', '.join(GATE_TARGET_IDS)}")
    if authentication_condition not in gate_target(target).authentication_conditions:
        raise GateEvidenceError(f"{target} may not be scored under {authentication_condition}")
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
        _comparable({"gate": {"keySet": GATE_KEY_SET_VERSION, "keys": detail}}, baseline)
        comparison = {
            "candidateTarget": target,
            "baselineTarget": target_of(baseline),
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
        # Written only when it is not the owned district, so a record of the page the retained
        # records scored is byte-identical to the ones already retained. target_of reads the
        # absence, and a test holds both halves.
        **({} if target == OWNED_DISTRICT_TARGET else {"target": target}),
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
